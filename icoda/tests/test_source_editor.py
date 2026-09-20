"""Source editor file safety, search/replace, navigation, and integration with workflow gates."""
from __future__ import annotations

import stat
from types import SimpleNamespace

import pytest

from icoda_core import persistence, prompt, source_edit, steps
from icoda_gui import source_editor


@pytest.mark.parametrize("raw,newline", [(b"int a;\n", "\n"), (b"int a;\r\n", "\r\n"),
                                          (b"\xef\xbb\xbfint a;\r\n", "\r\n"), (b"int a;", "\n")])
def test_save_preserves_format_and_permissions(tmp_path, raw, newline):
    path = tmp_path / "app.cpp"
    path.write_bytes(raw)
    path.chmod(0o640)
    doc = source_edit.Document.load(tmp_path, "app.cpp")
    doc.save(doc.text)
    assert path.read_bytes() == raw
    doc.save(doc.text.replace("a;", "answer;"))
    assert path.read_bytes() == raw.replace(b"a;", b"answer;")
    assert doc.newline == newline and stat.S_IMODE(path.stat().st_mode) == 0o640
    assert not list(tmp_path.glob(".app.cpp.*.tmp"))


def test_external_edits_are_never_overwritten(tmp_path):
    path = tmp_path / "app.cpp"
    path.write_text("original")
    doc = source_edit.Document.load(tmp_path, "app.cpp")
    path.write_text("external edits")
    with pytest.raises(source_edit.FileChangedError, match="changed on disk"):
        doc.save("my edits")
    assert path.read_text() == "external edits" and doc.text == "original"


def test_project_alias_and_normalized_paths_keep_the_same_document(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    pane, path, saved, failed = editor(root)
    pane.text.insert("end", "// edit\n")
    assert pane.open_file(alias, str(alias / "app.cpp")) and pane.dirty
    assert pane.open_file(root, "folder/../app.cpp") and pane.dirty
    doc = source_edit.Document.load(alias, str(alias / "app.cpp"))
    doc.save(doc.text + "// via alias\n")
    assert path.read_text().endswith("// via alias\n") and not failed and not saved


def test_failed_atomic_save_retains_original_and_cleans_temporary(tmp_path, monkeypatch):
    path = tmp_path / "app.cpp"
    path.write_text("original")
    doc = source_edit.Document.load(tmp_path, "app.cpp")
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(source_edit.os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        doc.save("edited")
    assert path.read_text() == "original" and doc.text == "original"
    assert list(tmp_path.iterdir()) == [path]


def test_path_escape_symlink_metadata_binary_and_unsupported_encoding_are_refused(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.cpp"
    outside.write_text("outside")
    (root / "escape.cpp").symlink_to(outside)
    for relative in ("../outside.cpp", "escape.cpp", ".git/config", ".icoda/state.json"):
        with pytest.raises(ValueError):
            source_edit.Document.load(root, relative)
    for data in (b"binary\0data", b"non-UTF8\xff", b"x" * (source_edit.MAX_BYTES + 1)):
        (root / "data").write_bytes(data)
        with pytest.raises(ValueError):
            source_edit.Document.load(root, "data")
    assert outside.read_text() == "outside"


def test_link_retarget_during_edit_and_readonly_file_are_preserved(tmp_path):
    for name in ("a.cpp", "b.cpp"):
        (tmp_path / name).write_text("same")
    link = tmp_path / "link.cpp"
    link.symlink_to(tmp_path / "a.cpp")
    doc = source_edit.Document.load(tmp_path, "link.cpp")
    link.unlink()
    link.symlink_to(tmp_path / "b.cpp")
    with pytest.raises(source_edit.FileChangedError):
        doc.save("edited")
    (tmp_path / "a.cpp").chmod(0o444)
    doc = source_edit.Document.load(tmp_path, "a.cpp")
    try:
        with pytest.raises(PermissionError, match="read-only"):
            doc.save("edited")
    finally:
        (tmp_path / "a.cpp").chmod(0o644)
    assert (tmp_path / "b.cpp").read_text() == "same"


def test_literal_unicode_search_and_case():
    assert source_edit.matches("🎯 a.b A.B a+b", "a.b") == [(2, 5), (6, 9)]
    assert source_edit.matches("🎯 a.b A.B a+b", "a.b", True) == [(2, 5)]
    assert source_edit.matches("text", "") == []


def editor(tmp_path):
    path = tmp_path / "app.cpp"
    path.write_text("// 🎯\nclass Box {};\nint answer() { return 1; }\n")
    saved, failed = [], []
    pane = source_editor.SourceEditor(None, project=lambda: tmp_path, busy=lambda: False,
                                     saved=saved.append, failed=lambda *a, **k: failed.append((a, k)))
    assert pane.open_file(tmp_path, "app.cpp", 3)
    return pane, path, saved, failed


def test_editor_navigation_retains_edits_and_save(tmp_path):
    pane, path, saved, failed = editor(tmp_path)
    assert pane.text.index("insert") == "3.0" and not pane.dirty
    pane.text.insert("end", "// unsaved\n")
    assert pane.open_file(tmp_path, "app.cpp", 2)
    assert pane.dirty and pane.text.index("insert") == "2.0"
    assert "unsaved" not in path.read_text()
    assert pane.save()
    assert "unsaved" in path.read_text() and not pane.dirty and len(saved) == 1 and not failed


def test_file_switch_cancel_discard_and_save(tmp_path, monkeypatch):
    pane, path, saved, failed = editor(tmp_path)
    second = tmp_path / "other.cpp"
    second.write_text("other")
    pane.text.insert("end", "my changes")
    monkeypatch.setattr(source_editor.messagebox, "askyesnocancel", lambda *a, **k: None)
    assert not pane.open_file(tmp_path, "other.cpp") and pane.dirty
    assert pane.document.path == path
    monkeypatch.setattr(source_editor.messagebox, "askyesnocancel", lambda *a, **k: True)
    assert pane.open_file(tmp_path, "other.cpp") and "my changes" in path.read_text()
    pane.text.insert("end", "discard these")
    monkeypatch.setattr(source_editor.messagebox, "askyesnocancel", lambda *a, **k: False)
    assert pane.open_file(tmp_path, "app.cpp") and second.read_text() == "other"
    assert not failed and len(saved) == 1


def test_find_wrap_replace_one_and_replace_all_are_literal(tmp_path):
    pane, path, saved, failed = editor(tmp_path)
    pane.text.delete("1.0", "end")
    pane.text.insert("1.0", "// 🎯\na.b A.B a.b")
    pane.goto(1)
    pane.query.set("a.b")
    pane.replacement.set(r"$1\literal")
    pane.find()
    assert pane._match == (5, 8)
    pane.find(backwards=True)
    assert pane._match == (13, 16)
    pane.find()
    assert pane._match == (5, 8)
    pane.replace_one()
    assert pane.content().startswith("// 🎯\n$1\\literal A.B")
    pane.match_case.set(True)
    pane.replace_all()
    assert "A.B" in pane.content() and "a.b" not in pane.content()
    assert pane.info.get() == "Replaced 1 matches"
    assert "a.b" not in path.read_text() and not saved and not failed
    pane.query.set("")
    pane.find()
    assert pane.info.get() == "Enter text to find"


def test_save_conflict_retries_before_error_and_keeps_buffer(tmp_path, monkeypatch):
    pane, path, saved, failed = editor(tmp_path)
    pane.text.insert("end", "my edits")
    path.write_text("external edits")
    attempts = []
    original = pane.document.save
    def save(text):
        attempts.append(text)
        return original(text)
    monkeypatch.setattr(pane.document, "save", save)
    assert not pane.save()
    assert len(attempts) == 2 and failed[0][1]["attempted"] is True
    assert pane.content().endswith("my edits") and pane.dirty
    assert path.read_text() == "external edits" and not saved


def test_busy_save_stays_in_buffer_and_transient_save_recovers(tmp_path, monkeypatch):
    pane, path, saved, failed = editor(tmp_path)
    pane.text.insert("end", "edit")
    pane.busy = lambda: True
    assert not pane.save() and "edit" not in path.read_text()
    pane.busy = lambda: False
    original = pane.document.save
    calls = []
    def save(text):
        calls.append(text)
        if len(calls) == 1:
            raise OSError("temporary file error")
        original(text)
    monkeypatch.setattr(pane.document, "save", save)
    assert pane.save() and len(calls) == 2 and not failed and len(saved) == 1


def app_with_source(app_module, tmp_path):
    from test_app import opened_project
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.cpp").write_text("// file\n\nclass A {\npublic:\nvoid f();\n};\n")
    (tmp_path / "src/b.cpp").write_text("void g() {}\n")
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "config.json")
    app.show(opened_project(tmp_path))
    return app


def test_click_file_class_function_and_entity_tree_opens_source(app_module, tmp_path, monkeypatch):
    app = app_with_source(app_module, tmp_path)
    app.select_node("file:src/a.cpp")
    assert app.source_editor.document.relative == "src/a.cpp" and app.source_editor.text.index("insert") == "1.0"
    app.select_node("entity:u:A")
    assert app.source_editor.text.index("insert") == "3.0"
    monkeypatch.setattr(app.tree, "selection", lambda: ("u:A:f",))
    app.on_tree_select(None)
    assert app.source_editor.text.index("insert") == "5.0"
    assert app.call_view.root_usr == "u:A:f"
    app.open_editor("entity:u:A")
    assert app.source_editor.text.index("insert") == "3.0"


def test_call_and_class_single_click_open_their_declarations(app_module, tmp_path, monkeypatch):
    app = app_with_source(app_module, tmp_path)
    for canvas, usr, expected in ((app.class_view, "u:A", "3.0"), (app.call_view, "u:A:f", "5.0")):
        canvas.dragged = False
        monkeypatch.setattr(canvas, "node_at", lambda x, y, usr=usr: usr)
        monkeypatch.setattr(canvas, "toggle_expansion_at", lambda x, y: False)
        canvas.on_release(SimpleNamespace(x=1, y=2, num=1))
        assert app.source_editor.text.index("insert") == expected
    app.source_editor.text.insert("end", "// edit")
    app.call_view.on_release(SimpleNamespace(x=1, y=2, num=1))
    assert app.source_editor.dirty


def test_candidate_source_edits_never_touch_project_and_invalidate_gates(app_module, tmp_path):
    app = app_with_source(app_module, tmp_path)
    worktree = tmp_path / ".icoda/worktree"
    (worktree / "src").mkdir(parents=True)
    source = worktree / "src/a.cpp"
    source.write_text("// candidate\n")
    proposal = steps.Proposal(1, prompt.StepRequest(prompt.ARCHITECTURE, 1), worktree,
                              model=app.opened.model, build=steps.BuildResult(True), test=steps.TestResult(True))
    app.steps.proposal = proposal
    app.call_view.model = proposal.model
    app.open_call_source("src/a.cpp", 1)
    assert app.source_editor.document.root == worktree.resolve()
    app.source_editor.text.insert("end", "// edit\n")
    assert app.source_editor.save()
    assert "// edit" in source.read_text() and "// edit" not in (tmp_path / "src/a.cpp").read_text()
    assert proposal.build.ok is None and proposal.test.ok is None and not proposal.ok
    assert "Rebuild" in app.status.get()


def test_file_hierarchy_and_mind_map_nodes_open_source(app_module, tmp_path, monkeypatch):
    app = app_with_source(app_module, tmp_path)
    for canvas in (app.call_view, app.class_view):
        monkeypatch.setattr(canvas, "node_at", lambda x, y: "file:src/b.cpp")
        monkeypatch.setattr(canvas, "toggle_expansion_at", lambda x, y: False)
        canvas.on_release(SimpleNamespace(x=1, y=2, num=1))
        assert app.source_editor.document.relative == "src/b.cpp"
    app.mind_map_view.activate_node("file:src/a.cpp")
    assert app.source_editor.document.relative == "src/a.cpp" and app.source_editor.text.index("insert") == "1.0"
    app.mind_map_view.activate_node("entity:u:A:f")
    assert app.source_editor.text.index("insert") == "5.0"


def test_cancel_preserves_buffer_on_project_switch_close_and_step(app_module, tmp_path, monkeypatch):
    app = app_with_source(app_module, tmp_path)
    app.open_editor("src/a.cpp")
    app.source_editor.text.insert("end", "pending edits")
    monkeypatch.setattr(source_editor.messagebox, "askyesnocancel", lambda *a, **k: None)
    actions = []
    monkeypatch.setattr(app.root, "destroy", lambda: actions.append("closed"))
    app.close()
    app.open_project(tmp_path / "other")
    app.new_project(tmp_path / "other")
    app.steps.run(lambda: actions.append("ran"), lambda value: None)
    assert not actions and app.project == tmp_path
    assert app.source_editor.dirty and not (tmp_path / "other").exists()
