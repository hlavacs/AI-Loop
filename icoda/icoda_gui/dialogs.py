"""Message boxes that stay small: long texts are cut, the whole text goes to the log and the panel."""

from __future__ import annotations

from tkinter import messagebox

MAX_LINES = 10
MAX_CHARS = 700


def shorten(text: str, max_lines: int = MAX_LINES, max_chars: int = MAX_CHARS) -> str:
    """The first lines of ``text``, cut to fit a message box, with a note when something was left out."""
    lines = text.strip().splitlines()
    kept = "\n".join(lines[:max_lines])
    if len(kept) > max_chars:
        kept = kept[:max_chars].rstrip() + "…"
    if kept != text.strip():
        kept += "\n\n(the full text is in the step panel and in .icoda/icoda.log)"
    return kept


def show_error(title: str, text: str) -> None:
    messagebox.showerror(title, shorten(text))
