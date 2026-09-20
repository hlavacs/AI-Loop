"""Tk canvas for the persistent project mind map produced by ``icoda_core``."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Iterable
from dataclasses import replace
from tkinter import ttk
from typing import Any

from icoda_core import clusters, mind_map, persistence, views
from icoda_core.model import DerivedModel
from icoda_core.steplog import StepLog, StepRecord
from icoda_gui import graph_canvas, zoom_controls


class MindMapCanvas(graph_canvas.GraphCanvas):
    """Render the core mind-map layout and persist developer expansion choices.

    A click activates a node: expandable nodes toggle in place, and nodes with
    an introducing iteration ask the application to show that historical step.
    All hierarchy, ordering, aggregation, and geometry remain in ``icoda_core``.
    """

    def __init__(self, parent: Any, select_step: Callable[[int], None],
                 resolve_actions: graph_canvas.ActionResolver | None = None,
                 dispatch_action: graph_canvas.ActionDispatcher | None = None,
                 focus_node: Callable[[str | None], None] | None = None,
                 open_source: Callable[[str], None] | None = None) -> None:
        super().__init__(parent, resolve_actions, dispatch_action)
        self.select_step = select_step
        self.focus_node = focus_node
        self.open_source = open_source
        self.tree: mind_map.MindMap | None = None
        self.layout: views.MindMapLayout | None = None
        self.state = mind_map.MindMapViewState()
        self.store: persistence.ProjectStore | None = None
        self.summary_var = tk.StringVar(value="Mind map: no project loaded")
        self.hover_var = tk.StringVar(value="")
        self._build_toolbar()
        self.build_canvas()

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.frame)
        bar.pack(fill=tk.X, padx=4, pady=2)
        zoom, controls = zoom_controls.build(
            bar,
            zoom_out=lambda: self.zoom(zoom_controls.ZOOM_OUT),
            fit=self.fit,
            reset=self.reset_zoom,
            zoom_in=lambda: self.zoom(zoom_controls.ZOOM_IN),
        )
        zoom.pack(side=tk.RIGHT)
        ttk.Label(bar, textvariable=self.summary_var, anchor="w").pack(side=tk.LEFT)
        ttk.Label(bar, textvariable=self.hover_var, anchor="w", foreground="#555555").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 0))
        self.toolbar_controls = controls

    def show(self, model: DerivedModel | None, history: StepLog | Iterable[StepRecord] = (),
             store: persistence.ProjectStore | None = None,
             clustering: clusters.Clustering | None = None) -> None:
        """Show a project, or safely clear the view when no project is loaded."""
        self.store = store
        self.state = store.load_state().mind_map if store is not None else mind_map.MindMapViewState()
        self.tree = mind_map.build_mind_map(model, history, clustering) if model is not None else None
        self.layout = views.layout_mind_map(self.tree, self.state) if self.tree is not None else None
        self.user_zoomed = False
        self._update_summary()
        self.fit() if self.layout is not None else self.redraw()

    def diagram_size(self) -> tuple[float, float] | None:
        return None if self.layout is None else (self.layout.width, self.layout.height)

    def redraw(self) -> None:
        self.canvas.delete("all")
        self.item_nodes = {}
        if self.layout is None:
            self._draw_empty("No project loaded.")
            return
        if not self.layout.nodes:
            self._draw_empty("No cluster, file, class, or function nodes in this model.")
            return
        nodes = self.layout.node_map()
        for edge in self.layout.edges:
            if self.edge_visible(edge.source, edge.target):
                self._draw_edge(nodes[edge.source], nodes[edge.target])
        visible_count = 0
        for node in self.layout.nodes:
            if self.node_visible(node.node.id):
                self._draw_node(node)
                visible_count += 1
        self.draw_filter_empty(visible_count)
        self.draw_appearance_key()

    def _draw_empty(self, text: str) -> None:
        self.canvas.create_text(float(self.canvas.winfo_width()) / 2, float(self.canvas.winfo_height()) / 2,
                                text=text, fill="#666666", font=("TkDefaultFont", 12))

    def _draw_edge(self, source: views.MindMapNodeLayout, target: views.MindMapNodeLayout) -> None:
        x1, y1 = self.to_screen(source.x, source.y)
        x2, y2 = self.to_screen(target.x, target.y)
        colour = self.edge_colour(source.node.id, target.node.id, "#9aa4b2")
        self.canvas.create_line(x1, y1, x2, y2, fill=colour, width=2)

    def _draw_node(self, layout: views.MindMapNodeLayout) -> None:
        node = layout.node
        x, y = self.to_screen(layout.x, layout.y)
        half_width = layout.width * self.scale / 2
        half_height = layout.height * self.scale / 2
        fill = self.node_fill(node.id, "#f5f5f5")
        box = self.canvas.create_rectangle(x - half_width, y - half_height, x + half_width, y + half_height,
                                           fill=fill, outline=self.node_outline(node.id, "#4b5563"))
        marker = "−" if node.children and node.id in self.state.expanded else "+" if node.children else "•"
        title = f"{marker} {node.kind.value.title()} · {node.name}"
        title_item = self.canvas.create_text(x - half_width + 7 * self.scale, y - 8 * self.scale,
                                             text=_shorten(title, 40), anchor="w",
                                             fill=self.node_text_colour(node.id),
                                             font=("TkDefaultFont", max(6, int(9 * self.scale)), "bold"))
        detail_item = self.canvas.create_text(x - half_width + 7 * self.scale, y + 8 * self.scale,
                                              text=_shorten(_metadata(node), 48), anchor="w",
                                              fill=self.node_text_colour(node.id, "#374151"),
                                              font=("TkDefaultFont", max(5, int(8 * self.scale))))
        for item in (box, title_item, detail_item):
            self.item_nodes[item] = node.id
        self.draw_stale_marker(node.id, x + half_width - 8, y - half_height + 8)

    def on_release(self, event: Any) -> None:
        self.drag_start = None
        if not self.dragged and getattr(event, "num", 1) == 1:
            node_id = self.node_at(event.x, event.y)
            if node_id is not None:
                self.activate_node(node_id)

    def activate_node(self, node_id: str) -> None:
        """Apply the click behavior for ``node_id`` without deriving any hierarchy."""
        tree = self.tree
        if tree is None:
            return
        node = tree.node_map().get(node_id)
        if node is None:
            return
        if self.focus_node is not None:
            self.focus_node(node.usr or None)
        if node.children:
            expanded = set(self.state.expanded)
            if node_id in expanded:
                expanded.remove(node_id)
            else:
                expanded.add(node_id)
            self.state = mind_map.MindMapViewState(tuple(expanded))
            self._save_state()
            self.layout = views.layout_mind_map(tree, self.state)
            self._update_summary()
            self.fit() if not self.user_zoomed else self.redraw()
        if node.introduced_iteration is not None:
            self.select_step(node.introduced_iteration)
        if self.open_source is not None and (node.usr or node.file):
            self.open_source(node.usr or node.file)

    def _save_state(self) -> None:
        if self.store is not None:
            self.store.save_state(replace(self.store.load_state(), mind_map=self.state))

    def _update_summary(self) -> None:
        if self.tree is None:
            self.summary_var.set("Mind map: no project loaded")
            return
        total = len(self.tree.nodes())
        visible = len(self.layout.nodes) if self.layout is not None else 0
        self.summary_var.set(f"Mind map: {total} nodes · {visible} visible" if total else
                             "Mind map: no project nodes")

    def on_motion(self, event: Any) -> None:
        node_id = self.node_at(event.x, event.y)
        node = self.tree.node_map().get(node_id) if self.tree is not None and node_id else None
        self.hover_var.set("" if node is None else f"{node.qualified_name} · {_metadata(node)}")


def _metadata(node: mind_map.MindMapNode) -> str:
    """Status, requirements and (when the history knows it) the step that introduced the node."""
    requirements = ", ".join(node.satisfied_requirement_ids) or "no requirements"
    parts = [node.status, requirements]
    if node.introduced_iteration is not None:
        parts.append(f"step #{node.introduced_iteration}")
    return " · ".join(parts)


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"
