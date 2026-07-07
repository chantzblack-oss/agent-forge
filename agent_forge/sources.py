"""Source-driven discovery — find real, fresh, diverse topics worth diving.

Raw HTTP to HN/arXiv/Reddit/Wikipedia is blocked by the sandbox proxy, so
discovery runs through the Claude CLI's live web search instead (the same
channel the dive scout uses). We task a web-searching agent to go pull the
most fascinating things actually being discussed right now across a wide
spread of sources, then return them as structured candidates.

The point: topics come from the real world, not an LLM's stale guess at
"what's interesting" — which is what made the first feed samey.
"""

from __future__ import annotations

import json
import re

from .providers import get_provider

_DISCOVERY_SYSTEM = (
    "You are a scout for a personal exploration feed — think of yourself as "
    "an obsessive curator who reads everything and surfaces the gems. USE "
    "WEB SEARCH aggressively; do not work from memory. Go find what is "
    "genuinely fascinating and being discussed RIGHT NOW across a wide "
    "spread of sources:\n"
    "  • Science/tech frontier — Hacker News front page, arXiv, Ars "
    "Technica, Quanta: new findings, weird tech, big arguments.\n"
    "  • History & the human — AskHistorians threads, Wikipedia featured / "
    "on-this-day, forgotten dramatic events.\n"
    "  • Mysteries & the strange — unsolved questions, strange phenomena, "
    "surprising r/science results, 'wait, that's REAL?' material.\n\n"
    "Selection bar (strict):\n"
    "- Each pick must pass the obscurity test: NOT something a mainstream "
    "explainer has already done to death.\n"
    "- NO clickbait framing: no manufactured shock, no 'scientists HATE "
    "this', no overselling. The substance must carry the hook.\n"
    "- Maximize DIVERSITY across the batch — no two picks from the same "
    "field; span science, history, tech, nature, human behavior, the weird.\n"
    "- Prefer concrete mechanisms, real stories with stakes, genuine "
    "mysteries — never vague topics.\n"
    "- Each must have a real hook that makes someone go 'wait, WHAT?'.\n\n"
    "COVERAGE CHECK (this decides how the topic is used, so do it "
    "honestly): for each candidate, search for existing high-quality FREE "
    "coverage — a genuinely excellent YouTube video, documentary, or "
    "long-form article on this exact topic. If one exists, set "
    "best_existing to {url, title, creator, why} — recommending the best "
    "existing thing is a WIN, not a failure. Only set best_existing to "
    "null when coverage is genuinely absent, dry (papers only), or "
    "misses the fascinating angle."
)


def _discovery_user(n: int, avoid: list[str]) -> str:
    seen = "\n".join(f"- {t}" for t in avoid[-60:]) or "(nothing yet)"
    return (
        f"Find {n} exploration candidates now, via live search. Already "
        f"covered (do NOT repeat or pick anything close):\n{seen}\n\n"
        "Return ONLY a JSON array, no prose. Each element:\n"
        '{"title": "punchy 2-5 word title", '
        '"topic": "one full sentence framing the dive, concrete and '
        'specific enough to research", '
        '"hook": "one sentence on why it makes you go wait WHAT", '
        '"field": "the domain, for diversity checking", '
        '"source": "where you found it", '
        '"best_existing": null or {"url": "...", "title": "...", '
        '"creator": "...", "why": "one line on why it is worth the click"}}'
    )


def discover(n: int = 10, avoid: list[str] | None = None) -> list[dict]:
    """Web-search for n fresh, diverse candidate topics. Returns dicts."""
    raw = get_provider("anthropic").complete(
        system=_DISCOVERY_SYSTEM,
        user=_discovery_user(n, avoid or []),
        model="opus",
        max_tokens=3000,
    )
    return _parse(raw)


def _parse(raw: str) -> list[dict]:
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return []
    try:
        items = json.loads(m.group(0))
    except Exception:
        return []
    out = []
    for it in items:
        if isinstance(it, dict) and it.get("topic"):
            best = it.get("best_existing")
            if not (isinstance(best, dict) and best.get("url")):
                best = None
            out.append({
                "title": it.get("title", "").strip(),
                "topic": it.get("topic", "").strip(),
                "hook": it.get("hook", "").strip(),
                "field": it.get("field", "").strip(),
                "source": it.get("source", "").strip(),
                "best_existing": best,
            })
    return out
