"""Deep mode — the definitive document, no video.

What a single chat with a model can't do, a pipeline can:
    scout -> parallel per-crux research -> ADVERSARIAL pass (attack the
    draft evidence, hunt disconfirming sources) -> synthesis by a writer
    with the full notes -> ruthless editor rewrite -> typeset PDF.

The output is a dossier that goes deeper than any one-pass answer:
positions with confidence levels, evidence graded by source quality,
the strongest case AGAINST its own conclusions, and what would change
the answer.
"""

from __future__ import annotations

import re
from pathlib import Path

from .providers import get_provider
from .explorer import EXPLORATIONS_DIR, WRITER_MODEL, _slugify
from . import research as _research


_COUNTER_SYSTEM = (
    "You are the adversarial reviewer on a research team. You receive "
    "the team's research notes on a question. Your ONLY job is to attack "
    "them: USE WEB SEARCH to hunt for disconfirming evidence, stronger "
    "counter-arguments, newer data, and reasons the load-bearing claims "
    "might be wrong or overstated. Name which specific claims survive "
    "your attack and which wobble. Dense notes with sources — you are "
    "the reason the final document can be trusted."
)

_WRITER_SYSTEM = (
    "You are writing the definitive dossier on a question — the document "
    "a serious person keeps and rereads, beyond what any one-pass answer "
    "could give. You have the research team's notes AND the adversarial "
    "reviewer's attack on them; weigh both honestly.\n\n"
    "THE BAR: every claim carries a number, a name, or a source. Where "
    "evidence is contested, show the contest and grade it. Take real "
    "positions with stated confidence ('~80% — here is what the 20% "
    "looks like'). If a sentence could appear in a generic blog post on "
    "this topic, cut it.\n\n"
    "STRUCTURE — adaptive to the question's type, but always:\n"
    "# <sharp title>\n"
    "## The verdict\n"
    "  the answer in 4-8 sentences, with confidence levels — readable "
    "alone.\n"
    "Then 4-7 sections YOU choose to fit the question (the mechanism, "
    "the evidence weighed side by side, the strongest case against this "
    "verdict, the history of how thinking evolved, the numbers that "
    "matter, who disagrees and why, practical implications). Always "
    "include somewhere: a section that steelmans the OPPOSITE of your "
    "verdict, and 'What would change this answer' — the concrete "
    "evidence or events that would move the verdict.\n"
    "Always end with:\n"
    "## Sources, annotated\n"
    "  8-14 real links from the research (never invented), each with a "
    "half-line on what it contributes and how much to trust it.\n\n"
    "MAKE IT VISUAL — this renders to a designed PDF:\n"
    "- TABLES wherever they beat prose (evidence weighed, options "
    "compared, numbers).\n"
    "- 2-3 inline SVG diagrams (the mechanism, the landscape of "
    "positions, a timeline). Raw <svg>, viewBox='0 0 800 400', LIGHT "
    "palette: ink #1d3038, accent #ff7a5e, accent2 #0e8ea3, muted "
    "#6b8893; text >= 20px; no background rect.\n"
    "- Blockquotes for the most striking findings. Bold the load-"
    "bearing numbers."
)

_EDITOR_SYSTEM = (
    "You are a ruthless editor at a serious publication. You receive a "
    "dossier draft. Rewrite it to its best self:\n"
    "- Cut every sentence that doesn't earn its place; tighten flab.\n"
    "- Sharpen hedges into positions with confidence levels; kill "
    "generic phrasing.\n"
    "- Verify the structure serves the question; merge weak sections.\n"
    "- Keep ALL real sources, tables, and svg diagrams (improve them "
    "where easy); never invent new facts or links.\n"
    "- Keep the same markdown format, starting with # title.\n"
    "Return ONLY the rewritten document."
)


def build_deep(question: str, on_progress=None) -> dict:
    """The full document pipeline. Returns {'title', 'doc'}."""
    say = on_progress or (lambda _m: None)
    provider = get_provider("anthropic")

    notes = _research.deep_research(question, say)

    say("adversarial pass — attacking the evidence…")
    counter = ""
    try:
        counter = provider.complete(
            system=_COUNTER_SYSTEM,
            user=f"The question: {question}\n\nThe team's notes:\n{notes[:20000]}",
            model=WRITER_MODEL, max_tokens=3000,
        ).strip()
    except Exception:
        pass

    say("writing the dossier…")
    from . import taste as _taste
    draft = provider.complete(
        system=_WRITER_SYSTEM + _taste.context(),
        user=(f"The question: {question}\n\nRESEARCH NOTES:\n{notes}"
              + (f"\n\nADVERSARIAL REVIEW:\n{counter}" if counter else "")),
        model=WRITER_MODEL, max_tokens=12000,
    ).strip()

    say("editor pass…")
    try:
        edited = provider.complete(
            system=_EDITOR_SYSTEM, user=draft,
            model=WRITER_MODEL, max_tokens=12000,
        ).strip()
        if edited.startswith("#") and len(edited) > len(draft) * 0.5:
            draft = edited
    except Exception:
        pass

    from .docrender import clean_markdown
    draft = clean_markdown(draft)
    m = re.search(r"^#\s+(.+)$", draft, re.M)
    if not m or draft.count("##") < 4 or len(draft) < 2500:
        raise RuntimeError("the dossier came back malformed — try "
                           "rephrasing the question")
    title = m.group(1).strip()
    slug = _slugify(title)
    EXPLORATIONS_DIR.mkdir(exist_ok=True)
    doc_path = EXPLORATIONS_DIR / f"{slug}.deep.md"
    doc_path.write_text(f"<!-- deep: {question} -->\n\n{draft}\n",
                        encoding="utf-8")
    return {"title": title, "doc": doc_path}
