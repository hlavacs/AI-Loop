"""The step panel: what the next step should do, the proposal's rationale, its delta and build output, and the
decision buttons (Propose, Approve, Reject, Adapt, Rebuild, Undo)."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from icoda_core import prompt, steps

ACTIONS = ("propose", "approve", "reject", "adapt", "rebuild", "open_worktree", "undo", "commit_manual")
LABELS = {"propose": "Propose", "approve": "Approve", "reject": "Reject…", "adapt": "Adapt…",
          "rebuild": "Rebuild", "open_worktree": "Open worktree", "undo": "Undo last step",
          "commit_manual": "Commit manual edits"}
NEEDS_PROPOSAL = {"approve", "reject", "adapt", "rebuild", "open_worktree"}


class StepPanel:
    """Controls in a frame; ``on_action`` receives the name of the pressed button."""

    def __init__(self, parent: Any, on_action: Callable[[str], None]) -> None:
        self.frame = ttk.Frame(parent)
        self.on_action = on_action
        self.proposal: steps.Proposal | None = None
        self.busy = False
        self.phase_var = tk.StringVar(value=prompt.ARCHITECTURE)
        self.request_var = tk.StringVar(value="")
        self.max_entities_var = tk.IntVar(value=5)
        self.title_var = tk.StringVar(value="No proposal")
        self.buttons: dict[str, Any] = {}
        self._build_request_row()
        self._build_texts()
        self.show(None)

    def _build_request_row(self) -> None:
        request_row = ttk.Frame(self.frame)
        request_row.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(request_row, text="Phase").pack(side=tk.LEFT)
        ttk.Combobox(request_row, textvariable=self.phase_var, values=[prompt.ARCHITECTURE, prompt.IMPLEMENTATION],
                     state="readonly", width=14).pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(request_row, text="Request (empty: the agent chooses)").pack(side=tk.LEFT)
        ttk.Entry(request_row, textvariable=self.request_var).pack(side=tk.LEFT, fill=tk.X, expand=True,
                                                                   padx=(2, 10))
        ttk.Label(request_row, text="Max entities").pack(side=tk.LEFT)
        ttk.Spinbox(request_row, from_=1, to=20, width=3, textvariable=self.max_entities_var).pack(side=tk.LEFT,
                                                                                                  padx=(2, 10))
        action_row = ttk.Frame(self.frame)
        action_row.pack(fill=tk.X, padx=4, pady=(0, 2))
        for action in ACTIONS:
            self.buttons[action] = ttk.Button(action_row, text=LABELS[action], command=self._pressed(action))
            self.buttons[action].pack(side=tk.LEFT, padx=2)

    def _build_texts(self) -> None:
        ttk.Label(self.frame, textvariable=self.title_var, font=("TkDefaultFont", 11, "bold"),
                  anchor="w").pack(fill=tk.X, padx=4)
        paned = ttk.PanedWindow(self.frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 4))
        self.rationale = _scrolled_text(paned, wrap="word")
        paned.add(self.rationale.master, weight=3)
        self.detail_notebook = ttk.Notebook(paned)
        self.details = _scrolled_text(self.detail_notebook, wrap="none", font=("TkFixedFont", 10))
        self.source_diff = _scrolled_text(self.detail_notebook, wrap="none", font=("TkFixedFont", 10))
        self.build_output = _scrolled_text(self.detail_notebook, wrap="none", font=("TkFixedFont", 10))
        self.detail_notebook.add(self.details.master, text="Delta")
        self.detail_notebook.add(self.source_diff.master, text="Source diff")
        self.detail_notebook.add(self.build_output.master, text="Build")
        paned.add(self.detail_notebook, weight=2)

    def _pressed(self, action: str) -> Callable[[], None]:
        return lambda: self.on_action(action)

    # -- state ----------------------------------------------------------------------------

    def request(self) -> prompt.StepRequest:
        return prompt.StepRequest(self.phase_var.get(), 0, self.request_var.get().strip(),
                                  max_entities=int(self.max_entities_var.get() or 5))

    def show(self, proposal: steps.Proposal | None) -> None:
        """Present a proposal (or clear the panel) and enable the buttons that apply to it."""
        self.proposal = proposal
        if proposal is None:
            self.title_var.set("No proposal")
            _set_text(self.rationale, "")
            _set_text(self.details, "")
            _set_text(self.source_diff, "")
            _set_text(self.build_output, "")
        elif proposal.ok and proposal.response is not None and proposal.delta is not None:
            self.title_var.set(f"Step {proposal.number}: {proposal.response.title}  "
                               f"(attempt {proposal.attempts})")
            _set_text(self.rationale, _rationale_text(proposal))
            _set_text(self.details, _delta_text(proposal))
            _set_text(self.source_diff, proposal.source_diff or "No source changes.")
            _set_text(self.build_output, proposal.build.output or "Build passed without output.")
        else:
            self.title_var.set(f"Step {proposal.number}: no usable proposal — {proposal.error}")
            _set_text(self.rationale, (proposal.response.rationale if proposal.response else "") or proposal.reply)
            _set_text(self.details, proposal.error)
            _set_text(self.source_diff, proposal.source_diff or "No source changes.")
            _set_text(self.build_output, proposal.build.output or "Build did not run.")
        self._update_buttons()

    def show_failure(self, text: str) -> None:
        """A step that raised: the whole message in the details box, buttons as before."""
        self.title_var.set("Step failed — " + (text.strip().splitlines()[0] if text.strip() else "no details"))
        _set_text(self.details, text)
        self._update_buttons()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self._update_buttons()

    def _update_buttons(self) -> None:
        usable = self.proposal is not None and self.proposal.ok
        for action, button in self.buttons.items():
            enabled = not self.busy and (action not in NEEDS_PROPOSAL or self.proposal is not None)
            if action == "approve":
                enabled = enabled and usable
            button.state(["!disabled"] if enabled else ["disabled"])


def _scrolled_text(parent: Any, **options: Any) -> Any:
    """A read-only Text with scrollbars; the frame is ``text.master``."""
    frame = ttk.Frame(parent)
    text = tk.Text(frame, height=9, state="disabled", **options)
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
    return text


def _set_text(widget: Any, text: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", tk.END)
    widget.insert("1.0", text)
    widget.configure(state="disabled")
