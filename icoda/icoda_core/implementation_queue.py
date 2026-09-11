"""Deterministic bottom-up queue for implementation-phase function steps.

Only callables that are marked ``stub`` or have no definition are queued.  Calls are
condensed into strongly connected components, then leaf components are emitted before
their callers.  Independent components, and functions within a recursive call cycle,
use the stable ``qualified name, signature, file, line, USR`` tie-break.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import replace
from enum import Enum

import networkx as nx

from icoda_core import clusters
from icoda_core.model import CALLABLE_KINDS, DerivedModel, EdgeKind, Entity, Kind
from icoda_core.persistence import ProjectPhase, ProjectState, ProjectStore


class Scope(str, Enum):
    """Developer-selected boundary for the next implementation batch."""

    QUEUE_ORDER = "queue_order"
    SINGLE_ENTITY = "single_entity"
    ENCLOSING_CLASS = "enclosing_class"
    ENCLOSING_CLUSTER = "enclosing_cluster"
    ALL_REMAINING_LEAVES = "all_remaining_leaves"


SCOPE_LABELS = (
    (Scope.QUEUE_ORDER, "Queue order"),
    (Scope.SINGLE_ENTITY, "Single entity"),
    (Scope.ENCLOSING_CLASS, "Enclosing class"),
    (Scope.ENCLOSING_CLUSTER, "Enclosing cluster"),
    (Scope.ALL_REMAINING_LEAVES, "All remaining leaves"),
)


def build(model: DerivedModel) -> tuple[str, ...]:
    """Return the USRs of not-yet-implemented callables in bottom-up order.

    A recursive cycle cannot be ordered by dependency, so it is treated as one unit and
    its members use the documented stable entity tie-break instead.
    """
    pending = {entity.usr: entity for entity in model.entities.values() if _pending(entity)}
    graph = nx.DiGraph()
    graph.add_nodes_from(sorted(pending, key=lambda usr: _key(pending[usr])))
    graph.add_edges_from((edge.source, edge.target) for edge in model.edges
                         if edge.kind == EdgeKind.CALLS
                         and edge.source in pending and edge.target in pending)
    components = [tuple(sorted(component, key=lambda usr: _key(pending[usr])))
                  for component in nx.strongly_connected_components(graph)]
    components.sort(key=lambda component: _key(pending[component[0]]))
    component_of = {usr: index for index, component in enumerate(components) for usr in component}
    dependencies: dict[int, set[int]] = {index: set() for index in range(len(components))}
    callers: dict[int, set[int]] = defaultdict(set)
    for source, target in graph.edges:
        source_component, target_component = component_of[source], component_of[target]
        if source_component != target_component:
            dependencies[source_component].add(target_component)
            callers[target_component].add(source_component)

    ready = [(_key(pending[component[0]]), index) for index, component in enumerate(components)
             if not dependencies[index]]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        _component_key, index = heapq.heappop(ready)
        ordered.extend(components[index])
        for caller in callers[index]:
            dependencies[caller].discard(index)
            if not dependencies[caller]:
                heapq.heappush(ready, (_key(pending[components[caller][0]]), caller))
    return tuple(ordered)


def ensure_state(store: ProjectStore, model: DerivedModel) -> ProjectState:
    """Populate an implementation queue once and persist it; other phases are untouched."""
    state = store.load_state()
    if state.phase != ProjectPhase.IMPLEMENTATION or state.implementation_queue \
            or state.implementation_cursor:
        return state
    updated = replace(state, implementation_queue=build(model))
    store.save_state(updated)
    return updated


def target_usr(state: ProjectState) -> str | None:
    """Return the developer override or queue head, or ``None`` when complete."""
    if state.phase != ProjectPhase.IMPLEMENTATION:
        return None
    if state.implementation_cursor >= len(state.implementation_queue):
        return None
    tail = state.implementation_queue[state.implementation_cursor:]
    if state.implementation_override in tail:
        return state.implementation_override
    return state.implementation_queue[state.implementation_cursor]


def can_override(model: DerivedModel, state: ProjectState, usr: str) -> bool:
    """Whether ``usr`` is a pending callable in the remaining persisted queue."""
    entity = model.entities.get(usr)
    return state.phase == ProjectPhase.IMPLEMENTATION and entity is not None and _pending(entity) \
        and usr in state.implementation_queue[state.implementation_cursor:]


def override_target(model: DerivedModel, state: ProjectState, usr: str) -> ProjectState:
    """Return state with ``usr`` moved to the cursor as the explicit next target."""
    if not can_override(model, state, usr):
        raise ValueError(f"{usr!r} is not a remaining implementation-queue callable")
    current = target_usr(state)
    prefix = state.implementation_queue[:state.implementation_cursor]
    tail = state.implementation_queue[state.implementation_cursor:]
    queue = (*prefix, usr, *(item for item in tail if item != usr))
    approach = state.approved_approach if current == usr else ""
    return replace(state, implementation_queue=queue, implementation_override=usr,
                   approved_approach=approach)


def scope_targets(model: DerivedModel, state: ProjectState,
                  scope: Scope | str | None = None) -> tuple[str, ...]:
    """Expand a scope to an exact, queue-ordered set of remaining pending USRs."""
    selected = Scope(scope or state.implementation_scope)
    candidates = _active_remaining(model, state)
    target = target_usr(state)
    if selected == Scope.QUEUE_ORDER:
        return candidates
    if selected == Scope.ALL_REMAINING_LEAVES:
        return _remaining_leaves(model, candidates)
    if target is None or target not in candidates:
        return ()
    if selected == Scope.SINGLE_ENTITY:
        return (target,)
    if selected == Scope.ENCLOSING_CLASS:
        owner = _enclosing_class(model, target)
        return (target,) if owner is None else _target_first(
            target, tuple(usr for usr in candidates if _enclosing_class(model, usr) == owner))
    cluster = clusters.cluster_files(model).cluster_of(model.entities[target].file)
    return _target_first(target, tuple(
        usr for usr in candidates if cluster is not None and model.entities[usr].file in cluster.files))


def select_scope(model: DerivedModel, state: ProjectState, scope: Scope | str) -> ProjectState:
    """Persist ``scope`` and group its exact expansion at the queue cursor."""
    selected = Scope(scope)
    targets = scope_targets(model, state, selected)
    prefix = state.implementation_queue[:state.implementation_cursor]
    tail = state.implementation_queue[state.implementation_cursor:]
    target_set = set(targets)
    queue = (*prefix, *targets, *(usr for usr in tail if usr not in target_set))
    return replace(state, implementation_queue=queue, implementation_scope=selected.value,
                   implementation_override="", approved_approach="")


def next_batch(model: DerivedModel, state: ProjectState, limit: int) -> list[str]:
    """Return the consecutive queue targets safe to cover in one small step.

    A candidate cannot join the batch while it still calls an unimplemented queue
    dependency that the batch does not contain.  This makes the helper safe even for
    hand-edited or stale persisted queues without changing their established order.
    """
    head = target_usr(state)
    if head is None:
        return []
    batch = [head]
    if limit <= 1:
        return batch
    eligible = set(scope_targets(model, state))
    tail = state.implementation_queue[state.implementation_cursor:]
    for candidate in (usr for usr in tail if usr != head and usr in eligible):
        if len(batch) >= limit:
            break
        if _has_dependency_outside_batch(model, candidate, {*batch, candidate}):
            break
        batch.append(candidate)
    return batch


def remaining(state: ProjectState) -> int:
    """Number of queue entries from the cursor through the current tail."""
    if state.phase != ProjectPhase.IMPLEMENTATION:
        return 0
    return max(0, len(state.implementation_queue) - state.implementation_cursor)


def _pending(entity: Entity) -> bool:
    return entity.kind in CALLABLE_KINDS and (entity.status == "stub" or not entity.is_definition)


def _active_remaining(model: DerivedModel, state: ProjectState) -> tuple[str, ...]:
    return tuple(usr for usr in state.implementation_queue[state.implementation_cursor:]
                 if usr in model.entities and _pending(model.entities[usr]))


def _enclosing_class(model: DerivedModel, usr: str) -> str | None:
    parent = model.entities[usr].parent
    while parent is not None:
        entity = model.entities.get(parent)
        if entity is None:
            return None
        if entity.kind in (Kind.CLASS, Kind.STRUCT):
            return entity.usr
        parent = entity.parent
    return None


def _remaining_leaves(model: DerivedModel, candidates: tuple[str, ...]) -> tuple[str, ...]:
    pending = set(candidates)
    graph = nx.DiGraph()
    graph.add_nodes_from(candidates)
    graph.add_edges_from((edge.source, edge.target) for edge in model.edges
                         if edge.kind == EdgeKind.CALLS and edge.source in pending and edge.target in pending)
    components = list(nx.strongly_connected_components(graph))
    component_of = {usr: index for index, component in enumerate(components) for usr in component}
    nonleaves = {edge.source for edge in model.edges if edge.kind == EdgeKind.CALLS
                 and edge.source in pending and edge.target in pending
                 and component_of[edge.source] != component_of[edge.target]}
    return tuple(usr for usr in candidates if usr not in nonleaves)


def _target_first(target: str, candidates: tuple[str, ...]) -> tuple[str, ...]:
    return (target, *(usr for usr in candidates if usr != target))


def _has_dependency_outside_batch(model: DerivedModel, usr: str, batch: set[str]) -> bool:
    return any(edge.target not in batch and edge.target in model.entities
               and _pending(model.entities[edge.target]) for edge in model.callees(usr))


def _key(entity: Entity) -> tuple[str, str, str, int, str]:
    return (entity.qualified_name, entity.signature, entity.file, entity.line, entity.usr)
