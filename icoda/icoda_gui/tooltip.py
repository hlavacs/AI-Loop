"""A small floating label near the pointer: shown on demand (canvas hover) or attached to a widget."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import Any

DELAY_MS = 500
WRAP = 420


class Tooltip:
    """``show``/``hide`` for callers that track the pointer themselves; ``attach`` for ordinary widgets."""

    def __init__(self, widget: Any) -> None:
        self.widget = widget
        self.window: Any = None
        self.pending: Any = None
        self.pointer = (0, 0)
        self.message = ""

    def follow(self, text: str, x: int, y: int) -> None:
        """Show changing object details after a short hover, without recreating the popup on every motion."""
        self.pointer = (x, y)
        if not text:
            self.hide()
        elif text != self.message:
            self.hide()
            self.message = text
            self.pending = self.widget.after(DELAY_MS, lambda: self.show(text, *self.pointer))
        elif self.window is not None:
            self.window.wm_geometry(f"+{x + 14}+{y + 12}")

    def show(self, text: str, x: int, y: int) -> None:
        self.hide()
        self.message = text
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.wm_geometry(f"+{x + 14}+{y + 12}")
        tk.Label(self.window, text=text, justify="left", background="#ffffe0", relief="solid", borderwidth=1,
                 padx=6, pady=3, wraplength=WRAP).pack()

    def hide(self) -> None:
        self.message = ""
        if self.pending is not None:
            try:
                self.widget.after_cancel(self.pending)
            except (RuntimeError, ValueError, TypeError):
                pass
            self.pending = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


def attach_objects(widget: Any, identify: Callable[[int, int], str | None],
                   describe: Callable[[str], str]) -> Tooltip:
    """Attach object details to a canvas or tree while preserving its existing mouse handlers."""
    tip = Tooltip(widget)

    def motion(event: Any) -> None:
        node = identify(event.x, event.y)
        tip.follow(describe(node) if node else "", event.x_root, event.y_root)

    widget.bind("<Motion>", motion, add="+")
    for event in ("<Leave>", "<Unmap>", "<ButtonPress-1>", "<ButtonPress-2>", "<ButtonPress-3>",
                  "<MouseWheel>", "<Button-4>", "<Button-5>"):
        widget.bind(event, lambda _event: tip.hide(), add="+")
    return tip


def attach(widget: Any, text: str | Callable[[], str]) -> Tooltip:
    """Show ``text`` (or what the callable returns at that moment) when the pointer rests on ``widget``."""
    tip = Tooltip(widget)

    def show() -> None:
        message = text() if callable(text) else text
        if message:
            tip.show(message, tip.pointer[0], tip.pointer[1])

    def schedule(event: Any) -> None:
        tip.hide()
        tip.pointer = (event.x_root, event.y_root)
        tip.pending = widget.after(DELAY_MS, show)

    widget.bind("<Enter>", schedule, add="+")
    widget.bind("<Leave>", lambda _event: tip.hide(), add="+")
    widget.bind("<ButtonPress>", lambda _event: tip.hide(), add="+")
    return tip
