"""The step panel: implementation approach, code proposal, verification output, and developer decisions."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from icoda_core import adaptation, grouping, implementation_queue, persistence, prompt, steplog, steps

ACTIONS = ("propose_approach", "approve_approach", "propose", "approve_architecture", "approve",
           "confirm_signature", "reject", "adapt", "rebuild", "open_worktree", "undo", "commit_manual")
LABELS = {"propose_approach": "Propose approach", "approve_approach": "Approve approach",
          "propose": "Propose", "approve": "Approve", "reject": "Reject…", "adapt": "Adapt…",
          "rebuild": "Rebuild", "open_worktree": "Open worktree", "undo": "Undo last step",
          "commit_manual": "Commit manual edits", "approve_architecture": "Approve architecture",
          "confirm_signature": "Confirm signatures"}


class StepPanel:
    """Controls in a frame; ``on_action`` receives the name of the pressed button."""

    def __init__(self, parent: Any, on_action: Callable[[str], None]) -> None:
        self.frame = ttk.Frame(parent)
        self.on_action = on_action
        self.proposal: steps.Proposal | None = None
        self.signature_confirmed = False
        self.approach: steps.Approach | None = None
        self.approach_approved = False
        self.has_implementation_target = False
        self.busy = False
        self.selected_iteration: int | None = None
        self.phase_var = tk.StringVar(value=persistence.ProjectPhase.SPECIFICATION.value)
        self.queue_var = tk.StringVar(value="Implementation queue: inactive")
        self.request_var = tk.StringVar(value="")
        self.max_entities_var = tk.IntVar(value=5)
        self.batch_size_var = tk.IntVar(value=1)
        self.scope_var = tk.StringVar(value="Queue order")
        self.auto_approve_var = tk.BooleanVar(value=False)
        self.title_var = tk.StringVar(value="No proposal")
        self.build_status_var = tk.StringVar(value="Build: not run")
        self.test_status_var = tk.StringVar(value="Tests: not run")
        self.signature_var = tk.StringVar(value="Signature changes: none")
        self.buttons: dict[str, Any] = {}
        self.enabled_actions: set[str] = set()
        self._build_request_row()
        self._build_texts()
        self.show(None)

    def _build_request_row(self) -> None:
        request_row = ttk.Frame(self.frame)
        request_row.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(request_row, text="Phase").pack(side=tk.LEFT)
        self.phase_label = ttk.Label(request_row, textvariable=self.phase_var, width=14)
        self.phase_label.pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(request_row, text="Request (empty: the agent chooses)").pack(side=tk.LEFT)
        ttk.Entry(request_row, textvariable=self.request_var).pack(side=tk.LEFT, fill=tk.X, expand=True,
                                                                   padx=(2, 10))
        ttk.Label(request_row, text="Max entities").pack(side=tk.LEFT)
        ttk.Spinbox(request_row, from_=1, to=20, width=3, textvariable=self.max_entities_var).pack(side=tk.LEFT,
                                                                                                  padx=(2, 10))
        ttk.Label(request_row, text="Batch size").pack(side=tk.LEFT)
        self.batch_size_spinbox = ttk.Spinbox(request_row, from_=1, to=20, width=3,
                                               textvariable=self.batch_size_var,
                                               command=self._batch_size_changed)
        self.batch_size_spinbox.pack(side=tk.LEFT, padx=(2, 0))
        self.batch_size_spinbox.bind("<Return>", self._batch_size_changed)
        self.batch_size_spinbox.bind("<FocusOut>", self._batch_size_changed)
        queue_row = ttk.Frame(self.frame)
        queue_row.pack(fill=tk.X, padx=4, pady=(0, 2))
        self.queue_label = ttk.Label(queue_row, textvariable=self.queue_var, anchor="w")
        self.queue_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(queue_row, text="Scope").pack(side=tk.LEFT, padx=(8, 2))
        self.scope_combobox = ttk.Combobox(
            queue_row, state="readonly", width=21, textvariable=self.scope_var,
            values=tuple(label for _scope, label in implementation_queue.SCOPE_LABELS))
        self.scope_combobox.pack(side=tk.LEFT)
        self.scope_combobox.bind("<<ComboboxSelected>>", self._scope_changed)
        self._build_grouping_control(queue_row)
        self.auto_approve_check = ttk.Checkbutton(
            queue_row, text="Auto-approve while gates pass", variable=self.auto_approve_var,
            command=self._auto_approve_changed)
        self.auto_approve_check.pack(side=tk.LEFT, padx=(10, 0))
        approach_row = ttk.Frame(self.frame)
        approach_row.pack(fill=tk.X, padx=4, pady=(0, 2))
        action_row = ttk.Frame(self.frame)
        action_row.pack(fill=tk.X, padx=4, pady=(0, 2))
        for action in ACTIONS:
            parent = approach_row if action in ("propose_approach", "approve_approach") else action_row
            self.buttons[action] = ttk.Button(parent, text=LABELS[action], command=self._pressed(action))
            self.buttons[action].pack(side=tk.LEFT, padx=2)

    def _build_texts(self) -> None:
        ttk.Label(self.frame, textvariable=self.title_var, font=("TkDefaultFont", 11, "bold"),
                  anchor="w").pack(fill=tk.X, padx=4)
        status_row = ttk.Frame(self.frame)
        status_row.pack(fill=tk.X, padx=4)
        ttk.Label(status_row, textvariable=self.build_status_var).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Label(status_row, textvariable=self.test_status_var).pack(side=tk.LEFT, padx=(0, 16))
        self.signature_label = ttk.Label(status_row, textvariable=self.signature_var)
        self.signature_label.pack(side=tk.LEFT)
        paned = ttk.PanedWindow(self.frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 4))
        self.rationale = _scrolled_text(paned, wrap="word")
        paned.add(self.rationale.master, weight=3)
        self.detail_notebook = ttk.Notebook(paned)
        self.approach_text = _scrolled_text(self.detail_notebook, wrap="word")
        self.details = _scrolled_text(self.detail_notebook, wrap="none", font=("TkFixedFont", 10))
        self.signature = _scrolled_text(self.detail_notebook, wrap="none", font=("TkFixedFont", 10))
        self.entity_summary = _scrolled_text(
            self.detail_notebook, wrap="none", font=("TkFixedFont", 10), editable=True)
        self.source_diff = _scrolled_text(self.detail_notebook, wrap="none", font=("TkFixedFont", 10))
        self.build_output = _scrolled_text(self.detail_notebook, wrap="none", font=("TkFixedFont", 10))
        self.test_output = _scrolled_text(self.detail_notebook, wrap="none", font=("TkFixedFont", 10))
        self.detail_notebook.add(self.approach_text.master, text="Approach")
        self.detail_notebook.add(self.details.master, text="Delta")
        self.detail_notebook.add(self.signature.master, text="Signature changes")
        self.detail_notebook.add(self.entity_summary.master, text="Entity summary")
        self.detail_notebook.add(self.source_diff.master, text="Source diff")
        self.detail_notebook.add(self.build_output.master, text="Build")
        self.detail_notebook.add(self.test_output.master, text="Tests")
        paned.add(self.detail_notebook, weight=2)

    def _pressed(self, action: str) -> Callable[[], None]:
        return lambda: self.on_action(action)

    def _batch_size_changed(self, _event: Any = None) -> None:
        self.batch_size_var.set(self.implementation_batch_size())
        self.on_action("batch_size_changed")

    def implementation_batch_size(self) -> int:
        try:
            return max(1, int(self.batch_size_var.get() or 1))
        except (ValueError, tk.TclError):
            return 1

    def _scope_changed(self, _event: Any = None) -> None:
        self.on_action("scope_changed")

    def implementation_scope(self) -> implementation_queue.Scope:
        labels = {label: scope for scope, label in implementation_queue.SCOPE_LABELS}
        return labels.get(self.scope_var.get(), implementation_queue.Scope.QUEUE_ORDER)

    def _auto_approve_changed(self) -> None:
        self.on_action("auto_approve_changed")

    # -- state ----------------------------------------------------------------------------

    def request(self) -> prompt.StepRequest:
        return prompt.StepRequest(self.phase_var.get(), 0, self.request_var.get().strip(),
                                  max_entities=int(self.max_entities_var.get() or 5))

    def set_phase(self, phase: persistence.ProjectPhase | str) -> None:
        """Display the project's persisted phase; this is intentionally not an editable control."""
        value = persistence.ProjectPhase(phase).value
        self.phase_var.set(value)
        if value != prompt.IMPLEMENTATION:
            self.approach, self.approach_approved, self.has_implementation_target = None, False, False
            _set_text(self.approach_text, "Approach round is inactive outside implementation.")
        self.queue_var.set("Implementation queue: loading…" if value == prompt.IMPLEMENTATION
                           else "Implementation queue: inactive")
        self.batch_size_spinbox.state(["!disabled"] if value == prompt.IMPLEMENTATION else ["disabled"])
        self.scope_combobox.state(["readonly"] if value == prompt.IMPLEMENTATION else ["disabled"])
        self.grouping_combobox.state(["readonly"] if value == prompt.IMPLEMENTATION else ["disabled"])
        self.auto_approve_check.state(["!disabled"] if value == prompt.IMPLEMENTATION else ["disabled"])
        self._update_buttons()

    def _build_grouping_control(self, parent: Any) -> None:
        self.grouping_var = tk.StringVar(value="One entity")
        ttk.Label(parent, text="Grouping").pack(side=tk.LEFT, padx=(8, 2))
        self.grouping_combobox = ttk.Combobox(
            parent, state="readonly", width=14, textvariable=self.grouping_var,
            values=tuple(label for _mode, label in grouping.GROUPING_LABELS))
        self.grouping_combobox.pack(side=tk.LEFT)
        self.grouping_combobox.bind("<<ComboboxSelected>>", self._grouping_changed)

    def _grouping_changed(self, _event: Any = None) -> None:
        self.on_action("grouping_changed")

    def implementation_grouping(self) -> grouping.Mode:
        labels = {label: mode for mode, label in grouping.GROUPING_LABELS}
        return labels.get(self.grouping_var.get(), grouping.Mode.SINGLE_ENTITY)

    def set_implementation_queue(self, target: str | None, remaining: int, approved_approach: str = "",
                                 batch_size: int = 1, batch: tuple[str, ...] = (),
                                 scope: str = implementation_queue.Scope.QUEUE_ORDER.value,
                                 overridden: bool = False, auto_approve: bool = False,
                                 grouping_mode: str = grouping.Mode.SINGLE_ENTITY.value,
                                 grouping_refusal: str = "") -> None:
        """Show the current target and restore its persisted approach decision."""
        self.batch_size_var.set(batch_size)
        scope_value = implementation_queue.Scope(scope)
        self.scope_var.set(dict(implementation_queue.SCOPE_LABELS)[scope_value])
        mode = grouping.Mode(grouping_mode)
        self.grouping_var.set(dict(grouping.GROUPING_LABELS)[mode])
        self.auto_approve_var.set(auto_approve)
        self.has_implementation_target = target is not None
        self.approach = None
        self.approach_approved = bool(approved_approach.strip())
        if self.phase_var.get() != prompt.IMPLEMENTATION:
            self.queue_var.set("Implementation queue: inactive")
        elif target is None:
            self.queue_var.set("Implementation queue: empty — no unimplemented functions")
        elif len(batch) > 1:
            if mode == grouping.Mode.FEW_LINE_GROUP:
                prefix = "Overridden group" if overridden else "Current group"
            else:
                prefix = "Overridden batch" if overridden else "Current batch"
            self.queue_var.set(f"{prefix} ({len(batch)}): {', '.join(batch)} — {remaining} remaining")
        else:
            prefix = "Overridden target" if overridden else "Current target"
            self.queue_var.set(f"{prefix}: {target} — {remaining} remaining")
        if grouping_refusal:
            self.queue_var.set(self.queue_var.get() + f" — Group refused: {grouping_refusal}")
        if self.phase_var.get() != prompt.IMPLEMENTATION:
            text = "Approach round is inactive outside implementation."
        else:
            text = ("Approved approach:\n\n" + approved_approach.strip()) if self.approach_approved \
                else "No approach approved for the current target."
        _set_text(self.approach_text, text)
        self._update_buttons()

    def show_approach(self, approach: steps.Approach | None, approved: bool = False) -> None:
        """Present the prose round and whether the developer has approved it."""
        self.approach = approach
        self.approach_approved = approved
        if approach is None:
            text = "No approach approved for the current target."
        else:
            status = "Approved" if approved else "Awaiting developer approval"
            text = f"{status}\n\n{approach.plan or approach.reply}"
            if approach.entities:
                text += "\n\nExpected entities:\n" + "\n".join(f"- {item}" for item in approach.entities)
            if approach.files:
                text += "\n\nExpected files:\n" + "\n".join(f"- {item}" for item in approach.files)
            if approach.error:
                text += "\n\nError: " + approach.error
        _set_text(self.approach_text, text)
        self._update_buttons()

    def show(self, proposal: steps.Proposal | None) -> None:
        """Present a proposal (or clear the panel) and enable the buttons that apply to it."""
        self.selected_iteration = None
        self.proposal = proposal
        self.signature_confirmed = False
        self.build_status_var.set("Build: " + _result_status(proposal.build.ok if proposal else None))
        self.test_status_var.set("Tests: " + _result_status(proposal.test.ok if proposal else None))
        if proposal is None:
            self.title_var.set("No proposal")
            _set_text(self.rationale, "")
            _set_text(self.details, "")
            _set_text(self.signature, "")
            _set_editable_text(self.entity_summary, adaptation.NO_USABLE_PROPOSAL)
            _set_text(self.source_diff, "")
            _set_text(self.build_output, "")
            _set_text(self.test_output, "")
        elif proposal.response is not None and proposal.delta is not None:
            title = f"Step {proposal.number}: {proposal.response.title}  (attempt {proposal.attempts})"
            batch_names = _proposal_batch_names(proposal)
            if len(batch_names) > 1:
                title += f" — batch: {', '.join(batch_names)}"
            self.title_var.set(title + (f" — {proposal.error}" if proposal.error else ""))
            _set_text(self.rationale, _rationale_text(proposal))
            _set_text(self.details, _delta_text(proposal))
            _set_text(self.signature, proposal.delta.signature_summary())
            self._show_entity_summary(proposal)
            _set_text(self.source_diff, proposal.source_diff or "No source changes.")
            _set_text(self.build_output, proposal.build.output or "Build passed without output.")
            _set_text(self.test_output, _test_text(proposal))
        else:
            self.title_var.set(f"Step {proposal.number}: no usable proposal — {proposal.error}")
            _set_text(self.rationale, (proposal.response.rationale if proposal.response else "") or proposal.reply)
            _set_text(self.details, proposal.error)
            _set_text(self.signature, proposal.delta.signature_summary() if proposal.delta else "No signature changes.")
            _set_editable_text(self.entity_summary, adaptation.NO_USABLE_PROPOSAL)
            _set_text(self.source_diff, proposal.source_diff or "No source changes.")
            _set_text(self.build_output, proposal.build.output or "Build did not run.")
            _set_text(self.test_output, _test_text(proposal))
        self._update_signature_status()
        self._update_buttons()

    def _show_entity_summary(self, proposal: steps.Proposal) -> None:
        text = adaptation.render_summary(proposal.entities) if proposal.entities else adaptation.NO_ENTITY_SUMMARY
        _set_editable_text(self.entity_summary, text)

    def edited_entity_summary(self) -> str:
        """Return the developer's current text from the editable structured-summary tab."""
        return str(self.entity_summary.get("1.0", "end-1c"))

    def show_adaptation_problems(self, problems: tuple[str, ...]) -> None:
        """Keep the edited text intact and make deterministic parse problems visible."""
        _set_text(self.details, adaptation.problems_text(problems))
        self.detail_notebook.select(self.entity_summary.master)

    def confirm_signature(self, proposal: steps.Proposal) -> None:
        """Confirm the signature decisions on the proposal currently shown in this panel."""
        if proposal is self.proposal and proposal.delta is not None and proposal.delta.signature_changes:
            self.signature_confirmed = True
            self._update_signature_status()
            self._update_buttons()

    def _update_signature_status(self) -> None:
        changes = self.proposal.delta.signature_changes if self.proposal and self.proposal.delta else ()
        if not changes:
            self.signature_var.set("Signature changes: none")
        elif self.signature_confirmed:
            self.signature_var.set(f"Signature changes: {len(changes)} confirmed")
        else:
            self.signature_var.set(f"Signature changes: {len(changes)} — confirmation required")

    def show_step(self, record: steplog.StepRecord) -> None:
        """Select one persisted historical step for review from the mind map."""
        self.selected_iteration = record.number
        self.proposal = None
        self.signature_confirmed = False
        self.title_var.set(f"Step {record.number}: {record.title or record.decision}")
        self.build_status_var.set("Build: " + _result_status(record.build_ok))
        self.test_status_var.set("Tests: " + _result_status(record.test_ok))
        _set_text(self.rationale, _historical_rationale(record))
        _set_text(self.details, _historical_details(record))
        _set_text(self.signature, "Historical signature confirmations are not stored in the step log.")
        _set_editable_text(self.entity_summary, adaptation.HISTORICAL_UNAVAILABLE)
        _set_text(self.source_diff, "Historical source diff is not stored in the step log.")
        _set_text(self.build_output, record.build_output or _empty_result_text("Build", record.build_ok))
        _set_text(self.test_output, record.test_output or _empty_result_text("Tests", record.test_ok))
        self._update_signature_status()
        self.detail_notebook.select(self.details.master)
        self._update_buttons()

    def show_failure(self, text: str) -> None:
        """A step that raised: the whole message in the details box, buttons as before."""
        self.title_var.set("Step failed — " + (text.strip().splitlines()[0] if text.strip() else "no details"))
        _set_text(self.details, text)
        self._update_buttons()

    def show_auto_approve_refusal(self, reason: str) -> None:
        """Keep the proposal visible while explaining why unattended work stopped."""
        self.title_var.set("Auto-approve stopped — " + reason)
        _set_text(self.details, reason)
        self._update_buttons()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self._update_buttons()

    def _update_buttons(self) -> None:
        usable = self.proposal is not None and self.proposal.ok
        signature_confirmation_required = bool(
            usable and self.proposal and self.proposal.delta and self.proposal.delta.signature_changes
            and not self.signature_confirmed)
        phase = self.phase_var.get()
        has_decision_item = self.proposal is not None or (self.approach is not None and not self.approach_approved)
        self.enabled_actions = set()
        for action, button in self.buttons.items():
            enabled = not self.busy
            if action == "propose_approach":
                enabled = enabled and phase == prompt.IMPLEMENTATION and self.has_implementation_target \
                    and not self.approach_approved and self.approach is None
            if action == "approve_approach":
                enabled = enabled and self.approach is not None and self.approach.ok and not self.approach_approved
            if action == "propose":
                enabled = enabled and (phase == prompt.ARCHITECTURE
                                       or (phase == prompt.IMPLEMENTATION and self.has_implementation_target
                                           and self.approach_approved))
            if action == "approve":
                enabled = enabled and usable and not signature_confirmation_required
            if action == "confirm_signature":
                enabled = enabled and signature_confirmation_required
            if action == "approve_architecture":
                enabled = enabled and phase == prompt.ARCHITECTURE and self.proposal is None
            if action == "reject":
                enabled = enabled and has_decision_item
            if action == "adapt":
                approach_adaptable = self.approach is not None and not self.approach_approved
                proposal_adaptable = bool(usable and self.proposal and self.proposal.entities)
                enabled = enabled and self.selected_iteration is None and (approach_adaptable or proposal_adaptable)
            if action in ("rebuild", "open_worktree"):
                enabled = enabled and self.proposal is not None
            if enabled:
                self.enabled_actions.add(action)
            button.state(["!disabled"] if enabled else ["disabled"])


def _scrolled_text(parent: Any, *, editable: bool = False, **options: Any) -> Any:
    """A read-only Text with scrollbars; the frame is ``text.master``."""
    frame = ttk.Frame(parent)
    text = tk.Text(frame, height=9, state="normal" if editable else "disabled", **options)
    vertical = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
    text.configure(yscrollcommand=vertical.set)
    vertical.pack(side=tk.RIGHT, fill=tk.Y)
    if options.get("wrap") == "none":
        horizontal = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=text.xview)
        text.configure(xscrollcommand=horizontal.set)
        horizontal.pack(side=tk.BOTTOM, fill=tk.X)
    text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    return text


def _rationale_text(proposal: steps.Proposal) -> str:
    assert proposal.response is not None
    text = proposal.response.rationale
    if proposal.response.questions:
        text += "\n\nQuestions:\n" + "\n".join(f"- {q}" for q in proposal.response.questions)
    return text


def _delta_text(proposal: steps.Proposal) -> str:
    assert proposal.delta is not None
    text = proposal.delta.summary()
    if proposal.request.phase == prompt.ARCHITECTURE:
        text += (f"\n\nArchitecture entity budget: {proposal.delta.architecture_entity_count()} / "
                 f"{proposal.request.max_entities}")
    batch_names = _proposal_batch_names(proposal)
    if len(batch_names) > 1:
        text = "Implementation batch:\n" + "\n".join(f"- {name}" for name in batch_names) + "\n\n" + text
    return text


def _proposal_batch_names(proposal: steps.Proposal) -> tuple[str, ...]:
    if len(proposal.request.batch) <= 1:
        return proposal.request.batch
    model = proposal.model
    return tuple(model.entities[usr].qualified_name if model is not None and usr in model.entities else usr
                 for usr in proposal.request.batch)


def _set_text(widget: Any, text: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", tk.END)
    widget.insert("1.0", text)
    widget.configure(state="disabled")


def _set_editable_text(widget: Any, text: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", tk.END)
    widget.insert("1.0", text)


def _historical_rationale(record: steplog.StepRecord) -> str:
    parts = []
    if record.request:
        parts.append("Request:\n" + record.request)
    if record.rationale:
        parts.append("Rationale:\n" + record.rationale)
    if record.reason:
        parts.append("Reason:\n" + record.reason)
    return "\n\n".join(parts) or "No rationale was recorded for this step."


def _historical_details(record: steplog.StepRecord) -> str:
    lines = [f"Phase: {record.phase}", f"Decision: {record.decision}"]
    if record.files:
        lines.append("Files:\n" + "\n".join(f"- {item}" for item in record.files))
    if record.entities_added:
        lines.append("Entities added:\n" + "\n".join(f"- {item}" for item in record.entities_added))
    if record.entities_changed:
        lines.append("Entities changed:\n" + "\n".join(f"- {item}" for item in record.entities_changed))
    if record.entities_renamed:
        renamed = "\n".join(f"- {old} -> {new}" for old, new in record.entities_renamed)
        lines.append("Entities renamed:\n" + renamed)
    return "\n\n".join(lines)


def _result_status(ok: bool | None) -> str:
    return "passed" if ok is True else "failed" if ok is False else "not run"


def _empty_result_text(label: str, ok: bool | None) -> str:
    return f"{label} passed without output." if ok is True else f"{label} failed without output." if ok is False \
        else f"{label} did not run."


def _test_text(proposal: steps.Proposal) -> str:
    if proposal.selected_tests:
        scope = "Selected tests:\n" + "\n".join(f"- {item}" for item in proposal.selected_tests)
    else:
        scope = "Full suite (no targeted tests selected)."
    result = proposal.test.output or _empty_result_text("Tests", proposal.test.ok)
    group = ""
    if proposal.request.grouped:
        names = _proposal_batch_names(proposal)
        group = ("Few-line group test coverage (recorded evidence required for every entity):\n"
                 + "\n".join(f"- {name}" for name in names) + "\n\n")
    return f"{group}{scope}\n\n{result}"
