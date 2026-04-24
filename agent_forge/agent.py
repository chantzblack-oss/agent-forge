"""Agent backed by a pluggable LLM provider (Anthropic SDK, Google SDK, or Claude CLI).

v0.6 additions:
- Multi-provider dispatch via ``agent_forge.providers`` — any agent can run
  against Anthropic, Google, or the Claude CLI based on ``AgentConfig.provider``.
- ``respond_silent()`` for parallel execution (captures output, no streaming).
- Scratchpad parsing: ``[SCRATCHPAD key]...[/SCRATCHPAD]`` blocks are extracted
  and written to the shared bus scratchpad.
- Directed-message detection: ``[DIRECT @Name: ...]`` patterns are returned
  as metadata so the orchestrator can schedule reactive turns.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .bus import MessageBus, Message, MessageType
from .narrator import Narrator
from .providers import get_provider, detect_provider, ProviderError


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

# ── regex for scratchpad and direct-message parsing ──────
_SCRATCHPAD_RE = re.compile(
    r"\[SCRATCHPAD\s+([\w./-]+)\](.*?)\[/SCRATCHPAD\]",
    re.DOTALL,
)
_DIRECT_RE = re.compile(
    r"\[DIRECT\s+@(\w+):\s*(.*?)\]",
    re.DOTALL,
)

# Protocol tokens that steer the engine but shouldn't be shown to the human.
_DISPLAY_STRIP_PATTERNS = [
    re.compile(r"\[DONE\]"),
    re.compile(r"\[COMPLETE\]"),
    re.compile(r"\[APPROVED\]"),
    # Tolerate colon / em-dash / whitespace separators after "@Human"
    re.compile(r"\[NEED\s+@Human[^\]]*\]", re.DOTALL),
    re.compile(r"\[DIRECT @\w+:\s*[^\]]*\]", re.DOTALL),
    re.compile(r"\[SCRATCHPAD [\w./-]+\].*?\[/SCRATCHPAD\]", re.DOTALL),
    re.compile(r"UNVERIFIED:\s*", re.IGNORECASE),
]

# Matches a search-query style citation: [Title ... — Author Year, Journal]
# The em-dash is the key separator. Excludes real [Label](url) markdown links.
_SEARCH_CITATION_RE = re.compile(
    r"\[([^\[\]\n]+?\s[—–-]\s[^\[\]\n]+?)\](?!\()"
)


def _search_citation_to_scholar(text: str) -> str:
    """Convert ``[Title — Author Year, Journal]`` into a Scholar search markdown link.

    Agents are instructed to prefer this format over raw URLs so they can't
    hallucinate broken links. The resulting markdown link ALWAYS works — worst
    case Scholar just returns related papers if the exact title doesn't match.
    """
    import urllib.parse as _urlparse

    def _replace(match: re.Match) -> str:
        query = match.group(1).strip()
        # Skip short / non-citation-looking labels (must have a year digit)
        if not re.search(r"\b(19|20)\d{2}\b", query):
            return match.group(0)
        encoded = _urlparse.quote_plus(query[:180])
        url = f"https://scholar.google.com/scholar?q={encoded}"
        return f"[{query}]({url})"

    return _SEARCH_CITATION_RE.sub(_replace, text)


def _clean_for_display(text: str) -> str:
    """Strip engine-protocol tokens, auto-link search-query citations, collapse blank lines."""
    cleaned = text
    # Auto-link search-query citations BEFORE stripping protocol tokens so the
    # em-dash pattern doesn't accidentally match a stripped [DIRECT @X — ...].
    cleaned = _search_citation_to_scholar(cleaned)
    for pat in _DISPLAY_STRIP_PATTERNS:
        cleaned = pat.sub("", cleaned)
    # Collapse 3+ blank lines to 2
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


@dataclass
class AgentConfig:
    name: str
    role: str
    personality: str
    # Which backend to use: "anthropic" | "google" | "claude_cli" | "auto".
    # "auto" detects from the model name (claude-* → anthropic, gemini-* → google).
    provider: str = "auto"
    # Provider-specific model id (e.g. "claude-opus-4-6", "gemini-2.5-pro").
    # Shorthand allowed: "opus", "sonnet", "haiku", "pro", "flash".
    model: str = "default"
    temperature: float = 0.8
    icon: str = ""
    max_tokens: int = 16000


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
        prior_contributions: str = "",
    ) -> None:
        self.config = config
        self.bus = bus
        self.narrator = narrator
        self.console = Console(force_terminal=True)
        self.team_roster: list[str] = team_roster or []
        # Pre-rendered summary of this agent's prior contributions across
        # past sessions (injected by the Orchestrator when the team assembles).
        # Makes each agent remember THEIR OWN stance, not just the shared bus.
        self.prior_contributions = prior_contributions

        # Resolve provider: explicit name, or auto-detect from model
        provider_name = config.provider
        if not provider_name or provider_name == "auto":
            provider_name = detect_provider(config.model)
        self._provider_name = provider_name
        # Lazy-load so a missing SDK for an unused provider doesn't block others
        self._provider = None

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
        """Generate a response, then render it as a clean markdown panel."""
        system = self._build_system()
        user_prompt = self._build_user_prompt(prompt, round_num)

        text: str
        try:
            text = self._call_cli(system, user_prompt)
        except FileNotFoundError:
            text = "[ERROR] 'claude' CLI not found. Make sure Claude Code is installed and on your PATH."
        except Exception as exc:
            text = f"[ERROR] {exc}"

        if text.startswith("[ERROR]"):
            self.console.print()
            self.console.print(
                f"  {self.icon} [{self.color}]{self.name}[/] "
                f"[dim]({self._provider_name}:{self.config.model})[/]"
            )
            self.console.print(f"  [bold red]{text}[/]")
        else:
            self.display_clean(text)

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
        """Display previously-captured output as a clean markdown panel."""
        if text.startswith("[ERROR]"):
            self.console.print()
            self.console.print(
                f"  {self.icon} [{self.color}]{self.name}[/] "
                f"[dim]({self._provider_name}:{self.config.model})[/]"
            )
            self.console.print(f"  [bold red]{text}[/]")
            return
        self.display_clean(text)

    def display_clean(self, text: str) -> None:
        """Render agent output as a Rich Markdown panel with protocol tokens stripped."""
        cleaned = _clean_for_display(text)
        if not cleaned:
            return
        border = self.color.replace("bold ", "")
        title = (
            f"{self.icon} [{self.color}]{self.name}[/] "
            f"[dim]\u00b7 {self.role} \u00b7 {self._provider_name}:{self.config.model}[/]"
        )
        self.console.print()
        self.console.print(
            Panel(
                Markdown(cleaned),
                title=title,
                title_align="left",
                border_style=border,
                padding=(0, 2),
            )
        )

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

        # Prepend per-agent prior contributions if present — each agent
        # remembers THEIR own past stance (not just the shared bus memory).
        prior_block = (
            f"\n{self.prior_contributions}\n"
            if self.prior_contributions else ""
        )

        return f"""{self.config.personality}
{prior_block}
IDENTITY: {self.name} ({self.role})
TEAM: {roster_str}

RESEARCH MANDATE
- You MUST search the web for any claim requiring current data or evidence.
- Prefer primary sources (govt data, peer-reviewed, SEC filings). Search multiple queries.

SOURCE CITATIONS — CRITICAL RULES
Hallucinated URLs are the #1 failure mode of LLM research. Follow these rules:

1. DEFAULT FORMAT — ALWAYS PREFER THIS:
   [Title of paper or finding — Author(s) Year, Journal]
   Example: [The free-energy principle — Friston 2010, Nature Rev Neuroscience]
   This always renders as a Google Scholar search link the user can click.
   It's IMPOSSIBLE to hallucinate — Scholar will find the actual paper.

2. URL FORMAT — ONLY WHEN YOU ARE 100% CERTAIN the URL is correct:
   [Label](https://real-url-you-verified.com/exact-path)
   Use this ONLY for URLs returned directly by your web search tool in this
   turn. NEVER type a URL from memory — you will get it wrong.

3. IF UNCERTAIN, USE FORMAT (1). Wrong URLs destroy user trust permanently.
   The user's framework has a Citationist that will flag bad URLs in red.
   Don't give it anything to flag.

4. Say "UNVERIFIED:" before claims you cannot source at all.

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
- NEVER start with 'Great point @X', 'Building on @X', 'Excellent analysis',
  or any sycophantic opener. Lead with YOUR point. Agreement in one sentence max.
- Be specific: numbers, names, dates, examples. Vague generalities are unacceptable.
- Acknowledge uncertainty. Distinguish known facts from estimates.
- Do NOT profile the user or build a frame around their questions. Each question
  stands alone unless the user explicitly connects it to prior discussion.
- Keep turns CONCISE. Say what matters, skip the rest. Under 200 words unless
  the question genuinely demands depth.
- End with [DONE]. Say [NEED @Human: question] for human input.
- Leaders only: say [COMPLETE] when the project goal is fully achieved.

{self._rigor_disciplines()}"""

    def _rigor_disciplines(self) -> str:
        """Role-aware rigor rules that apply to every serious team.

        Creative/debate/judge roles get lighter rules; analytical roles
        (leader/worker/critic/synthesizer) get the full discipline stack
        the Polymath team's personalities describe in more detail.
        """
        if self.role in ("debater", "judge"):
            # Debate Club members advocate positions and judge verdicts; rigor
            # is already built into those roles' structure. Skip discipline
            # stack that would blunt advocacy.
            return (
                "EVIDENCE DISCIPLINE\n"
                "- Every factual claim needs a source (inline citation or "
                "search-query format [Title — Author Year]).\n"
                "- Cite uncertainty explicitly when claims aren't fully "
                "supported."
            )

        base = (
            "RIGOR + CREATIVE REASONING DISCIPLINES\n"
            "- DOMAIN-ADAPTIVE EVIDENCE: match citations to the domain.\n"
            "- DOSE DISCIPLINE: cite dose-response evidence for specific "
            "numbers, or flag 'convention, not derived'.\n"
            "- CONDITIONAL CLAIMS: preserve conditions teammates raised.\n"
            "\n"
            "CREATIVE REASONING (equally important as rigor)\n"
            "- When a question asks for a PROTOCOL, DESIGN, STRATEGY, or "
            "EXPLORATION, you are EXPECTED to think beyond existing evidence. "
            "Don't just review the literature — REASON from mechanism, first "
            "principles, analogy, and creative synthesis.\n"
            "- Label claims honestly:\n"
            "  (Established: multiple RCTs) = strong human evidence\n"
            "  (Emerging: limited trials) = some human data\n"
            "  (Mechanistic: from first principles) = reasoning from known "
            "biology/physics/logic, not yet tested in humans\n"
            "  (Speculative: novel synthesis) = your original reasoning\n"
            "- 'No RCT exists' is NOT a reason to say nothing. It IS a "
            "reason to say what you think SHOULD work based on mechanism, "
            "label it honestly, and let the user decide.\n"
            "- The team's value is THINKING, not just CITING. A literature "
            "review is necessary but not sufficient. Add your own reasoning."
        )

        if self.role == "leader":
            return base + (
                "\n- EVIDENCE-TAGGING (when you synthesize): every "
                "recommendation must carry its tag — (Established), "
                "(Emerging), (Mechanistic), (Speculative), or "
                "(Canonical: [source]). No unlabeled claims."
            )
        if self.role in ("critic", "judge"):
            return base + (
                "\n- FALSIFIABILITY CHECK: for each major claim, ask what "
                "evidence would refute it.\n"
                "- IMPORTANT: Do NOT kill speculative/mechanistic reasoning "
                "just because no RCT exists. Challenge the LOGIC and "
                "MECHANISM — not the evidence tier. 'No RCT' is a label, "
                "not a death sentence. Ask: is the mechanism plausible? "
                "Are there known counter-mechanisms? What would falsify "
                "this speculative claim?"
            )
        return base

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

    # ── provider calls ───────────────────────────────────

    def _get_provider(self):
        if self._provider is None:
            self._provider = get_provider(self._provider_name)
        return self._provider

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def _call_cli(self, system: str, user_prompt: str) -> str:
        """Capture response from the configured provider (spinner during generation).

        Display is handled by the caller via display_clean() — this keeps the
        output pipeline consistent whether the turn was sequential or parallel.
        """
        try:
            provider = self._get_provider()
        except ProviderError as exc:
            return f"[ERROR] {exc}"

        spinner_style = self.color.replace("bold ", "")
        status = self.console.status(
            f"  {self.icon} [{self.color}]{self.name}[/] "
            f"[dim]({self._provider_name}:{self.config.model}) thinking...[/]",
            spinner="dots",
            spinner_style=spinner_style,
        )
        status.start()

        buf = ""
        try:
            for chunk in provider.stream(
                system, user_prompt, self.config.model, self.config.max_tokens,
            ):
                buf += chunk
        except Exception as exc:
            status.stop()
            return f"[ERROR] {type(exc).__name__}: {exc}"
        finally:
            status.stop()

        text = buf.strip()
        if not text:
            return "[ERROR] Empty response from provider. The model may be overloaded — try again."
        return text

    def _call_cli_silent(self, system: str, user_prompt: str) -> str:
        """Capture full response without streaming (for parallel execution)."""
        try:
            provider = self._get_provider()
            text = provider.complete(
                system, user_prompt, self.config.model, self.config.max_tokens,
            ).strip()
        except ProviderError as exc:
            return f"[ERROR] {exc}"
        except Exception as exc:
            return f"[ERROR] {type(exc).__name__}: {exc}"
        if not text:
            return "[ERROR] Empty response from provider. The model may be overloaded — try again."
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
