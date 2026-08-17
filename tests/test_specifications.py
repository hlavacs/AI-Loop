from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from ai_loop import db
from ai_loop.specifications import (
    AutomationLevel,
    MetricAssertion,
    Requirement,
    RequirementCategory,
    RequirementPriority,
    Risk,
    RiskSeverity,
    RiskUncertainty,
    SpecificationDocument,
    SpecificationError,
    SpecificationIntegrityError,
    SpecificationService,
    SpecificationStateError,
    SpecificationValidationError,
    TestLevel as VerificationTestLevel,
    UseCase,
    ValidationLoop,
    VerificationCase,
    VerificationMethod,
    validate_for_approval,
    validate_structural,
    validate_working_directory,
    sha256_bytes,
)


def complete_document_dict(
    *, threshold: int | float = 5, tolerance: int | float | None = 0
) -> dict:
    return {
        "schema_version": "1.0",
        "title": "Reliable command",
        "summary": "Add one reliable, observable command without changing existing behavior.",
        "objectives": ["Provide the requested command"],
        "in_scope": ["Command behavior and tests"],
        "out_of_scope": ["Unrelated commands"],
        "stakeholders": ["Repository maintainers"],
        "assumptions": ["The supported Python runtime is available"],
        "constraints": ["Keep the existing public interface compatible"],
        "dependencies": ["Python standard library"],
        "use_cases": [
            {
                "id": "UC1",
                "title": "Run the command",
                "actors": ["User"],
                "preconditions": ["The repository is available"],
                "trigger": "The user invokes the command",
                "main_flow": ["Validate input", "Perform the operation", "Report success"],
                "alternate_flows": ["Use defaults when optional input is absent"],
                "postconditions": ["The result is observable"],
                "error_and_edge_cases": ["Invalid input is rejected without partial state"],
                "requirement_ids": ["R1", "R2"],
            }
        ],
        "requirements": [
            {
                "id": "R1",
                "category": "functional",
                "priority": "must",
                "title": "Perform operation",
                "statement": "The system shall perform the requested operation.",
                "rationale": "This is the requested behavior.",
                "acceptance_criteria": ["The example input produces the expected result."],
                "source": "User brief",
            },
            {
                "id": "R2",
                "category": "quality",
                "priority": "must",
                "title": "Reject invalid input safely",
                "statement": "The system shall reject invalid input without partial state.",
                "rationale": "Failure behavior must be predictable.",
                "acceptance_criteria": ["Invalid input returns an error and leaves state unchanged."],
                "source": "User brief",
            },
        ],
        "decisions": [],
        "risks": [],
        "verification": [
            {
                "id": "VT1",
                "title": "Command behavior",
                "requirement_ids": ["R1", "R2"],
                "test_level": "acceptance",
                "method": "deterministic",
                "oracle": "Expected results encoded independently in the test fixture",
                "fixtures": ["A valid input and an invalid input"],
                "procedure": ["Run the focused test target", "Inspect the emitted result"],
                "pass_criteria": ["Valid and invalid scenarios both match the oracle"],
                "declared_metrics": ["duration_seconds"],
                "metric_assertions": [
                    {
                        "metric": "duration_seconds",
                        "operator": "<=",
                        "threshold": threshold,
                        "tolerance": tolerance,
                    }
                ],
                "coverage_targets": ["Valid and invalid input scenarios"],
                "automation": "automated",
                "blocking": True,
                "validation_loop": {
                    "maximum_correction_attempts": 2,
                    "repetitions_per_attempt": 1,
                    "stagnation_limit": 1,
                    "escalation_condition": "Escalate after the bounded attempts are exhausted",
                    "retain_evidence": True,
                },
                "command_override": None,
                "working_directory": ".",
                "timeout": 60,
                "required_evidence": ["Focused test log"],
            }
        ],
        "open_questions": [],
    }


def complete_document(
    *, threshold: int | float = 5, tolerance: int | float | None = 0
) -> SpecificationDocument:
    return SpecificationDocument.from_dict(
        complete_document_dict(threshold=threshold, tolerance=tolerance)
    )


class TestSpecificationModels:
    def test_strict_parse_and_tuple_serialization(self) -> None:
        payload = complete_document_dict()
        document = SpecificationDocument.from_dict(payload)
        assert document.requirements[0].category == RequirementCategory.FUNCTIONAL
        assert isinstance(document.objectives, tuple)
        assert isinstance(document.to_dict()["objectives"], list)
        assert SpecificationDocument.from_json(document.pretty_json()) == document

        payload["unexpected"] = True
        with pytest.raises(SpecificationError, match="unknown fields"):
            SpecificationDocument.from_dict(payload)

    def test_nested_unknown_fields_and_invalid_enums_are_rejected(self) -> None:
        payload = complete_document_dict()
        payload["requirements"][0]["unexpected"] = "value"
        with pytest.raises(SpecificationError, match="unknown fields"):
            SpecificationDocument.from_dict(payload)

        payload = complete_document_dict()
        payload["requirements"][0]["priority"] = "urgent"
        with pytest.raises(SpecificationError, match="must be one of"):
            SpecificationDocument.from_dict(payload)

    def test_canonical_serialization_normalizes_equivalent_numbers(self) -> None:
        integer = complete_document(threshold=5, tolerance=2)
        floating = complete_document(threshold=5.0, tolerance=2.0)
        assert integer.canonical_json() == floating.canonical_json()
        assert integer.content_hash() == floating.content_hash()
        assert integer.pretty_json() == floating.pretty_json()
        assert sha256_bytes(integer.pretty_json().encode()) == sha256_bytes(
            floating.pretty_json().encode()
        )
        assertion = floating.to_dict()["verification"][0]["metric_assertions"][0]
        assert assertion["threshold"] == 5
        assert isinstance(assertion["threshold"], float)
        assert '"threshold":5' in floating.canonical_json()
        assert '"tolerance":2' in floating.canonical_json()

    def test_milestone_7_specification_artifact_retains_canonical_shape_and_hash(self) -> None:
        artifact = Path(__file__).parent / "fixtures/milestone_7_specification.json"
        document = SpecificationDocument.from_json(artifact.read_text(encoding="utf-8"))

        assert document.content_hash() == (
            "16686255d3e8946316e26ac6684aa256d15e6be3fd401da323c3b0e03993060c"
        )
        assert sha256_bytes(artifact.read_bytes()) == (
            "068ff2ce3cc8feadc47ae40478c2e784283e867020168ee04f80818dac827c87"
        )
        assert document.canonical_json() == json.dumps(
            json.loads(artifact.read_text(encoding="utf-8")),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        assert set(document.to_dict()["verification"][0]) == set(
            json.loads(artifact.read_text(encoding="utf-8"))["verification"][0]
        )

    @pytest.mark.parametrize("value", [True, math.nan, math.inf, -math.inf, "5"])
    def test_invalid_numeric_assertion_values_are_rejected(self, value: object) -> None:
        payload = complete_document_dict()
        payload["verification"][0]["metric_assertions"][0]["threshold"] = value
        with pytest.raises(SpecificationError):
            SpecificationDocument.from_dict(payload)

    @pytest.mark.parametrize("operator", ["<", "<=", "==", "!=", ">=", ">"])
    def test_all_metric_assertion_operators_are_supported(self, operator: str) -> None:
        assertion = MetricAssertion("value", operator, 10, 0.5)
        actual = {"<": 10.4, "<=": 10.5, "==": 10.5, "!=": 10.6, ">=": 9.5, ">": 9.6}[operator]
        assert assertion.evaluate(actual)

    def test_equality_and_inequality_tolerances_are_consistent(self) -> None:
        assert MetricAssertion("m", "==", 1, 0.1).evaluate(1.1)
        assert not MetricAssertion("m", "==", 1, 0.1).evaluate(1.11)
        assert MetricAssertion("m", "<=", 1, 0.1).evaluate(1.1)
        assert MetricAssertion("m", ">=", 1, 0.1).evaluate(0.9)
        with pytest.raises(SpecificationError, match="non-negative"):
            MetricAssertion("m", "==", 1, -0.1).evaluate(1)


class TestStructuralValidation:
    def test_incomplete_draft_is_structurally_valid(self) -> None:
        SpecificationDocument.empty().validate_structural()

    @pytest.mark.parametrize(
        ("mutation", "message"),
        [
            (lambda data: data.update(schema_version="2.0"), "unsupported schema version"),
            (lambda data: data["requirements"][0].update(id="bad id"), "stable uppercase"),
            (lambda data: data["requirements"].append(dict(data["requirements"][0])), "duplicate"),
            (lambda data: data["use_cases"][0]["requirement_ids"].append("MISSING"), "unknown requirement"),
            (lambda data: data["risks"].append({
                "id": "RK1", "title": "Risk", "description": "Description", "severity": "low",
                "uncertainty": "low", "failure_modes": [], "detection_signals": [],
                "mitigations": [], "verification_ids": ["MISSING"]}), "unknown verification"),
            (lambda data: data["verification"][0]["validation_loop"].update(stagnation_limit=0), "positive integer"),
            (lambda data: data["verification"][0].update(timeout=0), "positive integer"),
            (lambda data: data["verification"][0].update(command_override="   "), "non-empty command"),
            (lambda data: data["verification"][0].update(declared_metrics=[""]), "non-empty string"),
            (lambda data: data["verification"][0]["metric_assertions"].append(
                dict(data["verification"][0]["metric_assertions"][0])), "duplicate assertion"),
        ],
    )
    def test_structural_rejections(self, mutation, message: str) -> None:
        payload = complete_document_dict()
        mutation(payload)
        with pytest.raises((SpecificationError, SpecificationValidationError), match=message):
            SpecificationDocument.from_dict(payload)

    @pytest.mark.parametrize(
        "working_directory",
        ["", "../escape", "child/../../escape", "/tmp/absolute", "C:\\absolute", "C:relative", "\\\\server\\share"],
    )
    def test_unsafe_working_directories_are_rejected(self, working_directory: str) -> None:
        with pytest.raises(SpecificationError):
            validate_working_directory(working_directory)

    def test_symlink_escape_is_rejected(self, tmp_path: Path) -> None:
        root = tmp_path / "worktree"
        outside = tmp_path / "outside"
        root.mkdir()
        outside.mkdir()
        (root / "link").symlink_to(outside, target_is_directory=True)
        with pytest.raises(SpecificationError, match="outside"):
            validate_working_directory("link/child", root)
        validate_working_directory("safe/child", root)

    def test_manual_case_cannot_block_or_execute_or_assert(self) -> None:
        payload = complete_document_dict()
        case = payload["verification"][0]
        case.update(automation="manual", blocking=True, command_override="pytest -q")
        with pytest.raises(SpecificationValidationError) as error:
            SpecificationDocument.from_dict(payload)
        messages = " ".join(issue.message for issue in error.value.issues)
        assert "cannot block" in messages
        assert "cannot define a command" in messages
        assert "cannot define metric assertions" in messages

    def test_directly_constructed_invalid_enum_is_rejected_at_runtime(self) -> None:
        document = complete_document()
        invalid = replace(document.requirements[0], priority="urgent")
        with pytest.raises(SpecificationValidationError, match="must be one of"):
            validate_structural(replace(document, requirements=(invalid, *document.requirements[1:])))


class TestApprovalValidation:
    def test_complete_document_is_approvable(self) -> None:
        validate_for_approval(complete_document())

    @pytest.mark.parametrize(
        ("mutation", "message"),
        [
            (lambda data: data.update(title=""), "title"),
            (lambda data: data.update(summary=""), "summary"),
            (lambda data: data.update(objectives=[]), "objectives"),
            (lambda data: data.update(in_scope=[]), "in_scope"),
            (lambda data: data.update(out_of_scope=[]), "out_of_scope"),
            (lambda data: data.update(stakeholders=[]), "stakeholders"),
            (lambda data: data.update(use_cases=[]), "use_cases"),
            (lambda data: data["use_cases"][0].update(main_flow=[]), "main_flow"),
            (lambda data: data["use_cases"][0].update(error_and_edge_cases=[]), "error_and_edge_cases"),
            (lambda data: data["requirements"][0].update(acceptance_criteria=[]), "acceptance_criteria"),
            (lambda data: data["requirements"][1].update(category="functional"), "quality requirement"),
            (lambda data: data["verification"][0].update(requirement_ids=["R1"]), "R2"),
            (lambda data: data.update(open_questions=["Which compatibility boundary applies?"]), "open_questions"),
            (lambda data: data["verification"][0].update(oracle=""), "oracle"),
            (lambda data: data["verification"][0].update(coverage_targets=[]), "coverage_targets"),
        ],
    )
    def test_approval_gates(self, mutation, message: str) -> None:
        payload = complete_document_dict()
        mutation(payload)
        document = SpecificationDocument.from_dict(payload)
        with pytest.raises(SpecificationValidationError, match=message):
            validate_for_approval(document)

    def test_unresolved_blocking_choices_prevent_approval(self) -> None:
        with pytest.raises(SpecificationValidationError, match="blocking suggested"):
            validate_for_approval(complete_document(), unresolved_blocking_decisions=1)

    def test_high_risk_requires_assurance_evidence(self) -> None:
        document = complete_document()
        risk = Risk(
            "RK1",
            "State corruption",
            "Repeated failures could corrupt state.",
            RiskSeverity.CRITICAL,
            RiskUncertainty.HIGH,
            (),
            (),
            (),
            ("VT1",),
        )
        bad_case = replace(
            document.verification[0],
            declared_metrics=(),
            metric_assertions=(),
            required_evidence=(),
            validation_loop=replace(document.verification[0].validation_loop, retain_evidence=False),
        )
        with pytest.raises(SpecificationValidationError) as error:
            validate_for_approval(replace(document, risks=(risk,), verification=(bad_case,)))
        messages = " ".join(issue.message for issue in error.value.issues)
        for expected in ("failure_modes", "detection_signals", "mitigations", "explicit metrics", "evidence retention"):
            assert expected in messages


class TestSpecificationSchema:
    def test_schema_is_strict_and_matches_runtime_serialization(self) -> None:
        schema = json.loads((Path(__file__).parents[1] / "specification.schema.json").read_text())
        assert schema["$schema"].endswith("2020-12/schema")
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"] == "1.0"
        assert schema["$defs"]["stableId"]["pattern"]
        for definition in ("useCase", "requirement", "specificationDecision", "risk", "validationLoop", "metricAssertion", "verificationCase"):
            assert schema["$defs"][definition]["additionalProperties"] is False
        verification = schema["$defs"]["verificationCase"]
        assert {
            "command_override",
            "working_directory",
            "timeout",
            "declared_metrics",
            "metric_assertions",
        } <= set(verification["required"])
        assert schema["$defs"]["metricAssertion"]["properties"]["operator"]["enum"] == [
            "<", "<=", "==", "!=", ">=", ">"
        ]
        assert schema["$defs"]["metricNameArray"]["uniqueItems"] is True
        serialized = json.loads(complete_document().pretty_json())
        assert set(serialized) == set(schema["required"])
        assert SpecificationDocument.from_dict(serialized).to_dict() == serialized


class TestSpecificationService:
    def test_lifecycle_revisions_attachment_and_immutable_artifacts(self, tmp_path: Path) -> None:
        database = tmp_path / "loop.sqlite3"
        service = SpecificationService(database, tmp_path / "artifacts")
        stored = service.create(tmp_path, complete_document(), creator="user", specification_id="SPEC1")
        assert stored.status == "draft"
        first_bytes = stored.artifact_path.read_bytes()
        assert service.list(tmp_path)[0]["id"] == "SPEC1"

        review = service.submit_for_review("SPEC1")
        assert review.status == "review"
        with pytest.raises(SpecificationStateError):
            service.revise("SPEC1", complete_document(), change_summary="bad", creator="user")
        assert service.return_to_draft("SPEC1").status == "draft"
        service.submit_for_review("SPEC1")
        approved = service.approve("SPEC1", approved_by="owner")
        assert approved.status == "approved"
        assert approved.approved_at

        revised_document = replace(complete_document(), summary="A deliberately revised summary.")
        revision = service.revise("SPEC1", revised_document, change_summary="Clarify summary", creator="owner")
        assert revision.version == 2
        assert revision.status == "draft"
        assert service.list(tmp_path)[0]["approved_version"] == 1
        assert approved.artifact_path.read_bytes() == first_bytes
        assert approved.artifact_path != revision.artifact_path

        with db.transaction(database) as conn:
            db.create_job(
                conn,
                job_id="J1",
                repo_path=str(tmp_path),
                worktree_path=str(tmp_path),
                branch=None,
                base_ref="HEAD",
                goal="Quick goal",
                constraints=[],
                acceptance=[],
                test_cmd="true",
                max_iterations=1,
                use_worktree=False,
            )
        service.attach_to_job("SPEC1", 1, "J1")
        with db.transaction(database) as conn:
            job = db.get_job(conn, "J1")
            assert job["specification_id"] == "SPEC1"
            assert job["specification_version"] == 1
            assert job["specification_content_hash"] == approved.canonical_content_hash
        with pytest.raises(SpecificationStateError):
            service.attach_to_job("SPEC1", 2, "J1")

    def test_unresolved_database_choice_blocks_service_approval(self, tmp_path: Path) -> None:
        database = tmp_path / "loop.sqlite3"
        service = SpecificationService(database, tmp_path / "artifacts")
        service.create(tmp_path, complete_document(), creator="user", specification_id="SPEC1")
        with db.transaction(database) as conn:
            now = db.utc_now()
            conn.execute(
                """
                INSERT INTO specification_decisions (
                    id, specification_id, source_version, topic, question, context,
                    options_json, recommendation, blocking, status, created_at, updated_at
                ) VALUES ('D1', 'SPEC1', 1, 'Compatibility', 'Which boundary?', 'Context',
                    ?, 'Keep compatibility', 1, 'unresolved', ?, ?)
                """,
                (db.to_json([{"name": "Keep compatibility"}, {"name": "Break compatibility"}]), now, now),
            )
        service.submit_for_review("SPEC1")
        listed = service.list_decisions("SPEC1")
        assert listed[0]["id"] == "D1"
        assert listed[0]["blocking"] is True
        assert listed[0]["options"] == [
            {"name": "Keep compatibility"},
            {"name": "Break compatibility"},
        ]
        assert "options_json" not in listed[0]
        with pytest.raises(SpecificationValidationError, match="blocking suggested"):
            service.approve("SPEC1", approved_by="owner")
        service.resolve_decision(
            "SPEC1",
            "D1",
            selected_option="Keep compatibility",
            rationale="The user selected compatibility.",
        )
        assert service.approve("SPEC1", approved_by="owner").status == "approved"
        assert service.supersede("SPEC1").status == "superseded"

    @pytest.mark.parametrize("target", ["canonical_json", "canonical_hash", "artifact"])
    def test_integrity_detects_independent_tampering(self, tmp_path: Path, target: str) -> None:
        root = tmp_path / target
        root.mkdir()
        database = root / "loop.sqlite3"
        service = SpecificationService(database, root / "artifacts")
        stored = service.create(root, complete_document(), creator="user", specification_id="SPEC1")
        if target == "canonical_json":
            with db.transaction(database) as conn:
                conn.execute(
                    "UPDATE specification_versions SET canonical_json = '{}' WHERE specification_id = 'SPEC1'"
                )
        elif target == "canonical_hash":
            with db.transaction(database) as conn:
                conn.execute(
                    "UPDATE specification_versions SET canonical_content_hash = ? WHERE specification_id = 'SPEC1'",
                    ("0" * 64,),
                )
        else:
            stored.artifact_path.write_bytes(stored.artifact_path.read_bytes() + b"\n")
        with pytest.raises(SpecificationIntegrityError):
            service.verify_integrity("SPEC1", 1)


class TestSpecificationMigrations:
    def test_legacy_database_migrates_idempotently_without_rewriting_rows(self, tmp_path: Path) -> None:
        database = tmp_path / "legacy.sqlite3"
        conn = sqlite3.connect(database)
        conn.executescript(
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
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                iteration INTEGER NOT NULL, goal TEXT NOT NULL,
                constraints_json TEXT NOT NULL, acceptance_json TEXT NOT NULL,
                test_cmd TEXT NOT NULL, status TEXT NOT NULL, created_by TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            INSERT INTO jobs VALUES (
                'J-legacy', '/repo', '/repo', NULL, 'HEAD', 'Original quick goal',
                '["keep"]', '["pass"]', 'true', 3, 0, 'planning', '',
                '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'
            );
            INSERT INTO tasks VALUES (
                'T-legacy', 'J-legacy', 0, 'Original task', '[]', '[]', 'true',
                'queued', 'controller', '2026-01-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00'
            );
            """
        )
        before = conn.execute("SELECT goal, constraints_json, acceptance_json, created_at FROM jobs").fetchone()
        conn.commit()
        conn.close()

        db.init_db(database)
        db.init_db(database)

        with db.transaction(database) as migrated:
            after = migrated.execute(
                "SELECT goal, constraints_json, acceptance_json, created_at FROM jobs"
            ).fetchone()
            assert tuple(after) == tuple(before)
            tables = {
                row[0]
                for row in migrated.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            assert {
                "specifications",
                "specification_versions",
                "specification_decisions",
                "specification_analyses",
            } <= tables
            job_columns = {row[1] for row in migrated.execute("PRAGMA table_info(jobs)")}
            task_columns = {row[1] for row in migrated.execute("PRAGMA table_info(tasks)")}
            assert {"specification_id", "specification_version"} <= job_columns
            assert {"requirement_ids_json", "verification_ids_json"} <= task_columns
            assert db.get_job(migrated, "J-legacy")["goal"] == "Original quick goal"
            task = db.get_task(migrated, "T-legacy")
            assert task["requirement_ids"] == []
            assert task["verification_ids"] == []
