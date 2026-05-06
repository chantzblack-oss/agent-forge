from __future__ import annotations

from dataclasses import dataclass
import re

from agent_forge.claims import ClaimGraph
from agent_forge.bench.tasks import BenchTask, RubricCheck


@dataclass(frozen=True)
class ScoreBreakdown:
    accuracy: float
    citation_quality: float
    hallucination: float
    actionability: float
    efficiency: float

    @property
    def total(self) -> float:
        return (
            (self.accuracy * 0.50)
            + (self.citation_quality * 0.20)
            + (self.hallucination * 0.15)
            + (self.actionability * 0.10)
            + (self.efficiency * 0.05)
        )


WEIGHTS: dict[str, float] = {
    "accuracy": 0.50,
    "citation_quality": 0.20,
    "hallucination": 0.15,
    "actionability": 0.10,
    "efficiency": 0.05,
}


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _compile_phrase_pattern(phrase: str) -> re.Pattern[str]:
    p = phrase.strip()
    if not p:
        return re.compile(r"$^")
    if re.search(r"\s", p):
        escaped = re.escape(p)
        escaped = escaped.replace(r"\ ", r"\s+")
        return re.compile(escaped, flags=re.IGNORECASE)
    return re.compile(rf"\b{re.escape(p)}\b", flags=re.IGNORECASE)


def _contains_all_required(text: str, check: RubricCheck) -> bool:
    for phrase in check.required_phrases:
        if not _compile_phrase_pattern(phrase).search(text):
            return False
    return True


def _contains_any_forbidden(text: str, check: RubricCheck) -> bool:
    for phrase in check.forbidden_phrases:
        if _compile_phrase_pattern(phrase).search(text):
            return True
    return False


def _has_citation_like(text: str) -> bool:
    return bool(re.search(r"\[[^\]]+\]\(https?://[^)]+\)", text))


def _has_uncertainty_signal(text: str) -> bool:
    return bool(
        re.search(
            r"\b(uncertain|uncertainty|assumption|assumptions|unknown|confidence)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _actionability_score(text: str) -> float:
    signals = 0
    if re.search(r"\b(what to do this week|action items|recommendations?)\b", text, re.I):
        signals += 1
    if re.search(r"\b(owner|timeline|success metric|next 90 days|next steps)\b", text, re.I):
        signals += 1
    if re.search(r"\b(1\.|2\.|3\.|- )", text):
        signals += 1
    return signals / 3.0


def _efficiency_score(latency_s: float | None, cost_usd: float | None) -> float:
    if latency_s is None and cost_usd is None:
        return 0.5
    lat_score = 0.5
    if latency_s is not None:
        lat_score = _clamp01(1.0 - (latency_s / 60.0))
    cost_score = 0.5
    if cost_usd is not None:
        cost_score = _clamp01(1.0 - cost_usd)
    return (lat_score + cost_score) / 2.0


def score_task(
    *,
    task: BenchTask,
    claims: ClaimGraph,
    transcript_text: str,
    latency_s: float | None = None,
    cost_usd: float | None = None,
) -> ScoreBreakdown:
    text = transcript_text or ""

    checks = task.checks
    if not checks:
        accuracy = 1.0
    else:
        passed = 0
        for check in checks:
            ok = True
            if not _contains_all_required(text, check):
                ok = False
            if _contains_any_forbidden(text, check):
                ok = False
            if check.must_have_citation and not _has_citation_like(text):
                ok = False
            if check.must_acknowledge_uncertainty and not _has_uncertainty_signal(text):
                ok = False
            if ok:
                passed += 1
        accuracy = passed / len(checks)

    evidence_claims = claims.evidence_claims()
    if not evidence_claims:
        citation_quality = 0.0
    else:
        citation_quality = _clamp01(claims.citation_density())

    if not evidence_claims:
        hallucination = 0.0
    else:
        unsupported = len(claims.unsupported())
        hallucination = _clamp01(1.0 - (unsupported / len(evidence_claims)))

    actionability = _actionability_score(text)
    efficiency = _efficiency_score(latency_s=latency_s, cost_usd=cost_usd)

    return ScoreBreakdown(
        accuracy=_clamp01(accuracy),
        citation_quality=_clamp01(citation_quality),
        hallucination=_clamp01(hallucination),
        actionability=_clamp01(actionability),
        efficiency=_clamp01(efficiency),
    )
