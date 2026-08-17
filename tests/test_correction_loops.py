from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import controller
from ai_loop import db
from ai_loop.specifications import SpecificationDocument, SpecificationService
from ai_loop.verification_orchestrator import (
    RunnerResult,
    VerificationExecutionError,
    build_runtime_verification_summary,
    classify_metric_trend,
    compute_failure_fingerprint,
    run_task_verification,
)
from tests.test_specification_compiler import create_quick_job, document


class FakeRunner:
    def __init__(self, *results: RunnerResult):
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []

    def run(self, **kwargs: Any) -> RunnerResult:
        self.calls.append(dict(kwargs))
        return self.results[len(self.calls) - 1]


class FakeClock:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"2026-08-16T14:00:{self.value:02d}+00:00"


def runner_result(
    duration: float,
    *,
    noise: str = "ordinary diagnostic noise",
    diagnostic: str = "ERROR expected duration <= 5 actual value is outside the bound",
) -> RunnerResult:
    return RunnerResult(
        output=(
            f"{noise}\n{diagnostic}\n"
            f'AI_LOOP_METRICS={{"metrics":{{"duration_seconds":{duration}}}}}'
        ),
        return_code=0,
        elapsed_seconds=0.1,
    )


def passing_result(duration: float = 1.0) -> RunnerResult:
    return RunnerResult(
        output=f'AI_LOOP_METRICS={{"metrics":{{"duration_seconds":{duration}}}}}',
        return_code=0,
        elapsed_seconds=0.1,
    )


def formal_runtime(
    tmp_path: Path,
    *,
    attempt_limit: int = 4,
    stagnation_limit: int = 2,
) -> tuple[SpecificationService, Any]:
    payload = document(command_override="verify focused case").to_dict()
    payload["verification"][0]["validation_loop"].update(
        maximum_correction_attempts=attempt_limit,
        stagnation_limit=stagnation_limit,
        escalation_condition=(
            "Provide the protected service credential or decide whether the "
            "contract may be changed."
        ),
    )
    service = SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts")
    service.create(
        tmp_path,
        SpecificationDocument.from_dict(payload),
        creator="author",
        specification_id="SPEC1",
    )
    service.submit_for_review("SPEC1")
    service.approve("SPEC1", approved_by="owner")
    stored = service.create_formal_job(
        specification_id="SPEC1",
        specification_version=1,
        job_id="JFORMAL",
        repo_path=str(tmp_path),
        worktree_path=str(tmp_path),
        branch=None,
        base_ref="HEAD",
        test_cmd="auto",
        max_iterations=8,
        use_worktree=False,
    )
    with db.transaction(service.db_path) as conn:
        db.create_task(
            conn,
            task_id="T1",
            job_id="JFORMAL",
            iteration=0,
            goal="Diagnose and repair the focused VT1 duration failure",
            constraints=[],
            acceptance=["VT1 satisfies its duration assertion"],
            test_cmd="verify focused case",
            created_by="test",
            requirement_ids=["R1"],
            verification_ids=["VT1"],
        )
    return service, stored


def execute(
    service: SpecificationService,
    stored: Any,
    result: RunnerResult,
    *,
    clock: FakeClock,
) -> None:
    run_task_verification(
        service.db_path,
        "JFORMAL",
        "T1",
        stored.manifest,
        FakeRunner(result),
        clock=clock,
    )


def repair_decision(action: str = "REPAIR") -> dict[str, Any]:
    decision: dict[str, Any] = {
        "action": action,
        "reason": "repair the bounded verification failure",
        "history_summary": "VT1 remains outside its bound",
        "progress": {
            "completed_work_units": 1,
            "remaining_work_units": 1,
            "remaining_minutes": 5,
        },
    }
    if action in {"REPAIR", "CONTINUE"}:
        decision["next_task"] = {
            "goal": "Diagnose VT1 using its retained evidence and actual duration",
            "constraints": ["Do not replan unrelated requirements"],
            "acceptance": ["VT1 passes its declared assertion"],
            "test_cmd": "verify focused case",
            "requirement_ids": ["R1"],
            "verification_ids": ["VT1"],
        }
    return decision


def human_decision() -> dict[str, Any]:
    return {
        "action": "HUMAN_NEEDED",
        "reason": "VT1 exhausted its hard correction bound",
        "history_summary": "Automated correction is bounded and exhausted.",
        "progress": {
            "completed_work_units": 1,
            "remaining_work_units": 1,
            "remaining_minutes": None,
        },
    }


def test_failure_fingerprint_ignores_irrelevant_churn_but_changes_for_real_failure() -> None:
    common = {
        "return_codes": [1],
        "failed_assertions": [
            {
                "metric": "duration_seconds",
                "operator": "<=",
                "threshold": 5,
                "tolerance": 0,
                "actual": 10,
            }
        ],
        "errors": ["metric assertion failed: duration_seconds"],
        "selected_metrics": {"duration_seconds": 10},
    }
    first = compute_failure_fingerprint(
        **common,
        output="build 101 at 2026-08-16T14:00:01Z\nERROR expected <= 5",
    )
    churned = compute_failure_fingerprint(
        **common,
        output="unrelated cache message 999\nERROR expected <= 5",
    )
    changed = compute_failure_fingerprint(
        **common,
        output="unrelated cache message 999\nERROR credential unavailable",
    )

    assert first == churned
    assert changed != first


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        ([{"duration": 10}, {"duration": 8}, {"duration": 6}], "improving"),
        ([{"duration": 6}, {"duration": 8}, {"duration": 10}], "regressing"),
        ([{"duration": 8}, {"duration": 8}, {"duration": 8}], "unchanged"),
        ([{"duration": 10}, {"duration": 8}, {"duration": 9}], "oscillating"),
        ([{"duration": 10, "errors": 1}, {"duration": 8, "errors": 2}], "non-deterministic"),
    ],
)
def test_metric_trend_classifications(
    history: list[dict[str, float]], expected: str
) -> None:
    assertions = [
        {"metric": "duration", "operator": "<=", "threshold": 5, "tolerance": 0},
        {"metric": "errors", "operator": "<=", "threshold": 0, "tolerance": 0},
    ]
    assert classify_metric_trend(history, assertions) == expected


def test_pass_resets_stagnation_and_consecutive_failure_but_retains_history(
    tmp_path: Path,
) -> None:
    service, stored = formal_runtime(tmp_path)
    clock = FakeClock()

    execute(service, stored, runner_result(10), clock=clock)
    execute(service, stored, passing_result(), clock=clock)
    execute(service, stored, runner_result(10), clock=clock)

    with db.transaction(service.db_path) as conn:
        history = db.list_verification_correction_attempts(
            conn, "JFORMAL", verification_id="VT1"
        )
        state = dict(
            conn.execute(
                "SELECT * FROM job_verification_states WHERE job_id = 'JFORMAL' AND verification_id = 'VT1'"
            ).fetchone()
        )
    assert [item["status"] for item in history] == [
        "executable_but_failing",
        "passing",
        "executable_but_failing",
    ]
    assert [item["consecutive_failures"] for item in history] == [1, 0, 1]
    assert [item["stagnation_series"] for item in history] == [1, 0, 2]
    assert state["consecutive_failures"] == 1
    assert state["stagnation_count"] == 0
    assert len(history) == 3


def test_stagnation_series_changes_only_for_meaningfully_different_failure(
    tmp_path: Path,
) -> None:
    service, stored = formal_runtime(tmp_path, attempt_limit=5, stagnation_limit=3)
    clock = FakeClock()

    execute(service, stored, runner_result(10, noise="cache key 1"), clock=clock)
    execute(service, stored, runner_result(10, noise="cache key 999"), clock=clock)
    execute(
        service,
        stored,
        runner_result(10, diagnostic="ERROR protected credential unavailable"),
        clock=clock,
    )

    with db.transaction(service.db_path) as conn:
        history = db.list_verification_correction_attempts(
            conn, "JFORMAL", verification_id="VT1"
        )
    assert history[0]["failure_fingerprint"] == history[1]["failure_fingerprint"]
    assert [item["stagnation_series"] for item in history] == [1, 1, 2]
    assert [item["stagnation_count"] for item in history] == [0, 1, 0]
    assert [item["meaningful_change"] for item in history] == [False, False, True]
    assert history[2]["failure_fingerprint"] != history[1]["failure_fingerprint"]


def test_metric_improvement_prevents_false_stagnation_without_hiding_failure(
    tmp_path: Path,
) -> None:
    service, stored = formal_runtime(tmp_path, attempt_limit=5, stagnation_limit=1)
    clock = FakeClock()

    execute(service, stored, runner_result(10), clock=clock)
    execute(service, stored, runner_result(8), clock=clock)

    with db.transaction(service.db_path) as conn:
        history = db.list_verification_correction_attempts(
            conn, "JFORMAL", verification_id="VT1"
        )
    assert history[-1]["status"] == "executable_but_failing"
    assert history[-1]["metric_trend"] == "improving"
    assert history[-1]["stagnation_count"] == 0
    assert history[-1]["stagnation_series"] == history[0]["stagnation_series"]


def test_controller_focused_repair_context_contains_exact_failure_contract(
    tmp_path: Path,
) -> None:
    service, stored = formal_runtime(tmp_path)
    execute(service, stored, runner_result(10), clock=FakeClock())

    summary = build_runtime_verification_summary(
        service.db_path, "JFORMAL", stored.manifest
    )
    contexts = controller.build_focused_repair_context(summary)

    assert len(contexts) == 1
    context = contexts[0]
    assert context["failed_case"] == {
        "verification_id": "VT1",
        "title": "Command behavior",
        "requirement_ids": ["R1", "R2"],
    }
    assert context["failed_repetition"] == 1
    assert context["expected_vs_actual"] == [
        {
            "metric": "duration_seconds",
            "operator": "<=",
            "threshold": 5,
            "tolerance": 0,
            "actual": 10.0,
        }
    ]
    assert context["retained_evidence_paths"][0].endswith("repetition-0001.log")
    assert context["recent_metric_trend"] == "insufficient"
    assert context["previous_repair_goals"] == [
        "Diagnose and repair the focused VT1 duration failure"
    ]
    assert context["remaining_attempt_budget"] == 3
    controller.validate_decision_correction(repair_decision(), summary)
    controller.validate_decision_realization(
        repair_decision(),
        (
            *summary,
            {
                "verification_id": "VT_OTHER",
                "automation": "automated",
                "blocking": True,
                "status": "unrealized",
                "missing_infrastructure": ["case marker is missing"],
            },
        ),
    )
    with pytest.raises(ValueError, match="not broad replanning"):
        controller.validate_decision_correction(repair_decision("CONTINUE"), summary)


def test_hard_bound_forces_human_needed_with_complete_escalation_report(
    tmp_path: Path,
) -> None:
    service, stored = formal_runtime(tmp_path, attempt_limit=2, stagnation_limit=1)
    clock = FakeClock()
    execute(service, stored, runner_result(10), clock=clock)
    execute(service, stored, runner_result(10), clock=clock)
    summary = build_runtime_verification_summary(
        service.db_path, "JFORMAL", stored.manifest
    )

    assert summary is not None
    case = summary[0]
    assert case["status"] == "escalated"
    assert case["remaining_attempt_budget"] == 0
    report = case["escalation_report"]
    assert report["requirement_at_risk"][0]["requirement_id"] == "R1"
    assert report["failed_verification"]["verification_id"] == "VT1"
    assert report["observed_behavior"]["failed_assertions"][0]["actual"] == 10.0
    assert len(report["attempted_corrections"]) == 2
    assert report["metric_history"] == [
        {"duration_seconds": 10.0},
        {"duration_seconds": 10.0},
    ]
    assert report["retained_evidence"][0].endswith("repetition-0001.log")
    assert report["policy_exhaustion"]["exhausted_by"] == [
        "attempt_limit",
        "stagnation_limit",
    ]
    assert "credential" in report["human_input_needed"]["request"]

    rejected_runner = FakeRunner(runner_result(10))
    with pytest.raises(VerificationExecutionError, match="requires HUMAN_NEEDED"):
        run_task_verification(
            service.db_path,
            "JFORMAL",
            "T1",
            stored.manifest,
            rejected_runner,
            clock=clock,
        )
    assert rejected_runner.calls == []

    with pytest.raises(controller.CompletionDecisionError, match="requires HUMAN_NEEDED"):
        controller.parse_and_validate_decision(
            json.dumps(repair_decision()),
            stored.manifest,
            summary,
        )

    outputs = [json.dumps(repair_decision()), json.dumps(human_decision())]
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(command))
        return subprocess.CompletedProcess(
            command, 0, stdout=outputs[len(calls) - 1], stderr=""
        )

    with patch.object(controller.shutil, "which", return_value="/usr/bin/claude"), patch.object(
        controller.subprocess, "run", side_effect=fake_run
    ):
        decision = controller.run_claude(
            "claude",
            "FORMAL REVIEW",
            traceability_manifest=stored.manifest,
            realization_summary=summary,
        )

    assert len(calls) == 2
    assert decision["action"] == "HUMAN_NEEDED"
    assert decision["escalation_report"] == report


@pytest.mark.parametrize(
    ("attempt_limit", "stagnation_limit", "attempts", "exhausted_by"),
    [
        (1, 5, 1, ["attempt_limit"]),
        (5, 1, 2, ["stagnation_limit"]),
    ],
)
def test_each_correction_policy_is_an_independent_hard_bound(
    tmp_path: Path,
    attempt_limit: int,
    stagnation_limit: int,
    attempts: int,
    exhausted_by: list[str],
) -> None:
    service, stored = formal_runtime(
        tmp_path,
        attempt_limit=attempt_limit,
        stagnation_limit=stagnation_limit,
    )
    clock = FakeClock()
    for _ in range(attempts):
        execute(service, stored, runner_result(10), clock=clock)

    summary = build_runtime_verification_summary(
        service.db_path, "JFORMAL", stored.manifest
    )
    assert summary is not None
    assert summary[0]["status"] == "escalated"
    assert summary[0]["escalation_report"]["policy_exhaustion"]["exhausted_by"] == exhausted_by


def test_quick_goal_has_no_adaptive_correction_or_escalation_gate(
    tmp_path: Path,
) -> None:
    database = tmp_path / "quick.sqlite3"
    db.init_db(database)
    create_quick_job(database, "JQUICK", tmp_path, test_cmd="auto")
    with db.transaction(database) as conn:
        db.create_task(
            conn,
            task_id="TQUICK",
            job_id="JQUICK",
            iteration=0,
            goal="Run ordinary Quick Goal work",
            constraints=[],
            acceptance=[],
            test_cmd="auto",
            created_by="test",
        )
    runner = FakeRunner(runner_result(10))

    assert run_task_verification(
        database, "JQUICK", "TQUICK", None, runner, clock=FakeClock()
    ) == ()
    assert runner.calls == []
    assert controller.build_focused_repair_context(None) == ()
    controller.validate_decision_correction(repair_decision("CONTINUE"), None)
    controller.validate_decision_completion(
        repair_decision("CONTINUE"), None, worker_run_id=None
    )
    with db.transaction(database) as conn:
        assert db.list_verification_correction_attempts(conn, "JQUICK") == []
        assert conn.execute(
            "SELECT COUNT(*) FROM job_verification_states WHERE job_id = 'JQUICK'"
        ).fetchone()[0] == 0


def test_correction_migration_is_additive_idempotent_and_preserves_legacy_job(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY, repo_path TEXT NOT NULL, worktree_path TEXT NOT NULL,
            branch TEXT, base_ref TEXT NOT NULL, goal TEXT NOT NULL,
            constraints_json TEXT NOT NULL, acceptance_json TEXT NOT NULL,
            test_cmd TEXT NOT NULL, max_iterations INTEGER NOT NULL,
            use_worktree INTEGER NOT NULL, status TEXT NOT NULL,
            history_summary TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO jobs VALUES (
            'JLEGACY', '/repo', '/repo', NULL, 'HEAD', 'Quick goal', '[]', '[]',
            'auto', 3, 0, 'planning', 'unchanged', 'created', 'updated'
        );
        """
    )
    before = connection.execute("SELECT * FROM jobs").fetchone()
    connection.commit()
    connection.close()

    db.init_db(database)
    db.init_db(database)

    with db.transaction(database) as conn:
        legacy = conn.execute(
            """
            SELECT id, repo_path, worktree_path, branch, base_ref, goal,
                constraints_json, acceptance_json, test_cmd, max_iterations,
                use_worktree, status, history_summary, created_at, updated_at
            FROM jobs
            """
        ).fetchone()
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        state_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(job_verification_states)")
        }
    assert tuple(legacy) == tuple(before)
    assert "verification_correction_attempts" in tables
    assert {
        "failure_fingerprint",
        "latest_metrics_json",
        "metric_trend",
        "stagnation_series",
        "escalation_report_json",
    }.issubset(state_columns)
