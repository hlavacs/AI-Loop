"""Specification defaults, validation with readable problems, ids, round trip and the compact prompt form."""

from __future__ import annotations

from pathlib import Path

from icoda_core import specification as spec_module


def test_default_specification_is_valid_and_round_trips(tmp_path: Path) -> None:
    spec = spec_module.default_specification("Demo")
    assert spec_module.validate(spec) == []
    spec_module.save(tmp_path / ".icoda" / "specification.json", spec)
    assert spec_module.load(tmp_path / ".icoda" / "specification.json") == spec


def test_ids_and_cross_references() -> None:
    spec = spec_module.default_specification("Demo")
    assert spec_module.next_id(spec, "requirements") == "R-1"
    spec["use_cases"].append({"id": "UC-1", "title": "Draw a scene", "actor": "developer"})
    spec["requirements"].append({"id": "R-1", "title": "Render shapes", "priority": "must", "use_cases": ["UC-1"]})
    spec["requirements"].append({"id": "R-7", "title": "Log", "priority": "could", "use_cases": ["UC-9"]})
    spec["verification"].append({"id": "V-1", "requirement": "R-3", "method": "unit test"})
    assert spec_module.next_id(spec, "requirements") == "R-8"
    problems = spec_module.validate(spec)
    assert any("unknown use case UC-9" in p for p in problems)
    assert any("unknown requirement R-3" in p for p in problems)


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


def test_compact_form() -> None:
    spec = spec_module.default_specification("Demo")
    spec["summary"] = "A small renderer."
    spec["objectives"] = ["Draw shapes"]
    spec["use_cases"].append({"id": "UC-1", "title": "Draw a scene", "actor": "developer", "description": "Adds shapes."})
    spec["requirements"].append({"id": "R-1", "title": "Render shapes", "priority": "must", "use_cases": ["UC-1"]})
    text = spec_module.compact(spec)
    assert text.startswith("# Demo\nA small renderer.")
    assert "## objectives\n- Draw shapes" in text
    assert "- UC-1: Draw a scene — actor=developer; Adds shapes." in text
    assert "- R-1: Render shapes — priority=must; use_cases=UC-1" in text
    assert "- max function lines: 30" in text and "- modules: True" in text
