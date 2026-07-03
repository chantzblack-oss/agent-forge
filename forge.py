#!/usr/bin/env python3
"""forge — drive Agent Forge non-interactively (from a phone / cloud session).

The interactive ``main.py`` menu can't be driven from a Claude Code cloud
session or a script. ``forge`` exposes the same engine as plain commands, so
you can explore, run any team, and export a transcript without a keyboard-
driven menu.

    # Blank slate — get a menu of things to explore (no API keys needed):
    python forge.py explore
    python forge.py explore --topic "money and behavioral economics"

    # Run a team on a question (auto-exports the transcript, prints the path):
    python forge.py run "Should I move my clinic to a hybrid model?" --team deliberation
    python forge.py run "Is moral realism defensible?" -t "Philosophy Salon"

    # See every team and whether your current keys can actually run it:
    python forge.py teams

Team names are fuzzy-matched, so ``-t deliberation`` finds
"Cross-Model Deliberation" and ``-t philosophy`` finds "Philosophy Salon".

Provider auth (handled automatically, in preference order):
  - Claude : the authenticated ``claude`` CLI (cloud sessions) or ANTHROPIC_API_KEY
  - Gemini : the ``gemini`` CLI or GEMINI_API_KEY   (needed by Cross-Model teams)
  - GPT    : OPENAI_API_KEY                          (needed by Tri-Model teams)
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

# Load .env (no dependency), mirroring main.py.
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

from rich.console import Console

from agent_forge import TEAMS, Orchestrator
from agent_forge.teams import TeamConfig

console = Console(force_terminal=True)
ACCENT = "bright_cyan"
MUTED = "grey58"


# ── provider availability ─────────────────────────────────

def _claude_ready() -> bool:
    return bool(shutil.which("claude") or os.environ.get("ANTHROPIC_API_KEY"))


def _gemini_ready() -> bool:
    return bool(shutil.which("gemini") or os.environ.get("GEMINI_API_KEY"))


def _openai_ready() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


# Map a per-agent provider alias to (human label, readiness check).
_PROVIDER_INFO = {
    "anthropic": ("Claude", _claude_ready),
    "claude_cli": ("Claude", _claude_ready),
    "claude_api": ("Claude", _claude_ready),
    "google": ("Gemini", _gemini_ready),
    "gemini_cli": ("Gemini", _gemini_ready),
    "gemini_api": ("Gemini", _gemini_ready),
    "openai": ("GPT", _openai_ready),
    "openai_api": ("GPT", _openai_ready),
    "gpt": ("GPT", _openai_ready),
}


def _team_providers(team: TeamConfig) -> set[str]:
    """Distinct provider aliases a team's agents use."""
    return {getattr(a, "provider", "anthropic") or "anthropic" for a in team.agents}


def _missing_providers(team: TeamConfig) -> list[str]:
    """Human labels of providers this team needs but that aren't configured."""
    missing = []
    for prov in _team_providers(team):
        label, ready = _PROVIDER_INFO.get(prov, ("Claude", _claude_ready))
        if not ready() and label not in missing:
            missing.append(label)
    return missing


def _find_team(query: str) -> TeamConfig | None:
    """Fuzzy-match a team by name (exact, then substring, then word overlap)."""
    q = query.strip().lower()
    for t in TEAMS:
        if t.name.lower() == q:
            return t
    hits = [t for t in TEAMS if q in t.name.lower()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        console.print(f"  [yellow]Ambiguous team '{query}'. Matches:[/]")
        for t in hits:
            console.print(f"    · {t.name}")
        return None
    # Fall back to word overlap.
    qwords = set(q.split())
    scored = sorted(
        ((len(qwords_overlap := qwords & set(t.name.lower().split())), t) for t in TEAMS),
        key=lambda x: x[0], reverse=True,
    )
    if scored and scored[0][0] > 0:
        return scored[0][1]
    return None


# ── commands ──────────────────────────────────────────────

def cmd_teams(_args) -> int:
    """List every team, grouped, marking which your current keys can run."""
    console.print()
    console.print(f"  [bold]Provider status[/]")
    for label, ready in (("Claude", _claude_ready), ("Gemini", _gemini_ready), ("GPT", _openai_ready)):
        mark = f"[green]ready[/]" if ready() else f"[red]not configured[/]"
        console.print(f"    {label:<8} {mark}")
    console.print()

    by_cat: dict[str, list[TeamConfig]] = {}
    for t in TEAMS:
        by_cat.setdefault(t.category, []).append(t)

    for cat, teams in by_cat.items():
        console.print(f"  [bold {ACCENT}]{cat}[/]")
        for t in teams:
            missing = _missing_providers(t)
            if missing:
                status = f"[red]needs {', '.join(missing)}[/]"
            else:
                status = "[green]ready[/]"
            console.print(f"    {t.icon} [bold]{t.name}[/]  {status}")
            console.print(f"       [{MUTED}]{t.description}[/]")
        console.print()
    return 0


def _run_team(team: TeamConfig, goal: str, narrate: str = "off") -> int:
    """Run a team non-interactively and auto-export the transcript."""
    missing = _missing_providers(team)
    if missing:
        console.print(
            f"  [red]Can't run '{team.name}': missing {', '.join(missing)}.[/]"
        )
        console.print(
            f"  [{MUTED}]Set the key(s) as env secrets, or pick a Claude-only "
            f"team (see: python forge.py teams).[/]"
        )
        return 2

    orchestrator = Orchestrator(narrate_mode=narrate)

    # Replace the interactive end-of-session prompt with auto-export + exit,
    # so the engine never blocks waiting on a keyboard.
    def _auto_end(self, goal, team, round_num):  # noqa: ANN001
        try:
            path = self._export_session()
            console.print(f"  [bold green]Exported transcript to {path}[/]")
        except Exception as e:  # pragma: no cover - export best-effort
            console.print(f"  [yellow]Export failed: {e}[/]")
        self._print_done()

    orchestrator._end_session = _auto_end.__get__(orchestrator)

    console.print(f"  [bold {ACCENT}]▶[/] {team.icon} [bold]{team.name}[/]")
    console.print(f"  [{MUTED}]goal:[/] {goal}\n")
    orchestrator.run(goal=goal, team=team)
    return 0


def cmd_run(args) -> int:
    team = _find_team(args.team)
    if not team:
        console.print(f"  [red]No team matches '{args.team}'.[/] Try: python forge.py teams")
        return 2
    return _run_team(team, args.goal, narrate=args.narrate)


_EXPLORE_SYSTEM = (
    "You are an exploration concierge for a curious, sharp generalist who "
    "arrives with no specific question and wants options. Offer a menu of "
    "distinct, genuinely interesting explorations. Be specific and vivid — "
    "each option should make them want to pick it. No filler."
)


def _explore_prompt(topic: str | None) -> str:
    focus = f" All options should relate to: {topic}." if topic else ""
    return (
        "Give me exactly 6 explorations worth an hour of attention." + focus +
        " Mix types: a mystery, a 'how X actually works', a big idea, a "
        "controversy, something timely, and a wildcard (unless a topic is "
        "given, in which case keep them all on-topic but still varied). "
        "Format each as a single numbered line: a bold 2-4 word label, then "
        "a one-sentence hook. After the list, add one line: 'Reply with a "
        "number and I'll go deep, or run a team on it with forge.py run.'"
    )


def cmd_explore(args) -> int:
    """Generate an exploration menu — works with just Claude (no extra keys)."""
    if not _claude_ready():
        console.print(
            "  [red]Explore needs Claude:[/] run inside a Claude Code session "
            "(CLI is authenticated) or set ANTHROPIC_API_KEY."
        )
        return 2

    from agent_forge.providers import get_provider

    console.print(f"  [bold {ACCENT}]✳ Explore[/]"
                  + (f"  [{MUTED}]· {args.topic}[/]" if args.topic else ""))
    console.print()
    try:
        provider = get_provider("anthropic")
        text = provider.complete(
            system=_EXPLORE_SYSTEM,
            user=_explore_prompt(args.topic),
            model="opus",
            max_tokens=1200,
        )
    except Exception as e:
        console.print(f"  [red]Explore failed:[/] {e}")
        return 1
    console.print(text)
    console.print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="forge",
        description="Drive Agent Forge non-interactively.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_teams = sub.add_parser("teams", help="list teams + which your keys can run")
    p_teams.set_defaults(func=cmd_teams)

    p_run = sub.add_parser("run", help="run a team on a goal (auto-exports)")
    p_run.add_argument("goal", help="the question / goal for the team")
    p_run.add_argument("-t", "--team", default="Polymath (Claude)",
                       help="team name (fuzzy). Default: Polymath (Claude)")
    p_run.add_argument("--narrate", default="off",
                       choices=["off", "highlights", "full"],
                       help="voice narration mode (default: off)")
    p_run.set_defaults(func=cmd_run)

    p_exp = sub.add_parser("explore", help="get a menu of things to explore")
    p_exp.add_argument("--topic", default=None,
                       help="optional focus area for the menu")
    p_exp.set_defaults(func=cmd_explore)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
