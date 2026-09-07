from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import controller
from ai_loop import db
from ai_loop.process_runner import BoundedProcessResult
from ai_loop.verification_orchestrator import (
    RealizationSignals,
    RealizationState,
    check_manifest_realization,
    refresh_job_realization,
    transition_realization_state,
)
from tests.test_specification_compiler import approved_service, create_quick_job


def manifest(command: str | None = None) -> dict:
    return {
        "verification": [
            {
                "verification_id": "VT1",
                "title": "Focused behavior",
                "requirement_ids": ["R1"],
                "automation": "automated",
                "blocking": True,
                "command": command or sys.executable,
                "command_source": "specification",
                "working_directory": ".",
                "fixtures": ["fixtures/input.json"],
                "metrics": ["result_count"],
                "required_evidence": ["test log"],
            },
            {
                "verification_id": "VT2",
                "title": "Documentation review",
                "requirement_ids": ["R1"],
                "automation": "manual",
                "blocking": False,
                "command": None,
                "command_source": "manual",
                "working_directory": ".",
                "fixtures": [],
                "metrics": [],
                "required_evidence": ["review note"],
            },
        ]
    }


def write_signals(root: Path, *, include_case: bool = True) -> None:
    lines = []
    if include_case:
        lines.append('AI_LOOP_CASE={"verification_id":"VT1"}')
    lines.extend(
        [
            'AI_LOOP_METRIC_EMITTER={"verification_id":"VT1","metrics":["result_count"]}',
            'AI_LOOP_EVIDENCE_PRODUCER={"verification_id":"VT1","kinds":["test log"]}',
        ]
    )
    (root / "verification.signals").write_text("\n".join(lines), encoding="utf-8")


def test_complete_static_infrastructure_becomes_executable_not_passing(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixtures/input.json"
    fixture.parent.mkdir()
    fixture.write_text("{}", encoding="utf-8")
    write_signals(tmp_path)

    automated, manual = check_manifest_realization(manifest(), tmp_path)

    assert automated.state == RealizationState.EXECUTABLE_BUT_FAILING
    assert automated.realized is True
    assert automated.command_resolved is True
    assert automated.case_marker is True
    assert automated.missing_infrastructure == ()
    assert manual.state == RealizationState.MANUAL_PENDING
    assert manual.realized is False
    assert manual.blocking is False


def test_broad_resolvable_command_is_unrealized_without_case_marker(tmp_path: Path) -> None:
    fixture = tmp_path / "fixtures/input.json"
    fixture.parent.mkdir()
    fixture.write_text("{}", encoding="utf-8")
    write_signals(tmp_path, include_case=False)

    result = check_manifest_realization(manifest(), tmp_path)[0]

    assert result.command_resolved is True
    assert result.state == RealizationState.UNREALIZED
    assert any("AI_LOOP_CASE" in issue for issue in result.issues)


def test_unresolved_auto_and_missing_producers_are_reported_as_infrastructure(
    tmp_path: Path,
) -> None:
    (tmp_path / "case.signals").write_text(
        'AI_LOOP_CASE={"verification_id":"VT1"}', encoding="utf-8"
    )

    result = check_manifest_realization(manifest("auto"), tmp_path)[0]

    assert result.state == RealizationState.UNREALIZED
    assert result.command_resolved is False
    assert result.missing_fixtures == ("fixtures/input.json",)
    assert result.missing_metric_emitters == ("result_count",)
    assert result.missing_evidence_producers == ("test log",)
    assert "unresolved 'auto'" in " ".join(result.issues)


def test_deterministic_fixture_generator_and_adapter_result_realize_case(
    tmp_path: Path,
) -> None:
    signals = RealizationSignals(
        verification_id="VT1",
        case_marker=True,
        fixture_generators=("fixtures/input.json",),
        metric_emitters=("result_count",),
        evidence_producers=("test log",),
    )

    result = check_manifest_realization(
        manifest(), tmp_path, adapter_results=[signals]
    )[0]

    assert result.state == RealizationState.EXECUTABLE_BUT_FAILING
    assert result.missing_infrastructure == ()


@pytest.mark.parametrize("working_directory", ["../escape", "/tmp", r"C:\\temp"])
def test_working_directory_traversal_and_absolute_paths_are_rejected(
    tmp_path: Path, working_directory: str
) -> None:
    payload = manifest()
    payload["verification"][0]["working_directory"] = working_directory

    result = check_manifest_realization(payload, tmp_path)[0]

    assert result.state == RealizationState.UNREALIZED
    assert result.working_directory is None


def test_working_directory_symlink_escape_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    payload = manifest()
    payload["verification"][0]["working_directory"] = "escape"

    result = check_manifest_realization(payload, tmp_path)[0]

    assert result.state == RealizationState.UNREALIZED
    assert "outside the worktree" in " ".join(result.issues)


def test_runtime_metric_and_evidence_envelopes_in_marked_source_are_signals(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixtures/input.json"
    fixture.parent.mkdir()
    fixture.write_text("{}", encoding="utf-8")
    (tmp_path / "case.txt").write_text(
        "\n".join(
            [
                'AI_LOOP_CASE={"verification_id":"VT1"}',
                'AI_LOOP_METRICS={"metrics":{"result_count":1}}',
                'AI_LOOP_EVIDENCE={"items":[{"kind":"test log"}]}',
            ]
        ),
        encoding="utf-8",
    )

    result = check_manifest_realization(manifest(), tmp_path)[0]

    assert result.state == RealizationState.EXECUTABLE_BUT_FAILING


@pytest.mark.parametrize(
    ("previous", "realized", "manual", "expected"),
    [
        (None, False, False, RealizationState.UNREALIZED),
        ("unrealized", True, False, RealizationState.EXECUTABLE_BUT_FAILING),
        ("executable_but_failing", True, False, RealizationState.EXECUTABLE_BUT_FAILING),
        ("passing", True, False, RealizationState.PASSING),
        ("stagnated", True, False, RealizationState.STAGNATED),
        ("escalated", True, False, RealizationState.ESCALATED),
        ("passing", False, False, RealizationState.UNREALIZED),
        ("passing", True, True, RealizationState.MANUAL_PENDING),
    ],
)
def test_realization_state_transitions(
    previous: str | None,
    realized: bool,
    manual: bool,
    expected: RealizationState,
) -> None:
    assert (
        transition_realization_state(previous, realized=realized, manual=manual)
        == expected
    )


def test_formal_state_persists_and_manifest_artifact_is_not_rewritten(
    tmp_path: Path,
) -> None:
    service, _approved = approved_service(tmp_path, command_override=sys.executable)
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
    artifact_before = stored.artifact_path.read_bytes()
    (tmp_path / "formal-case.signals").write_text(
        "\n".join(
            [
                'AI_LOOP_CASE={"verification_id":"VT1"}',
                "AI_LOOP_FIXTURE_GENERATOR="
                '{"verification_id":"VT1","fixtures":'
                '["A valid and an invalid input"]}',
                'AI_LOOP_METRIC_EMITTER={"verification_id":"VT1","metrics":["duration_seconds"]}',
                'AI_LOOP_EVIDENCE_PRODUCER={"verification_id":"VT1","kinds":["Focused test log"]}',
            ]
        ),
        encoding="utf-8",
    )

    checks = refresh_job_realization(service, "JFORMAL")

    assert checks is not None
    assert checks[0].state == RealizationState.EXECUTABLE_BUT_FAILING
    with db.transaction(service.db_path) as conn:
        states = conn.execute(
            """
            SELECT verification_id, status FROM job_verification_states
            WHERE job_id = 'JFORMAL' ORDER BY verification_id
            """
        ).fetchall()
        assert [tuple(row) for row in states] == [
            ("VT1", "executable_but_failing"),
            ("VT2", "manual_pending"),
        ]
    assert stored.artifact_path.read_bytes() == artifact_before
    assert service.load_job_manifest("JFORMAL").artifact_hash == stored.artifact_hash
    prompt_context = service.load_job_prompt_context("JFORMAL")
    assert prompt_context.runtime_verification_summary[0]["status"] == (
        "executable_but_failing"
    )


def test_quick_goal_refresh_is_a_noop_with_no_manifest_or_state(tmp_path: Path) -> None:
    service, _approved = approved_service(tmp_path)
    create_quick_job(service.db_path, "JQUICK", tmp_path, test_cmd="auto")

    assert refresh_job_realization(service, "JQUICK") is None
    assert service.load_job_prompt_context("JQUICK") is None
    with db.transaction(service.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM verification_manifests WHERE job_id = 'JQUICK'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM job_verification_states WHERE job_id = 'JQUICK'"
        ).fetchone()[0] == 0


def done_decision() -> dict:
    return {
        "action": "DONE",
        "reason": "all production behavior is implemented",
        "history_summary": "implementation complete",
        "progress": {
            "completed_work_units": 1,
            "remaining_work_units": 0,
            "remaining_minutes": 0,
        },
    }


def continue_decision() -> dict:
    return {
        "action": "CONTINUE",
        "reason": "verification infrastructure remains",
        "history_summary": "implementation complete; realizing VT1",
        "progress": {
            "completed_work_units": 1,
            "remaining_work_units": 1,
            "remaining_minutes": 5,
        },
        "next_task": {
            "goal": "Create the missing VT1 verification infrastructure",
            "constraints": ["Add the exact case marker and producers"],
            "acceptance": ["VT1 is statically realized"],
            "test_cmd": "pytest -q",
            "requirement_ids": [],
            "verification_ids": ["VT1"],
        },
    }


def realization_summary(*, automation: str = "automated") -> tuple[dict, ...]:
    return (
        {
            "verification_id": "VT1",
            "automation": automation,
            "status": "manual_pending" if automation == "manual" else "unrealized",
            "missing_infrastructure": ["missing AI_LOOP_CASE marker for VT1"],
        },
    )


def test_unrealized_formal_done_uses_bounded_remake_for_infrastructure_task() -> None:
    outputs = [json.dumps(done_decision()), json.dumps(continue_decision())]
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        return BoundedProcessResult(command, 0, stdout=outputs[len(calls) - 1], stderr="")

    from tests.test_task_traceability import MANIFEST

    with patch.object(controller.shutil, "which", return_value="/usr/bin/claude"), patch.object(
        controller, "run_bounded_process", side_effect=fake_run
    ):
        decision = controller.run_claude(
            "claude",
            "FORMAL REVIEW",
            traceability_manifest=MANIFEST,
            realization_summary=realization_summary(),
        )

    assert decision["action"] == "CONTINUE"
    assert decision["next_task"]["verification_ids"] == ["VT1"]
    assert len(calls) == 2
    assert "focused verification-infrastructure task" in calls[1][-1]
    assert "AI_LOOP_CASE" in calls[1][-1]


def test_manual_pending_does_not_block_autonomous_done() -> None:
    controller.validate_decision_realization(
        done_decision(), realization_summary(automation="manual")
    )


def test_unrealized_case_requires_next_task_to_carry_its_verification_id() -> None:
    decision = continue_decision()
    decision["next_task"]["verification_ids"] = []
    decision["next_task"]["requirement_ids"] = ["R1"]

    with pytest.raises(ValueError, match="verification-infrastructure.*VT1"):
        controller.validate_decision_realization(decision, realization_summary())


def test_formal_prompts_prioritize_missing_infrastructure_and_quick_prompts_do_not(
    tmp_path: Path,
) -> None:
    from tests.test_task_traceability import job, prompt_context, task

    formal = controller.review_prompt(
        job(tmp_path),
        task(),
        {"codex_output": "ok", "test_output": "ok", "diff": "", "status": "completed"},
        prompt_context(),
    )
    quick = controller.review_prompt(
        job(tmp_path),
        task(),
        {"codex_output": "ok", "test_output": "ok", "diff": "", "status": "completed"},
    )

    assert "focused verification-infrastructure task" in formal
    assert "Do not return DONE while an automated case is unrealized" in formal
    assert "focused verification-infrastructure task" not in quick
