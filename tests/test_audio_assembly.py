"""TTS clip durability, provenance, validation, and the
no-silent-omission rule. Uses real ffmpeg-generated audio so the
decode-validation path is exercised for real."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_forge import video

FF = video._ffmpeg()


def _real_mp3(path: Path, seconds: float = 0.4) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([FF, "-y", "-f", "lavfi", "-t", str(seconds),
                    "-i", "sine=frequency=300:sample_rate=24000",
                    "-q:a", "7", str(path)],
                   check=True, capture_output=True)
    return path


def _tts_writes_real_audio(text, out, *a, **k):
    _real_mp3(Path(out))
    return True


def _scenes(n=3):
    return [{"kicker": f"c{i}", "narration": f"line number {i}",
             "delivery": "neutral"} for i in range(n)]


# ── synthesis keys ─────────────────────────────────────────

def test_synthesis_key_stable_and_input_sensitive(monkeypatch):
    monkeypatch.delenv("FORGE_TTS_MODEL", raising=False)
    monkeypatch.delenv("FORGE_OPENAI_VOICE", raising=False)
    k1 = video._synthesis_key("hello world", "warm", "")
    assert k1 == video._synthesis_key("hello world", "warm", "")
    assert k1 != video._synthesis_key("hello world!", "warm", "")
    assert k1 != video._synthesis_key("hello world", "grave", "")
    monkeypatch.setenv("FORGE_OPENAI_VOICE", "nova")
    assert k1 != video._synthesis_key("hello world", "warm", "")


def test_provider_separates_keys_and_edge_includes_rate():
    base = video._synthesis_key("text", "n", "")
    edge1 = video._synthesis_key("text", "n", "", "edge", "+4%", "+0Hz")
    edge2 = video._synthesis_key("text", "n", "", "edge", "+9%", "+0Hz")
    assert base != edge1
    assert edge1 != edge2                    # rate is sound-affecting


# ── cache reuse and provenance ─────────────────────────────

def test_cached_openai_clip_reused_without_tts(tmp_path, monkeypatch):
    scenes = _scenes(1)
    sc = scenes[0]
    notes = video._acting_notes(sc, "persona")
    key = video._synthesis_key(sc["narration"], notes, "")
    clips = tmp_path / "clips"
    cached = _real_mp3(clips / f"{key}.mp3")

    def no_tts(*a, **k):
        raise AssertionError("TTS was called for a cached clip")
    monkeypatch.setattr(video, "_openai_tts", no_tts)
    monkeypatch.setattr(video, "synth", no_tts)

    mp3s, durs, narrated, fallbacks = video._narrate_all(
        scenes, tmp_path, FF, lambda m: None, "persona", clips_dir=clips)
    assert mp3s[0] == cached
    assert narrated == 1 and fallbacks == 0


def test_fallback_provenance_survives_restart(tmp_path, monkeypatch):
    """OpenAI down -> Edge clip cached under its own name. A later run
    with OpenAI still down reuses it and STILL reports fallback=True."""
    scenes = _scenes(1)
    clips = tmp_path / "clips"
    monkeypatch.setattr(video, "_openai_tts", lambda *a, **k: False)
    monkeypatch.setattr(
        video, "synth",
        lambda text, out, **k: bool(_real_mp3(Path(out))))

    mp3s, _d, _n, fallbacks = video._narrate_all(
        scenes, tmp_path, FF, lambda m: None, "", clips_dir=clips)
    assert fallbacks == 1
    assert mp3s[0].name.endswith(".edge.mp3")     # provenance in the name

    # "restart": edge cached, OpenAI still down, synth must NOT rerun
    def no_edge(*a, **k):
        raise AssertionError("edge re-synthesized a cached clip")
    monkeypatch.setattr(video, "synth", no_edge)
    mp3s2, _d, _n, fallbacks2 = video._narrate_all(
        scenes, tmp_path, FF, lambda m: None, "", clips_dir=clips)
    assert mp3s2[0] == mp3s[0]
    assert fallbacks2 == 1                        # still reported honestly


def test_restored_openai_upgrades_fallback_clip(tmp_path, monkeypatch):
    scenes = _scenes(1)
    clips = tmp_path / "clips"
    monkeypatch.setattr(video, "_openai_tts", lambda *a, **k: False)
    monkeypatch.setattr(
        video, "synth",
        lambda text, out, **k: bool(_real_mp3(Path(out))))
    video._narrate_all(scenes, tmp_path, FF, lambda m: None, "",
                       clips_dir=clips)
    # OpenAI comes back: the fallback clip is superseded, not reused
    monkeypatch.setattr(video, "_openai_tts", _tts_writes_real_audio)
    mp3s, _d, _n, fallbacks = video._narrate_all(
        scenes, tmp_path, FF, lambda m: None, "", clips_dir=clips)
    assert fallbacks == 0
    assert not mp3s[0].name.endswith(".edge.mp3")


def test_corrupt_cached_clip_rejected(tmp_path, monkeypatch):
    """A >1000-byte file of garbage must not pass as finished audio."""
    scenes = _scenes(1)
    sc = scenes[0]
    notes = video._acting_notes(sc, "persona")
    key = video._synthesis_key(sc["narration"], notes, "")
    clips = tmp_path / "clips"
    clips.mkdir()
    (clips / f"{key}.mp3").write_bytes(b"\x00" * 5000)   # corrupt

    monkeypatch.setattr(video, "_openai_tts", _tts_writes_real_audio)
    mp3s, *_ = video._narrate_all(
        scenes, tmp_path, FF, lambda m: None, "persona", clips_dir=clips)
    assert mp3s[0] is not None
    assert video._clip_valid(FF, mp3s[0])        # replaced with real audio


def test_invalid_tts_bytes_never_promoted(tmp_path, monkeypatch):
    """TTS that returns undecodable bytes must not produce a cached clip."""
    scenes = _scenes(1)
    clips = tmp_path / "clips"

    def garbage_tts(text, out, *a, **k):
        Path(out).write_bytes(b"not audio" * 500)
        return True
    monkeypatch.setattr(video, "_openai_tts", garbage_tts)
    monkeypatch.setattr(video, "synth", lambda *a, **k: False)
    mp3s, *_ = video._narrate_all(
        scenes, tmp_path, FF, lambda m: None, "", clips_dir=clips)
    assert mp3s[0] is None
    assert not list(clips.glob("*.mp3"))         # nothing promoted
    assert not list(clips.glob("*.part*"))       # nothing half-written


def test_clip_metadata_sidecar_written(tmp_path, monkeypatch):
    import json
    scenes = _scenes(1)
    clips = tmp_path / "clips"
    monkeypatch.setattr(video, "_openai_tts", _tts_writes_real_audio)
    mp3s, *_ = video._narrate_all(
        scenes, tmp_path, FF, lambda m: None, "", clips_dir=clips)
    meta = json.loads(mp3s[0].with_suffix(".json").read_text())
    assert meta["provider"] == "openai"
    assert meta["fallback"] is False
    assert meta["duration"] > 0 and meta["size"] > 0


def test_duplicate_identical_scenes_do_not_race(tmp_path, monkeypatch):
    """Two scenes with identical text/notes share a synthesis key; the
    per-attempt unique temp files mean both attempts commit safely."""
    scenes = [{"kicker": "a", "narration": "identical line",
               "delivery": "neutral"},
              {"kicker": "b", "narration": "identical line",
               "delivery": "neutral"}]
    clips = tmp_path / "clips"
    monkeypatch.setattr(video, "_openai_tts", _tts_writes_real_audio)
    mp3s, *_ = video._narrate_all(
        scenes, tmp_path, FF, lambda m: None, "", clips_dir=clips)
    assert mp3s[0] is not None and mp3s[1] is not None
    assert not list(clips.glob("*.part*"))


# ── no silent omission ────────────────────────────────────

def test_missing_segment_refuses_assembly(tmp_path, monkeypatch):
    scenes = _scenes(3)

    def tts_fails_middle(text, out, *a, **k):
        if "number 1" in text:
            return False
        return _tts_writes_real_audio(text, out)
    monkeypatch.setattr(video, "_openai_tts", tts_fails_middle)
    monkeypatch.setattr(video, "synth", lambda *a, **k: False)

    with pytest.raises(video.NarrationIncomplete) as ei:
        video.render_podcast(scenes, tmp_path / "out.m4a",
                             clips_dir=tmp_path / "clips")
    assert ei.value.missing == [1]
    assert ei.value.total == 3
    # the two good clips survived for the retry
    assert len(list((tmp_path / "clips").glob("*.mp3"))) == 2


def test_retry_after_partial_failure_only_pays_for_missing(tmp_path,
                                                           monkeypatch):
    scenes = _scenes(3)
    clips = tmp_path / "clips"
    calls: list[str] = []
    attempts = {"number 1": 0}

    def flaky(text, out, *a, **k):
        calls.append(text)
        if "number 1" in text:
            attempts["number 1"] += 1
            if attempts["number 1"] == 1:
                return False                      # fails only first time
        return _tts_writes_real_audio(text, out)
    monkeypatch.setattr(video, "_openai_tts", flaky)
    monkeypatch.setattr(video, "synth", lambda *a, **k: False)

    with pytest.raises(video.NarrationIncomplete):
        video.render_podcast(scenes, tmp_path / "o.m4a", clips_dir=clips)
    calls.clear()
    # retry: only the missing segment goes back to TTS
    mp3s, *_ = video._narrate_all(
        scenes, tmp_path, FF, lambda m: None, "", clips_dir=clips)
    assert all(m is not None for m in mp3s)
    assert len(calls) == 1 and "number 1" in calls[0]
