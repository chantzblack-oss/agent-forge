"""Stub scorer. Codex owns the real scoring logic; this exists so runner.py
has a stable callable to import. Replace with the production version.

Score components (weights agreed with Codex):
  accuracy:           0.50
  citation_quality:   0.20
  hallucination_pen:  0.15
  actionability:      0.10
  efficiency:         0.05
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .tasks import BenchTask


WEIGHTS: dict[str, float] = {
    "accuracy": 0.50,
    "citation_quality": 0.20,
    "hallucination_pen": 0.15,
    "actionability": 0.10,
    "efficiency": 0.05,
}


@dataclass
class ScoreBreakdown:
    accuracy: float = 0.0
    citation_quality: float = 0.0
    hallucination_pen: float = 0.0  # higher = better (1.0 = no hallucinations)
    actionability: float = 0.0
    efficiency: float = 0.0
    rubric_results: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return (
            self.accuracy * WEIGHTS["accuracy"]
            + self.citation_quality * WEIGHTS["citation_quality"]
            + self.hallucination_pen * WEIGHTS["hallucination_pen"]
            + self.actionability * WEIGHTS["actionability"]
            + self.efficiency * WEIGHTS["efficiency"]
        )


def score(task: BenchTask, transcript_text: str, claim_graph, *, latency_s: float = 0.0, cost_usd: float = 0.0) -> ScoreBreakdown:
    """V1 phrase-and-graph scorer. Codex will replace this body.

    Phrase checks: required_phrases must all appear (case-insensitive); any
    forbidden_phrase fails the rubric. must_have_citation: at least one
    Evidence claim with both source_url and source_date. must_acknowledge_
    uncertainty: transcript or leader claim mentions 'uncertain' / 'unknown' /
    'depends on' / similar.
    """
    breakdown = ScoreBreakdown()
    text_low = transcript_text.lower()

    rubric_pass = 0
    rubric_total = max(len(task.checks), 1)

    for check in task.checks:
        ok = True
        for phrase in check.required_phrases:
            if phrase.lower() not in text_low:
                ok = False
                breakdown.notes.append(f"{check.id}: missing required phrase '{phrase}'")
                break
        for phrase in check.forbidden_phrases:
            if phrase.lower() in text_low:
                ok = False
                breakdown.notes.append(f"{check.id}: forbidden phrase '{phrase}' present")
                break
        if ok and check.must_have_citation:
            evidence = claim_graph.evidence_claims() if claim_graph is not None else []
            cited = [c for c in evidence if c.source_url and c.source_date]
            if not cited:
                ok = False
                breakdown.notes.append(f"{check.id}: no fully cited Evidence claims")
        if ok and check.must_acknowledge_uncertainty:
            uncertainty_markers = ("uncertain", "unknown", "depends on", "unclear", "[need @human", "confidence: low")
            if not any(m in text_low for m in uncertainty_markers):
                ok = False
                breakdown.notes.append(f"{check.id}: no uncertainty markers")
        breakdown.rubric_results[check.id] = ok
        if ok:
            rubric_pass += 1

    breakdown.accuracy = rubric_pass / rubric_total

    if claim_graph is not None:
        breakdown.citation_quality = claim_graph.citation_density()
        unsupported = len(claim_graph.unsupported())
        stale = len(claim_graph.stale(24))
        evidence_total = max(len(claim_graph.evidence_claims()), 1)
        # Hallucination proxy: fraction of evidence claims that are NOT unsupported and NOT stale.
        good = max(evidence_total - unsupported - stale, 0)
        breakdown.hallucination_pen = good / evidence_total
    else:
        breakdown.citation_quality = 0.0
        breakdown.hallucination_pen = 0.0

    if "what to do this week" in text_low or "## action" in text_low:
        breakdown.actionability = 1.0
    elif "recommend" in text_low or "next step" in text_low:
        breakdown.actionability = 0.5

    # Efficiency: 1.0 at <=60s, linearly down to 0.0 at 600s. Cost not weighted in v1.
    if latency_s <= 0:
        breakdown.efficiency = 1.0
    else:
        breakdown.efficiency = max(0.0, min(1.0, 1.0 - (latency_s - 60) / 540))

    return breakdown
