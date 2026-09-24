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

from icoda_core import diagram_partition
from icoda_core.model import DerivedModel, EdgeKind

EDGE_WEIGHTS = {EdgeKind.CALLS: 1.0, EdgeKind.USES_TYPE: 1.0, EdgeKind.INHERITS: 2.0, EdgeKind.IMPORTS: 1.0,
                EdgeKind.INCLUDES: 1.0}
HYSTERESIS = 1.5
HOME_PULL = 0.5
MAX_CLUSTER_SIZE = diagram_partition.MAX_GROUP_SIZE
LOUVAIN_SEED = 0
SEEDED_LABEL_PROPAGATION = "seeded_label_propagation"
LOUVAIN = "louvain"


@dataclass
class Cluster:
    id: str
    name: str
    files: list[str] = field(default_factory=list)
    parent_id: str | None = None


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


@dataclass(frozen=True)
class LayoutDecision:
    """One immutable, deterministic edit of the persisted cluster layout."""

    names: tuple[tuple[str, str], ...] = ()
    pins: tuple[tuple[str, str], ...] = ()
    changed: bool = False

    def to_layout(self) -> Layout:
        """Return the existing persistence value owned by :class:`Layout`."""
        return Layout(dict(self.names), dict(self.pins))


@dataclass(frozen=True)
class Clustering:
    clusters: list[Cluster]
    algorithm: str = SEEDED_LABEL_PROPAGATION

    def cluster_of(self, file: str) -> Cluster | None:
        return next((c for c in self.clusters if file in c.files), None)

    def index_of(self, file: str) -> int:
        return next((i for i, c in enumerate(self.clusters) if file in c.files), -1)


def cluster_is_pinned(layout: Layout, clustering: Clustering, cluster_id: str) -> bool:
    """Every member is pinned to this cluster or to its oversized parent."""
    cluster = next((item for item in clustering.clusters if item.id == cluster_id), None)
    if cluster is None or not cluster.files:
        return False
    return all(layout.pins.get(file) in {cluster_id, cluster.parent_id} and file in layout.pins
               for file in cluster.files)


def pin_cluster(layout: Layout, clustering: Clustering, cluster_id: str) -> LayoutDecision:
    """Record every current file in ``cluster_id`` so later clustering reapplies that membership."""
    cluster = next((item for item in clustering.clusters if item.id == cluster_id), None)
    pins = dict(layout.pins)
    if cluster is not None:
        pins.update((file, cluster_id) for file in sorted(cluster.files))
    return _layout_decision(layout, layout.names, pins)


def pin_file(layout: Layout, clustering: Clustering, file: str, target_cluster_id: str) -> LayoutDecision:
    """Record one current file against one current target cluster, or refuse an unknown selection."""
    files = {item for cluster in clustering.clusters for item in cluster.files}
    cluster_ids = {cluster.id for cluster in clustering.clusters}
    pins = dict(layout.pins)
    if file in files and target_cluster_id in cluster_ids:
        pins[file] = target_cluster_id
    return _layout_decision(layout, layout.names, pins)


def unpin_file(layout: Layout, file: str) -> LayoutDecision:
    """Remove one file pin while leaving every other pin and cluster name unchanged."""
    pins = dict(layout.pins)
    pins.pop(file, None)
    return _layout_decision(layout, layout.names, pins)


def unpin_cluster(layout: Layout, cluster_id: str, clustering: Clustering | None = None) -> LayoutDecision:
    """Unpin a cluster or one displayed child of an oversized pinned cluster."""
    members = {file for cluster in clustering.clusters for file in cluster.files if cluster.id == cluster_id} \
        if clustering is not None else set()
    pins = {file: target for file, target in layout.pins.items() if target != cluster_id and file not in members}
    return _layout_decision(layout, layout.names, pins)


def rename_cluster(layout: Layout, cluster_id: str, name: str) -> LayoutDecision:
    """Set one non-empty display name while leaving stable cluster ids and memberships unchanged."""
    names = dict(layout.names)
    cleaned = name.strip()
    if cleaned:
        names[cluster_id] = cleaned
    return _layout_decision(layout, names, layout.pins)


def _layout_decision(layout: Layout, names: dict[str, str], pins: dict[str, str]) -> LayoutDecision:
    sorted_names = tuple(sorted(names.items()))
    sorted_pins = tuple(sorted(pins.items()))
    changed = sorted_names != tuple(sorted(layout.names.items())) or sorted_pins != tuple(sorted(layout.pins.items()))
    return LayoutDecision(sorted_names, sorted_pins, changed)


def file_graph(model: DerivedModel) -> nx.Graph:
    """Undirected weighted graph of the project files; external nodes are left out."""
    graph = nx.Graph()
    graph.add_nodes_from(sorted(model.files))
    edges = sorted(model.file_edges().items(), key=lambda item: (item[0][0], item[0][1], item[0][2].value))
    for (source, target, kind), count in edges:
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


def split_large(labels: dict[str, str], max_size: int = MAX_CLUSTER_SIZE,
                graph: nx.Graph | None = None, hints: diagram_partition.Topics | None = None) -> dict[str, str]:
    """Refine oversized groups using relationships and themes, with a deterministic size bound."""
    if max_size < 1:
        raise ValueError("max_size must be positive")
    groups: dict[str, list[str]] = defaultdict(list)
    for file in sorted(labels):
        groups[labels[file]].append(file)
    if graph is None:
        graph = nx.Graph()
        graph.add_nodes_from(labels)
    hints = hints or {file: diagram_partition.topics(file) for file in labels}
    result = dict(labels)
    used = set(labels.values())
    for label, files in sorted(groups.items()):
        if len(files) <= max_size:
            continue
        parts = diagram_partition.split(graph.subgraph(files), hints, max_size)
        index = 1
        for part in parts:
            while f"{label}#{index}" in used:
                index += 1
            key = f"{label}#{index}"
            used.add(key)
            result.update((file, key) for file in part)
    return result


def _needs_louvain(graph: nx.Graph, labels: dict[str, str]) -> bool:
    """Return whether propagation collapsed a graph too large for one meaningful circle."""
    return graph.number_of_nodes() > MAX_CLUSTER_SIZE and len(set(labels.values())) == 1


def _louvain_labels(graph: nx.Graph, seeds: dict[str, str]) -> dict[str, str] | None:
    """Return fixed-seed Louvain communities with stable directory-derived labels, if available."""
    detect = getattr(nx.algorithms.community, "louvain_communities", None)
    if detect is None or not graph.number_of_edges():
        return None
    communities = sorted(tuple(sorted(community))
                         for community in detect(graph, weight="weight", seed=LOUVAIN_SEED))
    bases: list[str] = []
    for community in communities:
        counts: dict[str, int] = defaultdict(int)
        for file in community:
            counts[seeds[file]] += 1
        bases.append(min(counts, key=lambda label: (-counts[label], label)))
    totals: dict[str, int] = defaultdict(int)
    for base in bases:
        totals[base] += 1
    occurrences: dict[str, int] = defaultdict(int)
    labels: dict[str, str] = {}
    for community, base in zip(communities, bases, strict=True):
        occurrences[base] += 1
        label = base if totals[base] == 1 else f"{base}#{occurrences[base]}"
        labels.update((file, label) for file in community)
    return labels


def cluster_files(model: DerivedModel, layout: Layout | None = None, max_size: int = MAX_CLUSTER_SIZE) -> Clustering:
    """Cluster files, apply saved choices, then refine oversized groups without dropping their pins."""
    layout = layout or Layout()
    graph = file_graph(model)
    seeds = {file: directory_seed(file) for file in graph.nodes}
    labels = seeded_label_propagation(graph, seeds)
    algorithm = SEEDED_LABEL_PROPAGATION
    if _needs_louvain(graph, labels):
        fallback_labels = _louvain_labels(graph, seeds)
        if fallback_labels is not None:
            labels = fallback_labels
            algorithm = LOUVAIN
    for file, cluster_id in layout.pins.items():
        if file in labels:
            labels[file] = cluster_id
    parents = dict(labels)
    hints = {file: diagram_partition.topics(file, model.files[file].module) for file in labels}
    labels = split_large(labels, max_size, graph, hints)
    return Clustering(_build_clusters(labels, layout, parents, hints), algorithm)


def _build_clusters(labels: dict[str, str], layout: Layout, parents: dict[str, str],
                    hints: diagram_partition.Topics) -> list[Cluster]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for file in sorted(labels):
        grouped[labels[file]].append(file)
    clusters = []
    for cluster_id in sorted(grouped):
        default_name = PurePosixPath(cluster_id).name or cluster_id
        files = grouped[cluster_id]
        parent = parents[files[0]] if parents[files[0]] != cluster_id else None
        if "#" in cluster_id:
            base = parent or cluster_id.split("#", 1)[0]
            title = layout.names.get(base, PurePosixPath(base).name or base)
            topic = diagram_partition.theme(files, hints, sorted(labels))
            default_name = f"{title} / {topic} ({cluster_id.rsplit('#', 1)[1]})"
        clusters.append(Cluster(cluster_id, layout.names.get(cluster_id, default_name), files, parent))
    return clusters
