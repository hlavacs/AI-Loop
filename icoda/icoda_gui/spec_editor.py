"""The specification editor: one notebook page per section of ``specification.schema.json``.

The pages keep their state in plain Python (:meth:`FieldSet.get`, :meth:`RecordListPage.values`) and the Tk
widgets mirror it, so the editor can be driven and tested without a display.
"""

from __future__ import annotations

import copy
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Any

from icoda_core import specification
from icoda_core.specification import RECORD_SECTIONS, Specification
from icoda_gui import screen

ENTRY_WIDTH = 64
SECTION_ORDER = ("objectives", "in_scope", "out_of_scope", "stakeholders", "assumptions", "constraints",
                 "dependencies", "use_cases", "requirements", "decisions", "risks", "verification",
                 "open_questions")
SECTION_TITLES = {
    "objectives": "Objectives", "in_scope": "In scope", "out_of_scope": "Out of scope",
    "stakeholders": "Stakeholders", "assumptions": "Assumptions", "constraints": "Constraints",
    "dependencies": "Dependencies", "use_cases": "Use cases", "requirements": "Requirements",
    "decisions": "Decisions", "risks": "Risks", "verification": "Verification", "open_questions": "Open questions",
}
LINES_HINTS = {
    "objectives": "What the project is for — one objective per line.",
    "in_scope": "What the project does — one item per line.",
    "out_of_scope": "What the project deliberately does not do — one item per line.",
    "stakeholders": "Who cares about the project and why — one per line.",
    "assumptions": "What is taken for granted — one per line.",
    "constraints": "Limits the solution must respect (time, money, law, hardware) — one per line.",
    "dependencies": "External systems, libraries and data the project relies on — one per line.",
    "open_questions": "Questions nobody has answered yet — one per line.",
}


@dataclass(frozen=True)
class FieldSpec:
    """One editable value on a page.

    ``kind`` is ``entry`` (one line), ``text`` (many lines), ``lines`` (a list, one per line), ``tags`` (a list,
    comma separated), ``choice`` (one of ``options``), ``multi`` (any of ``options``), ``flag`` or ``int``.
    """

    key: str
    label: str
    kind: str = "entry"
    options: Sequence[str] = ()
    height: int = 4


OVERVIEW_FIELDS = (FieldSpec("title", "Title"), FieldSpec("summary", "Summary", "text", height=8))
RECORD_FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    "use_cases": (FieldSpec("title", "Title"), FieldSpec("actor", "Actor"),
                  FieldSpec("description", "Description", "text", height=8)),
    "requirements": (FieldSpec("title", "Title"),
                     FieldSpec("priority", "Priority", "choice", ("must", "should", "could")),
                     FieldSpec("category", "Category", "choice",
                               ("", "functional", "quality", "interface", "constraint")),
                     FieldSpec("use_cases", "Use cases (UC-1, UC-2, …)", "tags"),
                     FieldSpec("description", "Description", "text", height=8)),
    "decisions": (FieldSpec("title", "Title"), FieldSpec("rationale", "Rationale", "text", height=8)),
    "risks": (FieldSpec("title", "Title"),
              FieldSpec("severity", "Severity", "choice", ("", "low", "medium", "high")),
              FieldSpec("mitigation", "Mitigation", "text", height=8)),
    "verification": (FieldSpec("requirement", "Requirement (R-n)"),
                     FieldSpec("method", "Method", "choice",
                               ("unit test", "integration test", "manual test", "review", "analysis")),
                     FieldSpec("description", "Description", "text", height=8)),
}
RECORD_DEFAULTS: dict[str, dict[str, Any]] = {"requirements": {"priority": "must"},
                                              "verification": {"method": "unit test"}}
PROFILE_FIELDS = (
    FieldSpec("language", "Language", "choice", ("C++", "Python")),
    FieldSpec("standard", "Standard"),
    FieldSpec("modules", "C++20 modules", "flag"),
    FieldSpec("build", "Build"),
    FieldSpec("platforms", "Platforms", "multi", ("macOS", "Linux", "Windows")),
    FieldSpec("test_framework", "Test framework"),
    FieldSpec("library_policy", "Library policy"),
    FieldSpec("max_function_lines", "Max function lines", "int"),
    FieldSpec("hard_max_function_lines", "Hard max function lines", "int"),
    FieldSpec("max_data_members", "Max data members", "int"),
    FieldSpec("max_methods", "Max methods", "int"),
    FieldSpec("style_notes", "Style notes (one per line)", "lines", height=8),
)


class FieldSet:
    """Builds the widgets for some fields in a two-column grid and converts between them and a dict."""

    def __init__(self, parent: Any, fields: Sequence[FieldSpec]) -> None:
        self.fields = tuple(fields)
        self.vars: dict[str, Any] = {}  # a Tk variable, or option -> variable for ``multi``
        self.texts: dict[str, Any] = {}
        for row, spec in enumerate(self.fields):
            ttk.Label(parent, text=spec.label).grid(row=row, column=0, sticky="nw", padx=6, pady=3)
            self._build(parent, row, spec)
        parent.columnconfigure(1, weight=1)

    def _build(self, parent: Any, row: int, spec: FieldSpec) -> None:
        if spec.kind in ("text", "lines"):
            widget = tk.Text(parent, height=spec.height, width=ENTRY_WIDTH, wrap="word", undo=True)
            widget.grid(row=row, column=1, sticky="nsew", padx=6, pady=3)
            parent.rowconfigure(row, weight=1)
            self.texts[spec.key] = widget
        elif spec.kind == "flag":
            flag = tk.BooleanVar(value=False)
            ttk.Checkbutton(parent, variable=flag).grid(row=row, column=1, sticky="w", padx=6, pady=3)
            self.vars[spec.key] = flag
        elif spec.kind == "multi":
            frame = ttk.Frame(parent)
            frame.grid(row=row, column=1, sticky="w", padx=6, pady=3)
            choices: dict[str, Any] = {}
            for option in spec.options:
                choices[option] = tk.BooleanVar(value=False)
                ttk.Checkbutton(frame, text=option, variable=choices[option]).pack(side=tk.LEFT, padx=(0, 10))
            self.vars[spec.key] = choices
        else:
            var = tk.StringVar(value="")
            if spec.kind == "choice":
                ttk.Combobox(parent, textvariable=var, values=list(spec.options), state="readonly",
                             width=24).grid(row=row, column=1, sticky="w", padx=6, pady=3)
            else:
                ttk.Entry(parent, textvariable=var, width=ENTRY_WIDTH).grid(row=row, column=1, sticky="ew",
                                                                            padx=6, pady=3)
            self.vars[spec.key] = var

    def set(self, values: Mapping[str, Any]) -> None:
        for spec in self.fields:
            value = values.get(spec.key)
            if spec.kind in ("text", "lines"):
                text = "\n".join(value) if isinstance(value, list) else str(value or "")
                self.texts[spec.key].delete("1.0", tk.END)
                self.texts[spec.key].insert("1.0", text)
            elif spec.kind == "flag":
                self.vars[spec.key].set(bool(value))
            elif spec.kind == "multi":
                chosen = set(value or ())
                for option, flag in self.vars[spec.key].items():
                    flag.set(option in chosen)
            elif spec.kind == "tags":
                self.vars[spec.key].set(", ".join(value or ()))
            else:
                self.vars[spec.key].set("" if value is None else str(value))

    def get(self) -> dict[str, Any]:
        """The values as they belong in the specification; empty optional values are left out."""
        values: dict[str, Any] = {}
        for spec in self.fields:
            value = self._value(spec)
            if value not in ("", [], None):
                values[spec.key] = value
        return values

    def _value(self, spec: FieldSpec) -> Any:
        if spec.kind == "text":
            return self.texts[spec.key].get("1.0", tk.END).strip()
        if spec.kind == "lines":
            return _lines(self.texts[spec.key].get("1.0", tk.END))
        if spec.kind == "flag":
            return bool(self.vars[spec.key].get())
        if spec.kind == "multi":
            return [option for option, flag in self.vars[spec.key].items() if flag.get()]
        raw = str(self.vars[spec.key].get()).strip()
        if spec.kind == "tags":
            return [tag.strip() for tag in raw.replace(";", ",").split(",") if tag.strip()]
        if spec.kind == "int":
            return int(raw) if raw.isdigit() else raw  # anything else stays text so that validation names it
        return raw


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


class LinesPage:
    """A section that is a list of strings: one per line in a text box."""

    def __init__(self, parent: Any, hint: str) -> None:
        ttk.Label(parent, text=hint, anchor="w").pack(fill=tk.X, padx=6, pady=(6, 2))
        self.text = tk.Text(parent, wrap="word", undo=True)
        self.text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def load(self, lines: Sequence[str]) -> None:
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", "\n".join(lines))

    def values(self) -> list[str]:
        return _lines(self.text.get("1.0", tk.END))


class RecordListPage:
    """A section of numbered records: the list on the left, the fields of the selected record on the right."""

    def __init__(self, parent: Any, section: str, fields: Sequence[FieldSpec]) -> None:
        self.section = section
        self.records: list[dict[str, Any]] = []
        self.current: int | None = None
        self._selecting = False
        left = ttk.Frame(parent)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=6)
        self.tree = ttk.Treeview(left, columns=("title",), show="tree headings", height=18, selectmode="browse")
        self.tree.heading("#0", text="id")
        self.tree.heading("title", text="title")
        self.tree.column("#0", width=70, stretch=False)
        self.tree.column("title", width=240)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        buttons = ttk.Frame(left)
        buttons.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(buttons, text="Add", command=self.add).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Remove", command=self.remove).pack(side=tk.LEFT, padx=4)
        right = ttk.Frame(parent)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.id_var = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.id_var, font=("TkDefaultFont", 11, "bold"),
                  anchor="w").pack(fill=tk.X, padx=6, pady=(0, 6))
        form = ttk.Frame(right)
        form.pack(fill=tk.BOTH, expand=True)
        self.form = FieldSet(form, fields)
        self._show(None)

    def load(self, records: Sequence[Mapping[str, Any]]) -> None:
        self.records = [dict(r) for r in records]
        self.current = None
        self._refresh()
        if self.records:
            self.select(0)
        else:
            self._show(None)

    def values(self) -> list[dict[str, Any]]:
        self._commit()
        return [dict(r) for r in self.records]

    def add(self) -> dict[str, Any]:
        """Append a record with the next free id and select it."""
        self._commit()
        record = {"id": specification.next_id({self.section: self.records}, self.section),
                  **RECORD_DEFAULTS.get(self.section, {})}
        self.records.append(record)
        self._refresh()
        self.select(len(self.records) - 1)
        return record

    def remove(self) -> None:
        if self.current is None:
            return
        index = self.current
        del self.records[index]
        self.current = None
        self._refresh()
        if self.records:
            self.select(min(index, len(self.records) - 1))
        else:
            self._show(None)

    def select(self, index: int) -> None:
        self._commit()
        self.current = index
        self._show(self.records[index])
        self._selecting = True
        try:
            self.tree.selection_set(str(index))
            self.tree.see(str(index))
        finally:
            self._selecting = False

    def _on_select(self, _event: Any) -> None:
        if self._selecting:
            return
        chosen = self.tree.selection()
        if chosen and int(chosen[0]) != self.current:
            self.select(int(chosen[0]))

    def _commit(self) -> None:
        """Write the form back into the current record."""
        if self.current is None or self.current >= len(self.records):
            return
        record = {"id": self.records[self.current]["id"], **self.form.get()}
        self.records[self.current] = record
        self.tree.item(str(self.current), text=record["id"], values=(_headline(record),))

    def _show(self, record: Mapping[str, Any] | None) -> None:
        self.id_var.set(record["id"] if record else "no entry — press Add")
        self.form.set(record or {})

    def _refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, record in enumerate(self.records):
            self.tree.insert("", tk.END, iid=str(index), text=record.get("id", "?"), values=(_headline(record),))


def _headline(record: Mapping[str, Any]) -> str:
    return str(record.get("title") or record.get("requirement") or "")


class SpecificationEditor:
    """A window with one page per section, Validate/Save/Close, and the problems of the last validation."""

    def __init__(self, parent: Any, spec: Specification, on_save: Callable[[Specification], None],
                 title: str = "Specification") -> None:
        self.on_save = on_save
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        screen.fit_to_screen(self.window, 1120, 760)
        self._build_bar()  # packed first, at the bottom, so that the buttons stay visible on small screens
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.overview = FieldSet(self._page("Overview"), OVERVIEW_FIELDS)
        self.lines: dict[str, LinesPage] = {}
        self.records: dict[str, RecordListPage] = {}
        for section in SECTION_ORDER:
            page = self._page(SECTION_TITLES[section])
            if section in RECORD_SECTIONS:
                self.records[section] = RecordListPage(page, section, RECORD_FIELDS[section])
            else:
                self.lines[section] = LinesPage(page, LINES_HINTS[section])
        self.profile = FieldSet(self._page("Code Profile"), PROFILE_FIELDS)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.load(spec)

    def _build_bar(self) -> None:
        bar = ttk.Frame(self.window)
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=6, pady=(0, 6))
        self.problems = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.problems, foreground="#c00000", anchor="w",
                  wraplength=760).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(bar, text="Close", command=self.close).pack(side=tk.RIGHT)
        ttk.Button(bar, text="Save", command=self.save).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bar, text="Validate", command=self.validate).pack(side=tk.RIGHT)

    def _page(self, title: str) -> Any:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=title)
        return frame

    # -- state ----------------------------------------------------------------------------

    def load(self, spec: Specification) -> None:
        self.overview.set(spec)
        for section, lines in self.lines.items():
            lines.load(spec.get(section, []))
        for section, records in self.records.items():
            records.load(spec.get(section, []))
        self.profile.set(spec.get("code_profile", {}))
        self.loaded = self.to_specification()

    def to_specification(self) -> Specification:
        spec: Specification = {"schema_version": 1, "title": "", "summary": "", **self.overview.get()}
        for section in SECTION_ORDER:
            spec[section] = (self.records[section].values() if section in self.records
                             else self.lines[section].values())
        spec["code_profile"] = self.profile.get()
        return spec

    def changed(self) -> bool:
        return self.to_specification() != self.loaded

    # -- actions --------------------------------------------------------------------------

    def validate(self) -> list[str]:
        problems = specification.validate(self.to_specification())
        if problems:
            shown = "; ".join(problems[:3])
            self.problems.set(shown + (f" … ({len(problems)} problems)" if len(problems) > 3 else ""))
        else:
            self.problems.set("valid")
        return problems

    def save(self) -> bool:
        """Validate; when valid hand the specification to ``on_save`` and remember it as the saved state."""
        if self.validate():
            return False
        spec = self.to_specification()
        self.on_save(copy.deepcopy(spec))
        self.loaded = spec
        self.problems.set("saved")
        return True

    def close(self) -> None:
        if self.changed() and messagebox.askyesno("Specification", "Save the changes before closing?") \
                and not self.save():
            return
        self.window.destroy()
