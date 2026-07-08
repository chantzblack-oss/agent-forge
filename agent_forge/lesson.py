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
    "APIs, facts, and studies CURRENT and CORRECT — never invent a step or "
    "a finding you're unsure of; verify it.\n\n"
    "THE BAR: the learner has already read the generic advice and found it "
    "useless. If a sentence could appear in any listicle on this topic, "
    "CUT IT. Every claim carries a number, a named study or researcher, a "
    "named technique, or a mechanism. Kill at least one popular myth about "
    "the topic, by name. Take positions — 'do X, not Y, because Z' — "
    "instead of surveying options. Prefer the counterintuitive finding "
    "that's true over the obvious one that's polite. Concrete protocols "
    "with quantities, schedules, and exact phrasings — never 'consider "
    "reflecting on your values', always the actual exercise with the "
    "actual numbers.\n\n"
    "Produce a lesson document in markdown:\n"
    "# <clear lesson title>\n"
    "## The mental model\n"
    "  3-5 short paragraphs: how this actually works and why it's shaped "
    "that way — the intuition a beginner is missing. Concrete analogies, "
    "real research where it exists.\n"
    "Then 3-5 MORE sections YOU choose to fit the topic — pick what this "
    "subject actually needs, e.g. for tech/build skills: prerequisites, "
    "the exact steps (commands/code in fenced blocks, copy-paste ready), "
    "traps; for judgment/life skills: the evidence (what studies actually "
    "found, with names), the protocols (numbered, concrete, schedulable), "
    "the diagnostics (how to tell which failure mode is yours), the traps "
    "(what most advice gets wrong). Never force a section that doesn't "
    "fit.\n"
    "Always end with EXACTLY these two:\n"
    "## Cheat sheet\n"
    "  the compressed reference as a TABLE — the protocols/commands/"
    "numbers only, so the learner can execute from this section alone.\n"
    "## Go deeper\n"
    "  5-8 real, high-quality sources found via your web search THIS "
    "turn — never invented. Mix formats: articles/docs, a paper or "
    "primary source, and 1-2 videos where they exist. Markdown links "
    "with a real URL each, plus a half-line on why it's worth the "
    "click. Omit rather than fabricate.\n\n"
    "Be specific and honest. If something is genuinely contested, say so "
    "and say which side the evidence currently favors.\n\n"
    "MAKE IT VISUAL — this renders to a designed PDF:\n"
    "- Use a markdown TABLE wherever it beats prose (the cheat sheet "
    "itself, tool comparisons, dosage/settings/numbers).\n"
    "- Include 1-2 inline SVG diagrams for the core mental model (a "
    "labeled flow, an anatomy, a before/after). Raw <svg> in the "
    "markdown, viewBox='0 0 800 400', LIGHT theme palette: ink #1d3038, "
    "accent #ff7a5e, accent2 #0e8ea3, muted #6b8893; text >= 20px; no "
    "background rect.\n"
    "- Bold the load-bearing numbers and commands."
)


_LESSON_VIDEO_SYSTEM = (
    "You are a director making the COMPANION video to a written lesson the "
    "learner already has in hand. HARD RULE: do not restate the document. "
    "The learner just read it — a video that summarizes it is a wasted "
    "artifact. Your job is everything a reference document can't do.\n"
    "DESIGN THE STRUCTURE FOR THIS TOPIC — there is no fixed formula. "
    "Choose from these moves (and invent your own) based on what THIS "
    "skill actually needs to click:\n"
    "  - THE WHY: a story, stake, or surprising fact that makes the skill "
    "worth having (material NOT in the doc; draw on what you know beyond it)\n"
    "  - INTUITION: the mental model via fresh analogies the doc didn't use\n"
    "  - WORKED SCENARIO: a concrete character playing the skill out "
    "end-to-end with real numbers and decisions\n"
    "  - TRAPS AS STORIES: a top mistake dramatized as a mini-vignette, "
    "not a bullet warning\n"
    "  - MYTH KILL, HISTORY BEAT, 'WHAT THE PROS SEE', BEFORE/AFTER — "
    "whatever fits\n"
    "A hands-on skill probably wants a long worked scenario; a conceptual "
    "topic wants intuition and history; a high-stakes one wants traps. "
    "Weight accordingly. Close with one line: the exact steps are in your "
    "cheat-sheet.\n"
    "Never walk the doc's step list. Never repeat its phrasing. If a scene "
    "would work as a paragraph of the doc, cut it. EVERY scene must hand "
    "the viewer something NEW — a specific fact, number, name, or image "
    "they didn't have a scene ago; pure restatement or transition beats "
    "get cut. Return 9-16 scenes — "
    "as many as the material earns, no padding. Vary the rhythm: a "
    "one-sentence punch scene is allowed between longer beats.\n"
    "PICK A VOICE that fits the skill and commit: playful and funny for "
    "everyday skills (self-deprecating, a running gag about how everyone "
    "gets this wrong), calm and steady for high-stakes ones (money, "
    "safety, health), hype for genuinely exciting ones. Real wit only — "
    "irony and understatement, never forced jokes. Sound like a friend "
    "who's great at this and actually wants you to win, not a narrator. "
    "Punchy verbs, surprising-but-precise comparisons, second person; "
    "ask the viewer a hard question now and then, or give a flat "
    "command; vary the sentence music — one clean punch here, a quick "
    "triplet there. Never sound like someone reading slides.\n\n"
    "Each scene: {kicker (2-4 words), headline (<=7 words, on-screen), "
    "narration (1-3 spoken sentences, HARD MAX 40 words — split big "
    "ideas into more scenes — in the video's chosen voice; engineer "
    "pacing with punctuation: em-dashes for pivots, ellipses for "
    "hesitation, short sentences for punch — the narrator performs it; "
    "no markdown — written like a person actually talks: contractions, short "
    "sentences, concrete verbs; BANNED: the \"That's not X. That's Y.\" "
    "pattern, 'here's the thing/magic', rhetorical-question openers, and "
    "a punchline every scene — one aphorism per video, max), "
    "read (a short acting note for how this exact line should be "
    "delivered — 'slow on the number, let it sink in', 'deadpan, the "
    "absurdity does the work'), "
    "layout (the shot type: standard | punch | fullviz — 'punch' 2-4 "
    "times for the biggest one-liners as giant centered type: the hook, "
    "a shocking number, the closing line; 'fullviz' when the diagram is "
    "the story; all-'standard' feels like a slideshow), "
    "pose (the on-screen host's body language: explain | point | warn | "
    "celebrate | think | wave | none — 'point' when a diagram is up, 'warn' "
    "in the trap vignettes, 'celebrate' at the payoff, 'wave' to open/close), "
    "delivery (the narrator's read for this beat: neutral | bright | hype | "
    "grave | hushed — vary it with the material), "
    "data (PREFER over hand-drawn svg whenever the beat is numeric — the "
    "engine renders polished animated charts: {\"type\":\"bars\",\"title\","
    "\"unit\",\"items\":[{\"label\",\"value\"}..<=6]} | {\"type\":\"gauge\","
    "\"value\":0-100,\"label\"} | {\"type\":\"scale\",\"min_label\","
    "\"max_label\",\"value\":0-100,\"marker_label\"} | {\"type\":\"flow\","
    "\"steps\":[2-6 short steps]} for chains/processes), "
    "visual (optional inline SVG diagram on a SINGLE line — JSON strings cannot contain raw newlines — viewBox='0 0 880 700', no external "
    "refs/scripts; palette ink #eaf3f2 accent #ff7a5e accent2 #35c2d6 muted "
    "#5d7a84, text >= 26px and ALWAYS filled with a light palette color, "
    "never dark; the svg sits on the video's dark background — "
    "NO background rect or light fill behind the diagram; keep every "
    "label outside the shape it names or sized to fit with room to spare, "
    "never touching a shape edge)}. Lessons NEED diagrams — draw the "
    "actual structure being taught (graphs with labeled nodes and arrows, "
    "before/after states, flows); aim for a visual on most scenes.\n"
    "Return ONLY a JSON array."
)


def build_lesson(topic: str, on_progress=None, on_doc=None) -> dict:
    """Research a skill/topic, write a cheat-sheet doc, and render a video."""
    say = on_progress or (lambda _m: None)

    say("researching the lesson…")
    doc = get_provider("anthropic").complete(
        system=_LESSON_SYSTEM, user=f"Teach me: {topic}",
        model=WRITER_MODEL, max_tokens=6000,
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
