"""Shared right-click node actions and application dispatch through the Tk stub."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from icoda_core import implementation_queue, persistence, steplog, test_selection
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind
from icoda_gui import graph_canvas, step_controller


class RecordingMenu:
    """Small menu double that records the exact labels, states, and commands."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.items: list[dict[str, Any]] = []
        self.popup: tuple[int, int] | None = None

    def delete(self, *_args: Any) -> None:
        self.items.clear()

    def add_command(self, **kwargs: Any) -> None:
        self.items.append(kwargs)

    def add_separator(self) -> None:
        self.items.append({"separator": True})

    def add_cascade(self, **kwargs: Any) -> None:
        self.items.append(kwargs)

    def tk_popup(self, x: int, y: int) -> None:
        self.popup = (x, y)

    def grab_release(self) -> None:
        return None

    def invoke(self, label: str) -> None:
        item = next(item for item in self.items if item.get("label") == label)
        item["command"]()

    def submenu(self, label: str) -> RecordingMenu:
        item = next(item for item in self.items if item.get("label") == label)
        return cast(RecordingMenu, item["menu"])


class RecordingCanvas:
    def __init__(self) -> None:
        self.bindings: dict[str, Any] = {}

    def bind(self, event: str, handler: Any) -> None:
        self.bindings[event] = handler


def _event() -> Any:
    return SimpleNamespace(x=12, y=18, x_root=112, y_root=218)


def test_shared_menu_has_plan_actions_and_dispatches_derived_context(monkeypatch: Any) -> None:
    monkeypatch.setattr(graph_canvas.tk, "Menu", RecordingMenu)
    canvas = RecordingCanvas()
    dispatched: list[tuple[str, graph_canvas.NodeActionContext]] = []
    context = graph_canvas.NodeActionContext(
        "u:target", 7, ("tests/target_test.cpp",), "u:target", "u:target", True, True)
    actions = graph_canvas.NodeActionMenu(
        canvas, lambda _x, _y: "u:target", lambda _node: context,
        lambda action, value: dispatched.append((action, value)))

    assert "<Button-3>" in canvas.bindings and actions.open(_event()) == "break"
    menu = cast(RecordingMenu, actions.menu)
    assert [item.get("label") for item in menu.items if "label" in item] == [
        "Show introducing step", "Propose the next step here", "Implement this function",
        "Run the tests of changed functions",
    ]
    assert all(item["state"] == tk.NORMAL for item in menu.items if "label" in item)
    menu.invoke("Show introducing step")
    menu.invoke("Propose the next step here")
    menu.invoke("Implement this function")
    menu.invoke("Run the tests of changed functions")
    assert dispatched == [
        (graph_canvas.SHOW_STEP, context),
        (graph_canvas.PROPOSE_HERE, context),
        (graph_canvas.IMPLEMENT_HERE, context),
        (graph_canvas.RUN_TESTS, context),
    ]
    assert dispatched[-1][1].tests == ("tests/target_test.cpp",)


def test_unknown_step_no_tests_background_and_missing_project_are_inert(monkeypatch: Any) -> None:
    monkeypatch.setattr(graph_canvas.tk, "Menu", RecordingMenu)
    canvas = RecordingCanvas()
    dispatched: list[str] = []
    empty = graph_canvas.NodeActionContext("u:unknown")
    actions = graph_canvas.NodeActionMenu(
        canvas, lambda _x, _y: "u:unknown", lambda _node: empty,
        lambda action, _context: dispatched.append(action))
    actions.open(_event())
    menu = cast(RecordingMenu, actions.menu)
    states = {item["label"]: item["state"] for item in menu.items if "label" in item}
    assert states["Show introducing step"] == tk.DISABLED
    assert states["Propose the next step here"] == tk.DISABLED
    assert states["Implement this function"] == tk.DISABLED
    assert states["Run the tests of changed functions"] == tk.DISABLED
    menu.invoke("Show introducing step")
    menu.invoke("Propose the next step here")
    menu.invoke("Implement this function")
    menu.invoke("Run the tests of changed functions")
    assert dispatched == []

    background = graph_canvas.NodeActionMenu(canvas, lambda _x, _y: None, lambda _node: empty, None)
    assert background.open(_event()) == "break" and background.context is None
    no_project = graph_canvas.NodeActionMenu(canvas, lambda _x, _y: "u:x", lambda _node: None, None)
    assert no_project.open(_event()) == "break" and no_project.context is None

    busy = graph_canvas.NodeActionContext("u:busy", tests=("tests/busy_test.cpp",), can_run_tests=False)
    actions.resolve = lambda _node: busy
    actions.open(_event())
    test_item = next(item for item in menu.items
                     if item.get("label") == "Run the tests of changed functions")
    assert test_item["state"] == tk.DISABLED

    missing_payload = graph_canvas.NodeActionContext("u:missing", can_propose=True, can_implement=True)
    actions.resolve = lambda _node: missing_payload
    actions.open(_event())
    states = {item["label"]: item["state"] for item in menu.items if "label" in item}
    assert states["Propose the next step here"] == tk.DISABLED
    assert states["Implement this function"] == tk.DISABLED
    menu.invoke("Propose the next step here")
    menu.invoke("Implement this function")
    assert dispatched == []


def _covered_model(root: Path) -> DerivedModel:
    model = DerivedModel(str(root))
    model.files["src/widget.cpp"] = FileInfo("src/widget.cpp")
    model.files["tests/widget_test.cpp"] = FileInfo("tests/widget_test.cpp")
    model.add_entity(Entity("u:widget", Kind.CLASS, "Widget", "app::Widget", "src/widget.cpp", 3))
    model.add_entity(Entity("u:run", Kind.METHOD, "run", "app::Widget::run", "src/widget.cpp", 5,
                            parent="u:widget", status="stub"))
    model.add_entity(Entity("u:test", Kind.FUNCTION, "test_run", "test_run", "tests/widget_test.cpp", 2))
    model.add_edge(Edge(EdgeKind.CALLS, "u:test", "u:run", "tests/widget_test.cpp", 3))
    return model


def test_app_context_selects_introducing_step_and_dispatches_exact_core_tests(
        app_module: Any, tmp_path: Path, monkeypatch: Any) -> None:
    from test_app import opened_project

    opened = opened_project(tmp_path)
    opened.model = _covered_model(tmp_path)
    store = persistence.ProjectStore(tmp_path)
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION, ("u:run",), 0))
    record = steplog.StepRecord(
        7, "architecture", "approved", title="Introduce Widget", files=["src/widget.cpp"],
        entities_added=["u:widget", "u:run"], selected_tests=["tests/widget_test.cpp"], test_ok=True)
    steplog.StepLog(store.steps_path).append(record)
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened)

    context = app.graph_actions("u:run")
    assert context is not None and context.introducing_iteration == 7
    expected = test_selection.select_tests(opened.model, steplog.StepLog(store.steps_path), "u:run")
    assert context.tests == expected == ("tests/widget_test.cpp",)
    app.call_view.action_menu.menu = RecordingMenu()
    app.call_view.action_menu.hit_test = lambda _x, _y: "u:run"
    app.call_view.action_menu.open(_event())
    menu = cast(RecordingMenu, app.call_view.action_menu.menu)
    menu.invoke("Show introducing step")
    assert app.panel.selected_iteration == 7 and app.panel.title_var.get() == "Step 7: Introduce Widget"

    dispatched: list[tuple[Any, ...]] = []
    monkeypatch.setattr(app.steps, "action", lambda *args: dispatched.append(args))
    menu.invoke("Implement this function")
    menu.invoke("Run the tests of changed functions")
    assert context.target_usr == "u:run"
    assert dispatched == [("implement_here", "u:run"), ("run_tests", expected)]


def test_app_menu_proposes_with_the_node_usr_through_the_step_controller_path(
        app_module: Any, tmp_path: Path, monkeypatch: Any) -> None:
    from test_app import opened_project

    opened = opened_project(tmp_path)
    opened.model = _covered_model(tmp_path)
    persistence.ProjectStore(tmp_path).save_state(
        persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE))
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened)
    context = app.graph_actions("u:run")
    assert context is not None and context.focus == "u:run" and context.can_propose

    app.call_view.action_menu.menu = RecordingMenu()
    app.call_view.action_menu.hit_test = lambda _x, _y: "u:run"
    app.call_view.action_menu.open(_event())
    dispatched: list[tuple[Any, ...]] = []
    monkeypatch.setattr(app.steps, "action", lambda *args: dispatched.append(args))
    cast(RecordingMenu, app.call_view.action_menu.menu).invoke("Propose the next step here")

    assert dispatched == [("propose_here", "u:run")]


def test_app_menu_disables_step_actions_for_missing_payload_or_no_panel_action(
        app_module: Any, tmp_path: Path, monkeypatch: Any) -> None:
    from test_app import opened_project

    opened = opened_project(tmp_path)
    opened.model = _covered_model(tmp_path)
    persistence.ProjectStore(tmp_path).save_state(
        persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION, ("u:run",), 0))
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened)
    dispatched: list[tuple[Any, ...]] = []
    monkeypatch.setattr(app.steps, "action", lambda *args: dispatched.append(args))
    app.call_view.action_menu.menu = RecordingMenu()

    missing = graph_canvas.NodeActionContext("u:missing")
    app.call_view.action_menu.resolve = lambda _node: missing
    app.call_view.action_menu.hit_test = lambda _x, _y: "u:missing"
    app.call_view.action_menu.open(_event())
    menu = cast(RecordingMenu, app.call_view.action_menu.menu)
    states = {item["label"]: item["state"] for item in menu.items if "label" in item}
    assert states["Propose the next step here"] == states["Implement this function"] == tk.DISABLED
    menu.invoke("Propose the next step here")
    menu.invoke("Implement this function")

    app.call_view.action_menu.resolve = app.graph_actions
    app.panel.set_busy(True)
    assert not {"propose_approach", "propose"} & app.panel.enabled_actions
    app.call_view.action_menu.hit_test = lambda _x, _y: "u:run"
    app.call_view.action_menu.open(_event())
    states = {item["label"]: item["state"] for item in menu.items if "label" in item}
    assert states["Propose the next step here"] == states["Implement this function"] == tk.DISABLED
    menu.invoke("Propose the next step here")
    menu.invoke("Implement this function")
    assert dispatched == []


def test_app_context_is_safe_for_no_project_empty_model_and_empty_history(
        app_module: Any, tmp_path: Path) -> None:
    from test_app import opened_project

    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    assert app.graph_actions("u:any") is None
    opened = opened_project(tmp_path)
    opened.model = DerivedModel(str(tmp_path))
    app.show(opened)
    assert app.graph_actions("u:any") == graph_canvas.NodeActionContext("u:any")


def test_cluster_menu_pin_and_rename_entries_repaint_displayed_label(
        app_module: Any, tmp_path: Path, monkeypatch: Any) -> None:
    from test_app import opened_project

    app = app_module.App(
        app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened_project(tmp_path))
    context = app.graph_actions("cluster:src")
    assert context is not None and context.cluster_id == "src" and not context.cluster_pinned
    app.mind_map_view.action_menu.menu = RecordingMenu()
    app.mind_map_view.action_menu.hit_test = lambda _x, _y: "cluster:src"
    app.mind_map_view.action_menu.open(_event())
    menu = cast(RecordingMenu, app.mind_map_view.action_menu.menu)
    labels = [item.get("label") for item in menu.items if "label" in item]
    assert labels[-3:] == ["Pin cluster", "Unpin cluster", "Rename cluster…"]

    menu.invoke("Pin cluster")
    saved = persistence.ProjectStore(tmp_path).load_layout()
    assert saved.pins == {"src/a.cpp": "src", "src/b.cpp": "src"}
    rendered: list[str] = []
    monkeypatch.setattr(
        app.canvas, "create_text",
        lambda *_args, **kwargs: rendered.append(str(kwargs.get("text", ""))) or len(rendered))
    monkeypatch.setattr(app_module.simpledialog, "askstring", lambda *args, **kwargs: "Application Core")

    menu.invoke("Rename cluster…")

    assert persistence.ProjectStore(tmp_path).load_layout().names == {"src": "Application Core"}
    assert "Application Core" in rendered
    assert app.mind_map_view.tree is not None
    assert app.mind_map_view.tree.clusters[0].name == "Application Core"


def test_file_menu_cluster_picker_is_file_only_and_repaints_chosen_membership(
        app_module: Any, tmp_path: Path, monkeypatch: Any) -> None:
    from icoda_core import clusters, session, views

    model = DerivedModel(str(tmp_path))
    for file in ("app/selected.cpp", "app/peer.cpp", "tests/target.cpp"):
        model.files[file] = FileInfo(file)
    clustering = clusters.cluster_files(model)
    app = app_module.App(
        app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(session.OpenedProject(
        tmp_path, model, clustering, views.layout_file_view(model, clustering), None))
    monkeypatch.setattr(graph_canvas.tk, "Menu", RecordingMenu)
    app.view.action_menu.menu = RecordingMenu()

    app.view.action_menu.hit_test = lambda _x, _y: "file:app/selected.cpp"
    app.view.action_menu.open(_event())
    file_menu = cast(RecordingMenu, app.view.action_menu.menu)
    file_labels = [item.get("label") for item in file_menu.items if "label" in item]
    assert "Pin file to cluster" in file_labels
    picker = file_menu.submenu("Pin file to cluster")
    assert [item.get("label") for item in picker.items] == ["app", "tests"]

    app.view.action_menu.hit_test = lambda _x, _y: "cluster:app"
    app.view.action_menu.open(_event())
    cluster_labels = [item.get("label") for item in file_menu.items if "label" in item]
    assert "Pin file to cluster" not in cluster_labels

    app.view.action_menu.hit_test = lambda _x, _y: "file:app/selected.cpp"
    app.view.action_menu.open(_event())
    file_menu.submenu("Pin file to cluster").invoke("tests")

    saved = persistence.ProjectStore(tmp_path).load_layout()
    assert saved.pins == {"app/selected.cpp": "tests"}
    assert app.opened is not None
    assert app.opened.clustering.cluster_of("app/selected.cpp") is not None
    assert app.opened.clustering.cluster_of("app/selected.cpp").id == "tests"
    assert app.view.layout is not None
    assert app.view.layout.nodes["app/selected.cpp"].cluster == "tests"


def test_real_app_scope_control_and_implement_here_override_persist_and_target_request(
        app_module: Any, tmp_path: Path, monkeypatch: Any) -> None:
    from test_simulation import (
        ARCHITECTURE_SOURCE,
        MAIN,
        NORMALIZE,
        ScriptedProvider,
        _approach,
        _ImmediateThread,
        _reply,
        _run_immediately,
        runner_factory,
        write_simulation_project,
    )

    project = tmp_path / "queue-control"
    write_simulation_project(project)
    store = persistence.ProjectStore(project)
    provider = ScriptedProvider([
        _reply("Add formatter architecture", {"service.py": ARCHITECTURE_SOURCE}),
        _approach("Implement the developer-selected main target.", "service.main", ("service.py",)),
    ])
    original_open = app_module.session.open_project
    monkeypatch.setattr(app_module.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(
        app_module.session, "open_project",
        lambda root, config: original_open(root, config, in_process=True))
    monkeypatch.setattr(step_controller.messagebox, "askyesno", lambda *args, **kwargs: True)
    app = app_module.App(
        app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "config.json")
    app.run_async = _run_immediately
    app.steps = step_controller.StepController(app, runner_factory(provider))
    app.open_project(project)
    app._poll()
    app.edit_specification()
    assert app.spec_editor is not None and app.spec_editor.save()
    app._poll()
    app.steps.action("propose")
    app.steps.action("approve")
    app.steps.action("approve_architecture")
    app._poll()

    assert implementation_queue.target_usr(store.load_state()) == NORMALIZE
    assert app.panel.scope_combobox.kwargs["textvariable"] is app.panel.scope_var
    assert set(app.panel.scope_combobox.kwargs["values"]) >= {
        "Single entity", "Enclosing class", "Enclosing cluster", "All remaining leaves"
    }
    app.panel.scope_var.set("Enclosing class")
    app.steps.action("scope_changed")
    app._poll()
    assert store.load_state().implementation_scope == "enclosing_class"

    context = app.graph_actions(MAIN)
    assert context is not None and context.can_implement and context.target_usr == MAIN
    app.dispatch_graph_action(graph_canvas.IMPLEMENT_HERE, context)

    state = store.load_state()
    decision = app.steps.approach
    assert state.implementation_override == MAIN
    assert state.implementation_queue[:2] == (MAIN, NORMALIZE)
    assert implementation_queue.target_usr(state) == MAIN
    assert "Overridden target: service.main" in app.panel.queue_var.get()
    assert decision is not None and decision.request.target == MAIN and decision.request.batch == (MAIN,)
    assert f"USR `{MAIN}`" in provider.prompts[-1]
    app.steps.action("approve_approach")
    record = steplog.StepLog(store.steps_path).records()[-1]
    assert record.round == "approach" and record.batch == [MAIN]
