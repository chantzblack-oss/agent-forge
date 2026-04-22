"""Agent Forge — Multi-agent orchestration framework."""

__version__ = "0.8.2"

from .bus import MessageBus, Message, MessageType, Scratchpad
from .agent import Agent, AgentConfig, AgentResponse
from .engine import Orchestrator
from .narrator import Narrator
from .providers import Provider, ProviderError, get_provider, detect_provider
from .teams import TEAMS, CATEGORIES, TeamConfig, TeamCategory
