from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pytest

from ai_loop import db
from ai_loop.elicitation import (
    CliStructuredOutputProvider,
    ElicitationEngine,
    ElicitationValidationError,
    StaleElicitationError,
    StructuredOutputRequest,
    apply_elicitation_analysis,
    build_repository_analysis_prompt,
    elicitation_result_schema,
    validate_elicitation_result,
)
from ai_loop.specifications import (
    Requirement,
    RequirementCategory,
    RequirementPriority,
    SpecificationDecision,
    SpecificationDocument,
    SpecificationIntegrityError,
    SpecificationService,
)


class FakeStructuredOutputProvider:
    provider = "fake"
    model = "fake-structured-model"

    def __init__(self, outputs: list[Any | Callable[[StructuredOutputRequest], Any]]):
        self.outputs = list(outputs)
        self.requests: list[StructuredOutputRequest] = []

    def generate_structured_output(self, request: StructuredOutputRequest) -> Any:
        self.requests.append(request)
        if not self.outputs:
            raise AssertionError("fake provider received an unbounded extra request")
        output = self.outputs.pop(0)
        return output(request) if callable(output) else output


def source_document() -> SpecificationDocument:
    return replace(
        SpecificationDocument.empty(
            title="Exact user title",
            summary="Exact user summary",
        ),
        objectives=("Existing objective",),
        in_scope=("Existing scope",),
        decisions=(
            SpecificationDecision(
                topic="Storage",
                selected_decision="Keep SQLite",
                rationale="The user chose compatibility.",
                rejected_alternatives=("Replace persistence",),
                consequences=("Retain existing databases",),
            ),
        ),
        requirements=(
            Requirement(
                id="R1",
                category=RequirementCategory.FUNCTIONAL,
                priority=RequirementPriority.MUST,
                title="Existing requirement",
                statement="The system shall retain the existing behavior.",
                rationale="The user requires compatibility.",
                acceptance_criteria=("The existing scenario still passes.",),
                source="User",
            ),
        ),
    )


def additive_result(document: SpecificationDocument | None = None) -> dict[str, Any]:
    source = document or source_document()
    suggestion = source.to_dict()
    suggestion["objectives"].append("Exercise boundary behavior")
    suggestion["requirements"].append(
        {
            "id": "R2",
            "category": "quality",
            "priority": "should",
            "title": "Bounded retries",
            "statement": "The system should bound retries under repeated failure.",
            "rationale": "Unbounded retries consume resources.",
            "acceptance_criteria": ["A configured retry limit stops repeated failure."],
            "source": "Repository analysis",
        }
    )
    return {
        "summary": "The repository suggests one missing reliability contract.",
        "suggested_specification": suggestion,
        "choices": [
            {
                "topic": "Retry policy",
                "question": "Which retry policy should constrain transient failures?",
                "context": "The implementation currently has no user-approved policy.",
                "options": [
                    {
                        "name": "Fixed limit",
                        "description": "Use a fixed maximum attempt count.",
                        "tradeoffs": ["Predictable cost", "May stop before recovery"],
                    },
                    {
                        "name": "Time budget",
                        "description": "Retry until a bounded time budget expires.",
                        "tradeoffs": ["Adapts to latency", "Attempt count varies"],
                    },
                ],
                "recommendation": "Fixed limit",
                "blocking": True,
            }
        ],
        "warnings": ["A deployment-specific retry limit still needs user approval."],
    }


def create_service(tmp_path: Path) -> SpecificationService:
    service = SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts")
    service.create(
        tmp_path,
        source_document(),
        creator="user",
        specification_id="SPEC1",
    )
    return service


def test_result_schema_embeds_complete_strict_specification_schema() -> None:
    schema = elicitation_result_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "summary",
        "suggested_specification",
        "choices",
        "warnings",
    }
    embedded = schema["properties"]["suggested_specification"]
    assert embedded["additionalProperties"] is False
    assert set(embedded["required"]) == set(SpecificationDocument.empty().to_dict())
    assert "$defs" in schema
    assert "$defs" not in embedded
    assert schema["$defs"]["decisionProposal"]["properties"]["options"]["minItems"] == 2
    assert schema["$defs"]["decisionProposal"]["properties"]["options"]["maxItems"] == 5
    assert "specification.schema.json" not in json.dumps(schema)


def test_prompt_requires_read_only_deep_repository_analysis(tmp_path: Path) -> None:
    service = create_service(tmp_path)
    prompt = build_repository_analysis_prompt(service.load("SPEC1"))
    for phrase in (
        "READ-ONLY RULE",
        "manifests",
        "public APIs",
        "tests",
        "build files",
        "configuration",
        "alternate flows",
        "invalid",
        "cleanup",
        "cancellation",
        "retries",
        "concurrency",
        "ordering",
        "persistence",
        "compatibility",
        "security",
        "observability",
        "performance",
        "numerical stability",
        "repetition",
        "resource pressure",
        "non-determinism",
    ):
        assert phrase in prompt
    assert source_document().pretty_json() in prompt


@pytest.mark.parametrize("provider", ["codex", "claude", "gemini"])
def test_cli_provider_uses_selected_model_and_read_only_command_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    captured: dict[str, Any] = {}

    monkeypatch.setattr("ai_loop.elicitation.shutil.which", lambda _binary: "/bin/fake")

    def fake_run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        if "--output-last-message" in command:
            result_path = Path(command[command.index("--output-last-message") + 1])
            result_path.write_text('{"accepted":true}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout='{"accepted":true}', stderr="")

    monkeypatch.setattr("ai_loop.elicitation.subprocess.run", fake_run)
    adapter = CliStructuredOutputProvider(
        provider=provider,
        binary=f"custom-{provider}",
        model="selected-controller-model",
        timeout=123,
    )
    result = adapter.generate_structured_output(
        StructuredOutputRequest(
            prompt="Inspect only",
            schema={"type": "object"},
            repository_path=tmp_path,
            read_only=True,
        )
    )

    assert result == {"accepted": True}
    assert captured["kwargs"]["cwd"] == str(tmp_path.resolve())
    assert captured["kwargs"]["timeout"] == 123
    command = captured["command"]
    assert command[0] == f"custom-{provider}"
    if provider == "codex":
        assert ["--sandbox", "read-only"] == command[
            command.index("--sandbox") : command.index("--sandbox") + 2
        ]
        assert "--output-schema" in command
        assert ["-m", "selected-controller-model"] == command[-3:-1]
        assert captured["kwargs"]["input"] == "Inspect only"
    elif provider == "claude":
        assert ["--permission-mode", "plan"] == command[
            command.index("--permission-mode") : command.index("--permission-mode") + 2
        ]
        assert "--json-schema" in command
        assert ["--model", "selected-controller-model"] in [
            command[index : index + 2] for index in range(len(command) - 1)
        ]
    else:
        assert "--sandbox" in command
        assert ["-m", "selected-controller-model"] == command[1:3]


def test_valid_additive_analysis_is_immutable_and_bound_to_source(tmp_path: Path) -> None:
    service = create_service(tmp_path)
    provider = FakeStructuredOutputProvider([additive_result()])
    completed = ElicitationEngine(service, provider).analyze("SPEC1", 1)

    assert completed.result.suggested_specification.title == "Exact user title"
    assert completed.result.suggested_specification.objectives == (
        "Existing objective",
        "Exercise boundary behavior",
    )
    assert completed.result.choices[0].recommendation == "Fixed limit"
    assert completed.repair_used is False
    assert len(provider.requests) == 1
    assert provider.requests[0].read_only is True
    assert provider.requests[0].repository_path == tmp_path.resolve()
    assert provider.requests[0].schema == elicitation_result_schema()

    stored = completed.stored
    assert stored.status == "validated"
    assert stored.specification_id == "SPEC1"
    assert stored.source_version == 1
    assert stored.provider == "fake"
    assert stored.model == "fake-structured-model"
    assert stored.artifact_path is not None and stored.artifact_path.is_file()
    artifact_bytes = stored.artifact_path.read_bytes()
    assert hashlib.sha256(artifact_bytes).hexdigest() == stored.artifact_hash
    assert json.loads(artifact_bytes) == stored.validated_result
    assert service.load_analysis(stored.analysis_id) == stored
    assert service.list_analyses("SPEC1") == [stored]

    with db.transaction(service.db_path) as conn:
        row = conn.execute(
            "SELECT * FROM specification_analyses WHERE id = ?", (stored.analysis_id,)
        ).fetchone()
        assert row["source_version"] == 1
        assert row["prompt_hash"] == stored.prompt_hash
        assert row["artifact_hash"] == stored.artifact_hash
        assert row["created_at"] and row["updated_at"]


def test_malformed_json_receives_exactly_one_successful_repair(tmp_path: Path) -> None:
    service = create_service(tmp_path)
    provider = FakeStructuredOutputProvider(["{not valid JSON", json.dumps(additive_result())])
    completed = ElicitationEngine(service, provider).analyze("SPEC1")
    assert completed.repair_used is True
    assert [request.repair for request in provider.requests] == [False, True]
    assert "one permitted repair request" in provider.requests[1].prompt
    assert completed.stored.application_metadata["repair_used"] is True


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda result: result["suggested_specification"].update(objectives=[]), "removed existing"),
        (
            lambda result: result["suggested_specification"].update(
                summary="Rewritten by the model"
            ),
            "non-empty user-authored scalar",
        ),
        (
            lambda result: result["suggested_specification"]["requirements"][0].update(
                id="R9"
            ),
            "stable ID changed",
        ),
        (
            lambda result: result["suggested_specification"]["decisions"].append(
                {
                    "topic": "Retry policy",
                    "selected_decision": "Fixed limit",
                    "rationale": "Model recommendation",
                    "rejected_alternatives": ["Time budget"],
                    "consequences": ["Bounded attempts"],
                }
            ),
            "may propose choices but may not add",
        ),
    ],
)
def test_non_additive_output_is_rejected_after_one_repair(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None], message: str
) -> None:
    service = create_service(tmp_path)
    invalid = additive_result()
    mutate(invalid)
    provider = FakeStructuredOutputProvider([invalid, copy.deepcopy(invalid)])
    with pytest.raises(ElicitationValidationError, match=message):
        ElicitationEngine(service, provider).analyze("SPEC1")
    assert [request.repair for request in provider.requests] == [False, True]
    analyses = service.list_analyses("SPEC1")
    assert len(analyses) == 1
    assert analyses[0].status == "failed"
    assert analyses[0].artifact_path is None


def test_broken_requirement_traceability_is_rejected(tmp_path: Path) -> None:
    service = create_service(tmp_path)
    invalid = additive_result()
    invalid["suggested_specification"]["use_cases"].append(
        {
            "id": "UC1",
            "title": "Broken link",
            "actors": ["User"],
            "preconditions": ["Repository exists"],
            "trigger": "Run command",
            "main_flow": ["Run"],
            "alternate_flows": ["Retry"],
            "postconditions": ["Result exists"],
            "error_and_edge_cases": ["Invalid input"],
            "requirement_ids": ["MISSING"],
        }
    )
    provider = FakeStructuredOutputProvider([invalid, invalid])
    with pytest.raises(ElicitationValidationError, match="unknown requirement identifier: MISSING"):
        ElicitationEngine(service, provider).analyze("SPEC1")
    assert len(provider.requests) == 2


def test_stale_source_version_is_rejected_at_transaction_boundary(tmp_path: Path) -> None:
    service = create_service(tmp_path)

    def revise_during_analysis(_request: StructuredOutputRequest) -> dict[str, Any]:
        service.revise(
            "SPEC1",
            replace(source_document(), summary="A user-authored newer revision."),
            change_summary="User changed the draft",
            creator="user",
        )
        return additive_result()

    provider = FakeStructuredOutputProvider([revise_during_analysis])
    with pytest.raises(StaleElicitationError, match="source is stale"):
        ElicitationEngine(service, provider).analyze("SPEC1", 1)
    assert len(provider.requests) == 1
    analyses = service.list_analyses("SPEC1")
    assert len(analyses) == 1
    assert analyses[0].status == "stale"
    assert analyses[0].source_version == 1
    assert analyses[0].validated_result is None


def test_runtime_validation_rejects_provider_claimed_schema_success() -> None:
    value = additive_result()
    value["unexpected"] = "provider said this was valid"
    with pytest.raises(ElicitationValidationError, match="unknown fields"):
        validate_elicitation_result(value, source_document())


def test_choices_only_creates_new_identical_draft_revision_and_choices(
    tmp_path: Path,
) -> None:
    service = create_service(tmp_path)
    original = service.load("SPEC1", 1)
    original_artifact = original.artifact_path.read_bytes()
    completed = ElicitationEngine(
        service, FakeStructuredOutputProvider([additive_result()])
    ).analyze("SPEC1")

    applied = apply_elicitation_analysis(
        service,
        completed.stored.analysis_id,
        application_mode="choices_only",
        creator="user",
    )

    assert applied.snapshot.version == 2
    assert applied.snapshot.status == "draft"
    assert applied.snapshot.document == original.document
    assert applied.snapshot.artifact_path != original.artifact_path
    assert original.artifact_path.read_bytes() == original_artifact
    assert applied.application_mode == "choices_only"
    assert applied.additions == ()
    assert applied.decisions_created == 1
    choices = service.list_decisions("SPEC1")
    assert len(choices) == 1
    assert choices[0]["source_version"] == 1
    assert choices[0]["topic"] == "Retry policy"
    assert choices[0]["status"] == "unresolved"
    assert choices[0]["blocking"] is True
    metadata = service.load_analysis(completed.stored.analysis_id).application_metadata
    assert metadata["applied_analysis_id"] == completed.stored.analysis_id
    assert metadata["application_mode"] == "choices_only"
    assert metadata["applied_version"] == 2
    assert metadata["added"] == []
    assert metadata["decisions_created"] == 1


def test_apply_all_creates_additive_revision_and_records_exact_additions(
    tmp_path: Path,
) -> None:
    service = create_service(tmp_path)
    suggestion = additive_result()
    suggestion["suggested_specification"]["requirements"][0][
        "acceptance_criteria"
    ].append("A nested additive criterion is retained.")
    completed = ElicitationEngine(
        service, FakeStructuredOutputProvider([suggestion])
    ).analyze("SPEC1")

    applied = apply_elicitation_analysis(
        service,
        completed.stored.analysis_id,
        application_mode="apply_all",
        creator="user",
    )

    assert applied.snapshot.version == 2
    assert applied.snapshot.document.title == "Exact user title"
    assert applied.snapshot.document.summary == "Exact user summary"
    assert applied.snapshot.document.objectives == (
        "Existing objective",
        "Exercise boundary behavior",
    )
    assert [change["path"] for change in applied.additions] == [
        "specification.objectives[1]",
        "specification.requirements[0].acceptance_criteria[1]",
        "specification.requirements[1]",
    ]
    assert all(change["operation"] == "append" for change in applied.additions)
    metadata = service.load_analysis(completed.stored.analysis_id).application_metadata
    assert metadata["added"] == list(applied.additions)
    assert "3 specification addition(s), 1 choice(s)" in applied.snapshot.change_summary


def test_applying_analysis_rejects_newer_stored_draft_without_partial_changes(
    tmp_path: Path,
) -> None:
    service = create_service(tmp_path)
    completed = ElicitationEngine(
        service, FakeStructuredOutputProvider([additive_result()])
    ).analyze("SPEC1")
    newer = service.revise(
        "SPEC1",
        replace(source_document(), summary="A newer exact user draft."),
        change_summary="User edit after analysis",
        creator="user",
    )

    with pytest.raises(StaleElicitationError, match="Run Analyze again"):
        apply_elicitation_analysis(
            service,
            completed.stored.analysis_id,
            application_mode="apply_all",
            creator="user",
        )

    assert service.load("SPEC1").version == newer.version == 2
    assert service.load("SPEC1").document.summary == "A newer exact user draft."
    assert service.list_decisions("SPEC1") == []
    assert "applied_version" not in service.load_analysis(
        completed.stored.analysis_id
    ).application_metadata
    assert not (tmp_path / "artifacts/specifications/SPEC1/versions/0003.json").exists()


@pytest.mark.parametrize("target", ["result_json", "artifact_hash", "artifact"])
def test_analysis_integrity_detects_independent_tampering(
    tmp_path: Path, target: str
) -> None:
    service = create_service(tmp_path)
    stored = ElicitationEngine(
        service, FakeStructuredOutputProvider([additive_result()])
    ).analyze("SPEC1").stored
    assert stored.artifact_path is not None
    if target == "artifact":
        stored.artifact_path.write_bytes(stored.artifact_path.read_bytes() + b"\n")
    else:
        with db.transaction(service.db_path) as conn:
            if target == "artifact_hash":
                conn.execute(
                    "UPDATE specification_analyses SET artifact_hash = ? WHERE id = ?",
                    ("0" * 64, stored.analysis_id),
                )
            else:
                tampered = copy.deepcopy(stored.validated_result)
                assert tampered is not None
                tampered["summary"] = "Tampered but canonical"
                conn.execute(
                    "UPDATE specification_analyses SET validated_result_json = ? WHERE id = ?",
                    (
                        json.dumps(tampered, sort_keys=True, separators=(",", ":")),
                        stored.analysis_id,
                    ),
                )
    with pytest.raises(SpecificationIntegrityError):
        service.load_analysis(stored.analysis_id)
