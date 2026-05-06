"""Render BenchResult sets as markdown comparison tables and per-task detail."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

from .runner import BenchResult


def _fmt(x: float) -> str:
    return f"{x:.2f}"


def render_comparison(results: list[BenchResult]) -> str:
    """One row per (task_id, team_name) showing the score breakdown."""
    if not results:
        return "_(no results)_"

    headers = [
        "task_id", "team", "total",
        "acc", "cite", "halluc", "action", "eff",
        "lat_s", "[COMPLETE]", "gate_fail",
    ]
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]

    for r in sorted(results, key=lambda x: (x.task_id, x.team_name)):
        s = r.score
        lines.append("| " + " | ".join([
            r.task_id,
            r.team_name,
            _fmt(s.total),
            _fmt(s.accuracy),
            _fmt(s.citation_quality),
            _fmt(s.hallucination),
            _fmt(s.actionability),
            _fmt(s.efficiency),
            _fmt(r.latency_s),
            "✓" if r.completed else "✗",
            "✓" if r.quality_gate_failed else "✗",
        ]) + " |")
    return "\n".join(lines)


def render_team_aggregates(results: list[BenchResult]) -> str:
    """One row per team with mean scores across all attempted tasks."""
    if not results:
        return "_(no results)_"
    by_team: dict[str, list[BenchResult]] = defaultdict(list)
    for r in results:
        by_team[r.team_name].append(r)

    headers = ["team", "n", "mean_total", "mean_acc", "mean_cite", "mean_halluc", "complete_rate", "gate_fail_rate"]
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for team_name, rs in sorted(by_team.items()):
        n = len(rs)
        lines.append("| " + " | ".join([
            team_name,
            str(n),
            _fmt(mean(r.total for r in rs)),
            _fmt(mean(r.score.accuracy for r in rs)),
            _fmt(mean(r.score.citation_quality for r in rs)),
            _fmt(mean(r.score.hallucination for r in rs)),
            _fmt(sum(1 for r in rs if r.completed) / n),
            _fmt(sum(1 for r in rs if r.quality_gate_failed) / n),
        ]) + " |")
    return "\n".join(lines)


def render_full_report(results: list[BenchResult]) -> str:
    parts = [
        "# Agent Forge Benchmark Report",
        "",
        "## Per-task results",
        "",
        render_comparison(results),
        "",
        "## Team aggregates",
        "",
        render_team_aggregates(results),
        "",
    ]
    return "\n".join(parts)
