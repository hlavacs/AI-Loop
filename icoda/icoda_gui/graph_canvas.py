"""Shared navigation and per-node action menu machinery for graph canvases."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from tkinter import ttk
from types import MappingProxyType
from typing import Any

from icoda_core import expansion
from icoda_core.graph_filter import NodeDecision
from icoda_core.node_status import NodeAppearance
from icoda_gui import zoom_controls

SHOW_STEP = "show_step"
PROPOSE_HERE = "propose_here"
IMPLEMENT_HERE = "implement_here"
RUN_TESTS = "run_tests"
PIN_CLUSTER = "pin_cluster"
UNPIN_CLUSTER = "unpin_cluster"
RENAME_CLUSTER = "rename_cluster"
PIN_FILE_TO_CLUSTER = "pin_file_to_cluster"
STALE_MARKER = "⚠"
NODE_COLOURS = MappingProxyType({
    "stub": "#d9d9d9",
    "implemented": "#aec7e8",
    "tested": "#98df8a",
    "covered": "#98df8a",
    "uncovered": "#ffb3b3",
    "neutral": "#f5f5f5",
})
DIMMED_APPEARANCE = MappingProxyType({
    "fill": "#e5e7eb",
    "outline": "#cbd5e1",
    "text": "#9ca3af",
    "edge": "#d1d5db",
})
EXPANSION_AFFORDANCE = MappingProxyType({
    "collapsed": "+",
    "expanded": "−",
    "fill": "#ffffff",
    "outline": "#4b5563",
    "text": "#1f2937",
})


@dataclass(frozen=True)
class NodeActionContext:
    """Already-derived state needed to enable and dispatch one node's actions."""

    node_id: str
    introducing_iteration: int | None = None
    tests: tuple[str, ...] = ()
    focus: str = ""
    target_usr: str = ""
    can_propose: bool = False
    can_implement: bool = False
    can_run_tests: bool = True
    cluster_id: str = ""
    cluster_pinned: bool = False
    cluster_name: str = ""
    file_path: str = ""
    cluster_ids: tuple[str, ...] = ()
    target_cluster_id: str = ""


ActionResolver = Callable[[str], NodeActionContext | None]
ActionDispatcher = Callable[[str, NodeActionContext], None]
ExpansionDispatcher = Callable[[str], None]


class NodeActionMenu:
    """The one right-click menu shared by File, Call, Class, and Mind Map views."""

    def __init__(self, canvas: Any, hit_test: Callable[[int, int], str | None],
                 resolve: ActionResolver | None, dispatch: ActionDispatcher | None) -> None:
        self.canvas, self.hit_test = canvas, hit_test
        self.resolve, self.dispatch = resolve, dispatch
        self.menu = tk.Menu(canvas, tearoff=0)
        self.target_menu: Any | None = None
        self.context: NodeActionContext | None = None
        canvas.bind("<Button-3>", self.open)

    def open(self, event: Any) -> str:
        """Post actions for the hit node; a background right-click is an inert no-op."""
        node_id = self.hit_test(event.x, event.y)
        context = self.resolve(node_id) if node_id is not None and self.resolve is not None else None
        self.context = context
        if context is None:
            return "break"
        self._populate(context)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        return "break"

    def _populate(self, context: NodeActionContext) -> None:
        self.menu.delete(0, tk.END)
        self._command("Show introducing step", SHOW_STEP, context.introducing_iteration is not None)
        self.menu.add_separator()
        self._command("Propose the next step here", PROPOSE_HERE,
                      context.can_propose and bool(context.focus))
        self._command("Implement this function", IMPLEMENT_HERE,
                      context.can_implement and bool(context.target_usr))
        self._command("Run the tests of changed functions", RUN_TESTS,
                      bool(context.tests) and context.can_run_tests)
        if context.cluster_id:
            self.menu.add_separator()
            self._command("Pin cluster", PIN_CLUSTER, not context.cluster_pinned)
            self._command("Unpin cluster", UNPIN_CLUSTER, context.cluster_pinned)
            self._command("Rename cluster…", RENAME_CLUSTER, True)
        if context.file_path and context.cluster_ids:
            self.menu.add_separator()
            self.target_menu = tk.Menu(self.menu, tearoff=0)
            for cluster_id in context.cluster_ids:
                self.target_menu.add_command(
                    label=cluster_id,
                    command=self._file_pin_command(cluster_id),
                )
            self.menu.add_cascade(label="Pin file to cluster", menu=self.target_menu)

    def _file_pin_command(self, target_cluster_id: str) -> Callable[[], None]:
        def dispatch() -> None:
            self._dispatch(PIN_FILE_TO_CLUSTER, target_cluster_id)

        return dispatch

    def _command(self, label: str, action: str, enabled: bool) -> None:
        self.menu.add_command(label=label, state=tk.NORMAL if enabled else tk.DISABLED,
                              command=lambda: self._dispatch(action) if enabled else None)

    def _dispatch(self, action: str, target_cluster_id: str = "") -> None:
        if self.context is not None and self.dispatch is not None:
            context = replace(self.context, target_cluster_id=target_cluster_id) if target_cluster_id else self.context
            self.dispatch(action, context)


class NodeAppearanceCanvas:
    """The one appearance mapping, colour table, and stale marker used by all diagrams."""

    def __init__(self) -> None:
        self.canvas: Any
        self.node_appearances: Mapping[str, NodeAppearance] = MappingProxyType({})
        self.node_decisions: Mapping[str, NodeDecision] = MappingProxyType({})
        self.expansion_result: expansion.ExpansionResult | None = None
        self.expansion_dispatch: ExpansionDispatcher | None = None
        self.item_nodes: dict[int, str] = {}
        self.expansion_items: dict[int, str] = {}
        self.expansion_layer_enabled = True
        self.hierarchy_scrollbar: Any | None = None
        self.hierarchy_offset = 0
        self.hierarchy_page_size = 1
        self.hierarchy_bounds: tuple[float, float, float, float] | None = None
        self.hierarchy_background: Any | None = None
        self.hierarchy_position: tuple[float, float] | None = None
        self._hierarchy_drag_anchor: tuple[float, float] | None = None
        self.coverage_mode = False
        self.globally_stale = False
        self.stale_reason = ""
        self.filter_active = False
        self.neighborhood_depth = 0

    def set_node_appearances(self, appearances: Mapping[str, NodeAppearance], *, coverage_mode: bool = False,
                             globally_stale: bool = False, stale_reason: str = "") -> None:
        self.node_appearances = appearances
        self.coverage_mode, self.globally_stale = coverage_mode, globally_stale
        self.stale_reason = stale_reason
        self.redraw()

    def set_coverage_mode(self, enabled: bool) -> None:
        self.coverage_mode = bool(enabled)
        self.redraw()

    def set_graph_filter(self, decisions: Mapping[str, NodeDecision], *, filter_active: bool = False,
                         neighborhood_depth: int = 0) -> None:
        self.node_decisions = decisions
        self.filter_active = filter_active
        self.neighborhood_depth = neighborhood_depth
        self.redraw()

    def set_expansion(self, result: expansion.ExpansionResult,
                      dispatch: ExpansionDispatcher | None = None) -> None:
        """Publish the one core-derived expansion result used by every reusable diagram."""
        self.expansion_result, self.expansion_dispatch = result, dispatch
        self.redraw()

    def expansion_decision(self, node_id: str) -> expansion.ExpansionDecision | None:
        return self.expansion_result.decision_for(node_id) if self.expansion_result is not None else None

    def node_decision(self, node_id: str) -> NodeDecision:
        decision = self.node_decisions.get(node_id)
        if decision is not None:
            return decision
        expansion_decision = self.expansion_decision(node_id)
        return expansion_decision.graph_decision if expansion_decision is not None else NodeDecision()

    def node_visible(self, node_id: str) -> bool:
        decision = self.expansion_decision(node_id)
        return not self.node_decision(node_id).hidden and (decision is None or decision.visible)

    def node_dimmed(self, node_id: str) -> bool:
        return self.node_decision(node_id).dimmed

    def node_appearance(self, node_id: str) -> NodeAppearance | None:
        usr = node_id.removeprefix("entity:")
        return self.node_appearances.get(usr)

    def node_fill(self, node_id: str, fallback: str | None = None) -> str:
        if self.node_dimmed(node_id):
            return DIMMED_APPEARANCE["fill"]
        appearance = self.node_appearance(node_id)
        if appearance is None:
            return fallback or NODE_COLOURS["neutral"]
        if self.coverage_mode:
            return NODE_COLOURS["covered" if appearance.covered else "uncovered"]
        return NODE_COLOURS.get(appearance.status, fallback or NODE_COLOURS["neutral"])

    def node_outline(self, node_id: str, fallback: str) -> str:
        return DIMMED_APPEARANCE["outline"] if self.node_dimmed(node_id) else fallback

    def node_text_colour(self, node_id: str, fallback: str = "#111111") -> str:
        return DIMMED_APPEARANCE["text"] if self.node_dimmed(node_id) else fallback

    def edge_visible(self, source: str, target: str) -> bool:
        return self.node_visible(source) and self.node_visible(target)

    def edge_colour(self, source: str, target: str, fallback: str) -> str:
        return DIMMED_APPEARANCE["edge"] if self.node_dimmed(source) or self.node_dimmed(target) else fallback

    def stale_marker(self, node_id: str) -> str:
        appearance = self.node_appearance(node_id)
        return STALE_MARKER if self.globally_stale or (appearance is not None and appearance.stale) else ""

    def draw_stale_marker(self, node_id: str, x: float, y: float) -> None:
        marker = self.stale_marker(node_id)
        if marker:
            self.canvas.create_text(x, y, text=marker, fill="#c00000",
                                    font=("TkDefaultFont", 10, "bold"))

    def draw_appearance_key(self, *, uncertain_calls: bool = False) -> None:
        mode = "RECORDED TEST REACHABILITY — green reached · red not reached" if self.coverage_mode else \
            "STATUS — gray stub · blue implemented · green tested"
        if uncertain_calls:
            mode += " · dashed ? uncertain dynamic call"
        self.canvas.create_text(12, 12, anchor="nw", text=mode, fill="#4b5563",
                                font=("TkDefaultFont", 9, "bold"))
        if self.globally_stale:
            detail = f" — {self.stale_reason}" if self.stale_reason else ""
            self.canvas.create_text(12, 30, anchor="nw", text=f"STALE{detail}", fill="#c00000",
                                    font=("TkDefaultFont", 10, "bold"))

    def draw_filter_empty(self, visible_count: int, text: str = "No nodes match the current filter.") -> None:
        if self.filter_active and visible_count == 0:
            self.canvas.create_text(float(self.canvas.winfo_width()) / 2,
                                    float(self.canvas.winfo_height()) / 2,
                                    text=text, fill="#666666", font=("TkDefaultFont", 12))

    def rendered_expansion_nodes(self) -> frozenset[str]:
        """Return the exact shared node set represented by this canvas."""
        return self.expansion_result.graph.node_keys if self.expansion_result is not None else frozenset()

    def draw_expansion_layer(self) -> None:
        """Draw a bounded hierarchy viewport with scrolling independent of the diagram."""
        self.expansion_items = {}
        if (not self.expansion_layer_enabled or self.expansion_result is None
                or not self.expansion_result.graph.nodes):
            self.hide_hierarchy()
            return
        nodes = self.expansion_result.graph.nodes
        canvas_width, canvas_height = float(self.canvas.winfo_width()), float(self.canvas.winfo_height())
        left, top = self.hierarchy_position or (canvas_width - 294.0, 48.0)
        width, row_height = min(280.0, max(100.0, canvas_width - 24.0)), 27.0
        left = max(12.0, min(left, canvas_width - width - 12.0))
        top = max(48.0, min(top, canvas_height - 64.0))
        if self.hierarchy_position is not None:
            self.hierarchy_position = (left, top)
        self.hierarchy_page_size = max(1, int((self.canvas.winfo_height() - top - 25 - 12) // row_height))
        self.hierarchy_offset = min(self.hierarchy_offset, max(0, len(nodes) - self.hierarchy_page_size))
        visible = nodes[self.hierarchy_offset:self.hierarchy_offset + self.hierarchy_page_size]
        bottom = top + 25.0 + row_height * len(visible)
        self.hierarchy_bounds = (left, top, left + width, bottom)
        self.hierarchy_background = self.canvas.create_rectangle(
            left, top, left + width, bottom, fill="#ffffff", outline="#d1d5db", width=1)
        self.canvas.create_rectangle(left, top, left + width, top + 25,
                                      fill="#e8edf3", outline="#d1d5db")
        self.canvas.create_text(left + 8, top + 12, anchor="w", text="Hierarchy — drag here to move",
                                fill="#4b5563", font=("TkDefaultFont", 9, "bold"))
        positions = {
            node.key: (left + 8 + min(node.depth, 5) * 16.0,
                       top + 25.0 + row * row_height + row_height / 2)
            for row, node in enumerate(visible)
        }
        self._draw_hierarchy_branches(positions)
        for row, node in enumerate(visible):
            self._draw_expansion_row(node, left, top + 25.0 + row * row_height, width - 18, row_height)
        if self.hierarchy_scrollbar is None:
            self.hierarchy_scrollbar = ttk.Scrollbar(self.canvas, orient=tk.VERTICAL, command=self.scroll_hierarchy)
        self.hierarchy_scrollbar.place(x=left + width - 17, y=top + 25, width=16, height=bottom - top - 25)
        self.hierarchy_scrollbar.set(self.hierarchy_offset / len(nodes),
                                     (self.hierarchy_offset + len(visible)) / len(nodes))

    def hide_hierarchy(self) -> None:
        self.hierarchy_bounds = None
        self.hierarchy_background = None
        self._hierarchy_drag_anchor = None
        self.hierarchy_offset = 0
        self.expansion_items = {}
        if self.hierarchy_scrollbar is not None:
            self.hierarchy_scrollbar.place_forget()

    def in_hierarchy(self, x: int, y: int) -> bool:
        if self.hierarchy_bounds is None:
            return False
        left, top, right, bottom = self.hierarchy_bounds
        return left <= x <= right and top <= y <= bottom

    def press_hierarchy(self, event: Any) -> bool:
        """Let the header move the panel; row presses stay available for navigation."""
        self._hierarchy_drag_anchor = None
        if not self.in_hierarchy(event.x, event.y):
            return False
        assert self.hierarchy_bounds is not None
        left, top, _right, _bottom = self.hierarchy_bounds
        if event.y < top + 25:
            self._hierarchy_drag_anchor = (event.x - left, event.y - top)
        return True

    def drag_hierarchy(self, event: Any) -> bool:
        if self._hierarchy_drag_anchor is None:
            return False
        dx, dy = self._hierarchy_drag_anchor
        self.hierarchy_position = (event.x - dx, event.y - dy)
        self.redraw()
        return True

    def release_hierarchy(self) -> bool:
        """Consume header gestures so their release cannot select or open a node."""
        active = self._hierarchy_drag_anchor is not None
        self._hierarchy_drag_anchor = None
        return active

    def scroll_hierarchy(self, action: str, amount: str, unit: str = "units") -> None:
        total = len(self.expansion_result.graph.nodes) if self.expansion_result else 0
        if action == "moveto":
            offset = round(float(amount) * total)
        else:
            step = max(1, self.hierarchy_page_size - 1) if unit == "pages" else 1
            offset = self.hierarchy_offset + int(amount) * step
        self.hierarchy_offset = max(0, min(offset, total - self.hierarchy_page_size))
        self.redraw()

    def scroll_hierarchy_at(self, event: Any) -> bool:
        if not self.in_hierarchy(event.x, event.y):
            return False
        upwards = getattr(event, "delta", 0) > 0 or getattr(event, "num", 0) == 4
        self.scroll_hierarchy("scroll", "-3" if upwards else "3")
        return True

    def _draw_hierarchy_branches(self, positions: Mapping[str, tuple[float, float]]) -> None:
        """Connect rows to their parents; dependency arrows belong to the main diagram."""
        assert self.expansion_result is not None
        for node in self.expansion_result.graph.nodes:
            if node.key not in positions or node.parent is None or node.parent not in positions:
                continue
            parent_x, parent_y = positions[node.parent]
            child_x, child_y = positions[node.key]
            self.canvas.create_line(parent_x, parent_y, parent_x, child_y, child_x, child_y,
                                    fill="#cbd5e1")

    def _draw_expansion_row(self, node: expansion.ExpansionNode, left: float, top: float,
                            width: float, height: float) -> None:
        decision = self.expansion_decision(node.key)
        indent = min(node.depth, 5) * 16.0
        fill = self.node_fill(node.target_id, "#f8fafc")
        outline = self.node_outline(node.target_id, "#e5e7eb")
        box = self.canvas.create_rectangle(left + 4 + indent, top + 2, left + width - 4, top + height - 2,
                                           fill=fill, outline=outline)
        label = f"{'used' if node.synthetic else node.kind}  {node.label}"
        text_item = self.canvas.create_text(
            left + 10 + indent, top + height / 2, anchor="w", text=label,
            fill=self.node_text_colour(node.target_id), font=("TkDefaultFont", 8))
        self.item_nodes[box] = node.target_id
        self.item_nodes[text_item] = node.target_id
        if decision is not None and decision.expandable:
            self._draw_expand_affordance(node.key, decision.expanded, left + width - 17, top + height / 2)

    def _draw_expand_affordance(self, key: str, expanded: bool, x: float, y: float) -> None:
        item = self.canvas.create_rectangle(
            x - 8, y - 8, x + 8, y + 8, fill=EXPANSION_AFFORDANCE["fill"],
            outline=EXPANSION_AFFORDANCE["outline"])
        text_item = self.canvas.create_text(
            x, y, text=EXPANSION_AFFORDANCE["expanded" if expanded else "collapsed"],
            fill=EXPANSION_AFFORDANCE["text"], font=("TkDefaultFont", 10, "bold"))
        self.expansion_items[item] = key
        self.expansion_items[text_item] = key

    def toggle_expansion_at(self, x: int, y: int) -> bool:
        """Dispatch an affordance hit, leaving ordinary left-click navigation untouched."""
        for item in self.canvas.find_overlapping(x - 1, y - 1, x + 1, y + 1):
            key = self.expansion_items.get(item)
            if key is not None:
                if self.expansion_dispatch is not None:
                    self.expansion_dispatch(key)
                return True
        return False

    def redraw(self) -> None:
        raise NotImplementedError


class GraphCanvas(NodeAppearanceCanvas):
    """Base navigation used by the Call and Class View canvases."""

    def __init__(self, parent: Any, resolve_actions: ActionResolver | None = None,
                 dispatch_action: ActionDispatcher | None = None) -> None:
        super().__init__()
        self.frame = ttk.Frame(parent)
        self.scale, self.fit_scale = 1.0, 1.0
        self.offset, self.user_zoomed = (0.0, 0.0), False
        self.item_nodes: dict[int, str] = {}
        self.drag_start: tuple[int, int] | None = None
        self._drag_offset = self.offset
        self.dragged = False
        self.resolve_actions, self.dispatch_action = resolve_actions, dispatch_action

    def build_canvas(self) -> None:
        self.canvas = tk.Canvas(self.frame, background="white", cursor="fleur", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        bindings = (
            ("<MouseWheel>", self.on_wheel), ("<Button-4>", self.on_wheel), ("<Button-5>", self.on_wheel),
            ("<ButtonPress-1>", self.on_press), ("<B1-Motion>", self.on_drag),
            ("<ButtonRelease-1>", self.on_release), ("<ButtonPress-2>", self.on_press),
            ("<B2-Motion>", self.on_drag), ("<ButtonRelease-2>", self.on_release),
            ("<Double-ButtonRelease-1>", self.on_double_click), ("<Motion>", self.on_motion),
            ("<Configure>", self.on_resize),
        )
        for event, handler in bindings:
            self.canvas.bind(event, handler)
        self.action_menu = NodeActionMenu(
            self.canvas, self.node_at, self.resolve_actions, self.dispatch_action)

    def diagram_size(self) -> tuple[float, float] | None:
        raise NotImplementedError

    def redraw(self) -> None:
        raise NotImplementedError

    def on_release(self, event: Any) -> None:
        self.drag_start = None

    def on_motion(self, event: Any) -> None:
        return None

    def on_double_click(self, event: Any) -> None:
        self.drag_start = None

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        return (x * self.scale + self.offset[0], y * self.scale + self.offset[1])

    def fit(self) -> None:
        """Fit the complete current graph into the canvas."""
        self.user_zoomed = False
        size = self.diagram_size()
        if size is None:
            return
        width = max(int(self.canvas.winfo_width() or 0), 200)
        height = max(int(self.canvas.winfo_height() or 0), 200)
        graph_width, graph_height = size
        self.scale = min((width - 40) / max(graph_width, 1.0),
                         (height - 40) / max(graph_height, 1.0), 1.5)
        self.fit_scale = self.scale
        self.offset = ((width - graph_width * self.scale) / 2,
                       (height - graph_height * self.scale) / 2)
        self.redraw()

    def on_resize(self, _event: Any) -> None:
        if not self.user_zoomed:
            self.fit()
        else:
            self.redraw()

    def node_at(self, x: int, y: int) -> str | None:
        for item in reversed(self.canvas.find_overlapping(x - 1, y - 1, x + 1, y + 1)):
            if item == self.hierarchy_background:
                return None
            if item in self.item_nodes:
                return self.item_nodes[item]
        return None

    def zoom(self, factor: float, origin: tuple[float, float] | None = None) -> None:
        """Zoom around ``origin`` while keeping the fitted diagram as the lower limit."""
        if self.diagram_size() is None or self.scale <= 0:
            return
        target = min(max(zoom_controls.MAX_ZOOM, self.fit_scale), max(self.fit_scale, self.scale * factor))
        actual_factor = target / self.scale
        if abs(actual_factor - 1.0) < 0.001:
            return
        origin_x, origin_y = origin or (float(self.canvas.winfo_width()) / 2,
                                        float(self.canvas.winfo_height()) / 2)
        self.offset = (origin_x - (origin_x - self.offset[0]) * actual_factor,
                       origin_y - (origin_y - self.offset[1]) * actual_factor)
        self.scale, self.user_zoomed = target, True
        self.redraw()

    def reset_zoom(self) -> None:
        if self.diagram_size() is not None and self.scale > 0:
            self.zoom(max(self.fit_scale, 1.0) / self.scale)

    def on_wheel(self, event: Any) -> str:
        if self.scroll_hierarchy_at(event):
            return "break"
        zoom_in = getattr(event, "delta", 0) > 0 or getattr(event, "num", 0) == 4
        self.zoom(zoom_controls.ZOOM_IN if zoom_in else zoom_controls.ZOOM_OUT,
                  (float(event.x), float(event.y)))
        return "break"

    def on_press(self, event: Any) -> None:
        self.drag_start = None if self.press_hierarchy(event) else (event.x, event.y)
        self._drag_offset, self.dragged = self.offset, False

    def on_drag(self, event: Any) -> None:
        if self.drag_hierarchy(event):
            self.dragged = True
            return
        if self.drag_start is None:
            return
        dx, dy = event.x - self.drag_start[0], event.y - self.drag_start[1]
        if not self.dragged and abs(dx) + abs(dy) <= 3:
            return
        self.dragged, self.user_zoomed = True, True
        self.offset = (self._drag_offset[0] + dx, self._drag_offset[1] + dy)
        self.redraw()
