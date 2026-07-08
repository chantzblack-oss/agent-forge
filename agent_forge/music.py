"""Procedural ambient music bed — production polish with zero assets.

A quiet synthesized pad under the narration makes a video feel produced
instead of assembled. Everything is generated here in pure Python (soft
detuned sine partials, overlapping chords with smooth envelopes) so there
are no files to license, download, or ship — and the mood can follow the
script: a darker progression for grave material, a warmer one otherwise.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

_SR = 16000          # plenty for a low pad; keeps generation fast
_CHORD = 9.0         # seconds per chord
_PARTIALS = ((1.0, 1.0), (1.5, 0.55), (2.0, 0.45), (2.997, 0.12))

# progressions as root frequencies (chords are stacked fifths/octaves,
# so the root sequence carries the mood)
_MOODS = {
    # warm: Am - F - C - G territory
    "warm": (220.00, 174.61, 130.81, 196.00),
    # dark: low A minor drift
    "dark": (110.00, 130.81, 98.00, 87.31),
}


def pick_mood(scenes: list[dict]) -> str:
    """Darker bed when the script leans grave/hushed."""
    heavy = sum(1 for s in scenes
                if str(s.get("delivery", "")).lower() in ("grave", "hushed"))
    light = sum(1 for s in scenes
                if str(s.get("delivery", "")).lower() in ("bright", "hype"))
    return "dark" if heavy > light else "warm"


def sfx_track(total: float, events: list, out_wav: Path) -> Path:
    """Synthesize the sound-design layer: ('whoosh'|'tick'|'riser', t)
    events on a silent track the length of the video. Pure code — no
    asset files."""
    from array import array
    import random
    n = int(total * _SR)
    buf = array("f", bytes(4 * n))
    rnd = random.Random(7)

    def add(i, v):
        if 0 <= i < n:
            buf[i] += v

    for kind, t in events:
        s = int(max(t, 0) * _SR)
        if kind == "whoosh":            # a soft air sweep on a scene cut
            length = int(0.5 * _SR)
            for i in range(length):
                env = math.sin(math.pi * i / length) ** 2
                add(s + i, (rnd.random() * 2 - 1) * env * 0.5)
        elif kind == "tick":            # a chart element landing
            length = int(0.05 * _SR)
            for i in range(length):
                env = 1 - i / length
                add(s + i, math.sin(2 * math.pi * 1100 * i / _SR) * env * 0.6)
        elif kind == "riser":           # tension ramp into a punch card
            length = int(0.9 * _SR)
            for i in range(length):
                p = i / length
                f = 180 + 520 * p * p
                env = p * p * 0.55
                add(s + i, (math.sin(2 * math.pi * f * i / _SR) * 0.6
                            + (rnd.random() * 2 - 1) * 0.4) * env)

    peak = max(1e-6, max(abs(x) for x in buf))
    scale = min(0.5 / peak, 1.0)
    chunk = 65536
    with wave.open(str(out_wav), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(_SR)
        for lo in range(0, n, chunk):
            seg = buf[lo:lo + chunk]
            f.writeframes(struct.pack(
                f"<{len(seg)}h",
                *(int(max(-1.0, min(1.0, x * scale)) * 32767) for x in seg)))
    return out_wav


def ambient_bed(seconds: float, out_wav: Path, mood: str = "warm") -> Path:
    """Render `seconds` of ambient pad to a mono 16-bit wav.

    Memory-frugal on purpose (this runs on a small worker next to ffmpeg):
    samples live in a typed array (4 bytes each, not boxed floats) and the
    wav is written in chunks.
    """
    from array import array

    roots = _MOODS.get(mood, _MOODS["warm"])
    n = int(seconds * _SR)
    buf = array("f", bytes(4 * n))
    step = _CHORD / 2          # chords overlap halfway for a seamless pad
    ci = 0
    t = 0.0
    while t < seconds:
        root = roots[ci % len(roots)]
        start = int(t * _SR)
        length = min(int(_CHORD * _SR), n - start)
        if length <= 0:
            break
        for ratio, amp in _PARTIALS:
            for detune in (0.9985, 1.0015):     # slow beating = motion
                f = root * ratio * detune
                w = 2 * math.pi * f / _SR
                a = amp * 0.5
                for i in range(length):
                    # sin^2 envelope: silent at both ends of the chord
                    env = math.sin(math.pi * i / length) ** 2
                    buf[start + i] += a * env * math.sin(w * i)
        ci += 1
        t += step
    peak = max(1e-6, max(abs(x) for x in buf))
    scale = 0.6 / peak
    chunk = 65536
    with wave.open(str(out_wav), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(_SR)
        for lo in range(0, n, chunk):
            seg = buf[lo:lo + chunk]
            f.writeframes(struct.pack(
                f"<{len(seg)}h",
                *(int(max(-1.0, min(1.0, x * scale)) * 32767) for x in seg)))
    return out_wav
