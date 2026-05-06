from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Domain = Literal[
    "research",
    "decision",
    "technical",
    "debate",
    "security",
    "healthcare",
    "policy",
]

Difficulty = Literal["medium", "hard", "very_hard"]


@dataclass(frozen=True)
class RubricCheck:
    id: str
    description: str
    required_phrases: tuple[str, ...] = ()
    forbidden_phrases: tuple[str, ...] = ()
    must_have_citation: bool = False
    must_acknowledge_uncertainty: bool = False


@dataclass(frozen=True)
class BenchTask:
    id: str
    title: str
    domain: Domain
    difficulty: Difficulty
    prompt: str
    expected_deliverable: str
    checks: tuple[RubricCheck, ...] = field(default_factory=tuple)
    source: Literal["handwritten", "adapted_public"] = "handwritten"
    tags: tuple[str, ...] = ()


def _handwritten_tasks() -> list[BenchTask]:
    return [
        BenchTask(
            id="hw_research_01",
            title="Grid Transition Tradeoff Synthesis",
            domain="research",
            difficulty="hard",
            source="handwritten",
            tags=("energy", "economics", "infrastructure"),
            prompt=(
                "Assess whether the U.S. can reach 100% clean electricity by 2035 while "
                "maintaining reliability and affordability. Provide an executive recommendation "
                "with assumptions, risks, and first-90-day actions."
            ),
            expected_deliverable="decision memo with evidence-backed action plan",
            checks=(
                RubricCheck(
                    id="c1",
                    description="Must include explicit reliability-affordability tradeoff analysis",
                    required_phrases=("reliability", "affordability", "tradeoff"),
                ),
                RubricCheck(
                    id="c2",
                    description="Must include concrete action items",
                    required_phrases=("WHAT TO DO THIS WEEK", "action"),
                ),
                RubricCheck(
                    id="c3",
                    description="Must include citations",
                    must_have_citation=True,
                ),
            ),
        ),
        BenchTask(
            id="hw_security_01",
            title="SaaS Security Audit Under Compliance Constraints",
            domain="security",
            difficulty="hard",
            source="handwritten",
            tags=("soc2", "threat_model", "grc"),
            prompt=(
                "You are auditing a B2B SaaS handling healthcare scheduling and payment data. "
                "Identify top 5 security risks, map each to SOC 2/NIST controls, and propose "
                "mitigations with residual risk."
            ),
            expected_deliverable="risk register with control mapping and mitigation plan",
            checks=(
                RubricCheck(
                    id="c1",
                    description="Must map findings to named controls",
                    required_phrases=("SOC 2", "NIST"),
                ),
                RubricCheck(
                    id="c2",
                    description="Must include residual risk reasoning",
                    required_phrases=("residual risk",),
                ),
                RubricCheck(
                    id="c3",
                    description="Must include citations",
                    must_have_citation=True,
                ),
            ),
        ),
        BenchTask(
            id="hw_technical_01",
            title="Rate Limiter Design Decision",
            domain="technical",
            difficulty="hard",
            source="handwritten",
            tags=("system_design", "backend"),
            prompt=(
                "Design a multi-tenant rate limiter supporting burst handling, fairness, and "
                "regional failover. Recommend architecture and justify token bucket vs sliding "
                "window tradeoffs."
            ),
            expected_deliverable="architecture decision with operational constraints",
            checks=(
                RubricCheck(
                    id="c1",
                    description="Must discuss at least two algorithm choices",
                    required_phrases=("token bucket", "sliding window"),
                ),
                RubricCheck(
                    id="c2",
                    description="Must include failure-mode analysis",
                    required_phrases=("failure mode", "fallback"),
                ),
            ),
        ),
        BenchTask(
            id="hw_debate_01",
            title="Policy Debate with Steelman Requirements",
            domain="debate",
            difficulty="medium",
            source="handwritten",
            tags=("public_policy", "argumentation"),
            prompt=(
                "Debate whether cities should ban private cars in downtown cores by 2035. "
                "Provide strongest argument for and against, then a decision framework."
            ),
            expected_deliverable="balanced debate plus explicit decision framework",
            checks=(
                RubricCheck(
                    id="c1",
                    description="Must present both sides charitably",
                    required_phrases=("for", "against", "decision framework"),
                ),
                RubricCheck(
                    id="c2",
                    description="Must include uncertainty bounds",
                    must_acknowledge_uncertainty=True,
                ),
            ),
        ),
        BenchTask(
            id="hw_ambiguity_01",
            title="Adversarial Ambiguity Handling",
            domain="decision",
            difficulty="very_hard",
            source="handwritten",
            tags=("uncertainty", "clarification"),
            prompt=(
                "Decide whether Project Atlas should be approved immediately. (No definition of "
                "Project Atlas, constraints, budget, timeline, or success criteria provided.)"
            ),
            expected_deliverable="safe handling of ambiguity with clarification requests",
            checks=(
                RubricCheck(
                    id="c1",
                    description="Must request clarifying info before hard recommendation",
                    required_phrases=("need", "clarify", "assumption"),
                ),
                RubricCheck(
                    id="c2",
                    description="Must acknowledge uncertainty explicitly",
                    must_acknowledge_uncertainty=True,
                ),
            ),
        ),
    ]


def _adapted_public_tasks() -> list[BenchTask]:
    return [
        BenchTask(
            id="pub_multihop_01",
            title="Multi-hop Fact Synthesis (Hotpot-style adapted)",
            domain="research",
            difficulty="hard",
            source="adapted_public",
            tags=("multihop", "fact_synthesis"),
            prompt=(
                "Answer a multi-hop factual question requiring at least two independent sources; "
                "include reconciliation if sources disagree."
            ),
            expected_deliverable="single answer with multi-source support",
            checks=(RubricCheck(id="c1", description="Must cite >=2 sources", must_have_citation=True),),
        ),
        BenchTask(
            id="pub_mmlu_policy_01",
            title="Policy/Econ Reasoning (MMLU-style adapted)",
            domain="policy",
            difficulty="hard",
            source="adapted_public",
            tags=("econ", "policy"),
            prompt=(
                "Evaluate a policy scenario with competing macroeconomic outcomes and choose a "
                "policy path under uncertainty."
            ),
            expected_deliverable="reasoned policy choice with alternatives",
            checks=(RubricCheck(id="c1", description="Must compare alternatives", required_phrases=("alternative", "tradeoff")),),
        ),
        BenchTask(
            id="pub_gpqa_science_01",
            title="Scientific Claim Audit (GPQA-style adapted)",
            domain="research",
            difficulty="very_hard",
            source="adapted_public",
            tags=("science", "evidence_quality"),
            prompt=(
                "Assess a contested scientific claim. Distinguish hypothesis, evidence quality, "
                "and what experiment would falsify the conclusion."
            ),
            expected_deliverable="claim audit with falsifiability criteria",
            checks=(
                RubricCheck(id="c1", description="Must include falsification condition", required_phrases=("falsify",)),
                RubricCheck(id="c2", description="Must include citations", must_have_citation=True),
            ),
        ),
        BenchTask(
            id="pub_security_reasoning_01",
            title="Threat Model Reasoning (CTF/security-style adapted)",
            domain="security",
            difficulty="hard",
            source="adapted_public",
            tags=("threat_model", "mitigation"),
            prompt=(
                "Given a web architecture narrative, identify probable attack chains and prioritize "
                "mitigations by exploitability and impact."
            ),
            expected_deliverable="prioritized threat model and mitigation roadmap",
            checks=(RubricCheck(id="c1", description="Must prioritize by impact + likelihood", required_phrases=("impact", "likelihood")),),
        ),
        BenchTask(
            id="pub_healthcare_reasoning_01",
            title="Clinical Evidence Triage (exam-style adapted)",
            domain="healthcare",
            difficulty="very_hard",
            source="adapted_public",
            tags=("clinical", "evidence"),
            prompt=(
                "Given a clinical scenario, compare likely interventions, expected outcomes, and "
                "evidence confidence without giving definitive medical advice."
            ),
            expected_deliverable="evidence triage with confidence levels",
            checks=(
                RubricCheck(id="c1", description="Must avoid overconfident diagnosis", must_acknowledge_uncertainty=True),
                RubricCheck(id="c2", description="Must include confidence labeling", required_phrases=("confidence",)),
            ),
        ),
    ]


def load_tasks() -> list[BenchTask]:
    tasks = _handwritten_tasks() + _adapted_public_tasks()
    return sorted(tasks, key=lambda t: t.id)


def get_task(task_id: str) -> BenchTask:
    for t in load_tasks():
        if t.id == task_id:
            return t
    raise KeyError(f"Unknown task id: {task_id}")
