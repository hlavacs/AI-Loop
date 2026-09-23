"""GUI-independent geometry for the File, Class, Call and mind-map views.

M1 provides the File View: one circle per cluster placed on a ring, the cluster's files on its
circumference with related files next to each other, merged arrows between files, thick aggregate
arrows between cluster centres, and one node per external library. The circles are geometry only —
they are never drawn — and a cluster with a single file has that file at its centre (radius 0).
Nothing here imports tkinter.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field, replace

from icoda_core import class_view, mind_map
from icoda_core.clusters import Clustering
from icoda_core.model import CALLABLE_KINDS, DerivedModel, EdgeKind, Entity, Kind

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
    return _order_files(files, model.file_edges())


def _order_files(files: list[str], file_edges: dict[tuple[str, str, EdgeKind], int]) -> list[str]:
    weight: dict[tuple[str, str], int] = defaultdict(int)
    file_set = set(files)
    for (source, target, _kind), count in file_edges.items():
        if source in file_set and target in file_set:
            weight[(source, target)] += count
            weight[(target, source)] += count
    degree = _degree_index(files, weight)
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


def _degree_index(files: list[str], weight: dict[tuple[str, str], int]) -> dict[str, int]:
    degree = {file: 0 for file in files}
    for (source, _target), count in weight.items():
        degree[source] += count
    return degree


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
    return _place_files(circle, model.file_edges())


def _place_files(circle: ClusterCircle,
                 file_edges: dict[tuple[str, str, EdgeKind], int]) -> dict[str, Node]:
    nodes = {}
    ordered = _order_files(circle.files, file_edges)
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
    return _merge_arrows(model, model.file_edges())


def _merge_arrows(model: DerivedModel,
                  file_edges: dict[tuple[str, str, EdgeKind], int]) -> list[Arrow]:
    merged: dict[tuple[str, str], Arrow] = {}
    for (source, target, kind), count in file_edges.items():
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
    cluster_by_file: dict[str, str] = {}
    for cluster in clustering.clusters:
        for file in cluster.files:
            cluster_by_file.setdefault(file, cluster.id)
    merged: dict[tuple[str, str], Arrow] = {}
    for arrow in arrows:
        source_id = cluster_by_file.get(arrow.source, arrow.source)
        target_id = cluster_by_file.get(arrow.target, arrow.target)
        if source_id == target_id:
            continue
        aggregate = merged.setdefault((source_id, target_id), Arrow(source_id, target_id))
        for kind, count in arrow.counts.items():
            aggregate.counts[kind] = aggregate.counts.get(kind, 0) + count
    return sorted(merged.values(), key=lambda a: (a.source, a.target))


def layout_file_view(model: DerivedModel, clustering: Clustering, width: float = 1600.0,
                     height: float = 1000.0) -> FileViewLayout:
    file_edges = model.file_edges()
    circles = place_circles(clustering, width, height - 100)
    nodes: dict[str, Node] = {}
    for circle in circles:
        nodes.update(_place_files(circle, file_edges))
    external_nodes = place_externals(model, width, height)
    if nodes:
        # Keep external libraries beside the actual file graph, not the bottom of an arbitrary 1000-unit page.
        left, right = min(node.x for node in nodes.values()), max(node.x for node in nodes.values())
        bottom = max(node.y for node in nodes.values())
        span = max(right - left, 160.0)
        for index, node in enumerate(external_nodes.values()):
            node.x = (left + right - span) / 2 + span * (index + 1) / (len(external_nodes) + 1)
            node.y = bottom + 90.0
    nodes.update(external_nodes)
    arrows = _merge_arrows(model, file_edges)
    return FileViewLayout(circles, nodes, arrows, aggregate_to_clusters(arrows, clustering), width, height)


def organise_file_view(layout: FileViewLayout,
                       sizes: dict[str, tuple[float, float]] | None = None) -> FileViewLayout:
    """Make room for file labels, then relax cluster centres using their relations.

    A bounded, deterministic spring calculation needs no numerical-library dependency. Cluster
    membership stays unchanged; dense clusters use compact rows and external libraries stay below the files.
    """
    if not layout.circles:
        return layout
    sizes = sizes or {key: (max(map(len, node.label.splitlines())) * 8.0 + 24.0,
                           len(node.label.splitlines()) * 18.0 + 18.0) for key, node in layout.nodes.items()}
    nodes = {key: replace(node) for key, node in layout.nodes.items()}
    circles = []
    radii = []
    for circle in layout.circles:
        members = [layout.nodes[file] for file in circle.files]
        if len(members) > 8:
            width = max(sizes[node.id][0] for node in members)
            height = max(sizes[node.id][1] for node in members)
            columns = max(1, math.ceil(math.sqrt(len(members) * height / width)))
            rows = math.ceil(len(members) / columns)
            for i, node in enumerate(members):
                row, column = divmod(i, columns)
                nodes[node.id] = replace(node, x=circle.cx + (column - (columns - 1) / 2) * width,
                                        y=circle.cy + (row - (rows - 1) / 2) * height)
            radius = math.hypot((columns - 1) * width, (rows - 1) * height) / 2
            circles.append(replace(circle, radius=radius))
            radii.append(radius + max(width, height) / 2)
            continue
        factor = 1.0
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                dx, dy = abs(a.x - b.x), abs(a.y - b.y)
                width, height = (sizes[a.id][0] + sizes[b.id][0]) / 2, (sizes[a.id][1] + sizes[b.id][1]) / 2
                factor = max(factor, min(width / dx if dx > .001 else math.inf,
                                         height / dy if dy > .001 else math.inf))
        for node in members:
            nodes[node.id] = replace(node, x=circle.cx + (node.x - circle.cx) * factor,
                                    y=circle.cy + (node.y - circle.cy) * factor)
        circles.append(replace(circle, radius=circle.radius * factor))
        radii.append(circles[-1].radius + max((max(sizes[n.id]) / 2 for n in members), default=0.0))
    layout = replace(layout, circles=circles, nodes=nodes)
    index = {circle.id: i for i, circle in enumerate(circles)}
    weights: dict[tuple[int, int], int] = defaultdict(int)
    for arrow in layout.cluster_arrows:
        if arrow.source in index and arrow.target in index:
            source_index, target_index = sorted((index[arrow.source], index[arrow.target]))
            weights[source_index, target_index] += arrow.weight
    positions = [[circle.cx, circle.cy] for circle in circles]
    centre_x = sum(p[0] for p in positions) / len(positions)
    centre_y = sum(p[1] for p in positions) / len(positions)
    for iteration in range(80):
        forces = [[(centre_x - x) * .01, (centre_y - y) * .01] for x, y in positions]
        for i, (x, y) in enumerate(positions):
            for j in range(i + 1, len(positions)):
                dx, dy = positions[j][0] - x, positions[j][1] - y
                distance = math.hypot(dx, dy)
                if distance < .001:
                    dx, dy, distance = 1.0, 0.0, 1.0
                spacing = radii[i] + radii[j] + 60.0
                force = 900.0 / distance + max(spacing - distance, 0.0) * .5
                force -= .1 * math.log1p(weights.get((i, j), 0)) * max(distance - spacing, 0.0)
                fx, fy = dx / distance * force, dy / distance * force
                forces[i][0] -= fx
                forces[i][1] -= fy
                forces[j][0] += fx
                forces[j][1] += fy
        step = max(20.0, max(radii) * .15) * (1.0 - iteration / 80) + .5
        for position, (fx, fy) in zip(positions, forces, strict=True):
            factor = min(1.0, step / max(math.hypot(fx, fy), .001))
            position[0] += fx * factor
            position[1] += fy * factor
    left = min(p[0] - c.radius for p, c in zip(positions, circles, strict=True)) - 80.0
    top = min(p[1] - c.radius for p, c in zip(positions, circles, strict=True)) - 80.0
    moved = [replace(circle, cx=x - left, cy=y - top)
             for circle, (x, y) in zip(circles, positions, strict=True)]
    offsets = {old.id: (new.cx - old.cx, new.cy - old.cy)
               for old, new in zip(circles, moved, strict=True)}
    nodes = {key: replace(node, x=node.x + offsets.get(node.cluster, (0.0, 0.0))[0],
                         y=node.y + offsets.get(node.cluster, (0.0, 0.0))[1])
             for key, node in layout.nodes.items()}
    right = max(circle.cx + circle.radius for circle in moved)
    bottom = max(circle.cy + circle.radius for circle in moved)
    externals = [node for node in nodes.values() if node.kind == "external"]
    for i, node in enumerate(externals):
        node.x = 80.0 + max(right - 80.0, 160.0) * (i + 1) / (len(externals) + 1)
        node.y = bottom + 90.0
    return replace(layout, circles=moved, nodes=nodes,
                   width=max([right, *(node.x for node in nodes.values())]) + 80.0,
                   height=bottom + (170.0 if externals else 80.0))


def file_view_group(layout: FileViewLayout, group: str) -> FileViewLayout:
    """Return one group's files and internal relationships without changing the complete graph."""
    if group.startswith("cluster:"):
        circle = next(circle for circle in layout.circles if circle.id == group.removeprefix("cluster:"))
        members = set(circle.files)
    elif group == "external:overview":
        members = {key for key, node in layout.nodes.items() if node.kind == "external"}
    else:
        members = {group}
    return replace(layout, nodes={key: node for key, node in layout.nodes.items() if key in members},
                   circles=[replace(circle, files=[file for file in circle.files if file in members])
                            for circle in layout.circles if any(file in members for file in circle.files)],
                   file_arrows=[arrow for arrow in layout.file_arrows
                                if arrow.source in members and arrow.target in members], cluster_arrows=[])


def file_view_overview(layout: FileViewLayout, visible: set[str]) -> FileViewLayout:
    """Summarise visible files by cluster and merge their relationships for a readable overview."""
    nodes = {key: node for key, node in layout.nodes.items() if key in visible}
    owners = {key: key for key in nodes}
    for circle in layout.circles:
        files = [file for file in circle.files if file in nodes]
        if len(files) < 2:
            continue
        key = f"cluster:{circle.id}"
        nodes[key] = Node(key, f"{circle.name}\n{len(files)} files", circle.cx, circle.cy, circle.id, "cluster")
        for file in files:
            owners[file] = key
            del nodes[file]
    external_ids = [key for key, node in nodes.items() if node.kind == "external"]
    if len(external_ids) > 1:
        key = "external:overview"
        nodes[key] = Node(key, f"External libraries\n{len(external_ids)} libraries", 0, 0, "", "external")
        for external in external_ids:
            owners[external] = key
            del nodes[external]
    merged: dict[tuple[str, str], Arrow] = {}
    for arrow in layout.file_arrows:
        if arrow.source not in owners or arrow.target not in owners:
            continue
        source, target = owners[arrow.source], owners[arrow.target]
        if source == target:
            continue
        aggregate = merged.setdefault((source, target), Arrow(source, target))
        for kind, count in arrow.counts.items():
            aggregate.counts[kind] = aggregate.counts.get(kind, 0) + count
    arrows = list(merged.values())
    # The overview has its own compact geometry; the expanded file circles would waste its space.
    summary_nodes, circles = {}, []
    for i, (key, node) in enumerate(nodes.items()):
        angle = 2 * math.pi * i / len(nodes)
        x, y = 80 * math.sqrt(len(nodes)) * math.cos(angle), 80 * math.sqrt(len(nodes)) * math.sin(angle)
        summary_nodes[key] = replace(node, x=x, y=y, cluster=key, kind="file")
        circles.append(ClusterCircle(key, node.label, x, y, 0.0, [key]))
    summary = organise_file_view(FileViewLayout(circles, summary_nodes, arrows, arrows, layout.width, layout.height))
    return replace(summary, circles=[], cluster_arrows=[], nodes={
        key: replace(node, x=summary.nodes[key].x, y=summary.nodes[key].y) for key, node in nodes.items()})


def entity_scope(model: DerivedModel, selected: Entity) -> list[Entity]:
    """Show one entity, including members of a selected class, namespace or enum."""
    scoped = {selected.usr: selected}
    if selected.kind in {Kind.CLASS, Kind.STRUCT, Kind.NAMESPACE, Kind.ENUM}:
        separator = "." if selected.file.endswith(".py") else "::"
        prefix = selected.qualified_name + separator
        for entity in model.entities.values():
            # Out-of-line C++ methods can have the namespace as their lexical parent.
            if entity.qualified_name.startswith(prefix):
                scoped[entity.usr] = entity
        children = defaultdict(list)
        for entity in model.entities.values():
            children[entity.parent].append(entity)
        pending = list(scoped)
        while pending:
            for entity in children[pending.pop()]:
                if entity.usr not in scoped:
                    scoped[entity.usr] = entity
                    pending.append(entity.usr)
    return sorted(scoped.values(), key=lambda entity: (entity.file, entity.line, entity.usr))


def entity_tree_label(entity: Entity) -> str:
    """Show one callable signature, using trailing return types for cached C++ declarations."""
    signature = entity.signature.strip()
    if not signature:
        return entity.name
    if entity.kind not in CALLABLE_KINDS:
        return f"{entity.name}  {signature}"
    if signature.startswith(("def ", "async def ")):
        return signature
    # The analyser stores '<result type> <display name>(...)'. Match the full name so operator()
    # and function-pointer types in the result or arguments are not mistaken for the parameter list.
    result, separator, arguments = signature.partition(f" {entity.name}(")
    if not separator:
        return signature
    declaration = f"{entity.name}({arguments}"
    if entity.kind in (Kind.CONSTRUCTOR, Kind.DESTRUCTOR):
        return declaration
    if result == "auto":
        return signature
    return f"auto {declaration} -> {result}"


def entity_location_label(entity: Entity) -> str:
    """Compact declaration/definition locations for existing view detail lines."""
    if entity.declaration_file and entity.declaration_file != entity.file:
        return f"declaration {entity.declaration_file} · definition {entity.file}"
    if not entity.is_definition:
        return f"declaration {entity.declaration_file or entity.file} · no definition"
    return f"definition {entity.file}"


def entity_purpose(entity: Entity) -> str:
    """The first sentence of the actual source documentation, for hover details."""
    text = " ".join(entity.brief.split())
    if not text:
        return "A purpose comment still needs to be added to the source."
    sentence = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text, maxsplit=1)[0]
    return sentence if sentence.endswith((".", "!", "?")) else sentence + "."


def compact_file_view(layout: FileViewLayout, columns: int, column_width: float,
                      row_height: float) -> FileViewLayout:
    """Pack the same files and relations into rows when labeled boxes overlap in a narrow pane."""
    columns = max(columns, 1)
    nodes = {node.id: replace(node, x=(index % columns + .5) * column_width,
                              y=(index // columns + .5) * row_height)
             for index, node in enumerate(layout.nodes.values())}
    rows = math.ceil(len(nodes) / columns)
    return FileViewLayout(layout.circles, nodes, layout.file_arrows, [],
                          columns * column_width, rows * row_height)


def arrow_endpoints(a: Node, b: Node, margin: float = 12.0) -> tuple[float, float, float, float]:
    """Start and end of a straight arrow between two nodes, shortened so it does not cover the node markers."""
    dx, dy = b.x - a.x, b.y - a.y
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    return (a.x + ux * margin, a.y + uy * margin, b.x - ux * margin, b.y - uy * margin)


# --------------------------------------------------------------------------- Class View

CLASS_PANEL_WIDTH = 320.0
CLASS_HEADER_HEIGHT = 48.0
CLASS_MEMBER_HEIGHT = 25.0
CLASS_PANEL_GAP = 80.0


@dataclass
class ClassNodeLayout:
    node: class_view.ClassNode
    x: float
    y: float
    width: float
    height: float


@dataclass
class ClassViewLayout:
    graph: class_view.ClassGraph
    nodes: dict[str, ClassNodeLayout]
    edges: tuple[class_view.ClassEdge, ...]
    width: float
    height: float


def layout_class_view(graph: class_view.ClassGraph) -> ClassViewLayout:
    """Place expanded class panels on a stable grid, leaving room for relation drawings."""
    if not graph.nodes:
        return ClassViewLayout(graph, {}, graph.edges, 1.0, 1.0)
    columns = max(1, math.ceil(math.sqrt(len(graph.nodes))))
    rows = math.ceil(len(graph.nodes) / columns)
    panel_height = max(_class_panel_height(node) for node in graph.nodes)
    width = columns * CLASS_PANEL_WIDTH + (columns + 1) * CLASS_PANEL_GAP
    height = rows * panel_height + (rows + 1) * CLASS_PANEL_GAP
    nodes: dict[str, ClassNodeLayout] = {}
    for index, node in enumerate(graph.nodes):
        row, column = divmod(index, columns)
        x = CLASS_PANEL_GAP + CLASS_PANEL_WIDTH / 2 + column * (CLASS_PANEL_WIDTH + CLASS_PANEL_GAP)
        y = CLASS_PANEL_GAP + panel_height / 2 + row * (panel_height + CLASS_PANEL_GAP)
        nodes[node.usr] = ClassNodeLayout(node, x, y, CLASS_PANEL_WIDTH, _class_panel_height(node))
    return ClassViewLayout(graph, nodes, graph.edges, width, height)


def _class_panel_height(node: class_view.ClassNode) -> float:
    return CLASS_HEADER_HEIGHT + max(len(node.members), 1) * CLASS_MEMBER_HEIGHT + 8.0


# --------------------------------------------------------------------------- Mind map

MIND_MAP_NODE_WIDTH = 260.0
MIND_MAP_NODE_HEIGHT = 36.0
MIND_MAP_COLUMN_GAP = 54.0
MIND_MAP_ROW_GAP = 14.0
MIND_MAP_MARGIN = 30.0


@dataclass(frozen=True)
class MindMapNodeLayout:
    node: mind_map.MindMapNode
    x: float
    y: float
    width: float
    height: float
    depth: int


@dataclass(frozen=True)
class MindMapEdgeLayout:
    source: str
    target: str


@dataclass(frozen=True)
class MindMapLayout:
    mind_map: mind_map.MindMap
    nodes: tuple[MindMapNodeLayout, ...]
    edges: tuple[MindMapEdgeLayout, ...]
    width: float
    height: float

    def node_map(self) -> dict[str, MindMapNodeLayout]:
        return {item.node.id: item for item in self.nodes}


def layout_mind_map(tree: mind_map.MindMap,
                    state: mind_map.MindMapViewState | None = None) -> MindMapLayout:
    """Lay out the visible pre-order tree; omitted expanded ids mean fully collapsed."""
    state = state or mind_map.MindMapViewState()
    visible = _visible_mind_map_nodes(tree, frozenset(state.expanded))
    nodes = tuple(_mind_map_node_layout(node, depth, row) for row, (node, depth, _parent) in enumerate(visible))
    edges = tuple(MindMapEdgeLayout(parent, node.id) for node, _depth, parent in visible if parent is not None)
    if not nodes:
        return MindMapLayout(tree, (), (), 1.0, 1.0)
    width = max(node.x + node.width / 2 for node in nodes) + MIND_MAP_MARGIN
    height = nodes[-1].y + MIND_MAP_NODE_HEIGHT / 2 + MIND_MAP_MARGIN
    return MindMapLayout(tree, nodes, edges, width, height)


def _visible_mind_map_nodes(tree: mind_map.MindMap, expanded: frozenset[str]
                            ) -> tuple[tuple[mind_map.MindMapNode, int, str | None], ...]:
    visible: list[tuple[mind_map.MindMapNode, int, str | None]] = []
    for root in tree.clusters:
        _append_visible(root, 0, None, expanded, visible)
    return tuple(visible)


def _append_visible(node: mind_map.MindMapNode, depth: int, parent: str | None,
                    expanded: frozenset[str], visible: list[tuple[mind_map.MindMapNode, int, str | None]]) -> None:
    visible.append((node, depth, parent))
    if node.id not in expanded:
        return
    for child in node.children:
        _append_visible(child, depth + 1, node.id, expanded, visible)


def _mind_map_node_layout(node: mind_map.MindMapNode, depth: int, row: int) -> MindMapNodeLayout:
    x = MIND_MAP_MARGIN + MIND_MAP_NODE_WIDTH / 2 + depth * (MIND_MAP_NODE_WIDTH + MIND_MAP_COLUMN_GAP)
    y = MIND_MAP_MARGIN + MIND_MAP_NODE_HEIGHT / 2 + row * (MIND_MAP_NODE_HEIGHT + MIND_MAP_ROW_GAP)
    return MindMapNodeLayout(node, x, y, MIND_MAP_NODE_WIDTH, MIND_MAP_NODE_HEIGHT, depth)


# --------------------------------------------------------------------------- Call View

COLUMN_WIDTH = 260.0
ROW_HEIGHT = 44.0
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
    uncertain: bool = False


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


def layout_call_view(model: DerivedModel, root: str | tuple[str, ...], depth: int = 3, callers: bool = False,
                     selected: str | None = None) -> CallViewLayout:
    """Breadth-first from one entry or a library's function set, one column per call depth."""
    roots = (root,) if isinstance(root, str) else root
    levels: dict[str, int] = dict.fromkeys(roots, 0)
    parents: dict[str, str] = {}
    queue = list(levels)
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
    width = COLUMN_WIDTH * (max(levels.values(), default=0) + 1)
    height = ROW_HEIGHT * max((list(levels.values()).count(level) for level in set(levels.values())), default=1)
    return CallViewLayout(roots[0] if roots else "", nodes, edges, path, width, height)


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
    seen: dict[tuple[str, str, str], CallEdge] = {}
    for edge in model.edges_of(EdgeKind.CALLS):
        if edge.source not in levels or edge.target not in levels:
            continue
        key = (edge.source, edge.target, edge.label)
        if key in seen:
            seen[key].uncertain = seen[key].uncertain or edge.uncertain
            continue
        forward = levels[edge.target] > levels[edge.source] if not callers else levels[edge.source] > levels[edge.target]
        call_edge = CallEdge(edge.source, edge.target, edge.label, loop=not forward, uncertain=edge.uncertain)
        seen[key] = call_edge
        edges.append(call_edge)
    return edges


def _path_to(parents: dict[str, str], selected: str | None) -> set[str]:
    path: set[str] = set()
    current = selected
    while current is not None:
        path.add(current)
        current = parents.get(current)
    return path
