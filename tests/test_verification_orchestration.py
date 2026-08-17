from __future__ import annotations

import copy
import sqlite3
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from ai_loop import db
from ai_loop.verification_orchestrator import (
    MAX_DATABASE_OUTPUT_CHARACTERS,
    RepetitionStatus,
    RunnerResult,
    SubprocessVerificationRunner,
    VerificationExecutionError,
    evaluate_metric_assertion,
    parse_numeric_metrics,
    run_case_attempt,
    run_task_verification,
    select_task_verification_cases,
)
from tests.test_specification_compiler import approved_service, create_quick_job
from tests.test_task_traceability import MANIFEST


class FakeRunner:
    def __init__(self, *results: RunnerResult | Exception):
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []

    def run(self, **kwargs: Any) -> RunnerResult:
        self.calls.append(dict(kwargs))
        result = self.results[len(self.calls) - 1]
        if isinstance(result, Exception):
            raise result
        return result


class FakeClock:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"2026-08-16T00:00:{self.value:02d}+00:00"


def case(*, repetitions: int = 1) -> dict[str, Any]:
    value = copy.deepcopy(MANIFEST["verification"][0])
    value["command"] = "run focused verification"
    value["validation_loop"]["repetitions_per_attempt"] = repetitions
    return value


def result(
    output: str = 'AI_LOOP_METRICS={"metrics":{"result_count":1}}',
    *,
    return_code: int | None = 0,
    timed_out: bool = False,
    launch_error: str | None = None,
) -> RunnerResult:
    return RunnerResult(
        output=output,
        return_code=return_code,
        elapsed_seconds=0.25,
        timed_out=timed_out,
        launch_error=launch_error,
        termination_details="terminated by timeout" if timed_out else None,
    )


def test_success_runs_through_domain_neutral_runner(tmp_path: Path) -> None:
    runner = FakeRunner(result())

    attempt = run_case_attempt(case(), tmp_path, runner, clock=FakeClock())

    assert attempt.passed is True
    assert attempt.repetitions[0].status == RepetitionStatus.PASSED
    assert attempt.repetitions[0].metrics == {"result_count": 1.0}
    assert runner.calls == [
        {
            "command": "run focused verification",
            "worktree": tmp_path,
            "working_directory": ".",
            "timeout": 60,
        }
    ]


def test_nonzero_exit_fails_even_when_metrics_pass(tmp_path: Path) -> None:
    attempt = run_case_attempt(
        case(), tmp_path, FakeRunner(result(return_code=7)), clock=FakeClock()
    )

    repetition = attempt.repetitions[0]
    assert attempt.passed is False
    assert repetition.status == RepetitionStatus.FAILED
    assert repetition.return_code == 7
    assert "return code 7" in " ".join(repetition.errors)


def test_runner_launch_exception_is_captured(tmp_path: Path) -> None:
    attempt = run_case_attempt(
        case(), tmp_path, FakeRunner(OSError("executable unavailable")), clock=FakeClock()
    )

    repetition = attempt.repetitions[0]
    assert repetition.status == RepetitionStatus.LAUNCH_ERROR
    assert repetition.return_code is None
    assert "OSError: executable unavailable" in " ".join(repetition.errors)


def test_timeout_is_captured_distinctly(tmp_path: Path) -> None:
    attempt = run_case_attempt(
        case(),
        tmp_path,
        FakeRunner(result(return_code=None, timed_out=True)),
        clock=FakeClock(),
    )

    repetition = attempt.repetitions[0]
    assert repetition.status == RepetitionStatus.TIMED_OUT
    assert repetition.timed_out is True
    assert any("timed out after 60 seconds" in error for error in repetition.errors)


def test_missing_metric_object_fails_zero_exit(tmp_path: Path) -> None:
    attempt = run_case_attempt(
        case(), tmp_path, FakeRunner(result("ordinary successful output")), clock=FakeClock()
    )

    repetition = attempt.repetitions[0]
    assert repetition.status == RepetitionStatus.FAILED
    assert "missing required metrics object" in repetition.errors
    assert "missing metric key: result_count" in repetition.errors


def test_missing_asserted_key_is_named_exactly(tmp_path: Path) -> None:
    attempt = run_case_attempt(
        case(),
        tmp_path,
        FakeRunner(result('AI_LOOP_METRICS={"metrics":{"another_metric":2}}')),
        clock=FakeClock(),
    )

    repetition = attempt.repetitions[0]
    assert repetition.status == RepetitionStatus.FAILED
    assert "missing declared metric key: result_count" in repetition.errors
    assert repetition.assertion_results[0].error == "missing metric key: result_count"


def test_threshold_failure_retains_expected_and_actual(tmp_path: Path) -> None:
    attempt = run_case_attempt(
        case(),
        tmp_path,
        FakeRunner(result('AI_LOOP_METRICS={"metrics":{"result_count":0}}')),
        clock=FakeClock(),
    )

    assertion = attempt.repetitions[0].assertion_results[0]
    assert assertion.passed is False
    assert assertion.operator == ">="
    assert assertion.threshold == 1
    assert assertion.actual == 0.0


@pytest.mark.parametrize(
    ("operator", "threshold", "tolerance", "actual"),
    [
        ("<", 10, 0, 9),
        ("<=", 10, 0, 10),
        ("==", 10, 0.5, 10.5),
        ("!=", 10, 0.5, 10.6),
        (">=", 10, 0, 10),
        (">", 10, 0, 11),
        ("<=", 10, 0.5, 10.5),
        (">=", 10, 0.5, 9.5),
    ],
)
def test_all_assertion_operators_and_absolute_tolerance(
    operator: str,
    threshold: float,
    tolerance: float,
    actual: float,
) -> None:
    evaluated = evaluate_metric_assertion(
        {
            "metric": "observed",
            "operator": operator,
            "threshold": threshold,
            "tolerance": tolerance,
        },
        actual,
    )

    assert evaluated.passed is True


def test_tolerance_passes_at_runtime(tmp_path: Path) -> None:
    verification = case()
    verification["metric_assertions"][0] = {
        "metric": "result_count",
        "operator": "==",
        "threshold": 1,
        "tolerance": 0.1,
    }
    attempt = run_case_attempt(
        verification,
        tmp_path,
        FakeRunner(result('AI_LOOP_METRICS={"metrics":{"result_count":1.1}}')),
        clock=FakeClock(),
    )

    assert attempt.passed is True


def test_every_repetition_runs_and_one_failure_fails_attempt(tmp_path: Path) -> None:
    runner = FakeRunner(
        result(),
        result('AI_LOOP_METRICS={"metrics":{"result_count":0}}'),
        result(),
    )

    attempt = run_case_attempt(
        case(repetitions=3), tmp_path, runner, clock=FakeClock()
    )

    assert len(runner.calls) == 3
    assert [item.status for item in attempt.repetitions] == [
        RepetitionStatus.PASSED,
        RepetitionStatus.FAILED,
        RepetitionStatus.PASSED,
    ]
    assert attempt.passed is False


@pytest.mark.parametrize(
    "payload",
    [
        '{"metrics":{"x":true}}',
        '{"metrics":{"x":"1"}}',
        '{"metrics":{"x":NaN}}',
        '{"metrics":{"x":Infinity}}',
        '{"metrics":{"x":1e10000}}',
    ],
)
def test_metric_parser_rejects_non_numeric_or_nonfinite_values(payload: str) -> None:
    assert parse_numeric_metrics(f"AI_LOOP_METRICS={payload}") is None


def test_metric_parser_uses_last_valid_bounded_payload_and_bare_json() -> None:
    output = "\n".join(
        [
            'AI_LOOP_METRICS={"metrics":{"x":1}}',
            '{"metrics":{"x":2}}',
            'AI_LOOP_METRICS={"metrics":{"x":false}}',
        ]
    )

    assert parse_numeric_metrics(output) == {"x": 2.0}


@pytest.mark.parametrize("working_directory", ["../escape", "/tmp", r"C:\\temp"])
def test_execution_revalidates_unsafe_directories_before_fake_runner(
    tmp_path: Path, working_directory: str
) -> None:
    verification = case()
    verification["working_directory"] = working_directory
    runner = FakeRunner(result())

    with pytest.raises(VerificationExecutionError):
        run_case_attempt(verification, tmp_path, runner, clock=FakeClock())

    assert runner.calls == []


def test_execution_revalidates_symlink_containment_before_fake_runner(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    verification = case()
    verification["working_directory"] = "escape"
    runner = FakeRunner(result())

    with pytest.raises(VerificationExecutionError, match="outside the worktree"):
        run_case_attempt(verification, tmp_path, runner, clock=FakeClock())

    assert runner.calls == []


def test_subprocess_runner_captures_combined_output_and_context(tmp_path: Path) -> None:
    completed = subprocess.CompletedProcess(
        ["bash", "-lc", "verify"], 3, stdout="standard output", stderr="standard error"
    )
    with patch(
        "ai_loop.verification_orchestrator.subprocess.run", return_value=completed
    ) as launched:
        observed = SubprocessVerificationRunner().run(
            command="verify", worktree=tmp_path, working_directory=".", timeout=12
        )

    assert observed.output == "standard output\nstandard error"
    assert observed.return_code == 3
    assert observed.timed_out is False
    assert observed.elapsed_seconds >= 0
    assert launched.call_args.kwargs["cwd"] == str(tmp_path.resolve())
    assert launched.call_args.kwargs["timeout"] == 12


def test_requirement_and_explicit_case_selection_and_unknown_rejection() -> None:
    selected = select_task_verification_cases(
        MANIFEST, {"requirement_ids": ["R1"], "verification_ids": []}
    )
    assert [item["verification_id"] for item in selected] == ["VT1"]

    with pytest.raises(VerificationExecutionError, match="MISSING_REQUIREMENT"):
        select_task_verification_cases(
            MANIFEST,
            {"requirement_ids": ["MISSING_REQUIREMENT"], "verification_ids": []},
        )
    with pytest.raises(VerificationExecutionError, match="MISSING_CASE"):
        select_task_verification_cases(
            MANIFEST,
            {"requirement_ids": [], "verification_ids": ["MISSING_CASE"]},
        )


def _formal_runtime(tmp_path: Path, *, task_requirement_ids: list[str]) -> tuple[Any, Any]:
    service, _approved = approved_service(tmp_path, command_override="verify focused case")
    stored = service.create_formal_job(
        specification_id="SPEC1",
        specification_version=1,
        job_id="JFORMAL",
        repo_path=str(tmp_path),
        worktree_path=str(tmp_path),
        branch=None,
        base_ref="HEAD",
        test_cmd="auto",
        max_iterations=4,
        use_worktree=False,
    )
    with db.transaction(service.db_path) as conn:
        db.create_task(
            conn,
            task_id="T1",
            job_id="JFORMAL",
            iteration=0,
            goal="Verify the formal contract",
            constraints=[],
            acceptance=[],
            test_cmd="verify focused case",
            created_by="test",
            requirement_ids=task_requirement_ids,
            verification_ids=[],
        )
    return service, stored


def test_unknown_reference_is_rejected_before_any_command_runs(tmp_path: Path) -> None:
    service, stored = _formal_runtime(tmp_path, task_requirement_ids=["UNKNOWN"])
    runner = FakeRunner(result())

    with pytest.raises(VerificationExecutionError, match="UNKNOWN"):
        run_task_verification(
            service.db_path,
            "JFORMAL",
            "T1",
            stored.manifest,
            runner,
            clock=FakeClock(),
        )

    assert runner.calls == []
    with db.transaction(service.db_path) as conn:
        assert db.list_verification_repetitions(conn, "JFORMAL") == []


def test_repetitions_persist_append_only_and_round_trip(tmp_path: Path) -> None:
    service, stored = _formal_runtime(tmp_path, task_requirement_ids=["R1"])
    output = (
        "x" * (MAX_DATABASE_OUTPUT_CHARACTERS + 100)
        + '\nAI_LOOP_METRICS={"metrics":{"duration_seconds":1}}'
    )

    first = run_task_verification(
        service.db_path,
        "JFORMAL",
        "T1",
        stored.manifest,
        FakeRunner(result(output)),
        clock=FakeClock(),
    )
    second = run_task_verification(
        service.db_path,
        "JFORMAL",
        "T1",
        stored.manifest,
        FakeRunner(result(output)),
        clock=FakeClock(),
    )

    assert first[0].passed is True
    assert second[0].attempt == 2
    with db.transaction(service.db_path) as conn:
        rows = db.list_verification_repetitions(
            conn, "JFORMAL", task_id="T1", verification_id="VT1"
        )
        state = conn.execute(
            """
            SELECT status FROM job_verification_states
            WHERE job_id = 'JFORMAL' AND verification_id = 'VT1'
            """
        ).fetchone()[0]
    assert [row["attempt"] for row in rows] == [1, 2]
    assert [row["repetition"] for row in rows] == [1, 1]
    assert [row["status"] for row in rows] == ["passed", "passed"]
    assert rows[0]["metrics"] == {"duration_seconds": 1.0}
    assert rows[0]["output_truncated"] is True
    assert len(rows[0]["output"]) == MAX_DATABASE_OUTPUT_CHARACTERS
    assert rows[0]["assertion_results"] == [
        {
            "actual": 1.0,
            "error": None,
            "metric": "duration_seconds",
            "operator": "<=",
            "passed": True,
            "threshold": 5,
            "tolerance": 0,
        }
    ]
    assert rows[0]["started_at"] == "2026-08-16T00:00:01+00:00"
    assert rows[0]["finished_at"] == "2026-08-16T00:00:02+00:00"
    assert state == "passing"


def test_quick_goal_has_no_selection_runtime_state_or_repetitions(tmp_path: Path) -> None:
    database = tmp_path / "loop.sqlite3"
    db.init_db(database)
    create_quick_job(database, "JQUICK", tmp_path, test_cmd="auto")
    with db.transaction(database) as conn:
        db.create_task(
            conn,
            task_id="TQUICK",
            job_id="JQUICK",
            iteration=0,
            goal="Ordinary quick task",
            constraints=[],
            acceptance=[],
            test_cmd="auto",
            created_by="test",
        )
    runner = FakeRunner(result())

    assert run_task_verification(
        database, "JQUICK", "TQUICK", None, runner, clock=FakeClock()
    ) == ()
    assert runner.calls == []
    with db.transaction(database) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM job_verification_states WHERE job_id = 'JQUICK'"
        ).fetchone()[0] == 0
        assert db.list_verification_repetitions(conn, "JQUICK") == []


def test_repetition_migration_is_additive_idempotent_and_preserves_rows(
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
            'auto', 3, 0, 'planning', '', 'created', 'updated'
        );
        """
    )
    before = connection.execute("SELECT * FROM jobs").fetchone()
    connection.commit()
    connection.close()

    db.init_db(database)
    db.init_db(database)

    with db.transaction(database) as migrated:
        legacy = migrated.execute(
            """
            SELECT id, repo_path, worktree_path, branch, base_ref, goal,
                constraints_json, acceptance_json, test_cmd, max_iterations,
                use_worktree, status, history_summary, created_at, updated_at
            FROM jobs
            """
        ).fetchone()
        tables = {
            row[0]
            for row in migrated.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert tuple(legacy) == tuple(before)
    assert "verification_repetitions" in tables
