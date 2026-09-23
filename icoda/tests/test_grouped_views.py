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
    assert detail.width == views.COLUMN_WIDTH and detail.height == 2 * views.ROW_HEIGHT
    edge, = detail.edges
    assert edge.label == "recursive" and edge.loop and edge.uncertain
    overview, groups = views.entity_view_overview(model, grouping, {"f1"}, [], "functions")
    assert groups == {"cluster:a": {"f1"}}
    assert overview.nodes["cluster:a"].label == "Renamed A\n1 function"
