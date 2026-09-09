"""Open ICODA on the sample project and capture validated File and Call View screenshots."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import ImageGrab, ImageStat

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from icoda_core import persistence, prompt, response, steps


def load_application() -> Any:
    spec = importlib.util.spec_from_file_location("icoda_acceptance_app", ROOT / "icoda.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load icoda.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_for_project(root: tk.Tk, app: Any, timeout: float = 180.0) -> None:
    deadline = time.monotonic() + timeout
    while app.opened is None and time.monotonic() < deadline:
        root.update()
        status = str(app.status.get())
        if status.startswith("Analysis failed"):
            raise RuntimeError(status)
        time.sleep(0.05)
    if app.opened is None:
        raise TimeoutError(f"project did not open within {timeout:.0f} seconds")


def capture(root: tk.Tk, path: Path) -> dict[str, float | int]:
    root.lift()
    root.attributes("-topmost", True)
    root.update()
    time.sleep(0.25)
    left, top = root.winfo_rootx(), root.winfo_rooty()
    width, height = root.winfo_width(), root.winfo_height()
    image = ImageGrab.grab(bbox=(left, top, left + width, top + height))
    image.save(path)
    sample = image.convert("RGB").resize((96, 64))
    colours = sample.getcolors(maxcolors=96 * 64) or []
    variance = max(ImageStat.Stat(sample).var)
    if width < 800 or height < 500 or len(colours) < 8 or variance < 20:
        raise RuntimeError(f"invalid screenshot {path.name}: {width}x{height}, {len(colours)} colours, "
                           f"variance {variance:.1f}")
    return {"width": image.width, "height": image.height, "colours": len(colours),
            "variance": round(variance, 2)}


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
        wait_for_project(root, app)
        if app.opened.model.stale:
            raise RuntimeError("GUI opened a stale model: " + app.opened.model.stale_reason)
        app.fit_view()
        require_visible(root, {**app.panel.buttons, **app.view.zoom_control_widgets})
        file_metrics = capture(root, args.output / "file-view.png")
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
        displayed_diff = ("diff --git a/src/app/app.cppm b/src/app/app.cppm\n"
                          "--- a/src/app/app.cppm\n+++ b/src/app/app.cppm\n"
                          "@@ -8,3 +8,7 @@ export namespace app {\n"
                          "+/// @brief Returns the configured answer.\n"
                          "+int answer() {\n+    return 42;\n+}\n")
        review = steps.Proposal(
            1,
            prompt.StepRequest(prompt.ARCHITECTURE, 1, "add the configured answer"),
            args.project,
            attempts=1,
            response=response.StepResponse("Add configured answer", "The specification requires it.", ()),
            build=steps.BuildResult(True, "Build and tests passed."),
            delta=steps.Delta((), (), (), ("src/app/app.cppm",)),
            source_diff=displayed_diff,
        )
        app.panel.show(review)
        app.panel.detail_notebook.select(app.panel.source_diff.master)
        root.update()
        if displayed_diff.strip() not in app.panel.source_diff.get("1.0", "end"):
            raise RuntimeError("proposal Source diff tab did not show the worktree diff")
        proposal_diff_metrics = capture(root, args.output / "proposal-source-diff.png")
        state = {"status": app.status.get(), "summary": app.opened.summary,
                 "file_view": file_metrics, "file_view_zoomed": file_zoomed_metrics,
                 "call_view": call_metrics, "call_view_zoomed": call_zoomed_metrics,
                 "proposal_source_diff": proposal_diff_metrics,
                 "navigation": {"file": {"fit_scale": file_fit_scale, "zoomed_scale": file_zoomed_scale,
                                           "pan": file_pan},
                                "call": {"fit_scale": call_fit_scale, "zoomed_scale": call_zoomed_scale,
                                         "pan": call_pan}}}
        (args.output / "gui-state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(state))
    finally:
        root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
