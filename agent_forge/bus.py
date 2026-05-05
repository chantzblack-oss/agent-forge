"""Message bus for inter-agent communication."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MessageType(Enum):
    SYSTEM = "system"
    CHAT = "chat"
    TASK = "task"
    RESULT = "result"
    FEEDBACK = "feedback"
    HUMAN = "human"
    REBUTTAL = "rebuttal"  # reactive response to a challenge or critique


@dataclass
class Message:
    sender: str
    content: str
    msg_type: MessageType = MessageType.CHAT
    recipient: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    round_num: int = 0

    def format(self) -> str:
        target = f" -> {self.recipient}" if self.recipient else ""
        tag = ""
        if self.msg_type == MessageType.REBUTTAL:
            tag = " (rebuttal)"
        return f"[{self.sender}{target}{tag}] {self.content}"


def extract_requests(text: str) -> list[tuple[str, str]]:
    """Find [REQUEST @AgentName: question] patterns in agent output.

    Supports names with spaces and punctuation up to the request colon.
    Example: ``[REQUEST @Data Analyst: Validate assumptions]``.
    """
    requests: list[tuple[str, str]] = []
    for m in re.finditer(r"\[REQUEST\s+@([^:\]\n]+?)\s*:\s*(.+?)\]", text, flags=re.DOTALL):
        target = m.group(1).strip()
        question = m.group(2).strip()
        if target and question:
            requests.append((target, question))
    return requests


def _name_patterns(name: str) -> list[str]:
    """Build mention variants for a roster name.

    Supports exact form and a canonicalized underscore variant so a teammate
    named ``Data Analyst`` can be mentioned as ``@Data_Analyst``.
    """
    canonical = re.sub(r"\s+", "_", name.strip())
    variants = {name.strip(), canonical}
    return [v for v in variants if v]


def extract_mentions(text: str, valid_names: list[str]) -> list[str]:
    """Find @AgentName mentions in text, returning names that exist in roster."""
    mentioned: list[str] = []
    for name in valid_names:
        for variant in _name_patterns(name):
            pattern = rf"(?<!\w)@{re.escape(variant)}(?![\w-])"
            if re.search(pattern, text):
                mentioned.append(name)
                break
    return mentioned


class MessageBus:
    """Central hub for all agent communication."""

    def __init__(self) -> None:
        self.messages: list[Message] = []

    def post(self, message: Message) -> None:
        self.messages.append(message)

    def get_for(self, agent_name: str, limit: int = 30) -> list[Message]:
        """Messages relevant to a specific agent (broadcasts + directs)."""
        return [
            m
            for m in self.messages
            if m.recipient is None
            or m.recipient == agent_name
            or m.sender == agent_name
        ][-limit:]

    def get_all(self, limit: int = 50) -> list[Message]:
        return self.messages[-limit:]

    def format_context(
        self,
        agent_name: str,
        current_round: int = 0,
        max_chars_old: int = 1500,
    ) -> str:
        """Build a conversation transcript with smart truncation.

        Current round messages appear in full. Older round messages are
        truncated to *max_chars_old* so the context window stays focused
        on the latest work. Messages that @mention this agent are flagged
        so the agent knows to pay attention.
        """
        msgs = self.get_for(agent_name)
        if not msgs:
            return "(No messages yet — you're starting fresh.)"

        parts: list[str] = []
        active_round = -1

        for m in msgs:
            if m.round_num != active_round:
                active_round = m.round_num
                parts.append(f"══ ROUND {active_round} ══")

            content = m.content
            # Truncate messages from older rounds to keep context focused
            if current_round > 0 and m.round_num < current_round:
                if len(content) > max_chars_old:
                    content = content[:max_chars_old] + "\n[... truncated — full output was delivered above ...]"

            target = f" -> {m.recipient}" if m.recipient else ""

            # Flag messages that directly mention this agent
            mention_tag = ""
            if (
                m.sender != agent_name
                and f"@{agent_name}" in m.content
            ):
                mention_tag = " ⚡ MENTIONS YOU"

            rebuttal_tag = ""
            if m.msg_type == MessageType.REBUTTAL:
                rebuttal_tag = " (rebuttal)"

            parts.append(
                f"[{m.sender}{target}{rebuttal_tag}{mention_tag}]:\n{content}"
            )

        return "\n\n---\n\n".join(parts)

    def clear(self) -> None:
        self.messages.clear()
