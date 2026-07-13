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
- [ ] **Phase 1 — durable, resumable jobs** (`job_state.py`, staged
      runner on the explorations volume, single-heavy-job queue,
      never-silently-omit narration, retention cleanup)
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
