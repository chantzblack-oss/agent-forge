"""Simulation engine — run a what-if forward and watch it unfold.

The third format. A lesson teaches you to DO something, a debate helps you
DECIDE something; a simulation shows you WHAT HAPPENS IF. It takes a
scenario — geopolitical, economic, scientific, or personal — pins the
assumptions, and runs it forward through branch points to end states with
rough odds:

    build_sim(scenario) ->
        explorations/<slug>.sim.md    (the dossier: assumptions, timeline,
                                       branches, end states, early signals)
        explorations/<slug>.sim.mp4   (the host walks the timeline live)

The dossier is researched (web search on) so the causal chains start from
real numbers, and it ships the moment it exists.
"""

from __future__ import annotations

import re
from pathlib import Path

from .providers import get_provider
from .explorer import EXPLORATIONS_DIR, WRITER_MODEL, _slugify
from . import video as _video
from . import research as _research


_DOSSIER_SYSTEM = (
    "You are running a rigorous simulation of a what-if scenario. USE WEB "
    "SEARCH to anchor the starting conditions in real, current numbers "
    "and facts — the causal chains must launch from reality, not vibes. "
    "Reason like a superforecaster: base rates, historical analogues, "
    "second-order effects, and honest uncertainty. Never present one "
    "storyline as fate.\n\n"
    "Produce a markdown dossier with EXACTLY these sections:\n"
    "# <the scenario, phrased sharply>\n"
    "## The setup\n"
    "  the assumptions you're pinning down to make this runnable — what "
    "exactly happens at T-zero, and the 3-5 starting facts/numbers (from "
    "search) that matter most. Bullet each.\n"
    "## How it unfolds\n"
    "  the mainline run: a timeline (T+days/weeks/months/years as fits "
    "the scenario) of consequences and second-order effects, each step "
    "causally chained to the last. Name the mechanisms.\n"
    "## The branch points\n"
    "  the 2-4 moments where the run genuinely forks: what the fork is, "
    "what pushes it each way.\n"
    "## End states\n"
    "  2-4 distinct outcomes with rough likelihoods (e.g. ~50% / ~30% / "
    "~15% / ~5%) and a short paragraph each on the reasoning. The odds "
    "must follow from the branch points; say what analogues inform them.\n"
    "## Early signals\n"
    "  what to watch in the first stretch that tells you which branch "
    "you're actually on. Concrete and observable, bullet each.\n"
    "## What this run can't see\n"
    "  the biggest unknowns and the ways this simulation most likely "
    "breaks — honest limits, not hedging boilerplate.\n"
    "## Sources\n"
    "  4-8 real links found via your web search THIS turn — the data and "
    "analogues the run stands on. Never invented; omit rather than "
    "fabricate.\n\n"
    "For personal scenarios (career, money, life choices) do exactly the "
    "same thing at human scale: real salary/cost/market numbers where "
    "search can find them, honest base rates for how such moves go.\n\n"
    "MAKE IT VISUAL — this renders to a designed PDF:\n"
    "- End states as a markdown TABLE: outcome | odds | what gets you "
    "there.\n"
    "- Include 1-2 inline SVG diagrams — the branch map is the obvious "
    "one (timeline with labeled forks). Raw <svg> in the markdown, "
    "viewBox='0 0 800 400', LIGHT theme palette: ink #1d3038, accent "
    "#ff7a5e, accent2 #0e8ea3, muted #6b8893; text >= 20px; no "
    "background rect.\n"
    "- Bold the load-bearing numbers.\n"
    "- FORMATTING DISCIPLINE: every bullet on its OWN line starting '- ' (never inline ' - ' chains); blockquote callouts are for STRIKING FACTS — a number, a date, a record — never for quoting philosophy or prose."
)


_SIM_SCRIPT_SYSTEM = (
    "You are directing a simulation playback — the viewer is in mission "
    "control watching a what-if run forward in front of them. You are "
    "handed the researched dossier; the viewer has it too. Do not recite "
    "it — PLAY it: present tense, events landing as the clock advances.\n"
    "Structure the run:\n"
    "  - Cold open: T-zero, the trigger, delivered like it just happened.\n"
    "  - Advance the clock scene by scene (kicker carries the timestamp: "
    "'T+3 DAYS', 'T+6 MONTHS'). One consequence per scene, mechanism "
    "named, numbers from the dossier.\n"
    "  - At each branch point, make the fork FELT: hushed, what tips it.\n"
    "  - Play the mainline to its end state, then step back: the other "
    "end states and their rough odds, fast.\n"
    "  - Close: the first early signal to watch for in the real world, "
    "and a pointer to the dossier for the full branch map.\n"
    "EVERY scene must hand the viewer something NEW — a specific fact, "
    "number, name, or image they didn't have a scene ago; a beat that "
    "only restates or transitions gets cut. "
    "Every fact, number, and probability must come from the dossier; "
    "where it hedges, hedge. 12-18 scenes — as many as the material earns. Write like a person talks — "
    "contractions, short sentences, punchy verbs, second person; the "
    "operator occasionally talks TO the viewer ('watch this number'). "
    "Never sound like someone reading slides. BANNED: the \"That's not "
    "X. That's Y.\" pattern, 'here's the thing', rhetorical-question "
    "openers.\n"
    "The host is the run operator: 'point' at diagrams, 'warn' at branch "
    "points, 'think' on the odds, 'wave' only to close.\n\n"
    "Each scene: {layout (standard | punch | fullviz — 'punch' 2-4 times "
    "for the biggest beats as giant centered type: T-zero, a shocking "
    "number, the closing signal; 'fullviz' when the branch map is the "
    "story), kicker (2-4 words, usually the timestamp), headline "
    "(<=7 words, on-screen), narration (1-3 spoken sentences, HARD MAX "
    "55 words — split big ideas into more scenes; engineer pacing with "
    "punctuation — em-dashes for pivots, ellipses for tension before a "
    "reveal — the operator performs it), pose "
    "(explain | point | warn | celebrate | think | wave | none), delivery "
    "(neutral | bright | hype | grave | hushed), read (a short acting "
    "note for this exact line), photo (OPTIONAL Wikimedia search query "
    "for a REAL photograph when an actual person/place/event grounds the "
    "beat — specific proper nouns; 2-4 scenes per video), "
    "image (a cinematic shot description — a film still: subject, angle, "
    "lighting — painted by the engine as full-bleed scene art; use it to "
    "SHOW the consequence the clock just landed on, so most scenes carry "
    "photo, image, or data), "
    "data (PREFER over hand-drawn svg for "
    "numeric beats — engine-rendered animated charts: {\"type\":\"bars\","
    "\"items\":[{\"label\",\"value\"}..]} | {\"type\":\"gauge\",\"value\":"
    "0-100,\"label\"} | {\"type\":\"scale\",\"min_label\",\"max_label\","
    "\"value\":0-100,\"marker_label\"} | {\"type\":\"flow\",\"steps\":"
    "[..]} — flow is perfect for causal cascades, scale for odds), "
    "visual (optional inline SVG on a SINGLE "
    "line — JSON strings cannot contain raw newlines — viewBox='0 0 880 "
    "700', no external refs/scripts, under 900 characters; it sits on "
    "the video's dark background — NO backdrop rect; palette ink #eaf3f2 "
    "accent #ff7a5e accent2 #35c2d6 muted #5d7a84, text >= 26px and "
    "ALWAYS filled with a light palette color — dark fills vanish, "
    "labels clear of shape edges). Timelines and branch diagrams teach best "
    "here — draw the fork when you're standing at one. At least HALF "
    "the scenes carry a visual; any number, comparison, or sequence "
    "gets drawn.}\n"
    "Return ONLY a JSON array."
)


def build_sim(scenario: str, on_progress=None, on_doc=None,
              audio: bool = False) -> dict:
    """Research a scenario dossier, deliver it, then render the timeline
    playback video."""
    say = on_progress or (lambda _m: None)
    provider = get_provider("anthropic")

    say("pinning assumptions and running the scenario…")
    dossier = provider.complete(
        system=_DOSSIER_SYSTEM,
        user=f"Scenario: {scenario}"
             + ("" if scenario.startswith("CONTINUATION")
                else _research.notes_block(scenario, say)),
        model=WRITER_MODEL, max_tokens=6000,
    ).strip()
    from .docrender import clean_markdown
    dossier = clean_markdown(dossier)

    m = re.search(r"^#\s+(.+)$", dossier, re.M)
    if not m or dossier.count("##") < 4 or len(dossier) < 1200:
        raise RuntimeError("dossier came back malformed — try rephrasing "
                           "the scenario")
    title = m.group(1).strip()
    slug = _slugify(title)
    EXPLORATIONS_DIR.mkdir(exist_ok=True)
    doc_path = EXPLORATIONS_DIR / f"{slug}.sim.md"
    doc_path.write_text(f"<!-- simulation: {scenario} -->\n\n{dossier}\n",
                        encoding="utf-8")

    if on_doc is not None:
        try:
            on_doc(doc_path)
        except Exception:
            pass
    return video_from_dossier(doc_path, on_progress=say, audio=audio)


def video_from_dossier(doc_path: str | Path, on_progress=None,
                       audio: bool = False) -> dict:
    """Script and render the playback from an existing dossier — also the
    resume path when a restart killed the render half."""
    say = on_progress or (lambda _m: None)
    provider = get_provider("anthropic")
    doc_path = Path(doc_path)
    dossier = re.sub(r"^<!--.*?-->\s*", "",
                     doc_path.read_text(encoding="utf-8"), flags=re.S).strip()
    m = re.search(r"^#\s+(.+)$", dossier, re.M)
    title = m.group(1).strip() if m else doc_path.stem
    slug = _slugify(title)

    say("staging the playback…")
    from . import taste as _taste
    script_system = (_SIM_SCRIPT_SYSTEM + (_video.AUDIO_SCRIPT_ADDENDUM if audio else "") + _taste.context())
    raw = provider.complete(
        system=script_system, user=f"The dossier:\n\n{dossier}",
        model=WRITER_MODEL, max_tokens=16000,
    )
    scenes = _video._parse_scenes(raw)
    if not scenes:
        raw2 = provider.complete(
            system=_SIM_SCRIPT_SYSTEM,
            user=(f"The dossier:\n\n{dossier}\n\nYour previous output "
                  f"could not be parsed as JSON. Output ONLY the raw JSON "
                  f"array — no code fences, no commentary — and keep "
                  f"every svg on a single line."),
            model=WRITER_MODEL, max_tokens=16000,
        )
        scenes = _video._parse_scenes(raw2)
    if not scenes:
        raise RuntimeError("simulation script returned no scenes")
    say("script-doctor pass…")
    scenes = _video.polish_scenes(
        scenes, (_video.AUDIO_POLISH_NOTE if audio else "") + "This is a simulation playback: keep the advancing clock, "
                "make the branch-point tension sharper, and keep every "
                "number traceable to the dossier.")

    vd = ("You are a mission-control operator narrating a live run — "
          "calm, precise, quietly intense. Tension builds in the "
          "voice as the clock advances; clipped on the data, hushed "
          "at the forks.")
    if audio:
        out = EXPLORATIONS_DIR / f"{slug}.sim.m4a"
        r = _video.render_podcast(scenes, out, on_progress=say,
                                  voice_direction=vd)
    else:
        out = EXPLORATIONS_DIR / f"{slug}.sim.mp4"
        r = _video.render_scenes(
            scenes, out, on_progress=say, title=title, badge="SIMULATION",
            voice_direction=vd)
    r["title"] = title
    r["doc"] = doc_path
    return r
