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
import time
from typing import Iterator

from .base import Provider, ProviderError


def _is_transient(exc: Exception) -> bool:
    """True for server-side / rate-limit errors that often succeed on retry."""
    msg = str(exc).lower()
    return any(
        marker in msg
        for marker in (
            "503", "unavailable", "500", "502", "504",
            "overloaded", "temporarily", "deadline",
            "429", "rate_limit", "quota",
        )
    )


# Family aliases → resolved dynamically from OpenAI's model list
# (agent_forge/model_resolver.resolve_openai). Use these to always pick
# up new model versions as they ship; pass a concrete ID to pin.
_FAMILY_ALIASES = {"gpt", "gpt-5", "gpt-4", "gpt-4o", "o1", "o3", "o4"}

DEFAULT_MODEL = "gpt"

# o-series reasoning models have different parameter conventions
_REASONING_PREFIXES = ("o1", "o3", "o4")


def _resolve_model(model: str) -> str:
    """Resolve a family alias to the latest concrete OpenAI model ID."""
    if not model or model == "default":
        model = DEFAULT_MODEL
    # Shortcut aliases that users commonly type but aren't family names
    if model in ("gpt5", "gpt-5.4"):
        model = "gpt"
    if model == "4o":
        model = "gpt-4o"
    if model == "o3-mini":
        model = "o3"
    if model in _FAMILY_ALIASES:
        from ..model_resolver import resolve_openai
        return resolve_openai(model)
    return model


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

    _RETRY_DELAYS = [2, 5, 10]

    def stream(self, system: str, user: str, model: str, max_tokens: int) -> Iterator[str]:
        """Stream with retry-on-transient (3 attempts, 2s/5s/10s backoff).

        Retry is only attempted BEFORE any chunks have been yielded;
        mid-stream failures raise immediately.
        """
        kwargs = self._call_kwargs(system, user, model, max_tokens, streaming=True)
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                got_any = False
                stream = self._client.chat.completions.create(**kwargs)
                for chunk in stream:
                    try:
                        delta = chunk.choices[0].delta
                        content = getattr(delta, "content", None)
                        if content:
                            got_any = True
                            yield content
                    except (IndexError, AttributeError):
                        continue
                return
            except Exception as exc:
                last_exc = exc
                if got_any or not _is_transient(exc):
                    raise ProviderError(
                        f"OpenAI ({_resolve_model(model)}) call failed: {str(exc)[:300]}"
                    ) from exc
                if attempt < 2:
                    time.sleep(self._RETRY_DELAYS[attempt])
        if last_exc is not None:
            raise ProviderError(
                f"OpenAI ({_resolve_model(model)}) call failed after 3 retries: {str(last_exc)[:300]}"
            ) from last_exc

    def complete(self, system: str, user: str, model: str, max_tokens: int) -> str:
        """Complete with retry-on-transient (3 attempts, 2s/5s/10s backoff)."""
        kwargs = self._call_kwargs(system, user, model, max_tokens, streaming=False)
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = self._client.chat.completions.create(**kwargs)
                try:
                    return resp.choices[0].message.content or ""
                except (IndexError, AttributeError):
                    return ""
            except Exception as exc:
                last_exc = exc
                if not _is_transient(exc):
                    raise ProviderError(
                        f"OpenAI ({_resolve_model(model)}) call failed: {str(exc)[:300]}"
                    ) from exc
                if attempt < 2:
                    time.sleep(self._RETRY_DELAYS[attempt])
        if last_exc is not None:
            raise ProviderError(
                f"OpenAI ({_resolve_model(model)}) call failed after 3 retries: {str(last_exc)[:300]}"
            ) from last_exc
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
            # OpenAI's newer models (gpt-5.x, o-series) all use
            # max_completion_tokens. Using it universally works for
            # current models and is forward-compatible.
            "max_completion_tokens": max_tokens,
        }
        return kwargs
