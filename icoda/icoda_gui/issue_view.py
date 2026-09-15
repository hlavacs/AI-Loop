"""Readable rule-check issue list with source navigation.

Errors come first, one row each. Warnings are folded into one row per rule (with the count) so that a long list
of the same advice does not bury the few errors; a fold opens on click and shows the entities.
"""

from __future__ import annotations

import tkinter as tk
from collections import OrderedDict
from collections.abc import Callable, Sequence
from tkinter import ttk
from typing import Any

from icoda_core import rules
from icoda_core.model import DerivedModel


def fold_warnings(issues: Sequence[rules.Issue]) -> list[tuple[str, list[int]]]:
    """Warning indexes grouped by rule, in first-seen order: [(rule_id, [index, ...]), ...]."""
    groups: OrderedDict[str, list[int]] = OrderedDict()
    for index, issue in enumerate(issues):
        if issue.severity != "error":
            groups.setdefault(issue.rule_id, []).append(index)
    return list(groups.items())


class IssueOverview:
    """A severity/rule/message table: errors first, warnings folded by rule."""

    def __init__(self, parent: Any, open_editor: Callable[[str, int], None]) -> None:
        self.frame = ttk.Frame(parent)
        self.open_editor = open_editor
        self.issues: tuple[rules.Issue, ...] = ()
        self.summary_var = tk.StringVar(value="Rule checks: no model")
        self.note_var = tk.StringVar(value="")
        self._build()

    def _build(self) -> None:
        ttk.Label(self.frame, textvariable=self.summary_var, anchor="w",
                  font=("TkDefaultFont", 11, "bold")).pack(fill=tk.X, padx=8, pady=(8, 2))
        ttk.Label(self.frame, textvariable=self.note_var, anchor="w",
                  foreground="#555555").pack(fill=tk.X, padx=8, pady=(0, 6))
        holder = ttk.Frame(self.frame)
        holder.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        columns = ("severity", "rule", "entity", "message", "location")
        self.tree = ttk.Treeview(holder, columns=columns, show="tree headings")
        self.tree.column("#0", width=24, stretch=False)
        for name, heading, width in (("severity", "Severity", 65), ("rule", "Rule", 110),
                                     ("entity", "Entity", 155), ("message", "What to do", 305),
                                     ("location", "Location", 125)):
            self.tree.heading(name, text=heading)
            self.tree.column(name, width=width, anchor="w")
        scrollbar = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.tag_configure("error", foreground="#b42318")
        self.tree.tag_configure("warning", foreground="#9a6700")
        self.tree.bind("<Double-Button-1>", self._open_selected)

    def show(self, model: DerivedModel, history: rules.History) -> None:
        self.issues = rules.check(model, history)
        errors = sum(issue.severity == "error" for issue in self.issues)
        warnings = len(self.issues) - errors
        folded = fold_warnings(self.issues)
        summary = f"Rule checks: {len(self.issues)} issues · {errors} errors · {warnings} warnings"
        if folded:
            summary += f" (folded into {len(folded)} rules)"
        self.summary_var.set(summary)
        if not self.issues:
            note = "No rule-check issues. This view remains available as project history grows."
        elif folded:
            note = ("Errors are listed first. Click a warning row to open its entities; double-click an entity "
                    "to open it in the editor.")
        else:
            note = "Double-click an issue to open its offending entity in the editor."
        self.note_var.set(note)
        self.tree.delete(*self.tree.get_children())
        for number, issue in enumerate(self.issues):
            if issue.severity == "error":
                self.tree.insert("", tk.END, iid=str(number), values=self._row(model, issue), tags=("error",))
        for rule_id, indexes in folded:
            first = self.issues[indexes[0]]
            values = ("Warning", rule_id, f"{len(indexes)} entities", first.message, "")
            parent = self.tree.insert("", tk.END, iid=f"rule:{rule_id}", values=values, tags=("warning",),
                                      open=False)
            for index in indexes:
                self.tree.insert(parent, tk.END, iid=str(index), values=self._row(model, self.issues[index]),
                                 tags=("warning",))

    @staticmethod
    def _row(model: DerivedModel, issue: rules.Issue) -> tuple[str, str, str, str, str]:
        entity = model.entities.get(issue.usr)
        name = entity.qualified_name if entity is not None else issue.usr
        return (issue.severity.title(), issue.rule_id, name, issue.message, f"{issue.file}:{issue.line}")

    def _open_selected(self, _event: Any) -> None:
        for item in self.tree.selection():
            try:
                issue = self.issues[int(item)]
            except (ValueError, IndexError):
                continue
            self.open_editor(issue.file, issue.line)
