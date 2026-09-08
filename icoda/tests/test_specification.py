"""Specification defaults, validation with readable problems, ids, round trip, upgrade and the compact form."""

from __future__ import annotations

from pathlib import Path

from icoda_core import specification as spec_module


def test_defaults_are_valid_and_round_trip(tmp_path: Path) -> None:
    spec = spec_module.default_specification("Demo")
    assert spec["schema_version"] == 2 and spec_module.validate(spec) == []
    spec_module.save(tmp_path / ".icoda" / "specification.json", spec)
    assert spec_module.load(tmp_path / ".icoda" / "specification.json") == spec


def test_ids_and_cross_references() -> None:
    spec = spec_module.default_specification("Demo")
    assert spec_module.next_id(spec, "requirements") == "R-1"
    spec["use_cases"] = [{"id": "UC-1", "title": "Draw"}]
    spec["requirements"] = [{"id": "R-7", "title": "Fast", "priority": "must", "use_cases": ["UC-1", "UC-9"]}]
    spec["decisions"] = [{"id": "D-1", "title": "SDL"}, {"id": "D-1", "title": "again"}]
    assert spec_module.next_id(spec, "requirements") == "R-8"
    problems = spec_module.validate(spec)
    assert "Requirements R-7: unknown use case UC-9" in problems
    assert "Decisions: duplicate ids" in problems


def test_schema_problems_are_readable() -> None:
    spec = spec_module.default_specification("Demo")
    spec["requirements"].append({"id": "REQ-1", "title": "", "priority": "urgent"})
    problems = spec_module.validate(spec)
    assert any(p.startswith("requirements/0/id") for p in problems)
    assert any("priority" in p and "urgent" in p for p in problems)
    assert "Requirements REQ-1: title must not be empty" in problems
    del spec["title"]
    assert "Overview: title is missing" in spec_module.validate(spec)
    spec["use_cases"].append({"id": "UC-1"})
    assert "Use cases UC-1: title is missing" in spec_module.validate(spec)


def test_version_1_files_are_upgraded() -> None:
    old = {"schema_version": 1, "title": "Old", "summary": "s", "objectives": ["a"], "in_scope": ["b"],
           "out_of_scope": ["c"], "stakeholders": ["x"], "assumptions": [], "constraints": [], "dependencies": [],
           "use_cases": [{"id": "UC-1", "title": "Log in", "actor": "user", "description": "Enter."}],
           "requirements": [{"id": "R-1", "title": "Check", "priority": "must", "category": "functional"}],
           "decisions": [{"id": "D-1", "title": "argon2", "rationale": "hard"}], "risks": [{"id": "RK-1"}],
           "verification": [], "open_questions": ["why"], "code_profile": {"language": "C++", "standard": "20"}}
    spec = spec_module.upgrade(old)
    assert spec_module.validate(spec) == [] and spec["schema_version"] == 2
    assert spec["goals"] == ["a", "b"] and spec["out_of_scope"] == ["c"]
    assert spec["use_cases"] == [{"id": "UC-1", "title": "Log in", "description": "Actor: user. Enter."}]
    assert spec["requirements"] == [{"id": "R-1", "title": "Check", "priority": "must"}]
    assert spec["code_profile"]["standard"] == "20" and spec["code_profile"]["max_methods"] == 15
    assert spec_module.upgrade(spec) is spec


def test_compact_form() -> None:
    spec = spec_module.default_specification("Demo")
    spec["summary"] = "A small renderer."
    spec["goals"] = ["Draw shapes"]
    spec["use_cases"] = [{"id": "UC-1", "title": "Draw a scene", "description": "Adds shapes."}]
    spec["requirements"] = [{"id": "R-1", "title": "Render shapes", "priority": "must", "use_cases": ["UC-1"]}]
    text = spec_module.compact(spec)
    assert text.startswith("# Demo\nA small renderer.")
    assert "## goals\n- Draw shapes" in text
    assert "- UC-1: Draw a scene — Adds shapes." in text
    assert "- R-1: Render shapes — priority=must; use_cases=UC-1" in text
    assert "- max function lines: 30" in text and "- modules: True" in text
