"""The Class View: class/struct panels, members, statuses, and type relations."""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from icoda_core import class_view as class_graph
from icoda_core import views
from icoda_core.model import DerivedModel
from icoda_gui import graph_canvas, zoom_controls

RELATION_COLOURS = {
    class_graph.ClassEdgeKind.INHERITANCE: "#2ca02c",
    class_graph.ClassEdgeKind.COMPOSITION: "#ff7f0e",
    class_graph.ClassEdgeKind.USAGE: "#ff7f0e",
}


class ClassViewCanvas(graph_canvas.GraphCanvas):
    """A project-wide expanded Class View using the common graph navigation."""

    def __init__(self, parent: Any, open_editor: Callable[[str, int], None],
                 resolve_actions: graph_canvas.ActionResolver | None = None,
                 dispatch_action: graph_canvas.ActionDispatcher | None = None,
                 focus_node: Callable[[str | None], None] | None = None) -> None:
        super().__init__(parent, resolve_actions, dispatch_action)
        self.open_editor = open_editor
        self.focus_node = focus_node
        self.model: DerivedModel | None = None
        self.graph = class_graph.ClassGraph()
        self.layout: views.ClassViewLayout | None = None
        self.selected: str | None = None
        self.summary_var = tk.StringVar(value="No model")
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

    def show(self, model: DerivedModel) -> None:
        self.model = model
        self.graph = class_graph.build_class_graph(model)
        self.layout = views.layout_class_view(self.graph)
        self.selected, self.user_zoomed = None, False
        count = len(self.graph.nodes)
        self.summary_var.set(f"{count} class{'es' if count != 1 else ''} / structs" if count
                             else "No classes or structs in this model")
        self.fit()

    def diagram_size(self) -> tuple[float, float] | None:
        return None if self.layout is None else (self.layout.width, self.layout.height)

    def redraw(self) -> None:
        self.canvas.delete("all")
        self.item_nodes = {}
        if self.layout is None:
            self.hide_hierarchy()
            return
        if not self.layout.nodes:
            self._draw_empty()
            self.draw_expansion_layer()
            return
        for edge in self.layout.edges:
            if self.edge_visible(edge.source, edge.target):
                self._draw_edge(edge)
        visible_count = 0
        for node in self.layout.nodes.values():
            if self.node_visible(node.node.usr):
                self._draw_node(node)
                visible_count += 1
        self.draw_filter_empty(visible_count)
        self.draw_appearance_key()
        self.draw_expansion_layer()

    def _draw_empty(self) -> None:
        self.canvas.create_text(float(self.canvas.winfo_width()) / 2, float(self.canvas.winfo_height()) / 2,
                                text="No classes or structs in this model.", fill="#666666",
                                font=("TkDefaultFont", 12))

    def _draw_edge(self, edge: class_graph.ClassEdge) -> None:
        assert self.layout is not None
        source, target = self.layout.nodes[edge.source], self.layout.nodes[edge.target]
        if source is target:
            self._draw_loop(source, edge)
            return
        x1, y1, x2, y2 = self._panel_endpoints(source, target)
        sx1, sy1 = self.to_screen(x1, y1)
        sx2, sy2 = self.to_screen(x2, y2)
        colour = self.edge_colour(edge.source, edge.target, RELATION_COLOURS[edge.kind])
        options: dict[str, Any] = {"fill": colour, "width": 2, "smooth": True}
        if edge.kind == class_graph.ClassEdgeKind.USAGE:
            options.update(dash=(6, 4), arrow=tk.LAST)
        self.canvas.create_line(sx1, sy1, sx2, sy2, **options)
        self._draw_relation_marker(edge.kind, sx1, sy1, sx2, sy2, colour)
        label = edge.kind.value + (f" ×{edge.count}" if edge.count > 1 else "")
        self.canvas.create_text((sx1 + sx2) / 2, (sy1 + sy2) / 2 - 7, text=label, fill=colour,
                                font=("TkDefaultFont", max(7, int(8 * self.scale))))

    def _draw_loop(self, node: views.ClassNodeLayout, edge: class_graph.ClassEdge) -> None:
        right, top = self.to_screen(node.x + node.width / 2, node.y - node.height / 4)
        radius = 18 * self.scale
        colour = self.edge_colour(edge.source, edge.target, RELATION_COLOURS[edge.kind])
        options: dict[str, Any] = {"outline": colour, "width": 2}
        if edge.kind == class_graph.ClassEdgeKind.USAGE:
            options["dash"] = (6, 4)
        self.canvas.create_oval(right - radius, top - radius, right + radius, top + radius, **options)

    def _panel_endpoints(self, source: views.ClassNodeLayout,
                         target: views.ClassNodeLayout) -> tuple[float, float, float, float]:
        dx, dy = target.x - source.x, target.y - source.y
        source_factor = _border_factor(dx, dy, source.width, source.height)
        target_factor = _border_factor(dx, dy, target.width, target.height)
        return (source.x + dx * source_factor, source.y + dy * source_factor,
                target.x - dx * target_factor, target.y - dy * target_factor)

    def _draw_relation_marker(self, kind: class_graph.ClassEdgeKind, x1: float, y1: float,
                              x2: float, y2: float, colour: str) -> None:
        length = math.hypot(x2 - x1, y2 - y1) or 1.0
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        if kind == class_graph.ClassEdgeKind.INHERITANCE:
            points = _triangle(x2, y2, ux, uy, 11 * self.scale)
            self.canvas.create_polygon(*points, fill="white", outline=colour, width=2)
        elif kind == class_graph.ClassEdgeKind.COMPOSITION:
            points = _diamond(x1, y1, ux, uy, 9 * self.scale)
            self.canvas.create_polygon(*points, fill=colour, outline=colour)

    def _draw_node(self, layout: views.ClassNodeLayout) -> None:
        node = layout.node
        x, y = self.to_screen(layout.x, layout.y)
        half_width, half_height = layout.width * self.scale / 2, layout.height * self.scale / 2
        top = y - half_height
        outline = "#1f77b4" if self.selected == node.usr else "#444444"
        outline = self.node_outline(node.usr, outline)
        panel = self.canvas.create_rectangle(x - half_width, top, x + half_width, y + half_height,
                                             fill=self.node_fill(node.usr, "white"), outline=outline,
                                             width=3 if self.selected == node.usr else 1)
        header_bottom = top + views.CLASS_HEADER_HEIGHT * self.scale
        header = self.canvas.create_rectangle(x - half_width, top, x + half_width, header_bottom,
                                              fill=self.node_fill(node.usr, "#e8eef7"), outline=outline)
        title = f"{node.kind.value} {node.qualified_name}"
        title_item = self.canvas.create_text(x, top + 15 * self.scale, text=_shorten(title, 42),
                                             fill=self.node_text_colour(node.usr),
                                             font=("TkDefaultFont", max(7, int(10 * self.scale)), "bold"))
        counts = f"{len(node.data_members)} data · {len(node.member_functions)} methods"
        self.canvas.create_text(x, top + 34 * self.scale, text=counts,
                                fill=self.node_text_colour(node.usr, "#555555"),
                                font=("TkDefaultFont", max(6, int(8 * self.scale))))
        for item in (panel, header, title_item):
            self.item_nodes[item] = node.usr
        self.draw_stale_marker(node.usr, x + half_width - 8, top + 8)
        for row, member in enumerate(node.members):
            if self.node_visible(member.usr):
                self._draw_member(layout, member, row, header_bottom)

    def _draw_member(self, layout: views.ClassNodeLayout, member: class_graph.ClassMember,
                     row: int, header_bottom: float) -> None:
        x, _y = self.to_screen(layout.x, layout.y)
        half_width = layout.width * self.scale / 2
        row_height = views.CLASS_MEMBER_HEIGHT * self.scale
        top, bottom = header_bottom + row * row_height, header_bottom + (row + 1) * row_height
        fill = self.node_fill(member.usr, "#fafafa")
        box = self.canvas.create_rectangle(x - half_width, top, x + half_width, bottom,
                                           fill=fill, outline=self.node_outline(member.usr, "#d0d0d0"))
        text = self.canvas.create_text(x - half_width + 8 * self.scale, (top + bottom) / 2,
                                      text=_shorten(member_text(member), 48), anchor="w",
                                      fill=self.node_text_colour(member.usr),
                                      font=("TkDefaultFont", max(6, int(9 * self.scale))))
        self.item_nodes[box] = member.usr
        self.item_nodes[text] = member.usr
        self.draw_stale_marker(member.usr, x + half_width - 8, (top + bottom) / 2)

    def on_release(self, event: Any) -> None:
        self.drag_start = None
        if self.release_hierarchy():
            return
        if not self.dragged and getattr(event, "num", 1) == 1 and self.toggle_expansion_at(event.x, event.y):
            return
        if not self.dragged and getattr(event, "num", 1) == 1:
            self.selected = self.node_at(event.x, event.y)
            if self.focus_node is not None:
                self.focus_node(self.selected)
            self.redraw()
            entity = self.model.entities.get(self.selected) if self.model is not None and self.selected else None
            if entity is not None:
                self.open_editor(entity.file, entity.line)
            elif self.model is not None and self.selected \
                    and self.selected.removeprefix("file:") in self.model.files:
                self.open_editor(self.selected.removeprefix("file:"), 1)

    def on_motion(self, event: Any) -> None:
        usr = self.node_at(event.x, event.y)
        entity = self.model.entities.get(usr) if self.model is not None and usr else None
        if entity is None:
            self.hover_var.set("")
            return
        status = f" [{entity.status}]" if entity.status else ""
        location = views.entity_location_label(entity)
        self.hover_var.set(
            f"{entity.qualified_name} {entity.signature}{status} · {location}  {entity.brief}".strip())

    def on_double_click(self, event: Any) -> None:
        self.drag_start = None
        if self.release_hierarchy() or self.dragged:
            return
        usr = self.node_at(event.x, event.y)
        entity = self.model.entities.get(usr) if self.model is not None and usr else None
        if entity is not None:
            self.open_editor(entity.file, entity.line)


def member_text(member: class_graph.ClassMember) -> str:
    """The member label, including the implementation status of callables."""
    if member.kind.value == "field":
        return f"{member.name}: {member.declaration}"
    declaration = member.declaration or member.name
    return f"{declaration}  [{member.status}]"


def _border_factor(dx: float, dy: float, width: float, height: float) -> float:
    horizontal = width / (2 * abs(dx)) if dx else float("inf")
    vertical = height / (2 * abs(dy)) if dy else float("inf")
    return min(horizontal, vertical)


def _triangle(x: float, y: float, ux: float, uy: float, size: float) -> tuple[float, ...]:
    base_x, base_y = x - ux * size, y - uy * size
    return (x, y, base_x - uy * size * 0.65, base_y + ux * size * 0.65,
            base_x + uy * size * 0.65, base_y - ux * size * 0.65)


def _diamond(x: float, y: float, ux: float, uy: float, size: float) -> tuple[float, ...]:
    return (x, y, x + ux * size - uy * size * 0.55, y + uy * size + ux * size * 0.55,
            x + ux * size * 2, y + uy * size * 2,
            x + ux * size + uy * size * 0.55, y + uy * size - ux * size * 0.55)


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"
