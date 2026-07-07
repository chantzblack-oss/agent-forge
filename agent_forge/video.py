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
VOICE = os.environ.get("FORGE_TTS_VOICE", "en-US-GuyNeural")


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# ── 1. script ────────────────────────────────────────────

_SCRIPT_SYSTEM = (
    "You are a video director adapting a researched essay into a narrated "
    "vertical-video script (think a smart, punchy explainer). Return 10-14 "
    "scenes. Each scene is one beat of narration the viewer HEARS plus a "
    "short headline they SEE.\n\n"
    "Rules:\n"
    "- narration: 1-3 spoken sentences, conversational, vivid, no markdown, "
    "no stage directions — just what the voice says. Open cold on the story; "
    "no 'in this video'.\n"
    "- headline: <= 7 words, the on-screen text for that beat (also serves "
    "as the caption for muted viewing).\n"
    "- kicker: 2-4 word eyebrow label.\n"
    "- Every fact/number must come from the essay; where it hedges, hedge.\n"
    "- Build momentum; end on the essay's most mind-bending point, then one "
    "closing beat that names the open question.\n"
    "Return ONLY a JSON array of {kicker, headline, narration}."
)


def script_from_essay(essay: str, script_system: str | None = None) -> list[dict]:
    raw = get_provider("anthropic").complete(
        system=script_system or _SCRIPT_SYSTEM, user=f"Essay:\n\n{essay}",
        model=WRITER_MODEL, max_tokens=4000,
    )
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    scenes = json.loads(m.group(0)) if m else []
    return [s for s in scenes if s.get("narration") and s.get("headline")]


# ── 2. narration (host only; silent fallback in sandbox) ──

def synth(text: str, out_mp3: Path) -> bool:
    """Synthesize narration to mp3. Returns True on success, False if TTS
    is unreachable (sandbox) so the caller falls back to a timed silent clip."""
    try:
        import edge_tts
        os.environ.setdefault("SSL_CERT_FILE", "/root/.ccr/ca-bundle.crt")
        proxy = os.environ.get("HTTPS_PROXY")

        async def _go():
            c = edge_tts.Communicate(text, VOICE, proxy=proxy)
            await c.save(str(out_mp3))

        asyncio.run(_go())
        return out_mp3.exists() and out_mp3.stat().st_size > 0
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
   display:flex;flex-direction:column;justify-content:center;padding:120px 96px;box-sizing:border-box}}
 .kicker{{color:#ff7a5e;font-weight:800;letter-spacing:.16em;text-transform:uppercase;font-size:34px;margin-bottom:40px}}
 .headline{{font-weight:800;font-size:96px;line-height:1.05;letter-spacing:-.02em}}
 .accent{{color:#35c2d6}}
 .n{{position:absolute;top:70px;right:96px;color:#3f5a63;font-size:30px;font-weight:700}}
 .bar{{position:absolute;left:96px;bottom:120px;height:8px;width:{barw}px;background:#ff7a5e;border-radius:99px}}
</style></head><body>
 <div class=n>{idx} / {total}</div>
 <div class=kicker>{kicker}</div>
 <div class=headline>{headline}</div>
 <div class=bar></div>
</body></html>"""


def _render_still(scene: dict, idx: int, total: int, out_png: Path) -> None:
    from playwright.sync_api import sync_playwright
    hl = (scene["headline"].replace("<", "&lt;"))
    html = _SLIDE_TMPL.format(
        w=W, h=H, idx=idx, total=total, barw=int(880 * idx / total),
        kicker=scene.get("kicker", "").replace("<", "&lt;"),
        headline=hl,
    )
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        htmlpath = f.name
    with sync_playwright() as p:
        exe = "/opt/pw-browsers/chromium"
        b = p.chromium.launch(executable_path=exe if os.path.exists(exe) else None)
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.goto("file://" + htmlpath)
        pg.wait_for_timeout(200)
        pg.screenshot(path=str(out_png))
        b.close()


# ── 4. assemble ──────────────────────────────────────────

def _clip(ff: str, png: Path, dur: float, out: Path, audio: Path | None) -> None:
    # Ken Burns slow zoom over the still.
    frames = max(1, int(dur * FPS))
    vf = (f"scale={W}:{H},zoompan=z='min(zoom+0.0006,1.10)':"
          f"d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H},"
          f"format=yuv420p")
    cmd = [ff, "-y", "-loop", "1", "-i", str(png)]
    if audio:
        cmd += ["-i", str(audio)]
    cmd += ["-t", f"{dur:.2f}", "-r", str(FPS), "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p"]
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
    clips: list[Path] = []
    narrated = 0
    total = len(scenes)
    for i, sc in enumerate(scenes, 1):
        say(f"scene {i}/{total}: {sc['headline']}")
        png = work / f"s{i:02d}.png"
        _render_still(sc, i, total, png)
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
