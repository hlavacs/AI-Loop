"""Pure classification of whether the proposal on screen may be auto-approved."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

IMPLEMENTATION_ONLY = "automatic approval is available only in the implementation phase"
GATED_ROUND = "architecture and approach rounds require developer approval"
HISTORICAL_RECORD = "historical step-log records cannot be automatically approved"
NO_PROPOSAL = "there is no current implementation proposal to approve automatically"
BUILD_GATE = "the proposal build gate is not passing"
TEST_GATE = "the proposal test gate is not passing"
SIGNATURE_CONFIRMATION_REQUIRED = (
    "the proposal changes existing entity signatures; confirm the signature changes before approving"
)


@dataclass(frozen=True)
class Decision:
    """A deterministic permission plus one stable reason when permission is refused."""

    permitted: bool
    reason: str = ""


def derive(
    phase: object,
    proposal: object | None,
    signature_changes_confirmed: bool = False,
    *,
    approach_round: bool = False,
    historical_record: bool = False,
) -> Decision:
    """Classify the currently shown item using only its already-derived gates and delta."""
    if historical_record:
        return Decision(False, HISTORICAL_RECORD)
    if _phase_value(phase) != "implementation":
        return Decision(False, IMPLEMENTATION_ONLY)
    if approach_round or _proposal_phase(proposal) != "implementation":
        return Decision(False, GATED_ROUND)
    if proposal is None:
        return Decision(False, NO_PROPOSAL)
    if _gate_ok(proposal, "build") is not True:
        return Decision(False, BUILD_GATE)
    if _gate_ok(proposal, "test") is not True:
        return Decision(False, TEST_GATE)
    delta = getattr(proposal, "delta", None)
    signature_changes: object = getattr(delta, "signature_changes", ())
    if bool(signature_changes) and not signature_changes_confirmed:
        return Decision(False, SIGNATURE_CONFIRMATION_REQUIRED)
    return Decision(True)


def _phase_value(phase: object) -> str:
    return str(getattr(phase, "value", phase))


def _proposal_phase(proposal: object | None) -> str:
    if proposal is None:
        return "implementation"
    request: Any = getattr(proposal, "request", None)
    return str(getattr(request, "phase", "implementation"))


def _gate_ok(proposal: object, name: str) -> bool | None:
    return getattr(getattr(proposal, name, None), "ok", None)
