"""Team registry — organized by category."""

from __future__ import annotations

from dataclasses import dataclass, field
from ..agent import AgentConfig


@dataclass
class TeamConfig:
    name: str
    description: str
    icon: str
    category: str
    agents: list[AgentConfig]
    round_order: list[str]
    max_rounds: int = 3
    # Optional explicit execution plan: list of groups, where each group runs
    # in parallel and groups run sequentially. e.g.
    #   [["Principal"], ["Analyst", "Contrarian"], ["Synthesizer"], ["Reviewer"], ["Principal"]]
    # If None, the orchestrator auto-derives groups from round_order by
    # collapsing consecutive workers/debaters into parallel groups.
    execution_plan: list[list[str]] | None = None


@dataclass
class TeamCategory:
    name: str
    icon: str
    teams: list[TeamConfig]


# Import teams AFTER TeamConfig is defined to avoid circular imports
from .core import STORYTELLER, RESEARCH_LAB, DEBATE_CLUB, STARTUP_SIM, CODE_SHOP
from .healthcare import CLINICAL_CASE, PRACTICE_GROWTH, BEHAVIORAL_HEALTH
from .creative import WRITERS_ROOM, PHILOSOPHY_SALON, DND_CAMPAIGN, COMEDY_WRITERS
from .technical import SECURITY_AUDIT, DATA_SCIENCE, SYSTEM_DESIGN
from .business import LEGAL_ANALYSIS, FINANCIAL_PLANNING, CRISIS_COMMS
from .cross_model import CROSS_MODEL_BRAINTRUST, CROSS_MODEL_DEBATE


CATEGORIES: list[TeamCategory] = [
    TeamCategory(
        name="Cross-Model",
        icon="\U0001f9e0",
        teams=[CROSS_MODEL_BRAINTRUST, CROSS_MODEL_DEBATE],
    ),
    TeamCategory(
        name="Work",
        icon="\U0001f4bc",
        teams=[RESEARCH_LAB, STARTUP_SIM, CODE_SHOP],
    ),
    TeamCategory(
        name="Healthcare",
        icon="\U0001f3e5",
        teams=[CLINICAL_CASE, PRACTICE_GROWTH, BEHAVIORAL_HEALTH],
    ),
    TeamCategory(
        name="Creative",
        icon="\U0001f3a8",
        teams=[STORYTELLER, WRITERS_ROOM, DND_CAMPAIGN, COMEDY_WRITERS],
    ),
    TeamCategory(
        name="Technical",
        icon="\u2699\ufe0f",
        teams=[SECURITY_AUDIT, DATA_SCIENCE, SYSTEM_DESIGN],
    ),
    TeamCategory(
        name="Debate & Ideas",
        icon="\U0001f4a1",
        teams=[DEBATE_CLUB, PHILOSOPHY_SALON],
    ),
    TeamCategory(
        name="Business",
        icon="\U0001f4c8",
        teams=[LEGAL_ANALYSIS, FINANCIAL_PLANNING, CRISIS_COMMS],
    ),
]

# Flat list for backward compat
TEAMS: list[TeamConfig] = []
for cat in CATEGORIES:
    TEAMS.extend(cat.teams)
