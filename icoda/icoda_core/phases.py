"""Validated project phase transitions, persisted and recorded in the step log."""

from __future__ import annotations

from icoda_core import implementation_queue, specification
from icoda_core.model import DerivedModel
from icoda_core.persistence import PHASE_TRANSITIONS, PhaseTransitionError, ProjectPhase, ProjectStore
from icoda_core.steplog import StepLog, StepRecord

TRANSITION_TITLES = {
    (ProjectPhase.SPECIFICATION, ProjectPhase.ARCHITECTURE): "specification completed",
    (ProjectPhase.ARCHITECTURE, ProjectPhase.IMPLEMENTATION): "architecture approved",
    (ProjectPhase.IMPLEMENTATION, ProjectPhase.ARCHITECTURE): "architecture session opened",
}


def transition_refusal(store: ProjectStore, target: ProjectPhase) -> str:
    """Expose lifecycle and specification-editor gates without constructing a desktop controller."""
    current = store.load_state()
    try:
        current.transition_to(target)
    except PhaseTransitionError as exc:
        return str(exc)
    if current.phase == ProjectPhase.SPECIFICATION:
        if not store.specification_path.is_file():
            return "Save a valid specification before leaving the specification phase."
        try:
            problems = specification.validate(specification.load(store.specification_path))
        except (OSError, ValueError, TypeError, AttributeError):
            return "The saved specification cannot be read. Open and validate it first."
        if problems:
            return "Validate and save the specification first: " + "; ".join(problems)
    return ""


def transition_options(store: ProjectStore) -> dict[ProjectPhase, str]:
    """Legal lifecycle destinations with any current editor-gate refusal."""
    return {phase: transition_refusal(store, phase)
            for phase in sorted(PHASE_TRANSITIONS[store.load_state().phase])}


def advance(store: ProjectStore, target: ProjectPhase, model: DerivedModel) -> StepRecord:
    """Apply an explicitly requested transition with the editor gate and architecture queue setup."""
    reason = transition_refusal(store, target)
    if reason:
        raise PhaseTransitionError(reason)
    record = transition(store, target)
    if target == ProjectPhase.IMPLEMENTATION:
        implementation_queue.ensure_state(store, model)
    return record


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
