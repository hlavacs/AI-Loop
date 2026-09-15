"""The next-step hint: one sentence per situation, in the order a developer meets them."""

from __future__ import annotations

from icoda_core import guidance
from icoda_core.guidance import Situation, next_step


def test_the_first_run_is_led_from_no_project_to_the_first_proposal() -> None:
    assert "Open a project" in next_step(Situation())
    assert "save it" in next_step(Situation(project_open=True, phase=guidance.SPECIFICATION))
    assert "Build" in next_step(Situation(project_open=True, phase=guidance.ARCHITECTURE, has_model=False))
    assert "LLM panel" in next_step(Situation(project_open=True, phase=guidance.ARCHITECTURE,
                                              provider_ready=False))
    hint = next_step(Situation(project_open=True, phase=guidance.ARCHITECTURE))
    assert hint.startswith("Architecture phase: press Propose") and "Approve architecture" in hint


def test_a_proposal_and_its_problems_are_explained() -> None:
    ready = Situation(project_open=True, phase=guidance.ARCHITECTURE, proposal="ok", step_number=3)
    assert next_step(ready).startswith("Step 3 is ready.") and "Approve" in next_step(ready)
    signatures = Situation(project_open=True, phase=guidance.ARCHITECTURE, proposal="ok", step_number=3,
                           signature_confirmation_required=True)
    assert "Confirm signatures" in next_step(signatures)
    failed = Situation(project_open=True, phase=guidance.IMPLEMENTATION, proposal="failed", step_number=4)
    assert next_step(failed).startswith("Step 4 did not pass") and "Rebuild" in next_step(failed)
    historical = Situation(project_open=True, phase=guidance.ARCHITECTURE, historical_step=2)
    assert "step 2 from the history" in next_step(historical)


def test_the_implementation_phase_walks_through_the_approach_round() -> None:
    base = Situation(project_open=True, phase=guidance.IMPLEMENTATION, target="app::parse", remaining=4)
    assert "Propose approach" in next_step(base) and "(4 left in the queue)" in next_step(base)
    assert "Approve approach" in next_step(Situation(**{**base.__dict__, "approach": "pending"}))
    assert "Propose approach again" in next_step(Situation(**{**base.__dict__, "approach": "failed"}))
    assert next_step(Situation(**{**base.__dict__, "approach": "approved"})).startswith(
        "The approach for app::parse is approved. Press Propose")
    assert "Every function in the queue is implemented" in next_step(
        Situation(**{**base.__dict__, "has_target": False}))


def test_busy_and_auto_approve_notes() -> None:
    busy = Situation(project_open=True, phase=guidance.ARCHITECTURE, busy=True, activity="asking the agent")
    assert next_step(busy) == "Working: asking the agent."
    assert next_step(Situation(**{**busy.__dict__, "cancellable": True})).endswith("Press Cancel to stop.")
    noted = Situation(project_open=True, phase=guidance.IMPLEMENTATION, proposal="ok", step_number=5,
                      auto_approve_note="Auto-approve paused: the test gate is not passing. Decide yourself.")
    assert next_step(noted).endswith("Decide yourself.")
