"""Readable specification coverage and callable recorded-test reachability overview."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Iterable, Mapping
from tkinter import ttk
from typing import Any

from icoda_core import coverage_index, requirement_coverage
from icoda_core.model import DerivedModel
from icoda_core.steplog import StepLog, StepRecord


class CoverageOverview:
    """Compact requirement coverage and callable reachability tables with their evidence."""

    def __init__(self, parent: Any, open_editor: Callable[[str, int], None]) -> None:
        self.frame = ttk.Frame(parent)
        self.open_editor = open_editor
        self.index = coverage_index.CoverageIndex()
        self.requirements: tuple[requirement_coverage.RequirementCoverage, ...] = ()
        self.requirements_summary_var = tk.StringVar(value="Specification coverage: no model")
        self.requirements_note_var = tk.StringVar(value="")
        self.summary_var = tk.StringVar(value="Recorded test reachability: no model")
        self.note_var = tk.StringVar(value="")
        self._build()

    def _build(self) -> None:
        ttk.Label(self.frame, textvariable=self.requirements_summary_var, anchor="w",
                  font=("TkDefaultFont", 11, "bold")).pack(fill=tk.X, padx=8, pady=(8, 2))
        ttk.Label(self.frame, textvariable=self.requirements_note_var, anchor="w",
                  foreground="#555555").pack(fill=tk.X, padx=8, pady=(0, 6))
        requirements_holder = ttk.Frame(self.frame)
        requirements_holder.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        requirement_columns = ("coverage", "id", "kind", "item", "entities")
        self.requirement_tree = ttk.Treeview(
            requirements_holder, columns=requirement_columns, show="headings", height=6)
        for name, heading, width in (
            ("coverage", "Coverage", 90), ("id", "ID", 70), ("kind", "Kind", 90),
            ("item", "Specification item", 260), ("entities", "Implementing entities", 300),
        ):
            self.requirement_tree.heading(name, text=heading)
            self.requirement_tree.column(name, width=width, anchor="w")
        requirement_scrollbar = ttk.Scrollbar(
            requirements_holder, orient=tk.VERTICAL, command=self.requirement_tree.yview)
        self.requirement_tree.configure(yscrollcommand=requirement_scrollbar.set)
        self.requirement_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        requirement_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.requirement_tree.tag_configure("covered", foreground="#187a2f")
        self.requirement_tree.tag_configure("uncovered", foreground="#b42318")
        ttk.Label(self.frame, textvariable=self.summary_var, anchor="w",
                  font=("TkDefaultFont", 11, "bold")).pack(fill=tk.X, padx=8, pady=(0, 2))
        ttk.Label(self.frame, textvariable=self.note_var, anchor="w",
                  foreground="#555555").pack(fill=tk.X, padx=8, pady=(0, 6))
        holder = ttk.Frame(self.frame)
        holder.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        columns = ("coverage", "callable", "tests", "steps")
        self.tree = ttk.Treeview(holder, columns=columns, show="headings")
        for name, heading, width in (("coverage", "Reachability", 90), ("callable", "Callable", 260),
                                     ("tests", "Reaching recorded tests", 280),
                                     ("steps", "Evidence", 140)):
            self.tree.heading(name, text=heading)
            self.tree.column(name, width=width, anchor="w")
        scrollbar = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.tag_configure("covered", foreground="#187a2f")
        self.tree.tag_configure("uncovered", foreground="#b42318")
        self.tree.bind("<Double-Button-1>", self._open_selected)

    def show(self, model: DerivedModel, log: StepLog | Iterable[StepRecord],
             index: coverage_index.CoverageIndex | None = None,
             specification: Mapping[str, Any] | None = None) -> None:
        self.requirements = requirement_coverage.project(specification or {}, model)
        requirement_total = len(self.requirements)
        requirement_uncovered = sum(entry.uncovered for entry in self.requirements)
        requirement_covered = requirement_total - requirement_uncovered
        self.requirements_summary_var.set(
            "Specification coverage: no requirements or goals" if not requirement_total else
            f"Specification coverage: {requirement_covered}/{requirement_total} goals and requirements covered · "
            f"{requirement_uncovered} UNCOVERED")
        self.requirements_note_var.set(
            "No specification requirements or goals are available; add them in Project → Specification."
            if not requirement_total else
            "Coverage requires an exact @satisfies identifier; goals use G-1, G-2, ….")
        self.requirement_tree.delete(*self.requirement_tree.get_children())
        for requirement_entry in self.requirements:
            status = "UNCOVERED" if requirement_entry.uncovered else "Covered"
            entities = ", ".join(
                entity.qualified_name for entity in requirement_entry.implementing_entities)
            self.requirement_tree.insert(
                "", tk.END, iid=f"{requirement_entry.kind}:{requirement_entry.identifier}",
                values=(status, requirement_entry.identifier, requirement_entry.kind.title(),
                        requirement_entry.title,
                        entities or "No implementing entity"),
                tags=(status.lower(),),
            )
        self.index = index or coverage_index.build_index(model, log)
        total, uncovered = len(self.index.entries), len(self.index.uncovered)
        covered = total - uncovered
        self.summary_var.set("Recorded test reachability: no callable entities" if not total else
                             f"Recorded test reachability: {covered}/{total} analysed callables reached · "
                             f"{uncovered} not reached")
        self.note_var.set("No reaching recorded test identifiers are available; the overview remains available."
                          if total and not covered else
                          "This structural index uses successful step records and analysed call edges; it does not "
                          "measure test quality or behavior.")
        self.tree.delete(*self.tree.get_children())
        for entry in self.index.entries:
            status = "Reached" if entry.covered else "Not reached"
            callable_name = entry.qualified_name + (f"  {entry.signature}" if entry.signature else "")
            tests = ", ".join(entry.tests) if entry.tests else "No reaching recorded test"
            steps = ", ".join(_step_label(item) for item in entry.evidence) if entry.evidence else "—"
            self.tree.insert("", tk.END, iid=entry.usr, values=(status, callable_name, tests, steps),
                             tags=("covered" if entry.covered else "uncovered",))

    def _open_selected(self, _event: Any) -> None:
        entries = self.index.entry_map()
        for usr in self.tree.selection():
            entry = entries.get(usr)
            if entry is not None:
                self.open_editor(entry.file, entry.line)


def _step_label(evidence: coverage_index.CoverageEvidence) -> str:
    return f"#{evidence.step} {evidence.title}".rstrip()
