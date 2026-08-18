from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ai_loop import db
from ai_loop.evidence_adapters import (
    collect_realization_signals,
    load_evidence_adapters,
)
from ai_loop.verification_orchestrator import (
    EvidenceAdapterResult,
    EvidenceArtifact,
    RealizationSignals,
    RealizationState,
    RunnerResult,
    check_manifest_realization,
    run_case_attempt,
    run_task_verification,
)
from tests.test_evidence_and_coverage import (
    FakeRunner,
    evidence_item,
    evidence_output,
    runtime_case,
)
from tests.test_verification_realization import manifest
from tests.test_specification_compiler import approved_service


class ConfiguredAdapter:
    def __init__(self, score: float = 0.9, *, fail: bool = False):
        self.score = score
        self.fail = fail

    def evaluate(self, evidence: EvidenceArtifact, *, worktree: Path) -> EvidenceAdapterResult | None:
        if self.fail:
            raise RuntimeError("adapter unavailable")
        if evidence.name != "adapter-input":
            return None
        return EvidenceAdapterResult(
            passed=True,
            metrics={
                "result_count": self.score,
                "adapter.score": self.score,
                "duration_seconds": self.score,
            },
            evidence=(
                evidence_item(
                    name="adapter-coverage",
                    kind="coverage",
                    inline={"measurements": {"adapter.score": self.score}},
                ),
            ),
            realization_signals=(
                RealizationSignals(
                    verification_id=evidence.verification_id,
                    case_marker=True,
                    fixture_generators=(
                        "fixtures/input.json",
                        "A valid and an invalid input",
                    ),
                    evidence_producers=("test log", "Focused test log"),
                ),
            ),
        )


def configured_raw(**options: Any) -> str:
    return json.dumps(
        [
            {
                "id": "configured",
                "adapter": f"{__name__}:ConfiguredAdapter",
                "options": options,
            }
        ]
    )


def artifact() -> EvidenceArtifact:
    return EvidenceArtifact(
        name="adapter-input",
        kind="structured-data",
        media_type="application/json",
        description="Adapter input",
        requirement_ids=("R1",),
        verification_id="VT1",
        comparison=None,
        size=2,
        sha256="0" * 64,
        artifact_path=None,
        inline_value={},
        preview="{}",
        measurements={},
        scenarios=(),
    )


def test_configuration_loads_import_path_and_registry_key() -> None:
    imported = load_evidence_adapters(configured_raw(score=0.75))
    registered = load_evidence_adapters(
        '[{"id":"local","adapter":"local","options":{"score":0.5}}]',
        registry={"local": ConfiguredAdapter},
    )

    assert len(imported.adapters) == 1
    assert len(registered.adapters) == 1
    assert imported.adapters[0].evaluate(artifact(), worktree=Path(".")).metrics[
        "adapter.score"
    ] == 0.75
    assert registered.adapters[0].evaluate(artifact(), worktree=Path(".")).metrics[
        "adapter.score"
    ] == 0.5


def test_configured_result_signals_are_merged_into_realization(tmp_path: Path) -> None:
    loaded = load_evidence_adapters(configured_raw())
    signals = collect_realization_signals(
        loaded.adapters, (artifact(),), worktree=tmp_path
    )

    result = check_manifest_realization(
        manifest(), tmp_path, adapter_results=signals
    )[0]

    assert result.state == RealizationState.EXECUTABLE_BUT_FAILING
    assert result.missing_infrastructure == ()


def test_broken_adapter_is_audited_and_cannot_fabricate_realization(tmp_path: Path) -> None:
    audits = []
    missing = load_evidence_adapters(
        '[{"id":"missing","adapter":"no_such_adapter.module:Adapter"}]',
        audit=audits.append,
    )
    failing = load_evidence_adapters(configured_raw(fail=True), audit=audits.append)

    signals = collect_realization_signals(
        failing.adapters, (artifact(),), worktree=tmp_path, audit=audits.append
    )
    result = check_manifest_realization(manifest(), tmp_path, adapter_results=signals)[0]

    assert missing.adapters == ()
    assert signals == ()
    assert result.state == RealizationState.UNREALIZED
    assert {(item.adapter, item.stage) for item in audits} == {
        ("missing", "load"),
        ("configured", "evaluate"),
    }


def test_adapter_coverage_does_not_override_zero_execution_proof(tmp_path: Path) -> None:
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
            "required_scenarios": [],
            "evidence_kind": "coverage",
        }
    ]
    output = evidence_output(evidence_item(name="adapter-input", kind="structured-data"))
    runner = FakeRunner(output)
    runner.run = lambda **_kwargs: RunnerResult(
        output=output,
        return_code=0,
        elapsed_seconds=0.1,
        selected_case_count=0,
        executed_case_count=0,
        skipped_case_count=0,
    )

    attempt = run_case_attempt(
        case,
        tmp_path,
        runner,
        adapters=load_evidence_adapters(configured_raw()).adapters,
    )

    repetition = attempt.repetitions[0]
    assert repetition.coverage_results[0].passed is True
    assert repetition.execution_proof.passed is False
    assert "selected zero test cases" in str(repetition.execution_proof.error)
    assert attempt.passed is False


def test_configured_adapter_runs_in_formal_verification_and_prompt_refresh(
    tmp_path: Path, monkeypatch: Any
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
        max_iterations=2,
        use_worktree=False,
    )
    with db.transaction(service.db_path) as conn:
        db.create_task(
            conn,
            task_id="T1",
            job_id="JFORMAL",
            iteration=0,
            goal="Verify adapter evidence",
            constraints=[],
            acceptance=[],
            test_cmd="verify",
            created_by="test",
            requirement_ids=["R1"],
            verification_ids=["VT1"],
        )
    monkeypatch.setenv("AI_LOOP_EVIDENCE_ADAPTERS", configured_raw())
    output = evidence_output(evidence_item(name="adapter-input", kind="structured-data"))

    attempts = run_task_verification(
        service.db_path,
        "JFORMAL",
        "T1",
        stored.manifest,
        FakeRunner(output),
    )
    context = service.load_job_prompt_context("JFORMAL")

    assert attempts[0].repetitions[0].metrics["adapter.score"] == 0.9
    assert attempts[0].passed is True
    assert context.runtime_verification_summary[0]["missing_infrastructure"] == []
    assert context.runtime_verification_summary[0]["status"] == "passing"
