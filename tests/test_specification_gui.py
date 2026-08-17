from __future__ import annotations

import os
from pathlib import Path

import pytest

from ai_loop.specification_gui import (
    MetricAssertionParseError,
    _verification_for_dialog,
    _verification_from_dialog,
    document_to_record,
    format_metric_assertions,
    format_structured_records,
    issues_by_tab,
    parse_metric_assertions,
    parse_structured_records,
    record_to_document,
    render_choice_summary,
    render_specification_json_diff,
    open_specification_editor,
)
from ai_loop.specification_workflow import EDITOR_STAGES, StageAssessment, WorkflowIssue
from ai_loop.specifications import SpecificationDocument, SpecificationService


def editable_document(worktree: Path) -> SpecificationDocument:
    payload = SpecificationDocument.empty(
        title="Preserve this exact title",
        summary="First line.\n\n  User-authored indentation stays.",
    ).to_dict()
    payload.update(
        {
            "objectives": ["Objective with trailing spaces  "],
            "in_scope": ["Formal editing"],
            "out_of_scope": ["Automatic implementation"],
            "stakeholders": ["Specification owner"],
            "requirements": [
                {
                    "id": "R1",
                    "category": "functional",
                    "priority": "must",
                    "title": "Save exact text",
                    "statement": "The editor shall preserve authored content.",
                    "rationale": "The user owns the contract.",
                    "acceptance_criteria": ["A round trip is byte-for-byte equal per string."],
                    "source": "User",
                },
                {
                    "id": "R2",
                    "category": "quality",
                    "priority": "must",
                    "title": "Remain responsive",
                    "statement": "The editor shall run service work outside the Tk thread.",
                    "rationale": "A blocked editor can lose user input.",
                    "acceptance_criteria": ["The background callback performs service calls."],
                    "source": "User",
                },
            ],
            "use_cases": [
                {
                    "id": "UC1",
                    "title": "Edit a draft",
                    "actors": ["Owner"],
                    "preconditions": ["A draft exists"],
                    "trigger": "The owner opens it",
                    "main_flow": ["Edit text", "Save the draft"],
                    "alternate_flows": ["Cancel without saving"],
                    "postconditions": ["The selected revision is stored"],
                    "error_and_edge_cases": ["Validation errors identify the field"],
                    "requirement_ids": ["R1", "R2"],
                }
            ],
            "verification": [
                {
                    "id": "VT1",
                    "title": "Round trip",
                    "requirement_ids": ["R1", "R2"],
                    "test_level": "unit",
                    "method": "deterministic",
                    "oracle": "The original document",
                    "fixtures": ["Authored whitespace"],
                    "procedure": ["Convert to a record", "Convert back"],
                    "pass_criteria": ["Documents compare equal"],
                    "declared_metrics": ["changed_fields"],
                    "metric_assertions": [
                        {
                            "metric": "changed_fields",
                            "operator": "==",
                            "threshold": 0.0,
                            "tolerance": 0.0,
                        }
                    ],
                    "coverage_targets": ["Every specification field"],
                    "automation": "automated",
                    "blocking": True,
                    "validation_loop": {
                        "maximum_correction_attempts": 1,
                        "repetitions_per_attempt": 1,
                        "stagnation_limit": 1,
                        "escalation_condition": "Escalate after the bounded attempt",
                        "retain_evidence": True,
                    },
                    "command_override": None,
                    "working_directory": ".",
                    "timeout": 30,
                    "required_evidence": ["Test log"],
                }
            ],
        }
    )
    return SpecificationDocument.from_dict(payload, worktree=worktree)


def test_document_record_round_trip_preserves_authored_values(tmp_path: Path) -> None:
    document = editable_document(tmp_path)

    record = document_to_record(document)
    record["summary"] = "Editor-only mutation"

    assert document.summary == "First line.\n\n  User-authored indentation stays."
    record["summary"] = document.summary
    restored = record_to_document(record, worktree=tmp_path)
    assert restored == document
    assert restored.objectives == ("Objective with trailing spaces  ",)


def test_metric_assertion_expression_round_trip_and_numeric_normalization() -> None:
    parsed = parse_metric_assertions(
        "duration_seconds <= 5.0 0.25\nrequests != 0\nerror_rate < 0.01"
    )

    assert [(item.metric, item.operator) for item in parsed] == [
        ("duration_seconds", "<="),
        ("requests", "!="),
        ("error_rate", "<"),
    ]
    assert parsed[0].threshold == 5
    assert parsed[0].tolerance == 0.25
    assert parsed[1].tolerance is None
    assert format_metric_assertions(parsed) == (
        "duration_seconds <= 5 0.25\nrequests != 0\nerror_rate < 0.01"
    )


def test_structured_verification_records_survive_edit_persist_reload_round_trip(
    tmp_path: Path,
) -> None:
    payload = editable_document(tmp_path).to_dict()
    verification = payload["verification"][0]
    verification["coverage_targets"] = [
        {
            "name": "scenario-coverage",
            "coverage_type": "scenario",
            "description": "Original scenario observation",
            "measurement_key": "scenario.rate",
            "operator": ">=",
            "threshold": 0.9,
            "tolerance": 0.01,
            "required_scenarios": ["ordinary", "invalid"],
            "evidence_kind": "coverage",
        }
    ]
    verification["required_evidence"] = [
        {
            "name": "scenario-observations",
            "kind": "structured-data",
            "media_type": "application/json",
            "description": "Original structured observations",
            "requirement_ids": ["R1", "R2"],
        }
    ]
    document = SpecificationDocument.from_dict(payload, worktree=tmp_path)
    service = SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts")
    created = service.create(
        tmp_path,
        document,
        creator="author",
        specification_id="SPEC-ROUND-TRIP",
    )

    record = document_to_record(created.document)
    dialog_record = _verification_for_dialog(record["verification"][0])
    dialog_record["metric_assertions"] = "changed_fields == 1 0"

    coverage_records = list(parse_structured_records(dialog_record["coverage_targets"]))
    coverage_records[0]["description"] = "Edited scenario observation"
    coverage_records[0]["threshold"] = 0.95
    dialog_record["coverage_targets"] = format_structured_records(coverage_records)

    evidence_records = list(parse_structured_records(dialog_record["required_evidence"]))
    evidence_records[0]["description"] = "Edited structured observations"
    evidence_records[0]["media_type"] = "application/vnd.ai-loop.observations+json"
    dialog_record["required_evidence"] = format_structured_records(evidence_records)

    record["verification"][0] = _verification_from_dialog(dialog_record)
    edited = record_to_document(record, worktree=tmp_path)
    service.revise(
        created.specification_id,
        edited,
        change_summary="Edit assertions and observation evidence",
        creator="author",
    )
    reloaded = service.load(created.specification_id).document.to_dict()["verification"][0]

    assert reloaded["metric_assertions"] == [
        {
            "metric": "changed_fields",
            "operator": "==",
            "threshold": 1,
            "tolerance": 0,
        }
    ]
    assert reloaded["coverage_targets"] == coverage_records
    assert reloaded["required_evidence"] == evidence_records


@pytest.mark.parametrize(
    ("text", "line", "detail"),
    [
        ("ok >= 1\n\nbroken expression\nlast <= 2", 3, "expected"),
        ("ok >= 1\nok <= 2", 2, "already has an assertion"),
        ("ok == 1 -0.1", 1, "non-negative"),
        ("ok == nan", 1, "finite"),
    ],
)
def test_metric_assertion_parse_errors_name_exact_line(
    text: str, line: int, detail: str
) -> None:
    with pytest.raises(MetricAssertionParseError) as caught:
        parse_metric_assertions(text)

    assert caught.value.line_number == line
    assert str(caught.value).startswith(f"line {line}:")
    assert detail in str(caught.value)


def test_issue_to_tab_routing_is_complete_and_stable() -> None:
    assessment = StageAssessment(
        issues=(
            WorkflowIssue("Overview", "title", "error", "Title is required"),
            WorkflowIssue("Verification", "verification[0].oracle", "warning", "Add oracle"),
            WorkflowIssue("Not A Tab", "unknown.path", "error", "Fallback issue"),
        ),
        structurally_valid=False,
        approval_ready=False,
    )

    routed = issues_by_tab(assessment)

    assert tuple(routed) == EDITOR_STAGES
    assert routed["Overview"] == (assessment.issues[0],)
    assert routed["Verification"] == (assessment.issues[1],)
    assert routed["Review"] == (assessment.issues[2],)
    assert all(isinstance(routed[stage], tuple) for stage in EDITOR_STAGES)


def test_specification_gui_import_exposes_every_stage_without_opening_tk() -> None:
    # The import at module collection time succeeds without constructing Tk.
    assert EDITOR_STAGES == (
        "Overview",
        "Scope",
        "Use Cases",
        "Requirements",
        "Risks",
        "Verification",
        "Choices",
        "Review",
    )


def test_exact_json_diff_is_deterministic_and_preserves_complete_json_context() -> None:
    source = SpecificationDocument.empty(title="A")
    suggestion = SpecificationDocument.empty(title="A", summary="B")

    assert render_specification_json_diff(source, suggestion) == (
        "--- stored-draft.json\n"
        "+++ suggested-specification.json\n"
        "@@ -11,7 +11,7 @@\n"
        '   "risks": [],\n'
        '   "schema_version": "1.0",\n'
        '   "stakeholders": [],\n'
        '-  "summary": "",\n'
        '+  "summary": "B",\n'
        '   "title": "A",\n'
        '   "use_cases": [],\n'
        '   "verification": []\n'
    )


def test_choice_summary_is_separate_and_includes_all_decision_fields() -> None:
    summary = render_choice_summary(
        [
            {
                "topic": "Retry policy",
                "question": "Which bounded policy?",
                "context": "The repository has no approved limit.",
                "options": [
                    {
                        "name": "Fixed",
                        "description": "Use an attempt count.",
                        "tradeoffs": ["Predictable", "Less adaptive"],
                    },
                    {
                        "name": "Budget",
                        "description": "Use elapsed time.",
                        "tradeoffs": ["Adaptive", "Variable attempts"],
                    },
                ],
                "recommendation": "Fixed",
                "blocking": True,
            }
        ]
    )

    for expected in (
        "Topic: Retry policy",
        "Question: Which bounded policy?",
        "Context: The repository has no approved limit.",
        "Recommendation: Fixed",
        "Blocking: yes",
        "Fixed: Use an attempt count.",
        "Tradeoff: Predictable",
        "Budget: Use elapsed time.",
    ):
        assert expected in summary
    assert "suggested_specification" not in summary


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a Tk display")
def test_staged_editor_smoke_uses_initial_goal_and_all_tabs(tmp_path: Path) -> None:
    try:
        import tkinter as tk
    except ImportError:
        pytest.skip("Tk is not installed")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk cannot connect to a display")
    root.withdraw()

    def immediate_runner(work, done, **_kwargs):
        try:
            done(work(), None)
        except Exception as exc:  # pragma: no cover - diagnostic error path
            done(None, str(exc))

    try:
        editor = open_specification_editor(
            root,
            service=SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts"),
            repository_path=tmp_path,
            initial_goal="Exact optional goal text",
            run_background=immediate_runner,
            elicitation_provider_factory=lambda: object(),
        )
        assert editor.summary_text.get("1.0", "end-1c") == "Exact optional goal text"
        assert tuple(editor.tabs) == EDITOR_STAGES
        labels = [
            editor.notebook.tab(editor.tabs[stage], "text").lstrip("! ")
            for stage in EDITOR_STAGES
        ]
        assert labels == list(EDITOR_STAGES)
        assert "Milestone 4" in editor.deferred_var.get()

        editor.record = document_to_record(editable_document(tmp_path))
        editor._load_record_into_widgets()
        editor._refresh_assessment()
        assert editor.assessment.approval_ready
        editor.save_draft()
        assert editor.snapshot is not None
        assert editor.snapshot.status == "draft"
        assert str(editor.analyze_button.cget("state")) == "normal"
        editor._set_busy(True, "Test analysis in progress")
        assert str(editor.save_button.cget("state")) == "disabled"
        assert str(editor.submit_button.cget("state")) == "disabled"
        assert str(editor.approve_button.cget("state")) == "disabled"
        assert str(editor.analyze_button.cget("state")) == "disabled"
        editor._set_busy(False)
        assert str(editor.analyze_button.cget("state")) == "normal"
        editor.submit_for_review()
        assert editor.snapshot.status == "review"
        editor.approve()
        assert editor.snapshot.status == "approved"
        editor.window.destroy()
    finally:
        root.destroy()
