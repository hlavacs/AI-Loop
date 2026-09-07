"""File clusters: seeded label propagation, splitting, pins and names.

Connected components are not used: in a real project everything is reachable from ``main()``. Instead
every file starts with its directory as label, stays anchored to that directory with a pull of
``HOME_PULL`` times its own degree, and adopts a neighbouring label only when that label pulls at least
``HYSTERESIS`` times harder than its current one. The result follows the folder structure where the code
does, and the code where it does not; a file moves only on strong evidence. Deterministic throughout.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import networkx as nx

from icoda_core.model import DerivedModel, EdgeKind

EDGE_WEIGHTS = {EdgeKind.CALLS: 1.0, EdgeKind.USES_TYPE: 1.0, EdgeKind.INHERITS: 2.0, EdgeKind.IMPORTS: 1.0,
                EdgeKind.INCLUDES: 1.0}
HYSTERESIS = 1.5
HOME_PULL = 0.5
MAX_CLUSTER_SIZE = 40


@dataclass
class Cluster:
    id: str
    name: str
    files: list[str] = field(default_factory=list)


@dataclass
class Layout:
    """Developer choices that must survive re-clustering: cluster names and pinned files."""

    names: dict[str, str] = field(default_factory=dict)
    pins: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, dict[str, str]]:
        return {"names": dict(self.names), "pins": dict(self.pins)}

    @classmethod
    def from_dict(cls, data: dict[str, dict[str, str]]) -> Layout:
        return cls(dict(data.get("names", {})), dict(data.get("pins", {})))


@dataclass
class Clustering:
    clusters: list[Cluster]

    def cluster_of(self, file: str) -> Cluster | None:
        return next((c for c in self.clusters if file in c.files), None)

    def index_of(self, file: str) -> int:
        return next((i for i, c in enumerate(self.clusters) if file in c.files), -1)


def file_graph(model: DerivedModel) -> nx.Graph:
    """Undirected weighted graph of the project files; external nodes are left out."""
    graph = nx.Graph()
    graph.add_nodes_from(sorted(model.files))
    for (source, target, kind), count in model.file_edges().items():
        weight = EDGE_WEIGHTS.get(kind, 1.0) * count
        if graph.has_edge(source, target):
            graph[source][target]["weight"] += weight
        else:
            graph.add_edge(source, target, weight=weight)
    return graph


def directory_seed(file: str) -> str:
    parent = PurePosixPath(file).parent.as_posix()
    return "." if parent == "" else parent


def seeded_label_propagation(graph: nx.Graph, seeds: dict[str, str], iterations: int = 50,
                             hysteresis: float = HYSTERESIS, home: float = HOME_PULL) -> dict[str, str]:
    """Each node keeps its label unless another label's neighbours pull ``hysteresis`` times harder."""
    labels = dict(seeds)
    for _ in range(iterations):
        changed = False
        for node in sorted(graph.nodes):
            pull: dict[str, float] = defaultdict(float)
            for neighbour, data in graph[node].items():
                pull[labels[neighbour]] += data.get("weight", 1.0)
            if not pull:
                continue
            pull[seeds[node]] += home * sum(d.get("weight", 1.0) for d in graph[node].values())
            best = min(pull, key=lambda label: (-pull[label], label))
            if best != labels[node] and pull[best] >= hysteresis * pull.get(labels[node], 0.0):
                labels[node] = best
                changed = True
        if not changed:
            break
    return labels


def split_large(labels: dict[str, str], max_size: int = MAX_CLUSTER_SIZE) -> dict[str, str]:
    """Split any label group above ``max_size`` into numbered chunks of sorted files."""
    groups: dict[str, list[str]] = defaultdict(list)
    for file in sorted(labels):
        groups[labels[file]].append(file)
    result = dict(labels)
    for label, files in groups.items():
        if len(files) <= max_size:
            continue
        for index, file in enumerate(files):
            result[file] = f"{label}#{index // max_size + 1}"
    return result


def cluster_files(model: DerivedModel, layout: Layout | None = None, max_size: int = MAX_CLUSTER_SIZE) -> Clustering:
    """Cluster the project's files; pins and names from ``layout`` are applied last."""
    layout = layout or Layout()
    graph = file_graph(model)
    seeds = {file: directory_seed(file) for file in graph.nodes}
    labels = split_large(seeded_label_propagation(graph, seeds), max_size)
    for file, cluster_id in layout.pins.items():
        if file in labels:
            labels[file] = cluster_id
    return Clustering(_build_clusters(labels, layout))


def _build_clusters(labels: dict[str, str], layout: Layout) -> list[Cluster]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for file in sorted(labels):
        grouped[labels[file]].append(file)
    clusters = []
    for cluster_id in sorted(grouped):
        default_name = PurePosixPath(cluster_id).name or cluster_id
        clusters.append(Cluster(cluster_id, layout.names.get(cluster_id, default_name), grouped[cluster_id]))
    return clusters
