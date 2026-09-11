"""Persistent, GUI-independent project mind-map projection.

The public :func:`build_mind_map` builder produces the hierarchy required by
``EVOLUTION.md``: cluster -> file -> class/function, with member functions
nested below their class.  Cluster and file siblings are ordered by their
stable ids; entity siblings are ordered by kind (class before function), then
qualified name, signature, source position and USR.  Thus neither entity nor
edge insertion order affects the result.

Class and function nodes carry their entity's status and ``@satisfies`` ids.
Synthetic file and cluster nodes aggregate those values from their descendants;
their status is the least-complete descendant status (stub, implemented,
tested), or ``unknown`` when they contain no callable/class nodes.  Introducing
iterations come from effective approved/manual step records.  Renames retain
the old USR's iteration, and unknown history is represented by ``None``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from icoda_core import clusters
from icoda_core.model import CALLABLE_KINDS, DerivedModel, Entity, Kind
from icoda_core.steplog import APPROACH_ROUND, StepLog, StepRecord

CLASS_KINDS = frozenset({Kind.CLASS, Kind.STRUCT})
STATUS_ORDER = {"stub": 0, "implemented": 1, "tested": 2}


class MindMapNodeKind(str, Enum):
    """The four node kinds specified for the M4 mind map."""

    CLUSTER = "cluster"
    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"


@dataclass(frozen=True)
class MindMapNode:
    """One immutable mind-map node and its already ordered children."""

    id: str
    kind: MindMapNodeKind
    name: str
    qualified_name: str
    status: str
    satisfied_requirement_ids: tuple[str, ...]
    introduced_iteration: int | None
    file: str = ""
    usr: str = ""
    children: tuple[MindMapNode, ...] = ()


@dataclass(frozen=True)
class MindMap:
    """The stable forest of project clusters."""

    clusters: tuple[MindMapNode, ...] = ()

    def nodes(self) -> tuple[MindMapNode, ...]:
        """Return every node once in deterministic pre-order."""
        return tuple(node for cluster in self.clusters for node in _walk(cluster))

    def node_map(self) -> dict[str, MindMapNode]:
        return {node.id: node for node in self.nodes()}


@dataclass(frozen=True)
class MindMapViewState:
    """Persistent expansion choices; no expanded ids means fully collapsed."""

    expanded: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "expanded", tuple(sorted(set(self.expanded))))

    def to_dict(self) -> dict[str, Any]:
        return {"expanded": list(self.expanded)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MindMapViewState:
        value = data.get("expanded", ())
        if not isinstance(value, (list, tuple)):
            return cls()
        return cls(tuple(str(node_id) for node_id in value))


@dataclass(frozen=True)
class _Introductions:
    entities: dict[str, int]
    files: dict[str, int]


def build_mind_map(model: DerivedModel,
                   history: StepLog | Iterable[StepRecord],
                   clustering: clusters.Clustering | None = None) -> MindMap:
    """Build the deterministic M4 hierarchy from ``model`` and step history.

    ``history`` may be the project's :class:`StepLog` or an in-memory iterable
    of records.  Rejected, failed, approach-only and undone steps do not
    introduce nodes.
    """
    records = history.records() if isinstance(history, StepLog) else list(history)
    introductions = _introductions(model, records)
    entities = _project_entities(model)
    grouped = _files_by_cluster(model, entities, clustering)
    roots = tuple(_cluster_node(cluster_id, name, files, entities, introductions)
                  for cluster_id, name, files in grouped)
    return MindMap(roots)


def _project_entities(model: DerivedModel) -> tuple[Entity, ...]:
    included = CLASS_KINDS | CALLABLE_KINDS
    return tuple(sorted((entity for entity in model.entities.values() if entity.kind in included),
                        key=_entity_key))


def _files_by_cluster(model: DerivedModel, entities: tuple[Entity, ...],
                      clustering: clusters.Clustering | None) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    grouped: dict[str, list[str]] = defaultdict(list)
    names: dict[str, str] = {}
    for cluster in (clustering or clusters.cluster_files(model)).clusters:
        grouped[cluster.id].extend(cluster.files)
        names[cluster.id] = cluster.name
    assigned = {file for files in grouped.values() for file in files}
    for file in sorted({entity.file for entity in entities if entity.file} - assigned):
        cluster_id = clusters.directory_seed(file)
        grouped[cluster_id].append(file)
        names.setdefault(cluster_id, PurePosixPath(cluster_id).name or cluster_id)
    return tuple((cluster_id, names[cluster_id], tuple(sorted(set(grouped[cluster_id]))))
                 for cluster_id in sorted(grouped))


def _cluster_node(cluster_id: str, name: str, files: tuple[str, ...], entities: tuple[Entity, ...],
                  introductions: _Introductions) -> MindMapNode:
    children = tuple(_file_node(file, entities, introductions) for file in files)
    return _container_node(f"cluster:{cluster_id}", MindMapNodeKind.CLUSTER, name, name, children,
                           _first_iteration(child.introduced_iteration for child in children))


def _file_node(file: str, entities: tuple[Entity, ...], introductions: _Introductions) -> MindMapNode:
    local = tuple(entity for entity in entities if entity.file == file)
    classes = tuple(entity for entity in local if entity.kind in CLASS_KINDS)
    nested = {child.usr for owner in classes for child in local if child.parent == owner.usr
              and child.kind in CALLABLE_KINDS}
    children = tuple(sorted((*(_class_node(owner, local, introductions) for owner in classes),
                             *(_entity_node(entity, introductions) for entity in local
                               if entity.kind in CALLABLE_KINDS and entity.usr not in nested)),
                            key=_node_key))
    iteration = introductions.files.get(file, _first_iteration(child.introduced_iteration for child in children))
    return _container_node(f"file:{file}", MindMapNodeKind.FILE, PurePosixPath(file).name, file, children,
                           iteration, file=file)


def _class_node(entity: Entity, local: tuple[Entity, ...], introductions: _Introductions) -> MindMapNode:
    children = tuple(_entity_node(child, introductions) for child in local
                     if child.parent == entity.usr and child.kind in CALLABLE_KINDS)
    children = tuple(sorted(children, key=_node_key))
    return MindMapNode(f"entity:{entity.usr}", MindMapNodeKind.CLASS, entity.name, entity.qualified_name,
                       entity.status, _requirements(entity.satisfies), introductions.entities.get(entity.usr),
                       entity.file, entity.usr, children)


def _entity_node(entity: Entity, introductions: _Introductions) -> MindMapNode:
    return MindMapNode(f"entity:{entity.usr}", MindMapNodeKind.FUNCTION, entity.name, entity.qualified_name,
                       entity.status, _requirements(entity.satisfies), introductions.entities.get(entity.usr),
                       entity.file, entity.usr)


def _container_node(node_id: str, kind: MindMapNodeKind, name: str, qualified_name: str,
                    children: tuple[MindMapNode, ...], iteration: int | None,
                    file: str = "") -> MindMapNode:
    descendants = tuple(item for child in children for item in _walk(child))
    requirements = tuple(sorted({requirement for child in descendants
                                 for requirement in child.satisfied_requirement_ids}))
    status = _aggregate_status(child.status for child in descendants)
    return MindMapNode(node_id, kind, name, qualified_name, status, requirements, iteration, file, children=children)


def _introductions(model: DerivedModel, records: list[StepRecord]) -> _Introductions:
    effective = _effective_records(records)
    entity_iterations: dict[str, int] = {}
    file_iterations: dict[str, int] = {}
    for record in effective:
        for file in record.files:
            file_iterations.setdefault(file, record.number)
        for usr in record.entities_added:
            entity_iterations.setdefault(usr, record.number)
            entity = model.entities.get(usr)
            if entity is not None and entity.file:
                file_iterations.setdefault(entity.file, record.number)
        for previous, current in record.entities_renamed:
            entity_iterations.setdefault(current, entity_iterations.get(previous, record.number))
    return _Introductions(entity_iterations, file_iterations)


def _effective_records(records: list[StepRecord]) -> list[StepRecord]:
    undone = {record.undoes for record in records if record.decision == "undone"}
    result = [record for record in records if record.number not in undone
              and record.round != APPROACH_ROUND and record.decision in ("approved", "manual")]
    return sorted(result, key=lambda record: (record.number, record.time, record.title, record.phase, record.decision))


def _aggregate_status(statuses: Iterable[str]) -> str:
    values = tuple(status for status in statuses if status and status != "unknown")
    return min(values, key=lambda status: (STATUS_ORDER.get(status, 99), status)) if values else "unknown"


def _requirements(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _first_iteration(values: Iterable[int | None]) -> int | None:
    known = tuple(value for value in values if value is not None)
    return min(known) if known else None


def _entity_key(entity: Entity) -> tuple[int, str, str, str, int, str]:
    group = 0 if entity.kind in CLASS_KINDS else 1
    return (group, entity.qualified_name, entity.signature, entity.file, entity.line, entity.usr)


def _node_key(node: MindMapNode) -> tuple[int, str, str, str, str]:
    group = 0 if node.kind == MindMapNodeKind.CLASS else 1
    return (group, node.qualified_name, node.name, node.file, node.usr)


def _walk(node: MindMapNode) -> Iterable[MindMapNode]:
    yield node
    for child in node.children:
        yield from _walk(child)
