#!/usr/bin/env python3
"""
Agent Forge — Multi-agent orchestration engine.

Assemble AI teams that collaborate, debate, and create.
"""

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
from rich.align import Align
import rich.box

from agent_forge import Orchestrator, TEAMS, CATEGORIES, TeamCategory, __version__
from agent_forge.teams import TeamConfig
from agent_forge.narrator import Narrator


console = Console(force_terminal=True)


# ── theme ────────────────────────────────────────────────

ACCENT = "bright_cyan"       # primary accent (titles, numbers)
MUTED = "grey58"             # secondary text
EMPH = "bold bright_white"   # active focus


# ── banner ───────────────────────────────────────────────

def print_banner() -> None:
    """Minimal, modern banner — one panel, three lines."""
    console.print()

    title = Text()
    title.append("agent", style=f"bold {ACCENT}")
    title.append(" ", style="")
    title.append("forge", style="bold white")
    subtitle = Text("multi-agent research teams that teach", style=f"italic {MUTED}")

    inner = Text()
    inner.append_text(title)
    inner.append("\n")
    inner.append_text(subtitle)

    console.print(Align.center(
        Panel(
            Align.center(inner),
            border_style=ACCENT,
            padding=(1, 4),
            width=52,
        )
    ))

    meta = Text()
    meta.append(f"  v{__version__}   ", style=MUTED)
    meta.append(f"{len(TEAMS)} teams", style=f"bold {ACCENT}")
    meta.append(f" · ", style=MUTED)
    meta.append(f"{len(CATEGORIES)} categories", style=f"bold {ACCENT}")
    meta.append(f"   · cross-model ready", style=MUTED)
    console.print(Align.center(meta))
    console.print()


# ── category + team selection ────────────────────────────

def print_categories() -> None:
    """Clean category menu — icon / name / teaser on one line each."""
    # Tiny descriptive teaser for each category (falls back to team names)
    TEASERS = {
        "Chat":            "open-ended learning & exploration",
        "Cross-Model":     "Claude + Gemini for maximum rigor",
        "Work":            "research · startup · code",
        "Healthcare":      "clinical · practice · behavioral",
        "Creative":        "story · writing · D&D · comedy",
        "Technical":       "security · data · systems",
        "Debate & Ideas":  "structured debate · philosophy",
        "Business":        "legal · finance · crisis comms",
    }
    console.print()
    console.print(f"  [{ACCENT}]┌[/] [bold]Pick a category[/]")
    console.print(f"  [{ACCENT}]│[/]")

    for i, cat in enumerate(CATEGORIES, 1):
        teaser = TEASERS.get(cat.name, f"{len(cat.teams)} teams")
        console.print(
            f"  [{ACCENT}]│[/]  [bold {ACCENT}]{i}[/]  {cat.icon}  "
            f"[bold]{cat.name:<16}[/]  [{MUTED}]{teaser}[/]"
        )

    console.print(f"  [{ACCENT}]│[/]")
    console.print(
        f"  [{ACCENT}]└[/]  [{MUTED}]{len(CATEGORIES) + 1}  ·  browse all teams[/]"
    )
    console.print()


def print_teams_in_category(cat: TeamCategory) -> None:
    """Show teams in a category — one clean line each with agent count."""
    console.print()
    console.print(f"  {cat.icon}  [bold bright_white]{cat.name}[/]")
    console.print()

    for i, team in enumerate(cat.teams, 1):
        agent_count = len(team.agents)
        rounds = team.max_rounds
        mode = []
        if getattr(team, "chat_mode", False):
            mode.append("chat")
        if getattr(team, "deliberation_mode", False):
            mode.append("deliberation")
        mode_str = " · ".join(mode) if mode else f"{rounds} round" + ("s" if rounds != 1 else "")

        console.print(
            f"  [bold {ACCENT}]{i}[/]  {team.icon}  [bold]{team.name}[/]"
        )
        console.print(
            f"     [{MUTED}]{team.description}[/]"
        )
        console.print(
            f"     [{MUTED}]{agent_count} agents · {mode_str}[/]"
        )
        console.print()

    console.print(f"  [{MUTED}]0  ·  back[/]")
    console.print()


def print_all_teams() -> None:
    """Clean flat list of every team."""
    console.print()
    console.print(f"  [bold bright_white]All teams[/]")
    console.print()

    table = Table(
        show_header=True,
        header_style=f"bold {MUTED}",
        box=rich.box.SIMPLE,
        padding=(0, 1),
        pad_edge=True,
    )
    table.add_column("#", style=f"bold {ACCENT}", width=3, justify="right")
    table.add_column("", width=3)
    table.add_column("Team", style="bold", min_width=22)
    table.add_column("Category", style=MUTED)
    table.add_column("Description", style=MUTED)

    for i, team in enumerate(TEAMS, 1):
        table.add_row(str(i), team.icon, team.name, team.category, team.description)

    console.print(table)
    console.print()


def select_team() -> TeamConfig:
    """Category browser → team selector."""
    while True:
        print_categories()

        choices = [str(i) for i in range(1, len(CATEGORIES) + 2)]
        cat_idx = IntPrompt.ask(f"  [{ACCENT}]→[/]", choices=choices, show_choices=False)

        if cat_idx == len(CATEGORIES) + 1:
            print_all_teams()
            team_idx = IntPrompt.ask(
                f"  [{ACCENT}]→[/] team",
                choices=[str(i) for i in range(1, len(TEAMS) + 1)],
                show_choices=False,
            )
            return TEAMS[team_idx - 1]

        cat = CATEGORIES[cat_idx - 1]
        print_teams_in_category(cat)

        team_choices = [str(i) for i in range(0, len(cat.teams) + 1)]
        team_idx = IntPrompt.ask(
            f"  [{ACCENT}]→[/] team",
            choices=team_choices,
            show_choices=False,
        )

        if team_idx == 0:
            continue

        return cat.teams[team_idx - 1]


# ── narration ────────────────────────────────────────────

def select_narration_mode() -> str:
    """Compact narration picker — one line per option."""
    console.print()
    console.print(f"  [bold]Voice narration[/]  [{MUTED}](optional)[/]")
    console.print()
    console.print(f"  [bold {ACCENT}]1[/]  off          [{MUTED}]silent, text only[/]")
    console.print(f"  [bold {ACCENT}]2[/]  highlights   [{MUTED}]leader summaries + final[/] [dim](default)[/]")
    console.print(f"  [bold {ACCENT}]3[/]  full         [{MUTED}]every agent speaks[/]")
    console.print()

    choice = IntPrompt.ask(
        f"  [{ACCENT}]→[/]",
        choices=["1", "2", "3"],
        default=2,
        show_choices=False,
    )

    modes = {
        1: Narrator.MODE_OFF,
        2: Narrator.MODE_HIGHLIGHTS,
        3: Narrator.MODE_FULL,
    }
    return modes[choice]


# ── main loop ────────────────────────────────────────────

def confirm_team(team: TeamConfig) -> None:
    """Clean confirmation line for the picked team."""
    agents = "  ".join(f"{a.icon} {a.name}" for a in team.agents)
    console.print()
    console.print(f"  [bold {ACCENT}]✓[/]  {team.icon} [bold]{team.name}[/]")
    console.print(f"     [{MUTED}]{agents}[/]")


def main() -> None:
    print_banner()
    time.sleep(0.08)
    console.print(f"  [{MUTED}]✓ Claude Code CLI detected[/]")

    narration_mode = select_narration_mode()

    while True:
        team_config = select_team()
        confirm_team(team_config)

        orchestrator = Orchestrator(narrate_mode=narration_mode)

        if getattr(team_config, "chat_mode", False):
            orchestrator.chat(team=team_config)
        else:
            console.print()
            goal = Prompt.ask(f"  [{ACCENT}]→[/] goal for {team_config.name}")
            if not goal.strip():
                console.print(f"  [red]No goal provided.[/]")
                continue
            orchestrator.run(goal=goal, team=team_config)

        console.print()
        again = Prompt.ask(
            f"  [{ACCENT}]→[/] another session? [dim](y/n)[/]",
            default="n",
        )
        if again.lower().strip() not in ("y", "yes"):
            console.print()
            console.print(f"  [{MUTED}]see you next time.[/]\n")
            break


if __name__ == "__main__":
    main()
