"""Cross-model consensus protocol — claim-level verification across providers.

Each Evidence claim emitted by the team can be re-asked of N independent
provider models with a Yes/No/Unsure verdict. Majority resolves; ties or
disagreement below threshold escalate to a stronger judge model. The
result overwrites the claim's confidence in the ClaimGraph so downstream
gates and the bench scorer consume the verified value.

Provider failures degrade to 'unsure' rather than aborting consensus —
the protocol is robustness-over-purity. The notes field preserves the
error for debugging.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent_forge.claims import Claim, ClaimGraph, Confidence
from agent_forge.providers import get_provider

VerdictLabel = Literal["yes", "no", "unsure"]


@dataclass(frozen=True)
class ConsensusResult:
    claim_id: str
    original_text: str
    votes: dict[str, str]
    agreement: float
    escalated: bool
    judge_verdict: str | None
    adjusted_confidence: Confidence
    notes: str


class ConsensusEngine:
    def __init__(
        self,
        models: list[str],
        judge_model: str,
        agreement_threshold: float = 0.66,
    ) -> None:
        if not models:
            raise ValueError("ConsensusEngine requires at least one verification model")
        self.models = models
        self.judge_model = judge_model
        self.agreement_threshold = agreement_threshold

    def verify_claim(self, claim: Claim, context: str) -> ConsensusResult:
        votes: dict[str, str] = {}
        labels: list[VerdictLabel] = []

        for model in self.models:
            verdict = self._ask_model(model=model, claim=claim, context=context)
            votes[model] = verdict
            labels.append(self._extract_label(verdict))

        majority_label, agreement = self._majority(labels)
        escalated = agreement < self.agreement_threshold
        judge_verdict: str | None = None

        final_label: VerdictLabel = majority_label
        notes = f"majority={majority_label}; agreement={agreement:.2f}"

        if escalated:
            judge_verdict = self._ask_judge(claim=claim, context=context, votes=votes)
            judge_label = self._extract_label(judge_verdict)
            final_label = judge_label
            notes = f"{notes}; escalated_to={self.judge_model}; judge={judge_label}"

        adjusted_confidence = self._label_to_confidence(final_label, agreement, escalated)
        return ConsensusResult(
            claim_id=claim.id,
            original_text=claim.text,
            votes=votes,
            agreement=agreement,
            escalated=escalated,
            judge_verdict=judge_verdict,
            adjusted_confidence=adjusted_confidence,
            notes=notes,
        )

    def verify_evidence(self, graph: ClaimGraph, context: str) -> list[ConsensusResult]:
        results: list[ConsensusResult] = []
        by_id = {c.id: c for c in graph.all()}

        for claim in graph.evidence_claims():
            result = self.verify_claim(claim=claim, context=context)
            results.append(result)
            target = by_id.get(result.claim_id)
            if target is not None:
                target.confidence = result.adjusted_confidence

        return results

    def _ask_model(self, *, model: str, claim: Claim, context: str) -> str:
        system = (
            "You are a strict verifier. "
            "Answer with exactly one of: Yes / No / Unsure, then one sentence reason."
        )
        user = (
            f"Context:\n{context}\n\n"
            f"Claim:\n{claim.text}\n\n"
            "Question: Does this claim hold?"
        )
        try:
            provider = get_provider(model)
            text, _stats = provider.complete(
                model=model,
                system=system,
                user=user,
                timeout_s=60.0,
                temperature=0.0,
            )
            return (text or "").strip() or "Unsure - empty response."
        except Exception as exc:
            return f"Unsure - provider error: {exc}"

    def _ask_judge(self, *, claim: Claim, context: str, votes: dict[str, str]) -> str:
        system = (
            "You are the consensus judge. "
            "Given model votes, return exactly one of Yes / No / Unsure "
            "plus one sentence justification."
        )
        votes_block = "\n".join(f"- {m}: {v}" for m, v in votes.items())
        user = (
            f"Context:\n{context}\n\n"
            f"Claim:\n{claim.text}\n\n"
            f"Votes:\n{votes_block}\n\n"
            "Decide final verdict."
        )
        try:
            provider = get_provider(self.judge_model)
            text, _stats = provider.complete(
                model=self.judge_model,
                system=system,
                user=user,
                timeout_s=90.0,
                temperature=0.0,
            )
            return (text or "").strip() or "Unsure - empty judge response."
        except Exception as exc:
            return f"Unsure - judge error: {exc}"

    @staticmethod
    def _extract_label(text: str) -> VerdictLabel:
        t = (text or "").strip().lower()
        if t.startswith("yes"):
            return "yes"
        if t.startswith("no"):
            return "no"
        return "unsure"

    @staticmethod
    def _majority(labels: list[VerdictLabel]) -> tuple[VerdictLabel, float]:
        counts = {"yes": 0, "no": 0, "unsure": 0}
        for label in labels:
            counts[label] += 1
        winner = max(counts.items(), key=lambda kv: kv[1])[0]
        agreement = counts[winner] / max(1, len(labels))
        return winner, agreement  # type: ignore[return-value]

    @staticmethod
    def _label_to_confidence(label: VerdictLabel, agreement: float, escalated: bool) -> Confidence:
        if label == "yes":
            if not escalated and agreement >= 0.99:
                return "high"
            if agreement >= 0.66:
                return "med"
            return "low"
        return "low"  # 'no' or 'unsure'
