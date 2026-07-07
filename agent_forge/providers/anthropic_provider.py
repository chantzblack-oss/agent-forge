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


# Family aliases → resolved dynamically from the live Anthropic model list
# (see agent_forge/model_resolver.resolve_anthropic). Hard-coded fallbacks
# live in the resolver so the system still works without an API call.
_FAMILY_ALIASES = {"opus", "sonnet", "haiku"}

DEFAULT_MODEL = "opus"  # family alias; dynamically resolved


def _resolve_model(model: str) -> str:
    """Resolve a family alias (opus/sonnet/haiku) to the actual latest model ID.

    Concrete model IDs (``claude-opus-4-7-20251201`` etc) pass through
    unchanged — use those to pin a specific version. Use ``opus`` /
    ``sonnet`` / ``haiku`` to always get the newest in that family.
    """
    if not model or model == "default":
        model = DEFAULT_MODEL
    if model in _FAMILY_ALIASES:
        from ..model_resolver import resolve_anthropic
        return resolve_anthropic(model)
    return model


def _thinking_budget(max_tokens: int) -> int:
    """Size the extended-thinking budget relative to the output budget.

    Anthropic requires budget_tokens >= 1024 and budget_tokens < max_tokens.
    For short conversational turns (max_tokens around 2000) we use the
    minimum 1024, leaving ~976 tokens for output — enough for a 150-word
    reply. For larger calls we use ~40% of max_tokens with a ceiling that
    always leaves at least 512 tokens for the actual response.
    """
    if max_tokens <= 3072:
        return 1024
    budget = max(1024, (max_tokens * 6) // 10)
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
        base = self._call_kwargs(system, user, model, max_tokens)
        for kwargs in self._thinking_variants(base, max_tokens):
            try:
                with self._client.messages.stream(**kwargs) as stream:
                    for text in stream.text_stream:
                        if text:
                            yield text
                return
            except Exception as e:  # noqa: BLE001
                if self._is_thinking_400(e):
                    continue  # this model rejects that thinking form; try next
                raise

    def complete(self, system: str, user: str, model: str, max_tokens: int) -> str:
        base = self._call_kwargs(system, user, model, max_tokens)
        last: Exception | None = None
        for kwargs in self._thinking_variants(base, max_tokens):
            try:
                msg = self._client.messages.create(**kwargs)
                parts: list[str] = []
                for block in msg.content:
                    if getattr(block, "type", "") == "thinking":
                        continue  # thinking blocks aren't part of the prose
                    text = getattr(block, "text", None)
                    if text:
                        parts.append(text)
                return "".join(parts)
            except Exception as e:  # noqa: BLE001
                last = e
                if self._is_thinking_400(e):
                    continue
                raise
        raise last  # type: ignore[misc]

    # ── thinking negotiation ──────────────────────────────

    @staticmethod
    def _is_thinking_400(e: Exception) -> bool:
        """True when a request failed specifically because of the thinking
        parameter (so a different thinking form may succeed)."""
        msg = str(getattr(e, "message", e)).lower()
        return ("400" in str(getattr(e, "status_code", "")) or "400" in msg
                or "invalid_request" in msg) and "thinking" in msg

    def _thinking_variants(self, base: dict, max_tokens: int) -> list[dict]:
        """Highest-quality thinking form first, then graceful fallbacks.

        Order: adaptive (current models) -> enabled+budget_tokens (older
        models) -> no thinking (last resort). We keep thinking ON for quality
        and only drop a form when THIS model rejects it with a 400."""
        if not self._enable_thinking:
            return [base]
        adaptive = {**base, "thinking": {"type": "adaptive"},
                    "output_config": {"effort": "high"}}
        enabled = {**base, "thinking": {"type": "enabled",
                                        "budget_tokens": _thinking_budget(max_tokens)}}
        return [adaptive, enabled, base]

    # ── call construction ────────────────────────────────

    def _call_kwargs(
        self, system: str, user: str, model: str, max_tokens: int,
    ) -> dict:
        """Build the base kwargs (thinking added per-variant by the caller)."""
        return {
            "model": _resolve_model(model),
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": self._tools(),
        }

    # ── tools ────────────────────────────────────────────

    def _tools(self) -> list[dict]:
        tools: list[dict] = []
        if self._enable_web_search:
            tools.append({
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 15,
            })
        if self._enable_web_fetch:
            tools.append({
                "type": "web_fetch_20250910",
                "name": "web_fetch",
                "max_uses": 15,
            })
        return tools
