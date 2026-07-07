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


def _require_claude() -> bool:
    if _claude_ready():
        return True
    console.print(
        "  [red]This needs Claude:[/] run inside a Claude Code session "
        "(CLI is authenticated) or set ANTHROPIC_API_KEY."
    )
    return False


def cmd_explore(args) -> int:
    """Journal-aware exploration menu — works with just Claude (no extra keys)."""
    if not _require_claude():
        return 2
    from agent_forge import explorer

    n_seen = len(explorer.load_journal())
    console.print(f"  [bold {ACCENT}]✳ Explore[/]"
                  + (f"  [{MUTED}]· {args.topic}[/]" if args.topic else "")
                  + f"  [{MUTED}]· journal: {n_seen} past dives[/]")
    console.print()
    try:
        text = explorer.menu(n=args.n, topic=args.topic)
    except Exception as e:
        console.print(f"  [red]Explore failed:[/] {e}")
        return 1
    console.print(text)
    console.print()
    console.print(f"  [{MUTED}]Pick one → python forge.py dive \"<topic>\"   "
                  f"(or: python forge.py surprise)[/]")
    return 0


def _compile_interactive(md_path) -> None:
    from agent_forge.interactive import compile_interactive
    try:
        out = compile_interactive(
            md_path, on_progress=lambda m: console.print(f"  [{MUTED}]{m}[/]")
        )
        console.print(f"  [bold green]✓ interactive:[/] {out}")
    except Exception as e:
        console.print(f"  [yellow]interactive compile failed: {e}[/]")


def _print_dive_result(result: dict) -> None:
    console.print()
    console.print(f"  [bold green]✓[/] [bold]{result['title']}[/]")
    console.print(f"  [{MUTED}]saved:[/] {result['path']}")
    console.print(f"  [{MUTED}]skeptic seat:[/] {result['skeptic']}")
    if result["threads"]:
        console.print(f"  [{MUTED}]open threads:[/]")
        for i, t in enumerate(result["threads"], 1):
            console.print(f"    {i}. {t}")


def cmd_dive(args) -> int:
    """Self-verifying deep dive: draft → skeptic attack → revised final."""
    if not _require_claude():
        return 2
    if getattr(args, "fast", False):
        os.environ["EXPLORER_FAST"] = "1"
    from agent_forge import explorer

    console.print(f"  [bold {ACCENT}]▼ Dive[/]  {args.topic}")
    try:
        result = explorer.dive(
            args.topic,
            on_progress=lambda m: console.print(f"  [{MUTED}]{m}[/]"),
        )
    except Exception as e:
        console.print(f"  [red]Dive failed:[/] {e}")
        return 1
    _print_dive_result(result)
    if getattr(args, "interactive", False):
        _compile_interactive(result["path"])
    return 0


def cmd_surprise(args) -> int:
    """Sight-unseen: the engine picks a topic (avoiding your history) and dives."""
    if not _require_claude():
        return 2
    if getattr(args, "fast", False):
        os.environ["EXPLORER_FAST"] = "1"
    from agent_forge import explorer

    console.print(f"  [bold {ACCENT}]🎲 Surprise[/]")
    try:
        result = explorer.surprise(
            on_progress=lambda m: console.print(f"  [{MUTED}]{m}[/]"),
        )
    except Exception as e:
        console.print(f"  [red]Surprise failed:[/] {e}")
        return 1
    _print_dive_result(result)
    if getattr(args, "interactive", False):
        _compile_interactive(result["path"])
    return 0


def cmd_thread(args) -> int:
    """Show (or follow) the open threads left by the most recent dive."""
    from agent_forge import explorer

    open_threads = explorer.threads()
    if not open_threads:
        console.print(f"  [{MUTED}]No dives in the journal yet — "
                      f"run: python forge.py surprise[/]")
        return 0
    if args.pick is None:
        console.print(f"  [bold {ACCENT}]⑂ Open threads[/] from your last dive:")
        for i, t in enumerate(open_threads, 1):
            console.print(f"    {i}. {t}")
        console.print(f"\n  [{MUTED}]Follow one → python forge.py thread <number>[/]")
        return 0
    if not 1 <= args.pick <= len(open_threads):
        console.print(f"  [red]Pick 1-{len(open_threads)}.[/]")
        return 2
    if not _require_claude():
        return 2
    topic = open_threads[args.pick - 1]
    console.print(f"  [bold {ACCENT}]⑂ Thread[/]  {topic}")
    result = explorer.dive(
        topic, on_progress=lambda m: console.print(f"  [{MUTED}]{m}[/]")
    )
    _print_dive_result(result)
    return 0


def cmd_queue(args) -> int:
    """Batch: dive (and compile) several topics back to back, unattended."""
    if not _require_claude():
        return 2
    if getattr(args, "fast", False):
        os.environ["EXPLORER_FAST"] = "1"
    from agent_forge import explorer
    compile_fn = None
    if not args.no_interactive:
        from agent_forge.interactive import compile_interactive
        compile_fn = compile_interactive

    topics = args.topics or None
    console.print(f"  [bold {ACCENT}]▤ Queue[/]  "
                  + (f"{len(topics)} topics" if topics else f"{args.n} auto-picked"))
    results = explorer.queue(
        topics=topics, n=args.n,
        on_progress=lambda m: console.print(f"  [{MUTED}]{m}[/]"),
        compile_fn=compile_fn,
    )
    console.print()
    console.print(f"  [bold green]✓ {len(results)} episode(s) ready[/]")
    for r in results:
        target = r.get("html") or r["path"]
        console.print(f"    · [bold]{r['title']}[/]")
        console.print(f"      [{MUTED}]{target}[/]")
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

    p_exp = sub.add_parser("explore", help="journal-aware menu of things to explore")
    p_exp.add_argument("--topic", default=None,
                       help="optional focus area for the menu")
    p_exp.add_argument("-n", type=int, default=6, help="number of options (default 6)")
    p_exp.set_defaults(func=cmd_explore)

    p_dive = sub.add_parser("dive", help="self-verifying deep dive on a topic")
    p_dive.add_argument("topic", help="what to dive into")
    p_dive.add_argument("--fast", action="store_true",
                        help="sonnet writer — ~3x faster, slightly shallower")
    p_dive.add_argument("-i", "--interactive", action="store_true",
                        help="also compile a phone-first interactive HTML page")
    p_dive.set_defaults(func=cmd_dive)

    p_sur = sub.add_parser("surprise", help="engine picks a topic and dives")
    p_sur.add_argument("--fast", action="store_true",
                       help="sonnet writer — ~3x faster, slightly shallower")
    p_sur.add_argument("-i", "--interactive", action="store_true",
                       help="also compile a phone-first interactive HTML page")
    p_sur.set_defaults(func=cmd_surprise)

    p_int = sub.add_parser("interactive",
                           help="compile an existing dive .md into interactive HTML")
    p_int.add_argument("md", help="path to an explorations/*.md dive")
    p_int.set_defaults(func=lambda a: (_compile_interactive(a.md), 0)[1])

    p_thr = sub.add_parser("thread", help="show/follow open threads from last dive")
    p_thr.add_argument("pick", nargs="?", type=int, default=None,
                       help="thread number to follow (omit to list)")
    p_thr.set_defaults(func=cmd_thread)

    p_q = sub.add_parser("queue", help="batch several dives (+compile) unattended")
    p_q.add_argument("topics", nargs="*", help="topics to dive; omit to auto-pick")
    p_q.add_argument("-n", type=int, default=3, help="how many to auto-pick (default 3)")
    p_q.add_argument("--fast", action="store_true", help="sonnet writer, faster")
    p_q.add_argument("--no-interactive", action="store_true",
                     help="essays only, skip interactive HTML compile")
    p_q.set_defaults(func=cmd_queue)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
