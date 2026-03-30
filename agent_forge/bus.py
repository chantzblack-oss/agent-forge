"""Message bus for inter-agent communication."""

from __future__ import annotations

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
        return f"[{self.sender}{target}] {self.content}"


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
        on the latest work.
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
            # NEVER truncate SYSTEM messages (e.g. PROJECT GOAL) — agents need the full goal
            if current_round > 0 and m.round_num < current_round and m.msg_type != MessageType.SYSTEM:
                if len(content) > max_chars_old:
                    content = content[:max_chars_old] + "\n[... truncated — full output was delivered above ...]"

            target = f" -> {m.recipient}" if m.recipient else ""
            parts.append(f"[{m.sender}{target}]:\n{content}")

        return "\n\n---\n\n".join(parts)

    def clear(self) -> None:
        self.messages.clear()
