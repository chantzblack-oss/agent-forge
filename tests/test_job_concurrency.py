"""Thread-safety of shared durable state: saves, acquires, ledger."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_forge import job_state as js


@pytest.fixture(autouse=True)
def _tmp_volume(tmp_path, monkeypatch):
    monkeypatch.setattr(js, "EXPLORATIONS_DIR", tmp_path)
    yield tmp_path


def test_concurrent_saves_preserve_both_mutations():
    job = js.STORE.create("lesson", "audio", "t", 1)

    def set_and_save(key):
        for i in range(50):
            job.d[key] = i
            job.save()
    with ThreadPoolExecutor(max_workers=2) as ex:
        list(ex.map(set_and_save, ["alpha", "beta"]))
    reloaded = js.STORE.load(job.id)
    assert reloaded.d["alpha"] == 49
    assert reloaded.d["beta"] == 49


def test_concurrent_acquires_yield_one_active():
    jobs = [js.STORE.create("lesson", "audio", f"t{i}", 1)
            for i in range(6)]
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(js.STORE.acquire, jobs))
    assert sum(results) == 1                       # exactly one winner
    active = js.STORE.active_id()
    assert active in {j.id for j in jobs}
    queued = js.STORE.queued_ids()
    assert active not in queued
    assert len(queued) == 5                        # everyone else queued


def test_concurrent_ledger_adds_not_lost():
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda _i: js.STORE.ledger_add("job"), range(24)))
    assert js.STORE.ledger_count_24h() == 24


def test_temp_files_never_collide(tmp_path):
    target = tmp_path / "shared.json"

    def write(i):
        for n in range(40):
            js.atomic_write_json(target, {"writer": i, "n": n})
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(write, range(4)))
    assert js.read_json(target)["n"] == 39
    assert not list(tmp_path.glob("*.tmp-*"))      # no leftover temp files
