"""Windows are sized to the screen: never wider or taller than what is visible."""

from __future__ import annotations

import tkinter as tk

from icoda_gui import screen


def test_windows_shrink_to_the_screen() -> None:
    root = tk.Tk()  # the stub reports a 1440 x 900 screen
    assert screen.fit_to_screen(root, 1400, 900) == (1400, 760)
    assert screen.fit_to_screen(root, 1120, 760) == (1120, 760)
    assert screen.fit_to_screen(root, 600, 400) == (600, 400)
    assert screen.fit_to_screen(root, 3000, 2000) == (1400, 760)
