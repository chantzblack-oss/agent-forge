"""Anthropic provider — direct SDK calls with web-search tool enabled."""

from __future__ import annotations

import os
from typing import Iterator

from .base import Provider, ProviderError


# Default model when AgentConfig.model == "default" or "opus"
DEFAULT_MODEL = "claude-opus-4-5"

# Normalize shorthand aliases → full model IDs
_MODEL_ALIASES: dict[str, str] = {
    "default": DEFAULT_MODEL,
    "opus":    "claude-opus-4-5",
    "sonnet":  "claude-sonnet-4-5",
    "haiku":   "claude-haiku-4-5",
}


def _resolve_model(model: str) -> str:
    return _MODEL_ALIASES.get(model, model)


class AnthropicProvider(Provider):
    """Anthropic Claude via the official SDK, with web-search tool on by default."""

    name = "anthropic"

    def __init__(self, api_key: str | None = None, enable_web_search: bool = True) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ProviderError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from exc

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError(
                "ANTHROPIC_API_KEY not set. Export it or add it to .env."
            )
        self._client = Anthropic(api_key=key)
        self._enable_web_search = enable_web_search

    # ── public ────────────────────────────────────────────

    def stream(self, system: str, user: str, model: str, max_tokens: int) -> Iterator[str]:
        with self._client.messages.stream(
            model=_resolve_model(model),
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=self._tools(),
        ) as stream:
            for text in stream.text_stream:
                if text:
                    yield text

    def complete(self, system: str, user: str, model: str, max_tokens: int) -> str:
        msg = self._client.messages.create(
            model=_resolve_model(model),
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=self._tools(),
        )
        parts: list[str] = []
        for block in msg.content:
            # TextBlock has .text; tool_use blocks are ignored for prose output
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts)

    # ── tools ────────────────────────────────────────────

    def _tools(self) -> list[dict]:
        if not self._enable_web_search:
            return []
        return [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5,
            }
        ]
