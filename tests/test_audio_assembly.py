"""TTS clip durability and the no-silent-omission rule."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_forge import video


def test_synthesis_key_stable_and_input_sensitive(monkeypatch):
    monkeypatch.delenv("FORGE_TTS_MODEL", raising=False)
    monkeypatch.delenv("FORGE_OPENAI_VOICE", raising=False)
    k1 = video._synthesis_key("hello world", "warm", "")
    assert k1 == video._synthesis_key("hello world", "warm", "")
    assert k1 != video._synthesis_key("hello world!", "warm", "")
    assert k1 != video._synthesis_key("hello world", "grave", "")
    monkeypatch.setenv("FORGE_OPENAI_VOICE", "nova")
    assert k1 != video._synthesis_key("hello world", "warm", "")


def _scenes(n=3):
    return [{"kicker": f"c{i}", "narration": f"line number {i}",
             "delivery": "neutral"} for i in range(n)]


def test_cached_clip_is_reused_without_any_tts_call(tmp_path, monkeypatch):
    scenes = _scenes(1)
    sc = scenes[0]
    notes = video._acting_notes(sc, "persona")
    key = video._synthesis_key(sc["narration"], notes, "")
    clips = tmp_path / "clips"
    clips.mkdir()
    cached = clips / f"{key}.mp3"
    cached.write_bytes(b"a" * 2000)                # a "finished" clip

    def no_tts(*a, **k):
        raise AssertionError("TTS was called for a cached clip")
    monkeypatch.setattr(video, "_openai_tts", no_tts)
    monkeypatch.setattr(video, "synth", no_tts)
    monkeypatch.setattr(video, "_audio_dur", lambda ff, p: 2.0)
    monkeypatch.setattr(video, "_ffmpeg", lambda: "ffmpeg")

    mp3s, durs, narrated, fallbacks = video._narrate_all(
        scenes, tmp_path, "ffmpeg", lambda m: None, "persona",
        clips_dir=clips)
    assert mp3s[0] == cached
    assert narrated == 1 and fallbacks == 0


def test_new_clip_lands_via_part_rename(tmp_path, monkeypatch):
    scenes = _scenes(1)
    clips = tmp_path / "clips"
    clips.mkdir()

    def fake_tts(text, out, *a, **k):
        Path(out).write_bytes(b"b" * 5000)
        return True
    monkeypatch.setattr(video, "_openai_tts", fake_tts)
    monkeypatch.setattr(video, "_audio_dur", lambda ff, p: 2.0)

    mp3s, *_ = video._narrate_all(
        scenes, tmp_path, "ffmpeg", lambda m: None, "p", clips_dir=clips)
    assert mp3s[0] is not None and mp3s[0].parent == clips
    assert mp3s[0].suffix == ".mp3"
    assert not list(clips.glob("*.part*"))         # nothing half-written


def test_missing_segment_refuses_assembly(tmp_path, monkeypatch):
    scenes = _scenes(3)

    def tts_fails_middle(text, out, *a, **k):
        if "number 1" in text:
            return False
        Path(out).write_bytes(b"c" * 5000)
        return True
    monkeypatch.setattr(video, "_openai_tts", tts_fails_middle)
    monkeypatch.setattr(video, "synth", lambda *a, **k: False)
    monkeypatch.setattr(video, "_audio_dur", lambda ff, p: 2.0)
    monkeypatch.setattr(video, "_ffmpeg", lambda: "ffmpeg")

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
        Path(out).write_bytes(b"d" * 5000)
        return True
    monkeypatch.setattr(video, "_openai_tts", flaky)
    monkeypatch.setattr(video, "synth", lambda *a, **k: False)
    monkeypatch.setattr(video, "_audio_dur", lambda ff, p: 2.0)
    monkeypatch.setattr(video, "_ffmpeg", lambda: "ffmpeg")

    with pytest.raises(video.NarrationIncomplete):
        video.render_podcast(scenes, tmp_path / "o.m4a", clips_dir=clips)
    calls.clear()
    # retry: only the missing segment goes back to TTS
    mp3s, *_ = video._narrate_all(
        scenes, tmp_path, "ffmpeg", lambda m: None, "", clips_dir=clips)
    assert all(m is not None for m in mp3s)
    assert len(calls) == 1 and "number 1" in calls[0]
