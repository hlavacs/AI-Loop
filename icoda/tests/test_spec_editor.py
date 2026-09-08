"""The specification editor against the Tk stub: every page round-trips, records get ids, saving validates."""

from __future__ import annotations

import tkinter as tk
from typing import Any

from icoda_core import specification
from icoda_gui import spec_editor


def editor_with(spec: dict[str, Any] | None = None) -> tuple[spec_editor.SpecificationEditor, list[dict[str, Any]]]:
    saved: list[dict[str, Any]] = []
    editor = spec_editor.SpecificationEditor(tk.Tk(), spec or specification.default_specification("Demo"),
                                             saved.append)
    return editor, saved


def full_specification() -> dict[str, Any]:
    spec = specification.default_specification("Full")
    spec["summary"] = "A project with\ntwo lines of summary."
    spec["goals"] = ["goal one", "goal two"]
    spec["out_of_scope"] = ["multiplayer"]
    spec["not_allowed"] = ["Boost", "raw new"]
    spec["done_when"] = ["all tests pass"]
    spec["use_cases"] = [{"id": "UC-1", "title": "Log in", "description": "Enter the system."}]
    spec["requirements"] = [{"id": "R-1", "title": "Password check", "priority": "must", "use_cases": ["UC-1"],
                             "description": "Reject wrong passwords."}]
    spec["decisions"] = [{"id": "D-1", "title": "Use argon2", "rationale": "Memory hard."}]
    spec["code_profile"]["platforms"] = ["Linux", "Windows"]
    spec["code_profile"]["modules"] = False
    spec["code_profile"]["max_methods"] = 12  # not shown in the editor, but kept
    return spec


def test_default_specification_round_trips_unchanged() -> None:
    editor, _ = editor_with()
    assert editor.to_specification() == specification.default_specification("Demo")
    assert not editor.changed()
    assert editor.validate() == []
    assert list(editor.pages) == ["overview", "scope", "use_cases", "requirements", "decisions", "code_profile"]


def test_every_section_round_trips() -> None:
    spec = full_specification()
    editor, saved = editor_with(spec)
    assert editor.to_specification() == spec
    assert editor.save() and saved == [spec]
    assert editor.problems.get() == "saved"


def test_fill_in_then_add_creates_records_with_ids_and_defaults() -> None:
    editor, _ = editor_with()
    page = editor.records["requirements"]
    assert page.add() is None and "requirement first" in page.header.get()  # an empty form adds nothing
    page.form.vars["title"].set("Fast start")
    page.form.vars["use_cases"].set("UC-1, UC-2")
    page.form.texts["description"].insert("1.0", "Starts within a second.")
    first = page.add()
    assert first is not None and first["id"] == "R-1" and first["priority"] == "must"
    assert page.current is None and page.form.vars["title"].get() == ""  # the form is ready for the next entry
    page.form.vars["title"].set("Second")
    page.form.vars["priority"].set("could")
    second = page.add()
    assert second is not None and second["id"] == "R-2" and second["priority"] == "could"
    assert page.values()[0] == {"id": "R-1", "title": "Fast start", "priority": "must",
                                "use_cases": ["UC-1", "UC-2"], "description": "Starts within a second."}


def test_selecting_edits_a_record_and_new_returns_to_a_new_entry() -> None:
    editor, _ = editor_with(full_specification())
    page = editor.records["use_cases"]
    assert page.current is None and page.form.vars["title"].get() == ""
    page.select(0)
    assert page.form.vars["title"].get() == "Log in" and "UC-1" in page.header.get()
    page.form.vars["title"].set("Log in twice")
    assert page.add() is None and page.current is None  # Add on a selected record keeps the edit, starts anew
    assert page.values()[0]["title"] == "Log in twice"
    page.form.vars["title"].set("Log out")
    assert page.add() is not None and [r["id"] for r in page.values()] == ["UC-1", "UC-2"]
    page.select(1)
    page.remove()
    assert [r["id"] for r in page.values()] == ["UC-1"] and page.current is None
    page.form.vars["title"].set("Again")
    assert page.add()["id"] == "UC-2"  # type: ignore[index]


def test_saving_an_invalid_specification_reports_the_problems() -> None:
    editor, saved = editor_with()
    editor.overview.vars["title"].set("")
    page = editor.records["requirements"]
    page.form.vars["title"].set("Needs UC-9")
    page.form.vars["use_cases"].set("UC-9")
    assert page.add() is not None
    assert not editor.save() and saved == []
    problems = editor.problems.get()
    assert problems.startswith("Overview: title must not be empty") and "UC-9" in problems
    assert editor.changed() and editor.current_page == "overview"
    spec = specification.default_specification("Demo")
    spec["use_cases"] = [{"id": "UC-1"}]
    editor.load(spec)
    assert not editor.save() and editor.problems.get() == "Use cases UC-1: title is missing"
    assert editor.current_page == "use_cases"


def test_profile_fields_convert_numbers_and_lists() -> None:
    editor, _ = editor_with()
    editor.profile.vars["max_function_lines"].set("40")
    editor.profile.vars["standard"].set("")
    editor.profile.vars["platforms"]["Windows"].set(False)
    editor.profile.texts["style_notes"].delete("1.0", "end")
    editor.profile.texts["style_notes"].insert("1.0", "one\n\n  two  \n")
    profile = editor.to_specification()["code_profile"]
    assert profile["max_function_lines"] == 40 and profile["platforms"] == ["macOS", "Linux"]
    assert profile["style_notes"] == ["one", "two"] and profile["max_methods"] == 15
    assert editor.validate() == ["Code profile: standard is missing"] and editor.current_page == "code_profile"


def test_version_1_specification_opens_in_the_editor() -> None:
    old = {"schema_version": 1, "title": "Old", "summary": "", "objectives": ["ship"], "in_scope": [],
           "out_of_scope": [], "stakeholders": [], "assumptions": [], "constraints": [], "dependencies": [],
           "use_cases": [{"id": "UC-1", "title": "Start"}], "requirements": [], "decisions": [], "risks": [],
           "verification": [], "open_questions": [], "code_profile": specification.default_code_profile()}
    editor, saved = editor_with(old)
    assert editor.to_specification()["goals"] == ["ship"] and editor.save()
    assert saved[0]["not_allowed"] == [] and saved[0]["done_when"] == []
    assert saved[0]["schema_version"] == 2 and saved[0]["use_cases"] == [{"id": "UC-1", "title": "Start"}]


def test_scope_page_holds_the_four_lists() -> None:
    editor, _ = editor_with()
    editor.scope.texts["not_allowed"].insert("1.0", "Boost\nexceptions\n")
    editor.scope.texts["done_when"].insert("1.0", "every use case runs")
    spec = editor.to_specification()
    assert spec["not_allowed"] == ["Boost", "exceptions"] and spec["done_when"] == ["every use case runs"]
    assert editor.validate() == [] and spec_editor._page_of("Done when: x") == "scope"
