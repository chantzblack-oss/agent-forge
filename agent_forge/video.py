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
    "vertical-video script (think a smart, punchy explainer). Return 9-12 "
    "scenes. Each scene is one beat of narration the viewer HEARS plus a "
    "short headline they SEE.\n\n"
    "Rules:\n"
    "- narration: 1-3 spoken sentences, conversational, vivid, no markdown, "
    "no stage directions — just what the voice says. Open cold on the story; "
    "no 'in this video'.\n"
    "- headline: <= 7 words, the on-screen text for that beat (also serves "
    "as the caption for muted viewing).\n"
    "- kicker: 2-4 word eyebrow label.\n"
    "- visual: for scenes where a picture teaches more than words, an inline "
    "SVG diagram for that exact beat (viewBox='0 0 880 700', no external "
    "refs, no <script>; the ENTIRE svg must be ONE line — JSON strings "
    "cannot contain raw newlines — and each svg must stay under 900 "
    "characters: simple shapes and labels, not artwork). Design real diagrams: graphs with labeled nodes, "
    "timelines, before/after, flows with arrows, simple scene illustrations. "
    "Palette on dark: ink #eaf3f2, accent #ff7a5e, accent2 #35c2d6, "
    "muted #5d7a84. Text >= 26px. A visual is REQUIRED on every scene that "
    "explains a mechanism, number, comparison, or sequence — typography-only "
    "is acceptable only for pure emotional beats (max 3 per video).\n"
    "- Every fact/number must come from the essay; where it hedges, hedge.\n"
    "- Build momentum; end on the essay's most mind-bending point, then one "
    "closing beat that names the open question.\n"
    "Return ONLY a JSON array of {kicker, headline, narration, visual?}."
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
        model=WRITER_MODEL, max_tokens=24000,
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
        model=WRITER_MODEL, max_tokens=24000,
    )
    return _parse_scenes(raw2)


# ── 2. narration (host only; silent fallback in sandbox) ──

def synth(text: str, out_mp3: Path) -> bool:
    """Synthesize narration to mp3. Returns True on success, False if TTS
    is unreachable (sandbox) so the caller falls back to a timed silent clip."""
    try:
        import edge_tts
        os.environ.setdefault("SSL_CERT_FILE", "/root/.ccr/ca-bundle.crt")
        proxy = os.environ.get("HTTPS_PROXY")

        async def _go(voice):
            c = edge_tts.Communicate(text, voice, rate="+4%", proxy=proxy)
            await c.save(str(out_mp3))

        for voice in (VOICE, "en-US-GuyNeural"):
            try:
                asyncio.run(_go(voice))
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
   display:flex;flex-direction:column;justify-content:center;padding:110px 96px;box-sizing:border-box;position:relative}}
 .orb{{position:absolute;top:-260px;right:-260px;width:680px;height:680px;border-radius:50%;
   background:radial-gradient(circle at 35% 35%,rgba(53,194,214,.20),rgba(53,194,214,0) 65%)}}
 .orb2{{position:absolute;bottom:-320px;left:-280px;width:760px;height:760px;border-radius:50%;
   background:radial-gradient(circle at 60% 40%,rgba(255,122,94,.13),rgba(255,122,94,0) 65%)}}
 .bignum{{position:absolute;top:44px;left:96px;font-size:150px;font-weight:800;
   color:rgba(53,194,214,.10);letter-spacing:-.04em;line-height:1}}
 .kicker{{color:#ff7a5e;font-weight:800;letter-spacing:.16em;text-transform:uppercase;font-size:34px;margin-bottom:30px}}
 .headline{{font-weight:800;font-size:{hlsize}px;line-height:1.05;letter-spacing:-.02em}}
 .accent{{color:#35c2d6}}
 .caption{{margin-top:44px;font-size:36px;line-height:1.5;color:#a7c2c9;max-width:860px}}
 .viz{{margin-top:56px}}
 .viz svg{{width:100%;height:auto;display:block;max-height:640px}}
 .n{{position:absolute;top:70px;right:96px;color:#3f5a63;font-size:30px;font-weight:700}}
 .bar{{position:absolute;left:96px;bottom:120px;height:8px;width:{barw}px;background:#ff7a5e;border-radius:99px}}
</style></head><body>
 <div class=orb></div><div class=orb2></div>
 <div class=bignum>{idx:02d}</div>
 <div class=n>{idx} / {total}</div>
 <div class=kicker>{kicker}</div>
 <div class=headline>{headline}</div>
 {viz}
 <div class=caption>{caption}</div>
 <div class=bar></div>
</body></html>"""


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


def _scene_html(scene: dict, idx: int, total: int) -> str:
    hl = (scene["headline"].replace("<", "&lt;"))
    viz = _safe_visual(scene)
    caption = scene.get("narration", "").replace("<", "&lt;")
    if len(caption) > 240:
        caption = caption[:237] + "…"
    return _SLIDE_TMPL.format(
        w=W, h=H, idx=idx, total=total, barw=int(880 * idx / total),
        kicker=scene.get("kicker", "").replace("<", "&lt;"),
        headline=hl,
        hlsize=72 if viz else 92,   # smaller headline when a diagram shares the frame
        viz=viz,
        caption=caption,
    )


# Chromium flags that roughly halve its footprint — required to fit video
# rendering inside a 512MB worker instance.
_LOWMEM_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                "--renderer-process-limit=1", "--no-zygote", "--single-process"]


def _render_all_stills(scenes: list[dict], workdir: Path, say) -> list[Path]:
    """Render every scene still in ONE low-memory browser session, then close
    it completely before any ffmpeg work starts (peak-memory discipline)."""
    from playwright.sync_api import sync_playwright
    total = len(scenes)
    pngs: list[Path] = []
    exe = "/opt/pw-browsers/chromium"
    with sync_playwright() as p:
        b = p.chromium.launch(
            executable_path=exe if os.path.exists(exe) else None,
            args=_LOWMEM_ARGS)
        pg = b.new_page(viewport={"width": W, "height": H})
        for i, sc in enumerate(scenes, 1):
            say(f"scene {i}/{total}: {sc['headline']}")
            with tempfile.NamedTemporaryFile(
                    "w", suffix=".html", delete=False, encoding="utf-8") as f:
                f.write(_scene_html(sc, i, total))
                htmlpath = f.name
            pg.goto("file://" + htmlpath)
            pg.wait_for_timeout(150)
            png = workdir / f"s{i:02d}.png"
            pg.screenshot(path=str(png))
            pngs.append(png)
            os.unlink(htmlpath)
        b.close()
    return pngs


# ── 4. assemble ──────────────────────────────────────────

def _clip(ff: str, png: Path, dur: float, out: Path, audio: Path | None) -> None:
    # Ken Burns slow zoom over the still.
    frames = max(1, int(dur * FPS))
    vf = (f"scale={W}:{H},zoompan=z='min(zoom+0.0006,1.10)':"
          f"d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H},"
          f"fade=t=in:st=0:d=0.35,format=yuv420p")
    cmd = [ff, "-y", "-loop", "1", "-i", str(png)]
    if audio:
        cmd += ["-i", str(audio)]
    cmd += ["-t", f"{dur:.2f}", "-r", str(FPS), "-vf", vf,
            "-threads", "1",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += [str(out)]
    subprocess.run(cmd, check=True, capture_output=True)


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

    work = Path(tempfile.mkdtemp(prefix="forge_video_"))
    ff = _ffmpeg()
    # Phase 1: all stills in one browser session, fully closed before ffmpeg
    # ever runs — Chromium and ffmpeg together exceed a 512MB instance.
    pngs = _render_all_stills(scenes, work, say)
    clips: list[Path] = []
    narrated = 0
    total = len(scenes)
    for i, sc in enumerate(scenes, 1):
        say(f"encoding {i}/{total}")
        png = pngs[i - 1]
        mp3 = work / f"s{i:02d}.mp3"
        has_audio = synth(sc["narration"], mp3)
        narrated += 1 if has_audio else 0
        if has_audio:
            dur = _audio_dur(ff, mp3) + 0.4
        else:
            dur = _reading_seconds(sc["narration"])
        clip = work / f"c{i:02d}.mp4"
        _clip(ff, png, dur, clip, mp3 if has_audio else None)
        clips.append(clip)

    say("stitching…")
    out = EXPLORATIONS_DIR / (md_path.stem + ".mp4")
    _concat(ff, clips, out, silent=(narrated == 0))
    return {"path": out, "scenes": total, "narrated": narrated,
            "voiced": narrated > 0}


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
