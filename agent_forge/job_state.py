"""Durable, stage-driven job state — the memory that survives restarts.

The worker runs on a host that restarts on every deploy (and on OOM).
Anything in RAM at that moment is gone; anything paid for and not
persisted is repurchased. This module is the antidote:

- every job gets a directory on the persistent explorations volume:
      explorations/.jobs/<job_id>/
          state.json      (authoritative, schema-versioned, atomic)
          document.md     (checkpointed research)
          script.json     (checkpointed scene/beat list, saved pre-TTS)
          source.txt      (uploaded-PDF text for audiobook jobs)
          clips/          (synthesis-keyed TTS clips — restart-reusable)
          final.*         (the finished artifact)
- `pending_job.json` remains ONLY as an atomic pointer to the active
  job id (plus a legacy-payload migration path).
- one heavy job runs at a time; extra requests queue in order.
- the daily spend ledger lives on the volume, so a deploy can't reset
  the circuit breaker.

Every state write is tmp + flush + fsync + os.replace, so a crash
mid-write can never corrupt the last good state.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path

from .explorer import EXPLORATIONS_DIR

SCHEMA_VERSION = 2

# Stage vocabulary (Phase 1 uses a subset; Phase 3 fills in the canary
# stages). Order matters only for display; transitions are recorded, not
# hard-enforced.
STAGES = (
    "accepted", "researching", "document_ready", "script_generating",
    "script_ready", "canary_selected", "canary_rendering", "canary_scored",
    "canary_retrying", "full_tts", "assembled", "mixed", "final_qc",
    "delivery_pending", "delivered", "waiting_retry", "needs_attention",
    "cancelled",
)

# Stages that mean "the job is over" — the active slot can be released.
TERMINAL = {"delivered", "cancelled"}
# Stages that mean "retained for the owner to look at / retry".
RETAINED = {"waiting_retry", "needs_attention"}

MAX_STAGE_FAILURES = 3          # then: needs_attention
RETAIN_FAILED_DAYS = float(os.environ.get("FORGE_JOB_RETAIN_DAYS", "7"))
KEEP_DELIVERED = int(os.environ.get("FORGE_JOBS_KEEP_DELIVERED", "40"))


def jobs_dir() -> Path:
    return EXPLORATIONS_DIR / ".jobs"


def _pointer_path() -> Path:
    return EXPLORATIONS_DIR / "pending_job.json"


def _queue_path() -> Path:
    return jobs_dir() / "queue.json"


def _ledger_path() -> Path:
    return jobs_dir() / "ledger.json"


def atomic_write_json(path: Path, obj) -> None:
    """tmp in the SAME directory + flush + fsync + os.replace: a crash at
    any instant leaves either the old file or the new file, never a mix."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:                                  # persist the rename itself
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


class Job:
    """A dict-with-a-home. `d` is the authoritative state; `save()` makes
    it durable. Convenience accessors keep worker code readable."""

    def __init__(self, d: dict):
        self.d = d

    # -- identity / paths -------------------------------------------------
    @property
    def id(self) -> str:
        return self.d["job_id"]

    @property
    def dir(self) -> Path:
        return jobs_dir() / self.id

    def path(self, name: str) -> Path:
        return self.dir / name

    @property
    def clips_dir(self) -> Path:
        p = self.path("clips")
        p.mkdir(parents=True, exist_ok=True)
        return p

    # -- fields ------------------------------------------------------------
    @property
    def stage(self) -> str:
        return self.d.get("stage", "accepted")

    @property
    def mode(self) -> str:
        return self.d.get("mode", "")

    @property
    def kind(self) -> str:
        return self.d.get("kind", "")

    @property
    def chat(self):
        return self.d.get("chat_id")

    @property
    def topic(self) -> str:
        return self.d.get("topic", "")

    def get(self, k, default=None):
        return self.d.get(k, default)

    # -- persistence --------------------------------------------------------
    def save(self) -> None:
        self.d["updated_at"] = time.time()
        atomic_write_json(self.path("state.json"), self.d)

    def set_stage(self, stage: str, **fields) -> None:
        assert stage in STAGES, stage
        self.d["stage"] = stage
        history = self.d.setdefault("stage_history", [])
        history.append({"stage": stage, "at": time.time()})
        self.d.update(fields)
        self.save()

    def set_path(self, key: str, p) -> None:
        self.d.setdefault("paths", {})[key] = str(p)
        self.save()

    def get_path(self, key: str) -> Path | None:
        v = self.d.get("paths", {}).get(key)
        return Path(v) if v else None

    def warn(self, msg: str) -> None:
        self.d.setdefault("warnings", []).append(
            {"at": time.time(), "msg": str(msg)[:500]})
        self.save()

    def error(self, msg: str) -> None:
        self.d.setdefault("errors", []).append(
            {"at": time.time(), "msg": str(msg)[:500]})
        self.save()

    def record_failure(self, stage: str, msg: str) -> int:
        """Count a failure at `stage`; return the total for that stage."""
        fails = self.d.setdefault("stage_failures", {})
        fails[stage] = fails.get(stage, 0) + 1
        self.error(f"[{stage}] {msg}")
        return fails[stage]


class JobStore:
    """Creation, the active-slot pointer, the queue, the ledger, and
    retention. All state lives on the explorations volume."""

    # -- creation / loading -------------------------------------------------
    def create(self, kind: str, mode: str, topic: str, chat,
               **extra) -> Job:
        assert mode in ("audio", "video", "document"), mode
        jid = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + \
            "-" + uuid.uuid4().hex[:6]
        d = {
            "schema_version": SCHEMA_VERSION,
            "job_id": jid,
            "kind": kind,
            "mode": mode,
            "topic": topic,
            "title": None,
            "chat_id": chat,
            "status": "pending",
            "stage": "accepted",
            "stage_history": [{"stage": "accepted", "at": time.time()}],
            "stage_failures": {},
            "paths": {},
            "controls": {"cancelled": False},
            "tts": {"fallback_count": 0},
            "delivery": {"attempts": 0, "message_id": None},
            "resume_count": 0,
            "errors": [],
            "warnings": [],
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        d.update(extra)
        job = Job(d)
        job.dir.mkdir(parents=True, exist_ok=True)
        job.save()
        return job

    def load(self, job_id: str) -> Job | None:
        d = read_json(jobs_dir() / job_id / "state.json")
        return Job(d) if d and d.get("job_id") else None

    # -- active pointer + queue ----------------------------------------------
    def active_id(self) -> str | None:
        d = read_json(_pointer_path())
        if isinstance(d, dict):
            return d.get("job_id")
        return None

    def legacy_payload(self) -> dict | None:
        """The pre-schema pending payload ({kind, topic, chat, doc}), if
        that's what is on disk. Used once, at migration."""
        d = read_json(_pointer_path())
        if isinstance(d, dict) and "job_id" not in d and d.get("chat"):
            return d
        return None

    def acquire(self, job: Job) -> bool:
        """Try to make `job` the active heavy job. False -> it was queued."""
        active = self.active_id()
        if active and active != job.id and self.load(active):
            q = read_json(_queue_path(), default=[]) or []
            if job.id not in q:
                q.append(job.id)
                atomic_write_json(_queue_path(), q)
            job.d["status"] = "queued"
            job.save()
            return False
        atomic_write_json(_pointer_path(), {"job_id": job.id})
        job.d["status"] = "running"
        job.save()
        return True

    def queue_position(self, job_id: str) -> int | None:
        q = read_json(_queue_path(), default=[]) or []
        return q.index(job_id) + 1 if job_id in q else None

    def release(self, job: Job) -> str | None:
        """Free the active slot (only if `job` holds it) and return the
        next queued job id, if any."""
        if self.active_id() == job.id:
            try:
                _pointer_path().unlink(missing_ok=True)
            except OSError:
                pass
        q = read_json(_queue_path(), default=[]) or []
        q = [j for j in q if j != job.id]
        nxt = None
        while q and nxt is None:
            cand = q[0]
            if self.load(cand):
                nxt = cand
            q = q[1:] if nxt is None else q[1:]
        atomic_write_json(_queue_path(), q)
        return nxt

    def queued_ids(self) -> list[str]:
        return list(read_json(_queue_path(), default=[]) or [])

    # -- retained jobs (waiting_retry / needs_attention) ---------------------
    def latest_retained(self) -> Job | None:
        best = None
        for p in sorted(jobs_dir().glob("*/state.json")):
            d = read_json(p)
            if d and d.get("stage") in RETAINED:
                if best is None or d.get("updated_at", 0) > \
                        best.d.get("updated_at", 0):
                    best = Job(d)
        return best

    # -- spend ledger ---------------------------------------------------------
    def ledger_count_24h(self) -> int:
        entries = read_json(_ledger_path(), default=[]) or []
        cutoff = time.time() - 86400
        return sum(1 for e in entries if e.get("at", 0) > cutoff)

    def ledger_add(self, kind: str) -> None:
        entries = read_json(_ledger_path(), default=[]) or []
        cutoff = time.time() - 86400
        entries = [e for e in entries if e.get("at", 0) > cutoff]
        entries.append({"at": time.time(), "kind": kind})
        atomic_write_json(_ledger_path(), entries)

    # -- retention --------------------------------------------------------------
    def sweep(self) -> None:
        """Disk hygiene for a 2 GB volume. Delivered jobs lose their raw
        clips immediately; failed jobs are kept RETAIN_FAILED_DAYS then
        dropped; only the newest KEEP_DELIVERED delivered job dirs are
        kept (their finals live in explorations/ anyway)."""
        now = time.time()
        delivered: list[tuple[float, Path]] = []
        for state_p in jobs_dir().glob("*/state.json"):
            d = read_json(state_p)
            if not d:
                continue
            jdir = state_p.parent
            for pat in ("*.part", "*.part.*"):
                for part in jdir.rglob(pat):
                    try:
                        part.unlink()
                    except OSError:
                        pass
            stage = d.get("stage")
            upd = d.get("updated_at", now)
            if stage in TERMINAL:
                clips = jdir / "clips"
                if clips.is_dir():
                    shutil.rmtree(clips, ignore_errors=True)
                delivered.append((upd, jdir))
            elif stage in RETAINED and \
                    now - upd > RETAIN_FAILED_DAYS * 86400:
                if self.active_id() != d.get("job_id"):
                    shutil.rmtree(jdir, ignore_errors=True)
        delivered.sort(reverse=True)
        for _upd, jdir in delivered[KEEP_DELIVERED:]:
            if self.active_id() != jdir.name:
                shutil.rmtree(jdir, ignore_errors=True)


STORE = JobStore()
