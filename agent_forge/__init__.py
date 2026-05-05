"""Agent Forge — Multi-agent orchestration framework."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__version__ = "0.6.0"

__all__ = [
    "MessageBus",
    "Message",
    "MessageType",
    "Agent",
    "AgentConfig",
    "Orchestrator",
    "Narrator",
    "TEAMS",
    "CATEGORIES",
    "TeamConfig",
    "TeamCategory",
]

_MODULE_BY_SYMBOL = {
    "MessageBus": "agent_forge.bus",
    "Message": "agent_forge.bus",
    "MessageType": "agent_forge.bus",
    "Agent": "agent_forge.agent",
    "AgentConfig": "agent_forge.agent",
    "Orchestrator": "agent_forge.engine",
    "Narrator": "agent_forge.narrator",
    "TEAMS": "agent_forge.teams",
    "CATEGORIES": "agent_forge.teams",
    "TeamConfig": "agent_forge.teams",
    "TeamCategory": "agent_forge.teams",
}


def __getattr__(name: str) -> Any:
    if name not in _MODULE_BY_SYMBOL:
        raise AttributeError(f"module 'agent_forge' has no attribute {name!r}")
    module = import_module(_MODULE_BY_SYMBOL[name])
    return getattr(module, name)
