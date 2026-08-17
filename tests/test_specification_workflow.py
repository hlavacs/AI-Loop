from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ai_loop.specification_workflow import (
    EDITOR_STAGES,
    approve,
    assess_specification,
    create_draft,
    derive_formal_job_inputs,
    load_formal_job_inputs,
    return_to_draft,
    route_validation_issue,
    save_draft,
    submit_for_review,
)
from ai_loop.specifications import (
    SpecificationDocument,
    SpecificationService,
    SpecificationStateError,
    SpecificationValidationError,
    ValidationIssue,
)


def complete_document() -> SpecificationDocument:
    return SpecificationDocument.from_dict(
        {
            "schema_version": "1.0",
            "title": "Preserve public behavior",
            "summary": "Implement the requested behavior without changing the public API.",
            "objectives": ["Provide the requested behavior"],
            "in_scope": ["The command and its focused tests"],
            "out_of_scope": ["Unrelated command changes"],
            "stakeholders": ["Repository maintainers"],
            "assumptions": ["The supported Python runtime is installed"],
            "constraints": ["Keep the existing public API compatible"],
            "dependencies": ["Python standard library"],
            "use_cases": [
                {
                    "id": "UC1",
                    "title": "Run the command",
                    "actors": ["User"],
                    "preconditions": ["The repository is available"],
                    "trigger": "The user invokes the command",
                    "main_flow": ["Validate input", "Perform the operation", "Report success"],
                    "alternate_flows": ["Use the documented default"],
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
                    "acceptance_criteria": [
                        "Invalid input returns an error and leaves state unchanged."
                    ],
                    "source": "User brief",
                },
            ],
            "decisions": [
                {
                    "topic": "Compatibility",
                    "selected_decision": "Retain the existing command signature",
                    "rationale": "Existing callers depend on it",
                    "rejected_alternatives": ["Replace the command"],
                    "consequences": ["New behavior remains additive"],
                }
            ],
            "risks": [],
            "verification": [
                {
                    "id": "VT1",
                    "title": "Command behavior",
                    "requirement_ids": ["R1", "R2"],
                    "test_level": "acceptance",
                    "method": "deterministic",
                    "oracle": "Expected results encoded independently in the fixture",
                    "fixtures": ["A valid and an invalid input"],
                    "procedure": ["Run the focused test", "Inspect the emitted result"],
                    "pass_criteria": ["Valid and invalid scenarios match the oracle"],
                    "declared_metrics": ["duration_seconds"],
                    "metric_assertions": [
                        {
                            "metric": "duration_seconds",
                            "operator": "<=",
                            "threshold": 5,
                            "tolerance": 0,
                        }
                    ],
                    "coverage_targets": ["Valid and invalid input scenarios"],
                    "automation": "automated",
                    "blocking": True,
                    "validation_loop": {
                        "maximum_correction_attempts": 2,
                        "repetitions_per_attempt": 1,
                        "stagnation_limit": 1,
                        "escalation_condition": "Escalate when attempts are exhausted",
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
    )


@pytest.mark.parametrize(
    ("path", "expected_stage"),
    [
        ("title", "Overview"),
        ("constraints[0]", "Scope"),
        ("use_cases[0].main_flow", "Use Cases"),
        ("requirements[0].acceptance_criteria", "Requirements"),
        ("risks[0].mitigations", "Risks"),
        ("verification[0].oracle", "Verification"),
        ("open_questions", "Choices"),
        ("schema_version", "Review"),
    ],
)
def test_issue_routing_covers_every_editor_stage(path: str, expected_stage: str) -> None:
    source = ValidationIssue("approval", path, "error", "Fix this field")
    routed = route_validation_issue(source)
    assert routed.owning_stage == expected_stage
    assert routed.path == path
    assert routed.severity == "error"
    assert routed.message == "Fix this field"
    assert routed.actionable_message == "Fix this field"


def test_stage_assessment_uses_structural_and_approval_validation() -> None:
    document = replace(SpecificationDocument.empty(), schema_version="2.0")
    assessment = assess_specification(document, unresolved_blocking_decisions=1)

    assert not assessment.structurally_valid
    assert not assessment.approval_ready
    assert tuple(assessment.issues_by_stage()) == EDITOR_STAGES
    assert any(issue.path == "schema_version" for issue in assessment.issues_for_stage("Review"))
    assert any(issue.path == "title" for issue in assessment.issues_for_stage("Overview"))
    assert any(issue.path == "in_scope" for issue in assessment.issues_for_stage("Scope"))
    assert any(issue.path == "use_cases" for issue in assessment.issues_for_stage("Use Cases"))
    assert any(issue.path == "requirements" for issue in assessment.issues_for_stage("Requirements"))
    assert any(issue.path == "choices" for issue in assessment.issues_for_stage("Choices"))
    with pytest.raises(ValueError, match="unknown specification editor stage"):
        assessment.issues_for_stage("Unknown")


def test_workflow_lifecycle_delegates_transitions_and_gates(tmp_path: Path) -> None:
    service = SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts")
    created = create_draft(
        service,
        tmp_path,
        complete_document(),
        creator="author",
        specification_id="SPEC1",
    )
    assert (created.status, created.version) == ("draft", 1)

    revised = save_draft(
        service,
        "SPEC1",
        replace(created.document, summary="A user-authored clarified summary."),
        creator="author",
        change_summary="Clarify the summary",
    )
    assert (revised.status, revised.version) == ("draft", 2)
    assert submit_for_review(service, "SPEC1").status == "review"
    with pytest.raises(SpecificationStateError, match="only a draft"):
        submit_for_review(service, "SPEC1")
    with pytest.raises(SpecificationStateError, match="only a draft or approved"):
        save_draft(
            service,
            "SPEC1",
            revised.document,
            creator="author",
            change_summary="Invalid review edit",
        )

    assert return_to_draft(service, "SPEC1").status == "draft"
    submit_for_review(service, "SPEC1")
    approved = approve(service, "SPEC1", approved_by="owner")
    assert approved.status == "approved"
    assert approved.approved_at is not None
    with pytest.raises(SpecificationStateError, match="under review"):
        return_to_draft(service, "SPEC1")


def test_workflow_approval_rejects_incomplete_verification_coverage(tmp_path: Path) -> None:
    service = SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts")
    payload = complete_document().to_dict()
    payload["verification"][0]["requirement_ids"] = ["R1"]
    incomplete = SpecificationDocument.from_dict(payload)
    create_draft(
        service,
        tmp_path,
        incomplete,
        creator="author",
        specification_id="SPEC1",
    )
    submit_for_review(service, "SPEC1")

    with pytest.raises(SpecificationValidationError, match="R2.*not covered"):
        approve(service, "SPEC1", approved_by="owner")
    assert service.load("SPEC1").status == "review"


def test_formal_job_derivation_preserves_contract_and_traceability(tmp_path: Path) -> None:
    service = SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts")
    draft = create_draft(
        service,
        tmp_path,
        complete_document(),
        creator="author",
        specification_id="SPEC1",
    )
    with pytest.raises(SpecificationStateError, match="approved immutable"):
        derive_formal_job_inputs(draft)

    submit_for_review(service, "SPEC1")
    approved = approve(service, "SPEC1", approved_by="owner")
    inputs = load_formal_job_inputs(service, "SPEC1", approved.version)

    assert "SPEC1 version 1" in inputs.goal
    assert approved.canonical_content_hash in inputs.goal
    assert approved.document.title in inputs.goal
    assert approved.document.summary in inputs.goal
    assert inputs.requirement_ids == ("R1", "R2")
    assert inputs.verification_ids == ("VT1",)
    assert any("authoritative" in item and "SPEC1 version 1" in item for item in inputs.constraints)
    assert "[Out of scope] Unrelated command changes" in inputs.constraints
    assert "[Assumption] The supported Python runtime is installed" in inputs.constraints
    assert any("Keep the existing public API compatible" in item for item in inputs.constraints)
    assert "[Approved decision: Compatibility] Retain the existing command signature" in inputs.constraints
    assert "[Approved decision consequence: Compatibility] New behavior remains additive" in inputs.constraints
    assert "[Requirement R1] The example input produces the expected result." in inputs.acceptance
    assert (
        "[Requirement R2] Invalid input returns an error and leaves state unchanged."
        in inputs.acceptance
    )
    assert "[Blocking verification VT1] Valid and invalid scenarios match the oracle" in inputs.acceptance
    assert inputs.as_job_inputs() == {
        "goal": inputs.goal,
        "constraints": list(inputs.constraints),
        "acceptance": list(inputs.acceptance),
    }
