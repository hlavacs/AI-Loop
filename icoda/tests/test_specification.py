"""Specification defaults, validation with readable problems, ids, round trip, upgrade and the compact form."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from icoda_core import persistence
from icoda_core import specification as spec_module


def test_defaults_are_valid_and_round_trip(tmp_path: Path) -> None:
    spec = spec_module.default_specification("Demo")
    assert spec["schema_version"] == 2 and spec_module.validate(spec) == []
    spec_module.save(tmp_path / ".icoda" / "specification.json", spec)
    assert spec_module.load(tmp_path / ".icoda" / "specification.json") == spec


def test_atomic_save_preserves_previous_specification_when_replace_fails(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / ".icoda" / "specification.json"
    previous = spec_module.default_specification("Existing specification")
    spec_module.save(path, previous)
    previous_bytes = path.read_bytes()
    assert sorted(item.name for item in path.parent.iterdir()) == ["specification.json"]
    observed: dict[str, bytes] = {}

    def fail_replace(source: Path, target: Path) -> None:
        observed["temporary"] = source.read_bytes()
        observed["target"] = target.read_bytes()
        raise OSError("injected replace failure")

    monkeypatch.setattr(persistence.os, "replace", fail_replace)
    replacement = spec_module.default_specification("Replacement specification")

    with pytest.raises(OSError, match="injected replace failure"):
        spec_module.save(path, replacement)

    expected_temporary = (json.dumps(replacement, indent=2, ensure_ascii=False) + "\n").encode()
    assert observed["temporary"] == expected_temporary
    assert observed["target"] == previous_bytes
    assert path.read_bytes() == previous_bytes
    assert spec_module.load(path) == previous
    assert sorted(item.name for item in path.parent.iterdir()) == ["specification.json"]


def test_save_uses_persistence_atomic_write_and_cleans_up_after_mid_write_failure(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".icoda" / "specification.json"
    path.parent.mkdir()
    path.write_bytes(b"previous specification bytes\n")
    previous_bytes = path.read_bytes()
    calls: list[Path] = []
    atomic_write = persistence._atomic_write_text

    def observed_atomic_write(target: Path, text: str) -> None:
        calls.append(target)
        atomic_write(target, text)

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("injected mid-write failure")

    monkeypatch.setattr(persistence, "_atomic_write_text", observed_atomic_write)
    monkeypatch.setattr(persistence.os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="injected mid-write failure"):
        spec_module.save(path, spec_module.default_specification("Replacement"))

    assert calls == [path]
    assert path.read_bytes() == previous_bytes
    assert sorted(item.name for item in path.parent.iterdir()) == ["specification.json"]


def test_pre_profile_specification_loads_with_the_unchanged_cpp_default(tmp_path: Path) -> None:
    path = tmp_path / "specification.json"
    (tmp_path / "app.py").write_text("pass\n", encoding="utf-8")
    path.write_text(
        '{"schema_version": 2, "title": "Legacy", "summary": "", "goals": [], '
        '"out_of_scope": [], "not_allowed": [], "done_when": [], "use_cases": [], '
        '"requirements": [], "decisions": []}',
        encoding="utf-8",
    )
    loaded = spec_module.load(path)
    assert loaded["code_profile"] == spec_module.default_code_profile()


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


def test_adversarial_document_reports_every_schema_violation_without_being_saved(tmp_path: Path) -> None:
    path = tmp_path / "specification.json"
    path.write_bytes(b"existing specification bytes\n")
    spec = spec_module.default_specification("Demo")
    spec["schema_version"] = 99
    spec["title"] = ""
    spec["goals"] = "not a list"
    spec["use_cases"] = [{"id": "hostile"}]
    spec["code_profile"]["unexpected"] = "x"

    assert spec_module.validate(spec) == [
        "code_profile: Additional properties are not allowed ('unexpected' was unexpected)",
        "goals: 'not a list' is not of type 'array'",
        "schema_version: 2 was expected",
        "Overview: title must not be empty",
        "Use cases hostile: title is missing",
        "use_cases/0/id: 'hostile' does not match '^UC-[0-9]+$'",
    ]
    assert path.read_bytes() == b"existing specification bytes\n"


@pytest.mark.parametrize("content", ["{", '{"schema_version": 2'])
def test_load_corrupt_or_truncated_specification_raises_without_replacing_it(
        tmp_path: Path, content: str) -> None:
    path = tmp_path / "specification.json"
    path.write_text(content, encoding="utf-8")
    before = path.read_bytes()

    with pytest.raises(json.JSONDecodeError):
        spec_module.load(path)

    assert path.read_bytes() == before
    assert sorted(item.name for item in tmp_path.iterdir()) == ["specification.json"]


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
    partial = {"schema_version": 2, "title": "t"}
    assert spec_module.upgrade(partial)["not_allowed"] == [] and spec_module.upgrade(partial)["done_when"] == []


def test_compact_form() -> None:
    spec = spec_module.default_specification("Demo")
    spec["summary"] = "A small renderer."
    spec["goals"] = ["Draw shapes"]
    spec["not_allowed"] = ["Boost"]
    spec["done_when"] = ["All tests pass"]
    spec["use_cases"] = [{"id": "UC-1", "title": "Draw a scene", "description": "Adds shapes."}]
    spec["requirements"] = [{"id": "R-1", "title": "Render shapes", "priority": "must", "use_cases": ["UC-1"]}]
    text = spec_module.compact(spec)
    assert text.startswith("# Demo\nA small renderer.")
    assert "## goals\n- Draw shapes" in text
    assert "## not allowed\n- Boost" in text and "## done when\n- All tests pass" in text
    assert "- UC-1: Draw a scene — Adds shapes." in text
    assert "- R-1: Render shapes — priority=must; use_cases=UC-1" in text
    assert "- max function lines: 30" in text and "- modules: True" in text
