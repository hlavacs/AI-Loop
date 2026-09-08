"""File View geometry: circles do not overlap, files sit on the circumference, arrows merge and aggregate."""

from __future__ import annotations

import math

from icoda_core import clusters, views
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind, merge_external_names


def small_model() -> DerivedModel:
    model = DerivedModel("/p")
    for f in ("app/main.cpp", "app/config.cpp", "core/a.cpp", "core/b.cpp", "core/c.cpp"):
        model.files[f] = FileInfo(f)
    model.add_entity(Entity("u:main", Kind.FUNCTION, "main", "main", "app/main.cpp", 1))
    model.add_entity(Entity("u:a", Kind.FUNCTION, "a", "a", "core/a.cpp", 1))
    model.add_edge(Edge(EdgeKind.CALLS, "u:main", "u:a", "app/main.cpp", 2))
    model.add_edge(Edge(EdgeKind.CALLS, "u:main", "u:a", "app/main.cpp", 3))
    model.add_edge(Edge(EdgeKind.IMPORTS, "app/main.cpp", "core/a.cpp", "app/main.cpp", 1))
    model.add_edge(Edge(EdgeKind.IMPORTS, "app/main.cpp", "app/config.cpp", "app/main.cpp", 1))
    model.add_edge(Edge(EdgeKind.CALLS, "core/b.cpp", "core/c.cpp", "core/b.cpp", 1))
    model.add_edge(Edge(EdgeKind.CALLS, "core/a.cpp", "core/b.cpp", "core/a.cpp", 1))
    model.add_edge(Edge(EdgeKind.CALLS, "core/a.cpp", "core/b.cpp", "core/a.cpp", 2))
    model.add_edge(Edge(EdgeKind.CALLS, "u:main", "external:std", "app/main.cpp", 4, "printf"))
    merge_external_names(model, "std", ["printf"])
    return model


def test_layout_places_every_file_on_its_circle() -> None:
    model = small_model()
    clustering = clusters.cluster_files(model)
    layout = views.layout_file_view(model, clustering)
    assert {c.id for c in layout.circles} == {"app", "core"}
    for circle in layout.circles:
        for file in circle.files:
            node = layout.nodes[file]
            assert math.isclose(math.hypot(node.x - circle.cx, node.y - circle.cy), circle.radius, abs_tol=1e-6)
    a, b = layout.circles
    assert math.hypot(a.cx - b.cx, a.cy - b.cy) > a.radius + b.radius
    assert layout.nodes["external:std"].kind == "external"


def test_arrows_merge_kinds_and_aggregate_per_cluster() -> None:
    model = small_model()
    clustering = clusters.cluster_files(model)
    layout = views.layout_file_view(model, clustering)
    main_to_a = next(a for a in layout.file_arrows if (a.source, a.target) == ("app/main.cpp", "core/a.cpp"))
    assert main_to_a.counts == {EdgeKind.CALLS: 2, EdgeKind.IMPORTS: 1}
    assert main_to_a.dominant == EdgeKind.CALLS and main_to_a.badge == "c2 i1"
    external = next(a for a in layout.file_arrows if a.target == "external:std")
    assert external.source == "app/main.cpp" and external.weight == 1
    cluster_level = {(a.source, a.target): a.weight for a in layout.cluster_arrows}
    assert cluster_level[("app", "core")] == 3 and cluster_level[("app", "external:std")] == 1
    assert ("app", "app") not in cluster_level


def test_related_files_are_neighbours_on_the_circumference() -> None:
    model = small_model()
    ordered = views.order_files(["core/a.cpp", "core/b.cpp", "core/c.cpp"], model)
    gap = abs(ordered.index("core/b.cpp") - ordered.index("core/a.cpp"))
    assert min(gap, len(ordered) - gap) == 1 and ordered[0] == "core/b.cpp"


def test_arrow_endpoints_are_shortened() -> None:
    a, b = views.Node("a", "a", 0, 0, "x"), views.Node("b", "b", 100, 0, "x")
    assert views.arrow_endpoints(a, b, margin=10) == (10, 0, 90, 0)


def call_model() -> DerivedModel:
    model = DerivedModel("/p")
    model.files["m.cpp"] = FileInfo("m.cpp")
    for usr, name in (("u:main", "main"), ("u:a", "a"), ("u:b", "b"), ("u:c", "c"), ("u:t", "tmain")):
        model.add_entity(Entity(usr, Kind.FUNCTION, name, name, "m.cpp", 1, signature=f"void {name}()"))
    model.entities["u:t"] = Entity("u:t", Kind.FUNCTION, "main", "main", "t.cpp", 1)  # a second main, no calls
    for source, target, label in (("u:main", "u:a", ""), ("u:main", "u:b", ""), ("u:a", "u:c", "push (Circle)"),
                                  ("u:c", "u:a", ""), ("u:c", "u:c", ""), ("u:b", "external:std", "printf")):
        model.add_edge(Edge(EdgeKind.CALLS, source, target, "m.cpp", 2, label))
    return model


def test_call_view_levels_loops_and_path() -> None:
    model = call_model()
    assert views.default_root(model) == "u:main"
    layout = views.layout_call_view(model, "u:main", depth=3, selected="u:c")
    levels = {usr: node.level for usr, node in layout.nodes.items()}
    assert levels == {"u:main": 0, "u:a": 1, "u:b": 1, "u:c": 2, "external:std": 2}
    assert layout.nodes["external:std"].kind == "external" and layout.nodes["external:std"].label == "std"
    loops = {(e.source, e.target) for e in layout.edges if e.loop}
    assert loops == {("u:c", "u:a"), ("u:c", "u:c")}
    assert next(e for e in layout.edges if e.target == "u:c").label == "push (Circle)"
    assert layout.path == {"u:main", "u:a", "u:c"}
    assert layout.width == views.COLUMN_WIDTH * 3 and layout.height == views.ROW_HEIGHT * 2


def test_call_view_depth_and_callers() -> None:
    model = call_model()
    shallow = views.layout_call_view(model, "u:main", depth=1)
    assert set(shallow.nodes) == {"u:main", "u:a", "u:b"}
    callers = views.layout_call_view(model, "u:c", depth=2, callers=True)
    assert {usr: n.level for usr, n in callers.nodes.items()} == {"u:c": 0, "u:a": 1, "u:main": 2}
    assert all(not e.loop for e in callers.edges if e.source == "u:main")
