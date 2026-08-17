from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from ai_loop import db
from ai_loop.specification_compiler import ManifestIntegrityError, compile_verification_manifest
from ai_loop.specification_workflow import analyze_specification_change
from ai_loop.specifications import SpecificationDocument, SpecificationService, SpecificationStateError
from ai_loop.verification_orchestrator import RunnerResult, run_task_verification
from tests.test_specification_compiler import create_quick_job, document


def coverage(name: str, threshold: float) -> dict[str, object]:
    return {
        "name": name,
        "coverage_type": "scenario",
        "description": f"Measured {name}",
        "measurement_key": f"{name}.rate",
        "operator": ">=",
        "threshold": threshold,
        "tolerance": 0.01,
        "required_scenarios": ["ordinary", "invalid"],
        "evidence_kind": "coverage",
    }


def initial_document() -> SpecificationDocument:
    payload = document(command_override="verify VT1").to_dict()
    payload["decisions"] = [
        {
            "topic": "Storage",
            "selected_decision": "Keep the current format",
            "rationale": "Compatibility",
            "rejected_alternatives": ["Replace it"],
            "consequences": ["Existing data remains readable"],
        },
        {
            "topic": "Legacy mode",
            "selected_decision": "Retain it",
            "rationale": "Existing users",
            "rejected_alternatives": ["Remove it"],
            "consequences": ["Compatibility tests remain"],
        },
    ]
    payload["verification"][0]["coverage_targets"] = [coverage("scenario-rate", 0.8)]
    vt3 = copy.deepcopy(payload["verification"][0])
    vt3.update(
        id="VT3",
        title="Unchanged quality contract",
        requirement_ids=["R2"],
        command_override="verify VT3",
        declared_metrics=["quality_score", "legacy_count"],
        metric_assertions=[
            {"metric": "quality_score", "operator": ">=", "threshold": 1, "tolerance": 0},
            {"metric": "legacy_count", "operator": "==", "threshold": 1, "tolerance": 0},
        ],
        coverage_targets=[coverage("quality-rate", 0.8)],
    )
    payload["verification"].append(vt3)
    return SpecificationDocument.from_dict(payload)


def create_approved_service(tmp_path: Path) -> tuple[SpecificationService, object]:
    service = SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts")
    service.create(tmp_path, initial_document(), creator="author", specification_id="SPEC1")
    service.submit_for_review("SPEC1")
    return service, service.approve("SPEC1", approved_by="owner")


def approve_revision(
    service: SpecificationService, payload: dict[str, object], summary: str
):
    service.revise(
        "SPEC1",
        SpecificationDocument.from_dict(payload),
        creator="author",
        change_summary=summary,
    )
    service.submit_for_review("SPEC1")
    return service.approve("SPEC1", approved_by="owner")


def create_formal(service: SpecificationService, root: Path, job_id: str = "JFORMAL"):
    return service.create_formal_job(
        specification_id="SPEC1",
        specification_version=1,
        job_id=job_id,
        repo_path=str(root),
        worktree_path=str(root),
        branch=None,
        base_ref="HEAD",
        test_cmd="pytest -q",
        max_iterations=6,
        use_worktree=False,
    )


class PassingRetargetRunner:
    def run(self, **_kwargs: object) -> RunnerResult:
        envelope = {
            "metrics": {"duration_seconds": 1},
            "items": [
                {
                    "name": "scenario-coverage",
                    "kind": "coverage",
                    "inline": {
                        "measurements": {"scenario-rate.rate": 0.95},
                        "scenarios": ["ordinary", "invalid"],
                    },
                    "media_type": "application/json",
                    "description": "Retarget coverage",
                    "requirement_ids": ["R1", "R2"],
                    "verification_id": "VT1",
                }
            ],
        }
        return RunnerResult(
            output="AI_LOOP_EVIDENCE=" + json.dumps(envelope),
            return_code=0,
            elapsed_seconds=0.1,
        )


def test_stable_id_diff_reports_every_contract_family_deterministically(tmp_path: Path) -> None:
    service, previous = create_approved_service(tmp_path)
    payload = previous.document.to_dict()
    payload["requirements"][0]["statement"] = "The system shall perform the revised operation."
    added_requirement = copy.deepcopy(payload["requirements"][0])
    added_requirement.update(id="R3", priority="could", title="Optional interface")
    payload["requirements"].append(added_requirement)
    payload["use_cases"][0]["requirement_ids"].append("R3")
    payload["decisions"] = [
        {
            **payload["decisions"][0],
            "selected_decision": "Use the compatible versioned format",
        },
        {
            "topic": "Retries",
            "selected_decision": "Bound retries",
            "rationale": "Predictability",
            "rejected_alternatives": ["Unbounded retries"],
            "consequences": ["Exhaustion is visible"],
        },
    ]
    payload["risks"][0]["mitigations"] = ["Validate and commit atomically"]
    payload["risks"].append(
        {
            "id": "RK2",
            "title": "Retry exhaustion",
            "description": "Retries may be exhausted.",
            "severity": "medium",
            "uncertainty": "low",
            "failure_modes": ["Operation remains incomplete"],
            "detection_signals": ["Retry counter reaches its bound"],
            "mitigations": ["Escalate with evidence"],
            "verification_ids": ["VT1"],
        }
    )
    vt1 = payload["verification"][0]
    vt1["requirement_ids"].append("R3")
    vt1["command_override"] = "verify revised VT1"
    vt1["metric_assertions"][0]["threshold"] = 4
    vt1["coverage_targets"][0]["threshold"] = 0.9
    vt1["coverage_targets"].append(coverage("boundary-rate", 1.0))
    payload["verification"][2]["metric_assertions"] = payload["verification"][2]["metric_assertions"][:1]
    payload["verification"][2]["coverage_targets"] = ["Quality scenarios remain covered"]
    payload["verification"] = [payload["verification"][0], payload["verification"][2]]
    vt4 = copy.deepcopy(payload["verification"][0])
    vt4.update(
        id="VT4",
        title="Optional interface verification",
        requirement_ids=["R3"],
        command_override="verify VT4",
        declared_metrics=["interface_count"],
        metric_assertions=[
            {"metric": "interface_count", "operator": ">=", "threshold": 1, "tolerance": 0}
        ],
        coverage_targets=[coverage("interface-rate", 1.0)],
    )
    payload["verification"].append(vt4)
    newer = approve_revision(service, payload, "Complete contract changes")

    first = analyze_specification_change(
        previous,
        newer,
        previous_manifest=compile_verification_manifest(previous, "pytest -q"),
        newer_manifest=compile_verification_manifest(newer, "pytest -q"),
    )
    second = analyze_specification_change(
        previous,
        newer,
        previous_manifest=compile_verification_manifest(previous, "pytest -q"),
        newer_manifest=compile_verification_manifest(newer, "pytest -q"),
    )

    assert first == second
    assert list(first["changes"]) == [
        "requirements",
        "decisions",
        "risks",
        "verification_cases",
        "commands",
        "metric_assertions",
        "coverage_targets",
    ]
    assert first["changes"]["requirements"]["added"][0]["stable_id"] == "R3"
    assert first["changes"]["requirements"]["changed"][0]["stable_id"] == "R1"
    assert first["changes"]["decisions"]["removed"][0]["stable_id"] == "Legacy mode"
    assert first["changes"]["risks"]["changed"][0]["stable_id"] == "RK1"
    assert first["changes"]["verification_cases"]["removed"][0]["stable_id"] == "VT2"
    assert first["changes"]["commands"]["changed"][0]["stable_id"] == "VT1"
    assert first["changes"]["metric_assertions"]["changed"][0]["stable_id"] == "VT1:duration_seconds"
    assert first["changes"]["coverage_targets"]["changed"][0]["stable_id"] == "VT1:scenario-rate"


def test_retarget_persists_hash_checked_impact_and_selectively_invalidates(tmp_path: Path) -> None:
    service, previous = create_approved_service(tmp_path)
    original_manifest = create_formal(service, tmp_path)
    original_manifest_bytes = original_manifest.artifact_path.read_bytes()
    original_spec_bytes = previous.artifact_path.read_bytes()
    with db.transaction(service.db_path) as conn:
        db.create_task(
            conn,
            task_id="TOLD",
            job_id="JFORMAL",
            iteration=1,
            goal="Historical verification",
            constraints=[],
            acceptance=[],
            test_cmd="pytest -q",
            created_by="test",
            requirement_ids=["R1", "R2"],
            verification_ids=["VT1", "VT3"],
        )
        for verification_id, metric in (("VT1", "duration_seconds"), ("VT3", "quality_score")):
            db.create_verification_repetition(
                conn,
                job_id="JFORMAL",
                task_id="TOLD",
                worker_run_id=None,
                verification_id=verification_id,
                attempt=1,
                repetition=1,
                command=f"verify {verification_id}",
                working_directory=str(tmp_path),
                timeout_seconds=60,
                status="passed",
                return_code=0,
                output="passed",
                output_truncated=False,
                metrics={metric: 1.0},
                assertion_results=[],
                evidence=[],
                coverage_results=[],
                elapsed_seconds=0.1,
                timed_out=False,
                error=None,
                termination_details=None,
                started_at="2026-08-16T10:00:00+00:00",
                finished_at="2026-08-16T10:00:01+00:00",
            )
            conn.execute(
                """
                UPDATE job_verification_states
                SET status = 'passing', attempts_completed = 1
                WHERE job_id = 'JFORMAL' AND verification_id = ?
                """,
                (verification_id,),
            )

    payload = previous.document.to_dict()
    payload["requirements"][0]["statement"] = "The system shall perform the revised operation."
    payload["verification"][0]["command_override"] = "verify revised VT1"
    payload["verification"][0]["metric_assertions"][0]["threshold"] = 4
    newer = approve_revision(service, payload, "Revise R1 and VT1")

    result = service.attach_newer_approved_revision("JFORMAL", "SPEC1", newer.version)

    assert result.manifest.specification_version == 2
    assert result.impact.result["previous_specification"]["version"] == 1
    assert result.impact.result["new_specification"]["version"] == 2
    assert result.impact.artifact_path.name == "change-impact-v0001-to-v0002.json"
    assert service.verify_job_change_impact(result.impact.id) == result.impact
    assert original_manifest.artifact_path.read_bytes() == original_manifest_bytes
    assert previous.artifact_path.read_bytes() == original_spec_bytes
    assert service.load("SPEC1", 1).canonical_content_hash == previous.canonical_content_hash

    with db.transaction(service.db_path) as conn:
        job = db.get_job(conn, "JFORMAL")
        states = {
            row["verification_id"]: dict(row)
            for row in conn.execute(
                "SELECT * FROM job_verification_states WHERE job_id = 'JFORMAL'"
            )
        }
        repetitions = db.list_verification_repetitions(conn, "JFORMAL")
        task = db.get_task(conn, result.task_id)
        event = conn.execute(
            "SELECT * FROM events WHERE job_id = 'JFORMAL' AND kind = 'approved_specification_retargeted'"
        ).fetchone()
        original_row = conn.execute(
            "SELECT * FROM verification_manifests WHERE job_id = 'JFORMAL'"
        ).fetchone()
        revisions = conn.execute(
            "SELECT COUNT(*) FROM verification_manifest_revisions WHERE job_id = 'JFORMAL'"
        ).fetchone()[0]
    assert job["specification_version"] == 2
    assert states["VT1"]["status"] == "unrealized"
    assert states["VT1"]["attempt_offset"] == 1
    assert states["VT3"]["status"] == "passing"
    assert states["VT3"]["attempt_offset"] == 0
    assert len(repetitions) == 2  # evidence history remains append-only
    assert task["verification_ids"] == ["VT1", "VT2"]
    assert "VT3" not in task["verification_ids"]
    assert event is not None
    event_payload = json.loads(event["payload_json"])
    assert event_payload["impact_content_hash"] == result.impact.canonical_content_hash
    assert original_row["canonical_content_hash"] == original_manifest.canonical_content_hash
    assert revisions == 1

    attempts = run_task_verification(
        service.db_path,
        "JFORMAL",
        result.task_id,
        result.manifest.manifest,
        PassingRetargetRunner(),
    )
    assert attempts[0].attempt == 2  # append-only global history
    assert attempts[0].passed is True, attempts[0].repetitions[0].errors
    with db.transaction(service.db_path) as conn:
        state = conn.execute(
            """
            SELECT status, attempts_completed, attempt_offset
            FROM job_verification_states
            WHERE job_id = 'JFORMAL' AND verification_id = 'VT1'
            """
        ).fetchone()
    assert tuple(state) == ("passing", 1, 1)  # policy budget restarted for the new contract

    result.impact.artifact_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ManifestIntegrityError, match="artifact hash mismatch"):
        service.verify_job_change_impact(result.impact.id)


def test_change_migration_is_additive_idempotent_and_quick_goal_isolated(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, repo_path TEXT NOT NULL, worktree_path TEXT NOT NULL,
                branch TEXT, base_ref TEXT NOT NULL, goal TEXT NOT NULL,
                constraints_json TEXT NOT NULL, acceptance_json TEXT NOT NULL,
                test_cmd TEXT NOT NULL, max_iterations INTEGER NOT NULL,
                use_worktree INTEGER NOT NULL, status TEXT NOT NULL,
                history_summary TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO jobs VALUES (
                'LEGACY', ?, ?, NULL, 'HEAD', 'Keep me', '[]', '[]', 'auto', 2,
                0, 'planning', '', 'before', 'before'
            )
            """,
            (str(tmp_path), str(tmp_path)),
        )
    db.init_db(database)
    db.init_db(database)
    with db.transaction(database) as conn:
        assert db.get_job(conn, "LEGACY")["goal"] == "Keep me"
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"verification_manifest_revisions", "specification_change_impacts"} <= tables
        columns = {row[1] for row in conn.execute("PRAGMA table_info(job_verification_states)")}
        assert "attempt_offset" in columns

    service = SpecificationService(database, tmp_path / "artifacts")
    create_quick_job(database, "JQUICK", tmp_path)
    with pytest.raises(SpecificationStateError, match="Quick Goal"):
        service.attach_newer_approved_revision("JQUICK", "SPEC1", 2)
    with db.transaction(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM specification_change_impacts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM verification_manifest_revisions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM tasks WHERE job_id = 'JQUICK'").fetchone()[0] == 0
