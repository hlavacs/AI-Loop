"""The Call View: the function-level call graph from a root, one column per call depth.

Functions are boxes coloured by status; a proposal's new entities get a green outline and changed ones an orange
outline; the path from the root to the selected function and its outgoing calls are drawn thick; a call back towards the root (recursion)
is drawn as a loop. Zoom, pan, hover and double click behave as in the File View.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from icoda_core import call_trace, views
from icoda_core.model import DerivedModel
from icoda_gui import graph_canvas, zoom_controls

BOX_WIDTH, BOX_HEIGHT = views.CALL_BOX_WIDTH, views.CALL_BOX_HEIGHT
ADDED, CHANGED = "#2ca02c", "#ff7f0e"
FREE_CALL_COLOUR = "#9467bd"


class CallViewCanvas(graph_canvas.GraphCanvas):
    """Toolbar (root, depth, callers) and canvas; ``show`` lays out a model, ``show_proposal`` a proposal's delta."""

    def __init__(self, parent: Any, open_editor: Callable[[str, int], None],
                 resolve_actions: graph_canvas.ActionResolver | None = None,
                 dispatch_action: graph_canvas.ActionDispatcher | None = None,
                 focus_node: Callable[[str | None], None] | None = None,
                 select_node: Callable[[str], None] | None = None,
                 load_trace: Callable[[], None] | None = None) -> None:
        super().__init__(parent, resolve_actions, dispatch_action)
        self.open_editor = open_editor
        self.focus_node = focus_node
        self.select_node = select_node
        self.model: DerivedModel | None = None
        self.layout: views.CallViewLayout | None = None
        self.root_usr: str | None = None
        self.entry_usr: str | None = None
        self.library_mode = False
        self.selected: str | None = None
        self.added: set[str] = set()
        self.changed: set[str] = set()
        self.playback: call_trace.CallPlayback | None = None
        self.playback_free_functions: tuple[str, ...] = ()
        self.playback_edge_counts: dict[tuple[str, str], int] = {}
        self.depth_var = tk.IntVar(value=3)
        self.callers_var = tk.BooleanVar(value=False)
        self.root_var = tk.StringVar(value="")
        self.hover_var = tk.StringVar(value="")
        self.playback_status_var = tk.StringVar(value="No trace loaded")
        self.load_trace = load_trace
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
        playback = ttk.Frame(bar)
        playback.pack(fill=tk.X, pady=(2, 0))
        self.playback_buttons = {}
        for label, command in (("Load trace", self._load_trace), ("Previous call", self.previous_call),
                               ("Next call", self.next_call), ("Reset", self.reset_playback)):
            button = ttk.Button(playback, text=label, command=command,
                                state=tk.NORMAL if label == "Load trace" else tk.DISABLED)
            button.pack(side=tk.LEFT, padx=(0, 4))
            self.playback_buttons[label] = button
        stepping = ttk.Frame(bar)
        stepping.pack(fill=tk.X, pady=(2, 0))
        for label, command in (("Step Over", self.step_over), ("Step Into", self.step_into),
                               ("Step Out", self.step_out)):
            button = ttk.Button(stepping, text=label, command=command, state=tk.DISABLED)
            button.pack(side=tk.LEFT, padx=(0, 4))
            self.playback_buttons[label] = button
        ttk.Label(stepping, textvariable=self.playback_status_var, anchor="w").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

    # -- trace playback -------------------------------------------------------------------

    def _load_trace(self) -> None:
        if self.load_trace is not None:
            self.load_trace()

    def set_playback(self, playback: call_trace.CallPlayback) -> None:
        self.playback = playback
        self.playback_free_functions = ()
        if (not self.library_mode and self.model is not None
                and self.entry_usr in self.model.entities):
            reachable = views.reachable_calls(self.model, self.entry_usr)
            self.playback_free_functions = tuple(
                entity.usr for entity in playback.entities if entity.usr not in reachable
            )
        self._clear_playback_selection()
        self.playback_status_var.set(playback.status)
        for label in ("Previous call", "Next call", "Reset"):
            self.playback_buttons[label].state(["!disabled"] if playback.total else ["disabled"])
        self._update_playback_status()

    def step_into(self) -> None:
        self._step_playback("into")

    def step_over(self) -> None:
        self._step_playback("over")

    def step_out(self) -> None:
        self._step_playback("out")

    def _step_playback(self, mode: str) -> None:
        if self.playback is None or not self.playback.can_step(mode):
            return
        entity = getattr(self.playback, f"step_{mode}")()
        if entity is None:
            self._clear_playback_selection()
        else:
            self._select_playback_entity(entity.usr)
        self._update_playback_status()

    def next_call(self) -> None:
        if self.playback is None:
            return
        entity = self.playback.next_call()
        if entity is not None:
            self._select_playback_entity(entity.usr)
        self._update_playback_status()

    def previous_call(self) -> None:
        if self.playback is None:
            return
        entity = self.playback.previous_call()
        if entity is None:
            self._clear_playback_selection()
        else:
            self._select_playback_entity(entity.usr)
        self._update_playback_status()

    def reset_playback(self) -> None:
        if self.playback is None:
            return
        self.playback.reset()
        self._clear_playback_selection()
        self._update_playback_status()

    def seek_first_call(self, usr: str) -> bool:
        """Jump loaded playback to a diagram function's first recorded call."""
        if self.playback is None:
            return False
        entity = self.playback.seek_first_call(usr)
        if entity is None:
            return False
        self._select_playback_entity(entity.usr)
        self._update_playback_status()
        return True

    def _update_playback_status(self) -> None:
        if self.playback is None:
            return
        status = self.playback.status
        if self.selected is not None and self.layout is not None and self.selected not in self.layout.nodes:
            status += " — outside the current diagram; source shown in editor"
        self.playback_status_var.set(status)
        for label, mode in (("Step Into", "into"), ("Step Over", "over"), ("Step Out", "out")):
            self.playback_buttons[label].state(
                ["!disabled"] if self.playback.can_step(mode) else ["disabled"])

    def _select_playback_entity(self, usr: str) -> None:
        # Playback is a selection, not a request to replace the entry-point graph.
        if not self.library_mode and self.model is not None and self.entry_usr in self.model.entities:
            self.root_usr = self.entry_usr
        self.playback_edge_counts = {}
        if self.playback is not None and self.playback.current_repeat_count > 1:
            self.playback_edge_counts = {
                (caller, usr): count for caller, count in self.playback.current_caller_counts.items()
            }
        self.select(usr)
        if self.focus_node is not None:
            self.focus_node(usr)
        if self.select_node is not None:
            self.select_node(usr)

    def _clear_playback_selection(self) -> None:
        self.playback_edge_counts = {}
        self.select(None)
        if self.focus_node is not None:
            self.focus_node(None)

    # -- state ----------------------------------------------------------------------------

    def show(self, model: DerivedModel, root: str | None = None, added: set[str] | None = None,
             changed: set[str] | None = None) -> None:
        self.model = model
        self.added, self.changed = added or set(), changed or set()
        self.root_usr = root or (None if self.library_mode else
                                 self.entry_usr if self.entry_usr in model.entities else views.default_root(model))
        self.toolbar_controls["from-main"].configure(text="Library API" if self.library_mode else "From main")
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
        roots = views.library_roots(self.model) if self.root_usr is None else (self.root_usr,)
        base_root_count = len(roots)
        depth = int(self.depth_var.get() or 3)
        callers = bool(self.callers_var.get())
        self.layout = views.layout_call_view(self.model, roots, depth, callers, self.selected)
        current = self.playback.current_entity if self.playback is not None else None
        if self.root_usr is not None and self.playback is not None:
            required_paths: list[tuple[str, ...]] = []
            free_functions = list(self.playback_free_functions)
            if current is not None and current.usr == self.selected:
                path = views.call_path(self.model, self.root_usr, current.usr)
                if path:
                    required_paths.append(path)
                    for source, _target in self.playback_edge_counts:
                        caller_path = views.call_path(self.model, self.root_usr, source)
                        if caller_path:
                            required_paths.append(caller_path)
                        else:
                            free_functions.append(source)
                else:
                    if current.usr not in free_functions:
                        free_functions.append(current.usr)
                    if self.playback is not None and self.playback.current_repeat_count > 1:
                        self.playback_edge_counts = {
                            (self.root_usr, current.usr): self.playback.current_repeat_count
                        }
            self.layout = views.layout_call_view(
                self.model, roots, depth, callers, self.selected,
                tuple(required_paths), tuple(dict.fromkeys(free_functions)),
            )
        elif current is not None and current.usr == self.selected and current.usr not in self.layout.nodes:
            roots += (current.usr,)
            self.layout = views.layout_call_view(self.model, roots, depth, callers, self.selected)
        label = self.layout.nodes[self.root_usr].label if self.root_usr else f"Library API ({base_root_count})"
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
            if self.edge_visible(edge.source, edge.target) and (
                    self.selected not in self.layout.nodes or self._focused_edge(edge)):
                self._draw_edge(edge)
        visible_count = 0
        for node in self.layout.nodes.values():
            if self.node_visible(node.usr):
                self._draw_node(node)
                visible_count += 1
        self.draw_filter_empty(visible_count)
        self.draw_appearance_key(uncertain_calls=True, free_calls=True)
        self.draw_expansion_layer()

    def _focused_edge(self, edge: views.CallEdge) -> bool:
        assert self.layout is not None
        endpoints = (edge.source, edge.target)
        return (endpoints in self.layout.path_edges or edge.source == self.selected
                or endpoints in self.playback_edge_counts)

    def _draw_edge(self, edge: views.CallEdge) -> None:
        assert self.layout is not None
        a, b = self.layout.nodes[edge.source], self.layout.nodes[edge.target]
        width = 3 if self._focused_edge(edge) else 1
        colour = self.edge_colour(edge.source, edge.target, FREE_CALL_COLOUR if edge.free else "#1f77b4")
        repeat_count = self.playback_edge_counts.get((edge.source, edge.target), 0)
        repeat_label = f"×{repeat_count}" if repeat_count else ""
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
            loop_label = " · ".join(part for part in (repeat_label, "?" if edge.uncertain else "") if part)
            if loop_label:
                self.canvas.create_text(x + radius, y - half_height - 8, text=loop_label, fill=colour,
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
        label = " · ".join(part for part in (label, repeat_label) if part)
        if label and (self.scale > 0.5 or repeat_label):
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
            if node is None:
                self.select(None)
                if self.focus_node is not None:
                    self.focus_node(None)
            else:
                if self.seek_first_call(node):
                    return
                if node != self.selected:
                    self.select(node)
                    if self.focus_node is not None:
                        self.focus_node(node)
                entity = self.model.entities.get(node) if self.model is not None else None
                if self.select_node is not None:
                    self.select_node(node)
                elif entity is not None:
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
