from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from agent_forge.claims import Claim, ClaimGraph
from agent_forge.engine import Orchestrator
from agent_forge.agent import AgentConfig
from agent_forge.teams import TeamConfig


@dataclass
class _TeamFixture:
    orch: Orchestrator


def _make_orch(*, critic_months: int = 24) -> Orchestrator:
    orch = Orchestrator(narrate_mode="off")
    orch._team = TeamConfig(
        name="Gate Test Team",
        description="Gate Test Team",
        icon="🧪",
        category="Test",
        agents=[
            AgentConfig(name="Lead", role="leader", personality="lead"),
            AgentConfig(name="Critic", role="critic", personality="critic", stale_evidence_months=critic_months),
        ],
        round_order=["Lead", "Critic", "Lead"],
        max_rounds=1,
    )
    return orch


def _seed_graph(
    *,
    evidence_supported: int = 1,
    evidence_unsupported: int = 0,
    stale_count: int = 0,
    include_leader_confidence: bool = True,
    total_evidence_for_density: int | None = None,
) -> ClaimGraph:
    g = ClaimGraph()
    n = 1

    for i in range(evidence_supported):
        g.add(
            Claim(
                id=f"r1.Worker.c{n}",
                text=f"supported evidence {i}",
                agent="Worker",
                role="worker",
                round=1,
                section="Evidence",
                source_url=f"https://example.com/{i}",
                source_date=date(2026, 1, 1),
                confidence=None,
                raw_excerpt="## Evidence supported",
            )
        )
        n += 1

    for i in range(evidence_unsupported):
        g.add(
            Claim(
                id=f"r1.Worker.c{n}",
                text=f"unsupported evidence {i}",
                agent="Worker",
                role="worker",
                round=1,
                section="Evidence",
                source_url=None,
                source_date=None,
                confidence=None,
                raw_excerpt="## Evidence unsupported",
            )
        )
        n += 1

    if total_evidence_for_density is not None:
        current = len(g.evidence_claims())
        while current < total_evidence_for_density:
            g.add(
                Claim(
                    id=f"r1.Worker.c{n}",
                    text="density filler unsupported",
                    agent="Worker",
                    role="worker",
                    round=1,
                    section="Evidence",
                    source_url=None,
                    source_date=None,
                    confidence=None,
                    raw_excerpt="## Evidence filler",
                )
            )
            n += 1
            current += 1

    for i in range(stale_count):
        g.add(
            Claim(
                id=f"r1.Worker.c{n}",
                text=f"stale evidence {i}",
                agent="Worker",
                role="worker",
                round=1,
                section="Evidence",
                source_url=f"https://old.example.com/{i}",
                source_date=date(2020, 1, 1),
                confidence=None,
                raw_excerpt="## Evidence stale",
            )
        )
        n += 1

    g.add(
        Claim(
            id=f"r1.Lead.c{n}",
            text="final answer",
            agent="Lead",
            role="leader",
            round=1,
            section=None,
            source_url=None,
            source_date=None,
            confidence="med" if include_leader_confidence else None,
            raw_excerpt="[COMPLETE] final",
        )
    )

    return g


def test_gate_flags_stale_claims() -> None:
    orch = _make_orch(critic_months=24)
    g = _seed_graph(evidence_supported=1, stale_count=1)
    orch.bus._claims = g
    ok, issues = orch._gate_check()
    assert not ok
    assert any("stale evidence claim" in i for i in issues)


def test_gate_flags_unsupported_claims() -> None:
    orch = _make_orch()
    g = _seed_graph(evidence_supported=1, evidence_unsupported=2)
    orch.bus._claims = g
    ok, issues = orch._gate_check()
    assert not ok
    assert any("missing url or date" in i for i in issues)


def test_gate_flags_zero_evidence_claims() -> None:
    orch = _make_orch()
    g = ClaimGraph()
    g.add(
        Claim(
            id="r1.Lead.c1",
            text="final",
            agent="Lead",
            role="leader",
            round=1,
            section=None,
            source_url=None,
            source_date=None,
            confidence="med",
            raw_excerpt="[COMPLETE] final",
        )
    )
    orch.bus._claims = g
    ok, issues = orch._gate_check()
    assert not ok
    assert any("zero structured Evidence claims" in i for i in issues)


def test_gate_flags_low_citation_density() -> None:
    orch = _make_orch()
    g = _seed_graph(evidence_supported=1, total_evidence_for_density=3)
    orch.bus._claims = g
    ok, issues = orch._gate_check()
    assert not ok
    assert any("citation density" in i for i in issues)


def test_gate_flags_missing_leader_confidence() -> None:
    orch = _make_orch()
    g = _seed_graph(evidence_supported=1, include_leader_confidence=False)
    orch.bus._claims = g
    ok, issues = orch._gate_check()
    assert not ok
    assert any("missing Confidence" in i for i in issues)


def test_quality_gate_failed_path_reachable() -> None:
    orch = _make_orch()
    g = _seed_graph(evidence_supported=0, evidence_unsupported=1, include_leader_confidence=False)
    orch.bus._claims = g
    ok, issues = orch._gate_check()
    assert not ok
    assert len(issues) >= 2


def test_security_team_7_month_old_source_trips_stale_with_6_month_threshold() -> None:
    orch = _make_orch(critic_months=6)
    g = ClaimGraph()
    g.add(
        Claim(
            id="r1.Worker.c1",
            text="security evidence 7 months old",
            agent="Worker",
            role="worker",
            round=1,
            section="Evidence",
            source_url="https://example.com/security",
            source_date=date(2025, 10, 1),
            confidence=None,
            raw_excerpt="## Evidence old",
        )
    )
    g.add(
        Claim(
            id="r1.Lead.c2",
            text="final",
            agent="Lead",
            role="leader",
            round=1,
            section=None,
            source_url=None,
            source_date=None,
            confidence="med",
            raw_excerpt="[COMPLETE] final",
        )
    )
    orch.bus._claims = g

    stale = orch.bus.claims.stale(orch._effective_stale_threshold(), as_of=date(2026, 5, 1))
    assert len(stale) == 1
    ok, issues = orch._gate_check()
    assert not ok
    assert any("stale evidence claim" in i for i in issues)
