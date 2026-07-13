# Agent Forge — staged upgrade roadmap

Source: independent external review (Codex, 2026-07-13), reconciled and
executed by Claude Code. One phase at a time; a phase starts only after
the previous one meets its acceptance criteria. Full phase specs live in
the execution pack (kept in the session/upload, not in the repo).

## Baseline (recorded 2026-07-13, Phase 0 start)

- `PYTHONPATH=. python -m compileall -q agent_forge` — PASS
- `PYTHONPATH=. python -m pytest -q` — FAILED at collection:
  `tests/test_wonderlab.py` imported from `agent_forge.wonderlab`, which
  had no `__init__.py` (namespace dir, nothing exported).
- After the `__init__.py` fix: 7 passed.
- Known-confirmed issues at baseline: `_ok()` admitted everyone when
  `TELEGRAM_ALLOWED_USERS` was empty; `/diag` sent the first 14 chars of
  the Anthropic key to Telegram; `/test` copy claimed "no API spend"
  while costing ~1¢ of TTS.

## Phases

- [x] **Phase 0 — trustworthy baseline & safety guardrails**
  - [x] compile/test baseline recorded
  - [x] wonderlab collection failure fixed (package `__init__.py`)
  - [x] Telegram auth fails closed; `FORGE_ALLOW_PUBLIC=1` dev override;
        startup refuses an empty allowlist
  - [x] `/diag` reports presence/length only — no key material
  - [x] `/test` copy is truthful (no LLM spend, ~1¢ TTS)
  - [x] auth + diag-secrecy tests added (`tests/test_worker_auth.py`)
- [x] **Phase 1 — durable, resumable jobs** (completed 2026-07-13)
  - [x] `job_state.py`: schema-v2 state under `explorations/.jobs/<id>/`,
        atomic writes (tmp+fsync+replace), stage history, per-stage
        failure counts, legacy-payload detection, retention sweep,
        volume-backed daily spend ledger
  - [x] `pending_job.json` demoted to an atomic pointer; legacy payloads
        never guessed (owner notified — a podcast can't become a video)
  - [x] synthesis-keyed TTS clip cache (`clips/`, `.part.mp3` rename
        discipline) — restarts/retries never repurchase finished audio
  - [x] `NarrationIncomplete`: a podcast refuses to assemble with
        missing segments (the None-filter silent-omission bug is dead)
  - [x] stage-driven runner `_execute_job` + `_run_format_job`/
        `_run_deep_job`/`_run_narrate_job`; document checkpointed before
        early PDF send; script checkpointed before any TTS
  - [x] one-heavy-job queue with positions; queued jobs start on
        release AND on boot; auto-feed skips while a job is active
  - [x] `/retry` (fresh failure budget at the stuck stage);
        needs_attention after 3 failures at a stage; resume-loop cap (4)
  - [x] uploaded-PDF audiobooks persist their source in the job dir
  - [x] restock/daily loops start from `_post_init` on EVERY boot
        (previously only after a resume — clean boots had no auto-feed)
  - [x] tests: `test_job_state` `test_job_queue` `test_job_resume`
        `test_audio_assembly` (39 total passing) + end-to-end sandbox
        smoke with real ffmpeg: crash mid-TTS kept 3/4 clips, retry
        bought exactly the 1 missing clip, episode delivered
  - Deviations: `_make_lesson`/`_make_show` kept as thin wrappers over
    the runner (compatibility with routing call sites); full
    stage-granular canary fields land with Phase 3; delivery failures
    release the queue slot but retain the job (retry re-assembles from
    cached clips at ~$0)
- [ ] **Phase 2 — performance-beat scripting** (audio-only script
      doctor, 55–85-word beats, OpenAI speed param, contextual gaps,
      music modes, `audio_pipeline.py`)
- [ ] **Phase 3 — resumable audio canary + quality gate**
      (`audio_quality.py`, prosody metrics, one bounded repair,
      canary-reuse economics, quality manifest)
- [ ] **Phase 4 — feedback & observability** (inline feedback keyboard,
      `feedback.py`, compact QA line, `/status`, stage instrumentation)
- [ ] **Phase 5 — live production card** (one edited Telegram message,
      controls, early editorial treatment)
- [ ] **Phase 6 — preferences, episode packages, library**
      (`preferences.py`, `artifacts.py`, chapters/cover art, reuse
      transformations)
- [ ] **Phase 7 — interactive learning** (predict/reveal, quiz,
      challenge, series, swipe deck)
- [ ] **Phase 8 — phone-native documents & personalization split**
      (mobile brief renderer profile, dossier navigation, learning
      state, full-document follow-up retrieval)
- [ ] **Phase 9 — measured performance & cost control** (stage
      telemetry report, cache layers, queue/ETA, prebuilt scheduled
      programming)

## Standing deviations from the pack (reasoned)

- The pack's line numbers/file claims were re-verified against the tree
  before each change; where they diverge, the tree wins.
- `docs/` did not exist before this file; deployment docs live in
  `deploy/` and `CLAUDE.md`, and updates land there.
