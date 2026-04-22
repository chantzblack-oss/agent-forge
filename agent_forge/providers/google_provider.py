"""Google Gemini provider — direct google-genai SDK calls with search grounding."""

from __future__ import annotations

import os
from typing import Iterator

from .base import Provider, ProviderError


# Default to Flash — Google's free-tier quota for 2.5-pro is often 0 for new
# Studio keys (pro is paid-tier only). Flash has real free-tier access and is
# still highly capable.  Users with paid-tier keys can specify model="pro".
DEFAULT_MODEL = "gemini-2.5-flash"

_MODEL_ALIASES: dict[str, str] = {
    "default":     DEFAULT_MODEL,
    "pro":         "gemini-2.5-pro",
    "flash":       "gemini-2.5-flash",
    "flash-lite":  "gemini-2.5-flash-lite",
}


def _resolve_model(model: str) -> str:
    return _MODEL_ALIASES.get(model, model)


def _reraise_with_hint(exc: Exception, model: str) -> None:
    """Turn noisy google-genai errors into short, actionable ProviderError hints."""
    msg = str(exc)
    low = msg.lower()

    # Quota exhausted (very common: free-tier pro has limit=0)
    if "429" in msg or "resource_exhausted" in low or "quota" in low:
        if model.startswith("gemini-2.5-pro") or model == "gemini-pro":
            raise ProviderError(
                "Gemini quota exceeded for "
                + model
                + ". Free-tier Studio keys often have limit=0 for 2.5-pro "
                "(it's paid-tier only). Use model='flash' instead — it has a "
                "real free-tier quota. To switch: edit your team config or let "
                "Agent Forge's default kick in."
            ) from exc
        raise ProviderError(
            f"Gemini quota exceeded for {model}. "
            "Retry in a few minutes, switch to model='flash-lite', or upgrade "
            "to paid tier at https://aistudio.google.com/apikey."
        ) from exc

    # Bad key
    if "api key not valid" in low or "api_key_invalid" in low or "unauthenticated" in low:
        raise ProviderError(
            "Gemini API key is not valid. Regenerate at "
            "https://aistudio.google.com/apikey and re-export GEMINI_API_KEY."
        ) from exc

    # Everything else — short, not the 400-line traceback
    raise ProviderError(f"Gemini ({model}) call failed: {msg[:300]}") from exc


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
        try:
            for chunk in self._client.models.generate_content_stream(
                model=_resolve_model(model),
                contents=user,
                config=config,
            ):
                text = getattr(chunk, "text", None)
                if text:
                    yield text
        except Exception as exc:
            _reraise_with_hint(exc, _resolve_model(model))

    def complete(self, system: str, user: str, model: str, max_tokens: int) -> str:
        config = self._config(system, max_tokens)
        try:
            response = self._client.models.generate_content(
                model=_resolve_model(model),
                contents=user,
                config=config,
            )
        except Exception as exc:
            _reraise_with_hint(exc, _resolve_model(model))
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
