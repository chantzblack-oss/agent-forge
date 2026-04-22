"""Provider registry — resolves a provider name into a backend instance."""

from __future__ import annotations

from functools import lru_cache

from .base import Provider, ProviderError


# ── auto-detection from model name ────────────────────────

_ANTHROPIC_MODEL_PREFIXES = ("claude-", "claude_", "opus", "sonnet", "haiku")
_GOOGLE_MODEL_PREFIXES = ("gemini",)


def detect_provider(model: str) -> str:
    """Guess the provider name from a model string.

    Falls back to 'anthropic' for empty or 'default' model values since that
    was the pre-v0.6 behavior.
    """
    m = (model or "").lower()
    if not m or m == "default":
        return "anthropic"
    for prefix in _ANTHROPIC_MODEL_PREFIXES:
        if m.startswith(prefix):
            return "anthropic"
    for prefix in _GOOGLE_MODEL_PREFIXES:
        if m.startswith(prefix):
            return "google"
    # Default when we can't tell
    return "anthropic"


# ── construction (cached) ─────────────────────────────────

@lru_cache(maxsize=None)
def get_provider(name: str) -> Provider:
    """Return a singleton provider instance by name.

    Providers are expensive to construct (API clients, SDK imports) and
    stateless across calls, so we cache one instance per name.
    """
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    if name == "google":
        from .google_provider import GoogleProvider
        return GoogleProvider()
    if name == "claude_cli":
        from .claude_cli_provider import ClaudeCliProvider
        return ClaudeCliProvider()
    raise ProviderError(f"Unknown provider: {name!r}. Known: anthropic, google, claude_cli.")


def reset_providers() -> None:
    """Clear the provider cache — useful in tests or after changing env vars."""
    get_provider.cache_clear()


__all__ = [
    "Provider",
    "ProviderError",
    "get_provider",
    "detect_provider",
    "reset_providers",
]
