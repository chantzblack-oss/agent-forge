"""Thread-safe message bus with round summaries and shared scratchpad."""

from __future__ import annotations

import threading
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
    DIRECT = "direct"


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


class Scratchpad:
    """Thread-safe shared artifact store for agents to build on.

    Agents can write named artifacts (code, data, conclusions) that persist
    across rounds.  Every agent sees the full scratchpad in their context so
    they can reference and update shared work products.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._artifacts: dict[str, dict] = {}

    def write(self, key: str, content: str, author: str, round_num: int) -> None:
        with self._lock:
            self._artifacts[key] = {
                "content": content,
                "author": author,
                "round": round_num,
                "updated": datetime.now(),
            }

    def read(self, key: str) -> str | None:
        with self._lock:
            entry = self._artifacts.get(key)
            return entry["content"] if entry else None

    def all_entries(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._artifacts)

    def format_for_context(self) -> str:
        with self._lock:
            if not self._artifacts:
                return ""
            parts = ["══ SHARED SCRATCHPAD ══"]
            for key, entry in self._artifacts.items():
                header = f"📌 [{key}] (by {entry['author']}, round {entry['round']})"
                parts.append(f"{header}:\n{entry['content']}")
            return "\n\n".join(parts)


class MessageBus:
    """Thread-safe central hub for all agent communication.

    Improvements over v0.3:
    - Thread-safe via ``threading.Lock`` (required for parallel agent execution).
    - Round summaries replace aggressive per-message truncation so agents in
      round 3 still understand round 1 at a conceptual level.
    - Shared ``Scratchpad`` lets agents collaboratively build artifacts.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.messages: list[Message] = []
        self.scratchpad = Scratchpad()
        self._round_summaries: dict[int, str] = {}

    # ── posting / querying ───────────────────────────────

    def post(self, message: Message) -> None:
        with self._lock:
            self.messages.append(message)

    def get_for(self, agent_name: str, limit: int = 50) -> list[Message]:
        """Messages relevant to a specific agent (broadcasts + directs)."""
        with self._lock:
            relevant = [
                m
                for m in self.messages
                if m.recipient is None
                or m.recipient == agent_name
                or m.sender == agent_name
            ]
            return relevant[-limit:]

    def get_all(self, limit: int = 50) -> list[Message]:
        with self._lock:
            return self.messages[-limit:]

    def get_round_messages(self, round_num: int) -> list[Message]:
        with self._lock:
            return [m for m in self.messages if m.round_num == round_num]

    # ── round summaries ──────────────────────────────────

    def set_round_summary(self, round_num: int, summary: str) -> None:
        """Cache a concise summary for an entire round.

        Once set, ``format_context`` will use the summary instead of the raw
        messages for that round (when building context for later rounds).
        """
        with self._lock:
            self._round_summaries[round_num] = summary

    def get_round_summary(self, round_num: int) -> str | None:
        with self._lock:
            return self._round_summaries.get(round_num)

    # ── context formatting ───────────────────────────────

    def format_context(
        self,
        agent_name: str,
        current_round: int = 0,
    ) -> str:
        """Build a conversation transcript with round summaries for older rounds.

        Current-round messages appear in full.  Older rounds are replaced by
        their cached summary (if one exists) so context stays focused without
        losing the conceptual thread.
        """
        msgs = self.get_for(agent_name)
        if not msgs:
            return "(No messages yet — you're starting fresh.)"

        # Snapshot summaries under lock
        with self._lock:
            summaries = dict(self._round_summaries)

        parts: list[str] = []
        emitted_summary_rounds: set[int] = set()
        active_round = -1

        for m in msgs:
            # ── entering a new round ──
            if m.round_num != active_round:
                active_round = m.round_num

                # Old round with a cached summary → emit once, skip raw messages
                if current_round > 0 and active_round < current_round and active_round in summaries:
                    if active_round not in emitted_summary_rounds:
                        parts.append(
                            f"══ ROUND {active_round} (SUMMARY) ══\n{summaries[active_round]}"
                        )
                        emitted_summary_rounds.add(active_round)
                    continue
                else:
                    parts.append(f"══ ROUND {active_round} ══")

            # Skip individual messages from already-summarised rounds
            if active_round in emitted_summary_rounds:
                continue

            target = f" -> {m.recipient}" if m.recipient else ""
            parts.append(f"[{m.sender}{target}]:\n{m.content}")

        # Append shared scratchpad so every agent sees it
        scratchpad_ctx = self.scratchpad.format_for_context()
        if scratchpad_ctx:
            parts.append(scratchpad_ctx)

        return "\n\n---\n\n".join(parts)

    # ── lifecycle ────────────────────────────────────────

    def clear(self) -> None:
        with self._lock:
            self.messages.clear()
            self._round_summaries.clear()
            self.scratchpad = Scratchpad()
