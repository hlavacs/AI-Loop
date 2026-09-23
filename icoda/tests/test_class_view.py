"""Pure Class View graph projection and its Tk-stub canvas."""

from __future__ import annotations

import tkinter as tk
from typing import Any

import pytest

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


@pytest.mark.parametrize("scale", [0.35, 1.0, 2.0])
@pytest.mark.parametrize("kind", [class_view.ClassEdgeKind.USAGE, class_view.ClassEdgeKind.COMPOSITION])
def test_class_self_relation_has_visible_marker_outside_panel(monkeypatch: Any, scale: float,
                                                            kind: class_view.ClassEdgeKind) -> None:
    canvas = class_view_gui.ClassViewCanvas(tk.Tk(), lambda _file, _line: None)
    model = model_with_classes()
    source = "u:run" if kind == class_view.ClassEdgeKind.USAGE else "u:value"
    model.add_edge(Edge(EdgeKind.USES_TYPE, source, "u:widget"))
    canvas.show(model)
    assert canvas.layout is not None
    canvas.scale, canvas.offset = scale, (37, 53)
    node = canvas.layout.nodes["u:widget"]
    edge = next(edge for edge in canvas.layout.edges if edge.source == edge.target)
    lines: list[tuple[tuple[float, ...], dict[str, Any]]] = []
    markers: list[tuple[float, ...]] = []
    monkeypatch.setattr(canvas.canvas, "create_line", lambda *args, **kwargs: lines.append((args, kwargs)))
    monkeypatch.setattr(canvas.canvas, "create_polygon", lambda *args, **kwargs: markers.append(args))

    canvas._draw_edge(edge)

    assert len(lines) == 1
    points, options = lines[0]
    right, _ = canvas.to_screen(node.x + node.width / 2, node.y)
    assert len(points) >= 8 and min(points[::2]) > right
    assert points[1] < points[-1] and options["smooth"]
    if kind == class_view.ClassEdgeKind.USAGE:
        assert options["arrow"] == tk.LAST and "dash" in options
    else:
        assert "arrow" not in options and "dash" not in options
        assert len(markers) == 1 and min(markers[0][::2]) > right


def test_organise_class_panels_packs_actual_heights_without_losing_members_or_relations() -> None:
    import copy
    from itertools import combinations

    from icoda_core import views

    model = model_with_classes()
    for index in range(30):
        usr = f"c{index:02}"
        model.add_entity(Entity(usr, Kind.CLASS, usr, usr, "types.cppm", index + 40))
        for member in range(80 if index == 0 else index % 6):
            model.add_entity(Entity(f"{usr}:m{member}", Kind.METHOD, f"m{member}", f"{usr}::m{member}",
                                    "types.cppm", 100 + member, parent=usr, status="implemented"))
    original = views.layout_class_view(class_view.build_class_graph(model))
    saved = copy.deepcopy(original)
    packed = views.organise_class_view(original)
    assert original == saved and views.organise_class_view(packed) == packed
    assert packed.graph is original.graph and packed.edges == original.edges
    assert packed.nodes.keys() == original.nodes.keys()
    assert packed.width * packed.height < original.width * original.height / 2
    for usr, node in packed.nodes.items():
        assert node.node is original.nodes[usr].node
        assert (node.width, node.height) == (original.nodes[usr].width, original.nodes[usr].height)
        assert 0 <= node.x - node.width / 2 <= node.x + node.width / 2 <= packed.width
        assert 0 <= node.y - node.height / 2 <= node.y + node.height / 2 <= packed.height
    for a, b in combinations(packed.nodes.values(), 2):
        assert (abs(a.x - b.x) >= (a.width + b.width) / 2 + views.CLASS_PANEL_GAP
                or abs(a.y - b.y) >= (a.height + b.height) / 2 + views.CLASS_PANEL_GAP)


def test_organise_class_panels_brings_connected_classes_closer() -> None:
    import math

    from icoda_core import views

    model = DerivedModel("/p")
    for index in range(12):
        usr = f"c{index:02}"
        model.add_entity(Entity(usr, Kind.CLASS, usr, usr, "types.cppm", index))
    model.add_edge(Edge(EdgeKind.INHERITS, "c00", "c11"))
    original = views.layout_class_view(class_view.build_class_graph(model))
    packed = views.organise_class_view(original)

    def distance(layout):
        a, b = layout.nodes["c00"], layout.nodes["c11"]
        return math.hypot(a.x - b.x, a.y - b.y)

    assert distance(packed) < distance(original)


@pytest.mark.parametrize("count", [0, 1, 12])
def test_organise_class_panels_handles_empty_single_and_disconnected_views(count: int) -> None:
    from icoda_core import views

    model = DerivedModel("/p")
    for index in range(count):
        model.add_entity(Entity(str(index), Kind.CLASS, str(index), str(index), "types.cppm", index))
    original = views.layout_class_view(class_view.build_class_graph(model))
    packed = views.organise_class_view(original)
    assert len(packed.nodes) == count and packed.width > 0 and packed.height > 0
    assert views.organise_class_view(packed) == packed
