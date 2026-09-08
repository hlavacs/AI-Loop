"""Window sizes that fit the screen the application runs on."""

from __future__ import annotations

from typing import Any

MARGIN_X = 40   # window frame and a little air
MARGIN_Y = 140  # menu bar, dock or task bar, title bar


def fit_to_screen(window: Any, width: int, height: int) -> tuple[int, int]:
    """Size ``window`` to ``width`` x ``height`` or smaller so that it fits the screen, and centre it."""
    try:
        screen_width, screen_height = int(window.winfo_screenwidth()), int(window.winfo_screenheight())
    except (TypeError, ValueError, RuntimeError):
        screen_width, screen_height = width + MARGIN_X, height + MARGIN_Y
    fitted_width = max(min(width, screen_width - MARGIN_X), 400)
    fitted_height = max(min(height, screen_height - MARGIN_Y), 300)
    x = max((screen_width - fitted_width) // 2, 0)
    y = max((screen_height - MARGIN_Y - fitted_height) // 2, 0)
    window.geometry(f"{fitted_width}x{fitted_height}+{x}+{y}")
    return fitted_width, fitted_height
