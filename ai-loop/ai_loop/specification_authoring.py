"""ICODA's six-tab authoring controls, kept independent of the ICODA installation.

Field definitions and entry gestures mirror icoda_gui.spec_editor. Parity tests
compare both definitions and record actions. AI-Loop retains hidden execution
metadata when a record is edited.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

try:
    import tkinter as tk
    from tkinter import ttk
except (ImportError, RuntimeError):  # Importable without Tk, like the main editor.
    tk = None
    ttk = None


def attach_hint(widget: Any, text: str) -> None:
    from ai_loop.gui_components import HoverTooltip
    tip = HoverTooltip(widget, delay_ms=500, wraplength=420)
    tip.attach(widget, text)
    widget._specification_hint = text


def next_record_id(records: Sequence[Mapping[str, Any]], section: str) -> str:
    prefix = {"use_cases": "UC", "requirements": "R", "decisions": "D"}[section]
    numbers = [int(match.group(1)) for record in records
               if (match := re.fullmatch(rf"{prefix}-(\d+)", str(record.get("id", ""))))]
    return f"{prefix}-{max(numbers, default=0) + 1}"


ENTRY_WIDTH = 64
SECTION_TITLES = {"use_cases": "Use cases", "requirements": "Requirements", "decisions": "Decisions"}


@dataclass(frozen=True)
class FieldSpec:
    """One editable value on a page.

    ``kind`` is ``entry`` (one line), ``text`` (many lines), ``lines`` (a list, one per line), ``tags`` (a list,
    comma separated), ``choice`` (one of ``options``), ``multi`` (any of ``options``), ``flag`` or ``int``.
    ``hint`` is the tooltip: what to enter, with an example.
    """

    key: str
    label: str
    kind: str = "entry"
    options: Sequence[str] = ()
    height: int = 4
    hint: str = ""


OVERVIEW_FIELDS = (
    FieldSpec("title", "Title", hint="A short name for the project.\nExample: Asteroid Miner"),
    FieldSpec("summary", "Description", "text", height=6,
              hint="What the program is and who uses it, in a few sentences.\nExample: A 2D game in which the "
                   "player steers a ship through an asteroid field and mines ore for points."),
)
SCOPE_FIELDS = (
    FieldSpec("goals", "Goals", "lines", height=5,
              hint="One goal per line: what the project must achieve.\nExample: Runs at 60 frames per second on "
                   "a laptop"),
    FieldSpec("out_of_scope", "Not in scope", "lines", height=4,
              hint="One item per line: what the project deliberately leaves out, so the agent does not add "
                   "it.\nExample: Multiplayer"),
    FieldSpec("not_allowed", "Not allowed", "lines", height=4,
              hint="One item per line: libraries, techniques or features the code must not use.\n"
                   "Example: Boost\nExample: exceptions for control flow\nExample: global variables"),
    FieldSpec("done_when", "Done when", "lines", height=4,
              hint="One condition per line that marks the project as finished.\nExample: Every use case runs "
                   "without a crash\nExample: Every implemented function has a passing unit test"),
)
RECORD_FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    "use_cases": (
        FieldSpec("title", "Use case", hint="One thing a user does with the program, as a short sentence.\n"
                                            "Example: The player starts a new game"),
        FieldSpec("description", "Details", "text", height=8,
                  hint="Optional: the steps, the result, special cases.\nExample: The player picks a difficulty; "
                       "the field is generated; the ship appears in the centre."),
    ),
    "requirements": (
        FieldSpec("title", "Requirement", hint="One testable statement about what the program must do or be.\n"
                                               "Example: The game saves its state when it is closed"),
        FieldSpec("priority", "Priority", "choice", ("must", "should", "could"),
                  hint="must: without it the project fails\nshould: important\ncould: nice to have"),
        FieldSpec("use_cases", "Use cases", "tags",
                  hint="Optional: the use cases this requirement serves, by id, comma separated.\n"
                       "Example: UC-1, UC-3"),
        FieldSpec("description", "Details", "text", height=8,
                  hint="Optional: numbers, limits, formats.\nExample: Saving takes at most 100 ms"),
    ),
    "decisions": (
        FieldSpec("title", "Decision", hint="A choice already made, so that the agent does not reopen it.\n"
                                            "Example: Use SDL3 for graphics and input"),
        FieldSpec("rationale", "Why", "text", height=8,
                  hint="Optional: the reason.\nExample: Cross-platform, well documented, available in vcpkg"),
    ),
}
RECORD_DEFAULTS: dict[str, dict[str, Any]] = {"requirements": {"priority": "must"}}
PROFILE_FIELDS = (
    FieldSpec("language", "Language", "choice", ("C++", "Python"), hint="The project's source language."),
    FieldSpec("standard", "Standard", hint="The language standard the code is written in.\nExample: 23"),
    FieldSpec("modules", "C++20 modules", "flag", hint="Generate C++20 modules instead of header files."),
    FieldSpec("platforms", "Platforms", "multi", ("macOS", "Linux", "Windows"),
              hint="Where the program must build and run."),
    FieldSpec("test_framework", "Test framework", hint="The unit test framework the agent writes tests for.\n"
                                                       "Example: doctest"),
    FieldSpec("test_runner", "Test runner", hint="The command used to run tests.\nExample: python -m pytest"),
    FieldSpec("test_file_convention", "Test files", hint="Where test files live and how they are named.\n"
                                                             "Example: tests/test_<module>.py"),
    FieldSpec("source_file_extension", "Source extension", hint="The extension for source files.\nExample: .py"),
    FieldSpec("module_naming", "Module naming", hint="The naming style for modules.\nExample: snake_case"),
    FieldSpec("class_naming", "Class naming", hint="The naming style for classes.\nExample: PascalCase"),
    FieldSpec("function_naming", "Function naming", hint="The naming style for functions.\nExample: snake_case"),
    FieldSpec("library_policy", "Libraries", hint="How third-party libraries are added.\nExample: vcpkg "
                                                  "manifest; single-header libraries vendored under third_party/"),
    FieldSpec("max_function_lines", "Max function lines", "int",
              hint="Functions longer than this are split into smaller ones.\nExample: 30"),
    FieldSpec("hard_max_function_lines", "Hard max function lines", "int",
              hint="A function longer than this is refused outright, not only reported.\nExample: 60"),
    FieldSpec("max_methods", "Max methods per class", "int",
              hint="A class with more methods than this is flagged as too large.\nExample: 15"),
    FieldSpec("max_data_members", "Max data members", "int",
              hint="A class with more data members than this is flagged as too large.\nExample: 8"),
    FieldSpec("style_notes", "Style rules", "lines", height=6,
              hint="One rule per line that the agent must follow.\nExample: Prefer STL algorithms to loops"),
)
HIDDEN_PROFILE_KEYS = ("build",)
SAVE_HINT = "Check the specification and write it to the project (Ctrl+S, ⌘S on macOS)."


class FieldSet:
    """Builds the widgets for some fields in a two-column grid and converts between them and a dict."""

    def __init__(self, parent: Any, fields: Sequence[FieldSpec]) -> None:
        self.fields = tuple(fields)
        self.vars: dict[str, Any] = {}  # a Tk variable, or option -> variable for ``multi``
        self.texts: dict[str, Any] = {}
        self.widgets: dict[str, Any] = {}
        self.labels: dict[str, Any] = {}
        for row, spec in enumerate(self.fields):
            label = ttk.Label(parent, text=spec.label)
            self.labels[spec.key] = label
            label.grid(row=row, column=0, sticky="nw", padx=6, pady=3)
            self._build(parent, row, spec)
            if spec.hint:
                attach_hint(label, spec.hint)
                attach_hint(self.widgets[spec.key], spec.hint)
        parent.columnconfigure(1, weight=1)

    def _build(self, parent: Any, row: int, spec: FieldSpec) -> None:
        widget: Any
        if spec.kind in ("text", "lines"):
            widget = tk.Text(parent, height=spec.height, width=ENTRY_WIDTH, wrap="word", undo=True)
            widget.grid(row=row, column=1, sticky="nsew", padx=6, pady=3)
            parent.rowconfigure(row, weight=1)
            self.texts[spec.key] = widget
        elif spec.kind == "flag":
            flag = tk.BooleanVar(value=False)
            widget = ttk.Checkbutton(parent, variable=flag)
            widget.grid(row=row, column=1, sticky="w", padx=6, pady=3)
            self.vars[spec.key] = flag
        elif spec.kind == "multi":
            widget = ttk.Frame(parent)
            widget.grid(row=row, column=1, sticky="w", padx=6, pady=3)
            choices: dict[str, Any] = {}
            for option in spec.options:
                choices[option] = tk.BooleanVar(value=False)
                ttk.Checkbutton(widget, text=option, variable=choices[option]).pack(side=tk.LEFT, padx=(0, 10))
            self.vars[spec.key] = choices
        else:
            var = tk.StringVar(value="")
            if spec.kind == "choice":
                widget = ttk.Combobox(parent, textvariable=var, values=list(spec.options), state="readonly", width=24)
                widget.grid(row=row, column=1, sticky="w", padx=6, pady=3)
            else:
                widget = ttk.Entry(parent, textvariable=var, width=ENTRY_WIDTH)
                widget.grid(row=row, column=1, sticky="ew", padx=6, pady=3)
            self.vars[spec.key] = var
        self.widgets[spec.key] = widget

    def focus_first(self) -> None:
        """Put the keyboard focus into the first field (the title, for records)."""
        if self.fields:
            self.widgets[self.fields[0].key].focus_set()

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


class RecordListPage:
    """A section of numbered records: the list on the left, a form on the right.

    With nothing selected the form is a *new entry*: fill it in and press Add (or Return in the title). Clicking a
    row selects the record; its edits are kept when another row is selected, on Add, New or Save.
    """

    def __init__(self, parent: Any, section: str, fields: Sequence[FieldSpec],
                 on_change: Callable[[], None] | None = None) -> None:
        self.section = section
        self.on_change = on_change or (lambda: None)
        self.fields = tuple(fields)
        self.records: list[dict[str, Any]] = []
        self.current: int | None = None
        self._selecting = False
        left = ttk.Frame(parent)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=6)
        self.tree = ttk.Treeview(left, columns=("title",), show="tree headings", height=16, selectmode="browse")
        self.tree.heading("#0", text="id")
        self.tree.heading("title", text=self.fields[0].label)
        self.tree.column("#0", width=60, stretch=False)
        self.tree.column("title", width=260)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        attach_hint(self.tree, "Click a row to edit it. Press New for a new entry, Remove to delete the row.")
        self.buttons: dict[str, Any] = {}
        buttons = ttk.Frame(left)
        buttons.pack(fill=tk.X, pady=(4, 0))
        for text, command, hint in (("Add", self.add, "Add what is in the form as a new entry (or press Return)."),
                                    ("New", self.new, "Clear the form for a new entry."),
                                    ("Remove", self.remove, "Delete the selected row.")):
            button = ttk.Button(buttons, text=text, command=command)
            self.buttons[text] = button
            button.pack(side=tk.LEFT, padx=(0, 4))
            attach_hint(button, hint)
        right = ttk.Frame(parent)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.header = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.header, font=("TkDefaultFont", 11, "bold"),
                  anchor="w").pack(fill=tk.X, padx=6, pady=(0, 6))
        form = ttk.Frame(right)
        form.pack(fill=tk.BOTH, expand=True)
        self.form = FieldSet(form, self.fields)
        self.form.widgets[self.fields[0].key].bind("<Return>", lambda _event: self.add())
        self._show(None)

    # -- state ----------------------------------------------------------------------------

    def load(self, records: Sequence[Mapping[str, Any]]) -> None:
        self.records = [dict(r) for r in records]
        self.current = None
        self._refresh()
        self._show(None)

    def values(self) -> list[dict[str, Any]]:
        self._commit()
        return [dict(r) for r in self.records]

    # -- actions --------------------------------------------------------------------------

    def add(self) -> dict[str, Any] | None:
        """Append the form as a new record; with a record selected, keep its edits and start a new entry."""
        if self.current is not None:
            self.new()
            return None
        values = self.form.get()
        headline = str(values.get(self.fields[0].key, "")).strip()
        if not headline:
            self.header.set(f"New entry: fill in the {self.fields[0].label.lower()} first, then press Add")
            self.form.focus_first()
            return None
        record = {"id": next_record_id(self.records, self.section),
                  **RECORD_DEFAULTS.get(self.section, {}), **values}
        self.records.append(record)
        self._refresh()
        self._show(None)
        self.header.set(f"{record['id']} added — next entry")
        self.form.focus_first()
        self.on_change()
        return record

    def new(self) -> None:
        """Keep the selected record's edits and switch the form to a new entry."""
        self._commit()
        self.current = None
        self._selecting = True
        try:
            self.tree.selection_remove(*self.tree.get_children())
        finally:
            self._selecting = False
        self._show(None)
        self.form.focus_first()
        self.on_change()

    def remove(self) -> None:
        if self.current is None:
            self.header.set("Select a row on the left to remove it")
            return
        del self.records[self.current]
        self.current = None
        self._refresh()
        self._show(None)
        self.on_change()

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

    # -- internals ------------------------------------------------------------------------

    def _commit(self) -> None:
        """Write the form back into the selected record."""
        if self.current is None or self.current >= len(self.records):
            return
        values = self.form.get()
        if values == self._shown_values:
            return
        # Keep AI-Loop's historical and verification metadata outside this form.
        record = {key: value for key, value in self.records[self.current].items()
                  if key not in {field.key for field in self.fields}}
        record.update(values)
        self.records[self.current] = record
        self._shown_values = copy.deepcopy(values)
        self.tree.item(str(self.current), text=record["id"], values=(_headline(record),))

    def _show(self, record: Mapping[str, Any] | None) -> None:
        if record is None:
            self.header.set("New entry — fill in the form, then press Add")
            self.form.set(RECORD_DEFAULTS.get(self.section, {}))
            self.empty_form = self.form.get()
        else:
            self.header.set(f"{record['id']} — editing (New starts a new entry)")
            self.form.set(record)
        self._shown_values = copy.deepcopy(self.form.get())

    def pending_entry(self) -> bool:
        return self.current is None and self.form.get() != self.empty_form

    def _refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, record in enumerate(self.records):
            self.tree.insert("", tk.END, iid=str(index), text=record.get("id", "?"), values=(_headline(record),))


def _headline(record: Mapping[str, Any]) -> str:
    return str(record.get("title") or "")
