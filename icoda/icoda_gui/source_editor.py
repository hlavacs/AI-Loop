"""A source editor pane with conservative saves, navigation, undo, and literal find/replace."""
from __future__ import annotations

import sys
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from icoda_core import source_edit


class SourceEditor:
    def __init__(self, parent: Any, *, project: Callable[[], Path | None], busy: Callable[[], bool],
                 saved: Callable[[source_edit.Document], None], failed: Callable[..., None]) -> None:
        self.project, self.busy, self.saved, self.failed = project, busy, saved, failed
        self.frame = ttk.Frame(parent)
        self.document: source_edit.Document | None = None
        self.loading = False
        self.path_var = tk.StringVar(value="Select a file, class, or function to edit its source.")
        self.info = tk.StringVar(value="")
        self.query, self.replacement = tk.StringVar(value=""), tk.StringVar(value="")
        self.match_case = tk.BooleanVar(value=False)
        self._match: tuple[int, int] | None = None
        self.buttons: dict[str, Any] = {}
        ttk.Label(self.frame, textvariable=self.path_var, anchor="w", width=1).pack(fill=tk.X, padx=5, pady=3)
        row = ttk.Frame(self.frame)
        row.pack(fill=tk.X, padx=4)
        for name, callback in (("Open…", self.choose_file), ("Save", self.save), ("Reload", self.reload),
                               ("Undo", lambda: self.undo(False)), ("Redo", lambda: self.undo(True))):
            button = ttk.Button(row, text=name, command=callback, width=6)
            button.pack(side=tk.LEFT, padx=(0, 3))
            self.buttons[name] = button
        search = ttk.Frame(self.frame)
        search.pack(fill=tk.X, padx=5, pady=(4, 0))
        ttk.Label(search, text="Find").grid(row=0, column=0, sticky="w")
        self.find_entry = ttk.Entry(search, textvariable=self.query, width=12)
        self.find_entry.grid(row=0, column=1, sticky="ew", padx=3)
        self.find_entry.bind("<Return>", lambda _event: self.find())
        self.find_entry.bind("<Shift-Return>", lambda _event: self.find(backwards=True))
        for column, name, callback in ((2, "Previous", lambda: self.find(backwards=True)),
                                       (3, "Next", self.find)):
            self.buttons[name] = ttk.Button(search, text=name, command=callback, width=7)
            self.buttons[name].grid(row=0, column=column)
        ttk.Label(search, text="Replace").grid(row=1, column=0, sticky="w")
        self.replace_entry = ttk.Entry(search, textvariable=self.replacement, width=12)
        self.replace_entry.grid(row=1, column=1, sticky="ew", padx=3)
        for column, name, callback in ((2, "Replace", self.replace_one), (3, "All", self.replace_all)):
            self.buttons[name] = ttk.Button(search, text=name, command=callback, width=7)
            self.buttons[name].grid(row=1, column=column)
        ttk.Checkbutton(search, text="Match case", variable=self.match_case).grid(row=2, column=1, sticky="w")
        search.columnconfigure(1, weight=1)
        ttk.Label(self.frame, textvariable=self.info, anchor="w").pack(side=tk.BOTTOM, fill=tk.X, padx=5)
        body = ttk.Frame(self.frame)
        body.pack(fill=tk.BOTH, expand=True, padx=4, pady=3)
        self.text = tk.Text(body, width=40, height=10, wrap="none", undo=True, autoseparators=True,
                            maxundo=200, font="TkFixedFont", exportselection=False, state="disabled")
        vertical = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.text.yview)
        horizontal = ttk.Scrollbar(body, orient=tk.HORIZONTAL, command=self.text.xview)
        self.text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        horizontal.pack(side=tk.BOTTOM, fill=tk.X)
        vertical.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.tag_configure("location", background="#fff2bd")
        self.text.tag_configure("match", background="#b8ddff")
        self.text.bind("<<Modified>>", self._modified)
        self.text.bind("<KeyRelease>", self._position)
        self.text.bind("<ButtonRelease-1>", self._position)
        modifier = "Command" if sys.platform == "darwin" else "Control"
        replace_key = "Alt-f" if sys.platform == "darwin" else "h"
        for key, action in (("s", self.save), ("f", self.focus_find), (replace_key, self.focus_replace),
                            ("z", lambda: self.undo(False)), ("Shift-z", lambda: self.undo(True))):
            self.text.bind(f"<{modifier}-{key}>", self._shortcut(action))
        for entry in (self.find_entry, self.replace_entry):
            entry.bind(f"<{modifier}-s>", self._shortcut(self.save))
        self.text.bind("<Control-y>", self._shortcut(lambda: self.undo(True)))
        self.text.bind("<Tab>", self._indent)
        self._state()

    @staticmethod
    def _shortcut(action: Callable[..., Any]) -> Callable[..., str]:
        def invoke(_event: Any) -> str:
            action()
            return "break"
        return invoke

    def content(self) -> str:
        return str(self.text.get("1.0", "end-1c"))

    @property
    def dirty(self) -> bool:
        return self.document is not None and self.content() != self.document.text

    def _state(self) -> None:
        doc = self.document
        self.path_var.set((f"{doc.root.name}: {doc.relative}" + (" • unsaved" if self.dirty else ""))
                          if doc else "Select a file, class, or function to edit its source.")
        for name, button in self.buttons.items():
            enabled = name == "Open…" or doc is not None
            button.state(["!disabled"] if enabled else ["disabled"])

    def _modified(self, _event: Any = None) -> None:
        if self.loading or not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        self._match = None
        self.text.tag_remove("match", "1.0", "end")
        self._state()

    def _position(self, _event: Any = None) -> None:
        if self.document is not None:
            line, column = self.text.index("insert").split(".")
            self.info.set(f"Line {line}, column {int(column) + 1}" + ("  • unsaved" if self.dirty else ""))

    def _indent(self, _event: Any = None) -> str:
        if self.document is not None:
            self.text.insert("insert", "    ")
        return "break"

    def confirm_saved(self) -> bool:
        if not self.dirty:
            return True
        assert self.document is not None
        choice = messagebox.askyesnocancel("Unsaved source edits", f"Save changes to {self.document.relative}?",
                                          parent=self.frame)
        if choice is None:
            return False
        if choice:
            return self.save()
        self._install(self.document)  # discard the buffer, keeping the known disk baseline
        return True

    def clear(self) -> bool:
        if not self.confirm_saved():
            return False
        self.document = None
        self.loading = True
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self.loading = False
        self.info.set("")
        self._state()
        return True

    def choose_file(self) -> None:
        root = self.document.root if self.document else self.project()
        if root is None:
            return
        path = filedialog.askopenfilename(parent=self.frame, initialdir=str(root), title="Open source file")
        if path:
            self.open_file(root, path)

    def open_file(self, root: Path, file: str, line: int = 1) -> bool:
        try:
            file = source_edit.relative_path(root, file)
        except ValueError:
            pass  # the normal open/recovery path reports invalid locations below
        if self.document is not None and self.document.root == root.resolve() \
                and file == self.document.relative:
            self.goto(line)
            return True
        if not self.confirm_saved():
            return False
        try:
            document = source_edit.Document.load(root, file)
        except (OSError, ValueError) as exc:
            return self._failure(exc, lambda: source_edit.Document.load(root, file),
                                 lambda doc: self._install(doc, line), lambda: self.open_file(root, file, line), root)
        self._install(document, line)
        return True

    def _install(self, document: source_edit.Document, line: int = 1) -> None:
        self.loading = True
        self.document = document
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", document.text)
        self.text.edit_reset()
        self.text.edit_modified(False)
        self.loading = False
        self._match = None
        self.goto(line)
        self._state()

    def goto(self, line: int) -> None:
        line = max(1, min(int(line), self.content().count("\n") + 1))
        self.text.mark_set("insert", f"{line}.0")
        self.text.tag_remove("location", "1.0", "end")
        self.text.tag_add("location", f"{line}.0", f"{line}.0 lineend")
        self.text.see(f"{line}.0")
        self.info.set(f"Line {line}")

    def _failure(self, error: Exception, repair: Callable[..., Any], repaired: Callable[..., Any],
                 retry: Callable[..., Any], root: Path) -> bool:
        # File operations are bounded to 2 MiB. Retry once without replacing the editor buffer on failure.
        try:
            result = repair()
        except (OSError, ValueError) as second:
            self.info.set(str(second))
            self.failed(second, attempted=True, retry=retry, cwd=root)
            return False
        repaired(result)
        return True

    def save(self) -> bool:
        if self.document is None or not self.dirty:
            return True
        if self.busy():
            self.info.set("Wait for the running operation before saving. Your edits are kept here.")
            return False
        document, text = self.document, self.content()
        try:
            document.save(text)
        except (OSError, ValueError) as exc:
            return self._failure(exc, lambda: document.save(text), lambda _result: self._saved(document),
                                 self.save, document.root)
        self._saved(document)
        return True

    def _saved(self, document: source_edit.Document) -> None:
        self._state()
        self.info.set("Saved")
        self.saved(document)

    def reload(self) -> None:
        if self.document is None or not self.confirm_saved():
            return
        root, file = self.document.root, self.document.relative
        try:
            document = source_edit.Document.load(root, file)
        except (OSError, ValueError) as exc:
            self._failure(exc, lambda: source_edit.Document.load(root, file), self._install, self.reload, root)
            return
        self._install(document)

    def undo(self, redo: bool = False) -> None:
        try:
            if redo:
                self.text.edit_redo()
            else:
                self.text.edit_undo()
        except tk.TclError:  # empty undo/redo stacks are normal
            pass
        self._state()

    def focus_find(self) -> None:
        self.find_entry.focus_set()
        self.find_entry.selection_range(0, "end")

    def focus_replace(self) -> None:
        self.replace_entry.focus_set()

    def _index(self, offset: int) -> str:
        # Tcl 8 and Tcl 9 count astral Unicode characters differently; use this interpreter's count.
        count = self.text.tk.call("string", "length", self.content()[:offset])
        return f"1.0 + {count} chars"

    def find(self, backwards: bool = False) -> None:
        if self.document is None:
            return
        ranges = source_edit.matches(self.content(), self.query.get(), bool(self.match_case.get()))
        self.text.tag_remove("match", "1.0", "end")
        if not ranges:
            self._match = None
            self.info.set("No matches" if self.query.get() else "Enter text to find")
            return
        current = len(self.text.get("1.0", "insert"))
        if self._match is not None:
            current = self._match[0] if backwards else self._match[1]
        chosen = next((pair for pair in reversed(ranges) if pair[0] < current), ranges[-1]) if backwards else (
            next((pair for pair in ranges if pair[0] >= current), ranges[0]))
        self._match = chosen
        start, end = (self._index(offset) for offset in chosen)
        self.text.tag_add("match", start, end)
        self.text.mark_set("insert", start)
        self.text.see(start)
        self.info.set(f"Match {ranges.index(chosen) + 1} of {len(ranges)}")

    def replace_one(self) -> None:
        if self.document is None:
            return
        ranges = source_edit.matches(self.content(), self.query.get(), bool(self.match_case.get()))
        if self._match not in ranges:
            self.find()
            return
        start, end = self._match
        self.text.edit_separator()
        begin, finish = self._index(start), self._index(end)
        self.text.configure(autoseparators=False)
        try:
            self.text.delete(begin, finish)
            self.text.insert(begin, self.replacement.get())
        finally:
            self.text.configure(autoseparators=True)
        self.text.edit_separator()
        self.text.mark_set("insert", self._index(start + len(self.replacement.get())))
        self._match = None
        self._state()
        self.info.set("Replaced 1 match")

    def replace_all(self) -> None:
        if self.document is None:
            return
        ranges = source_edit.matches(self.content(), self.query.get(), bool(self.match_case.get()))
        self.text.edit_separator()
        self.text.configure(autoseparators=False)
        try:
            for start, end in reversed(ranges):
                self.text.delete(self._index(start), self._index(end))
                self.text.insert(self._index(start), self.replacement.get())
        finally:
            self.text.configure(autoseparators=True)
        self.text.edit_separator()
        self._match = None
        self._state()
        self.info.set(f"Replaced {len(ranges)} matches")
