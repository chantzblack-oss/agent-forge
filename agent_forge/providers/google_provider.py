"""Google Gemini provider — direct google-genai SDK calls with search grounding."""

from __future__ import annotations

import os
import time
from typing import Iterator

from .base import Provider, ProviderError


def _is_transient(exc: Exception) -> bool:
    """True for server-side capacity / overload errors that often succeed on retry."""
    msg = str(exc).lower()
    return any(
        marker in msg
        for marker in (
            "503", "unavailable", "500", "502", "504",
            "overloaded", "temporarily", "deadline",
        )
    )


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "resource_exhausted" in msg or "quota" in msg


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
        """Stream with retry-on-transient and fallback to flash if pro is overloaded.

        Strategy: up to 3 attempts with exponential backoff (3s, 8s, 15s).  If
        all retries of the requested model fail with transient errors AND the
        model was pro, one final attempt on flash.  Retry is only attempted
        BEFORE any chunks have been yielded; mid-stream failures raise.
        """
        config = self._config(system, max_tokens)
        resolved = _resolve_model(model)

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                got_any = False
                for chunk in self._client.models.generate_content_stream(
                    model=resolved, contents=user, config=config,
                ):
                    got_any = True
                    text = getattr(chunk, "text", None)
                    if text:
                        yield text
                return
            except Exception as exc:
                last_exc = exc
                if got_any:
                    _reraise_with_hint(exc, resolved)
                if not _is_transient(exc):
                    _reraise_with_hint(exc, resolved)
                if attempt < 2:
                    time.sleep([3, 8, 15][attempt])

        # All retries on the requested model exhausted — try flash as a fallback
        if resolved != "gemini-2.5-flash" and last_exc is not None:
            try:
                for chunk in self._client.models.generate_content_stream(
                    model="gemini-2.5-flash", contents=user, config=config,
                ):
                    text = getattr(chunk, "text", None)
                    if text:
                        yield text
                return
            except Exception as fallback_exc:
                _reraise_with_hint(fallback_exc, "gemini-2.5-flash (fallback)")
        if last_exc is not None:
            _reraise_with_hint(last_exc, resolved)

    def complete(self, system: str, user: str, model: str, max_tokens: int) -> str:
        """complete() with same retry + flash-fallback strategy as stream()."""
        config = self._config(system, max_tokens)
        resolved = _resolve_model(model)

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = self._client.models.generate_content(
                    model=resolved, contents=user, config=config,
                )
                return getattr(response, "text", "") or ""
            except Exception as exc:
                last_exc = exc
                if not _is_transient(exc):
                    _reraise_with_hint(exc, resolved)
                if attempt < 2:
                    time.sleep([3, 8, 15][attempt])

        if resolved != "gemini-2.5-flash" and last_exc is not None:
            try:
                response = self._client.models.generate_content(
                    model="gemini-2.5-flash", contents=user, config=config,
                )
                return getattr(response, "text", "") or ""
            except Exception as fallback_exc:
                _reraise_with_hint(fallback_exc, "gemini-2.5-flash (fallback)")
        if last_exc is not None:
            _reraise_with_hint(last_exc, resolved)
        return ""

    # ── config ───────────────────────────────────────────

    def _config(self, system: str, max_tokens: int):
        types = self._types
        tools: list = []

        # Google Search grounding — model decides when to search.
        if self._enable_search:
            tools.append(types.Tool(google_search=types.GoogleSearch()))

        # URL context — lets Gemini directly fetch and read a specified URL,
        # parallel to Anthropic's web_fetch. Only available on newer google-genai
        # SDK versions; gracefully skip if not exposed.
        try:
            UrlContext = getattr(types, "UrlContext", None)
            if UrlContext is not None:
                tools.append(types.Tool(url_context=UrlContext()))
        except Exception:
            pass

        # Extended thinking. Gemini 2.5 Pro enables this by default; thinking
        # tokens count against max_output_tokens. A modest budget (~25%) gives
        # the model room to reason without starving output. Higher than our
        # previous 10% cap — with the token budget also raised (2000+), 25%
        # is sustainable without the clipping we saw before.
        thinking_cfg = None
        try:
            ThinkingConfig = getattr(types, "ThinkingConfig", None)
            if ThinkingConfig is not None:
                thinking_cfg = ThinkingConfig(
                    thinking_budget=max(256, max_tokens // 4),
                    include_thoughts=False,
                )
        except Exception:
            thinking_cfg = None

        kwargs: dict = {
            "system_instruction": system,
            "max_output_tokens": max_tokens,
            "tools": tools or None,
        }
        if thinking_cfg is not None:
            kwargs["thinking_config"] = thinking_cfg
        return types.GenerateContentConfig(**kwargs)
