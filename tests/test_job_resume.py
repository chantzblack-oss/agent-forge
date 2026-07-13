"""Stage-driven resume: audio stays audio, research is never repeated,
delivery-pending uploads the existing file, failures retain the job."""

from __future__ import annotations

import asyncio
import types
from pathlib import Path

import pytest

from agent_forge import job_state as js
from agent_forge import worker


@pytest.fixture(autouse=True)
def _tmp_volume(tmp_path, monkeypatch):
    monkeypatch.setattr(js, "EXPLORATIONS_DIR", tmp_path)
    monkeypatch.setattr(worker._explorer, "EXPLORATIONS_DIR", tmp_path)
    yield tmp_path


class FakeMsg:
    message_id = 777


class FakeBot:
    def __init__(self):
        self.sent: list[tuple] = []
        self.fail_sends = 0

    async def send_message(self, chat_id=None, text=None, *a, **k):
        if text is None and a:
            text = a[0]
        self.sent.append(("message", chat_id, text))
        return FakeMsg()

    async def send_audio(self, chat_id=None, audio=None, **k):
        if self.fail_sends:
            self.fail_sends -= 1
            raise TimeoutError("upload died")
        self.sent.append(("audio", chat_id, k.get("caption")))
        return FakeMsg()

    async def send_video(self, chat_id=None, video=None, **k):
        self.sent.append(("video", chat_id, k.get("caption")))
        return FakeMsg()

    async def send_document(self, chat_id=None, document=None, **k):
        self.sent.append(("document", chat_id, k.get("caption")))
        return FakeMsg()


class FakeCtx:
    def __init__(self):
        self.bot = FakeBot()


def _good_doc(tmp_path) -> Path:
    p = tmp_path / "topic.case.md"
    p.write_text("# The Case\n\n" + "## S\ntext\n" * 4 + "x" * 1200,
                 encoding="utf-8")
    return p


def test_audio_mode_survives_resume(tmp_path, monkeypatch):
    """The old resume replayed formats with default (video) settings —
    the podcast-became-video bug. Now the job's persisted mode drives."""
    doc = _good_doc(tmp_path)
    job = js.STORE.create("story", "audio", "the case", 5)
    job.set_path("document", doc)
    job.set_stage("document_ready")
    js.STORE.acquire(job)

    seen = {}

    def fake_from_doc(d, say, audio, cp, clips, scenes):
        seen["audio"] = audio
        seen["doc"] = str(d)
        seen["scenes"] = scenes
        out = tmp_path / "e.m4a"
        out.write_bytes(b"m4a")
        return {"title": "The Case", "path": out, "voiced": True}

    monkeypatch.setitem(worker._FORMATS, "story",
                        dict(worker._FORMATS["story"],
                             from_doc=fake_from_doc))
    ctx = FakeCtx()
    asyncio.run(worker._execute_job(ctx, job))
    assert seen["audio"] is True                      # audio stayed audio
    assert seen["doc"] == str(doc)                    # research reused
    done = js.STORE.load(job.id)
    assert done.stage == "delivered"
    assert done.d["delivery"]["message_id"] == 777
    assert js.STORE.active_id() is None


def test_checkpointed_script_skips_regeneration(tmp_path, monkeypatch):
    doc = _good_doc(tmp_path)
    job = js.STORE.create("story", "audio", "t", 5)
    job.set_path("document", doc)
    scenes = [{"kicker": "a", "narration": "x"}]
    js.atomic_write_json(job.path("script.json"), scenes)
    job.set_path("script", job.path("script.json"))
    job.set_stage("script_ready")
    js.STORE.acquire(job)

    seen = {}

    def fake_from_doc(d, say, audio, cp, clips, sc):
        seen["scenes"] = sc
        out = tmp_path / "e.m4a"
        out.write_bytes(b"m4a")
        return {"title": "T", "path": out, "voiced": True}

    monkeypatch.setitem(worker._FORMATS, "story",
                        dict(worker._FORMATS["story"],
                             from_doc=fake_from_doc))
    asyncio.run(worker._execute_job(FakeCtx(), job))
    assert seen["scenes"] == scenes                   # script reused


def test_failure_retains_job_and_frees_slot(tmp_path, monkeypatch):
    doc = _good_doc(tmp_path)
    job = js.STORE.create("story", "audio", "t", 5)
    job.set_path("document", doc)
    job.set_stage("document_ready")
    js.STORE.acquire(job)

    def exploding(d, say, audio, cp, clips, sc):
        raise RuntimeError("provider down")

    monkeypatch.setitem(worker._FORMATS, "story",
                        dict(worker._FORMATS["story"],
                             from_doc=exploding))
    ctx = FakeCtx()
    asyncio.run(worker._execute_job(ctx, job))
    kept = js.STORE.load(job.id)
    assert kept.stage == "waiting_retry"              # retained, not lost
    assert js.STORE.active_id() is None               # slot freed
    assert any("retry" in str(s[2]).lower() for s in ctx.bot.sent)


def test_third_failure_becomes_needs_attention(tmp_path, monkeypatch):
    doc = _good_doc(tmp_path)
    job = js.STORE.create("story", "audio", "t", 5)
    job.set_path("document", doc)
    job.set_stage("document_ready")
    # two strikes already at the stage where the exploding builder runs
    job.d["stage_failures"] = {"script_generating": 2}
    job.save()
    js.STORE.acquire(job)

    monkeypatch.setitem(
        worker._FORMATS, "story",
        dict(worker._FORMATS["story"],
             from_doc=lambda *a: (_ for _ in ()).throw(
                 RuntimeError("still broken"))))
    asyncio.run(worker._execute_job(FakeCtx(), job))
    assert js.STORE.load(job.id).stage == "needs_attention"


def test_delivery_pending_resume_uploads_without_rebuilding(tmp_path,
                                                            monkeypatch):
    final = tmp_path / "done.m4a"
    final.write_bytes(b"finished audio")
    job = js.STORE.create("story", "audio", "t", 5)
    job.d["title"] = "Done Episode"
    job.set_path("final", final)
    job.set_stage("delivery_pending")
    js.STORE.acquire(job)

    def must_not_build(*a, **k):
        raise AssertionError("resume rebuilt a finished episode")
    monkeypatch.setitem(worker._FORMATS, "story",
                        dict(worker._FORMATS["story"],
                             builder=must_not_build,
                             from_doc=must_not_build))

    app = types.SimpleNamespace(bot=FakeBot())
    monkeypatch.setattr(worker._jobs.STORE, "active_id", lambda: job.id)
    asyncio.run(worker._resume_job(app))
    assert js.STORE.load(job.id).stage == "delivered"
    assert any(s[0] == "audio" for s in app.bot.sent)


def test_failed_upload_keeps_job(tmp_path, monkeypatch):
    doc = _good_doc(tmp_path)
    job = js.STORE.create("story", "audio", "t", 5)
    job.set_path("document", doc)
    job.set_stage("document_ready")
    js.STORE.acquire(job)

    def fake_from_doc(d, say, audio, cp, clips, sc):
        out = tmp_path / "e.m4a"
        out.write_bytes(b"m4a")
        return {"title": "T", "path": out, "voiced": True}
    monkeypatch.setitem(worker._FORMATS, "story",
                        dict(worker._FORMATS["story"],
                             from_doc=fake_from_doc))
    monkeypatch.setattr(worker.asyncio, "sleep",
                        lambda *_a, **_k: asyncio.sleep(0))
    ctx = FakeCtx()
    ctx.bot.fail_sends = 99                           # every upload dies
    asyncio.run(worker._execute_job(ctx, job))
    kept = js.STORE.load(job.id)
    assert kept.stage == "waiting_retry"              # not lost, not delivered
    assert kept.get_path("final").exists()            # artifact retained


def test_resume_gives_up_after_crash_loop(tmp_path, monkeypatch):
    job = js.STORE.create("story", "audio", "loopy", 5)
    job.d["resume_count"] = 4
    job.save()
    js.STORE.acquire(job)
    app = types.SimpleNamespace(bot=FakeBot())
    asyncio.run(worker._resume_job(app))
    assert js.STORE.load(job.id).stage == "needs_attention"


def test_dead_resume_paths_hand_slot_to_queue(tmp_path, monkeypatch):
    """A malformed/over-resumed active job must not strand the queue:
    the early-return paths start the next queued job."""
    dead = js.STORE.create("story", "audio", "loopy", 5)
    dead.d["resume_count"] = 4
    dead.save()
    js.STORE.acquire(dead)
    queued = js.STORE.create("lesson", "audio", "next up", 5)
    js.STORE.acquire(queued)                       # -> queued

    started = []

    async def fake_execute(context, job):
        started.append(job.id)
    monkeypatch.setattr(worker, "_execute_job", fake_execute)
    app = types.SimpleNamespace(bot=FakeBot())
    asyncio.run(worker._resume_job(app))
    assert js.STORE.load(dead.id).stage == "needs_attention"
    assert started == [queued.id]                  # queue continued


def test_delivery_failure_keeps_delivery_as_resume_stage(tmp_path,
                                                         monkeypatch):
    """P0: an upload failure must NOT send /retry back through the
    builder — resume_stage stays delivery_pending."""
    doc = _good_doc(tmp_path)
    job = js.STORE.create("story", "audio", "t", 5)
    job.set_path("document", doc)
    job.set_stage("document_ready")
    js.STORE.acquire(job)

    def fake_from_doc(d, say, audio, cp, clips, sc):
        out = tmp_path / "e.m4a"
        out.write_bytes(b"finished audio")
        return {"title": "T", "path": out, "voiced": True}
    monkeypatch.setitem(worker._FORMATS, "story",
                        dict(worker._FORMATS["story"],
                             from_doc=fake_from_doc))
    ctx = FakeCtx()
    ctx.bot.fail_sends = 99
    asyncio.run(worker._execute_job(ctx, job))
    kept = js.STORE.load(job.id)
    assert kept.stage == "waiting_retry"
    assert kept.get("resume_stage") == "delivery_pending"

    # retry: upload only — any builder/TTS call is a failure
    def must_not_build(*a, **k):
        raise AssertionError("retry rebuilt instead of uploading")
    monkeypatch.setitem(worker._FORMATS, "story",
                        dict(worker._FORMATS["story"],
                             builder=must_not_build,
                             from_doc=must_not_build))
    before = kept.get_path("final").read_bytes()
    ctx2 = FakeCtx()
    js.STORE.acquire(kept)
    asyncio.run(worker._execute_job(ctx2, kept))
    done = js.STORE.load(job.id)
    assert done.stage == "delivered"
    assert done.d["delivery"]["message_id"] == 777
    assert done.get_path("final").read_bytes() == before   # byte-for-byte
    assert any(s[0] == "audio" for s in ctx2.bot.sent)


def test_retry_resets_failed_stage_counter(tmp_path):
    job = js.STORE.create("story", "audio", "t", 5)
    job.d["stage_failures"] = {"delivery_pending": 2}
    job.set_stage("waiting_retry", resume_stage="delivery_pending")
    # the reset targets resume_stage, not the retained bookkeeping stage
    failed = job.get("resume_stage") or job.stage
    job.d.setdefault("stage_failures", {})[failed] = 0
    assert job.d["stage_failures"]["delivery_pending"] == 0


def test_unsent_document_resent_on_resume(tmp_path, monkeypatch):
    """Restart after document checkpoint but before its PDF reached
    Telegram: the resume sends the PDF."""
    doc = _good_doc(tmp_path)
    job = js.STORE.create("story", "audio", "t", 5)
    job.set_path("document", doc)
    job.set_stage("document_ready")           # doc_sent never recorded
    js.STORE.acquire(job)

    def fake_from_doc(d, say, audio, cp, clips, sc):
        out = tmp_path / "e.m4a"
        out.write_bytes(b"m4a")
        return {"title": "T", "path": out, "voiced": True}
    monkeypatch.setitem(worker._FORMATS, "story",
                        dict(worker._FORMATS["story"],
                             from_doc=fake_from_doc))
    from agent_forge import docrender
    monkeypatch.setattr(docrender, "md_to_pdf", lambda p, *a, **k: p)
    ctx = FakeCtx()
    asyncio.run(worker._execute_job(ctx, job))
    assert any(s[0] == "document" for s in ctx.bot.sent)   # PDF re-sent
    assert js.STORE.load(job.id).get("doc_sent") is True


def test_script_checkpoint_failure_stops_before_tts(tmp_path, monkeypatch):
    """P1: a durable checkpoint that cannot persist must prevent paid
    TTS work — the job is retained, not silently degraded."""
    from agent_forge import story as _story
    doc = _good_doc(tmp_path)
    job = js.STORE.create("story", "audio", "t", 5)
    job.set_path("document", doc)
    job.set_stage("document_ready")
    js.STORE.acquire(job)

    def exploding_cp(kind, payload):
        raise OSError("volume full")
    monkeypatch.setattr(worker, "_job_checkpoint",
                        lambda job, loop=None: exploding_cp)

    def must_not_render(*a, **k):
        raise AssertionError("TTS ran after checkpoint failure")
    monkeypatch.setattr(worker._video, "render_podcast", must_not_render)
    monkeypatch.setattr(worker._video, "render_scenes", must_not_render)

    scenes = [{"kicker": "a", "narration": "x"}]
    real_from_doc = worker._FORMATS["story"]["from_doc"]

    def from_doc_with_script(d, say, audio, cp, clips, sc):
        return _story.video_from_casefile(d, say, audio=audio,
                                          checkpoint=cp, clips_dir=clips,
                                          scenes=scenes)
    monkeypatch.setitem(worker._FORMATS, "story",
                        dict(worker._FORMATS["story"],
                             from_doc=from_doc_with_script))
    ctx = FakeCtx()
    asyncio.run(worker._execute_job(ctx, job))
    kept = js.STORE.load(job.id)
    assert kept.stage in ("waiting_retry", "needs_attention")
