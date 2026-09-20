"""Pure hierarchical expansion shared by the File, Call, and Class diagrams.

The model remains the source of hierarchy and edges.  This module only projects those
facts through the already-derived status/filter decisions and an explicit expansion
state; it never parses, filters, or computes status itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePath
from types import MappingProxyType

from icoda_core.graph_filter import Graph, NodeDecision, NodeDecisionMap
from icoda_core.model import DerivedModel, EdgeKind, Kind
from icoda_core.node_status import NodeAppearance, NodeAppearanceMap

CONTAINER_KINDS = frozenset({Kind.CLASS, Kind.STRUCT, Kind.ENUM})


@dataclass(frozen=True)
class ExpansionNode:
    """One canonical node in the project hierarchy."""

    key: str
    target_id: str
    label: str
    kind: str
    parent: str | None
    depth: int
    synthetic: bool = False


@dataclass(frozen=True)
class ExpandedEdge:
    """Existing model edges aggregated onto their currently visible endpoints."""

    kind: EdgeKind
    source: str
    target: str
    count: int = 1
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExpandedGraph:
    """The immutable visible graph produced for one explicit expansion state."""

    nodes: tuple[ExpansionNode, ...] = ()
    edges: tuple[ExpandedEdge, ...] = ()

    @property
    def node_keys(self) -> frozenset[str]:
        return frozenset(node.key for node in self.nodes)


@dataclass(frozen=True)
class ExpansionDecision:
    """Expansion and reused appearance decisions for one hierarchy node."""

    key: str
    parent: str | None
    children: tuple[str, ...]
    is_container: bool
    expandable: bool
    expanded: bool
    collapsed: bool
    visible: bool
    synthetic: bool
    graph_decision: NodeDecision
    appearance: NodeAppearance | None


ExpansionDecisionMap = Mapping[str, ExpansionDecision]


@dataclass(frozen=True)
class ExpansionResult:
    """A frozen expanded graph, its decisions, and accepted input state."""

    graph: ExpandedGraph
    decisions: ExpansionDecisionMap
    aliases: Mapping[str, str]
    expanded: frozenset[str]

    def decision_for(self, node_id: str) -> ExpansionDecision | None:
        return self.decisions.get(self.aliases.get(node_id, node_id))


@dataclass(frozen=True)
class _Hierarchy:
    nodes: Mapping[str, ExpansionNode]
    children: Mapping[str, tuple[str, ...]]
    aliases: Mapping[str, str]


def derive(model: DerivedModel, graph: Graph, decisions: NodeDecisionMap,
           appearances: NodeAppearanceMap, expanded: frozenset[str] = frozenset()) -> ExpansionResult:
    """Derive one immutable expansion projection without recomputing existing facts."""
    hierarchy = _hierarchy(model, graph)
    indexed_decisions = _index_decisions(hierarchy, decisions)
    accepted = frozenset(
        hierarchy.aliases.get(key, key) for key in expanded
        if _expandable(hierarchy, hierarchy.aliases.get(key, key))
    )
    visible = _visible_nodes(hierarchy, indexed_decisions, accepted)
    expansion_decisions = _decisions(hierarchy, indexed_decisions, appearances, accepted, visible)
    nodes = _ordered_visible_nodes(hierarchy, visible)
    edges = _expanded_edges(graph, hierarchy, expansion_decisions)
    return ExpansionResult(
        ExpandedGraph(nodes, edges), MappingProxyType(expansion_decisions),
        hierarchy.aliases, accepted)


def _ordered_visible_nodes(hierarchy: _Hierarchy, visible: frozenset[str]) -> tuple[ExpansionNode, ...]:
    """Keep each file/class and all its descendants together, including through filtered parents."""
    roots = [key for key, node in hierarchy.nodes.items() if node.parent not in hierarchy.nodes]
    pending = list(reversed(roots))
    ordered = []
    while pending:
        key = pending.pop()
        if key in visible:
            ordered.append(hierarchy.nodes[key])
        pending.extend(reversed(hierarchy.children[key]))
    return tuple(ordered)


def _hierarchy(model: DerivedModel, graph: Graph) -> _Hierarchy:
    nodes: dict[str, ExpansionNode] = {}
    aliases: dict[str, str] = {}
    graph_nodes = frozenset(graph.nodes)
    clusters = sorted(set(graph.cluster_by_file.values()))
    for cluster in clusters:
        _add_node(nodes, aliases, f"cluster:{cluster}", f"cluster:{cluster}",
                  graph.cluster_names.get(cluster, cluster),
                  "cluster", None, 0, (cluster,))
    for file in _graph_files(model, graph, graph_nodes):
        parent = f"cluster:{graph.cluster_by_file[file]}" if file in graph.cluster_by_file else None
        depth = 1 if parent else 0
        _add_node(nodes, aliases, f"file:{file}", file, PurePath(file).name,
                  "file", parent, depth, (file,))
    entities = tuple(entity for entity in sorted(
        model.entities.values(), key=lambda item: (item.file, item.line, item.usr))
        if entity.kind != Kind.NAMESPACE and _in_graph(graph_nodes, entity.usr))
    for entity in entities:
        _add_node(nodes, aliases, f"entity:{entity.usr}", entity.usr, entity.name,
                  entity.kind.value, None, 0, (entity.usr,))
    parents = {
        f"entity:{entity.usr}": _entity_parent(model, nodes, entity.usr) or aliases.get(entity.file)
        for entity in entities
    }
    for key, parent in parents.items():
        node = nodes[key]
        nodes[key] = ExpansionNode(
            node.key, node.target_id, node.label, node.kind, parent,
            _hierarchy_depth(key, nodes, parents), node.synthetic)
    for library, external in sorted(model.externals.items()):
        parent = f"external:{library}"
        _add_node(nodes, aliases, parent, parent, library, "external", None, 0)
        for index, name in enumerate(external.names):
            key = f"external-symbol:{library}:{index}"
            _add_node(nodes, aliases, key, key, name, "external-symbol", parent, 1, synthetic=True)
    children: dict[str, list[str]] = {key: [] for key in nodes}
    for node in nodes.values():
        if node.parent in children:
            children[node.parent].append(node.key)
    frozen_children = {key: tuple(values) for key, values in children.items()}
    return _Hierarchy(MappingProxyType(nodes), MappingProxyType(frozen_children),
                      MappingProxyType(aliases))


def _add_node(nodes: dict[str, ExpansionNode], aliases: dict[str, str], key: str, target_id: str,
              label: str, kind: str, parent: str | None, depth: int, raw_aliases: tuple[str, ...] = (),
              synthetic: bool = False) -> None:
    nodes[key] = ExpansionNode(key, target_id, label, kind, parent, depth, synthetic)
    aliases[key] = key
    for alias in raw_aliases:
        aliases[alias] = key


def _graph_files(model: DerivedModel, graph: Graph, graph_nodes: frozenset[str]) -> tuple[str, ...]:
    candidates = set(model.files) | {entity.file for entity in model.entities.values() if entity.file}
    return tuple(sorted(file for file in candidates if file in graph_nodes or f"file:{file}" in graph_nodes))


def _in_graph(graph_nodes: frozenset[str], usr: str) -> bool:
    return usr in graph_nodes or f"entity:{usr}" in graph_nodes


def _entity_parent(model: DerivedModel, nodes: Mapping[str, ExpansionNode], usr: str) -> str | None:
    parent = model.entities[usr].parent
    seen: set[str] = set()
    while parent and parent not in seen:
        seen.add(parent)
        entity = model.entities.get(parent)
        if entity is None:
            return None
        key = f"entity:{parent}"
        if entity.kind != Kind.NAMESPACE and key in nodes:
            return key
        parent = entity.parent
    return None


def _hierarchy_depth(key: str, nodes: Mapping[str, ExpansionNode],
                     parents: Mapping[str, str | None]) -> int:
    depth, parent = 0, parents.get(key)
    seen = {key}
    while parent is not None and parent not in seen:
        depth += 1
        seen.add(parent)
        parent = parents.get(parent, nodes[parent].parent if parent in nodes else None)
    return depth


def _expandable(hierarchy: _Hierarchy, key: str) -> bool:
    return bool(hierarchy.children.get(key))


def _visible_nodes(hierarchy: _Hierarchy, decisions: NodeDecisionMap,
                   expanded: frozenset[str]) -> frozenset[str]:
    visible: set[str] = set()
    for key, node in hierarchy.nodes.items():
        decision = _graph_decision(decisions, hierarchy, key)
        if decision.hidden or not _ancestors_expanded(hierarchy, node.parent, expanded):
            continue
        visible.add(key)
    return frozenset(visible)


def _ancestors_expanded(hierarchy: _Hierarchy, parent: str | None,
                        expanded: frozenset[str]) -> bool:
    seen: set[str] = set()
    while parent is not None and parent not in seen:
        if parent not in expanded:
            return False
        seen.add(parent)
        node = hierarchy.nodes.get(parent)
        parent = node.parent if node is not None else None
    return True


def _graph_decision(decisions: NodeDecisionMap, hierarchy: _Hierarchy, key: str) -> NodeDecision:
    decision = decisions.get(key)
    if decision is not None:
        return decision
    node = hierarchy.nodes[key]
    if node.synthetic and node.parent is not None:
        return _graph_decision(decisions, hierarchy, node.parent)
    return NodeDecision()


def _index_decisions(hierarchy: _Hierarchy, decisions: NodeDecisionMap) -> NodeDecisionMap:
    indexed = {key: decisions[key] for key in hierarchy.nodes if key in decisions}
    for alias, canonical in hierarchy.aliases.items():
        if alias in decisions:
            indexed.setdefault(canonical, decisions[alias])
    return MappingProxyType(indexed)


def _decisions(hierarchy: _Hierarchy, decisions: NodeDecisionMap,
               appearances: NodeAppearanceMap, expanded: frozenset[str],
               visible: frozenset[str]) -> dict[str, ExpansionDecision]:
    result: dict[str, ExpansionDecision] = {}
    for key, node in hierarchy.nodes.items():
        children = hierarchy.children[key]
        expandable = bool(children)
        graph_decision = _graph_decision(decisions, hierarchy, key)
        appearance = appearances.get(key.removeprefix("entity:"))
        result[key] = ExpansionDecision(
            key, node.parent, children, expandable or node.kind in _container_kinds(),
            expandable, key in expanded, expandable and key not in expanded,
            key in visible, node.synthetic, graph_decision, appearance)
    return result


def _container_kinds() -> frozenset[str]:
    return frozenset({"cluster", "file", "external", *(kind.value for kind in CONTAINER_KINDS)})


def _expanded_edges(graph: Graph, hierarchy: _Hierarchy,
                    decisions: Mapping[str, ExpansionDecision]) -> tuple[ExpandedEdge, ...]:
    counts: dict[tuple[EdgeKind, str, str], int] = {}
    labels: dict[tuple[EdgeKind, str, str], set[str]] = {}
    for edge in graph.edges:
        source = _visible_anchor(edge.source, hierarchy, decisions)
        target = _visible_anchor(edge.target, hierarchy, decisions)
        if source is None or target is None or source == target:
            continue
        key = (edge.kind, source, target)
        counts[key] = counts.get(key, 0) + 1
        if edge.label:
            labels.setdefault(key, set()).add(edge.label)
    result: list[ExpandedEdge] = []
    for key, count in sorted(counts.items(), key=lambda item: (
            item[0][1], item[0][2], item[0][0].value)):
        kind, source, target = key
        result.append(ExpandedEdge(
            kind, source, target, count, tuple(sorted(labels.get(key, ())))))
    return tuple(result)


def _visible_anchor(endpoint: str, hierarchy: _Hierarchy,
                    decisions: Mapping[str, ExpansionDecision]) -> str | None:
    key = hierarchy.aliases.get(endpoint, endpoint)
    own = decisions.get(key)
    if own is None or own.graph_decision.hidden:
        return None
    seen: set[str] = set()
    while key not in seen:
        seen.add(key)
        decision = decisions.get(key)
        if decision is None:
            return None
        if decision.visible:
            return key
        if decision.parent is None:
            return None
        key = decision.parent
    return None
