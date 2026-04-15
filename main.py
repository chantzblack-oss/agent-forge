#!/usr/bin/env python3
"""
Agent Forge — Multi-agent orchestration engine.

Assemble AI teams that collaborate, debate, and create.
"""

import argparse
import random
import sys
import time

# Ensure UTF-8 output on Windows for emoji support
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt
from rich.table import Table
from rich.text import Text
import rich.box

from agent_forge import Orchestrator, TEAMS, CATEGORIES, TeamCategory
from agent_forge.teams import TeamConfig
from agent_forge.agent import AgentConfig, ROLE_STYLES
from agent_forge.narrator import Narrator


console = Console(force_terminal=True)


# ── Banner ────────────────────────────────────────────────

def print_banner() -> None:
    """Animated banner with staggered reveal."""
    console.print()

    banner = Text()
    banner.append("\u2592\u2592\u2592 ", style="bright_red")
    banner.append("AGENT FORGE", style="bold bright_white")
    banner.append(" \u2592\u2592\u2592", style="bright_red")
    console.print(Panel(banner, border_style="bright_red", padding=(1, 2)))

    info_lines = [
        ("    [dim]Multi-Agent Orchestration Engine[/]", 0.06),
        ("    [dim italic]v0.6.0[/]", 0.06),
        ("    [dim]Opus 4.6 \u00b7 Extended Thinking \u00b7 Web Search \u00b7 Voice[/]", 0.06),
        (f"    [dim]{len(TEAMS)} specialized teams across {len(CATEGORIES)} domains[/]", 0.06),
    ]
    for line, delay in info_lines:
        time.sleep(delay)
        console.print(line)


# ── Domain / Team Selection ───────────────────────────────

def print_categories() -> None:
    """Show the domain category menu with extra options."""
    console.print()
    console.print("  [bold bright_white]Choose a Domain[/]")
    console.print()
    for i, cat in enumerate(CATEGORIES, 1):
        team_names = ", ".join(t.name for t in cat.teams)
        console.print(
            f"  [bold white][{i}][/]  {cat.icon} [bold]{cat.name}[/]  "
            f"[dim]({len(cat.teams)} teams: {team_names})[/]"
        )
    console.print()
    n = len(CATEGORIES)
    console.print(f"  [bold white][{n + 1}][/]  \U0001f4cb [dim]Show all teams[/]")
    console.print(f"  [bold white][{n + 2}][/]  \U0001f527 [bold]Custom Team Builder[/]")
    console.print(f"  [bold white][{n + 3}][/]  \U0001f3b2 [bold]Random Team[/]")
    console.print()


def print_teams_in_category(cat: TeamCategory) -> None:
    """Show teams within a category with agent roster preview."""
    console.print()
    console.print(f"  {cat.icon} [bold bright_white]{cat.name}[/]")
    console.print()

    table = Table(
        show_header=False,
        box=None,
        padding=(0, 2),
        pad_edge=True,
    )
    table.add_column("num", style="bold bright_white", width=4, justify="right")
    table.add_column("icon", width=3)
    table.add_column("name", style="bold", width=22)
    table.add_column("desc", style="dim")

    for i, team in enumerate(cat.teams, 1):
        table.add_row(f"[{i}]", team.icon, team.name, team.description)

    console.print(table)
    console.print()

    for team in cat.teams:
        agents_str = "  ".join(
            f"{a.icon} {a.name}[dim]({a.role})[/]" for a in team.agents
        )
        console.print(f"    [dim]{team.name}:[/] {agents_str}")
    console.print()


def print_all_teams() -> None:
    """Flat list of all teams across all categories."""
    console.print()
    console.print("  [bold bright_white]All Teams[/]")
    console.print()

    table = Table(
        show_header=False,
        box=None,
        padding=(0, 2),
        pad_edge=True,
    )
    table.add_column("num", style="bold bright_white", width=4, justify="right")
    table.add_column("icon", width=3)
    table.add_column("name", style="bold", width=22)
    table.add_column("cat", style="dim", width=18)
    table.add_column("desc", style="dim")

    for i, team in enumerate(TEAMS, 1):
        table.add_row(
            f"[{i}]", team.icon, team.name, team.category, team.description
        )

    console.print(table)
    console.print()


def select_team() -> TeamConfig:
    """Category browser -> team selector with custom team builder."""
    while True:
        print_categories()

        n = len(CATEGORIES)
        choices = [str(i) for i in range(1, n + 4)]
        cat_idx = IntPrompt.ask("  Select", choices=choices)

        # Show all teams
        if cat_idx == n + 1:
            print_all_teams()
            team_idx = IntPrompt.ask(
                "  Select a team",
                choices=[str(i) for i in range(1, len(TEAMS) + 1)],
            )
            return TEAMS[team_idx - 1]

        # Custom team builder
        if cat_idx == n + 2:
            custom = build_custom_team()
            if custom:
                return custom
            continue

        # Random team
        if cat_idx == n + 3:
            team = random.choice(TEAMS)
            console.print(f"\n  [bold bright_white]\U0001f3b2 Random pick: {team.icon} {team.name}[/]")
            return team

        cat = CATEGORIES[cat_idx - 1]
        print_teams_in_category(cat)

        team_choices = [str(i) for i in range(1, len(cat.teams) + 1)] + ["0"]
        console.print("  [dim][0] Back to domains[/]")
        console.print()
        team_idx = IntPrompt.ask("  Select a team", choices=team_choices)

        if team_idx == 0:
            continue

        return cat.teams[team_idx - 1]


# ── Agent Profile Browser ────────────────────────────────

def show_agent_profiles(team: TeamConfig) -> None:
    """Display detailed agent profiles for a team."""
    console.print()
    console.print(Panel(
        f"  {team.icon} [bold]{team.name}[/] — Agent Roster",
        border_style="bright_blue",
    ))

    for ac in team.agents:
        style = ROLE_STYLES.get(ac.role, {})
        color = style.get("color", "white")
        icon = ac.icon or style.get("icon", "\U0001f916")

        console.print()
        console.print(f"  {icon} [{color}][bold]{ac.name}[/][/]  [dim]({ac.role})[/]")
        if ac.tagline:
            console.print(f"     [italic]\"{ac.tagline}\"[/]")
        # Show first 200 chars of personality
        preview = ac.personality[:200].replace("\n", " ")
        if len(ac.personality) > 200:
            preview += "..."
        console.print(f"     [dim]{preview}[/]")

    console.print()


# ── Quick-Start Goals ─────────────────────────────────────

def select_goal(team: TeamConfig) -> str:
    """Goal selection — quick-start presets OR custom input."""
    has_goals = bool(team.quickstart_goals)

    if has_goals:
        console.print()
        console.print(f"  [bold]Goal for {team.name}[/]")
        console.print()
        console.print("  [bold white][Q][/]  [bold bright_cyan]Quick Start[/]  [dim]— pick a pre-built goal[/]")
        console.print("  [bold white][C][/]  [dim]Custom[/]        [dim]— write your own goal[/]")
        console.print("  [bold white][P][/]  [dim]Profiles[/]      [dim]— view agent details[/]")
        console.print()

        choice = Prompt.ask(
            "  [bold]>[/]",
            choices=["q", "c", "p", "Q", "C", "P"],
            default="q",
        ).lower()

        if choice == "p":
            show_agent_profiles(team)
            return select_goal(team)  # recurse back to goal selection

        if choice == "q":
            return pick_quickstart_goal(team)

    return read_goal(team.name)


def pick_quickstart_goal(team: TeamConfig) -> str:
    """Let the user pick from pre-built goals or shuffle for a random one."""
    console.print()
    console.print(f"  [bold bright_cyan]Quick Start Goals[/]  [dim]— {team.icon} {team.name}[/]")
    console.print()

    for i, goal in enumerate(team.quickstart_goals, 1):
        # Truncate long goals for display
        display = goal[:90] + "..." if len(goal) > 90 else goal
        console.print(f"  [bold white][{i}][/]  {display}")

    console.print()
    console.print(f"  [bold white][R][/]  \U0001f3b2 [dim]Random pick[/]")
    console.print(f"  [bold white][C][/]  [dim]Write custom goal instead[/]")
    console.print()

    valid = [str(i) for i in range(1, len(team.quickstart_goals) + 1)] + ["r", "c", "R", "C"]
    choice = Prompt.ask("  [bold]>[/]", choices=valid)

    if choice.lower() == "r":
        goal = random.choice(team.quickstart_goals)
        console.print(f"  [dim]\u2713 Random goal selected[/]")
        return goal
    if choice.lower() == "c":
        return read_goal(team.name)

    return team.quickstart_goals[int(choice) - 1]


def read_goal(team_name: str) -> str:
    """Read a goal with multi-line support."""
    console.print(f"  [bold]Goal for {team_name}[/]")
    console.print("  [dim]Type your goal below. Press Enter twice to submit.[/]")
    console.print()

    lines: list[str] = []
    while True:
        try:
            prefix = "  > " if not lines else "  . "
            line = console.input(f"  [dim]{prefix.strip()}[/] ")
        except (EOFError, KeyboardInterrupt):
            break
        if line == "" and lines:
            break
        if line == "" and not lines:
            continue
        lines.append(line)

    return " ".join(lines)


# ── Custom Team Builder ───────────────────────────────────

def build_custom_team() -> TeamConfig | None:
    """Let users assemble a custom team from agents across all teams."""
    console.print()
    console.print(Panel(
        "  \U0001f527 [bold]Custom Team Builder[/]\n"
        "  [dim]Mix agents from any team to create your own squad[/]",
        border_style="bright_magenta",
    ))

    # Build a flat roster of all unique agents
    all_agents: list[tuple[AgentConfig, str]] = []  # (agent, source_team_name)
    seen_names: set[str] = set()
    for team in TEAMS:
        for ac in team.agents:
            if ac.name not in seen_names:
                all_agents.append((ac, team.name))
                seen_names.add(ac.name)

    # Group by role for easier browsing
    role_groups: dict[str, list[tuple[int, AgentConfig, str]]] = {}
    for idx, (ac, src) in enumerate(all_agents):
        role_groups.setdefault(ac.role, []).append((idx, ac, src))

    # Show agents grouped by role
    console.print()
    role_order = ["leader", "worker", "critic", "debater", "judge", "synthesizer"]
    flat_index: list[tuple[AgentConfig, str]] = []

    for role in role_order:
        if role not in role_groups:
            continue
        style = ROLE_STYLES.get(role, {})
        color = style.get("color", "white")
        console.print(f"  [{color}]── {role.upper()}S ──[/]")

        for _, ac, src in role_groups[role]:
            n = len(flat_index) + 1
            icon = ac.icon or style.get("icon", "\U0001f916")
            tagline_str = f"  [dim italic]{ac.tagline}[/]" if ac.tagline else ""
            console.print(
                f"  [bold white][{n:2d}][/]  {icon} [{color}]{ac.name}[/]  "
                f"[dim]from {src}[/]{tagline_str}"
            )
            flat_index.append((ac, src))

    # Selection
    console.print()
    console.print("  [dim]Pick 3-6 agents by number, separated by commas.[/]")
    console.print("  [dim]You need at least one leader. Example: 1, 5, 12, 18, 23[/]")
    console.print()

    try:
        raw = Prompt.ask("  [bold]Agents[/]")
    except (EOFError, KeyboardInterrupt):
        return None

    if not raw.strip():
        return None

    # Parse selection
    try:
        indices = [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        console.print("  [red]Invalid input — enter numbers separated by commas.[/]")
        return None

    if len(indices) < 3 or len(indices) > 6:
        console.print("  [red]Pick between 3 and 6 agents.[/]")
        return None

    selected: list[AgentConfig] = []
    for idx in indices:
        if idx < 1 or idx > len(flat_index):
            console.print(f"  [red]Invalid agent number: {idx}[/]")
            return None
        selected.append(flat_index[idx - 1][0])

    # Verify at least one leader
    has_leader = any(a.role == "leader" for a in selected)
    if not has_leader:
        console.print("  [yellow]No leader selected — promoting first agent to leader role.[/]")
        # Create a copy with leader role
        first = selected[0]
        selected[0] = AgentConfig(
            name=first.name,
            role="leader",
            personality=first.personality,
            model=first.model,
            temperature=first.temperature,
            icon=first.icon,
            max_tokens=first.max_tokens,
            tagline=first.tagline,
        )

    # Name the team
    console.print()
    team_name = Prompt.ask("  [bold]Name your team[/]", default="Custom Squad")

    # Build round order: leader first, then workers/debaters, then critics, leader again
    leaders = [a.name for a in selected if a.role == "leader"]
    workers = [a.name for a in selected if a.role in ("worker", "debater", "synthesizer")]
    critics = [a.name for a in selected if a.role in ("critic", "judge")]
    round_order = leaders + workers + critics + leaders

    custom_team = TeamConfig(
        name=team_name,
        description="Custom-assembled team",
        icon="\U0001f527",
        category="Custom",
        agents=selected,
        round_order=round_order,
        max_rounds=3,
    )

    agents_str = ", ".join(f"{a.icon} {a.name}" for a in selected)
    console.print(f"\n  [bold green]\u2713 {team_name}[/]: {agents_str}")
    return custom_team


# ── Narration ─────────────────────────────────────────────

def select_narration_mode() -> str:
    console.print()
    console.print("  [bold]Voice Narration[/]")
    console.print()
    console.print(
        "  [bold white][1][/]  [dim]Off[/]          Text only, no audio"
    )
    console.print(
        "  [bold white][2][/]  [bold]Highlights[/]   Leader summaries + final deliverable"
    )
    console.print(
        "  [bold white][3][/]  [dim]Full[/]         Every agent speaks (summarized, not raw)"
    )
    console.print()

    choice = IntPrompt.ask(
        "  Narration mode",
        choices=["1", "2", "3"],
        default=2,
    )

    modes = {
        1: Narrator.MODE_OFF,
        2: Narrator.MODE_HIGHLIGHTS,
        3: Narrator.MODE_FULL,
    }
    mode = modes[choice]

    labels = {
        Narrator.MODE_OFF: "off",
        Narrator.MODE_HIGHLIGHTS: "highlights",
        Narrator.MODE_FULL: "full",
    }
    console.print(f"  [dim]\u2713 Narration: {labels[mode]}[/]")
    return mode


# ── CLI Args ──────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Agent Forge — Multi-agent orchestration engine",
    )
    parser.add_argument(
        "--goal", "-g",
        type=str,
        help="Goal for the team (skips interactive goal prompt)",
    )
    parser.add_argument(
        "--goal-file", "-gf",
        type=str,
        help="Read goal from a text file",
    )
    parser.add_argument(
        "--team", "-t",
        type=str,
        help="Team name to select (e.g. 'Code Shop', 'Research Lab')",
    )
    parser.add_argument(
        "--narration", "-n",
        choices=["off", "highlights", "full"],
        default=None,
        help="Voice narration mode",
    )
    parser.add_argument(
        "--list-teams",
        action="store_true",
        help="List all available teams and exit",
    )
    parser.add_argument(
        "--random",
        action="store_true",
        help="Pick a random team",
    )
    return parser.parse_args()


def find_team_by_name(name: str) -> TeamConfig | None:
    """Fuzzy-match a team by name (case-insensitive, partial match)."""
    low = name.lower()
    for team in TEAMS:
        if team.name.lower() == low:
            return team
    for team in TEAMS:
        if low in team.name.lower():
            return team
    return None


# ── Main ──────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    # Quick list mode
    if args.list_teams:
        for i, team in enumerate(TEAMS, 1):
            print(f"  {i:2d}. {team.icon} {team.name:<24s} [{team.category}]")
        return

    print_banner()

    time.sleep(0.1)
    console.print()
    console.print("  [dim]\u2713 Claude Code CLI detected[/]")

    # Narration mode
    narration_map = {
        "off": Narrator.MODE_OFF,
        "highlights": Narrator.MODE_HIGHLIGHTS,
        "full": Narrator.MODE_FULL,
    }
    if args.narration:
        narration_mode = narration_map[args.narration]
        console.print(f"  [dim]\u2713 Narration: {args.narration}[/]")
    else:
        narration_mode = select_narration_mode()

    # Pre-selected team from CLI
    cli_team: TeamConfig | None = None
    if args.random:
        cli_team = random.choice(TEAMS)
        console.print(f"  [dim]\u2713 Random team: {cli_team.icon} {cli_team.name}[/]")
    elif args.team:
        cli_team = find_team_by_name(args.team)
        if not cli_team:
            console.print(f"  [red]Team '{args.team}' not found.[/]")
            console.print("  [dim]Available: " + ", ".join(t.name for t in TEAMS) + "[/]")
            return

    # Pre-loaded goal from CLI
    cli_goal: str | None = None
    if args.goal_file:
        with open(args.goal_file, encoding="utf-8") as f:
            cli_goal = f.read().strip()
    elif args.goal:
        cli_goal = args.goal

    while True:
        team_config = cli_team or select_team()

        # Confirm selection
        console.print()
        console.print(
            f"  [bold bright_white]\u2713 {team_config.icon} {team_config.name}[/]"
        )
        agents_str = ", ".join(
            f"{a.icon} {a.name}" for a in team_config.agents
        )
        console.print(f"  [dim]Agents: {agents_str}[/]")
        console.print(f"  [dim]Rounds: {team_config.max_rounds}[/]")

        # Goal input
        if cli_goal:
            goal = cli_goal
            console.print()
            console.print(f"  [bold]Goal:[/] {goal[:120]}{'...' if len(goal) > 120 else ''}")
        else:
            goal = select_goal(team_config)

        if not goal.strip():
            console.print("  [red]No goal provided.[/]")
            continue

        # Confirm and run
        console.print()
        display_goal = goal[:100] + "..." if len(goal) > 100 else goal
        console.print(f"  [bold]Goal:[/] {display_goal}")

        # Run
        orchestrator = Orchestrator(narrate_mode=narration_mode)
        orchestrator.run(goal=goal, team=team_config)

        # If everything came from CLI, exit after one run
        if cli_team and cli_goal:
            break

        # Again?
        cli_goal = None
        console.print()
        again = Prompt.ask(
            "  [bold]Run another session?[/] [dim](y/n)[/]",
            default="n",
        )
        if again.lower().strip() not in ("y", "yes"):
            console.print()
            console.print("  [dim]See you next time.[/]\n")
            break


if __name__ == "__main__":
    main()
