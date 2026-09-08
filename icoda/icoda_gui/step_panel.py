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
        row = ttk.Frame(self.frame)
        row.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(row, text="Phase").pack(side=tk.LEFT)
        ttk.Combobox(row, textvariable=self.phase_var, values=[prompt.ARCHITECTURE, prompt.IMPLEMENTATION],
                     state="readonly", width=14).pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(row, text="Request (empty: the agent chooses)").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.request_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 10))
        ttk.Label(row, text="Max entities").pack(side=tk.LEFT)
        ttk.Spinbox(row, from_=1, to=20, width=3, textvariable=self.max_entities_var).pack(side=tk.LEFT, padx=(2, 10))
        for action in ACTIONS:
            self.buttons[action] = ttk.Button(row, text=LABELS[action], command=self._pressed(action))
            self.buttons[action].pack(side=tk.LEFT, padx=2)

    def _build_texts(self) -> None:
        ttk.Label(self.frame, textvariable=self.title_var, font=("TkDefaultFont", 11, "bold"),
                  anchor="w").pack(fill=tk.X, padx=4)
        paned = ttk.PanedWindow(self.frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 4))
        self.rationale = tk.Text(paned, wrap="word", height=9, state="disabled")
        paned.add(self.rationale, weight=3)
        self.details = tk.Text(paned, wrap="none", height=9, state="disabled", font=("TkFixedFont", 10))
        paned.add(self.details, weight=2)

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
        elif proposal.ok and proposal.response is not None and proposal.delta is not None:
            self.title_var.set(f"Step {proposal.number}: {proposal.response.title}  "
                               f"(attempt {proposal.attempts})")
            _set_text(self.rationale, _rationale_text(proposal))
            _set_text(self.details, proposal.delta.summary() + "\n\nbuild:\n" + proposal.build.output)
        else:
            self.title_var.set(f"Step {proposal.number}: no usable proposal — {proposal.error}")
            _set_text(self.rationale, (proposal.response.rationale if proposal.response else "") or proposal.reply)
            _set_text(self.details, proposal.build.output or proposal.error)
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


def _rationale_text(proposal: steps.Proposal) -> str:
    assert proposal.response is not None
    text = proposal.response.rationale
    if proposal.response.questions:
        text += "\n\nQuestions:\n" + "\n".join(f"- {q}" for q in proposal.response.questions)
    return text


def _set_text(widget: Any, text: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", tk.END)
    widget.insert("1.0", text)
    widget.configure(state="disabled")
