"""Extracting and validating the agent's JSON reply, and applying its files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from icoda_core import adaptation, response

GOOD = {"title": "Introduce the renderer", "rationale": "The renderer is the first collaborator of main().",
        "files": [{"path": "src/renderer/renderer.cppm", "content": "export module renderer;\n"},
                  {"path": "src/old.cpp", "action": "delete"}],
        "entities": [{"name": "renderer::Renderer", "kind": "class", "file": "src/renderer/renderer.cppm"}]}


def test_parses_json_wrapped_in_prose_and_fences() -> None:
    text = "Here is the step:\n```json\n" + json.dumps(GOOD) + "\n```\nDone."
    parsed, error = response.parse_response(text)
    assert error == "" and parsed is not None
    assert parsed.title == "Introduce the renderer" and len(parsed.files) == 2
    assert parsed.files[1].delete
    assert parsed.entities == (
        adaptation.EntitySummary("renderer::Renderer", "class", "src/renderer/renderer.cppm"),)


def test_entities_free_reply_keeps_the_additive_empty_default() -> None:
    raw = json.dumps({"title": "Small step", "rationale": "No summary supplied.",
                      "files": [{"path": "src/a.cpp", "content": "int a;\n"}]})
    parsed, error = response.parse_response(raw)
    assert error == "" and parsed is not None
    assert parsed.entities == ()


def test_reports_missing_broken_and_invalid_json() -> None:
    assert response.parse_response("no json here")[1] == "the reply contains no JSON object"
    assert "does not parse" in response.parse_response('{"title": "x", "files": [}')[1]
    parsed, error = response.parse_response(json.dumps({"title": "", "rationale": "r", "files": []}))
    assert parsed is None and "title" in error and "files" in error


def test_approach_response_is_prose_only_and_validates_expected_paths() -> None:
    raw = json.dumps({"plan": "Use std::ranges::find; about six lines.", "entities": ["app::find"],
                      "files": ["src/app.cpp", "tests/app_test.cpp"]})
    parsed, error = response.parse_approach_response(raw)
    assert error == "" and parsed is not None
    assert parsed.plan.startswith("Use std::ranges") and parsed.entities == ("app::find",)
    assert parsed.files == ("src/app.cpp", "tests/app_test.cpp")

    with_content = json.dumps({"plan": "plan", "entities": [],
                               "files": [], "content": "int changed = 1;"})
    assert "Additional properties" in response.parse_approach_response(with_content)[1]
    unsafe = json.dumps({"plan": "plan", "entities": [], "files": ["../outside.cpp"]})
    assert "must not leave" in response.parse_approach_response(unsafe)[1]


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


def test_parse_response_purely_parses_multifile_multihunk_unified_diff(
        monkeypatch: pytest.MonkeyPatch) -> None:
    diff_a = """diff --git a/src/a.txt b/src/a.txt
--- a/src/a.txt
+++ b/src/a.txt
@@ -1,2 +1,2 @@
 alpha
-beta
+BETA
@@ -5 +5,2 @@
-epsilon
+EPSILON
+zeta
"""
    diff_b = """diff --git a/src/b.txt b/src/b.txt
--- a/src/b.txt
+++ b/src/b.txt
@@ -2,2 +2,2 @@ section
 second
-third
+THIRD
"""
    raw = json.dumps({"title": "Patch two files", "rationale": "Keep the change focused.",
                      "files": [{"path": "src/a.txt", "content": diff_a},
                                {"path": "src/b.txt", "content": diff_b}]})

    def forbidden_filesystem_access(*args: object, **kwargs: object) -> str:
        raise AssertionError(f"parse_response accessed the filesystem: {args!r} {kwargs!r}")

    monkeypatch.setattr(Path, "read_text", forbidden_filesystem_access)
    monkeypatch.setattr(Path, "read_bytes", forbidden_filesystem_access)
    monkeypatch.setattr(Path, "write_text", forbidden_filesystem_access)
    monkeypatch.setattr(Path, "write_bytes", forbidden_filesystem_access)
    parsed, error = response.parse_response(raw)
    assert error == "" and parsed is not None
    assert all(getattr(value, "__name__", "") != "tkinter" for value in response.__dict__.values())
    assert {change.path for change in parsed.files} == {"src/a.txt", "src/b.txt"}
    assert parsed.files[0].hunks == (
        response.DiffHunk(1, 2, 1, 2, (" alpha\n", "-beta\n", "+BETA\n")),
        response.DiffHunk(5, 1, 5, 2, ("-epsilon\n", "+EPSILON\n", "+zeta\n")),
    )
    assert parsed.files[1].hunks == (
        response.DiffHunk(2, 2, 2, 2, (" second\n", "-third\n", "+THIRD\n")),
    )


def test_parse_response_rejects_malformed_diff_header_and_hunk_counts() -> None:
    def parsed_error(patch: str) -> str:
        raw = json.dumps({"title": "Bad patch", "rationale": "Invalid on purpose.",
                          "files": [{"path": "src/a.txt", "content": patch}]})
        return response.parse_response(raw)[1]

    malformed = """diff --git a/src/a.txt b/src/a.txt
--- a/src/a.txt
+++ b/src/a.txt
@@ old +new @@
-old
+new
"""
    wrong_counts = """diff --git a/src/a.txt b/src/a.txt
--- a/src/a.txt
+++ b/src/a.txt
@@ -1,2 +1,2 @@
-old
+new
"""
    assert parsed_error(malformed) == (
        "unified diff for 'src/a.txt' has malformed hunk header at line 4: '@@ old +new @@'"
    )
    assert parsed_error(wrong_counts) == (
        "unified diff for 'src/a.txt' hunk 1 line counts disagree with its header: "
        "expected old 2/new 2, got old 1/new 1"
    )
    assert "tk" not in response.__dict__ and "tkinter" not in response.__dict__
