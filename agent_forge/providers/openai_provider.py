"""OpenAI provider — GPT-5 via the Responses API with web search.

Capabilities on this path:

- **Streaming** via ``responses.create(stream=True)`` with delta events.
- **Web search** (``web_search_preview``) — GPT can search the web in real time,
  matching Claude's web_search and Gemini's Google Search grounding.
- **Model aliases**: ``gpt``/``gpt5``/``gpt-5`` -> ``gpt-5``, ``4o`` -> ``gpt-4o``,
  ``o1``/``o3``/``o4-mini`` -> their canonical names.
- **Fallback**: If the ``openai`` SDK is too old for the Responses API, falls
  back to ``chat.completions`` (without web search).
"""

from __future__ import annotations

import os
from typing import Iterator

from .base import Provider, ProviderError


_FAMILY_ALIASES = {"gpt", "gpt-5", "gpt-4", "gpt-4o", "o1", "o3", "o4"}

DEFAULT_MODEL = "gpt"

_REASONING_PREFIXES = ("o1", "o3", "o4")


def _resolve_model(model: str) -> str:
    if not model or model == "default":
        model = DEFAULT_MODEL
    if model in ("gpt5", "gpt-5.4", "gpt-5.5"):
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
    """OpenAI GPT via the Responses API with web search + chat.completions fallback."""

    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        enable_web_search: bool = True,
    ) -> None:
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
        self._enable_web_search = enable_web_search
        self._use_responses = hasattr(self._client, "responses")

    # -- public ----------------------------------------------------

    def stream(self, system: str, user: str, model: str, max_tokens: int) -> Iterator[str]:
        resolved = _resolve_model(model)
        if self._use_responses:
            yield from self._stream_responses(resolved, system, user, max_tokens)
        else:
            yield from self._stream_chat(resolved, system, user, max_tokens)

    def complete(self, system: str, user: str, model: str, max_tokens: int) -> str:
        resolved = _resolve_model(model)
        if self._use_responses:
            return self._complete_responses(resolved, system, user, max_tokens)
        return self._complete_chat(resolved, system, user, max_tokens)

    # -- Responses API (preferred — has web search) ----------------

    def _responses_kwargs(self, model: str, system: str, user: str, max_tokens: int) -> dict:
        kwargs: dict = {
            "model": model,
            "instructions": system,
            "input": user,
            "max_output_tokens": max_tokens,
        }
        if self._enable_web_search:
            kwargs["tools"] = [{"type": "web_search_preview"}]
        return kwargs

    def _stream_responses(self, model: str, system: str, user: str, max_tokens: int) -> Iterator[str]:
        kwargs = self._responses_kwargs(model, system, user, max_tokens)
        kwargs["stream"] = True
        try:
            stream = self._client.responses.create(**kwargs)
            for event in stream:
                if getattr(event, "type", "") == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield delta
        except Exception as exc:
            raise ProviderError(
                f"OpenAI ({model}) call failed: {str(exc)[:300]}"
            ) from exc

    def _complete_responses(self, model: str, system: str, user: str, max_tokens: int) -> str:
        kwargs = self._responses_kwargs(model, system, user, max_tokens)
        try:
            resp = self._client.responses.create(**kwargs)
            return getattr(resp, "output_text", "") or ""
        except Exception as exc:
            raise ProviderError(
                f"OpenAI ({model}) call failed: {str(exc)[:300]}"
            ) from exc

    # -- chat.completions fallback (old SDK, no web search) --------

    def _stream_chat(self, model: str, system: str, user: str, max_tokens: int) -> Iterator[str]:
        kwargs: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": True,
            "max_completion_tokens": max_tokens,
        }
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
                f"OpenAI ({model}) call failed: {str(exc)[:300]}"
            ) from exc

    def _complete_chat(self, model: str, system: str, user: str, max_tokens: int) -> str:
        kwargs: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": max_tokens,
        }
        try:
            resp = self._client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except (IndexError, AttributeError):
            return ""
        except Exception as exc:
            raise ProviderError(
                f"OpenAI ({model}) call failed: {str(exc)[:300]}"
            ) from exc
