"""Story engine — long-form narrative dread with receipts.

The dark-documentary format: true crime, disasters, historical mysteries,
maritime tragedies, horror with a paper trail. Modeled on the channels
that do this best — deep, honest, atmospheric — never exploitative.

    build_story(case) ->
        explorations/<slug>.case.md    (the case file: timeline, people,
                                        evidence, theories weighed)
        explorations/<slug>.case.mp4   (the episode: cold open in the
                                        horror, rewind, walk it beat by
                                        beat, weigh the theories)
"""

from __future__ import annotations

import re
from pathlib import Path

from .providers import get_provider
from .explorer import EXPLORATIONS_DIR, WRITER_MODEL, _slugify
from . import video as _video
from . import research as _research


_CASEFILE_SYSTEM = (
    "You are building the definitive case file on a dark story — true "
    "crime, disaster, vanishing, historical mystery, or horror with a "
    "paper trail. USE WEB SEARCH hard: primary sources, contemporary "
    "reporting, official findings. The reader has seen the shallow "
    "retellings; your job is the version that separates documented fact "
    "from internet legend — and says so, line by line.\n"
    "RESPECT RULE: real victims are people, not props. No gore relish, "
    "no speculation about suffering, no invented dialogue.\n\n"
    "Produce a markdown case file with EXACTLY these sections:\n"
    "# <the case, titled like a great episode — evocative, not clickbait>\n"
    "## The cold facts\n"
    "  a small TABLE: what | where | when | who was involved | status "
    "(solved/unsolved/disputed).\n"
    "## The timeline\n"
    "  the full reconstruction, timestamped as precisely as sources "
    "allow. Where accounts conflict, show both and say which source "
    "says what.\n"
    "## The people\n"
    "  everyone who matters, one to two lines each — who they were, not "
    "just their role.\n"
    "## The evidence\n"
    "  what was actually found, examined, or recorded — physical, "
    "documentary, testimonial. Flag anything the retellings exaggerate.\n"
    "## The theories\n"
    "  each serious theory: the case FOR it, the fact that most "
    "undermines it, and a plausibility read. Include the boring theory "
    "if the boring theory is probably right.\n"
    "## Fact vs legend\n"
    "  the specific claims the internet repeats that the record does not "
    "support — named and corrected.\n"
    "## Open questions\n"
    "  what remains genuinely unknown, and what evidence could still "
    "surface.\n"
    "## Sources\n"
    "  5-8 real links from your search THIS turn — favor primary "
    "documents, archives, official reports, and the best long-form "
    "coverage. Never invented; omit rather than fabricate.\n\n"
    "MAKE IT VISUAL — this renders to a designed PDF:\n"
    "- The cold facts and theories as TABLES.\n"
    "- 1-2 inline SVG diagrams where geography or sequence matters (a "
    "route map, a deck plan, a timeline rail). Raw <svg>, viewBox='0 0 "
    "800 400', LIGHT palette: ink #1d3038, accent #ff7a5e, accent2 "
    "#0e8ea3, muted #6b8893; text >= 20px; no background rect.\n"
    "- Bold the load-bearing facts."
)


_STORY_SCRIPT_SYSTEM = (
    "You are directing a dark-documentary episode from a researched case "
    "file the viewer also has. Think of the best long-form storytellers "
    "in true crime and disaster history: unhurried, atmospheric, honest "
    "about uncertainty, respectful of the dead — and impossible to stop "
    "watching.\n"
    "STRUCTURE — the documentary arc:\n"
    "  - COLD OPEN in medias res: the single most chilling documented "
    "moment, mid-story, hushed. No preamble.\n"
    "  - Rewind: 'to understand what happened here…' — set the world, "
    "make us know the people as people (photos where they exist).\n"
    "  - The event, beat by beat: advance through the timeline (kicker "
    "carries the timestamp), tension building scene over scene.\n"
    "  - The investigation/aftermath: what was found, in the order it "
    "was found.\n"
    "  - The theories, weighed honestly — including the boring one if "
    "the boring one is probably right. Fact vs legend called out.\n"
    "  - Close on the open question that won't leave you alone. Let it "
    "linger; no tidy bow, no moral.\n"
    "16-26 scenes — this format EARNS length; go as long as the material "
    "holds. Deliveries skew hushed and grave with bright used only for "
    "dawn-before-the-storm contrast. Photos are the soul here: use the "
    "photo field on 4-8 scenes (the ship, the road, the people, the "
    "place today). Use 'punch' layout for timestamps that land like "
    "verdicts and the final question.\n"
    "RESPECT RULE: victims are people, not props — no gore relish, no "
    "invented dialogue, nothing the record doesn't support. Where the "
    "case file hedges, the narration hedges — honest uncertainty IS the "
    "atmosphere.\n"
    "Every fact, time, and name must come from the case file.\n\n"
    "Each scene: {kicker (2-4 words, often the timestamp), headline "
    "(<=7 words, on-screen), narration (1-3 spoken sentences, HARD MAX "
    "40 words; engineer pacing with punctuation — ellipses for dread, "
    "em-dashes for the turn, short sentences like footsteps), layout "
    "(standard | punch | fullviz), pose (explain | point | warn | think "
    "| none — the host mostly stays still in this format; 'none' is "
    "welcome on photo scenes), delivery (neutral | bright | grave | "
    "hushed), read (an acting note for this exact line — 'barely above "
    "a whisper', 'flat, like reading a report'), photo (Wikimedia "
    "search query — specific proper nouns), data (engine charts: "
    "{\"type\":\"flow\",\"steps\":[..]} for cascades, bars/gauge/scale "
    "for numbers), visual (optional single-line SVG, viewBox='0 0 880 "
    "700', dark background, NO backdrop rect, light-palette text only — "
    "maps and timeline rails shine here)}.\n"
    "Return ONLY a JSON array."
)


def build_story(case: str, on_progress=None, on_doc=None) -> dict:
    """Research the case file, deliver it, then render the episode."""
    say = on_progress or (lambda _m: None)
    provider = get_provider("anthropic")

    say("opening the case file…")
    casefile = provider.complete(
        system=_CASEFILE_SYSTEM,
        user=f"The case: {case}" + _research.notes_block(case, say),
        model=WRITER_MODEL, max_tokens=6500,
    ).strip()

    m = re.search(r"^#\s+(.+)$", casefile, re.M)
    title = m.group(1).strip() if m else case
    slug = _slugify(title)
    EXPLORATIONS_DIR.mkdir(exist_ok=True)
    doc_path = EXPLORATIONS_DIR / f"{slug}.case.md"
    doc_path.write_text(f"<!-- case: {case} -->\n\n{casefile}\n",
                        encoding="utf-8")

    if on_doc is not None:
        try:
            on_doc(doc_path)
        except Exception:
            pass
    return video_from_casefile(doc_path, on_progress=say)


def video_from_casefile(doc_path: str | Path, on_progress=None) -> dict:
    """Script and render the episode from an existing case file — also
    the resume path."""
    say = on_progress or (lambda _m: None)
    provider = get_provider("anthropic")
    doc_path = Path(doc_path)
    casefile = re.sub(r"^<!--.*?-->\s*", "",
                      doc_path.read_text(encoding="utf-8"), flags=re.S).strip()
    m = re.search(r"^#\s+(.+)$", casefile, re.M)
    title = m.group(1).strip() if m else doc_path.stem
    slug = _slugify(title)

    say("writing the episode…")
    from . import taste as _taste
    script_system = _STORY_SCRIPT_SYSTEM + _taste.context()
    raw = provider.complete(
        system=script_system, user=f"The case file:\n\n{casefile}",
        model=WRITER_MODEL, max_tokens=16000,
    )
    scenes = _video._parse_scenes(raw)
    if not scenes:
        raw2 = provider.complete(
            system=_STORY_SCRIPT_SYSTEM,
            user=(f"The case file:\n\n{casefile}\n\nYour previous output "
                  f"could not be parsed as JSON. Output ONLY the raw JSON "
                  f"array — no code fences, no commentary — and keep "
                  f"every svg on a single line."),
            model=WRITER_MODEL, max_tokens=16000,
        )
        scenes = _video._parse_scenes(raw2)
    if not scenes:
        raise RuntimeError("story script returned no scenes")
    say("script-doctor pass…")
    scenes = _video.polish_scenes(
        scenes, "This is a dark-documentary episode: protect the cold "
                "open, keep the dread building scene over scene, keep "
                "the respect rule absolute, and make the closing "
                "question land like a stone in a well.")

    out = EXPLORATIONS_DIR / f"{slug}.case.mp4"
    r = _video.render_scenes(scenes, out, on_progress=say,
                             title=title, badge="CASE FILE")
    r["title"] = title
    r["doc"] = doc_path
    return r
