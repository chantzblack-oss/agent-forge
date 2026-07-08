"""Lesson engine — "teach me X" becomes a video + a cheat-sheet.

Learning has two halves that want different media:
- The MENTAL MODEL — how the thing works, why it's shaped that way, the few
  ideas you need before you start, the traps. Video is great at this.
- The EXECUTION — the exact commands, code, steps you actually run. Video is
  terrible at this (you can't copy-paste from it). Text is great at this.

So a lesson is BOTH:
    build_lesson(topic) ->
        explorations/<slug>.lesson.md   (the cheat-sheet you execute from)
        explorations/<slug>.mp4         (the video that makes it click)

The doc is researched (web search on) so steps/commands are current and
correct, not hallucinated. The video is scripted from the doc but tuned to
teach the model and the plan, and to hand off to the cheat-sheet for the
actual doing.
"""

from __future__ import annotations

import re
from pathlib import Path

from .providers import get_provider
from .explorer import EXPLORATIONS_DIR, WRITER_MODEL, _slugify
from . import video as _video


_LESSON_SYSTEM = (
    "You are a rigorous, concrete teacher building a lesson on a skill or "
    "topic the learner asked for. USE WEB SEARCH to get steps, commands, "
    "APIs, and facts CURRENT and CORRECT — never invent a command or a step "
    "you're unsure of; verify it.\n\n"
    "Produce a lesson document in markdown with EXACTLY these sections:\n"
    "# <clear lesson title>\n"
    "## The mental model\n"
    "  3-5 short paragraphs: how this actually works and why it's shaped "
    "that way — the intuition a beginner is missing. Concrete analogies.\n"
    "## What you need first\n"
    "  the handful of prerequisite concepts/tools, one line each.\n"
    "## The steps\n"
    "  a numbered, do-this-then-that path. For build/tech topics include the "
    "ACTUAL commands or code in fenced blocks — copy-paste ready. For "
    "practical topics, concrete actions and exact phrasings.\n"
    "## Traps\n"
    "  the mistakes beginners make and how to avoid them, bullet each.\n"
    "## Cheat sheet\n"
    "  the compressed reference — the commands/steps/numbers only, so the "
    "learner can execute from this section alone.\n"
    "## Go deeper\n"
    "  5-8 real, high-quality sources to dig into, found via your web "
    "search THIS turn — never invented. Mix formats: articles/docs, a "
    "paper or primary source, and 1-2 videos (YouTube/conference talks) "
    "where they exist. Markdown links with a real URL each, plus a "
    "half-line on why it's worth the click. If search returns nothing for "
    "an item, omit it rather than fabricate a link.\n\n"
    "Be specific and honest. If something is genuinely contested or "
    "version-dependent, say so."
)


_LESSON_VIDEO_SYSTEM = (
    "You are a director making the COMPANION video to a written lesson the "
    "learner already has in hand. HARD RULE: do not restate the document. "
    "The learner just read it — a video that summarizes it is a wasted "
    "artifact. Your job is everything a reference document can't do:\n"
    "  1. THE WHY — open with the story, stakes, or surprising fact that "
    "makes this skill worth having (material NOT in the doc; draw on what "
    "you know beyond it).\n"
    "  2. INTUITION — build the mental model through fresh analogies and "
    "angles the doc didn't use; make it click, don't list it.\n"
    "  3. ONE WORKED SCENARIO — invent a concrete character/situation and "
    "play the skill out end-to-end with real numbers and decisions, like a "
    "case study the doc has no room for.\n"
    "  4. TRAPS AS STORIES — dramatize the top 2 mistakes as mini-vignettes "
    "(what it looks like when it goes wrong), not as bullet warnings.\n"
    "  5. Close with one line: the exact steps are in your cheat-sheet.\n"
    "Never walk the doc's step list. Never repeat its phrasing. If a scene "
    "would work as a paragraph of the doc, cut it. Return 9-12 scenes.\n\n"
    "Each scene: {kicker (2-4 words), headline (<=7 words, on-screen), "
    "narration (1-3 spoken sentences, warm and clear, no markdown), "
    "pose (the on-screen host's body language: explain | point | warn | "
    "celebrate | think | wave | none — 'point' when a diagram is up, 'warn' "
    "in the trap vignettes, 'celebrate' at the payoff, 'wave' to open/close), "
    "visual (optional inline SVG diagram on a SINGLE line — JSON strings cannot contain raw newlines — viewBox='0 0 880 700', no external "
    "refs/scripts; palette ink #eaf3f2 accent #ff7a5e accent2 #35c2d6 muted "
    "#5d7a84, text >= 26px)}. Lessons NEED diagrams — draw the actual "
    "structure being taught (graphs with labeled nodes and arrows, "
    "before/after states, flows); aim for a visual on most scenes.\n"
    "Arc: hook with why this matters or a myth to kill -> build the mental "
    "model one idea per scene -> the plan at a high level -> the biggest "
    "trap -> a closing 'now go do it, the steps are in your cheat-sheet'.\n"
    "Everything must match the lesson doc. Return ONLY a JSON array."
)


def build_lesson(topic: str, on_progress=None, on_doc=None) -> dict:
    """Research a skill/topic, write a cheat-sheet doc, and render a video."""
    say = on_progress or (lambda _m: None)

    say("researching the lesson…")
    doc = get_provider("anthropic").complete(
        system=_LESSON_SYSTEM, user=f"Teach me: {topic}",
        model=WRITER_MODEL, max_tokens=4000,
    ).strip()

    title = _video._first_h1 if False else None  # noqa (keep import graph simple)
    m = re.search(r"^#\s+(.+)$", doc, re.M)
    title = m.group(1).strip() if m else topic
    slug = _slugify(title)

    doc_path = EXPLORATIONS_DIR / f"{slug}.lesson.md"
    EXPLORATIONS_DIR.mkdir(exist_ok=True)
    doc_path.write_text(
        f"<!-- lesson: {topic} -->\n\n{doc}\n", encoding="utf-8"
    )

    if on_doc is not None:
        try:
            on_doc(doc_path)
        except Exception:
            pass

    say("rendering the lesson video…")
    vid = _video.build_video(
        doc_path, on_progress=say, script_system=_LESSON_VIDEO_SYSTEM
    )
    return {"title": title, "doc": doc_path, "video": vid["path"],
            "voiced": vid["voiced"], "scenes": vid["scenes"]}
