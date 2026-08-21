from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_loop.specification_gui import (
    FieldSemanticFeedback,
    MetricAssertionParseError,
    PROCESS_OVERVIEW_TEXT,
    SPECIFICATION_FIELD_EXAMPLES,
    SPECIFICATION_FIELD_GUIDANCE,
    SPECIFICATION_SAVEFILE_SCHEMA,
    SPECIFICATION_SAVEFILE_VERSION,
    SpecificationSavefileError,
    SpecificationSuggestion,
    _verification_for_dialog,
    _verification_from_dialog,
    analyze_specification,
    analyze_specification_suggestions,
    compute_field_feedback,
    document_to_record,
    format_metric_assertions,
    format_structured_records,
    issues_by_tab,
    parse_metric_assertions,
    parse_structured_records,
    record_to_document,
    render_choice_summary,
    render_specification_json_diff,
    savefile_to_record,
    specification_to_savefile_bytes,
    open_specification_editor,
    worked_example_document,
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


def test_specification_savefile_round_trips_records_losslessly(tmp_path: Path) -> None:
    records = (
        document_to_record(editable_document(tmp_path)),
        document_to_record(worked_example_document(worktree=tmp_path)),
    )

    for record in records:
        content = specification_to_savefile_bytes(record)
        assert f'"schema": "{SPECIFICATION_SAVEFILE_SCHEMA}"'.encode() in content
        assert f'"version": {SPECIFICATION_SAVEFILE_VERSION}'.encode() in content
        assert savefile_to_record(content) == record
        assert record_to_document(savefile_to_record(content), worktree=tmp_path).to_dict() == record


def test_specification_savefile_preserves_an_unfinished_wizard_draft() -> None:
    record = document_to_record(SpecificationDocument.empty())
    record["title"] = "Work in progress"
    record["summary"] = "TBD"
    record["requirements"] = []

    restored = savefile_to_record(specification_to_savefile_bytes(record))

    assert restored == record
    assert analyze_specification(restored)[0].severity == "blocking"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"not json", "Malformed specification JSON"),
        (b"[]", "must contain a JSON object"),
        (
            b'{"schema":"some-other-schema","version":1,"specification":{}}',
            "Incompatible specification file schema",
        ),
        (
            b'{"schema":"ai-loop/specification-draft","version":2,"specification":{}}',
            "Unsupported specification file version",
        ),
        (
            b'{"schema":"ai-loop/specification-draft","version":1,"specification":[]}',
            "field 'specification' must contain a JSON object",
        ),
        (
            b'{"schema":"ai-loop/specification-draft","version":1,"specification":{}}',
            "incompatible editable shape",
        ),
    ],
)
def test_specification_savefile_rejects_malformed_or_incompatible_content(
    content: bytes, message: str
) -> None:
    with pytest.raises(SpecificationSavefileError, match=message):
        savefile_to_record(content)


def test_gui_formal_specification_entrypoint_selects_dedicated_tab() -> None:
    from ai_loop_gui import AiLoopGui

    selected: list[object] = []
    initialized: list[bool] = []
    gui = AiLoopGui.__new__(AiLoopGui)
    gui.specification_tab = object()
    gui.workspace = SimpleNamespace(select=selected.append)
    gui._ensure_specification_tab_editor = lambda: initialized.append(True)

    gui.open_formal_specification()

    assert selected == [gui.specification_tab]
    assert initialized == [True]


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
    assert isinstance(coverage_records[0], dict)
    coverage_records[0]["description"] = "Edited scenario observation"
    coverage_records[0]["threshold"] = 0.95
    dialog_record["coverage_targets"] = format_structured_records(coverage_records)

    evidence_records = list(parse_structured_records(dialog_record["required_evidence"]))
    assert isinstance(evidence_records[0], dict)
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


def test_onboarding_copy_covers_process_and_every_specification_input() -> None:
    import ai_loop.specification_gui as specification_gui

    for expected in (
        "Author the specification",
        "submit it for review",
        "approve",
        "Start Implementation",
        "PLAN",
        "worker implements",
        "runtime proof",
        "DONE",
    ):
        assert expected in PROCESS_OVERVIEW_TEXT

    top_level_inputs = {
        "title",
        "summary",
        "objectives",
        "stakeholders",
        "in_scope",
        "out_of_scope",
        "assumptions",
        "constraints",
        "dependencies",
        "use_cases",
        "requirements",
        "risks",
        "verification",
        "decisions",
        "open_questions",
    }
    field_groups = {
        "use_cases": specification_gui.USE_CASE_FIELDS,
        "requirements": specification_gui.REQUIREMENT_FIELDS,
        "risks": specification_gui.RISK_FIELDS,
        "decisions": specification_gui.DECISION_FIELDS,
        "verification": specification_gui.VERIFICATION_FIELDS,
    }
    expected_paths = top_level_inputs | {
        f"{group}.{field.key}"
        for group, fields in field_groups.items()
        for field in fields
    }

    assert expected_paths <= set(SPECIFICATION_FIELD_GUIDANCE)
    assert expected_paths <= set(SPECIFICATION_FIELD_EXAMPLES)
    assert all(SPECIFICATION_FIELD_GUIDANCE[path].strip() for path in expected_paths)
    assert all(SPECIFICATION_FIELD_EXAMPLES[path].strip() for path in expected_paths)
    assert "blocking automated coverage" in SPECIFICATION_FIELD_GUIDANCE["requirements"]
    assert "runtime evidence" in SPECIFICATION_FIELD_GUIDANCE["verification"]
    assert "verification fixtures" in SPECIFICATION_FIELD_GUIDANCE["assumptions"]


def test_worked_example_populates_every_field_and_round_trips(tmp_path: Path) -> None:
    document = worked_example_document(worktree=tmp_path)
    record = document_to_record(document)

    def assert_populated(value: object, path: str) -> None:
        if isinstance(value, str):
            assert value.strip(), path
        elif isinstance(value, list):
            assert value, path
            for index, item in enumerate(value):
                assert_populated(item, f"{path}[{index}]")
        elif isinstance(value, dict):
            assert value, path
            for key, item in value.items():
                assert_populated(item, f"{path}.{key}")
        else:
            assert value is not None, path

    assert_populated(record, "specification")
    assert record_to_document(record, worktree=tmp_path) == document
    assert document.open_questions


def test_field_feedback_uses_workflow_traceability_and_runtime_assertions(
    tmp_path: Path,
) -> None:
    strong = document_to_record(worked_example_document(worktree=tmp_path))

    healthy = compute_field_feedback(strong, worktree=tmp_path)

    assert isinstance(healthy["title"], FieldSemanticFeedback)
    assert healthy["title"].health == "healthy"
    assert healthy["requirements"].health == "healthy"
    assert healthy["verification[0].metric_assertions"].health == "healthy"

    weak = document_to_record(worked_example_document(worktree=tmp_path))
    weak["summary"] = ""
    weak["title"] = "TBD"
    weak["verification"][0]["requirement_ids"] = []
    weak["verification"][0]["metric_assertions"] = []

    feedback = compute_field_feedback(weak, worktree=tmp_path)

    assert feedback["summary"].health == "empty"
    assert "required for approval" in feedback["summary"].message
    assert feedback["title"].health == "weak"
    assert "placeholder" in feedback["title"].message
    assert "not covered by verification" in feedback["requirements[0].id"].message
    assert "runtime-provable metric assertions" in feedback[
        "verification[0].metric_assertions"
    ].message


def test_holistic_specification_suggestions_are_ranked_and_report_clean_draft(
    tmp_path: Path,
) -> None:
    record = document_to_record(editable_document(tmp_path))
    record["summary"] = ""
    record["title"] = "TBD"
    record["verification"][0]["metric_assertions"] = []
    original = document_to_record(record_to_document(record, worktree=tmp_path))

    suggestions = analyze_specification_suggestions(record, worktree=tmp_path)

    assert suggestions == analyze_specification(record, worktree=tmp_path)

    assert all(isinstance(item, SpecificationSuggestion) for item in suggestions)
    assert [item.severity for item in suggestions] == [
        "blocking",
        "important",
        "advisory",
    ]
    assert suggestions[0].field == "summary"
    assert suggestions[0].tab == "Overview"
    assert "before approval" in suggestions[0].message
    assert suggestions[1].field == "verification[0].metric_assertions"
    assert suggestions[1].tab == "Verification"
    assert "runtime-provable" in suggestions[1].message
    assert suggestions[2].field == "title"
    assert "placeholder" in suggestions[2].message
    assert record == original

    clean_record = document_to_record(worked_example_document(worktree=tmp_path))
    clean_record["open_questions"] = []

    assert analyze_specification_suggestions(clean_record, worktree=tmp_path) == (
        SpecificationSuggestion(
            severity="clear",
            field="specification",
            tab="Review",
            message=(
                "No blocking issues found. The specification is ready for workflow review."
            ),
        ),
    )


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a Tk display")
def test_editor_can_embed_in_specification_tab_with_json_controls(
    tmp_path: Path,
) -> None:
    try:
        import tkinter as tk
        from tkinter import ttk
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
        host = ttk.Frame(root)
        host.grid(row=0, column=0, sticky="nsew")
        editor = open_specification_editor(
            host,
            service=SpecificationService(
                tmp_path / "loop.sqlite3", tmp_path / "artifacts"
            ),
            repository_path=tmp_path,
            run_background=immediate_runner,
            embedded=True,
        )

        assert editor.window is host
        assert editor.close_button.winfo_manager() == ""
        assert editor.save_specification_button.cget("text") == "Save JSON"
        assert editor.load_specification_button.cget("text") == "Load JSON"
        assert editor.notebook.winfo_manager() == "grid"
        assert set(editor._stage_scroll_canvases) == {"Overview", "Scope"}
        assert all(
            str(canvas.cget("yscrollcommand"))
            for canvas in editor._stage_scroll_canvases.values()
        )
        assert all(
            str(widget.cget("yscrollcommand"))
            for widget in (
                editor.summary_text,
                editor.objectives_text,
                editor.stakeholders_text,
                *editor.scope_widgets.values(),
                editor.open_questions_text,
            )
        )
        assert editor._responsive_wraplength(640, margin=20) == 620
        assert editor._responsive_wraplength(1400, margin=20) == 1040
        editor.close()
        assert host.winfo_exists()
    finally:
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a Tk display")
def test_editor_live_feedback_reacts_to_field_edits(tmp_path: Path) -> None:
    try:
        import tkinter as tk
    except ImportError:
        pytest.skip("Tk is not installed")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk cannot connect to a display")
    root.withdraw()

    try:
        editor = open_specification_editor(
            root,
            service=SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts"),
            repository_path=tmp_path,
        )
        assert "Empty" in editor.guidance_labels["title"].cget("text")

        editor.title_var.set("TBD")
        editor._finish_scheduled_assessment()
        assert "replace placeholder" in editor.guidance_labels["title"].cget("text")

        editor.title_var.set("Appointment reminder delivery")
        editor._finish_scheduled_assessment()
        assert "Looks good" in editor.guidance_labels["title"].cget("text")
        editor.window.destroy()
    finally:
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a Tk display")
def test_editor_renders_guidance_and_load_example_control(tmp_path: Path) -> None:
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        pytest.skip("Tk is not installed")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk cannot connect to a display")
    root.withdraw()

    import ai_loop.specification_gui as specification_gui

    def immediate_runner(work, done, **_kwargs):
        try:
            done(work(), None)
        except Exception as exc:  # pragma: no cover - diagnostic error path
            done(None, str(exc))

    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)

    try:
        editor = open_specification_editor(
            root,
            service=SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts"),
            repository_path=tmp_path,
            run_background=immediate_runner,
        )
        assert editor.process_overview_label.winfo_manager() == "grid"
        assert editor.process_overview_label.cget("text") == PROCESS_OVERVIEW_TEXT
        assert all(
            label.winfo_manager()
            and "Example:" in str(label.cget("text"))
            for label in editor.guidance_labels.values()
        )
        assert {
            "title",
            "summary",
            "objectives",
            "stakeholders",
            "in_scope",
            "out_of_scope",
            "assumptions",
            "constraints",
            "dependencies",
            "use_cases",
            "requirements",
            "risks",
            "verification",
            "decisions",
            "open_questions",
        } <= set(editor.guidance_labels)

        load_buttons = [
            widget
            for widget in descendants(editor.window)
            if isinstance(widget, ttk.Button) and widget.cget("text") == "Load example"
        ]
        assert load_buttons == [editor.load_example_button]

        field_groups = {
            "use_cases": specification_gui.USE_CASE_FIELDS,
            "requirements": specification_gui.REQUIREMENT_FIELDS,
            "risks": specification_gui.RISK_FIELDS,
            "decisions": specification_gui.DECISION_FIELDS,
            "verification": specification_gui.VERIFICATION_FIELDS,
        }
        for key, fields in field_groups.items():
            dialog = specification_gui._RecordDialog(
                editor.window,
                f"Guidance for {key}",
                fields,
                field_path_prefix=key,
            )
            assert set(dialog.guidance_labels) == {field.key for field in fields}
            assert all(
                label.winfo_manager()
                and "Example:" in str(label.cget("text"))
                for label in dialog.guidance_labels.values()
            )
            dialog.window.destroy()

        editor.load_example_button.invoke()
        assert editor.snapshot is None
        assert editor.selector_var.get() == "New specification"
        assert "not submitted or approved" in editor.status_var.get()
        assert str(editor.start_button.cget("state")) == "disabled"
        assert not editor.assessment.approval_ready
        assert all(editor.record[key] for key in field_groups)

        loaded = editor._current_document()
        loaded_record = document_to_record(loaded)
        assert loaded_record == editor._collect_record()
        editor.record = loaded_record
        editor._load_record_into_widgets()
        assert editor._current_document() == loaded
        editor.window.destroy()
    finally:
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a Tk display")
def test_editor_save_and_load_specification_file_handlers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    try:
        import tkinter as tk
    except ImportError:
        pytest.skip("Tk is not installed")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk cannot connect to a display")
    root.withdraw()

    import ai_loop.specification_gui as specification_gui

    def immediate_runner(work, done, **_kwargs):
        try:
            done(work(), None)
        except Exception as exc:  # pragma: no cover - diagnostic error path
            done(None, str(exc))

    save_path = tmp_path / "saved-specification.json"
    monkeypatch.setattr(
        specification_gui.filedialog,
        "asksaveasfilename",
        lambda **_kwargs: str(save_path),
    )
    monkeypatch.setattr(
        specification_gui.filedialog,
        "askopenfilename",
        lambda **_kwargs: str(save_path),
    )

    try:
        editor = open_specification_editor(
            root,
            service=SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts"),
            repository_path=tmp_path,
            run_background=immediate_runner,
            implementation_work_factory=lambda _snapshot: lambda: "must-not-run",
        )
        editor.load_example()
        expected = editor._collect_record()

        editor.save_specification_button.invoke()
        assert savefile_to_record(save_path.read_bytes()) == expected

        editor.record = document_to_record(SpecificationDocument.empty())
        editor._load_record_into_widgets()
        assert editor._collect_record() != expected

        refresh_calls = 0
        original_refresh = editor._refresh_assessment

        def track_refresh() -> None:
            nonlocal refresh_calls
            refresh_calls += 1
            original_refresh()

        monkeypatch.setattr(editor, "_refresh_assessment", track_refresh)
        editor.load_specification_button.invoke()

        assert editor._collect_record() == expected
        assert editor._current_document() == worked_example_document(worktree=tmp_path)
        assert refresh_calls == 1
        assert editor.snapshot is None
        assert editor.selector_var.get() == "New specification"
        assert "not submitted or approved" in editor.status_var.get()
        assert str(editor.start_button.cget("state")) == "disabled"
        editor.window.destroy()
    finally:
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a Tk display")
def test_editor_test_specification_button_is_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    try:
        import tkinter as tk
    except ImportError:
        pytest.skip("Tk is not installed")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk cannot connect to a display")
    root.withdraw()

    import ai_loop.specification_gui as specification_gui

    shown: list[tuple[SpecificationSuggestion, ...]] = []

    class ReviewDialog:
        def __init__(self, _parent, suggestions):
            shown.append(tuple(suggestions))

        def show(self):
            return None

    monkeypatch.setattr(
        specification_gui,
        "_SpecificationSuggestionsDialog",
        ReviewDialog,
    )

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
            run_background=immediate_runner,
            implementation_work_factory=lambda _snapshot: lambda: "must-not-run",
        )
        editor.load_example()
        snapshot_before = editor.snapshot
        draft_before = editor._current_document().canonical_json()
        choices_before = tuple(editor.suggested_choices)

        assert editor.test_specification_button.cget("text") == "Test specification"
        assert str(editor.start_button.cget("state")) == "disabled"
        editor.test_specification_button.invoke()

        assert shown
        assert any(item.severity == "blocking" for item in shown[0])
        assert editor.snapshot is snapshot_before
        assert editor._current_document().canonical_json() == draft_before
        assert tuple(editor.suggested_choices) == choices_before
        assert str(editor.start_button.cget("state")) == "disabled"
        editor.window.destroy()
    finally:
        root.destroy()


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
            implementation_work_factory=lambda _snapshot: lambda: "J-SMOKE",
        )
        assert editor.summary_text.get("1.0", "end-1c") == "Exact optional goal text"
        assert tuple(editor.tabs) == EDITOR_STAGES
        labels = [
            editor.notebook.tab(editor.tabs[stage], "text").lstrip("! ")
            for stage in EDITOR_STAGES
        ]
        assert labels == list(EDITOR_STAGES)
        assert "Approve the specification" in editor.deferred_var.get()
        assert str(editor.start_button.cget("state")) == "disabled"

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
        assert str(editor.start_button.cget("state")) == "normal"
        editor.window.destroy()
    finally:
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a Tk display")
def test_start_implementation_button_pins_approved_spec_and_queues_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    try:
        import tkinter as tk
    except ImportError:
        pytest.skip("Tk is not installed")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk cannot connect to a display")
    root.withdraw()

    import ai_loop.specification_gui as specification_gui
    import ai_loop_gui
    from ai_loop import db

    database = tmp_path / "loop.sqlite3"
    service = SpecificationService(database, tmp_path / "artifacts")
    backend = ai_loop_gui.LoopBackend.__new__(ai_loop_gui.LoopBackend)
    backend.settings = SimpleNamespace(
        db_path=database,
        runs_dir=tmp_path / "runs",
        redis_url="redis://unused/0",
        notify_email=None,
    )
    backend.ensure_provider_clis = lambda **_kwargs: None
    backend.ensure_redis_running = lambda: None
    backend.launch_processes = lambda _job_id, _models: {}

    queued: list[tuple[str, str, dict[str, object]]] = []
    groups: list[tuple[str, str]] = []
    monkeypatch.setattr(ai_loop_gui, "active_jobs", lambda _path: [])
    monkeypatch.setattr(ai_loop_gui, "timestamp_id", lambda _prefix: "JFORMALGUI")
    monkeypatch.setattr(
        ai_loop_gui,
        "create_pre_job_commit",
        lambda _repo, _job_id: {"created": False},
    )
    monkeypatch.setattr(ai_loop_gui, "redis_client", lambda _url: object())

    def publish_plan(_client, job_id, *, publication_key=None):
        groups.extend(
            [
                ("ai:claude:requests", f"claude-controllers:{job_id}"),
                ("ai:codex:tasks", f"codex-workers:{job_id}"),
            ]
        )
        queued.append(
            (
                "ai:claude:requests",
                "request",
                {"type": "PLAN", "job_id": job_id, "scope": "job"},
            )
        )
        assert publication_key == f"formal-job:{job_id}"
        return True

    monkeypatch.setattr(ai_loop_gui, "publish_controller_plan", publish_plan)
    monkeypatch.setattr(ai_loop_gui, "job_started_email", lambda *_args, **_kwargs: (False, "off"))
    monkeypatch.setattr(specification_gui.messagebox, "showinfo", lambda *_args, **_kwargs: None)

    models = ai_loop_gui.ModelDefaults(
        codex_model="",
        fable_model="",
        opus_model="",
        gemini_model="",
        controller_model="",
        codex_bin="codex",
        claude_bin="claude",
        gemini_bin="gemini",
        codex_bypass_sandbox=False,
    )

    def immediate_runner(work, done, **_kwargs):
        try:
            done(work(), None)
        except Exception as exc:  # pragma: no cover - diagnostic error path
            done(None, str(exc))

    def implementation_work(snapshot):
        return lambda: backend.create_job(
            repo=tmp_path,
            goal=snapshot.document.summary,
            test_cmd="pytest -q",
            constraints=[],
            acceptance=[],
            max_iterations=3,
            base_ref="HEAD",
            use_worktree=False,
            allow_parallel=False,
            worker="codex",
            controller="claude",
            granularity="normal",
            models=models,
            specification_id=snapshot.specification_id,
            specification_version=snapshot.version,
        )

    try:
        editor = open_specification_editor(
            root,
            service=service,
            repository_path=tmp_path,
            run_background=immediate_runner,
            implementation_work_factory=implementation_work,
        )
        editor.record = document_to_record(editable_document(tmp_path))
        editor._load_record_into_widgets()
        editor._refresh_assessment()
        editor.save_draft()
        editor.submit_for_review()
        editor.approve()

        approved = editor.snapshot
        assert approved is not None and approved.status == "approved"
        assert str(editor.start_button.cget("state")) == "normal"
        editor.start_button.invoke()

        with db.transaction(database) as conn:
            job = db.get_job(conn, "JFORMALGUI")
            assert job["specification_id"] == approved.specification_id
            assert job["specification_version"] == approved.version
            assert job["specification_content_hash"] == approved.canonical_content_hash
        assert service.load_job_manifest("JFORMALGUI") is not None
        assert groups == [
            ("ai:claude:requests", "claude-controllers:JFORMALGUI"),
            ("ai:codex:tasks", "codex-workers:JFORMALGUI"),
        ]
        assert queued == [
            (
                "ai:claude:requests",
                "request",
                {"type": "PLAN", "job_id": "JFORMALGUI", "scope": "job"},
            )
        ]
        assert str(editor.start_button.cget("state")) == "disabled"
        editor.window.destroy()
    finally:
        root.destroy()


def test_start_implementation_headless_enqueues_exactly_one_pinned_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ai_loop.specification_gui as specification_gui
    import ai_loop_gui
    from ai_loop import db

    database = tmp_path / "loop.sqlite3"
    service = SpecificationService(database, tmp_path / "artifacts")
    created = service.create(
        tmp_path,
        editable_document(tmp_path),
        creator="test-author",
        specification_id="SPEC-HEADLESS-START",
    )
    service.submit_for_review(created.specification_id)
    approved = service.approve(created.specification_id, approved_by="test-approver")

    backend = ai_loop_gui.LoopBackend.__new__(ai_loop_gui.LoopBackend)
    backend.settings = SimpleNamespace(
        db_path=database,
        runs_dir=tmp_path / "runs",
        redis_url="redis://unused/0",
        notify_email=None,
    )
    backend.ensure_provider_clis = lambda **_kwargs: None
    backend.ensure_redis_running = lambda: None
    backend.launch_processes = lambda _job_id, _models: {}

    plan_publications: list[dict[str, object]] = []
    monkeypatch.setattr(ai_loop_gui, "active_jobs", lambda _path: [])
    monkeypatch.setattr(ai_loop_gui, "timestamp_id", lambda _prefix: "JFORMALHEADLESS")
    monkeypatch.setattr(
        ai_loop_gui,
        "create_pre_job_commit",
        lambda _repo, _job_id: {"created": False},
    )
    monkeypatch.setattr(ai_loop_gui, "redis_client", lambda _url: object())

    def publish_plan(_client, job_id, *, publication_key=None):
        plan_publications.append(
            {
                "type": "PLAN",
                "job_id": job_id,
                "scope": "job",
                "publication_key": publication_key,
            }
        )
        return True

    monkeypatch.setattr(ai_loop_gui, "publish_controller_plan", publish_plan)
    monkeypatch.setattr(
        ai_loop_gui,
        "job_started_email",
        lambda *_args, **_kwargs: (False, "off"),
    )

    formal_creation_calls: list[dict[str, object]] = []
    original_create_formal_job = SpecificationService.create_formal_job

    def track_create_formal_job(self, **job):
        formal_creation_calls.append(dict(job))
        return original_create_formal_job(self, **job)

    monkeypatch.setattr(
        SpecificationService,
        "create_formal_job",
        track_create_formal_job,
    )

    models = ai_loop_gui.ModelDefaults(
        codex_model="",
        fable_model="",
        opus_model="",
        gemini_model="",
        controller_model="",
        codex_bin="codex",
        claude_bin="claude",
        gemini_bin="gemini",
        codex_bypass_sandbox=False,
    )
    value = lambda result: SimpleNamespace(get=lambda: result)
    gui = SimpleNamespace(
        backend=backend,
        worker_var=value("codex"),
        controller_var=value("claude"),
        test_cmd_var=value("pytest -q"),
        max_iterations_var=value("3"),
        base_ref_var=value("HEAD"),
        no_worktree_var=value(True),
        allow_parallel_var=value(False),
        granularity_var=value("normal"),
        _exclusive_conflict=lambda _kind: None,
        current_models=lambda: models,
    )

    pending: list[tuple[object, object]] = []
    info_messages: list[str] = []
    error_messages: list[str] = []
    started_jobs: list[str] = []
    monkeypatch.setattr(
        specification_gui,
        "messagebox",
        SimpleNamespace(
            showinfo=lambda _title, message, **_kwargs: info_messages.append(message),
            showerror=lambda _title, message, **_kwargs: error_messages.append(message),
        ),
    )

    editor = specification_gui.SpecificationEditor.__new__(
        specification_gui.SpecificationEditor
    )
    editor.snapshot = approved
    editor._implementation_work_factory = lambda snapshot: (
        ai_loop_gui.AiLoopGui._formal_implementation_work(gui, snapshot)
    )
    editor._implementation_job_id = None
    editor._implementation_start_in_flight = False
    editor._has_unsaved_edits = lambda: False
    editor._update_actions = lambda: None
    editor._background = (
        lambda work, done, **_kwargs: pending.append((work, done))
    )
    editor._show_snapshot_status = lambda: None
    editor._on_implementation_started = started_jobs.append
    editor.status_var = SimpleNamespace(set=lambda _value: None)
    editor.deferred_var = SimpleNamespace(set=lambda _value: None)
    editor.window = object()

    editor.start_implementation()
    editor.start_implementation()

    assert editor._implementation_start_in_flight
    assert len(pending) == 1
    assert "already being created" in info_messages[0]

    work, done = pending.pop()
    job_id = work()
    done(job_id, None)
    editor.start_implementation()

    assert error_messages == []
    assert started_jobs == ["JFORMALHEADLESS"]
    assert editor._implementation_job_id == "JFORMALHEADLESS"
    assert not editor._implementation_start_in_flight
    assert pending == []
    assert "already started as JFORMALHEADLESS" in info_messages[-1]
    assert len(formal_creation_calls) == 1
    assert formal_creation_calls[0]["specification_id"] == approved.specification_id
    assert formal_creation_calls[0]["specification_version"] == approved.version

    with db.transaction(database) as conn:
        jobs = conn.execute("SELECT * FROM jobs").fetchall()
        assert len(jobs) == 1
        job = dict(jobs[0])
    assert job["id"] == "JFORMALHEADLESS"
    assert job["specification_id"] == approved.specification_id
    assert job["specification_version"] == approved.version
    assert job["specification_content_hash"] == approved.canonical_content_hash
    assert service.load_job_manifest(job["id"]) is not None
    assert plan_publications == [
        {
            "type": "PLAN",
            "job_id": "JFORMALHEADLESS",
            "scope": "job",
            "publication_key": "formal-job:JFORMALHEADLESS",
        }
    ]
