"""Readable rule-check issue list with source navigation."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from icoda_core import rules
from icoda_core.model import DerivedModel


class IssueOverview:
    """A compact severity/rule/message table for the current derived model."""

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
        self.tree = ttk.Treeview(holder, columns=columns, show="headings")
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
        self.summary_var.set(f"Rule checks: {len(self.issues)} issues · {errors} errors · {warnings} warnings")
        self.note_var.set("No rule-check issues. This view remains available as project history grows."
                          if not self.issues else
                          "Double-click an issue to open its offending entity in the editor.")
        self.tree.delete(*self.tree.get_children())
        entities = model.entities
        for number, issue in enumerate(self.issues):
            entity = entities.get(issue.usr)
            name = entity.qualified_name if entity is not None else issue.usr
            location = f"{issue.file}:{issue.line}"
            values = (issue.severity.title(), issue.rule_id, name, issue.message, location)
            self.tree.insert("", tk.END, iid=str(number), values=values, tags=(issue.severity,))

    def _open_selected(self, _event: Any) -> None:
        for item in self.tree.selection():
            try:
                issue = self.issues[int(item)]
            except (ValueError, IndexError):
                continue
            self.open_editor(issue.file, issue.line)
