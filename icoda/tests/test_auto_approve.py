"""Exact decisions for the pure auto-approval gate."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from icoda_core import auto_approve, persistence, prompt, response, steps


def proposal(tmp_path: Path, phase: str = prompt.IMPLEMENTATION) -> steps.Proposal:
    return steps.Proposal(
        1, prompt.StepRequest(phase, 1, target="u:f"), tmp_path,
        response=response.StepResponse("Implement f", "Atomic change.", ()),
        build=steps.BuildResult(True), test=steps.TestResult(True),
        delta=steps.Delta((), (), (), ()),
    )


def test_clean_implementation_proposal_is_permitted_and_decision_is_frozen(tmp_path: Path) -> None:
    decision = auto_approve.derive(persistence.ProjectPhase.IMPLEMENTATION, proposal(tmp_path))

    assert decision == auto_approve.Decision(True, "")
    with pytest.raises(FrozenInstanceError):
        decision.permitted = False  # type: ignore[misc]


def test_every_refusal_has_its_exact_stable_reason(tmp_path: Path) -> None:
    build_failed = proposal(tmp_path)
    build_failed.build = steps.BuildResult(False)
    test_failed = proposal(tmp_path)
    test_failed.test = steps.TestResult(False)
    signature_change = proposal(tmp_path)
    signature_change.delta = steps.Delta(
        (), (), (), (), signature_changes=(steps.SignatureChange("u:f", "f", "int f()", "long f()"),))

    decisions = {
        auto_approve.derive(persistence.ProjectPhase.ARCHITECTURE, proposal(tmp_path)),
        auto_approve.derive(persistence.ProjectPhase.IMPLEMENTATION, build_failed),
        auto_approve.derive(persistence.ProjectPhase.IMPLEMENTATION, test_failed),
        auto_approve.derive(persistence.ProjectPhase.IMPLEMENTATION, signature_change),
        auto_approve.derive(
            persistence.ProjectPhase.IMPLEMENTATION, proposal(tmp_path), approach_round=True),
        auto_approve.derive(
            persistence.ProjectPhase.IMPLEMENTATION, None, historical_record=True),
        auto_approve.derive(persistence.ProjectPhase.IMPLEMENTATION, None),
    }

    assert decisions == {
        auto_approve.Decision(False, "automatic approval is available only in the implementation phase"),
        auto_approve.Decision(False, "the proposal build gate is not passing"),
        auto_approve.Decision(False, "the proposal test gate is not passing"),
        auto_approve.Decision(False, "the proposal changes existing entity signatures; confirm the signature "
                                     "changes before approving"),
        auto_approve.Decision(False, "architecture and approach rounds require developer approval"),
        auto_approve.Decision(False, "historical step-log records cannot be automatically approved"),
        auto_approve.Decision(False, "there is no current implementation proposal to approve automatically"),
    }


def test_architecture_proposal_needs_its_own_gate_even_if_panel_phase_is_implementation(tmp_path: Path) -> None:
    decision = auto_approve.derive(
        persistence.ProjectPhase.IMPLEMENTATION, proposal(tmp_path, prompt.ARCHITECTURE))

    assert decision == auto_approve.Decision(
        False, "architecture and approach rounds require developer approval")
