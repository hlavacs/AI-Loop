"""Pure shared filtering and neighbourhood emphasis for every graph view."""

from __future__ import annotations

import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from icoda_core.model import DerivedModel, Edge, Entity, Kind
from icoda_core.node_status import NodeAppearance, NodeAppearanceMap


@dataclass(frozen=True)
class FilterDescription:
    """The explicit criteria accepted by the single diagram filter entry."""

    name: str = ""
    kind: str = ""
    status: str = ""
    covered: bool | None = None
    stale: bool | None = None
    cluster: str = ""
    namespace: str = ""
    edge_type: str = ""

    @property
    def active(self) -> bool:
        return any((self.name, self.kind, self.status, self.cluster, self.namespace,
                    self.edge_type, self.covered is not None, self.stale is not None))


@dataclass(frozen=True)
class NodeDecision:
    """Visibility and emphasis for one USR or aggregate diagram node id."""

    matched_by_filter: bool = True
    hidden: bool = False
    dimmed_because_outside_neighborhood: bool = False

    @property
    def dimmed(self) -> bool:
        return self.dimmed_because_outside_neighborhood


@dataclass(frozen=True)
class Graph:
    """Existing graph endpoints plus their already-derived cluster assignment."""

    nodes: tuple[str, ...] = ()
    edges: tuple[Edge, ...] = ()
    cluster_by_file: Mapping[str, str] = MappingProxyType({})
    cluster_names: Mapping[str, str] = MappingProxyType({})


NodeDecisionMap = Mapping[str, NodeDecision]
EMPTY_FILTER = FilterDescription()


def project_graph(model: DerivedModel, cluster_by_file: Mapping[str, str] | None = None,
                  cluster_names: Mapping[str, str] | None = None) -> Graph:
    """Expose model/view node ids while retaining the model's existing edges."""
    clusters = MappingProxyType(dict(cluster_by_file or {}))
    cluster_ids = set(clusters.values())
    files = set(model.files) | {entity.file for entity in model.entities.values() if entity.file}
    nodes = set(model.entities) | files | set(cluster_ids)
    nodes.update(f"entity:{usr}" for usr in model.entities)
    nodes.update(f"file:{file}" for file in files)
    nodes.update(f"cluster:{cluster}" for cluster in cluster_ids)
    nodes.update(f"external:{library}" for library in model.externals)
    for edge in model.edges:
        nodes.update((edge.source, edge.target))
    names = MappingProxyType(dict(cluster_names or {}))
    return Graph(tuple(sorted(nodes)), tuple(model.edges), clusters, names)


def parse(text: str) -> FilterDescription:
    """Parse forgiving ``field:value`` tokens; unqualified text is a name substring."""
    values: dict[str, str] = {}
    names: list[str] = []
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    for token in tokens:
        field, separator, value = token.partition(":")
        field = field.lower().replace("-", "_")
        if separator and field in _TEXT_FIELDS | {"covered", "stale"}:
            values[field] = value
        else:
            names.append(token)
    return FilterDescription(
        name=values.get("name", " ".join(names)),
        kind=values.get("kind", ""),
        status=values.get("status", ""),
        covered=_boolean(values.get("covered")),
        stale=_boolean(values.get("stale")),
        cluster=values.get("cluster", ""),
        namespace=values.get("namespace", ""),
        edge_type=values.get("edge_type", values.get("edge", "")),
    )


def derive(model: DerivedModel, graph: Graph, appearances: NodeAppearanceMap,
           criteria: FilterDescription = EMPTY_FILTER, *, focus_usr: str | None = None,
           neighborhood_depth: int = 0) -> NodeDecisionMap:
    """Return one frozen decision map shared unchanged by all diagram canvases."""
    reachable = _neighborhood(graph, focus_usr, neighborhood_depth)
    decisions: dict[str, NodeDecision] = {}
    for node_id in graph.nodes:
        usrs = _node_usrs(model, graph, node_id)
        matched = not criteria.active or _node_matches(
            model, graph, appearances, node_id, usrs, criteria)
        dimmed = bool(reachable) and not bool(set(usrs or (node_id,)) & reachable)
        decisions[node_id] = NodeDecision(matched, not matched, matched and dimmed)
    return MappingProxyType(decisions)


_TEXT_FIELDS = {"name", "kind", "status", "cluster", "namespace", "edge", "edge_type"}


def _boolean(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.casefold()
    if lowered in {"true", "yes", "1", "covered", "stale"}:
        return True
    if lowered in {"false", "no", "0", "uncovered", "fresh"}:
        return False
    return None


def _node_usrs(model: DerivedModel, graph: Graph, node_id: str) -> tuple[str, ...]:
    raw = node_id.removeprefix("entity:")
    if raw in model.entities:
        entity = model.entities[raw]
        children = model.children(raw) if entity.kind in {Kind.CLASS, Kind.STRUCT} else []
        return tuple(dict.fromkeys((raw, *(child.usr for child in children))))
    file = node_id.removeprefix("file:")
    if file in model.files or any(entity.file == file for entity in model.entities.values()):
        return tuple(entity.usr for entity in model.entities_in(file))
    cluster = node_id.removeprefix("cluster:")
    if cluster in set(graph.cluster_by_file.values()):
        return tuple(entity.usr for entity in model.entities.values()
                     if graph.cluster_by_file.get(entity.file) == cluster)
    return ()


def _node_matches(model: DerivedModel, graph: Graph, appearances: NodeAppearanceMap,
                  node_id: str, usrs: tuple[str, ...], criteria: FilterDescription) -> bool:
    entities = tuple(model.entities[usr] for usr in usrs if usr in model.entities)
    if not entities:
        return _synthetic_matches(graph, node_id, criteria)
    return any(_entity_matches(entity, graph, appearances.get(entity.usr), criteria)
               for entity in entities)


def _entity_matches(entity: Entity, graph: Graph, appearance: NodeAppearance | None,
                    criteria: FilterDescription) -> bool:
    namespace = entity.qualified_name.rpartition("::")[0]
    cluster = graph.cluster_by_file.get(entity.file, "")
    return (
        _contains(entity.name, criteria.name)
        and _contains(entity.kind.value, criteria.kind)
        and _contains(appearance.status if appearance else "", criteria.status)
        and _optional_equals(appearance.covered if appearance else None, criteria.covered)
        and _optional_equals(appearance.stale if appearance else False, criteria.stale)
        and _contains(cluster, criteria.cluster)
        and _contains(namespace, criteria.namespace)
        and _has_edge_type(graph.edges, entity.usr, criteria.edge_type)
    )


def _synthetic_matches(graph: Graph, node_id: str, criteria: FilterDescription) -> bool:
    kind = "external" if node_id.startswith("external:") else ""
    return (
        _contains(node_id, criteria.name)
        and _contains(kind, criteria.kind)
        and not criteria.status
        and criteria.covered is None
        and (criteria.stale is None or criteria.stale is False)
        and not criteria.cluster
        and not criteria.namespace
        and _has_edge_type(graph.edges, node_id, criteria.edge_type)
    )


def _contains(actual: str, wanted: str) -> bool:
    return not wanted or wanted.casefold() in actual.casefold()


def _optional_equals(actual: bool | None, wanted: bool | None) -> bool:
    return wanted is None or actual is wanted


def _has_edge_type(edges: Iterable[Edge], usr: str, wanted: str) -> bool:
    if not wanted:
        return True
    normalized = wanted.casefold().replace("_", "-")
    return any(edge.kind.value.casefold() == normalized and usr in (edge.source, edge.target)
               for edge in edges)


def _neighborhood(graph: Graph, focus_usr: str | None, depth: int) -> frozenset[str]:
    if not focus_usr or depth <= 0 or focus_usr not in graph.nodes:
        return frozenset()
    reached = {focus_usr}
    frontier = {focus_usr}
    for _ in range(depth):
        adjacent = {endpoint for edge in graph.edges if edge.source in frontier or edge.target in frontier
                    for endpoint in (edge.source, edge.target)}
        frontier = adjacent - reached
        reached.update(frontier)
        if not frontier:
            break
    return frozenset(reached)
