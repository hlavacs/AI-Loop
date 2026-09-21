"""Compare the authoring controls with ICODA and exercise the complete entry path."""
from __future__ import annotations

import ast
import copy
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from ai_loop import specification_authoring as authoring
from ai_loop.specification_gui import SpecificationEditor
from ai_loop.specification_gui_support import specification_to_savefile_bytes
from ai_loop.specifications import SpecificationDocument, SpecificationService


@pytest.fixture
def icoda_reference(monkeypatch):
    """Execute ICODA's actual controls without requiring its backend dependencies."""
    import tkinter as tk
    from tkinter import ttk

    root = Path(__file__).resolve().parents[2] / "icoda"
    names = {
        "FieldSpec", "FieldSet", "RecordListPage", "_lines", "_headline",
        "ENTRY_WIDTH", "SECTION_TITLES", "OVERVIEW_FIELDS", "SCOPE_FIELDS",
        "RECORD_FIELDS", "RECORD_DEFAULTS", "PROFILE_FIELDS", "HIDDEN_PROFILE_KEYS", "SAVE_HINT",
    }
    source = ast.parse((root / "icoda_gui/spec_editor.py").read_text())
    selected = [node for node in source.body if (
        isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names
        or isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)
        or isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in names
    )]
    core = ast.parse((root / "icoda_core/specification.py").read_text())
    next_id = next(node for node in core.body if isinstance(node, ast.FunctionDef) and node.name == "next_id")
    module = ModuleType("_icoda_authoring_reference")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    module.__dict__.update(tk=tk, ttk=ttk, Any=Any, Mapping=Mapping, Sequence=Sequence,
                           dataclass=dataclass, re=re, copy=copy, Specification=dict,
                           RECORD_SECTIONS={"use_cases": "UC", "requirements": "R", "decisions": "D"},
                           tooltip=SimpleNamespace(attach=lambda *args: None))
    exec(compile(ast.Module(body=[next_id], type_ignores=[]), "icoda-next-id", "exec"), module.__dict__)
    module.specification = SimpleNamespace(next_id=module.next_id)
    exec(compile(ast.Module(body=selected, type_ignores=[]), "icoda-authoring-reference", "exec"), module.__dict__)
    return module


def test_all_six_tabs_have_exact_icoda_fields_controls_order_and_hints(icoda_reference):
    for name in ("OVERVIEW_FIELDS", "SCOPE_FIELDS", "PROFILE_FIELDS"):
        assert [asdict(item) for item in getattr(authoring, name)] == [asdict(item) for item in getattr(icoda_reference, name)]
    for section in icoda_reference.RECORD_FIELDS:
        assert [asdict(item) for item in authoring.RECORD_FIELDS[section]] == [asdict(item) for item in icoda_reference.RECORD_FIELDS[section]]
    assert authoring.HIDDEN_PROFILE_KEYS == icoda_reference.HIDDEN_PROFILE_KEYS
    assert authoring.RECORD_DEFAULTS == icoda_reference.RECORD_DEFAULTS
    for section in authoring.RECORD_FIELDS:
        prefix = {"use_cases": "UC", "requirements": "R", "decisions": "D"}[section]
        rows = [{"id": f"{prefix}-1"}, {"id": f"{prefix}-7"}]
        assert authoring.next_record_id(rows, section) == icoda_reference.next_id({section: rows}, section)


@pytest.fixture
def tk_root():
    if not os.environ.get("DISPLAY"):
        pytest.skip("requires a Tk display")
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def editor(tk_root, tmp_path, monkeypatch):
    import ai_loop.specification_gui as gui
    # Fail instead of hanging if any unexpected modal error appears.
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, message, **kw: pytest.fail(f"{title}: {message}"))
    value = SpecificationEditor(
        tk_root, service=SpecificationService(tmp_path / "loop.sqlite3", tmp_path / "artifacts"),
        repository_path=tmp_path, run_background=lambda work, done, **kw: done(work(), None),
    )
    yield value
    if value.window.winfo_exists():
        value.window.destroy()


@pytest.mark.parametrize("section", ["use_cases", "requirements", "decisions"])
def test_record_add_edit_new_remove_and_clear_match_icoda(tk_root, icoda_reference, section):
    from tkinter import ttk
    pages = [module.RecordListPage(ttk.Frame(tk_root), section, module.RECORD_FIELDS[section])
             for module in (authoring, icoda_reference)]
    for page in pages:
        assert page.current is None and page.form.vars["title"].get() == ""
        assert page.add() is None
        page.form.vars["title"].set("First activity")
        if section == "requirements":
            page.form.vars["use_cases"].set("UC-1; UC-3, UC-4")
        first = page.add()
        assert first is not None and page.current is None
        assert page.form.vars["title"].get() == ""
        page.form.vars["title"].set("Second activity")
        page.add()
        page.select(0)
        page.form.vars["title"].set("Edited first activity")
        page.select(1)  # Selection commits edits in the previous row.
        page.form.vars["title"].set("Edited second activity")
        assert page.add() is None  # Add with a selection means commit + New.
        assert len(page.values()) == 2 and page.current is None
        page.select(0)
        page.form.texts[page.fields[-1].key].insert("1.0", "Temporary details")
        page.new()
        page.select(0)
        page.form.texts[page.fields[-1].key].delete("1.0", "end")
        page.values()  # Save/Validate reads commit edits without a separate Apply.
        assert page.fields[-1].key not in page.values()[0]
        page.select(1)
        page.remove()
        assert page.current is None and len(page.values()) == 1
    assert pages[0].values() == pages[1].values()
    assert pages[0].header.get() == pages[1].header.get()


def test_all_tabs_round_trip_through_save_and_reread(editor):
    editor.overview.vars["title"].set("Score clamp")
    editor.overview.texts["summary"].insert("1.0", "Clamp a score in C++.")
    for name, text in {"goals": "Clamp integer scores", "out_of_scope": "Graphics",
                       "not_allowed": "Global state", "done_when": "Boundary tests pass"}.items():
        editor.scope.texts[name].insert("1.0", text)
    for section, title in {"use_cases": "Clamp a score", "requirements": "Clamp within the bounds",
                           "decisions": "Use integer arithmetic"}.items():
        page = editor.records[section]
        page.form.vars["title"].set(title)
        if section == "requirements":
            page.form.vars["use_cases"].set("UC-1")
        page.buttons["Add"].invoke()
    editor.profile.vars["platforms"]["Windows"].set(False)
    editor.profile.vars["max_methods"].set("12")
    assert editor.validate() == []
    assert editor.problems.get() == "valid"
    page = editor.records["requirements"]
    page.select(0)
    page.form.texts["description"].insert("1.0", "Keep in-range scores unchanged.")
    editor.save_button.invoke()
    assert editor.problems.get() == "saved"
    assert page.current == 0  # Saving keeps the active editor and selection.
    assert not editor.changed()
    saved = editor.snapshot.document
    assert saved.requirements[0].description == "Keep in-range scores unchanged."
    assert saved.code_profile["platforms"] == ["macOS", "Linux"]
    assert saved.code_profile["max_methods"] == 12
    assert "build" not in editor.profile.vars and "build" in saved.code_profile
    assert not editor.assessment.approval_ready  # Entry is complete; execution still needs proof.
    editor.reread_button.invoke()
    assert editor._current_document() == saved
    assert editor.problems.get() == "reread"


def test_validate_routes_to_tab_without_saving(editor):
    assert editor.validate()[0] == "Overview: title must not be empty"
    assert editor.notebook.select() == str(editor.tabs["Overview"])
    editor.title_var.set("Score clamp")
    page = editor.records["requirements"]
    page.form.vars["title"].set("Clamp the score")
    page.form.vars["use_cases"].set("UC-9")
    page.add()
    assert any("UC-9" in problem for problem in editor.validate())
    assert editor.notebook.select() == str(editor.tabs["Requirements"])
    page.select(0)
    page.form.vars["use_cases"].set("")
    editor.profile.vars["standard"].set("")
    assert any("standard" in problem for problem in editor.validate())
    assert editor.notebook.select() == str(editor.tabs["Code profile"])
    assert editor.snapshot is None


def test_save_during_review_keeps_entry_workflow_and_requires_new_approval(editor):
    from test_specification_alignment import executable_record
    editor.record = executable_record()
    editor._load_record_into_widgets()
    editor.save_draft()
    editor.submit_for_review()
    original = editor.snapshot
    assert original.status == "review"
    assert str(editor.save_button.cget("state")) == "normal"
    editor.save_button.invoke()
    assert editor.snapshot == original  # Saving unchanged text does not cancel review.
    page = editor.records["requirements"]
    page.select(0)
    page.form.vars["title"].set("Clamp a revised score")
    editor.save_button.invoke()
    assert editor.snapshot.status == "draft"
    assert editor.snapshot.version == original.version + 1
    assert editor.snapshot.document.requirements[0].title == "Clamp a revised score"
    assert str(editor.approve_button.cget("state")) == "disabled"
    assert str(editor.start_button.cget("state")) == "disabled"
    assert editor.service.load(original.specification_id, original.version).document == original.document
    assert page.current == 0 and not editor.changed()


def test_external_reread_protects_unadded_forms_and_removes_stale_rows(editor, tmp_path, monkeypatch):
    import ai_loop.specification_gui as gui
    path = tmp_path / "specification.json"
    record = SpecificationDocument.empty(title="Externally saved").to_dict()
    path.write_bytes(specification_to_savefile_bytes(record))
    editor._source_file = path
    page = editor.records["decisions"]
    page.form.vars["title"].set("Not added yet")
    assert editor.changed()
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **kw: False)
    editor.reread_specification()
    assert page.form.vars["title"].get() == "Not added yet"
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **kw: True)
    editor.reread_specification()
    assert editor.title_var.get() == "Externally saved"
    assert page.current is None and page.form.vars["title"].get() == ""
    assert not editor.changed()
    editor.title_var.set("Newer project revision")
    editor.save_button.invoke()
    editor.reread_button.invoke()
    assert editor.title_var.get() == "Newer project revision"
    assert editor.snapshot is not None
    assert path.read_bytes() == specification_to_savefile_bytes(record)


def test_inline_edit_preserves_legacy_data_and_hidden_profile(editor):
    from test_specification_alignment import executable_record
    record = executable_record()
    record["requirements"][0]["acceptance_criteria"] = ["Run the boundary scenario"]
    record["requirements"][0]["source"] = "Original user brief"
    editor.record = record
    editor._load_record_into_widgets()
    page = editor.records["requirements"]
    page.select(0)
    page.form.vars["title"].set("Clamp a revised score")
    result = editor._collect_record()
    for key in ("acceptance_criteria", "source"):
        assert result["requirements"][0][key] == record["requirements"][0][key]
    assert result["verification"] == record["verification"]
    assert result["code_profile"]["build"] == record["code_profile"]["build"]


def test_close_and_save_shortcut_behave_like_icoda(editor, monkeypatch):
    import ai_loop.specification_gui as gui
    modifier = "Command" if sys.platform == "darwin" else "Control"
    assert editor.window.bind(f"<{modifier}-s>")
    assert editor.window.bind(f"<{modifier}-w>")
    for page in editor.records.values():
        assert page.form.widgets["title"].bind("<Return>")
    editor.title_var.set("Unsaved project")
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **kw: True)
    editor.close()
    assert editor.snapshot is not None and editor.snapshot.document.title == "Unsaved project"
    assert not editor.window.winfo_exists()


def test_typing_during_background_save_stays_unsaved_and_keeps_editor_open(editor):
    pending = []
    editor._run_background = lambda work, done, **kw: pending.append((work, done))
    editor.title_var.set("Submitted title")
    editor.save_draft(on_saved=editor._finish_close)
    editor.title_var.set("Newer title still being edited")
    work, done = pending.pop(0)
    done(work(), None)
    assert editor.window.winfo_exists()
    assert editor.snapshot.document.title == "Submitted title"
    assert editor.title_var.get() == "Newer title still being edited"
    assert editor.changed()
    work, done = pending.pop(0)  # Finish the specification-selector refresh.
    done(work(), None)
