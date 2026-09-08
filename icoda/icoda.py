"""ICODA — Interactive Code Development and Analysis.

The application: main window, the File View canvas, the entity panel, the status bar, and the wiring to
the supporting modules in ``icoda_core``. Start it through ``icoda.bash`` (``icoda.cmd`` on Windows).
"""

from __future__ import annotations

import math
import queue
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from icoda_core import __version__, persistence, session, views

NODE_RADIUS = 6
CLUSTER_LEVEL_BELOW = 1.6  # file-level arrows appear once zoomed in this far beyond the fit


class Tooltip:
    """A small floating label shown near the pointer."""

    def __init__(self, widget: Any) -> None:
        self.widget = widget
        self.window: Any = None

    def show(self, text: str, x: int, y: int) -> None:
        self.hide()
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{x + 14}+{y + 12}")
        tk.Label(self.window, text=text, justify="left", background="#ffffe0", relief="solid", borderwidth=1,
                 padx=6, pady=3).pack()

    def hide(self) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None


class FileViewCanvas:
    """Draws a :class:`views.FileViewLayout` on a Tk canvas with zoom, pan, hover, click and double click."""

    def __init__(self, canvas: Any, app: App) -> None:
        self.canvas = canvas
        self.app = app
        self.layout: views.FileViewLayout | None = None
        self.scale = 1.0
        self.fit_scale = 1.0
        self.user_zoomed = False
        self.offset = (0.0, 0.0)
        self.drag_start: tuple[int, int] | None = None
        self.dragged = False
        self.item_nodes: dict[int, str] = {}
        self.tooltip = Tooltip(canvas)
        for event, handler in (("<MouseWheel>", self.on_wheel), ("<Button-4>", self.on_wheel),
                               ("<Button-5>", self.on_wheel), ("<ButtonPress-1>", self.on_press),
                               ("<B1-Motion>", self.on_drag), ("<ButtonRelease-1>", self.on_release),
                               ("<Double-Button-1>", self.on_double_click), ("<Motion>", self.on_motion),
                               ("<Configure>", self.on_resize)):
            canvas.bind(event, handler)

    # -- coordinates ------------------------------------------------------------------------

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        return (x * self.scale + self.offset[0], y * self.scale + self.offset[1])

    def show(self, layout: views.FileViewLayout) -> None:
        self.layout = layout
        self.user_zoomed = False
        self.scale, self.offset = 1.0, (0.0, 0.0)
        self.fit()
        self.canvas.after(150, self.on_resize, None)  # once more when the window geometry has settled

    def fit(self) -> None:
        """Scale and centre the whole diagram — as drawn, labels included — inside the visible canvas."""
        if self.layout is None or not self.layout.nodes:
            self.redraw()
            return
        width = max(int(self.canvas.winfo_width() or 0), 200)
        height = max(int(self.canvas.winfo_height() or 0), 200)
        for _ in range(2):  # label sizes depend on the scale, so measure, fit, and measure once more
            self.redraw()
            bounds = self.canvas.bbox("all") or (0, 0, width, height)
            left, top, right, bottom = (float(v) for v in bounds)
            drawn_width, drawn_height = max(right - left, 1.0), max(bottom - top, 1.0)
            factor = min((width - 24) / drawn_width, (height - 24) / drawn_height)
            self.scale *= factor
            self.offset = (self.offset[0] * factor + (width - drawn_width * factor) / 2 - left * factor,
                           self.offset[1] * factor + (height - drawn_height * factor) / 2 - top * factor)
        self.fit_scale = self.scale
        self.redraw()

    def on_resize(self, _event: Any) -> None:
        if not self.user_zoomed:
            self.fit()

    # -- drawing ----------------------------------------------------------------------------

    def redraw(self) -> None:
        self.canvas.delete("all")
        self.item_nodes = {}
        if self.layout is None:
            return
        self._draw_circles()
        self._draw_arrows()
        self._draw_nodes()
        if self.app.opened is not None and self.app.opened.model.stale:
            self.canvas.create_text(12, 12, anchor="nw", fill="#c00000", font=("TkDefaultFont", 11, "bold"),
                                    text=f"STALE — {self.app.opened.model.stale_reason}")

    def _draw_circles(self) -> None:
        """The circles themselves are never drawn; a multi-file cluster shows its name in the empty centre."""
        assert self.layout is not None
        for circle in self.layout.circles:
            if len(circle.files) < 2:
                continue
            cx, cy = self.to_screen(circle.cx, circle.cy)
            self.canvas.create_text(cx, cy, text=circle.name, fill="#9a9a9a",
                                    font=("TkDefaultFont", max(8, int(12 * self.scale)), "bold"))

    def _draw_arrows(self) -> None:
        assert self.layout is not None
        cluster_level = self.scale < self.fit_scale * CLUSTER_LEVEL_BELOW
        clustering = self.app.opened.clustering if self.app.opened else None
        for arrow in self.layout.file_arrows:
            same_cluster = clustering is not None and clustering.index_of(arrow.source) == clustering.index_of(arrow.target)
            if cluster_level and not same_cluster and not arrow.target.startswith("external:"):
                continue
            self._draw_arrow(self.layout.nodes[arrow.source], self.layout.nodes[arrow.target], arrow, 1.0)
        if cluster_level:
            for arrow in self.layout.cluster_arrows:
                self._draw_arrow(self._cluster_anchor(arrow.source), self._cluster_anchor(arrow.target), arrow, 2.0)

    def _cluster_anchor(self, endpoint: str) -> views.Node:
        assert self.layout is not None
        if endpoint in self.layout.nodes:
            return self.layout.nodes[endpoint]
        circle = next(c for c in self.layout.circles if c.id == endpoint)
        return views.Node(circle.id, circle.name, circle.cx, circle.cy, circle.id, "cluster")

    def _draw_arrow(self, a: views.Node, b: views.Node, arrow: views.Arrow, base_width: float) -> None:
        margin = 12 if a.kind == "file" else (self._radius_of(a) if a.kind == "cluster" else 30)
        x0, y0, x1, y1 = views.arrow_endpoints(a, b, margin)
        x1, y1 = self._shorten_end(x0, y0, x1, y1, b)
        sx0, sy0 = self.to_screen(x0, y0)
        sx1, sy1 = self.to_screen(x1, y1)
        if b.kind == "external":
            self.canvas.create_line(sx0, sy0, sx1, sy1, fill="#c0c0c0", width=1, arrow="last", dash=(2, 4))
            return
        colour = views.ARROW_COLOURS[arrow.dominant]
        width = min(4.0, base_width + math.log2(arrow.weight) * 0.5)
        self.canvas.create_line(sx0, sy0, sx1, sy1, fill=colour, width=width, arrow="last")
        self.canvas.create_text((sx0 + sx1) / 2, (sy0 + sy1) / 2 - 6, text=arrow.badge, fill=colour,
                                font=("TkDefaultFont", max(7, int(8 * self.scale))))

    def _shorten_end(self, x0: float, y0: float, x1: float, y1: float, b: views.Node) -> tuple[float, float]:
        if b.kind != "cluster":
            return x1, y1
        _, _, ex, ey = views.arrow_endpoints(views.Node("", "", x0, y0, ""), b, self._radius_of(b))
        return ex, ey

    def _radius_of(self, node: views.Node) -> float:
        assert self.layout is not None
        return max(next((c.radius for c in self.layout.circles if c.id == node.id), 30.0), 12.0)

    def _draw_nodes(self) -> None:
        assert self.layout is not None
        for node in self.layout.nodes.values():
            x, y = self.to_screen(node.x, node.y)
            if node.kind == "external":
                item = self.canvas.create_rectangle(x - 34, y - 12, x + 34, y + 12, fill="#f0f0f0", outline="#8a8a8a")
                self.canvas.create_text(x, y, text=node.label, fill="#505050")
            else:
                fill = "#d62728" if self._has_errors(node.id) else "#4c78a8"
                item = self.canvas.create_oval(x - NODE_RADIUS, y - NODE_RADIUS, x + NODE_RADIUS, y + NODE_RADIUS,
                                               fill=fill, outline="")
                self._draw_label(node, x, y)
            self.item_nodes[item] = node.id

    def _draw_label(self, node: views.Node, x: float, y: float) -> None:
        assert self.layout is not None
        circle = next((c for c in self.layout.circles if c.id == node.cluster), None)
        dx, dy = (node.x - circle.cx, node.y - circle.cy) if circle else (1.0, 0.0)
        length = math.hypot(dx, dy) or 1.0
        anchor = "w" if dx >= 0 else "e"
        self.canvas.create_text(x + dx / length * 10, y + dy / length * 10, text=node.label, anchor=anchor,
                                font=("TkDefaultFont", max(7, int(9 * self.scale))))

    def _has_errors(self, file: str) -> bool:
        opened = self.app.opened
        return bool(opened and file in opened.model.files and opened.model.files[file].errors)

    # -- interaction ------------------------------------------------------------------------

    def on_wheel(self, event: Any) -> None:
        delta = getattr(event, "delta", 0) or (120 if getattr(event, "num", 0) == 4 else -120)
        factor = 1.1 if delta > 0 else 1 / 1.1
        new_scale = min(8.0, max(0.2, self.scale * factor))
        factor = new_scale / self.scale
        self.offset = (event.x - (event.x - self.offset[0]) * factor, event.y - (event.y - self.offset[1]) * factor)
        self.scale = new_scale
        self.user_zoomed = True
        self.redraw()

    def on_press(self, event: Any) -> None:
        self.drag_start, self.dragged = (event.x, event.y), False

    def on_drag(self, event: Any) -> None:
        if self.drag_start is None:
            return
        dx, dy = event.x - self.drag_start[0], event.y - self.drag_start[1]
        if abs(dx) + abs(dy) > 3:
            self.dragged = True
            self.user_zoomed = True
        self.offset = (self.offset[0] + dx, self.offset[1] + dy)
        self.drag_start = (event.x, event.y)
        self.redraw()

    def on_release(self, event: Any) -> None:
        if not self.dragged:
            node = self.node_at(event.x, event.y)
            if node is not None:
                self.app.select_node(node)
        self.drag_start = None

    def on_double_click(self, event: Any) -> None:
        node = self.node_at(event.x, event.y)
        if node is not None and not node.startswith("external:"):
            self.app.open_editor(node)

    def on_motion(self, event: Any) -> None:
        node = self.node_at(event.x, event.y)
        if node is None:
            self.tooltip.hide()
        else:
            self.tooltip.show(self.app.describe_node(node), event.x_root, event.y_root)

    def node_at(self, x: int, y: int) -> str | None:
        for item in self.canvas.find_overlapping(x - 2, y - 2, x + 2, y + 2):
            if item in self.item_nodes:
                return self.item_nodes[item]
        return None


class App:
    """Main window with menu, File View, entity panel and status bar."""

    def __init__(self, root: tk.Tk, project: Path | None = None, config: persistence.UserConfig | None = None,
                 config_path: Path | None = None) -> None:
        self.root = root
        self.project: Path | None = None
        self.opened: session.OpenedProject | None = None
        self.config_path = config_path or persistence.config_path()
        self.config = config or persistence.UserConfig.load(self.config_path)
        self.status = tk.StringVar(value="No project open")
        self.results: queue.Queue[session.OpenedProject | Exception] = queue.Queue()
        root.title("ICODA")
        root.geometry("1400x900")
        self._build_menu()
        self._build_panel()
        self._build_statusbar()
        if project is not None:
            self.open_project(project)

    # -- construction -----------------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open Project…", command=self.ask_open_project)
        self.recent_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Open Recent", menu=self.recent_menu)
        file_menu.add_command(label="Reload", command=self.reload)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Fit to Window", command=self.fit_view)
        menubar.add_cascade(label="View", menu=view_menu)
        self.root.config(menu=menubar)
        self._fill_recent_menu()

    def fit_view(self) -> None:
        self.view.user_zoomed = False
        self.view.fit()

    def _fill_recent_menu(self) -> None:
        self.recent_menu.delete(0, tk.END)
        for path in self.config.known_projects:
            self.recent_menu.add_command(label=path, command=self._opener(Path(path)))

    def _opener(self, path: Path) -> Any:
        return lambda: self.open_project(path)

    def _build_panel(self) -> None:
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(paned, background="white", highlightthickness=0, width=1050, height=800)
        paned.add(self.canvas, weight=4)
        side = ttk.Frame(paned, width=320)
        paned.add(side, weight=0)
        self.side_title = tk.StringVar(value="Entities")
        ttk.Label(side, textvariable=self.side_title, anchor="w").pack(fill=tk.X, padx=4, pady=2)
        self.tree = ttk.Treeview(side, columns=("kind", "line"), show="tree headings")
        self.tree.heading("kind", text="kind")
        self.tree.heading("line", text="line")
        self.tree.column("kind", width=80)
        self.tree.column("line", width=50)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-Button-1>", self.on_tree_double_click)
        self.view = FileViewCanvas(self.canvas, self)

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self.root)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Label(bar, textvariable=self.status, anchor="w").pack(fill=tk.X, padx=6, pady=2)

    # -- projects ---------------------------------------------------------------------------

    def ask_open_project(self) -> None:
        chosen = filedialog.askdirectory(title="Open project directory")
        if chosen:
            self.open_project(Path(chosen))

    def open_project(self, path: Path) -> None:
        self.project = Path(path).expanduser().resolve()
        self.root.title(f"ICODA — {self.project.name}")
        self.status.set(f"Analysing {self.project} …")
        threading.Thread(target=self._analyse, args=(self.project,), daemon=True).start()
        self.root.after(100, self._poll)

    def reload(self) -> None:
        if self.project is not None:
            self.open_project(self.project)

    def _analyse(self, root: Path) -> None:
        try:
            self.results.put(session.open_project(root, self.config))
        except Exception as exc:  # noqa: BLE001  (reported in the status bar and logged with its traceback)
            session.log_event("analysis failed:\n" + traceback.format_exc(), root)
            self.results.put(exc)

    def _poll(self) -> None:
        try:
            result = self.results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll)
            return
        if isinstance(result, Exception):
            log = (self.project or Path(".")) / ".icoda" / "icoda.log"
            self.status.set(f"Analysis failed: {result!r}  (details in {log})")
            messagebox.showerror("ICODA", f"{result!r}\n\nDetails: {log}")
        else:
            self.show(result)

    def show(self, opened: session.OpenedProject) -> None:
        """Present an opened project: canvas, status bar, recent list, configuration."""
        self.opened = opened
        self.project = opened.root
        try:
            self.view.show(opened.layout)
        except Exception:  # noqa: BLE001  (a drawing problem must not hide the rest of the window)
            session.log_event("drawing failed:\n" + traceback.format_exc(), opened.root)
            self.status.set("drawing failed (details in .icoda/icoda.log)")
            return
        session.log_event(f"drawn: canvas {self.canvas.winfo_width()}x{self.canvas.winfo_height()}, "
                          f"{len(opened.layout.nodes)} nodes, scale {self.view.scale:.3f}, offset {self.view.offset}",
                          opened.root)
        libclang = opened.libclang or "libclang: none found"
        notes = ("  |  " + "; ".join(opened.messages)) if opened.messages else ""
        self.status.set(f"{opened.root.name}: {opened.summary}  |  {libclang}{notes}")
        self.config.save(self.config_path)
        self._fill_recent_menu()
        self.side_title.set("Entities")
        self.tree.delete(*self.tree.get_children())

    # -- nodes ------------------------------------------------------------------------------

    def describe_node(self, node_id: str) -> str:
        if self.opened is None:
            return node_id
        if node_id.startswith("external:"):
            library = node_id.split(":", 1)[1]
            names = self.opened.model.externals[library].names
            return f"{library}\n" + ", ".join(names[:12]) + (" …" if len(names) > 12 else "")
        info = self.opened.model.files.get(node_id)
        entities = self.opened.model.entities_in(node_id)
        lines = [node_id, f"{info.unit}{' module ' + info.module if info and info.module else ''}" if info else ""]
        lines.append(f"{len(entities)} entities")
        if info and info.errors:
            lines.append(f"errors: {info.errors[0]}")
        return "\n".join(line for line in lines if line)

    def select_node(self, node_id: str) -> None:
        """A click on a file lists its entities in the side panel (the Class View arrives in M4)."""
        if self.opened is None or node_id.startswith("external:"):
            return
        self.side_title.set(node_id)
        self.tree.delete(*self.tree.get_children())
        entities = sorted(self.opened.model.entities_in(node_id), key=lambda e: e.line)
        parents = {e.usr: e for e in entities}
        for entity in entities:
            parent = entity.parent if entity.parent in parents else ""
            label = entity.name + (f"  {entity.signature}" if entity.signature else "")
            self.tree.insert(parent, tk.END, iid=entity.usr, text=label, values=(entity.kind.value, entity.line),
                             open=True)

    def on_tree_double_click(self, _event: Any) -> None:
        if self.opened is None:
            return
        for usr in self.tree.selection():
            entity = self.opened.model.entities.get(usr)
            if entity is not None:
                self.open_editor(entity.file, entity.line)

    def open_editor(self, file: str, line: int = 1) -> None:
        if self.project is None:
            return
        if not session.open_in_editor(self.project / file, line, self.config.editor):
            self.status.set(f"could not open an editor for {file}")


def parse_args(argv: list[str]) -> Path | None:
    """Return the project directory given on the command line, or None."""
    if len(argv) > 1:
        raise SystemExit(f"usage: icoda.py [project-directory]  (ICODA {__version__})")
    return Path(argv[0]) if argv else None


def main(argv: list[str] | None = None) -> int:
    project = parse_args(sys.argv[1:] if argv is None else argv)
    root = tk.Tk()
    app = App(root, project)
    if project is None and app.config.last_project and Path(app.config.last_project).is_dir():
        app.open_project(Path(app.config.last_project))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
