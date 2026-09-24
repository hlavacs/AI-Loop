"""The window against the Tk stub: showing an opened project, describing and selecting nodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from icoda_core import clusters, persistence, session, specification, views
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
    assert app.coverage_view.summary_var.get() == \
        "Recorded test reachability: 0/2 analysed callables reached · 2 not reached"
    assert app.issue_view.issues and "issues" in app.issue_view.summary_var.get()
    assert app.panel.phase_var.get() == "implementation"
    assert app.panel.queue_var.get() == "Implementation queue: empty — no unimplemented functions"
    assert config_path.is_file()


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
    monkeypatch.setattr(app_module.threading, "Thread", ImmediateThread)
    app = app_module.App(
        app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "config.json")

    attempts = []
    def repair():
        attempts.append(True)
        return ValueError("The persisted state is truncated; original bytes preserved.")
    monkeypatch.setattr(app, "_recover_analysis", repair)
    app.run_async = lambda work, done: done(work())
    app.open_project(project)
    app._poll()

    message = (f"cannot open project: {store.state_path} contains invalid JSON; refusing to replace the persisted "
               f"state with defaults; leftover proposal worktree preserved at {worktree}")
    assert attempts == [True]
    assert "Prompt" in app.status.get()
    assert message in app.recovery.issue.detail
    assert store.state_path.read_bytes() == truncated_state
    assert (worktree / "unfinished.py").is_file()


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


def test_describe_and_select_nodes(app_module, tmp_path: Path, monkeypatch) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened_project(tmp_path))
    assert "2 entities" in app.describe_node("src/a.cpp")
    assert "errors: expected" in app.describe_node("src/b.cpp")
    assert app.describe_node("external:std").startswith("std\nprintf")
    assert app.describe_node("file:src/a.cpp") == app.describe_node("src/a.cpp")
    entity = app.displayed.model.entities["u:A:f"]
    entity.brief, entity.satisfies, entity.test_files = "Updates the object.", ("R-1",), ("tests/a.cpp",)
    entity.declaration_file = "include/a.hpp"
    description = app.describe_node("entity:u:A:f")
    assert description == app.describe_node("u:A:f")
    for expected in ("Method: A::f", "void f()", "src/a.cpp:5", "include/a.hpp", "Status: implemented",
                     "Purpose: Updates the object.", "Requirements: R-1", "Tests: tests/a.cpp"):
        assert expected in description
    assert description.count("Updates the object.") == 1
    entity.brief += " Keeps existing values intact."
    assert "Purpose: Updates the object.\n" in app.describe_node(entity.usr)
    assert entity.brief in app.describe_node(entity.usr)
    assert "Class: A" in app.describe_node("u:A")
    assert "Function: g" in app.describe_node("u:g")
    assert "Cluster:" in app.describe_node("cluster:" + app.displayed.clustering.clusters[0].id)
    assert "External symbol: printf" in app.describe_node("external-symbol:std:0")
    assert app.describe_node("external-symbol:missing:0") == app.describe_node("unknown") == ""
    candidate = DerivedModel.from_json(app.displayed.model.to_json())
    candidate.entities["u:A:f"].signature = "void f(int value)"
    candidate.entities["u:A:f"].brief = "Updates only the supplied value."
    candidate.add_entity(Entity("u:new", Kind.FUNCTION, "new_api", "new_api", "new.cpp", 7))
    assert "void f(int value)" in app.describe_node("u:A:f", candidate)
    assert "Purpose: Updates only the supplied value." in app.describe_node("u:A:f", candidate)
    assert "Function: new_api" in app.describe_node("u:new", candidate)
    assert "void f()" in app.describe_node("u:A:f") and not app.describe_node("u:new")
    labels: dict[str, str] = {}
    monkeypatch.setattr(app.tree, "insert", lambda *args, **kwargs: labels.update({kwargs["iid"]: kwargs["text"]}))
    app.select_node("src/a.cpp")
    assert app.side_title.get() == "src/a.cpp"
    assert labels == {"u:A": "A", "u:A:f": "auto f() -> void"}
    app.select_node("external:std")
    assert app.side_title.get() == "src/a.cpp"


def test_zoom_keeps_the_point_under_the_cursor(app_module, tmp_path: Path) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened_project(tmp_path))
    view = app.view

    class Wheel:
        x, y, delta, num = 300, 200, 120, 0
        state = 0x0004  # Ctrl+wheel zooms; ordinary scrolling pans.

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


def test_organise_button_keeps_clusters_after_fit_and_resize(app_module, tmp_path: Path, monkeypatch) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    opened = opened_project(tmp_path)
    opened.clustering = clusters.Clustering([
        clusters.Cluster("a", "A", ["src/a.cpp"]), clusters.Cluster("b", "B", ["src/b.cpp"])])
    opened.layout = views.layout_file_view(opened.model, opened.clustering)
    view = app.view
    view.show(opened.layout)
    monkeypatch.setattr(app, "run_async", lambda work, done: done(work()))
    monkeypatch.setattr(view, "_boxes_overlap", lambda: True)
    view.organise_button.kwargs["command"]()
    organised = view.layout
    assert view.organised and not view.compact and organised is not opened.layout
    assert organised.circles and organised.cluster_arrows
    view.fit()
    view.on_resize(None)
    assert view.layout is organised and not view.compact
    monkeypatch.setattr(view, "_boxes_overlap", lambda: False)
    view.show(opened.layout)
    assert not view.organised and view.layout is opened.layout


def test_organise_ignores_result_after_project_changes(app_module, tmp_path: Path, monkeypatch) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    pending = []
    monkeypatch.setattr(app, "run_async", lambda work, done: pending.append((work, done)))
    view = app.view
    view.show(opened_project(tmp_path).layout)
    view.organise()
    replacement = opened_project(tmp_path).layout
    view.show(replacement)
    work, done = pending.pop()
    done(work())
    assert view.layout is replacement and not view.organised


@pytest.mark.parametrize("group_count", [4, 12])
def test_crowded_file_view_starts_with_clusters_before_organising(
        app_module, tmp_path: Path, monkeypatch, group_count: int) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    model = DerivedModel(str(tmp_path))
    grouping = clusters.Clustering([])
    for group in range(group_count):
        files = [f"group{group}/file{i}.cpp" for i in range(16)]
        model.files.update({file: FileInfo(file, unit="source") for file in files})
        grouping.clusters.append(clusters.Cluster(str(group), f"Group {group}", files))
    layout = views.layout_file_view(model, grouping)
    view = app.view

    def graph_bounds(tag):
        boxes = list(view.node_boxes.values())
        if tag == "file-graph" and boxes:
            return (min(box[0] for box in boxes), min(box[1] for box in boxes),
                    max(box[2] for box in boxes), max(box[3] for box in boxes))
        return None

    monkeypatch.setattr(view.canvas, "bbox", graph_bounds)
    view.show(layout)
    for action in (view.redraw, view.fit, lambda: view.on_resize(None)):
        action()
        assert view.overview and not view.organised and not view.compact, (view.scale, view.compact)
        assert view.layout is layout
        assert set(view._draw_layout.nodes) == {f"cluster:{group}" for group in range(group_count)}
        assert all(node.kind == "cluster" for node in view._draw_layout.nodes.values())
        assert all(node.label.endswith("16 files") for node in view._draw_layout.nodes.values())

    view.open_group("cluster:0")
    assert not view.overview and set(view.layout.nodes) == set(grouping.clusters[0].files)
    view.fit()
    assert view.focused_group == "cluster:0" and not view.overview
    view.back_to_overview()
    assert view.overview and view.layout is layout
    view.show(opened_project(tmp_path).layout)
    assert not view.overview and view.focused_group is None


@pytest.mark.parametrize("organised", [False, True])
@pytest.mark.parametrize("entry", ["zoom", "double_click"])
def test_opened_group_stays_active_until_explicit_return_to_overview(
        app_module, tmp_path: Path, monkeypatch, entry: str, organised: bool) -> None:
    from types import SimpleNamespace

    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    view = app.view
    view.show(opened_project(tmp_path).layout)
    complete_layout = view.layout
    view.organised, view.overview = organised, True
    view.scale, view.fit_scale = .5, .2
    view.offset, view.user_zoomed = (31.0, 47.0), True
    view.redraw()
    view.zoom(1.1)
    assert view.overview and view.focused_group is None
    parent_viewport = (view.scale, view.offset, view.fit_scale, view.user_zoomed)
    assert set(view._draw_layout.nodes) == {"cluster:src", "external:std"}
    if entry == "zoom":
        node = view._draw_layout.nodes["cluster:src"]
        view.zoom(2.0, view.to_screen(node.x, node.y))
    else:
        monkeypatch.setattr(view, "node_at", lambda *_: "cluster:src")
        view.on_double_click(SimpleNamespace(x=0, y=0))
    assert view.focused_group == "cluster:src" and not view.overview
    assert set(view.layout.nodes) == {"src/a.cpp", "src/b.cpp"}
    assert view._original_layout is complete_layout
    view.zoom(.05)
    assert view.scale < 1.0 and not view.overview
    before = view.offset
    view.on_press(SimpleNamespace(x=20, y=30))
    view.on_drag(SimpleNamespace(x=70, y=45))
    view.on_release(SimpleNamespace(x=70, y=45, num=1))
    assert view.offset == (before[0] + 50, before[1] + 15)
    view.on_resize(None)
    monkeypatch.setattr(view, "_fit_graph", lambda *_: setattr(view, "scale", .4))
    view.fit()
    view.on_resize(None)
    view.reset_zoom()
    assert view.focused_group == "cluster:src" and not view.overview
    assert set(view._draw_layout.nodes) == {"src/a.cpp", "src/b.cpp"}
    view.overview_button.kwargs["command"]()
    assert view.focused_group is None and view.overview and view.layout is complete_layout
    assert (view.scale, view.offset, view.fit_scale, view.user_zoomed) == parent_viewport
    assert set(view._draw_layout.nodes) == {"cluster:src", "external:std"}


def test_organising_inside_a_group_stays_inside_and_new_graph_clears_the_group(
        app_module, tmp_path: Path, monkeypatch) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    view = app.view
    view.show(opened_project(tmp_path).layout)
    view.organised, view.overview = True, True
    view.open_group("cluster:src")
    monkeypatch.setattr(app, "run_async", lambda work, done: done(work()))
    view.organise()
    assert view.focused_group == "cluster:src" and not view.overview
    assert set(view.layout.nodes) == {"src/a.cpp", "src/b.cpp"}
    view.show(views.FileViewLayout([], {}, [], [], 1, 1))
    assert view.focused_group is None and view._overview_viewport is None
    view.back_to_overview()
    assert not view.layout.nodes


def test_overview_refreshes_when_the_file_filter_changes(app_module, tmp_path: Path, monkeypatch) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    view = app.view
    view.show(opened_project(tmp_path).layout)
    view.organised, view.overview = True, True
    view.scale = .5
    view.redraw()
    assert "cluster:src" in view._draw_layout.nodes
    monkeypatch.setattr(view, "node_visible", lambda key: key == "src/a.cpp")
    view.redraw()
    assert set(view._draw_layout.nodes) == {"src/a.cpp"} and not view._draw_layout.file_arrows


def test_crowded_file_view_highlights_only_the_hovered_files_connections(
        app_module, tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    view = app.view
    nodes = {str(i): views.Node(str(i), str(i), i * 150, 100, "") for i in range(31)}
    edges = [views.Arrow("0", "1", {EdgeKind.CALLS: 1}), views.Arrow("2", "3", {EdgeKind.CALLS: 1})]
    view.layout = views.FileViewLayout([], nodes, edges, [], 5000, 400)
    view.organised = True
    lines = []
    monkeypatch.setattr(view.canvas, "create_line", lambda *args, **kwargs: lines.append(kwargs))
    view.redraw()
    assert len(lines) == 2 and all(line["fill"] == "#e2e8f0" for line in lines)
    lines.clear()
    monkeypatch.setattr(view, "node_at", lambda *_: "0")
    view._focus_file_edges(SimpleNamespace(x=0, y=0))
    assert view.edge_focus == "0" and len(lines) == 1
    assert lines[0]["fill"] == views.ARROW_COLOURS[EdgeKind.CALLS]
    assert len(view.node_boxes) == 31


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


def test_build_menu_runs_the_build_gate_and_reloads_or_reports(app_module, tmp_path: Path, monkeypatch) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    opened: list[Path] = []
    app.open_project = opened.append
    app.run_async = lambda work, done: done(work())
    app.project = tmp_path
    persistence.ProjectStore(tmp_path).save_state(
        persistence.ProjectState(phase=persistence.ProjectPhase.ARCHITECTURE))
    results = [app_module.steps.BuildResult(True, "ok"), app_module.steps.BuildResult(False, "error: boom")]
    monkeypatch.setattr(app_module.steps, "build_project", lambda root: results.pop(0))
    repairs = []
    runner = app.steps._ensure_runner()
    def repair(error):
        repairs.append(error)
        return ValueError("No isolated repair available")
    monkeypatch.setattr(runner, "repair_project", repair)

    app.build_project()
    assert opened == [tmp_path] and app.status.get().startswith("build passed") and not app.panel.busy
    app.build_project()
    assert opened == [tmp_path] and "Prompt" in app.status.get()
    assert repairs == ["error: boom"]
    assert "boom" in app.recovery.issue.detail
    log = persistence.ProjectStore(tmp_path).dir / "icoda.log"
    assert "build passed (Project ▸ Build)" in log.read_text(encoding="utf-8")
    app.project = None
    app.build_project()  # without a project: an information box, nothing else
    assert opened == [tmp_path]


def test_existing_project_build_failure_investigates_without_architecture_repair(
        app_module, tmp_path: Path, monkeypatch) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.project = tmp_path
    persistence.ProjectStore(tmp_path).save_state(
        persistence.ProjectState(phase=persistence.ProjectPhase.IMPLEMENTATION))
    app.run_async = lambda work, done: done(work())
    monkeypatch.setattr(app_module.steps, "build_project", lambda root: app_module.steps.BuildResult(False, "boom"))
    failures = []
    monkeypatch.setattr(app.recovery, "handle_failure", lambda error, **options: failures.append((error, options)))
    app.build_project()
    assert failures[0][0] == "Build failed.\nboom"
    assert failures[0][1] == {"retry": app.build_project}
    assert not app.panel.busy


def test_test_command_menu_edits_the_project_state(app_module, tmp_path: Path, monkeypatch) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.project = tmp_path
    store = persistence.ProjectStore(tmp_path)
    store.ensure()
    asked: list[dict[str, object]] = []

    def askstring(title: str, prompt: str, **kwargs: object) -> str:
        asked.append({"title": title, **kwargs})
        return "ctest --preset debug --output-on-failure"

    monkeypatch.setattr(app_module.simpledialog, "askstring", askstring)
    app.edit_test_command()
    assert store.load_state().test_command == ("ctest", "--preset", "debug", "--output-on-failure")
    assert asked[0]["title"] == "Test command" and "initialvalue" in asked[0]
    assert app.status.get() == "test command set to: ctest --preset debug --output-on-failure"
    monkeypatch.setattr(app_module.simpledialog, "askstring", lambda *args, **kwargs: None)
    app.edit_test_command()
    assert store.load_state().test_command == ("ctest", "--preset", "debug", "--output-on-failure")


def test_libclang_apply_reloads_an_open_project_instead_of_asking_for_a_restart(app_module, tmp_path: Path,
                                                                                  monkeypatch) -> None:
    detected = [app_module.toolchain.Candidate("/llvm/one/libclang.so", "linux")]
    monkeypatch.setattr(app_module.toolchain, "candidates", lambda: detected)
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    reloads: list[int] = []
    app.reload = lambda: reloads.append(1)
    app.libclang_choice_var.set(detected[0].path)
    app.apply_libclang_choice()
    assert reloads == [] and "next reload" in app.status.get()
    app.show(opened_project(tmp_path))
    app.apply_libclang_choice()
    assert reloads == [1] and "Reloading the project" in app.status.get()
    assert "Restart" not in app.status.get()


def test_help_menu_opens_documents_and_the_log(app_module, tmp_path: Path, monkeypatch) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    opened: list[Path] = []
    monkeypatch.setattr(app_module.session, "open_with_system", lambda path: opened.append(path) or True)
    for _label, relative in app_module.DOCUMENTS:
        assert (app_module.DOCS_ROOT / relative).is_file(), relative
    app.open_document("docs/GETTING_STARTED.md")
    assert opened[-1].name == "GETTING_STARTED.md"
    app.open_document("docs/MISSING.md")
    assert "not part of this installation" in app.status.get()
    assert app.log_path() == (tmp_path / "icoda.log")  # beside the settings while no project is open
    app.open_log_file()
    assert "no log file yet" in app.status.get()
    app.project = tmp_path
    store = persistence.ProjectStore(tmp_path)
    store.ensure()
    session.log_event("hello", tmp_path)
    app.open_log_file()
    assert opened[-1] == store.dir / "icoda.log"


def test_analysis_progress_keeps_the_panel_busy_until_the_result_arrives(app_module, tmp_path: Path,
                                                                          monkeypatch) -> None:
    started: list[Any] = []

    class LazyThread:
        def __init__(self, target, args, daemon) -> None:
            del daemon
            self.target, self.args = target, args

        def start(self) -> None:
            started.append(self)

    monkeypatch.setattr(app_module.threading, "Thread", LazyThread)
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    monkeypatch.setattr(app_module.session, "open_project", lambda root, config: opened_project(root))
    persistence.ProjectStore(tmp_path).ensure()
    app.open_project(tmp_path)
    app.open_project(tmp_path)  # a second reload while the first analysis is still running
    assert app.panel.busy and app.panel.activity_var.get() == "analysing the project" and app._pending_analyses == 2
    assert "Working: analysing the project." == app.panel.hint_var.get()
    for thread in started:
        thread.target(*thread.args)
    app._poll()
    assert app.panel.busy and app._pending_analyses == 1  # one result is still to come
    app._poll()
    assert not app.panel.busy and app._pending_analyses == 0 and app.opened is not None
    assert app.panel.project_open and app.panel.has_model


def test_a_reload_during_a_step_keeps_the_step_busy_state(app_module, tmp_path: Path, monkeypatch) -> None:
    started: list[Any] = []

    class LazyThread:
        def __init__(self, target, args, daemon) -> None:
            del daemon
            self.target, self.args = target, args

        def start(self) -> None:
            started.append(self)

    monkeypatch.setattr(app_module.threading, "Thread", LazyThread)
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    monkeypatch.setattr(app_module.session, "open_project", lambda root, config: opened_project(root))
    persistence.ProjectStore(tmp_path).ensure()
    app.panel.set_busy(True, "asking the agent for the next step", cancellable=True)
    app.open_project(tmp_path)
    assert app.panel.activity_var.get() == "asking the agent for the next step" and app.panel.cancellable
    started[-1].target(*started[-1].args)
    app._poll()
    assert app.panel.busy  # the step is still running; only the step's end frees the buttons
    app.panel.set_busy(False)
    app._source_snapshot = ()
    app._refresh_external_edits(None)  # not busy: a focus refresh may reload
    assert app._pending_analyses == 1


def test_reload_button_refreshes_external_source_but_keeps_unsaved_edits(app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    source = tmp_path / "main.cpp"
    source.write_text("int main() { return 0; }\n")
    app.project = tmp_path
    assert app.source_editor.open_file(tmp_path, "main.cpp")
    opened = []
    monkeypatch.setattr(app, "open_project", opened.append)
    reload = app.reload_button.kwargs["command"]
    source.write_text("int main() { return 1; }\n")
    reload()
    assert opened == [tmp_path] and "return 1;" in app.source_editor.content()
    app.source_editor.text.insert("end", "// unsaved\n")
    source.write_text("int main() { return 2; }\n")
    reload()
    assert len(opened) == 2 and "unsaved" in app.source_editor.content()
    assert app.source_editor.dirty and "return 2;" in source.read_text()
    app.panel.set_busy(True, "building")
    reload()
    assert len(opened) == 2
    app.panel.set_busy(False)
    app.project = None
    reload()
    assert len(opened) == 2


def test_reread_specification_refreshes_editor_and_coverage_without_writing(app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened_project(tmp_path))
    path = persistence.ProjectStore(tmp_path).specification_path
    original = specification.default_specification("Original")
    specification.save(path, original)
    app.edit_specification()
    editor = app.spec_editor
    editor.show_page("scope")
    app.edit_specification()
    assert app.spec_editor is editor
    (tmp_path / "main.cpp").write_text("int main() {}\n")
    app.source_editor.open_file(tmp_path, "main.cpp")
    app.source_editor.text.insert("end", "// unsaved source\n")
    draft = app.source_editor.content()
    updated = specification.default_specification("External")
    updated["goals"] = ["New goal"]
    updated["code_profile"]["build"] = "External build settings"
    specification.save(path, updated)
    saved_bytes = path.read_bytes()
    monkeypatch.setattr(app, "open_project", lambda *_: pytest.fail("Reread must not reanalyse code"))
    app.reread_spec_button.kwargs["command"]()
    assert app.spec_editor is editor and editor.to_specification() == updated
    assert not editor.changed() and editor.current_page == "scope"
    assert len(app.coverage_view.requirements) == 1
    assert path.read_bytes() == saved_bytes
    assert app.source_editor.content() == draft and app.source_editor.dirty
    editor.close()
    app.reread_specification()
    assert app.spec_editor is not editor and app.spec_editor.to_specification() == updated


def test_reread_specification_preserves_dirty_edits_until_confirmed(app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.project = tmp_path
    path = persistence.ProjectStore(tmp_path).specification_path
    specification.save(path, specification.default_specification("Original"))
    app.edit_specification()
    editor = app.spec_editor
    editor.overview.vars["title"].set("Unsaved")
    specification.save(path, specification.default_specification("External"))
    monkeypatch.setattr(app_module.spec_editor.messagebox, "askyesno", lambda *a, **kw: False)
    editor.reread_button.kwargs["command"]()
    assert editor.to_specification()["title"] == "Unsaved" and editor.changed()
    assert specification.load(path)["title"] == "External"
    monkeypatch.setattr(app_module.spec_editor.messagebox, "askyesno", lambda *a, **kw: True)
    editor.reread_button.kwargs["command"]()
    assert editor.to_specification()["title"] == "External" and not editor.changed()


@pytest.mark.parametrize("contents", [None, '{"title":', '{"title": ""}', '{"requirements": [7]}'])
def test_reread_failure_retries_before_prompt_and_preserves_edits(
        app_module, tmp_path, monkeypatch, contents):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.project = tmp_path
    app.edit_specification()
    app.spec_editor.overview.vars["title"].set("Unsaved")
    path = persistence.ProjectStore(tmp_path).specification_path
    path.parent.mkdir(exist_ok=True)
    if contents is not None:
        path.write_text(contents)
    calls = []
    original_load = specification.load

    def read(path):
        calls.append(path)
        return original_load(path)

    def run(work, done):
        try:
            result = work()
        except ValueError as exc:
            result = exc
        done(result)

    monkeypatch.setattr(specification, "load", read)
    app.run_async = run
    app.reread_specification()
    assert calls == [path, path]
    assert "Prompt" in app.status.get() and "specification" in app.recovery.issue.detail
    assert app.spec_editor.to_specification()["title"] == "Unsaved" and app.spec_editor.changed()
    assert path.read_text() == contents if contents is not None else not path.exists()


def test_reread_recovers_an_interrupted_external_write(app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.project = tmp_path
    calls = []

    def read(path):
        calls.append(path)
        if len(calls) == 1:
            raise ValueError("external writer has not finished")
        return specification.default_specification("Recovered")

    monkeypatch.setattr(specification, "load", read)
    app.run_async = lambda work, done: done(work())
    app.reread_specification()
    assert len(calls) == 2 and app.spec_editor.to_specification()["title"] == "Recovered"
    assert app.status.get().startswith("Specification reread") and not app.panel.busy


def test_reread_guards_busy_missing_and_changed_project(app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.reread_specification()
    assert app.spec_editor is None
    app.project = tmp_path
    app.edit_specification()
    editor = app.spec_editor
    monkeypatch.setattr(specification, "load", lambda *_: pytest.fail("Must not read while unavailable"))
    app.panel.set_busy(True, "building")
    editor.reread_button.kwargs["command"]()
    app.panel.set_busy(False)
    app.project = tmp_path / "another"
    editor.reread_button.kwargs["command"]()
    assert app.spec_editor is editor
    with pytest.raises(ValueError, match="Open .* again"):
        editor.save()
    app.edit_specification()
    assert app.spec_editor is not editor
    app.project = tmp_path
    app.edit_specification()
    assert app.spec_editor is editor
