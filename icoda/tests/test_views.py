"""File View geometry: circles do not overlap, files sit on the circumference, arrows merge and aggregate."""

from __future__ import annotations

import math
from copy import deepcopy

import pytest

from icoda_core import clusters, views
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind, merge_external_names


@pytest.mark.parametrize("kind,name,signature,expected", [
    (Kind.METHOD, "try_submit", "bool try_submit(void (*)(void *) noexcept, void *)",
     "auto try_submit(void (*)(void *) noexcept, void *) -> bool"),
    (Kind.FUNCTION, "run", "int run()", "auto run() -> int"),
    (Kind.METHOD, "stop", "void stop()", "auto stop() -> void"),
    (Kind.METHOD, "value", "const Value & value() const", "auto value() const -> const Value &"),
    (Kind.METHOD, "operator()", "int operator()(int) const", "auto operator()(int) const -> int"),
    (Kind.METHOD, "operator->", "Node * operator->() const", "auto operator->() const -> Node *"),
    (Kind.FUNCTION, "callback", "void (*)(int) callback()", "auto callback() -> void (*)(int)"),
    (Kind.CONSTRUCTOR, "WorkTree<Count>", "void WorkTree<Count>()", "WorkTree<Count>()"),
    (Kind.DESTRUCTOR, "~Worker", "void ~Worker()", "~Worker()"),
    (Kind.FUNCTION, "run", "auto run() -> int", "auto run() -> int"),
    (Kind.FUNCTION, "run", "def run(value: int) -> bool", "def run(value: int) -> bool"),
    (Kind.FUNCTION, "run", "async def run() -> int", "async def run() -> int"),
    (Kind.FUNCTION, "run", "", "run"),
    (Kind.FIELD, "root_", "WorkTreeNode<Count>", "root_  WorkTreeNode<Count>"),
])
def test_entity_tree_labels_show_one_signature_with_cpp_trailing_return_types(
        kind: Kind, name: str, signature: str, expected: str) -> None:
    entity = Entity("u:test", kind, name, name, "source.cpp", 1, signature=signature)
    assert views.entity_tree_label(entity) == expected
    assert entity.signature == signature  # Display formatting must not change signature-comparison inputs.


@pytest.mark.parametrize("kind", list(Kind))
def test_entity_purpose_uses_one_sentence_of_documentation(kind) -> None:
    entity = Entity("u", kind, "Thing", "Thing", "a.cpp", 1,
                    brief="Keeps each window's current state.\n Later text describes its fields.")
    assert views.entity_purpose(entity) == "Keeps each window's current state."
    entity.brief = "Returns a scale of 1.5 for high density displays"
    assert views.entity_purpose(entity) == "Returns a scale of 1.5 for high density displays."
    entity.brief = ""
    assert views.entity_purpose(entity) == "A purpose comment still needs to be added to the source."


@pytest.mark.parametrize("separator, extension", [("::", "cpp"), (".", "py")])
def test_entity_scope_includes_nested_and_out_of_line_members_only(separator, extension):
    model = DerivedModel("/p")
    owner = Entity("C", Kind.CLASS, "C", separator.join(("app", "C")), f"z.{extension}", 3)
    model.add_entity(owner)
    model.add_entity(Entity("field", Kind.FIELD, "value", owner.qualified_name + separator + "value",
                            owner.file, 4, parent=owner.usr))
    model.add_entity(Entity("method", Kind.METHOD, "run", owner.qualified_name + separator + "run",
                            f"a.{extension}", 1, parent="namespace"))
    model.add_entity(Entity("nested", Kind.CLASS, "Nested", owner.qualified_name + separator + "Nested",
                            owner.file, 5, parent=owner.usr))
    model.add_entity(Entity("child", Kind.FIELD, "data", "data", owner.file, 6, parent="nested"))
    model.add_entity(Entity("other", Kind.CLASS, "Other", owner.qualified_name + "Other", owner.file, 7))
    assert {e.usr for e in views.entity_scope(model, owner)} == {"C", "field", "method", "nested", "child"}
    assert views.entity_scope(model, model.entities["method"]) == [model.entities["method"]]


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


def test_external_nodes_stay_near_files_independent_of_nominal_page_height() -> None:
    model = small_model()
    for height in (1000, 10000):
        layout = views.layout_file_view(model, clusters.cluster_files(model), height=height)
        files = [node for node in layout.nodes.values() if node.kind == "file"]
        external = layout.nodes["external:std"]
        assert external.y == max(node.y for node in files) + 90
        assert min(node.x for node in files) <= external.x <= max(node.x for node in files)


def test_compact_file_view_preserves_files_relations_and_original_layout() -> None:
    model = small_model()
    layout = views.layout_file_view(model, clusters.cluster_files(model))
    positions = [(node.x, node.y) for node in layout.nodes.values()]
    compact = views.compact_file_view(layout, columns=2, column_width=120, row_height=35)
    assert compact.nodes.keys() == layout.nodes.keys()
    assert compact.circles == layout.circles
    assert compact.file_arrows == layout.file_arrows and not compact.cluster_arrows
    assert len({(node.x, node.y) for node in compact.nodes.values()}) == len(layout.nodes)
    assert {node.x for node in compact.nodes.values()} == {60, 180}
    assert [(node.x, node.y) for node in layout.nodes.values()] == positions


def test_organise_file_view_brings_connected_clusters_closer_and_preserves_contents() -> None:
    model = small_model()
    for index in range(6):
        model.files[f"extra{index}/file.cpp"] = FileInfo(f"extra{index}/file.cpp")
    grouping = clusters.Clustering([
        clusters.Cluster("app", "App", ["app/main.cpp", "app/config.cpp"]),
        *(clusters.Cluster(f"extra{i}", f"Extra {i}", [f"extra{i}/file.cpp"]) for i in range(3)),
        clusters.Cluster("core", "Core", ["core/a.cpp", "core/b.cpp", "core/c.cpp"]),
        *(clusters.Cluster(f"extra{i}", f"Extra {i}", [f"extra{i}/file.cpp"]) for i in range(3, 6)),
    ])
    original = views.layout_file_view(model, grouping)
    saved = deepcopy(original)
    organised = views.organise_file_view(original)
    before = {circle.id: circle for circle in original.circles}
    after = {circle.id: circle for circle in organised.circles}
    assert math.hypot(after["app"].cx - after["core"].cx, after["app"].cy - after["core"].cy) < \
        math.hypot(before["app"].cx - before["core"].cx, before["app"].cy - before["core"].cy)
    assert original == saved and views.organise_file_view(original) == organised
    assert organised.file_arrows == original.file_arrows
    assert organised.cluster_arrows == original.cluster_arrows
    assert organised.nodes.keys() == original.nodes.keys()
    for circle in organised.circles:
        old = before[circle.id]
        assert (circle.name, circle.radius, circle.files) == (old.name, old.radius, old.files)
        for file in circle.files:
            node, previous = organised.nodes[file], original.nodes[file]
            assert node.cluster == previous.cluster
            assert node.x - circle.cx == pytest.approx(previous.x - old.cx)
            assert node.y - circle.cy == pytest.approx(previous.y - old.cy)
        for other in organised.circles:
            if other.id != circle.id:
                assert math.hypot(circle.cx - other.cx, circle.cy - other.cy) >= circle.radius + other.radius
    assert organised.nodes["external:std"].y > max(
        node.y for node in organised.nodes.values() if node.kind == "file")
    assert all(0 <= node.x <= organised.width and 0 <= node.y <= organised.height
               for node in organised.nodes.values())


@pytest.mark.parametrize("count", [0, 1, 5])
def test_organise_file_view_handles_empty_single_and_disconnected_clusters(count: int) -> None:
    model = DerivedModel("/p")
    grouping = clusters.Clustering([])
    for index in range(count):
        file = f"group{index}/a.cpp"
        model.files[file] = FileInfo(file)
        grouping.clusters.append(clusters.Cluster(str(index), str(index), [file]))
    layout = views.layout_file_view(model, grouping)
    result = views.organise_file_view(layout)
    assert result.nodes.keys() == layout.nodes.keys()
    assert len({(node.x, node.y) for node in result.nodes.values()}) == count
    assert all(math.isfinite(node.x) and math.isfinite(node.y) for node in result.nodes.values())


def test_organise_spaces_labels_in_a_large_single_cluster() -> None:
    model = DerivedModel("/p")
    files = [f"core/long_module_name_{i}.cpp" for i in range(40)]
    model.files = {file: FileInfo(file) for file in files}
    grouping = clusters.Clustering([clusters.Cluster("core", "Core", files)])
    layout = views.layout_file_view(model, grouping)
    sizes = {file: (220.0, 40.0) for file in files}
    result = views.organise_file_view(layout, sizes)
    assert result.circles[0].radius > layout.circles[0].radius
    assert result.circles[0].files == files
    nodes = list(result.nodes.values())
    for i, node in enumerate(nodes):
        for other in nodes[i + 1:]:
            assert abs(node.x - other.x) >= 220.0 - 1e-6 or abs(node.y - other.y) >= 40.0 - 1e-6
    repeated = views.organise_file_view(result, sizes)
    assert repeated.circles[0].radius == pytest.approx(result.circles[0].radius)


def test_file_overview_preserves_visible_relations_and_respects_hidden_files() -> None:
    model = small_model()
    layout = views.layout_file_view(model, clusters.cluster_files(model))
    saved = deepcopy(layout)
    overview = views.file_view_overview(layout, set(layout.nodes))
    assert set(overview.nodes) == {"cluster:app", "cluster:core", "external:std"}
    assert overview.nodes["cluster:core"].label.endswith("3 files")
    edge = next(arrow for arrow in overview.file_arrows if arrow.target == "cluster:core")
    assert edge.source == "cluster:app" and edge.counts == {EdgeKind.CALLS: 2, EdgeKind.IMPORTS: 1}
    assert all(arrow.source in overview.nodes and arrow.target in overview.nodes for arrow in overview.file_arrows)
    filtered = views.file_view_overview(layout, {"app/main.cpp", "core/b.cpp", "core/c.cpp"})
    assert set(filtered.nodes) == {"app/main.cpp", "cluster:core"}
    assert filtered.nodes["cluster:core"].label.endswith("2 files")
    assert not filtered.file_arrows  # Both inter-cluster relations target the hidden core/a.cpp.
    assert not views.file_view_overview(layout, set()).nodes
    assert layout == saved


def test_file_overview_groups_external_libraries_without_losing_relations() -> None:
    model = small_model()
    merge_external_names(model, "SDL", ["poll"])
    model.add_edge(Edge(EdgeKind.CALLS, "u:main", "external:SDL", "app/main.cpp", 5))
    layout = views.layout_file_view(model, clusters.cluster_files(model))
    overview = views.file_view_overview(layout, set(layout.nodes))
    assert "external:std" not in overview.nodes and "external:SDL" not in overview.nodes
    assert overview.nodes["external:overview"].label == "External libraries\n2 libraries"
    edge = next(arrow for arrow in overview.file_arrows if arrow.target == "external:overview")
    assert edge.source == "cluster:app" and edge.counts == {EdgeKind.CALLS: 2}
    filtered = views.file_view_overview(layout, set(layout.nodes) - {"external:SDL"})
    assert "external:std" in filtered.nodes and "external:overview" not in filtered.nodes


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


def test_call_view_multiple_library_roots_keep_disconnected_apis_and_shared_callees() -> None:
    model = call_model()
    layout = views.layout_call_view(model, ("u:a", "u:b"), depth=1, selected="u:c")
    assert {usr: node.level for usr, node in layout.nodes.items()} == {
        "u:a": 0, "u:b": 0, "u:c": 1, "external:std": 1}
    assert layout.path == {"u:a", "u:c"}
    empty = views.layout_call_view(model, ())
    assert not empty.nodes and not empty.edges and not empty.path
