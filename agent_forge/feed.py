"""Feed — a YouTube-style feed of explorations you consume, not drive.

The idea: you never need an idea. A library of explorations is generated in
the background and kept stocked; the feed shows you what's ready; you tap a
number and the full piece plays as clean readable text. Your picks tune what
gets made next. Endless, zero-input, coherent — and all plain text, the one
thing that renders on any phone.

Pieces:
- library() — every ready exploration (from the journal), newest first.
- feed(n) — the browsable menu string: what's queued up for you to watch.
- play(i) — the full exploration text for feed row i (marks it watched).
- watched log lives in explorations/watched.json so the feed can show
  what's new and the restocker can avoid repeats.

The heavy lifting (generating explorations) is explorer.dive/queue; this
module is just the shelf and the remote control.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .explorer import EXPLORATIONS_DIR, load_journal

WATCHED_PATH = EXPLORATIONS_DIR / "watched.json"


def _watched() -> set[str]:
    if not WATCHED_PATH.exists():
        return set()
    try:
        return set(json.loads(WATCHED_PATH.read_text()))
    except Exception:
        return set()


def _mark_watched(file: str) -> None:
    seen = _watched()
    seen.add(file)
    WATCHED_PATH.write_text(json.dumps(sorted(seen), indent=2))


def library() -> list[dict]:
    """Ready explorations, newest first, each annotated watched/new."""
    seen = _watched()
    items = list(reversed(load_journal()))  # journal is oldest-first
    for it in items:
        it["watched"] = it.get("file") in seen
    return items


def _hook(entry: dict) -> str:
    """Pull a one-line hook: the exploration's own comment header, else tags."""
    f = EXPLORATIONS_DIR.parent / entry.get("file", "")
    try:
        first = f.read_text(encoding="utf-8").splitlines()[0]
        m = re.search(r"exploration:\s*(.+?)\s*(?:\||-->)", first)
        if m:
            hook = m.group(1)
            # keep it to a punchy clause
            return hook.split(" — ")[-1][:120] if " — " in hook else hook[:120]
    except Exception:
        pass
    return ", ".join(entry.get("tags", [])[:4])


def feed(n: int = 12) -> str:
    """Render the browsable feed menu."""
    items = library()[:n]
    if not items:
        return "  (feed is empty — the background restocker hasn't produced anything yet)"
    lines = ["  ▶ YOUR FEED\n"]
    for i, it in enumerate(items, 1):
        tag = "" if it["watched"] else "  •NEW"
        lines.append(f"  {i:>2}. {it.get('topic','?')}{tag}")
        lines.append(f"      {_hook(it)}")
    lines.append("\n  Reply with a number to play it.")
    return "\n".join(lines)


def play(i: int) -> dict:
    """Return the full exploration for feed row i and mark it watched."""
    items = library()
    if not 1 <= i <= len(items):
        raise IndexError(f"feed has {len(items)} items")
    entry = items[i - 1]
    path = EXPLORATIONS_DIR.parent / entry["file"]
    text = path.read_text(encoding="utf-8")
    # strip the HTML comment header line for clean reading
    text = re.sub(r"^<!--.*?-->\s*", "", text, flags=re.DOTALL)
    _mark_watched(entry.get("file", ""))
    return {"title": entry.get("topic", "?"), "text": text.strip(),
            "threads": entry.get("threads", [])}
