"""The audience of one — a taste profile that tunes every script.

Two standing context blocks get appended to every script-writing prompt:
- TASTE: the viewer's accumulated feedback notes ("hooks were weak",
  "loved the worked scenario") — the channel learns THIS viewer's
  standards, not a generic audience's.
- CONTINUITY: recent episode titles, so scripts can call back to earlier
  episodes like a real show with a real (one-person) audience.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .explorer import EXPLORATIONS_DIR, load_journal

TASTE_FILE = EXPLORATIONS_DIR / "taste.md"


def add(note: str) -> None:
    EXPLORATIONS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(TASTE_FILE, "a", encoding="utf-8") as f:
        f.write(f"- ({stamp}) {note.strip()}\n")


def _taste() -> str:
    try:
        txt = TASTE_FILE.read_text(encoding="utf-8").strip()
        # keep the most recent notes if the file grows long
        lines = [l for l in txt.splitlines() if l.strip()]
        return "\n".join(lines[-25:])
    except Exception:
        return ""


def _recent_titles(n: int = 8) -> list[str]:
    try:
        entries = load_journal()
        return [e.get("title") or e.get("topic", "") for e in entries[-n:]
                if (e.get("title") or e.get("topic"))]
    except Exception:
        return []


def context() -> str:
    """The standing block appended to script prompts."""
    parts = []
    t = _taste()
    if t:
        parts.append(
            "VIEWER TASTE PROFILE — this channel has an audience of ONE, "
            "and these are their standing notes from past episodes. "
            "Treat them as directives:\n" + t)
    titles = _recent_titles()
    if titles:
        parts.append(
            "CONTINUITY — recent episodes on this channel: "
            + "; ".join(titles[:8])
            + ". Call back to one when it genuinely connects (a shared "
            "trap, a contrast, a running theme) — never force it.")
    return ("\n\n" + "\n\n".join(parts)) if parts else ""
