"""Bounded diagram groups retain relationships, themes, and navigation."""

import tkinter as tk
from collections import Counter

import networkx as nx
import pytest

from icoda_core import clusters, diagram_partition, views
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind
from icoda_gui.class_view import ClassViewCanvas


def themed_classes(count=60):
    model = DerivedModel("/themes")
    model.files["src/all.cpp"] = FileInfo("src/all.cpp")
    arrows = []
    for theme in ("Render", "Audio", "Physics"):
        for index in range(count):
            usr = f"{index:03}:{theme}"
            model.add_entity(Entity(usr, Kind.CLASS, f"{theme}Item{index}",
                                    f"app::{theme}::Item{index}", "src/all.cpp", index + 1))
            for previous in range(index):
                other = f"{previous:03}:{theme}"
                model.add_edge(Edge(EdgeKind.USES_TYPE, usr, other))
                arrows.append(views.Arrow(usr, other, {EdgeKind.USES_TYPE: 1}))
    grouping = clusters.Clustering([clusters.Cluster("src", "Application", ["src/all.cpp"])])
    return model, grouping, arrows


def test_hundreds_of_classes_in_one_file_are_bounded_and_thematic():
    model, grouping, arrows = themed_classes()
    layout, groups = views.entity_view_overview(model, grouping, set(model.entities), arrows, "classes")
    assert Counter(usr for group in groups.values() for usr in group) == Counter(model.entities.keys())
    assert max(map(len, groups.values())) <= diagram_partition.MAX_GROUP_SIZE
    assert all(len({model.entities[usr].qualified_name.split("::")[1] for usr in group}) == 1
               for group in groups.values())
    assert all("Application / " in node.label for node in layout.nodes.values())
    assert {arrow.source for arrow in layout.file_arrows} <= set(groups)
    assert {arrow.target for arrow in layout.file_arrows} <= set(groups)


def test_dense_graph_uses_namespaces_when_community_detection_has_no_theme():
    nodes = [f"{index:03}:{theme}" for theme in ("Render", "Audio", "Physics") for index in range(20)]
    graph = nx.complete_graph(nodes)
    hints = {node: diagram_partition.topics("all.cpp", "app::" + node.split(":")[1] + "::Item")
             for node in nodes}
    groups = diagram_partition.split(graph, hints)
    assert {frozenset(group) for group in groups} == {
        frozenset(node for node in nodes if node.endswith(":" + theme)) for theme in ("Render", "Audio", "Physics")}


@pytest.mark.parametrize("shape", ["clique", "star", "isolated"])
def test_bounded_fallback_has_no_loss_duplicates_or_insertion_order_dependency(shape):
    graph = {"clique": nx.complete_graph, "star": lambda n: nx.star_graph(n - 1),
             "isolated": nx.empty_graph}[shape](123)
    graph = nx.relabel_nodes(graph, lambda n: f"node{n:03}")
    reversed_graph = nx.Graph()
    reversed_graph.add_nodes_from(reversed(list(graph)))
    reversed_graph.add_edges_from(reversed(list(graph.edges)))
    first = diagram_partition.split(graph, {})
    assert first == diagram_partition.split(reversed_graph, {})
    assert max(map(len, first)) <= 40
    assert sorted(node for group in first for node in group) == sorted(graph)


def test_every_large_file_cluster_gets_relationship_based_splits():
    model = DerivedModel("/p")
    for theme in ("render", "audio", "physics"):
        files = [f"src/{index:03}_{theme}.cpp" for index in range(20)]
        for file in files:
            model.files[file] = FileInfo(file)
        for i, source in enumerate(files):
            for target in files[i + 1:]:
                model.add_edge(Edge(EdgeKind.INCLUDES, source, target))
    model.files["other/extra.cpp"] = FileInfo("other/extra.cpp")
    result = clusters.cluster_files(model)
    groups = [group for group in result.clusters if group.id != "other"]
    assert len(groups) == 3
    assert all(len({file.split("_")[1] for file in group.files}) == 1 for group in groups)
    assert all(len(group.files) <= 40 for group in result.clusters)


def test_large_pinned_cluster_gets_bounded_children_and_can_unpin_one_child():
    model = DerivedModel("/p")
    for index in range(95):
        file = f"src/item{index}.cpp"
        model.files[file] = FileInfo(file)
    layout = clusters.Layout(names={"chosen": "Chosen"}, pins={file: "chosen" for file in model.files})
    result = clusters.cluster_files(model, layout)
    assert max(len(group.files) for group in result.clusters) <= 40
    assert all(group.parent_id == "chosen" and group.name.startswith("Chosen / ") for group in result.clusters)
    assert all(clusters.cluster_is_pinned(layout, result, group.id) for group in result.clusters)
    first = result.clusters[0]
    unpinned = clusters.unpin_cluster(layout, first.id, result).to_layout()
    assert set(unpinned.pins) == set(model.files) - set(first.files)
    assert len(layout.pins) == 95


def test_split_ids_do_not_collide_with_existing_groups():
    labels = {f"src/{index}.cpp": "src" for index in range(60)}
    labels["other.cpp"] = "src#1"
    result = clusters.split_large(labels)
    assert result["other.cpp"] == "src#1"
    assert all(result[file] != "src#1" for file in labels if file != "other.cpp")
    assert max(Counter(result.values()).values()) <= 40


def test_opening_each_class_group_stays_bounded_and_back_restores_overview():
    model, grouping, _ = themed_classes(35)
    view = ClassViewCanvas(tk.Tk(), lambda *_: None)
    view.group_clustering = grouping
    view.show(model)
    parent = view.scale, view.offset, view.fit_scale, view.user_zoomed
    assert view.overview
    for key, group in view.groups.items():
        view.open_group(key)
        assert set(view.layout.nodes) == group
        assert len(view.layout.nodes) <= 40
        view.back_to_overview()
        assert view.overview and (view.scale, view.offset, view.fit_scale, view.user_zoomed) == parent


def test_split_validates_limit_and_handles_empty_graph():
    assert diagram_partition.split(nx.Graph(), {}) == []
    with pytest.raises(ValueError):
        diagram_partition.split(nx.Graph(), {}, 0)
