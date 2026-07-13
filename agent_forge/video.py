"""Video engine — turn an exploration into a narrated MP4 you watch.

An MP4 is the one rich format that plays natively on any phone (no JS, no
sandbox, no swipe). This module compiles a dive into a vertical video:

    essay -> scene script (headline + narration + visual) -> per-scene
    narration audio (edge-tts) -> per-scene still (rendered HTML, 1080x1920)
    -> ffmpeg clip (Ken Burns over the still, for the audio's duration)
    -> concat -> explorations/<slug>.mp4

Graceful degradation is the whole trick:
- On an always-on HOST, edge-tts reaches the voice service and every scene
  gets real narration; scene length = narration length.
- In a locked-down SANDBOX (no TTS network), narration is skipped and each
  scene runs a fixed reading-time; the result is a SILENT CAPTIONED video —
  still a real, playable MP4 for previewing the visuals.

Either way the scene stills carry the words on screen, so the video is
watchable muted (captioned by construction).

Requires ffmpeg. We use the pip-bundled binary from imageio-ffmpeg so no
system install is needed.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .providers import get_provider
from .explorer import EXPLORATIONS_DIR, WRITER_MODEL

W, H = 1080, 1920          # vertical, phone-native
FPS = 30
VOICE = os.environ.get("FORGE_TTS_VOICE", "en-US-AndrewMultilingualNeural")


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# ── 1. script ────────────────────────────────────────────

_SCRIPT_SYSTEM = (
    "You are a video director adapting a researched essay into a narrated "
    "vertical-video script (think a smart, punchy explainer). Return 9-16 "
    "scenes — as many as the material earns, no padding. Each scene is one "
    "beat of narration the viewer HEARS plus a short headline they SEE. "
    "Design the structure for THIS essay: a detective story wants a "
    "slow-burn reveal, a mechanism wants stepwise build-up, a controversy "
    "wants both sides then a verdict. Vary the rhythm — a one-sentence "
    "punch scene between longer beats is allowed.\n"
    "PICK A VOICE for this video and commit to it: wry and funny for "
    "absurd or delightful material, deadpan for the bizarre, gravity for "
    "tragedy or high stakes, conspiratorial hush for mysteries, infectious "
    "awe for wonders. Humor is welcome when the material is funny — real "
    "wit (irony, understatement, a running gag), never forced jokes or "
    "cringe. Dark material gets respect, not edginess. The tone should "
    "feel like a host who genuinely reacts to what they're telling you, "
    "and it can shift as the story turns.\n\n"
    "Rules:\n"
    "- narration: 1-3 spoken sentences, HARD MAX 55 words (a scene should "
    "run 10-18 seconds — long monologues kill the pace; split big ideas "
    "into more scenes), no markdown, no stage directions — "
    "just what the voice says. Engineer the pacing with punctuation — "
    "the narrator performs it: em-dashes for a sharp mid-thought pivot, "
    "ellipses for a hesitation or trailing thought, a short sentence for "
    "a punch. Write like a person actually talks: "
    "contractions, mostly short sentences, concrete verbs; it must pass "
    "being read aloud. BANNED: the \"That's not X. That's Y.\" pattern, "
    "'Here's the thing', 'here's the magic', 'But wait', rhetorical "
    "questions as openers, and ending every scene on a punchline — one "
    "aphorism per VIDEO, max. Open cold on the story; no 'in this "
    "video'.\n"
    "- read: a short acting note for how this exact line should be "
    "delivered, like a director talking to a voice actor — e.g. 'slow "
    "down on the number, let it sink in' or 'deadpan, almost bored, the "
    "absurdity does the work'. Make it specific to the line.\n"
    "- headline: <= 7 words, the on-screen text for that beat (also serves "
    "as the caption for muted viewing).\n"
    "- kicker: 2-4 word eyebrow label.\n"
    "- data: PREFER this over a hand-drawn svg whenever the beat is "
    "numeric — the engine renders it as a polished animated chart whose "
    "visual weight matches the math. One of:\n"
    "    {\"type\":\"bars\",\"title\":..,\"unit\":..,\"items\":[{\"label\":..,\"value\":<number>}, ...<=6]}\n"
    "    {\"type\":\"gauge\",\"title\":..,\"value\":<0-100>,\"label\":..} for one percentage\n"
    "    {\"type\":\"scale\",\"title\":..,\"min_label\":..,\"max_label\":..,\"value\":<0-100>,\"marker_label\":..} for a spectrum\n"
    "    {\"type\":\"flow\",\"title\":..,\"steps\":[..2-6 short steps..]} for a chain reaction or process\n"
    "- visual: for scenes where a picture teaches more than words, an inline "
    "SVG diagram for that exact beat (viewBox='0 0 880 700', no external "
    "refs, no <script>; the ENTIRE svg must be ONE line — JSON strings "
    "cannot contain raw newlines — and each svg must stay under 900 "
    "characters: simple shapes and labels, not artwork). The svg sits on "
    "the video's dark background — NO background rect, no light fill "
    "behind the diagram; draw shapes and text directly with the palette "
    "below. Keep every label OUTSIDE the shape it names or sized to fit "
    "with room to spare — never let text touch or cross a shape edge. "
    "Design real diagrams: graphs with labeled nodes, "
    "timelines, before/after, flows with arrows, simple scene illustrations. "
    "Palette on dark: ink #eaf3f2, accent #ff7a5e, accent2 #35c2d6, "
    "muted #5d7a84, amber #ffb454. Text >= 26px, and svg text fill must "
    "ALWAYS be one of those light palette colors — never a dark fill, it "
    "vanishes on the dark background. Inside a visual you may place "
    "clean stroke icons: <icon name='flame' x='100' y='80' size='64' "
    "color='#ff7a5e'/> — names: flame clock dollar alert zap shield "
    "home heart bulb hourglass check x trend-up trend-down target globe. A visual is REQUIRED on every scene that "
    "explains a mechanism, number, comparison, or sequence — typography-only "
    "is acceptable only for pure emotional beats (max 3 per video).\n"
    "- photo: OPTIONAL search query for a REAL photograph (fetched from "
    "Wikimedia Commons) when an actual person, place, machine, or event "
    "beats any diagram — e.g. 'Concorde takeoff', 'Chernobyl control "
    "room', 'Muhammad Ali Liston'. Specific proper nouns work best. Use "
    "on 2-5 scenes per video where reality punches hardest; the photo "
    "becomes the full-bleed background of that scene.\n"
    "- image: a cinematic SHOT DESCRIPTION for scenes where neither a "
    "real photo nor a chart fits — write it like a film still: subject, "
    "camera angle, lighting, mood ('overhead view of a container ship "
    "dwarfed by a rogue wave, storm light'). The engine paints it in "
    "the channel's house style as the scene's full-bleed background. "
    "MOST scenes should carry photo, image, or data — a text-only "
    "frame is the exception, not the default.\n"
    "- layout: the shot type — standard | punch | fullviz. Use 'punch' "
    "2-4 times per video for the biggest one-liners (giant centered "
    "type, no diagram): the hook, a shocking number, a hard question, "
    "the final line. Use 'fullviz' when the diagram IS the story. A "
    "video that is all 'standard' feels like a slideshow — vary the "
    "shots like an editor would.\n"
    "- pose: the on-screen host's body language for the beat, one of "
    "explain | point | warn | celebrate | think | wave | none. Use 'point' "
    "when there's a diagram to gesture at, 'warn' on danger/mistake beats, "
    "'celebrate' on the payoff, 'think' on open questions, 'wave' to open "
    "and close, 'none' when the frame should be host-free.\n"
    "- delivery: how the narrator should say this beat, one of "
    "neutral | bright | hype | grave | hushed. Match the beat: bright for "
    "playful lines, hype for the payoff, grave for tragedy or stakes, "
    "hushed for mystery and tension. Vary it — a whole video in one "
    "delivery is a monotone.\n"
    "- EVERY scene must hand the viewer something NEW — a specific fact, "
    "number, name, or image they didn't have a scene ago. If a scene only "
    "restates or transitions, cut it.\n"
    "- Every fact/number must come from the essay; where it hedges, hedge.\n"
    "- Build momentum; end on the essay's most mind-bending point, then one "
    "closing beat that names the open question.\n"
    "VOICE: a sharp, funny friend who respects the viewer's time. Punchy "
    "verbs, surprising-but-precise comparisons, second person. Vary the "
    "sentence music — some scenes land one clean punch, others run quick "
    "triplets; ask the viewer a hard question now and then, or give a "
    "flat command. Never sound like a narrator reading slides.\n"
    "Return ONLY a JSON array of {kicker, headline, narration, layout, "
    "pose, delivery, read, photo?, image?, data?, visual?}."
)


AUDIO_SCRIPT_ADDENDUM = (
    "\n\nAUDIO EDITION — this is a PODCAST episode, not a video. The "
    "listener sees nothing; visual fields (layout/visual/data/photo/"
    "image/pose/headline) are unnecessary. Instead of many short scenes, "
    "return 6-10 SEGMENTS: each {kicker (chapter label), narration "
    "(120-260 words of FLOWING spoken prose — full paragraphs, real "
    "transitions carrying the listener forward, varied sentence music; "
    "write the whole thing as one continuous radio piece cut into "
    "chapters, NOT fragments), delivery, read (an acting note for the "
    "whole segment), speaker where the format has speakers}. The 40-word "
    "cap does NOT apply here. Describe what matters — the listener "
    "can't see anything. Segments must flow into each other: end each "
    "one leaning into the next."
)

AUDIO_POLISH_NOTE = (
    " AUDIO EDITION: segments are 120-260 words of flowing spoken "
    "prose — do NOT shorten them to captions; improve flow, transitions "
    "and inflection cues instead. The 40-word cap does not apply."
)


def _repair_json(txt: str) -> str:
    """Escape raw newlines/tabs inside JSON string literals — the usual
    reason model-written JSON with embedded SVG fails to parse."""
    out = []
    in_str = False
    esc = False
    for ch in txt:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            elif ch == "\n":
                out.append("\\n"); continue
            elif ch == "\t":
                out.append("\\t"); continue
            elif ch == "\r":
                continue
        elif ch == '"':
            in_str = True
        out.append(ch)
    return "".join(out)


def _salvage_truncated(blob: str) -> str:
    """A response cut off mid-array can still yield its complete scenes:
    trim to the last complete '}' and close the array."""
    last = blob.rfind("}")
    if last == -1:
        return blob
    return blob[:last + 1] + "]"


def _parse_scenes(raw: str) -> list[dict]:
    """Extract the scene array from model output, tolerating code fences,
    surrounding prose, and trailing junk."""
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?\s*", "", txt)
    txt = re.sub(r"\s*```$", "", txt)
    start = txt.find("[")
    if start == -1:
        return []
    end = txt.rfind("]")
    blob = txt[start:end + 1] if end > start else txt[start:]
    scenes = None
    for candidate in (blob, _repair_json(blob),
                      _salvage_truncated(_repair_json(txt[start:]))):
        try:
            scenes = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue
    if scenes is None:
        return []
    if not isinstance(scenes, list):
        return []
    out = []
    for s in scenes:
        if isinstance(s, dict) and s.get("narration"):
            s.setdefault("headline", str(s.get("kicker", "")) or "…")
            out.append(s)
    return out


_POLISH_SYSTEM = (
    "You are a ruthless script doctor for a premium explainer studio. You "
    "receive the draft scene-list JSON for a vertical video. FIRST, judge "
    "it like a jaded viewer: score every scene 1-10 for grip (would a "
    "smart viewer skip it?), specificity, and visual power. Any scene "
    "under 8 gets rewritten until it earns its place — or cut outright. "
    "Then elevate the whole script to world-class without changing the "
    "schema:\n"
    "- Sharpen every narration line: cut filler, replace abstraction with "
    "a concrete image, make lines quotable. Keep the punctuation-as-"
    "performance style (em-dashes, ellipses) and the 40-word cap.\n"
    "- KILL cliches on sight: 'vanished without a trace', 'little did "
    "they know', 'to this day', 'sent chills', 'what happened next', "
    "'nestled in', 'shrouded in mystery', 'only time will tell' — "
    "replace each with the specific concrete detail it was hiding.\n"
    "- Deepen: wherever the draft gestures ('costs a lot', 'takes time'), "
    "replace with the precise number or name ALREADY IN THE DRAFT's "
    "material — never invent facts that aren't there.\n"
    "- Storytell: plant a setup in the first third that pays off in the "
    "last scene; add one callback; end each scene pulling toward the "
    "next. If the draft has a running gag, make it land harder.\n"
    "- Upgrade weak visuals: where a beat is numeric, replace decorative "
    "svg with a data{} chart spec; keep at least half the scenes visual.\n"
    "- Refine the read acting notes so each is specific to its line; "
    "keep delivery/pose/layout variety, and speaker fields if present.\n"
    "- Same JSON schema, svgs on a single line.\n"
    "Return ONLY the improved JSON array."
)


def _outside_critique(scenes: list[dict]) -> str:
    """Writers' room: a DIFFERENT model (Gemini, when a key is present)
    critiques the draft. A second brain catches what self-review can't."""
    if not os.environ.get("GEMINI_API_KEY"):
        return ""
    try:
        g = get_provider("gemini")
        crit = g.complete(
            system=("You are an outside script consultant for a premium "
                    "explainer studio. Read this draft scene-list JSON and "
                    "give the 3-6 sharpest, most concrete improvements — "
                    "cite scene numbers, quote the weak line, propose the "
                    "stronger one. Focus on grip, specificity, and arc. "
                    "No praise, no generalities."),
            user=json.dumps(scenes, ensure_ascii=False)[:24000],
            model=os.environ.get("FORGE_GEMINI_MODEL", "gemini-2.5-flash"),
            max_tokens=1500,
        ).strip()
        return crit[:4000]
    except Exception:
        return ""


def polish_scenes(scenes: list[dict], note: str = "") -> list[dict]:
    """Second full pass: the script doctor. First drafts don't ship."""
    try:
        crit = _outside_critique(scenes)
        crit_block = (f"\n\nAn outside consultant's notes (weigh them, "
                      f"adopt what's right):\n{crit}" if crit else "")
        provider = get_provider("anthropic")
        raw = provider.complete(
            system=_POLISH_SYSTEM,
            user=(note + crit_block + "\n\nDraft script JSON:\n"
                  + json.dumps(scenes, ensure_ascii=False)),
            model=WRITER_MODEL, max_tokens=16000,
        )
        better = _parse_scenes(raw)
        if len(better) >= max(len(scenes) - 2, 5):
            return better
    except Exception:
        import logging
        logging.getLogger("agent_forge.video").exception(
            "polish pass failed; shipping the draft")
    return scenes


def script_from_essay(essay: str, script_system: str | None = None,
                      polish_note: str = "") -> list[dict]:
    system = script_system or _SCRIPT_SYSTEM
    try:
        from . import taste as _taste
        system = system + _taste.context()
    except Exception:
        pass
    provider = get_provider("anthropic")
    raw = provider.complete(
        system=system, user=f"Essay:\n\n{essay}",
        model=WRITER_MODEL, max_tokens=16000,
    )
    scenes = _parse_scenes(raw)
    if scenes:
        return polish_scenes(scenes, polish_note)
    # One corrective retry: no visuals this time (guaranteed parseable).
    import logging
    logging.getLogger("agent_forge.video").warning(
        "scene parse failed; raw head: %r", raw[:400])
    raw2 = provider.complete(
        system=system,
        user=(f"Essay:\n\n{essay}\n\nYour previous output could not be "
              f"parsed as JSON. Output ONLY the raw JSON array — no code "
              f"fences, no commentary, starting with '[' and ending with ']'. "
              f"Keep the visual diagrams, but each svg must be a SINGLE "
              f"line and no string may contain raw newlines."),
        model=WRITER_MODEL, max_tokens=16000,
    )
    scenes = _parse_scenes(raw2)
    return polish_scenes(scenes, polish_note) if scenes else scenes


# ── 2. narration (host only; silent fallback in sandbox) ──

# Per-scene delivery: same narrator, different energy. The script model
# picks one word per scene; it maps to TTS rate/pitch so a hype beat is
# quick and lifted while a grave one slows and drops.
_DELIVERIES = {
    "neutral": ("+4%", "+0Hz"),
    "bright":  ("+9%", "+6Hz"),
    "hype":    ("+13%", "+10Hz"),
    "grave":   ("-6%", "-8Hz"),
    "hushed":  ("-11%", "-12Hz"),
}

# Acting notes for the expressive TTS path, keyed by the same delivery word.
# The scene's free-text `read` direction (if the script wrote one) is
# appended, so the model can direct line reads like "leaning in, almost
# laughing at how simple this is".
_DELIVERY_NOTES = {
    "neutral": "Natural, warm storyteller. Conversational and unhurried, "
               "like explaining something you love to a friend.",
    "bright":  "Light and playful, a smile in the voice, quick on your feet.",
    "hype":    "Genuinely excited — energy building, leaning into the reveal.",
    "grave":   "Slow down. Serious and weighted; let the stakes land.",
    "hushed":  "Quiet and intimate, leaning in, like sharing a secret.",
}


def _delivery(scene: dict) -> tuple[str, str]:
    return _DELIVERIES.get(
        str(scene.get("delivery", "")).strip().lower(), _DELIVERIES["neutral"])


def _acting_notes(scene: dict, persona: str = "") -> str:
    base = _DELIVERY_NOTES.get(
        str(scene.get("delivery", "")).strip().lower(),
        _DELIVERY_NOTES["neutral"])
    read = str(scene.get("read", "") or "").strip()
    parts = [p for p in (persona, base, read) if p]
    return " ".join(parts) + (" Keep the pace natural — engaged, never "
                              "sleepy, never announcer-y.")


# Voice casting: strict recurring roles so the format is recognizable the
# moment audio starts. Narrator (lessons/sims/explainers) is a grounded
# broadcast voice; debates pair a higher-energy believer against a
# measured, deep skeptic for natural vocal friction.
def _speaker_openai_voice(spk: str) -> str | None:
    if spk == "a":
        return os.environ.get("FORGE_OPENAI_VOICE_A", "nova")
    if spk == "b":
        return os.environ.get("FORGE_OPENAI_VOICE_B", "echo")
    return None


def _speaker_edge_voice(spk: str) -> str | None:
    if spk == "a":
        return VOICE
    if spk == "b":
        return os.environ.get("FORGE_TTS_VOICE_B",
                              "en-US-AvaMultilingualNeural")
    return None


def _openai_tts(text: str, out_mp3: Path, instructions: str,
                voice: str | None = None) -> bool:
    """Expressive narration via OpenAI TTS. Retries hard (rate limits are
    the common failure) before returning False — a silent fallback to the
    robotic voice ruins a whole video, so fight for this one."""
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    import time as _t
    from openai import OpenAI
    client = OpenAI()
    for attempt in range(4):
        try:
            resp = client.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice=voice or os.environ.get("FORGE_OPENAI_VOICE", "onyx"),
                input=text, instructions=instructions,
            )
            out_mp3.write_bytes(resp.content)
            if out_mp3.exists() and out_mp3.stat().st_size > 0:
                return True
        except Exception:
            _t.sleep(3 * (attempt + 1))     # 429s clear on the next window
    return False


def synth(text: str, out_mp3: Path,
          rate: str = "+4%", pitch: str = "+0Hz",
          voice: str | None = None) -> bool:
    """Synthesize narration to mp3. Returns True on success, False if TTS
    is unreachable (sandbox) so the caller falls back to a timed silent clip."""
    try:
        import edge_tts
        os.environ.setdefault("SSL_CERT_FILE", "/root/.ccr/ca-bundle.crt")
        proxy = os.environ.get("HTTPS_PROXY")

        async def _go(voice):
            c = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch,
                                     proxy=proxy)
            await c.save(str(out_mp3))

        for v in (voice or VOICE, "en-US-GuyNeural"):
            try:
                asyncio.run(_go(v))
                if out_mp3.exists() and out_mp3.stat().st_size > 0:
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False


def _reading_seconds(text: str) -> float:
    words = len(text.split())
    return max(2.5, min(12.0, words / 2.6))   # ~155 wpm, clamped


# ── 3. scene stills ──────────────────────────────────────

_SLIDE_TMPL = """<!doctype html><html><head><meta charset=utf-8><style>
 html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden}}
 html{{background:#06141b}}
 body{{animation:kb {dur}s linear forwards;transform-origin:50% 42%}}
 @keyframes kb{{from{{transform:scale(1)}}to{{transform:scale(1.035)}}}}
 body{{background:radial-gradient(120% 90% at 50% 12%,#12333f,#06141b 70%);
   color:#eaf3f2;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
   display:flex;flex-direction:column;justify-content:center;padding:110px 96px {padbot}px 96px;box-sizing:border-box;position:relative}}
 .orb{{position:absolute;top:-260px;right:-260px;width:680px;height:680px;border-radius:50%;
   background:radial-gradient(circle at 35% 35%,rgba(53,194,214,.20),rgba(53,194,214,0) 65%);
   animation:drift {dur}s ease-in-out infinite alternate}}
 .orb2{{position:absolute;bottom:-320px;left:-280px;width:760px;height:760px;border-radius:50%;
   background:radial-gradient(circle at 60% 40%,rgba(255,122,94,.13),rgba(255,122,94,0) 65%);
   animation:drift2 {dur}s ease-in-out infinite alternate}}
 @keyframes drift{{from{{transform:translate(0,0) scale(1)}}to{{transform:translate(-60px,40px) scale(1.08)}}}}
 @keyframes drift2{{from{{transform:translate(0,0) scale(1)}}to{{transform:translate(50px,-40px) scale(1.06)}}}}
 .bignum{{position:absolute;top:44px;left:96px;font-size:150px;font-weight:800;
   color:rgba(53,194,214,.10);letter-spacing:-.04em;line-height:1;
   opacity:0;animation:rise .9s .1s cubic-bezier(.16,1,.3,1) forwards}}
 .kicker{{color:#ff7a5e;font-weight:800;letter-spacing:.16em;text-transform:uppercase;font-size:34px;margin-bottom:30px;
   opacity:0;animation:rise .7s .15s cubic-bezier(.16,1,.3,1) forwards}}
 .headline{{font-weight:800;font-size:{hlsize}px;line-height:1.04;letter-spacing:-.03em}}
 .headline .w{{display:inline-block;opacity:0;transform:translateY(38px) scale(.98);
   animation:wordin .7s cubic-bezier(.16,1,.3,1) forwards}}
 @keyframes wordin{{to{{opacity:1;transform:none}}}}
 .accent{{color:#35c2d6}}
 .caption{{margin-top:44px;position:relative;min-height:300px}}
 .cap{{position:absolute;top:0;left:0;font-size:{capsize}px;line-height:1.45;
   color:#b8d2d8;max-width:760px;opacity:0;transform:translateY(18px)}}
 @keyframes capin{{to{{opacity:1;transform:none}}}}
 @keyframes capout{{to{{opacity:0;transform:translateY(-14px)}}}}
 .viz{{margin-top:56px;opacity:0;transform:translateY(30px) scale(.97);
   animation:vizrise .9s {vizdelay}s cubic-bezier(.16,1,.3,1) forwards}}
 @keyframes vizrise{{to{{opacity:1;transform:none}}}}
 .viz svg{{width:100%;height:auto;display:block;max-height:640px}}
 .viz svg > *{{opacity:0;animation:vizin .6s cubic-bezier(.34,1.56,.64,1) forwards}}
 @keyframes vizin{{to{{opacity:1}}}}
 @keyframes rise{{from{{opacity:0;transform:translateY(22px)}}to{{opacity:1;transform:none}}}}
 .n{{position:absolute;top:70px;right:96px;color:#3f5a63;font-size:30px;font-weight:700;
   opacity:0;animation:rise .6s .2s ease-out forwards}}
 .bar{{position:absolute;left:96px;bottom:120px;height:8px;background:#ff7a5e;border-radius:99px;
   width:0;animation:grow {dur}s linear forwards}}
 @keyframes grow{{to{{width:{barw}px}}}}
 {layout_css}
</style></head><body>
 {photo}
 <div class=orb></div><div class=orb2></div>
 <div class=bignum>{idx:02d}</div>
 <div class=n>{idx} / {total}</div>
 <div class=kicker>{kicker}</div>
 <div class=headline>{headline}</div>
 {viz}
 <div class=caption>{caption}</div>
 <div class=bar></div>
 {host}
 <script>
  // stagger svg children so diagrams draw themselves in — but never touch
  // elements that carry their own inline animation (it would desync them,
  // and the class fade they replaced can't run anyway)
  document.querySelectorAll('.viz svg > *, .artl svg > *').forEach(function(el, i) {{
    if (el.style.animation) {{ el.style.opacity = 1; return; }}
    el.style.animationDelay = ({vizdelay} + 0.15 + i * 0.22) + 's';
  }});
 </script>
</body></html>"""


# ── the host: an animated stick-figure presenter ─────────
# A rigged SVG character rendered in the corner of every scene. Limbs are
# grouped so CSS keyframes can pose and animate them; the script model picks
# one pose word per scene, which selects the CSS below.

_HOST_POSES = {
    # arms gesture while talking — the default
    "explain": """
 .host .armR{animation:hgR 1.7s ease-in-out infinite alternate}
 @keyframes hgR{from{transform:rotate(-6deg)}to{transform:rotate(-34deg)}}
 .host .armL{animation:hgL 2.1s .3s ease-in-out infinite alternate}
 @keyframes hgL{from{transform:rotate(4deg)}to{transform:rotate(18deg)}}""",
    # left arm extended toward the diagram (which sits to the host's left)
    "point": """
 .host .armL{animation:hpt 1.1s ease-in-out infinite alternate}
 @keyframes hpt{from{transform:rotate(40deg)}to{transform:rotate(47deg)}}
 .host .armR{transform:rotate(-8deg)}""",
    # both arms up, head shaking, flat mouth — something went wrong
    "warn": """
 .host .armL{transform:rotate(65deg)}
 .host .armR{transform:rotate(-65deg)}
 .host .head{animation:hshake .5s ease-in-out infinite alternate}
 @keyframes hshake{from{transform:rotate(-7deg)}to{transform:rotate(7deg)}}
 .host .mouth{d:path("M100 58 L120 58")}""",
    # arms wide overhead, big bounce — the payoff beat
    "celebrate": """
 .host .armL{transform:rotate(95deg)}
 .host .armR{transform:rotate(-95deg)}
 .host .fig{animation:hbig 1s ease-in-out infinite alternate}
 @keyframes hbig{from{transform:translateY(0)}to{transform:translateY(-14px)}}""",
    # hand toward chin, head tilted, flat mouth — pondering
    "think": """
 .host .armR{transform:rotate(-118deg)}
 .host .head{transform:rotate(9deg)}
 .host .mouth{d:path("M101 58 L119 58")}""",
    # right arm up, waving — openers and closers
    "wave": """
 .host .armR{animation:hwave .8s ease-in-out infinite alternate}
 @keyframes hwave{from{transform:rotate(-100deg)}to{transform:rotate(-138deg)}}""",
}

_HOST_TMPL = """
<style>
 .{cls}{{position:absolute;{pos};bottom:168px;width:{width}px;
   opacity:0;animation:rise .7s .5s ease-out forwards{dim}}}
 .{cls} .fig{{animation:hbob 2.3s ease-in-out infinite alternate;
   transform-origin:110px 165px}}
 @keyframes hbob{{from{{transform:translateY(0)}}to{{transform:translateY(7px)}}}}
 .{cls} line,.{cls} path{{stroke:{stroke};stroke-width:9;stroke-linecap:round;fill:none}}
 .{cls} .armL,.{cls} .armR{{transform-origin:110px 92px}}
 .{cls} .head{{transform-origin:110px 44px}}
 {pose_css}
</style>
<div class={cls}><svg viewBox="0 0 220 270">
 <g class=fig>
  <g class=head>
   <circle cx=110 cy=44 r=27 fill=none stroke={stroke} stroke-width=9 />
   <circle cx=100 cy=39 r=3.6 fill={stroke} stroke=none />
   <circle cx=120 cy=39 r=3.6 fill={stroke} stroke=none />
   <path class=mouth d="M99 54 Q110 63 121 54" stroke-width=5 />
  </g>
  <line x1=110 y1=71 x2=110 y2=165 />
  <g class=armL><line x1=110 y1=92 x2=58 y2=140 /></g>
  <g class=armR><line x1=110 y1=92 x2=162 y2=140 /></g>
  <line x1=110 y1=165 x2=76 y2=240 />
  <line x1=110 y1=165 x2=144 y2=240 />
 </g>
</svg></div>"""


def _host_block(cls: str, pose: str | None, pos: str, stroke: str,
                active: bool, width: int = 225) -> str:
    pose_css = ""
    if active and pose:
        pose_css = _HOST_POSES.get(pose, _HOST_POSES["explain"]) \
            .replace(".host", "." + cls)
    return _HOST_TMPL.format(
        cls=cls, pos=pos, stroke=stroke, pose_css=pose_css, width=width,
        dim="" if active else ";filter:opacity(.35)")


def _host_html(scene: dict, has_viz: bool = True) -> str:
    pose = str(scene.get("pose", "")).strip().lower()
    spk = str(scene.get("speaker", "") or "").strip().lower()
    # with no diagram the host IS the scene's visual — let it fill the frame
    w = 225 if has_viz else 330
    if spk in ("a", "b"):
        # debate: two hosts in opposite corners; the speaker is lit and
        # posed, the listener dims and idles.
        return (
            _host_block("hostA", pose if spk == "a" else None,
                        "left:60px", "#eaf3f2", spk == "a", width=w)
            + _host_block("hostB", pose if spk == "b" else None,
                          "right:60px", "#35c2d6", spk == "b", width=w))
    if pose == "none":
        return ""
    return _host_block("host", pose or "explain", "right:60px",
                       "#eaf3f2", True, width=w)


# ── iconography: clean stroke icons the script can place by name ─────────
# 24x24 viewbox, stroke-based (Lucide-style). Used via
#   <icon name="flame" x="100" y="80" size="64" color="#ff7a5e"/>
_ICONS = {
    "flame": '<path d="M12 2c2.5 4.5 6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 3.5-6.5 6-11z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>',
    "dollar": '<path d="M12 2v20M16.5 6.5c-1-2-9-2.5-9 1.5s9 2.5 9 6.5-8 3.5-9 1.5"/>',
    "alert": '<path d="M12 3 2 20h20L12 3zM12 10v4M12 17h.01"/>',
    "zap": '<path d="M13 2 3 14h7l-1 8 11-13h-8l1-7z"/>',
    "shield": '<path d="M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-4z"/>',
    "home": '<path d="M3 11 12 3l9 8M5 10v10h14V10"/>',
    "heart": '<path d="M12 21C4 14 4 7 8.5 5.5 11 4.7 12 7 12 7s1-2.3 3.5-1.5C20 7 20 14 12 21z"/>',
    "bulb": '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 1 4 10.5c-.8.7-1 1.5-1 2.5h-6c0-1-.2-1.8-1-2.5A6 6 0 0 1 12 3z"/>',
    "hourglass": '<path d="M6 3h12M6 21h12M8 3c0 4.5 8 6 8 9s-8 4.5-8 9M16 3c0 4.5-8 6-8 9s8 4.5 8 9"/>',
    "check": '<path d="M4 12l5 5L20 7"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "trend-up": '<path d="M3 17l6-6 4 4 8-8M14 7h7v7"/>',
    "trend-down": '<path d="M3 7l6 6 4-4 8 8M14 17h7v-7"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
}

_ICON_TAG = re.compile(
    r"<icon\s+name=['\"](\w[\w-]*)['\"]"
    r"(?:\s+x=['\"]([\d.]+)['\"])?(?:\s+y=['\"]([\d.]+)['\"])?"
    r"(?:\s+size=['\"]([\d.]+)['\"])?(?:\s+color=['\"](#[0-9a-fA-F]{3,8})['\"])?"
    r"\s*/?>", re.I)


def _expand_icons(svg: str) -> str:
    def sub(m):
        body = _ICONS.get(m.group(1).lower())
        if not body:
            return ""
        x, y = m.group(2) or "0", m.group(3) or "0"
        size = float(m.group(4) or 48)
        color = m.group(5) or "#eaf3f2"
        return (f'<g transform="translate({x},{y}) scale({size / 24:.3f})" '
                f'fill="none" stroke="{color}" stroke-width="2" '
                f'stroke-linecap="round" stroke-linejoin="round">{body}</g>')
    return _ICON_TAG.sub(sub, svg)


# ── programmatic data viz: the engine draws the chart, not the model ─────
_DATA_COLORS = ["#35c2d6", "#ff7a5e", "#ffb454", "#8bd450", "#b48ce8"]


def _data_html(data: dict, vizdelay: float, dur: float = 8.0) -> str:
    """Render a structured data spec as a polished animated chart. The
    visual weight of the graphic matches the math by construction."""
    try:
        kind = str(data.get("type", "")).lower()
        title = str(data.get("title", "") or "")[:80].replace("<", "&lt;")
        head = f'<div class="dvt">{title}</div>' if title else ""
        ease = "cubic-bezier(.16,1,.3,1)"
        spring = "cubic-bezier(.34,1.56,.64,1)"

        def _sync(n_items: int, i: int) -> float:
            # spread reveals across the spoken part of the scene so the
            # chart appears to narrate along with the voice
            span = max(dur - 2.2, 1.0) * 0.75
            return vizdelay + 0.2 + span * (i / max(n_items - 1, 1))

        if kind == "bars":
            items = [i for i in data.get("items", [])
                     if isinstance(i, dict) and i.get("label") is not None][:6]
            vals = [max(float(i.get("value", 0)), 0.0) for i in items]
            top = max(vals) or 1.0
            unit = str(data.get("unit", "") or "")[:12]
            rows = []
            for n, (it, val) in enumerate(zip(items, vals)):
                c = it.get("color") or _DATA_COLORS[n % len(_DATA_COLORS)]
                pct = max(val / top * 100, 3)
                num = f"{val:g}" if len(f"{val:g}") < 8 else f"{val:,.0f}"
                shown = f"{unit}{num}" if unit in ("$", "€", "£") else f"{num}{unit}"
                rows.append(
                    f'<div class="dr"><span class="dl">{str(it["label"])[:22].replace("<","&lt;")}</span>'
                    f'<div class="dt"><div class="df" style="width:{pct:.1f}%;'
                    f'background:{c};animation-delay:{_sync(len(items), n):.2f}s"></div></div>'
                    f'<span class="dv2">{shown}</span></div>')
            return (f'<div class="viz dchart">{head}{"".join(rows)}</div>'
                    f'<style>.dchart{{margin-top:56px}}'
                    f'.dvt{{font-size:32px;color:#9fb8bf;margin-bottom:26px;letter-spacing:.04em}}'
                    f'.dr{{display:flex;align-items:center;gap:22px;margin:20px 0}}'
                    f'.dl{{width:240px;font-size:29px;color:#eaf3f2;text-align:right;flex-shrink:0}}'
                    f'.dt{{flex:1;height:44px;background:rgba(255,255,255,.06);border-radius:11px}}'
                    f'.df{{height:100%;border-radius:11px;transform:scaleX(0);transform-origin:left;'
                    f'animation:dgrow 1.1s {ease} forwards}}'
                    f'.dv2{{width:140px;font-size:29px;font-weight:700;color:#eaf3f2;flex-shrink:0}}'
                    f'@keyframes dgrow{{to{{transform:scaleX(1)}}}}</style>')

        if kind == "gauge":
            val = min(max(float(data.get("value", 0)), 0.0), 100.0)
            label = str(data.get("label", "") or "")[:24].replace("<", "&lt;")
            circ = 2 * 3.14159 * 130
            off = circ * (1 - val / 100)
            return (f'<div class="viz dchart">{head}'
                    f'<svg viewBox="0 0 880 420" style="max-height:460px">'
                    f'<circle cx="440" cy="210" r="130" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="26"/>'
                    f'<circle cx="440" cy="210" r="130" fill="none" stroke="#35c2d6" stroke-width="26" '
                    f'stroke-linecap="round" stroke-dasharray="{circ:.0f}" stroke-dashoffset="{circ:.0f}" '
                    f'transform="rotate(-90 440 210)" style="opacity:1;animation:doff 1.4s {vizdelay + .2:.2f}s {ease} forwards"/>'
                    f'<text x="440" y="200" fill="#eaf3f2" font-size="72" font-weight="800" text-anchor="middle">{val:g}%</text>'
                    f'<text x="440" y="258" fill="#9fb8bf" font-size="30" text-anchor="middle">{label}</text>'
                    f'</svg><style>@keyframes doff{{to{{stroke-dashoffset:{off:.0f}}}}}'
                    f'.dchart{{margin-top:56px}}.dvt{{font-size:32px;color:#9fb8bf;margin-bottom:20px}}</style></div>')

        if kind == "scale":
            val = min(max(float(data.get("value", 50)), 0.0), 100.0)
            lo = str(data.get("min_label", "") or "")[:18].replace("<", "&lt;")
            hi = str(data.get("max_label", "") or "")[:18].replace("<", "&lt;")
            mk = str(data.get("marker_label", "") or "")[:22].replace("<", "&lt;")
            return (f'<div class="viz dchart">{head}'
                    f'<div class="ds"><div class="dsm" style="left:{val:.0f}%;'
                    f'animation-delay:{vizdelay + .3:.2f}s"><div class="dsl">{mk}</div></div></div>'
                    f'<div class="dse"><span>{lo}</span><span>{hi}</span></div>'
                    f'<style>.dchart{{margin-top:66px}}'
                    f'.dvt{{font-size:32px;color:#9fb8bf;margin-bottom:34px}}'
                    f'.ds{{position:relative;height:14px;border-radius:99px;'
                    f'background:linear-gradient(90deg,#35c2d6,#ffb454,#ff7a5e);margin:70px 10px 16px}}'
                    f'.dsm{{position:absolute;top:50%;width:34px;height:34px;border-radius:50%;'
                    f'background:#eaf3f2;border:5px solid #06141b;transform:translate(-50%,-50%) scale(0);'
                    f'animation:dpop .7s {spring} forwards}}'
                    f'.dsl{{position:absolute;bottom:44px;left:50%;transform:translateX(-50%);'
                    f'white-space:nowrap;font-size:28px;font-weight:700;color:#eaf3f2}}'
                    f'.dse{{display:flex;justify-content:space-between;font-size:26px;color:#5d7a84;margin:0 10px}}'
                    f'@keyframes dpop{{to{{transform:translate(-50%,-50%) scale(1)}}}}</style></div>')

        if kind == "flow":
            steps = [str(s)[:34].replace("<", "&lt;")
                     for s in data.get("steps", []) if s][:6]
            if not steps:
                return ""
            parts = []
            for n, s in enumerate(steps):
                d = _sync(len(steps), n)
                if n:
                    parts.append(f'<div class="dfc" style="animation-delay:{d - .25:.2f}s"></div>')
                parts.append(f'<div class="dfn" style="animation-delay:{d:.2f}s">{s}</div>')
            return (f'<div class="viz dchart">{head}{"".join(parts)}'
                    f'<style>.dchart{{margin-top:48px;display:flex;flex-direction:column;align-items:center}}'
                    f'.dvt{{font-size:32px;color:#9fb8bf;margin-bottom:24px}}'
                    f'.dfn{{min-width:420px;text-align:center;padding:20px 34px;border:3px solid #35c2d6;'
                    f'border-radius:14px;font-size:30px;font-weight:700;color:#eaf3f2;'
                    f'transform:scale(.85);opacity:0;animation:dnode .6s {spring} forwards}}'
                    f'.dfc{{width:4px;height:40px;background:#5d7a84;transform:scaleY(0);'
                    f'transform-origin:top;animation:dline .4s {ease} forwards}}'
                    f'@keyframes dnode{{to{{transform:scale(1);opacity:1}}}}'
                    f'@keyframes dline{{to{{transform:scaleY(1)}}}}</style></div>')
    except Exception:
        return ""
    return ""


_SVG_FORBIDDEN = re.compile(
    r"<\s*(script|foreignObject|iframe)|href\s*=|url\s*\(|javascript:", re.I
)


def _safe_visual(scene: dict) -> str:
    """Return the scene's SVG wrapped for layout, or '' if absent/unsafe."""
    svg = (scene.get("visual") or "").strip()
    if not svg or "<svg" not in svg.lower():
        return ""
    svg = _expand_icons(svg)
    if _SVG_FORBIDDEN.search(svg):
        return ""
    return f'<div class="viz">{svg}</div>'


# Per-scene shot types — a production varies its shots; a slideshow doesn't.
_LAYOUTS = {
    "standard": "",
    # one line, giant type, dead center — punchlines, questions, commands
    "punch": """
 body{align-items:center;text-align:center}
 .kicker{text-align:center}
 .headline{font-size:130px;line-height:1.0;max-width:880px}
 .caption{margin-left:auto;margin-right:auto;text-align:center}
 .cap{left:50%;transform:translate(-50%,18px);width:760px}
 @keyframes capin{to{opacity:1;transform:translate(-50%,0)}}
 @keyframes capout{to{opacity:0;transform:translate(-50%,-14px)}}
 .bignum{display:none}""",
    # the diagram is the star — text steps back
    "fullviz": """
 .headline{font-size:54px}
 .viz svg{max-height:980px}
 .caption{min-height:190px}
 .cap{font-size:32px}""",
}


def _caption_html(narration: str, dur: float) -> str:
    """Live captions: the narration plays sentence-by-sentence in sync with
    the voice — each line fades in as it's spoken and out when done. No
    truncation, and the frame keeps moving for the whole scene."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", narration)
             if s.strip()]
    if not sents:
        return ""
    total_chars = sum(len(s) for s in sents) or 1
    lead, tail = 0.5, 1.2           # breath in, LONG settle so the last
                                    # caption stays readable
    span = max(dur - lead - tail, 1.0)
    out, acc = [], 0
    for i, s in enumerate(sents):
        st = lead + span * (acc / total_chars)
        acc += len(s)
        en = lead + span * (acc / total_chars)
        anims = f"capin .4s {st:.2f}s ease-out forwards"
        if i < len(sents) - 1:
            # finish fading out before the next line fades in
            anims += f", capout .3s {max(en - 0.3, st + 0.5):.2f}s ease-in forwards"
        out.append(f'<div class="cap" style="animation:{anims}">'
                   f'{s.replace("<", "&lt;")}</div>')
    return "".join(out)


def _scene_html(scene: dict, idx: int, total: int, dur: float = 8.0) -> str:
    words = scene["headline"].replace("<", "&lt;").split()
    hl = " ".join(
        f'<span class="w" style="animation-delay:{0.25 + i * 0.09:.2f}s">{w}</span>'
        for i, w in enumerate(words))
    viz = ""
    if isinstance(scene.get("data"), dict):
        viz = _data_html(scene["data"], 0.9, dur=max(dur, 3.0))
    if not viz:
        viz = _safe_visual(scene)
    caption = _caption_html(scene.get("narration", ""), max(dur, 3.0))
    host = _host_html(scene, has_viz=bool(viz))
    layout = str(scene.get("layout", "") or "").strip().lower()
    if layout == "punch":
        viz = ""          # punch scenes are type-only by design
    photo_html, photo_css = "", ""
    ph = scene.get("_photo")
    art = (scene.get("artwork") or "").strip()
    if not ph and art and "<svg" in art.lower():
        art = _expand_icons(art)
        if not _SVG_FORBIDDEN.search(art):
            photo_html = f'<div class=artl>{art}</div>'
            photo_css = (
                " body>*{position:relative;z-index:1}"
                " .artl{position:absolute;inset:0;z-index:0;opacity:.95}"
                " .artl svg{width:100%;height:100%;display:block}"
                " .artl svg > *{opacity:0;animation:vizin 1.2s"
                " cubic-bezier(.16,1,.3,1) forwards,"
                f" artfloat {max(dur * 0.9, 6):.1f}s ease-in-out infinite alternate}}"
                " @keyframes artfloat{to{transform:translateY(-16px)}}")
    if ph:
        credit = (scene.get("_photocredit") or "").replace("<", "&lt;")
        photo_html = (
            f"<div class=ph style=\"background-image:url('file://{ph}')\"></div>"
            f"<div class=phg></div>"
            + (f'<div class=phc>&#128247; {credit}</div>' if credit else ""))
        photo_css = (
            " body>*{position:relative;z-index:1}"
            " .ph{position:absolute;inset:0;z-index:0;background-size:cover;"
            f"background-position:center;animation:phz {max(dur, 3.0):.1f}s ease-in-out forwards}}"
            " @keyframes phz{from{transform:scale(1.05)}to{transform:scale(1.16)}}"
            " .phg{position:absolute;inset:0;z-index:0;"
            "background:linear-gradient(180deg,rgba(6,20,27,.30),rgba(6,20,27,.90) 72%)}"
            " .phc{position:absolute;top:64px;left:96px;font-size:20px;"
            "color:rgba(234,243,242,.55)}")
    return _SLIDE_TMPL.format(
        photo=photo_html,
        layout_css=_LAYOUTS.get(layout, "") + photo_css,
        w=W, h=H, idx=idx, total=total, barw=int(880 * idx / total),
        kicker=scene.get("kicker", "").replace("<", "&lt;"),
        headline=hl,
        hlsize=72 if viz else 92,   # smaller headline when a diagram shares the frame
        viz=viz,
        caption=caption,
        host=host,
        # in debate scenes hosts hold both corners; lift the text clear
        padbot=470 if str(scene.get("speaker", "") or "").strip().lower()
        in ("a", "b") else 110,
        dur=max(dur, 3.0),
        vizdelay=0.9,
        capsize=44 if not viz else 36,
    )


# Chromium flags that roughly halve its footprint — required to fit video
# rendering inside a 512MB worker instance.
_LOWMEM_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                "--renderer-process-limit=1", "--no-zygote", "--single-process"]


CAPTURE_FPS = 20     # scrub-capture rate — quality is the priority here;
                     # renders take what they take


def _record_scenes(scenes: list[dict], durs: list[float],
                   workdir: Path, say):
    """Render each scene to a directory of frames by SCRUBBING its CSS
    animations (Web Animations API: pause everything, set currentTime per
    frame, screenshot).

    Realtime recording on a small worker drops frames (laggy) and encodes
    a soft VP8 (blurry). Scrubbing decouples smoothness from CPU: every
    frame is exactly 1/fps of animation time, captured pixel-perfect, so
    the result is identical on a laptop or a 1-CPU container."""
    from playwright.sync_api import sync_playwright
    total = len(scenes)
    exe = "/opt/pw-browsers/chromium"

    def _launch(p):
        return p.chromium.launch(
            executable_path=exe if os.path.exists(exe) else None,
            args=_LOWMEM_ARGS)

    def _one(b, sc, i, dur) -> Path:
        fdir = workdir / f"frames{i:02d}"
        fdir.mkdir(exist_ok=True)
        pg = b.new_page(viewport={"width": W, "height": H})
        with tempfile.NamedTemporaryFile(
                "w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(_scene_html(sc, i, total, dur))
            htmlpath = f.name
        try:
            pg.goto("file://" + htmlpath)
            pg.evaluate(
                "()=>{window.__anims=document.getAnimations({subtree:true});"
                "window.__anims.forEach(a=>a.pause())}")
            nframes = max(int(dur * CAPTURE_FPS), CAPTURE_FPS)
            for fr in range(nframes):
                pg.evaluate(
                    "t=>window.__anims.forEach(a=>{a.currentTime=t})",
                    fr * 1000.0 / CAPTURE_FPS)
                pg.screenshot(path=str(fdir / f"f{fr:05d}.jpg"),
                              type="jpeg", quality=90, animations="allow")
            pg.close()
        finally:
            os.unlink(htmlpath)
        if not any(fdir.glob("f*.jpg")):
            raise RuntimeError(f"scene {i} captured no frames")
        return fdir

    with sync_playwright() as p:
        b = _launch(p)
        for i, (sc, dur) in enumerate(zip(scenes, durs), 1):
            say(f"animating {i}/{total}: {sc['headline']}")
            if i % 5 == 0:
                # recycle the browser periodically to bound leaks on the
                # small worker
                try:
                    b.close()
                except Exception:
                    pass
                b = _launch(p)
            try:
                fdir = _one(b, sc, i, dur)
            except Exception:
                # relaunch and retry the scene once if Chromium died
                try:
                    b.close()
                except Exception:
                    pass
                b = _launch(p)
                fdir = _one(b, sc, i, dur)
            # yield per scene so the caller can encode and free the frames
            # before the next capture — keeps peak disk to one scene
            yield i - 1, fdir
        b.close()


# ── 4. assemble ──────────────────────────────────────────

def _clip(ff: str, src: Path, dur: float, out: Path, audio: Path | None) -> None:
    """Encode one scene to h264 with the narration under it. `src` is a
    directory of PNG frames (virtual-time capture) or a legacy webm."""
    cmd = [ff, "-y"]
    if src.is_dir():
        cmd += ["-framerate", str(CAPTURE_FPS),
                "-i", str(src / "f%05d.jpg")]
    else:
        cmd += ["-i", str(src)]
    if audio:
        cmd += ["-i", str(audio)]
    else:
        # EVERY clip must carry an audio stream: concat takes its stream
        # layout from the first clip, so one silent-card clip without
        # audio mutes the whole video
        cmd += ["-f", "lavfi", "-t", f"{dur:.2f}",
                "-i", "anullsrc=channel_layout=mono:sample_rate=24000"]
    # dip-to-black on both ends so scene cuts read as edits, not glitches
    cmd += ["-t", f"{dur:.2f}", "-r", str(FPS),
            "-vf", (f"scale={W}:{H},fade=t=in:st=0:d=0.22,"
                    f"fade=t=out:st={max(dur - 0.35, 0.5):.2f}:d=0.35,"
                    f"format=yuv420p"),
            "-threads", "1",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
            "-pix_fmt", "yuv420p",
            "-map", "0:v", "-map", "1:a"]
    if audio:
        # a small breath before the line lands
        cmd += ["-af", "adelay=300:all=1"]
    cmd += ["-c:a", "aac", "-b:a", "160k", "-ar", "24000", str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    if src.is_dir():
        # frames are big; free the disk as soon as the clip exists
        import shutil
        shutil.rmtree(src, ignore_errors=True)


def _synthesis_key(text: str, notes: str, spk: str,
                   provider: str = "openai",
                   rate: str = "", pitch: str = "") -> str:
    """Stable identity of one TTS request: same key -> same audio, so a
    clip found on disk under this key is safe to reuse after a restart.
    Includes every sound-affecting input — provider, model, voice, and
    (for the Edge fallback) rate/pitch — so OpenAI and Edge audio can
    never be confused for each other."""
    import hashlib
    if provider == "edge":
        voice = _speaker_edge_voice(spk) or \
            os.environ.get("FORGE_TTS_VOICE", VOICE)
        raw = "\x1f".join((text, notes, spk, "edge", voice, rate, pitch))
    else:
        model = os.environ.get("FORGE_TTS_MODEL", "gpt-4o-mini-tts")
        voice = _speaker_openai_voice(spk) or \
            os.environ.get("FORGE_OPENAI_VOICE", "onyx")
        raw = "\x1f".join((text, notes, spk, "openai", model, voice))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _clip_valid(ff: str, p: Path) -> bool:
    """A cached/renamed clip must actually decode — size alone lets a
    corrupt or truncated file masquerade as finished audio."""
    try:
        if not p.exists() or p.stat().st_size < 1000:
            return False
        r = subprocess.run([ff, "-v", "error", "-i", str(p),
                            "-f", "null", "-"],
                           capture_output=True, timeout=30)
        return r.returncode == 0 and not r.stderr.strip()
    except Exception:
        return False


def _commit_clip(ff: str, tmp: Path, final: Path, meta: dict) -> bool:
    """Validate-then-rename: invalid TTS bytes are never promoted to a
    completed clip. A sidecar json records provenance (provider, model,
    voice, fallback) so cache hits report the truth after a restart."""
    if not _clip_valid(ff, tmp):
        tmp.unlink(missing_ok=True)
        return False
    meta = dict(meta, size=tmp.stat().st_size,
                duration=_audio_dur(ff, tmp))
    os.replace(tmp, final)
    try:
        from .job_state import atomic_write_json
        atomic_write_json(final.with_suffix(".json"), meta)
    except Exception:
        pass                      # provenance is best-effort, audio is not
    return True


def _narrate_all(scenes, work: Path, ff: str, say, persona: str,
                 clips_dir: Path | None = None):
    """Parallel TTS for every scene. Returns (mp3s, durs, narrated,
    fallbacks). With `clips_dir`, clips persist under synthesis-keyed
    names and are REUSED on retry/restart — paid audio is never
    repurchased. Files land via .part + rename, so a crash mid-write
    can't leave a truncated clip masquerading as a good one."""
    say(f"narrating {len(scenes)} scenes…")
    if clips_dir is not None:
        clips_dir.mkdir(parents=True, exist_ok=True)

    prevs = [""] + [s.get("narration", "").strip() for s in scenes[:-1]]

    def _narrate(args):
        i, sc = args
        text = sc.get("narration", "").strip()
        if not text:
            return None, False
        rate, pitch = _delivery(sc)
        spk = str(sc.get("speaker", "") or "").strip().lower()
        notes = _acting_notes(sc, persona)
        prev = prevs[i - 1]
        if prev:
            # continuity: the read should pick up where the last line
            # left off, not restart cold
            notes += (" You are mid-piece — the line just before this "
                      f"one was: \"…{prev[-140:]}\" Continue from that "
                      "energy, don't restart.")
        if clips_dir is not None:
            import uuid as _uuid
            oai_final = clips_dir / \
                f"{_synthesis_key(text, notes, spk)}.mp3"
            edge_final = clips_dir / \
                (f"{_synthesis_key(text, notes, spk, 'edge', rate, pitch)}"
                 ".edge.mp3")
            # a valid OpenAI clip is authoritative: reuse, $0
            if _clip_valid(ff, oai_final):
                return oai_final, False
            # per-attempt unique temp: duplicate identical scenes can
            # never race on one .part file
            tmp = clips_dir / f".{_uuid.uuid4().hex[:10]}.part.mp3"
            if _openai_tts(text, tmp, notes,
                           voice=_speaker_openai_voice(spk)) and \
                    _commit_clip(ff, tmp, oai_final, {
                        "provider": "openai", "fallback": False,
                        "model": os.environ.get("FORGE_TTS_MODEL",
                                                "gpt-4o-mini-tts"),
                        "voice": _speaker_openai_voice(spk)
                        or os.environ.get("FORGE_OPENAI_VOICE", "onyx"),
                        "key": oai_final.stem}):
                return oai_final, False
            tmp.unlink(missing_ok=True)
            # OpenAI unavailable: a cached Edge clip is reused but STAYS
            # marked as fallback (its filename is its provenance) — and
            # because OpenAI is always tried first, it upgrades on the
            # next healthy run
            if _clip_valid(ff, edge_final):
                return edge_final, True
            tmp = clips_dir / f".{_uuid.uuid4().hex[:10]}.part.mp3"
            if synth(text, tmp, rate=rate, pitch=pitch,
                     voice=_speaker_edge_voice(spk)) and \
                    _commit_clip(ff, tmp, edge_final, {
                        "provider": "edge", "fallback": True,
                        "voice": _speaker_edge_voice(spk)
                        or os.environ.get("FORGE_TTS_VOICE", VOICE),
                        "rate": rate, "pitch": pitch,
                        "key": edge_final.stem.replace(".edge", "")}):
                return edge_final, True
            tmp.unlink(missing_ok=True)
            return None, False
        final = work / f"s{i:02d}.mp3"
        if _openai_tts(text, final, notes,
                       voice=_speaker_openai_voice(spk)):
            return final, False
        ok = synth(text, final, rate=rate, pitch=pitch,
                   voice=_speaker_edge_voice(spk))
        return (final if ok else None), ok    # fallback = robotic voice

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as ex:   # gentle on rate limits
        results = list(ex.map(_narrate, enumerate(scenes, 1)))
    mp3s, durs, narrated = [], [], 0
    fallbacks = sum(1 for _m, fb in results if fb)
    if fallbacks:
        say(f"⚠️ {fallbacks} scenes fell back to the robotic voice — "
            "check OpenAI rate limits/credits")
    for sc, (mp3, _fb) in zip(scenes, results):
        if mp3 is not None:
            narrated += 1
            mp3s.append(mp3)
            durs.append(_audio_dur(ff, mp3) + 1.0)
        else:
            mp3s.append(None)
            durs.append(_reading_seconds(sc.get("narration", "")))
    return mp3s, durs, narrated, fallbacks


class NarrationIncomplete(RuntimeError):
    """Some spoken segments could not be synthesized. An episode with
    silently missing chapters must never ship — the caller retries or
    retains the job instead."""

    def __init__(self, missing: list[int], total: int):
        self.missing = missing
        self.total = total
        super().__init__(
            f"narration incomplete: {len(missing)} of {total} segments "
            f"failed TTS (segments {missing}); refusing to assemble an "
            "episode with missing chapters")


def render_podcast(scenes: list[dict], out: Path, on_progress=None,
                   voice_direction: str | None = None,
                   mood: str | None = None,
                   clips_dir: Path | None = None) -> dict:
    """Assemble the scene list as a PODCAST episode: narration with
    breathing room, music bed ducked underneath — no video render at all.
    Minutes instead of half-hours.

    EVERY spoken segment must synthesize (OpenAI, then the Edge
    fallback); a missing segment raises NarrationIncomplete rather than
    shipping an episode with silent holes. Pass `clips_dir` to persist
    clips under synthesis keys so a retry only pays for what's missing."""
    say = on_progress or (lambda _m: None)
    work = Path(tempfile.mkdtemp(prefix="forge_pod_"))
    ff = _ffmpeg()
    mp3s, durs, narrated, fallbacks = _narrate_all(
        scenes, work, ff, say, voice_direction or "", clips_dir=clips_dir)
    spoken = [i for i, sc in enumerate(scenes)
              if (sc.get("narration") or "").strip()]
    missing = [i for i in spoken if mp3s[i] is None]
    if missing:
        raise NarrationIncomplete(missing, len(spoken))
    voiced = [m for m in mp3s if m is not None]
    if not voiced:
        raise RuntimeError("no narration could be synthesized")

    say("assembling the episode…")
    gap = work / "gap.wav"
    subprocess.run([ff, "-y", "-f", "lavfi", "-t", "0.65",
                    "-i", "anullsrc=channel_layout=mono:sample_rate=24000",
                    str(gap)], check=True, capture_output=True)
    inputs, chain = [], []
    n = 0
    for m in voiced:
        if n:
            inputs += ["-i", str(gap)]
            chain.append(f"[{n}:a]")
            n += 1
        inputs += ["-i", str(m)]
        chain.append(f"[{n}:a]")
        n += 1
    voice = work / "voice.m4a"
    subprocess.run(
        [ff, "-y"] + inputs
        + ["-filter_complex",
           "".join(chain) + f"concat=n={n}:v=0:a=1[a]",
           "-map", "[a]", "-c:a", "aac", "-b:a", "128k", str(voice)],
        check=True, capture_output=True)

    total_s = _audio_dur(ff, voice)
    if os.environ.get("FORGE_MUSIC", "1") != "0":
        try:
            say("laying the music bed…")
            from . import music as _music
            bed = work / "bed.wav"
            _music.ambient_bed(total_s, bed,
                               mood or _music.pick_mood(scenes))
            subprocess.run(
                [ff, "-y", "-i", str(voice), "-i", str(bed),
                 "-filter_complex",
                 "[1:a]volume=0.35,afade=t=in:d=2.5[m];"
                 "[m][0:a]sidechaincompress=threshold=0.02:ratio=10:"
                 "attack=40:release=450[md];"
                 "[0:a][md]amix=inputs=2:duration=first:"
                 "dropout_transition=0:normalize=0[a]",
                 "-map", "[a]", "-c:a", "aac", "-b:a", "128k",
                 str(out)], check=True, capture_output=True)
        except Exception:
            import logging
            logging.getLogger("agent_forge.video").exception(
                "podcast music failed; delivering dry voice")
            out.write_bytes(voice.read_bytes())
    else:
        out.write_bytes(voice.read_bytes())
    return {"path": out, "scenes": len(scenes), "narrated": narrated,
            "voiced": True, "fallback": fallbacks,
            "minutes": round(total_s / 60, 1)}


def render_scenes(scenes: list[dict], out: Path, on_progress=None,
                  title: str | None = None, badge: str | None = None,
                  voice_direction: str | None = None,
                  mood: str | None = None,
                  clips_dir: Path | None = None) -> dict:
    """Narrate, record and stitch a scene list into an MP4 at `out`.
    With `title`, the video gets show packaging: a branded title card in
    and a library card out (music-only beats, no narration)."""
    say = on_progress or (lambda _m: None)
    if title:
        scenes = ([{"kicker": badge or "AGENT FORGE", "headline": title[:70],
                    "narration": "", "layout": "punch", "pose": "wave",
                    "delivery": "neutral"}]
                  + list(scenes)
                  + [{"kicker": "AGENT FORGE", "headline": "Saved to your library",
                      "narration": "", "layout": "punch", "pose": "celebrate",
                      "delivery": "neutral"}])
    work = Path(tempfile.mkdtemp(prefix="forge_video_"))
    ff = _ffmpeg()
    total = len(scenes)
    # Phase 0: imagery — real photographs and generated scene art run in
    # parallel (both are network-bound).
    def _fetch_imagery(args):
        i, sc = args
        q = str(sc.get("photo", "") or "").strip()
        if q:
            from . import photos as _photos
            r = _photos.find_photo(q, work / f"ph{i:02d}.jpg")
            if r:
                sc["_photo"] = str(r["path"])
                sc["_photocredit"] = r["credit"]
                return
        shot = str(sc.get("image", "") or "").strip()
        if shot:
            from . import imagery as _imagery
            p = work / f"art{i:02d}.png"
            if _imagery.generate_image(shot, p):
                sc["_photo"] = str(p)
                sc["_photocredit"] = ""
    wanted = [(i, sc) for i, sc in enumerate(scenes)
              if sc.get("photo") or sc.get("image")]
    if wanted:
        say(f"painting {len(wanted)} scenes…")
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as ex:
            list(ex.map(_fetch_imagery, wanted))
    mp3s, durs, narrated, fallbacks = _narrate_all(
        scenes, work, ff, say, voice_direction or "", clips_dir=clips_dir)
    # Phase 2: capture each scene (virtual-time, pixel-perfect) and encode
    # it immediately — frames are freed before the next scene is captured.
    clips: list[Path] = []
    for i, fdir in _record_scenes(scenes, durs, work, say):
        clip = work / f"c{i + 1:02d}.mp4"
        _clip(ff, fdir, durs[i], clip, mp3s[i])
        clips.append(clip)

    req_img = sum(1 for s in scenes if s.get("image") or s.get("photo"))
    got_img = sum(1 for s in scenes if s.get("_photo"))
    n_data = sum(1 for s in scenes if isinstance(s.get("data"), dict))
    quality = (f"{total} scenes · voice {narrated - fallbacks}/{narrated} "
               f"expressive · imagery {got_img}/{req_img} · charts {n_data}")
    say("stitching…")
    _concat(ff, clips, out, silent=(narrated == 0))
    if os.environ.get("FORGE_MUSIC", "1") != "0":
        try:
            say("sound design…")
            from . import music as _music
            bed = work / "bed.wav"
            _music.ambient_bed(sum(durs), bed,
                               mood or _music.pick_mood(scenes))
            sfx = None
            if os.environ.get("FORGE_SFX", "0") == "1":
                # optional sound-design layer (off by default — the
                # transition sounds wore thin fast)
                events, t = [], 0.0
                for i, (sc, d) in enumerate(zip(scenes, durs)):
                    if i:
                        events.append(("whoosh", t - 0.18))
                    if isinstance(sc.get("data"), dict):
                        events.append(("tick", t + 1.25))
                    if str(sc.get("layout", "") or "").lower() == "punch" and i:
                        events.append(("riser", t - 0.9))
                    t += d
                sfx = work / "sfx.wav"
                _music.sfx_track(sum(durs), events, sfx)
            _mix_music(ff, out, bed, sfx)
        except Exception:
            import logging
            logging.getLogger("agent_forge.video").exception(
                "music bed failed; delivering without it")
    return {"path": out, "scenes": total, "narrated": narrated,
            "voiced": narrated > 0, "fallback": fallbacks,
            "quality": quality}


def _mix_music(ff: str, video: Path, bed: Path, sfx: Path | None = None) -> None:
    """Final mix, in place: the music bed DUCKS under the narration
    (sidechain compression keyed by the voice) and swells in the gaps;
    the sound-design layer sits on top at a low level."""
    tmp = video.with_name(video.stem + ".music.mp4")
    inputs = [ff, "-y", "-i", str(video), "-i", str(bed)]
    if sfx and sfx.exists():
        inputs += ["-i", str(sfx)]
        fc = ("[1:a]volume=0.42,afade=t=in:d=2.5[m];"
              "[m][0:a]sidechaincompress=threshold=0.02:ratio=10:"
              "attack=40:release=450[md];"
              "[2:a]volume=0.45[s];"
              "[0:a][md][s]amix=inputs=3:duration=first:"
              "dropout_transition=0:normalize=0[a]")
    else:
        fc = ("[1:a]volume=0.42,afade=t=in:d=2.5[m];"
              "[m][0:a]sidechaincompress=threshold=0.02:ratio=10:"
              "attack=40:release=450[md];"
              "[0:a][md]amix=inputs=2:duration=first:"
              "dropout_transition=0:normalize=0[a]")
    subprocess.run(
        inputs + ["-filter_complex", fc, "-map", "0:v", "-map", "[a]",
                  "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", str(tmp)],
        check=True, capture_output=True)
    tmp.replace(video)


def build_video(md_path: str | Path, on_progress=None,
                script_system: str | None = None,
                badge: str | None = None,
                voice_direction: str | None = None,
                mood: str | None = None,
                audio: bool = False,
                checkpoint=None,
                clips_dir: Path | None = None,
                scenes: list[dict] | None = None) -> dict:
    """Compile a dive markdown into a narrated (or silent-captioned) MP4.

    `checkpoint(kind, payload)` (optional) is called with
    ("script", scenes) the moment the script exists — BEFORE any TTS
    spend — so a durable job can resume from the script instead of
    re-buying script generation. Pass precomputed `scenes` (e.g. a
    checkpointed script.json) to skip generation entirely."""
    say = on_progress or (lambda _m: None)
    md_path = Path(md_path)
    essay = re.sub(r"^<!--.*?-->\s*", "", md_path.read_text(encoding="utf-8"), flags=re.S)

    if scenes is None:
        say("writing the script…")
        base_system = script_system or _SCRIPT_SYSTEM
        scenes = script_from_essay(
            essay,
            script_system=base_system + (AUDIO_SCRIPT_ADDENDUM if audio else ""),
            polish_note=AUDIO_POLISH_NOTE if audio else "")
    if not scenes:
        raise RuntimeError("script generation returned no scenes")
    if checkpoint is not None:
        # durable checkpoint: a script that can't be persisted
        # must stop the pipeline BEFORE any TTS spend
        checkpoint("script", scenes)
    m = re.search(r"^#\s+(.+)$", essay, re.M)
    title = m.group(1).strip() if m else None
    if audio:
        return render_podcast(
            scenes, EXPLORATIONS_DIR / (md_path.stem + ".m4a"),
            on_progress=say, voice_direction=voice_direction, mood=mood,
            clips_dir=clips_dir)
    out = EXPLORATIONS_DIR / (md_path.stem + ".mp4")
    return render_scenes(
        scenes, out, on_progress=say,
        title=title, badge=badge or "THE EXPLAINER",
        voice_direction=voice_direction or
        "You are a gifted storyteller sharing something that genuinely "
        "amazes you — natural, warm, alive. Real inflection: lean into "
        "the surprising word, drop for the aside, lift for the reveal.",
        mood=mood, clips_dir=clips_dir)


def _audio_dur(ff: str, mp3: Path) -> float:
    # ffprobe isn't bundled; parse ffmpeg -i stderr for Duration.
    p = subprocess.run([ff, "-i", str(mp3)], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", p.stderr)
    if not m:
        return 4.0
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def _concat(ff: str, clips: list[Path], out: Path, silent: bool) -> None:
    # every clip carries an audio stream now (real narration or anullsrc),
    # so a straight stream-copy concat is always correct
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(out)],
                   check=True, capture_output=True)
    lst.unlink(missing_ok=True)
