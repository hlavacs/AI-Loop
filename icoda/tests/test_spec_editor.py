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


def test_records_get_consecutive_ids_and_defaults() -> None:
    editor, _ = editor_with()
    page = editor.records["requirements"]
    first = page.add()
    assert first["id"] == "R-1" and first["priority"] == "must"
    page.form.vars["title"].set("Fast start")
    page.form.vars["use_cases"].set("UC-1, UC-2")
    page.form.texts["description"].insert("1.0", "Starts within a second.")
    second = page.add()
    assert second["id"] == "R-2" and page.current == 1
    records = page.values()
    assert records[0] == {"id": "R-1", "title": "Fast start", "priority": "must", "use_cases": ["UC-1", "UC-2"],
                          "description": "Starts within a second."}
    page.select(0)
    assert page.form.vars["title"].get() == "Fast start"
    page.remove()
    assert [r["id"] for r in page.values()] == ["R-2"] and page.current == 0
    assert page.add()["id"] == "R-3"


def test_saving_an_invalid_specification_reports_the_problems() -> None:
    editor, saved = editor_with()
    editor.overview.vars["title"].set("")
    editor.records["verification"].add()
    editor.records["verification"].form.vars["requirement"].set("R-9")
    assert not editor.save() and saved == []
    problems = editor.problems.get()
    assert "title" in problems and "R-9" in problems
    assert editor.changed()


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
