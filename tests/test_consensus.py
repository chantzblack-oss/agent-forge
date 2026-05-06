from __future__ import annotations

from dataclasses import dataclass

from agent_forge.claims import Claim, ClaimGraph
from agent_forge.consensus import ConsensusEngine
from agent_forge.providers import register_provider, reset_providers


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


def _claim(text: str = "Claim text", cid: str = "r1.A.c1") -> Claim:
    return Claim(
        id=cid,
        text=text,
        agent="A",
        role="worker",
        round=1,
        section="Evidence",
        source_url="https://example.com",
        source_date=None,
        confidence=None,
        raw_excerpt=text,
    )


def test_verify_claim_full_agreement_yes_not_escalated() -> None:
    reset_providers()
    register_provider("mock-claude", lambda: MockProvider("Yes - matches evidence."))
    register_provider("mock-gpt", lambda: MockProvider("Yes - corroborated."))
    register_provider("mock-gemini", lambda: MockProvider("Yes - consistent."))

    engine = ConsensusEngine(
        models=["mock-claude", "mock-gpt", "mock-gemini"],
        judge_model="mock-judge",
        agreement_threshold=0.66,
    )
    result = engine.verify_claim(_claim(), context="ctx")
    assert result.escalated is False
    assert result.agreement == 1.0
    assert result.adjusted_confidence == "high"
    assert len(result.votes) == 3
    assert result.judge_verdict is None


def test_verify_claim_disagreement_escalates_and_uses_judge() -> None:
    reset_providers()
    register_provider("mock-claude", lambda: MockProvider("Yes - plausible."))
    register_provider("mock-gpt", lambda: MockProvider("No - contradicted."))
    register_provider("mock-gemini", lambda: MockProvider("Unsure - insufficient data."))
    register_provider("mock-judge", lambda: MockProvider("Yes - overall evidence supports it."))

    engine = ConsensusEngine(
        models=["mock-claude", "mock-gpt", "mock-gemini"],
        judge_model="mock-judge",
        agreement_threshold=0.80,
    )
    result = engine.verify_claim(_claim(), context="ctx")
    assert result.escalated is True
    assert result.judge_verdict is not None
    assert result.adjusted_confidence in ("low", "med")
    assert "escalated_to=mock-judge" in result.notes


def test_verify_claim_provider_error_degrades_to_unsure() -> None:
    class ErrorProvider:
        def complete(self, **kwargs):
            raise RuntimeError("boom")

    reset_providers()
    register_provider("mock-a", lambda: ErrorProvider())
    register_provider("mock-b", lambda: MockProvider("Yes - ok."))
    register_provider("mock-c", lambda: MockProvider("Yes - ok."))
    register_provider("mock-judge", lambda: MockProvider("Yes - ok."))

    engine = ConsensusEngine(
        models=["mock-a", "mock-b", "mock-c"],
        judge_model="mock-judge",
        agreement_threshold=0.66,
    )
    result = engine.verify_claim(_claim(), context="ctx")
    assert result.escalated is False
    assert result.adjusted_confidence in ("med", "high")
    assert any(v.lower().startswith("unsure") for v in result.votes.values())


def test_verify_evidence_updates_claim_confidence() -> None:
    reset_providers()
    register_provider("mock-claude", lambda: MockProvider("Yes - supported."))
    register_provider("mock-gpt", lambda: MockProvider("Yes - supported."))
    register_provider("mock-gemini", lambda: MockProvider("Yes - supported."))

    engine = ConsensusEngine(
        models=["mock-claude", "mock-gpt", "mock-gemini"],
        judge_model="mock-judge",
    )

    g = ClaimGraph()
    c1 = _claim(text="Evidence claim 1", cid="r1.W.c1")
    c2 = _claim(text="Evidence claim 2", cid="r1.W.c2")
    g.add(c1)
    g.add(c2)

    results = engine.verify_evidence(g, context="ctx")
    assert len(results) == 2
    by_id = {c.id: c for c in g.all()}
    assert by_id["r1.W.c1"].confidence == "high"
    assert by_id["r1.W.c2"].confidence == "high"


def test_verify_evidence_only_processes_evidence_section() -> None:
    reset_providers()
    register_provider("mock-claude", lambda: MockProvider("Yes - supported."))
    register_provider("mock-gpt", lambda: MockProvider("Yes - supported."))
    register_provider("mock-gemini", lambda: MockProvider("Yes - supported."))

    engine = ConsensusEngine(
        models=["mock-claude", "mock-gpt", "mock-gemini"],
        judge_model="mock-judge",
    )

    g = ClaimGraph()
    evidence_claim = _claim(text="Evidence claim", cid="r1.W.c1")
    non_evidence_claim = Claim(
        id="r1.W.c2",
        text="Recommendation claim",
        agent="W",
        role="worker",
        round=1,
        section="Recommendations",
        source_url=None,
        source_date=None,
        confidence=None,
        raw_excerpt="## Recommendations",
    )
    g.add(evidence_claim)
    g.add(non_evidence_claim)

    results = engine.verify_evidence(g, context="ctx")
    assert len(results) == 1
    assert results[0].claim_id == "r1.W.c1"
