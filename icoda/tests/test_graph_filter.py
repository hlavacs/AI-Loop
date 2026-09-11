"""Pure shared graph filter and neighbourhood derivation tests."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from icoda_core import graph_filter
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind
from icoda_core.node_status import NodeAppearance


def _facts() -> tuple[DerivedModel, graph_filter.Graph, dict[str, NodeAppearance]]:
    model = DerivedModel(".")
    model.files["src/ui.cpp"] = FileInfo("src/ui.cpp")
    model.files["src/core.cpp"] = FileInfo("src/core.cpp")
    model.add_entity(Entity("u:root", Kind.FUNCTION, "render_all", "ui::render_all", "src/ui.cpp", 1))
    model.add_entity(Entity("u:near", Kind.METHOD, "paint", "ui::Panel::paint", "src/ui.cpp", 4))
    model.add_entity(Entity("u:far", Kind.CLASS, "Store", "core::Store", "src/core.cpp", 1))
    model.add_entity(Entity("u:stale", Kind.FUNCTION, "load", "core::load", "src/core.cpp", 8))
    model.add_edge(Edge(EdgeKind.CALLS, "u:root", "u:near"))
    model.add_edge(Edge(EdgeKind.USES_TYPE, "u:near", "u:far"))
    model.add_edge(Edge(EdgeKind.CALLS, "u:far", "u:stale"))
    clusters = {"src/ui.cpp": "presentation", "src/core.cpp": "engine"}
    graph = graph_filter.project_graph(model, clusters)
    appearances = {
        "u:root": NodeAppearance(status="tested", covered=True),
        "u:near": NodeAppearance(status="implemented", covered=False),
        "u:far": NodeAppearance(),
        "u:stale": NodeAppearance(status="stub", stale=True, covered=False),
    }
    return model, graph, appearances


def _derive(criteria: graph_filter.FilterDescription | None = None, *,
            focus: str | None = None, depth: int = 0) -> graph_filter.NodeDecisionMap:
    model, graph, appearances = _facts()
    return graph_filter.derive(model, graph, appearances, criteria or graph_filter.FilterDescription(),
                               focus_usr=focus, neighborhood_depth=depth)


def _visible(decisions: graph_filter.NodeDecisionMap) -> set[str]:
    return {usr for usr in ("u:root", "u:near", "u:far", "u:stale") if not decisions[usr].hidden}


def test_empty_model_and_graph_return_frozen_empty_mapping() -> None:
    decisions = graph_filter.derive(DerivedModel("."), graph_filter.Graph(), MappingProxyType({}))
    assert dict(decisions) == {}
    with pytest.raises(TypeError):
        decisions["u:new"] = graph_filter.NodeDecision()  # type: ignore[index]


def test_empty_filter_hides_and_dims_nothing() -> None:
    decisions = _derive()
    assert _visible(decisions) == {"u:root", "u:near", "u:far", "u:stale"}
    assert all(decision.matched_by_filter and not decision.dimmed for decision in decisions.values())


@pytest.mark.parametrize(("criteria", "expected"), [
    (graph_filter.FilterDescription(name="paint"), {"u:near"}),
    (graph_filter.FilterDescription(kind="class"), {"u:far"}),
    (graph_filter.FilterDescription(status="stub"), {"u:stale"}),
    (graph_filter.FilterDescription(covered=True), {"u:root"}),
    (graph_filter.FilterDescription(covered=False), {"u:near", "u:stale"}),
    (graph_filter.FilterDescription(stale=True), {"u:stale"}),
])
def test_each_required_filter_criterion_in_isolation(
        criteria: graph_filter.FilterDescription, expected: set[str]) -> None:
    assert _visible(_derive(criteria)) == expected


def test_two_criteria_are_combined_with_and() -> None:
    criteria = graph_filter.FilterDescription(kind="function", covered=False)
    assert _visible(_derive(criteria)) == {"u:stale"}


def test_filter_matching_nothing_hides_every_node() -> None:
    assert _visible(_derive(graph_filter.FilterDescription(name="does-not-exist"))) == set()


def test_plan_cluster_namespace_and_edge_type_filters() -> None:
    assert _visible(_derive(graph_filter.FilterDescription(cluster="presentation"))) == {"u:root", "u:near"}
    assert _visible(_derive(graph_filter.FilterDescription(namespace="core"))) == {"u:far", "u:stale"}
    assert _visible(_derive(graph_filter.FilterDescription(edge_type="uses-type"))) == {"u:near", "u:far"}


def test_no_focus_dims_nothing() -> None:
    assert not any(decision.dimmed for decision in _derive(focus=None, depth=2).values())


def test_depth_one_and_two_use_existing_edges_as_undirected_neighborhood() -> None:
    depth_one = _derive(focus="u:root", depth=1)
    assert {usr for usr in ("u:root", "u:near", "u:far", "u:stale") if not depth_one[usr].dimmed} == {
        "u:root", "u:near"}
    depth_two = _derive(focus="u:root", depth=2)
    assert {usr for usr in ("u:root", "u:near", "u:far", "u:stale") if not depth_two[usr].dimmed} == {
        "u:root", "u:near", "u:far"}


def test_focus_usr_absent_from_graph_dims_nothing() -> None:
    assert not any(decision.dimmed for decision in _derive(focus="u:absent", depth=2).values())


def test_single_entry_parser_is_forgiving_and_explicit() -> None:
    assert graph_filter.parse(
        'name:"render all" kind:function status:tested covered:yes stale:fresh '
        "cluster:presentation namespace:ui edge:calls"
    ) == graph_filter.FilterDescription(
        "render all", "function", "tested", True, False, "presentation", "ui", "calls")
    assert graph_filter.parse('"unfinished filter') == graph_filter.FilterDescription(name='"unfinished filter')
