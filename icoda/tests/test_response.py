"""Extracting and validating the agent's JSON reply, and applying its files."""

from __future__ import annotations

import json
from pathlib import Path

from icoda_core import response

GOOD = {"title": "Introduce the renderer", "rationale": "The renderer is the first collaborator of main().",
        "files": [{"path": "src/renderer/renderer.cppm", "content": "export module renderer;\n"},
                  {"path": "src/old.cpp", "action": "delete"}],
        "entities": [{"name": "renderer::Renderer", "kind": "class", "file": "src/renderer/renderer.cppm"}]}


def test_parses_json_wrapped_in_prose_and_fences() -> None:
    text = "Here is the step:\n```json\n" + json.dumps(GOOD) + "\n```\nDone."
    parsed, error = response.parse_response(text)
    assert error == "" and parsed is not None
    assert parsed.title == "Introduce the renderer" and len(parsed.files) == 2
    assert parsed.files[1].delete and parsed.entities[0]["kind"] == "class"


def test_reports_missing_broken_and_invalid_json() -> None:
    assert response.parse_response("no json here")[1] == "the reply contains no JSON object"
    assert "does not parse" in response.parse_response('{"title": "x", "files": [}')[1]
    parsed, error = response.parse_response(json.dumps({"title": "", "rationale": "r", "files": []}))
    assert parsed is None and "title" in error and "files" in error


def test_path_rules() -> None:
    assert response.path_problem("src/a.cppm") == ""
    assert "relative" in response.path_problem("/etc/passwd")
    assert "relative" in response.path_problem("C:\\x\\y.cpp")
    assert "leave" in response.path_problem("../outside.cpp")
    assert "git" in response.path_problem(".git/config")
    assert "git" in response.path_problem("build/x")
    bad = dict(GOOD, files=[{"path": "a.cpp"}, {"path": "a.cpp", "content": ""}])
    problems = response.validate(bad)
    assert any("full content" in p for p in problems) and any("twice" in p for p in problems)


def test_apply_changes_writes_and_deletes(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "old.cpp").write_text("x")
    parsed, _ = response.parse_response(json.dumps(GOOD))
    assert parsed is not None
    touched = response.apply_changes(tmp_path, parsed.files)
    assert touched == ["src/renderer/renderer.cppm", "src/old.cpp"]
    assert (tmp_path / "src/renderer/renderer.cppm").read_text() == "export module renderer;\n"
    assert not (tmp_path / "src/old.cpp").exists()
