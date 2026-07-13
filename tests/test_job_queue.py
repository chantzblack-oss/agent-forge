"""One heavy job at a time: the second request queues, never overwrites."""

from __future__ import annotations

import pytest

from agent_forge import job_state as js


@pytest.fixture(autouse=True)
def _tmp_volume(tmp_path, monkeypatch):
    monkeypatch.setattr(js, "EXPLORATIONS_DIR", tmp_path)
    yield tmp_path


def test_second_job_queues_not_overwrites():
    a = js.STORE.create("lesson", "audio", "first", 1)
    b = js.STORE.create("story", "audio", "second", 1)
    assert js.STORE.acquire(a) is True
    assert js.STORE.acquire(b) is False
    assert js.STORE.active_id() == a.id            # pointer untouched
    assert js.STORE.queue_position(b.id) == 1
    # both jobs' state files intact and distinct
    assert js.STORE.load(a.id).topic == "first"
    assert js.STORE.load(b.id).topic == "second"


def test_release_hands_slot_to_next_in_order():
    a = js.STORE.create("lesson", "audio", "a", 1)
    b = js.STORE.create("lesson", "audio", "b", 1)
    c = js.STORE.create("lesson", "audio", "c", 1)
    js.STORE.acquire(a)
    js.STORE.acquire(b)
    js.STORE.acquire(c)
    assert js.STORE.queued_ids() == [b.id, c.id]
    nxt = js.STORE.release(a)
    assert nxt == b.id
    assert js.STORE.active_id() is None            # b must acquire explicitly
    # crash-safety: b is only PEEKED — it stays queued until acquire
    assert b.id in js.STORE.queued_ids()
    bb = js.STORE.load(b.id)
    assert js.STORE.acquire(bb) is True
    assert js.STORE.active_id() == b.id
    assert js.STORE.queued_ids() == [c.id]


def test_crash_between_release_and_acquire_never_orphans():
    """The exact P0 scenario: release returns the next id, then the
    process dies before acquire. On 'reboot', the job must still be
    reachable — queued or reconciled — never lost."""
    a = js.STORE.create("lesson", "audio", "a", 1)
    b = js.STORE.create("lesson", "audio", "b", 1)
    js.STORE.acquire(a)
    js.STORE.acquire(b)
    nxt = js.STORE.release(a)                      # …and then we "crash"
    assert nxt == b.id
    # reboot: reconcile + the boot queue-starter can see b
    js.STORE.reconcile()
    assert b.id in js.STORE.queued_ids()
    bb = js.STORE.load(b.id)
    assert js.STORE.acquire(bb) is True


def test_reconcile_clears_terminal_pointer_and_keeps_queue():
    a = js.STORE.create("lesson", "audio", "a", 1)
    b = js.STORE.create("lesson", "audio", "b", 1)
    js.STORE.acquire(a)
    js.STORE.acquire(b)
    a.set_stage("delivered")                       # done but pointer left
    js.STORE.reconcile()
    assert js.STORE.active_id() is None            # stale pointer cleared
    assert js.STORE.queued_ids() == [b.id]         # queue intact


def test_reconcile_requeues_orphaned_nonterminal_job():
    a = js.STORE.create("lesson", "audio", "orphan", 1)
    a.set_stage("script_ready")                    # mid-flight
    # neither active nor queued (simulated metadata loss)
    assert js.STORE.active_id() is None
    assert js.STORE.queued_ids() == []
    js.STORE.reconcile()
    assert a.id in js.STORE.queued_ids()
    # retained/terminal jobs are NOT resurrected
    r = js.STORE.create("story", "audio", "kept", 1)
    r.set_stage("needs_attention")
    d = js.STORE.create("sim", "audio", "done", 1)
    d.set_stage("delivered")
    js.STORE.reconcile()
    q = js.STORE.queued_ids()
    assert r.id not in q and d.id not in q


def test_release_by_non_active_keeps_pointer():
    a = js.STORE.create("lesson", "audio", "a", 1)
    b = js.STORE.create("lesson", "audio", "b", 1)
    js.STORE.acquire(a)
    js.STORE.acquire(b)                            # queued
    js.STORE.release(b)                            # b gives up its queue spot
    assert js.STORE.active_id() == a.id
    assert js.STORE.queued_ids() == []


def test_release_skips_vanished_queue_entries(tmp_path):
    import shutil
    a = js.STORE.create("lesson", "audio", "a", 1)
    b = js.STORE.create("lesson", "audio", "b", 1)
    c = js.STORE.create("lesson", "audio", "c", 1)
    js.STORE.acquire(a)
    js.STORE.acquire(b)
    js.STORE.acquire(c)
    shutil.rmtree(b.dir)                           # b's state deleted
    nxt = js.STORE.release(a)
    assert nxt == c.id


def test_reacquire_same_active_is_idempotent():
    a = js.STORE.create("lesson", "audio", "a", 1)
    assert js.STORE.acquire(a) is True
    assert js.STORE.acquire(a) is True             # same job, still active
    assert js.STORE.queued_ids() == []
