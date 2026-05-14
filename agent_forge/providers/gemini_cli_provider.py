"""Gemini CLI provider — Google's official `gemini` CLI.

Install:
    npm install -g @google/gemini-cli

Auth options (one of):
    1. Interactive OAuth — run `gemini` once, sign in with your Google
       account.  Uses your Gemini Advanced / Workspace / free-tier quota.
       No API key required.
    2. API key — export GEMINI_API_KEY=... (only if you want SDK-path billing).
    3. Vertex AI — export GOOGLE_GENAI_USE_VERTEXAI=true (uses gcloud ADC).

The CLI auth-checks before reading stdin, so this provider captures any
auth failure early and surfaces it as a ProviderError with actionable
instructions.
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

_AUTH_HINT = (
    "gemini CLI is installed but not authenticated. Fix with ONE of:\n"
    "  • Interactive OAuth (recommended, no API key): run `gemini` once "
    "in a terminal and sign in with Google.\n"
    "  • API key: export GEMINI_API_KEY=...\n"
    "  • Vertex AI: export GOOGLE_GENAI_USE_VERTEXAI=true (requires gcloud auth)."
)


def _resolve_model(model: str) -> str:
    return _MODEL_ALIASES.get(model, model or "gemini-2.5-pro")


def _is_auth_error(stderr: str) -> bool:
    low = (stderr or "").lower()
    return (
        "please set an auth method" in low
        or "api key not valid" in low
        or "api key invalid" in low
        or "unauthenticated" in low
        or "please log in" in low
    )


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

    def _args(self, model: str) -> list[str]:
        # -p/--prompt triggers non-interactive (headless) mode.  Passing an
        # empty string here makes the CLI read the full prompt from stdin
        # (the CLI help says: "Appended to input on stdin (if any)").
        # --output-format text keeps output plain (no JSON envelope).
        # --yolo auto-accepts tool calls without prompting the user.
        return [
            _GEMINI_PATH,
            "-m", _resolve_model(model),
            "-p", "",
            "--output-format", "text",
            "--yolo",
        ]

    def _merge_system(self, system: str, user: str) -> str:
        return f"<SYSTEM_INSTRUCTIONS>\n{system}\n</SYSTEM_INSTRUCTIONS>\n\n{user}"

    def stream(self, system: str, user: str, model: str, max_tokens: int) -> Iterator[str]:
        proc = subprocess.Popen(
            self._args(model),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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
            # Surface auth errors that arrived via stderr after the fact
            if proc.returncode != 0:
                err = proc.stderr.read() if proc.stderr else ""
                if _is_auth_error(err):
                    raise ProviderError(_AUTH_HINT)
                if err.strip():
                    raise ProviderError(f"gemini CLI failed (exit {proc.returncode}): {err.strip()[:400]}")

    def complete(self, system: str, user: str, model: str, max_tokens: int) -> str:
        proc = subprocess.Popen(
            self._args(model),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self._cwd,
        )
        stdout, stderr = proc.communicate(input=self._merge_system(system, user))
        if proc.returncode != 0:
            if _is_auth_error(stderr):
                raise ProviderError(_AUTH_HINT)
            raise ProviderError(
                f"gemini CLI failed (exit {proc.returncode}): {(stderr or '').strip()[:400]}"
            )
        return stdout.strip() if stdout else ""
