"""Gemini CLI provider — Google's official `gemini` CLI, OAuth-authed (no API key).

Install:
    npm install -g @google/gemini-cli

Auth: run `gemini` once and sign in with your Google account (Gemini
Advanced / Workspace / free tier).  No API key required.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from typing import Iterator

from .base import Provider, ProviderError


_GEMINI_PATH: str | None = shutil.which("gemini")

_MODEL_ALIASES: dict[str, str] = {
    "default":    "gemini-2.5-pro",
    "pro":        "gemini-2.5-pro",
    "flash":      "gemini-2.5-flash",
    "flash-lite": "gemini-2.5-flash-lite",
}


def _resolve_model(model: str) -> str:
    return _MODEL_ALIASES.get(model, model or "gemini-2.5-pro")


class GeminiCliProvider(Provider):
    """Google Gemini via the `gemini` CLI subprocess."""

    name = "gemini_cli"

    def __init__(self) -> None:
        if not _GEMINI_PATH:
            raise ProviderError(
                "gemini CLI not found on PATH. Install with: "
                "npm install -g @google/gemini-cli  (then run `gemini` once to auth)"
            )
        # Neutral cwd so the child CLI doesn't pick up GEMINI.md / project
        # context from the caller's directory.
        self._cwd = tempfile.mkdtemp(prefix="agent_forge_gemini_")

    def _args(self, system: str, model: str) -> list[str]:
        # The gemini CLI accepts `-p <prompt>` for non-interactive single-shot,
        # `-m <model>` for model selection, and reads extra input from stdin.
        # System prompts are prepended to the user prompt since the CLI doesn't
        # take a separate --system-prompt flag as of 2025.
        return [
            _GEMINI_PATH,
            "-m", _resolve_model(model),
            "--yolo",  # auto-accept tool calls
        ]

    def _merge_system(self, system: str, user: str) -> str:
        return f"<SYSTEM_INSTRUCTIONS>\n{system}\n</SYSTEM_INSTRUCTIONS>\n\n{user}"

    def stream(self, system: str, user: str, model: str, max_tokens: int) -> Iterator[str]:
        proc = subprocess.Popen(
            self._args(system, model),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self._cwd,
        )
        try:
            proc.stdin.write(self._merge_system(system, user))
            proc.stdin.close()
            for line in proc.stdout:
                yield line
        finally:
            proc.wait()

    def complete(self, system: str, user: str, model: str, max_tokens: int) -> str:
        proc = subprocess.Popen(
            self._args(system, model),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self._cwd,
        )
        stdout, _ = proc.communicate(input=self._merge_system(system, user))
        return stdout.strip() if stdout else ""
