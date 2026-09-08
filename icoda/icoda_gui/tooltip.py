"""A small floating label near the pointer: shown on demand (canvas hover) or attached to a widget."""

from __future__ import annotations

import tkinter as tk
from typing import Any

DELAY_MS = 500
WRAP = 420


class Tooltip:
    """``show``/``hide`` for callers that track the pointer themselves; ``attach`` for ordinary widgets."""

    def __init__(self, widget: Any) -> None:
        self.widget = widget
        self.window: Any = None
        self.pending: Any = None

    def show(self, text: str, x: int, y: int) -> None:
        self.hide()
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{x + 14}+{y + 12}")
        tk.Label(self.window, text=text, justify="left", background="#ffffe0", relief="solid", borderwidth=1,
                 padx=6, pady=3, wraplength=WRAP).pack()

    def hide(self) -> None:
        if self.pending is not None:
            try:
                self.widget.after_cancel(self.pending)
            except (RuntimeError, ValueError, TypeError):
                pass
            self.pending = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


def attach(widget: Any, text: str) -> Tooltip:
    """Show ``text`` when the pointer rests on ``widget`` for half a second."""
    tip = Tooltip(widget)

    def schedule(event: Any) -> None:
        tip.hide()
        tip.pending = widget.after(DELAY_MS, lambda: tip.show(text, event.x_root, event.y_root))

    widget.bind("<Enter>", schedule, add="+")
    widget.bind("<Leave>", lambda _event: tip.hide(), add="+")
    widget.bind("<ButtonPress>", lambda _event: tip.hide(), add="+")
    return tip
