"""Card-deck compiler — episodes designed AS swipeable image cards.

Screenshotting an interactive web page made dull cards: UI chrome, dead
"tap to flip" hints, prose chopped mid-thought. This compiler designs the
episode natively for the swipe format instead:

- Every card is one fixed-size slide (412x900 CSS px, rendered @2x) that
  must land ONE beat: a hook, a guess-dare, a reveal, a mechanism diagram,
  a twist, a verdict.
- The swipe replaces the tap: PREDICT cards pose a dare ("Lock in your
  guess before you swipe") and the NEXT card pays it off with the real
  number and a "most people guess X" sting. That preserves the
  predict-before-reveal loop with zero JavaScript.
- Big type, one striking inline-SVG visual per card, cliffhanger bottom
  lines. A card that merely summarizes is a failed card.

Pipeline: essay markdown -> one HTML file of .slide divs -> playwright
screenshots each slide -> explorations/<slug>_cards/card_NN.png
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .providers import get_provider
from .explorer import EXPLORATIONS_DIR, WRITER_MODEL

CARD_W, CARD_H = 412, 900

_DECK_SYSTEM = f"""You are designing a swipeable card deck — the mobile-story
format (think Instagram story meets Kurzgesagt) — from a researched essay.
The reader sees ONE card at a time and swipes for the next. Design for
thrill and teaching, in that order of what gets cut last.

Output: ONE HTML document containing a sequence of
<div class="slide">...</div> elements, each EXACTLY {CARD_W}x{CARD_H} CSS px
(set .slide{{width:{CARD_W}px;height:{CARD_H}px;overflow:hidden;position:relative}}).
All CSS in one <style>. No JavaScript at all. No external requests — draw
every visual with inline SVG, CSS shapes, or big unicode. Use a bold,
modern, high-contrast dark design (this deck is an image; pick one look
and commit — no theme switching).

Deck grammar (10-14 cards):
1. COLD OPEN — a scene or paradox in huge type. No title-page throat-
   clearing; card 1 must already be the story grabbing the reader.
2. THE DARE — "Lock in your guess before you swipe." Pose a concrete
   question with 3-4 options or a scale. This card ends on the dare.
3. THE PAYOFF — the real answer, huge, with a sting ("Most people guess
   X. It's Y — and that's the polite version.").
4-11. THE RIDE — one beat per card: a mechanism made visual (real SVG
   diagram, labeled), a character/scene card, a twist card, a second
   dare/payoff pair mid-deck, a "the part nobody tells you" card.
12. THE FRAME — the essay's cross-field synthesis as a mic-drop card,
   labeled as a framing, not a fact.
13. STINGER — one open question that leaves an itch. Ends with
   "reply 1, 2, or 3 to pull the next thread" and three numbered threads
   in small type.

Card craft rules:
- Max ~45 words per card. Type is the visual: hierarchy, scale contrast
  (one 64-90px number or phrase per card where it earns it).
- Every card needs a visual anchor (SVG diagram, dramatic number, scene
  illustration in simple shapes) — never a wall of centered text.
- Every fact, number, and quote must come from the essay. Where the essay
  hedges, the card hedges (a "~" or "disputed" tag is fine and adds edge).
- Voice: confident narrator with a dry streak. Never textbook. Never
  bullet-point-summary voice.
- Bottom of most cards: a one-line pull to the next ("swipe — it gets
  worse", "the trigger never saw it coming →").

Output ONLY the raw HTML, starting with <!doctype html>."""


_SHOT_SCRIPT = """
import sys
from playwright.sync_api import sync_playwright
import os
html_path, out_dir = sys.argv[1], sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path='/opt/pw-browsers/chromium'
                          if os.path.exists('/opt/pw-browsers/chromium') else None)
    pg = b.new_page(viewport={'width': %(w)d, 'height': %(h)d}, device_scale_factor=2)
    pg.goto('file://' + html_path)
    pg.wait_for_timeout(500)
    slides = pg.query_selector_all('.slide')
    for i, s in enumerate(slides, 1):
        s.scroll_into_view_if_needed()
        pg.wait_for_timeout(60)
        s.screenshot(path=f"{out_dir}/card_{i:02d}.png")
    print(len(slides))
    b.close()
""" % {"w": CARD_W, "h": CARD_H}


def compile_deck(md_path: str | Path, on_progress=None) -> list[Path]:
    """Compile a dive's markdown into a directory of swipeable card PNGs."""
    say = on_progress or (lambda _m: None)
    md_path = Path(md_path)
    essay = md_path.read_text(encoding="utf-8")

    say("designing card deck…")
    html = get_provider("anthropic").complete(
        system=_DECK_SYSTEM,
        user=f"Essay to compile into a card deck:\n\n{essay}",
        model=WRITER_MODEL,
        max_tokens=16000,
    ).strip()
    html = re.sub(r"^```(?:html)?\s*", "", html)
    html = re.sub(r"\s*```$", "", html)

    deck_html = EXPLORATIONS_DIR / (md_path.stem + ".deck.html")
    deck_html.write_text(html, encoding="utf-8")

    out_dir = EXPLORATIONS_DIR / (md_path.stem + "_cards")
    out_dir.mkdir(exist_ok=True)

    say("rendering cards…")
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(_SHOT_SCRIPT)
        script = f.name
    proc = subprocess.run(
        [sys.executable, script, str(deck_html.resolve()), str(out_dir.resolve())],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"card render failed: {proc.stderr[-500:]}")
    n = int(proc.stdout.strip().splitlines()[-1])
    say(f"{n} cards rendered")
    return sorted(out_dir.glob("card_*.png"))
