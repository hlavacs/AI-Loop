"""A minimal stand-in for tkinter so the GUI code can be imported and driven without a display."""

from __future__ import annotations

import re
import sys
import types
from collections.abc import Iterator
from typing import Any


class _Widget:
    """Accepts any construction arguments and any method call; records nothing."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    def __getattr__(self, name: str) -> Any:
        if name == "bbox":
            return lambda *args, **kwargs: None
        if name in ("winfo_width", "winfo_height"):
            return lambda: 800
        if name in ("winfo_screenwidth", "winfo_screenheight"):
            return lambda: 1440 if name.endswith("width") else 900
        return _Widget

    def __call__(self, *args: Any, **kwargs: Any) -> _Widget:
        return _Widget(*args, **kwargs)

    def __iter__(self) -> Iterator[Any]:
        return iter(())

    def __len__(self) -> int:
        return 0


class _Var:
    """A variable whose write traces fire on ``set``, as Tk's do."""

    def __init__(self, value: Any = None, **kwargs: Any) -> None:
        self._value = value
        self._traces: list[Any] = []

    def get(self) -> Any:
        return self._value

    def set(self, value: Any) -> None:
        self._value = value
        for callback in list(self._traces):
            callback("", "", "write")

    def trace_add(self, mode: str, callback: Any) -> str:
        if mode == "write":
            self._traces.append(callback)
        return f"trace{len(self._traces)}"


class _Text(_Widget):
    """A small in-memory Text supporting source-editor character/line indices."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.content = ""
        self.marks = {"insert": 0}
        self.modified = False
        self.tags: dict[str, list[tuple[int, int]]] = {}
        self.tk = types.SimpleNamespace(call=lambda _string, _length, text: len(text))

    def _offset(self, index: str) -> int:
        index = str(index)
        if index == "end":
            return len(self.content) + 1
        if index == "end-1c":
            return len(self.content)
        if index in self.marks:
            return self.marks[index]
        match = re.fullmatch(r"1\.0 \+ (\d+) chars", index)
        if match:
            return int(match.group(1))
        line, column = index.split(".", 1)
        rows = self.content.splitlines(keepends=True)
        begin = sum(map(len, rows[:int(line) - 1]))
        if column.endswith(" lineend"):
            return begin + len(rows[int(line) - 1].rstrip("\n")) if int(line) <= len(rows) else len(self.content)
        return min(len(self.content), begin + int(column))

    def insert(self, index: str, text: str) -> None:
        position = min(self._offset(index), len(self.content))
        self.content = self.content[:position] + text + self.content[position:]
        self.marks["insert"] = position + len(text)
        self.modified = True

    def delete(self, start: str = "1.0", end: str = "end") -> None:
        begin, finish = self._offset(start), self._offset(end)
        self.content = self.content[:begin] + self.content[finish:]
        self.marks["insert"] = min(begin, len(self.content))
        self.modified = True

    def get(self, start: str = "1.0", end: str = "end") -> str:
        return (self.content + "\n")[self._offset(start):self._offset(end)]

    def mark_set(self, mark: str, index: str) -> None:
        self.marks[mark] = self._offset(index)

    def index(self, index: str) -> str:
        prefix = self.content[:self._offset(index)]
        return f"{prefix.count(chr(10)) + 1}.{len(prefix.rsplit(chr(10), 1)[-1])}"

    def edit_modified(self, value: bool | None = None) -> bool:
        if value is not None:
            self.modified = value
        return self.modified

    def tag_add(self, name: str, start: str, end: str) -> None:
        self.tags.setdefault(name, []).append((self._offset(start), self._offset(end)))

    def tag_remove(self, name: str, start: str, end: str) -> None:
        self.tags.pop(name, None)


class _Tk(_Widget):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.titles: list[str] = []

    def title(self, value: str | None = None) -> str | None:
        if value is not None:
            self.titles.append(value)
        return self.titles[-1] if self.titles else None

    def mainloop(self) -> None:
        return None


def _module(name: str, **attrs: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    module.__getattr__ = lambda attribute: attribute.upper() if attribute.isupper() else _Widget  # type: ignore[attr-defined]
    return module


def install() -> None:
    """Register the stub modules under the tkinter names in ``sys.modules``."""
    root = _module("tkinter", Tk=_Tk, Toplevel=_Tk, Text=_Text, StringVar=_Var, IntVar=_Var, BooleanVar=_Var,
                   DoubleVar=_Var, TclError=RuntimeError, BOTH="both", X="x", Y="y", LEFT="left", RIGHT="right",
                   TOP="top", BOTTOM="bottom", END="end", W="w", E="e", N="n", S="s", NW="nw", NE="ne", SW="sw",
                   SE="se", CENTER="center", HORIZONTAL="horizontal", VERTICAL="vertical", DISABLED="disabled",
                   NORMAL="normal")
    ttk = _module("tkinter.ttk")
    filedialog = _module("tkinter.filedialog", askdirectory=lambda **kwargs: "", askopenfilename=lambda **kwargs: "")
    messagebox = _module("tkinter.messagebox", showerror=lambda *a, **k: None, showinfo=lambda *a, **k: None,
                         askyesno=lambda *a, **k: False, askyesnocancel=lambda *a, **k: None)
    font = _module("tkinter.font")
    simpledialog = _module("tkinter.simpledialog", askstring=lambda *a, **k: None)
    for name, module in (("tkinter", root), ("tkinter.ttk", ttk), ("tkinter.filedialog", filedialog),
                         ("tkinter.messagebox", messagebox), ("tkinter.font", font),
                         ("tkinter.simpledialog", simpledialog)):
        sys.modules[name] = module
    root.ttk = ttk  # type: ignore[attr-defined]
    root.simpledialog = simpledialog  # type: ignore[attr-defined]
    root.filedialog = filedialog  # type: ignore[attr-defined]
    root.messagebox = messagebox  # type: ignore[attr-defined]
    root.font = font  # type: ignore[attr-defined]
