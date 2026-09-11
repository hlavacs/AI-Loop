"""Pure shared hierarchy expansion and edge aggregation tests."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from icoda_core import expansion, graph_filter
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, External, FileInfo, Kind
from icoda_core.node_status import NodeAppearance


def _facts() -> tuple[DerivedModel, graph_filter.Graph, graph_filter.NodeDecisionMap,
                      dict[str, NodeAppearance]]:
    model = DerivedModel(".")
    model.files["src/widget.cpp"] = FileInfo("src/widget.cpp")
    model.files["src/worker.cpp"] = FileInfo("src/worker.cpp")
    model.add_entity(Entity("u:widget", Kind.CLASS, "Widget", "app::Widget", "src/widget.cpp", 1))
    model.add_entity(Entity("u:run", Kind.METHOD, "run", "app::Widget::run", "src/widget.cpp", 3,
                            parent="u:widget", status="stub"))
    model.add_entity(Entity("u:helper", Kind.FUNCTION, "helper", "app::helper", "src/widget.cpp", 8,
                            status="tested"))
    model.add_entity(Entity("u:work", Kind.FUNCTION, "work", "app::work", "src/worker.cpp", 1,
                            status="tested"))
    model.add_edge(Edge(EdgeKind.CALLS, "u:run", "u:work", label="int"))
    model.add_edge(Edge(EdgeKind.CALLS, "u:helper", "u:work"))
    model.externals["std"] = External("std", ("std::string", "std::vector"))
    model.add_edge(Edge(EdgeKind.USES_TYPE, "u:run", "external:std"))
    graph = graph_filter.project_graph(
        model, {"src/widget.cpp": "ui", "src/worker.cpp": "engine"})
    appearances = {
        usr: NodeAppearance(status=entity.status if entity.kind in {Kind.FUNCTION, Kind.METHOD} else "")
        for usr, entity in model.entities.items()
    }
    decisions = graph_filter.derive(model, graph, appearances)
    return model, graph, decisions, appearances


def _derive(expanded: frozenset[str] = frozenset(), *, criteria: graph_filter.FilterDescription | None = None
            ) -> expansion.ExpansionResult:
    model, graph, decisions, appearances = _facts()
    if criteria is not None:
        decisions = graph_filter.derive(model, graph, appearances, criteria)
    return expansion.derive(model, graph, decisions, appearances, expanded)


def test_empty_model_returns_frozen_empty_result() -> None:
    model = DerivedModel(".")
    result = expansion.derive(model, graph_filter.Graph(), MappingProxyType({}), MappingProxyType({}))
    assert result.graph == expansion.ExpandedGraph()
    assert dict(result.decisions) == {}
    with pytest.raises(TypeError):
        result.decisions["new"] = None  # type: ignore[index,assignment]


def test_fully_collapsed_graph_has_only_clusters_and_external_libraries() -> None:
    result = _derive()
    assert result.graph.node_keys == {"cluster:engine", "cluster:ui", "external:std"}
    assert result.decisions["cluster:ui"].collapsed
    assert result.decisions["external:std"].collapsed
    assert result.graph.edges == (
        expansion.ExpandedEdge(EdgeKind.CALLS, "cluster:ui", "cluster:engine", 2, ("int",)),
        expansion.ExpandedEdge(EdgeKind.USES_TYPE, "cluster:ui", "external:std"),
    )


def test_one_and_two_levels_expand_from_cluster_to_file_to_class() -> None:
    one = _derive(frozenset({"cluster:ui"}))
    assert one.graph.node_keys == {
        "cluster:engine", "cluster:ui", "file:src/widget.cpp", "external:std"}
    assert one.decisions["cluster:ui"].expanded

    two = _derive(frozenset({"cluster:ui", "src/widget.cpp"}))
    assert two.graph.node_keys == {
        "cluster:engine", "cluster:ui", "file:src/widget.cpp", "entity:u:widget",
        "entity:u:helper", "external:std"}
    assert two.decisions["file:src/widget.cpp"].expanded


def test_collapsing_again_returns_exactly_the_original_collapsed_graph() -> None:
    collapsed = _derive()
    assert _derive(frozenset({"cluster:ui", "file:src/widget.cpp"})).graph != collapsed.graph
    assert _derive().graph == collapsed.graph


def test_three_levels_reveal_class_members_and_reuse_their_appearance() -> None:
    result = _derive(frozenset({"cluster:ui", "file:src/widget.cpp", "u:widget"}))
    assert "entity:u:run" in result.graph.node_keys
    decision = result.decisions["entity:u:run"]
    assert decision.appearance is not None and decision.appearance.status == "stub"


def test_container_without_children_and_unknown_or_leaf_state_entries_are_inert() -> None:
    model, graph, decisions, appearances = _facts()
    model.files["src/empty.cpp"] = FileInfo("src/empty.cpp")
    graph = graph_filter.project_graph(model, {
        "src/widget.cpp": "ui", "src/worker.cpp": "engine", "src/empty.cpp": "empty"})
    decisions = graph_filter.derive(model, graph, appearances)
    result = expansion.derive(
        model, graph, decisions, appearances,
        frozenset({"file:src/empty.cpp", "entity:u:helper", "unknown:key"}))
    assert not result.decisions["file:src/empty.cpp"].expandable
    assert result.expanded == frozenset()
    assert result.graph.node_keys == {"cluster:empty", "cluster:engine", "cluster:ui", "external:std"}


def test_external_without_referenced_symbols_stays_readable_and_inert() -> None:
    model = DerivedModel(".", externals={"fmt": External("fmt")})
    graph = graph_filter.project_graph(model)
    decisions = graph_filter.derive(model, graph, MappingProxyType({}))
    result = expansion.derive(
        model, graph, decisions, MappingProxyType({}), frozenset({"external:fmt"}))
    assert result.graph.node_keys == {"external:fmt"}
    assert result.decisions["external:fmt"].is_container
    assert not result.decisions["external:fmt"].expandable
    assert result.expanded == frozenset()


def test_expanded_external_library_reveals_only_used_names_as_synthetic_leaves() -> None:
    result = _derive(frozenset({"external:std"}))
    children = result.decisions["external:std"].children
    assert len(children) == 2
    assert {result.decisions[key].synthetic for key in children} == {True}
    assert {node.label for node in result.graph.nodes if node.key in children} == {
        "std::string", "std::vector"}
    assert all(not result.decisions[key].is_container for key in children)


def test_expanded_container_with_all_children_filtered_out_remains_visible() -> None:
    result = _derive(
        frozenset({"cluster:ui", "file:src/widget.cpp", "entity:u:widget"}),
        criteria=graph_filter.FilterDescription(kind="class"))
    assert result.decisions["entity:u:widget"].visible
    assert result.decisions["entity:u:widget"].expanded
    assert not result.decisions["entity:u:run"].visible
    assert "entity:u:widget" in result.graph.node_keys
    assert "entity:u:run" not in result.graph.node_keys
