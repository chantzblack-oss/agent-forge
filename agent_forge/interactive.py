"""Interactive compiler — turn a dive into something you play with, not read.

Takes a finished exploration (the markdown from ``explorer.dive``) plus its
scout briefing and compiles a single self-contained HTML page designed for a
phone: no external requests, works offline, light/dark aware.

The compile prompt enforces interaction patterns rather than layout details,
so every episode is different but always *does* something:

- **Predict-before-reveal** — the reader commits to a guess (tap a choice,
  drag a slider to their estimate) BEFORE the real number/answer animates in.
  This is the single highest-value interaction for learning; every episode
  must open with one.
- **A manipulable model** — at least one slider/toggle "toy" where dragging a
  parameter visibly changes an outcome (a canvas or SVG redrawn by JS), built
  from the essay's core mechanism.
- **Myth vs. reality flips** — tap cards that show the familiar version, flip
  to what's actually defensible (sourced from the dive's own skeptic pass).
- **Tap-through scenes** — content arrives as a sequence of screens with a
  progress dots row, not a wall of text. Each scene: at most ~60 words plus
  its interaction.
- **A final synthesis challenge** — the cross-field connection posed as a
  question to the reader first, their tap revealing the essay's framing.

Usage:
    from agent_forge.interactive import compile_interactive
    path = compile_interactive(md_path)          # explorations/<slug>.html
"""

from __future__ import annotations

import re
from pathlib import Path

from .providers import get_provider

from .explorer import EXPLORATIONS_DIR, WRITER_MODEL

_COMPILE_SYSTEM = """You are an interactive-experience designer compiling a
researched essay into a single-file interactive HTML page for a PHONE.

Hard requirements (violating any of these is failure):
- ONE self-contained HTML document. All CSS in one <style>, all JS in one
  <script>. No external requests of any kind: no CDNs, no fonts, no images
  (draw with inline SVG / canvas / unicode). No console errors.
- Mobile-first: max content width ~600px centered, 16px+ base font, buttons
  min 44px tall, generous spacing. Must also look fine on desktop.
- Light AND dark: style via CSS custom properties; respect
  @media (prefers-color-scheme: dark) and also honor
  :root[data-theme="dark"] / :root[data-theme="light"] overrides.
- Structure: tap-through scenes (divs shown one at a time) with progress
  dots and Back/Next buttons. 8-14 scenes total. NEVER a long scroll of
  paragraphs; max ~60 words of prose per scene.

Required interactions (all of them, adapted to THIS content):
1. Scene 2 or 3 is a PREDICT-BEFORE-REVEAL: the reader drags a slider or
   taps a choice to commit a guess, then the real answer animates in with a
   one-line "you were close / way off" verdict.
2. One MANIPULABLE MODEL scene: a slider or toggles driving a live SVG or
   canvas drawing of the essay's core mechanism — dragging visibly changes
   the picture and a number readout.
3. One MYTH VS REALITY scene: 2-4 tap-to-flip cards (familiar claim on the
   front, the defensible version on the back).
4. One QUIZ scene late in the flow: 3 questions, one at a time, instant
   feedback that TEACHES (the explanation matters more than right/wrong).
5. Final scene: the essay's cross-field synthesis posed as a question the
   reader answers first (free tap on 2-3 stances), then the essay's framing
   is revealed, clearly labeled as a framing, not a fact.

Content rules:
- Every number, date, and claim must come from the provided essay. Do not
  invent facts the essay doesn't contain. Where the essay hedges, the page
  hedges.
- Keep the essay's voice: vivid, precise, occasionally wry.
- Title the page with the essay's title.

Output ONLY the raw HTML document, starting with <!doctype html>. No
markdown fences, no commentary."""


def compile_interactive(md_path: str | Path, on_progress=None) -> Path:
    """Compile a dive's markdown into a self-contained interactive HTML page."""
    say = on_progress or (lambda _m: None)
    md_path = Path(md_path)
    essay = md_path.read_text(encoding="utf-8")

    say("compiling interactive experience…")
    html = get_provider("anthropic").complete(
        system=_COMPILE_SYSTEM,
        user=f"Essay to compile:\n\n{essay}",
        model=WRITER_MODEL,
        max_tokens=16000,
    ).strip()

    # Strip accidental markdown fences.
    html = re.sub(r"^```(?:html)?\s*", "", html)
    html = re.sub(r"\s*```$", "", html)
    if "<html" not in html.lower():
        raise RuntimeError("compiler did not return an HTML document")

    out = EXPLORATIONS_DIR / (md_path.stem + ".html")
    out.write_text(html, encoding="utf-8")
    return out
