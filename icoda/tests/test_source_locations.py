"""Resolve cached source locations after files or build directories move."""
from pathlib import Path

import pytest

from icoda_core import source_edit
from icoda_gui import source_editor


def write(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("// source\n", encoding="utf-8")


def test_existing_path_wins_without_search(tmp_path, monkeypatch):
    write(tmp_path, "src/main.cpp")
    write(tmp_path, "copy/main.cpp")
    monkeypatch.setattr(source_edit.os, "walk", lambda *_: pytest.fail("Existing files need no search"))
    assert source_edit.find_source(tmp_path, "src/main.cpp") == ("src/main.cpp",)


@pytest.mark.parametrize("file", ["include/VVPPL.h", "src/VVPPL.cpp", "shaders/invert_spv.h"])
def test_finds_dependency_sources_in_another_build_directory(tmp_path, file):
    old = f"build/debug-windows/_deps/library/{file}"
    current = f"build/release-windows/_deps/library/{file}"
    write(tmp_path, current)
    assert source_edit.find_source(tmp_path, old) == (current,)


def test_prefers_the_matching_parent_directories(tmp_path):
    write(tmp_path, "build/release/_deps/library/src/util.cpp")
    write(tmp_path, "unrelated/util.cpp")
    assert source_edit.find_source(tmp_path, "build/debug/_deps/library/src/util.cpp") == (
        "build/release/_deps/library/src/util.cpp",)


def test_equal_matches_remain_ambiguous(tmp_path):
    write(tmp_path, "build/release/src/util.cpp")
    write(tmp_path, "build/debug/src/util.cpp")
    assert source_edit.find_source(tmp_path, "build/old/src/util.cpp") == (
        "build/debug/src/util.cpp", "build/release/src/util.cpp")


def test_search_stays_inside_the_selected_project_or_worktree(tmp_path):
    write(tmp_path, "src/util.cpp")
    worktree = tmp_path / ".icoda/worktree"
    worktree.mkdir(parents=True)
    assert source_edit.find_source(worktree, "src/util.cpp") == ()
    write(tmp_path, ".git/old/removed.cpp")
    write(tmp_path, ".icoda/worktree/removed.cpp")
    assert source_edit.find_source(tmp_path, "src/removed.cpp") == ()


def test_search_rejects_escapes_and_external_symlinks(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    write(tmp_path, "outside.cpp")
    (root / "outside.cpp").symlink_to(tmp_path / "outside.cpp")
    assert source_edit.find_source(root, "old/outside.cpp") == ()
    with pytest.raises(ValueError):
        source_edit.find_source(root, "../missing.cpp")


@pytest.mark.parametrize("node", ["file:src/b.cpp", "entity:u:g"])
def test_click_relocated_source_opens_it_without_provider_recovery(app_module, tmp_path, monkeypatch, node):
    from test_source_editor import app_with_source

    app = app_with_source(app_module, tmp_path)
    moved = tmp_path / "moved/b.cpp"
    moved.parent.mkdir()
    (tmp_path / "src/b.cpp").rename(moved)
    monkeypatch.setattr(app.recovery, "handle_failure",
                        lambda *a, **k: pytest.fail("Relocated files must not start provider recovery"))
    monkeypatch.setattr(app.views, "select", lambda *_: pytest.fail("Keep the selected diagram"))
    app.select_node(node)
    assert app.source_editor.document.path == moved
    assert app.source_editor.document.relative == "moved/b.cpp"
    assert "moved/b.cpp" in app.status.get()
    app.source_editor.text.insert("end", "// unsaved")
    monkeypatch.setattr(app.source_editor, "confirm_saved", lambda: pytest.fail("The same file stays open"))
    app.select_node(node)
    assert app.source_editor.document.path == moved and app.source_editor.dirty


def test_ambiguous_source_keeps_editor_and_does_not_start_provider(app_module, tmp_path, monkeypatch):
    from test_source_editor import app_with_source

    app = app_with_source(app_module, tmp_path)
    app.open_editor("src/a.cpp")
    document = app.source_editor.document
    (tmp_path / "src/b.cpp").unlink()
    write(tmp_path, "first/b.cpp")
    write(tmp_path, "second/b.cpp")
    monkeypatch.setattr(app.recovery, "handle_failure", lambda *a, **k: pytest.fail("No provider recovery"))
    app.select_node("src/b.cpp")
    assert "Multiple source files" in app.status.get()
    assert app.source_editor.document is document


@pytest.mark.parametrize("node", ["file:src/b.cpp", "entity:u:g"])
@pytest.mark.parametrize("dirty", [False, True])
def test_click_missing_cached_source_stays_in_diagram_and_keeps_editor(
        app_module, tmp_path, monkeypatch, node, dirty):
    from test_source_editor import app_with_source

    app = app_with_source(app_module, tmp_path)
    app.open_editor("src/a.cpp")
    if dirty:
        app.source_editor.text.insert("end", "// unsaved edits")
    document, content = app.source_editor.document, app.source_editor.content()
    missing = tmp_path / "src/b.cpp"
    missing.unlink()
    monkeypatch.setattr(app.recovery, "handle_failure",
                        lambda *a, **k: pytest.fail("Missing source must not start provider recovery"))
    monkeypatch.setattr(app.views, "select", lambda *_: pytest.fail("Keep the selected diagram"))
    monkeypatch.setattr(app.side_views, "select", lambda *_: pytest.fail("Keep the selected sidebar tab"))
    monkeypatch.setattr(source_editor.messagebox, "askyesnocancel",
                        lambda *a, **k: pytest.fail("Do not discard edits to open a missing file"))

    app.select_node(node)
    assert "src/b.cpp" in app.status.get() and str(tmp_path) in app.status.get()
    assert "Reload" in app.status.get()
    assert app.source_editor.info.get() == app.status.get()
    assert app.source_editor.document is document and app.source_editor.content() == content
    assert app.source_editor.dirty is dirty and app.recovery.issue is None
    if not dirty:
        missing.write_text("void g() {}\n")
        app.select_node(node)
        assert app.source_editor.document.relative == "src/b.cpp"


def test_missing_candidate_source_does_not_fall_back_to_project(app_module, tmp_path, monkeypatch):
    from test_source_editor import app_with_source

    app = app_with_source(app_module, tmp_path)
    app.open_editor("src/a.cpp")
    document = app.source_editor.document
    worktree = tmp_path / ".icoda/worktree"
    worktree.mkdir(parents=True)
    monkeypatch.setattr(app.recovery, "handle_failure",
                        lambda *a, **k: pytest.fail("Missing candidate source must not start recovery"))
    app.open_editor("src/a.cpp", root=worktree, reveal=True)
    assert str(worktree) in app.status.get() and "src/a.cpp" in app.status.get()
    assert app.source_editor.document is document


