"""Tk-stub coverage for the persistent M4 mind-map canvas and step navigation."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

from icoda_core import mind_map, persistence, steplog, views
from icoda_core.model import DerivedModel, Entity, FileInfo, Kind
from icoda_gui import graph_canvas, mind_map_view


def _model(introduced: bool = True) -> tuple[DerivedModel, list[steplog.StepRecord]]:
    model = DerivedModel("/project")
    model.files["src/widget.cpp"] = FileInfo("src/widget.cpp")
    model.add_entity(Entity("u:widget", Kind.CLASS, "Widget", "app::Widget", "src/widget.cpp", 3,
                            satisfies=("R-1",), status="implemented"))
    model.add_entity(Entity("u:run", Kind.METHOD, "run", "app::Widget::run", "src/widget.cpp", 5,
                            parent="u:widget", satisfies=("R-2",), status="tested"))
    records = [steplog.StepRecord(3, "architecture", "approved", title="Introduce Widget",
                                  files=["src/widget.cpp"], entities_added=["u:widget", "u:run"],
                                  build_ok=True, test_ok=True)] if introduced else []
    return model, records


def test_canvas_renders_core_layout_and_persists_each_expansion(tmp_path: Path, monkeypatch: Any) -> None:
    model, history = _model()
    store = persistence.ProjectStore(tmp_path)
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION))
    selected: list[int] = []
    canvas = mind_map_view.MindMapCanvas(tk.Tk(), selected.append)
    assert isinstance(canvas.action_menu, graph_canvas.NodeActionMenu)
    labels: list[str] = []
    original_create_text = canvas.canvas.create_text

    def record_text(*args: Any, **kwargs: Any) -> Any:
        labels.append(str(kwargs.get("text", "")))
        return original_create_text(*args, **kwargs)

    monkeypatch.setattr(canvas.canvas, "create_text", record_text)
    canvas.show(model, history, store)
    assert canvas.tree is not None
    assert canvas.layout == views.layout_mind_map(canvas.tree, mind_map.MindMapViewState())
    assert {item.node.id for item in canvas.layout.nodes} == {"cluster:src"}

    monkeypatch.setattr(canvas, "node_at", lambda _x, _y: "cluster:src")
    event = type("Pointer", (), {"x": 120, "y": 80, "num": 1})()
    canvas.on_press(event)
    canvas.on_release(event)

    expected = mind_map.MindMapViewState(("cluster:src",))
    assert canvas.state == expected and canvas.layout == views.layout_mind_map(canvas.tree, expected)
    loaded_state = store.load_state()
    assert loaded_state.mind_map == expected and loaded_state.phase == persistence.ProjectPhase.IMPLEMENTATION
    assert selected == [3]
    assert any("implemented" in label and "R-1" in label and "step #3" in label for label in labels)

    reopened = mind_map_view.MindMapCanvas(tk.Tk(), lambda _iteration: None)
    reopened.show(model, history, persistence.ProjectStore(tmp_path))
    assert reopened.tree is not None
    assert reopened.state == expected
    assert reopened.layout == views.layout_mind_map(reopened.tree, expected)
    assert {item.node.id for item in reopened.layout.nodes} == {"cluster:src", "file:src/widget.cpp"}


def test_no_project_empty_model_empty_history_and_unknown_iteration_are_safe() -> None:
    selected: list[int] = []
    canvas = mind_map_view.MindMapCanvas(tk.Tk(), selected.append)
    canvas.show(None)
    assert canvas.tree is None and canvas.layout is None
    assert canvas.summary_var.get() == "Mind map: no project loaded"

    canvas.show(DerivedModel("/empty"), [])
    assert canvas.tree is not None
    assert canvas.tree == mind_map.MindMap()
    assert canvas.layout == views.MindMapLayout(canvas.tree, (), (), 1.0, 1.0)

    model, empty_history = _model(introduced=False)
    canvas.show(model, empty_history)
    assert canvas.tree is not None
    canvas.activate_node("cluster:src")
    canvas.activate_node("file:src/widget.cpp")
    before = canvas.state
    canvas.activate_node("entity:u:run")
    assert selected == [] and canvas.state == before
    assert canvas.tree.node_map()["entity:u:run"].introduced_iteration is None


def test_app_navigation_selects_the_introducing_record_in_step_panel(app_module: Any, tmp_path: Path) -> None:
    from test_app import opened_project

    store = persistence.ProjectStore(tmp_path)
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION))
    store.ensure()
    steplog.StepLog(store.steps_path).append(
        steplog.StepRecord(7, "architecture", "approved", title="Add A", files=["src/a.cpp"],
                           entities_added=["u:A", "u:A:f"], build_ok=True, test_ok=True))
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened_project(tmp_path))

    app.mind_map_view.activate_node("cluster:src")

    assert app.panel.selected_iteration == 7
    assert app.panel.title_var.get() == "Step 7: Add A"
    assert "src/a.cpp" in app.panel.details.get("1.0", "end")
