"""Extracting and validating the agent's JSON reply, and applying its files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from icoda_core import adaptation, response, steps

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
    assert response.parse_response('{"title": "x", "files": [}')[1] == (
        "the JSON object does not parse: Expecting value at line 1, column 26"
    )
    parsed, error = response.parse_response(json.dumps({"title": "", "rationale": "r", "files": []}))
    assert parsed is None and error == (
        "the JSON object does not match the response schema: files: [] should be non-empty; "
        "title: '' should be non-empty"
    )


def test_approach_response_refuses_missing_broken_and_whitespace_only_prose() -> None:
    assert response.parse_approach_response("no object")[1] == "the reply contains no JSON object"
    assert response.parse_approach_response('{"plan": ]}')[1] == (
        "the JSON object does not parse: Expecting value at line 1, column 10"
    )
    raw = json.dumps({"plan": "   ", "entities": [], "files": []})
    assert response.parse_approach_response(raw)[1] == (
        "the JSON object does not match the approach schema: plan: must contain prose"
    )
    invalid_unicode = json.dumps({"plan": "plan\ud800", "entities": [], "files": []})
    assert response.parse_approach_response(invalid_unicode)[1] == (
        "the JSON object does not match the approach schema: plan: must contain valid UTF-8 text"
    )


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


@pytest.mark.parametrize(("files", "expected"), [
    ([], "files: [] should be non-empty"),
    (["hostile"], "files/0: 'hostile' is not of type 'object'"),
    ([{"path": "", "content": "x"}],
     "files/0/path: '' should be non-empty; files/0/path: must be a plain relative path"),
    ([{"path": "  ", "content": "x"}], "files/0/path: must be a plain relative path"),
    ([{"path": "bad\0name", "content": "x"}], "files/0/path: must not contain a NUL byte"),
    ([{"path": "C:\\outside.txt", "content": "x"}],
     "files/0/path: must be relative to the project root"),
    ([{"path": "a", "content": "first"}, {"path": "a", "action": "delete"}],
     "files/1/path: 'a' appears twice"),
    ([{"path": "a", "content": "\ud800"}], "files/0/content: must contain valid UTF-8 text"),
    ([{"path": "a", "content": 7}], "files/0/content: 7 is not of type 'string'"),
])
def test_parse_response_refuses_adversarial_schema_paths_and_unicode_without_touching_disk(
        tmp_path: Path, files: list[object], expected: str) -> None:
    existing = tmp_path / "a"
    existing.write_bytes(b"unchanged\n")
    before = existing.read_bytes()
    raw = json.dumps({"title": "Hostile", "rationale": "Exercise validation.", "files": files})

    parsed, error = response.parse_response(raw)

    assert parsed is None
    assert error == "the JSON object does not match the response schema: " + expected
    assert existing.read_bytes() == before


def test_parse_response_refuses_implausibly_large_replies_before_json_parsing(tmp_path: Path) -> None:
    existing = tmp_path / "keep.txt"
    existing.write_bytes(b"unchanged\n")
    oversized = "{" + "x" * response.MAX_RESPONSE_BYTES + "}"
    expected = f"the reply exceeds the {response.MAX_RESPONSE_BYTES}-byte size limit"

    assert response.parse_response(oversized) == (None, expected)
    assert response.parse_approach_response(oversized) == (None, expected)
    assert existing.read_bytes() == b"unchanged\n"


def test_apply_changes_writes_and_deletes(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "old.cpp").write_text("x")
    parsed, _ = response.parse_response(json.dumps(GOOD))
    assert parsed is not None
    touched = response.apply_changes(tmp_path, parsed.files)
    assert touched == ["src/renderer/renderer.cppm", "src/old.cpp"]
    assert (tmp_path / "src/renderer/renderer.cppm").read_text() == "export module renderer;\n"
    assert not (tmp_path / "src/old.cpp").exists()


def test_apply_changes_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    escaped = outside / "generated.cpp"
    escaped.write_text("external\n", encoding="utf-8")
    (root / "src").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="leaves the project root"):
        response.apply_changes(root, [response.FileChange("src/generated.cpp", "proposed\n")])

    assert escaped.read_text(encoding="utf-8") == "external\n"


def test_apply_changes_rejects_absolute_path(tmp_path: Path) -> None:
    outside = tmp_path / "outside.cpp"
    outside.write_text("external\n", encoding="utf-8")

    with pytest.raises(ValueError) as refused:
        response.apply_changes(tmp_path / "worktree", [response.FileChange(str(outside), "proposed\n")])

    assert str(refused.value) == f"{outside}: must be relative to the project root"
    assert outside.read_text(encoding="utf-8") == "external\n"


def test_apply_changes_rejects_parent_traversal(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    outside = tmp_path / "outside.cpp"
    outside.write_text("external\n", encoding="utf-8")

    with pytest.raises(ValueError) as refused:
        response.apply_changes(root, [response.FileChange("../outside.cpp", "proposed\n")])

    assert str(refused.value) == "../outside.cpp: must not leave the project root"
    assert outside.read_text(encoding="utf-8") == "external\n"


def test_apply_changes_rejects_symlinked_target_file(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    outside = tmp_path / "outside.cpp"
    outside.write_text("external\n", encoding="utf-8")
    (root / "generated.cpp").symlink_to(outside)

    with pytest.raises(ValueError, match="leaves the project root"):
        response.apply_changes(root, [response.FileChange("generated.cpp", "proposed\n")])

    assert outside.read_text(encoding="utf-8") == "external\n"


def test_apply_changes_rejects_delete_through_symlinked_parent(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    external = outside / "keep.cpp"
    external.write_text("external\n", encoding="utf-8")
    (root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="leaves the project root"):
        response.apply_changes(root, [response.FileChange("linked/keep.cpp", delete=True)])

    assert external.read_text(encoding="utf-8") == "external\n"


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


@pytest.mark.parametrize(("patch", "expected"), [
    (
        ("diff --git a/src/other.txt b/src/other.txt\n--- a/src/a.txt\n+++ b/src/a.txt\n"
         "@@ -1 +1 @@\n-old\n+new\n"),
        ("unified diff for 'src/a.txt' has header 'diff --git a/src/other.txt b/src/other.txt'; "
         "expected 'diff --git a/src/a.txt b/src/a.txt'"),
    ),
    (
        ("diff --git a/src/a.txt b/src/a.txt\n--- a/src/wrong.txt\n+++ b/src/a.txt\n"
         "@@ -1 +1 @@\n-old\n+new\n"),
        "unified diff for 'src/a.txt' must contain exact --- a/src/a.txt and +++ b/src/a.txt headers",
    ),
    (
        ("diff --git a/src/a.txt b/src/a.txt\n--- a/src/a.txt\n+++ b/src/a.txt\n"
         "@@ -1 +1 @@\ndiff --git a/src/b.txt b/src/b.txt\n"),
        "unified diff for 'src/a.txt' contains more than one file",
    ),
    (
        ("diff --git a/src/a.txt b/src/a.txt\n--- a/src/a.txt\n+++ b/src/a.txt\n"
         "@@ -1 +1 @@\n\\ No newline at end of file\n"),
        "unified diff for 'src/a.txt' has a misplaced no-newline marker",
    ),
    (
        ("diff --git a/src/a.txt b/src/a.txt\n--- a/src/a.txt\n+++ b/src/a.txt\n"
         "@@ -1 +1 @@\n?bad\n"),
        "unified diff for 'src/a.txt' has an invalid hunk line at line 5",
    ),
])
def test_parse_response_refuses_hostile_unified_diff_structure(patch: str, expected: str) -> None:
    raw = json.dumps({"title": "Bad patch", "rationale": "Invalid on purpose.",
                      "files": [{"path": "src/a.txt", "content": patch}]})

    assert response.parse_response(raw) == (None, expected)


@pytest.mark.parametrize(("source", "path", "expected"), [
    (b"actual context\n", "src/a.txt",
     "unified diff for 'src/a.txt' does not apply: hunk 1 does not match at old line 1"),
    (None, "src/missing.txt", "unified diff for 'src/missing.txt' names an unknown file"),
])
def test_diff_context_or_unknown_file_is_refused_before_any_file_changes(
        tmp_path: Path, source: bytes | None, path: str, expected: str) -> None:
    root = tmp_path / "worktree"
    target = root / path
    target.parent.mkdir(parents=True)
    if source is not None:
        target.write_bytes(source)
    sentinel = root / "keep.txt"
    sentinel.write_bytes(b"keep byte-identical\n")
    patch = (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
             "@@ -1 +1 @@\n-expected context\n+replacement\n")
    raw = json.dumps({"title": "Bad patch", "rationale": "Must not apply.",
                      "files": [{"path": path, "content": patch}]})
    parsed, error = response.parse_response(raw)
    assert error == "" and parsed is not None
    before = {item.relative_to(root): item.read_bytes() for item in root.rglob("*") if item.is_file()}

    with pytest.raises(ValueError) as refused:
        steps._apply_candidate_files(root, parsed.files)

    assert str(refused.value) == expected
    assert {item.relative_to(root): item.read_bytes() for item in root.rglob("*") if item.is_file()} == before


def test_diff_rejects_non_utf8_target_before_any_file_changes(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    target = root / "data.bin"
    target.write_bytes(b"\xff\xfe\x00")
    patch = ("diff --git a/data.bin b/data.bin\n--- a/data.bin\n+++ b/data.bin\n"
             "@@ -1 +1 @@\n-old\n+new\n")
    raw = json.dumps({"title": "Bad encoding", "rationale": "Must not apply.",
                      "files": [{"path": "data.bin", "content": patch}]})
    parsed, error = response.parse_response(raw)
    assert error == "" and parsed is not None

    with pytest.raises(ValueError) as refused:
        steps._apply_candidate_files(root, parsed.files)

    assert str(refused.value) == "unified diff for 'data.bin' cannot patch a non-UTF-8 file"
    assert target.read_bytes() == b"\xff\xfe\x00"
