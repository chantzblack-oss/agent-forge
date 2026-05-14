"""Provider abstraction — backends that generate agent responses.

A provider knows how to call a specific LLM API (Anthropic, Google, etc.)
given a system prompt and user prompt. Providers must implement both
streaming (for sequential agent turns) and complete (for parallel execution
where output is captured then displayed).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator


class Provider(ABC):
    """Abstract backend that produces agent responses."""

    name: str = "abstract"

    @abstractmethod
    def stream(self, system: str, user: str, model: str, max_tokens: int) -> Iterator[str]:
        """Yield text chunks as they are generated.

        Implementations should yield whatever granularity the underlying API
        produces (token, sentence, whole response) — the orchestrator treats
        each yielded string as a partial append.
        """
        raise NotImplementedError

    @abstractmethod
    def complete(self, system: str, user: str, model: str, max_tokens: int) -> str:
        """Return the full response as a single string."""
        raise NotImplementedError


class ProviderError(RuntimeError):
    """Raised when a provider fails in an expected way (missing key, bad model, etc.)."""
