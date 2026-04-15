"""Team registry — organized by category."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List
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
    quickstart_goals: list[str] = field(default_factory=list)


@dataclass
class TeamCategory:
    name: str
    icon: str
    teams: list[TeamConfig]


# Import teams AFTER TeamConfig is defined to avoid circular imports
from .core import STORYTELLER, RESEARCH_LAB, DEBATE_CLUB, STARTUP_SIM, CODE_SHOP
from .healthcare import CLINICAL_CASE, PRACTICE_GROWTH, BEHAVIORAL_HEALTH
from .creative import (
    WRITERS_ROOM, PHILOSOPHY_SALON, DND_CAMPAIGN, COMEDY_WRITERS,
    MUSIC_STUDIO, GAME_DESIGN,
)
from .technical import SECURITY_AUDIT, DATA_SCIENCE, SYSTEM_DESIGN, DEVOPS_WAR_ROOM
from .business import LEGAL_ANALYSIS, FINANCIAL_PLANNING, CRISIS_COMMS, PRODUCT_LAUNCH
from .education import STUDY_GROUP, LANGUAGE_LAB
from .personal import LIFE_STRATEGY, CAREER_BOARD
from .science import SCIENCE_LAB, INVESTIGATIVE_UNIT


CATEGORIES: list[TeamCategory] = [
    TeamCategory(
        name="Work",
        icon="\U0001f4bc",
        teams=[RESEARCH_LAB, STARTUP_SIM, CODE_SHOP, PRODUCT_LAUNCH],
    ),
    TeamCategory(
        name="Healthcare",
        icon="\U0001f3e5",
        teams=[CLINICAL_CASE, PRACTICE_GROWTH, BEHAVIORAL_HEALTH],
    ),
    TeamCategory(
        name="Creative",
        icon="\U0001f3a8",
        teams=[STORYTELLER, WRITERS_ROOM, MUSIC_STUDIO, DND_CAMPAIGN, GAME_DESIGN, COMEDY_WRITERS],
    ),
    TeamCategory(
        name="Technical",
        icon="\u2699\ufe0f",
        teams=[SECURITY_AUDIT, DATA_SCIENCE, SYSTEM_DESIGN, DEVOPS_WAR_ROOM],
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
    TeamCategory(
        name="Education",
        icon="\U0001f393",
        teams=[STUDY_GROUP, LANGUAGE_LAB],
    ),
    TeamCategory(
        name="Personal & Life",
        icon="\U0001f9ed",
        teams=[LIFE_STRATEGY, CAREER_BOARD],
    ),
    TeamCategory(
        name="Science & Investigation",
        icon="\U0001f52c",
        teams=[SCIENCE_LAB, INVESTIGATIVE_UNIT],
    ),
]

# Flat list for backward compat
TEAMS: list[TeamConfig] = []
for cat in CATEGORIES:
    TEAMS.extend(cat.teams)
