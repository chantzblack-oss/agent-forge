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
        """Execute a full multi-agent session."""
        self.bus = MessageBus()
        self.agents = {}
        self._transcript = []
        self._goal = goal
        self._team = team
        self._start_time = _time.time()
        self.narrator = Narrator(mode=self.narrate_mode)

        try:
            self._run_session(goal, team)
        finally:
            if self.narrator:
                self.narrator.shutdown()

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
                self._end_session(goal, team, round_num)
                return
            if result == "error":
                self.console.print("\n  [bold red]Stopping due to error.[/]")
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

        while turns_used < team.max_deliberation_turns:
            agent = self.agents[next_speaker]
            self._print_turn_header(turns_used + 1, team.max_deliberation_turns, agent)

            prompt = self._build_deliberation_prompt(
                agent, round_num, team.max_rounds,
                turn_number=turns_used + 1,
                max_turns=team.max_deliberation_turns,
                is_opening=turns_used == 0,
            )

            # Override the model's max_tokens for this short turn
            original_max = agent.config.max_tokens
            agent.config.max_tokens = turn_budget
            try:
                resp = agent.respond(prompt, round_num=round_num, is_final_round=is_final)
            finally:
                agent.config.max_tokens = original_max

            status = self._post_agent(resp, agent, round_num, is_final)
            turns_used += 1

            if status in ("complete", "error"):
                return status

            last_speaker = next_speaker
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
        r = f"Deliberation — turn {turn_number}/{max_turns} of round {round_num}/{max_rounds}."
        if is_opening and agent.role == "leader":
            return (
                f"{r} You are OPENING the deliberation.  Review the PROJECT GOAL and "
                f"frame the question sharply.  Then call on ONE teammate by name using "
                f"[DIRECT @Name: specific question] to kick things off.  Under 150 words."
            )

        base = (
            f"{r} This is a LIVE conversation — not a report. Keep your turn to "
            f"~150 words.  Lead with your single best point.  "
            f"If you want a specific teammate to respond, use [DIRECT @Name: question] "
            f"at the end of your turn (you can also @mention them inline).  "
            f"Ask hard questions.  Cite sources briefly with URLs.  End with [DONE]."
        )

        if agent.role == "leader":
            return (
                f"{base}  As leader, moderate: if the discussion is circling, redirect; "
                f"if it's converging, test the consensus; if it's time to close, say [COMPLETE] "
                f"with a one-paragraph decision."
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

        if "[NEED @Human" in content:
            self._handle_human_request(resp.message, round_num)

        # Surface scratchpad writes to the operator
        for key, _ in resp.scratchpad_writes:
            self.console.print(f"  [dim]📌 scratchpad ← {key} (by {agent.name})[/]")

        # Reactive turns for direct requests
        if resp.direct_requests:
            self._handle_direct_requests(resp, agent, round_num, is_final)

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
        self.console.print()
        self.console.print(
            f"  [bold yellow]\U0001f4ac {msg.sender} needs your input[/]"
        )
        if self.narrator:
            self.narrator.narrate_system(
                f"{msg.sender} is requesting your input.",
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
