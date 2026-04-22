"""Google Gemini provider — direct google-genai SDK calls with search grounding."""

from __future__ import annotations

import os
from typing import Iterator

from .base import Provider, ProviderError


DEFAULT_MODEL = "gemini-2.5-pro"

_MODEL_ALIASES: dict[str, str] = {
    "default":     DEFAULT_MODEL,
    "pro":         "gemini-2.5-pro",
    "flash":       "gemini-2.5-flash",
    "flash-lite":  "gemini-2.5-flash-lite",
}


def _resolve_model(model: str) -> str:
    return _MODEL_ALIASES.get(model, model)


class GoogleProvider(Provider):
    """Google Gemini via google-genai SDK, with Google Search grounding on."""

    name = "google"

    def __init__(self, api_key: str | None = None, enable_search: bool = True) -> None:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ProviderError(
                "google-genai package not installed. Run: pip install google-genai"
            ) from exc

        key = api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ProviderError(
                "GOOGLE_API_KEY (or GEMINI_API_KEY) not set. Export it or add it to .env."
            )
        self._genai = genai
        self._types = types
        self._client = genai.Client(api_key=key)
        self._enable_search = enable_search

    # ── public ────────────────────────────────────────────

    def stream(self, system: str, user: str, model: str, max_tokens: int) -> Iterator[str]:
        config = self._config(system, max_tokens)
        for chunk in self._client.models.generate_content_stream(
            model=_resolve_model(model),
            contents=user,
            config=config,
        ):
            text = getattr(chunk, "text", None)
            if text:
                yield text

    def complete(self, system: str, user: str, model: str, max_tokens: int) -> str:
        config = self._config(system, max_tokens)
        response = self._client.models.generate_content(
            model=_resolve_model(model),
            contents=user,
            config=config,
        )
        return getattr(response, "text", "") or ""

    # ── config ───────────────────────────────────────────

    def _config(self, system: str, max_tokens: int):
        types = self._types
        tools: list = []
        if self._enable_search:
            tools.append(types.Tool(google_search=types.GoogleSearch()))
        return types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            tools=tools or None,
        )
