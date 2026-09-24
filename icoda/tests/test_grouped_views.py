"""Call/Class group scope is independent of camera navigation and call graph rebuilding."""
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


@pytest.mark.parametrize("canvas_type", [CallViewCanvas, ClassViewCanvas])
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


def test_call_selection_and_depth_changes_keep_group_even_when_it_shrinks() -> None:
    model, grouping = grouped_model()
    view = CallViewCanvas(tk.Tk(), lambda *_: None)
    view.group_clustering = grouping
    view.show(model)
    view.open_group("cluster:a")
    view.zoom(2)
    viewport = view.scale, view.offset
    view.select("f1")
    assert view.layout.path == {"f0", "f1"}
    assert (view.scale, view.offset) == viewport
    view.callers_var.set(True)
    view.controls_changed()
    assert set(view.layout.nodes) == {"f0"}
    assert view.focused_group == "cluster:a" and not view.overview
    view.fit()
    view.zoom(.01)
    assert set(view.layout.nodes) == {"f0"} and not view.overview
    view.callers_var.set(False)
    view.controls_changed()
    assert len(view.layout.nodes) == 8 and not view.overview
    view.back_to_overview()
    assert len(view.layout.nodes) == 20 and view.overview
    view.open_group("cluster:b")
    view.set_root("f2")
    assert view.focused_group is None and set(view.layout.nodes) == {"f2"}


@pytest.mark.parametrize("canvas_type,prefix", [(CallViewCanvas, "f"), (ClassViewCanvas, "c")])
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
    detail = views.call_view_group(complete, {"f1", "f2"})
    assert set(complete.nodes) == {f"f{i}" for i in range(20)}
    assert set(detail.nodes) == {"f1", "f2"}
    assert detail.width > 0 and detail.height > 0
    assert all(0 < node.x < detail.width and 0 < node.y < detail.height for node in detail.nodes.values())
    assert {usr: node.level for usr, node in detail.nodes.items()} == {
        usr: complete.nodes[usr].level for usr in detail.nodes}
    edge, = detail.edges
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


def test_single_class_group_keeps_all_details_when_fitted_organised_or_zoomed(monkeypatch) -> None:
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
    view.open_group("cluster:a")
    assert view.scale < .5 and set(view.layout.nodes) == {"c0"}
    expected = {"class C0", "1 data · 60 methods", "value: int"}
    expected.update(f"void run{index}()  [implemented]" for index in range(60))
    for action in (view.redraw, view.fit, view.organise, lambda: view.on_resize(None),
                   lambda: view.zoom(.1), view.reset_zoom):
        labels.clear()
        action()
        assert expected <= set(labels)
        assert {"field", *(f"method{index}" for index in range(60))} <= set(view.item_nodes.values())
        assert view.focused_group == "cluster:a" and not view.overview
