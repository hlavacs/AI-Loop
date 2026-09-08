"""Connects the step panel and the Call View to a :class:`steps.StepRunner`.

The slow parts (asking the provider, building, parsing) run through the window's ``run_async``; the results come
back on the Tk thread. Dialogs ask for a rejection reason or adaptation constraints.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from tkinter import messagebox, simpledialog
from typing import Any

from icoda_core import session, steps

Work = Callable[[], Any]
Done = Callable[[Any], None]


class StepController:
    """``window`` provides project, config, provider_field, status, panel, call_view, run_async, reload, root."""

    def __init__(self, window: Any, runner_factory: Callable[..., steps.StepRunner] = steps.StepRunner) -> None:
        self.window = window
        self.runner_factory = runner_factory
        self.runner: steps.StepRunner | None = None
        self.proposal: steps.Proposal | None = None

    # -- dispatch -------------------------------------------------------------------------

    def action(self, name: str) -> None:
        if self.window.project is None:
            messagebox.showinfo("ICODA", "Open or create a project first.")
            return
        handler = getattr(self, name, None)
        if handler is None:
            raise ValueError(f"unknown step action {name}")
        handler()

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
                self.window.status.set(f"step failed: {result}")
                messagebox.showerror("ICODA", str(result))
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

    def propose(self, constraints: tuple[str, ...] = ()) -> None:
        runner = self._ensure_runner()
        request = replace(self.window.panel.request(), constraints=constraints)

        def work() -> steps.Proposal:
            runner.prepare()
            return runner.propose(request)

        self._start(work, self._show_proposal)

    def _show_proposal(self, proposal: steps.Proposal) -> None:
        self.proposal = proposal
        self.window.panel.show(proposal)
        if proposal.ok and proposal.model is not None and proposal.delta is not None:
            self.window.call_view.show_proposal(proposal.model, proposal.delta)
            self.window.show_call_view()
            self.window.status.set(f"step {proposal.number}: proposal ready — approve, reject or adapt")
        else:
            self.window.status.set(f"step {proposal.number}: {proposal.error}")

    def approve(self) -> None:
        runner, proposal = self._ensure_runner(), self.proposal
        if proposal is None or not proposal.ok:
            return

        def done(record: steps.StepRecord) -> None:
            self.proposal = None
            self.window.panel.show(None)
            self.window.status.set(f"step {record.number} approved and committed: {record.title}")
            self.window.reload()

        self._start(lambda: runner.approve(proposal), done)

    def reject(self) -> None:
        runner, proposal = self._ensure_runner(), self.proposal
        if proposal is None:
            return
        reason = simpledialog.askstring("Reject", "Why? The reason goes into the next prompt.", parent=self.window.root)
        if reason is None:
            return

        def done(record: steps.StepRecord) -> None:
            self.proposal = None
            self.window.panel.show(None)
            self.window.status.set(f"step {record.number} rejected; propose again for a different step")

        self._start(lambda: runner.reject(proposal, reason), done)

    def adapt(self) -> None:
        if self.proposal is None:
            return
        text = simpledialog.askstring("Adapt", "Hard constraints for the next attempt, separated by ';'.",
                                      parent=self.window.root)
        if text is None:
            return
        constraints = tuple(part.strip() for part in text.split(";") if part.strip())
        self.propose(constraints)

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
