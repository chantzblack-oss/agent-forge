"""End-to-end harness test: one task, one team, mock model — score above floor."""

from __future__ import annotations

import json

from agent_forge.bench import (
    BenchResult,
    get_task,
    load_tasks,
    run_suite,
    run_task,
    render_full_report,
)
from agent_forge.teams.core import RESEARCH_LAB


def test_load_tasks_returns_ten_in_stable_order() -> None:
    tasks = load_tasks()
    assert len(tasks) == 10
    ids = [t.id for t in tasks]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
    sources = {t.source for t in tasks}
    assert sources == {"handwritten", "adapted_public"}
    handwritten = [t for t in tasks if t.source == "handwritten"]
    public = [t for t in tasks if t.source == "adapted_public"]
    assert len(handwritten) == 5
    assert len(public) == 5


def test_run_task_end_to_end_with_mock_passes_score_floor() -> None:
    import copy
    team = copy.deepcopy(RESEARCH_LAB)
    team.max_rounds = 1
    task = get_task("hw_research_01")

    result = run_task(task, team, live=False)

    assert isinstance(result, BenchResult)
    assert result.task_id == "hw_research_01"
    assert result.completed is True
    assert result.quality_gate_failed is False
    # Mock is rubric-tuned for hw_research_01; total should clear 0.5 floor.
    assert result.total >= 0.5, f"total={result.total} breakdown={result.score}"
    # Citation density should be high since mock workers cite every Evidence claim.
    assert result.score.citation_quality >= 0.7

    # Claims sidecar JSON parses.
    claims = json.loads(result.claims_json)
    assert isinstance(claims, list)
    assert any(c["section"] == "Evidence" for c in claims)


def test_run_suite_renders_report_with_per_task_and_aggregate_tables() -> None:
    import copy
    team = copy.deepcopy(RESEARCH_LAB)
    team.max_rounds = 1
    tasks = [get_task("hw_research_01"), get_task("hw_security_01")]
    results = run_suite(tasks, team, live=False)
    assert len(results) == 2
    report = render_full_report(results)
    assert "Per-task results" in report
    assert "Team aggregates" in report
    assert "hw_research_01" in report
    assert "hw_security_01" in report
    assert "Research Lab" in report
