"""A minimal stand-in for tkinter so the GUI code can be imported and driven without a display."""

from __future__ import annotations

import sys
import types
from typing import Any


class _Widget:
    """Accepts any construction arguments and any method call; records nothing."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    def __getattr__(self, name: str) -> Any:
        return _Widget

    def __call__(self, *args: Any, **kwargs: Any) -> _Widget:
        return _Widget(*args, **kwargs)


class _Var:
    def __init__(self, value: Any = None, **kwargs: Any) -> None:
        self._value = value

    def get(self) -> Any:
        return self._value

    def set(self, value: Any) -> None:
        self._value = value


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
    root = _module("tkinter", Tk=_Tk, StringVar=_Var, IntVar=_Var, BooleanVar=_Var, DoubleVar=_Var,
                   TclError=RuntimeError, BOTH="both", X="x", Y="y", LEFT="left", RIGHT="right", TOP="top",
                   BOTTOM="bottom", END="end", W="w", E="e", N="n", S="s", NW="nw", NE="ne", SW="sw", SE="se",
                   CENTER="center", HORIZONTAL="horizontal", VERTICAL="vertical", DISABLED="disabled",
                   NORMAL="normal")
    ttk = _module("tkinter.ttk")
    filedialog = _module("tkinter.filedialog", askdirectory=lambda **kwargs: "", askopenfilename=lambda **kwargs: "")
    messagebox = _module("tkinter.messagebox", showerror=lambda *a, **k: None, showinfo=lambda *a, **k: None,
                         askyesno=lambda *a, **k: False)
    font = _module("tkinter.font")
    for name, module in (("tkinter", root), ("tkinter.ttk", ttk), ("tkinter.filedialog", filedialog),
                         ("tkinter.messagebox", messagebox), ("tkinter.font", font)):
        sys.modules[name] = module
    root.ttk = ttk  # type: ignore[attr-defined]
    root.filedialog = filedialog  # type: ignore[attr-defined]
    root.messagebox = messagebox  # type: ignore[attr-defined]
    root.font = font  # type: ignore[attr-defined]
