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
from . import taste as _taste

# last delivered sim dossier per chat — enables "branch A/B" continuations
_LAST_SIM: dict[int, str] = {}

# The in-flight job, persisted to disk so a restart (deploy/OOM) can
# resume the render instead of silently orphaning it.
_PENDING = None


def _pending_path():
    return _explorer.EXPLORATIONS_DIR / "pending_job.json"


def _pending_write(kind: str, topic: str, chat: int, doc: str | None = None):
    import json
    try:
        _explorer.EXPLORATIONS_DIR.mkdir(exist_ok=True)
        _pending_path().write_text(json.dumps(
            {"kind": kind, "topic": topic, "chat": chat, "doc": doc}))
    except Exception:
        log.warning("pending-job write failed")


def _pending_clear():
    try:
        _pending_path().unlink(missing_ok=True)
    except Exception:
        pass

log = logging.getLogger("agent_forge.worker")

# Hard daily cap on expensive jobs (lessons/surprises/auto-feed items).
# Each job is roughly $1.50-2.50 of API spend; this is the in-app circuit
# breaker so no bug can ever drain an account. Override with MAX_JOBS_PER_DAY.
_MAX_JOBS_PER_DAY = int(os.environ.get("MAX_JOBS_PER_DAY", "6"))
_jobs_today: list[float] = []


def _job_allowed() -> bool:
    import time as _t
    cutoff = _t.time() - 86400
    _jobs_today[:] = [t for t in _jobs_today if t > cutoff]
    if len(_jobs_today) >= _MAX_JOBS_PER_DAY:
        return False
    _jobs_today.append(_t.time())
    return True


def _jobs_left() -> bool:
    """Peek at the cap without consuming a slot (the real consumption
    happens inside the job pipeline)."""
    import time as _t
    cutoff = _t.time() - 86400
    _jobs_today[:] = [t for t in _jobs_today if t > cutoff]
    return len(_jobs_today) < _MAX_JOBS_PER_DAY

_ALLOWED = {int(x) for x in os.environ.get("TELEGRAM_ALLOWED_USERS", "").replace(" ", "").split(",") if x}


def _ok(update: Update) -> bool:
    return not _ALLOWED or (update.effective_user and update.effective_user.id in _ALLOWED)


async def _run_blocking(fn, *a, **k):
    """Run a heavy sync job (dive/lesson/video) off the event loop."""
    return await asyncio.get_event_loop().run_in_executor(None, lambda: fn(*a, **k))


def _progress_sender(context, chat: int, every: float = 75.0):
    """A thread-safe on_progress callback that relays pipeline stages to
    the chat, throttled so a render sends a handful of updates, not one
    per frame. Answers 'is it working or hung?' without log-digging."""
    import time as _t
    loop = asyncio.get_event_loop()
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
    for attempt in (1, 2):
        try:
            with open(path, "rb") as f:
                await context.bot.send_video(
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
        "• /tonight — the programming director picks tonight's format "
        "and topic for you.\n"
        "• /surprise — a fresh, wild explainer.\n"
        "• Reply to any video with a question — the host answers you.\n"
        "• Send a voice memo instead of typing — I’ll transcribe it.\n"
        "• After a simulation: reply “branch <name>” to run a fork as "
        "its own episode.\n"
        "• /taste <note> — feedback that becomes a standing rule for "
        "every future script.\n"
        "• /feed and /play <n> — your library.\n\n"
        "Give me a few minutes per video — it’s researched, written, "
        "narrated and rendered."
    )


async def _make_lesson(update, context, topic: str):
    if not _job_allowed():
        await context.bot.send_message(
            update.effective_chat.id,
            f"Daily budget guard: {_MAX_JOBS_PER_DAY} jobs/day reached. "
            "Raise MAX_JOBS_PER_DAY in Render env if intentional.")
        return
    chat = update.effective_chat.id
    await context.bot.send_message(chat, f"Building your lesson on: {topic}\n(a few minutes…)")
    _pending_write("lesson", topic, chat)

    async def _send_doc_early(doc_path):
        # The research is the expensive part — deliver it the moment it exists,
        # so a later video failure never wastes what was already paid for.
        # Render to a typeset PDF (raw .md shows as unformatted text on phones).
        send_path = doc_path
        try:
            from .docrender import md_to_pdf
            send_path = await _run_blocking(md_to_pdf, doc_path)
        except Exception:
            log.exception("pdf render failed; sending raw md")
        with open(send_path, "rb") as f:
            await context.bot.send_document(
                chat_id=chat, document=f, filename=send_path.name,
                caption="cheat-sheet (video rendering…)", **_SEND_KW)

    loop = asyncio.get_event_loop()

    def _on_doc(doc_path):
        _pending_write("lesson", topic, chat, doc=str(doc_path))
        asyncio.run_coroutine_threadsafe(_send_doc_early(doc_path), loop)

    try:
        r = await _run_blocking(_lesson.build_lesson, topic,
                                _progress_sender(context, chat), _on_doc)
    except Exception as e:  # pragma: no cover
        log.exception("lesson failed")
        await context.bot.send_message(
            chat, f"That one failed: {type(e).__name__}: {e}"
        )
        _pending_clear()
        return
    _pending_clear()
    tag = "" if r["voiced"] else " (silent — no TTS on this host)"
    await _deliver_video(context, chat, r["video"], f"\U0001f393 {r['title']}{tag}")


async def _make_show(update, context, topic: str, builder, *,
                     opening: str, doc_subtitle: str, doc_caption: str,
                     emoji: str, kind: str = "show"):
    """Shared runner for the doc+video formats (debate, simulation): job
    guard, early PDF delivery of the paper half, then the video."""
    if not _job_allowed():
        await context.bot.send_message(
            update.effective_chat.id,
            f"Daily budget guard: {_MAX_JOBS_PER_DAY} jobs/day reached. "
            "Raise MAX_JOBS_PER_DAY in Render env if intentional.")
        return
    chat = update.effective_chat.id
    await context.bot.send_message(chat, f"{opening}: {topic}\n(a few minutes…)")
    _pending_write(kind, topic, chat)

    async def _send_doc_early(doc_path):
        # Same doctrine as lessons: the research is the expensive part, so
        # the paper half ships the moment it exists.
        send_path = doc_path
        try:
            from .docrender import md_to_pdf
            send_path = await _run_blocking(md_to_pdf, doc_path, doc_subtitle)
        except Exception:
            log.exception("pdf render failed; sending raw md")
        with open(send_path, "rb") as f:
            await context.bot.send_document(
                chat_id=chat, document=f, filename=send_path.name,
                caption=doc_caption, **_SEND_KW)

    loop = asyncio.get_event_loop()

    def _on_doc(doc_path):
        _pending_write(kind, topic, chat, doc=str(doc_path))
        asyncio.run_coroutine_threadsafe(_send_doc_early(doc_path), loop)

    try:
        r = await _run_blocking(builder, topic,
                                _progress_sender(context, chat), _on_doc)
    except Exception as e:  # pragma: no cover
        log.exception("%s failed", opening)
        await context.bot.send_message(
            chat, f"That one failed: {type(e).__name__}: {e}")
        _pending_clear()
        return
    _pending_clear()
    tag = "" if r["voiced"] else " (silent — no TTS on this host)"
    await _deliver_video(context, chat, r["path"], f"{emoji} {r['title']}{tag}")
    return r


async def _make_debate(update, context, topic: str):
    await _make_show(
        update, context, topic, _debate.build_debate,
        opening="Setting up the debate",
        doc_subtitle="Agent Forge debate brief",
        doc_caption="debate brief (the hosts are warming up…)",
        emoji="\U0001f94a", kind="debate")


async def _make_sim(update, context, scenario: str):
    r = await _make_show(
        update, context, scenario, _sim.build_sim,
        opening="Running the simulation",
        doc_subtitle="Agent Forge scenario dossier",
        doc_caption="scenario dossier (playback rendering…)",
        emoji="\U0001f52e", kind="sim")
    if r and r.get("doc"):
        _LAST_SIM[update.effective_chat.id] = str(r["doc"])
        await context.bot.send_message(
            update.effective_chat.id,
            "🔀 This run followed the mainline. Reply “branch <name or "
            "letter>” (from the dossier's branch points) and I'll run "
            "that fork as its own episode.")


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


async def _answer_reply(update, context, question: str):
    """The viewer replied to a delivered video/cheat-sheet with a question:
    answer as the host — text plus a voice note. Cheap (one text call + TTS),
    so it doesn't count against the daily job cap."""
    chat = update.effective_chat.id
    target = update.message.reply_to_message
    caption = target.caption or target.text or ""
    doc = _find_doc_for(caption)
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
        await _make_debate(update, context, txt[len("debate"):].strip(" :—-"))
        return
    if low.startswith(("story", "case:")):
        case = (txt[len("story"):] if low.startswith("story")
                else txt.split(":", 1)[1]).strip(" :—-")
        if case.lower() in ("", "surprise", "me", "surprise me", "time"):
            await _discover_story(update, context)
        else:
            await _make_story(update, context, case)
        return
    if low.startswith("simulate"):
        await _make_sim(update, context, txt[len("simulate"):].strip(" :—-"))
        return
    if low.startswith("what if"):
        await _make_sim(update, context, txt)
        return
    topic = txt[len("teach me"):].strip(" :—-") if low.startswith("teach me") else txt
    await _make_lesson(update, context, topic)


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


async def _make_story(update, context, case: str):
    await _make_show(
        update, context, case, _story.build_story,
        opening="Opening the case file",
        doc_subtitle="Agent Forge case file",
        doc_caption="case file (the episode is rendering…)",
        emoji="\U0001f56f️", kind="story")


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
        chat, "🔧 Rendering the pipeline check (~2 min, no API spend)…")
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
    head = key[:14] + "…" if key else "(missing)"
    await context.bot.send_message(
        chat, f"key: {head} len={len(key)}\ntesting a live call…")

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
    """Runs inside the bot's event loop — safe to schedule background tasks."""
    asyncio.get_event_loop().run_in_executor(None, _selfcheck)
    # A restart (deploy, OOM, crash) kills any in-flight job — announce
    # it, then RESUME the job from its persisted state.
    if not _pending_path().exists():
        for uid in _ALLOWED:
            try:
                await app.bot.send_message(
                    uid, "⚡ Worker restarted (deploy). Ready.")
            except Exception:
                log.warning("restart notice to %s failed", uid)
    else:
        asyncio.create_task(_resume_job(app))


async def _resume_job(app: Application):
    """Pick up the job a restart killed. If the doc (the expensive
    research half) exists, only the video half re-runs."""
    import json
    try:
        job = json.loads(_pending_path().read_text())
    except Exception:
        _pending_clear()
        return
    _pending_clear()      # cleared up front so a crash here can't loop
    chat, kind = job.get("chat"), job.get("kind", "")
    topic, doc = job.get("topic", ""), job.get("doc")
    if not chat:
        return
    if not doc or not Path(doc).exists():
        await app.bot.send_message(
            chat, f"⚡ A restart killed “{topic}” before research "
                  "finished — send it again.")
        return
    # never resume a malformed doc (e.g. the model asked a question back
    # instead of researching) — that renders garbage on a loop
    import re as _re
    try:
        _txt = Path(doc).read_text(encoding="utf-8")
    except Exception:
        _txt = ""
    if (not _re.search(r"^#\s+.+$", _txt, _re.M)
            or _txt.count("##") < 3 or len(_txt) < 1200):
        await app.bot.send_message(
            chat, f"⚡ A restart killed “{topic or 'a job'}”, and its "
                  "research looks malformed — not resuming it. Send the "
                  "request again.")
        return
    await app.bot.send_message(
        chat, f"♻️ Restart killed the render of “{topic}” — resuming it "
              "now (the research is already done).")
    say = _progress_sender(app, chat)
    try:
        if kind == "lesson":
            r = await _run_blocking(
                _video.build_video, doc, say,
                _lesson._LESSON_VIDEO_SYSTEM, "THE LESSON")
            title = topic
        elif kind == "debate":
            r = await _run_blocking(_debate.video_from_brief, doc, say)
            title = r["title"]
        elif kind == "sim":
            r = await _run_blocking(_sim.video_from_dossier, doc, say)
            title = r["title"]
            _LAST_SIM[chat] = str(doc)
        elif kind == "story":
            r = await _run_blocking(_story.video_from_casefile, doc, say)
            title = r["title"]
        else:
            return
        emoji = {"lesson": "\U0001f393", "debate": "\U0001f94a",
                 "sim": "\U0001f52e", "story": "\U0001f56f️"}.get(
                     kind, "\U0001f3ac")
        await _deliver_video(app, chat, r["path"], f"{emoji} {title}")
    except Exception as e:
        log.exception("resume failed")
        await app.bot.send_message(
            chat, f"Resume failed: {type(e).__name__}: {e} — send the "
                  "request again.")
    every = int(os.environ.get("RESTOCK_EVERY", "0"))
    if every and _ALLOWED:
        asyncio.create_task(_restock_loop(app))
    if os.environ.get("FORGE_DAILY_HOUR", "").strip() and _ALLOWED:
        asyncio.create_task(_daily_loop(app))


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
    full pipeline runs exactly as if the viewer had asked."""
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

    app = Application.builder().token(token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("teach", cmd_teach))
    app.add_handler(CommandHandler("debate", cmd_debate))
    app.add_handler(CommandHandler("simulate", cmd_simulate))
    app.add_handler(CommandHandler("taste", cmd_taste))
    app.add_handler(CommandHandler("story", cmd_story))
    app.add_handler(CommandHandler("tonight", cmd_tonight))
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("surprise", cmd_surprise))
    app.add_handler(CommandHandler("diag", cmd_diag))
    app.add_handler(CommandHandler("feed", cmd_feed))
    app.add_handler(CommandHandler("play", cmd_play))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    log.info("learning-feed worker up; auto-feed every %ss",
             os.environ.get("RESTOCK_EVERY", "0"))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
