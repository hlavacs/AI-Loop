"""The step panel: implementation approach, code proposal, verification output, and developer decisions.

Only the buttons that belong to the project's phase are shown; a sentence above them says what to do next, and
every button explains itself (and why it is grey) in a tooltip. While a step runs, a moving bar and the current
activity replace the buttons, with Cancel for the parts that can be stopped.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from icoda_core import (
    adaptation,
    grouping,
    guidance,
    implementation_queue,
    persistence,
    prompt,
    steplog,
    steps,
)
from icoda_gui import tooltip

ACTIONS = ("propose_approach", "approve_approach", "propose", "approve_architecture", "approve",
           "confirm_signature", "reject", "adapt", "rebuild", "open_worktree", "undo", "commit_manual")
LABELS = {"propose_approach": "Propose approach", "approve_approach": "Approve approach",
          "propose": "Propose", "approve": "Approve", "reject": "Reject…", "adapt": "Adapt…",
          "rebuild": "Rebuild", "open_worktree": "Open worktree", "undo": "Undo last step",
          "commit_manual": "Commit manual edits", "approve_architecture": "Approve architecture",
          "confirm_signature": "Confirm signatures"}
MORE_ACTIONS = ("rebuild", "open_worktree", "commit_manual")  # rarely needed: behind the More… button
PHASE_ACTIONS: dict[str, tuple[str, ...]] = {
    prompt.ARCHITECTURE: ("propose", "approve", "confirm_signature", "reject", "adapt", "approve_architecture",
                          "undo"),
    prompt.IMPLEMENTATION: ("propose_approach", "approve_approach", "propose", "approve", "confirm_signature",
                            "reject", "adapt", "undo"),
}
HELP = {
    "propose_approach": ("Ask the agent how the current target should be implemented (prose only, no code).",
                         "needs an unimplemented target and no approach waiting for a decision"),
    "approve_approach": ("Accept the approach; the next Propose asks for the code and its tests.",
                         "needs an approach that is waiting for a decision"),
    "propose": ("Ask the agent for the next step. It is built and tested in a separate worktree first.",
                "in the implementation phase it needs an approved approach"),
    "approve": ("Take the proposal into the project: promote, rebuild, log and commit it.",
                "needs a proposal that builds and passes its tests (and confirmed signatures)"),
    "confirm_signature": ("Confirm that the changed function signatures are intended.",
                          "only shown when a proposal changes signatures"),
    "reject": ("Discard the proposal or approach; the reason goes into the next prompt.",
               "needs a proposal or an approach"),
    "adapt": ("Ask again with constraints, or with the edits you made in the Summary tab.",
              "needs a usable proposal or a pending approach"),
    "approve_architecture": ("Close the architecture phase and start implementing function by function.",
                             "decide on the current proposal first"),
    "undo": ("Revert the last approved step with a commit of its own.", "not while a step is running"),
    "rebuild": ("Build, test and parse the worktree again after editing it by hand.", "needs a proposal"),
    "open_worktree": ("Open the proposal's worktree in the editor.", "needs a proposal"),
    "commit_manual": ("Commit your own edits as a manual step so the next proposal starts from a clean tree.",
                      "not while a step is running"),
}
CONTROL_HELP = {
    "request": "What the next step should do. Leave it empty and the agent chooses the most useful step.",
    "max_entities": "How many classes and functions one architecture step may add at most.",
    "batch_size": "How many functions one implementation step may implement together.",
    "scope": "Where the implementation queue takes its next targets from.",
    "grouping": "One function per step, or a validated group of short functions.",
    "auto_approve": "Approve every step automatically while build and tests pass; stops at the first failure.",
    "cancel": "Stop the running agent call, build or test. Nothing is recorded.",
    "more": "Rarely needed actions: Rebuild, Open worktree, Commit manual edits.",
}


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
        self.target_name = ""
        self.remaining = 0
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
        self.hint_var = tk.StringVar(value="")
        self.activity_var = tk.StringVar(value="")
        self.buttons: dict[str, Any] = {}
        self.enabled_actions: set[str] = set()
        self.visible_actions: tuple[str, ...] = ()
        self.disabled_reasons: dict[str, str] = {}
        self.cancellable = False
        self.project_open = False
        self.has_model = True
        self.provider_ready = True
        self.auto_approve_note = ""
        self.tooltips: dict[str, tooltip.Tooltip] = {}
        self.details_visible = True
        self.on_details_visibility: Callable[[], None] | None = None
        self._build_request_row()
        self._build_texts()
        self.show(None)

    def _build_request_row(self) -> None:
        request_row = ttk.Frame(self.frame)
        request_row.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(request_row, text="Phase").pack(side=tk.LEFT)
        self.phase_label = ttk.Label(request_row, textvariable=self.phase_var, width=14)
        self.phase_label.pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(request_row, text="Request").pack(side=tk.LEFT)
        self.request_entry = ttk.Entry(request_row, textvariable=self.request_var)
        self.request_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 10))
        self.tooltips["request"] = tooltip.attach(self.request_entry, CONTROL_HELP["request"])
        ttk.Label(request_row, text="Max entities").pack(side=tk.LEFT)
        self.max_entities_spinbox = ttk.Spinbox(request_row, from_=1, to=20, width=3,
                                                textvariable=self.max_entities_var)
        self.max_entities_spinbox.pack(side=tk.LEFT, padx=(2, 10))
        self.tooltips["max_entities"] = tooltip.attach(self.max_entities_spinbox, CONTROL_HELP["max_entities"])
        ttk.Label(request_row, text="Batch size").pack(side=tk.LEFT)
        self.batch_size_spinbox = ttk.Spinbox(request_row, from_=1, to=20, width=3,
                                               textvariable=self.batch_size_var,
                                               command=self._batch_size_changed)
        self.batch_size_spinbox.pack(side=tk.LEFT, padx=(2, 0))
        self.batch_size_spinbox.bind("<Return>", self._batch_size_changed)
        self.batch_size_spinbox.bind("<FocusOut>", self._batch_size_changed)
        self.tooltips["batch_size"] = tooltip.attach(self.batch_size_spinbox, CONTROL_HELP["batch_size"])
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
        self.tooltips["scope"] = tooltip.attach(self.scope_combobox, CONTROL_HELP["scope"])
        self._build_grouping_control(queue_row)
        self.auto_approve_check = ttk.Checkbutton(
            queue_row, text="Auto-approve while gates pass", variable=self.auto_approve_var,
            command=self._auto_approve_changed)
        self.auto_approve_check.pack(side=tk.LEFT, padx=(10, 0))
        self.tooltips["auto_approve"] = tooltip.attach(self.auto_approve_check, CONTROL_HELP["auto_approve"])
        self.hint_label = ttk.Label(self.frame, textvariable=self.hint_var, anchor="w", justify="left",
                                    wraplength=1200, foreground="#1f4e79")
        self.hint_label.pack(fill=tk.X, padx=6, pady=(2, 2))
        self.action_row = ttk.Frame(self.frame)
        self.action_row.pack(fill=tk.X, padx=4, pady=(0, 2))
        for action in ACTIONS:
            self.buttons[action] = ttk.Button(self.action_row, text=LABELS[action], command=self._pressed(action))
            self.tooltips[action] = tooltip.attach(self.buttons[action], self._help_for(action))
        self.more_button = ttk.Menubutton(self.action_row, text="More…")
        self.more_menu = tk.Menu(self.more_button, tearoff=0)
        for action in MORE_ACTIONS:
            self.more_menu.add_command(label=LABELS[action], command=self._pressed(action))
        self.more_button.configure(menu=self.more_menu)
        self.tooltips["more"] = tooltip.attach(self.more_button, CONTROL_HELP["more"])
        self.cancel_button = ttk.Button(self.action_row, text="Cancel", command=self._pressed("cancel"))
        self.tooltips["cancel"] = tooltip.attach(self.cancel_button, CONTROL_HELP["cancel"])
        self.progress = ttk.Progressbar(self.action_row, mode="indeterminate", length=160)
        self.activity_label = ttk.Label(self.action_row, textvariable=self.activity_var, foreground="#1f77b4")

    def _build_texts(self) -> None:
        title_row = ttk.Frame(self.frame)
        title_row.pack(fill=tk.X, padx=4)
        self.details_toggle = ttk.Button(title_row, text="Hide details", command=self.toggle_details)
        self.details_toggle.pack(side=tk.RIGHT, padx=(6, 0))
        tooltip.attach(self.details_toggle, "Show or hide the review details to give the graph and editor more space.")
        ttk.Label(title_row, textvariable=self.title_var, font=("TkDefaultFont", 11, "bold"),
                  anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
        status_row = ttk.Frame(self.frame)
        status_row.pack(fill=tk.X, padx=4)
        ttk.Label(status_row, textvariable=self.build_status_var).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Label(status_row, textvariable=self.test_status_var).pack(side=tk.LEFT, padx=(0, 16))
        self.signature_label = ttk.Label(status_row, textvariable=self.signature_var)
        self.signature_label.pack(side=tk.LEFT)
        paned = self.review_panes = ttk.PanedWindow(self.frame, orient=tk.HORIZONTAL)
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
        self.prompt_view = _scrolled_text(self.detail_notebook, wrap="word", font=("TkFixedFont", 10))
        self.reply_view = _scrolled_text(self.detail_notebook, wrap="word", font=("TkFixedFont", 10))
        self.detail_notebook.add(self.approach_text.master, text="Approach")
        self.detail_notebook.add(self.details.master, text="Delta")
        self.detail_notebook.add(self.signature.master, text="Signatures")
        self.detail_notebook.add(self.entity_summary.master, text="Summary")
        self.detail_notebook.add(self.source_diff.master, text="Diff")
        self.detail_notebook.add(self.build_output.master, text="Build")
        self.detail_notebook.add(self.test_output.master, text="Tests")
        self.detail_notebook.add(self.prompt_view.master, text="Prompt")
        self.detail_notebook.add(self.reply_view.master, text="Reply")
        paned.add(self.detail_notebook, weight=2)

    def toggle_details(self) -> None:
        self.set_details_visible(not self.details_visible)

    def set_details_visible(self, visible: bool) -> None:
        """Collapsing the review pane retains every tab and any edited summary."""
        if visible == self.details_visible:
            return
        self.details_visible = visible
        if visible:
            self.review_panes.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 4))
        else:
            self.review_panes.pack_forget()
        self.details_toggle.configure(text="Hide details" if visible else "Show details")
        if self.on_details_visibility is not None:
            self.on_details_visibility()

    def _pressed(self, action: str) -> Callable[[], None]:
        return lambda: self.on_action(action)

    def _help_for(self, action: str) -> Callable[[], str]:
        """The button's tooltip: what it does, plus why it is grey when it is."""
        def text() -> str:
            what, when = HELP[action]
            reason = self.disabled_reasons.get(action)
            return f"{what}\nAvailable: {when}." + (f"\nGrey now: {reason}." if reason else "")

        return text

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
        self.tooltips["grouping"] = tooltip.attach(self.grouping_combobox, CONTROL_HELP["grouping"])

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
        self.target_name = ", ".join(batch) if len(batch) > 1 else (target or "")
        self.remaining = remaining
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
            self._show_exchange(approach.prompt_text, approach.reply)
        _set_text(self.approach_text, text)
        self.auto_approve_note = ""
        self._update_buttons()
        if approach is not None:
            self.set_details_visible(True)
            self.detail_notebook.select(self.approach_text.master)

    def show(self, proposal: steps.Proposal | None) -> None:
        """Present a proposal (or clear the panel) and enable the buttons that apply to it."""
        self.set_details_visible(proposal is not None)
        self.selected_iteration = None
        self.proposal = proposal
        self.signature_confirmed = False
        self.auto_approve_note = ""
        self._show_exchange(proposal.prompt_text if proposal else "", proposal.reply if proposal else "")
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

    def _show_exchange(self, prompt_text: str, reply: str) -> None:
        """The Prompt and Reply tabs: exactly what went to the agent and what came back."""
        _set_text(self.prompt_view, prompt_text or "No prompt has been sent for this item.")
        _set_text(self.reply_view, reply or "No reply has been received for this item.")

    def _show_entity_summary(self, proposal: steps.Proposal) -> None:
        text = adaptation.render_summary(proposal.entities) if proposal.entities else adaptation.NO_ENTITY_SUMMARY
        _set_editable_text(self.entity_summary, text)

    def edited_entity_summary(self) -> str:
        """Return the developer's current text from the editable structured-summary tab."""
        return str(self.entity_summary.get("1.0", "end-1c"))

    def show_adaptation_problems(self, problems: tuple[str, ...]) -> None:
        """Keep the edited text intact and make deterministic parse problems visible."""
        self.set_details_visible(True)
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
        self.set_details_visible(True)
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
        _set_text(self.prompt_view, "The prompt of a historical step is not stored in the step log.")
        _set_text(self.reply_view, "The reply of a historical step is not stored in the step log.")
        self._update_signature_status()
        self.detail_notebook.select(self.details.master)
        self._update_buttons()

    def show_failure(self, text: str) -> None:
        """A step that raised: the whole message in the details box, buttons as before."""
        self.set_details_visible(True)
        self.detail_notebook.select(self.details.master)
        self.title_var.set("Step failed — " + (text.strip().splitlines()[0] if text.strip() else "no details"))
        _set_text(self.details, text)
        self._update_buttons()

    def show_auto_approve_refusal(self, reason: str) -> None:
        """Auto-approve paused: the proposal stays as it is; the hint line says why the developer must decide."""
        self.auto_approve_note = f"Auto-approve paused: {reason}. Decide yourself."
        self._update_buttons()

    def set_project_facts(self, project_open: bool, has_model: bool = True, provider_ready: bool = True) -> None:
        """What the hint needs to know about the surroundings: is a project open, built, and an agent chosen."""
        self.project_open, self.has_model, self.provider_ready = project_open, has_model, provider_ready
        self._update_buttons()

    def set_busy(self, busy: bool, activity: str = "", cancellable: bool = False) -> None:
        """Replace the buttons with a moving bar and the activity while work runs; Cancel when it can be stopped."""
        self.busy, self.cancellable = busy, cancellable
        self.activity_var.set(activity)
        if busy:
            self.progress.start(40)
        else:
            self.progress.stop()
        self._update_buttons()

    def set_activity(self, activity: str) -> None:
        """The runner's progress message, shown next to the moving bar."""
        self.activity_var.set(activity)
        if self.busy:
            self.hint_var.set(guidance.next_step(self._situation()))

    def _update_buttons(self) -> None:
        """Enable, explain and show the buttons of the phase; then refresh the hint line."""
        self.enabled_actions = set()
        self.disabled_reasons = {}
        for action, button in self.buttons.items():
            reason = self._blocked_reason(action)
            if reason is None:
                self.enabled_actions.add(action)
            else:
                self.disabled_reasons[action] = reason
            button.state(["!disabled"] if reason is None else ["disabled"])
        self._arrange_action_row()
        self.hint_var.set(guidance.next_step(self._situation()))

    def _signature_confirmation_required(self) -> bool:
        usable = self.proposal is not None and self.proposal.ok
        return bool(usable and self.proposal and self.proposal.delta and self.proposal.delta.signature_changes
                    and not self.signature_confirmed)

    def _blocked_reason(self, action: str) -> str | None:
        """None when the action is possible now, otherwise a short reason (shown in the tooltip)."""
        if self.busy:
            return "a step is running"
        usable = self.proposal is not None and self.proposal.ok
        phase = self.phase_var.get()
        pending_approach = self.approach is not None and not self.approach_approved
        if action == "propose_approach":
            if phase != prompt.IMPLEMENTATION:
                return "only in the implementation phase"
            if not self.has_implementation_target:
                return "the implementation queue is empty"
            if self.approach_approved:
                return "the approach is already approved; press Propose"
            if self.approach is not None:
                return "decide on the current approach first"
        elif action == "approve_approach":
            if self.approach is None or self.approach_approved:
                return "no approach is waiting for a decision"
            if not self.approach.ok:
                return "the approach is not usable; ask again or reject it"
        elif action == "propose":
            if phase == prompt.IMPLEMENTATION:
                if not self.has_implementation_target:
                    return "the implementation queue is empty"
                if not self.approach_approved:
                    return "approve an approach first"
            elif phase != prompt.ARCHITECTURE:
                return "save the specification first"
        elif action == "approve":
            if not usable:
                return "no proposal that builds and passes its tests"
            if self._signature_confirmation_required():
                return "confirm the signature changes first"
        elif action == "confirm_signature":
            if not self._signature_confirmation_required():
                return "no unconfirmed signature changes"
        elif action == "approve_architecture":
            if phase != prompt.ARCHITECTURE:
                return "only in the architecture phase"
            if self.proposal is not None:
                return "approve or reject the current proposal first"
        elif action == "reject":
            if self.proposal is None and not pending_approach:
                return "nothing to reject"
        elif action == "adapt":
            proposal_adaptable = bool(usable and self.proposal and self.proposal.entities)
            if self.selected_iteration is not None:
                return "a historical step is shown"
            if not (pending_approach or proposal_adaptable):
                return "needs a usable proposal or a pending approach"
        elif action in ("rebuild", "open_worktree"):
            if self.proposal is None:
                return "no proposal"
        return None

    def _arrange_action_row(self) -> None:
        """Pack the phase's buttons in order (Confirm signatures only when needed), then More…; busy shows the bar."""
        for widget in (*self.buttons.values(), self.more_button, self.cancel_button, self.progress,
                       self.activity_label):
            widget.pack_forget()
        if self.busy:
            self.progress.pack(side=tk.LEFT, padx=(2, 8), pady=2)
            self.activity_label.pack(side=tk.LEFT, padx=(0, 8))
            if self.cancellable:
                self.cancel_button.pack(side=tk.LEFT, padx=2)
            self.visible_actions = ()
            return
        actions = [action for action in PHASE_ACTIONS.get(self.phase_var.get(), ())
                   if action != "confirm_signature" or self._signature_confirmation_required()]
        for action in actions:
            self.buttons[action].pack(side=tk.LEFT, padx=2)
        self.visible_actions = tuple(actions)
        if self.project_open and self.phase_var.get() != persistence.ProjectPhase.SPECIFICATION.value:
            self.more_button.pack(side=tk.LEFT, padx=(8, 2))
            for index, action in enumerate(MORE_ACTIONS):
                self.more_menu.entryconfigure(index, state="normal" if action in self.enabled_actions
                                              else "disabled")

    def _situation(self) -> guidance.Situation:
        """The facts the hint sentence is built from."""
        proposal = "none"
        if self.proposal is not None:
            proposal = "ok" if self.proposal.ok else "failed"
        approach = "none"
        if self.approach_approved:
            approach = "approved"
        elif self.approach is not None:
            approach = "pending" if self.approach.ok else "failed"
        number = self.proposal.number if self.proposal is not None else 0
        return guidance.Situation(
            project_open=self.project_open, phase=self.phase_var.get(), busy=self.busy,
            activity=self.activity_var.get(), cancellable=self.cancellable, has_model=self.has_model,
            provider_ready=self.provider_ready, proposal=proposal, step_number=number,
            signature_confirmation_required=self._signature_confirmation_required(), approach=approach,
            has_target=self.has_implementation_target, target=self.target_name, remaining=self.remaining,
            historical_step=self.selected_iteration, auto_approve_note=self.auto_approve_note)


def _scrolled_text(parent: Any, *, editable: bool = False, **options: Any) -> Any:
    """A read-only Text with scrollbars; the frame is ``text.master``."""
    frame = ttk.Frame(parent)
    text = tk.Text(frame, height=9, width=40, state="normal" if editable else "disabled", **options)
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
        group = ("Few-line group recorded-test reachability (required for every entity):\n"
                 + "\n".join(f"- {name}" for name in names) + "\n\n")
    return f"{group}{scope}\n\n{result}"
