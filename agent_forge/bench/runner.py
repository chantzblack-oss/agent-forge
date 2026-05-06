"""Bench runner: executes a BenchTask against a TeamConfig and produces a
scored BenchResult. Supports mock mode (deterministic, CI-friendly) and live
mode (real CLI calls).
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import Callable
from unittest.mock import patch

from ..agent import Agent
from ..engine import Orchestrator
from ..teams import TeamConfig
from .tasks import BenchTask
from .scorer import ScoreBreakdown, score_task

ModelCallable = Callable[[Agent, str, str], str]
"""(agent, system_prompt, user_prompt) -> model output text"""


@dataclass
class BenchResult:
    task_id: str
    team_name: str
    score: ScoreBreakdown
    latency_s: float
    transcript_text: str
    claims_json: str
    completed: bool  # True iff leader emitted [COMPLETE] or session ended cleanly
    quality_gate_failed: bool

    @property
    def total(self) -> float:
        return self.score.total


def _default_mock_model(agent: Agent, system: str, user_prompt: str) -> str:
    """Deterministic mock that produces schema-compliant output per role.

    Honors enough of the rubric format for v1 scoring to register signal:
    workers emit four sections with cited evidence; leader emits Confidence
    + Top Unknowns + WHAT TO DO THIS WEEK before [COMPLETE].
    """
    if agent.role == "leader":
        if "FINAL ROUND" in user_prompt or "FINAL DELIVERABLE" in user_prompt or "End with [COMPLETE]" in user_prompt:
            return (
                "## Synthesis\n"
                "Phased rollout balances reliability and affordability tradeoffs against "
                "current constraints. Alternatives include token bucket vs sliding window "
                "approaches, with failure mode and fallback considered. SOC 2 and NIST "
                "controls map to identified residual risk; falsify by running the proposed "
                "experiment. Compare alternatives by impact and likelihood.\n\n"
                "Confidence: med\n"
                "Top Unknowns That Could Overturn This:\n"
                "- Storage cost trajectory\n"
                "- Regulatory ruling timing\n\n"
                "## WHAT TO DO THIS WEEK\n"
                "1. Greenlight the action with for and against decision framework agreed.\n"
                "2. Need to clarify open assumption with stakeholder; may be uncertain.\n"
                "3. Confidence labels attached to all interventions.\n"
                "[COMPLETE]"
            )
        return "## Plan\n@Worker quantify costs. @Critic audit. [DONE]"
    if agent.role in ("worker", "debater"):
        return (
            "## Key Finding\n"
            "Tradeoff between reliability and affordability is real but bounded.\n\n"
            "## Evidence\n"
            "- Lazard LCOE 2024 shows utility solar at $29-92/MWh. (2026-01-15) [Lazard](https://www.lazard.com/x).\n"
            "- IEA reports 90% of new capacity in 2024 was renewable. (February 2026) [IEA](https://www.iea.org/y).\n\n"
            "## Conflict Check\n"
            "- NREL stability study suggests grid risk above 80% renewables; reconciled by phased buildout. (January 2026) [NREL](https://www.nrel.gov/z).\n\n"
            "## Recommendations\n"
            "1. Greenlight Tier-1 storage RFP this quarter.\n"
            "2. Commission interconnection queue audit.\n"
            "3. Map findings to SOC 2 and NIST controls; assess residual risk; falsify "
            "with controlled experiment. Compare alternatives by impact and likelihood. "
            "Confidence in this is medium; outcome may be uncertain — clarify assumption "
            "with sponsor.\n"
            "[DONE]"
        )
    return (
        "Verdict: Strong.\nStrengths: thorough, well-cited.\n"
        "Issues with Fixes: none material.\nEvidence Check: spot-checked 2 sources.\n"
        "Rate: Strong. [DONE]"
    )


def run_task(
    task: BenchTask,
    team: TeamConfig,
    *,
    live: bool = False,
    model_call: ModelCallable | None = None,
    score_fn: Callable[..., ScoreBreakdown] = score_task,
    consensus=None,  # type: ignore[no-untyped-def]
) -> BenchResult:
    """Execute one task on one team. Returns a scored BenchResult.

    If `consensus` is a ConsensusEngine instance, it's attached to the
    orchestrator and Evidence claims get cross-provider verified before the
    leader's [COMPLETE] is accepted.
    """
    if live and model_call is not None:
        raise ValueError("live=True is incompatible with a custom model_call")
    if not live and model_call is None:
        model_call = _default_mock_model

    start = _time.monotonic()

    if live:
        orch = Orchestrator(narrate_mode="off")
        if consensus is not None:
            orch.attach_consensus(consensus)
        orch.run(task.prompt, team)
    else:
        orch = Orchestrator(narrate_mode="off")
        if consensus is not None:
            orch.attach_consensus(consensus)
        # Mock mode: patch CLI + skip the interactive end-session prompt so the
        # harness never blocks on stdin under pytest capture.
        with patch("agent_forge.agent._CLAUDE_PATH", "/usr/bin/claude"), patch(
            "agent_forge.agent.Agent._call_cli", new=lambda self, s, u: model_call(self, s, u)
        ), patch("agent_forge.engine.Prompt.ask", new=lambda *a, **kw: "done"):
            orch.run(task.prompt, team)

    latency_s = _time.monotonic() - start

    transcript_text = "\n\n".join(
        f"[{e['agent']} ({e['role']})]\n{e['content']}" for e in orch._transcript
    )
    claims_json = orch.bus.claims.to_json()
    quality_gate_failed = any(
        e.get("content", "").startswith("[QUALITY_GATE_FAILED]")
        for e in orch._transcript
    )
    completed = any("[COMPLETE]" in e.get("content", "") for e in orch._transcript)

    breakdown = score_fn(
        task=task,
        claims=orch.bus.claims,
        transcript_text=transcript_text,
        latency_s=latency_s,
    )

    return BenchResult(
        task_id=task.id,
        team_name=team.name,
        score=breakdown,
        latency_s=latency_s,
        transcript_text=transcript_text,
        claims_json=claims_json,
        completed=completed,
        quality_gate_failed=quality_gate_failed,
    )


def run_suite(
    tasks: list[BenchTask],
    team: TeamConfig,
    *,
    live: bool = False,
    model_call: ModelCallable | None = None,
    score_fn: Callable[..., ScoreBreakdown] = score_task,
    consensus=None,  # type: ignore[no-untyped-def]
) -> list[BenchResult]:
    return [
        run_task(t, team, live=live, model_call=model_call, score_fn=score_fn, consensus=consensus)
        for t in tasks
    ]
