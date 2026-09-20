"""ICODA — Interactive Code Development and Analysis.

The application: main window, the File View canvas, the entity panel, the status bar, and the wiring to
the supporting modules in ``icoda_core``. Start it through ``icoda.bash`` (``icoda.cmd`` on Windows).
"""

from __future__ import annotations

import math
import queue
import shlex
import sys
import threading
import tkinter as tk
import traceback
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from icoda_core import (
    __version__,
    agent,
    analysis,
    clusters,
    coverage_index,
    executables,
    expansion,
    generator,
    graph_filter,
    grouping,
    implementation_queue,
    node_status,
    persistence,
    phases,
    session,
    source_edit,
    source_watch,
    specification,
    steplog,
    steps,
    test_selection,
    toolchain,
    views,
)
from icoda_core.model import CALLABLE_KINDS, DerivedModel
from icoda_gui import (
    call_view,
    class_view,
    coverage_view,
    executable_selector,
    graph_canvas,
    issue_view,
    mind_map_view,
    provider_field,
    screen,
    source_editor,
    spec_editor,
    step_controller,
    step_panel,
    tasks,
    tooltip,
    troubleshooting,
    zoom_controls,
)

CLUSTER_LEVEL_BELOW = 1.6  # file-level arrows appear once zoomed in this far beyond the fit
DOCS_ROOT = Path(__file__).resolve().parent
DOCUMENTS = (("Getting started", "docs/GETTING_STARTED.md"), ("Tutorial", "docs/TUTORIAL.md"),
             ("Handbook", "HANDBOOK.md"), ("Troubleshooting", "docs/TROUBLESHOOTING.md"))
MODIFIER = "Command" if sys.platform == "darwin" else "Control"
ACCELERATOR = "⌘" if sys.platform == "darwin" else "Ctrl+"
STALL_SECONDS = 5.0

class FileViewCanvas(graph_canvas.NodeAppearanceCanvas):
    """Draws a :class:`views.FileViewLayout` on a Tk canvas with zoom, pan, hover, click and double click."""

    def __init__(self, canvas: Any, app: App) -> None:
        super().__init__()
        self.canvas = canvas
        self.app = app
        self.layout: views.FileViewLayout | None = None
        self._original_layout: views.FileViewLayout | None = None
        self.compact = False
        self.scale = 1.0
        self.fit_scale = 1.0
        self.user_zoomed = False
        self.offset = (0.0, 0.0)
        self.drag_start: tuple[int, int] | None = None
        self.dragged = False
        self.item_nodes: dict[int, str] = {}
        self.node_boxes: dict[str, tuple[float, float, float, float]] = {}
        self.zoom_control_widgets: dict[str, Any] = {}
        self.tooltip = tooltip.Tooltip(canvas)
        for event, handler in (("<MouseWheel>", self.on_wheel), ("<Button-4>", self.on_wheel),
                               ("<Button-5>", self.on_wheel), ("<ButtonPress-1>", self.on_press),
                               ("<B1-Motion>", self.on_drag), ("<ButtonRelease-1>", self.on_release),
                               ("<ButtonPress-2>", self.on_press), ("<B2-Motion>", self.on_drag),
                               ("<ButtonRelease-2>", self.on_release),
                               ("<Double-Button-1>", self.on_double_click), ("<Motion>", self.on_motion),
                               ("<Configure>", self.on_resize)):
            canvas.bind(event, handler)
        self.action_menu = graph_canvas.NodeActionMenu(
            canvas, self.node_at, app.graph_actions, app.dispatch_graph_action)

    def build_zoom_controls(self, parent: Any) -> Any:
        controls, self.zoom_control_widgets = zoom_controls.build(
            parent,
            zoom_out=lambda: self.zoom(zoom_controls.ZOOM_OUT),
            fit=self.fit,
            reset=self.reset_zoom,
            zoom_in=lambda: self.zoom(zoom_controls.ZOOM_IN),
        )
        return controls

    # -- coordinates ------------------------------------------------------------------------

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        return (x * self.scale + self.offset[0], y * self.scale + self.offset[1])

    def show(self, layout: views.FileViewLayout) -> None:
        self.layout = self._original_layout = layout
        self.user_zoomed = False
        self.scale, self.offset = 1.0, (0.0, 0.0)
        self.fit()
        self.canvas.after(150, self.on_resize, None)  # once more when the window geometry has settled

    def fit(self) -> None:
        """Scale and centre the whole diagram — as drawn, labels included — inside the visible canvas."""
        self.user_zoomed = False
        self.layout = self._original_layout or self.layout
        self.compact = False
        if self.layout is None or not self.layout.nodes:
            self.redraw()
            return
        width = max(int(self.canvas.winfo_width() or 0), 200)
        height = max(int(self.canvas.winfo_height() or 0), 200)
        # The status legend and hierarchy use screen coordinates; neither belongs in the fitted graph bounds.
        hierarchy = 306 if self.expansion_result is not None and self.expansion_result.graph.nodes else 0
        available_width, available_height = max(width - hierarchy - 24, 100), max(height - 60, 100)
        self._fit_graph(available_width, available_height)
        if self._boxes_overlap():
            column_width = max(box[2] - box[0] for box in self.node_boxes.values()) + 4
            row_height = max(box[3] - box[1] for box in self.node_boxes.values()) + 8
            columns = max(1, int((available_width + 4) / column_width))
            self.layout = views.compact_file_view(self.layout, columns, column_width, row_height)
            self.compact = True
            self.scale, self.offset = 1.0, (0.0, 0.0)
            self._fit_graph(available_width, available_height)
        self.fit_scale = self.scale
        self.redraw()

    def _boxes_overlap(self) -> bool:
        boxes = sorted(self.node_boxes.values())
        for index, a in enumerate(boxes):
            for b in boxes[index + 1:]:
                if b[0] >= a[2]:
                    break
                if a[1] < b[3] and b[1] < a[3]:
                    return True
        return False

    def _fit_graph(self, available_width: float, available_height: float) -> None:
        for _ in range(6):  # text remains readable while node positions and edge geometry scale
            self.redraw()
            bounds = self.canvas.bbox("file-graph") or (0, 0, available_width, available_height)
            left, top, right, bottom = (float(v) for v in bounds)
            drawn_width, drawn_height = max(right - left, 1.0), max(bottom - top, 1.0)
            factor = min(available_width / drawn_width, available_height / drawn_height)
            factor = min(factor, zoom_controls.MAX_ZOOM / self.scale)
            self.scale *= factor
            self.offset = (self.offset[0] * factor + 12 + (available_width - drawn_width * factor) / 2 - left * factor,
                           self.offset[1] * factor + 48 + (available_height - drawn_height * factor) / 2 - top * factor)
            if abs(factor - 1.0) < 0.001:
                break

    def on_resize(self, _event: Any) -> None:
        if not self.user_zoomed:
            self.fit()

    # -- drawing ----------------------------------------------------------------------------

    def redraw(self) -> None:
        self.canvas.delete("all")
        self.item_nodes = {}
        self.node_boxes = {}
        if self.layout is None:
            return
        self._draw_circles()
        visible_count = self._draw_nodes()
        self._draw_arrows()
        self.canvas.tag_lower("file-edge")
        self.canvas.addtag_all("file-graph")
        self.draw_filter_empty(visible_count)
        self.draw_appearance_key()
        self.draw_expansion_layer()

    def _draw_circles(self) -> None:
        """The circles themselves are never drawn; a multi-file cluster shows its name in the empty centre."""
        assert self.layout is not None
        if self.compact:
            return  # cluster labels and actions remain in the hierarchy beside the compact file grid
        for circle in self.layout.circles:
            if len(circle.files) < 2 or not any(self.node_visible(file) for file in circle.files):
                continue
            cx, cy = self.to_screen(circle.cx, circle.cy)
            label = self.canvas.create_text(cx, cy, text=circle.name, fill="#9a9a9a",
                                            font=("TkDefaultFont", max(8, int(12 * self.scale)), "bold"))
            self.item_nodes[label] = f"cluster:{circle.id}"

    def _draw_arrows(self) -> None:
        assert self.layout is not None
        cluster_level = not self.compact and self.scale < self.fit_scale * CLUSTER_LEVEL_BELOW
        clustering = self.app.opened.clustering if self.app.opened else None
        for arrow in self.layout.file_arrows:
            if not self.edge_visible(arrow.source, arrow.target):
                continue
            same_cluster = clustering is not None and clustering.index_of(arrow.source) == clustering.index_of(arrow.target)
            if cluster_level and not same_cluster and not arrow.target.startswith("external:"):
                continue
            self._draw_arrow(self.layout.nodes[arrow.source], self.layout.nodes[arrow.target], arrow, 1.0)
        if cluster_level:
            for arrow in self.layout.cluster_arrows:
                if not self.edge_visible(arrow.source, arrow.target):
                    continue
                self._draw_arrow(self._cluster_anchor(arrow.source), self._cluster_anchor(arrow.target), arrow, 2.0)

    def _cluster_anchor(self, endpoint: str) -> views.Node:
        assert self.layout is not None
        if endpoint in self.layout.nodes:
            return self.layout.nodes[endpoint]
        circle = next(c for c in self.layout.circles if c.id == endpoint)
        return views.Node(circle.id, circle.name, circle.cx, circle.cy, circle.id, "cluster")

    def _draw_arrow(self, a: views.Node, b: views.Node, arrow: views.Arrow, base_width: float) -> None:
        sx0, sy0 = self._edge_point(a, b)
        sx1, sy1 = self._edge_point(b, a)
        if b.kind == "external":
            colour = self.edge_colour(a.id, b.id, "#c0c0c0")
            self.canvas.create_line(sx0, sy0, sx1, sy1, fill=colour, width=1, arrow="last", dash=(2, 4),
                                    tags="file-edge")
            return
        colour = self.edge_colour(a.id, b.id, views.ARROW_COLOURS[arrow.dominant])
        width = min(4.0, base_width + math.log2(arrow.weight) * 0.5)
        self.canvas.create_line(sx0, sy0, sx1, sy1, fill=colour, width=width, arrow="last", tags="file-edge")
        self.canvas.create_text((sx0 + sx1) / 2, (sy0 + sy1) / 2 - 6, text=arrow.badge, fill=colour,
                                font=("TkDefaultFont", max(7, int(8 * self.scale))), tags="file-edge")

    def _edge_point(self, node: views.Node, towards: views.Node) -> tuple[float, float]:
        x, y = self.to_screen(node.x, node.y)
        tx, ty = self.to_screen(towards.x, towards.y)
        dx, dy = tx - x, ty - y
        box = self.node_boxes.get(node.id)
        if box is not None:
            half_width, half_height = (box[2] - box[0]) / 2, (box[3] - box[1]) / 2
            ratios = [size / abs(delta) for size, delta in ((half_width, dx), (half_height, dy)) if delta]
            fraction = min(ratios, default=0.0)
        else:
            fraction = self._radius_of(node) * self.scale / (math.hypot(dx, dy) or 1)
        return x + dx * fraction, y + dy * fraction

    def _radius_of(self, node: views.Node) -> float:
        assert self.layout is not None
        return max(next((c.radius for c in self.layout.circles if c.id == node.id), 30.0), 12.0)

    def _draw_nodes(self) -> int:
        assert self.layout is not None
        count = 0
        for node in self.layout.nodes.values():
            if not self.node_visible(node.id):
                continue
            count += 1
            x, y = self.to_screen(node.x, node.y)
            label = self.canvas.create_text(x, y, text=node.label, fill=self.node_text_colour(node.id),
                                            font=("TkDefaultFont", max(9, min(12, int(9 * self.scale)))))
            bounds = self.canvas.bbox(label) or (x - 45, y - 8, x + 45, y + 8)
            left, top, right, bottom = (float(v) for v in bounds)
            box = (left - 8, top - 5, right + 8, bottom + 5)
            self.node_boxes[node.id] = box
            fallback = "#f0f0f0" if node.kind == "external" else "#aec7e8"
            outline = "#d62728" if self._has_errors(node.id) else "#64748b"
            item = self.canvas.create_rectangle(*box, fill=self.node_fill(node.id, fallback),
                                                 outline=self.node_outline(node.id, outline))
            self.canvas.tag_lower(item, label)
            self.draw_stale_marker(node.id, box[2] - 3, box[1])
            self.item_nodes[item] = node.id
            self.item_nodes[label] = node.id
        return count

    def _has_errors(self, file: str) -> bool:
        opened = self.app.opened
        return bool(opened and file in opened.model.files and opened.model.files[file].errors)

    # -- interaction ------------------------------------------------------------------------

    def zoom(self, factor: float, origin: tuple[float, float] | None = None) -> None:
        """Zoom around ``origin`` while keeping the complete fitted diagram as the lower limit."""
        if self.layout is None or self.scale <= 0:
            return
        target = min(max(zoom_controls.MAX_ZOOM, self.fit_scale), max(self.fit_scale, self.scale * factor))
        actual_factor = target / self.scale
        if abs(actual_factor - 1.0) < 0.001:
            return
        origin_x, origin_y = origin or (float(self.canvas.winfo_width()) / 2, float(self.canvas.winfo_height()) / 2)
        self.offset = (origin_x - (origin_x - self.offset[0]) * actual_factor,
                       origin_y - (origin_y - self.offset[1]) * actual_factor)
        self.scale = target
        self.user_zoomed = True
        self.redraw()

    def reset_zoom(self) -> None:
        if self.layout is not None and self.scale > 0:
            self.zoom(max(self.fit_scale, 1.0) / self.scale)

    def on_wheel(self, event: Any) -> str:
        delta = getattr(event, "delta", 0) or (120 if getattr(event, "num", 0) == 4 else -120)
        self.zoom(zoom_controls.ZOOM_IN if delta > 0 else zoom_controls.ZOOM_OUT,
                  (float(event.x), float(event.y)))
        return "break"

    def on_press(self, event: Any) -> None:
        self.drag_start, self.dragged = (event.x, event.y), False
        self.tooltip.hide()

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
        if not self.dragged and getattr(event, "num", 1) == 1 and self.toggle_expansion_at(event.x, event.y):
            self.drag_start = None
            return
        if not self.dragged and getattr(event, "num", 1) == 1:
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
                 config_path: Path | None = None, watchdog: bool = False) -> None:
        self.root = root
        self.project: Path | None = None
        self.opened: session.OpenedProject | None = None
        self.displayed: session.OpenedProject | None = None
        self._call_source_root: Path | None = None
        self.spec_editor: spec_editor.SpecificationEditor | None = None
        self._spec_editors: dict[Path, spec_editor.SpecificationEditor] = {}
        self.config_path = config_path or persistence.config_path()
        self.config = config or persistence.UserConfig.load(self.config_path)
        self.status = tk.StringVar(value="No project open")
        self.language_var = tk.StringVar(value="Language: —")
        self.coverage_mode_var = tk.BooleanVar(value=False)
        self.graph_filter_var = tk.StringVar(value="")
        self.neighborhood_depth_var = tk.IntVar(value=0)
        self.libclang_choice_var = tk.StringVar(value="")
        self.libclang_result_var = tk.StringVar(value="No libclang selection evaluated")
        self.libclang_window: tk.Toplevel | None = None
        self.expansion_state: frozenset[str] = frozenset()
        self._expansion_initialized = False
        self._expansion_auto_expand = True
        self.graph_focus_usr: str | None = None
        self._source_snapshot: source_watch.Snapshot | None = None
        self.results: queue.Queue[session.OpenedProject | Exception] = queue.Queue()
        self.providers = agent.load_providers()
        self.tasks = tasks.UiTasks(root, on_failure=lambda trace: session.log_event("background task failed:\n"
                                                                                 + trace, self.project))
        self.run_async, self.run_on_ui = self.tasks.run_async, self.tasks.run_on_ui
        self._pending_analyses = 0
        self._editor_refresh_pending: Path | None = None
        self._panel_busy_by_analysis = False
        self.watchdog: tasks.Watchdog | None = None
        if watchdog:  # a real window only: reports a frozen Tk thread with every thread's stack in the log
            self.watchdog = tasks.Watchdog(root, lambda text: session.log_event("watchdog: " + text, self.project),
                                           stall_seconds=STALL_SECONDS)
        root.title("ICODA")
        screen.fit_to_screen(root, 1400, 900)
        self._build_menu()
        self._build_statusbar()  # packed first so that it is never squeezed out
        self._build_panel()
        self._bind_shortcuts()
        self.graph_filter_var.trace_add("write", self.apply_graph_filter)
        self.neighborhood_depth_var.trace_add("write", self.apply_graph_filter)
        self.steps = step_controller.StepController(self)
        self.recovery = troubleshooting.Troubleshooting(self)
        self.executables = executable_selector.ExecutableSelector(self, self.executable_bar, self.side_views)
        self.panel.activity_var.trace_add("write", lambda *_args: self._update_reload_button())
        self.status.trace_add("write", lambda *_args: self._update_reload_button())
        self._update_reload_button()
        root.report_callback_exception = self._callback_error
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<FocusIn>", self._refresh_external_edits)
        self.panel.set_project_facts(False)
        if project is not None:
            self.open_project(project)

    # -- construction -----------------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Project…", command=self.ask_new_project, accelerator=ACCELERATOR + "N")
        file_menu.add_command(label="Open Project…", command=self.ask_open_project, accelerator=ACCELERATOR + "O")
        self.recent_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Open Recent", menu=self.recent_menu)
        file_menu.add_command(label="Reload", command=self.reload, accelerator=ACCELERATOR + "R")
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.close, accelerator=ACCELERATOR + "Q")
        menubar.add_cascade(label="File", menu=file_menu)
        project_menu = tk.Menu(menubar, tearoff=0)
        project_menu.add_command(label="Specification…", command=self.edit_specification,
                                 accelerator=ACCELERATOR + "E")
        project_menu.add_command(label="Build", command=self.build_project, accelerator=ACCELERATOR + "B")
        project_menu.add_command(label="Test Command…", command=self.edit_test_command)
        project_menu.add_command(label="Choose libclang Library…", command=self.choose_libclang_library)
        project_menu.add_separator()
        project_menu.add_command(label="Propose Approach", command=lambda: self.steps.action("propose_approach"))
        project_menu.add_command(label="Propose Next Step", command=lambda: self.steps.action("propose"),
                                 accelerator=ACCELERATOR + "Return")
        project_menu.add_command(label="Approve Architecture", command=lambda: self.steps.action(
            "approve_architecture"))
        project_menu.add_command(label="Undo Last Step", command=lambda: self.steps.action("undo"))
        project_menu.add_command(label="Commit Manual Edits", command=lambda: self.steps.action("commit_manual"))
        menubar.add_cascade(label="Project", menu=project_menu)
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Fit to Window", command=self.fit_view)
        view_menu.add_command(label="File View", command=lambda: self.views.select(0))
        view_menu.add_command(label="Call View", command=self.show_call_view)
        view_menu.add_command(label="Class View", command=self.show_class_view)
        view_menu.add_command(label="Mind Map", command=self.show_mind_map_view)
        view_menu.add_command(label="Coverage Overview", command=self.show_coverage_view)
        view_menu.add_command(label="Rule Issues", command=self.show_issue_view)
        view_menu.add_command(label="Source Editor", command=lambda: self.side_views.select(self.source_editor.frame))
        view_menu.add_separator()
        view_menu.add_checkbutton(label="Recorded-test reachability colours", variable=self.coverage_mode_var,
                                  command=self.toggle_coverage_mode)
        menubar.add_cascade(label="View", menu=view_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        for label, relative in DOCUMENTS:
            help_menu.add_command(label=label, command=self._document_opener(relative))
        help_menu.add_separator()
        help_menu.add_command(label="Open Log File", command=self.open_log_file)
        help_menu.add_command(label="About ICODA", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)
        self._fill_recent_menu()

    def _bind_shortcuts(self) -> None:
        """Keyboard shortcuts for the menu entries that carry an accelerator (Command on macOS, Control elsewhere)."""
        for key, handler in (("n", self.ask_new_project), ("o", self.ask_open_project), ("r", self.reload),
                             ("q", self.close), ("e", self.edit_specification), ("b", self.build_project),
                             ("Return", lambda: self.steps.action("propose"))):
            self.root.bind_all(f"<{MODIFIER}-{key}>", self._shortcut(handler))

    @staticmethod
    def _shortcut(handler: Any) -> Any:
        def run(_event: Any) -> str:
            handler()
            return "break"
        return run

    # -- help -------------------------------------------------------------------------------

    def _document_opener(self, relative: str) -> Any:
        return lambda: self.open_document(relative)

    def open_document(self, relative: str) -> None:
        """Open one of the shipped documents with the system's default application."""
        path = DOCS_ROOT / relative
        if not path.is_file():
            self.status.set(f"{relative} is not part of this installation")
        elif not session.open_with_system(path):
            self.status.set(f"could not open {path}")

    def log_path(self) -> Path:
        """Where the current project (or, without one, ICODA itself) writes its log."""
        if self.project is not None:
            return persistence.ProjectStore(self.project).dir / session.LOG_NAME
        return self.config_path.parent / session.LOG_NAME

    def open_log_file(self) -> None:
        path = self.log_path()
        if not path.is_file():
            self.status.set(f"there is no log file yet at {path}")
        elif not session.open_with_system(path):
            self.status.set(f"could not open {path}")

    def show_about(self) -> None:
        messagebox.showinfo("About ICODA", f"ICODA {__version__} — Interactive Code Development and Analysis\n\n"
                            f"Log file: {self.log_path()}\nSettings: {self.config_path}\n\n"
                            "Help ▸ Getting started explains the first project; Help ▸ Troubleshooting the usual "
                            "problems.")

    def choose_libclang_library(self) -> None:
        """Show the detected libraries as a deterministic chooser, with the active choice marked."""
        selection = toolchain.select_candidate(toolchain.candidates(), self.config.preferred_libclang)
        self.libclang_choice_var.set(selection.active.path if selection.active is not None else "")
        self._show_libclang_selection(selection)
        window = tk.Toplevel(self.root)
        self.libclang_window = window
        window.title("Choose libclang Library")
        window.geometry("900x540")
        window.minsize(800, 500)
        window.transient(self.root)
        window.columnconfigure(0, weight=1)
        ttk.Label(window, text="Detected libclang libraries", font=("TkDefaultFont", 12, "bold")).grid(
            row=0, column=0, sticky="w", padx=16, pady=(16, 8))
        ttk.Radiobutton(window, text="Automatic detection", variable=self.libclang_choice_var, value="").grid(
            row=1, column=0, sticky="w", padx=16, pady=3)
        row = 2
        for candidate in selection.candidates:
            marker = " [active]" if candidate == selection.active else ""
            ttk.Radiobutton(
                window, text=f"{candidate.path} ({candidate.source}){marker}",
                variable=self.libclang_choice_var, value=candidate.path,
            ).grid(row=row, column=0, sticky="w", padx=16, pady=3)
            row += 1
        ttk.Label(window, textvariable=self.libclang_result_var, justify="left", wraplength=820).grid(
            row=row, column=0, sticky="ew", padx=16, pady=(10, 8))
        buttons = ttk.Frame(window)
        buttons.grid(row=row + 1, column=0, sticky="e", padx=16, pady=(0, 16))
        ttk.Button(buttons, text="Apply", command=self.apply_libclang_choice).pack(side="left", padx=4)
        ttk.Button(buttons, text="Close", command=window.destroy).pack(side="left", padx=4)

    def apply_libclang_choice(self) -> None:
        """Persist the listed choice and display what is selected versus already loaded."""
        detected = toolchain.candidates()
        requested = self.libclang_choice_var.get() or None
        if requested is not None and requested not in {candidate.path for candidate in detected}:
            requested = None
        self.config.preferred_libclang = requested
        self.config.save(self.config_path)
        selection = toolchain.select_candidate(detected, requested)
        self._show_libclang_selection(selection)
        active = selection.active.path if selection.active is not None else "none"
        if self.opened is not None and self.project is not None:  # the analysis child loads the library afresh
            self.status.set(f"Libclang choice saved. Active selection: {active}. Reloading the project …")
            self.reload()
        else:
            self.status.set(f"Libclang choice saved. Active selection: {active}. It is used at the next reload.")

    def _show_libclang_selection(self, selection: toolchain.Selection) -> None:
        active = selection.active.path if selection.active is not None else "none"
        loaded = self.opened.libclang if self.opened is not None and self.opened.libclang else "none"
        self.libclang_result_var.set(f"Active: {active}\nCurrently loaded: {loaded}\n{selection.reason}")

    def fit_view(self) -> None:
        self.view.user_zoomed = False
        self.view.fit()
        self.call_view.user_zoomed = False
        self.call_view.fit()
        self.class_view.user_zoomed = False
        self.class_view.fit()
        self.mind_map_view.user_zoomed = False
        self.mind_map_view.fit()

    def show_call_view(self) -> None:
        self.views.select(1)

    def show_class_view(self) -> None:
        self.views.select(2)

    def show_coverage_view(self) -> None:
        self.views.select(4)

    def show_issue_view(self) -> None:
        self.views.select(5)

    def show_mind_map_view(self) -> None:
        self.views.select(3)

    def toggle_coverage_mode(self) -> None:
        """Switch every diagram together; it is deliberately safe before a project is open."""
        enabled = bool(self.coverage_mode_var.get())
        for canvas in self._diagram_canvases():
            canvas.set_coverage_mode(enabled)

    def apply_graph_filter(self, *_trace_args: str) -> None:
        """Apply or clear the one filter/depth setting without loading a project."""
        self.refresh_graph_appearances()

    def clear_graph_filter(self) -> None:
        """Clear an active or already-empty filter safely."""
        self.graph_filter_var.set("")

    def focus_graph_node(self, usr: str | None) -> None:
        """Use the currently selected entity as the shared neighbourhood focus."""
        self.graph_focus_usr = usr
        self.refresh_graph_appearances()

    def toggle_graph_expansion(self, key: str) -> None:
        """Toggle one core-approved container key in every reusable diagram."""
        if self.opened is None:
            return
        decision = self.view.expansion_decision(key)
        if decision is None or not decision.expandable:
            return
        self._expansion_initialized = True
        self._expansion_auto_expand = False
        self.expansion_state = self.expansion_state ^ {decision.key}
        self.refresh_graph_appearances()

    def collapse_all(self) -> None:
        """Reset all reusable diagrams together; safe before a project is open."""
        if self.opened is None:
            return
        self._expansion_initialized = True
        self._expansion_auto_expand = False
        self.expansion_state = frozenset()
        self.refresh_graph_appearances()

    def _fill_recent_menu(self) -> None:
        self.recent_menu.delete(0, tk.END)
        for path in self.config.known_projects:
            self.recent_menu.add_command(label=path, command=self._opener(Path(path)))

    def _opener(self, path: Path) -> Any:
        return lambda: self.open_project(path)

    def _build_panel(self) -> None:
        self.executable_bar = ttk.Frame(self.root)
        self.executable_bar.pack(fill=tk.X, pady=2)
        vertical = self.main_panes = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        vertical.pack(fill=tk.BOTH, expand=True)
        paned = ttk.PanedWindow(vertical, orient=tk.HORIZONTAL)
        vertical.add(paned, weight=4)
        view_host = ttk.Frame(paned)
        diagram_toolbar = ttk.Frame(view_host)
        diagram_toolbar.pack(fill=tk.X, padx=4, pady=2)
        self._build_graph_controls(diagram_toolbar)
        self.views = ttk.Notebook(view_host)
        self.views.pack(fill=tk.BOTH, expand=True)
        file_view = ttk.Frame(self.views)
        file_toolbar = ttk.Frame(file_view)
        file_toolbar.pack(fill=tk.X, padx=4, pady=2)
        self.canvas = tk.Canvas(file_view, background="white", cursor="fleur", highlightthickness=0, width=1050,
                                height=620)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.views.add(file_view, text="File View")
        self.call_view = call_view.CallViewCanvas(
            self.views, self.open_call_source, self.graph_actions, self.dispatch_graph_action,
            self.focus_graph_node)
        self.views.add(self.call_view.frame, text="Call View")
        self.class_view = class_view.ClassViewCanvas(
            self.views, self.open_editor, self.graph_actions, self.dispatch_graph_action,
            self.focus_graph_node)
        self.views.add(self.class_view.frame, text="Class View")
        self.mind_map_view = mind_map_view.MindMapCanvas(
            self.views, self.select_step, self.graph_actions, self.dispatch_graph_action,
            self.focus_graph_node, self.select_node)
        self.views.add(self.mind_map_view.frame, text="Mind Map")
        self.coverage_view = coverage_view.CoverageOverview(self.views, self.open_editor)
        self.views.add(self.coverage_view.frame, text="Coverage")
        self.issue_view = issue_view.IssueOverview(self.views, self.open_editor)
        self.views.add(self.issue_view.frame, text="Issues")
        paned.add(view_host, weight=4)
        side = ttk.Frame(paned, width=320)
        paned.add(side, weight=0)
        llm = ttk.LabelFrame(side, text="LLM")
        llm.pack(fill=tk.X, padx=4, pady=(4, 2))
        self.provider_field = provider_field.ProviderField(llm, self.providers, binary=self._default_binary(),
                                                           model=self.config.model)
        self.provider_field.frame.pack(fill=tk.X, padx=4, pady=4)
        self.provider_field.on_change = self._provider_changed
        self.side_views = ttk.Notebook(side)
        self.side_views.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        entities = ttk.Frame(self.side_views)
        self.side_views.add(entities, text="Entities")
        self.side_title = tk.StringVar(value="Entities")
        ttk.Label(entities, textvariable=self.side_title, anchor="w").pack(fill=tk.X, padx=4, pady=2)
        self.tree = ttk.Treeview(entities, columns=("kind", "line"), show="tree headings")
        self.tree.heading("kind", text="kind")
        self.tree.heading("line", text="line")
        self.tree.column("kind", width=80)
        self.tree.column("line", width=50)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-Button-1>", self.on_tree_double_click)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.source_editor = source_editor.SourceEditor(
            self.side_views, project=lambda: self.project, busy=lambda: self.panel.busy,
            saved=self._editor_saved, failed=lambda *args, **kwargs: self.recovery.handle_failure(*args, **kwargs))
        self.side_views.add(self.source_editor.frame, text="Source Editor")
        self.view = FileViewCanvas(self.canvas, self)
        self.view.build_zoom_controls(file_toolbar).pack(side=tk.RIGHT)
        self.panel = step_panel.StepPanel(vertical, lambda action: self.steps.action(action))
        vertical.add(self.panel.frame, weight=0)
        self.panel.on_details_visibility = self._resize_step_panel
        self._step_panel_resize_pending = False
        vertical.bind("<Configure>", lambda _event: self.panel._fit_collapsed())
        self._resize_step_panel()

    def _resize_step_panel(self) -> None:
        """Give space released by the review details back to the graph and editor."""
        if self._step_panel_resize_pending:
            return
        self._step_panel_resize_pending = True

        def resize() -> None:
            self._step_panel_resize_pending = False
            height = self.main_panes.winfo_height()
            if height > 1:
                position = max(180, height - self.panel.frame.winfo_reqheight() - 6)
                if abs(self.main_panes.sashpos(0) - position) > 1:
                    self.main_panes.sashpos(0, position)
        self.root.after_idle(resize)

    def _build_graph_controls(self, parent: Any) -> None:
        ttk.Label(parent, text="Filter:").pack(side=tk.LEFT)
        self.graph_filter_entry = ttk.Entry(parent, textvariable=self.graph_filter_var, width=20)
        self.graph_filter_entry.pack(side=tk.LEFT, padx=(2, 8))
        self.graph_filter_tooltip = tooltip.attach(
            self.graph_filter_entry,
            "Space-separated filters: name:, kind:, status:, covered: (recorded-test reachability), stale:, "
            "cluster:, namespace:, edge:. "
            "Plain text filters by name; clear the entry to show all nodes.")
        ttk.Label(parent, text="Neighborhood:").pack(side=tk.LEFT)
        self.neighborhood_spinbox = ttk.Spinbox(
            parent, from_=0, to=12, width=3, textvariable=self.neighborhood_depth_var,
            command=self.apply_graph_filter)
        self.neighborhood_spinbox.pack(side=tk.LEFT, padx=(2, 4))
        ttk.Label(parent, text="0=off").pack(side=tk.LEFT)
        self.neighborhood_tooltip = tooltip.attach(
            self.neighborhood_spinbox,
            "Dim nodes beyond this many graph edges from the currently selected entity; 0 disables dimming.")
        self.collapse_all_button = ttk.Button(parent, text="Collapse all", command=self.collapse_all)
        self.collapse_all_button.pack(side=tk.RIGHT, padx=(8, 0))

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self.root)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.reload_button = ttk.Button(bar, text="Reload project", command=self.reload)
        self.reload_button.pack(side=tk.LEFT, padx=(4, 6), pady=2)
        self.reload_button.state(["disabled"])
        self.reload_tooltip = tooltip.attach(
            self.reload_button, "Reload source and project metadata after external changes (" + ACCELERATOR
            + "R). Unsaved source-editor changes are kept. Available when no operation is running.")
        self.reread_spec_button = ttk.Button(bar, text="Reread specification", command=self.reread_specification)
        self.reread_spec_button.pack(side=tk.LEFT, padx=(0, 6), pady=2)
        tooltip.attach(self.reread_spec_button, "Read .icoda/specification.json again, update Coverage, "
                       "and show it in the specification editor. Unsaved edits require confirmation.")
        ttk.Label(bar, textvariable=self.language_var, anchor="e").pack(side=tk.RIGHT, padx=6, pady=2)
        self.status_progress = ttk.Progressbar(bar, mode="indeterminate", length=110)
        ttk.Label(bar, textvariable=self.status, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6,
                                                                  pady=2)

    def _set_analysing(self, running: bool) -> None:
        """A moving bar in the status line while the analysis child runs; the step panel waits as well.

        A step that is already running keeps its own busy state: its activity stays visible and its buttons come
        back only when the step ends, not when a reload it did not start finishes.
        """
        if running:
            self.status_progress.pack(side=tk.RIGHT, padx=6)
            self.status_progress.start(40)
            if not self.panel.busy:
                self.panel.set_busy(True, "analysing the project")
                self._panel_busy_by_analysis = True
        else:
            self.status_progress.stop()
            self.status_progress.pack_forget()
            if self._panel_busy_by_analysis:
                self._panel_busy_by_analysis = False
                self.panel.set_busy(False)

    # -- projects ---------------------------------------------------------------------------

    def ask_open_project(self) -> None:
        chosen = filedialog.askdirectory(title="Open project directory")
        if chosen:
            self.open_project(Path(chosen))

    def open_project(self, path: Path) -> None:
        if self.recovery.busy or self.executables.running:
            return
        resolved = Path(path).expanduser().resolve()
        if self.project != resolved:
            if not self.source_editor.clear():
                return
            self.executables.clear()
            self._editor_refresh_pending = None
            self.recovery.reset()
            self.steps.proposal = None
            self.steps.approach = None
            self.steps.confirmed_signature_proposal = None
            self.expansion_state = frozenset()
            self._expansion_initialized = False
            self._expansion_auto_expand = True
            self.graph_focus_usr = None
            self._source_snapshot = None
            self.panel.show(None)
        self.project = resolved
        self.recovery.set_project(self.project)
        self.language_var.set(f"Language: {analysis.detect_language(self.project)}")
        self.root.title(f"ICODA — {self.project.name}")
        self.status.set(f"Analysing {self.project} …")
        session.log_event("opening: analysis started", self.project)
        self.panel.set_project_facts(True, self.panel.has_model, self._provider_ready())
        self._set_analysing(True)
        self._pending_analyses += 1
        threading.Thread(target=self._analyse, args=(self.project,), daemon=True).start()
        if self._pending_analyses == 1:  # one poll loop serves every analysis in flight
            self.root.after(100, self._poll)

    def ask_new_project(self) -> None:
        chosen = filedialog.askdirectory(title="New project: choose an empty directory", mustexist=False)
        if chosen:
            self.new_project(Path(chosen))

    def new_project(self, path: Path) -> None:
        """Phase 0: create ``.icoda/`` and open the specification editor; saving it writes the step 0 skeleton."""
        if self.recovery.busy or self.executables.running:
            return
        if not self.source_editor.clear():
            return
        self.executables.clear()
        self._editor_refresh_pending = None
        self.recovery.reset()
        self.steps.proposal = None
        self.steps.approach = None
        self.steps.confirmed_signature_proposal = None
        self.project = Path(path).expanduser().resolve()
        self.recovery.set_project(self.project)
        self._source_snapshot = None
        self.project.mkdir(parents=True, exist_ok=True)
        persistence.ProjectStore(self.project).ensure()
        self.panel.set_phase(persistence.ProjectPhase.SPECIFICATION)
        self.panel.set_project_facts(True, False, self._provider_ready())
        self.root.title(f"ICODA — {self.project.name}")
        self.status.set(f"New project {self.project}: write the specification and save it")
        self.edit_specification()

    def edit_specification(self) -> None:
        if self.project is None:
            messagebox.showinfo("ICODA", "Open or create a project first.")
            return
        editor = self._current_spec_editor()
        if editor is not None:
            self.spec_editor = editor
            editor.window.deiconify()
            editor.window.lift()
            return
        store = persistence.ProjectStore(self.project)
        if store.specification_path.is_file():
            spec = specification.load(store.specification_path)
        else:
            spec = specification.default_specification(self.project.name, analysis.detect_language(self.project))
        self._open_spec_editor(spec)

    def _current_spec_editor(self) -> spec_editor.SpecificationEditor | None:
        editor = self._spec_editors.get(self.project) if self.project is not None else None
        return editor if editor is not None and not editor.closed else None

    def _open_spec_editor(self, spec: specification.Specification) -> None:
        assert self.project is not None
        project = self.project

        def save(value: specification.Specification) -> None:
            if self.project != project:
                raise ValueError(f"Open {project} again before saving its specification. Your edits are kept.")
            self._save_specification(value)

        def reread() -> None:
            if self.project == project:
                self.reread_specification()

        self.spec_editor = spec_editor.SpecificationEditor(
            self.root, spec, save, title=f"Specification — {project.name}", on_reread=reread)
        self._spec_editors[project] = self.spec_editor
        self._update_reload_button()

    def reread_specification(self) -> None:
        """Refresh the saved specification without regenerating code or replacing unsaved edits silently."""
        if self.project is None or self.panel.busy:
            return
        project = self.project
        path = persistence.ProjectStore(project).specification_path

        def read() -> specification.Specification:
            try:
                spec = specification.load(path)
                problems = specification.validate(spec)
                if problems:
                    raise ValueError("; ".join(problems[:3]))
                return spec
            except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
                raise ValueError(f"Cannot reread the specification at {path}: {exc}. "
                                 "The saved file and editor contents have been preserved.") from exc

        def apply(spec: specification.Specification) -> None:
            if self.project != project:
                return
            editor = self._current_spec_editor()
            if editor is not None:
                self.spec_editor = editor
                if not editor.confirm_reread():
                    self.status.set("Specification reread cancelled — unsaved edits kept")
                    return
                editor.load(spec)
                editor.problems.set("reread from disk")
                editor.window.deiconify()
                editor.window.lift()
            else:
                self._open_spec_editor(spec)
            if self.displayed is not None and self.displayed.root == project:
                records = steplog.StepLog(persistence.ProjectStore(project).steps_path).records()
                self.coverage_view.show(self.displayed.model, records,
                                        self.executable_coverage(self.displayed.model, records), spec)
            self.status.set("Specification reread from .icoda/specification.json")
            session.log_event("specification reread", project)

        try:
            spec = read()
        except ValueError as exc:
            self.recovery.handle_failure(exc, retry=self.reread_specification, repair=read, repaired=apply)
            return
        apply(spec)

    def _save_specification(self, spec: specification.Specification) -> None:
        """Write ``.icoda/specification.json``; for a project without code, write the skeleton (step 0)."""
        assert self.project is not None
        store = persistence.ProjectStore(self.project)
        store.ensure()
        specification.save(store.specification_path, spec)
        session.log_event("specification saved", self.project)
        if (self.project / "CMakeLists.txt").exists() or self._is_existing_specification_edit():
            self._reload_after_specification_save()
            return
        written = generator.write_skeleton(self.project, self.project.name, spec["code_profile"])
        phases.transition(store, persistence.ProjectPhase.ARCHITECTURE)
        self.panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
        session.log_event(f"skeleton written: {written}", self.project)
        if messagebox.askyesno("ICODA", f"Specification saved and the project skeleton written ({len(written)} "
                               "files).\n\nBuild it now? ICODA runs the build, then analyses the project. "
                               "(Later: Project ▸ Build.)"):
            self.build_project()
        else:
            self.open_project(self.project)

    # -- building ---------------------------------------------------------------------------

    def build_project(self) -> None:
        """Project ▸ Build: run the project's build gate in the background, then reload the analysis."""
        if self.project is None:
            messagebox.showinfo("ICODA", "Open or create a project first.")
            return
        if self.panel.busy:
            return
        project = self.project

        def work() -> steps.BuildResult:
            result = steps.build_project(project)
            if self.steps.cancel_requested:
                raise steps.StepCancelled()
            return result

        def done(result: steps.BuildResult) -> None:
            if result.ok:
                session.log_event("build passed (Project ▸ Build)", project)
                self.status.set("build passed — analysing the project …")
                self.open_project(project)
            else:
                session.log_event("build failed (Project ▸ Build):\n" + result.output, project)
                runner = self.steps._ensure_runner()
                self.recovery.handle_failure("Build failed.\n" + result.output, retry=self.build_project,
                    repair=lambda: runner.repair_project(result.output),
                    repaired=self.steps._show_proposal)

        self.steps.run(work, done, "building the project", cancellable=True)

    def edit_test_command(self) -> None:
        """Project ▸ Test Command…: the command that gates every proposal, kept in .icoda/state.json."""
        if self.project is None:
            messagebox.showinfo("ICODA", "Open or create a project first.")
            return
        store = persistence.ProjectStore(self.project)
        state = store.load_state()
        text = simpledialog.askstring(
            "Test command", "The command that runs the project's tests. Every proposal must pass it.\n"
            "Example: ctest --preset debug --output-on-failure", initialvalue=shlex.join(state.test_command),
            parent=self.root)
        if text is None:
            return
        command = tuple(shlex.split(text))
        store.save_state(replace(state, test_command=command))
        session.log_event(f"test command set to {command}", self.project)
        self.status.set("test command set to: " + (shlex.join(command) or "(none — tests are skipped)"))

    def reload(self) -> None:
        """Refresh external changes without interrupting work or discarding editor changes."""
        if self.project is None or self.panel.busy:
            return
        editor = self.source_editor
        if editor.document is not None and editor.document.root == self.project.resolve():
            editor.refresh()
        self.open_project(self.project)

    def _update_reload_button(self) -> None:
        enabled = self.project is not None and not self.panel.busy
        self.reload_button.state(["!disabled"] if enabled else ["disabled"])
        self.reread_spec_button.state(["!disabled"] if enabled else ["disabled"])
        self.executables.update_controls()
        for project, editor in self._spec_editors.items():
            if not editor.closed:
                editor_enabled = enabled and project == self.project
                editor.reread_button.state(["!disabled"] if editor_enabled else ["disabled"])

    def _refresh_external_edits(self, _event: Any) -> None:
        """Re-analyse externally edited source when the application regains focus (not while a step runs)."""
        if self.project is None or self.opened is None or self._source_snapshot is None or self.panel.busy:
            return
        current = source_watch.snapshot_files(self.project, self.opened.model.files)
        if not source_watch.changed_files(self._source_snapshot, current):
            return
        self._source_snapshot = current
        self.reload()

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
        self._pending_analyses = max(0, self._pending_analyses - 1)
        if self._pending_analyses:
            self.root.after(100, self._poll)
        else:
            self._set_analysing(False)
        if isinstance(result, Exception):
            self.recovery.handle_failure(result, retry=self.reload,
                                         repair=self._recover_analysis, repaired=self.show)
        else:
            self.show(result)

    def _recover_analysis(self) -> session.OpenedProject:
        """Refresh the compile database and derived model once before reporting an analysis error."""
        assert self.project is not None
        built = steps.build_project(self.project)
        if not built.ok:
            raise steps.StepError("Analysis recovery could not build the project:\n" + built.output)
        return session.open_project(self.project, self.config)

    def _callback_error(self, _kind: type[BaseException], error: BaseException, trace: Any) -> None:
        session.log_event("UI callback failed:\n" + "".join(traceback.format_exception(
            type(error), error, trace)), self.project)
        # An unknown callback may have been a save or another mutation: diagnosing it is safe,
        # but rebuilding the view would not prove that the failed operation succeeded.
        self.recovery.handle_failure(str(error), retry=self.reload)

    def show(self, opened: session.OpenedProject) -> None:
        """Present an opened project: canvas, status bar, recent list, configuration."""
        self.opened = opened
        self.project = opened.root
        self.recovery.set_project(self.project)
        session.log_event("showing: model ready, updating the window", opened.root)
        self.language_var.set(f"Language: {analysis.detect_language(opened.root)}")
        store = persistence.ProjectStore(opened.root)
        state = implementation_queue.ensure_state(store, opened.model)
        self.panel.set_phase(state.phase)
        self.panel.set_project_facts(True, bool(opened.model.files), self._provider_ready())
        target = implementation_queue.target_usr(state)
        grouping_refusal = ""
        if state.implementation_grouping == grouping.Mode.FEW_LINE_GROUP.value:
            profile = specification.load(store.specification_path).get("code_profile", {}) \
                if store.specification_path.is_file() \
                else specification.default_code_profile(analysis.detect_language(opened.root))
            decision = grouping.derive(
                implementation_queue.scope_targets(opened.model, state), opened.model, profile)
            batch = tuple(item.usr for item in decision.entities)
            grouping_refusal = decision.refusal_reason
        else:
            batch = tuple(implementation_queue.next_batch(
                opened.model, state, state.implementation_batch_size))
        display_target = batch[0] if batch else target
        entity = opened.model.entities.get(display_target) if display_target is not None else None
        batch_names = tuple(opened.model.entities[usr].qualified_name if usr in opened.model.entities else usr
                            for usr in batch)
        self.panel.set_implementation_queue(entity.qualified_name if entity is not None else display_target,
                                            implementation_queue.remaining(state), state.approved_approach,
                                            state.implementation_batch_size, batch_names,
                                            state.implementation_scope,
                                            target is not None and target == state.implementation_override,
                                            state.auto_approve, state.implementation_grouping,
                                            grouping_refusal)
        self.executables.show(opened.root, opened.model)
        try:
            self.show_executable()
        except Exception as exc:  # noqa: BLE001  (rebuild the view once before displaying a drawing failure)
            session.log_event("drawing failed:\n" + traceback.format_exc(), opened.root)
            self.recovery.handle_failure(exc, retry=self.reload,
                                         repair=self._recover_analysis, repaired=self.show)
            return
        assert self.displayed is not None
        session.log_event(f"drawn: canvas {self.canvas.winfo_width()}x{self.canvas.winfo_height()}, "
                          f"{len(self.displayed.layout.nodes)} nodes, scale {self.view.scale:.3f}, offset {self.view.offset}",
                          opened.root)
        libclang = opened.libclang or "libclang: none found"
        notes = ("  |  " + "; ".join(opened.messages)) if opened.messages else ""
        self.status.set(f"{opened.root.name}: {self.displayed.summary}  |  {libclang}{notes}")
        self.config.save(self.config_path)
        self._fill_recent_menu()
        self.side_title.set("Entities")
        self.tree.delete(*self.tree.get_children())
        self._restore_provider(opened.root)
        if self.executables.choices and self.executables.selected is None:
            self.status.set("Select an example / executable to display its code views.")
        self._source_snapshot = source_watch.snapshot_files(opened.root, opened.model.files)
        if not self.panel.details_visible:
            self._resize_step_panel()
        session.log_event("shown: window ready", opened.root)

    def executable_model(self, model: DerivedModel) -> DerivedModel:
        """Keep workflow analysis complete while every code view uses the selected executable."""
        if not self.executables.choices and not executables.entries(model):
            return model  # Library-only projects have no executable to select.
        return executables.scope_model(model, self.executables.selected, root=self.project)

    def show_executable(self) -> None:
        """Repaint all code views from one executable projection, preserving the active tab."""
        if self.opened is None:
            return
        opened = self.opened
        store = persistence.ProjectStore(opened.root)
        model = self.executable_model(opened.model)
        clustering = clusters.cluster_files(model, store.load_layout())
        layout = views.layout_file_view(model, clustering)
        self.displayed = session.OpenedProject(opened.root, model, clustering, layout,
                                               opened.libclang, opened.messages)
        self._call_source_root = opened.root
        self.graph_focus_usr = None
        self.side_title.set("Entities")
        self.tree.delete(*self.tree.get_children())
        document = self.source_editor.document
        if document is not None and document.relative not in model.files and not self.source_editor.dirty:
            self.source_editor.clear()
        self.view.show(layout)
        self.call_view.show(model)
        self.class_view.show(model)
        log = steplog.StepLog(store.steps_path)
        self.mind_map_view.show(model, log, store, clustering)
        records = log.records()
        coverage = self.executable_coverage(model, records)
        self.refresh_graph_appearances(model, store.load_state(), records, coverage)
        spec = specification.load(store.specification_path) if store.specification_path.is_file() else {}
        self.coverage_view.show(model, records, coverage, spec)
        self.issue_view.show(model, log)

    def executable_coverage(self, model: DerivedModel, records: list[steplog.StepRecord]) -> coverage_index.CoverageIndex:
        """Keep recorded test evidence while restricting the displayed callable rows."""
        source = self.opened.model if self.opened is not None else model
        complete = coverage_index.build_index(source, records)
        entries = tuple(entry for entry in complete.entries if entry.usr in model.entities)
        return coverage_index.CoverageIndex(entries, tuple(entry.usr for entry in entries if not entry.covered))

    def show_proposal_calls(self, proposal: steps.Proposal) -> None:
        if proposal.model is not None:
            self.call_view.show_proposal(self.executable_model(proposal.model), proposal.delta)
            self._call_source_root = proposal.worktree

    def _reload_after_specification_save(self) -> None:
        """Publish an edited truth through the ordinary asynchronous analysis/show path."""
        self.status.set("specification saved")
        if self.opened is not None and self.opened.root == self.project:
            self.open_project(self.project)

    def _is_existing_specification_edit(self) -> bool:
        return (
            self.opened is not None
            and self.opened.root == self.project
            and self.panel.phase_var.get() != persistence.ProjectPhase.SPECIFICATION.value
        )

    def refresh_graph_appearances(
        self, model: DerivedModel | None = None, state: persistence.ProjectState | None = None,
        records: list[steplog.StepRecord] | None = None,
        coverage: coverage_index.CoverageIndex | None = None,
    ) -> None:
        """Re-derive once and publish the same frozen mapping to all four diagrams."""
        if model is None:
            model = self.displayed.model if self.displayed is not None else None
        if model is None or self.project is None:
            return
        model = self.executable_model(model)
        store = persistence.ProjectStore(self.project)
        state = state or store.load_state()
        records = records if records is not None else steplog.StepLog(store.steps_path).records()
        coverage = coverage or self.executable_coverage(model, records)
        appearances = node_status.derive(model, state, records, coverage)
        clustering = self.displayed.clustering if self.displayed is not None else clusters.cluster_files(model)
        cluster_by_file = {file: cluster.id for cluster in clustering.clusters for file in cluster.files}
        cluster_names = {cluster.id: cluster.name for cluster in clustering.clusters}
        graph = graph_filter.project_graph(model, cluster_by_file, cluster_names)
        criteria = graph_filter.parse(str(self.graph_filter_var.get() or ""))
        try:
            depth = max(0, int(self.neighborhood_depth_var.get() or 0))
        except (TypeError, ValueError):
            depth = 0
        decisions = graph_filter.derive(
            model, graph, appearances, criteria,
            focus_usr=self.graph_focus_usr, neighborhood_depth=depth)
        expanded = expansion.derive(model, graph, decisions, appearances, self.expansion_state)
        if not self._expansion_initialized or self._expansion_auto_expand:
            self.expansion_state = frozenset(
                key for key, decision in expanded.decisions.items() if decision.expandable)
            expanded = expansion.derive(model, graph, decisions, appearances, self.expansion_state)
            self._expansion_initialized = True
        else:
            self.expansion_state = expanded.expanded
        for canvas in self._diagram_canvases():
            canvas.set_node_appearances(
                appearances, coverage_mode=bool(self.coverage_mode_var.get()),
                globally_stale=model.stale, stale_reason=model.stale_reason)
            canvas.set_graph_filter(decisions, filter_active=criteria.active,
                                    neighborhood_depth=depth)
        for canvas in self._expansion_canvases():
            canvas.set_expansion(expanded, self.toggle_graph_expansion)

    def _diagram_canvases(self) -> tuple[Any, ...]:
        return self.view, self.call_view, self.class_view, self.mind_map_view

    def _expansion_canvases(self) -> tuple[Any, ...]:
        return self.view, self.call_view, self.class_view

    def show_after_step(self, model: DerivedModel | None) -> None:
        """Present an approved proposal's parsed model without starting a project analysis reload."""
        if model is None or self.opened is None:
            self.reload()
            return
        store = persistence.ProjectStore(self.opened.root)
        steplog.apply_statuses(model, steplog.StepLog(store.steps_path))
        clustering = clusters.cluster_files(model, store.load_layout())
        layout = views.layout_file_view(model, clustering)
        self.show(session.OpenedProject(
            self.opened.root, model, clustering, layout, self.opened.libclang, self.opened.messages))

    # -- provider ---------------------------------------------------------------------------

    def _default_binary(self) -> str:
        """The command of the provider chosen in the user configuration, if it is still listed."""
        try:
            return agent.find_provider(self.providers, self.config.provider).command
        except KeyError:
            return ""

    def _restore_provider(self, root: Path) -> None:
        """Select the binary and model saved for the project in ``.icoda/ui.json``."""
        saved = persistence.ProjectStore(root).load_ui().get("provider") or {}
        if saved.get("binary"):
            self.provider_field.set(saved["binary"], saved.get("model", ""))

    def _provider_changed(self) -> None:
        """Remember the selection per project (with the binary path) and as the default for new projects."""
        selection = self.provider_field.selection()
        if selection.provider_id:
            self.config.provider, self.config.model = selection.provider_id, selection.model
            self.config.save(self.config_path)
        if self.opened is not None:
            store = persistence.ProjectStore(self.opened.root)
            store.save_ui({**store.load_ui(), "provider": selection.to_dict()})
        if hasattr(self, "panel"):
            self.panel.set_project_facts(self.project is not None, self.panel.has_model, self._provider_ready())
        if hasattr(self, "recovery"):
            self.recovery.follow_provider()

    def _provider_ready(self) -> bool:
        """A known agent is chosen and its command-line tool is installed."""
        selection = self.provider_field.selection()
        if not selection.provider_id:
            return False
        try:
            provider = agent.find_provider(self.providers, selection.provider_id)
        except KeyError:
            return False
        return agent.binary_available(provider, selection.binary or None)

    # -- nodes ------------------------------------------------------------------------------

    def graph_actions(self, node_id: str) -> graph_canvas.NodeActionContext | None:
        """Return core-derived history/test data and current controller enablement for a diagram node."""
        if self.displayed is None or self.project is None or self.mind_map_view.tree is None:
            return None
        model, tree = self.displayed.model, self.mind_map_view.tree
        key = node_id if node_id.startswith(("entity:", "file:", "cluster:")) else \
            f"entity:{node_id}" if node_id in model.entities else f"file:{node_id}"
        node = tree.node_map().get(key)
        if node is None:
            return graph_canvas.NodeActionContext(node_id)
        store = persistence.ProjectStore(self.project)
        state = store.load_state()
        target = node.usr if node.usr in model.entities else ""
        source = self.opened.model if self.opened is not None else model
        tests = test_selection.select_tests(source, steplog.StepLog(store.steps_path), target) if target else ()
        callable_target = target in model.entities and model.entities[target].kind in CALLABLE_KINDS
        cluster_id = key.removeprefix("cluster:") if key.startswith("cluster:") else ""
        file_path = key.removeprefix("file:") if key.startswith("file:") else ""
        cluster = next((item for item in self.displayed.clustering.clusters if item.id == cluster_id), None)
        layout = store.load_layout()
        enabled = self.panel.enabled_actions
        return graph_canvas.NodeActionContext(
            node_id, node.introduced_iteration, tests, node.usr or node.file or node.id,
            target, "propose" in enabled and state.phase == persistence.ProjectPhase.ARCHITECTURE,
            callable_target and implementation_queue.can_override(model, state, target)
            and bool({"propose_approach", "propose"} & enabled),
            not self.panel.busy,
            cluster_id,
            clusters.cluster_is_pinned(layout, self.displayed.clustering, cluster_id) if cluster_id else False,
            cluster.name if cluster is not None else "",
            file_path,
            tuple(sorted(item.id for item in self.displayed.clustering.clusters)) if file_path else (),
        )

    def dispatch_graph_action(self, action: str, context: graph_canvas.NodeActionContext) -> None:
        """Route the shared graph menu through step history or the existing step controller."""
        if self.project is None or self.opened is None or self.displayed is None:
            return
        if action == graph_canvas.SHOW_STEP and context.introducing_iteration is not None:
            self.select_step(context.introducing_iteration)
        elif action == graph_canvas.PROPOSE_HERE:
            self.steps.action("propose_here", context.focus)
        elif action == graph_canvas.IMPLEMENT_HERE:
            self.steps.action("implement_here", context.target_usr)
        elif action == graph_canvas.RUN_TESTS:
            self.steps.action("run_tests", context.tests)
        elif action == graph_canvas.PIN_CLUSTER:
            self._apply_cluster_layout(clusters.pin_cluster(
                persistence.ProjectStore(self.project).load_layout(), self.displayed.clustering, context.cluster_id))
        elif action == graph_canvas.UNPIN_CLUSTER:
            self._apply_cluster_layout(clusters.unpin_cluster(
                persistence.ProjectStore(self.project).load_layout(), context.cluster_id))
        elif action == graph_canvas.RENAME_CLUSTER:
            name = simpledialog.askstring(
                "Rename cluster", "Cluster name:", initialvalue=context.cluster_name, parent=self.root)
            if name is not None:
                self._apply_cluster_layout(clusters.rename_cluster(
                    persistence.ProjectStore(self.project).load_layout(), context.cluster_id, name))
        elif action == graph_canvas.PIN_FILE_TO_CLUSTER:
            self._apply_cluster_layout(clusters.pin_file(
                persistence.ProjectStore(self.project).load_layout(), self.displayed.clustering,
                context.file_path, context.target_cluster_id))

    def _apply_cluster_layout(self, decision: clusters.LayoutDecision) -> None:
        """Persist a core-derived cluster edit and repaint every view without re-analysing source."""
        if not decision.changed or self.project is None or self.opened is None:
            return
        layout = decision.to_layout()
        persistence.ProjectStore(self.project).save_layout(layout)
        clustering = clusters.cluster_files(self.opened.model, layout)
        self.show(session.OpenedProject(
            self.opened.root, self.opened.model, clustering,
            views.layout_file_view(self.opened.model, clustering), self.opened.libclang,
            self.opened.messages))

    def describe_node(self, node_id: str) -> str:
        if self.displayed is None:
            return node_id
        if node_id.startswith("external:"):
            library = node_id.split(":", 1)[1]
            names = self.displayed.model.externals[library].names
            return f"{library}\n" + ", ".join(names[:12]) + (" …" if len(names) > 12 else "")
        info = self.displayed.model.files.get(node_id)
        entities = self.displayed.model.entities_in(node_id)
        lines = [node_id, f"{info.unit}{' module ' + info.module if info and info.module else ''}" if info else ""]
        lines.append(f"{len(entities)} entities")
        if info and info.errors:
            lines.append(f"errors: {info.errors[0]}")
        return "\n".join(line for line in lines if line)

    def select_node(self, node_id: str) -> None:
        """A file/entity click opens its source and retains the file's entity list in the adjacent tab."""
        if self.displayed is None or node_id.startswith(("external:", "cluster:")):
            return
        usr = node_id.removeprefix("entity:")
        selected_entity = self.displayed.model.entities.get(usr)
        node_id = selected_entity.file if selected_entity is not None else node_id.removeprefix("file:")
        if node_id not in self.displayed.model.files:
            return
        self.focus_graph_node(usr if selected_entity is not None else None)
        self.side_title.set(node_id)
        self.tree.delete(*self.tree.get_children())
        entities = sorted(self.displayed.model.entities_in(node_id), key=lambda e: e.line)
        parents = {e.usr: e for e in entities}
        for entity in entities:
            parent = entity.parent if entity.parent in parents else ""
            label = entity.name + (f"  {entity.signature}" if entity.signature else "")
            self.tree.insert(parent, tk.END, iid=entity.usr, text=label, values=(entity.kind.value, entity.line),
                             open=True)
        self.open_editor(node_id, selected_entity.line if selected_entity is not None else 1)

    def on_tree_select(self, _event: Any) -> None:
        """A selected function becomes the root of the Call View."""
        if self.opened is None:
            return
        for usr in self.tree.selection():
            if usr in self.opened.model.entities:
                entity = self.opened.model.entities[usr]
                if entity.kind in CALLABLE_KINDS:
                    self.call_view.set_root(usr)
                self.focus_graph_node(usr)
                self.open_editor(entity.file, entity.line)

    def on_tree_double_click(self, _event: Any) -> None:
        if self.opened is None:
            return
        for usr in self.tree.selection():
            entity = self.opened.model.entities.get(usr)
            if entity is not None:
                self.open_editor(entity.file, entity.line)

    def open_editor(self, file: str, line: int = 1, *, root: Path | None = None) -> None:
        selected_root = root or self.project
        if selected_root is None or file.startswith(("external:", "cluster:")):
            return
        if self.opened is not None:
            entity = self.opened.model.entities.get(file.removeprefix("entity:"))
            if entity is not None:
                file, line = entity.file, entity.line
        file = file.removeprefix("file:")
        if self.source_editor.open_file(selected_root, file, line):
            self.side_views.select(self.source_editor.frame)

    def open_call_source(self, file: str, line: int = 1) -> None:
        self.open_editor(file, line, root=self._call_source_root or self.project)

    def _editor_saved(self, document: source_edit.Document) -> None:
        self._source_changed(document.root)

    def _source_changed(self, root: Path) -> None:
        """Refresh analysis and invalidate checks after editor saves or Prompt edits."""
        proposal = self.steps.proposal
        if proposal is not None and root == proposal.worktree.resolve():
            proposal.build, proposal.test = steps.BuildResult(), steps.TestResult()
            proposal.error = ""
            self.steps.confirmed_signature_proposal = None
            self.panel.show(proposal)
            self.status.set("Candidate files changed. Rebuild the candidate before approval.")
        elif self.project is not None and root == self.project.resolve():
            if proposal is not None:
                proposal.error = "Project source changed. Commit manual edits and request a new proposal."
                self.panel.show(proposal)
            self._editor_refresh_pending = self.project
            self.root.after(250, self._refresh_editor_save)
            self.status.set("Project files changed — refreshing analysis; changes remain uncommitted.")

    def _refresh_editor_save(self) -> None:
        if self._editor_refresh_pending != self.project or self._editor_refresh_pending is None:
            return
        if self.panel.busy:
            self.root.after(250, self._refresh_editor_save)
            return
        self._editor_refresh_pending = None
        self.reload()

    def close(self) -> None:
        if self.source_editor.confirm_saved():
            self.executables.stop()
            self.root.destroy()

    def select_step(self, iteration: int) -> None:
        """Show the effective recorded step selected in the mind map."""
        if self.project is None:
            return
        records = steplog.StepLog(persistence.ProjectStore(self.project).steps_path).records()
        matching = [record for record in records if record.number == iteration
                    and record.round != steplog.APPROACH_ROUND
                    and record.decision in ("approved", "manual")]
        if matching:
            self.panel.show_step(matching[-1])


def parse_args(argv: list[str]) -> Path | None:
    """Return the project directory given on the command line, or None."""
    if len(argv) > 1:
        raise SystemExit(f"usage: icoda.py [project-directory]  (ICODA {__version__})")
    return Path(argv[0]) if argv else None


def main(argv: list[str] | None = None) -> int:
    project = parse_args(sys.argv[1:] if argv is None else argv)
    root = tk.Tk()
    app = App(root, project, watchdog=True)
    if project is None and app.config.last_project and Path(app.config.last_project).is_dir():
        app.open_project(Path(app.config.last_project))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
