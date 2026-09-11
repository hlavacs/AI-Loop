"""Connects the step panel and the Call View to a :class:`steps.StepRunner`.

The slow parts (asking the provider, building, parsing) run through the window's ``run_async``; the results come
back on the Tk thread. Dialogs ask for a rejection reason or adaptation constraints.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from tkinter import messagebox, simpledialog
from typing import Any

from icoda_core import (
    adaptation,
    analysis,
    auto_approve,
    grouping,
    implementation_queue,
    persistence,
    session,
    specification,
    steps,
    test_selection,
)
from icoda_gui import dialogs

Work = Callable[[], Any]
Done = Callable[[Any], None]
SIGNATURE_CONFIRMATION_REQUIRED = (
    auto_approve.SIGNATURE_CONFIRMATION_REQUIRED)
ADAPT_CONSTRAINTS_PROMPT = "Hard constraints for the next attempt, separated by ';'."


class StepController:
    """``window`` provides project, config, provider_field, status, panel, call_view, run_async, reload, root."""

    def __init__(self, window: Any, runner_factory: Callable[..., steps.StepRunner] = steps.StepRunner) -> None:
        self.window = window
        self.runner_factory = runner_factory
        self.runner: steps.StepRunner | None = None
        self.proposal: steps.Proposal | None = None
        self.approach: steps.Approach | None = None
        self.confirmed_signature_proposal: steps.Proposal | None = None
        self._automatic_approvals_remaining: int | None = None

    # -- dispatch -------------------------------------------------------------------------

    def action(self, name: str, *args: Any) -> None:
        if self.window.project is None:
            messagebox.showinfo("ICODA", "Open or create a project first.")
            return
        handler = getattr(self, name, None)
        if handler is None:
            raise ValueError(f"unknown step action {name}")
        handler(*args)

    def _ensure_runner(self) -> steps.StepRunner:
        selection = self.window.provider_field.selection()
        if self.runner is None or Path(self.runner.root).resolve() != Path(self.window.project).resolve():
            self.runner = self.runner_factory(Path(self.window.project), self.window.config, selection.provider_id
                                              or "", selection.binary, selection.model, progress=self._progress)
        else:
            self.runner.provider_id = selection.provider_id or ""
            self.runner.binary, self.runner.model_id = selection.binary, selection.model
        return self.runner

    def _progress(self, message: str) -> None:
        self.window.run_on_ui(self.window.status.set, message)

    def _start(self, work: Work, done: Done) -> None:
        self.window.panel.set_busy(True)

        def finished(result: Any) -> None:
            self.window.panel.set_busy(False)
            if isinstance(result, steps.DirtyTree):
                self._offer_manual_commit(str(result), lambda: self._start(work, done))
            elif isinstance(result, Exception):
                self.window.status.set(f"step failed: {str(result).splitlines()[0] if str(result) else result!r}")
                self.window.panel.show_failure(str(result))
                dialogs.show_error("ICODA", str(result))
            else:
                done(result)

        self.window.run_async(work, finished)

    def _offer_manual_commit(self, message: str, then: Callable[[], None]) -> None:
        if messagebox.askyesno("ICODA", message + "\n\nCommit them now as a manual step?"):
            runner = self._ensure_runner()
            self._start(runner.commit_manual_edits, lambda _record: then())
        else:
            self.window.status.set(message)

    # -- actions --------------------------------------------------------------------------

    def propose_approach(self, constraints: tuple[str, ...] = (), focus: tuple[str, ...] = ()) -> None:
        runner = self._ensure_runner()
        request = replace(self.window.panel.request(), constraints=constraints, focus=focus)

        def work() -> steps.Approach:
            runner.prepare()
            return runner.propose_approach(request)

        self._start(work, self._show_approach)

    def _show_approach(self, approach: steps.Approach) -> None:
        self.approach = approach
        self.window.panel.show_approach(approach)
        if approach.ok:
            self.window.status.set(f"step {approach.number}: approach ready — approve, reject or adapt")
        else:
            self.window.status.set(f"step {approach.number}: {approach.error}")
        self._consider_auto_approve(approach_round=True)

    def propose(self, constraints: tuple[str, ...] = (), focus: tuple[str, ...] = ()) -> None:
        runner = self._ensure_runner()
        request = replace(self.window.panel.request(), constraints=constraints, focus=focus)

        def work() -> steps.Proposal:
            runner.prepare()
            return runner.propose(request)

        self._start(work, self._show_proposal)

    def _show_proposal(self, proposal: steps.Proposal) -> None:
        self.proposal = proposal
        self.confirmed_signature_proposal = None
        self.window.panel.show(proposal)
        if proposal.model is not None and proposal.delta is not None:
            self.window.call_view.show_proposal(proposal.model, proposal.delta)
            self.window.show_call_view()
        if proposal.ok:
            self.window.status.set(f"step {proposal.number}: proposal ready — approve, reject or adapt")
        elif proposal.build.ok is False:
            self.window.status.set(f"step {proposal.number}: build failed")
        elif proposal.test.ok is False:
            self.window.status.set(f"step {proposal.number}: build passed; tests failed")
        else:
            self.window.status.set(f"step {proposal.number}: {proposal.error}")
        self._consider_auto_approve()

    def propose_here(self, focus: str) -> None:
        """Use the selected diagram node as the existing architecture action's focus."""
        if focus:
            self.propose(focus=(focus,))

    def implement_here(self, target_usr: str) -> None:
        """Persist the selected callable as queue target, then use the two-round path."""
        if not target_usr:
            return
        opened = getattr(self.window, "opened", None)
        if opened is None:
            if "propose_approach" in self.window.panel.enabled_actions:
                self.propose_approach(focus=(target_usr,))
            elif "propose" in self.window.panel.enabled_actions:
                self.propose(focus=(target_usr,))
            return
        store = persistence.ProjectStore(Path(self.window.project))
        state = store.load_state()
        model = opened.model
        if not implementation_queue.can_override(model, state, target_usr):
            return
        updated = implementation_queue.override_target(model, state, target_usr)
        store.save_state(updated)
        entity = model.entities[target_usr]
        batch, refusal = self._implementation_batch(model, updated)
        batch_names = tuple(model.entities[usr].qualified_name for usr in batch)
        self.window.panel.set_implementation_queue(
            entity.qualified_name, implementation_queue.remaining(updated), updated.approved_approach,
            updated.implementation_batch_size, batch_names, updated.implementation_scope, True,
            updated.auto_approve, updated.implementation_grouping, refusal)
        self.approach = None
        if updated.approved_approach:
            self.propose(focus=(target_usr,))
        else:
            self.propose_approach(focus=(target_usr,))

    def run_tests(self, selection: Sequence[str]) -> None:
        """Run a core-selected test scope through the existing runner and busy lifecycle."""
        selected = tuple(selection)
        if not selected or self.window.panel.busy:
            return
        runner = self._ensure_runner()
        state = persistence.ProjectStore(Path(self.window.project)).load_state()
        command = test_selection.command(state.test_command, selected)
        self._start(lambda: runner.test(Path(self.window.project), command),
                    lambda result: self._show_test_result(result, selected))

    def _show_test_result(self, result: steps.TestResult, selected: tuple[str, ...]) -> None:
        outcome = "passed" if result.ok is True else "failed" if result.ok is False else "did not run"
        self.window.status.set(f"targeted tests {outcome}: {', '.join(selected)}")
        if result.ok is not True:
            self.window.panel.show_failure(result.output or f"Targeted tests {outcome}.")

    def approve(self, automatic: bool = False) -> None:
        proposal = self.proposal
        if proposal is None or not proposal.ok:
            return
        if proposal.delta is not None and proposal.delta.signature_changes \
                and self.confirmed_signature_proposal is not proposal:
            raise steps.StepError(SIGNATURE_CONFIRMATION_REQUIRED)
        runner = self._ensure_runner()

        def done(record: steps.StepRecord) -> None:
            self.proposal = None
            self.confirmed_signature_proposal = None
            self.window.panel.show(None)
            self.window.show_after_step(proposal.model)
            self.window.status.set(f"step {record.number} approved and committed: {record.title}")
            if automatic:
                self._automatic_step_completed()

        self._start(lambda: runner.approve(proposal), done)

    def confirm_signature(self) -> None:
        """Record the developer's confirmation for only the currently displayed proposal."""
        proposal = self.proposal
        if proposal is None or proposal.delta is None or not proposal.delta.signature_changes:
            return
        self.confirmed_signature_proposal = proposal
        self.window.panel.confirm_signature(proposal)
        self.window.status.set(f"step {proposal.number}: signature changes confirmed; approval is now available")
        self._consider_auto_approve()

    def approve_approach(self) -> None:
        runner, approach = self._ensure_runner(), self.approach
        if approach is None or not approach.ok:
            return

        def done(record: steps.StepRecord) -> None:
            self.window.panel.show_approach(approach, approved=True)
            self.approach = None
            self.window.status.set(f"{record.title} approved; the code-and-test round is now available")
            if self.window.panel.auto_approve_var.get():
                self.propose()

        self._start(lambda: runner.approve_approach(approach), done)

    def auto_approve_changed(self) -> None:
        """Persist the developer switch and evaluate the item already shown in the panel."""
        assert self.window.project is not None
        store = persistence.ProjectStore(Path(self.window.project))
        enabled = bool(self.window.panel.auto_approve_var.get())
        store.save_state(replace(store.load_state(), auto_approve=enabled))
        self._automatic_approvals_remaining = None
        self.window.status.set("automatic approval enabled" if enabled else "automatic approval disabled")
        if enabled:
            self._consider_auto_approve(
                approach_round=self.approach is not None and self.proposal is None)

    def _consider_auto_approve(self, *, approach_round: bool = False) -> None:
        if not self.window.panel.auto_approve_var.get():
            return
        decision = auto_approve.derive(
            self.window.panel.phase_var.get(), self.proposal,
            self.confirmed_signature_proposal is self.proposal,
            approach_round=approach_round,
            historical_record=self.window.panel.selected_iteration is not None,
        )
        if not decision.permitted:
            self._stop_auto_approve(decision.reason)
            return
        if self._automatic_approvals_remaining is None:
            state = persistence.ProjectStore(Path(self.window.project)).load_state()
            self._automatic_approvals_remaining = implementation_queue.remaining(state)
        if self._automatic_approvals_remaining <= 0:
            self._stop_auto_approve("the implementation queue is empty; automatic approval stopped")
            return
        self.approve(automatic=True)

    def _automatic_step_completed(self) -> None:
        assert self._automatic_approvals_remaining is not None
        self._automatic_approvals_remaining -= 1
        store = persistence.ProjectStore(Path(self.window.project))
        state = store.load_state()
        if implementation_queue.remaining(state) == 0:
            self._stop_auto_approve("the implementation queue is empty; automatic approval stopped")
        else:
            self.propose_approach()

    def _stop_auto_approve(self, reason: str) -> None:
        self._automatic_approvals_remaining = None
        self.window.panel.show_auto_approve_refusal(reason)
        self.window.status.set("auto-approve stopped: " + reason)

    def approve_architecture(self) -> None:
        """The explicit developer gate from architecture into implementation."""
        if self.proposal is not None:
            messagebox.showinfo("ICODA", "Approve or reject the current proposal before approving the architecture.")
            return
        runner = self._ensure_runner()
        if not messagebox.askyesno("ICODA", "Approve the architecture and begin implementation?"):
            return

        def done(record: steps.StepRecord) -> None:
            self.window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
            self.window.status.set(f"{record.title}; implementation phase is now active")
            self.window.reload()

        self._start(runner.approve_architecture, done)

    def batch_size_changed(self) -> None:
        """Persist the developer's next-step batch limit and invalidate any old approach."""
        assert self.window.project is not None
        store = persistence.ProjectStore(Path(self.window.project))
        state = store.load_state()
        batch_size = self.window.panel.implementation_batch_size()
        if batch_size == state.implementation_batch_size:
            return
        store.save_state(replace(state, implementation_batch_size=batch_size, approved_approach=""))
        self.approach = None
        self.window.status.set(f"implementation batch size set to {batch_size}")
        self.window.reload()

    def scope_changed(self) -> None:
        """Persist the developer-selected implementation scope and regroup the queue."""
        if self.window.project is None or self.window.opened is None:
            return
        store = persistence.ProjectStore(Path(self.window.project))
        state = store.load_state()
        scope = self.window.panel.implementation_scope()
        if scope.value == state.implementation_scope:
            return
        store.save_state(implementation_queue.select_scope(self.window.opened.model, state, scope))
        self.approach = None
        self.window.panel.show(None)
        self.window.status.set(f"implementation scope set to {dict(implementation_queue.SCOPE_LABELS)[scope]}")
        self.window.reload()

    def grouping_changed(self) -> None:
        """Persist and preview the developer's one-entity or validated few-line choice."""
        opened = getattr(self.window, "opened", None)
        if self.window.project is None or opened is None:
            return
        store = persistence.ProjectStore(Path(self.window.project))
        state = store.load_state()
        mode = self.window.panel.implementation_grouping()
        updated = replace(state, implementation_grouping=mode.value, approved_approach="")
        store.save_state(updated)
        batch, refusal = self._implementation_batch(opened.model, updated)
        names = tuple(opened.model.entities[usr].qualified_name for usr in batch)
        target = names[0] if names else None
        self.window.panel.set_implementation_queue(
            target, implementation_queue.remaining(updated), batch_size=updated.implementation_batch_size,
            batch=names, scope=updated.implementation_scope, auto_approve=updated.auto_approve,
            grouping_mode=updated.implementation_grouping, grouping_refusal=refusal,
        )
        self.approach = None
        self.window.panel.show(None)
        self.window.status.set(
            f"implementation grouping set to {dict(grouping.GROUPING_LABELS)[mode]}"
            + (f"; {refusal}" if refusal else ""))

    def _implementation_batch(
        self, model: Any, state: persistence.ProjectState,
    ) -> tuple[tuple[str, ...], str]:
        if state.implementation_grouping != grouping.Mode.FEW_LINE_GROUP.value:
            return (tuple(implementation_queue.next_batch(
                model, state, state.implementation_batch_size)), "")
        store = persistence.ProjectStore(Path(self.window.project))
        if store.specification_path.is_file():
            profile = specification.load(store.specification_path).get("code_profile", {})
        else:
            profile = specification.default_code_profile(analysis.detect_language(Path(self.window.project)))
        decision = grouping.derive(implementation_queue.scope_targets(model, state), model, profile)
        return tuple(entity.usr for entity in decision.entities), decision.refusal_reason

    def reject(self) -> None:
        runner = self._ensure_runner()
        decision = self.proposal or self.approach
        if decision is None:
            return
        reason = simpledialog.askstring("Reject", "Why? The reason goes into the next prompt.", parent=self.window.root)
        if reason is None:
            return

        def done(record: steps.StepRecord) -> None:
            if self.proposal is not None:
                self.proposal = None
                self.confirmed_signature_proposal = None
                self.window.panel.show(None)
                message = f"step {record.number} rejected; propose again for a different step"
            else:
                self.approach = None
                self.window.panel.show_approach(None)
                message = f"step {record.number} approach rejected; propose another approach"
            self.window.status.set(message)

        if self.proposal is not None:
            proposal = self.proposal
            work = lambda: runner.reject(proposal, reason)
        else:
            assert self.approach is not None
            approach = self.approach
            work = lambda: runner.reject_approach(approach, reason)
        self._start(work, done)

    def adapt(self) -> None:
        if self.proposal is not None:
            if not self.proposal.ok or not self.proposal.entities:
                return
            parsed = adaptation.parse_summary(self.window.panel.edited_entity_summary())
            if parsed.problems:
                self.window.panel.show_adaptation_problems(parsed.problems)
                self.window.status.set(adaptation.problems_text(parsed.problems))
                return
            instruction = adaptation.describe_changes(self.proposal.entities, parsed.entities)
            if instruction == adaptation.UNCHANGED_SUMMARY:
                text = simpledialog.askstring("Adapt", ADAPT_CONSTRAINTS_PROMPT, parent=self.window.root)
                if text is None:
                    return
                constraints = tuple(part.strip() for part in text.split(";") if part.strip())
            else:
                constraints = (instruction,)
            self.confirmed_signature_proposal = None
            self.propose(constraints)
            return
        if self.approach is None:
            return
        text = simpledialog.askstring("Adapt", ADAPT_CONSTRAINTS_PROMPT, parent=self.window.root)
        if text is None:
            return
        constraints = tuple(part.strip() for part in text.split(";") if part.strip())
        self.approach = None
        self.window.panel.show_approach(None)
        self.propose_approach(constraints)

    def rebuild(self) -> None:
        runner, proposal = self._ensure_runner(), self.proposal
        if proposal is not None:
            self._start(lambda: runner.rebuild(proposal), self._show_proposal)

    def open_worktree(self) -> None:
        if self.proposal is not None:
            session.open_in_editor(self.proposal.worktree, 1, self.window.config.editor)

    def undo(self) -> None:
        runner = self._ensure_runner()
        if not messagebox.askyesno("ICODA", "Undo the last approved step with a revert commit?"):
            return

        def done(record: steps.StepRecord) -> None:
            self.window.status.set(f"step {record.number} undone: {record.title}")
            self.window.reload()

        self._start(runner.undo, done)

    def commit_manual(self) -> None:
        runner = self._ensure_runner()

        def done(record: steps.StepRecord | None) -> None:
            self.window.status.set("nothing to commit" if record is None
                                   else f"manual edits committed as step {record.number}")

        self._start(runner.commit_manual_edits, done)
