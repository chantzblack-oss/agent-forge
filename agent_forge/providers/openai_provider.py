"""OpenAI provider — GPT-5 and the o-series reasoning models via the official SDK.

Capabilities on this path:

- **Streaming** via ``chat.completions.create(stream=True)`` with delta events.
- **Model aliases**: ``gpt``/``gpt5``/``gpt-5`` → ``gpt-5``, ``4o`` → ``gpt-4o``,
  ``o1``/``o3``/``o4-mini`` → their canonical names.
- **Reasoning-model handling**: o-series models use ``max_completion_tokens``
  instead of ``max_tokens`` and don't accept a temperature — the provider
  detects this and sends the right parameters.

Web search (via the Responses API ``web_search`` tool) is not enabled on
this path because the search-query citation format the agents now use
(``[Title — Author Year, Journal]`` auto-linked to Google Scholar) is
hallucination-proof and works without provider-side search. The Citationist
will still fetch and verify any explicit ``[Label](url)`` citations.
"""

from __future__ import annotations

import os
from typing import Iterator

from .base import Provider, ProviderError


DEFAULT_MODEL = "gpt-5.4"

# Shorthand → canonical model id
_MODEL_ALIASES: dict[str, str] = {
    "default":  DEFAULT_MODEL,
    "gpt":      "gpt-5.4",
    "gpt5":     "gpt-5.4",
    "gpt-5":    "gpt-5",
    "gpt-5.4":  "gpt-5.4",
    "4o":       "gpt-4o",
    "gpt-4o":   "gpt-4o",
    "4o-mini":  "gpt-4o-mini",
    "o1":       "o1",
    "o1-mini":  "o1-mini",
    "o3":       "o3-mini",
    "o3-mini":  "o3-mini",
    "o4-mini":  "o4-mini",
}

# o-series reasoning models have different parameter conventions
_REASONING_PREFIXES = ("o1", "o3", "o4")


def _resolve_model(model: str) -> str:
    return _MODEL_ALIASES.get(model, model or DEFAULT_MODEL)


def _is_reasoning_model(model: str) -> bool:
    return any(model.startswith(p) for p in _REASONING_PREFIXES)


class OpenAIProvider(Provider):
    """OpenAI GPT via the official SDK with streaming."""

    name = "openai"

    def __init__(self, api_key: str | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderError(
                "openai package not installed. Run: pip install openai"
            ) from exc

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ProviderError(
                "OPENAI_API_KEY not set. Export it or add it to .env."
            )
        self._client = OpenAI(api_key=key)

    # ── public ────────────────────────────────────────────

    def stream(self, system: str, user: str, model: str, max_tokens: int) -> Iterator[str]:
        kwargs = self._call_kwargs(system, user, model, max_tokens, streaming=True)
        try:
            stream = self._client.chat.completions.create(**kwargs)
            for chunk in stream:
                try:
                    delta = chunk.choices[0].delta
                    content = getattr(delta, "content", None)
                    if content:
                        yield content
                except (IndexError, AttributeError):
                    continue
        except Exception as exc:
            raise ProviderError(
                f"OpenAI ({_resolve_model(model)}) call failed: {str(exc)[:300]}"
            ) from exc

    def complete(self, system: str, user: str, model: str, max_tokens: int) -> str:
        kwargs = self._call_kwargs(system, user, model, max_tokens, streaming=False)
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise ProviderError(
                f"OpenAI ({_resolve_model(model)}) call failed: {str(exc)[:300]}"
            ) from exc
        try:
            return resp.choices[0].message.content or ""
        except (IndexError, AttributeError):
            return ""

    # ── call construction ────────────────────────────────

    def _call_kwargs(
        self,
        system: str,
        user: str,
        model: str,
        max_tokens: int,
        streaming: bool,
    ) -> dict:
        resolved = _resolve_model(model)
        kwargs: dict = {
            "model": resolved,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": streaming,
        }
        # Parameter convention differs between standard and reasoning models
        if _is_reasoning_model(resolved):
            kwargs["max_completion_tokens"] = max_tokens
            # o-series models don't accept custom temperature
        else:
            kwargs["max_tokens"] = max_tokens
        return kwargs
