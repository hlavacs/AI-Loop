"""Validated project phase transitions, persisted and recorded in the step log."""

from __future__ import annotations

from icoda_core.persistence import ProjectPhase, ProjectStore
from icoda_core.steplog import StepLog, StepRecord

TRANSITION_TITLES = {
    (ProjectPhase.SPECIFICATION, ProjectPhase.ARCHITECTURE): "specification completed",
    (ProjectPhase.ARCHITECTURE, ProjectPhase.IMPLEMENTATION): "architecture approved",
    (ProjectPhase.IMPLEMENTATION, ProjectPhase.ARCHITECTURE): "architecture session opened",
}


def transition(store: ProjectStore, target: ProjectPhase) -> StepRecord:
    """Validate, persist and log one developer-controlled phase transition."""
    current = store.load_state()
    updated = current.transition_to(target)
    title = TRANSITION_TITLES[(current.phase, target)]
    record = StepRecord(StepLog(store.steps_path).next_number(), target.value, "phase_transition", title=title,
                        previous_phase=current.phase.value)
    store.save_state(updated)
    try:
        return StepLog(store.steps_path).append(record)
    except OSError:
        store.save_state(current)
        raise
