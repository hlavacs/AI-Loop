"""Pure external-source snapshot detection."""

from __future__ import annotations

from pathlib import Path

from icoda_core import git, source_watch


def test_changed_files_reports_only_the_edited_analysed_source(tmp_path: Path) -> None:
    edited = tmp_path / "edited.py"
    untouched = tmp_path / "untouched.py"
    edited.write_text("value = 1\n", encoding="utf-8")
    untouched.write_text("other = 2\n", encoding="utf-8")
    before = source_watch.snapshot_files(tmp_path, ("edited.py", "untouched.py"))

    edited.write_text("value = 1000\n", encoding="utf-8")
    after = source_watch.snapshot_files(tmp_path, ("edited.py", "untouched.py"))

    assert source_watch.changed_files(before, after) == frozenset({"edited.py"})
    assert "untouched.py" not in source_watch.changed_files(before, after)
    assert "tkinter" not in Path(source_watch.__file__).read_text(encoding="utf-8")


def test_project_snapshot_detects_renames_and_new_files_but_ignores_build_and_metadata(tmp_path):
    git.run_git(["init", "-q"], tmp_path)
    (tmp_path / ".gitignore").write_text("build/\n")
    (tmp_path / "app.cppm").write_text("int run();\n")
    git.run_git(["add", "app.cppm", ".gitignore"], tmp_path)
    before = source_watch.snapshot_project(tmp_path)
    (tmp_path / "app.cppm").rename(tmp_path / "app.cpp")
    (tmp_path / "app.hpp").write_text("int run();\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build/output").write_text("binary")
    (tmp_path / ".icoda").mkdir()
    (tmp_path / ".icoda/cache.json").write_text("{}")
    after = source_watch.snapshot_project(tmp_path)
    assert before is not None and after is not None
    assert source_watch.changed_files(before, after) == {"app.cppm", "app.cpp", "app.hpp"}


def test_new_project_snapshot_before_git_initialization(tmp_path):
    before = source_watch.snapshot_project(tmp_path)
    assert before == ()
    (tmp_path / "app.py").write_text("def run(): pass\n")
    (tmp_path / ".icoda").mkdir()
    (tmp_path / ".icoda/cache.json").write_text("{}")
    after = source_watch.snapshot_project(tmp_path)
    assert after is not None
    assert source_watch.changed_files(before, after) == {"app.py"}


def test_new_project_inside_ignored_parent_directory_still_detects_edits(tmp_path):
    git.run_git(["init", "-q"], tmp_path)
    (tmp_path / ".gitignore").write_text("new-project/\n")
    project = tmp_path / "new-project"
    project.mkdir()
    (project / "draft.py").write_text("def run(): pass\n")
    before = source_watch.snapshot_project(project)
    (project / "draft.py").rename(project / "app.py")
    after = source_watch.snapshot_project(project)
    assert before is not None and after is not None
    assert source_watch.changed_files(before, after) == {"draft.py", "app.py"}
