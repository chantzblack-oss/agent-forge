"""Agent Forge — Multi-agent orchestration framework."""

__version__ = "0.6.0"

from .bus import MessageBus, Message, MessageType
from .agent import Agent, AgentConfig
from .engine import Orchestrator
from .narrator import Narrator
from .teams import TEAMS, CATEGORIES, TeamConfig, TeamCategory
