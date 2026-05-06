"""Verify Orchestrator._gate_check invokes ConsensusEngine when attached."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from agent_forge.agent import AgentConfig
from agent_forge.claims import Claim, ClaimGraph
from agent_forge.consensus import ConsensusEngine
from agent_forge.engine import Orchestrator
from agent_forge.providers import register_provider, reset_providers
from agent_forge.teams import TeamConfig


@dataclass
class _MockStats:
    provider: str = "mock"
    model: str = "mock"
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class MockProvider:
    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, **kwargs):
        return self.response, _MockStats()


def _orch_with_team() -> Orchestrator:
    o = Orchestrator(narrate_mode="off")
    o._team = TeamConfig(
        name="Gate Consensus Team",
        description="d", icon="🧪", category="Test",
        agents=[
            AgentConfig(name="Lead", role="leader", personality="lead"),
            AgentConfig(name="Critic", role="critic", personality="critic"),
        ],
        round_order=["Lead", "Critic", "Lead"],
        max_rounds=1,
    )
    o._goal = "test goal"
    return o


def _seed_with_evidence(orch: Orchestrator, n_evidence: int = 3) -> None:
    g = ClaimGraph()
    for i in range(n_evidence):
        g.add(Claim(
            id=f"r1.W.c{i+1}",
            text=f"evidence {i}",
            agent="W", role="worker", round=1,
            section="Evidence",
            source_url=f"https://example.com/{i}",
            source_date=date(2026, 1, 1),
            confidence=None,
            raw_excerpt="## Evidence",
        ))
    g.add(Claim(
        id="r1.Lead.c1", text="final", agent="Lead", role="leader", round=1,
        section=None, source_url=None, source_date=None,
        confidence="med", raw_excerpt="[COMPLETE] final",
    ))
    orch.bus._claims = g


def test_gate_passes_when_consensus_agrees() -> None:
    reset_providers()
    register_provider("mock-claude", lambda: MockProvider("Yes - supported."))
    register_provider("mock-gpt", lambda: MockProvider("Yes - supported."))
    register_provider("mock-gemini", lambda: MockProvider("Yes - supported."))

    orch = _orch_with_team()
    _seed_with_evidence(orch, n_evidence=3)
    orch.attach_consensus(ConsensusEngine(
        models=["mock-claude", "mock-gpt", "mock-gemini"],
        judge_model="mock-judge",
    ))

    ok, issues = orch._gate_check()
    assert ok, f"expected gate to pass, issues={issues}"
    assert len(orch._consensus_results) == 3
    assert all(not r.escalated for r in orch._consensus_results)


def test_gate_fails_when_consensus_rejects_majority() -> None:
    reset_providers()
    register_provider("mock-claude", lambda: MockProvider("No - contradicted."))
    register_provider("mock-gpt", lambda: MockProvider("No - contradicted."))
    register_provider("mock-gemini", lambda: MockProvider("No - contradicted."))

    orch = _orch_with_team()
    _seed_with_evidence(orch, n_evidence=3)
    orch.attach_consensus(ConsensusEngine(
        models=["mock-claude", "mock-gpt", "mock-gemini"],
        judge_model="mock-judge",
    ))

    ok, issues = orch._gate_check()
    assert not ok
    assert any("consensus rejected" in i for i in issues)


def test_gate_skips_consensus_when_not_attached() -> None:
    orch = _orch_with_team()
    _seed_with_evidence(orch, n_evidence=3)
    # No attach_consensus
    ok, _ = orch._gate_check()
    assert ok
    assert orch._consensus_results == []


def test_gate_consensus_failure_does_not_crash_orchestrator() -> None:
    """If consensus itself raises, gate surfaces it as an issue, doesn't crash."""
    class BrokenEngine:
        def verify_evidence(self, graph, context):
            raise RuntimeError("upstream failure")

    orch = _orch_with_team()
    _seed_with_evidence(orch, n_evidence=2)
    orch.attach_consensus(BrokenEngine())

    ok, issues = orch._gate_check()
    assert not ok
    assert any("consensus verification failed" in i for i in issues)
