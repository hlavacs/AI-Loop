"""The window against the Tk stub: showing an opened project, describing and selecting nodes."""

from __future__ import annotations

from pathlib import Path

from icoda_core import clusters, persistence, session, steplog, views
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind, merge_external_names


def opened_project(tmp_path: Path) -> session.OpenedProject:
    model = DerivedModel(str(tmp_path))
    for f in ("src/a.cpp", "src/b.cpp"):
        model.files[f] = FileInfo(f, unit="source")
    model.files["src/b.cpp"].errors = ("expected ';'",)
    model.add_entity(Entity("u:A", Kind.CLASS, "A", "A", "src/a.cpp", 3))
    model.add_entity(Entity("u:A:f", Kind.METHOD, "f", "A::f", "src/a.cpp", 5, parent="u:A", signature="void f()"))
    model.add_entity(Entity("u:g", Kind.FUNCTION, "g", "g", "src/b.cpp", 1))
    model.add_edge(Edge(EdgeKind.CALLS, "u:g", "u:A:f", "src/b.cpp", 2))
    model.add_edge(Edge(EdgeKind.CALLS, "u:g", "external:std", "src/b.cpp", 3, "printf"))
    merge_external_names(model, "std", ["printf"])
    clustering = clusters.cluster_files(model)
    return session.OpenedProject(tmp_path, model, clustering, views.layout_file_view(model, clustering), None,
                                 ["no libclang found"])


def test_show_updates_status_config_and_canvas(app_module, tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    persistence.ProjectStore(tmp_path).save_state(
        persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION))
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=config_path)
    app.show(opened_project(tmp_path))
    assert "2 files" in app.status.get() and "libclang: none found" in app.status.get()
    assert "no libclang found" in app.status.get()
    assert app.view.layout is not None and "src/a.cpp" in app.view.layout.nodes
    assert app.class_view.layout is not None and set(app.class_view.layout.nodes) == {"u:A"}
    assert app.mind_map_view.layout is not None
    assert {item.node.id for item in app.mind_map_view.layout.nodes} == {"cluster:src"}
    assert app.coverage_view.summary_var.get() == "Test coverage: 0/2 callables covered · 2 uncovered"
    assert app.issue_view.issues and "issues" in app.issue_view.summary_var.get()
    assert app.panel.phase_var.get() == "implementation"
    assert app.panel.queue_var.get() == "Implementation queue: empty — no unimplemented functions"
    assert config_path.is_file()


<<<<<<< HEAD
def test_show_restores_the_persisted_phase(app_module, tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.ensure()
    steplog.StepLog(store.steps_path).append(steplog.StepRecord(1, "implementation", "phase"))
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened_project(tmp_path))
    assert app.panel.phase_var.get() == "implementation"


=======
def test_open_project_reports_truncated_state_without_tk_traceback(app_module, tmp_path: Path, monkeypatch) -> None:
    class ImmediateThread:
        def __init__(self, target, args, daemon) -> None:
            del daemon
            self.target, self.args = target, args

        def start(self) -> None:
            self.target(*self.args)

    project = tmp_path / "interrupted"
    store = persistence.ProjectStore(project)
    store.ensure()
    truncated_state = store.state_path.read_bytes()[:-7]
    store.state_path.write_bytes(truncated_state)
    worktree = store.dir / "worktree"
    worktree.mkdir()
    (worktree / "unfinished.py").write_text("proposal = 'not promoted'\n", encoding="utf-8")
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(app_module.dialogs, "show_error", lambda title, text: shown.append((title, text)))
    monkeypatch.setattr(app_module.threading, "Thread", ImmediateThread)
    app = app_module.App(
        app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "config.json")

    app.open_project(project)
    app._poll()

    message = (f"cannot open project: {store.state_path} contains invalid JSON; refusing to replace the persisted "
               f"state with defaults; leftover proposal worktree preserved at {worktree}")
    assert message in app.status.get()
    assert shown == [("ICODA", f"ProjectStateError('{message}')\n\nDetails: {store.dir / 'icoda.log'}")]


def test_open_project_shows_persisted_phase_after_analysis(app_module, tmp_path: Path, monkeypatch) -> None:
    class ImmediateThread:
        def __init__(self, target, args, daemon) -> None:
            del daemon
            self.target, self.args = target, args

        def start(self) -> None:
            self.target(*self.args)

    project = tmp_path / "implementation"
    project.mkdir()
    persistence.ProjectStore(project).save_state(
        persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION))
    monkeypatch.setattr(app_module.session, "open_project", lambda root, config: opened_project(root))
    monkeypatch.setattr(app_module.threading, "Thread", ImmediateThread)
    app = app_module.App(
        app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "config.json")

    app.open_project(project)
    app._poll()

    assert app.panel.phase_var.get() == "implementation"


def test_view_notebook_registers_mind_map_beside_existing_m4_tabs(app_module, tmp_path: Path, monkeypatch) -> None:
    labels: list[str] = []

    def record_add(widget, child, **options):
        if "text" in options:
            labels.append(str(options["text"]))

    monkeypatch.setattr(app_module.ttk.Notebook, "add", record_add, raising=False)
    app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    assert labels[:6] == ["File View", "Call View", "Class View", "Mind Map", "Coverage", "Issues"]


>>>>>>> main
def test_describe_and_select_nodes(app_module, tmp_path: Path) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened_project(tmp_path))
    assert "2 entities" in app.describe_node("src/a.cpp")
    assert "errors: expected" in app.describe_node("src/b.cpp")
    assert app.describe_node("external:std").startswith("std\nprintf")
    app.select_node("src/a.cpp")
    assert app.side_title.get() == "src/a.cpp"
    app.select_node("external:std")
    assert app.side_title.get() == "src/a.cpp"


def test_zoom_keeps_the_point_under_the_cursor(app_module, tmp_path: Path) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened_project(tmp_path))
    view = app.view

    class Wheel:
        x, y, delta, num = 300, 200, 120, 0

    before = ((300 - view.offset[0]) / view.scale, (200 - view.offset[1]) / view.scale)
    assert view.on_wheel(Wheel()) == "break"
    after = ((300 - view.offset[0]) / view.scale, (200 - view.offset[1]) / view.scale)
    assert abs(before[0] - after[0]) < 1e-6 and abs(before[1] - after[1]) < 1e-6 and view.scale > view.fit_scale
    assert set(view.zoom_control_widgets) == {"zoom-out", "fit", "reset", "zoom-in"}
    view.reset_zoom()
    assert abs(view.scale - max(view.fit_scale, 1.0)) < 1e-6
    view.fit()
    view.zoom(0.8)
    assert abs(view.scale - view.fit_scale) < 1e-6


def test_dragging_moves_file_view_without_selecting_a_node(app_module, tmp_path: Path, monkeypatch) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened_project(tmp_path))
    view = app.view
    selected: list[str] = []
    monkeypatch.setattr(app, "select_node", selected.append)
    monkeypatch.setattr(view, "node_at", lambda _x, _y: "src/a.cpp")

    class Pointer:
        def __init__(self, x: int, y: int, num: int = 1) -> None:
            self.x, self.y, self.num = x, y, num

    before = view.offset
    view.on_press(Pointer(100, 100))
    view.on_drag(Pointer(125, 115))
    view.on_release(Pointer(125, 115))
    assert view.offset == (before[0] + 25, before[1] + 15) and view.dragged and selected == []
    view.on_press(Pointer(125, 115))
    view.on_release(Pointer(125, 115))
    assert selected == ["src/a.cpp"]
    view.on_press(Pointer(125, 115, 2))
    view.on_release(Pointer(125, 115, 2))
    assert selected == ["src/a.cpp"]


def test_new_project_writes_specification_and_skeleton_on_save(app_module, tmp_path: Path) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    opened: list[Path] = []
    app.open_project = opened.append
    project = tmp_path / "fresh"
    app.new_project(project)
    assert app.spec_editor is not None and (project / ".icoda").is_dir()
    assert app.spec_editor.to_specification()["title"] == "fresh"
    app.spec_editor.scope.texts["goals"].insert("1.0", "ship it")
    assert app.spec_editor.save()
    assert (project / ".icoda" / "specification.json").is_file() and (project / "CMakeLists.txt").is_file()
    assert (project / "src" / "app" / "app.cppm").is_file() and opened == [project]
    store = persistence.ProjectStore(project)
    assert store.load_state().phase == persistence.ProjectPhase.ARCHITECTURE
    app.spec_editor.scope.texts["goals"].insert("1.0", "twice\n")
    assert app.spec_editor.save() and opened == [project]  # the skeleton is written once
    app.edit_specification()
    assert app.spec_editor.to_specification()["goals"] == ["twice", "ship it"]


def test_save_specification_publishes_architecture_phase_before_reload(app_module, tmp_path: Path) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    project = tmp_path / "fresh"
    app.new_project(project)
    assert app.spec_editor is not None
    opened: list[Path] = []
    app.open_project = opened.append

    app._save_specification(app.spec_editor.to_specification())

    assert app.panel.phase_var.get() == "architecture"
    assert opened == [project]


def test_provider_selection_is_saved_per_project_and_as_default(app_module, tmp_path: Path) -> None:
    config_path = tmp_path / "c.json"
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=config_path)
    app.show(opened_project(tmp_path))
    assert app.provider_field.selection().provider_id == "claude"
    app.provider_field.binary_var.set("/usr/local/bin/codex")
    app.provider_field.model_var.set("my-model")
    saved = persistence.ProjectStore(tmp_path).load_ui()["provider"]
    assert saved == {"provider": "codex", "binary": "/usr/local/bin/codex", "model": "my-model"}
    config = persistence.UserConfig.load(config_path)
    assert (config.provider, config.model) == ("codex", "my-model")
    again = app_module.App(app_module.tk.Tk(), config=config, config_path=config_path)
    assert again.provider_field.selection().binary == "codex"  # the default: the command, not the path
    again.show(opened_project(tmp_path))
    assert again.provider_field.selection().binary == "/usr/local/bin/codex"


def test_libclang_menu_applies_persists_and_displays_chosen_library(app_module, tmp_path: Path, monkeypatch) -> None:
    entries: list[dict[str, object]] = []

    class RecordingMenu:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_command(self, **kwargs) -> None:
            entries.append(kwargs)

        def add_cascade(self, **kwargs) -> None:
            pass

        def add_separator(self) -> None:
            pass

        def add_checkbutton(self, **kwargs) -> None:
            pass

        def delete(self, *args) -> None:
            pass

    detected = [app_module.toolchain.Candidate("/llvm/one/libclang.so", "linux"),
                app_module.toolchain.Candidate("/llvm/two/libclang.so", "wheel")]
    monkeypatch.setattr(app_module.tk, "Menu", RecordingMenu)
    monkeypatch.setattr(app_module.toolchain, "candidates", lambda: detected)
    config_path = tmp_path / "config.json"
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=config_path)
    menu_entry = next(entry for entry in entries if entry.get("label") == "Choose libclang Library…")

    menu_entry["command"]()
    assert app.libclang_choice_var.get() == detected[0].path
    assert "Active: /llvm/one/libclang.so" in app.libclang_result_var.get()
    app.libclang_choice_var.set(detected[1].path)
    app.apply_libclang_choice()

    assert app.config.preferred_libclang == detected[1].path
    assert persistence.UserConfig.load(config_path).preferred_libclang == detected[1].path
    assert "Active: /llvm/two/libclang.so" in app.libclang_result_var.get()
    assert "/llvm/two/libclang.so" in app.status.get()
