"""Durable job state: atomicity, failure accounting, ledger, retention."""

from __future__ import annotations

import json
import os

import pytest

from agent_forge import job_state as js


@pytest.fixture(autouse=True)
def _tmp_volume(tmp_path, monkeypatch):
    monkeypatch.setattr(js, "EXPLORATIONS_DIR", tmp_path)
    yield tmp_path


def test_create_persists_schema_v2():
    job = js.STORE.create("lesson", "audio", "volcanoes", 42)
    on_disk = json.loads(job.path("state.json").read_text())
    assert on_disk["schema_version"] == 2
    assert on_disk["mode"] == "audio"
    assert on_disk["stage"] == "accepted"
    assert on_disk["chat_id"] == 42


def test_stage_history_recorded():
    job = js.STORE.create("story", "video", "case", 1)
    job.set_stage("researching")
    job.set_stage("document_ready")
    stages = [h["stage"] for h in job.d["stage_history"]]
    assert stages == ["accepted", "researching", "document_ready"]


def test_crashed_write_never_corrupts_last_good_state(monkeypatch):
    job = js.STORE.create("deep", "document", "q", 1)
    job.set_stage("researching")
    good = job.path("state.json").read_text()

    def boom(src, dst):
        raise OSError("disk died mid-replace")
    with monkeypatch.context() as m:      # scoped: only os.replace breaks
        m.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            job.set_stage("document_ready")
    assert job.path("state.json").read_text() == good
    reloaded = js.STORE.load(job.id)
    assert reloaded.stage == "researching"


def test_mode_survives_reload():
    job = js.STORE.create("lesson", "audio", "t", 1)
    assert js.STORE.load(job.id).mode == "audio"


def test_record_failure_counts_per_stage():
    job = js.STORE.create("lesson", "audio", "t", 1)
    assert job.record_failure("full_tts", "boom") == 1
    assert job.record_failure("full_tts", "boom") == 2
    assert job.record_failure("mixed", "boom") == 1
    assert js.STORE.load(job.id).d["stage_failures"]["full_tts"] == 2


def test_ledger_survives_and_caps():
    for _ in range(3):
        js.STORE.ledger_add("job")
    assert js.STORE.ledger_count_24h() == 3
    # a "restart" = fresh read from disk, not a fresh count
    assert js.JobStore().ledger_count_24h() == 3


def test_legacy_payload_detected():
    js.atomic_write_json(js._pointer_path(),
                         {"kind": "lesson", "topic": "x", "chat": 9,
                          "doc": None})
    assert js.STORE.legacy_payload() == {
        "kind": "lesson", "topic": "x", "chat": 9, "doc": None}
    js.atomic_write_json(js._pointer_path(), {"job_id": "abc"})
    assert js.STORE.legacy_payload() is None


def test_retention_sweep():
    delivered = js.STORE.create("lesson", "audio", "old", 1)
    (delivered.clips_dir / "k.mp3").write_bytes(b"x" * 10)
    (delivered.dir / "junk.mp3.part").write_bytes(b"y")
    delivered.set_stage("delivered")

    stale = js.STORE.create("story", "video", "stale", 1)
    stale.set_stage("needs_attention")
    stale.d["updated_at"] = 0            # ancient
    js.atomic_write_json(stale.path("state.json"), stale.d)

    fresh = js.STORE.create("sim", "audio", "fresh", 1)
    fresh.set_stage("needs_attention")

    js.STORE.sweep()
    assert not (delivered.dir / "clips").exists()      # clips dropped
    assert not (delivered.dir / "junk.mp3.part").exists()
    assert delivered.path("state.json").exists()       # state retained
    assert not stale.dir.exists()                      # expired failure
    assert fresh.dir.exists()                          # recent failure kept
