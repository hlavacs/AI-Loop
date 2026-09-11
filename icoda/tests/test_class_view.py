"""Pure Class View graph projection and its Tk-stub canvas."""

from __future__ import annotations

import tkinter as tk
from typing import Any

from icoda_core import class_view
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind
from icoda_gui import class_view as class_view_gui
from icoda_gui import graph_canvas


def model_with_classes() -> DerivedModel:
    model = DerivedModel("/p")
    model.files["types.cppm"] = FileInfo("types.cppm")
    entities = (
        Entity("u:empty", Kind.CLASS, "Empty", "app::Empty", "types.cppm", 30),
        Entity("u:run", Kind.METHOD, "run", "app::Widget::run", "types.cppm", 16,
               parent="u:widget", signature="void run(app::Base)", status="implemented"),
        Entity("u:value", Kind.FIELD, "value", "app::Widget::value", "types.cppm", 12,
               parent="u:widget", signature="app::Base"),
        Entity("u:widget", Kind.STRUCT, "Widget", "app::Widget", "types.cppm", 10, end_line=24,
               template_params=("T",)),
        Entity("u:stop", Kind.METHOD, "stop", "app::Widget::stop", "types.cppm", 15,
               parent="u:widget", signature="void stop()", status="stub"),
        Entity("u:base", Kind.CLASS, "Base", "app::Base", "types.cppm", 2, end_line=8),
    )
    for entity in entities:
        model.add_entity(entity)
    model.add_edge(Edge(EdgeKind.USES_TYPE, "u:run", "u:base"))
    model.add_edge(Edge(EdgeKind.INHERITS, "u:widget", "u:base"))
    model.add_edge(Edge(EdgeKind.USES_TYPE, "u:value", "u:base"))
    model.add_edge(Edge(EdgeKind.USES_TYPE, "u:run", "u:base", line=17))
    return model


def test_build_class_graph_has_members_statuses_and_relationships() -> None:
    graph = class_view.build_class_graph(model_with_classes())
    assert [node.qualified_name for node in graph.nodes] == ["app::Base", "app::Empty", "app::Widget"]
    widget = graph.node_map()["u:widget"]
    assert [(member.name, member.declaration) for member in widget.data_members] == [("value", "app::Base")]
    assert [(member.name, member.status) for member in widget.member_functions] == [
        ("run", "implemented"), ("stop", "stub")]
    assert graph.node_map()["u:empty"].members == ()
    assert [(edge.kind, edge.source, edge.target, edge.count) for edge in graph.edges] == [
        (class_view.ClassEdgeKind.COMPOSITION, "u:widget", "u:base", 1),
        (class_view.ClassEdgeKind.INHERITANCE, "u:widget", "u:base", 1),
        (class_view.ClassEdgeKind.USAGE, "u:widget", "u:base", 2),
    ]


def test_build_class_graph_is_deterministic_and_empty_without_classes() -> None:
    model = model_with_classes()
    assert class_view.build_class_graph(model) == class_view.build_class_graph(model)
    no_classes = DerivedModel("/old")
    no_classes.add_entity(Entity("u:f", Kind.FUNCTION, "f", "f", "old.cpp", 1, status="stub"))
    loaded = DerivedModel.from_json(no_classes.to_json())
    assert class_view.build_class_graph(loaded) == class_view.ClassGraph()


def test_class_view_canvas_renders_edges_member_statuses_and_empty_model(monkeypatch: Any) -> None:
    opened: list[tuple[str, int]] = []
    canvas = class_view_gui.ClassViewCanvas(tk.Tk(), lambda file, line: opened.append((file, line)))
    assert isinstance(canvas.action_menu, graph_canvas.NodeActionMenu)
    labels: list[str] = []
    original_create_text = canvas.canvas.create_text

    def record_text(*args: Any, **kwargs: Any) -> Any:
        labels.append(str(kwargs.get("text", "")))
        return original_create_text(*args, **kwargs)

    monkeypatch.setattr(canvas.canvas, "create_text", record_text)
    canvas.show(model_with_classes())
    assert canvas.layout is not None and set(canvas.layout.nodes) == {"u:base", "u:empty", "u:widget"}
    assert {edge.kind for edge in canvas.layout.edges} == set(class_view.ClassEdgeKind)
    assert "void run(app::Base)  [implemented]" in labels
    assert "void stop()  [stub]" in labels
    assert canvas.scale > 0 and {"zoom-out", "fit", "reset", "zoom-in"} == set(canvas.toolbar_controls)
    fitted = canvas.fit_scale
    canvas.zoom(1.25)
    assert canvas.scale > fitted

    canvas.show(DerivedModel.from_json(DerivedModel("/old").to_json()))
    assert canvas.layout is not None and canvas.layout.nodes == {}
    assert canvas.summary_var.get() == "No classes or structs in this model"
    assert "No classes or structs in this model." in labels


def test_class_view_renders_paired_entity_once_with_both_file_names(monkeypatch: Any) -> None:
    model = model_with_classes()
    member = model.entities["u:run"]
    member.file = "src/widget.cpp"
    member.declaration_file = "include/widget.hpp"
    canvas = class_view_gui.ClassViewCanvas(tk.Tk(), lambda _file, _line: None)
    labels: list[str] = []
    original_create_text = canvas.canvas.create_text

    def record_text(*args: Any, **kwargs: Any) -> Any:
        labels.append(str(kwargs.get("text", "")))
        return original_create_text(*args, **kwargs)

    monkeypatch.setattr(canvas.canvas, "create_text", record_text)
    canvas.show(model)
    monkeypatch.setattr(canvas, "node_at", lambda _x, _y: "u:run")

    canvas.on_motion(type("Pointer", (), {"x": 1, "y": 1})())

    assert labels.count("void run(app::Base)  [implemented]") == 1
    assert "include/widget.hpp" in canvas.hover_var.get()
    assert "src/widget.cpp" in canvas.hover_var.get()
