"""Open ICODA and capture validated File, Call, Class, Coverage, and Issue View screenshots."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import struct
import subprocess
import sys
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image, ImageGrab, ImageStat

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from icoda_core import (
    adaptation,
    clusters,
    coverage_index,
    implementation_queue,
    mind_map,
    persistence,
    prompt,
    response,
    session,
    specification,
    steplog,
    steps,
    test_selection,
    views,
)
from icoda_core.model import CALLABLE_KINDS, DerivedModel, Edge, EdgeKind, Entity, External, FileInfo, Kind
from icoda_gui import graph_canvas


def load_application() -> Any:
    spec = importlib.util.spec_from_file_location("icoda_acceptance_app", ROOT / "icoda.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load icoda.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_for_project(root: tk.Tk, app: Any, expected: Path | None = None,
                     timeout: float = 180.0) -> None:
    deadline = time.monotonic() + timeout
    expected = expected.resolve() if expected is not None else None
    while (app.opened is None or expected is not None and app.opened.root != expected) \
            and time.monotonic() < deadline:
        root.update()
        status = str(app.status.get())
        if status.startswith("Analysis failed"):
            raise RuntimeError(status)
        time.sleep(0.05)
    if app.opened is None:
        raise TimeoutError(f"project did not open within {timeout:.0f} seconds")


def wait_for_refresh(root: tk.Tk, app: Any, previous: session.OpenedProject,
                     timeout: float = 180.0) -> None:
    """Wait until a focus-triggered analysis publishes a new opened-project value."""
    deadline = time.monotonic() + timeout
    while app.opened is previous and time.monotonic() < deadline:
        root.update()
        status = str(app.status.get())
        if status.startswith("Analysis failed"):
            raise RuntimeError(status)
        time.sleep(0.05)
    if app.opened is previous:
        raise TimeoutError(f"focus refresh did not finish within {timeout:.0f} seconds")


def capture(root: tk.Tk, path: Path, *, lift: bool = True) -> dict[str, float | int]:
    if lift:
        root.lift()
        root.attributes("-topmost", True)
    root.update()
    time.sleep(0.25)
    left, top = root.winfo_rootx(), root.winfo_rooty()
    width, height = root.winfo_width(), root.winfo_height()
    image = ImageGrab.grab(bbox=(left, top, left + width, top + height))
    sample = image.convert("RGB").resize((96, 64))
    colours = sample.getcolors(maxcolors=96 * 64) or []
    variance = max(ImageStat.Stat(sample).var)
    if (len(colours) < 8 or variance < 20) and shutil.which("xwd"):
        image = _capture_xwd(root, path.with_suffix(".xwd"))
        sample = image.resize((96, 64))
        colours = sample.getcolors(maxcolors=96 * 64) or []
        variance = max(ImageStat.Stat(sample).var)
    image.save(path)
    if width < 800 or height < 500 or len(colours) < 8 or variance < 20:
        raise RuntimeError(f"invalid screenshot {path.name}: {width}x{height}, {len(colours)} colours, "
                           f"variance {variance:.1f}")
    return {"width": image.width, "height": image.height, "colours": len(colours),
            "variance": round(variance, 2)}


def _capture_xwd(root: tk.Tk, path: Path) -> Image.Image:
    subprocess.run(["xwd", "-silent", "-id", str(root.winfo_id()), "-out", str(path)], check=True)
    data = path.read_bytes()
    header = struct.unpack(">25I", data[:100])
    width, height, bits, stride = header[4], header[5], header[11], header[12]
    if bits != 32 or len(data) < stride * height:
        raise RuntimeError(f"unsupported XWD screenshot format: {width}x{height}x{bits}")
    pixels = data[-stride * height:]
    return Image.frombytes("RGB", (width, height), pixels, "raw", "BGRX", stride, 1)


def require_visible(root: tk.Tk, widgets: dict[str, Any]) -> None:
    """Reject controls that Tk squeezed or placed outside the application window."""
    root.update()
    left, right = root.winfo_rootx(), root.winfo_rootx() + root.winfo_width()
    for name, widget in widgets.items():
        width = widget.winfo_width()
        widget_left = widget.winfo_rootx()
        if not widget.winfo_ismapped() or width + 4 < widget.winfo_reqwidth():
            raise RuntimeError(f"control is clipped: {name} ({width}px of {widget.winfo_reqwidth()}px)")
        if widget_left < left or widget_left + width > right + 2:
            raise RuntimeError(f"control is outside the window: {name}")


def _rectangle_fills(canvas: tk.Canvas) -> set[str]:
    return {str(canvas.itemcget(item, "fill")) for item in canvas.find_all()
            if canvas.type(item) == "rectangle"}


def _canvas_text(canvas: tk.Canvas) -> set[str]:
    return {str(canvas.itemcget(item, "text")) for item in canvas.find_all()
            if canvas.type(item) == "text"}


def _rendered_nodes(canvas: Any) -> set[str]:
    return set(canvas.item_nodes.values())


def _require_labelled_nodes(canvas: Any, labels: set[str], capture_name: str) -> int:
    rendered = _rendered_nodes(canvas)
    texts = _canvas_text(canvas.canvas)
    labelled = sum(any(label and label in text for text in texts) for label in labels)
    if not rendered or labelled == 0:
        raise RuntimeError(
            f"{capture_name} rendered {len(rendered)} nodes but {labelled} readable node labels"
        )
    return labelled


def _write_python_project(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "service.py").write_text(
        """from pathlib import Path

def normalize(value: str) -> str:
    return value.strip()

class Store:
    def load(self, value: str) -> str:
        Path(value)
        return normalize(value)

def main(store: Store) -> str:
    return store.load(' item ')
""",
        encoding="utf-8",
    )
    tests = root / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "test_service.py").write_text(
        """from service import Store, main

def test_main() -> None:
    assert main(Store()) == 'item'
""",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    root.geometry("1200x760+20+20")
    try:
        module = load_application()
        app = module.App(root, args.project.resolve(), config=persistence.UserConfig(),
                         config_path=args.output / "user-config.json")
        root.geometry("1200x760+20+20")
        wait_for_project(root, app, args.project)
        if app.opened.model.stale:
            raise RuntimeError("GUI opened a stale model: " + app.opened.model.stale_reason)
        app.choose_libclang_library()
        if app.libclang_window is None or not app.libclang_window.winfo_exists():
            raise RuntimeError("libclang chooser did not open a real Tk window")
        app.libclang_window.geometry("900x540+140+80")
        root.update()
        if "Active:" not in app.libclang_result_var.get() or "Currently loaded:" not in app.libclang_result_var.get():
            raise RuntimeError("libclang chooser did not display selected and loaded libraries")
        libclang_chooser_metrics = capture(app.libclang_window, args.output / "libclang-chooser.png")
        app.libclang_window.destroy()
        app.libclang_window = None
        app.fit_view()
        require_visible(root, {**app.panel.buttons, "batch-size": app.panel.batch_size_spinbox,
                               "implementation-scope": app.panel.scope_combobox,
                               "implementation-grouping": app.panel.grouping_combobox,
                               "auto-approve": app.panel.auto_approve_check,
                               "confirm-signature": app.panel.buttons["confirm_signature"],
                               "filter": app.graph_filter_entry,
                               "neighborhood": app.neighborhood_spinbox,
                               "collapse-all": app.collapse_all_button,
                               **app.view.zoom_control_widgets})
        auto_approve_before = bool(app.panel.auto_approve_var.get())
        if app.panel.phase_var.get() == prompt.IMPLEMENTATION:
            app.panel.auto_approve_check.invoke()
            root.update()
            if bool(app.panel.auto_approve_var.get()) is auto_approve_before:
                raise RuntimeError("auto-approve control did not toggle its bound variable")
        auto_approve_metrics = capture(root, args.output / "auto-approve.png")
        if bool(app.panel.auto_approve_var.get()) is not auto_approve_before:
            app.panel.auto_approve_check.invoke()
        file_metrics = capture(root, args.output / "file-view.png")
        pinned_cluster = next((cluster for cluster in app.opened.clustering.clusters
                               if len(cluster.files) >= 2), None)
        if pinned_cluster is None:
            raise RuntimeError("File View has no multi-file cluster for pin/rename acceptance")
        cluster_context = app.graph_actions(f"cluster:{pinned_cluster.id}")
        if cluster_context is None or cluster_context.cluster_id != pinned_cluster.id:
            raise RuntimeError("cluster node did not resolve through the shared action seam")
        app.dispatch_graph_action(graph_canvas.PIN_CLUSTER, cluster_context)
        module.simpledialog.askstring = lambda *args, **kwargs: "Pinned Application Core"
        app.dispatch_graph_action(graph_canvas.RENAME_CLUSTER, cluster_context)
        renamed_context = app.graph_actions(f"cluster:{pinned_cluster.id}")
        if renamed_context is None or not renamed_context.cluster_pinned:
            raise RuntimeError("cluster pin did not survive the GUI repaint")
        if renamed_context.cluster_name != "Pinned Application Core":
            raise RuntimeError("cluster rename did not survive the GUI repaint")
        assert app.view.layout is not None and app.mind_map_view.tree is not None
        renamed_circle = next(circle for circle in app.view.layout.circles if circle.id == pinned_cluster.id)
        if renamed_circle.name != "Pinned Application Core":
            raise RuntimeError("File View did not render the renamed cluster")
        if app.mind_map_view.tree.node_map()[f"cluster:{pinned_cluster.id}"].name != "Pinned Application Core":
            raise RuntimeError("Mind Map did not render the renamed cluster")
        for canvas_name, canvas in (("Call View", app.call_view), ("Class View", app.class_view)):
            result = canvas.expansion_result
            label = next((node.label for node in result.graph.nodes
                          if node.key == f"cluster:{pinned_cluster.id}"), None) if result is not None else None
            if label != "Pinned Application Core":
                raise RuntimeError(f"{canvas_name} hierarchy did not render the renamed cluster")
        cluster_x, cluster_y = app.view.to_screen(renamed_circle.cx, renamed_circle.cy)
        app.view.action_menu.open(SimpleNamespace(
            x=int(cluster_x), y=int(cluster_y),
            x_root=app.canvas.winfo_rootx() + int(cluster_x),
            y_root=app.canvas.winfo_rooty() + int(cluster_y)))
        root.update()
        cluster_pin_rename_metrics = capture(root, args.output / "cluster-pin-rename.png", lift=False)
        app.view.action_menu.menu.unpost()
        source_cluster = next((cluster for cluster in app.opened.clustering.clusters
                               if cluster.id != pinned_cluster.id and cluster.files), None)
        if source_cluster is None:
            raise RuntimeError("File View has no second cluster for the single-file picker acceptance")
        selected_file = source_cluster.files[0]
        selected_node = app.view.layout.nodes[selected_file]
        file_x, file_y = app.view.to_screen(selected_node.x, selected_node.y)
        file_context = app.graph_actions(f"file:{selected_file}")
        if file_context is None or file_context.file_path != selected_file:
            raise RuntimeError("canonical file node did not resolve through the shared action seam")
        app.view.action_menu.context = file_context
        app.view.action_menu._populate(file_context)
        file_menu = app.view.action_menu.menu
        end_index = file_menu.index(tk.END)
        picker_index = next((index for index in range(int(end_index) + 1)
                             if file_menu.type(index) == "cascade"
                             and file_menu.entrycget(index, "label") == "Pin file to cluster"), None)
        if picker_index is None:
            raise RuntimeError("file-node menu did not render the Pin file to cluster picker")
        target_menu = app.view.action_menu.target_menu
        if target_menu is None:
            raise RuntimeError("file-node picker has no target-cluster submenu")
        target_end = target_menu.index(tk.END)
        target_labels = [target_menu.entrycget(index, "label") for index in range(int(target_end) + 1)]
        expected_targets = sorted(cluster.id for cluster in app.opened.clustering.clusters)
        if target_labels != expected_targets:
            raise RuntimeError(f"file-node picker targets {target_labels!r}, expected {expected_targets!r}")
        target_menu.invoke(target_labels.index(pinned_cluster.id))
        file_menu.unpost()
        saved_layout = persistence.ProjectStore(args.project).load_layout()
        if saved_layout.pins.get(selected_file) != pinned_cluster.id:
            raise RuntimeError("file-node picker did not persist the chosen target cluster")
        reassigned = app.opened.clustering.cluster_of(selected_file)
        if reassigned is None or reassigned.id != pinned_cluster.id:
            raise RuntimeError("file-node picker did not repaint the selected file in the chosen cluster")
        assert app.view.layout is not None
        selected_node = app.view.layout.nodes[selected_file]
        file_x, file_y = app.view.to_screen(selected_node.x, selected_node.y)
        file_context = app.graph_actions(f"file:{selected_file}")
        if file_context is None:
            raise RuntimeError("repainted file node lost its shared action context")
        app.view.action_menu.context = file_context
        app.view.action_menu._populate(file_context)
        app.view.action_menu.menu.tk_popup(
            app.canvas.winfo_rootx() + int(file_x), app.canvas.winfo_rooty() + int(file_y))
        root.update()
        file_cluster_picker_metrics = capture(root, args.output / "file-cluster-picker.png", lift=False)
        app.view.action_menu.menu.unpost()
        file_fit_scale = app.view.fit_scale
        app.view.zoom_control_widgets["zoom-in"].invoke()
        if app.view.scale <= file_fit_scale:
            raise RuntimeError("File View zoom-in control did not increase the scale")
        file_offset = app.view.offset
        app.view.on_press(SimpleNamespace(x=420, y=260, num=2))
        app.view.on_drag(SimpleNamespace(x=452, y=282, num=2))
        app.view.on_release(SimpleNamespace(x=452, y=282, num=2))
        file_pan = (app.view.offset[0] - file_offset[0], app.view.offset[1] - file_offset[1])
        if file_pan != (32, 22):
            raise RuntimeError(f"File View mouse pan moved by {file_pan}, expected (32, 22)")
        file_zoomed_scale = app.view.scale
        file_zoomed_metrics = capture(root, args.output / "file-view-zoomed.png")
        app.view.zoom_control_widgets["reset"].invoke()
        if abs(app.view.scale - max(file_fit_scale, 1.0)) > 0.001:
            raise RuntimeError("File View 100% control did not restore the original scale")
        app.view.zoom_control_widgets["fit"].invoke()
        if abs(app.view.scale - app.view.fit_scale) > 0.001:
            raise RuntimeError("File View Fit control did not fit the diagram")
        app.show_call_view()
        root.update()
        require_visible(root, app.call_view.toolbar_controls)
        call_metrics = capture(root, args.output / "call-view.png")
        call_fit_scale = app.call_view.fit_scale
        app.call_view.toolbar_controls["zoom-in"].invoke()
        if app.call_view.scale <= call_fit_scale:
            raise RuntimeError("Call View zoom-in control did not increase the scale")
        call_offset = app.call_view.offset
        app.call_view.on_press(SimpleNamespace(x=420, y=260, num=2))
        app.call_view.on_drag(SimpleNamespace(x=452, y=282, num=2))
        app.call_view.on_release(SimpleNamespace(x=452, y=282, num=2))
        call_pan = (app.call_view.offset[0] - call_offset[0], app.call_view.offset[1] - call_offset[1])
        if call_pan != (32, 22):
            raise RuntimeError(f"Call View mouse pan moved by {call_pan}, expected (32, 22)")
        call_zoomed_scale = app.call_view.scale
        call_zoomed_metrics = capture(root, args.output / "call-view-zoomed.png")
        app.call_view.toolbar_controls["reset"].invoke()
        if abs(app.call_view.scale - max(call_fit_scale, 1.0)) > 0.001:
            raise RuntimeError("Call View 100% control did not restore the original scale")
        app.call_view.toolbar_controls["fit"].invoke()
        if abs(app.call_view.scale - app.call_view.fit_scale) > 0.001:
            raise RuntimeError("Call View Fit control did not fit the diagram")
        if app.call_view.layout is None or not app.call_view.layout.nodes:
            raise RuntimeError("Call View has no node for the context-menu capture")
        menu_node = next(iter(app.call_view.layout.nodes.values()))
        menu_x, menu_y = app.call_view.to_screen(menu_node.x, menu_node.y)
        app.call_view.action_menu.open(SimpleNamespace(
            x=int(menu_x), y=int(menu_y),
            x_root=app.call_view.canvas.winfo_rootx() + int(menu_x),
            y_root=app.call_view.canvas.winfo_rooty() + int(menu_y)))
        root.update()
        node_menu_metrics = capture(root, args.output / "node-action-menu.png", lift=False)
        app.call_view.action_menu.menu.unpost()
        dispatch_model = DerivedModel(str(args.project))
        for usr, name in (("acceptance:dispatch", "dispatch"), ("acceptance:fixed", "fixed_member"),
                          ("acceptance:virtual", "base_virtual_member")):
            dispatch_model.add_entity(Entity(
                usr, Kind.FUNCTION, name, name, "src/dispatch.cpp", 1, status="implemented"))
        dispatch_model.add_edge(Edge(
            EdgeKind.CALLS, "acceptance:dispatch", "acceptance:fixed", "src/dispatch.cpp", 4))
        dispatch_model.add_edge(Edge(
            EdgeKind.CALLS, "acceptance:dispatch", "acceptance:virtual", "src/dispatch.cpp", 5,
            uncertain=True))
        app.call_view.expansion_layer_enabled = False
        app.call_view.show(dispatch_model, "acceptance:dispatch")
        root.update()
        call_lines = [item for item in app.call_view.canvas.find_all()
                      if app.call_view.canvas.type(item) == "line"
                      and app.call_view.canvas.itemcget(item, "arrow") == "last"]
        dashed = [item for item in call_lines if app.call_view.canvas.itemcget(item, "dash")]
        certain = [item for item in call_lines if not app.call_view.canvas.itemcget(item, "dash")]
        call_text = _canvas_text(app.call_view.canvas)
        if len(dashed) != 1 or len(certain) != 1 or "?" not in call_text:
            raise RuntimeError(
                f"uncertain Call View expected one dashed ? edge and one solid edge; "
                f"got dashed={len(dashed)}, solid={len(certain)}, question={'?' in call_text}"
            )
        if not any("uncertain dynamic call" in text for text in call_text):
            raise RuntimeError("uncertain Call View has no developer-facing legend entry")
        uncertain_call_metrics = capture(root, args.output / "uncertain-dynamic-call.png")
        app.call_view.expansion_layer_enabled = True
        appearance_model = DerivedModel(str(args.project))
        appearance_model.add_entity(Entity(
            "acceptance:root", Kind.FUNCTION, "appearance_root", "appearance_root", "src/appearance.cpp", 1,
            status="implemented"))
        appearance_model.add_entity(Entity(
            "acceptance:covered", Kind.FUNCTION, "covered", "covered", "src/appearance.cpp", 4,
            status="tested", body_hash="current", satisfies=("R-17",)))
        appearance_model.add_entity(Entity(
            "acceptance:uncovered", Kind.FUNCTION, "uncovered", "uncovered", "src/appearance.cpp", 8,
            status="stub"))
        appearance_model.add_entity(Entity(
            "acceptance:tested", Kind.FUNCTION, "tested_fresh", "tested_fresh", "src/appearance.cpp", 12,
            status="tested"))
        appearance_model.add_entity(Entity(
            "acceptance:test", Kind.FUNCTION, "appearance_test", "appearance_test",
            "tests/appearance_test.cpp", 1))
        appearance_model.add_edge(Edge(EdgeKind.CALLS, "acceptance:root", "acceptance:covered"))
        appearance_model.add_edge(Edge(EdgeKind.CALLS, "acceptance:root", "acceptance:uncovered"))
        appearance_model.add_edge(Edge(EdgeKind.CALLS, "acceptance:root", "acceptance:tested"))
        appearance_model.add_edge(Edge(EdgeKind.CALLS, "acceptance:test", "acceptance:covered"))
        appearance_record = steplog.StepRecord(
            17, "implementation", "approved", entities_changed=["acceptance:covered"], test_ok=True,
            selected_tests=["tests/appearance_test.cpp"],
            entity_body_hashes={"acceptance:covered": "previous"})
        appearance_records = [appearance_record]
        appearance_state = persistence.ProjectState(
            persistence.ProjectPhase.IMPLEMENTATION, ("acceptance:uncovered",), 0)
        appearance_coverage = coverage_index.build_index(appearance_model, appearance_records)
        app.call_view.show(appearance_model, "acceptance:root")
        app.coverage_mode_var.set(False)
        app.refresh_graph_appearances(
            appearance_model, appearance_state, appearance_records, appearance_coverage)
        app.show_call_view()
        root.update()
        status_fills = _rectangle_fills(app.call_view.canvas)
        if graph_canvas.NODE_COLOURS["stub"] not in status_fills:
            raise RuntimeError("status diagram has no gray stub node")
        if graph_canvas.STALE_MARKER not in _canvas_text(app.call_view.canvas):
            raise RuntimeError("status diagram has no per-node stale marker")
        status_colour_metrics = capture(root, args.output / "diagram-status-colours.png")
        unfiltered_nodes = _rendered_nodes(app.call_view)
        if len(unfiltered_nodes) < 4:
            raise RuntimeError(f"unfiltered diagram rendered only {len(unfiltered_nodes)} nodes")
        diagram_unfiltered_metrics = capture(root, args.output / "diagram-unfiltered.png")
        app.graph_filter_var.set("status:stub")
        app.refresh_graph_appearances(
            appearance_model, appearance_state, appearance_records, appearance_coverage)
        app.call_view.fit()
        root.update()
        filtered_nodes = _rendered_nodes(app.call_view)
        if not filtered_nodes or len(filtered_nodes) >= len(unfiltered_nodes):
            raise RuntimeError(
                f"filtered diagram has {len(filtered_nodes)} nodes; unfiltered had {len(unfiltered_nodes)}")
        if "uncovered" not in _canvas_text(app.call_view.canvas):
            raise RuntimeError("filtered diagram does not retain the matching node's readable label")
        diagram_filtered_metrics = capture(root, args.output / "diagram-filtered.png")
        app.clear_graph_filter()
        app.focus_graph_node("acceptance:covered")
        app.neighborhood_depth_var.set(1)
        app.refresh_graph_appearances(
            appearance_model, appearance_state, appearance_records, appearance_coverage)
        app.call_view.fit()
        root.update()
        dimmed_nodes = {node for node in _rendered_nodes(app.call_view) if app.call_view.node_dimmed(node)}
        if not dimmed_nodes or graph_canvas.DIMMED_APPEARANCE["fill"] not in _rectangle_fills(app.call_view.canvas):
            raise RuntimeError("neighborhood diagram rendered no node with the shared dimmed appearance")
        diagram_dimmed_metrics = capture(root, args.output / "diagram-neighborhood-dimmed.png")
        app.neighborhood_depth_var.set(0)
        app.focus_graph_node(None)
        original_opened = app.opened
        if original_opened is None:
            raise RuntimeError("project disappeared before expansion acceptance")
        expansion_model = DerivedModel(str(args.project))
        expansion_model.files["src/expansion.cpp"] = FileInfo("src/expansion.cpp")
        expansion_model.add_entity(Entity(
            "acceptance:container", Kind.CLASS, "ExpansionDemo", "acceptance::ExpansionDemo",
            "src/expansion.cpp", 1))
        expansion_model.add_entity(Entity(
            "acceptance:child", Kind.METHOD, "expand_me", "acceptance::ExpansionDemo::expand_me",
            "src/expansion.cpp", 3, parent="acceptance:container", status="implemented"))
        expansion_model.externals["std"] = External("std", ("std::string", "std::vector"))
        expansion_model.add_edge(Edge(
            EdgeKind.USES_TYPE, "acceptance:child", "external:std", "src/expansion.cpp", 4))
        expansion_clustering = clusters.cluster_files(expansion_model)
        app.show(session.OpenedProject(
            args.project.resolve(), expansion_model, expansion_clustering,
            views.layout_file_view(expansion_model, expansion_clustering), None))
        app.show_call_view()
        app.collapse_all()
        root.update()
        collapsed_nodes = app.call_view.rendered_expansion_nodes()
        expansion_result = app.call_view.expansion_result
        if expansion_result is None:
            raise RuntimeError("collapsed hierarchy has no shared expansion result")
        container_key = expansion_result.decisions["entity:acceptance:container"].parent
        if container_key is None:
            raise RuntimeError("acceptance class has no file container")
        container_key = expansion_result.decisions[container_key].parent or container_key
        if container_key not in collapsed_nodes:
            raise RuntimeError(f"collapsed hierarchy does not render container {container_key}")
        expansion_collapsed_metrics = capture(root, args.output / "diagram-container-collapsed.png")
        app.toggle_graph_expansion(container_key)
        root.update()
        expanded_nodes = app.call_view.rendered_expansion_nodes()
        if len(expanded_nodes) <= len(collapsed_nodes):
            raise RuntimeError(
                f"expanded hierarchy has {len(expanded_nodes)} nodes; collapsed had {len(collapsed_nodes)}")
        expansion_expanded_metrics = capture(root, args.output / "diagram-container-expanded.png")
        app.toggle_graph_expansion("external:std")
        root.update()
        external_result = app.call_view.expansion_result
        external_children = external_result.decisions["external:std"].children if external_result else ()
        if not external_children or not set(external_children) <= app.call_view.rendered_expansion_nodes():
            raise RuntimeError("expanded external library reveals no referenced-symbol child node")
        texts = _canvas_text(app.call_view.canvas)
        if not {"used  std::string", "used  std::vector"} <= texts:
            raise RuntimeError("expanded external library child labels are not visible")
        expansion_external_metrics = capture(root, args.output / "diagram-external-expanded.png")
        app.show(original_opened)
        app.call_view.show(appearance_model, "acceptance:root")
        app._expansion_initialized = False
        app._expansion_auto_expand = True
        app.neighborhood_depth_var.set(0)
        app.focus_graph_node(None)
        app.refresh_graph_appearances(
            appearance_model, appearance_state, appearance_records, appearance_coverage)
        app.coverage_mode_var.set(True)
        app.toggle_coverage_mode()
        coverage_fills = _rectangle_fills(app.call_view.canvas)
        if not {graph_canvas.NODE_COLOURS["covered"], graph_canvas.NODE_COLOURS["uncovered"]} <= coverage_fills:
            raise RuntimeError("coverage diagram does not show both covered and uncovered node colours")
        coverage_colour_metrics = capture(root, args.output / "diagram-coverage-colours.png")
        app.coverage_mode_var.set(False)
        app.toggle_coverage_mode()
        assert app.opened is not None
        app.show(app.opened)
        app.show_class_view()
        root.update()
        if not app.class_view.graph.nodes:
            raise RuntimeError("Class View has no class or struct nodes")
        require_visible(root, app.class_view.toolbar_controls)
        class_metrics = capture(root, args.output / "class-view.png")
        class_fit_scale = app.class_view.fit_scale
        app.class_view.toolbar_controls["zoom-in"].invoke()
        if app.class_view.scale <= class_fit_scale:
            raise RuntimeError("Class View zoom-in control did not increase the scale")
        class_offset = app.class_view.offset
        app.class_view.on_press(SimpleNamespace(x=420, y=260, num=2))
        app.class_view.on_drag(SimpleNamespace(x=452, y=282, num=2))
        app.class_view.on_release(SimpleNamespace(x=452, y=282, num=2))
        class_pan = (app.class_view.offset[0] - class_offset[0], app.class_view.offset[1] - class_offset[1])
        if class_pan != (32, 22):
            raise RuntimeError(f"Class View mouse pan moved by {class_pan}, expected (32, 22)")
        class_zoomed_scale = app.class_view.scale
        class_zoomed_metrics = capture(root, args.output / "class-view-zoomed.png")
        app.class_view.toolbar_controls["reset"].invoke()
        if abs(app.class_view.scale - max(class_fit_scale, 1.0)) > 0.001:
            raise RuntimeError("Class View 100% control did not restore the original scale")
        app.class_view.toolbar_controls["fit"].invoke()
        if abs(app.class_view.scale - app.class_view.fit_scale) > 0.001:
            raise RuntimeError("Class View Fit control did not fit the diagram")
        store = persistence.ProjectStore(args.project.resolve())
        store.save_state(replace(store.load_state(), mind_map=mind_map.MindMapViewState()))
        log = steplog.StepLog(store.steps_path)
        app.mind_map_view.show(app.opened.model, log, store)
        if app.mind_map_view.tree is None or not app.mind_map_view.tree.clusters:
            raise RuntimeError("Mind Map has no cluster nodes")
        branch = next((node for node in app.mind_map_view.tree.clusters if node.children), None)
        if branch is None:
            raise RuntimeError("Mind Map has no expandable cluster")
        app.mind_map_view.activate_node(branch.id)
        descendant = next((node for node in branch.children if node.children), None)
        if descendant is not None:
            app.mind_map_view.activate_node(descendant.id)
            nested = next((node for node in descendant.children if node.children), None)
            if nested is not None:
                app.mind_map_view.activate_node(nested.id)
        app.show_mind_map_view()
        root.update()
        require_visible(root, app.mind_map_view.toolbar_controls)
        mind_map_metrics = capture(root, args.output / "mind-map.png")
        coverage_model = DerivedModel.from_json(app.opened.model.to_json())
        target = next(entity for entity in coverage_model.entities.values() if entity.kind in CALLABLE_KINDS)
        coverage_test = "tests/coverage_acceptance.cpp"
        coverage_model.add_entity(Entity("acceptance:test", Kind.FUNCTION, "test_focused_callable",
                                         "acceptance::test_focused_callable", coverage_test, 1))
        coverage_model.add_edge(Edge(EdgeKind.CALLS, "acceptance:test", target.usr,
                                     "tests/coverage_acceptance.cpp", 3))
        if coverage_test not in test_selection.model_test_identifiers(coverage_model):
            raise RuntimeError("acceptance test identifier was not discovered")
        coverage_record = steplog.StepRecord(
            1, "implementation", "approved", title="Verified focused test", test_ok=True,
            selected_tests=[coverage_test], time="2026-09-10T08:00:00+00:00")
        app.coverage_view.show(coverage_model, [coverage_record])
        app.show_coverage_view()
        root.update()
        if not app.coverage_view.index.entries or not app.coverage_view.index.covered:
            raise RuntimeError("Coverage overview has no callable test evidence")
        coverage_metrics = capture(root, args.output / "coverage-overview.png")
        target.satisfies = tuple(sorted(set(target.satisfies) | {"G-1", "R-54"}))
        requirement_spec = {
            "goals": ["Keep the developer informed"],
            "requirements": [
                {"id": "R-54", "title": "Show implementing code", "priority": "must"},
                {"id": "R-55", "title": "Show newly requested work", "priority": "must"},
            ],
        }
        app.coverage_view.show(coverage_model, [coverage_record], specification=requirement_spec)
        root.update()
        if len(app.coverage_view.requirements) != 3:
            raise RuntimeError("Coverage overview did not render all requirements and goals")
        if sum(entry.uncovered for entry in app.coverage_view.requirements) != 1:
            raise RuntimeError("Coverage overview did not distinguish covered and uncovered requirements")
        requirement_coverage_metrics = capture(root, args.output / "requirements-coverage.png")
        issue_model = DerivedModel.from_json(app.opened.model.to_json())
        issue_model.add_entity(Entity(
            "acceptance:platform", Kind.FUNCTION, "open_native", "acceptance::open_native", "main.cpp", 2, 58,
            signature="void open_native(int a, int b, int c, int d, int e, int f)", status="implemented"))
        issue_model.add_edge(Edge(EdgeKind.CALLS, "acceptance:platform", "external:windows",
                                  "main.cpp", 4, "CreateFileW"))
        app.issue_view.show(issue_model, [])
        app.show_issue_view()
        root.update()
        if not app.issue_view.issues:
            raise RuntimeError("Issue View has no rule-check issues")
        if not any(issue.message and issue.file and issue.line for issue in app.issue_view.issues):
            raise RuntimeError("Issue View contains no actionable source location")
        issue_metrics = capture(root, args.output / "rule-issues.png")
        app.show_call_view()
        root.update()
        target = next(entity.usr for entity in app.opened.model.entities.values() if entity.kind in CALLABLE_KINDS)
        approach = steps.Approach(
            1, prompt.StepRequest(prompt.IMPLEMENTATION, 1, target=target), target, attempts=1,
            plan="Use std::ranges::find, keep the existing signature, and add a focused test; about 8 lines.",
            entities=(app.opened.model.entities[target].qualified_name,),
            files=(app.opened.model.entities[target].file, "tests/implementation_test.cpp"),
        )
        app.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
        app.panel.set_implementation_queue(app.opened.model.entities[target].qualified_name, 1)
        app.panel.show_approach(approach)
        app.panel.detail_notebook.select(app.panel.approach_text.master)
        root.update()
        if approach.plan not in app.panel.approach_text.get("1.0", "end"):
            raise RuntimeError("Approach tab did not show the provider's plan")
        if not app.panel.buttons["approve_approach"].instate(["!disabled"]):
            raise RuntimeError("Approve approach is disabled for a usable unapproved approach")
        if app.panel.buttons["propose"].instate(["!disabled"]):
            raise RuntimeError("Code proposal is enabled before approach approval")
        approach_metrics = capture(root, args.output / "implementation-approach.png")
        app.panel.show_approach(approach, approved=True)
        if not app.panel.buttons["propose"].instate(["!disabled"]):
            raise RuntimeError("Code proposal is disabled after approach approval")
        app.panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
        displayed_diff = ("diff --git a/src/app/app.cppm b/src/app/app.cppm\n"
                          "--- a/src/app/app.cppm\n+++ b/src/app/app.cppm\n"
                          "@@ -8,3 +8,7 @@ export namespace app {\n"
                          "+/// @brief Returns the configured answer.\n"
                          "+int answer() {\n+    return 42;\n+}\n")
        review_entities = tuple(entity for entity in app.opened.model.entities.values()
                                if entity.kind in steps.ARCHITECTURE_ENTITY_KINDS)[:2]
        review = steps.Proposal(
            1,
            prompt.StepRequest(prompt.ARCHITECTURE, 1, "add the configured answer"),
            args.project,
            attempts=1,
<<<<<<< HEAD
            response=response.StepResponse("Add configured answer", "The specification requires it.", ()),
            build=steps.BuildResult(True, True, "Build completed successfully.", "All 8 tests passed."),
=======
            response=response.StepResponse(
                "Add configured answer", "The specification requires it.", (),
                entities=(adaptation.EntitySummary(
                    "app::answer", "function", "src/app/app.cppm", "int answer()", ("R-1",)),)),
            build=steps.BuildResult(True, "Build passed."), test=steps.TestResult(True, "Tests passed."),
>>>>>>> main
            delta=steps.Delta(review_entities, (), (), ("src/app/app.cppm",)),
            source_diff=displayed_diff,
        )
        app.panel.show(review)
        app.panel.detail_notebook.select(app.panel.entity_summary.master)
        root.update()
        require_visible(root, {"entity-summary": app.panel.entity_summary,
                               "adapt": app.panel.buttons["adapt"]})
        canonical_summary = adaptation.render_summary(review.entities)
        if app.panel.edited_entity_summary() != canonical_summary:
            raise RuntimeError("Entity summary tab did not show the canonical proposal summary")
        edited_summary = canonical_summary.replace("int answer()", "int answer(int configured)")
        app.panel.entity_summary.delete("1.0", tk.END)
        app.panel.entity_summary.insert("1.0", edited_summary)
        adaptation_actions: list[str] = []
        original_action = app.panel.on_action
        app.panel.on_action = adaptation_actions.append
        app.panel.buttons["adapt"].invoke()
        app.panel.on_action = original_action
        if adaptation_actions != ["adapt"]:
            raise RuntimeError("Adapt control did not dispatch the structured adaptation action")
        structured_adaptation_metrics = capture(root, args.output / "structured-adaptation.png")
        app.panel.detail_notebook.select(app.panel.details.master)
        root.update()
        if "Architecture entity budget: 2 / 5" not in app.panel.details.get("1.0", "end"):
            raise RuntimeError("proposal Delta tab did not show architecture budget use")
        proposal_delta_metrics = capture(root, args.output / "proposal-delta.png")
        app.panel.detail_notebook.select(app.panel.source_diff.master)
        root.update()
        if displayed_diff.strip() not in app.panel.source_diff.get("1.0", "end"):
            raise RuntimeError("proposal Source diff tab did not show the worktree diff")
        proposal_diff_metrics = capture(root, args.output / "proposal-source-diff.png")
<<<<<<< HEAD
        app.panel.detail_notebook.select(app.panel.build_output.master)
        root.update()
        if "Build completed successfully." not in app.panel.build_output.get("1.0", "end"):
            raise RuntimeError("proposal Build tab did not show the separate compiler output")
        proposal_build_metrics = capture(root, args.output / "proposal-build.png")
        app.panel.detail_notebook.select(app.panel.test_output.master)
        root.update()
        if "All 8 tests passed." not in app.panel.test_output.get("1.0", "end"):
            raise RuntimeError("proposal Tests tab did not show the separate CTest output")
        proposal_tests_metrics = capture(root, args.output / "proposal-tests.png")
=======
        signature_target = next(entity for entity in app.opened.model.entities.values()
                                if entity.kind in CALLABLE_KINDS and entity.signature)
        signature_model = DerivedModel.from_json(app.opened.model.to_json())
        previous_signature = signature_target.signature
        proposed_signature = previous_signature + " /* confirmed change */"
        signature_model.entities[signature_target.usr].signature = proposed_signature
        signature_delta = steps.compute_delta(app.opened.model, signature_model, [signature_target.file])
        signature_review = steps.Proposal(
            2, prompt.StepRequest(prompt.ARCHITECTURE, 2, "change an existing signature"), args.project,
            attempts=1, response=response.StepResponse("Change existing signature", "The API needs it.", ()),
            build=steps.BuildResult(True, "Build passed."), test=steps.TestResult(True, "Tests passed."),
            model=signature_model, delta=signature_delta, source_diff="signature-only acceptance proposal",
        )
        app.steps._show_proposal(signature_review)
        app.panel.detail_notebook.select(app.panel.signature.master)
        root.update()
        signature_text = app.panel.signature.get("1.0", "end")
        if previous_signature not in signature_text or proposed_signature not in signature_text:
            raise RuntimeError("Signature changes tab did not show both declaration versions")
        if "approve" in app.panel.enabled_actions or "confirm_signature" not in app.panel.enabled_actions:
            raise RuntimeError("Signature proposal did not require confirmation before approval")
        signature_confirmation_metrics = capture(root, args.output / "signature-confirmation.png")
        app.panel.buttons["confirm_signature"].invoke()
        if "approve" not in app.panel.enabled_actions or "confirm_signature" in app.panel.enabled_actions:
            raise RuntimeError("Confirm signatures did not re-enable proposal approval")
        review.selected_tests = ("tests/answer_test.cpp", "app::answer_returns_configured_value")
        review.test, review.error = steps.TestResult(False, "answer: expected 42, got 41"), "the proposal tests fail"
        app.panel.show(review)
        app.panel.detail_notebook.select(app.panel.test_output.master)
        root.update()
        if app.panel.build_status_var.get() != "Build: passed" or app.panel.test_status_var.get() != "Tests: failed":
            raise RuntimeError("proposal did not show separate build-passed and test-failed indicators")
        displayed_tests = app.panel.test_output.get("1.0", "end")
        if not all(item in displayed_tests for item in review.selected_tests):
            raise RuntimeError("proposal Tests tab did not show the targeted test selection")
        proposal_test_metrics = capture(root, args.output / "proposal-targeted-tests.png")
        batch_targets = tuple(entity.usr for entity in app.opened.model.entities.values()
                              if entity.kind in CALLABLE_KINDS)[:2]
        if len(batch_targets) != 2:
            raise RuntimeError("acceptance project has fewer than two callable batch targets")
        review.request = prompt.StepRequest(
            prompt.IMPLEMENTATION, 1, target=batch_targets[0], batch=batch_targets)
        review.model = app.opened.model
        review.error = ""
        app.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
        batch_names = tuple(app.opened.model.entities[usr].qualified_name for usr in batch_targets)
        app.panel.set_implementation_queue(
            batch_names[0], len(batch_targets), batch_size=2, batch=batch_names)
        app.panel.show(review)
        app.panel.detail_notebook.select(app.panel.details.master)
        root.update()
        batch_details = app.panel.details.get("1.0", "end")
        if not all(name in batch_details for name in batch_names) or "Implementation batch:" not in batch_details:
            raise RuntimeError("proposal Delta tab did not show every implementation batch member")
        proposal_batch_metrics = capture(root, args.output / "proposal-batch.png")
        review.request = replace(review.request, grouped=True)
        app.panel.set_implementation_queue(
            batch_names[0], len(batch_targets), batch_size=2, batch=batch_names,
            grouping_mode="few_line_group")
        app.panel.show(review)
        app.panel.detail_notebook.select(app.panel.test_output.master)
        root.update()
        grouped_tests = app.panel.test_output.get("1.0", "end")
        if app.panel.grouping_var.get() != "Few-line group" or not all(
                name in grouped_tests for name in batch_names):
            raise RuntimeError("few-line grouping review did not name every grouped entity")
        grouping_metrics = capture(root, args.output / "few-line-grouping.png")
        override_model = DerivedModel.from_json(app.opened.model.to_json())
        override_targets = tuple(entity.usr for entity in override_model.entities.values()
                                 if entity.kind in CALLABLE_KINDS)[:2]
        if len(override_targets) != 2:
            raise RuntimeError("acceptance project has fewer than two queue-override targets")
        for usr in override_targets:
            override_model.entities[usr].status = "stub"
        override_state = persistence.ProjectState(
            persistence.ProjectPhase.IMPLEMENTATION, override_targets, 0,
            implementation_scope=implementation_queue.Scope.SINGLE_ENTITY.value)
        override_state = implementation_queue.override_target(
            override_model, override_state, override_targets[1])
        store.save_state(override_state)
        override_clustering = clusters.cluster_files(override_model)
        app.show(session.OpenedProject(
            args.project.resolve(), override_model, override_clustering,
            views.layout_file_view(override_model, override_clustering), None))
        root.update()
        expected_override = override_model.entities[override_targets[1]].qualified_name
        if app.panel.scope_var.get() != "Single entity":
            raise RuntimeError("implementation scope control did not show Single entity")
        if f"Overridden target: {expected_override}" not in app.panel.queue_var.get():
            raise RuntimeError("implementation queue overview did not show the overridden target")
        queue_override_metrics = capture(root, args.output / "implementation-queue-override.png")
        python_project = args.output / "python-project"
        _write_python_project(python_project)
        app.open_project(python_project)
        wait_for_project(root, app, python_project)
        if app.language_var.get() != "Language: Python":
            raise RuntimeError(f"Python project language is not visible: {app.language_var.get()!r}")
        app.fit_view()
        app.views.select(0)
        root.update()
        assert app.view.layout is not None
        python_file_labels = _require_labelled_nodes(
            app.view, {node.label for node in app.view.layout.nodes.values()}, "python-file-view.png"
        )
        python_file_metrics = capture(root, args.output / "python-file-view.png")
        app.show_class_view()
        root.update()
        python_class_labels = _require_labelled_nodes(
            app.class_view, {node.name for node in app.class_view.graph.nodes},
            "python-class-view.png",
        )
        python_class_metrics = capture(root, args.output / "python-class-view.png")
        app.show_call_view()
        root.update()
        assert app.call_view.layout is not None
        python_call_labels = _require_labelled_nodes(
            app.call_view, {node.label for node in app.call_view.layout.nodes.values()},
            "python-call-view.png",
        )
        python_call_metrics = capture(root, args.output / "python-call-view.png")
        app.edit_specification()
        editor = app.spec_editor
        editor.show_page("code_profile")
        editor.window.geometry("1000x760+140+20")
        root.update()
        python_profile = editor.to_specification()["code_profile"]
        if python_profile != specification.default_code_profile("Python"):
            raise RuntimeError(f"Python code profile is not the detected default: {python_profile!r}")
        visible_python_fields = {
            key: editor.profile.widgets[key]
            for key in (
                "test_framework", "test_runner", "test_file_convention", "source_file_extension",
                "module_naming", "class_naming", "function_naming",
            )
        }
        require_visible(editor.window, visible_python_fields)
        python_profile_metrics = capture(editor.window, args.output / "python-code-profile.png")
        editor.close()
        refresh_usr = "python:service:normalize"
        previous_opened = app.opened
        previous_hash = previous_opened.model.entities[refresh_usr].body_hash
        python_source = python_project / "service.py"
        python_source.write_text(
            python_source.read_text(encoding="utf-8").replace(
                "return value.strip()", "return value.strip().lower()"
            ),
            encoding="utf-8",
        )
        root.event_generate("<FocusIn>", when="tail")
        wait_for_refresh(root, app, previous_opened)
        if app.opened.model.entities[refresh_usr].body_hash == previous_hash:
            raise RuntimeError("real FocusIn binding did not publish the externally edited function body")
        app.views.select(0)
        root.update()
        focus_refresh_metrics = capture(root, args.output / "external-edit-focus-refresh.png")
>>>>>>> main
        state = {"status": app.status.get(), "summary": app.opened.summary,
                 "libclang_chooser": libclang_chooser_metrics,
                 "file_view": file_metrics, "file_view_zoomed": file_zoomed_metrics,
                 "call_view": call_metrics, "call_view_zoomed": call_zoomed_metrics,
                 "uncertain_dynamic_call": uncertain_call_metrics,
                 "node_action_menu": node_menu_metrics,
                 "cluster_pin_rename": cluster_pin_rename_metrics,
                 "file_cluster_picker": file_cluster_picker_metrics,
                 "class_view": class_metrics, "class_view_zoomed": class_zoomed_metrics,
                 "mind_map": mind_map_metrics,
                 "coverage_overview": coverage_metrics,
                 "requirements_coverage": requirement_coverage_metrics,
                 "diagram_status_colours": status_colour_metrics,
                 "diagram_coverage_colours": coverage_colour_metrics,
                 "diagram_unfiltered": diagram_unfiltered_metrics,
                 "diagram_filtered": diagram_filtered_metrics,
                 "diagram_neighborhood_dimmed": diagram_dimmed_metrics,
                 "diagram_container_collapsed": expansion_collapsed_metrics,
                 "diagram_container_expanded": expansion_expanded_metrics,
                 "diagram_external_expanded": expansion_external_metrics,
                 "rule_issues": issue_metrics,
                 "auto_approve": auto_approve_metrics,
                 "implementation_approach": approach_metrics,
                 "structured_adaptation": structured_adaptation_metrics,
                 "proposal_delta": proposal_delta_metrics, "proposal_source_diff": proposal_diff_metrics,
<<<<<<< HEAD
                 "proposal_build": proposal_build_metrics, "proposal_tests": proposal_tests_metrics,
=======
                 "signature_confirmation": signature_confirmation_metrics,
                 "proposal_test_failed": proposal_test_metrics, "proposal_batch": proposal_batch_metrics,
                 "few_line_grouping": grouping_metrics,
                 "implementation_queue_override": queue_override_metrics,
                 "python_file_view": {**python_file_metrics, "labelled_nodes": python_file_labels},
                 "python_class_view": {**python_class_metrics, "labelled_nodes": python_class_labels},
                 "python_call_view": {**python_call_metrics, "labelled_nodes": python_call_labels},
                 "python_code_profile": python_profile_metrics,
                 "external_edit_focus_refresh": focus_refresh_metrics,
>>>>>>> main
                 "navigation": {"file": {"fit_scale": file_fit_scale, "zoomed_scale": file_zoomed_scale,
                                           "pan": file_pan},
                                "call": {"fit_scale": call_fit_scale, "zoomed_scale": call_zoomed_scale,
                                         "pan": call_pan},
                                "class": {"fit_scale": class_fit_scale, "zoomed_scale": class_zoomed_scale,
                                          "pan": class_pan}}}
        (args.output / "gui-state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(state))
    finally:
        root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
