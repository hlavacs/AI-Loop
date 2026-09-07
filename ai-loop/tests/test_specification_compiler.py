from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ai_loop import db
from ai_loop.specification_compiler import (
    ManifestCompilationError,
    ManifestIntegrityError,
    VerificationManifest,
    compile_verification_manifest,
)
from ai_loop.specifications import (
    SpecificationDocument,
    SpecificationService,
    SpecificationStateError,
    sha256_bytes,
    sha256_text,
)


def document(
    *,
    command_override: str | None = None,
    working_directory: str = ".",
    timeout: int = 60,
    threshold: int | float = 5.0,
    tolerance: int | float | None = 0.0,
) -> SpecificationDocument:
    return SpecificationDocument.from_dict(
        {
            "schema_version": "1.0",
            "title": "Reliable command",
            "summary": "Implement a reliable command while preserving compatibility.",
            "objectives": ["Provide the requested command"],
            "in_scope": ["Command behavior and verification"],
            "out_of_scope": ["Unrelated commands"],
            "stakeholders": ["Repository maintainers"],
            "assumptions": ["Python is available"],
            "constraints": ["Keep the existing interface compatible"],
            "dependencies": ["Python standard library"],
            "use_cases": [
                {
                    "id": "UC1",
                    "title": "Run the command",
                    "actors": ["User"],
                    "preconditions": ["The repository is available"],
                    "trigger": "The user invokes the command",
                    "main_flow": ["Validate input", "Perform operation", "Report success"],
                    "alternate_flows": ["Use documented defaults"],
                    "postconditions": ["The result is observable"],
                    "error_and_edge_cases": ["Invalid input leaves state unchanged"],
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
                    "acceptance_criteria": ["Valid input produces the expected result."],
                    "source": "User brief",
                },
                {
                    "id": "R2",
                    "category": "quality",
                    "priority": "must",
                    "title": "Reject invalid input safely",
                    "statement": "The system shall reject invalid input without partial state.",
                    "rationale": "Failure behavior must be predictable.",
                    "acceptance_criteria": ["Invalid input leaves state unchanged."],
                    "source": "User brief",
                },
            ],
            "decisions": [],
            "risks": [
                {
                    "id": "RK1",
                    "title": "Partial state",
                    "description": "A failure could leave partial state.",
                    "severity": "medium",
                    "uncertainty": "low",
                    "failure_modes": ["State is written before validation"],
                    "detection_signals": ["State differs after invalid input"],
                    "mitigations": ["Validate before writing"],
                    "verification_ids": ["VT1"],
                }
            ],
            "verification": [
                {
                    "id": "VT1",
                    "title": "Command behavior",
                    "requirement_ids": ["R1", "R2"],
                    "test_level": "acceptance",
                    "method": "deterministic",
                    "oracle": "Expected results encoded independently in the fixture",
                    "fixtures": ["A valid and an invalid input"],
                    "procedure": ["Run the focused target", "Inspect the result"],
                    "pass_criteria": ["Valid and invalid scenarios match the oracle"],
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
                        "escalation_condition": "Escalate after bounded attempts",
                        "retain_evidence": True,
                    },
                    "command_override": command_override,
                    "working_directory": working_directory,
                    "timeout": timeout,
                    "required_evidence": ["Focused test log"],
                },
                {
                    "id": "VT2",
                    "title": "Documentation review",
                    "requirement_ids": ["R1"],
                    "test_level": "acceptance",
                    "method": "manual",
                    "oracle": "Maintainer review",
                    "fixtures": [],
                    "procedure": ["Review the documentation"],
                    "pass_criteria": ["The command is documented"],
                    "declared_metrics": [],
                    "metric_assertions": [],
                    "coverage_targets": ["Public documentation"],
                    "automation": "manual",
                    "blocking": False,
                    "validation_loop": {
                        "maximum_correction_attempts": 1,
                        "repetitions_per_attempt": 1,
                        "stagnation_limit": 1,
                        "escalation_condition": "Record review as pending",
                        "retain_evidence": False,
                    },
                    "command_override": None,
                    "working_directory": ".",
                    "timeout": 60,
                    "required_evidence": ["Review note"],
                },
            ],
            "open_questions": [],
        }
    )


def approved_service(tmp_path: Path, **document_options):
    tmp_path.mkdir(parents=True, exist_ok=True)
    service = SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts")
    service.create(
        tmp_path,
        document(**document_options),
        creator="author",
        specification_id="SPEC1",
    )
    service.submit_for_review("SPEC1")
    return service, service.approve("SPEC1", approved_by="owner")


def create_quick_job(database: Path, job_id: str, root: Path, test_cmd: str = "pytest -q") -> None:
    with db.transaction(database) as conn:
        db.create_job(
            conn,
            job_id=job_id,
            repo_path=str(root),
            worktree_path=str(root),
            branch=None,
            base_ref="HEAD",
            goal="Quick goal",
            constraints=[],
            acceptance=[],
            test_cmd=test_cmd,
            max_iterations=3,
            use_worktree=False,
        )


class TestManifestSchemaAndCompiler:
    def test_schema_is_strict_versioned_and_reusable(self) -> None:
        schema = json.loads(
            (Path(__file__).parents[1] / "verification_manifest.schema.json").read_text()
        )
        assert schema["$schema"].endswith("2020-12/schema")
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"] == "1.0"
        assert schema["$defs"]["stableId"]["pattern"]
        for name in (
            "specificationReference",
            "workItem",
            "metricAssertion",
            "validationLoop",
            "verificationEntry",
        ):
            assert schema["$defs"][name]["additionalProperties"] is False
        verification = schema["$defs"]["verificationEntry"]
        assert {
            "command",
            "command_source",
            "working_directory",
            "timeout",
            "metrics",
            "metric_assertions",
        } <= set(verification["required"])
        assert verification["properties"]["command_source"]["enum"] == [
            "specification", "job_default", "manual"
        ]
        assert schema["$defs"]["metricAssertion"]["properties"]["operator"]["enum"] == [
            "<", "<=", "==", "!=", ">=", ">"
        ]

    def test_deterministic_round_trip_and_complete_bidirectional_traceability(
        self, tmp_path: Path
    ) -> None:
        _service, approved = approved_service(tmp_path)
        first = compile_verification_manifest(approved, "pytest -q")
        second = compile_verification_manifest(approved, "pytest -q")

        assert first.canonical_json() == second.canonical_json()
        assert first.content_hash() == second.content_hash()
        assert VerificationManifest.from_json(first.pretty_json()).canonical_json() == first.canonical_json()
        assert '"threshold":5' in first.canonical_json()
        payload = first.to_dict()
        assert payload["specification"] == {
            "id": "SPEC1",
            "version": 1,
            "schema_version": "1.0",
            "content_hash": approved.canonical_content_hash,
        }
        assert [item["requirement_id"] for item in payload["work_items"]] == ["R1", "R2"]
        assert payload["work_items"][0]["linked_use_case_ids"] == ["UC1"]
        assert payload["work_items"][0]["linked_risk_ids"] == ["RK1"]
        assert payload["work_items"][0]["linked_verification_ids"] == ["VT1", "VT2"]
        assert payload["work_items"][1]["linked_verification_ids"] == ["VT1"]
        automated, manual = payload["verification"]
        assert automated["requirement_ids"] == ["R1", "R2"]
        assert automated["risk_ids"] == ["RK1"]
        assert automated["command"] == "pytest -q"
        assert automated["command_source"] == "job_default"
        assert automated["metrics"] == ["duration_seconds"]
        assert manual["command"] is None
        assert manual["command_source"] == "manual"

    def test_command_override_and_unresolved_auto_rules(self, tmp_path: Path) -> None:
        _service, approved = approved_service(tmp_path, command_override="python verify.py")
        manifest = compile_verification_manifest(approved, "auto")
        assert manifest.verification[0]["command"] == "python verify.py"
        assert manifest.verification[0]["command_source"] == "specification"

        other = tmp_path / "default"
        other.mkdir()
        _service, inherited = approved_service(other)
        with pytest.raises(ManifestCompilationError, match="unresolved 'auto'"):
            compile_verification_manifest(inherited, "auto")

    def test_per_case_execution_contract_propagates_without_flattening(
        self, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "contract"
        (worktree / "verification").mkdir(parents=True)
        _service, approved = approved_service(
            worktree,
            command_override="python verify_case.py --case VT1",
            working_directory="verification",
            timeout=47,
            threshold=12.5,
            tolerance=0.25,
        )

        case = compile_verification_manifest(approved, "auto").verification[0]

        assert case["command"] == "python verify_case.py --case VT1"
        assert case["command_source"] == "specification"
        assert case["working_directory"] == "verification"
        assert case["timeout"] == 47
        assert case["metrics"] == ["duration_seconds"]
        assert case["metric_assertions"] == [
            {
                "metric": "duration_seconds",
                "operator": "<=",
                "threshold": 12.5,
                "tolerance": 0.25,
            }
        ]

    def test_compiled_numeric_contract_has_stable_canonical_and_artifact_hashes(
        self, tmp_path: Path
    ) -> None:
        integer_service, integer_snapshot = approved_service(
            tmp_path / "integer", threshold=5, tolerance=2
        )
        float_service, float_snapshot = approved_service(
            tmp_path / "float", threshold=5.0, tolerance=2.0
        )

        integer = compile_verification_manifest(integer_snapshot, "pytest -q")
        floating = compile_verification_manifest(float_snapshot, "pytest -q")

        assert integer.canonical_json() == floating.canonical_json()
        assert integer.content_hash() == floating.content_hash()
        assert integer.pretty_json() == floating.pretty_json()
        assert integer_snapshot.canonical_content_hash == float_snapshot.canonical_content_hash
        assert integer_snapshot.artifact_hash == float_snapshot.artifact_hash
        assert sha256_bytes(integer.pretty_json().encode()) == sha256_bytes(
            floating.pretty_json().encode()
        )
        assert '"threshold":5' in floating.canonical_json()
        assert '"tolerance":2' in floating.canonical_json()

        persisted_integer = integer_service.create_formal_job(
            specification_id="SPEC1",
            specification_version=1,
            job_id="JNUMERIC",
            repo_path=str(tmp_path / "integer"),
            worktree_path=str(tmp_path / "integer"),
            branch=None,
            base_ref="HEAD",
            test_cmd="pytest -q",
            max_iterations=2,
            use_worktree=False,
        )
        persisted_float = float_service.create_formal_job(
            specification_id="SPEC1",
            specification_version=1,
            job_id="JNUMERIC",
            repo_path=str(tmp_path / "float"),
            worktree_path=str(tmp_path / "float"),
            branch=None,
            base_ref="HEAD",
            test_cmd="pytest -q",
            max_iterations=2,
            use_worktree=False,
        )
        assert persisted_integer.canonical_content_hash == persisted_float.canonical_content_hash
        assert persisted_integer.artifact_hash == persisted_float.artifact_hash

    def test_milestone_7_manifest_artifact_retains_canonical_shape_and_hash(self) -> None:
        artifact = Path(__file__).parent / "fixtures/milestone_7_verification_manifest.json"
        original = json.loads(artifact.read_text(encoding="utf-8"))
        manifest = VerificationManifest.from_json(artifact.read_text(encoding="utf-8"))

        assert manifest.content_hash() == (
            "dee5648254cb2e291d7a6137b6e701fb9635005527c93eb698aff7d54845c969"
        )
        assert sha256_bytes(artifact.read_bytes()) == (
            "964a488bd5fb1c4cefb807aa49313e1047acdaa5a26c28c2db17ff319a7e67e4"
        )
        assert manifest.canonical_json() == json.dumps(
            original,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        assert set(manifest.verification[0]) == set(original["verification"][0])

    def test_runtime_manifest_parser_rejects_unknown_fields(self, tmp_path: Path) -> None:
        _service, approved = approved_service(tmp_path)
        payload = compile_verification_manifest(approved, "pytest -q").to_dict()
        payload["unexpected"] = True
        with pytest.raises(ManifestCompilationError, match="unknown fields"):
            VerificationManifest.from_dict(payload)

    def test_unapproved_snapshot_cannot_compile(self, tmp_path: Path) -> None:
        service = SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts")
        draft = service.create(
            tmp_path, document(), creator="author", specification_id="SPEC1"
        )
        with pytest.raises(SpecificationStateError, match="approved immutable"):
            compile_verification_manifest(draft, "pytest -q")


class TestManifestPersistence:
    def test_formal_creation_pins_and_persists_independent_immutable_hashes(
        self, tmp_path: Path
    ) -> None:
        service, approved = approved_service(tmp_path)
        stored = service.create_formal_job(
            specification_id="SPEC1",
            specification_version=1,
            job_id="JFORMAL",
            repo_path=str(tmp_path),
            worktree_path=str(tmp_path),
            branch=None,
            base_ref="HEAD",
            test_cmd="pytest -q",
            max_iterations=4,
            use_worktree=False,
        )
        artifact_bytes = stored.artifact_path.read_bytes()
        assert stored.artifact_path == (
            tmp_path
            / "artifacts/jobs/JFORMAL/specification/verification-manifest.json"
        )
        assert stored.canonical_content_hash == sha256_text(stored.manifest.canonical_json())
        assert stored.artifact_hash == sha256_bytes(artifact_bytes)
        assert stored.canonical_content_hash != stored.artifact_hash
        with db.transaction(service.db_path) as conn:
            job = db.get_job(conn, "JFORMAL")
            assert job["specification_id"] == "SPEC1"
            assert job["specification_version"] == 1
            assert job["specification_content_hash"] == approved.canonical_content_hash
            assert "SPEC1 version 1" in job["goal"]
            assert conn.execute(
                "SELECT COUNT(*) FROM job_verification_states WHERE job_id = 'JFORMAL'"
            ).fetchone()[0] == 2
        assert service.load_job_manifest("JFORMAL").artifact_path.read_bytes() == artifact_bytes
        prompt_context = service.load_job_prompt_context("JFORMAL")
        assert prompt_context is not None
        assert prompt_context.specification == approved.document.to_dict()
        assert prompt_context.manifest == stored.manifest.to_dict()
        assert [item["verification_id"] for item in prompt_context.runtime_verification_summary] == [
            "VT1",
            "VT2",
        ]
        assert [item["status"] for item in prompt_context.runtime_verification_summary] == [
            "unrealized",
            "manual_pending",
        ]

    def test_attachment_uses_same_manifest_and_quick_jobs_stay_isolated(
        self, tmp_path: Path
    ) -> None:
        service, _approved = approved_service(tmp_path)
        initial = service.create_formal_job(
            specification_id="SPEC1",
            specification_version=1,
            job_id="JFORMAL",
            repo_path=str(tmp_path),
            worktree_path=str(tmp_path),
            branch=None,
            base_ref="HEAD",
            test_cmd="pytest -q",
            max_iterations=3,
            use_worktree=False,
        )
        create_quick_job(service.db_path, "JATTACH", tmp_path)
        create_quick_job(service.db_path, "JQUICK", tmp_path)
        assert service.load_job_manifest("JATTACH") is None
        assert service.load_job_manifest("JQUICK") is None
        assert service.load_job_prompt_context("JQUICK") is None

        service.attach_to_job("SPEC1", 1, "JATTACH")
        attached = service.load_job_manifest("JATTACH")
        assert attached is not None
        attached_bytes = attached.artifact_path.read_bytes()
        assert attached.manifest.canonical_json() == initial.manifest.canonical_json()
        assert attached.canonical_content_hash == initial.canonical_content_hash
        service.attach_to_job("SPEC1", 1, "JATTACH")
        assert attached.artifact_path.read_bytes() == attached_bytes
        assert service.load_job_manifest("JQUICK") is None
        with db.transaction(service.db_path) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM verification_manifests WHERE job_id = 'JQUICK'"
            ).fetchone()[0] == 0

    def test_lazy_backfill_initializes_state_and_records_event(self, tmp_path: Path) -> None:
        service, approved = approved_service(tmp_path)
        with db.transaction(service.db_path) as conn:
            db.create_job(
                conn,
                job_id="JLEGACYFORMAL",
                repo_path=str(tmp_path),
                worktree_path=str(tmp_path),
                branch=None,
                base_ref="HEAD",
                goal="Historical formal goal",
                constraints=[],
                acceptance=[],
                test_cmd="pytest -q",
                max_iterations=3,
                use_worktree=False,
                specification_id="SPEC1",
                specification_version=1,
                specification_content_hash=approved.canonical_content_hash,
            )
        assert service.load_job_manifest("JLEGACYFORMAL", backfill=False) is None
        stored = service.load_job_manifest("JLEGACYFORMAL")
        assert stored is not None
        with db.transaction(service.db_path) as conn:
            states = conn.execute(
                """
                SELECT verification_id, status FROM job_verification_states
                WHERE job_id = 'JLEGACYFORMAL' ORDER BY verification_id
                """
            ).fetchall()
            assert [tuple(row) for row in states] == [
                ("VT1", "unrealized"),
                ("VT2", "manual_pending"),
            ]
            events = conn.execute(
                "SELECT kind FROM events WHERE job_id = 'JLEGACYFORMAL'"
            ).fetchall()
            assert [row["kind"] for row in events] == ["verification_manifest_backfilled"]
        assert service.load_job_manifest("JLEGACYFORMAL").created_at == stored.created_at

    @pytest.mark.parametrize(
        "target", ["canonical_json", "canonical_hash", "artifact_hash", "artifact"]
    )
    def test_integrity_detects_independent_manifest_tampering(
        self, tmp_path: Path, target: str
    ) -> None:
        root = tmp_path / target
        root.mkdir()
        service, _approved = approved_service(root)
        stored = service.create_formal_job(
            specification_id="SPEC1",
            specification_version=1,
            job_id="JFORMAL",
            repo_path=str(root),
            worktree_path=str(root),
            branch=None,
            base_ref="HEAD",
            test_cmd="pytest -q",
            max_iterations=3,
            use_worktree=False,
        )
        if target == "canonical_json":
            with db.transaction(service.db_path) as conn:
                conn.execute(
                    "UPDATE verification_manifests SET canonical_json = '{}' WHERE job_id = 'JFORMAL'"
                )
        elif target == "canonical_hash":
            with db.transaction(service.db_path) as conn:
                conn.execute(
                    "UPDATE verification_manifests SET canonical_content_hash = ? WHERE job_id = 'JFORMAL'",
                    ("0" * 64,),
                )
        elif target == "artifact_hash":
            with db.transaction(service.db_path) as conn:
                conn.execute(
                    "UPDATE verification_manifests SET artifact_hash = ? WHERE job_id = 'JFORMAL'",
                    ("0" * 64,),
                )
        else:
            stored.artifact_path.write_bytes(stored.artifact_path.read_bytes() + b"\n")
        with pytest.raises(ManifestIntegrityError):
            service.load_job_manifest("JFORMAL")

    def test_unapproved_attachment_does_not_pin_or_create_artifact(self, tmp_path: Path) -> None:
        service = SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts")
        service.create(tmp_path, document(), creator="author", specification_id="SPEC1")
        create_quick_job(service.db_path, "JQUICK", tmp_path)
        with pytest.raises(SpecificationStateError, match="approved immutable"):
            service.attach_to_job("SPEC1", 1, "JQUICK")
        assert service.load_job_manifest("JQUICK") is None
        assert not (
            tmp_path / "artifacts/jobs/JQUICK/specification/verification-manifest.json"
        ).exists()

    def test_formal_creation_rejects_unresolved_auto_before_job_commit(
        self, tmp_path: Path
    ) -> None:
        service, _approved = approved_service(tmp_path)
        with pytest.raises(ManifestCompilationError, match="unresolved 'auto'"):
            service.create_formal_job(
                specification_id="SPEC1",
                specification_version=1,
                job_id="JFORMAL",
                repo_path=str(tmp_path),
                worktree_path=str(tmp_path),
                branch=None,
                base_ref="HEAD",
                test_cmd="auto",
                max_iterations=3,
                use_worktree=False,
            )
        with db.transaction(service.db_path) as conn:
            assert conn.execute("SELECT 1 FROM jobs WHERE id = 'JFORMAL'").fetchone() is None
        assert not (
            tmp_path / "artifacts/jobs/JFORMAL/specification/verification-manifest.json"
        ).exists()


def test_manifest_migration_is_additive_idempotent_and_preserves_legacy_rows(
    tmp_path: Path,
) -> None:
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
    before_job = conn.execute("SELECT * FROM jobs").fetchone()
    before_task = conn.execute("SELECT * FROM tasks").fetchone()
    conn.commit()
    conn.close()

    db.init_db(database)
    db.init_db(database)
    with db.transaction(database) as migrated:
        assert tuple(migrated.execute(
            "SELECT id, repo_path, worktree_path, branch, base_ref, goal, constraints_json, "
            "acceptance_json, test_cmd, max_iterations, use_worktree, status, history_summary, "
            "created_at, updated_at FROM jobs"
        ).fetchone()) == tuple(before_job)
        assert tuple(migrated.execute(
            "SELECT id, job_id, iteration, goal, constraints_json, acceptance_json, test_cmd, "
            "status, created_by, created_at, updated_at FROM tasks"
        ).fetchone()) == tuple(before_task)
        tables = {
            row[0]
            for row in migrated.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"verification_manifests", "job_verification_states"} <= tables
        job_columns = {row[1] for row in migrated.execute("PRAGMA table_info(jobs)")}
        task_columns = {row[1] for row in migrated.execute("PRAGMA table_info(tasks)")}
        assert {
            "specification_id",
            "specification_version",
            "specification_content_hash",
        } <= job_columns
        assert {"requirement_ids_json", "verification_ids_json"} <= task_columns
        assert db.get_job(migrated, "J-legacy")["specification_id"] is None
        assert db.get_task(migrated, "T-legacy")["requirement_ids"] == []
        assert migrated.execute("SELECT COUNT(*) FROM verification_manifests").fetchone()[0] == 0


def test_task_traceability_json_columns_round_trip_without_controller_wiring(
    tmp_path: Path,
) -> None:
    database = tmp_path / "loop.sqlite3"
    db.init_db(database)
    create_quick_job(database, "J1", tmp_path)
    with db.transaction(database) as conn:
        db.create_task(
            conn,
            task_id="T1",
            job_id="J1",
            iteration=0,
            goal="Traceable task",
            constraints=[],
            acceptance=[],
            test_cmd="pytest -q",
            created_by="test",
            requirement_ids=["R1", "R2"],
            verification_ids=["VT1"],
        )
        task = db.get_task(conn, "T1")
    assert task["requirement_ids"] == ["R1", "R2"]
    assert task["verification_ids"] == ["VT1"]
