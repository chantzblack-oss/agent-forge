"""Backwards-compat provider: the original Claude CLI subprocess path.

Kept so users who don't want to install the anthropic SDK (or who prefer
Claude Code's auth) can still run Agent Forge.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Iterator

from .base import Provider, ProviderError


_CLAUDE_PATH: str | None = shutil.which("claude")


class ClaudeCliProvider(Provider):
    name = "claude_cli"

    def __init__(self) -> None:
        if not _CLAUDE_PATH:
            raise ProviderError(
                "claude CLI not found on PATH. Install Claude Code or use a different provider."
            )
        # Run the subprocess from a neutral temp directory so the child CLI
        # doesn't inherit project-specific CLAUDE.md / settings from the
        # caller's cwd (which would leak into every agent's system prompt).
        self._cwd = tempfile.mkdtemp(prefix="agent_forge_claude_")

    def _clean_env(self) -> dict[str, str]:
        env = os.environ.copy()
        # The CLI uses its own auth — remove the SDK key so it doesn't conflict.
        env.pop("ANTHROPIC_API_KEY", None)
        return env

    def _args(self, system: str, model: str) -> list[str]:
        return [
            _CLAUDE_PATH,
            "-p",
            "--system-prompt", system,
            "--model", model or "opus",
            "--effort", "max",
            "--no-session-persistence",
            "--allowedTools", "WebSearch", "WebFetch",
        ]

    def stream(self, system: str, user: str, model: str, max_tokens: int) -> Iterator[str]:
        proc = subprocess.Popen(
            self._args(system, model),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self._clean_env(),
            cwd=self._cwd,
        )
        try:
            proc.stdin.write(user)
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
            env=self._clean_env(),
            cwd=self._cwd,
        )
        stdout, _ = proc.communicate(input=user)
        return stdout.strip() if stdout else ""
