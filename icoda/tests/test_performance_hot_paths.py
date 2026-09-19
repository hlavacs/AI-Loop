"""Operation-count guards for the retained large-project benchmark hot paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from icoda_core import expansion, graph_filter, python_analysis, views
from icoda_core.clusters import Cluster, Clustering
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind


def _write_python_project(root: Path, module_count: int) -> None:
    for index in range(module_count):
        previous = f"from module_{index - 1:03d} import bridge_{index - 1:03d}\n" if index else ""
        previous_call = f" + bridge_{index - 1:03d}(value)" if index else ""
        (root / f"module_{index:03d}.py").write_text(
            f"{previous}"
            f"class Service{index:03d}:\n"
            "    def first(self, value: int) -> int:\n"
            "        return self.second(value)\n\n"
            "    def second(self, value: int) -> int:\n"
            "        return value + 1\n\n"
            f"def bridge_{index:03d}(value: int) -> int:\n"
            f"    service = Service{index:03d}()\n"
            f"    return service.first(value){previous_call}\n",
            encoding="utf-8",
        )


def _layout_facts(size: int) -> tuple[DerivedModel, Clustering]:
    model = DerivedModel("/project")
    clusters = []
    for index in range(size):
        file = f"package_{index:03d}/module.py"
        usr = f"u:{index}"
        model.files[file] = FileInfo(file)
        model.add_entity(Entity(usr, Kind.FUNCTION, str(index), str(index), file, 1))
        clusters.append(Cluster(f"cluster-{index}", f"Cluster {index}", [file]))
        if index:
            model.add_edge(Edge(EdgeKind.CALLS, f"u:{index - 1}", usr))
    return model, Clustering(clusters)


def test_python_analysis_edge_deduplication_work_stays_linear(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    original = python_analysis._add_edge
    calls = 0

    def counted(context: Any, edge: Edge) -> None:
        nonlocal calls
        calls += 1
        original(context, edge)

    def forbid_rebuilt_edge_set(_model: DerivedModel) -> set[Edge]:
        raise AssertionError("parse_project must use its per-call edge index")

    monkeypatch.setattr(python_analysis, "_add_edge", counted)
    monkeypatch.setattr(DerivedModel, "_edge_set", forbid_rebuilt_edge_set)
    counts = []
    for module_count in (12, 24):
        project = tmp_path / str(module_count)
        project.mkdir()
        _write_python_project(project, module_count)
        before = calls
        model = python_analysis.parse_project(project)
        counts.append(calls - before)
        assert len(model.edges) == counts[-1]
    assert counts[1] <= counts[0] * 2.1


def test_file_layout_builds_relation_indexes_once(monkeypatch: Any) -> None:
    original = DerivedModel.file_edges
    calls = 0

    def counted(model: DerivedModel) -> dict[tuple[str, str, EdgeKind], int]:
        nonlocal calls
        calls += 1
        return original(model)

    monkeypatch.setattr(DerivedModel, "file_edges", counted)
    counts = []
    for size in (12, 24):
        model, clustering = _layout_facts(size)
        before = calls
        views.layout_file_view(model, clustering)
        counts.append(calls - before)
    assert counts == [1, 1]


def test_file_order_degree_index_scans_weight_once(monkeypatch: Any) -> None:
    original = views._degree_index
    scanned_pairs = 0

    def counted(files: list[str], weight: dict[tuple[str, str], int]) -> dict[str, int]:
        nonlocal scanned_pairs
        scanned_pairs += len(weight)
        return original(files, weight)

    monkeypatch.setattr(views, "_degree_index", counted)
    counts = []
    for size in (12, 24):
        files = [f"module_{index:03d}.py" for index in range(size)]
        file_edges = {
            (files[index - 1], files[index], EdgeKind.CALLS): 1
            for index in range(1, size)
        }
        before = scanned_pairs
        views._order_files(files, file_edges)
        counts.append(scanned_pairs - before)
    assert counts == [22, 46]


def test_expansion_graph_membership_uses_one_set_index(monkeypatch: Any) -> None:
    original = expansion._in_graph
    calls = 0
    indexed = True

    def counted(graph_nodes: frozenset[str], usr: str) -> bool:
        nonlocal calls, indexed
        calls += 1
        indexed = indexed and isinstance(graph_nodes, frozenset)
        return original(graph_nodes, usr)

    monkeypatch.setattr(expansion, "_in_graph", counted)
    counts = []
    for size in (12, 24):
        model, clustering = _layout_facts(size)
        cluster_by_file = {
            file: cluster.id
            for cluster in clustering.clusters
            for file in cluster.files
        }
        graph = graph_filter.project_graph(model, cluster_by_file)
        decisions = graph_filter.derive(model, graph, {})
        before = calls
        expansion.derive(model, graph, decisions, {}, frozenset(graph.nodes))
        counts.append(calls - before)
    assert indexed
    assert counts == [12, 24]
