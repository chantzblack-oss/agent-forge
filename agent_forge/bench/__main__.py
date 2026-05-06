"""CLI entry: python -m agent_forge.bench --team <name> [--tasks all|<id> ...] [--live]"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .. import teams as teams_module
from .runner import run_suite
from .tasks import get_task, load_tasks
from .report import render_full_report


def _resolve_team(name: str):
    for attr in dir(teams_module):
        candidate = getattr(teams_module, attr)
        if hasattr(candidate, "name") and getattr(candidate, "name", "").lower() == name.lower():
            return candidate
    if name.lower() == "research_lab":
        from ..teams.core import RESEARCH_LAB
        return RESEARCH_LAB
    raise SystemExit(f"Unknown team: {name}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent_forge.bench")
    p.add_argument("--team", required=True, help="Team config name (e.g. 'Research Lab' or 'research_lab')")
    p.add_argument("--tasks", nargs="+", default=["all"], help="Task IDs or 'all'")
    p.add_argument("--live", action="store_true", help="Use real model calls (default: deterministic mock)")
    p.add_argument("--out", default=None, help="Path to write the markdown report (default: stdout)")
    args = p.parse_args(argv)

    team = _resolve_team(args.team)

    if args.tasks == ["all"]:
        tasks = load_tasks()
    else:
        tasks = [get_task(t) for t in args.tasks]

    results = run_suite(tasks, team, live=args.live)
    report = render_full_report(results)

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"Report written to {args.out}")
    else:
        print(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
