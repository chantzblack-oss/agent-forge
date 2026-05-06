from __future__ import annotations

import os
from typing import Any

from .base import LLMProvider, ProviderCallStats
from .errors import ProviderError, ProviderRateLimited, ProviderTimeout


class OpenAIProvider(LLMProvider):
    """OpenAI provider via official openai Python SDK.
    Returns plain text + ProviderCallStats.
    """

    _FALLBACK_PRICING_PER_1M: dict[str, tuple[float, float]] = {
        "gpt-5": (5.0, 15.0),
        "gpt-4.1": (5.0, 15.0),
        "gpt-4o": (2.5, 10.0),
        "gpt-4o-mini": (0.15, 0.60),
    }

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._base_url = base_url or os.getenv("OPENAI_BASE_URL")
        if not self._api_key:
            raise ProviderError("OPENAI_API_KEY not set")

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
            from openai import OpenAI
            from openai import APITimeoutError, RateLimitError, APIError
        except Exception as exc:
            raise ProviderError(f"OpenAI SDK import failed: {exc}") from exc

        client = OpenAI(api_key=self._api_key, base_url=self._base_url)

        try:
            resp = client.responses.create(
                model=model,
                timeout=timeout_s,
                temperature=temperature,
                max_output_tokens=max_tokens,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": system}]},
                    {"role": "user", "content": [{"type": "input_text", "text": user}]},
                ],
            )
        except APITimeoutError as exc:
            raise ProviderTimeout(f"OpenAI timeout ({timeout_s}s) for model={model}") from exc
        except RateLimitError as exc:
            raise ProviderRateLimited(f"OpenAI rate limited for model={model}") from exc
        except APIError as exc:
            raise ProviderError(f"OpenAI API error for model={model}: {exc}") from exc
        except Exception as exc:
            raise ProviderError(f"OpenAI provider failure for model={model}: {exc}") from exc

        text = self._extract_text(resp)
        in_tokens, out_tokens = self._extract_usage(resp)
        cost_usd = self._estimate_cost_usd(model=model, input_tokens=in_tokens, output_tokens=out_tokens)

        stats = ProviderCallStats(
            provider="openai",
            model=model,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_usd=cost_usd,
        )
        return text, stats

    def _extract_text(self, resp: Any) -> str:
        text = getattr(resp, "output_text", None)
        if isinstance(text, str) and text.strip():
            return text

        out_parts: list[str] = []
        for item in getattr(resp, "output", []) or []:
            for c in getattr(item, "content", []) or []:
                t = getattr(c, "text", None)
                if isinstance(t, str):
                    out_parts.append(t)
        joined = "\n".join(p for p in out_parts if p).strip()
        return joined or ""

    def _extract_usage(self, resp: Any) -> tuple[int | None, int | None]:
        usage = getattr(resp, "usage", None)
        if not usage:
            return None, None
        in_tokens = getattr(usage, "input_tokens", None)
        out_tokens = getattr(usage, "output_tokens", None)
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
