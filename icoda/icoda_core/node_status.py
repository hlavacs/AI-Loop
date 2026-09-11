"""Pure, immutable node appearance facts shared by every graph view."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from icoda_core import bodyhash
from icoda_core.coverage_index import CoverageEntry, CoverageIndex
from icoda_core.model import CALLABLE_KINDS, DerivedModel
from icoda_core.persistence import ProjectPhase, ProjectState
from icoda_core.steplog import StepLog, StepRecord, last_entity_body_hashes


@dataclass(frozen=True)
class NodeAppearance:
    """Non-GUI appearance inputs for one entity USR."""

    status: str = ""
    queue_status: str = ""
    stale: bool = False
    covered: bool | None = None
    covering_test_count: int = 0


NodeAppearanceMap = Mapping[str, NodeAppearance]


def derive(model: DerivedModel, state: ProjectState,
           log: StepLog | Iterable[StepRecord], coverage: CoverageIndex) -> NodeAppearanceMap:
    """Return a read-only per-USR appearance map from already-derived project facts."""
    records = log.records() if isinstance(log, StepLog) else list(log)
    touched_hashes = last_entity_body_hashes(records)
    coverage_entries = coverage.entry_map()
    queue = _remaining_queue(state)
    facts = {
        usr: _appearance(model, usr, touched_hashes.get(usr, ""), queue, coverage_entries)
        for usr in model.entities
    }
    return MappingProxyType(facts)


def _appearance(model: DerivedModel, usr: str, touched_hash: str,
                queue: Mapping[str, int], coverage: Mapping[str, CoverageEntry]) -> NodeAppearance:
    entity = model.entities[usr]
    entry = coverage.get(usr)
    tests = entry.tests if entry is not None else ()
    covered = entry.covered if entry is not None else None
    position = queue.get(usr)
    queue_status = "current" if position == 1 else "queued" if position is not None else ""
    body_stale = bodyhash.changed(touched_hash, entity.body_hash)
    status = entity.status if entity.kind in CALLABLE_KINDS else ""
    return NodeAppearance(status, queue_status, model.stale or body_stale, covered, len(tests))


def _remaining_queue(state: ProjectState) -> Mapping[str, int]:
    if state.phase != ProjectPhase.IMPLEMENTATION:
        return {}
    pending = state.implementation_queue[state.implementation_cursor:]
    return {usr: position for position, usr in enumerate(pending, 1)}
