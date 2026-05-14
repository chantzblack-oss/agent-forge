"""Provider registry — resolves a provider name into a backend instance.

Preference order (when provider == "anthropic" or "google"):
    1. The subscription-authenticated CLI (no API key needed)
    2. The SDK path (requires API key)

Explicit names ("claude_cli", "gemini_cli", "claude_api", "gemini_api") skip
auto-resolution and force a specific path.
"""

from __future__ import annotations

import shutil
from functools import lru_cache

from .base import Provider, ProviderError


# ── auto-detection from model name ────────────────────────

_ANTHROPIC_MODEL_PREFIXES = ("claude-", "claude_", "opus", "sonnet", "haiku")
_GOOGLE_MODEL_PREFIXES = ("gemini", "pro", "flash")
_OPENAI_MODEL_PREFIXES = ("gpt", "gpt-", "gpt5", "o1", "o3", "o4", "4o")


def detect_provider(model: str) -> str:
    """Guess the provider family from a model string.

    Returns an alias ("anthropic" | "google" | "openai") — the actual backend
    (CLI vs SDK) is chosen later by :func:`get_provider` based on what's
    installed and configured.
    """
    m = (model or "").lower()
    if not m or m == "default":
        return "anthropic"
    for prefix in _OPENAI_MODEL_PREFIXES:
        if m.startswith(prefix):
            return "openai"
    for prefix in _ANTHROPIC_MODEL_PREFIXES:
        if m.startswith(prefix):
            return "anthropic"
    for prefix in _GOOGLE_MODEL_PREFIXES:
        if m.startswith(prefix):
            return "google"
    return "anthropic"


# ── backend resolution ────────────────────────────────────

def _resolve_anthropic_backend() -> str:
    """CLI if `claude` is on PATH, else SDK."""
    if shutil.which("claude"):
        return "claude_cli"
    return "claude_api"


def _resolve_google_backend() -> str:
    """CLI if `gemini` is on PATH, else SDK."""
    if shutil.which("gemini"):
        return "gemini_cli"
    return "gemini_api"


@lru_cache(maxsize=None)
def get_provider(name: str) -> Provider:
    """Return a singleton provider instance by name.

    Aliases ("anthropic", "google") pick the best installed backend.
    """
    # Alias resolution (subscription CLI preferred, SDK as fallback)
    if name == "anthropic":
        return get_provider(_resolve_anthropic_backend())
    if name == "google":
        return get_provider(_resolve_google_backend())

    # Concrete backends
    if name == "claude_cli":
        from .claude_cli_provider import ClaudeCliProvider
        return ClaudeCliProvider()
    if name == "gemini_cli":
        from .gemini_cli_provider import GeminiCliProvider
        return GeminiCliProvider()
    if name == "claude_api":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    if name == "gemini_api":
        from .google_provider import GoogleProvider
        return GoogleProvider()

    # OpenAI — no CLI, SDK only
    if name in ("openai", "openai_api", "gpt"):
        from .openai_provider import OpenAIProvider
        return OpenAIProvider()

    raise ProviderError(
        f"Unknown provider: {name!r}. Known: anthropic, google, openai, "
        "claude_cli, gemini_cli, claude_api, gemini_api, openai_api."
    )


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
