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
    # If None, the orchestrator runs round_order fully sequentially.
    execution_plan: list[list[str]] | None = None

    # ── live deliberation mode ──────────────────────────
    # When True, a "round" is a dynamic back-and-forth conversation with
    # short turns and speaker selection based on @-mentions, [DIRECT @X]
    # requests, and leader moderation — instead of fixed round_order iteration.
    # Feels like a live meeting; different agents jump in as they have things
    # to add.  Default False (classic fixed-order rounds).
    deliberation_mode: bool = False
    # Max turns within a single deliberation "round" before forcing synthesis.
    max_deliberation_turns: int = 12
    # Per-turn soft budget — keeps turns short so the conversation flows.
    deliberation_turn_tokens: int = 800

    # ── chat mode ───────────────────────────────────────
    # When True, the team runs as a persistent conversation loop: user types
    # a question, the team deliberates and answers, the session loops until
    # the user exits.  Conversation history (bus messages) persists across
    # all user turns so context compounds naturally.
    chat_mode: bool = False


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
from .cross_model import CROSS_MODEL_BRAINTRUST, CROSS_MODEL_DEBATE, CROSS_MODEL_DELIBERATION
from .polymath import POLYMATH, POLYMATH_CLAUDE


CATEGORIES: list[TeamCategory] = [
    TeamCategory(
        name="Chat",
        icon="\U0001f4ac",
        teams=[POLYMATH_CLAUDE, POLYMATH],
    ),
    TeamCategory(
        name="Cross-Model",
        icon="\U0001f9e0",
        teams=[CROSS_MODEL_BRAINTRUST, CROSS_MODEL_DELIBERATION, CROSS_MODEL_DEBATE],
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
