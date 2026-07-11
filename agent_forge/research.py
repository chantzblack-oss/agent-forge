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


_GAP_SYSTEM = (
    "You are the research director. Read the team's notes on the "
    "question. Name the 2-4 most important follow-up questions that are "
    "STILL UNANSWERED — especially where the notes conflict, where a "
    "load-bearing claim has no source, or where an obvious angle was "
    "never searched. Each on its own line starting exactly 'FOLLOWUP: '. "
    "Nothing else."
)


def enabled() -> bool:
    return os.environ.get("FORGE_DEEP_RESEARCH", "1") != "0"


def deep_research(question: str, on_progress=None,
                  expansive: bool = False) -> str:
    """Scout + per-crux deep dives. `expansive` adds a SECOND wave: a
    research director reads wave one, names what's still unanswered, and
    the team dives again. Returns assembled research notes."""
    say = on_progress or (lambda _m: None)
    provider = get_provider("anthropic")
    dive_tokens = 3000 if expansive else 2400

    def _dive(crux: str) -> str | None:
        try:
            d = provider.complete(
                system=_CRUX_SYSTEM,
                user=f"The larger question: {question}\n\nYour crux: {crux}",
                model=WRITER_MODEL, max_tokens=dive_tokens,
            )
            return f"## Crux: {crux}\n{d.strip()}"
        except Exception:
            return None

    from concurrent.futures import ThreadPoolExecutor

    say("research: scouting the territory…")
    scout = provider.complete(
        system=_SCOUT_SYSTEM, user=question,
        model=WRITER_MODEL, max_tokens=2400,
    )
    cruxes = [c.strip() for c in
              re.findall(r"^\s*CRUX:\s*(.+)$", scout, re.M)]
    cruxes = cruxes[:6 if expansive else 4]
    notes = [f"## Scout notes\n{scout.strip()}"]
    if cruxes:
        say(f"research: {len(cruxes)} deep dives in parallel…")
        with ThreadPoolExecutor(max_workers=4) as ex:
            notes += [n for n in ex.map(_dive, cruxes) if n]

    if expansive and len(notes) > 1:
        # wave two: the director reads wave one and sends the team back
        say("research: the director maps what's still unanswered…")
        try:
            gaps = provider.complete(
                system=_GAP_SYSTEM,
                user="\n\n".join(notes)[:22000],
                model=WRITER_MODEL, max_tokens=1200,
            )
            follows = [f.strip() for f in
                       re.findall(r"^\s*FOLLOWUP:\s*(.+)$", gaps, re.M)][:4]
            if follows:
                say(f"research wave two: {len(follows)} follow-up dives…")
                with ThreadPoolExecutor(max_workers=4) as ex:
                    notes += [n for n in ex.map(_dive, follows) if n]
        except Exception:
            pass
    return "\n\n".join(notes)[:42000 if expansive else 26000]


def notes_block(question: str, on_progress=None) -> str:
    """The suffix appended to a doc-writer's user prompt, or ''. """
    if not enabled():
        return ""
    say = on_progress or (lambda _m: None)
    try:
        notes = deep_research(question, on_progress)
    except Exception:
        say("⚠️ deep research FAILED — doc will be single-pass")
        return ""
    if not notes.strip():
        say("⚠️ deep research returned nothing — doc will be single-pass")
        return ""
    say(f"research notes ready: {len(notes) // 1000}k chars, "
        f"{notes.count('## Crux')} crux dives")
    return ("\n\nRESEARCH NOTES from your scout team (verify anything "
            "load-bearing before asserting it; the notes may be "
            "incomplete but they are a head start):\n" + notes)
