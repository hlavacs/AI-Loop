"""Pure projection of a :class:`DerivedModel` into the Class View graph.

The graph is deliberately independent of clang and Tk.  Class and struct entities
become nodes, their direct fields and callable children become members, and model
relations become inheritance, composition, or usage edges between those nodes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from icoda_core.model import CALLABLE_KINDS, DerivedModel, EdgeKind, Entity, Kind

CLASS_KINDS = frozenset({Kind.CLASS, Kind.STRUCT})


class ClassEdgeKind(str, Enum):
    INHERITANCE = "inheritance"
    COMPOSITION = "composition"
    USAGE = "usage"


@dataclass(frozen=True)
class ClassMember:
    usr: str
    kind: Kind
    name: str
    qualified_name: str
    declaration: str
    status: str
    file: str
    line: int


@dataclass(frozen=True)
class ClassNode:
    usr: str
    kind: Kind
    name: str
    qualified_name: str
    file: str
    line: int
    end_line: int
    template_params: tuple[str, ...]
    data_members: tuple[ClassMember, ...]
    member_functions: tuple[ClassMember, ...]

    @property
    def members(self) -> tuple[ClassMember, ...]:
        return (*self.data_members, *self.member_functions)


@dataclass(frozen=True)
class ClassEdge:
    kind: ClassEdgeKind
    source: str
    target: str
    count: int = 1


@dataclass(frozen=True)
class ClassGraph:
    nodes: tuple[ClassNode, ...] = ()
    edges: tuple[ClassEdge, ...] = ()

    def node_map(self) -> dict[str, ClassNode]:
        return {node.usr: node for node in self.nodes}


def build_class_graph(model: DerivedModel) -> ClassGraph:
    """Return a stable class/struct graph derived solely from ``model``."""
    classes = {entity.usr: entity for entity in model.entities.values() if entity.kind in CLASS_KINDS}
    nodes = tuple(_class_node(model, entity) for entity in sorted(classes.values(), key=_entity_key))
    counts: dict[tuple[ClassEdgeKind, str, str], int] = {}
    for edge in model.edges:
        relation = _class_relation(model, classes, edge.kind, edge.source, edge.target)
        if relation is not None:
            counts[relation] = counts.get(relation, 0) + 1
    edges = tuple(ClassEdge(kind, source, target, count)
                  for (kind, source, target), count in sorted(counts.items(), key=_edge_key))
    return ClassGraph(nodes, edges)


def _class_node(model: DerivedModel, entity: Entity) -> ClassNode:
    children = sorted(model.children(entity.usr), key=_entity_key)
    data_members = tuple(_member(child) for child in children if child.kind == Kind.FIELD)
    member_functions = tuple(_member(child) for child in children if child.kind in CALLABLE_KINDS)
    return ClassNode(entity.usr, entity.kind, entity.name, entity.qualified_name, entity.file, entity.line,
                     entity.end_line, entity.template_params, data_members, member_functions)


def _member(entity: Entity) -> ClassMember:
    status = entity.status if entity.kind in CALLABLE_KINDS else ""
    return ClassMember(entity.usr, entity.kind, entity.name, entity.qualified_name,
                       entity.signature, status, entity.file, entity.line)


def _class_relation(model: DerivedModel, classes: dict[str, Entity], kind: EdgeKind,
                    source: str, target: str) -> tuple[ClassEdgeKind, str, str] | None:
    if target not in classes:
        return None
    if kind == EdgeKind.INHERITS and source in classes:
        return (ClassEdgeKind.INHERITANCE, source, target)
    if kind != EdgeKind.USES_TYPE:
        return None
    entity = model.entities.get(source)
    if entity is None or entity.parent not in classes:
        return None
    if entity.kind == Kind.FIELD:
        return (ClassEdgeKind.COMPOSITION, entity.parent, target)
    if entity.kind in CALLABLE_KINDS:
        return (ClassEdgeKind.USAGE, entity.parent, target)
    return None


def _entity_key(entity: Entity) -> tuple[str, str, str, int, str]:
    return (entity.qualified_name, entity.signature, entity.file, entity.line, entity.usr)


def _edge_key(item: tuple[tuple[ClassEdgeKind, str, str], int]) -> tuple[str, str, str]:
    (kind, source, target), _count = item
    return (source, target, kind.value)
