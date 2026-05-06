from __future__ import annotations

from datetime import date

from agent_forge.claims import Claim, ClaimGraph
from agent_forge.bench.tasks import BenchTask, RubricCheck
from agent_forge.bench.scorer import ScoreBreakdown, score_task


def _task(*checks: RubricCheck) -> BenchTask:
    return BenchTask(
        id="t1",
        title="T",
        domain="research",
        difficulty="hard",
        prompt="p",
        expected_deliverable="d",
        checks=checks,
        source="handwritten",
        tags=(),
    )


def _claims(evidence_total: int, unsupported: int = 0) -> ClaimGraph:
    g = ClaimGraph()
    n = 1
    for i in range(evidence_total):
        is_unsupported = i < unsupported
        g.add(
            Claim(
                id=f"r1.A.c{n}",
                text=f"evidence {i}",
                agent="A",
                role="worker",
                round=1,
                section="Evidence",
                source_url=None if is_unsupported else f"https://example.com/{i}",
                source_date=None if is_unsupported else date(2026, 1, 1),
                confidence=None,
                raw_excerpt="## Evidence item",
            )
        )
        n += 1
    return g


def test_accuracy_component_pass_and_fail() -> None:
    task = _task(
        RubricCheck(id="c1", description="need phrase", required_phrases=("decision framework",)),
        RubricCheck(id="c2", description="need uncertainty", must_acknowledge_uncertainty=True),
    )
    g = _claims(1, 0)
    good = "This includes a decision framework. Uncertainty remains."
    bad = "No rubric content."
    s_good = score_task(task=task, claims=g, transcript_text=good)
    s_bad = score_task(task=task, claims=g, transcript_text=bad)
    assert s_good.accuracy == 1.0
    assert s_bad.accuracy == 0.0


def test_word_boundary_prevents_false_positive_for_short_token() -> None:
    task = _task(RubricCheck(id="c1", description="short token", required_phrases=("for",)))
    g = _claims(1, 0)
    s = score_task(task=task, claims=g, transcript_text="We did this before launch.")
    assert s.accuracy == 0.0


def test_citation_quality_and_hallucination_components() -> None:
    task = _task()
    g = _claims(evidence_total=4, unsupported=1)
    s = score_task(task=task, claims=g, transcript_text="text")
    assert s.citation_quality == 0.75
    assert s.hallucination == 0.75


def test_zero_evidence_edge_case() -> None:
    task = _task()
    g = _claims(evidence_total=0, unsupported=0)
    s = score_task(task=task, claims=g, transcript_text="text")
    assert s.citation_quality == 0.0
    assert s.hallucination == 0.0


def test_zero_rubric_checks_edge_case() -> None:
    task = _task()
    g = _claims(evidence_total=1, unsupported=0)
    s = score_task(task=task, claims=g, transcript_text="anything")
    assert s.accuracy == 1.0


def test_exact_100_and_0_inputs() -> None:
    full_task = _task(
        RubricCheck(id="c1", description="req", required_phrases=("decision framework",), must_have_citation=True),
    )
    g_full = _claims(2, 0)
    full_text = "Decision framework [Source](https://example.com). WHAT TO DO THIS WEEK. Owner timeline success metric."
    s_full = score_task(task=full_task, claims=g_full, transcript_text=full_text, latency_s=0, cost_usd=0)
    assert s_full.accuracy == 1.0
    assert s_full.citation_quality == 1.0
    assert s_full.hallucination == 1.0
    assert s_full.total <= 1.0

    zero_task = _task(RubricCheck(id="c1", description="missing", required_phrases=("nonexistentphrase",)))
    g_zero = _claims(3, 3)
    s_zero = score_task(task=zero_task, claims=g_zero, transcript_text="", latency_s=120, cost_usd=2.0)
    assert s_zero.accuracy == 0.0
    assert s_zero.citation_quality == 0.0
    assert s_zero.hallucination == 0.0


def test_weight_math_total_matches_components() -> None:
    task = _task(RubricCheck(id="c1", description="one", required_phrases=("x",)))
    g = _claims(2, 1)
    s = score_task(task=task, claims=g, transcript_text="x WHAT TO DO THIS WEEK owner timeline", latency_s=30, cost_usd=0.5)
    expected = (
        s.accuracy * 0.50
        + s.citation_quality * 0.20
        + s.hallucination * 0.15
        + s.actionability * 0.10
        + s.efficiency * 0.05
    )
    assert abs(s.total - expected) < 1e-9
