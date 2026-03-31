#!/usr/bin/env python3
"""
Agent Forge — Multi-agent orchestration engine.

Assemble AI teams that collaborate, debate, and create.
"""

import argparse
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

from agent_forge import Orchestrator, TEAMS, CATEGORIES, TeamCategory
from agent_forge.teams import TeamConfig
from agent_forge.narrator import Narrator


console = Console(force_terminal=True)


def print_banner() -> None:
    """Animated banner with staggered reveal."""
    console.print()

    # Title panel
    banner = Text()
    banner.append("\u2592\u2592\u2592 ", style="bright_red")
    banner.append("AGENT FORGE", style="bold bright_white")
    banner.append(" \u2592\u2592\u2592", style="bright_red")
    console.print(Panel(banner, border_style="bright_red", padding=(1, 2)))

    # Staggered info lines — "boot-up" feel
    info_lines = [
        ("    [dim]Multi-Agent Orchestration Engine[/]", 0.06),
        ("    [dim italic]v0.5.0[/]", 0.06),
        ("    [dim]Opus 4.6 \u00b7 Extended Thinking \u00b7 Web Search \u00b7 Voice[/]", 0.06),
        (f"    [dim]{len(TEAMS)} specialized teams across {len(CATEGORIES)} domains[/]", 0.06),
    ]
    for line, delay in info_lines:
        time.sleep(delay)
        console.print(line)


def print_categories() -> None:
    """Show the domain category menu."""
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
    console.print(f"  [bold white][{len(CATEGORIES) + 1}][/]  [dim]Show all teams[/]")
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

    # Agent roster preview
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
    table.add_column("cat", style="dim", width=14)
    table.add_column("desc", style="dim")

    for i, team in enumerate(TEAMS, 1):
        table.add_row(
            f"[{i}]", team.icon, team.name, team.category, team.description
        )

    console.print(table)
    console.print()


def select_team() -> TeamConfig:
    """Category browser -> team selector."""
    while True:
        print_categories()

        choices = [str(i) for i in range(1, len(CATEGORIES) + 2)]
        cat_idx = IntPrompt.ask("  Select a domain", choices=choices)

        if cat_idx == len(CATEGORIES) + 1:
            print_all_teams()
            team_idx = IntPrompt.ask(
                "  Select a team",
                choices=[str(i) for i in range(1, len(TEAMS) + 1)],
            )
            return TEAMS[team_idx - 1]

        cat = CATEGORIES[cat_idx - 1]
        print_teams_in_category(cat)

        team_choices = [str(i) for i in range(1, len(cat.teams) + 1)] + ["0"]
        console.print("  [dim][0] Back to domains[/]")
        console.print()
        team_idx = IntPrompt.ask("  Select a team", choices=team_choices)

        if team_idx == 0:
            continue

        return cat.teams[team_idx - 1]


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


def read_goal(team_name: str) -> str:
    """Read a goal with multi-line support so long prompts don't truncate.

    Type normally for a short goal (single Enter submits).
    For longer goals, type multiple lines and press Enter on an empty line to submit.
    """
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
            # First line empty — keep waiting
            continue
        lines.append(line)

    return " ".join(lines)


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


def main() -> None:
    args = parse_args()

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
    if args.team:
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
        console.print()
        if cli_goal:
            goal = cli_goal
            console.print(f"  [bold]Goal:[/] {goal[:120]}{'...' if len(goal) > 120 else ''}")
        else:
            goal = read_goal(team_config.name)

        if not goal.strip():
            console.print("  [red]No goal provided.[/]")
            continue

        # Run
        orchestrator = Orchestrator(narrate_mode=narration_mode)
        orchestrator.run(goal=goal, team=team_config)

        # If everything came from CLI, exit after one run
        if cli_team and cli_goal:
            break

        # Again?
        cli_goal = None  # clear so next loop prompts interactively
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
