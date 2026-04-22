"""Agent with Claude CLI integration, streaming output, and voice narration.

v0.6 additions:
- ``respond_silent()`` for parallel execution (captures output, no streaming).
- Scratchpad parsing: ``[SCRATCHPAD key]...[/SCRATCHPAD]`` blocks are extracted
  and written to the shared bus scratchpad.
- Directed-message detection: ``[DIRECT @Name: ...]`` patterns are returned
  as metadata so the orchestrator can schedule reactive turns.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

from rich.console import Console

from .bus import MessageBus, Message, MessageType
from .narrator import Narrator


ROLE_STYLES: dict[str, dict[str, str]] = {
    "leader":      {"color": "bold cyan",    "icon": "\U0001f3af"},
    "worker":      {"color": "bold green",   "icon": "\u26a1"},
    "critic":      {"color": "bold yellow",  "icon": "\U0001f50d"},
    "synthesizer": {"color": "bold magenta", "icon": "\u2728"},
    "debater":     {"color": "bold blue",    "icon": "\u2694\ufe0f"},
    "judge":       {"color": "bold red",     "icon": "\u2696\ufe0f"},
}

_ROLE_ANSI: dict[str, str] = {
    "leader":      "\033[1;36m",
    "worker":      "\033[1;32m",
    "critic":      "\033[1;33m",
    "synthesizer": "\033[1;35m",
    "debater":     "\033[1;34m",
    "judge":       "\033[1;31m",
}
_ANSI_RESET = "\033[0m"

_CLAUDE_PATH: str | None = shutil.which("claude")

# ── regex for scratchpad and direct-message parsing ──────
_SCRATCHPAD_RE = re.compile(
    r"\[SCRATCHPAD\s+([\w./-]+)\](.*?)\[/SCRATCHPAD\]",
    re.DOTALL,
)
_DIRECT_RE = re.compile(
    r"\[DIRECT\s+@(\w+):\s*(.*?)\]",
    re.DOTALL,
)


@dataclass
class AgentConfig:
    name: str
    role: str
    personality: str
    model: str = "opus"
    temperature: float = 0.8
    icon: str = ""
    max_tokens: int = 0


@dataclass
class AgentResponse:
    """Structured result from an agent turn."""
    message: Message
    scratchpad_writes: list[tuple[str, str]]   # [(key, content), ...]
    direct_requests: list[tuple[str, str]]     # [(target_agent, question), ...]


class Agent:
    """A single AI agent backed by the Claude CLI with extended thinking and voice."""

    def __init__(
        self,
        config: AgentConfig,
        bus: MessageBus,
        narrator: Narrator | None = None,
        team_roster: list[str] | None = None,
    ) -> None:
        self.config = config
        self.bus = bus
        self.narrator = narrator
        self.console = Console(force_terminal=True)
        self.team_roster: list[str] = team_roster or []

        if not _CLAUDE_PATH:
            raise FileNotFoundError(
                "Could not find 'claude' CLI on PATH. "
                "Install Claude Code: https://docs.anthropic.com/en/docs/claude-code"
            )

    # ── properties ────────────────────────────────────────

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def role(self) -> str:
        return self.config.role

    @property
    def icon(self) -> str:
        if self.config.icon:
            return self.config.icon
        return ROLE_STYLES.get(self.role, {}).get("icon", "\U0001f916")

    @property
    def color(self) -> str:
        return ROLE_STYLES.get(self.role, {}).get("color", "bold white")

    # ── public API ────────────────────────────────────────

    def respond(
        self, prompt: str, round_num: int = 0, is_final_round: bool = False
    ) -> AgentResponse:
        """Generate a response with streaming output, narration, and bus posting."""
        system = self._build_system()
        user_prompt = self._build_user_prompt(prompt, round_num)
        self._print_header()

        try:
            text = self._call_cli(system, user_prompt)
        except FileNotFoundError:
            text = "[ERROR] 'claude' CLI not found. Make sure Claude Code is installed and on your PATH."
            self.console.print(f"  [bold red]{text}[/]")
        except Exception as exc:
            text = f"[ERROR] {exc}"
            self.console.print(f"  [bold red]{text}[/]")

        self._print_footer()

        if self.narrator and not text.startswith("[ERROR]"):
            self.narrator.narrate_agent(text, self.name, self.role, is_final_round)
            self.narrator.wait_until_done()

        return self._post_process(text, round_num)

    def respond_silent(
        self, prompt: str, round_num: int = 0
    ) -> AgentResponse:
        """Generate a response without streaming or narration (for parallel execution).

        Output is captured and returned — the engine can display it later.
        """
        system = self._build_system()
        user_prompt = self._build_user_prompt(prompt, round_num)

        try:
            text = self._call_cli_silent(system, user_prompt)
        except FileNotFoundError:
            text = "[ERROR] 'claude' CLI not found."
        except Exception as exc:
            text = f"[ERROR] {exc}"

        return self._post_process(text, round_num)

    def display_buffered(self, text: str) -> None:
        """Display previously-captured output with the agent's styled header/border."""
        self._print_header()
        ansi_color = _ROLE_ANSI.get(self.role, "\033[37m")
        for line in text.split("\n"):
            sys.stdout.write(f"  {ansi_color}\u2502{_ANSI_RESET} {line}\n")
        sys.stdout.flush()
        self._print_footer()

    # ── post-processing ──────────────────────────────────

    def _post_process(self, text: str, round_num: int) -> AgentResponse:
        """Parse scratchpad writes and direct messages, then post to bus."""
        scratchpad_writes: list[tuple[str, str]] = []
        direct_requests: list[tuple[str, str]] = []

        # Extract scratchpad blocks
        for match in _SCRATCHPAD_RE.finditer(text):
            key, content = match.group(1).strip(), match.group(2).strip()
            scratchpad_writes.append((key, content))
            self.bus.scratchpad.write(key, content, self.name, round_num)

        # Extract directed-message requests
        for match in _DIRECT_RE.finditer(text):
            target, question = match.group(1).strip(), match.group(2).strip()
            if target in self.team_roster:
                direct_requests.append((target, question))

        msg = Message(
            sender=self.name,
            content=text,
            msg_type=MessageType.FEEDBACK if self.role == "critic" else MessageType.RESULT,
            round_num=round_num,
        )
        self.bus.post(msg)

        return AgentResponse(
            message=msg,
            scratchpad_writes=scratchpad_writes,
            direct_requests=direct_requests,
        )

    # ── prompt construction ──────────────────────────────

    def _build_system(self) -> str:
        teammates = [n for n in self.team_roster if n != self.name]
        roster_str = ", ".join(teammates) if teammates else "(solo)"

        return f"""{self.config.personality}

IDENTITY: {self.name} ({self.role})
TEAM: {roster_str}

RESEARCH MANDATE
- You MUST search the web for any claim requiring current data or evidence.
- Cite sources inline as [Source Name](URL). Say "UNVERIFIED:" for unsourced claims.
- Prefer primary sources (govt data, peer-reviewed, SEC filings). Search multiple queries.

{self._output_format_for_role()}

COLLABORATION TOOLS
- Address teammates as @Name. ONLY reference agents listed in TEAM above.
- To write a shared artifact: [SCRATCHPAD artifact-name]content here[/SCRATCHPAD]
  (e.g., [SCRATCHPAD executive-summary]The key finding is...[/SCRATCHPAD])
- To request a reactive response from a teammate:
  [DIRECT @Name: your specific question or request]
- Shared artifacts are visible to ALL agents — use them to build on each other's work.

RULES
- Stay in character as {self.name}. Contribute real analytical/creative value.
- NEVER repeat information another agent already stated — reference it and build.
- Be specific: numbers, names, dates, examples. Vague generalities are unacceptable.
- Acknowledge uncertainty. Distinguish known facts from estimates.
- End with [DONE]. Say [NEED @Human: question] for human input.
- Leaders only: say [COMPLETE] when the project goal is fully achieved."""

    def _output_format_for_role(self) -> str:
        if self.role == "leader":
            return (
                "OUTPUT FORMAT (leader)\n"
                "- Opening: Use ## headers. Give numbered assignments with specific deliverables.\n"
                "- Synthesis: Lead with the key insight the team missed. Resolve contradictions.\n"
                "- Final deliverable: Executive Summary > Key Findings > Decision Framework > "
                "Action Items (with owners, timelines, success metrics)."
            )
        if self.role in ("worker", "debater"):
            return (
                "OUTPUT FORMAT (specialist)\n"
                "- Lead with your single most important finding — don't bury it.\n"
                "- Use ## headers to structure sections.\n"
                "- Evidence first, then interpretation. Every claim needs a source.\n"
                "- End with 2-3 specific, actionable recommendations.\n"
                "- Depth over breadth. 3 thorough points beat 10 shallow ones."
            )
        if self.role in ("critic", "judge"):
            return (
                "OUTPUT FORMAT (reviewer)\n"
                "- Structure: Verdict > Strengths (2-3 specific) > Issues with Fixes (2-3) > Evidence Check.\n"
                "- For each issue, give the SPECIFIC fix — not just the problem.\n"
                "- Spot-check at least one key claim with your own web search.\n"
                "- Rate: Exceptional / Strong / Adequate / Weak — with justification."
            )
        return "Deliver substantive, well-structured content with ## headers."

    def _build_user_prompt(self, round_prompt: str, round_num: int) -> str:
        context = self.bus.format_context(
            self.name,
            current_round=round_num,
        )
        return f"""CONVERSATION HISTORY
{context}

YOUR TASK THIS TURN
{round_prompt}"""

    # ── CLI calls ────────────────────────────────────────

    def _clean_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        return env

    def _cli_args(self, system: str) -> list[str]:
        return [
            _CLAUDE_PATH,
            "-p",
            "--system-prompt", system,
            "--model", self.config.model,
            "--effort", "max",
            "--no-session-persistence",
            "--allowedTools", "WebSearch", "WebFetch",
        ]

    def _call_cli(self, system: str, user_prompt: str) -> str:
        """Call Claude CLI with animated spinner, then stream response with colored border."""
        proc = subprocess.Popen(
            self._cli_args(system),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self._clean_env(),
        )

        proc.stdin.write(user_prompt)
        proc.stdin.close()

        spinner_style = self.color.replace("bold ", "")
        status = self.console.status(
            f"  {self.icon} [{self.color}]{self.name}[/] [dim]researching & thinking...[/]",
            spinner="dots",
            spinner_style=spinner_style,
        )
        status.start()

        ansi_color = _ROLE_ANSI.get(self.role, "\033[37m")
        lines: list[str] = []
        first_line = True

        for line in proc.stdout:
            if first_line:
                status.stop()
                first_line = False
            sys.stdout.write(f"  {ansi_color}\u2502{_ANSI_RESET} {line}")
            sys.stdout.flush()
            lines.append(line)

        if first_line:
            status.stop()

        proc.wait()
        text = "".join(lines).strip()

        if not text:
            return "[ERROR] No response from Claude CLI. The model may be overloaded — try again."
        return text

    def _call_cli_silent(self, system: str, user_prompt: str) -> str:
        """Call Claude CLI and capture output without streaming (for parallel execution)."""
        proc = subprocess.Popen(
            self._cli_args(system),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self._clean_env(),
        )

        proc.stdin.write(user_prompt)
        proc.stdin.close()

        stdout, _ = proc.communicate()
        text = stdout.strip() if stdout else ""

        if not text:
            return "[ERROR] No response from Claude CLI. The model may be overloaded — try again."
        return text

    # ── display ──────────────────────────────────────────

    def _print_header(self) -> None:
        self.console.print()
        self.console.print(
            f"  {self.icon} [{self.color}]{self.name}[/] "
            f"[dim]\u2500 {self.role} \u2500[/]"
        )

    def _print_footer(self) -> None:
        self.console.print()
