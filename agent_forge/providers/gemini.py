from __future__ import annotations

import os
from typing import Any

from .base import LLMProvider, ProviderCallStats
from .errors import ProviderError, ProviderRateLimited, ProviderTimeout


class GeminiProvider(LLMProvider):
    """Gemini provider via official google-genai SDK.
    Returns plain text + ProviderCallStats.
    """

    _FALLBACK_PRICING_PER_1M: dict[str, tuple[float, float]] = {
        "gemini-2.5-pro": (3.5, 10.5),
        "gemini-2.5-flash": (0.35, 1.05),
        "gemini-1.5-pro": (3.5, 10.5),
        "gemini-1.5-flash": (0.35, 1.05),
    }

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self._api_key:
            raise ProviderError("GEMINI_API_KEY / GOOGLE_API_KEY not set")

    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        timeout_s: float = 120.0,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **_: Any,
    ) -> tuple[str, ProviderCallStats]:
        try:
            from google import genai
            from google.genai import types as genai_types
        except Exception as exc:
            raise ProviderError(f"Google GenAI SDK import failed: {exc}") from exc

        try:
            client = genai.Client(api_key=self._api_key)

            config = genai_types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                max_output_tokens=max_tokens,
            )

            resp = client.models.generate_content(
                model=model,
                contents=user,
                config=config,
            )
        except TimeoutError as exc:
            raise ProviderTimeout(f"Gemini timeout ({timeout_s}s) for model={model}") from exc
        except Exception as exc:
            msg = str(exc).lower()
            if "rate" in msg and "limit" in msg:
                raise ProviderRateLimited(f"Gemini rate limited for model={model}") from exc
            raise ProviderError(f"Gemini provider failure for model={model}: {exc}") from exc

        text = self._extract_text(resp)
        in_tokens, out_tokens = self._extract_usage(resp)
        cost_usd = self._estimate_cost_usd(model=model, input_tokens=in_tokens, output_tokens=out_tokens)

        stats = ProviderCallStats(
            provider="gemini",
            model=model,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_usd=cost_usd,
        )
        return text, stats

    def _extract_text(self, resp: Any) -> str:
        text = getattr(resp, "text", None)
        if isinstance(text, str) and text.strip():
            return text

        out_parts: list[str] = []
        candidates = getattr(resp, "candidates", None) or []
        for cand in candidates:
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) if content is not None else None
            for part in parts or []:
                t = getattr(part, "text", None)
                if isinstance(t, str):
                    out_parts.append(t)
        return "\n".join(p for p in out_parts if p).strip()

    def _extract_usage(self, resp: Any) -> tuple[int | None, int | None]:
        usage = getattr(resp, "usage_metadata", None)
        if usage is None:
            return None, None
        in_tokens = getattr(usage, "prompt_token_count", None)
        out_tokens = getattr(usage, "candidates_token_count", None)
        return in_tokens, out_tokens

    def _estimate_cost_usd(
        self,
        *,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> float | None:
        if input_tokens is None or output_tokens is None:
            return None
        model_l = model.lower()
        in_rate = out_rate = None
        for prefix, (i, o) in self._FALLBACK_PRICING_PER_1M.items():
            if model_l.startswith(prefix):
                in_rate, out_rate = i, o
                break
        if in_rate is None or out_rate is None:
            return None
        return (input_tokens / 1_000_000.0) * in_rate + (output_tokens / 1_000_000.0) * out_rate
