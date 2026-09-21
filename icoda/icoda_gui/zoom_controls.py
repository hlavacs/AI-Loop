"""Compact zoom controls shared by ICODA's diagram views."""

from __future__ import annotations

from collections.abc import Callable
from tkinter import ttk
from typing import Any

from icoda_gui import tooltip

ZOOM_OUT = 0.8
ZOOM_IN = 1.25
MAX_ZOOM = 2.5


def build(
    parent: Any,
    *,
    zoom_out: Callable[[], None],
    fit: Callable[[], None],
    reset: Callable[[], None],
    zoom_in: Callable[[], None],
) -> tuple[Any, dict[str, Any]]:
    """Return an analyzer-style ``- Fit 100% +`` control strip and its widgets."""
    frame = ttk.Frame(parent)
    definitions = (
        ("zoom-out", "−", 3, zoom_out, "Zoom out. You can also hold Ctrl and scroll down over the diagram."),
        ("fit", "Fit", 4, fit, "Fit the complete diagram into the visible canvas area."),
        ("reset", "100%", 5, reset, "Reset the diagram to its original zoom level."),
        ("zoom-in", "+", 3, zoom_in, "Zoom in. You can also hold Ctrl and scroll up over the diagram."),
    )
    widgets: dict[str, Any] = {}
    for index, (name, label, width, command, help_text) in enumerate(definitions):
        button = ttk.Button(frame, text=label, width=width, command=command)
        button.pack(side="left", padx=(3, 0) if index else 0)
        tooltip.attach(button, help_text)
        widgets[name] = button
    return frame, widgets
