"""Anthropic provider — direct SDK calls with extended thinking + web tools.

Capabilities enabled by default on this path:

- **Extended thinking** — for Claude 4.x models (opus, sonnet, haiku). Budget
  is sized relative to ``max_tokens`` so a turn always has room for both
  reasoning and output. Temperature forced to 1.0 per Anthropic's API rules
  for thinking-enabled calls.
- **Web search** (``web_search_20250305``) — server-side; the model decides
  when to search and returns citations.
- **Web fetch** (``web_fetch_20250910``) — server-side; the model can retrieve
  specific URLs (needed for citation verification + reading cited papers).

These match the capabilities of the ``claude`` CLI path so SDK-route and
CLI-route produce comparable output.
"""

from __future__ import annotations

import os
from typing import Iterator

from .base import Provider, ProviderError


DEFAULT_MODEL = "claude-opus-4-5"

_MODEL_ALIASES: dict[str, str] = {
    "default": DEFAULT_MODEL,
    "opus":    "claude-opus-4-5",
    "sonnet":  "claude-sonnet-4-5",
    "haiku":   "claude-haiku-4-5",
}


def _resolve_model(model: str) -> str:
    return _MODEL_ALIASES.get(model, model)


def _thinking_budget(max_tokens: int) -> int:
    """Size the extended-thinking budget relative to the output budget.

    Anthropic requires budget_tokens >= 1024 and budget_tokens < max_tokens.
    For short conversational turns (max_tokens around 2000) we use the
    minimum 1024, leaving ~976 tokens for output — enough for a 150-word
    reply. For larger calls we use ~40% of max_tokens with a ceiling that
    always leaves at least 512 tokens for the actual response.
    """
    if max_tokens <= 2048:
        # Use the API minimum; gives output max_tokens - 1024
        return 1024
    budget = max(1024, (max_tokens * 4) // 10)
    ceiling = max_tokens - 512
    return min(budget, ceiling)


class AnthropicProvider(Provider):
    """Anthropic Claude via the official SDK with extended thinking + web tools."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        enable_web_search: bool = True,
        enable_web_fetch: bool = True,
        enable_thinking: bool = True,
    ) -> None:
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
        self._enable_web_fetch = enable_web_fetch
        self._enable_thinking = enable_thinking

    # ── public ────────────────────────────────────────────

    def stream(self, system: str, user: str, model: str, max_tokens: int) -> Iterator[str]:
        kwargs = self._call_kwargs(system, user, model, max_tokens)
        with self._client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                if text:
                    yield text

    def complete(self, system: str, user: str, model: str, max_tokens: int) -> str:
        kwargs = self._call_kwargs(system, user, model, max_tokens)
        msg = self._client.messages.create(**kwargs)
        parts: list[str] = []
        for block in msg.content:
            # TextBlock has .text; tool_use / thinking blocks are filtered out
            # for the final prose string.
            if getattr(block, "type", "") == "thinking":
                continue
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts)

    # ── call construction ────────────────────────────────

    def _call_kwargs(
        self, system: str, user: str, model: str, max_tokens: int,
    ) -> dict:
        """Build the kwargs dict for messages.create / messages.stream."""
        kwargs: dict = {
            "model": _resolve_model(model),
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": self._tools(),
        }
        if self._enable_thinking:
            # Anthropic API rule: when extended thinking is on, temperature
            # must be exactly 1.0 (or omitted, which defaults to 1.0).
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": _thinking_budget(max_tokens),
            }
        return kwargs

    # ── tools ────────────────────────────────────────────

    def _tools(self) -> list[dict]:
        tools: list[dict] = []
        if self._enable_web_search:
            tools.append({
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5,
            })
        if self._enable_web_fetch:
            tools.append({
                "type": "web_fetch_20250910",
                "name": "web_fetch",
                "max_uses": 5,
            })
        return tools
