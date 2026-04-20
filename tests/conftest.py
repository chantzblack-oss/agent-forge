"""Shared fixtures for Agent Forge test suite."""

from __future__ import annotations

import threading
from datetime import datetime
from unittest.mock import patch

import pytest

from agent_forge.bus import MessageBus, Message, MessageType
from agent_forge.agent import AgentConfig
from agent_forge.teams import TeamConfig


@pytest.fixture
def bus() -> MessageBus:
    return MessageBus()


@pytest.fixture
def populated_bus(bus: MessageBus) -> MessageBus:
    bus.post(Message(sender="System", content="PROJECT GOAL: Build a REST API", msg_type=MessageType.SYSTEM, round_num=0))
    bus.post(Message(sender="Architect", content="Plan: Backend models, Frontend views.", msg_type=MessageType.RESULT, round_num=1))
    bus.post(Message(sender="Backend", content="SQLAlchemy model with indexes.", msg_type=MessageType.RESULT, round_num=1))
    bus.post(Message(sender="Frontend", content="React task CRUD components.", msg_type=MessageType.RESULT, round_num=1))
    bus.post(Message(sender="Architect", content="@Tester: Focus on edge cases.", msg_type=MessageType.DIRECTED, recipient="Tester", round_num=1))
    bus.post(Message(sender="CodeReviewer", content="Backend model lacks created_at index.", msg_type=MessageType.FEEDBACK, round_num=1))
    bus.post(Message(sender="Architect", content="Round 2: incorporate feedback.", msg_type=MessageType.RESULT, round_num=2))
    bus.post(Message(sender="Backend", content="Added created_at index.", msg_type=MessageType.RESULT, round_num=2))
    return bus


@pytest.fixture
def leader_config() -> AgentConfig:
    return AgentConfig(name="Architect", role="leader", personality="You are the team leader.", model="opus", temperature=0.8, icon="🏗️")

@pytest.fixture
def worker_config() -> AgentConfig:
    return AgentConfig(name="Backend", role="worker", personality="You are a backend engineer.", model="sonnet", temperature=0.7)

@pytest.fixture
def critic_config() -> AgentConfig:
    return AgentConfig(name="CodeReviewer", role="critic", personality="You are a code reviewer.", model="haiku")

@pytest.fixture
def debater_config() -> AgentConfig:
    return AgentConfig(name="Advocate", role="debater", personality="You argue FOR the proposition.")

@pytest.fixture
def judge_config() -> AgentConfig:
    return AgentConfig(name="Judge", role="judge", personality="You are an impartial judge.")

@pytest.fixture
def synthesizer_config() -> AgentConfig:
    return AgentConfig(name="Synthesizer", role="synthesizer", personality="You find cross-cutting insights.")


@pytest.fixture
def minimal_team() -> TeamConfig:
    return TeamConfig(
        name="Test Team", description="Minimal team", icon="🧪", category="Test",
        agents=[
            AgentConfig(name="Lead", role="leader", personality="Leader."),
            AgentConfig(name="Worker1", role="worker", personality="Worker."),
            AgentConfig(name="Critic1", role="critic", personality="Critic."),
        ],
        round_order=["Lead", "Worker1", "Critic1", "Lead"],
        max_rounds=2,
    )


@pytest.fixture
def parallel_team() -> TeamConfig:
    return TeamConfig(
        name="Parallel Team", description="Parallel exec", icon="⚡", category="Test",
        agents=[
            AgentConfig(name="Boss", role="leader", personality="Boss."),
            AgentConfig(name="Dev1", role="worker", personality="Dev1."),
            AgentConfig(name="Dev2", role="worker", personality="Dev2."),
            AgentConfig(name="QA", role="critic", personality="QA."),
        ],
        round_order=["Boss", "Dev1", "Dev2", "QA", "Boss"],
        max_rounds=3,
        execution_plan=[["Boss"], ["Dev1", "Dev2"], ["QA"], ["Boss"]],
    )
