"""Multi-pass research — depth a single search call can't reach.

One research call produces a good article. World-class depth needs the
shape of a research team: scout the territory, name the 3-4 cruxes that
actually decide the question, then run a focused search on EACH crux, and
hand the assembled notes to the document writer for synthesis.

Adds ~4 web-search model calls per document. FORGE_DEEP_RESEARCH=0
disables it.
"""

from __future__ import annotations

import os
import re

from .providers import get_provider
from .explorer import WRITER_MODEL

_SCOUT_SYSTEM = (
    "You are the scout on a research team. USE WEB SEARCH to map the "
    "territory of the question fast:\n"
    "1. 8-12 load-bearing facts — numbers, names, dates, findings — each "
    "with where it came from.\n"
    "2. The popular beliefs about this that are wrong or contested.\n"
    "3. Then the 3-4 CRUXES: the sub-questions that actually decide the "
    "answer. Each on its own line, starting exactly 'CRUX: '.\n"
    "Dense notes, not prose. No filler."
)

_CRUX_SYSTEM = (
    "You are a specialist researcher assigned ONE crux of a larger "
    "question. USE WEB SEARCH aggressively on this crux alone: the "
    "strongest evidence on each side, the key numbers, named studies/"
    "sources/experts, where the honest uncertainty lies, and the single "
    "best source to cite. Dense notes with attributions, not prose."
)


def enabled() -> bool:
    return os.environ.get("FORGE_DEEP_RESEARCH", "1") != "0"


def deep_research(question: str, on_progress=None) -> str:
    """Scout + per-crux deep dives. Returns assembled research notes."""
    say = on_progress or (lambda _m: None)
    provider = get_provider("anthropic")

    say("research: scouting the territory…")
    scout = provider.complete(
        system=_SCOUT_SYSTEM, user=question,
        model=WRITER_MODEL, max_tokens=2400,
    )
    cruxes = [c.strip() for c in
              re.findall(r"^\s*CRUX:\s*(.+)$", scout, re.M)][:4]
    notes = [f"## Scout notes\n{scout.strip()}"]
    if cruxes:
        say(f"research: {len(cruxes)} deep dives in parallel…")

        def _dive(crux: str) -> str | None:
            try:
                d = provider.complete(
                    system=_CRUX_SYSTEM,
                    user=f"The larger question: {question}\n\nYour crux: {crux}",
                    model=WRITER_MODEL, max_tokens=2400,
                )
                return f"## Crux: {crux}\n{d.strip()}"
            except Exception:
                return None
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as ex:
            notes += [n for n in ex.map(_dive, cruxes) if n]
    return "\n\n".join(notes)[:26000]


def notes_block(question: str, on_progress=None) -> str:
    """The suffix appended to a doc-writer's user prompt, or ''. """
    if not enabled():
        return ""
    try:
        notes = deep_research(question, on_progress)
    except Exception:
        return ""
    if not notes.strip():
        return ""
    return ("\n\nRESEARCH NOTES from your scout team (verify anything "
            "load-bearing before asserting it; the notes may be "
            "incomplete but they are a head start):\n" + notes)
