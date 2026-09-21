"""ICODA authoring parity and AI-Loop's retained execution contract."""

from __future__ import annotations

import ast
import copy
import json
import os
from pathlib import Path

import pytest

from ai_loop.specification_compiler import compile_verification_manifest
from ai_loop.specification_fields import (
    CODE_PROFILE_SCHEMA,
    default_code_profile,
    editor_record,
)
from ai_loop.specification_gui_support import (
    compute_field_feedback,
    savefile_to_record,
    specification_to_savefile_bytes,
)
from ai_loop.specification_workflow import (
    analyze_specification_change,
    derive_formal_job_inputs,
)
from ai_loop.specifications import (
    SpecificationDocument,
    SpecificationService,
    SpecificationValidationError,
    approval_issues,
    canonical_json,
    sha256_text,
)
from test_specifications import complete_document_dict


def icoda_record() -> dict:
    return {
        "schema_version": 2,
        "title": "Score clamp",
        "summary": "Clamp an integer score in a C++ library and demonstrate it.",
        "goals": ["Provide a reusable clamp function"],
        "out_of_scope": ["A graphical interface"],
        "not_allowed": ["Global mutable state"],
        "done_when": ["Boundary tests pass and the example prints the clamped score"],
        "use_cases": [
            {
                "id": "UC-1",
                "title": "Clamp a score",
                "description": "Pass a score and bounds.",
            }
        ],
        "requirements": [
            {
                "id": "R-1",
                "title": "Clamp to the supplied bounds",
                "priority": "must",
                "description": "Keep in-range values unchanged.",
                "use_cases": ["UC-1"],
            }
        ],
        "decisions": [
            {
                "id": "D-1",
                "title": "Use integer scores",
                "rationale": "Exact comparison",
            }
        ],
        "code_profile": default_code_profile(),
    }


def approved(service: SpecificationService, record: dict, *, initial: bool = True):
    document = SpecificationDocument.from_dict(record)
    if initial:
        service.create(
            service.db_path.parent, document, creator="test", specification_id="SPEC1"
        )
    else:
        service.revise(
            "SPEC1",
            document,
            creator="test",
            change_summary="Revise the authoring contract",
        )
    service.submit_for_review("SPEC1")
    return service.approve("SPEC1", approved_by="test")


def executable_record() -> dict:
    record = savefile_to_record(json.dumps(icoda_record()))
    verification = complete_document_dict()["verification"][0]
    verification["requirement_ids"] = ["R-1"]
    record["verification"] = [verification]
    return record


def test_defaults_and_profile_schema_match_icoda_without_runtime_dependency() -> None:
    core = Path(__file__).resolve().parents[2] / "icoda" / "icoda_core"
    schema = json.loads((core / "specification.schema.json").read_text())
    profile = schema["properties"]["code_profile"]
    profile["properties"]["style_notes"] = schema["$defs"]["lines"]
    assert CODE_PROFILE_SCHEMA == profile
    # Read the literal defaults without importing ICODA or its dependencies.
    tree = ast.parse((core / "specification.py").read_text())
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "default_code_profile"
    )
    for node in ast.walk(function):
        if isinstance(node, ast.Return):
            expected = ast.literal_eval(node.value)
            assert default_code_profile(expected["language"]) == expected
    isolated = default_code_profile()
    isolated["style_notes"].clear()
    assert default_code_profile()["style_notes"]


def test_icoda_import_round_trip_preserves_every_authoring_field() -> None:
    source = icoda_record()
    record = savefile_to_record(json.dumps(source))
    for key, value in source.items():
        if key == "schema_version":
            assert record[key] == "1.1"
        elif key in {"requirements", "use_cases", "decisions"}:
            for original, imported in zip(value, record[key]):
                assert original.items() <= imported.items()
        else:
            assert record[key] == value
    document = SpecificationDocument.from_dict(record)
    assert SpecificationDocument.from_json(document.pretty_json()) == document
    assert savefile_to_record(specification_to_savefile_bytes(record)) == record


def test_old_snapshots_and_savefiles_keep_their_exact_canonical_hash() -> None:
    record = complete_document_dict()
    document = SpecificationDocument.from_dict(record)
    assert document.to_dict() == record
    assert document.content_hash() == sha256_text(canonical_json(record))
    assert savefile_to_record(specification_to_savefile_bytes(record)) == record
    upgraded = editor_record(record)
    assert record == document.to_dict()
    assert upgraded["goals"] == record["objectives"]
    assert upgraded["requirements"][0]["use_cases"] == ["UC1"]
    assert (
        upgraded["requirements"][0]["description"]
        == record["requirements"][0]["statement"]
    )
    assert upgraded["code_profile"]["language"] == ""  # No silently imposed language.
    upgraded["code_profile"] = default_code_profile("Python")
    assert SpecificationDocument.from_dict(upgraded).schema_version == "1.1"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("language", "Java"),
        ("modules", "yes"),
        ("max_methods", True),
        ("max_function_lines", 0),
        ("hard_max_function_lines", 1.5),
        ("platforms", ["FreeBSD"]),
        ("style_notes", "one rule"),
        ("unknown", "value"),
    ],
)
def test_invalid_profile_values_identify_their_field(key, value) -> None:
    record = SpecificationDocument.empty().to_dict()
    record["code_profile"][key] = value
    with pytest.raises(SpecificationValidationError, match=f"code_profile.{key}"):
        SpecificationDocument.from_dict(record)
    feedback = compute_field_feedback(record)
    assert feedback["code_profile"].health == "needs_attention"


def test_unknown_use_case_and_duplicate_decision_ids_are_rejected() -> None:
    record = savefile_to_record(json.dumps(icoda_record()))
    record["requirements"][0]["use_cases"] = ["UC-99"]
    with pytest.raises(SpecificationValidationError, match="unknown use case"):
        SpecificationDocument.from_dict(record)
    record["requirements"][0]["use_cases"] = ["UC-1"]
    record["decisions"].append(copy.deepcopy(record["decisions"][0]))
    with pytest.raises(SpecificationValidationError, match="duplicate identifier"):
        SpecificationDocument.from_dict(record)


def test_primary_fields_reach_jobs_and_compiled_work_items(tmp_path: Path) -> None:
    record = executable_record()
    profile = record["code_profile"]
    profile["test_runner"] = "ctest --test-dir build --output-on-failure"
    service = SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts")
    snapshot = approved(service, record)
    assert not approval_issues(snapshot.document)
    inputs = derive_formal_job_inputs(service.load("SPEC1"))
    assert record["summary"] in inputs.goal
    assert record["goals"][0] in inputs.goal
    assert f"[Out of scope] {record['out_of_scope'][0]}" in inputs.constraints
    assert f"[Not allowed] {record['not_allowed'][0]}" in inputs.constraints
    assert f"[Done when] {record['done_when'][0]}" in inputs.acceptance
    assert "[Approved decision: D-1] Use integer scores" in inputs.constraints
    for key in profile:
        assert any(
            item.startswith(f"[Code profile: {key.replace('_', ' ')}]")
            for item in inputs.constraints
        )
    manifest = compile_verification_manifest(snapshot, "auto")
    assert manifest.work_items[0]["linked_use_case_ids"] == ["UC-1"]
    assert (
        manifest.work_items[0]["statement"]
        == "Clamp to the supplied bounds\nKeep in-range values unchanged."
    )
    assert manifest.verification[0]["command"] == profile["test_runner"]
    assert manifest.verification[0]["command_source"] == "specification"
    assert any(
        "not covered by verification" in issue.message
        for issue in approval_issues(
            SpecificationDocument.from_dict({**record, "verification": []})
        )
    )


@pytest.mark.parametrize(
    "field",
    ["goals", "out_of_scope", "not_allowed", "done_when", "code_profile", "use_cases"],
)
def test_adopting_new_authoring_fields_requires_revalidation(
    tmp_path: Path, field: str
) -> None:
    record = executable_record()
    service = SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts")
    before = approved(service, record)
    if field == "code_profile":
        record[field]["standard"] = "20"
    elif field == "use_cases":
        record[field][0]["description"] = "Clamp each score in a batch."
    else:
        record[field].append("A revised contract condition")
    after = approved(service, record, initial=False)
    impact = analyze_specification_change(before, after)["impact"]
    assert impact["affected_requirement_ids"] == ["R-1"]
    assert impact["affected_verification_ids"] == ["VT1"]


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a Tk display")
def test_profile_editor_switch_save_load_and_requirement_links(tmp_path: Path) -> None:
    import tkinter as tk
    from ai_loop.specification_gui import (
        REQUIREMENT_FIELDS,
        SpecificationEditor,
        _RecordDialog,
    )

    root = tk.Tk()
    root.withdraw()

    def immediate(work, done, **_kwargs):
        done(work(), None)

    try:
        editor = SpecificationEditor(
            root,
            service=SpecificationService(
                tmp_path / "loop.sqlite3", tmp_path / "artifacts"
            ),
            repository_path=tmp_path,
            run_background=immediate,
        )
        editor.record = executable_record()
        editor._load_record_into_widgets()
        assert editor._collect_record() == editor.record
        editor.profile_vars["language"].set("Python")
        # Like ICODA, selecting a language preserves the other entered settings.
        expected_profile = {**default_code_profile(), "language": "Python"}
        assert editor._collect_record()["code_profile"] == expected_profile
        editor.profile_vars["max_methods"].set("22")
        editor.profile_vars["language"].set("C++")
        assert editor._collect_record()["code_profile"]["max_methods"] == 22
        editor.profile_vars["max_methods"].set("invalid")
        editor._refresh_assessment()
        assert any(
            issue.path == "code_profile.max_methods"
            for issue in editor.assessment.issues_for_stage("Code profile")
        )
        dialog = _RecordDialog(
            editor.window,
            "Requirement",
            REQUIREMENT_FIELDS,
            editor.record["requirements"][0],
            field_path_prefix="requirements",
        )
        tags = dialog._controls["use_cases"][1]
        tags.delete(0, "end")
        tags.insert(0, "UC-1, UC-3")
        values, errors = dialog._collect_values()
        assert not errors
        assert values["use_cases"] == ["UC-1", "UC-3"]
        dialog.window.destroy()
        legacy = SpecificationDocument.from_dict(complete_document_dict())
        editor.service.create(
            tmp_path, legacy, creator="test", specification_id="LEGACY"
        )
        editor.snapshot = editor.service.submit_for_review("LEGACY")
        editor.record = legacy.to_dict()
        editor._load_record_into_widgets()
        editor._refresh_assessment()
        assert not editor._has_unsaved_edits()
        assert editor.assessment.approval_ready
        editor.snapshot = editor.service.approve("LEGACY", approved_by="test")
        assert not editor._has_unsaved_edits()
        assert editor.snapshot.document.to_dict() == complete_document_dict()
        editor.close()
    finally:
        root.destroy()
