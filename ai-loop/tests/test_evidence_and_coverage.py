from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from ai_loop import db
from ai_loop.specification_compiler import compile_verification_manifest
from ai_loop.specifications import (
    CoverageTarget,
    CoverageType,
    EvidenceDeclaration,
    EvidenceKind,
    SpecificationDocument,
    SpecificationError,
    SpecificationService,
)
from ai_loop.verification_orchestrator import (
    EvidenceAdapterResult,
    RepetitionStatus,
    RunnerResult,
    VerificationExecutionError,
    evaluate_coverage_targets,
    parse_numeric_metrics,
    parse_structured_evidence,
    run_case_attempt,
    run_task_verification,
)
from tests.test_specification_compiler import approved_service
from tests.test_specifications import complete_document_dict
from tests.test_task_traceability import MANIFEST


def evidence_item(**updates: Any) -> dict[str, Any]:
    item = {
        "name": "coverage-report",
        "kind": "coverage",
        "inline": {"measurements": {"coverage.rate": 0.95}, "scenarios": ["ordinary"]},
        "media_type": "application/json",
        "description": "Generic coverage measurements",
        "requirement_ids": ["R1"],
        "verification_id": "VT1",
    }
    item.update(updates)
    return item


def evidence_output(*items: dict[str, Any], metrics: dict[str, Any] | None = None) -> str:
    envelope: dict[str, Any] = {"items": list(items)}
    if metrics is not None:
        envelope["metrics"] = metrics
    return "AI_LOOP_EVIDENCE=" + json.dumps(envelope, sort_keys=True, separators=(",", ":"))


def runtime_case() -> dict[str, Any]:
    value = copy.deepcopy(MANIFEST["verification"][0])
    value["command"] = "verify"
    value["metrics"] = []
    value["metric_assertions"] = []
    value["required_evidence"] = []
    value["coverage_targets"] = []
    return value


class FakeRunner:
    def __init__(self, output: str):
        self.output = output

    def run(self, **_kwargs: Any) -> RunnerResult:
        return RunnerResult(output=self.output, return_code=0, elapsed_seconds=0.1)


def test_evidence_envelope_and_metric_only_backward_compatibility(tmp_path: Path) -> None:
    output = evidence_output(evidence_item(), metrics={"score": 4})
    artifacts = parse_structured_evidence(
        output,
        verification_id="VT1",
        requirement_ids=["R1"],
        worktree=tmp_path,
        artifact_directory=tmp_path / "artifacts",
    )

    assert artifacts[0].measurements == {"coverage.rate": 0.95}
    assert parse_numeric_metrics(output) == {"score": 4.0}
    assert parse_numeric_metrics('AI_LOOP_METRICS={"metrics":{"score":3}}') == {
        "score": 3.0
    }


def test_orchestrator_computes_inline_size_and_hash_and_rejects_bad_claim(
    tmp_path: Path,
) -> None:
    inline = {"measurements": {"coverage.rate": 0.95}, "scenarios": ["ordinary"]}
    payload = json.dumps(
        inline, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    artifact = parse_structured_evidence(
        evidence_output(evidence_item(inline=inline)),
        verification_id="VT1",
        requirement_ids=["R1"],
        worktree=tmp_path,
    )[0]
    assert artifact.size == len(payload)
    assert artifact.sha256 == hashlib.sha256(payload).hexdigest()

    with pytest.raises(VerificationExecutionError, match="untrusted claimed hash"):
        parse_structured_evidence(
            evidence_output(evidence_item(inline=inline, sha256="0" * 64)),
            verification_id="VT1",
            requirement_ids=["R1"],
            worktree=tmp_path,
        )


@pytest.mark.parametrize(
    ("path_value", "message"),
    [
        ("../outside.bin", "parent traversal"),
        ("/tmp/outside.bin", "must not be absolute"),
        (r"C:\\outside.bin", "must not be absolute"),
        ("missing.bin", "does not exist"),
    ],
)
def test_evidence_path_security_rejections(
    tmp_path: Path, path_value: str, message: str
) -> None:
    item = evidence_item(kind="image", inline=None, path=path_value, media_type="image/png")
    with pytest.raises(VerificationExecutionError, match=message):
        parse_structured_evidence(
            evidence_output(item),
            verification_id="VT1",
            requirement_ids=["R1"],
            worktree=tmp_path,
            artifact_directory=tmp_path / "artifacts",
        )


def test_evidence_symlink_escape_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.bin"
    outside.write_bytes(b"outside")
    (tmp_path / "escaped.bin").symlink_to(outside)
    item = evidence_item(kind="image", inline=None, path="escaped.bin", media_type="image/png")

    with pytest.raises(VerificationExecutionError, match="outside"):
        parse_structured_evidence(
            evidence_output(item),
            verification_id="VT1",
            requirement_ids=["R1"],
            worktree=tmp_path,
            artifact_directory=tmp_path / "artifacts",
        )


def test_evidence_oversize_and_unsupported_inline_data_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "large.bin").write_bytes(b"1234")
    file_item = evidence_item(
        kind="image", inline=None, path="large.bin", media_type="image/png"
    )
    with pytest.raises(VerificationExecutionError, match="exceeds 3 bytes"):
        parse_structured_evidence(
            evidence_output(file_item),
            verification_id="VT1",
            requirement_ids=["R1"],
            worktree=tmp_path,
            artifact_directory=tmp_path / "artifacts",
            max_artifact_bytes=3,
        )

    with pytest.raises(VerificationExecutionError, match="structured object or array"):
        parse_structured_evidence(
            evidence_output(evidence_item(inline="not structured")),
            verification_id="VT1",
            requirement_ids=["R1"],
            worktree=tmp_path,
        )


def test_binary_artifact_is_copied_and_sqlite_contains_only_metadata_and_preview(
    tmp_path: Path,
) -> None:
    secret_payload = b"\x00binary-secret-payload\xff"
    (tmp_path / "result.bin").write_bytes(secret_payload)
    service, _approved = approved_service(tmp_path, command_override="verify")
    stored = service.create_formal_job(
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
    with db.transaction(service.db_path) as conn:
        db.create_task(
            conn,
            task_id="T1",
            job_id="JFORMAL",
            iteration=0,
            goal="Verify",
            constraints=[],
            acceptance=[],
            test_cmd="verify",
            created_by="test",
            requirement_ids=["R1"],
            verification_ids=[],
        )
    item = evidence_item(
        name="binary-result",
        kind="image",
        inline=None,
        path="result.bin",
        media_type="application/octet-stream",
    )
    output = (
        'AI_LOOP_METRICS={"metrics":{"duration_seconds":1}}\n'
        + evidence_output(item)
    )

    result = run_task_verification(
        service.db_path, "JFORMAL", "T1", stored.manifest, FakeRunner(output)
    )
    assert result[0].passed is True
    with db.transaction(service.db_path) as conn:
        raw = conn.execute(
            "SELECT evidence_json FROM verification_repetitions WHERE job_id = 'JFORMAL'"
        ).fetchone()[0]
        row = db.list_verification_repetitions(conn, "JFORMAL")[0]
    binary = next(item for item in row["evidence"] if item["name"] == "binary-result")
    assert Path(binary["artifact_path"]).read_bytes() == secret_payload
    assert binary["preview"] is None
    assert "inline_value" not in binary
    assert "binary-secret-payload" not in raw
    Path(binary["artifact_path"]).write_bytes(b"tampered")
    with db.transaction(service.db_path) as conn:
        with pytest.raises(ValueError, match="integrity mismatch"):
            db.list_verification_repetitions(conn, "JFORMAL")


@pytest.mark.parametrize(
    ("operator", "threshold", "tolerance", "actual", "expected"),
    [
        ("<", 1.0, 0.1, 1.05, True),
        ("<=", 1.0, 0.1, 1.1, True),
        ("==", 1.0, 0.1, 1.1, True),
        ("!=", 1.0, 0.1, 1.1, False),
        (">=", 1.0, 0.1, 0.9, True),
        (">", 1.0, 0.1, 0.95, True),
    ],
)
def test_coverage_target_operators_and_tolerance(
    tmp_path: Path,
    operator: str,
    threshold: float,
    tolerance: float,
    actual: float,
    expected: bool,
) -> None:
    evidence = parse_structured_evidence(
        evidence_output(
            evidence_item(inline={"measurements": {"coverage.rate": actual}, "scenarios": ["ordinary"]})
        ),
        verification_id="VT1",
        requirement_ids=["R1"],
        worktree=tmp_path,
    )
    target = {
        "name": "ordinary-coverage",
        "coverage_type": "scenario",
        "description": "Ordinary scenario coverage",
        "measurement_key": "coverage.rate",
        "operator": operator,
        "threshold": threshold,
        "tolerance": tolerance,
        "required_scenarios": ["ordinary"],
        "evidence_kind": "coverage",
    }
    result = evaluate_coverage_targets([target], evidence)[0]
    assert result.passed is expected
    assert result.enforcement == "machine_enforced"
    assert result.actual == actual


def test_descriptive_and_machine_enforced_coverage_are_distinct(tmp_path: Path) -> None:
    descriptive = {
        "name": "platform-review",
        "coverage_type": "platform",
        "description": "Review supported platforms",
        "measurement_key": None,
        "operator": None,
        "threshold": None,
        "tolerance": None,
        "required_scenarios": [],
        "evidence_kind": None,
    }
    machine = {
        "name": "branch-rate",
        "coverage_type": "branch",
        "description": "Measured branches",
        "measurement_key": "branch.rate",
        "operator": ">=",
        "threshold": 0.8,
        "tolerance": 0,
        "required_scenarios": ["ordinary", "boundary"],
        "evidence_kind": "coverage",
    }
    results = evaluate_coverage_targets(["Legacy prose", descriptive, machine], ())
    assert [item.enforcement for item in results] == [
        "descriptive",
        "descriptive",
        "machine_enforced",
    ]
    assert results[2].status == "failed"
    assert "missing emitted coverage evidence" in str(results[2].error)


def test_structured_required_evidence_is_a_runtime_gate(tmp_path: Path) -> None:
    case = runtime_case()
    case["required_evidence"] = [
        {
            "name": "required-result",
            "kind": "structured-data",
            "media_type": "application/json",
            "description": "Required result",
            "requirement_ids": ["R1"],
        }
    ]
    missing = run_case_attempt(case, tmp_path, FakeRunner("ordinary output"))
    assert missing.repetitions[0].status == RepetitionStatus.FAILED
    assert "missing required evidence item: required-result" in missing.repetitions[0].errors

    present = run_case_attempt(
        case,
        tmp_path,
        FakeRunner(
            evidence_output(
                evidence_item(
                    name="required-result",
                    kind="structured-data",
                    inline={"result": "ok"},
                )
            )
        ),
    )
    assert present.passed is True


class GenericAdapter:
    def evaluate(self, evidence: Any, *, worktree: Path) -> EvidenceAdapterResult | None:
        if evidence.name != "adapter-input":
            return None
        assert evidence.artifact_path is not None
        assert Path(evidence.artifact_path).read_bytes() == b"opaque-domain-file"
        return EvidenceAdapterResult(
            passed=True,
            metrics={"adapter.score": 0.9},
            evidence=(
                evidence_item(
                    name="adapter-coverage",
                    inline={
                        "measurements": {"adapter.score": 0.9},
                        "scenarios": ["adapter-case"],
                    },
                ),
            ),
        )


def test_external_adapter_returns_only_generic_metrics_and_evidence(tmp_path: Path) -> None:
    case = runtime_case()
    case["metrics"] = ["adapter.score"]
    case["metric_assertions"] = [
        {"metric": "adapter.score", "operator": ">=", "threshold": 0.8, "tolerance": 0}
    ]
    case["coverage_targets"] = [
        {
            "name": "adapter-contract",
            "coverage_type": "invariant",
            "description": "External adapter result",
            "measurement_key": "adapter.score",
            "operator": ">=",
            "threshold": 0.8,
            "tolerance": 0,
            "required_scenarios": ["adapter-case"],
            "evidence_kind": "coverage",
        }
    ]
    (tmp_path / "opaque.bin").write_bytes(b"opaque-domain-file")
    output = evidence_output(
        evidence_item(
            name="adapter-input",
            kind="structured-data",
            inline=None,
            path="opaque.bin",
            media_type="application/octet-stream",
        )
    )
    attempt = run_case_attempt(
        case,
        tmp_path,
        FakeRunner(output),
        adapters=(GenericAdapter(),),
        artifact_directory=tmp_path / "artifacts",
    )
    assert attempt.passed is True
    repetition = attempt.repetitions[0]
    assert repetition.metrics == {"adapter.score": 0.9}
    assert repetition.coverage_results[0].status == "passed"


def test_structured_models_schema_compiler_and_legacy_round_trip(tmp_path: Path) -> None:
    payload = complete_document_dict()
    payload["verification"][0]["coverage_targets"] = [
        {
            "name": "scenario-rate",
            "coverage_type": "scenario",
            "description": "Measured scenarios",
            "measurement_key": "scenario.rate",
            "operator": ">=",
            "threshold": 0.9,
            "tolerance": 0.01,
            "required_scenarios": ["ordinary", "invalid"],
            "evidence_kind": "coverage",
        }
    ]
    payload["verification"][0]["required_evidence"] = [
        {
            "name": "scenario-coverage",
            "kind": "coverage",
            "media_type": "application/json",
            "description": "Scenario measurements",
            "requirement_ids": ["R1", "R2"],
        }
    ]
    document = SpecificationDocument.from_dict(payload)
    target = document.verification[0].coverage_targets[0]
    declaration = document.verification[0].required_evidence[0]
    assert isinstance(target, CoverageTarget) and target.machine_enforced
    assert isinstance(declaration, EvidenceDeclaration)
    assert set(CoverageType) == {
        CoverageType.SOURCE_LINE,
        CoverageType.BRANCH,
        CoverageType.INTERFACE,
        CoverageType.SCENARIO,
        CoverageType.STATE_TRANSITION,
        CoverageType.REQUIREMENT,
        CoverageType.FIXTURE,
        CoverageType.INVARIANT,
        CoverageType.PLATFORM,
    }
    assert {item.value for item in EvidenceKind} == {
        "log",
        "structured-data",
        "intermediate-state",
        "trace",
        "image",
        "snapshot",
        "benchmark",
        "coverage",
        "reference-output",
        "comparison-result",
    }
    for schema_name in ("specification.schema.json", "verification_manifest.schema.json"):
        schema = json.loads((Path(__file__).parents[1] / schema_name).read_text())
        assert schema["$defs"]["coverageTarget"]["additionalProperties"] is False
        assert schema["$defs"]["evidenceDeclaration"]["additionalProperties"] is False
        assert set(schema["$defs"]["coverageTarget"]["properties"]["coverage_type"]["enum"]) == {
            item.value for item in CoverageType
        }
        assert set(schema["$defs"]["evidenceDeclaration"]["properties"]["kind"]["enum"]) == {
            item.value for item in EvidenceKind
        }
    service = SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts")
    service.create(tmp_path, document, creator="author", specification_id="SPEC9")
    service.submit_for_review("SPEC9")
    approved = service.approve("SPEC9", approved_by="owner")
    manifest_case = compile_verification_manifest(approved, "pytest -q").verification[0]
    assert manifest_case["coverage_targets"] == payload["verification"][0]["coverage_targets"]
    assert manifest_case["required_evidence"] == payload["verification"][0]["required_evidence"]

    legacy_path = Path(__file__).parent / "fixtures/milestone_7_specification.json"
    legacy_text = legacy_path.read_text(encoding="utf-8")
    legacy = SpecificationDocument.from_json(legacy_text)
    assert legacy.canonical_json() == json.dumps(
        json.loads(legacy_text), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def test_structured_contract_rejects_unknown_fields_and_partial_enforcement() -> None:
    payload = complete_document_dict()
    payload["verification"][0]["coverage_targets"] = [
        {
            "name": "partial",
            "coverage_type": "scenario",
            "description": "Partial contract",
            "measurement_key": "scenario.rate",
            "operator": None,
            "threshold": None,
            "tolerance": None,
            "required_scenarios": [],
            "evidence_kind": None,
        }
    ]
    with pytest.raises(SpecificationError, match="machine coverage requires"):
        SpecificationDocument.from_dict(payload)

    payload = complete_document_dict()
    payload["verification"][0]["required_evidence"] = [
        {
            "name": "log",
            "kind": "log",
            "media_type": "text/plain",
            "description": "Log",
            "requirement_ids": ["R1"],
            "unexpected": True,
        }
    ]
    with pytest.raises(SpecificationError, match="unknown fields"):
        SpecificationDocument.from_dict(payload)


def test_evidence_columns_are_additive_and_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE verification_repetitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            worker_run_id TEXT,
            verification_id TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            repetition INTEGER NOT NULL,
            command TEXT NOT NULL,
            working_directory TEXT NOT NULL,
            timeout_seconds INTEGER NOT NULL,
            status TEXT NOT NULL,
            return_code INTEGER,
            output TEXT NOT NULL,
            output_truncated INTEGER NOT NULL,
            metrics_json TEXT,
            assertion_results_json TEXT NOT NULL,
            elapsed_seconds REAL NOT NULL,
            timed_out INTEGER NOT NULL,
            error TEXT,
            termination_details TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            evidence_marker TEXT,
            UNIQUE (job_id, verification_id, attempt, repetition)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO verification_repetitions (
            id, job_id, task_id, verification_id, attempt, repetition, command,
            working_directory, timeout_seconds, status, output, output_truncated,
            assertion_results_json, elapsed_seconds, timed_out, started_at,
            finished_at, evidence_marker
        ) VALUES (
            1, 'J1', 'T1', 'VT1', 1, 1, 'verify', '.', 10, 'passed', '', 0,
            '[]', 0.1, 0, 'started', 'finished', 'untouched'
        )
        """
    )
    connection.commit()
    connection.close()

    db.init_db(database)
    db.init_db(database)
    with db.transaction(database) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(verification_repetitions)")}
        marker = conn.execute(
            "SELECT evidence_marker FROM verification_repetitions WHERE id = 1"
        ).fetchone()[0]
    assert {
        "evidence_json",
        "coverage_results_json",
        "execution_proof_json",
    } <= columns
    assert marker == "untouched"
