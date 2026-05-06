"""CLI: python -m agent_forge.bench --team <name> [--tasks all|hotpot|<id>...] [--live] [--n N] [--seed S]"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from .. import teams as teams_module
from .runner import run_suite
from .tasks import get_task, load_tasks
from .report import render_full_report
from .datasets import load_hotpot_starter, load_hotpot_from_file


def _resolve_team(name: str):
    for attr in dir(teams_module):
        candidate = getattr(teams_module, attr)
        if hasattr(candidate, "name") and getattr(candidate, "name", "").lower() == name.lower():
            return candidate
    if name.lower() in ("research_lab", "research lab"):
        from ..teams.core import RESEARCH_LAB
        return RESEARCH_LAB
    raise SystemExit(f"Unknown team: {name}")


def _resolve_tasks(args) -> list:
    selectors = args.tasks
    out = []
    for s in selectors:
        if s == "all":
            out.extend(load_tasks())
        elif s == "hotpot":
            out.extend(load_hotpot_starter())
        elif s.startswith("hotpot:"):
            out.extend(load_hotpot_from_file(s.split(":", 1)[1], limit=args.n))
        else:
            out.append(get_task(s))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent_forge.bench")
    p.add_argument("--team", required=True, help="Team config name (e.g. 'Research Lab' or 'Tri-Model Research Lab')")
    p.add_argument("--tasks", nargs="+", default=["all"],
                   help="Task selectors: 'all', 'hotpot', 'hotpot:<path>', or task IDs")
    p.add_argument("--live", action="store_true", help="Use real model calls (default: deterministic mock)")
    p.add_argument("--n", type=int, default=None, help="Limit number of tasks")
    p.add_argument("--seed", type=int, default=None, help="Random seed for task subsetting")
    p.add_argument("--out", default=None, help="Path to write the markdown report (default: stdout)")
    args = p.parse_args(argv)

    team = _resolve_team(args.team)
    tasks = _resolve_tasks(args)

    if args.seed is not None:
        random.seed(args.seed)
        random.shuffle(tasks)
    if args.n is not None:
        tasks = tasks[: args.n]

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
