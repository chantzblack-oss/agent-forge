"""Debate engine — two hosts argue a topic from opposite corners.

A debate is a fundamentally different artifact from a lesson, so it gets a
fundamentally different document. A lesson teaches you to DO something
(mental model -> steps -> cheat sheet). A debate teaches you to DECIDE
something, so its paper half is a BRIEF:

    build_debate(topic) ->
        explorations/<slug>.debate.md   (the brief: both cases, the cruxes,
                                         what evidence would settle it)
        explorations/<slug>.debate.mp4  (two hosts arguing it out)

The brief is researched (web search on) and delivered the moment it exists;
the hosts then perform FROM the brief, so the video and the paper agree.
"""

from __future__ import annotations

import re
from pathlib import Path

from .providers import get_provider
from .explorer import EXPLORATIONS_DIR, WRITER_MODEL, _slugify
from . import video as _video
from . import research as _research


_BRIEF_SYSTEM = (
    "You are writing a decision brief on a contested question. USE WEB "
    "SEARCH to ground both sides in real facts, numbers, and named "
    "sources. STEELMAN both sides — write each case the way its smartest "
    "honest advocate would. Do not declare a winner.\n\n"
    "Produce a markdown document with EXACTLY these sections:\n"
    "# <the question, phrased sharply>\n"
    "## What's actually being asked\n"
    "  2-3 sentences: the real disagreement under the surface question, "
    "and why reasonable people split on it.\n"
    "## The case for\n"
    "  the strongest honest case for one side: 3-5 short paragraphs, "
    "each anchored on a fact, number, or example.\n"
    "## The case against\n"
    "  the same treatment for the other side — equally strong.\n"
    "## Where they actually disagree\n"
    "  the 2-4 cruxes: the underlying questions of fact or value that, "
    "once you answer them, decide the whole thing. Bullet each.\n"
    "## What would settle it\n"
    "  the evidence or events that would genuinely move each side. Be "
    "concrete: a study, a number, an outcome.\n"
    "## How to decide for yourself\n"
    "  not a verdict — a short guide: which crux matters most, what to "
    "read/watch first, what most people get wrong about the question.\n"
    "## Sources\n"
    "  5-8 real, high-quality sources found via your web search THIS "
    "turn — never invented. Cover BOTH sides. Markdown links with a real "
    "URL each plus a half-line on which side it informs and why it's "
    "worth the click. Omit rather than fabricate.\n\n"
    "Be specific and honest. Where the evidence is genuinely thin or "
    "contested, say so in place.\n\n"
    "MAKE IT VISUAL — this renders to a designed PDF:\n"
    "- Include a markdown TABLE pitting the two cases side by side "
    "(claim vs claim on each crux) — tables render beautifully.\n"
    "- Include 1-2 inline SVG diagrams where a picture argues better "
    "than a paragraph (a spectrum with both camps placed on it, a "
    "causal chain, a 2x2). Raw <svg> in the markdown, viewBox='0 0 800 "
    "400', LIGHT theme palette: ink #1d3038, accent #ff7a5e, accent2 "
    "#0e8ea3, muted #6b8893; text >= 20px; no background rect.\n"
    "- Bold the load-bearing numbers.\n"
    "- Use a blockquote for the single most striking fact on each side.\n"
    "- FORMATTING DISCIPLINE: every bullet on its OWN line starting '- ' (never inline ' - ' chains); blockquote callouts are for STRIKING FACTS — a number, a date, a record — never for quoting philosophy or prose."
)


_DEBATE_SCRIPT_SYSTEM = (
    "You are the showrunner of a two-host debate show rendered as a "
    "vertical video. You are handed a researched decision brief; the "
    "viewer also has it. Your job is to make its two cases COLLIDE — "
    "the brief argues on paper, the show argues out loud.\n"
    "Two stick-figure hosts share the screen:\n"
    "  HOST A (left, speaker 'a') — warm, quick, the believer. Argues "
    "the brief's 'case for'. Can be funny.\n"
    "  HOST B (right, speaker 'b') — dry, precise, the skeptic. Argues "
    "the 'case against'. Deadpan.\n"
    "Every fact and number must come from the brief; where it hedges, "
    "hedge. Build the fight around the brief's CRUXES — that's where "
    "the hosts should actually clash, concede, and dig in.\n"
    "14-20 scenes — as many as the material earns. speaker is 'a' or 'b' for a host's line; null ONLY "
    "for the cold-open framing scene and the final scene. Alternate "
    "naturally — rebuttals, concessions, one host finishing the other's "
    "point — not a mechanical a/b/a/b. Write it like the best podcast "
    "banter: each line grabs a specific word or number from the line "
    "before it and pushes on THAT; hosts concede small points to win "
    "big ones ('fine, granted — but'); one running gag surfaces 2-3 "
    "times and pays off at the end. Concrete imagery over abstraction — "
    "'you're soaked at 2am' beats 'in adverse conditions'. If a line "
    "could sit in either host's mouth, it isn't written yet. BANNED: "
    "the \"That's not X. That's Y.\" pattern, 'here's the thing', "
    "rhetorical-question openers, and any line that merely restates "
    "the brief instead of fighting about it.\n"
    "EVERY scene must hand the viewer something NEW — a specific fact, "
    "number, name, or image they didn't have a scene ago; a beat that "
    "only restates or transitions gets cut.\n"
    "DIAGRAM DENSITY: at least HALF the scenes carry a visual. Any "
    "number, comparison, timeline, or spatial idea gets drawn — a bar "
    "pair for a stat clash, a two-column scorecard as hosts trade "
    "points, a simple scene sketch for an anecdote.\n"
    "End: each host gets one closing line, then a neutral final scene "
    "that names the crux the viewer should chew on — and points them to "
    "the brief for the full cases.\n\n"
    "Each scene: {speaker ('a'|'b'|null), layout (standard | punch | "
    "fullviz — 'punch' 2-4 times for the biggest one-liners as giant "
    "centered type: the opening question, a kill shot, the final line; "
    "'fullviz' when the diagram is the story), kicker (2-4 words), headline "
    "(<=7 words, on-screen), narration (1-3 spoken sentences, HARD MAX "
    "40 words — split big ideas into more scenes; engineer pacing with "
    "punctuation — em-dashes for sharp pivots, ellipses for hesitation, "
    "a short sentence for a jab — the voices perform it), pose "
    "(explain | point | warn | celebrate | think | wave), delivery "
    "(neutral | bright | hype | grave | hushed), read (a short acting "
    "note for how this exact line should be delivered), photo (OPTIONAL "
    "Wikimedia search query for a REAL photograph when an actual person/"
    "place/event beats a diagram — specific proper nouns; 2-4 scenes per "
    "video), image (a cinematic shot description — a film still: "
    "subject, angle, lighting — painted by the engine as full-bleed "
    "scene art; use where neither photo nor chart fits so most scenes "
    "carry visual matter), data (PREFER "
    "over hand-drawn svg for numeric beats — engine-rendered animated "
    "charts: {\"type\":\"bars\",\"items\":[{\"label\",\"value\"}..]} | "
    "{\"type\":\"gauge\",\"value\":0-100,\"label\"} | {\"type\":\"scale\","
    "\"min_label\",\"max_label\",\"value\":0-100,\"marker_label\"} | "
    "{\"type\":\"flow\",\"steps\":[..]} — perfect for stat clashes and "
    "scorecards), visual (optional "
    "inline SVG on a SINGLE line — JSON strings cannot contain raw "
    "newlines — viewBox='0 0 880 700', no external refs/scripts, under "
    "900 characters; it sits on the video's dark background — NO backdrop "
    "rect; palette ink #eaf3f2 accent #ff7a5e accent2 #35c2d6 muted "
    "#5d7a84, text >= 26px and ALWAYS filled with a light palette "
    "color — dark fills vanish, labels clear of shape edges)}.\n"
    "Return ONLY a JSON array."
)


def build_debate(topic: str, on_progress=None, on_doc=None,
                 audio: bool = False) -> dict:
    """Research a decision brief, deliver it, then render the two-host
    debate video performed from it."""
    say = on_progress or (lambda _m: None)
    provider = get_provider("anthropic")

    say("researching both sides…")
    brief = provider.complete(
        system=_BRIEF_SYSTEM,
        user=f"The question: {topic}" + _research.notes_block(topic, say),
        model=WRITER_MODEL, max_tokens=6000,
    ).strip()
    from .docrender import clean_markdown
    brief = clean_markdown(brief)

    m = re.search(r"^#\s+(.+)$", brief, re.M)
    if not m or brief.count("##") < 4 or len(brief) < 1200:
        raise RuntimeError("brief came back malformed — try rephrasing "
                           "the question")
    title = m.group(1).strip()
    slug = _slugify(title)
    EXPLORATIONS_DIR.mkdir(exist_ok=True)
    doc_path = EXPLORATIONS_DIR / f"{slug}.debate.md"
    doc_path.write_text(f"<!-- debate: {topic} -->\n\n{brief}\n",
                        encoding="utf-8")

    if on_doc is not None:
        try:
            on_doc(doc_path)
        except Exception:
            pass
    return video_from_brief(doc_path, on_progress=say, audio=audio)


def video_from_brief(doc_path: str | Path, on_progress=None,
                     audio: bool = False) -> dict:
    """Script and render the debate video from an existing brief — also
    the resume path when a restart killed the render half."""
    say = on_progress or (lambda _m: None)
    provider = get_provider("anthropic")
    doc_path = Path(doc_path)
    brief = re.sub(r"^<!--.*?-->\s*", "",
                   doc_path.read_text(encoding="utf-8"), flags=re.S).strip()
    m = re.search(r"^#\s+(.+)$", brief, re.M)
    title = m.group(1).strip() if m else doc_path.stem
    slug = _slugify(title)

    say("staging the debate…")
    from . import taste as _taste
    script_system = (_DEBATE_SCRIPT_SYSTEM + (_video.AUDIO_SCRIPT_ADDENDUM if audio else "") + _taste.context())
    raw = provider.complete(
        system=script_system, user=f"The brief:\n\n{brief}",
        model=WRITER_MODEL, max_tokens=16000,
    )
    scenes = _video._parse_scenes(raw)
    if not scenes:
        raw2 = provider.complete(
            system=_DEBATE_SCRIPT_SYSTEM,
            user=(f"The brief:\n\n{brief}\n\nYour previous output could "
                  f"not be parsed as JSON. Output ONLY the raw JSON array "
                  f"— no code fences, no commentary — and keep every svg "
                  f"on a single line."),
            model=WRITER_MODEL, max_tokens=16000,
        )
        scenes = _video._parse_scenes(raw2)
    if not scenes:
        raise RuntimeError("debate script returned no scenes")
    say("script-doctor pass…")
    scenes = _video.polish_scenes(
        scenes, (_video.AUDIO_POLISH_NOTE if audio else "") + "This is a two-host debate: keep the speakers' characters "
                "distinct (A warm believer, B dry skeptic), keep the "
                "rebuttal structure, and make the clash at the cruxes "
                "sharper.")

    vd = ("You are one of two rival podcast hosts mid-argument — "
          "genuinely reacting to what the other just said. Talk TO "
          "someone, not AT a script: interruptions of energy, real "
          "amusement, real exasperation.")
    if audio:
        out = EXPLORATIONS_DIR / f"{slug}.debate.m4a"
        r = _video.render_podcast(scenes, out, on_progress=say,
                                  voice_direction=vd, mood="warm")
    else:
        out = EXPLORATIONS_DIR / f"{slug}.debate.mp4"
        r = _video.render_scenes(
            scenes, out, on_progress=say, title=title, badge="THE DEBATE",
            voice_direction=vd, mood="warm")
    r["title"] = title
    r["doc"] = doc_path
    return r
