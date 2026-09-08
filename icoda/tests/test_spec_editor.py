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
    for section in specification.LIST_SECTIONS:
        spec[section] = [f"{section} one", f"{section} two"]
    spec["use_cases"] = [{"id": "UC-1", "title": "Log in", "actor": "user", "description": "Enter the system."}]
    spec["requirements"] = [{"id": "R-1", "title": "Password check", "priority": "must", "category": "functional",
                             "use_cases": ["UC-1"], "description": "Reject wrong passwords."}]
    spec["decisions"] = [{"id": "D-1", "title": "Use argon2", "rationale": "Memory hard."}]
    spec["risks"] = [{"id": "RK-1", "title": "Brute force", "severity": "high", "mitigation": "Rate limiting."}]
    spec["verification"] = [{"id": "V-1", "requirement": "R-1", "method": "unit test", "description": "Wrong pw."}]
    spec["code_profile"]["platforms"] = ["Linux", "Windows"]
    spec["code_profile"]["modules"] = False
    return spec


def test_default_specification_round_trips_unchanged() -> None:
    editor, _ = editor_with()
    assert editor.to_specification() == specification.default_specification("Demo")
    assert not editor.changed()
    assert editor.validate() == []


def test_every_section_round_trips() -> None:
    spec = full_specification()
    editor, saved = editor_with(spec)
    assert editor.to_specification() == spec
    assert editor.save() and saved == [spec]
    assert editor.problems.get() == "saved"


def test_fill_in_then_add_creates_records_with_ids_and_defaults() -> None:
    editor, _ = editor_with()
    page = editor.records["requirements"]
    assert page.add() is None and "title first" in page.header.get()  # an empty form adds nothing
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
    page = editor.records["verification"]
    page.form.vars["requirement"].set("R-9")
    assert page.add() is not None
    assert not editor.save() and saved == []
    problems = editor.problems.get()
    assert problems.startswith("Overview: title must not be empty") and "R-9" in problems
    assert editor.changed() and editor.current_page == "overview"
    spec = specification.default_specification("Demo")
    spec["use_cases"] = [{"id": "UC-1"}]
    editor.load(spec)
    assert not editor.save() and editor.problems.get() == "Use cases UC-1: title is missing"
    assert editor.current_page == "use_cases"


def test_profile_fields_convert_numbers_and_lists() -> None:
    editor, _ = editor_with()
    editor.profile.vars["max_function_lines"].set("40")
    editor.profile.vars["max_methods"].set("many")
    editor.profile.vars["platforms"]["Windows"].set(False)
    editor.profile.texts["style_notes"].delete("1.0", "end")
    editor.profile.texts["style_notes"].insert("1.0", "one\n\n  two  \n")
    profile = editor.to_specification()["code_profile"]
    assert profile["max_function_lines"] == 40 and profile["platforms"] == ["macOS", "Linux"]
    assert profile["style_notes"] == ["one", "two"]
    assert any("max_methods" in p for p in editor.validate())


def test_lines_pages_drop_blank_lines() -> None:
    editor, _ = editor_with()
    editor.lines["objectives"].load(["", "  first ", "second", ""])
    assert editor.to_specification()["objectives"] == ["first", "second"]
