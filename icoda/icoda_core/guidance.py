"""What the developer can do next, as one plain sentence for the step panel.

The panel collects the facts it knows into a :class:`Situation`; :func:`next_step` turns them into the hint shown
above the buttons. Nothing here touches Tk, so the wording is testable on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

SPECIFICATION = "specification"
ARCHITECTURE = "architecture"
IMPLEMENTATION = "implementation"


@dataclass(frozen=True)
class Situation:
    """Everything the hint depends on; every field has a safe default so callers name only what they know."""

    project_open: bool = False
    phase: str = ""
    busy: bool = False
    activity: str = ""
    cancellable: bool = False
    has_model: bool = True          # the analysis found files and entities
    provider_ready: bool = True     # a known agent binary is chosen and installed
    proposal: str = "none"          # none | ok | failed
    step_number: int = 0
    signature_confirmation_required: bool = False
    approach: str = "none"          # none | pending | approved | failed
    has_target: bool = True
    target: str = ""
    remaining: int = 0
    historical_step: int | None = None
    auto_approve_note: str = ""


def next_step(situation: Situation) -> str:
    """One sentence that says what to do now."""
    s = situation
    if s.busy:
        text = f"Working: {s.activity or 'please wait'}."
        return text + (" Press Cancel to stop." if s.cancellable else "")
    if not s.project_open:
        return "Open a project (File ▸ Open Project…) or start a new one (File ▸ New Project…)."
    if s.phase == SPECIFICATION:
        return ("Write the specification and save it (Project ▸ Specification…). Saving writes the project "
                "skeleton and moves the project into the architecture phase.")
    if not s.has_model:
        return ("The project is not built and analysed yet. Press Build (Project ▸ Build); "
                "ICODA builds it and reloads the analysis.")
    if not s.provider_ready:
        return ("Choose the coding agent in the LLM panel (Binary and Model). The agent's command-line tool must "
                "be installed and logged in.")
    note = f" {s.auto_approve_note}" if s.auto_approve_note else ""
    if s.historical_step is not None:
        return f"You are looking at step {s.historical_step} from the history. Press Propose for a new step." + note
    if s.proposal == "ok":
        if s.signature_confirmation_required:
            return (f"Step {s.step_number} changes function signatures: check the Signatures tab, then press "
                    "Confirm signatures before you approve." + note)
        return (f"Step {s.step_number} is ready. Read the rationale and the Diff tab, then Approve, Reject… "
                "(with a reason) or Adapt… (with constraints)." + note)
    if s.proposal == "failed":
        return (f"Step {s.step_number} did not pass its checks (see the Build and Tests tabs). Reject… it with a "
                "reason, Adapt… it, or edit the worktree and choose More… ▸ Rebuild." + note)
    if s.phase == ARCHITECTURE:
        return ("Architecture phase: press Propose to get the next structural step (an empty Request lets the agent "
                "choose). When the structure is complete, press Approve architecture." + note)
    if s.phase == IMPLEMENTATION:
        return _implementation_hint(s) + note
    return "Reload the project (File ▸ Reload) to continue."


def _implementation_hint(s: Situation) -> str:
    target = f" for {s.target}" if s.target else ""
    if not s.has_target:
        return ("Every function in the queue is implemented. Change the Scope to find more work, or extend the "
                "specification.")
    if s.approach == "pending":
        return f"An approach{target} is ready. Read it in the Approach tab, then Approve approach, Reject… or Adapt…."
    if s.approach == "failed":
        return ("No usable approach came back (see the Approach tab). Press Propose approach again, or Reject… "
                "with a reason.")
    if s.approach == "approved":
        return f"The approach{target} is approved. Press Propose to get the code and its tests."
    left = f" ({s.remaining} left in the queue)" if s.remaining else ""
    return (f"Implementation phase{left}: press Propose approach to ask how {s.target or 'the current target'} "
            "should be implemented.")
