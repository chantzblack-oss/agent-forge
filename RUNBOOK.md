# Cross-Provider Live Run — Runbook

This branch (`claude/add-agent-confidence-requirement-8cM6U`) ships a
multi-provider agentic framework that can collaborate across Claude, GPT,
and Gemini, enforce a structural quality gate, and verify Evidence claims
across providers via consensus.

The sandbox this branch was developed in **cannot** reach `api.openai.com`
or `generativelanguage.googleapis.com` (egress blocked by proxy). Live
multi-provider runs must be executed from a machine with internet access.

## Prerequisites

```bash
# Install Claude Code (Claude provider) and Python deps
# https://docs.anthropic.com/en/docs/claude-code
pip install -e .
pip install openai google-genai pytest rich

# Set keys in your shell
export OPENAI_API_KEY="sk-proj-..."
export GEMINI_API_KEY="AIza..."
# (Claude uses local CLI auth, not an env var)
```

## Step 1 — Verify provider reachability (cost: ~$0.001)

Before any benchmark run, prove that all three providers authenticate AND that
your network can reach them:

```bash
python -m agent_forge.bench.verify
```

Expected output on a working setup:

```
[OK]   Claude (CLI)   model=haiku                    1.2s
       reply: 'OK'
[OK]   OpenAI         model=gpt-4o-mini              0.6s
       reply: 'OK'
       tokens: (12,3)  cost: $0.000004
[OK]   Gemini         model=gemini-2.5-flash         0.7s
       reply: 'OK'
       tokens: (10,2)  cost: $0.000005

=== Summary: 3/3 providers reachable ===
Total verification cost: $0.000009
All providers OK — cross-provider runs viable.
```

If any provider fails, the script prints a one-line diagnosis: missing key,
auth failure, network egress blocked, SDK not installed, etc. Fix before
spending money on a benchmark.

## Step 2 — Smoke test on a single HotpotQA question (cost: ~$1-3)

```bash
python -m agent_forge.bench \
  --team "Cross-Provider Research Lab" \
  --tasks hotpot \
  --n 1 \
  --live \
  --out report_smoke.md
```

What this does:
- Loads `CROSS_PROVIDER_RESEARCH_LAB`: Claude leader (`opus`), GPT-5 worker,
  Gemini 2.5 Pro contrarian, Claude Haiku critic.
- Runs question 1 of the HotpotQA starter set (Scott Derrickson / Ed Wood).
- Caps at one task. Wall time: ~10-15 minutes.
- Writes a markdown report with score breakdown.

If the gate passes and the citation density clears 70%, you've validated the
multi-provider stack end-to-end. If not, the report tells you which axis
failed (accuracy / citation / hallucination / actionability / efficiency).

## Step 3 — 5-question pilot with consensus (cost: ~$10-30)

```bash
python -m agent_forge.bench \
  --team "Cross-Provider Research Lab" \
  --tasks hotpot \
  --n 5 \
  --live \
  --consensus opus gpt-4o gemini-2.5-pro \
  --judge-model opus \
  --out report_pilot.md
```

`--consensus` adds cross-provider verification of Evidence claims at the
gate. Each Evidence claim is re-asked of all three models (Yes / No / Unsure
with a one-sentence reason). Disagreement above the threshold escalates to
the judge. The leader's `[COMPLETE]` is blocked until evidence claims pass
verification.

This is the first run that actually exercises the framework's central
premise — that agents from different training contexts produce better
collective output than any single one.

## Step 4 — Single-Opus baseline (cost: ~$5-15)

To know whether the multi-agent framework is worth it, compare against a
single-Opus baseline on the same questions:

```bash
python -m agent_forge.bench \
  --team "Research Lab" \
  --tasks hotpot \
  --n 5 \
  --seed 42 \
  --live \
  --out report_baseline.md
```

(`Research Lab` defaults all agents to the orchestrator's `default_model`
which is `opus`.)

## Reading the reports

Each report has two tables:

**Per-task results** — one row per (task, team) showing all five score
components, latency, gate status. Fast scan for outliers.

**Team aggregates** — mean total / accuracy / citation / hallucination plus
completion rate and gate-fail rate. This is the headline number you compare
across runs.

A meaningful "the multi-agent framework works" claim requires:
- Multi-agent total ≥ single-Opus total (consistently, across questions)
- Multi-agent gate pass rate ≥ baseline
- Multi-agent citation density and hallucination metric better than baseline
- Cost / latency overhead is justified by the quality delta

If multi-agent scores ≤ baseline, the framework's premise is wrong and we
fix orchestration before adding capabilities.

## Cost guardrails

| Step | Approx cost | Approx wall time |
|------|------------|------------------|
| Verify | $0.001 | 5s |
| 1 question (no consensus) | $1-3 | 10-15 min |
| 1 question (with consensus) | $3-8 | 15-25 min |
| 5 questions (no consensus) | $5-15 | 1 hour |
| 5 questions (with consensus) | $15-40 | 2 hours |
| 25 questions full pilot | $50-150 | 6-10 hours |

Always do `--n 1` first. Then `--n 5`. Only do `--n 25` after the smaller
runs validate.

## Result artifacts

Every live run writes:
- `<team_slug>_<timestamp>.md` — markdown transcript (auto-saved by orchestrator on export)
- `<team_slug>_<timestamp>.claims.json` — structured ClaimGraph sidecar (per-claim text, source URL, parsed publication date, confidence, post-consensus adjusted confidence)
- `<args.out>` — bench report markdown

Inspect the `.claims.json` to see what the parser extracted; this is the
ground truth for everything downstream of the bench harness.

## Known limitations

- **Streaming for non-Claude providers is not yet implemented.** GPT and
  Gemini outputs print all-at-once after the full response (Claude streams).
  Affects UX, not correctness.
- **Claude provider doesn't expose token usage**, so its cost stays `None`.
  OpenAI and Gemini return real token counts and estimated costs.
- **Hand-tuned pricing tables** in the providers are approximate and
  sourced from public 2024-2026 docs; verify against your billing page.
- **No tool use yet.** Citations are still hallucinatable. Real web fetch
  + claim verification is phase 6.
