"""Benchmark harness — canonical hard tasks scored across team configurations."""

from .tasks import BenchTask, RubricCheck, load_tasks, get_task
from .scorer import ScoreBreakdown, WEIGHTS, score_task
from .runner import BenchResult, run_task, run_suite
from .report import render_comparison, render_team_aggregates, render_full_report

__all__ = [
    "BenchTask",
    "RubricCheck",
    "load_tasks",
    "get_task",
    "ScoreBreakdown",
    "WEIGHTS",
    "score_task",
    "BenchResult",
    "run_task",
    "run_suite",
    "render_comparison",
    "render_team_aggregates",
    "render_full_report",
]
