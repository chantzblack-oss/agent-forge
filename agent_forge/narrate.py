"""Narrate a document — the audiobook layer.

Any delivered document (deep dossier, case file, brief, lesson) can be
turned into a listenable narration: not raw text-to-speech (tables and
URLs read aloud are misery) but a conversion pass that rewrites the
document as spoken prose — every substantive fact and number kept,
tables voiced as comparisons, sources compressed to a closing line —
performed by a warm audiobook narrator over the quiet bed.
"""

from __future__ import annotations

import re
from pathlib import Path

from .providers import get_provider
from .explorer import WRITER_MODEL
from . import video as _video


_NARRATION_SYSTEM = (
    "You convert a written dossier into a LISTENABLE narration — the "
    "audiobook of the document, for someone who wants all of it without "
    "reading.\n"
    "Rules:\n"
    "- Keep EVERY substantive claim, number, name, and confidence level. "
    "This is the document performed, not summarized — expect roughly "
    "the same total length as the source's prose.\n"
    "- Tables become flowing spoken comparisons ('the scout puts it at "
    "2.5, the tracker at 2.6, and the frozen reading at 2.9…'). Never "
    "read cells or headers aloud.\n"
    "- Skip URLs entirely; the sources section becomes one closing "
    "sentence naming the two or three most load-bearing sources.\n"
    "- Skip figure/diagram descriptions unless the diagram carries a "
    "fact stated nowhere else.\n"
    "- Open with one line telling the listener what they're hearing "
    "(the document's title, conversationally), then flow.\n"
    "- Write as spoken prose: full paragraphs, real transitions, varied "
    "sentence music; em-dashes and ellipses as performance cues. Each "
    "segment ends leaning into the next.\n\n"
    "Return ONLY a JSON array of 8-16 segments: {kicker (chapter "
    "label), narration (150-280 words of flowing spoken prose), "
    "delivery (neutral | bright | grave | hushed — follow the "
    "material), read (an acting note for the segment)}."
)


def pdf_to_text(pdf_path: str | Path) -> str:
    """Extract readable text from any PDF (for narrating documents that
    only exist as files — forwarded, uploaded, or made in a session)."""
    from pypdf import PdfReader
    reader = PdfReader(str(pdf_path))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def build_narration(doc_path: str | Path, on_progress=None,
                    text: str | None = None,
                    out_path: str | Path | None = None,
                    checkpoint=None, clips_dir=None,
                    scenes: list[dict] | None = None) -> dict:
    """Convert a document to a narrated m4a next to it. Pass `text` to
    narrate extracted content (e.g. from a PDF) instead of reading md.
    `checkpoint`/`clips_dir`/`scenes` wire this into the durable job
    runner: the script is saved before TTS, clips are reusable across
    restarts, and a checkpointed script skips re-adaptation entirely."""
    say = on_progress or (lambda _m: None)
    doc_path = Path(doc_path)
    doc = text if text is not None else doc_path.read_text(encoding="utf-8")
    doc = re.sub(r"^<!--.*?-->\s*", "", doc, flags=re.S).strip()
    if len(doc) < 800:
        raise RuntimeError("document too short/unreadable to narrate")
    m = re.search(r"^#\s+(.+)$", doc, re.M)
    title = (m.group(1).strip() if m
             else doc.splitlines()[0].strip()[:80] or doc_path.stem)

    if scenes is None:
        say("adapting the document for narration…")
        provider = get_provider("anthropic")
        raw = provider.complete(
            system=_NARRATION_SYSTEM, user=doc[:34000],
            model=WRITER_MODEL, max_tokens=16000,
        )
        scenes = _video._parse_scenes(raw)
        if not scenes:
            raw2 = provider.complete(
                system=_NARRATION_SYSTEM,
                user=(doc[:34000] + "\n\nYour previous output could not be "
                      "parsed as JSON. Output ONLY the raw JSON array."),
                model=WRITER_MODEL, max_tokens=16000,
            )
            scenes = _video._parse_scenes(raw2)
    if not scenes:
        raise RuntimeError("narration adaptation returned no segments")
    if checkpoint is not None:
        # durable checkpoint: a script that can't be persisted
        # must stop the pipeline BEFORE any TTS spend
        checkpoint("script", scenes)

    out = Path(out_path) if out_path else doc_path.with_suffix(".m4a")
    r = _video.render_podcast(
        scenes, out, on_progress=say, clips_dir=clips_dir,
        voice_direction=(
            "You are a superb audiobook narrator — warm, intelligent, "
            "unhurried but never sleepy. Real inflection: lift slightly "
            "on surprising numbers, slow down for verdicts, drop for "
            "asides. The listener should forget they're being read to."),
        mood="warm")
    r["title"] = title
    return r
