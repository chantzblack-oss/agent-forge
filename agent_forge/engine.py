"""Orchestrator — assembles teams, manages rounds, handles human-in-the-loop.

v0.6 adds:
- Parallel execution of workers/debaters via ThreadPoolExecutor.
- Dynamic reactive turns when an agent emits [DIRECT @Name: ...].
- Convergence detection from critic/judge verdicts + leader [COMPLETE].
- Round summaries generated with a fast Haiku CLI call.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time as _time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt
from rich.table import Table
from rich.text import Text
import rich.box

from .agent import Agent, AgentResponse, ROLE_STYLES
from .bus import MessageBus, Message, MessageType
from .narrator import Narrator
from .teams import TeamConfig
from .verifier import (
    audit_deliberation,
    extract_citations_from_transcript,
    verify_citations_parallel,
    generate_synthesis_brief,
    mid_deliberation_pulse,
    DeliberationAudit,
    VerifiedCitation,
)
from .memory import SessionMemory, MemoryEntry

# Roles that can run in parallel within a round when auto-grouping.
_PARALLEL_ROLES = {"worker", "debater"}

_CLAUDE_PATH: str | None = shutil.which("claude")


class Orchestrator:
    """The conductor. Takes a goal + team config, runs multi-round collaboration."""

    def __init__(
        self,
        default_model: str = "opus",
        narrate_mode: str = Narrator.MODE_HIGHLIGHTS,
    ) -> None:
        self.default_model = default_model
        self.narrate_mode = narrate_mode
        self.console = Console(force_terminal=True)
        self.bus = MessageBus()
        self.agents: dict[str, Agent] = {}
        self.narrator: Narrator | None = None
        self._transcript: list[dict] = []
        self._goal: str = ""
        self._team: TeamConfig | None = None
        self._start_time: float = 0.0

    # ── public ────────────────────────────────────────────

    def run(self, goal: str, team: TeamConfig) -> None:
        """Execute a full multi-agent session.

        After the rounds complete, runs the v0.7 finalization stack:
        Verifier audit, Learning Recap, Citationist verification, and
        memory save — the same scaffolding that runs per-message in chat.
        """
        self.bus = MessageBus()
        self.agents = {}
        self._transcript = []
        self._goal = goal
        self._team = team
        self._start_time = _time.time()
        self.narrator = Narrator(mode=self.narrate_mode)
        try:
            self._memory: SessionMemory | None = SessionMemory()
        except Exception:
            self._memory = None

        try:
            self._run_session(goal, team)
        finally:
            if self.narrator:
                self.narrator.shutdown()

    def chat(self, team: TeamConfig) -> None:
        """Enter a persistent chat loop with the team.

        The team assembles once; conversation history (bus + scratchpad)
        persists across every user message. Each user turn triggers one
        short deliberation (respecting ``team.max_deliberation_turns``),
        then runs a Verifier audit, Citationist verification of the most
        important URLs, and saves a compact memory entry so future sessions
        can build on this one.

        Commands the user can type at the prompt:
          /bye, /quit, /exit  — end the session
          /reset              — wipe conversation history, keep team
          /export             — dump the transcript to a markdown file
          /ask <agent>        — direct a question to one specific agent
          /memory             — list stored prior-session summaries
        """
        self.bus = MessageBus()
        self.agents = {}
        self._transcript = []
        self._goal = f"Chat session with {team.name}"
        self._team = team
        self._start_time = _time.time()
        self.narrator = Narrator(mode=self.narrate_mode)
        # Persistent memory across sessions — silently disabled if init fails
        try:
            self._memory: SessionMemory | None = SessionMemory()
        except Exception:
            self._memory = None

        try:
            self._run_chat(team)
        finally:
            if self.narrator:
                self.narrator.shutdown()

    def _run_chat(self, team: TeamConfig) -> None:
        """Chat loop with persistent team state."""
        self._print_assembly(team)

        if self.narrator:
            agent_names = ", ".join(ac.name for ac in team.agents)
            self.narrator.narrate_system(
                f"Assembling {team.name}. Ready to chat.",
            )
            self.narrator.wait_until_done()

        roster = [ac.name for ac in team.agents]
        for ac in team.agents:
            if not ac.model or ac.model == "default":
                ac.model = self.default_model
            agent = Agent(
                config=ac,
                bus=self.bus,
                narrator=self.narrator,
                team_roster=roster,
            )
            self.agents[ac.name] = agent

        self._print_chat_banner(team)

        message_count = 0
        while True:
            self.console.print()
            try:
                user_input = Prompt.ask("  [bold bright_white]you[/]").strip()
            except (KeyboardInterrupt, EOFError):
                self.console.print()
                break
            if not user_input:
                continue

            # ── handle commands ──
            low = user_input.lower()
            if low in ("/bye", "/quit", "/exit", "/q"):
                break
            if low == "/reset":
                self.bus = MessageBus()
                self._transcript = []
                message_count = 0
                for a in self.agents.values():
                    a.bus = self.bus
                self.console.print("  [dim]✓ Conversation history cleared.[/]")
                continue
            if low == "/export":
                path = self._export_session()
                self.console.print(f"  [bold green]✓ Exported to {path}[/]")
                continue
            if low.startswith("/ask "):
                self._chat_ask_one(user_input[5:].strip(), message_count + 1)
                message_count += 1
                continue
            if low in ("/help", "/?"):
                self._print_chat_help()
                continue
            if low == "/memory":
                self._print_memory_list()
                continue

            # ── normal message: deliberate and answer ──

            # On the FIRST user message, pull relevant prior sessions from
            # memory so the team can build on what you've already learned.
            if message_count == 0 and self._memory is not None:
                self._inject_prior_memory(user_input)

            message_count += 1
            self.bus.post(Message(
                sender="Human",
                content=user_input,
                msg_type=MessageType.HUMAN,
                round_num=message_count,
            ))

            # One deliberation per user message
            self._execute_deliberation_round(team, round_num=message_count)

            # Audit: Verifier pass — surfaces what Skeptic missed
            self._render_audit_panel(user_input, round_num=message_count)

            # Pedagogical wrap-up: Learning Recap panel
            self._render_learning_recap(team, round_num=message_count)

            # Reliability: Citationist — fetch + verify the cited URLs
            self._render_citations_panel(round_num=message_count)

            # Persistence: save this deliberation for future sessions
            if self._memory is not None:
                self._save_to_memory(team, user_input, round_num=message_count)

            # After 3+ messages, summarize the earliest one to keep context focused
            if message_count >= 3:
                oldest_unsum = message_count - 2
                if not self.bus.get_round_summary(oldest_unsum):
                    self._generate_and_store_round_summary(oldest_unsum)

        self._print_chat_goodbye()

    def _chat_ask_one(self, request: str, turn: int) -> None:
        """Direct a single question at one agent (parsed as: '@Name question' or 'Name: question')."""
        import re as _re
        m = _re.match(r"^@?(\w+)[:\s]+(.+)$", request, _re.DOTALL)
        if not m:
            self.console.print(
                "  [yellow]Usage: /ask @AgentName your question[/]"
            )
            return
        target, question = m.group(1), m.group(2).strip()
        agent = self.agents.get(target)
        if not agent:
            self.console.print(f"  [yellow]Unknown agent: {target}[/]")
            return

        self.bus.post(Message(
            sender="Human",
            content=f"@{target}: {question}",
            msg_type=MessageType.HUMAN,
            round_num=turn,
        ))
        prompt = (
            f"The user has addressed you directly: {question}\n\n"
            "Answer thoroughly using your expertise. Keep it conversational. "
            "Reference prior context where relevant."
        )
        resp = agent.respond(prompt, round_num=turn, is_final_round=False)
        self._transcript.append({
            "round": turn,
            "agent": target,
            "role": agent.role,
            "content": resp.message.content,
        })

    # ── memory / audit / citations hooks ───────────────────

    def _finalize_session(
        self, goal: str, team: TeamConfig, round_num: int,
    ) -> None:
        """Whole-session finalization: audit + learning recap + citations + memory save.

        Called from ``_run_session`` at every exit path (complete, error,
        user-stop, max-rounds). Mirrors what ``chat()`` does per-message but
        scoped to the full classic-session transcript.

        Each sub-step is wrapped so a failure in one (e.g. Haiku timeout)
        doesn't block the others. Memory save is last so audit/recap/citations
        are visible even if persistence fails.
        """
        if not self._transcript:
            return

        # Verifier
        try:
            self._render_audit_panel(goal, round_num=None)
        except Exception:
            pass
        # Learning Recap (new for classic sessions)
        try:
            self._render_learning_recap(team, round_num=None)
        except Exception:
            pass
        # Citationist
        try:
            self._render_citations_panel(round_num=None)
        except Exception:
            pass
        # Memory save
        if self._memory is not None:
            try:
                self._save_to_memory(team, goal, round_num=None)
            except Exception:
                pass

    def _inject_prior_memory(self, user_question: str) -> None:
        """Pull top-N relevant prior sessions from memory and post them as system context."""
        if self._memory is None:
            return
        try:
            hits = self._memory.recall(user_question, n_results=3)
        except Exception:
            return
        if not hits:
            return

        ctx_block = SessionMemory.format_for_context(hits)
        self.bus.post(Message(
            sender="System",
            content=ctx_block,
            msg_type=MessageType.SYSTEM,
            round_num=0,
        ))
        # Compact user-facing hint
        self.console.print()
        self.console.print(
            f"  [dim]🧠 Memory: injected {len(hits)} relevant prior session(s) "
            f"(backend={self._memory.backend})[/]"
        )

    def _render_audit_panel(
        self, user_question: str, round_num: int | None = None,
    ) -> None:
        """Verifier pass — highlight what Skeptic missed.

        ``round_num=None`` audits the entire session (all rounds). A specific
        round_num limits the audit to that round's transcript entries, which
        is how chat mode uses it.
        """
        if round_num is None:
            round_entries = list(self._transcript)
        else:
            round_entries = [e for e in self._transcript if e.get("round") == round_num]
        try:
            audit = audit_deliberation(round_entries, user_question)
        except Exception:
            return
        if audit.is_empty():
            return

        lines: list[str] = []
        if audit.contradictions:
            lines.append("[bold bright_white]Unresolved contradictions[/]")
            for c in audit.contradictions:
                lines.append(f"  [yellow]⚠[/] {c}")
        if audit.unsupported_claims:
            if lines:
                lines.append("")
            lines.append("[bold bright_white]Unsupported claims[/]")
            for c in audit.unsupported_claims:
                lines.append(f"  [yellow]•[/] {c}")
        if audit.over_extrapolations:
            if lines:
                lines.append("")
            lines.append("[bold bright_white]Over-extrapolations[/]")
            for c in audit.over_extrapolations:
                lines.append(f"  [yellow]↯[/] {c}")
        if audit.coverage_gaps:
            if lines:
                lines.append("")
            lines.append("[bold bright_white]Coverage gaps[/] [dim](dimensions the team skipped)[/]")
            for c in audit.coverage_gaps:
                lines.append(f"  [bright_red]✗[/] {c}")

        self.console.print()
        self.console.print(Panel(
            Text.from_markup("\n".join(lines)),
            title="[bold yellow]🔎 Audit Addendum[/] [dim](Verifier)[/]",
            title_align="left",
            border_style="yellow",
            padding=(1, 2),
        ))

    def _render_citations_panel(self, round_num: int | None = None) -> None:
        """Citationist — fetch the top URLs and check they support the claims.

        ``round_num=None`` scans the entire session transcript for citations.
        """
        if round_num is None:
            round_entries = list(self._transcript)
        else:
            round_entries = [e for e in self._transcript if e.get("round") == round_num]
        tagged = extract_citations_from_transcript(round_entries, max_total=6)
        if not tagged:
            return

        self.console.print()
        self.console.print(
            f"  [dim]🔗 Verifying {len(tagged)} citation(s) — fetching sources...[/]"
        )
        try:
            results = verify_citations_parallel(tagged, max_workers=3)
        except Exception:
            return
        if not results:
            return

        lines: list[str] = []
        n_verified = sum(1 for _, c in results if c.status == "verified")
        n_paywalled = sum(1 for _, c in results if c.status == "paywalled")
        n_hallucinated = sum(
            1 for _, c in results if c.status in ("wrong_article", "not_found")
        )
        n_errored = sum(1 for _, c in results if c.status == "error")
        bits = [f"[green]{n_verified} verified[/]"]
        if n_paywalled:
            bits.append(f"[yellow]{n_paywalled} paywalled[/]")
        if n_hallucinated:
            bits.append(f"[red]{n_hallucinated} BAD URL[/]")
        if n_errored:
            bits.append(f"[dim]{n_errored} errored[/]")
        lines.append(" · ".join(bits))
        lines.append("")

        # Status → (badge, color, short label)
        _STATUS_DISPLAY = {
            "verified":      ("[green]✓[/]",    "green",  None),
            "paywalled":     ("[yellow]🔒[/]",  "yellow", "paywalled (may be real, can't verify)"),
            "wrong_article": ("[red]✗[/]",      "red",    "URL points to a DIFFERENT paper"),
            "not_found":     ("[red]✗[/]",      "red",    "URL does not exist (hallucinated)"),
            "error":         ("[dim]?[/]",     "dim",    "verification failed"),
        }

        for agent, cit in results:
            badge, _color, flag = _STATUS_DISPLAY.get(
                cit.status, ("[dim]?[/]", "dim", "unknown")
            )
            lines.append(
                f"{badge} [bold]{cit.label[:60]}[/] [dim]({agent})[/]"
            )
            lines.append(f"    [dim link={cit.url}]{cit.url}[/]")
            if flag:
                lines.append(f"    [dim]{flag}[/]")
            if cit.status == "verified" and cit.extracted_quote:
                lines.append(f"    [green]quote:[/] [italic]\"{cit.extracted_quote[:220]}\"[/]")
            elif cit.finding:
                lines.append(f"    [dim]note:[/] [dim]{cit.finding[:220]}[/]")

        self.console.print(Panel(
            Text.from_markup("\n".join(lines)),
            title="[bold green]🔗 Citations Verified[/] [dim](Citationist)[/]",
            title_align="left",
            border_style="green",
            padding=(1, 2),
        ))

    def _save_to_memory(
        self, team: TeamConfig, user_question: str, round_num: int | None = None,
    ) -> None:
        """Extract TL;DR + synthesis + concepts from this round (or whole session) and persist.

        ``round_num=None`` uses the last leader turn across the entire transcript,
        which is what classic ``run()`` sessions want.
        """
        if self._memory is None:
            return

        if round_num is None:
            scope = list(self._transcript)
        else:
            scope = [e for e in self._transcript if e.get("round") == round_num]
        # Leader's synthesis is the most recent leader turn in scope
        leader_entries = [e for e in scope if e.get("role") == "leader"]
        synthesis_full = leader_entries[-1]["content"] if leader_entries else ""
        if not synthesis_full:
            return

        tldr = self._extract_tldr_from_synthesis(synthesis_full)
        concepts = self._extract_concepts_from_recap()

        entry = MemoryEntry(
            session_id=SessionMemory.new_session_id(),
            timestamp=datetime.now().isoformat(timespec="seconds"),
            team_name=team.name,
            user_question=user_question[:1000],
            synthesis_tldr=tldr[:400],
            synthesis_full=synthesis_full[:5000],
            key_concepts=concepts[:8],
        )
        try:
            self._memory.remember(entry)
        except Exception:
            pass

    def _extract_tldr_from_synthesis(self, text: str) -> str:
        """Best-effort: grab 'The Takeaway' sentence from Scholar's 3-layer synthesis."""
        import re as _re
        m = _re.search(
            r"(?:The\s+Takeaway|TL;DR|\(a\)\s*(?:The\s+Takeaway)?)[:\s]*(.+?)(?:\n\n|\(b\)|$)",
            text, _re.IGNORECASE | _re.DOTALL,
        )
        if m:
            return m.group(1).strip()[:400]
        # Fallback: first non-header sentence
        for line in text.split("\n"):
            line = line.strip()
            if line and not line.startswith(("#", "(", "—", "-", "*", "[")):
                return line[:400]
        return text[:400]

    def _extract_concepts_from_recap(self) -> list[dict[str, str]]:
        """Parse 'Key Concepts' entries from the most recently rendered Learning Recap.

        We store concepts on the orchestrator during recap render; here we
        just read that cached list. Returns [] if recap generation failed.
        """
        return getattr(self, "_last_recap_concepts", [])

    def _print_memory_list(self) -> None:
        """Show the user their stored memory entries (/memory command)."""
        if self._memory is None:
            self.console.print("  [yellow]Memory is not initialized.[/]")
            return
        entries = self._memory.all_entries()
        if not entries:
            self.console.print("  [dim]No prior sessions yet.[/]")
            return
        self.console.print()
        self.console.print(
            f"  [bold]🧠 {len(entries)} session(s) in memory "
            f"[dim](backend={self._memory.backend})[/][/]"
        )
        for e in entries[-10:]:
            ts = e.get("timestamp", "")[:10]
            q = e.get("user_question", "")[:90]
            tldr = e.get("synthesis_tldr", "")[:120]
            self.console.print(f"  [dim]{ts}[/]  {q}")
            self.console.print(f"    [dim italic]→ {tldr}[/]")

    def _print_chat_banner(self, team: TeamConfig) -> None:
        mem_status = (
            f"memory: {self._memory.backend}" if self._memory is not None else "memory: off"
        )
        self.console.print()
        self.console.print(Panel(
            f"  [bold]{team.name}[/] is ready.  Ask anything.\n\n"
            f"  [dim]After each answer you'll see:[/]\n"
            f"  [dim]  🎓 Agent panels · 🔎 Audit · 📘 Learning Recap · 🔗 Citations Verified[/]\n"
            f"  [dim]Sessions are saved to memory — future questions build on this one.[/]\n\n"
            "  [dim]Commands: /ask @Name q · /memory · /export · /reset · /bye[/]\n"
            f"  [dim]Status: {mem_status}[/]",
            border_style="bright_blue",
            title="[bold]Chat[/]",
            padding=(1, 2),
        ))

    def _print_chat_help(self) -> None:
        self.console.print()
        self.console.print(
            "  [bold]commands:[/]\n"
            "    [bold white]/ask @Name question[/]  — direct a question at one agent\n"
            "    [bold white]/memory[/]              — list stored prior sessions\n"
            "    [bold white]/export[/]              — save transcript to markdown\n"
            "    [bold white]/reset[/]               — clear conversation history\n"
            "    [bold white]/bye[/]                 — end session"
        )

    def _print_chat_goodbye(self) -> None:
        self.console.print()
        self.console.print("  [dim]Goodbye.[/]")
        if self.narrator:
            self.narrator.narrate_system("Goodbye.")
            self.narrator.wait_until_done()

    def _run_session(self, goal: str, team: TeamConfig) -> None:
        """Inner session loop."""
        self._print_assembly(team)

        if self.narrator:
            agent_names = ", ".join(ac.name for ac in team.agents)
            self.narrator.narrate_system(
                f"Assembling {team.name} team. Agents: {agent_names}. "
                f"Goal: {goal}",
            )
            self.narrator.wait_until_done()

        roster = [ac.name for ac in team.agents]
        for ac in team.agents:
            if not ac.model or ac.model == "default":
                ac.model = self.default_model
            agent = Agent(
                config=ac,
                bus=self.bus,
                narrator=self.narrator,
                team_roster=roster,
            )
            self.agents[ac.name] = agent

        self.bus.post(Message(
            sender="System",
            content=f"PROJECT GOAL: {goal}",
            msg_type=MessageType.SYSTEM,
            round_num=0,
        ))

        # Pull relevant prior sessions from memory — same hook as chat()
        if getattr(self, "_memory", None) is not None:
            self._inject_prior_memory(goal)

        # Build execution plan (either explicit or auto-derived)
        execution_plan = self._resolve_execution_plan(team)

        # Execute rounds
        for round_num in range(1, team.max_rounds + 1):
            self._print_round(round_num, team.max_rounds)

            if self.narrator:
                self.narrator.narrate_system(
                    f"Round {round_num} of {team.max_rounds}. Begin.",
                )
                self.narrator.wait_until_done()

            if getattr(team, "deliberation_mode", False):
                result = self._execute_deliberation_round(team, round_num)
            else:
                result = self._execute_round(team, execution_plan, round_num)
            if result == "complete":
                self._print_round_recap(round_num)
                self._print_complete()
                self._finalize_session(goal, team, round_num)
                self._end_session(goal, team, round_num)
                return
            if result == "error":
                self.console.print("\n  [bold red]Stopping due to error.[/]")
                # Still try to finalize what we have
                self._finalize_session(goal, team, round_num)
                return

            # Round recap
            self._print_round_recap(round_num)

            # Convergence detection — stop early if critics approve + leader implicit consensus
            if round_num < team.max_rounds and self._check_convergence(round_num):
                self.console.print(
                    "\n  [bold bright_green]✓ Team converged — stopping early.[/]"
                )
                if self.narrator:
                    self.narrator.narrate_system(
                        "Team has reached convergence. Stopping early."
                    )
                    self.narrator.wait_until_done()
                break

            # Generate round summary for context compression in future rounds
            self._generate_and_store_round_summary(round_num)

            # Between-round interaction
            if round_num < team.max_rounds:
                action = self._between_rounds(team, round_num)
                if action == "stop":
                    self._finalize_session(goal, team, round_num)
                    self._end_session(goal, team, round_num)
                    return
                elif action not in ("continue", ""):
                    self.bus.post(Message(
                        sender="Human",
                        content=action,
                        msg_type=MessageType.HUMAN,
                        round_num=round_num,
                    ))

        # Force final synthesis if leader didn't [COMPLETE]
        leader = next(
            (a for a in self.agents.values() if a.role == "leader"), None
        )
        if leader:
            self._print_round(team.max_rounds, team.max_rounds)
            self.console.print("  [bold bright_white]Final synthesis...[/]")
            if self.narrator:
                self.narrator.narrate_system("Final synthesis. Delivering results.")
                self.narrator.wait_until_done()
            prompt = (
                "Deliver the FINAL DELIVERABLE NOW. Do NOT repeat data the team already "
                "presented — the reader has seen it all. Your job is to:\n"
                "1. Draw conclusions that emerge from COMBINING the team's work\n"
                "2. Resolve tensions between optimistic and critical perspectives\n"
                "3. Present a clear decision framework\n"
                "4. End with 'WHAT TO DO THIS WEEK' — 3-5 concrete first actions\n\n"
                "No planning, no task assignment, no process talk. "
                "Reference findings briefly, don't restate them. End with [COMPLETE]."
            )
            resp = leader.respond(prompt, round_num=team.max_rounds, is_final_round=True)
            self._transcript.append({
                "round": team.max_rounds,
                "agent": leader.name,
                "role": leader.role,
                "content": resp.message.content,
            })
        self._print_complete()
        self._finalize_session(goal, team, team.max_rounds)
        self._end_session(goal, team, team.max_rounds)

    # ── live deliberation mode ────────────────────────────

    def _execute_deliberation_round(
        self,
        team: TeamConfig,
        round_num: int,
    ) -> str:
        """Dynamic turn-taking loop — short turns, speaker picked by @-mentions.

        This is the "real-time meeting" flow: leader opens, then whoever
        was addressed (or @-mentioned) speaks next, creating organic
        back-and-forth instead of a fixed order.  Returns one of:
        "complete" (leader said [COMPLETE]), "error", or "ok".
        """
        import re as _re

        is_final = round_num == team.max_rounds
        leader_name = self._leader_name()
        if not leader_name:
            self.console.print("  [bold red]Deliberation requires a leader role.[/]")
            return "error"

        turns_used = 0
        next_speaker = leader_name                # leader opens the round
        last_speaker: str | None = None

        turn_budget = team.deliberation_turn_tokens
        midpoint_pulse_fired = False

        while turns_used < team.max_deliberation_turns:
            agent = self.agents[next_speaker]
            self._print_turn_header(turns_used + 1, team.max_deliberation_turns, agent)

            # Mid-deliberation coverage pulse — fires once, roughly at the
            # midpoint, so the remaining turns can redirect if the team is
            # missing a load-bearing dimension (e.g. social connection on
            # a resilience question).  Much more effective than end-of-round
            # coverage flagging in the Audit, which fires too late.
            if (not midpoint_pulse_fired
                    and turns_used >= max(3, team.max_deliberation_turns // 2)):
                midpoint_pulse_fired = True
                self._fire_midpoint_pulse(round_num)

            prompt = self._build_deliberation_prompt(
                agent, round_num, team.max_rounds,
                turn_number=turns_used + 1,
                max_turns=team.max_deliberation_turns,
                is_opening=turns_used == 0,
            )
            # Inject the pre-synthesis brief right before the leader closes.
            # The leader's prompt becomes 'here is the ledger, integrate from it'
            # instead of 'recall and integrate' — closes the smuggling channel.
            if (agent.role == "leader"
                    and turns_used >= team.max_deliberation_turns - 2
                    and turns_used >= 3):
                brief = self._get_synthesis_brief(round_num)
                if brief:
                    prompt = (
                        f"{prompt}\n\n"
                        "══ PRE-SYNTHESIS CLAIM LEDGER ══\n"
                        "(Integrate from THIS ledger. Preserve every grade and "
                        "condition exactly. Do NOT silently promote lower-grade "
                        "claims. Do NOT drop conditions any teammate raised.)\n\n"
                        f"{brief}"
                    )

            # Leaders need 2x budget for the three-layer pedagogical synthesis;
            # workers stay at the short-turn budget
            original_max = agent.config.max_tokens
            agent.config.max_tokens = turn_budget * 2 if agent.role == "leader" else turn_budget
            try:
                resp = agent.respond(prompt, round_num=round_num, is_final_round=is_final)
            finally:
                agent.config.max_tokens = original_max

            status = self._post_agent(resp, agent, round_num, is_final)
            turns_used += 1

            if status == "error":
                return status
            if status == "complete":
                # Give Skeptic (if team has one) a final pressure-test on the
                # synthesis itself. Scholar's close is the highest-leverage
                # place for false equivalences and flattened conditions to
                # sneak in, and the inline Skeptic turns never see the
                # synthesis. This one extra turn is the last-line defense.
                self._run_synthesis_audit(team, resp, round_num, is_final)
                return status

            # If _post_agent fired reactive turns (via [DIRECT @X]), the real
            # last speaker is whoever was called reactively — look it up from
            # the transcript so round-robin picks the right next agent.
            last_real_speaker = self._transcript[-1]["agent"] if self._transcript else next_speaker
            last_speaker = last_real_speaker
            next_speaker = self._pick_next_speaker(resp, team, last_speaker, leader_name)

        # Hit the turn cap — force leader to synthesize
        self.console.print(
            f"\n  [dim]Turn cap reached ({team.max_deliberation_turns}). Leader synthesizing.[/]"
        )
        leader = self.agents[leader_name]
        closing = (
            "The deliberation has reached its turn cap. Synthesize the discussion "
            "into a decision: (1) the one key insight that emerged, (2) remaining "
            "disagreements and how to resolve them, (3) next concrete actions. "
            "Under 400 words."
        )
        resp = leader.respond(closing, round_num=round_num, is_final_round=is_final)
        return self._post_agent(resp, leader, round_num, is_final)

    def _fire_midpoint_pulse(self, round_num: int) -> None:
        """Run a coverage pulse at the deliberation midpoint and inject the result."""
        question = self._current_question(round_num)
        transcript_so_far = [e for e in self._transcript if e.get("round") == round_num]
        try:
            missing = mid_deliberation_pulse(transcript_so_far, question)
        except Exception:
            return
        if not missing:
            return

        # Visible operator hint
        self.console.print()
        self.console.print(
            "  [bold bright_cyan]🧭 Mid-deliberation pulse:[/] "
            "[dim]dimensions the team should address before closing[/]"
        )
        for m in missing:
            self.console.print(f"  [cyan]›[/] {m}")

        # Inject into the bus so upcoming agents see it in their context
        hint_text = (
            "MID-DELIBERATION COVERAGE HINT: An external auditor flagged "
            "these dimensions as critical-but-not-yet-addressed for the "
            "user's question. The remaining turns should incorporate them "
            "or explicitly justify why they don't apply:\n\n"
            + "\n".join(f"  • {m}" for m in missing)
        )
        self.bus.post(Message(
            sender="System",
            content=hint_text,
            msg_type=MessageType.SYSTEM,
            round_num=round_num,
        ))

    def _get_synthesis_brief(self, round_num: int) -> str:
        """Build the pre-synthesis structured brief; cache per round."""
        cache_key = f"_synthesis_brief_r{round_num}"
        cached = getattr(self, cache_key, None)
        if cached is not None:
            return cached

        question = self._current_question(round_num)
        round_entries = [e for e in self._transcript if e.get("round") == round_num]
        try:
            brief = generate_synthesis_brief(round_entries, question)
        except Exception:
            brief = ""
        setattr(self, cache_key, brief)
        return brief

    def _current_question(self, round_num: int) -> str:
        """The user's question for this round (chat) or the session goal (classic run)."""
        round_msgs = self.bus.get_round_messages(round_num)
        human = next(
            (m.content for m in round_msgs if m.msg_type == MessageType.HUMAN),
            "",
        )
        return human or self._goal or ""

    def _run_synthesis_audit(
        self,
        team: TeamConfig,
        synthesis_resp: AgentResponse,
        round_num: int,
        is_final: bool,
    ) -> None:
        """One mandatory pressure-test of the leader's synthesis, by the critic.

        The inline Skeptic never sees the synthesis — they speak during the
        deliberation, then Scholar closes. This turn exists precisely to catch
        false equivalences Scholar introduced (e.g. 'MBSR and HIIT both earn
        prior-updater status' without comparable evidence), conditions that
        got flattened, and smuggled claims. If the synthesis is sound, the
        critic says 'synthesis approved' and stops — no manufactured doubt.
        """
        # Find the team's critic/judge (first one if multiple)
        critic = next(
            (a for a in self.agents.values() if a.role in ("critic", "judge")),
            None,
        )
        if critic is None:
            return

        synthesis_text = synthesis_resp.message.content
        audit_prompt = (
            "Scholar has delivered the closing synthesis for this deliberation. "
            "Your job right now is NOT to re-litigate the whole debate — it is "
            "to audit the SYNTHESIS specifically for three failure modes:\n\n"
            "1. FALSE EQUIVALENCE: Did Scholar equate two things the evidence "
            "doesn't equate? (e.g. 'X and Y both earn A-tier status' when only "
            "X has the transfer-test RCT)\n"
            "2. FLATTENED CONDITIONS: Did Scholar drop a condition YOU or a "
            "teammate introduced? (e.g. 'works for high-baseline-stress' got "
            "turned into blanket 'do it')\n"
            "3. SMUGGLED CLAIMS: Did Scholar introduce ANY assertion that the "
            "team never actually evidenced during deliberation?\n\n"
            f"SCHOLAR'S SYNTHESIS:\n\n{synthesis_text[:6000]}\n\n"
            "Deliver your audit in under 120 words. Quote the exact phrase "
            "you're flagging. If the synthesis is genuinely sound, say "
            "[SYNTHESIS APPROVED] in one sentence and stop — do not "
            "manufacture doubt."
        )
        self.console.print()
        self.console.print(
            f"  [dim]🔍 {critic.name} pressure-testing the synthesis...[/]"
        )
        # Give Skeptic a fresh small budget for this audit
        original_max = critic.config.max_tokens
        critic.config.max_tokens = 500
        try:
            audit_resp = critic.respond(
                audit_prompt, round_num=round_num, is_final_round=is_final,
            )
        finally:
            critic.config.max_tokens = original_max

        self._transcript.append({
            "round": round_num,
            "agent": critic.name,
            "role": critic.role,
            "content": f"[Synthesis Audit]\n\n{audit_resp.message.content}",
        })

    def _leader_name(self) -> str | None:
        for a in self.agents.values():
            if a.role == "leader":
                return a.name
        return None

    def _pick_next_speaker(
        self,
        resp: AgentResponse,
        team: TeamConfig,
        last_speaker: str,
        leader_name: str,
    ) -> str:
        """Decide who speaks next based on the previous agent's output.

        Priority:
          1. Explicit [DIRECT @X: ...] request
          2. Last-resort inline @mention of a teammate (other than self)
          3. Leader gets the floor back every ~3 turns to moderate
          4. Round-robin through non-leaders, skipping the last speaker
        """
        import re as _re

        content = resp.message.content
        # 1. Explicit direct request
        for target, _q in resp.direct_requests:
            if target in self.agents and target != last_speaker:
                return target
        # 2. @mention (first one that isn't self / [NEED @Human])
        mentions = _re.findall(r"@(\w+)", content)
        for name in mentions:
            if name == "Human":
                continue
            if name in self.agents and name != last_speaker:
                return name
        # 3. Periodic leader moderation
        recent = [e for e in self._transcript if e.get("role")][-3:]
        if last_speaker != leader_name and all(e["agent"] != leader_name for e in recent):
            return leader_name
        # 4. Round-robin (skip last speaker)
        non_leader = [
            n for n in team.round_order if n != leader_name and n != last_speaker
        ]
        if non_leader:
            return non_leader[0]
        return leader_name

    def _build_deliberation_prompt(
        self,
        agent: Agent,
        round_num: int,
        max_rounds: int,
        turn_number: int,
        max_turns: int,
        is_opening: bool,
    ) -> str:
        """Short, conversational prompt that encourages back-and-forth."""
        is_chat = bool(self._team and getattr(self._team, "chat_mode", False))
        focus = (
            "the user's MOST RECENT message in the conversation history"
            if is_chat else
            "the PROJECT GOAL"
        )
        r = (
            f"Turn {turn_number}/{max_turns}."
            if is_chat else
            f"Deliberation — turn {turn_number}/{max_turns} of round {round_num}/{max_rounds}."
        )

        if is_opening and agent.role == "leader":
            return (
                f"{r} You are OPENING the deliberation.  Read {focus} and "
                f"frame the question sharply — if it's vague, reframe it into "
                f"something the team can actually answer well.  Then call on "
                f"ONE teammate using [DIRECT @Name: specific task] to kick "
                f"things off.  Under 150 words."
            )

        base = (
            f"{r} This is a LIVE conversation — not a report. Keep your turn to "
            f"~150 words.  Lead with your single best point.  "
            f"Address {focus}.  "
            f"If you want a specific teammate to respond, use [DIRECT @Name: question] "
            f"at the end of your turn (you can also @mention them inline).  "
            f"Ask hard questions.  Cite sources briefly with URLs.  End with [DONE]."
        )

        if agent.role == "leader":
            synth = (
                "if it's time to close, say [COMPLETE] with a synthesis that "
                "ANSWERS the user's question — integrating what the team said, "
                "not summarizing it.  STRICT RULE: do not introduce NEW factual "
                "claims the team never discussed or evidenced.  If you want to "
                "include something, you must have heard it in the deliberation "
                "above.  The synthesis earns its power from integration, not "
                "from you quietly adding new assertions."
                if is_chat else
                "if it's time to close, say [COMPLETE] with a one-paragraph "
                "decision.  Do not introduce new factual claims in synthesis."
            )
            return (
                f"{base}  As leader, moderate: if the discussion is circling, redirect; "
                f"if it's converging, test the consensus; {synth}"
            )
        if agent.role in ("critic", "judge"):
            return (
                f"{base}  As reviewer, spot-check the most recent claim — "
                f"demand a source, challenge the logic, or say [APPROVED] if the "
                f"case is solid."
            )
        return base

    def _print_turn_header(self, turn: int, max_turns: int, agent: Agent) -> None:
        self.console.print()
        self.console.print(
            f"  [dim]turn {turn}/{max_turns} —[/] [{agent.color}]{agent.name}[/] "
            f"[dim]({agent.role})[/]"
        )

    # ── execution planning ────────────────────────────────

    def _resolve_execution_plan(self, team: TeamConfig) -> list[list[str]]:
        """Get explicit execution plan, or default to fully sequential.

        Parallel execution is opt-in per team via ``TeamConfig.execution_plan``
        because most teams encode real ordering dependencies in ``round_order``
        (debaters must react to each other; Storyteller's Charactersmith
        depends on Worldbuilder; Code Shop's Tester depends on Backend, etc.).
        Blindly parallelizing consecutive workers corrupts those semantics.

        Teams that benefit from real concurrent work — like Cross-Model
        Braintrust, where independent models should research the same
        question in parallel — declare it explicitly.
        """
        explicit = getattr(team, "execution_plan", None)
        if explicit:
            return explicit
        return [[name] for name in team.round_order]

    # ── round execution ───────────────────────────────────

    def _execute_round(
        self,
        team: TeamConfig,
        execution_plan: list[list[str]],
        round_num: int,
    ) -> str:
        """Run one full round honoring the execution plan. Returns 'ok' | 'complete' | 'error'."""
        is_final = round_num == team.max_rounds

        # Count how many times each agent appears — last occurrence is "final in round"
        last_positions: dict[str, int] = {}
        flat_order = [n for group in execution_plan for n in group]
        for i, name in enumerate(flat_order):
            last_positions[name] = i

        flat_idx = 0
        total = len(flat_order)

        for group in execution_plan:
            if len(group) == 1:
                agent_name = group[0]
                is_last = flat_idx == last_positions[agent_name]
                self._print_agent_position(flat_idx + 1, total, agent_name, self.agents[agent_name].role)
                status = self._run_one_agent(
                    team, agent_name, round_num, is_final,
                    position_in_round=flat_idx,
                    is_last_in_round=is_last,
                )
                flat_idx += 1
                if status in ("complete", "error"):
                    return status
            else:
                # Parallel group — all agents see identical context, run concurrently
                self._print_parallel_header(group)
                status = self._run_parallel_group(
                    team, group, round_num, is_final, flat_idx, last_positions,
                )
                flat_idx += len(group)
                if status in ("complete", "error"):
                    return status

        return "ok"

    def _run_one_agent(
        self,
        team: TeamConfig,
        agent_name: str,
        round_num: int,
        is_final: bool,
        position_in_round: int,
        is_last_in_round: bool,
    ) -> str:
        """Execute one agent sequentially with streaming output."""
        agent = self.agents[agent_name]
        prompt = self._build_prompt(
            agent, round_num, team.max_rounds,
            position_in_round=position_in_round,
            is_last_in_round=is_last_in_round,
        )
        resp = agent.respond(prompt, round_num=round_num, is_final_round=is_final)
        return self._post_agent(resp, agent, round_num, is_final)

    def _run_parallel_group(
        self,
        team: TeamConfig,
        group: list[str],
        round_num: int,
        is_final: bool,
        start_idx: int,
        last_positions: dict[str, int],
    ) -> str:
        """Run a group of agents concurrently; display results sequentially."""
        # Capture a single context snapshot so parallel agents work from identical state
        prompts: dict[str, str] = {}
        for i, name in enumerate(group):
            agent = self.agents[name]
            prompts[name] = self._build_prompt(
                agent, round_num, team.max_rounds,
                position_in_round=start_idx + i,
                is_last_in_round=(start_idx + i) == last_positions[name],
            )

        with ThreadPoolExecutor(max_workers=len(group)) as pool:
            futures = {
                name: pool.submit(
                    self.agents[name].respond_silent, prompts[name], round_num,
                )
                for name in group
            }
            responses: dict[str, AgentResponse] = {
                name: fut.result() for name, fut in futures.items()
            }

        # Display and post each result sequentially in group order
        for name in group:
            resp = responses[name]
            self.agents[name].display_buffered(resp.message.content)
            if self.narrator and not resp.message.content.startswith("[ERROR]"):
                self.narrator.narrate_agent(
                    resp.message.content, name, self.agents[name].role, is_final,
                )
            status = self._post_agent(resp, self.agents[name], round_num, is_final)
            if status in ("complete", "error"):
                return status

        if self.narrator:
            self.narrator.wait_until_done()
        return "ok"

    def _post_agent(
        self,
        resp: AgentResponse,
        agent: Agent,
        round_num: int,
        is_final: bool,
    ) -> str:
        """Record in transcript, handle human requests, trigger reactive turns."""
        content = resp.message.content
        self._transcript.append({
            "round": round_num,
            "agent": agent.name,
            "role": agent.role,
            "content": content,
        })

        import re as _re
        if _re.search(r"\[NEED\s+@Human", content):
            self._handle_human_request(resp.message, round_num)

        # Surface scratchpad writes to the operator
        for key, _ in resp.scratchpad_writes:
            self.console.print(f"  [dim]📌 scratchpad ← {key} (by {agent.name})[/]")

        # Reactive turns for direct requests — service each [DIRECT @X] inline,
        # then clear them from the response so the caller's _pick_next_speaker
        # doesn't double-book the same agent for the very next turn. Previously
        # an emission like "...[DIRECT @Connector: ...]" would (1) fire a
        # reactive turn handled here AND (2) make _pick_next_speaker target
        # Connector again on its next iteration, producing two near-identical
        # Connector turns back-to-back.
        if resp.direct_requests:
            self._handle_direct_requests(resp, agent, round_num, is_final)
            resp.direct_requests = []

        if content.startswith("[ERROR]"):
            return "error"
        if "[COMPLETE]" in content and agent.role == "leader":
            return "complete"
        return "ok"

    # ── dynamic reactive turns ────────────────────────────

    def _handle_direct_requests(
        self,
        resp: AgentResponse,
        sender: Agent,
        round_num: int,
        is_final: bool,
    ) -> None:
        """When an agent emits [DIRECT @Name: ...], give that teammate an immediate turn."""
        for target_name, question in resp.direct_requests:
            target = self.agents.get(target_name)
            if not target or target_name == sender.name:
                continue

            self.console.print()
            self.console.print(
                f"  [dim]↳ {sender.name} → {target_name}:[/] [italic]{question[:80]}[/]"
            )

            self.bus.post(Message(
                sender=sender.name,
                content=question,
                msg_type=MessageType.DIRECT,
                recipient=target_name,
                round_num=round_num,
            ))

            reactive_prompt = (
                f"{sender.name} has just directed this question at you:\n\n"
                f"  \"{question}\"\n\n"
                f"Respond directly and specifically. Under 200 words unless depth is required. "
                f"You may also emit your own [DIRECT @Name: ...] if you need a teammate's "
                f"input to answer. End with [DONE]."
            )
            reactive = target.respond(
                reactive_prompt, round_num=round_num, is_final_round=is_final,
            )
            self._transcript.append({
                "round": round_num,
                "agent": target.name,
                "role": target.role,
                "content": f"[Reactive reply to {sender.name}]\n\n{reactive.message.content}",
            })

    # ── convergence detection ─────────────────────────────

    def _check_convergence(self, round_num: int) -> bool:
        """Detect whether critics/judges signal the work is done.

        Converged if EITHER:
        - Any critic/judge emits [APPROVED], OR
        - A critic rates the work "Exceptional" with no flagged remaining gaps.
        """
        for m in self.bus.get_round_messages(round_num):
            agent = self.agents.get(m.sender)
            if not agent or agent.role not in ("critic", "judge"):
                continue
            content = m.content.upper()
            if "[APPROVED]" in content:
                return True
            if "VERDICT: EXCEPTIONAL" in content or "EXCEPTIONAL" in content.split("\n")[0]:
                gaps = "REMAINING GAPS"
                if gaps not in content:
                    return True
                # Check if the gaps section effectively says "none"
                after = content.split(gaps, 1)[1][:200]
                if "NONE" in after or "NO REMAINING" in after:
                    return True
        return False

    # ── learning recap (pedagogical wrap-up) ──────────────

    def _render_learning_recap(
        self, team: TeamConfig, round_num: int | None = None,
    ) -> None:
        """After a deliberation, generate a compact 'Learning Recap' panel.

        Uses a fast Haiku call to distill: TL;DR, key concepts with plain
        definitions, 3 follow-up questions, and 3 real search-URL resources
        (Google Scholar / YouTube search / general web) the user can click
        to go deeper.  Search URLs avoid hallucination — actual videos and
        papers are rendered only if the user actually clicks through.

        ``round_num=None`` recaps the whole session (all rounds) — used by
        classic ``run()`` finalization. A specific round_num is used in chat.
        """
        if not _CLAUDE_PATH:
            return

        if round_num is None:
            # Whole-session recap: pull from all messages
            round_msgs = self.bus.get_all(limit=500)
            # Use the stored goal as the question
            question = self._goal or ""
        else:
            round_msgs = self.bus.get_round_messages(round_num)
            # First HUMAN message in this round is the question
            question = next(
                (m.content for m in round_msgs if m.msg_type == MessageType.HUMAN),
                "",
            )
        if not round_msgs:
            return
        transcript = "\n\n".join(
            f"[{m.sender}]: {m.content[:1800]}"
            for m in round_msgs
            if m.msg_type != MessageType.HUMAN
        )[:14000]

        prompt = (
            "You are generating a Learning Recap panel for someone who just watched a team of "
            "expert AI agents deliberate on their question. The recap must teach clearly WITHOUT "
            "dumbing down. Output PLAIN TEXT in EXACTLY this format (no markdown decoration, no "
            "extra commentary):\n\n"
            "TLDR: <one sentence answer in plain English, no jargon>\n\n"
            "KEY_CONCEPTS:\n"
            "<term 1> :: <one-sentence plain-English definition>\n"
            "<term 2> :: <one-sentence plain-English definition>\n"
            "<term 3> :: <one-sentence plain-English definition>\n"
            "<term 4> :: <one-sentence plain-English definition>  (optional)\n"
            "<term 5> :: <one-sentence plain-English definition>  (optional)\n\n"
            "FOLLOWUPS:\n"
            "- <one-sentence question the user could ask next to go deeper>\n"
            "- <another good follow-up>\n"
            "- <another good follow-up>\n\n"
            "READ:\n"
            "- <book or paper title> by <author/venue, year>\n"
            "- <another title> by <author/venue, year>\n\n"
            "WATCH:\n"
            "- <channel name>: <specific topic/video title>\n"
            "- <channel name>: <specific topic/video title>\n\n"
            "RULES:\n"
            "- Pull key concepts from what the agents actually discussed.\n"
            "- For READ: real authors/titles you're confident exist; avoid URLs (we'll build "
            "search URLs ourselves).\n"
            "- For WATCH: suggest real, authoritative channels (Veritasium, Kurzgesagt, PBS Eons, "
            "3Blue1Brown, SciShow, Closer to Truth, etc.) that have relevant content.\n"
            "- No paragraphs of explanation — just the structured output above.\n\n"
            f"USER QUESTION: {question}\n\nDELIBERATION:\n{transcript}"
        )

        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        try:
            result = subprocess.run(
                [_CLAUDE_PATH, "-p",
                 "--model", "haiku",
                 "--effort", "low",
                 "--no-session-persistence"],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=60,
            )
            raw = result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            raw = ""

        if not raw:
            return

        self._render_recap_panel(raw)

    def _render_recap_panel(self, raw: str) -> None:
        """Parse the Haiku recap output and render it as a styled panel."""
        import urllib.parse

        tldr = ""
        concepts: list[tuple[str, str]] = []
        followups: list[str] = []
        reads: list[str] = []
        watches: list[str] = []

        section = None
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            upper = stripped.split(":", 1)[0].upper()
            if upper == "TLDR":
                tldr = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
                section = "tldr"
            elif upper == "KEY_CONCEPTS":
                section = "concepts"
            elif upper == "FOLLOWUPS":
                section = "followups"
            elif upper == "READ":
                section = "read"
            elif upper == "WATCH":
                section = "watch"
            elif section == "concepts" and "::" in stripped:
                term, _, defn = stripped.partition("::")
                concepts.append((term.strip(), defn.strip()))
            elif section == "followups" and stripped.startswith("-"):
                followups.append(stripped.lstrip("- ").strip())
            elif section == "read" and stripped.startswith("-"):
                reads.append(stripped.lstrip("- ").strip())
            elif section == "watch" and stripped.startswith("-"):
                watches.append(stripped.lstrip("- ").strip())

        if not (tldr or concepts or followups):
            return

        # Cache concepts so _save_to_memory can include them in the stored entry
        self._last_recap_concepts = [{"term": t, "definition": d} for t, d in concepts[:8]]

        parts: list[str] = []

        if tldr:
            parts.append(f"[bold bright_white]TL;DR[/]\n{tldr}")

        if concepts:
            lines = [f"[bold bright_white]Key Concepts[/]"]
            for term, defn in concepts[:5]:
                lines.append(f"  [bold cyan]{term}[/] — {defn}")
            parts.append("\n".join(lines))

        if followups:
            lines = [f"[bold bright_white]Ask Next[/]"]
            for q in followups[:3]:
                lines.append(f"  [dim]›[/] {q}")
            parts.append("\n".join(lines))

        if reads:
            lines = [f"[bold bright_white]Read[/]"]
            for item in reads[:3]:
                query = urllib.parse.quote_plus(item[:100])
                url = f"https://scholar.google.com/scholar?q={query}"
                lines.append(f"  [green]•[/] {item}\n    [dim link={url}]{url}[/]")
            parts.append("\n".join(lines))

        if watches:
            lines = [f"[bold bright_white]Watch[/]"]
            for item in watches[:3]:
                query = urllib.parse.quote_plus(item[:100])
                url = f"https://www.youtube.com/results?search_query={query}"
                lines.append(f"  [red]▶[/] {item}\n    [dim link={url}]{url}[/]")
            parts.append("\n".join(lines))

        body_markup = "\n\n".join(parts)
        self.console.print()
        self.console.print(Panel(
            Text.from_markup(body_markup),
            title="[bold]\U0001f4d8 Learning Recap[/]",
            title_align="left",
            border_style="bright_blue",
            padding=(1, 2),
        ))

    # ── round summary ─────────────────────────────────────

    def _generate_and_store_round_summary(self, round_num: int) -> None:
        """Use a fast Haiku CLI call to distill a round; cache in bus for later rounds."""
        if not _CLAUDE_PATH:
            return

        round_msgs = self.bus.get_round_messages(round_num)
        if not round_msgs:
            return

        transcript = "\n\n".join(
            f"[{m.sender}]: {m.content[:2500]}" for m in round_msgs
        )[:15000]

        prompt = (
            "Summarize this multi-agent discussion round in 150-250 words for future context. "
            "Capture: key findings, factual claims with sources, disagreements, decisions, "
            "open questions. Do NOT add commentary. Be dense and specific.\n\n"
            f"{transcript}"
        )

        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        try:
            result = subprocess.run(
                [_CLAUDE_PATH, "-p",
                 "--model", "haiku",
                 "--effort", "low",
                 "--no-session-persistence"],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=45,
            )
            if result.returncode == 0 and result.stdout.strip():
                self.bus.set_round_summary(round_num, result.stdout.strip())
        except Exception:
            pass

    # ── parallel display header ───────────────────────────

    def _print_parallel_header(self, group: list[str]) -> None:
        names = ", ".join(group)
        self.console.print()
        self.console.print(
            f"  [dim]⚡ Parallel group:[/] [bold]{names}[/] [dim](running concurrently)[/]"
        )

    # ── prompt construction ───────────────────────────────

    def _build_prompt(
        self,
        agent: Agent,
        round_num: int,
        max_rounds: int,
        position_in_round: int = 0,
        is_last_in_round: bool = False,
    ) -> str:
        r = f"Round {round_num}/{max_rounds}."
        is_final_round = round_num == max_rounds

        teammates = [
            f"@{name} ({self.agents[name].role})"
            for name in self.agents
            if name != agent.name
        ]
        teammate_str = ", ".join(teammates)

        # ── LEADER ──
        if agent.role == "leader":
            if not is_last_in_round:
                if round_num == 1:
                    return (
                        f"{r} You are leading this team. Your teammates are: {teammate_str}. "
                        f"Review the PROJECT GOAL. Outline your approach and assign SPECIFIC "
                        f"tasks to each teammate by their EXACT name. For each assignment, "
                        f"specify: (1) what to deliver, (2) what depth is expected, (3) what "
                        f"sources to search for. Do NOT invent team members that don't exist. "
                        f"Under 250 words — clear direction, not an essay."
                    )
                return (
                    f"{r} Based on the team's work and feedback so far, identify:\n"
                    f"1. The strongest findings that should be preserved\n"
                    f"2. The 2-3 specific gaps or weaknesses to address this round\n"
                    f"3. Revised assignments for each teammate with clear expectations\n"
                    f"Under 250 words."
                )

            if is_final_round:
                return (
                    f"{r} FINAL ROUND. Write the FINAL DELIVERABLE.\n\n"
                    f"CRITICAL: Do NOT repeat data your team already presented — the reader has "
                    f"already seen it. Your job is to:\n"
                    f"1. Draw conclusions that emerge from COMBINING the team's work — insights "
                    f"none of them reached individually\n"
                    f"2. Resolve tensions between optimistic and critical perspectives with a "
                    f"clear, evidence-based judgment\n"
                    f"3. Present a decision framework with specific criteria and thresholds\n"
                    f"4. End with 'WHAT TO DO THIS WEEK' — 3-5 concrete first actions with "
                    f"owners, timelines, and measurable success criteria\n\n"
                    f"Reference team findings briefly ('as the Analyst showed, X costs Y') but "
                    f"never restate their full analysis. Be specific with numbers. "
                    f"End with [COMPLETE]."
                )
            return (
                f"{r} Synthesize the team's contributions into a cohesive working draft.\n\n"
                f"RULES: Do NOT recap who said what. Do NOT restate data already presented. "
                f"Instead:\n"
                f"- Identify patterns across contributions that no single agent surfaced\n"
                f"- Resolve contradictions with evidence-based judgment calls\n"
                f"- Note the 1-2 specific gaps remaining for next round\n"
                f"Under 600 words. If the result is strong enough, say [COMPLETE]."
            )

        # ── WORKERS ──
        if agent.role in ("worker", "debater"):
            if is_final_round:
                return (
                    f"{r} FINAL ROUND. This is your last chance to deliver. Produce your "
                    f"absolute best work — the kind you'd put your name on in a professional "
                    f"publication. Incorporate all feedback from previous rounds. Every claim "
                    f"must be sourced. Every recommendation must be specific and actionable. "
                    f"NEVER repeat information another agent already covered — reference it "
                    f"and build on it. Search the web for any data gaps identified in review. "
                    f"New insights and evidence only."
                )
            if round_num == 1:
                return (
                    f"{r} The leader has outlined a plan. Deliver your contribution NOW.\n\n"
                    f"REQUIREMENTS:\n"
                    f"- Search the web for current, authoritative data before writing\n"
                    f"- Produce real, detailed, high-quality content — not a description of "
                    f"what you would do. Actually DO it.\n"
                    f"- Every factual claim needs a source with URL\n"
                    f"- Be concrete: specific numbers, names, dates, examples\n"
                    f"- Go deep on your area of expertise. Depth beats breadth.\n"
                    f"- Do NOT repeat information other agents have already provided."
                )
            return (
                f"{r} Incorporate feedback and improve your contribution.\n\n"
                f"REQUIREMENTS:\n"
                f"- Address every specific critique from the reviewer\n"
                f"- Search for additional evidence to fill gaps identified in review\n"
                f"- Produce actual content, not meta-commentary about process\n"
                f"- Only include NEW material — never restate what you or others said\n"
                f"- If the reviewer questioned a source, find a better one"
            )

        # ── CRITICS ──
        if agent.role in ("critic", "judge"):
            if is_final_round:
                return (
                    f"{r} FINAL ROUND. Deliver your final assessment.\n\n"
                    f"Structure:\n"
                    f"1. VERDICT: Overall quality rating (Exceptional / Strong / Adequate / Weak) "
                    f"with a one-sentence justification\n"
                    f"2. STRONGEST ELEMENTS: What should absolutely be preserved (2-3 items)\n"
                    f"3. REMAINING GAPS: The 1-2 most impactful improvements still possible\n"
                    f"4. If you spot any unsourced claims, verify them with a quick web search\n\n"
                    f"Do NOT ask for more rounds. Say [APPROVED]. Under 300 words."
                )
            return (
                f"{r} Review the team's work with the rigor of a top-tier peer reviewer.\n\n"
                f"Structure your review:\n"
                f"1. EVIDENCE AUDIT: Flag any statistics without sources, confidence levels, "
                f"or baselines. Spot-check 1-2 key claims with your own web search.\n"
                f"2. LOGIC CHECK: Flag reasoning gaps, unsupported leaps, or strawman arguments\n"
                f"3. CONSTRUCTIVE FIXES: For each problem, give a specific fix direction\n"
                f"4. STRENGTHS: Acknowledge what's genuinely strong — specifics, not flattery\n\n"
                f"Limit to the 3-4 most impactful improvements. Under 400 words."
            )

        return f"{r} Contribute to the team's goal."

    # ── human interaction ─────────────────────────────────

    def _handle_human_request(self, msg: Message, round_num: int) -> None:
        # Extract the question text from the [NEED @Human: ...] block so the
        # operator can see what was actually asked (display-strip hides the
        # token from the agent panel, so we re-surface it here).
        import re as _re
        # Accept colon, em-dash, or whitespace after "@Human"
        match = _re.search(
            r"\[NEED\s+@Human[:\-—\s]+(.*?)\]", msg.content, _re.DOTALL,
        )
        question = match.group(1).strip() if match else ""

        self.console.print()
        self.console.print(
            f"  [bold yellow]\U0001f4ac {msg.sender} needs your input[/]"
        )
        if question:
            self.console.print(f"  [yellow]›[/] {question}")
        self.console.print(
            "  [dim](type anything to redirect, or 'continue' to keep going)[/]"
        )
        if self.narrator:
            self.narrator.narrate_system(
                f"{msg.sender} is asking: {question}" if question
                else f"{msg.sender} is requesting your input.",
            )
            self.narrator.wait_until_done()

        response = Prompt.ask("  [bold]Your response[/]")
        if response.strip():
            self.bus.post(Message(
                sender="Human",
                content=response,
                msg_type=MessageType.HUMAN,
                round_num=round_num,
            ))

    def _between_rounds(self, team: TeamConfig, round_num: int) -> str:
        self.console.print()
        self.console.print("  [dim]\u2500\u2500\u2500 Round complete \u2500\u2500\u2500[/]")
        self.console.print()
        self.console.print(
            "  [bold white][Enter][/] Continue    "
            "[bold white][a][/] Ask an agent    "
            "[bold white][s][/] Stop    "
            "[bold white][e][/] Export"
        )
        self.console.print("  [dim]Or type feedback to redirect the team[/]")
        self.console.print()

        if self.narrator:
            self.narrator.narrate_system("Round complete. Awaiting your direction.")
            self.narrator.wait_until_done()

        choice = Prompt.ask("  [bold]>[/]", default="continue")
        low = choice.lower().strip()

        if low in ("c", "continue", ""):
            return "continue"
        if low in ("s", "stop", "q", "quit", "exit"):
            return "stop"
        if low == "e":
            path = self._export_session()
            self.console.print(f"  [bold green]\u2713 Exported to {path}[/]")
            return "continue"
        if low == "a":
            self._ask_agent(team, round_num)
            return "continue"
        return choice

    def _ask_agent(self, team: TeamConfig, round_num: int) -> None:
        """Let the user ask a follow-up question to a specific agent."""
        self.console.print()
        agent_names = list(self.agents.keys())
        for i, name in enumerate(agent_names, 1):
            agent = self.agents[name]
            style = ROLE_STYLES.get(agent.role, {})
            color = style.get("color", "white")
            self.console.print(
                f"  [bold white][{i}][/]  [{color}]{name}[/] [dim]({agent.role})[/]"
            )

        self.console.print()
        try:
            idx = IntPrompt.ask(
                "  Who do you want to ask",
                choices=[str(i) for i in range(1, len(agent_names) + 1)],
            )
        except KeyboardInterrupt:
            return

        agent_name = agent_names[idx - 1]
        agent = self.agents[agent_name]

        self.console.print()
        question = Prompt.ask(f"  [bold]Question for {agent_name}[/]")
        if not question.strip():
            return

        self.bus.post(Message(
            sender="Human",
            content=f"@{agent_name}: {question}",
            msg_type=MessageType.HUMAN,
            round_num=round_num,
        ))

        prompt = (
            f"The human operator has asked you a direct question: {question}\n\n"
            f"Answer thoroughly using your expertise. Search the web if needed. "
            f"This is a follow-up, so reference your earlier work where relevant."
        )
        resp = agent.respond(prompt, round_num=round_num, is_final_round=False)
        self._transcript.append({
            "round": round_num,
            "agent": agent_name,
            "role": agent.role,
            "content": f"[Follow-up Q: {question}]\n\n{resp.message.content}",
        })

    def _end_session(self, goal: str, team: TeamConfig, round_num: int) -> None:
        """End-of-session: show stats, offer export/follow-up."""
        self._print_session_stats()
        self.console.print()
        self.console.print(
            "  [bold white][Enter][/] Done    "
            "[bold white][e][/] Export session    "
            "[bold white][a][/] Ask an agent    "
            "[bold white][f][/] Follow up"
        )
        self.console.print()

        choice = Prompt.ask("  [bold]>[/]", default="done")
        low = choice.lower().strip()

        if low == "e":
            path = self._export_session()
            self.console.print(f"  [bold green]\u2713 Exported to {path}[/]")
            self._end_session(goal, team, round_num)
            return
        if low == "a":
            self._ask_agent(team, round_num)
            self._end_session(goal, team, round_num)
            return
        if low == "f" or (low not in ("d", "done", "")):
            direction = low if low != "f" else ""
            if low == "f":
                direction = Prompt.ask("  [bold]New direction[/]")
            elif low not in ("d", "done", ""):
                direction = choice
            if direction.strip():
                self.bus.post(Message(
                    sender="Human",
                    content=direction,
                    msg_type=MessageType.HUMAN,
                    round_num=round_num,
                ))
                self._print_round(round_num + 1, team.max_rounds + 1)
                for agent_name in team.round_order:
                    agent = self.agents[agent_name]
                    prompt = (
                        f"Round {round_num + 1}. The human has provided new direction. "
                        f"Review their input and adapt your contribution accordingly."
                    )
                    resp = agent.respond(
                        prompt, round_num=round_num + 1, is_final_round=True
                    )
                    self._transcript.append({
                        "round": round_num + 1,
                        "agent": agent_name,
                        "role": agent.role,
                        "content": resp.message.content,
                    })
                    if "[COMPLETE]" in resp.message.content and agent.role == "leader":
                        self._print_complete()
                        break
                self._end_session(goal, team, round_num + 1)
                return

        self._print_done()

    # ── session export ────────────────────────────────────

    def _export_session(self) -> str:
        """Save the full session transcript to a markdown file."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        team_slug = (
            self._team.name if self._team else "session"
        ).lower().replace(" ", "_")
        filename = f"agent_forge_{team_slug}_{ts}.md"

        lines = [
            f"# Agent Forge Session — {self._team.name if self._team else 'Unknown'}",
            "",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"**Goal:** {self._goal}",
        ]
        if self._team:
            agents_str = ", ".join(
                a.name + " (" + a.role + ")" for a in self._team.agents
            )
            lines.append(f"**Team:** {agents_str}")
            lines.append(f"**Max Rounds:** {self._team.max_rounds}")
        elapsed = _time.time() - self._start_time
        mins, secs = divmod(int(elapsed), 60)
        lines.append(f"**Duration:** {mins}m {secs}s")
        lines += ["", "---", ""]

        current_round = -1
        for entry in self._transcript:
            if entry["round"] != current_round:
                current_round = entry["round"]
                lines += [f"## Round {current_round}", ""]

            lines.append(f"### {entry['agent']} ({entry['role']})")
            lines.append("")
            lines.append(entry["content"])
            lines.append("")
            lines.append("---")
            lines.append("")

        path = os.path.join(os.getcwd(), filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return path

    # ── display ───────────────────────────────────────────

    def _print_assembly(self, team: TeamConfig) -> None:
        """Animated team assembly — agents appear one by one."""
        self.console.print()
        self.console.print(Panel(
            f"  {team.icon} [bold]{team.name}[/]\n  [dim]{team.description}[/]",
            border_style="bright_blue",
            title="[bold]Assembling Team[/]",
            padding=(1, 1),
        ))

        for ac in team.agents:
            _time.sleep(0.12)
            style = ROLE_STYLES.get(ac.role, {})
            icon = ac.icon or style.get("icon", "\U0001f916")
            color = style.get("color", "white")
            self.console.print(
                f"  {icon} [{color}]{ac.name}[/] [dim]({ac.role})[/]"
            )

        _time.sleep(0.15)
        self.console.print()
        self.console.print("  [bold green]\u2713 Team ready[/]")
        self.console.print()

    def _print_agent_position(
        self, pos: int, total: int, name: str, role: str
    ) -> None:
        """Show agent position within the round."""
        pips = "\u25cf " * pos + "\u25cb " * (total - pos)
        color = ROLE_STYLES.get(role, {}).get("color", "white")
        self.console.print(
            f"  [dim]{pips}[/] [dim]({pos}/{total})[/]"
        )

    def _print_round(self, num: int, total: int) -> None:
        """Round header with visual progress bar."""
        self.console.print()

        # Progress bar
        bar_width = 30
        filled = int(bar_width * num / total)
        bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
        pct = int(num / total * 100)
        self.console.print(f"  [bright_blue]{bar}[/] [bold]{pct}%[/]")

        self.console.rule(
            f"[bold bright_white] Round {num}/{total} [/]",
            style="bright_blue",
        )

    def _print_round_recap(self, round_num: int) -> None:
        """Summary table of what each agent contributed this round."""
        entries = [e for e in self._transcript if e["round"] == round_num]
        if not entries:
            return

        table = Table(
            show_header=False,
            box=rich.box.SIMPLE,
            padding=(0, 1),
            pad_edge=True,
        )
        table.add_column("agent", style="bold", width=18)
        table.add_column("summary", style="dim", ratio=1)

        for entry in entries:
            summary = self._extract_summary(entry["content"])
            color = ROLE_STYLES.get(entry["role"], {}).get("color", "white")
            table.add_row(
                f"[{color}]{entry['agent']}[/]",
                summary,
            )

        self.console.print()
        self.console.print(Panel(
            table,
            title=f"[bold bright_blue]Round {round_num} Recap[/]",
            border_style="dim",
            padding=(0, 1),
        ))

    def _extract_summary(self, text: str) -> str:
        """Pull the first meaningful sentence from agent output."""
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("#") or line.startswith("[") or line.startswith("---"):
                continue
            if line.startswith("Round ") or line.startswith("@") or line.startswith("**"):
                continue
            if len(line) > 80:
                return line[:77] + "..."
            return line
        return "..."

    def _print_session_stats(self) -> None:
        """Show session stats at the end."""
        elapsed = _time.time() - self._start_time
        mins, secs = divmod(int(elapsed), 60)

        agent_count = len(self.agents)
        turn_count = len(self._transcript)
        rounds = max((e["round"] for e in self._transcript), default=0)

        stats = Text()
        stats.append(f"  Agents: {agent_count}", style="dim")
        stats.append(f"  |  Rounds: {rounds}", style="dim")
        stats.append(f"  |  Turns: {turn_count}", style="dim")
        stats.append(f"  |  Duration: {mins}m {secs}s", style="dim")

        self.console.print()
        self.console.print(stats)

    def _print_complete(self) -> None:
        self.console.print()
        self.console.print(Panel(
            "[bold bright_green]\u2705 Project Complete[/]",
            border_style="green",
        ))
        if self.narrator:
            self.narrator.narrate_system("Project complete. All agents have finished.")
            self.narrator.wait_until_done()

    def _print_done(self) -> None:
        self.console.print()
        self.console.print(
            "  [dim]Session ended. Thanks for using Agent Forge.[/]\n"
        )
        if self.narrator:
            self.narrator.narrate_system("Session ended. Thanks for using Agent Forge.")
            self.narrator.wait_until_done()
