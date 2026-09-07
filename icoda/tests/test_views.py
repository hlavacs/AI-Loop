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
