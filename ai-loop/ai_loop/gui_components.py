"""Reusable Tk widgets and GUI value objects."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass


class HoverTooltip:
    def __init__(
        self, root: tk.Tk, *, delay_ms: int = 200, wraplength: int = 460
    ) -> None:
        self.root = root
        self.delay_ms = delay_ms
        self.wraplength = wraplength
        self.window: tk.Toplevel | None = None
        self.after_id: str | None = None

    def attach(self, widget: tk.Widget, text: str) -> None:
        if not text:
            return
        setattr(widget, "_ai_loop_help_attached", True)
        widget.bind(
            "<Enter>",
            lambda _event, w=widget, t=text: self._schedule_show(w, t),
            add="+",
        )
        widget.bind("<Leave>", lambda _event: self.hide(), add="+")
        widget.bind("<ButtonPress>", lambda _event: self.hide(), add="+")

    def _schedule_show(self, widget: tk.Widget, text: str) -> None:
        self.hide()
        self.after_id = self.root.after(self.delay_ms, lambda: self._show(widget, text))

    def _show(self, widget: tk.Widget, text: str) -> None:
        self.after_id = None
        if not text or not widget.winfo_exists():
            return
        self.window = window = tk.Toplevel(widget)
        window.withdraw()
        window.overrideredirect(True)
        try:
            window.attributes("-topmost", True)
        except tk.TclError:
            pass
        label = tk.Label(
            window,
            text=text,
            justify="left",
            wraplength=self.wraplength,
            padx=10,
            pady=8,
            relief="solid",
            borderwidth=1,
            bg="#fff9d8",
            fg="#202020",
            font=("TkDefaultFont", 11),
        )
        label.pack(fill="both", expand=True)
        x, y = widget.winfo_pointerxy()
        window.geometry(f"+{x + 18}+{y + 18}")
        window.deiconify()

    def hide(self) -> None:
        if self.after_id is not None:
            try:
                self.root.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None


@dataclass
class ModelDefaults:
    codex_model: str
    fable_model: str
    opus_model: str
    gemini_model: str
    controller_model: str
    codex_bin: str
    claude_bin: str
    gemini_bin: str
    codex_bypass_sandbox: bool
    controller_role_model: str = ""
    worker_role_model: str = ""
