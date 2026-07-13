"""Learning-feed worker — the always-on host process.

This is what turns the engine from "one video per cloud session" into a
personal learning channel that comes to your phone. It runs a Telegram bot
(Telegram plays MP4 inline, so videos feel like a feed) plus a background
restock loop.

On a real host the network is open, so:
- edge-tts reaches the voice service -> videos are NARRATED.
- discovery/dives web-search freely.

Commands (from your phone):
  /start                 — hello + how it works
  teach me <anything>    — a narrated lesson video + cheat-sheet
  <any message>          — same as "teach me <message>"
  /surprise              — a wild, fresh explainer video (discovered + dived)
  /feed                  — list what's in your library
  /play <n>              — replay a library item's video

Background: every RESTOCK_EVERY seconds it discovers a fresh topic, makes a
narrated explainer, and PUSHES it to you — the self-filling feed.

Env:
  TELEGRAM_BOT_TOKEN     (required)
  TELEGRAM_ALLOWED_USERS (comma-separated ids; strongly recommended)
  ANTHROPIC_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY  (as needed)
  FORGE_TTS_VOICE        (default en-US-GuyNeural)
  RESTOCK_EVERY          (seconds; 0 disables the auto-feed; default 0)
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)

from . import lesson as _lesson
from . import video as _video
from . import sources as _sources
from . import explorer as _explorer
from . import feed as _feed
from . import debate as _debate
from . import sim as _sim
from . import story as _story
from . import deep as _deep
from . import narrate as _narrate
from . import taste as _taste

from . import job_state as _jobs

# last delivered sim dossier per chat — enables "branch A/B" continuations
_LAST_SIM: dict[int, str] = {}

log = logging.getLogger("agent_forge.worker")

# Hard daily cap on expensive jobs (lessons/surprises/auto-feed items).
# Each job is roughly $1.50-2.50 of API spend; this is the in-app circuit
# breaker so no bug can ever drain an account. Override with MAX_JOBS_PER_DAY.
# The ledger lives on the persistent volume, so a deploy can't reset it.
_MAX_JOBS_PER_DAY = int(os.environ.get("MAX_JOBS_PER_DAY", "6"))


def _job_allowed() -> bool:
    if _jobs.STORE.ledger_count_24h() >= _MAX_JOBS_PER_DAY:
        return False
    _jobs.STORE.ledger_add("job")
    return True


def _jobs_left() -> bool:
    """Peek at the cap without consuming a slot (the real consumption
    happens inside the job pipeline)."""
    return _jobs.STORE.ledger_count_24h() < _MAX_JOBS_PER_DAY

_ALLOWED = {int(x) for x in os.environ.get("TELEGRAM_ALLOWED_USERS", "").replace(" ", "").split(",") if x}


def _ok(update: Update) -> bool:
    """Authorization: fail CLOSED. An empty allowlist admits nobody unless
    FORGE_ALLOW_PUBLIC=1 explicitly opts into public mode (local dev)."""
    if _ALLOWED:
        return bool(update.effective_user
                    and update.effective_user.id in _ALLOWED)
    return os.environ.get("FORGE_ALLOW_PUBLIC") == "1"


async def _run_blocking(fn, *a, **k):
    """Run a heavy sync job (dive/lesson/video) off the event loop."""
    return await asyncio.get_event_loop().run_in_executor(None, lambda: fn(*a, **k))


def _progress_sender(context, chat: int, every: float = 75.0):
    """A thread-safe on_progress callback that relays pipeline stages to
    the chat, throttled so a render sends a handful of updates, not one
    per frame. Answers 'is it working or hung?' without log-digging."""
    import time as _t
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # constructed off the event loop (inside an executor job) —
        # fall back to the bot's own loop so progress still flows
        loop = getattr(getattr(context, "application", context), "_forge_loop",
                       None) or asyncio.get_event_loop()
    last = {"t": _t.time()}

    def say(msg: str):
        now = _t.time()
        if now - last["t"] < every:
            return
        last["t"] = now
        asyncio.run_coroutine_threadsafe(
            context.bot.send_message(chat, f"🎬 {msg}"), loop)
    return say


_SEND_KW = dict(read_timeout=300, write_timeout=300,
                connect_timeout=60, pool_timeout=60)


async def _deliver_video(context, chat_id, path: Path, caption: str, doc: Path | None = None):
    # Uploads from the host can be slow; the library's default ~20s write
    # timeout kills them. Long timeouts + one retry.
    # Returns the sent Telegram message (so jobs can commit its id).
    is_audio = str(path).endswith((".m4a", ".mp3"))
    msg = None
    for attempt in (1, 2):
        try:
            with open(path, "rb") as f:
                if is_audio:
                    msg = await context.bot.send_audio(
                        chat_id=chat_id, audio=f, caption=caption[:1024],
                        title=caption.lstrip("🎙🎓🥊🔮🕯✨️ ")[:64],
                        performer="Agent Forge", **_SEND_KW)
                else:
                    msg = await context.bot.send_video(
                        chat_id=chat_id, video=f, caption=caption[:1024],
                        supports_streaming=True, **_SEND_KW)
            break
        except Exception:
            if attempt == 2:
                raise
            log.warning("video upload failed; retrying once")
            await asyncio.sleep(5)
    if doc and doc.exists():
        with open(doc, "rb") as f:
            await context.bot.send_document(
                chat_id=chat_id, document=f, filename=doc.name,
                caption="cheat-sheet", **_SEND_KW)
    return msg


# ── commands ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    await update.message.reply_text(
        "This is your learning channel.\n\n"
        "• Send “teach me <anything>” — a narrated lesson video + "
        "cheat-sheet PDF.\n"
        "• “debate <question>” — two hosts argue both sides.\n"
        "• “simulate <scenario>” or “what if …” — a what-if run forward: "
        "dossier + timeline playback.\n"
        "• “story <case>” — a dark-documentary episode: true crime, "
        "disasters, mysteries. Case file + the full tale.\n"
        "• “deep <question>” — no video: the definitive dossier. "
        "Multi-pass research, adversarial review, editor pass, typeset "
        "PDF.\n"
        "• /tonight — the programming director picks tonight's format "
        "and topic for you.\n"
        "• /surprise — a fresh, wild explainer.\n"
        "• Reply to any video with a question — the host answers you.\n"
        "• Reply “read it” to any PDF — a narrated audiobook version.\n"
        "• Send a voice memo instead of typing — I’ll transcribe it.\n"
        "• After a simulation: reply “branch <name>” to run a fork as "
        "its own episode.\n"
        "• /taste <note> — feedback that becomes a standing rule for "
        "every future script.\n"
        "• /retry — re-run the last failed job (everything already "
        "built is reused, you only pay for the missing part).\n"
        "• /feed and /play <n> — your library.\n\n"
        "Give me a few minutes per video — it’s researched, written, "
        "narrated and rendered."
    )


# ── the durable job runner ─────────────────────────────────
#
# Every heavy request becomes a persisted job (see job_state.py). The
# runner is stage-driven: whatever already exists on disk (document,
# script, TTS clips) is REUSED, never repurchased — a restart or /retry
# resumes exactly where the money stopped.

# Per-format configuration: how to build from scratch, how to build from
# an existing document, and how to dress the deliverables.
_FORMATS = {
    "lesson": dict(
        opening="Building your lesson on",
        builder=lambda topic, say, on_doc, audio, cp, clips:
            _lesson.build_lesson(topic, say, on_doc, audio=audio,
                                 checkpoint=cp, clips_dir=clips),
        from_doc=lambda doc, say, audio, cp, clips, scenes:
            _video.build_video(doc, say, _lesson._LESSON_VIDEO_SYSTEM,
                               "THE LESSON", audio=audio, checkpoint=cp,
                               clips_dir=clips, scenes=scenes),
        doc_subtitle="Agent Forge lesson",
        doc_caption="cheat-sheet (episode rendering…)",
        emoji="\U0001f393"),
    "debate": dict(
        opening="Setting up the debate",
        builder=lambda topic, say, on_doc, audio, cp, clips:
            _debate.build_debate(topic, say, on_doc, audio=audio,
                                 checkpoint=cp, clips_dir=clips),
        from_doc=lambda doc, say, audio, cp, clips, scenes:
            _debate.video_from_brief(doc, say, audio=audio, checkpoint=cp,
                                     clips_dir=clips, scenes=scenes),
        doc_subtitle="Agent Forge debate brief",
        doc_caption="debate brief (the hosts are warming up…)",
        emoji="\U0001f94a"),
    "sim": dict(
        opening="Running the simulation",
        builder=lambda topic, say, on_doc, audio, cp, clips:
            _sim.build_sim(topic, say, on_doc, audio=audio,
                           checkpoint=cp, clips_dir=clips),
        from_doc=lambda doc, say, audio, cp, clips, scenes:
            _sim.video_from_dossier(doc, say, audio=audio, checkpoint=cp,
                                    clips_dir=clips, scenes=scenes),
        doc_subtitle="Agent Forge scenario dossier",
        doc_caption="scenario dossier (playback rendering…)",
        emoji="\U0001f52e"),
    "story": dict(
        opening="Opening the case",
        builder=lambda topic, say, on_doc, audio, cp, clips:
            _story.build_story(topic, say, on_doc, audio=audio,
                               checkpoint=cp, clips_dir=clips),
        from_doc=lambda doc, say, audio, cp, clips, scenes:
            _story.video_from_casefile(doc, say, audio=audio, checkpoint=cp,
                                       clips_dir=clips, scenes=scenes),
        doc_subtitle="Agent Forge case file",
        doc_caption="case file (the episode is rendering…)",
        emoji="\U0001f56f️"),
}


def _job_checkpoint(job: "_jobs.Job", loop=None):
    """checkpoint(kind, payload) callable handed to builders — persists
    the script the moment it exists, BEFORE any TTS spend. Thread-safe:
    builders call it from the executor thread."""
    def cp(kind, payload):
        if kind == "script":
            _jobs.atomic_write_json(job.path("script.json"), payload)
            job.set_path("script", job.path("script.json"))
            job.set_stage("script_ready")
    return cp


def _load_script(job: "_jobs.Job"):
    p = job.get_path("script")
    if p and p.exists():
        scenes = _jobs.read_json(p)
        if isinstance(scenes, list) and scenes:
            return scenes
    return None


async def _start_job(context, chat: int, kind: str, mode: str, topic: str,
                     announce: str, prepare=None, **extra):
    """Create + persist the job, then run it now or queue it. The single
    entry point for every heavy request. `prepare(job)` runs after
    creation but BEFORE execution starts (persist sources, etc.)."""
    if not _job_allowed():
        await context.bot.send_message(
            chat,
            f"Daily budget guard: {_MAX_JOBS_PER_DAY} jobs/day reached. "
            "Raise MAX_JOBS_PER_DAY in Render env if intentional.")
        return None
    job = _jobs.STORE.create(kind, mode, topic, chat, **extra)
    if prepare is not None:
        prepare(job)
        job.save()
    if not _jobs.STORE.acquire(job):
        pos = _jobs.STORE.queue_position(job.id) or "?"
        await context.bot.send_message(
            chat, f"⏳ Another episode is in production — queued this one "
                  f"(position {pos}): {topic[:120]}")
        return job
    await context.bot.send_message(chat, announce)
    asyncio.create_task(_execute_job(context, job))
    return job


async def _execute_job(context, job: "_jobs.Job"):
    """Run one persisted job from whatever stage its state says, deliver,
    then start the next queued job. Failures are counted per stage:
    waiting_retry (with clips/doc kept), needs_attention after
    MAX_STAGE_FAILURES."""
    chat = job.chat
    say = _progress_sender(context, chat)
    loop = asyncio.get_running_loop()
    try:
        if job.kind in _FORMATS:
            await _run_format_job(context, job, say, loop)
        elif job.kind == "deep":
            await _run_deep_job(context, job, say)
        elif job.kind == "narrate":
            await _run_narrate_job(context, job, say)
        else:
            job.error(f"unknown kind {job.kind!r}")
            job.set_stage("needs_attention")
    except Exception as e:
        stage = job.stage
        log.exception("job %s failed at %s", job.id, stage)
        n = job.record_failure(stage, f"{type(e).__name__}: {e}")
        if isinstance(e, _video.NarrationIncomplete):
            detail = (f"{len(e.missing)} of {e.total} narration segments "
                      "failed TTS. Finished clips are saved — /retry only "
                      "pays for the missing ones.")
        else:
            detail = f"{type(e).__name__}: {str(e)[:300]}"
        if n >= _jobs.MAX_STAGE_FAILURES:
            job.set_stage("needs_attention")
            doc = job.get_path("document")
            extra = ""
            if doc and doc.exists():
                extra = ("\nThe research document was already delivered "
                         "and is safe.")
            await context.bot.send_message(
                chat, f"🛑 “{job.topic[:80]}” failed {n}× at stage "
                      f"{stage}: {detail}{extra}\nIt's retained — /retry "
                      "when you want another attempt.")
        else:
            job.set_stage("waiting_retry")
            await context.bot.send_message(
                chat, f"⚠️ “{job.topic[:80]}” failed at stage {stage} "
                      f"({n}/{_jobs.MAX_STAGE_FAILURES}): {detail}\n"
                      "Everything already built is saved — send /retry.")
    finally:
        nxt = _jobs.STORE.release(job)
        if nxt:
            njob = _jobs.STORE.load(nxt)
            if njob and _jobs.STORE.acquire(njob):
                await context.bot.send_message(
                    njob.chat, f"▶️ Starting the queued job: "
                               f"{njob.topic[:120]}")
                asyncio.create_task(_execute_job(context, njob))


async def _run_format_job(context, job: "_jobs.Job", say, loop):
    """lesson/debate/sim/story — document, then script, then episode."""
    cfg = _FORMATS[job.kind]
    chat = job.chat
    audio = job.mode == "audio"
    cp = _job_checkpoint(job)

    async def _send_doc_early(doc_path):
        send_path = doc_path
        try:
            from .docrender import md_to_pdf
            send_path = await _run_blocking(
                md_to_pdf, doc_path, cfg["doc_subtitle"])
        except Exception:
            log.exception("pdf render failed; sending raw md")
        with open(send_path, "rb") as f:
            await context.bot.send_document(
                chat_id=chat, document=f, filename=send_path.name,
                caption=cfg["doc_caption"], **_SEND_KW)
        job.d["doc_sent"] = True
        job.save()

    def _on_doc(doc_path):
        job.set_path("document", doc_path)
        job.set_stage("document_ready")
        asyncio.run_coroutine_threadsafe(_send_doc_early(doc_path), loop)

    doc = job.get_path("document")
    scenes = _load_script(job)
    if doc is None or not doc.exists():
        job.set_stage("researching")
        r = await _run_blocking(
            lambda: cfg["builder"](job.topic, say, _on_doc, audio, cp,
                                   job.clips_dir))
    else:
        # research already paid for — never repeat it
        job.set_stage("script_ready" if scenes else "script_generating")
        r = await _run_blocking(
            lambda: cfg["from_doc"](doc, say, audio, cp, job.clips_dir,
                                    scenes))
    title = r.get("title") or job.topic
    job.d["title"] = title
    path = r.get("path") or r.get("video")
    job.set_path("final", path)
    job.set_stage("delivery_pending")
    emoji = "\U0001f399" if audio else cfg["emoji"]
    tag = "" if r.get("voiced", True) else " (silent — no TTS on this host)"
    job.d["delivery"]["attempts"] = job.d["delivery"].get("attempts", 0) + 1
    job.save()
    msg = await _deliver_video(context, chat, Path(path),
                               f"{emoji} {title}{tag}")
    job.d["delivery"]["message_id"] = getattr(msg, "message_id", None)
    job.set_stage("delivered")
    if r.get("quality"):
        await context.bot.send_message(chat, f"🧪 {r['quality']}")
    if job.kind == "sim" and r.get("doc"):
        _LAST_SIM[chat] = str(r["doc"])
        await context.bot.send_message(
            chat, "🔀 This run followed the mainline. Reply “branch <name "
                  "or letter>” (from the dossier's branch points) and I'll "
                  "run that fork as its own episode.")


async def _make_lesson(update, context, topic: str, audio: bool = False):
    chat = update.effective_chat.id
    await _start_job(
        context, chat, "lesson", "audio" if audio else "video", topic,
        f"Building your lesson on: {topic}\n(a few minutes…)")


async def _make_show(update, context, topic: str, builder=None, *,
                     opening: str = "", doc_subtitle: str = "",
                     doc_caption: str = "", emoji: str = "",
                     kind: str = "show", audio: bool = False):
    """Compatibility wrapper: routes the doc+episode formats through the
    durable job runner (config now lives in _FORMATS)."""
    chat = update.effective_chat.id
    cfg = _FORMATS.get(kind)
    open_line = (cfg["opening"] if cfg else opening) or "Working on"
    await _start_job(
        context, chat, kind, "audio" if audio else "video", topic,
        f"{open_line}: {topic}\n(a few minutes…)")


async def _make_debate(update, context, topic: str, audio: bool = False):
    await _make_show(update, context, topic, kind="debate", audio=audio)


async def _make_sim(update, context, scenario: str, audio: bool = False):
    # branch replies are announced by the runner after delivery
    await _make_show(update, context, scenario, kind="sim", audio=audio)


def _find_doc_for(caption: str) -> Path | None:
    """Map a delivered video/document caption back to its lesson/dive md."""
    import re as _re
    t = _re.sub(r"^\W+\s*", "", caption or "").strip()   # strip emoji prefix
    t = _re.sub(r"\s*\((silent[^)]*)\)\s*$", "", t)
    if not t:
        return None
    slug = _explorer._slugify(t)
    for cand in (f"{slug}.lesson.md", f"{slug}.md"):
        p = _explorer.EXPLORATIONS_DIR / cand
        if p.exists():
            return p
    hits = sorted(_explorer.EXPLORATIONS_DIR.glob(f"{slug[:40]}*.md"))
    return hits[0] if hits else None


_READ_WORDS = ("read it", "read", "narrate", "narrate it",
               "read it to me", "read this", "audiobook")


async def _narrate_message(update, context, target, doc: Path | None):
    """Narrate the document carried by `target` (a Telegram message).
    `doc` is a known markdown source, if the filename matched the library;
    otherwise the PDF is downloaded and its text extracted."""
    chat = update.effective_chat.id
    pdf_text = None
    out_hint = None
    if doc is None and getattr(target, "document", None) \
            and str(target.document.file_name or "").lower().endswith(".pdf"):
        # a PDF we don't have the source for (forwarded / uploaded /
        # made in a session): download and extract its text
        import tempfile
        tg_file = await context.bot.get_file(target.document.file_id)
        pdf_local = Path(tempfile.mkdtemp(prefix="forge_read_")) / \
            (target.document.file_name or "doc.pdf")
        await tg_file.download_to_drive(str(pdf_local))
        try:
            pdf_text = await _run_blocking(_narrate.pdf_to_text, pdf_local)
        except Exception as e:
            await update.message.reply_text(
                f"Couldn't extract text from that PDF: {type(e).__name__}")
            return
        doc = pdf_local
        out_hint = str(_explorer.EXPLORATIONS_DIR / (pdf_local.stem + ".m4a"))
    if doc is None:
        await update.message.reply_text(
            "Couldn't match that message to a document — reply "
            "directly to the PDF you want read (forwarded PDFs "
            "work too).")
        return
    def _persist_source(job):
        # the source lives INSIDE the job dir — a temp-dir source would
        # be gone after a restart, stranding the job
        if pdf_text is not None:
            job.path("source.txt").write_text(pdf_text, encoding="utf-8")
        else:
            job.set_path("document", doc)

    await _start_job(
        context, chat, "narrate", "audio", f"audiobook: {doc.name}",
        "🎧 Adapting the document for narration (5-10 min)…",
        prepare=_persist_source, out_hint=out_hint)


async def on_document(update, context):
    """A PDF sent straight to the bot (no reply chain). Caption with a
    read-word — or NO caption at all — starts the audiobook narration;
    anything else gets a hint. This exists because Telegram's attach flow
    makes captions easy to miss: sending a PDF is itself the intent."""
    if not _ok(update):
        return
    msg = update.message
    if not (msg and msg.document
            and str(msg.document.file_name or "").lower().endswith(".pdf")):
        return
    # a library PDF's filename maps back to its markdown source
    doc = None
    stem = Path(msg.document.file_name).stem
    cand = _explorer.EXPLORATIONS_DIR / f"{stem}.md"
    if cand.exists():
        doc = cand
    caption = (msg.caption or "").lower().strip(" !.")
    if caption and caption not in _READ_WORDS:
        await msg.reply_text(
            "Got the PDF. Send it with no caption (or caption it "
            "“read it”) and I'll narrate it as an audiobook.")
        return
    await _narrate_message(update, context, msg, doc)


async def _answer_reply(update, context, question: str):
    """The viewer replied to a delivered video/cheat-sheet with a question:
    answer as the host — text plus a voice note. Cheap (one text call + TTS),
    so it doesn't count against the daily job cap."""
    chat = update.effective_chat.id
    target = update.message.reply_to_message
    caption = target.caption or target.text or ""
    doc = None
    # a reply to a PDF: the filename maps exactly to its markdown source
    if getattr(target, "document", None) and target.document.file_name:
        stem = Path(target.document.file_name).stem
        cand = _explorer.EXPLORATIONS_DIR / f"{stem}.md"
        if cand.exists():
            doc = cand
    if doc is None:
        doc = _find_doc_for(caption)

    # "read it" on a document -> the audiobook layer
    if question.lower().strip(" !.") in _READ_WORDS:
        await _narrate_message(update, context, target, doc)
        return
    grounding = ""
    if doc is not None:
        try:
            grounding = doc.read_text(encoding="utf-8")[:12000]
        except Exception:
            pass

    def _ask() -> str:
        from .providers import get_provider
        sys = ("You are the host of the video the viewer is replying to"
               + (f" (titled: {caption[:120]})" if caption else "")
               + ". Answer their question directly and concretely in 2-5 "
               "spoken sentences — conversational, no markdown, no lists. "
               "If you genuinely don't know, say so."
               + ("\n\nThe episode's source document, for grounding:\n\n"
                  + grounding if grounding else ""))
        return get_provider("anthropic").complete(
            system=sys, user=question, model="sonnet", max_tokens=1000,
        ).strip()

    try:
        ans = await _run_blocking(_ask)
    except Exception as e:
        await update.message.reply_text(f"Couldn't answer: {type(e).__name__}: {e}")
        return

    # voice-note the answer in the host's voice; text as the fallback/record
    import subprocess
    import tempfile
    workdir = Path(tempfile.mkdtemp(prefix="forge_reply_"))
    mp3 = workdir / "answer.mp3"

    def _tts() -> bool:
        return (_video._openai_tts(
                    ans, mp3,
                    "Warm, conversational — answering a viewer's question "
                    "directly, like the host of the show they just watched.")
                or _video.synth(ans, mp3))

    sent_voice = False
    try:
        if await _run_blocking(_tts):
            ogg = workdir / "answer.ogg"
            subprocess.run(
                [_video._ffmpeg(), "-y", "-i", str(mp3),
                 "-c:a", "libopus", "-b:a", "48k", str(ogg)],
                check=True, capture_output=True)
            with open(ogg, "rb") as f:
                await context.bot.send_voice(chat, voice=f)
            sent_voice = True
    except Exception:
        log.exception("voice reply failed; sending text only")
    if not sent_voice:
        await update.message.reply_text(ans)


async def _route_text(update, context, txt: str):
    txt = (txt or "").strip()
    if not txt:
        return
    target = update.message.reply_to_message if update.message else None
    if target and target.from_user and target.from_user.is_bot:
        await _answer_reply(update, context, txt)
        return
    low = txt.lower()
    audio = False
    if low.startswith("podcast"):
        audio = True
        txt = txt[len("podcast"):].strip(" :—-")
        low = txt.lower()
        if not txt:
            await update.message.reply_text(
                "Say: podcast story <case> / podcast debate <q> / "
                "podcast teach me <topic> — same shows, audio-only, "
                "minutes instead of half-hours.")
            return
    if low.startswith(("taste:", "feedback:")):
        note = txt.split(":", 1)[1].strip()
        if note:
            _taste.add(note)
            await update.message.reply_text(
                "Noted. Every future script gets this as a standing "
                "directive. (/taste to add more anytime)")
        return
    chat = update.effective_chat.id
    if low.startswith("branch") and _LAST_SIM.get(chat):
        try:
            prior = Path(_LAST_SIM[chat]).read_text(encoding="utf-8")[:8000]
        except Exception:
            prior = ""
        scenario = (f"CONTINUATION EPISODE. The viewer chose: '{txt}'. "
                    f"The prior run's dossier follows — commit to that "
                    f"branch at its branch point and simulate FROM there "
                    f"forward (new timeline, new consequences, new end "
                    f"states).\n\nPRIOR DOSSIER:\n{prior}")
        await _make_sim(update, context, scenario)
        return
    if low.startswith("debate"):
        await _make_debate(update, context, txt[len("debate"):].strip(" :—-"), audio=audio)
        return
    if low.startswith(("deep:", "deep ", "go deep on")):
        q = txt.split(":", 1)[1] if low.startswith("deep:") else \
            (txt[len("go deep on"):] if low.startswith("go deep on")
             else txt[len("deep"):])
        q = q.strip(" :—-")
        if q:
            await _make_deep(update, context, q)
            return
    if low.startswith(("story", "case:")):
        case = (txt[len("story"):] if low.startswith("story")
                else txt.split(":", 1)[1]).strip(" :—-")
        if case.lower() in ("", "surprise", "me", "surprise me", "time"):
            await _discover_story(update, context)
        else:
            await _make_story(update, context, case, audio=audio)
        return
    if low.startswith("simulate"):
        await _make_sim(update, context, txt[len("simulate"):].strip(" :—-"), audio=audio)
        return
    if low.startswith("what if"):
        await _make_sim(update, context, txt, audio=audio)
        return
    topic = txt[len("teach me"):].strip(" :—-") if low.startswith("teach me") else txt
    await _make_lesson(update, context, topic, audio=audio)


async def cmd_teach(update, context):
    if not _ok(update):
        return
    topic = " ".join(context.args) if context.args else ""
    if not topic:
        await update.message.reply_text("Say: teach me <topic>")
        return
    await _make_lesson(update, context, topic)


async def cmd_debate(update, context):
    if not _ok(update):
        return
    topic = " ".join(context.args) if context.args else ""
    if not topic:
        await update.message.reply_text("Say: /debate <question>")
        return
    await _make_debate(update, context, topic)


async def _make_story(update, context, case: str, audio: bool = False):
    await _make_show(update, context, case, kind="story", audio=audio)


async def cmd_story(update, context):
    """/story <case> — or /story alone to have the editor find one."""
    if not _ok(update):
        return
    case = " ".join(context.args) if context.args else ""
    if not case:
        await _discover_story(update, context)
        return
    await _make_story(update, context, case)


async def _discover_story(update, context):
    chat = update.effective_chat.id
    await context.bot.send_message(chat, "🕯️ Hunting for tonight's case…")
    try:
        avoid = ([e.get("topic", "") for e in _explorer.load_journal()]
                 + _story.covered_cases())
        case = await _run_blocking(_story.find_case, avoid)
    except Exception as e:
        await context.bot.send_message(
            chat, f"The hunt failed: {type(e).__name__}: {e}")
        return
    await context.bot.send_message(chat, f"Tonight's case: {case}")
    await _make_story(update, context, case)


async def _run_deep_job(context, job: "_jobs.Job", say):
    """Document-only flagship. Stages: researching -> document_ready ->
    delivery_pending -> delivered. A restart after the document exists
    only re-renders/re-uploads the PDF — the research is never repeated."""
    chat = job.chat
    doc = job.get_path("document")
    if doc is None or not doc.exists():
        job.set_stage("researching")
        r = await _run_blocking(_deep.build_deep, job.topic, say)
        doc = Path(str(r["doc"]))
        job.d["title"] = r["title"]
        job.set_path("document", doc)
        job.set_stage("document_ready")
    title = job.get("title") or job.topic
    send_path = doc
    try:
        from .docrender import md_to_pdf
        send_path = await _run_blocking(
            md_to_pdf, doc, "Agent Forge deep dossier")
    except Exception:
        log.exception("pdf render failed; sending raw md")
    job.set_path("final", send_path)
    job.set_stage("delivery_pending")
    with open(send_path, "rb") as f:
        msg = await context.bot.send_document(
            chat_id=chat, document=f, filename=send_path.name,
            caption=f"📜 {title}", **_SEND_KW)
    job.d["delivery"]["message_id"] = getattr(msg, "message_id", None)
    job.set_stage("delivered")


async def _run_narrate_job(context, job: "_jobs.Job", say):
    """Audiobook of a document. The source text is persisted in the job
    dir, the adapted script checkpoints before TTS, and clips are keyed —
    a restart resumes from whatever is already on disk."""
    chat = job.chat
    src = job.path("source.txt")
    text = src.read_text(encoding="utf-8") if src.exists() else None
    doc = job.get_path("document") or src
    scenes = _load_script(job)
    if scenes is None:
        job.set_stage("script_generating")
    else:
        job.set_stage("full_tts")
    out = job.get("out_hint") or str(
        _explorer.EXPLORATIONS_DIR / (Path(str(doc)).stem + ".m4a"))
    r = await _run_blocking(
        lambda: _narrate.build_narration(
            doc, say, text=text, out_path=out,
            checkpoint=_job_checkpoint(job), clips_dir=job.clips_dir,
            scenes=scenes))
    job.d["title"] = r.get("title") or job.topic
    job.set_path("final", r["path"])
    job.set_stage("delivery_pending")
    tag = f" ({r.get('minutes', '?')} min)" if r.get("minutes") else ""
    msg = await _deliver_video(context, chat, Path(str(r["path"])),
                               f"🎧 {job.get('title')}{tag}")
    job.d["delivery"]["message_id"] = getattr(msg, "message_id", None)
    job.set_stage("delivered")
    if r.get("fallback"):
        await context.bot.send_message(
            chat, f"⚠️ {r['fallback']} segments used the fallback "
                  "voice — check OpenAI limits.")


async def _make_deep(update, context, question: str):
    """Document-only flagship: the definitive dossier, no video."""
    chat = update.effective_chat.id
    await _start_job(
        context, chat, "deep", "document", question,
        f"Going deep: {question}\n(10-15 minutes — research, "
        "adversarial review, synthesis, edit…)")


async def cmd_deep(update, context):
    if not _ok(update):
        return
    q = " ".join(context.args) if context.args else ""
    if not q:
        await update.message.reply_text(
            "Say: /deep <the question/idea/debate/scenario you want the "
            "definitive document on>")
        return
    await _make_deep(update, context, q)


async def cmd_tonight(update, context):
    """One programmed feed slot, on demand: the director picks."""
    if not _ok(update):
        return
    chat = update.effective_chat.id
    await context.bot.send_message(chat, "📺 Asking the programming director…")
    try:
        ok = await _air_slot(context.application, chat)
        if not ok:
            await context.bot.send_message(
                chat, "The director came back empty — try again.")
    except Exception as e:
        await context.bot.send_message(
            chat, f"Programming failed: {type(e).__name__}: {e}")


async def cmd_test(update, context):
    """Zero-LLM pipeline check: canned scenes through the FULL production
    pipeline (packaging, charts, host, music, ducking). Costs ~a cent of
    TTS — run it after every deploy before spending on real content."""
    if not _ok(update):
        return
    chat = update.effective_chat.id
    await context.bot.send_message(
        chat, "🔧 Rendering the pipeline check (~2 min; no LLM spend, "
              "~1¢ of TTS)…")
    scenes = [
        {"kicker": "check one", "headline": "Voice and captions",
         "narration": "If you can hear this line, narration and the music "
                      "duck are working.",
         "pose": "wave", "delivery": "bright", "layout": "standard"},
        {"kicker": "check two", "headline": "Charts land with ticks",
         "narration": "Bars should grow with the voice — and land with a "
                      "tick.",
         "pose": "point", "delivery": "neutral", "layout": "fullviz",
         "data": {"type": "bars", "title": "SYSTEM CHECK",
                  "items": [{"label": "Audio", "value": 100},
                            {"label": "Motion", "value": 100},
                            {"label": "Charts", "value": 100}]}},
        {"kicker": "check three", "headline": "All systems live",
         "narration": "Punch card, riser, dip to black… you're clear to "
                      "spend real money.",
         "pose": "celebrate", "delivery": "hype", "layout": "punch"},
    ]
    out = _explorer.EXPLORATIONS_DIR / "pipeline-check.mp4"
    try:
        r = await _run_blocking(
            _video.render_scenes, scenes, out,
            _progress_sender(context, chat), "Pipeline Check", "SYSTEM")
        tag = "" if r["voiced"] else " (SILENT — TTS unreachable!)"
        await _deliver_video(context, chat, r["path"], f"🔧 Pipeline check{tag}")
    except Exception as e:
        await context.bot.send_message(
            chat, f"Pipeline check FAILED: {type(e).__name__}: {e}")


async def cmd_retry(update, context):
    """Re-run the most recent retained job (waiting_retry /
    needs_attention). Everything durable — document, script, finished
    TTS clips — is reused, so a retry only pays for what's missing."""
    if not _ok(update):
        return
    chat = update.effective_chat.id
    job = _jobs.STORE.latest_retained()
    if job is None:
        await update.message.reply_text(
            "Nothing is waiting for a retry — all jobs delivered.")
        return
    # a deliberate retry earns a fresh failure budget at the stuck stage
    job.d.setdefault("stage_failures", {})[job.stage] = 0
    job.d["status"] = "running"
    job.save()
    if not _jobs.STORE.acquire(job):
        pos = _jobs.STORE.queue_position(job.id) or "?"
        await update.message.reply_text(
            f"⏳ A job is running — queued the retry (position {pos}).")
        return
    await context.bot.send_message(
        chat, f"🔁 Retrying “{job.topic[:100]}” from stage {job.stage} — "
              "finished work is reused, only the missing part is paid "
              "for.")
    asyncio.create_task(_execute_job(context, job))


async def cmd_taste(update, context):
    """Feedback that persists: '/taste the hooks are too slow' becomes a
    standing directive in every future script."""
    if not _ok(update):
        return
    note = " ".join(context.args) if context.args else ""
    if not note:
        await update.message.reply_text(
            "Say: /taste <what you want more/less of> — it becomes a "
            "standing note every future script must obey.")
        return
    _taste.add(note)
    await update.message.reply_text("Noted. Future scripts obey.")


async def cmd_simulate(update, context):
    if not _ok(update):
        return
    scenario = " ".join(context.args) if context.args else ""
    if not scenario:
        await update.message.reply_text("Say: /simulate <scenario>")
        return
    await _make_sim(update, context, scenario)


async def on_text(update, context):
    if not _ok(update):
        return
    await _route_text(update, context, update.message.text or "")


async def on_voice(update, context):
    """A voice memo: transcribe it (OpenAI), then route it like typed text."""
    if not _ok(update):
        return
    v = update.message.voice or update.message.audio
    if not v:
        return
    import tempfile
    p = Path(tempfile.mkdtemp(prefix="forge_voice_")) / "in.ogg"
    tg_file = await context.bot.get_file(v.file_id)
    await tg_file.download_to_drive(str(p))

    def _transcribe() -> str:
        from openai import OpenAI
        client = OpenAI()
        with open(p, "rb") as fh:
            try:
                r = client.audio.transcriptions.create(
                    model="gpt-4o-mini-transcribe", file=fh)
            except Exception:
                fh.seek(0)
                r = client.audio.transcriptions.create(
                    model="whisper-1", file=fh)
        return (r.text or "").strip()

    try:
        txt = await _run_blocking(_transcribe)
    except Exception as e:
        await update.message.reply_text(
            f"Couldn't transcribe that: {type(e).__name__} "
            "(is OPENAI_API_KEY set on the host?)")
        return
    if not txt:
        await update.message.reply_text("I couldn't hear anything in that.")
        return
    await update.message.reply_text(f"Heard: “{txt}”")
    await _route_text(update, context, txt)


async def cmd_surprise(update, context):
    if not _ok(update):
        return
    if not _job_allowed():
        await context.bot.send_message(
            update.effective_chat.id,
            f"Daily budget guard: {_MAX_JOBS_PER_DAY} jobs/day reached. "
            "Raise MAX_JOBS_PER_DAY in Render env if intentional.")
        return
    chat = update.effective_chat.id
    await context.bot.send_message(chat, "Finding something wild…")
    try:
        avoid = [e.get("topic", "") for e in _explorer.load_journal()]
        cands = await _run_blocking(_sources.discover, 4, avoid)
        topic = cands[0]["topic"] if cands else "a genuinely surprising true story"
        dive = await _run_blocking(_explorer.dive, topic)
        vid = await _run_blocking(_video.build_video, dive["path"])
    except Exception as e:  # pragma: no cover
        await context.bot.send_message(chat, f"Failed: {e}")
        return
    tag = "" if vid["voiced"] else " (silent)"
    await _deliver_video(context, chat, vid["path"], f"✨ {dive['title']}{tag}")


async def cmd_diag(update, context):
    """Run the Anthropic selfcheck and reply with the raw result — no log
    digging needed."""
    if not _ok(update):
        return
    chat = update.effective_chat.id
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    await context.bot.send_message(
        chat, f"key: {'configured' if key else 'MISSING'} "
              f"(len={len(key)})\ntesting a live call…")

    def _test() -> str:
        try:
            from .providers import get_provider
            out = get_provider("anthropic").complete(
                system="Reply with exactly: ok", user="ping",
                model="claude-sonnet-5", max_tokens=2048,
            )
            return f"✅ Anthropic (the brain) WORKS — reply: {out[:60]}"
        except Exception as e:
            return f"❌ Anthropic (the brain): {type(e).__name__}: {str(e)[:400]}"

    def _test_voice() -> str:
        okey = os.environ.get("OPENAI_API_KEY", "")
        if not okey:
            return ("🔇 OPENAI_API_KEY missing — narration falls back to "
                    "the robotic edge-tts voice")
        import tempfile
        from pathlib import Path as _P
        mp3 = _P(tempfile.mkdtemp(prefix="forge_diag_")) / "t.mp3"
        if _video._openai_tts("Voice check.", mp3, "neutral"):
            return ("✅ OpenAI voice WORKS — videos narrate with the "
                    "expressive voice")
        return ("❌ OpenAI key present but TTS call FAILED — check the "
                "key/credits at platform.openai.com; narration falls "
                "back to the robotic voice")

    result = await _run_blocking(_test)
    await context.bot.send_message(chat, result)
    result = await _run_blocking(_test_voice)
    await context.bot.send_message(chat, result)


async def cmd_feed(update, context):
    if not _ok(update):
        return
    await update.message.reply_text(_feed.feed(n=15))


async def cmd_play(update, context):
    if not _ok(update):
        return
    try:
        i = int(context.args[0])
        item = _feed.library()[i - 1]
    except Exception:
        await update.message.reply_text("Usage: /play <n> (see /feed)")
        return
    stem = Path(item["file"]).stem
    mp4 = _explorer.EXPLORATIONS_DIR / f"{stem}.mp4"
    if not mp4.exists():
        await context.bot.send_message(update.effective_chat.id, "Rendering that one…")
        await _run_blocking(_video.build_video, _explorer.EXPLORATIONS_DIR.parent / item["file"])
    await _deliver_video(context, update.effective_chat.id, mp4, f"▶ {item['topic']}")


# ── background auto-feed ─────────────────────────────────

def _selfcheck() -> None:
    """One tiny Anthropic call at boot so the logs show immediately whether
    the API key + network path work (instead of failing on the first job)."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    log.info("selfcheck: ANTHROPIC_API_KEY %s (len=%d)",
             "present" if key else "MISSING", len(key))
    try:
        from .providers import get_provider
        out = get_provider("anthropic").complete(
            system="Reply with exactly: ok", user="ping",
            model="haiku", max_tokens=2048,
        )
        log.info("selfcheck: Anthropic reachable, reply=%r", out[:40])
    except Exception:
        log.exception("selfcheck: Anthropic call FAILED — lessons will fail too")


async def _post_init(app: Application) -> None:
    """Runs inside the bot's event loop — safe to schedule background
    tasks. The feed loops start HERE, on every boot — clean or resumed
    (they were previously nested inside the resume path only, so a clean
    boot never started the auto-feed)."""
    app._forge_loop = asyncio.get_running_loop()
    asyncio.get_event_loop().run_in_executor(None, _selfcheck)
    try:
        _jobs.STORE.sweep()
    except Exception:
        log.exception("retention sweep failed")
    # A restart (deploy, OOM, crash) kills any in-flight job — announce
    # it, then RESUME the job from its persisted state.
    resumed = False
    legacy = _jobs.STORE.legacy_payload()
    if legacy is not None:
        # pre-schema payload: {kind, topic, chat, doc}. Its audio flag was
        # never persisted, so the old resume could turn a podcast into a
        # video. Never guess the mode — tell the owner instead.
        try:
            (_explorer.EXPLORATIONS_DIR / "pending_job.json").unlink(
                missing_ok=True)
        except OSError:
            pass
        chat = legacy.get("chat")
        if chat:
            resumed = True
            await app.bot.send_message(
                chat, f"⚡ A restart killed “{legacy.get('topic', 'a job')}” "
                      "from before the durable-jobs upgrade — I can't tell "
                      "whether it was a podcast or a video, so I won't "
                      "guess. Send the request again (any finished "
                      "research PDF you already received is still good).")
    elif _jobs.STORE.active_id():
        resumed = True
        asyncio.create_task(_resume_job(app))
    elif _jobs.STORE.queued_ids():
        # a restart landed between one job finishing and the next
        # starting — don't strand the queue
        nxt = _jobs.STORE.queued_ids()[0]
        njob = _jobs.STORE.load(nxt)
        if njob and _jobs.STORE.acquire(njob):
            resumed = True
            await app.bot.send_message(
                njob.chat, f"▶️ Starting the queued job: "
                           f"{njob.topic[:120]}")
            asyncio.create_task(_execute_job(app, njob))
    if not resumed:
        for uid in _ALLOWED:
            try:
                await app.bot.send_message(
                    uid, "⚡ Worker restarted (deploy). Ready.")
            except Exception:
                log.warning("restart notice to %s failed", uid)
    every = int(os.environ.get("RESTOCK_EVERY", "0"))
    if every and _ALLOWED:
        asyncio.create_task(_restock_loop(app))
    if os.environ.get("FORGE_DAILY_HOUR", "").strip() and _ALLOWED:
        asyncio.create_task(_daily_loop(app))


async def _resume_job(app: Application):
    """Stage-driven resume of the persisted active job. Never clears
    state up front: the job stays on disk until it is delivered or
    retained as needs_attention. Whatever is already durable (document,
    script, TTS clips) is reused — only missing work re-runs."""
    jid = _jobs.STORE.active_id()
    job = _jobs.STORE.load(jid) if jid else None
    if job is None:
        try:
            (_explorer.EXPLORATIONS_DIR / "pending_job.json").unlink(
                missing_ok=True)
        except OSError:
            pass
        return
    chat = job.chat
    if not chat:
        job.set_stage("needs_attention")
        _jobs.STORE.release(job)
        return
    job.d["resume_count"] = job.get("resume_count", 0) + 1
    job.save()
    if job.stage == "delivered":
        _jobs.STORE.release(job)
        return
    if job.get("resume_count") > 4:
        job.set_stage("needs_attention")
        await app.bot.send_message(
            chat, f"🛑 “{job.topic[:80]}” has been interrupted "
                  f"{job.get('resume_count')} times — retaining it "
                  "instead of looping. /retry to attempt it again.")
        _jobs.STORE.release(job)
        return
    # never resume a malformed doc (e.g. the model asked a question back
    # instead of researching) — that renders garbage on a loop
    doc = job.get_path("document")
    if doc and doc.exists():
        import re as _re
        try:
            _txt = doc.read_text(encoding="utf-8")
        except Exception:
            _txt = ""
        if (not _re.search(r"^#\s+.+$", _txt, _re.M)
                or _txt.count("##") < 3 or len(_txt) < 1200):
            job.set_stage("needs_attention")
            await app.bot.send_message(
                chat, f"⚡ A restart killed “{job.topic[:80]}”, and its "
                      "research looks malformed — retained, not resumed. "
                      "Send the request again.")
            _jobs.STORE.release(job)
            return
    if job.stage == "delivery_pending" and job.get_path("final") \
            and job.get_path("final").exists():
        note = "uploading the finished episode"
    elif doc and doc.exists():
        note = "the research is already done"
    else:
        note = "restarting its research"
    await app.bot.send_message(
        chat, f"♻️ Restart killed “{job.topic[:80]}” at stage "
              f"{job.stage} — resuming ({note}).")
    # delivery_pending with a finished artifact: upload it, don't rebuild
    if job.stage == "delivery_pending":
        final = job.get_path("final")
        if final and final.exists():
            try:
                if final.suffix == ".pdf" or job.kind == "deep":
                    with open(final, "rb") as f:
                        msg = await app.bot.send_document(
                            chat_id=chat, document=f, filename=final.name,
                            caption=f"📜 {job.get('title') or job.topic}",
                            **_SEND_KW)
                else:
                    emoji = "\U0001f399" if job.mode == "audio" else "\U0001f3ac"
                    msg = await _deliver_video(
                        app, chat, final,
                        f"{emoji} {job.get('title') or job.topic}")
                job.d["delivery"]["message_id"] = getattr(
                    msg, "message_id", None)
                job.set_stage("delivered")
                nxt = _jobs.STORE.release(job)
                if nxt:
                    njob = _jobs.STORE.load(nxt)
                    if njob and _jobs.STORE.acquire(njob):
                        asyncio.create_task(_execute_job(app, njob))
                return
            except Exception:
                log.exception("resume delivery failed; falling through")
    await _execute_job(app, job)


async def _daily_loop(app: Application):
    """One auto-discovered episode pushed at a fixed UTC hour every day.
    Enable by setting FORGE_DAILY_HOUR (0-23) in the host env."""
    hour = int(os.environ.get("FORGE_DAILY_HOUR", "0")) % 24
    from datetime import datetime, timedelta, timezone
    while True:
        now = datetime.now(timezone.utc)
        nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        await asyncio.sleep((nxt - now).total_seconds())
        try:
            if not _jobs_left():
                log.info("daily episode skipped: job cap reached")
                continue
            for uid in _ALLOWED:
                await _air_slot(app, uid)
        except Exception as e:  # pragma: no cover
            log.warning("daily episode failed: %s", e)


class _LoopUpdate:
    """Minimal Update-shaped shim so the auto-feed drives the same job
    pipeline (_make_story/_make_sim/...) as a typed command."""
    def __init__(self, chat: int):
        from types import SimpleNamespace
        self.effective_chat = SimpleNamespace(id=chat)
        self.message = None


class _LoopContext:
    def __init__(self, bot):
        self.bot = bot


def _feed_avoid() -> list[str]:
    avoid = [e.get("topic", "") for e in _explorer.load_journal()]
    return avoid + _story.covered_cases()


async def _air_slot(app: Application, chat: int) -> bool:
    """One programmed feed slot: the director picks format+topic, then the
    full pipeline runs exactly as if the viewer had asked. Automatic
    programming never displaces a manual job — if one is active, skip
    this slot (the loop's next tick reschedules naturally)."""
    if _jobs.STORE.active_id():
        log.info("feed slot skipped: a job is already active")
        return False
    slot = await _run_blocking(_sources.pick_slot, _feed_avoid())
    if not slot:
        return False
    teaser = f" — {slot['teaser']}" if slot.get("teaser") else ""
    await app.bot.send_message(
        chat, f"📺 Tonight on the channel ({slot['format']}): "
              f"{slot['topic']}{teaser}")
    upd, ctx = _LoopUpdate(chat), _LoopContext(app.bot)
    fmt = slot["format"]
    if fmt == "story":
        await _make_story(upd, ctx, slot["topic"])
    elif fmt == "sim":
        await _make_sim(upd, ctx, slot["topic"])
    elif fmt == "debate":
        await _make_debate(upd, ctx, slot["topic"])
    else:
        dive = await _run_blocking(_explorer.dive, slot["topic"])
        vid = await _run_blocking(_video.build_video, dive["path"],
                                  _progress_sender(ctx, chat))
        await _deliver_video(ctx, chat, vid["path"], f"✨ {dive['title']}")
    return True


async def _restock_loop(app: Application):
    every = int(os.environ.get("RESTOCK_EVERY", "0"))
    if not every or not _ALLOWED:
        return
    await asyncio.sleep(30)
    while True:
        try:
            if not _jobs_left():
                log.info("auto-feed skipped: daily job cap reached")
            else:
                for uid in _ALLOWED:
                    await _air_slot(app, uid)
        except Exception as e:  # pragma: no cover
            log.warning("feed slot failed: %s", e)
        await asyncio.sleep(every)


def _sanitize_env() -> None:
    """Strip stray whitespace/newlines that sneak in when secrets are pasted
    into dashboard forms (a leading \\n in an API key makes every HTTP
    request die with 'Illegal header value')."""
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS",
              "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
              "FORGE_TTS_VOICE", "FORGE_TTS_VOICE_B",
              "FORGE_OPENAI_VOICE", "FORGE_OPENAI_VOICE_B",
              "FORGE_DAILY_HOUR"):
        v = os.environ.get(k)
        if v is None:
            continue
        cleaned = v.strip().strip("'\"").strip()
        if cleaned != v:
            os.environ[k] = cleaned


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    _sanitize_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set")
    if not _ALLOWED and os.environ.get("FORGE_ALLOW_PUBLIC") != "1":
        raise SystemExit(
            "TELEGRAM_ALLOWED_USERS is empty — refusing to start a bot "
            "that anyone on Telegram could use to spend your API credits. "
            "Set TELEGRAM_ALLOWED_USERS to your numeric Telegram id, or "
            "set FORGE_ALLOW_PUBLIC=1 to explicitly run open (local dev "
            "only).")

    app = Application.builder().token(token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("teach", cmd_teach))
    app.add_handler(CommandHandler("debate", cmd_debate))
    app.add_handler(CommandHandler("simulate", cmd_simulate))
    app.add_handler(CommandHandler("taste", cmd_taste))
    app.add_handler(CommandHandler("retry", cmd_retry))
    app.add_handler(CommandHandler("story", cmd_story))
    app.add_handler(CommandHandler("tonight", cmd_tonight))
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("deep", cmd_deep))
    app.add_handler(CommandHandler("surprise", cmd_surprise))
    app.add_handler(CommandHandler("diag", cmd_diag))
    app.add_handler(CommandHandler("feed", cmd_feed))
    app.add_handler(CommandHandler("play", cmd_play))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.Document.PDF, on_document))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    log.info("learning-feed worker up; auto-feed every %ss",
             os.environ.get("RESTOCK_EVERY", "0"))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
