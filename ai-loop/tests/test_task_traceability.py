from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import controller
import worker
from ai_loop import db
from ai_loop.process_runner import BoundedProcessResult


MANIFEST = {
    "schema_version": "1.0",
    "specification": {
        "id": "SPEC1",
        "version": 1,
        "schema_version": "1.0",
        "content_hash": "a" * 64,
    },
    "work_items": [
        {
            "requirement_id": "R1",
            "category": "functional",
            "priority": "must",
            "title": "Requirement one",
            "statement": "The behavior works.",
            "acceptance_criteria": ["The behavior is observed."],
            "linked_use_case_ids": ["UC1"],
            "linked_risk_ids": [],
            "linked_verification_ids": ["VT1"],
        }
    ],
    "verification": [
        {
            "verification_id": "VT1",
            "title": "Verify requirement one",
            "requirement_ids": ["R1"],
            "risk_ids": [],
            "test_level": "integration",
            "method": "deterministic",
            "automation": "automated",
            "blocking": True,
            "command": "pytest -q",
            "command_source": "job_default",
            "working_directory": ".",
            "timeout": 60,
            "oracle": "Expected result",
            "fixtures": ["fixture-one"],
            "procedure": ["Run the case"],
            "pass_criteria": ["The case passes"],
            "metrics": ["result_count"],
            "metric_assertions": [
                {
                    "metric": "result_count",
                    "operator": ">=",
                    "threshold": 1,
                    "tolerance": None,
                }
            ],
            "coverage_targets": ["ordinary and boundary scenarios"],
            "required_evidence": ["test log"],
            "validation_loop": {
                "maximum_correction_attempts": 2,
                "repetitions_per_attempt": 1,
                "stagnation_limit": 1,
                "escalation_condition": "Repeated failure",
                "retain_evidence": True,
            },
        }
    ],
}


def decision(
    *, requirement_ids: list[str] | None = None, verification_ids: list[str] | None = None
) -> dict:
    next_task = {
        "goal": "Implement requirement R1 and verification VT1",
        "constraints": [],
        "acceptance": [],
        "test_cmd": "pytest -q",
    }
    if requirement_ids is not None:
        next_task["requirement_ids"] = requirement_ids
    if verification_ids is not None:
        next_task["verification_ids"] = verification_ids
    return {
        "action": "CONTINUE",
        "reason": "work remains",
        "history_summary": "planning",
        "progress": {
            "completed_work_units": 0,
            "remaining_work_units": 1,
            "remaining_minutes": 5,
        },
        "next_task": next_task,
    }


def prompt_context() -> SimpleNamespace:
    return SimpleNamespace(
        specification={
            "schema_version": "1.0",
            "title": "Prompt contract title",
            "summary": "Prompt contract summary",
        },
        manifest=MANIFEST,
        runtime_verification_summary=(
            {
                "verification_id": "VT1",
                "title": "Verify requirement one",
                "requirement_ids": ["R1"],
                "blocking": True,
                "automation": "automated",
                "status": "unrealized",
                "updated_at": "2026-08-16T00:00:00+00:00",
            },
        ),
    )


def job(root: Path) -> dict:
    return {
        "id": "J1",
        "worktree_path": str(root),
        "goal": "Implement the contract",
        "constraints": [],
        "acceptance": [],
        "test_cmd": "pytest -q",
        "granularity": "normal",
        "email_token": "do-not-leak",
    }


def task() -> dict:
    return {
        "id": "T1",
        "iteration": 0,
        "goal": "Implement requirement R1",
        "constraints": [],
        "acceptance": [],
        "test_cmd": "pytest -q",
        "requirement_ids": ["R1"],
        "verification_ids": ["VT1"],
    }


def test_decision_schema_adds_optional_traceability_arrays() -> None:
    schema = json.loads(Path("decision.schema.json").read_text(encoding="utf-8"))
    next_task = schema["properties"]["next_task"]
    assert "requirement_ids" not in next_task["required"]
    assert "verification_ids" not in next_task["required"]
    assert next_task["properties"]["requirement_ids"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert next_task["properties"]["verification_ids"] == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_formal_traceability_accepts_either_known_requirement_or_verification() -> None:
    controller.validate_decision_traceability(decision(requirement_ids=["R1"]), MANIFEST)
    controller.validate_decision_traceability(decision(verification_ids=["VT1"]), MANIFEST)


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (decision(), "at least one"),
        (decision(requirement_ids=["MISSING"]), "MISSING"),
        (decision(verification_ids=["UNKNOWN"]), "UNKNOWN"),
        (decision(requirement_ids=["R1", "R1"]), "duplicate"),
        (decision(verification_ids=["VT1", "VT1"]), "duplicate"),
    ],
)
def test_formal_traceability_rejects_missing_unknown_and_duplicate_ids(
    candidate: dict, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        controller.validate_decision_traceability(candidate, MANIFEST)


def test_quick_goal_accepts_absent_or_empty_arrays_but_rejects_formal_ids() -> None:
    controller.validate_decision_traceability(decision(), None)
    controller.validate_decision_traceability(
        decision(requirement_ids=[], verification_ids=[]), None
    )
    with pytest.raises(ValueError, match="Quick Goal"):
        controller.validate_decision_traceability(decision(requirement_ids=["R1"]), None)


def test_invalid_formal_traceability_uses_existing_bounded_remake_loop() -> None:
    invalid = json.dumps(decision(requirement_ids=["MISSING"]))
    valid = json.dumps(decision(requirement_ids=["R1"], verification_ids=[]))
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        output = invalid if len(calls) == 1 else valid
        return BoundedProcessResult(command, 0, stdout=output, stderr="")

    with patch.object(controller.shutil, "which", return_value="/usr/bin/claude"), patch.object(
        controller, "run_bounded_process", side_effect=fake_run
    ):
        result = controller.run_claude(
            "claude", "ORIGINAL FORMAL PROMPT", traceability_manifest=MANIFEST
        )

    assert result["next_task"]["requirement_ids"] == ["R1"]
    assert len(calls) == 2
    assert "MISSING" in calls[1][-1]
    assert "ORIGINAL FORMAL PROMPT" in calls[1][-1]
    assert "requirement_ids" in calls[1][-1]


class FakeRedis:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, str]]] = []
        self.publications: dict[str, tuple[str, str]] = {}

    def xgroup_create(self, *_args, **_kwargs) -> None:
        return None

    def xadd(self, stream: str, fields: dict[str, str]) -> str:
        self.messages.append((stream, fields))
        return f"{len(self.messages)}-0"

    def eval(self, _script, _numkeys, stream, _dedupe_hash, key, field, payload):
        if key in self.publications:
            message_id, prior_payload = self.publications[key]
            if prior_payload != payload:
                raise ValueError("publication key reused with different payload")
            return [message_id, 0]
        message_id = self.xadd(stream, {field: payload})
        self.publications[key] = (message_id, payload)
        return [message_id, 1]


def test_create_next_task_persists_and_round_trips_formal_ids(tmp_path: Path) -> None:
    database = tmp_path / "loop.sqlite3"
    db.init_db(database)
    with db.transaction(database) as conn:
        db.create_job(
            conn,
            job_id="J1",
            repo_path=str(tmp_path),
            worktree_path=str(tmp_path),
            branch=None,
            base_ref="HEAD",
            goal="Formal job",
            constraints=[],
            acceptance=[],
            test_cmd="pytest -q",
            max_iterations=10,
            use_worktree=False,
        )
        stored_job = db.get_job(conn, "J1")

    client = FakeRedis()
    task_id = controller.create_next_task(
        SimpleNamespace(db_path=database),
        client,
        stored_job,
        decision(requirement_ids=["R1"], verification_ids=["VT1"]),
        "test",
    )
    with db.transaction(database) as conn:
        stored_task = db.get_task(conn, task_id)
    assert stored_task["requirement_ids"] == ["R1"]
    assert stored_task["verification_ids"] == ["VT1"]
    assert len(client.messages) == 1
    queued = json.loads(client.messages[0][1]["task"])
    assert queued["task_id"] == task_id
    assert queued["job_id"] == "J1"
    assert queued["iteration"] == stored_task["iteration"]
    assert queued["created_by"] == "test"


def test_formal_controller_prompts_include_complete_contract_and_traceability(
    tmp_path: Path,
) -> None:
    context = prompt_context()
    formal_plan = controller.plan_prompt(job(tmp_path), context)
    formal_review = controller.review_prompt(
        job(tmp_path),
        task(),
        {"codex_output": "ok", "test_output": "ok", "diff": "", "status": "completed"},
        context,
    )
    for prompt in (formal_plan, formal_review):
        assert "Approved immutable specification" in prompt
        assert "Prompt contract title" in prompt
        assert "Immutable execution manifest" in prompt
        assert "Runtime verification summary" in prompt
        assert "unrealized" in prompt
        assert "requirement_ids" in prompt
        assert "verification_ids" in prompt
        assert "coherent requirement, architecture, dependency, and risk boundaries" in prompt
    assert '"requirement_ids": [\n    "R1"' in formal_review
    assert '"verification_ids": [\n    "VT1"' in formal_review

    quick_plan = controller.plan_prompt(job(tmp_path))
    quick_review = controller.review_prompt(
        job(tmp_path),
        task(),
        {"codex_output": "ok", "test_output": "ok", "diff": "", "status": "completed"},
    )
    assert "Approved immutable specification" not in quick_plan
    assert "Immutable execution manifest" not in quick_review
    assert "Runtime verification summary" not in quick_plan
    assert "requirement_ids" not in controller.schema_text("normal")


def test_formal_worker_prompt_requires_linked_verification_infrastructure(
    tmp_path: Path,
) -> None:
    quick = worker.codex_prompt(job(tmp_path), task())
    formal = worker.codex_prompt(job(tmp_path), task(), formal_context=prompt_context())
    assert "Formal execution contract" not in quick
    assert "Approved immutable specification" not in quick
    assert "Formal execution contract" in formal
    assert "Prompt contract title" in formal
    assert "Immutable execution manifest" in formal
    assert "Runtime verification summary" in formal
    assert '"requirement_ids": ["R1"]' in formal
    assert '"verification_ids": ["VT1"]' in formal
    assert "REQUIRE their declared test targets, fixtures" in formal
    assert "metric emitters, and evidence producers" in formal
