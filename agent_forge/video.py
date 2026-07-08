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
    "vertical-video script (think a smart, punchy explainer). Return 7-14 "
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
    "- narration: 1-3 spoken sentences, HARD MAX 40 words (a scene should "
    "run 8-15 seconds — long monologues kill the pace; split big ideas "
    "into more scenes), no markdown, no stage directions — "
    "just what the voice says. Write like a person actually talks: "
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
    "muted #5d7a84. Text >= 26px. A visual is REQUIRED on every scene that "
    "explains a mechanism, number, comparison, or sequence — typography-only "
    "is acceptable only for pure emotional beats (max 3 per video).\n"
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
    "- Every fact/number must come from the essay; where it hedges, hedge.\n"
    "- Build momentum; end on the essay's most mind-bending point, then one "
    "closing beat that names the open question.\n"
    "Return ONLY a JSON array of {kicker, headline, narration, pose, "
    "delivery, read, visual?}."
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
    return [s for s in scenes
            if isinstance(s, dict) and s.get("narration") and s.get("headline")]


def script_from_essay(essay: str, script_system: str | None = None) -> list[dict]:
    system = script_system or _SCRIPT_SYSTEM
    provider = get_provider("anthropic")
    raw = provider.complete(
        system=system, user=f"Essay:\n\n{essay}",
        model=WRITER_MODEL, max_tokens=16000,
    )
    scenes = _parse_scenes(raw)
    if scenes:
        return scenes
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
    return _parse_scenes(raw2)


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


def _acting_notes(scene: dict) -> str:
    base = _DELIVERY_NOTES.get(
        str(scene.get("delivery", "")).strip().lower(),
        _DELIVERY_NOTES["neutral"])
    read = str(scene.get("read", "") or "").strip()
    return f"{base} {read}" if read else base


# Debate mode: scenes may carry speaker 'a' or 'b'; each speaker keeps a
# consistent voice across the video, on both TTS paths.
def _speaker_openai_voice(spk: str) -> str | None:
    if spk == "a":
        return os.environ.get("FORGE_OPENAI_VOICE", "ash")
    if spk == "b":
        return os.environ.get("FORGE_OPENAI_VOICE_B", "coral")
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
    """Expressive narration via OpenAI TTS. Returns False (so the caller
    falls back to edge-tts) when no key is set or the call fails."""
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    try:
        from openai import OpenAI
        resp = OpenAI().audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=voice or os.environ.get("FORGE_OPENAI_VOICE", "ash"),
            input=text, instructions=instructions,
        )
        out_mp3.write_bytes(resp.content)
        return out_mp3.exists() and out_mp3.stat().st_size > 0
    except Exception:
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
   opacity:0;animation:rise .8s .1s ease-out forwards}}
 .kicker{{color:#ff7a5e;font-weight:800;letter-spacing:.16em;text-transform:uppercase;font-size:34px;margin-bottom:30px;
   opacity:0;animation:rise .6s .15s ease-out forwards}}
 .headline{{font-weight:800;font-size:{hlsize}px;line-height:1.05;letter-spacing:-.02em}}
 .headline .w{{display:inline-block;opacity:0;transform:translateY(26px);
   animation:wordin .55s ease-out forwards}}
 @keyframes wordin{{to{{opacity:1;transform:none}}}}
 .accent{{color:#35c2d6}}
 .caption{{margin-top:44px;position:relative;min-height:300px}}
 .cap{{position:absolute;top:0;left:0;font-size:{capsize}px;line-height:1.45;
   color:#b8d2d8;max-width:760px;opacity:0;transform:translateY(18px)}}
 @keyframes capin{{to{{opacity:1;transform:none}}}}
 @keyframes capout{{to{{opacity:0;transform:translateY(-14px)}}}}
 .viz{{margin-top:56px;opacity:0;animation:rise .8s {vizdelay}s ease-out forwards}}
 .viz svg{{width:100%;height:auto;display:block;max-height:640px}}
 .viz svg > *{{opacity:0;animation:vizin .5s ease-out forwards}}
 @keyframes vizin{{to{{opacity:1}}}}
 @keyframes rise{{from{{opacity:0;transform:translateY(22px)}}to{{opacity:1;transform:none}}}}
 .n{{position:absolute;top:70px;right:96px;color:#3f5a63;font-size:30px;font-weight:700;
   opacity:0;animation:rise .6s .2s ease-out forwards}}
 .bar{{position:absolute;left:96px;bottom:120px;height:8px;background:#ff7a5e;border-radius:99px;
   width:0;animation:grow {dur}s linear forwards}}
 @keyframes grow{{to{{width:{barw}px}}}}
</style></head><body>
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
  // stagger svg children so diagrams draw themselves in
  document.querySelectorAll('.viz svg > *').forEach(function(el, i) {{
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


_SVG_FORBIDDEN = re.compile(
    r"<\s*(script|foreignObject|iframe)|href\s*=|url\s*\(|javascript:", re.I
)


def _safe_visual(scene: dict) -> str:
    """Return the scene's SVG wrapped for layout, or '' if absent/unsafe."""
    svg = (scene.get("visual") or "").strip()
    if not svg or "<svg" not in svg.lower():
        return ""
    if _SVG_FORBIDDEN.search(svg):
        return ""
    return f'<div class="viz">{svg}</div>'


def _caption_html(narration: str, dur: float) -> str:
    """Live captions: the narration plays sentence-by-sentence in sync with
    the voice — each line fades in as it's spoken and out when done. No
    truncation, and the frame keeps moving for the whole scene."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", narration)
             if s.strip()]
    if not sents:
        return ""
    total_chars = sum(len(s) for s in sents) or 1
    lead, tail = 0.45, 0.8          # breath in, settle out
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
    viz = _safe_visual(scene)
    caption = _caption_html(scene.get("narration", ""), max(dur, 3.0))
    host = _host_html(scene, has_viz=bool(viz))
    return _SLIDE_TMPL.format(
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


def _record_scenes(scenes: list[dict], durs: list[float],
                   workdir: Path, say) -> list[Path]:
    """Record each scene as ANIMATED video (CSS motion design captured from a
    real browser) in one low-memory browser, fully closed before ffmpeg."""
    from playwright.sync_api import sync_playwright
    total = len(scenes)
    webms: list[Path] = []
    exe = "/opt/pw-browsers/chromium"

    def _launch(p):
        return p.chromium.launch(
            executable_path=exe if os.path.exists(exe) else None,
            args=_LOWMEM_ARGS)

    def _one(b, sc, i, dur) -> Path:
        recdir = workdir / f"rec{i:02d}"
        ctx = b.new_context(
            viewport={"width": W, "height": H},
            record_video_dir=str(recdir),
            record_video_size={"width": W, "height": H})
        pg = ctx.new_page()
        with tempfile.NamedTemporaryFile(
                "w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(_scene_html(sc, i, total, dur))
            htmlpath = f.name
        try:
            pg.goto("file://" + htmlpath)
            pg.wait_for_timeout(int(dur * 1000))
            ctx.close()  # finalizes the recording
        finally:
            os.unlink(htmlpath)
        vids = sorted(recdir.glob("*.webm"),
                      key=lambda v: v.stat().st_size, reverse=True)
        if not vids or vids[0].stat().st_size == 0:
            raise RuntimeError(f"scene {i} recording missing")
        return vids[0]

    with sync_playwright() as p:
        b = _launch(p)
        for i, (sc, dur) in enumerate(zip(scenes, durs), 1):
            say(f"animating {i}/{total}: {sc['headline']}")
            try:
                webms.append(_one(b, sc, i, dur))
            except Exception:
                # Low-mem single-process Chromium occasionally dies while a
                # recording finalizes; relaunch and retry the scene once.
                try:
                    b.close()
                except Exception:
                    pass
                b = _launch(p)
                webms.append(_one(b, sc, i, dur))
        b.close()
    return webms


# ── 4. assemble ──────────────────────────────────────────

def _clip(ff: str, webm: Path, dur: float, out: Path, audio: Path | None) -> None:
    # Transcode the recorded animation to h264 and lay the narration under it.
    cmd = [ff, "-y", "-i", str(webm)]
    if audio:
        cmd += ["-i", str(audio)]
    # dip-to-black on both ends so scene cuts read as edits, not glitches
    cmd += ["-t", f"{dur:.2f}", "-r", str(FPS),
            "-vf", (f"scale={W}:{H},fade=t=in:st=0:d=0.22,"
                    f"fade=t=out:st={max(dur - 0.35, 0.5):.2f}:d=0.35,"
                    f"format=yuv420p"),
            "-threads", "1",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    if audio:
        # delay the line slightly so each scene opens with a breath
        cmd += ["-af", "adelay=350:all=1", "-c:a", "aac", "-b:a", "160k"]
    cmd += [str(out)]
    subprocess.run(cmd, check=True, capture_output=True)


def render_scenes(scenes: list[dict], out: Path, on_progress=None) -> dict:
    """Narrate, record and stitch a scene list into an MP4 at `out`."""
    say = on_progress or (lambda _m: None)
    work = Path(tempfile.mkdtemp(prefix="forge_video_"))
    ff = _ffmpeg()
    total = len(scenes)
    # Phase 1: narration first — scene durations come from the audio.
    mp3s: list[Path | None] = []
    durs: list[float] = []
    narrated = 0
    for i, sc in enumerate(scenes, 1):
        say(f"narrating {i}/{total}")
        mp3 = work / f"s{i:02d}.mp3"
        rate, pitch = _delivery(sc)
        spk = str(sc.get("speaker", "") or "").strip().lower()
        if (_openai_tts(sc["narration"], mp3, _acting_notes(sc),
                        voice=_speaker_openai_voice(spk))
                or synth(sc["narration"], mp3, rate=rate, pitch=pitch,
                         voice=_speaker_edge_voice(spk))):
            narrated += 1
            mp3s.append(mp3)
            # 0.35s breath before the line + a beat to settle after it
            durs.append(_audio_dur(ff, mp3) + 0.95)
        else:
            mp3s.append(None)
            durs.append(_reading_seconds(sc["narration"]))
    # Phase 2: record animated scenes (one browser, closed before ffmpeg).
    webms = _record_scenes(scenes, durs, work, say)
    # Phase 3: mux narration under each animation.
    clips: list[Path] = []
    for i in range(total):
        say(f"encoding {i + 1}/{total}")
        clip = work / f"c{i + 1:02d}.mp4"
        _clip(ff, webms[i], durs[i], clip, mp3s[i])
        clips.append(clip)

    say("stitching…")
    _concat(ff, clips, out, silent=(narrated == 0))
    if os.environ.get("FORGE_MUSIC", "1") != "0":
        try:
            say("laying the music bed…")
            from . import music as _music
            bed = work / "bed.wav"
            _music.ambient_bed(sum(durs), bed, _music.pick_mood(scenes))
            _mix_music(ff, out, bed)
        except Exception:
            import logging
            logging.getLogger("agent_forge.video").exception(
                "music bed failed; delivering without it")
    return {"path": out, "scenes": total, "narrated": narrated,
            "voiced": narrated > 0}


def _mix_music(ff: str, video: Path, bed: Path) -> None:
    """Mix the ambient bed quietly under the finished video, in place."""
    tmp = video.with_name(video.stem + ".music.mp4")
    subprocess.run(
        [ff, "-y", "-i", str(video), "-i", str(bed),
         "-filter_complex",
         "[1:a]volume=0.15,afade=t=in:d=2.5[m];"
         "[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
         "-map", "0:v", "-map", "[a]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", str(tmp)],
        check=True, capture_output=True)
    tmp.replace(video)


def build_video(md_path: str | Path, on_progress=None,
                script_system: str | None = None) -> dict:
    """Compile a dive markdown into a narrated (or silent-captioned) MP4."""
    say = on_progress or (lambda _m: None)
    md_path = Path(md_path)
    essay = re.sub(r"^<!--.*?-->\s*", "", md_path.read_text(encoding="utf-8"), flags=re.S)

    say("writing the script…")
    scenes = script_from_essay(essay, script_system=script_system)
    if not scenes:
        raise RuntimeError("script generation returned no scenes")
    out = EXPLORATIONS_DIR / (md_path.stem + ".mp4")
    return render_scenes(scenes, out, on_progress=say)


def _audio_dur(ff: str, mp3: Path) -> float:
    # ffprobe isn't bundled; parse ffmpeg -i stderr for Duration.
    p = subprocess.run([ff, "-i", str(mp3)], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", p.stderr)
    if not m:
        return 4.0
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def _concat(ff: str, clips: list[Path], out: Path, silent: bool) -> None:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if silent:
        # add a silent audio track so players that require audio still play
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-c:v", "copy", "-c:a", "aac", "-shortest"]
    else:
        cmd += ["-c", "copy"]
    cmd += [str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    lst.unlink(missing_ok=True)
