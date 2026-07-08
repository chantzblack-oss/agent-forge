"""Debate engine — two hosts argue a topic from opposite corners.

"debate <topic>" becomes a vertical video where two stick-figure hosts
(different colors, different voices, different temperaments) steelman the
two strongest sides of a question. No winner is declared — the closing
scene hands the question to the viewer.
"""

from __future__ import annotations

from .providers import get_provider
from .explorer import EXPLORATIONS_DIR, WRITER_MODEL, _slugify
from . import video as _video


_DEBATE_SYSTEM = (
    "You are the showrunner of a two-host debate show rendered as a "
    "vertical video. Two stick-figure hosts share the screen:\n"
    "  HOST A (left, speaker 'a') — warm, quick, the believer. Argues the "
    "strongest honest case for one side. Can be funny.\n"
    "  HOST B (right, speaker 'b') — dry, precise, the skeptic. Argues "
    "the strongest honest case for the other. Deadpan.\n"
    "USE WEB SEARCH to ground both sides in real facts and numbers. "
    "STEELMAN both sides — no strawmen, and do NOT declare a winner.\n"
    "12-16 scenes. speaker is 'a' or 'b' for a host's line; null ONLY for "
    "the cold-open framing scene and the final scene. Alternate naturally "
    "— rebuttals, concessions, one host finishing the other's point — not "
    "a mechanical a/b/a/b. Each host talks like a person: contractions, "
    "short sentences, replies to what the OTHER host just said (this is a "
    "conversation, not two lectures). BANNED: the \"That's not X. That's "
    "Y.\" pattern, 'here's the thing', rhetorical-question openers.\n"
    "End: each host gets one closing line, then a neutral final scene "
    "that hands the viewer the question.\n\n"
    "Each scene: {speaker ('a'|'b'|null), kicker (2-4 words), headline "
    "(<=7 words, on-screen), narration (1-3 spoken sentences), pose "
    "(explain | point | warn | celebrate | think | wave), delivery "
    "(neutral | bright | hype | grave | hushed), read (a short acting "
    "note for how this exact line should be delivered), visual (optional "
    "inline SVG on a SINGLE line — JSON strings cannot contain raw "
    "newlines — viewBox='0 0 880 700', no external refs/scripts, under "
    "900 characters; it sits on the video's dark background — NO backdrop "
    "rect; palette ink #eaf3f2 accent #ff7a5e accent2 #35c2d6 muted "
    "#5d7a84, text >= 26px, labels clear of shape edges)}.\n"
    "Return ONLY a JSON array."
)


def build_debate(topic: str, on_progress=None) -> dict:
    """Research and render a two-host debate video on `topic`."""
    say = on_progress or (lambda _m: None)
    say("writing the debate…")
    provider = get_provider("anthropic")
    raw = provider.complete(
        system=_DEBATE_SYSTEM, user=f"Debate topic: {topic}",
        model=WRITER_MODEL, max_tokens=16000,
    )
    scenes = _video._parse_scenes(raw)
    if not scenes:
        raw2 = provider.complete(
            system=_DEBATE_SYSTEM,
            user=(f"Debate topic: {topic}\n\nYour previous output could "
                  f"not be parsed as JSON. Output ONLY the raw JSON array "
                  f"— no code fences, no commentary — and keep every svg "
                  f"on a single line."),
            model=WRITER_MODEL, max_tokens=16000,
        )
        scenes = _video._parse_scenes(raw2)
    if not scenes:
        raise RuntimeError("debate script returned no scenes")

    EXPLORATIONS_DIR.mkdir(exist_ok=True)
    out = EXPLORATIONS_DIR / f"{_slugify(topic)}.debate.mp4"
    r = _video.render_scenes(scenes, out, on_progress=say)
    r["title"] = topic
    return r
