"""Claude provider — wraps the existing `claude` CLI flow.

Preserves backwards compatibility with the existing _call_cli implementation
in Agent. New providers (OpenAI, Gemini) call APIs directly; Claude routes
through the local CLI binary so existing user auth + tooling continues to
work without code changes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from .base import LLMProvider, ProviderCallStats
from .errors import ProviderError, ProviderTimeout


_CLAUDE_PATH: str | None = shutil.which("claude")


class ClaudeProvider(LLMProvider):
    """Routes calls through the local `claude` CLI binary."""

    _FALLBACK_PRICING_PER_1M: dict[str, tuple[float, float]] = {
        "opus": (15.0, 75.0),
        "sonnet": (3.0, 15.0),
        "haiku": (0.80, 4.0),
    }

    def __init__(self, claude_path: str | None = None) -> None:
        self._path = claude_path or _CLAUDE_PATH

    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        timeout_s: float = 600.0,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **_: Any,
    ) -> tuple[str, ProviderCallStats]:
        if not self._path:
            raise ProviderError(
                "claude CLI not found on PATH. Install Claude Code: "
                "https://docs.anthropic.com/en/docs/claude-code"
            )

        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)  # CLI uses its own auth

        args = [self._path, "--model", model, "--system-prompt", system]
        if max_tokens:
            args += ["--max-tokens", str(max_tokens)]

        try:
            result = subprocess.run(
                args,
                input=user,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderTimeout(f"claude CLI timeout ({timeout_s}s) for model={model}") from exc
        except Exception as exc:
            raise ProviderError(f"claude CLI invocation failed: {exc}") from exc

        if result.returncode != 0:
            raise ProviderError(
                f"claude CLI exit={result.returncode}: {result.stderr.strip()[:500]}"
            )

        text = result.stdout
        stats = ProviderCallStats(
            provider="claude",
            model=model,
            input_tokens=None,  # CLI doesn't expose tokens; live-only metric
            output_tokens=None,
            cost_usd=None,
        )
        return text, stats
