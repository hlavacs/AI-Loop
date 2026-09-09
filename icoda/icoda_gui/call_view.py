"""The Call View: the function-level call graph from a root, one column per call depth.

Functions are boxes coloured by status; a proposal's new entities get a green outline and changed ones an orange
outline; the path from the root to the selected function is drawn thick; a call back towards the root (recursion)
is drawn as a loop. Zoom, pan, hover and double click behave as in the File View.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from icoda_core import views
from icoda_core.model import DerivedModel
from icoda_gui import zoom_controls

BOX_WIDTH, BOX_HEIGHT = 200.0, 30.0
ADDED, CHANGED = "#2ca02c", "#ff7f0e"


class CallViewCanvas:
    """Toolbar (root, depth, callers) and canvas; ``show`` lays out a model, ``show_proposal`` a proposal's delta."""

    def __init__(self, parent: Any, open_editor: Callable[[str, int], None]) -> None:
        self.frame = ttk.Frame(parent)
        self.open_editor = open_editor
        self.model: DerivedModel | None = None
        self.layout: views.CallViewLayout | None = None
        self.root_usr: str | None = None
        self.selected: str | None = None
        self.added: set[str] = set()
        self.changed: set[str] = set()
        self.scale, self.fit_scale, self.offset, self.user_zoomed = 1.0, 1.0, (0.0, 0.0), False
        self.item_nodes: dict[int, str] = {}
        self.drag_start: tuple[int, int] | None = None
        self.dragged = False
        self.depth_var = tk.IntVar(value=3)
        self.callers_var = tk.BooleanVar(value=False)
        self.root_var = tk.StringVar(value="")
        self.hover_var = tk.StringVar(value="")
        self._build_toolbar()
        self.canvas = tk.Canvas(self.frame, background="white", cursor="fleur", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        for event, handler in (("<MouseWheel>", self.on_wheel), ("<Button-4>", self.on_wheel),
                               ("<Button-5>", self.on_wheel), ("<ButtonPress-1>", self.on_press),
                               ("<B1-Motion>", self.on_drag), ("<ButtonRelease-1>", self.on_release),
                               ("<ButtonPress-2>", self.on_press), ("<B2-Motion>", self.on_drag),
                               ("<ButtonRelease-2>", self.on_release),
                               ("<Double-Button-1>", self.on_double_click), ("<Motion>", self.on_motion),
                               ("<Configure>", self.on_resize)):
            self.canvas.bind(event, handler)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.frame)
        bar.pack(fill=tk.X, padx=4, pady=2)
        root_row = ttk.Frame(bar)
        root_row.pack(fill=tk.X)
        ttk.Label(root_row, text="Root:").pack(side=tk.LEFT)
        zoom, zoom_widgets = zoom_controls.build(
            root_row,
            zoom_out=lambda: self.zoom(zoom_controls.ZOOM_OUT),
            fit=self.fit,
            reset=self.reset_zoom,
            zoom_in=lambda: self.zoom(zoom_controls.ZOOM_IN),
        )
        zoom.pack(side=tk.RIGHT)
        ttk.Label(root_row, textvariable=self.root_var, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True,
                                                                          padx=(2, 0))
        controls = ttk.Frame(bar)
        controls.pack(fill=tk.X, pady=(2, 0))
        from_main = ttk.Button(controls, text="From main", command=self.from_main)
        depth_label = ttk.Label(controls, text="Depth:")
        depth = ttk.Spinbox(controls, from_=1, to=12, width=3, textvariable=self.depth_var,
                            command=self.controls_changed)
        callers = ttk.Checkbutton(controls, text="callers", variable=self.callers_var,
                                  command=self.controls_changed)
        from_main.pack(side=tk.LEFT)
        depth_label.pack(side=tk.LEFT, padx=(10, 2))
        depth.pack(side=tk.LEFT)
        callers.pack(side=tk.LEFT, padx=10)
        ttk.Label(controls, textvariable=self.hover_var, anchor="w", foreground="#555555").pack(side=tk.LEFT,
                                                                                                  fill=tk.X,
                                                                                                  expand=True)
        self.toolbar_controls = {"from-main": from_main, "depth-label": depth_label, "depth": depth,
                                 "callers": callers, **zoom_widgets}

    # -- state ----------------------------------------------------------------------------

    def show(self, model: DerivedModel, root: str | None = None, added: set[str] | None = None,
             changed: set[str] | None = None) -> None:
        self.model = model
        self.added, self.changed = added or set(), changed or set()
        self.root_usr = root or views.default_root(model)
        self.user_zoomed = False
        self.relayout()

    def show_proposal(self, model: DerivedModel, delta: Any) -> None:
        """The proposal's model with its new entities outlined green and changed ones orange."""
        self.show(model, None, {e.usr for e in delta.added}, {e.usr for e in delta.changed})

    def set_root(self, usr: str) -> None:
        if self.model is not None and usr in self.model.entities:
            self.root_usr, self.user_zoomed = usr, False
            self.relayout()

    def select(self, usr: str | None) -> None:
        self.selected = usr
        self.relayout()

    def from_main(self) -> None:
        if self.model is not None:
            self.root_usr, self.user_zoomed = views.default_root(self.model), False
            self.relayout()

    def controls_changed(self) -> None:
        self.user_zoomed = False
        self.relayout()

    def relayout(self) -> None:
        """Lay the graph out again; fit it unless the developer has zoomed or panned."""
        if self.model is None or self.root_usr is None:
            self.layout = None
            self.canvas.delete("all")
            return
        self.layout = views.layout_call_view(self.model, self.root_usr, int(self.depth_var.get() or 3),
                                             bool(self.callers_var.get()), self.selected)
        root = self.layout.nodes[self.root_usr]
        self.root_var.set(root.label + (" (callers)" if self.callers_var.get() else ""))
        if self.user_zoomed:
            self.redraw()
        else:
            self.fit()

    # -- geometry -------------------------------------------------------------------------

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        return (x * self.scale + self.offset[0], y * self.scale + self.offset[1])

    def fit(self) -> None:
        self.user_zoomed = False
        if self.layout is None:
            return
        width = max(int(self.canvas.winfo_width() or 0), 200)
        height = max(int(self.canvas.winfo_height() or 0), 200)
        self.scale = min((width - 40) / max(self.layout.width, 1.0), (height - 40) / max(self.layout.height, 1.0),
                         1.5)
        self.fit_scale = self.scale
        self.offset = ((width - self.layout.width * self.scale) / 2, (height - self.layout.height * self.scale) / 2)
        self.redraw()

    def on_resize(self, _event: Any) -> None:
        if not self.user_zoomed:
            self.fit()

    # -- drawing --------------------------------------------------------------------------

    def redraw(self) -> None:
        self.canvas.delete("all")
        self.item_nodes = {}
        if self.layout is None:
            return
        for edge in self.layout.edges:
            self._draw_edge(edge)
        for node in self.layout.nodes.values():
            self._draw_node(node)

    def _draw_edge(self, edge: views.CallEdge) -> None:
        assert self.layout is not None
        a, b = self.layout.nodes[edge.source], self.layout.nodes[edge.target]
        on_path = edge.source in self.layout.path and edge.target in self.layout.path
        width = 3 if on_path else 1
        if edge.loop and a is b:
            x, y = self.to_screen(a.x + BOX_WIDTH / 2, a.y)
            r = 10 * self.scale
            self.canvas.create_oval(x - r, y - 2 * r, x + r, y, outline="#1f77b4", width=width)
            return
        half = BOX_WIDTH / 2 if a.x <= b.x else -BOX_WIDTH / 2  # leave from the side that faces the target
        x1, y1 = self.to_screen(a.x + half, a.y)
        x2, y2 = self.to_screen(b.x - half, b.y)
        options: dict[str, Any] = {"fill": "#1f77b4", "width": width, "arrow": tk.LAST, "smooth": True}
        if edge.loop:
            options["dash"] = (4, 3)
        self.canvas.create_line(x1, y1, x2, y2, **options)
        if edge.label and self.scale > 0.5:
            self.canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2 - 8 * self.scale, text=edge.label,
                                    fill="#1f77b4", font=("TkDefaultFont", max(int(9 * self.scale), 6)))

    def _draw_node(self, node: views.CallNode) -> None:
        assert self.layout is not None
        x, y = self.to_screen(node.x, node.y)
        w, h = BOX_WIDTH * self.scale / 2, BOX_HEIGHT * self.scale / 2
        fill = "#f0f0f0" if node.kind == "external" else views.STATUS_COLOURS.get(node.status, "#aec7e8")
        outline = ADDED if node.usr in self.added else CHANGED if node.usr in self.changed else "#444444"
        width = 3 if node.usr in self.added or node.usr in self.changed else (2 if node.usr in self.layout.path else 1)
        box = self.canvas.create_rectangle(x - w, y - h, x + w, y + h, fill=fill, outline=outline, width=width)
        font_size = max(int(10 * self.scale), 5)
        text = self.canvas.create_text(x, y, text=_shorten(node.label, 28), font=("TkDefaultFont", font_size))
        self.item_nodes[box] = node.usr
        self.item_nodes[text] = node.usr

    # -- interaction ----------------------------------------------------------------------

    def node_at(self, x: int, y: int) -> str | None:
        for item in self.canvas.find_overlapping(x - 1, y - 1, x + 1, y + 1):
            if item in self.item_nodes:
                return self.item_nodes[item]
        return None

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
        zoom_in = getattr(event, "delta", 0) > 0 or getattr(event, "num", 0) == 4
        self.zoom(zoom_controls.ZOOM_IN if zoom_in else zoom_controls.ZOOM_OUT,
                  (float(event.x), float(event.y)))
        return "break"

    def on_press(self, event: Any) -> None:
        self.drag_start, self.dragged = (event.x, event.y), False

    def on_drag(self, event: Any) -> None:
        if self.drag_start is not None:
            dx, dy = event.x - self.drag_start[0], event.y - self.drag_start[1]
            if abs(dx) + abs(dy) > 3:
                self.dragged = True
            self.offset = (self.offset[0] + dx, self.offset[1] + dy)
            self.drag_start = (event.x, event.y)
            self.user_zoomed = True
            self.redraw()

    def on_release(self, event: Any) -> None:
        self.drag_start = None
        if not self.dragged and getattr(event, "num", 1) == 1:
            node = self.node_at(event.x, event.y)
            if node is not None and node != self.selected:
                self.select(node)

    def on_motion(self, event: Any) -> None:
        usr = self.node_at(event.x, event.y)
        node = self.layout.nodes.get(usr) if self.layout is not None and usr else None
        self.hover_var.set("" if node is None else f"{node.label} {node.signature}  {node.brief}".strip())

    def on_double_click(self, event: Any) -> None:
        usr = self.node_at(event.x, event.y)
        entity = self.model.entities.get(usr) if self.model is not None and usr else None
        if entity is not None:
            self.open_editor(entity.file, entity.line)


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else "…" + text[-(limit - 1):]
