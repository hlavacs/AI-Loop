"""Class group navigation and ungrouped Call waterfall regressions."""
from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace

import pytest

from icoda_core import clusters, views
from icoda_core.graph_filter import NodeDecision
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind
from icoda_gui.call_view import CallViewCanvas
from icoda_gui.class_view import ClassViewCanvas


def grouped_model() -> tuple[DerivedModel, clusters.Clustering]:
    model = DerivedModel("/p")
    for file in ("a.cpp", "b.cpp"):
        model.files[file] = FileInfo(file)
    for index in range(20):
        file = "a.cpp" if index < 8 else "b.cpp"
        model.add_entity(Entity(f"f{index}", Kind.FUNCTION, f"f{index}", f"f{index}", file, 1))
        model.add_entity(Entity(f"c{index}", Kind.CLASS, f"C{index}", f"C{index}", file, 2))
        if index:
            model.add_edge(Edge(EdgeKind.CALLS, "f0", f"f{index}"))
            model.add_edge(Edge(EdgeKind.INHERITS, f"c{index}", "c0"))
    grouping = clusters.Clustering([clusters.Cluster("a", "Renamed A", ["a.cpp"]),
                                   clusters.Cluster("b", "B", ["b.cpp"])])
    return model, grouping


@pytest.mark.parametrize("canvas_type", [ClassViewCanvas])
def test_group_camera_stays_scoped_until_explicit_back(canvas_type, monkeypatch) -> None:
    model, grouping = grouped_model()
    view = canvas_type(tk.Tk(), lambda *_: None)
    view.group_clustering = grouping
    view.show(model)
    assert view.overview and set(view.groups) == {"cluster:a", "cluster:b"}
    assert "Renamed A" in view.overview_layout.nodes["cluster:a"].label
    full = set(view.layout.nodes)
    viewport = view.scale, view.offset, view.fit_scale, view.user_zoomed
    node = view.overview_layout.nodes["cluster:a"]
    point = view.to_screen(node.x, node.y)
    # Zoom entry and double-click entry share the same sticky scope.
    view.zoom(max(1.0, view.fit_scale * 1.3) / view.scale + .01, point)
    assert view.focused_group == "cluster:a" and not view.overview
    members = set(view.groups[view.focused_group])
    assert set(view.layout.nodes) == members and len(members) == 8
    assert all(edge.source in members and edge.target in members for edge in view.layout.edges)
    view.zoom(.001)
    assert view.scale <= .1
    view.on_press(SimpleNamespace(x=20, y=30))
    view.on_drag(SimpleNamespace(x=70, y=80))
    view.on_release(SimpleNamespace(x=70, y=80))
    view.fit()
    monkeypatch.setattr(view.canvas, "winfo_width", lambda: 420)
    view.on_resize(None)
    view.reset_zoom()
    assert view.scale == pytest.approx(1.0)
    assert not view.overview and view.focused_group == "cluster:a"
    assert set(view.layout.nodes) == members
    view.back_to_overview()
    assert view.overview and view.focused_group is None and set(view.layout.nodes) == full
    assert (view.scale, view.offset, view.fit_scale, view.user_zoomed) == viewport
    monkeypatch.setattr(view, "node_at", lambda *_: "cluster:b")
    view.dragged = False
    view.on_double_click(SimpleNamespace(x=1, y=1))
    assert view.focused_group == "cluster:b" and len(view.layout.nodes) == 12
    view.show(model)
    assert view.focused_group is None and view.overview


def test_call_waterfall_keeps_all_functions_and_camera_when_selected() -> None:
    model, _ = grouped_model()
    view = CallViewCanvas(tk.Tk(), lambda *_: None)
    view.entry_usr = "f0"
    view.show(model)
    assert len(view.layout.nodes) == 20
    assert view.layout.nodes["f0"].level == 0
    assert all(node.level == 1 for usr, node in view.layout.nodes.items() if usr != "f0")
    view.zoom(2)
    viewport = view.scale, view.offset
    view.select("f1")
    assert view.layout.path == {"f0", "f1"}
    assert (view.scale, view.offset) == viewport
    view.callers_var.set(True)
    view.controls_changed()
    assert set(view.layout.nodes) == {"f0"}
    view.callers_var.set(False)
    view.controls_changed()
    assert len(view.layout.nodes) == 20
    view.set_root("f2")
    assert set(view.layout.nodes) == {"f2"}
    view.from_main()
    assert len(view.layout.nodes) == 20


@pytest.mark.parametrize("canvas_type,prefix", [(ClassViewCanvas, "c")])
def test_filtered_overview_counts_and_relations_only_use_visible_entities(canvas_type, prefix, monkeypatch) -> None:
    model, grouping = grouped_model()
    view = canvas_type(tk.Tk(), lambda *_: None)
    view.group_clustering = grouping
    view.show(model)
    labels, lines = [], []
    monkeypatch.setattr(view.canvas, "create_text", lambda *args, **kw: labels.append(kw["text"]) or len(labels))
    monkeypatch.setattr(view.canvas, "create_line", lambda *args, **kw: lines.append(args))
    # Hide the central endpoint; both groups still have visible members, but no visible inter-group edges.
    view.set_graph_filter({f"{prefix}0": NodeDecision(hidden=True)}, filter_active=True)
    assert "Renamed A\n7 / 8 visible" in labels
    assert not lines
    view.open_group("cluster:a")
    assert view.focused_group == "cluster:a" and not view.overview


def test_group_layout_preserves_call_metadata_and_singleton_cluster_id() -> None:
    model, grouping = grouped_model()
    model.add_edge(Edge(EdgeKind.CALLS, "f1", "f1", label="recursive", uncertain=True))
    complete = views.layout_call_view(model, "f0")
    assert set(complete.nodes) == {f"f{i}" for i in range(20)}
    edge = next(edge for edge in complete.edges if edge.source == edge.target == "f1")
    assert edge.label == "recursive" and edge.loop and edge.uncertain
    overview, groups = views.entity_view_overview(model, grouping, {"f1"}, [], "functions")
    assert groups == {"cluster:a": {"f1"}}
    assert overview.nodes["cluster:a"].label == "Renamed A\n1 function"


def test_class_subview_organises_automatically_and_button_keeps_scope(monkeypatch) -> None:
    model, grouping = grouped_model()
    view = ClassViewCanvas(tk.Tk(), lambda *_: None)
    view.group_clustering = grouping
    view.show(model)
    parent = view.scale, view.offset, view.fit_scale, view.user_zoomed
    calls = []
    original = views.organise_class_view

    def organise(layout):
        calls.append(set(layout.nodes))
        return original(layout)

    monkeypatch.setattr(views, "organise_class_view", organise)
    view.open_group("cluster:a")
    members = set(view.groups["cluster:a"])
    assert calls == [members]
    packed = view.layout
    view.zoom(2)
    view.organise()
    assert calls == [members, members] and view.layout == packed
    assert view.focused_group == "cluster:a" and not view.overview
    view.fit()
    view.on_resize(None)
    assert view.layout == packed and view.focused_group == "cluster:a"
    view.back_to_overview()
    assert view.overview and (view.scale, view.offset, view.fit_scale, view.user_zoomed) == parent
    view.organise()
    assert len(calls) == 2 and view.overview


def test_dense_class_subview_keeps_members_visible_and_highlights_connections_on_hover(monkeypatch) -> None:
    model, grouping = grouped_model()
    for index in range(20, 50):
        model.add_entity(Entity(f"c{index}", Kind.CLASS, f"C{index}", f"C{index}", "a.cpp", index))
        model.add_edge(Edge(EdgeKind.INHERITS, f"c{index}", "c0"))
    model.add_entity(Entity("method", Kind.METHOD, "run", "C0::run", "a.cpp", 60,
                            parent="c0", signature="void run()", status="implemented"))
    view = ClassViewCanvas(tk.Tk(), lambda *_: None)
    view.group_clustering = grouping
    view.show(model)
    view.open_group("cluster:a")
    labels, lines = [], []
    monkeypatch.setattr(view.canvas, "create_text", lambda *args, **kw: labels.append(kw["text"]) or len(labels))
    monkeypatch.setattr(view.canvas, "create_line", lambda *args, **kw: lines.append(kw))
    view.scale = .3
    view.redraw()
    assert "void run()  [implemented]" in labels
    assert lines and all(line["fill"] == "#e2e8f0" for line in lines)
    view.reset_zoom()
    assert "void run()  [implemented]" in labels
    monkeypatch.setattr(view, "node_at", lambda *_: "method")
    lines.clear()
    view.on_motion(SimpleNamespace(x=0, y=0))
    assert view.edge_focus == "c0" and lines
    assert all(line["fill"] == "#2ca02c" for line in lines)
    assert view.focused_group == "cluster:a" and not view.overview


def test_single_class_is_inline_with_all_details_when_fitted_or_zoomed(monkeypatch) -> None:
    model, grouping = grouped_model()
    for index in range(1, 8):
        model.entities[f"c{index}"].file = "b.cpp"
    model.add_entity(Entity("field", Kind.FIELD, "value", "C0::value", "a.cpp", 10,
                            parent="c0", signature="int"))
    for index in range(60):
        model.add_entity(Entity(f"method{index}", Kind.METHOD, f"run{index}", f"C0::run{index}", "a.cpp",
                                20 + index, parent="c0", signature=f"void run{index}()", status="implemented"))
    view = ClassViewCanvas(tk.Tk(), lambda *_: None)
    view.group_clustering = grouping
    view.show(model)
    labels = []
    create_text = view.canvas.create_text

    def record_text(*args, **kwargs):
        labels.append(kwargs.get("text", ""))
        return create_text(*args, **kwargs)

    monkeypatch.setattr(view.canvas, "create_text", record_text)
    assert set(view.overview_layout.nodes) == {"c0", "cluster:b"}
    assert view.overview_layout.nodes["c0"].kind == "class"
    assert "cluster:a" not in view.groups
    view.open_group("c0")
    assert view.overview and view.focused_group is None
    expected = {"class C0", "1 data · 60 methods", "value: int"}
    expected.update(f"void run{index}()  [implemented]" for index in range(60))
    for action in (view.redraw, view.fit, lambda: view.on_resize(None),
                   lambda: view.zoom(.1)):
        labels.clear()
        action()
        view.redraw()
        assert expected <= set(labels)
        assert {"field", *(f"method{index}" for index in range(60))} <= set(view.item_nodes.values())
        assert view.focused_group is None and view.overview
    point = view.to_screen(view.overview_layout.nodes["c0"].x, view.overview_layout.nodes["c0"].y)
    view.zoom(2 / view.scale, point)
    assert view.overview and view.focused_group is None
    opened = []
    view.open_editor = lambda *args: opened.append(args)
    monkeypatch.setattr(view, "node_at", lambda *_: "c0")
    view.on_double_click(SimpleNamespace(x=0, y=0))
    assert opened == [("a.cpp", 2)]


@pytest.mark.parametrize("interface", ["export", "header", "inferred"])
def test_library_api_roots_lead_to_shared_helpers_and_recursive_calls(interface) -> None:
    model = DerivedModel("/p")
    for name in ("api_a", "api_b", "helper", "leaf"):
        entity = Entity(name, Kind.FUNCTION, name, name, "library.cpp", 1)
        if name.startswith("api_"):
            entity.exported = interface == "export"
            entity.declaration_file = "library.hpp" if interface == "header" else ""
        model.add_entity(entity)
    for source, target in (("api_a", "helper"), ("api_b", "helper"),
                           ("helper", "leaf"), ("leaf", "helper")):
        model.add_edge(Edge(EdgeKind.CALLS, source, target))
    view = CallViewCanvas(tk.Tk(), lambda *_: None)
    view.library_mode = True
    view.show(model)
    assert views.library_roots(model) == ("api_a", "api_b")
    assert {usr: n.level for usr, n in view.layout.nodes.items()} == {
        "api_a": 0, "api_b": 0, "helper": 1, "leaf": 2}
    assert len(view.layout.edges) == 4
    assert next(e for e in view.layout.edges if e.source == "leaf").loop
    view.depth_var.set(1)
    view.controls_changed()
    assert set(view.layout.nodes) == {"api_a", "api_b", "helper"}
    view.set_root("helper")
    assert view.layout.nodes["helper"].level == 0
    view.from_main()
    assert view.layout.nodes["helper"].level == 1


def test_recursive_library_without_interface_still_has_an_entry() -> None:
    model = DerivedModel("/p")
    for name in ("b", "a"):
        model.add_entity(Entity(name, Kind.FUNCTION, name, name, "lib.cpp", 1))
    model.add_edge(Edge(EdgeKind.CALLS, "a", "b"))
    model.add_edge(Edge(EdgeKind.CALLS, "b", "a"))
    assert views.library_roots(model) == ("a",)
    assert set(views.layout_call_view(model, views.library_roots(model)).nodes) == {"a", "b"}
    assert views.library_roots(DerivedModel("/empty")) == ()


@pytest.mark.parametrize("library_mode", [False, True])
def test_call_selection_thickens_entry_path_and_direct_outgoing_calls(library_mode, monkeypatch) -> None:
    model = DerivedModel("/p")
    for name in ("main", "api", "middle", "selected", "child", "sibling", "grandchild"):
        model.add_entity(Entity(name, Kind.FUNCTION, name, name, "lib.cpp", 1,
                                exported=name in {"main", "api"}))
    for source, target in (("main", "middle"), ("middle", "selected"), ("main", "sibling"),
                           ("api", "sibling"), ("selected", "child"), ("selected", "selected"),
                           ("selected", "middle"), ("child", "grandchild")):
        model.add_edge(Edge(EdgeKind.CALLS, source, target, uncertain=target == "child"))
    view = CallViewCanvas(tk.Tk(), lambda *_: None)
    view.library_mode = library_mode
    view.depth_var.set(5)
    view.show(model)
    view.select("selected")
    assert view.layout.path == {"main", "middle", "selected"}
    lines = []
    monkeypatch.setattr(view.canvas, "create_line", lambda *args, **kwargs: lines.append(kwargs))
    for edge in view.layout.edges:
        lines.clear()
        view._draw_edge(edge)
        expected = 3 if edge.source == "selected" or (edge.source, edge.target) in {
            ("main", "middle"), ("middle", "selected")} else 1
        assert len(lines) == 1 and lines[0]["width"] == expected
        assert lines[0]["arrow"] == tk.LAST
        if edge.uncertain:
            assert lines[0]["dash"] == (6, 4)
    view.select("child")
    assert view.layout.path == {"main", "middle", "selected", "child"}
    view.select(None)
    lines.clear()
    for edge in view.layout.edges:
        view._draw_edge(edge)
    assert lines and all(line["width"] == 1 for line in lines)


def test_class_overview_draws_typed_connections_between_clusters_and_singletons(monkeypatch):
    model, grouping = grouped_model()
    model.files["single.cpp"] = FileInfo("single.cpp")
    model.add_entity(Entity("single", Kind.CLASS, "Single", "Single", "single.cpp", 1))
    model.add_entity(Entity("field", Kind.FIELD, "value", "Single::value", "single.cpp", 2, parent="single"))
    model.add_entity(Entity("method", Kind.METHOD, "run", "C0::run", "a.cpp", 3, parent="c0"))
    model.add_edge(Edge(EdgeKind.USES_TYPE, "field", "c8"))
    model.add_edge(Edge(EdgeKind.USES_TYPE, "method", "single"))
    view = ClassViewCanvas(tk.Tk(), lambda *_: None)
    view.group_clustering = grouping
    view.show(model)
    drawn = []
    original = view._draw_edge
    def record(edge, nodes=None):
        drawn.append(edge)
        original(edge, nodes)
    monkeypatch.setattr(view, "_draw_edge", record)
    view.redraw()
    assert {(e.source, e.target, e.kind.value, e.count) for e in drawn} == {
        ("cluster:b", "cluster:a", "inheritance", 12),
        ("single", "cluster:b", "composition", 1),
        ("cluster:a", "single", "usage", 1)}
    assert {"single", "field", "cluster:a", "cluster:b"} <= set(view.item_nodes.values())
    panels = list(view._overview_panels.values())
    for i, a in enumerate(panels):
        for b in panels[i+1:]:
            assert abs(a.x-b.x) >= (a.width+b.width)/2 or abs(a.y-b.y) >= (a.height+b.height)/2
    drawn.clear()
    view.set_graph_filter({"single": NodeDecision(hidden=True)}, filter_active=True)
    assert [(e.source, e.target) for e in drawn] == [("cluster:b", "cluster:a")]


@pytest.mark.parametrize("library_mode", [False, True])
def test_call_click_filters_arrows_and_background_restores_them(library_mode, monkeypatch):
    model = DerivedModel("/p")
    for name in ("main", "api", "parent", "chosen", "child", "other"):
        model.add_entity(Entity(name, Kind.FUNCTION, name, name, "lib.cpp", 1,
                                exported=name in {"main", "api"}))
    pairs = {("main", "parent"), ("parent", "chosen"), ("chosen", "child"),
             ("chosen", "chosen"), ("parent", "main"), ("main", "other"), ("api", "other")}
    for source, target in sorted(pairs):
        model.add_edge(Edge(EdgeKind.CALLS, source, target))
    focused = []
    view = CallViewCanvas(tk.Tk(), lambda *_: None, focus_node=focused.append)
    view.library_mode = library_mode
    view.show(model)
    all_edges = {(e.source, e.target) for e in view.layout.edges}
    drawn = []
    monkeypatch.setattr(view, "_draw_edge", lambda edge: drawn.append((edge.source, edge.target)))
    monkeypatch.setattr(view, "node_at", lambda *_: "chosen")
    click = SimpleNamespace(x=0, y=0, num=1)
    view.on_release(click)
    assert set(drawn) == {("main", "parent"), ("parent", "chosen"),
                          ("chosen", "child"), ("chosen", "chosen")}
    assert set(view.item_nodes.values()) == set(view.layout.nodes)
    monkeypatch.setattr(view, "node_at", lambda *_: None)
    view.dragged = True
    view.on_release(click)
    assert view.selected == "chosen"
    view.dragged = False
    drawn.clear()
    view.on_release(click)
    assert view.selected is None and not view.layout.path
    assert set(drawn) == all_edges and focused == ["chosen", None]
