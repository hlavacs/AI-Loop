"""Deterministic target selection for the implementation phase."""

from __future__ import annotations

import networkx as nx

from icoda_core.model import CALLABLE_KINDS, DerivedModel, Entity, is_test_file


def candidates(model: DerivedModel) -> list[Entity]:
    """Implementation candidates are non-test callables whose current status is ``stub``."""
    return sorted((entity for entity in model.entities.values()
                   if entity.kind in CALLABLE_KINDS and entity.status == "stub" and not is_test_file(entity.file)),
                  key=_entity_key)


def next_target(model: DerivedModel) -> Entity | None:
    """Choose a leaf stub; collapse cycles and choose deterministically within and between sink components."""
    available = {entity.usr: entity for entity in candidates(model)}
    if not available:
        return None
    graph = nx.DiGraph()
    graph.add_nodes_from(available)
    graph.add_edges_from((edge.source, edge.target) for edge in model.edges
                         if edge.source in available and edge.target in available)
    components = list(nx.strongly_connected_components(graph))
    component_of = {usr: index for index, component in enumerate(components) for usr in component}
    sinks = [component for index, component in enumerate(components)
             if not any(component_of[target] != index for source in component for target in graph.successors(source))]
    chosen = min(sinks, key=lambda component: tuple(_entity_key(available[usr]) for usr in sorted(component)))
    return min((available[usr] for usr in chosen), key=_entity_key)


def _entity_key(entity: Entity) -> tuple[str, str]:
    return entity.qualified_name.casefold(), entity.usr
