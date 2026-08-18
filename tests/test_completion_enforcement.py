from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import controller
from ai_loop import db
from ai_loop.process_runner import BoundedProcessResult
from ai_loop.verification_orchestrator import (
    RunnerResult,
    build_runtime_verification_summary,
    evaluate_completion_gate,
    run_task_verification,
)
from ai_loop.specifications import SpecificationDocument, SpecificationService
from tests.test_specification_compiler import (
    approved_service,
    create_quick_job,
    document,
)
from tests.test_task_traceability import MANIFEST


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
        return f"2026-08-16T12:00:{self.value:02d}+00:00"


def passing_result() -> RunnerResult:
    return RunnerResult(
        output=(
            "1 passed in 0.01s\n"
            'AI_LOOP_METRICS={"metrics":{"duration_seconds":1}}'
        ),
        return_code=0,
        elapsed_seconds=0.1,
    )


def done_decision() -> dict[str, Any]:
    return {
        "action": "DONE",
        "reason": "implementation is complete",
        "history_summary": "all implementation work is complete",
        "progress": {
            "completed_work_units": 1,
            "remaining_work_units": 0,
            "remaining_minutes": 0,
        },
    }


def human_decision() -> dict[str, Any]:
    return {
        "action": "HUMAN_NEEDED",
        "reason": "blocking verification VT1 is escalated",
        "history_summary": "automated work is bounded and user input is required",
        "progress": {
            "completed_work_units": 1,
            "remaining_work_units": 1,
            "remaining_minutes": None,
        },
    }


def final_verification_decision() -> dict[str, Any]:
    return {
        "action": "CONTINUE",
        "reason": "implementation is complete but current-run evidence is pending",
        "history_summary": "scheduling one final verification-only task",
        "progress": {
            "completed_work_units": 1,
            "remaining_work_units": 1,
            "remaining_minutes": 1,
        },
        "next_task": {
            "goal": "Run final verification only for every blocking case",
            "constraints": ["Do not change implementation files"],
            "acceptance": ["Every blocking case has fresh passing evidence"],
            "test_cmd": "pytest -q",
            "requirement_ids": [],
            "verification_ids": ["VT1"],
        },
    }


def completion_summary(
    *,
    status: str,
    freshness: str,
    worker_run_id: str = "RUN2",
    attempts: int = 0,
) -> tuple[dict[str, Any], ...]:
    return (
        {
            "verification_id": "VT1",
            "title": "Verify requirement one",
            "requirement_ids": ["R1"],
            "blocking": True,
            "automation": "automated",
            "status": status,
            "attempts_completed": attempts,
            "attempt_limit": 2,
            "repetitions_per_attempt": 1,
            "stagnation_limit": 1,
            "latest_metrics": None,
            "latest_evidence": [],
            "coverage_results": [],
            "execution_proof": {
                "passed": status == "passing",
                "selected_case_count": 1 if status == "passing" else None,
                "executed_case_count": 1 if status == "passing" else None,
                "skipped_case_count": 0 if status == "passing" else None,
                "assertion_record_count": 0,
                "observation_record_count": 0,
                "error": None,
            },
            "failed_assertions": [],
            "last_error": None,
            "last_task": None,
            "last_worker_run": None,
            "worker_run_under_review": worker_run_id,
            "evidence_freshness": freshness,
            "evidence_fresh": freshness == "fresh",
            "missing_infrastructure": [],
        },
    )


def create_run(
    database: Path,
    *,
    run_id: str,
    task_id: str,
    iteration: int,
) -> None:
    with db.transaction(database) as conn:
        db.create_run(
            conn,
            run_id=run_id,
            task_id=task_id,
            job_id="JFORMAL",
            iteration=iteration,
            codex_rc=0,
            codex_output="worker complete",
            test_rc=0,
            test_output="tests pass",
            git_status="",
            diff_stat="",
            diff="",
            changed_files=[],
            status="completed",
            error=None,
            started_at=f"2026-08-16T10:0{iteration}:00+00:00",
            finished_at=f"2026-08-16T10:0{iteration}:01+00:00",
        )


def formal_runtime(tmp_path: Path) -> tuple[Any, Any]:
    service, _approved = approved_service(
        tmp_path,
        command_override="verify focused case",
    )
    stored = service.create_formal_job(
        specification_id="SPEC1",
        specification_version=1,
        job_id="JFORMAL",
        repo_path=str(tmp_path),
        worktree_path=str(tmp_path),
        branch=None,
        base_ref="HEAD",
        test_cmd="auto",
        max_iterations=6,
        use_worktree=False,
    )
    with db.transaction(service.db_path) as conn:
        for iteration, task_id in enumerate(("T1", "T2")):
            db.create_task(
                conn,
                task_id=task_id,
                job_id="JFORMAL",
                iteration=iteration,
                goal=f"Implementation run {iteration + 1}",
                constraints=[],
                acceptance=[],
                test_cmd="verify focused case",
                created_by="test",
                requirement_ids=["R1"],
                verification_ids=[],
            )
    create_run(service.db_path, run_id="RUN1", task_id="T1", iteration=0)
    create_run(service.db_path, run_id="RUN2", task_id="T2", iteration=1)
    return service, stored


def formal_coverage_runtime(
    tmp_path: Path, *, high_risk: bool
) -> tuple[SpecificationService, Any, SpecificationDocument]:
    payload = document(command_override="verify focused case").to_dict()
    for requirement in payload["requirements"]:
        requirement["priority"] = "could"
    if not high_risk:
        payload["requirements"][0]["priority"] = "must"
    payload["risks"][0]["severity"] = "high" if high_risk else "medium"
    payload["verification"][0]["blocking"] = False
    specification = SpecificationDocument.from_dict(payload)

    service = SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts")
    service.create(
        tmp_path,
        specification,
        creator="author",
        specification_id="SPEC1",
    )
    service.submit_for_review("SPEC1")
    approved = service.approve("SPEC1", approved_by="owner")
    stored = service.create_formal_job(
        specification_id="SPEC1",
        specification_version=1,
        job_id="JFORMAL",
        repo_path=str(tmp_path),
        worktree_path=str(tmp_path),
        branch=None,
        base_ref="HEAD",
        test_cmd="auto",
        max_iterations=6,
        use_worktree=False,
    )
    with db.transaction(service.db_path) as conn:
        db.create_task(
            conn,
            task_id="T1",
            job_id="JFORMAL",
            iteration=0,
            goal="Implement the covered requirement",
            constraints=[],
            acceptance=[],
            test_cmd="verify focused case",
            created_by="test",
            requirement_ids=["R1"],
            verification_ids=[],
        )
    create_run(service.db_path, run_id="RUN2", task_id="T1", iteration=0)
    return service, stored, approved.document


def test_structured_summary_reports_pending_evidence_and_all_required_fields(
    tmp_path: Path,
) -> None:
    service, stored = formal_runtime(tmp_path)

    summary = build_runtime_verification_summary(
        service.db_path,
        "JFORMAL",
        stored.manifest,
        worker_run_id="RUN2",
    )

    assert summary is not None
    blocking = summary[0]
    assert blocking == {
        "verification_id": "VT1",
        "title": "Command behavior",
        "requirement_ids": ["R1", "R2"],
        "blocking": True,
        "automation": "automated",
        "status": "unrealized",
        "attempts_completed": 0,
        "attempt_limit": 2,
        "repetitions_per_attempt": 1,
        "stagnation_limit": 1,
        "latest_metrics": None,
        "latest_evidence": [],
        "coverage_results": [],
        "execution_proof": {},
        "failed_assertions": [],
        "last_error": None,
        "last_task": None,
        "last_worker_run": None,
        "worker_run_under_review": "RUN2",
        "evidence_freshness": "pending",
        "evidence_fresh": False,
        "updated_at": blocking["updated_at"],
    }
    gate = evaluate_completion_gate(summary, worker_run_id="RUN2")
    assert gate is not None
    assert gate.status == "pending"
    assert gate.ready is False
    assert gate.pending_verification_ids == ("VT1",)


def test_older_passing_worker_run_is_stale_after_later_implementation(
    tmp_path: Path,
) -> None:
    service, stored = formal_runtime(tmp_path)
    run_task_verification(
        service.db_path,
        "JFORMAL",
        "T1",
        stored.manifest,
        FakeRunner(passing_result()),
        worker_run_id="RUN1",
        clock=FakeClock(),
    )

    summary = build_runtime_verification_summary(
        service.db_path,
        "JFORMAL",
        stored.manifest,
        worker_run_id="RUN2",
    )

    assert summary is not None
    assert summary[0]["status"] == "passing"
    assert summary[0]["last_task"] == "T1"
    assert summary[0]["last_worker_run"] == "RUN1"
    assert summary[0]["latest_metrics"] == {"duration_seconds": 1.0}
    assert summary[0]["evidence_freshness"] == "stale"
    gate = evaluate_completion_gate(summary, worker_run_id="RUN2")
    assert gate is not None
    assert gate.stale_verification_ids == ("VT1",)
    assert gate.ready is False


def test_current_worker_run_passing_evidence_opens_completion_gate(
    tmp_path: Path,
) -> None:
    service, stored = formal_runtime(tmp_path)
    run_task_verification(
        service.db_path,
        "JFORMAL",
        "T2",
        stored.manifest,
        FakeRunner(passing_result()),
        worker_run_id="RUN2",
        clock=FakeClock(),
    )

    summary = build_runtime_verification_summary(
        service.db_path,
        "JFORMAL",
        stored.manifest,
        worker_run_id="RUN2",
    )
    gate = evaluate_completion_gate(summary, worker_run_id="RUN2")

    assert summary is not None
    assert summary[0]["evidence_freshness"] == "fresh"
    assert summary[0]["last_worker_run"] == "RUN2"
    assert gate is not None and gate.ready is True and gate.status == "ready"
    controller.validate_decision_completion(
        done_decision(), summary, worker_run_id="RUN2"
    )


@pytest.mark.parametrize(
    ("runner_result", "expected_reason"),
    [
        (
            RunnerResult(
                output=(
                    "no tests ran in 0.01s\n"
                    'AI_LOOP_METRICS={"metrics":{"duration_seconds":1}}'
                ),
                return_code=0,
                elapsed_seconds=0.1,
                selected_case_count=0,
                executed_case_count=0,
                skipped_case_count=0,
            ),
            "selected zero test cases",
        ),
        (
            RunnerResult(
                output=(
                    "1 skipped in 0.01s\n"
                    'AI_LOOP_METRICS={"metrics":{"duration_seconds":1}}'
                ),
                return_code=0,
                elapsed_seconds=0.1,
                selected_case_count=1,
                executed_case_count=0,
                skipped_case_count=1,
            ),
            "all selected test cases were skipped",
        ),
    ],
    ids=["zero-selected", "all-skipped"],
)
def test_missing_runtime_execution_proof_blocks_completion_gate_and_done(
    tmp_path: Path,
    runner_result: RunnerResult,
    expected_reason: str,
) -> None:
    service, stored = formal_runtime(tmp_path)
    run_task_verification(
        service.db_path,
        "JFORMAL",
        "T2",
        stored.manifest,
        FakeRunner(runner_result),
        worker_run_id="RUN2",
        clock=FakeClock(),
    )

    summary = build_runtime_verification_summary(
        service.db_path,
        "JFORMAL",
        stored.manifest,
        worker_run_id="RUN2",
    )
    gate = evaluate_completion_gate(summary, worker_run_id="RUN2")

    assert summary is not None
    assert summary[0]["status"] == "executable_but_failing"
    assert summary[0]["execution_proof"]["passed"] is False
    assert expected_reason in summary[0]["execution_proof"]["error"]
    assert gate is not None
    assert gate.ready is False
    assert gate.failing_verification_ids == ("VT1",)
    with pytest.raises(
        controller.CompletionDecisionError,
        match=f"execution proof rejection.*{expected_reason}",
    ):
        controller.validate_decision_completion(
            done_decision(), summary, worker_run_id="RUN2"
        )


def test_passing_state_without_positive_persisted_proof_cannot_open_gate() -> None:
    item = dict(
        completion_summary(
            status="passing", freshness="fresh", attempts=1
        )[0]
    )
    item["execution_proof"] = {
        "passed": False,
        "selected_case_count": 0,
        "executed_case_count": 0,
        "skipped_case_count": 0,
        "assertion_record_count": 0,
        "observation_record_count": 0,
        "error": "runtime execution proof missing: selected zero test cases",
    }

    gate = evaluate_completion_gate((item,), worker_run_id="RUN2")

    assert gate is not None
    assert gate.ready is False
    assert gate.failing_verification_ids == ("VT1",)
    with pytest.raises(
        controller.CompletionDecisionError,
        match="execution proof rejection.*selected zero test cases",
    ):
        controller.validate_decision_completion(
            done_decision(), (item,), worker_run_id="RUN2"
        )


@pytest.mark.parametrize(
    ("high_risk", "expected_required_ids"),
    [
        (False, ("R1",)),
        (True, ("R1", "R2")),
    ],
    ids=["mandatory", "high-risk"],
)
def test_requirement_coverage_blocks_done_until_linked_automated_case_passes(
    tmp_path: Path,
    high_risk: bool,
    expected_required_ids: tuple[str, ...],
) -> None:
    service, stored, specification = formal_coverage_runtime(
        tmp_path, high_risk=high_risk
    )
    summary = build_runtime_verification_summary(
        service.db_path,
        "JFORMAL",
        stored.manifest,
        worker_run_id="RUN2",
        specification=specification,
    )

    gate = evaluate_completion_gate(summary, worker_run_id="RUN2")
    assert gate is not None
    assert gate.ready is False
    assert gate.required_requirement_ids == expected_required_ids
    assert gate.missing_requirement_ids == expected_required_ids
    assert gate.blocking_verification_ids == ("VT1",)
    with pytest.raises(
        controller.CompletionDecisionError,
        match=r"mandatory/high-risk evidence.*R1.*worker run 'RUN2'",
    ) as raised:
        controller.validate_decision_completion(
            done_decision(), summary, worker_run_id="RUN2"
        )
    assert raised.value.final_verification_required is True

    run_task_verification(
        service.db_path,
        "JFORMAL",
        "T1",
        stored.manifest,
        FakeRunner(passing_result()),
        worker_run_id="RUN2",
        clock=FakeClock(),
    )
    passing_summary = build_runtime_verification_summary(
        service.db_path,
        "JFORMAL",
        stored.manifest,
        worker_run_id="RUN2",
        specification=specification,
    )
    passing_gate = evaluate_completion_gate(
        passing_summary, worker_run_id="RUN2"
    )

    assert passing_gate is not None
    assert passing_gate.ready is True
    assert passing_gate.missing_requirement_ids == ()
    controller.validate_decision_completion(
        done_decision(), passing_summary, worker_run_id="RUN2"
    )


def test_required_requirement_with_only_manual_coverage_blocks_done() -> None:
    summary = (
        {
            "verification_id": "VT-MANUAL",
            "requirement_ids": ["R-MUST"],
            "mandatory_requirement_ids": ["R-MUST"],
            "high_risk_requirement_ids": [],
            "blocking": False,
            "automation": "manual",
            "status": "manual_pending",
            "attempts_completed": 0,
            "worker_run_under_review": "RUN2",
            "evidence_freshness": "not_applicable",
        },
    )

    with pytest.raises(
        controller.CompletionDecisionError,
        match="requirements lack a linked automated verification: R-MUST",
    ):
        controller.validate_decision_completion(
            done_decision(), summary, worker_run_id="RUN2"
        )


def test_summary_reports_failed_assertions_error_and_failing_gate(
    tmp_path: Path,
) -> None:
    service, stored = formal_runtime(tmp_path)
    failing = RunnerResult(
        output='AI_LOOP_METRICS={"metrics":{"duration_seconds":10}}',
        return_code=0,
        elapsed_seconds=0.1,
    )
    run_task_verification(
        service.db_path,
        "JFORMAL",
        "T2",
        stored.manifest,
        FakeRunner(failing),
        worker_run_id="RUN2",
        clock=FakeClock(),
    )

    summary = build_runtime_verification_summary(
        service.db_path,
        "JFORMAL",
        stored.manifest,
        worker_run_id="RUN2",
    )
    gate = evaluate_completion_gate(summary, worker_run_id="RUN2")

    assert summary is not None
    assert summary[0]["attempts_completed"] == 1
    assert summary[0]["latest_metrics"] == {"duration_seconds": 10.0}
    assert summary[0]["failed_assertions"] == [
        {
            "actual": 10.0,
            "error": "metric assertion failed: duration_seconds",
            "metric": "duration_seconds",
            "operator": "<=",
            "passed": False,
            "threshold": 5,
            "tolerance": 0,
        }
    ]
    assert "duration_seconds" in summary[0]["last_error"]
    assert summary[0]["last_task"] == "T2"
    assert summary[0]["last_worker_run"] == "RUN2"
    assert gate is not None
    assert gate.status == "failing"
    assert gate.failing_verification_ids == ("VT1",)


def test_worker_run_linkage_is_checked_before_the_runner_is_called(
    tmp_path: Path,
) -> None:
    service, stored = formal_runtime(tmp_path)
    runner = FakeRunner(passing_result())

    with pytest.raises(ValueError, match="different job or task"):
        run_task_verification(
            service.db_path,
            "JFORMAL",
            "T1",
            stored.manifest,
            runner,
            worker_run_id="RUN2",
            clock=FakeClock(),
        )

    assert runner.calls == []


def test_pending_formal_done_is_rejected_and_requests_final_verification() -> None:
    with pytest.raises(
        controller.CompletionDecisionError,
        match="pending or stale.*final verification-only",
    ) as raised:
        controller.validate_decision_completion(
            done_decision(),
            completion_summary(
                status="executable_but_failing",
                freshness="pending",
            ),
            worker_run_id="RUN2",
        )

    assert raised.value.final_verification_required is True


def test_premature_done_uses_bounded_remake_for_exactly_one_final_task() -> None:
    outputs = [json.dumps(done_decision()), json.dumps(final_verification_decision())]
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        return BoundedProcessResult(
            command,
            0,
            stdout=outputs[len(calls) - 1],
            stderr="",
        )

    with patch.object(controller.shutil, "which", return_value="/usr/bin/claude"), patch.object(
        controller,
        "run_bounded_process",
        side_effect=fake_run,
    ):
        decision = controller.run_claude(
            "claude",
            "FORMAL REVIEW",
            traceability_manifest=MANIFEST,
            realization_summary=completion_summary(
                status="executable_but_failing",
                freshness="pending",
            ),
            worker_run_id="RUN2",
        )

    assert decision == final_verification_decision()
    assert len(calls) == 2
    assert "final verification-only task" in calls[1][-1]
    assert "VT1" in calls[1][-1]
    assert decision["next_task"]["requirement_ids"] == []
    assert decision["next_task"]["verification_ids"] == ["VT1"]


def test_formal_review_prompt_receives_structured_summary_and_gate(
    tmp_path: Path,
) -> None:
    context = SimpleNamespace(
        specification={"title": "Contract"},
        manifest=MANIFEST,
        runtime_verification_summary=completion_summary(
            status="passing",
            freshness="stale",
        ),
    )
    prompt = controller.review_prompt(
        {
            "id": "JFORMAL",
            "worktree_path": str(tmp_path),
            "goal": "Implement contract",
            "constraints": [],
            "acceptance": [],
            "test_cmd": "pytest -q",
            "granularity": "normal",
        },
        {
            "id": "T2",
            "requirement_ids": ["R1"],
            "verification_ids": ["VT1"],
        },
        {
            "id": "RUN2",
            "codex_output": "complete",
            "test_output": "pass",
            "diff": "",
        },
        context,
    )

    assert "Runtime verification summary" in prompt
    assert '"attempt_limit": 2' in prompt
    assert '"evidence_freshness": "stale"' in prompt
    assert "Fresh-run completion gate" in prompt
    assert '"status": "stale"' in prompt
    assert "worker run in this REVIEW" in prompt


def test_escalated_blocking_case_forces_human_needed_through_bounded_remake() -> None:
    outputs = [json.dumps(done_decision()), json.dumps(human_decision())]
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        return BoundedProcessResult(
            command,
            0,
            stdout=outputs[len(calls) - 1],
            stderr="",
        )

    with patch.object(controller.shutil, "which", return_value="/usr/bin/claude"), patch.object(
        controller,
        "run_bounded_process",
        side_effect=fake_run,
    ):
        decision = controller.run_claude(
            "claude",
            "FORMAL REVIEW",
            traceability_manifest=MANIFEST,
            realization_summary=completion_summary(
                status="escalated",
                freshness="pending",
                attempts=2,
            ),
            worker_run_id="RUN2",
        )

    assert decision["action"] == "HUMAN_NEEDED"
    assert len(calls) == 2
    assert "requires HUMAN_NEEDED" in calls[1][-1]


def test_quick_goal_never_builds_or_enforces_formal_completion_state(
    tmp_path: Path,
) -> None:
    database = tmp_path / "quick.sqlite3"
    db.init_db(database)
    create_quick_job(database, "JQUICK", tmp_path, test_cmd="auto")

    assert build_runtime_verification_summary(
        database,
        "JQUICK",
        None,
        worker_run_id="RUN-QUICK",
    ) is None
    assert evaluate_completion_gate(None, worker_run_id="RUN-QUICK") is None
    controller.validate_decision_completion(
        done_decision(),
        None,
        worker_run_id="RUN-QUICK",
    )
    parsed = controller.parse_and_validate_decision(json.dumps(done_decision()))
    assert parsed["action"] == "DONE"
