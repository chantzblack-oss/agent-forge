"""Agent Forge Telegram Bot — multi-agent deliberation from your phone.

Setup:
  1. Message @BotFather on Telegram, create a bot, get the token
  2. Export TELEGRAM_BOT_TOKEN=<your token>
  3. python -m agent_forge.telegram_bot

Commands:
  /start        — Welcome + instructions
  /ask <question> — Run Tri-Model deliberation
  /team         — Switch team (default: Tri-Model)
  /teams        — List available teams
  /status       — Check if a session is running
  /cancel       — Abort a running session
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path

# Load .env before anything else
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from . import TEAMS, Orchestrator
from .teams import TeamConfig, CATEGORIES

log = logging.getLogger("agent_forge.telegram")

# Authorized user IDs — set via TELEGRAM_ALLOWED_USERS (comma-separated)
_ALLOWED_USERS: set[int] = set()
_allowed_raw = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
if _allowed_raw:
    _ALLOWED_USERS = {int(x.strip()) for x in _allowed_raw.split(",") if x.strip()}

_DEFAULT_TEAM = "Polymath (Tri-Model)"

# Per-user state
_user_teams: dict[int, str] = {}
_user_sessions: dict[int, dict] = {}


def _get_team(user_id: int) -> TeamConfig:
    name = _user_teams.get(user_id, _DEFAULT_TEAM)
    return next((t for t in TEAMS if t.name == name), TEAMS[0])


def _is_authorized(user_id: int) -> bool:
    if not _ALLOWED_USERS:
        return True
    return user_id in _ALLOWED_USERS


async def _safe_edit(message, text: str) -> None:
    """Edit a message as plain text. Silently ignores 'not modified' errors."""
    try:
        await message.edit_text(text, parse_mode=None)
    except Exception:
        pass


# ── text cleaning ────────────────────────────────────────

_INTERNAL_TAGS = re.compile(
    r"\[COMPLETE\]|\[APPROVED\]|\[DONE\]|\[ERROR\]"
    r"|\[DIRECT\s+@\w+:[^\]]*\]"
    r"|\[NEED\s+@\w+[^\]]*\]"
)
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC = re.compile(r"(?<!\*)\*(.+?)\*(?!\*)")
_MD_HEADER = re.compile(r"^#{1,4}\s+", re.MULTILINE)
_MD_HR = re.compile(r"^-{3,}$", re.MULTILINE)
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_EVIDENCE_TAG = re.compile(r"\((Established|Emerging|Mechanistic|Speculative)\)")


def _clean(text: str) -> str:
    """Strip markdown and internal tags, return clean plain text for Telegram."""
    text = _INTERNAL_TAGS.sub("", text)
    text = _MD_BOLD.sub(r"\1", text)
    text = _MD_ITALIC.sub(r"\1", text)
    text = _MD_HEADER.sub("", text)
    text = _MD_HR.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _section(title: str, body: str) -> str:
    """Format a labeled section with a divider."""
    cleaned = _clean(body)
    if not cleaned:
        return ""
    return f"--- {title} ---\n{cleaned}"


# ── output formatting ────────────────────────────────────

def _format_for_telegram(transcript: list[dict], plain: dict | None, duration: float) -> str:
    parts: list[str] = []
    mins = int(duration // 60)
    secs = int(duration % 60)

    speakers = sorted(set(e["agent"] for e in transcript))
    parts.append(
        f"DELIBERATION COMPLETE\n"
        f"{mins}m {secs}s  /  {len(transcript)} turns\n"
        f"Team: {', '.join(speakers)}"
    )

    if plain:
        gist = plain.get("gist", "")
        example = plain.get("example", "")
        care = plain.get("care", "")
        sticky = plain.get("sticky", "")
        if gist:
            parts.append(_section("THE GIST", gist))
        if example:
            parts.append(_section("EXAMPLE", example))
        if care:
            parts.append(_section("WHY IT MATTERS", care))
        if sticky:
            parts.append(_section("REMEMBER", sticky))
    else:
        # Fall back to leader's final synthesis
        leader_entries = [
            e for e in transcript
            if e.get("role") == "leader" and "[COMPLETE]" in e.get("content", "")
        ]
        if leader_entries:
            content = leader_entries[-1]["content"]
            cleaned = _clean(content)

            # Try to extract the one-sentence answer
            answer_found = False
            for marker in ("One-sentence answer:", "one-sentence answer:"):
                if marker in cleaned:
                    after = cleaned.split(marker, 1)[1]
                    answer = after.split("\n\n")[0].strip()
                    parts.append(_section("ANSWER", answer))
                    rest = after.split("\n\n", 1)
                    if len(rest) > 1:
                        body = rest[1].strip()
                        if len(body) > 2500:
                            body = body[:2500] + "..."
                        parts.append(_section("DETAILS", body))
                    answer_found = True
                    break

            if not answer_found:
                if len(cleaned) > 3000:
                    cleaned = cleaned[:3000] + "..."
                parts.append(_section("SYNTHESIS", cleaned))

    # One-line highlight from each non-leader agent
    highlights: list[str] = []
    seen: set[str] = set()
    for entry in transcript:
        name = entry["agent"]
        if name in seen or entry.get("role") == "leader":
            continue
        seen.add(name)
        content = _clean(entry.get("content", ""))
        for line in content.split("\n"):
            line = line.strip()
            if len(line) > 30:
                if len(line) > 120:
                    line = line[:117] + "..."
                highlights.append(f"  {name}: {line}")
                break
    if highlights:
        parts.append("--- AGENT HIGHLIGHTS ---\n" + "\n".join(highlights))

    # Filter out empty sections
    return "\n\n".join(p for p in parts if p)


def _build_full_report(transcript: list[dict], goal: str, team: TeamConfig, duration: float) -> str:
    mins = int(duration // 60)
    secs = int(duration % 60)
    lines = [
        f"AGENT FORGE  —  {team.name}",
        f"Question: {goal}",
        f"Duration: {mins}m {secs}s",
        "",
        "=" * 60,
        "",
    ]
    current_round = 0
    for entry in transcript:
        r = entry.get("round", 0)
        if r != current_round:
            current_round = r
            lines.append(f"ROUND {r}")
            lines.append("-" * 40)
            lines.append("")
        lines.append(f"{entry['agent']}  ({entry['role']})")
        lines.append("")
        lines.append(_clean(entry.get("content", "")))
        lines.append("")
        lines.append("-" * 40)
        lines.append("")
    return "\n".join(lines)


def _run_session_sync(
    goal: str,
    team: TeamConfig,
    user_id: int,
    progress_callback,
) -> dict:
    from rich.console import Console

    orchestrator = Orchestrator(narrate_mode="off")
    orchestrator.console = Console(file=io.StringIO(), force_terminal=False)

    # Bypass all interactive prompts
    orchestrator._end_session = lambda *a, **kw: None
    orchestrator._between_rounds = lambda *a, **kw: "continue"

    session = {
        "status": "running",
        "turns": 0,
        "start": time.time(),
        "cancel": False,
        "timeline": [],
    }
    _user_sessions[user_id] = session

    original_post = orchestrator.__class__._post_agent

    def _tracking_post(self, resp, agent, round_num, is_final):
        if _user_sessions.get(user_id, {}).get("cancel"):
            return "complete"
        result = original_post(self, resp, agent, round_num, is_final)
        s = _user_sessions.get(user_id)
        if s:
            s["turns"] += 1
            s["last_agent"] = agent.name
            elapsed = int(time.time() - s["start"])
            # Build a one-line summary of what this agent said
            content = resp.message.content[:80].split("\n")[0]
            s["timeline"].append(f"{agent.name} ({agent.role}) — {elapsed}s")
            if progress_callback:
                try:
                    progress_callback(agent.name, agent.role, s["turns"], s["timeline"])
                except Exception:
                    pass
        return result

    orchestrator._post_agent = _tracking_post.__get__(orchestrator)

    try:
        orchestrator.run(goal=goal, team=team)
    except Exception as e:
        log.exception("Session error for user %s", user_id)
        _user_sessions[user_id] = {"status": "error", "error": str(e)}
        return {"error": str(e)}

    duration = time.time() - session["start"]
    plain = getattr(orchestrator, "_plain_translation", None)

    result = {
        "transcript": orchestrator._transcript,
        "plain": plain,
        "duration": duration,
        "goal": goal,
        "team": team,
    }
    _user_sessions[user_id] = {"status": "done"}
    return result


# ── Telegram handlers ──────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _is_authorized(user.id):
        await update.message.reply_text("Not authorized. Add your user ID to TELEGRAM_ALLOWED_USERS.")
        return
    await update.message.reply_text(
        "Agent Forge — Multi-model AI collaboration\n\n"
        "Send me any question and I'll run a full team deliberation "
        "(Claude + Gemini + GPT working together).\n\n"
        "Commands:\n"
        "/ask <question> — Run a deliberation\n"
        "/team — Switch team\n"
        "/teams — List teams\n"
        "/status — Check running session\n"
        "/cancel — Abort running session\n\n"
        "Or just type a question directly.",
    )


async def cmd_teams(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update.effective_user.id):
        return
    current = _user_teams.get(update.effective_user.id, _DEFAULT_TEAM)
    lines = ["AVAILABLE TEAMS\n"]
    for cat in CATEGORIES:
        lines.append(f"{cat.icon} {cat.name}")
        for t in cat.teams:
            marker = " << active" if t.name == current else ""
            lines.append(f"  {t.icon} {t.name}{marker}")
            lines.append(f"      {t.description}")
        lines.append("")
    lines.append("Switch with: /team <name>")
    await update.message.reply_text("\n".join(lines))


async def cmd_team(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not _is_authorized(user_id):
        return
    args = " ".join(context.args) if context.args else ""
    if not args:
        current = _user_teams.get(user_id, _DEFAULT_TEAM)
        await update.message.reply_text(f"Current team: {current}\n\nUsage: /team Polymath (Tri-Model)")
        return
    match = next((t for t in TEAMS if args.lower() in t.name.lower()), None)
    if not match:
        await update.message.reply_text(f"No team matching '{args}'. Use /teams to see options.")
        return
    _user_teams[user_id] = match.name
    await update.message.reply_text(f"Switched to {match.name}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    session = _user_sessions.get(user_id)
    if not session or session.get("status") != "running":
        await update.message.reply_text("No active session.")
        return
    turns = session.get("turns", 0)
    elapsed = int(time.time() - session.get("start", time.time()))
    timeline = session.get("timeline", [])
    lines = [f"SESSION IN PROGRESS — {turns} turns, {elapsed}s\n"]
    for entry in timeline:
        lines.append(f"  > {entry}")
    if timeline:
        lines.append(f"\nNext agent thinking...")
    await update.message.reply_text("\n".join(lines))


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    session = _user_sessions.get(user_id)
    if not session or session.get("status") != "running":
        await update.message.reply_text("No active session to cancel.")
        return
    session["cancel"] = True
    await update.message.reply_text("Cancelling after current turn finishes...")


async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not _is_authorized(user_id):
        await update.message.reply_text("Not authorized.")
        return

    session = _user_sessions.get(user_id)
    if session and session.get("status") == "running":
        await update.message.reply_text("A session is already running. Use /status to check or /cancel to abort.")
        return

    question = update.message.text.strip()
    if question.startswith("/ask"):
        question = question[4:].strip()
    if not question:
        await update.message.reply_text("Send me a question to research.")
        return

    team = _get_team(user_id)
    agent_names = [a.name for a in team.agents]
    status_msg = await update.message.reply_text(
        f"STARTING: {team.name}\n"
        f"Team: {', '.join(agent_names)}\n\n"
        f"This usually takes 5-8 minutes.\n"
        f"Use /status to check progress or /cancel to abort.",
    )

    loop = asyncio.get_event_loop()

    def _progress(agent_name: str, agent_role: str, turn_count: int, timeline: list[str]):
        # Build a live progress view
        lines = [f"{team.name} — {turn_count} turns completed\n"]
        # Show timeline of who has spoken
        for entry in timeline:
            lines.append(f"  > {entry}")
        lines.append(f"\nNext agent thinking...")
        asyncio.run_coroutine_threadsafe(
            _safe_edit(status_msg, "\n".join(lines)),
            loop,
        )

    def _run():
        return _run_session_sync(question, team, user_id, _progress)

    result = await loop.run_in_executor(None, _run)

    if "error" in result:
        error_text = result["error"]
        if len(error_text) > 500:
            error_text = error_text[:500] + "..."
        await _safe_edit(status_msg, f"Error: {error_text}")
        return

    transcript = result["transcript"]
    if not transcript:
        await _safe_edit(status_msg, "Session completed but produced no output.")
        return

    plain = result.get("plain")
    duration = result["duration"]

    formatted = _format_for_telegram(transcript, plain, duration)
    if len(formatted) > 4000:
        formatted = formatted[:4000] + "..."

    await _safe_edit(status_msg, formatted)

    report = _build_full_report(transcript, question, team, duration)
    doc = io.BytesIO(report.encode("utf-8"))
    doc.name = "agent_forge_report.md"
    try:
        await update.message.reply_document(
            document=doc,
            caption="Full deliberation transcript",
        )
    except Exception as e:
        log.warning("Failed to send report document: %s", e)


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_question(update, context)


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled exception: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                f"Something went wrong: {context.error}"
            )
        except Exception:
            pass


# ── Main ───────────────────────────────────────────────────

def main() -> None:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN not set.")
        print("1. Message @BotFather on Telegram")
        print("2. Create a bot with /newbot")
        print("3. Export TELEGRAM_BOT_TOKEN=<token>")
        sys.exit(1)

    print("Agent Forge Telegram Bot starting...")
    print(f"   Authorized users: {'all' if not _ALLOWED_USERS else _ALLOWED_USERS}")
    print(f"   Default team: {_DEFAULT_TEAM}")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("teams", cmd_teams))
    app.add_handler(CommandHandler("team", cmd_team))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question))
    app.add_error_handler(_error_handler)

    print("   Bot ready. Polling for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
