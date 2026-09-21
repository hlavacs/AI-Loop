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
from icoda_core.model import CALLABLE_KINDS, DerivedModel
from icoda_gui import graph_canvas, zoom_controls

BOX_WIDTH, BOX_HEIGHT = 200.0, 30.0
ADDED, CHANGED = "#2ca02c", "#ff7f0e"


class CallViewCanvas(graph_canvas.GraphCanvas):
    """Toolbar (root, depth, callers) and canvas; ``show`` lays out a model, ``show_proposal`` a proposal's delta."""

    def __init__(self, parent: Any, open_editor: Callable[[str, int], None],
                 resolve_actions: graph_canvas.ActionResolver | None = None,
                 dispatch_action: graph_canvas.ActionDispatcher | None = None,
                 focus_node: Callable[[str | None], None] | None = None) -> None:
        super().__init__(parent, resolve_actions, dispatch_action)
        self.open_editor = open_editor
        self.focus_node = focus_node
        self.model: DerivedModel | None = None
        self.layout: views.CallViewLayout | None = None
        self.root_usr: str | None = None
        self.entry_usr: str | None = None
        self.library_mode = False
        self.selected: str | None = None
        self.added: set[str] = set()
        self.changed: set[str] = set()
        self.depth_var = tk.IntVar(value=3)
        self.callers_var = tk.BooleanVar(value=False)
        self.root_var = tk.StringVar(value="")
        self.hover_var = tk.StringVar(value="")
        self._build_toolbar()
        self.build_canvas()

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
        ttk.Label(controls, textvariable=self.hover_var, anchor="w", foreground="#555555", width=1).pack(side=tk.LEFT,
                                                                                                  fill=tk.X,
                                                                                                  expand=True)
        self.toolbar_controls = {"from-main": from_main, "depth-label": depth_label, "depth": depth,
                                 "callers": callers, **zoom_widgets}

    # -- state ----------------------------------------------------------------------------

    def show(self, model: DerivedModel, root: str | None = None, added: set[str] | None = None,
             changed: set[str] | None = None) -> None:
        self.model = model
        self.added, self.changed = added or set(), changed or set()
        self.root_usr = root or (None if self.library_mode else
                                 self.entry_usr if self.entry_usr in model.entities else views.default_root(model))
        self.toolbar_controls["from-main"].configure(text="Library functions" if self.library_mode else "From main")
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
            entry = self.entry_usr if self.entry_usr in self.model.entities else views.default_root(self.model)
            self.root_usr, self.user_zoomed = None if self.library_mode else entry, False
            self.relayout()

    def controls_changed(self) -> None:
        self.user_zoomed = False
        self.relayout()

    def relayout(self) -> None:
        """Lay the graph out again; fit it unless the developer has zoomed or panned."""
        if self.model is None or (self.root_usr is None and not self.library_mode):
            self.layout = None
            self.root_var.set("")
            self.item_nodes = {}
            self.canvas.delete("all")
            self.hide_hierarchy()
            return
        roots = tuple(entity.usr for entity in sorted(self.model.entities.values(),
                                                      key=lambda e: (e.qualified_name, e.usr))
                      if entity.kind in CALLABLE_KINDS) if self.root_usr is None else (self.root_usr,)
        self.layout = views.layout_call_view(self.model, roots, int(self.depth_var.get() or 3),
                                             bool(self.callers_var.get()), self.selected)
        label = self.layout.nodes[self.root_usr].label if self.root_usr else f"Library functions ({len(roots)})"
        self.root_var.set(label + (" (callers)" if self.callers_var.get() else ""))
        if self.user_zoomed:
            self.redraw()
        else:
            self.fit()

    # -- geometry -------------------------------------------------------------------------

    def diagram_size(self) -> tuple[float, float] | None:
        return None if self.layout is None else (self.layout.width, self.layout.height)

    # -- drawing --------------------------------------------------------------------------

    def redraw(self) -> None:
        self.hide_tooltip()
        self.canvas.delete("all")
        self.item_nodes = {}
        if self.layout is None:
            self.hide_hierarchy()
            return
        for edge in self.layout.edges:
            if self.edge_visible(edge.source, edge.target):
                self._draw_edge(edge)
        visible_count = 0
        for node in self.layout.nodes.values():
            if self.node_visible(node.usr):
                self._draw_node(node)
                visible_count += 1
        self.draw_filter_empty(visible_count)
        self.draw_appearance_key(uncertain_calls=True)
        self.draw_expansion_layer()

    def _draw_edge(self, edge: views.CallEdge) -> None:
        assert self.layout is not None
        a, b = self.layout.nodes[edge.source], self.layout.nodes[edge.target]
        on_path = edge.source in self.layout.path and edge.target in self.layout.path
        width = 3 if on_path else 1
        colour = self.edge_colour(edge.source, edge.target, "#1f77b4")
        if edge.loop and a is b:
            x, y = self.to_screen(a.x + BOX_WIDTH / 2, a.y)
            radius, half_height = max(24 * self.scale, 16), BOX_HEIGHT * self.scale / 4
            # Leave and re-enter at separate ports; keep the arrow clear of the node's outline.
            loop_options: dict[str, Any] = {"fill": colour, "width": width, "smooth": True,
                                           "arrow": tk.LAST}
            if edge.uncertain:
                loop_options["dash"] = (6, 4)
            self.canvas.create_line(x + 3, y - half_height, x + radius, y - half_height,
                                    x + radius, y + half_height, x + 3, y + half_height, **loop_options)
            if edge.uncertain:
                self.canvas.create_text(x + radius, y - half_height - 8, text="?", fill=colour,
                                        font=("TkDefaultFont", max(int(10 * self.scale), 6), "bold"))
            return
        half = BOX_WIDTH / 2 if a.x <= b.x else -BOX_WIDTH / 2  # leave from the side that faces the target
        x1, y1 = self.to_screen(a.x + half, a.y)
        x2, y2 = self.to_screen(b.x - half, b.y)
        options: dict[str, Any] = {"fill": colour, "width": width, "arrow": tk.LAST, "smooth": True}
        if edge.uncertain:
            options["dash"] = (6, 4)
        elif edge.loop:
            options["dash"] = (4, 3)
        self.canvas.create_line(x1, y1, x2, y2, **options)
        label = f"{edge.label} · ?" if edge.label and edge.uncertain else "?" if edge.uncertain else edge.label
        if label and self.scale > 0.5:
            self.canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2 - 8 * self.scale, text=label,
                                    fill=colour, font=("TkDefaultFont", max(int(9 * self.scale), 6)))

    def _draw_node(self, node: views.CallNode) -> None:
        assert self.layout is not None
        x, y = self.to_screen(node.x, node.y)
        w, h = BOX_WIDTH * self.scale / 2, BOX_HEIGHT * self.scale / 2
        fill = self.node_fill(node.usr, "#f0f0f0" if node.kind == "external" else "#aec7e8")
        outline = ADDED if node.usr in self.added else CHANGED if node.usr in self.changed else "#444444"
        outline = self.node_outline(node.usr, outline)
        width = 3 if node.usr in self.added or node.usr in self.changed else (2 if node.usr in self.layout.path else 1)
        box = self.canvas.create_rectangle(x - w, y - h, x + w, y + h, fill=fill, outline=outline, width=width)
        font_size = max(int(10 * self.scale), 5)
        text = self.canvas.create_text(x, y, text=_shorten(node.label, 28),
                                      fill=self.node_text_colour(node.usr),
                                      font=("TkDefaultFont", font_size))
        self.item_nodes[box] = node.usr
        self.item_nodes[text] = node.usr
        self.draw_stale_marker(node.usr, x + w - 7, y - h + 7)

    # -- interaction ----------------------------------------------------------------------

    def on_release(self, event: Any) -> None:
        self.drag_start = None
        if self.release_hierarchy(event):
            return
        if not self.dragged and getattr(event, "num", 1) == 1 and self.toggle_expansion_at(event.x, event.y):
            return
        if not self.dragged and getattr(event, "num", 1) == 1:
            node = self.node_at(event.x, event.y)
            if node is not None:
                if node != self.selected:
                    self.select(node)
                    if self.focus_node is not None:
                        self.focus_node(node)
                entity = self.model.entities.get(node) if self.model is not None else None
                if entity is not None:
                    self.open_editor(entity.file, entity.line)
                elif self.model is not None and node.removeprefix("file:") in self.model.files:
                    self.open_editor(node.removeprefix("file:"), 1)

    def on_motion(self, event: Any) -> None:
        usr = self.node_at(event.x, event.y)
        node = self.layout.nodes.get(usr) if self.layout is not None and usr else None
        entity = self.model.entities.get(usr) if self.model is not None and usr else None
        location = f" · {views.entity_location_label(entity)}" if entity is not None else ""
        self.hover_var.set("" if node is None else f"{node.label} {node.signature}{location}  {node.brief}".strip())

    def on_double_click(self, event: Any) -> None:
        self.drag_start = None
        if self.release_hierarchy(event) or self.dragged:
            return
        usr = self.node_at(event.x, event.y)
        entity = self.model.entities.get(usr) if self.model is not None and usr else None
        if entity is not None:
            self.open_editor(entity.file, entity.line)


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else "…" + text[-(limit - 1):]
