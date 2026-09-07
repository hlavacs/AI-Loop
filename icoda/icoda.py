"""ICODA — Interactive Code Development and Analysis.

The application: main window, the view panel, the status bar, and the wiring between the supporting
modules in ``icoda_core``. Start it through ``icoda.bash`` (``icoda.cmd`` on Windows).
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from icoda_core import __version__


class App:
    """Main window with menu, view panel and status bar."""

    def __init__(self, root: tk.Tk, project: Path | None = None) -> None:
        self.root = root
        self.project: Path | None = None
        self.status = tk.StringVar(value="No project open")
        root.title("ICODA")
        root.geometry("1200x800")
        self._build_menu()
        self._build_panel()
        self._build_statusbar()
        if project is not None:
            self.open_project(project)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open Project…", command=self.ask_open_project)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

    def _build_panel(self) -> None:
        self.canvas = tk.Canvas(self.root, background="white", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self.root)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Label(bar, textvariable=self.status, anchor="w").pack(fill=tk.X, padx=6, pady=2)

    def ask_open_project(self) -> None:
        chosen = filedialog.askdirectory(title="Open project directory")
        if chosen:
            self.open_project(Path(chosen))

    def open_project(self, path: Path) -> None:
        self.project = Path(path).expanduser().resolve()
        self.root.title(f"ICODA — {self.project.name}")
        self.status.set(f"Project: {self.project}")


def parse_args(argv: list[str]) -> Path | None:
    """Return the project directory given on the command line, or None."""
    if len(argv) > 1:
        raise SystemExit(f"usage: icoda.py [project-directory]  (ICODA {__version__})")
    return Path(argv[0]) if argv else None


def main(argv: list[str] | None = None) -> int:
    project = parse_args(sys.argv[1:] if argv is None else argv)
    root = tk.Tk()
    App(root, project)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
