"""Orchestrator — assembles teams, manages rounds, handles human-in-the-loop."""

from __future__ import annotations

import os
import time as _time
from datetime import datetime

from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt
from rich.table import Table
from rich.text import Text
import rich.box

from .agent import Agent, ROLE_STYLES
from .bus import MessageBus, Message, MessageType
from .narrator import Narrator
from .teams import TeamConfig


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

        # Execute rounds
        for round_num in range(1, team.max_rounds + 1):
            self._print_round(round_num, team.max_rounds)

            if self.narrator:
                self.narrator.narrate_system(
                    f"Round {round_num} of {team.max_rounds}. Begin.",
                )
                self.narrator.wait_until_done()

            last_positions: dict[str, int] = {}
            for i, name in enumerate(team.round_order):
                last_positions[name] = i

            for pos, agent_name in enumerate(team.round_order):
                agent = self.agents[agent_name]
                is_last = pos == last_positions[agent_name]

                # Show agent position in round
                self._print_agent_position(pos + 1, len(team.round_order), agent_name, agent.role)

                prompt = self._build_prompt(
                    agent, round_num, team.max_rounds,
                    position_in_round=pos,
                    is_last_in_round=is_last,
                )
                is_final = round_num == team.max_rounds
                msg = agent.respond(prompt, round_num=round_num, is_final_round=is_final)

                self._transcript.append({
                    "round": round_num,
                    "agent": agent_name,
                    "role": agent.role,
                    "content": msg.content,
                })

                if "[NEED @Human" in msg.content:
                    self._handle_human_request(msg, round_num)

                if "[COMPLETE]" in msg.content and agent.role == "leader":
                    self._print_round_recap(round_num)
                    self._print_complete()
                    self._end_session(goal, team, round_num)
                    return

                if msg.content.startswith("[ERROR]"):
                    self.console.print("\n  [bold red]Stopping due to error.[/]")
                    return

            # Round recap
            self._print_round_recap(round_num)

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
            msg = leader.respond(prompt, round_num=team.max_rounds, is_final_round=True)
            self._transcript.append({
                "round": team.max_rounds,
                "agent": leader.name,
                "role": leader.role,
                "content": msg.content,
            })
        self._print_complete()
        self._end_session(goal, team, team.max_rounds)

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
        msg = agent.respond(prompt, round_num=round_num, is_final_round=False)
        self._transcript.append({
            "round": round_num,
            "agent": agent_name,
            "role": agent.role,
            "content": f"[Follow-up Q: {question}]\n\n{msg.content}",
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
                    msg = agent.respond(
                        prompt, round_num=round_num + 1, is_final_round=True
                    )
                    self._transcript.append({
                        "round": round_num + 1,
                        "agent": agent_name,
                        "role": agent.role,
                        "content": msg.content,
                    })
                    if "[COMPLETE]" in msg.content and agent.role == "leader":
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
