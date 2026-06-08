"""Wonderlab content contracts.

These dataclasses are the bridge between Agent Forge deliberation and a
renderer. Agents can be messy while they think; Wonderlab episodes should be
structured, auditable artifacts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ClaimType = Literal[
    "historical",
    "scientific",
    "economic",
    "interpretive",
    "controversial",
    "definition",
]
Confidence = Literal["high", "medium", "low"]
DisagreementType = Literal[
    "factual",
    "framing",
    "emphasis",
    "source-quality",
    "missing-context",
]
DisagreementResolution = Literal[
    "accepted",
    "rejected",
    "downgraded",
    "shown-as-controversy",
    "needs-human-review",
]
SceneType = Literal[
    "cinematic-intro",
    "scroll-story",
    "interactive-simulation",
    "timeline",
    "map",
    "debate",
    "myth-vs-reality",
    "source-gallery",
    "systems-diagram",
    "quiz",
    "synthesis-challenge",
]
PublishDecision = Literal["publish", "revise", "human-review", "reject"]
BuildMode = Literal["quick", "deep", "masterpiece"]


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    source_type: str
    publisher: str = ""
    year: str = ""
    url: str = ""
    notes: str = ""
    verification_status: str = "seeded-not-fetched"
    verified_title: str = ""
    verification_excerpt: str = ""
    verification_error: str = ""
    checked_at: str = ""


@dataclass(frozen=True)
class ClaimEvidence:
    source_id: str
    summary: str
    quote: str = ""
    locator: str = ""
    verification_status: str = "seeded"


@dataclass(frozen=True)
class Claim:
    id: str
    text: str
    claim_type: ClaimType
    confidence: Confidence
    sources: list[str] = field(default_factory=list)
    evidence: list[ClaimEvidence] = field(default_factory=list)
    supporting_evidence: list[str] = field(default_factory=list)
    counterpoints: list[str] = field(default_factory=list)
    used_in_scenes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ModelPosition:
    model: str
    position: str
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Disagreement:
    claim_id: str
    disagreement_type: DisagreementType
    model_positions: list[ModelPosition]
    resolution: DisagreementResolution
    summary: str = ""


@dataclass(frozen=True)
class TimelineEvent:
    id: str
    label: str
    period: str
    description: str
    claim_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Concept:
    id: str
    label: str
    explanation: str
    claim_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class InteractionVariable:
    id: str
    label: str
    min: float
    max: float
    default: float
    explanation: str


@dataclass(frozen=True)
class InteractionSpec:
    type: str
    title: str
    variables: list[InteractionVariable] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    learning_reveal: str = ""
    renderer_hint: str = ""


@dataclass(frozen=True)
class EpisodeScene:
    id: str
    title: str
    scene_type: SceneType
    learning_goal: str
    hook: str
    narration: list[str]
    visual_direction: str
    claims_used: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    estimated_reading_time_seconds: int = 60
    interaction: InteractionSpec | None = None


@dataclass(frozen=True)
class ResearchDossier:
    topic: str
    central_mystery: str
    one_sentence_thesis: str
    key_questions: list[str]
    timeline: list[TimelineEvent]
    core_concepts: list[Concept]
    misconceptions: list[str]
    controversies: list[str]
    claim_ledger: list[Claim]
    source_graph: list[Source]
    disagreements: list[Disagreement]
    visual_opportunities: list[str]
    interaction_opportunities: list[str]
    recommended_episode_structure: list[str]


@dataclass(frozen=True)
class EpisodeSpec:
    id: str
    title: str
    subtitle: str
    topic: str
    central_mystery: str
    mode: BuildMode
    scenes: list[EpisodeScene]
    claim_ledger: list[Claim]
    source_graph: list[Source]
    disagreements: list[Disagreement]
    source_lens_enabled: bool = True


@dataclass(frozen=True)
class EvalReport:
    factual_accuracy: int
    citation_coverage: int
    claim_scene_coverage: int
    source_quality: int
    conceptual_depth: int
    narrative_arc: int
    interaction_value: int
    accessibility: int
    performance_risk: int
    hallucination_risk: int
    publish_decision: PublishDecision
    required_fixes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StageResult:
    stage: str
    agent_role: str
    summary: str
    artifact_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WonderlabRun:
    run_id: str
    topic: str
    mode: BuildMode
    stages: list[StageResult]
    dossier: ResearchDossier
    episode: EpisodeSpec
    eval_report: EvalReport


def to_plain_dict(value: Any) -> Any:
    """Return JSON-ready dictionaries for dataclass artifacts."""
    return asdict(value)
