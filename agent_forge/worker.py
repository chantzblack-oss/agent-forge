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

log = logging.getLogger("agent_forge.worker")

_ALLOWED = {int(x) for x in os.environ.get("TELEGRAM_ALLOWED_USERS", "").replace(" ", "").split(",") if x}


def _ok(update: Update) -> bool:
    return not _ALLOWED or (update.effective_user and update.effective_user.id in _ALLOWED)


async def _run_blocking(fn, *a, **k):
    """Run a heavy sync job (dive/lesson/video) off the event loop."""
    return await asyncio.get_event_loop().run_in_executor(None, lambda: fn(*a, **k))


async def _deliver_video(context, chat_id, path: Path, caption: str, doc: Path | None = None):
    with open(path, "rb") as f:
        await context.bot.send_video(chat_id=chat_id, video=f, caption=caption[:1024],
                                     supports_streaming=True)
    if doc and doc.exists():
        with open(doc, "rb") as f:
            await context.bot.send_document(chat_id=chat_id, document=f,
                                            filename=doc.name, caption="cheat-sheet")


# ── commands ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    await update.message.reply_text(
        "This is your learning channel.\n\n"
        "• Send “teach me <anything>” — I’ll make a narrated lesson "
        "video + a cheat-sheet.\n"
        "• /surprise — a fresh, wild explainer.\n"
        "• /feed and /play <n> — your library.\n\n"
        "Give me a minute per video — it’s researched, written, "
        "narrated and rendered."
    )


async def _make_lesson(update, context, topic: str):
    chat = update.effective_chat.id
    await context.bot.send_message(chat, f"Building your lesson on: {topic}\n(a few minutes…)")
    last_err = None
    for attempt in range(3):
        try:
            r = await _run_blocking(_lesson.build_lesson, topic)
            break
        except Exception as e:  # pragma: no cover
            last_err = e
            log.exception("lesson attempt %d failed", attempt + 1)
            await asyncio.sleep(5 * (attempt + 1))
    else:
        await context.bot.send_message(
            chat, f"That one failed after 3 tries: {type(last_err).__name__}: {last_err}"
        )
        return
    tag = "" if r["voiced"] else " (silent — no TTS on this host)"
    await _deliver_video(context, chat, r["video"],
                         f"\U0001f393 {r['title']}{tag}", doc=r["doc"])


async def cmd_teach(update, context):
    if not _ok(update):
        return
    topic = " ".join(context.args) if context.args else ""
    if not topic:
        await update.message.reply_text("Say: teach me <topic>")
        return
    await _make_lesson(update, context, topic)


async def on_text(update, context):
    if not _ok(update):
        return
    txt = (update.message.text or "").strip()
    topic = txt[len("teach me"):].strip(" :—-") if txt.lower().startswith("teach me") else txt
    await _make_lesson(update, context, topic)


async def cmd_surprise(update, context):
    if not _ok(update):
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
            return f"✅ WORKS — reply: {out[:60]}"
        except Exception as e:
            return f"❌ {type(e).__name__}: {str(e)[:600]}"

    result = await _run_blocking(_test)
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
    every = int(os.environ.get("RESTOCK_EVERY", "0"))
    if every and _ALLOWED:
        asyncio.create_task(_restock_loop(app))


async def _restock_loop(app: Application):
    every = int(os.environ.get("RESTOCK_EVERY", "0"))
    if not every or not _ALLOWED:
        return
    await asyncio.sleep(30)
    while True:
        try:
            avoid = [e.get("topic", "") for e in _explorer.load_journal()]
            cands = await _run_blocking(_sources.discover, 3, avoid)
            if cands:
                dive = await _run_blocking(_explorer.dive, cands[0]["topic"])
                vid = await _run_blocking(_video.build_video, dive["path"])
                for uid in _ALLOWED:
                    await _deliver_video(app.bot, uid, vid["path"],
                                         f"\U0001f195 {dive['title']}")
        except Exception as e:  # pragma: no cover
            log.warning("restock failed: %s", e)
        await asyncio.sleep(every)


def _sanitize_env() -> None:
    """Strip stray whitespace/newlines that sneak in when secrets are pasted
    into dashboard forms (a leading \\n in an API key makes every HTTP
    request die with 'Illegal header value')."""
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS",
              "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
              "FORGE_TTS_VOICE"):
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
    app.add_handler(CommandHandler("surprise", cmd_surprise))
    app.add_handler(CommandHandler("diag", cmd_diag))
    app.add_handler(CommandHandler("feed", cmd_feed))
    app.add_handler(CommandHandler("play", cmd_play))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("learning-feed worker up; auto-feed every %ss",
             os.environ.get("RESTOCK_EVERY", "0"))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
