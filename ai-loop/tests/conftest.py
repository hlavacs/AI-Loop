"""Shared test setup.

1. Puts the repo root on sys.path so `import ai_loop`, `import resume_job`,
   `import ai_loop_gui`, ... work no matter which cwd pytest runs from.
2. When tkinter is unavailable AND AILOOP_TK_STUB=1 is set, installs a
   minimal tkinter stub into sys.modules so `import ai_loop_gui` succeeds
   and its pure-logic tests (e.g. ExclusiveConflictTests) can run on
   headless machines without the Tk libraries (such as CI containers).

The stub is deliberately dumb: module-level __getattr__ hands back a single
catch-all class (_TkStubDummy) for every attribute (tk.Tk, ttk.Frame,
messagebox.showinfo, ...). The class is subclassable (so
`class AiLoopGui(tk.Tk)` works at import time), instantiable with any
arguments, callable, and returns more dummies for any attribute access.
Only tkinter.TclError is a real Exception subclass because ai_loop_gui uses
it in `except` clauses.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _TkStubDummy:
    """Stands in for any tkinter class, function, or constant."""

    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return _TkStubDummy()

    def __getattr__(self, name):
        return _TkStubDummy()


def _install_tk_stub() -> None:
    tk_stub = types.ModuleType("tkinter")
    tk_stub.TclError = type("TclError", (Exception,), {})
    # PEP 562 module __getattr__: every other attribute is the dummy class.
    tk_stub.__getattr__ = lambda name: _TkStubDummy  # type: ignore[method-assign]
    for sub_name in ("ttk", "messagebox", "filedialog", "scrolledtext", "font"):
        sub = types.ModuleType(f"tkinter.{sub_name}")
        sub.__getattr__ = lambda name: _TkStubDummy  # type: ignore[method-assign]
        sys.modules[f"tkinter.{sub_name}"] = sub
        setattr(tk_stub, sub_name, sub)
    sys.modules["tkinter"] = tk_stub


if os.environ.get("AILOOP_TK_STUB") == "1":
    try:
        import tkinter  # noqa: F401  (real tkinter present: no stub needed)
    except Exception:
        _install_tk_stub()
