"""GUI-independent geometry for the File, Class, Call and mind-map views.

M1 provides the File View: one circle per cluster placed on a ring, the cluster's files on its
circumference with related files next to each other, merged arrows between files, thick aggregate
arrows between cluster centres, and one node per external library. The circles are geometry only —
they are never drawn — and a cluster with a single file has that file at its centre (radius 0).
Nothing here imports tkinter.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from icoda_core.clusters import Clustering
from icoda_core.model import CALLABLE_KINDS, DerivedModel, EdgeKind

ARROW_COLOURS = {EdgeKind.INCLUDES: "#8a8a8a", EdgeKind.IMPORTS: "#8a8a8a", EdgeKind.CALLS: "#1f77b4",
                 EdgeKind.INHERITS: "#2ca02c", EdgeKind.USES_TYPE: "#ff7f0e"}
KIND_INITIALS = {EdgeKind.INCLUDES: "i", EdgeKind.IMPORTS: "i", EdgeKind.CALLS: "c", EdgeKind.INHERITS: "h",
                 EdgeKind.USES_TYPE: "u"}
MIN_RADIUS = 70.0
FILE_SPACING = 26.0


@dataclass
class Node:
    id: str
    label: str
    x: float
    y: float
    cluster: str
    kind: str = "file"


@dataclass
class ClusterCircle:
    id: str
    name: str
    cx: float
    cy: float
    radius: float
    files: list[str] = field(default_factory=list)


@dataclass
class Arrow:
    """A merged relation: all edge kinds between the same two endpoints, with counts."""

    source: str
    target: str
    counts: dict[EdgeKind, int] = field(default_factory=dict)

    @property
    def weight(self) -> int:
        return sum(self.counts.values())

    @property
    def dominant(self) -> EdgeKind:
        return max(self.counts, key=lambda kind: (self.counts[kind], kind.value))

    @property
    def badge(self) -> str:
        return " ".join(f"{KIND_INITIALS[kind]}{count}" for kind, count in sorted(self.counts.items(),
                                                                                 key=lambda item: item[0].value))


@dataclass
class FileViewLayout:
    circles: list[ClusterCircle]
    nodes: dict[str, Node]
    file_arrows: list[Arrow]
    cluster_arrows: list[Arrow]
    width: float
    height: float


def circle_radius(file_count: int) -> float:
    """Radius of the arrangement; a single file sits at the centre, so its cluster has no radius."""
    if file_count <= 1:
        return 0.0
    return max(MIN_RADIUS, file_count * FILE_SPACING / (2 * math.pi) + 20)


def order_files(files: list[str], model: DerivedModel) -> list[str]:
    """Neighbours-first order along the circumference: a walk over the intra-cluster relations."""
    weight: dict[tuple[str, str], int] = defaultdict(int)
    for (source, target, _kind), count in model.file_edges().items():
        if source in files and target in files:
            weight[(source, target)] += count
            weight[(target, source)] += count
    degree = {f: sum(w for (a, _b), w in weight.items() if a == f) for f in files}
    remaining = sorted(files, key=lambda f: (-degree[f], f))
    ordered: list[str] = []
    while remaining:
        current = remaining.pop(0)
        ordered.append(current)
        while True:
            best = max(remaining, key=lambda f: (weight.get((current, f), 0), -remaining.index(f)), default=None)
            if best is None or weight.get((current, best), 0) == 0:
                break
            remaining.remove(best)
            ordered.append(best)
            current = best
    return ordered


def place_circles(clustering: Clustering, width: float, height: float) -> list[ClusterCircle]:
    """Clusters on a ring around the centre, the ring wide enough that circles do not touch."""
    radii = [circle_radius(len(c.files)) for c in clustering.clusters]
    count = len(radii)
    if count == 0:
        return []
    if count == 1:
        return [ClusterCircle(clustering.clusters[0].id, clustering.clusters[0].name, width / 2, height / 2,
                              radii[0], list(clustering.clusters[0].files))]
    ring = max(sum(max(2 * r, 60) + 40 for r in radii) / (2 * math.pi), max(radii) + 60)
    circles = []
    for index, (cluster, radius) in enumerate(zip(clustering.clusters, radii, strict=True)):
        angle = -math.pi / 2 + 2 * math.pi * index / count
        circles.append(ClusterCircle(cluster.id, cluster.name, width / 2 + ring * math.cos(angle),
                                     height / 2 + ring * math.sin(angle), radius, list(cluster.files)))
    return circles


def place_files(circle: ClusterCircle, model: DerivedModel) -> dict[str, Node]:
    nodes = {}
    ordered = order_files(circle.files, model)
    for index, file in enumerate(ordered):
        angle = -math.pi / 2 + 2 * math.pi * index / max(len(ordered), 1)
        nodes[file] = Node(file, file.rsplit("/", 1)[-1], circle.cx + circle.radius * math.cos(angle),
                           circle.cy + circle.radius * math.sin(angle), circle.id)
    return nodes


def place_externals(model: DerivedModel, width: float, height: float) -> dict[str, Node]:
    """External libraries in a row along the bottom edge."""
    libraries = sorted(model.externals)
    nodes = {}
    for index, library in enumerate(libraries):
        x = width * (index + 1) / (len(libraries) + 1)
        nodes[f"external:{library}"] = Node(f"external:{library}", library, x, height - 40, "", "external")
    return nodes


def merge_arrows(model: DerivedModel) -> list[Arrow]:
    """One arrow per (source file, target) with the counts of every relation kind between them."""
    merged: dict[tuple[str, str], Arrow] = {}
    for (source, target, kind), count in model.file_edges().items():
        merged.setdefault((source, target), Arrow(source, target)).counts[kind] = count
    for edge in model.edges:
        if edge.target.startswith("external:"):
            source_file = edge.source if edge.source in model.files else model.file_of(edge.source)
            if source_file is not None:
                arrow = merged.setdefault((source_file, edge.target), Arrow(source_file, edge.target))
                arrow.counts[edge.kind] = arrow.counts.get(edge.kind, 0) + 1
    return sorted(merged.values(), key=lambda a: (a.source, a.target))


def aggregate_to_clusters(arrows: list[Arrow], clustering: Clustering) -> list[Arrow]:
    """Arrows between different clusters summed per cluster pair; external targets keep their id."""
    merged: dict[tuple[str, str], Arrow] = {}
    for arrow in arrows:
        source_cluster = clustering.cluster_of(arrow.source)
        target_cluster = clustering.cluster_of(arrow.target)
        source_id = source_cluster.id if source_cluster else arrow.source
        target_id = target_cluster.id if target_cluster else arrow.target
        if source_id == target_id:
            continue
        aggregate = merged.setdefault((source_id, target_id), Arrow(source_id, target_id))
        for kind, count in arrow.counts.items():
            aggregate.counts[kind] = aggregate.counts.get(kind, 0) + count
    return sorted(merged.values(), key=lambda a: (a.source, a.target))


def layout_file_view(model: DerivedModel, clustering: Clustering, width: float = 1600.0,
                     height: float = 1000.0) -> FileViewLayout:
    circles = place_circles(clustering, width, height - 100)
    nodes: dict[str, Node] = {}
    for circle in circles:
        nodes.update(place_files(circle, model))
    nodes.update(place_externals(model, width, height))
    arrows = merge_arrows(model)
    return FileViewLayout(circles, nodes, arrows, aggregate_to_clusters(arrows, clustering), width, height)


def arrow_endpoints(a: Node, b: Node, margin: float = 12.0) -> tuple[float, float, float, float]:
    """Start and end of a straight arrow between two nodes, shortened so it does not cover the node markers."""
    dx, dy = b.x - a.x, b.y - a.y
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    return (a.x + ux * margin, a.y + uy * margin, b.x - ux * margin, b.y - uy * margin)


# --------------------------------------------------------------------------- Call View

COLUMN_WIDTH = 260.0
ROW_HEIGHT = 44.0
STATUS_COLOURS = {"stub": "#d9d9d9", "implemented": "#aec7e8", "tested": "#98df8a"}


@dataclass
class CallNode:
    usr: str
    label: str
    x: float
    y: float
    level: int
    status: str = "implemented"
    kind: str = "function"
    signature: str = ""
    brief: str = ""


@dataclass
class CallEdge:
    source: str
    target: str
    label: str = ""
    loop: bool = False  # recursion or a call back towards the root


@dataclass
class CallViewLayout:
    root: str
    nodes: dict[str, CallNode]
    edges: list[CallEdge]
    path: set[str]
    width: float
    height: float


def default_root(model: DerivedModel) -> str | None:
    """The USR of ``main`` — the one with the most callees when several units define one — else any function."""
    mains = [e for e in model.entities.values() if e.qualified_name == "main" and e.kind in CALLABLE_KINDS]
    if mains:
        return max(mains, key=lambda e: len(model.callees(e.usr))).usr
    callables = [e for e in model.entities.values() if e.kind in CALLABLE_KINDS]
    return callables[0].usr if callables else None


def layout_call_view(model: DerivedModel, root: str, depth: int = 3, callers: bool = False,
                     selected: str | None = None) -> CallViewLayout:
    """Breadth-first over the call graph from ``root``: one column per level, discovery order within a level."""
    levels: dict[str, int] = {root: 0}
    parents: dict[str, str] = {}
    queue = [root]
    while queue:
        usr = queue.pop(0)
        if levels[usr] >= depth:
            continue
        for edge in (model.callers(usr) if callers else model.callees(usr)):
            other = edge.source if callers else edge.target
            if other not in levels:
                levels[other] = levels[usr] + 1
                parents[other] = usr
                queue.append(other)
    nodes = _call_nodes(model, levels)
    edges = _call_edges(model, levels, callers)
    path = _path_to(parents, selected) if selected in levels else set()
    width = COLUMN_WIDTH * (max(levels.values()) + 1)
    height = ROW_HEIGHT * max(list(levels.values()).count(level) for level in set(levels.values()))
    return CallViewLayout(root, nodes, edges, path, width, height)


def _call_nodes(model: DerivedModel, levels: dict[str, int]) -> dict[str, CallNode]:
    per_level: dict[int, list[str]] = defaultdict(list)
    for usr, level in levels.items():
        per_level[level].append(usr)
    nodes: dict[str, CallNode] = {}
    for level, usrs in per_level.items():
        for row, usr in enumerate(usrs):
            entity = model.entities.get(usr)
            x, y = COLUMN_WIDTH * level + COLUMN_WIDTH / 2, ROW_HEIGHT * (row + 0.5)
            if entity is None:
                library = usr.split(":", 1)[1] if usr.startswith("external:") else usr
                nodes[usr] = CallNode(usr, library, x, y, level, kind="external")
            else:
                nodes[usr] = CallNode(usr, entity.qualified_name, x, y, level, entity.status, entity.kind.value,
                                      entity.signature, entity.brief)
    return nodes


def _call_edges(model: DerivedModel, levels: dict[str, int], callers: bool) -> list[CallEdge]:
    edges: list[CallEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in model.edges_of(EdgeKind.CALLS):
        if edge.source not in levels or edge.target not in levels:
            continue
        key = (edge.source, edge.target, edge.label)
        if key in seen:
            continue
        seen.add(key)
        forward = levels[edge.target] > levels[edge.source] if not callers else levels[edge.source] > levels[edge.target]
        edges.append(CallEdge(edge.source, edge.target, edge.label, loop=not forward))
    return edges


def _path_to(parents: dict[str, str], selected: str | None) -> set[str]:
    path: set[str] = set()
    current = selected
    while current is not None:
        path.add(current)
        current = parents.get(current)
    return path
