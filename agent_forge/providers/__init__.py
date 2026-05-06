"""Provider registry — resolve a model string to a concrete LLMProvider.

Routing is prefix-based off the model field:
  opus / sonnet / haiku / claude-*  → ClaudeProvider (CLI)
  gpt-* / o1* / o3*                  → OpenAIProvider
  gemini-*                           → GeminiProvider

Override via register_provider() for custom or test providers.
"""

from __future__ import annotations

from typing import Callable

from .base import LLMProvider, ProviderCallStats
from .errors import (
    ProviderError,
    ProviderTimeout,
    ProviderRateLimited,
    ProviderConfigError,
)


_PROVIDER_FACTORIES: dict[str, Callable[[], LLMProvider]] = {}
_INSTANCES: dict[str, LLMProvider] = {}


def register_provider(prefix: str, factory: Callable[[], LLMProvider]) -> None:
    """Register a factory for a model-name prefix. Tests use this for mocks."""
    _PROVIDER_FACTORIES[prefix.lower()] = factory
    _INSTANCES.pop(prefix.lower(), None)  # invalidate cached instance


def reset_providers() -> None:
    """Clear all registered providers and cached instances (test helper)."""
    _PROVIDER_FACTORIES.clear()
    _INSTANCES.clear()
    _register_defaults()


def get_provider(model: str) -> LLMProvider:
    """Resolve a model name to its provider instance. Cached per-prefix."""
    model_l = model.lower()
    # Longest prefix wins so 'gpt-4o-mini' matches before 'gpt-4o'.
    matches = sorted(
        (p for p in _PROVIDER_FACTORIES if model_l.startswith(p)),
        key=len,
        reverse=True,
    )
    if not matches:
        raise ProviderError(f"No provider registered for model {model!r}")
    prefix = matches[0]
    if prefix not in _INSTANCES:
        _INSTANCES[prefix] = _PROVIDER_FACTORIES[prefix]()
    return _INSTANCES[prefix]


def _register_defaults() -> None:
    """Register Claude/OpenAI/Gemini factories. Lazy-import on first use so a
    missing third-party SDK doesn't break import for users who only need one
    provider."""

    def _claude_factory() -> LLMProvider:
        from .claude import ClaudeProvider
        return ClaudeProvider()

    def _openai_factory() -> LLMProvider:
        from .openai import OpenAIProvider
        return OpenAIProvider()

    def _gemini_factory() -> LLMProvider:
        from .gemini import GeminiProvider
        return GeminiProvider()

    for p in ("opus", "sonnet", "haiku", "claude"):
        _PROVIDER_FACTORIES[p] = _claude_factory
    for p in ("gpt-", "o1", "o3"):
        _PROVIDER_FACTORIES[p] = _openai_factory
    _PROVIDER_FACTORIES["gemini"] = _gemini_factory


_register_defaults()


__all__ = [
    "LLMProvider",
    "ProviderCallStats",
    "ProviderError",
    "ProviderTimeout",
    "ProviderRateLimited",
    "ProviderConfigError",
    "register_provider",
    "reset_providers",
    "get_provider",
]
