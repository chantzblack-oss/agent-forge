"""LLMProvider abstraction — concrete providers implement complete()."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderCallStats:
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    latency_s: float | None = None


class LLMProvider(ABC):
    """Per-call provider interface. Implementations route a system+user prompt
    through their concrete model API and return plain text + call stats.

    No streaming for v1 — return full text. Adding streaming would require
    changes to Agent.respond and the orchestrator's display layer.
    """

    @abstractmethod
    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        timeout_s: float = 120.0,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> tuple[str, ProviderCallStats]:
        """Return (text, stats). Raise ProviderError on failure."""
