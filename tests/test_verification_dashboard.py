from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from ai_loop import db
from ai_loop.verification_orchestrator import (
    VerificationExecutionError,
    build_verification_dashboard_projection,
    load_verification_dashboard_projection,
    record_manual_verification_acknowledgement,
    shape_dashboard_evidence,
)
from tests.test_specification_compiler import approved_service, create_quick_job


def artifact_metadata(
    *,
    name: str = "result-data",
    kind: str = "structured-data",
    media_type: str = "application/json",
    preview: str | None = '{"ok":true}',
    artifact_path: str | None = "/artifact/result.json",
    size: int = 11,
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "media_type": media_type,
        "description": "Trusted runtime evidence",
        "requirement_ids": ["R1"],
        "verification_id": "VT1",
        "comparison": None,
        "size": size,
        "sha256": "a" * 64,
        "artifact_path": artifact_path,
        "preview": preview,
        "measurements": {},
        "scenarios": [],
    }


def dashboard_manifest() -> dict[str, Any]:
    loop = {
        "maximum_correction_attempts": 3,
        "repetitions_per_attempt": 2,
        "stagnation_limit": 2,
        "escalation_condition": "Ask the owner",
        "retain_evidence": True,
    }
    common = {
        "requirement_ids": ["R1"],
        "risk_ids": [],
        "test_level": "acceptance",
        "working_directory": ".",
        "timeout": 30,
        "fixtures": [],
        "procedure": ["Run the case"],
        "pass_criteria": ["The result is correct"],
        "metrics": [],
        "metric_assertions": [],
        "validation_loop": loop,
    }
    return {
        "schema_version": "1.0",
        "specification": {
            "id": "SPEC1",
            "version": 1,
            "schema_version": "1.0",
            "content_hash": "b" * 64,
        },
        "work_items": [],
        "verification": [
            {
                **common,
                "verification_id": "VT1",
                "title": "Automated contract",
                "method": "deterministic",
                "automation": "automated",
                "blocking": True,
                "command": "verify",
                "command_source": "specification",
                "oracle": "Compare against independently authored expected values",
                "coverage_targets": [
                    "Boundary scenarios are reviewed",
                    {
                        "name": "scenario-rate",
                        "coverage_type": "scenario",
                        "description": "Scenario coverage measurement",
                        "measurement_key": "scenario.rate",
                        "operator": ">=",
                        "threshold": 0.9,
                        "tolerance": 0,
                        "required_scenarios": ["ordinary"],
                        "evidence_kind": "coverage",
                    },
                    {
                        "name": "recovery-notes",
                        "coverage_type": "scenario",
                        "description": "Text-only recovery review",
                        "measurement_key": None,
                        "operator": None,
                        "threshold": None,
                        "tolerance": None,
                        "required_scenarios": [],
                        "evidence_kind": None,
                    },
                ],
                "required_evidence": [
                    "Human-readable log description",
                    {
                        "name": "result-data",
                        "kind": "structured-data",
                        "media_type": "application/json",
                        "description": "Structured result",
                        "requirement_ids": ["R1"],
                    },
                ],
            },
            {
                **common,
                "verification_id": "VT2",
                "title": "Manual review",
                "method": "manual",
                "automation": "manual",
                "blocking": False,
                "command": None,
                "command_source": "manual",
                "oracle": "Maintainer judgment",
                "coverage_targets": ["Documentation review"],
                "required_evidence": ["Review note"],
            },
        ],
    }


def dashboard_summary(*, emitted: bool = True) -> tuple[dict[str, Any], ...]:
    evidence = artifact_metadata() if emitted else None
    return (
        {
            "verification_id": "VT1",
            "title": "Automated contract",
            "requirement_ids": ["R1"],
            "blocking": True,
            "automation": "automated",
            "realization_state": "executable_but_failing",
            "status": "executable_but_failing",
            "attempts_completed": 1,
            "repetitions_per_attempt": 2,
            "latest_metrics": {"score": 0.8},
            "latest_evidence": [] if evidence is None else [evidence],
            "coverage_results": (
                []
                if not emitted
                else [
                    {
                        "name": "scenario-rate",
                        "enforcement": "machine_enforced",
                        "status": "failed",
                        "actual": 0.8,
                    }
                ]
            ),
            "failed_assertions": [{"metric": "score", "passed": False}],
            "stagnation_count": 1,
            "stagnation_series": 2,
            "metric_trend": "unchanged",
            "escalation_report": None,
            "last_error": "score is low",
            "evidence_freshness": "pending",
            "missing_evidence_producers": [],
        },
        {
            "verification_id": "VT2",
            "title": "Manual review",
            "requirement_ids": ["R1"],
            "blocking": False,
            "automation": "manual",
            "realization_state": "manual_pending",
            "status": "manual_pending",
            "attempts_completed": 0,
            "repetitions_per_attempt": 2,
            "latest_metrics": None,
            "latest_evidence": [],
            "coverage_results": [],
            "failed_assertions": [],
            "stagnation_count": 0,
            "stagnation_series": 0,
            "escalation_report": None,
        },
    )


def repetition() -> dict[str, Any]:
    return {
        "id": 9,
        "job_id": "J1",
        "task_id": "T1",
        "worker_run_id": "RUN1",
        "verification_id": "VT1",
        "attempt": 1,
        "repetition": 1,
        "command": "verify",
        "working_directory": ".",
        "timeout_seconds": 30,
        "status": "failed",
        "return_code": 1,
        "output": "x" * 5000,
        "output_truncated": False,
        "metrics": {"score": 0.8},
        "assertion_results": [{"metric": "score", "passed": False}],
        "evidence": [artifact_metadata()],
        "coverage_results": [],
        "elapsed_seconds": 0.2,
        "timed_out": False,
        "error": "score is low",
        "termination_details": None,
        "started_at": "start",
        "finished_at": "finish",
    }


def test_projection_exposes_complete_case_rows_attempts_and_manual_state() -> None:
    rows = build_verification_dashboard_projection(
        dashboard_manifest(),
        dashboard_summary(),
        repetitions=[repetition()],
        manual_acknowledgements=[
            {
                "id": 4,
                "job_id": "J1",
                "verification_id": "VT2",
                "acknowledged_by": "owner",
                "note": "Reviewed documentation",
                "created_at": "now",
            }
        ],
    )

    automated, manual = rows
    assert {
        "verification_id",
        "title",
        "requirement_ids",
        "blocking",
        "automation",
        "realization_state",
        "runtime_status",
        "attempt_count",
        "repetitions",
        "repetitions_per_attempt",
        "latest_metrics",
        "failed_assertions",
        "stagnation_count",
        "stagnation_series",
        "metric_trend",
        "escalation",
    } <= set(automated)
    assert automated["verification_id"] == "VT1"
    assert automated["requirement_ids"] == ["R1"]
    assert automated["blocking"] is True
    assert automated["automation"] == "automated"
    assert automated["realization_state"] == "executable_but_failing"
    assert automated["runtime_status"] == "executable_but_failing"
    assert automated["attempt_count"] == 1
    assert automated["repetitions"] == 1
    assert automated["repetitions_per_attempt"] == 2
    assert automated["latest_metrics"] == {"score": 0.8}
    assert automated["failed_assertions"][0]["metric"] == "score"
    assert (automated["stagnation_count"], automated["stagnation_series"]) == (1, 2)
    assert len(automated["attempts"][0]["repetitions"][0]["output_preview"]) == 4000
    assert automated["attempts"][0]["repetitions"][0]["output_preview_truncated"] is True
    assert automated["can_acknowledge_manual"] is False
    assert manual["runtime_status"] == "manual_pending"
    assert manual["can_acknowledge_manual"] is True
    assert manual["manual_acknowledgements"][0]["acknowledged_by"] == "owner"
    assert manual["manual_acknowledgement_changes_status"] is False


def test_contract_classification_never_promotes_descriptive_prose() -> None:
    row = build_verification_dashboard_projection(
        dashboard_manifest(), dashboard_summary()
    )[0]

    assert row["contracts"]["oracle"][0]["enforcement"] == "DESCRIPTIVE"
    assert [item["enforcement"] for item in row["contracts"]["coverage_targets"]] == [
        "DESCRIPTIVE",
        "MACHINE-ENFORCED",
        "DESCRIPTIVE",
    ]
    assert [item["enforcement"] for item in row["contracts"]["evidence_requirements"]] == [
        "DESCRIPTIVE",
        "MACHINE-ENFORCED",
    ]

    not_executed = build_verification_dashboard_projection(
        dashboard_manifest(), dashboard_summary(emitted=False)
    )[0]
    assert not_executed["contracts"]["coverage_targets"][1]["enforcement"] == "REALIZED"
    assert not_executed["contracts"]["evidence_requirements"][1]["enforcement"] == "REALIZED"
    assert not_executed["contracts"]["coverage_targets"][2]["enforcement"] == "DESCRIPTIVE"


def test_evidence_shaping_bounds_text_and_never_previews_binary() -> None:
    text = shape_dashboard_evidence(
        artifact_metadata(preview="z" * 9000), preview_limit=100
    )
    binary = shape_dashboard_evidence(
        artifact_metadata(
            kind="image",
            media_type="image/png",
            preview="must never be shown",
            artifact_path="/artifact/large.png",
            size=20_000_000,
        )
    )

    assert text["text_preview"] == "z" * 100
    assert text["preview_truncated"] is True
    assert binary["text_preview"] is None
    assert binary["preview_available"] is False
    assert binary["binary_or_large_metadata_only"] is True
    assert binary["artifact_path"] == "/artifact/large.png"
    assert binary["sha256"] == "a" * 64


def test_manual_acknowledgement_is_append_only_and_does_not_change_state(
    tmp_path: Path,
) -> None:
    service, _approved = approved_service(tmp_path, command_override="verify")
    service.create_formal_job(
        specification_id="SPEC1",
        specification_version=1,
        job_id="JFORMAL",
        repo_path=str(tmp_path),
        worktree_path=str(tmp_path),
        branch=None,
        base_ref="HEAD",
        test_cmd="auto",
        max_iterations=2,
        use_worktree=False,
    )

    acknowledgement = record_manual_verification_acknowledgement(
        service.db_path,
        "JFORMAL",
        "VT2",
        acknowledged_by=" owner ",
        note=" Documentation reviewed ",
    )

    assert acknowledgement["acknowledged_by"] == "owner"
    assert acknowledgement["note"] == "Documentation reviewed"
    with db.transaction(service.db_path) as conn:
        rows = db.list_verification_manual_acknowledgements(conn, "JFORMAL")
        state = conn.execute(
            """
            SELECT status FROM job_verification_states
            WHERE job_id = 'JFORMAL' AND verification_id = 'VT2'
            """
        ).fetchone()[0]
        event = conn.execute(
            "SELECT kind FROM events WHERE job_id = 'JFORMAL' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    assert rows == [acknowledgement]
    assert state == "manual_pending"
    assert event == "manual_verification_acknowledged"
    dashboard = load_verification_dashboard_projection(service.db_path, "JFORMAL")
    assert dashboard is not None
    manual_row = next(item for item in dashboard if item["verification_id"] == "VT2")
    assert manual_row["runtime_status"] == "manual_pending"
    assert manual_row["manual_acknowledgements"] == [acknowledgement]


def test_manual_acknowledgement_rejects_automated_and_blocking_cases(
    tmp_path: Path,
) -> None:
    service, _approved = approved_service(tmp_path, command_override="verify")
    service.create_formal_job(
        specification_id="SPEC1",
        specification_version=1,
        job_id="JFORMAL",
        repo_path=str(tmp_path),
        worktree_path=str(tmp_path),
        branch=None,
        base_ref="HEAD",
        test_cmd="auto",
        max_iterations=2,
        use_worktree=False,
    )
    with pytest.raises(VerificationExecutionError, match="automated"):
        record_manual_verification_acknowledgement(
            service.db_path,
            "JFORMAL",
            "VT1",
            acknowledged_by="owner",
            note="Cannot override automation",
        )

    with db.transaction(service.db_path) as conn:
        raw = conn.execute(
            "SELECT canonical_json FROM verification_manifests WHERE job_id = 'JFORMAL'"
        ).fetchone()[0]
        manifest = json.loads(raw)
        manual = next(
            item for item in manifest["verification"] if item["verification_id"] == "VT2"
        )
        manual["blocking"] = True
        conn.execute(
            "UPDATE verification_manifests SET canonical_json = ? WHERE job_id = 'JFORMAL'",
            (json.dumps(manifest, sort_keys=True, separators=(",", ":")),),
        )
        with pytest.raises(ValueError, match="blocking"):
            db.create_verification_manual_acknowledgement(
                conn,
                job_id="JFORMAL",
                verification_id="VT2",
                acknowledged_by="owner",
                note="Cannot override a blocking case",
            )


def test_quick_goal_dashboard_and_acknowledgement_are_strictly_isolated(
    tmp_path: Path,
) -> None:
    database = tmp_path / "loop.sqlite3"
    db.init_db(database)
    create_quick_job(database, "JQUICK", tmp_path)

    assert load_verification_dashboard_projection(database, "JQUICK") is None
    with pytest.raises(VerificationExecutionError, match="Quick Goal"):
        record_manual_verification_acknowledgement(
            database,
            "JQUICK",
            "VT2",
            acknowledged_by="owner",
            note="Not a formal job",
        )
    with db.transaction(database) as conn:
        assert db.list_verification_manual_acknowledgements(conn, "JQUICK") == []


def test_manual_acknowledgement_migration_is_additive_and_idempotent(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE legacy_marker (value TEXT NOT NULL)")
        conn.execute("INSERT INTO legacy_marker VALUES ('unchanged')")

    db.init_db(database)
    db.init_db(database)

    with sqlite3.connect(database) as conn:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(verification_manual_acknowledgements)"
            )
        }
        marker = conn.execute("SELECT value FROM legacy_marker").fetchone()[0]
    assert columns == {
        "id",
        "job_id",
        "verification_id",
        "acknowledged_by",
        "note",
        "created_at",
    }
    assert marker == "unchanged"


def test_projection_rejects_acknowledgement_attached_to_automated_case() -> None:
    with pytest.raises(VerificationExecutionError, match="invalid manual acknowledgement"):
        build_verification_dashboard_projection(
            dashboard_manifest(),
            dashboard_summary(),
            manual_acknowledgements=[
                {
                    "verification_id": "VT1",
                    "acknowledged_by": "owner",
                    "note": "invalid",
                }
            ],
        )
