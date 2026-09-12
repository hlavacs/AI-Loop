"""Capture the Specification screenshots used by the AI-Loop manual.

Run from ``ai-loop`` with a real display::

    .gui-venv/bin/python docs/capture_specification_screenshots.py

On a headless Linux host, prefix the same command with ``xvfb-run -a``.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image, ImageGrab, ImageStat

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "images"
SCREENSHOTS = (
    "specification-empty-new.png",
    "specification-overview.png",
    "specification-overview-more-fields.png",
    "specification-scope.png",
    "specification-requirements.png",
    "specification-requirement-dialog.png",
    "specification-field-help.png",
    "specification-process-help.png",
    "specification-choices.png",
    "specification-review.png",
)


def load_application() -> Any:
    spec = importlib.util.spec_from_file_location(
        "ai_loop_handbook_app", ROOT / "ai_loop_gui.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load ai_loop_gui.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_for(root: tk.Tk, condition: Callable[[], bool], label: str) -> None:
    deadline = time.monotonic() + 15
    while not condition() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)
    if not condition():
        raise TimeoutError(f"timed out waiting for {label}")


def capture(window: Any, name: str, *, lift: bool = True) -> None:
    if lift:
        window.lift()
        window.attributes("-topmost", True)
    window.update()
    time.sleep(0.2)
    left, top = window.winfo_rootx(), window.winfo_rooty()
    width, height = window.winfo_width(), window.winfo_height()
    image = ImageGrab.grab(bbox=(left, top, left + width, top + height))
    sample = image.convert("RGB").resize((96, 64))
    colours = sample.getcolors(maxcolors=96 * 64) or []
    variance = max(ImageStat.Stat(sample).var)
    if (len(colours) < 8 or variance < 20) and shutil.which("xwd"):
        xwd_path = OUTPUT / name.replace(".png", ".xwd")
        try:
            image = capture_xwd(
                int(window.winfo_id()), xwd_path
            )
        finally:
            xwd_path.unlink(missing_ok=True)
        sample = image.resize((96, 64))
        colours = sample.getcolors(maxcolors=96 * 64) or []
        variance = max(ImageStat.Stat(sample).var)
    if width < 500 or height < 400 or len(colours) < 8 or variance < 20:
        raise RuntimeError(
            f"invalid screenshot {name}: {width}x{height}, "
            f"{len(colours)} colours, variance {variance:.1f}"
        )
    image.save(OUTPUT / name)
    if lift:
        window.attributes("-topmost", False)
    print(f"{name}: {image.width}x{image.height}, {len(colours)} colours")


def capture_xwd(window_id: int, path: Path) -> Image.Image:
    subprocess.run(
        ["xwd", "-silent", "-id", str(window_id), "-out", str(path)], check=True
    )
    data = path.read_bytes()
    header = struct.unpack(">25I", data[:100])
    width, height, bits, stride = header[4], header[5], header[11], header[12]
    if bits not in {24, 32} or len(data) < stride * height:
        raise RuntimeError(f"unsupported XWD format: {width}x{height}x{bits}")
    pixels = data[-stride * height :]
    raw_mode = "BGRX" if bits == 32 else "BGR"
    return Image.frombytes("RGB", (width, height), pixels, "raw", raw_mode, stride, 1)


def descendants(root: tk.Tk, parent: str = ".") -> list[str]:
    result: list[str] = []
    for child in root.tk.splitlist(root.tk.call("winfo", "children", parent)):
        result.append(str(child))
        result.extend(descendants(root, str(child)))
    return result


def select_stage(root: tk.Tk, editor: Any, stage: str) -> None:
    editor.notebook.select(editor.tabs[stage])
    root.update()


def capture_messagebox(root: tk.Tk, button: Any, name: str) -> None:
    error: list[BaseException] = []

    def capture_and_close() -> None:
        try:
            dialog = next(
                child
                for child in descendants(root)
                if child.endswith(".__tk__messagebox")
            )
            xwd_path = OUTPUT / name.replace(".png", ".xwd")
            try:
                image = capture_xwd(
                    int(str(root.tk.call("winfo", "id", dialog)), 0), xwd_path
                )
            finally:
                xwd_path.unlink(missing_ok=True)
            sample = image.resize((96, 64))
            colours = sample.getcolors(maxcolors=96 * 64) or []
            variance = max(ImageStat.Stat(sample).var)
            if image.width < 300 or image.height < 100 or len(colours) < 8 or variance < 20:
                raise RuntimeError(
                    f"invalid dialog screenshot {name}: {image.width}x{image.height}, "
                    f"{len(colours)} colours, variance {variance:.1f}"
                )
            image.save(OUTPUT / name)
            print(
                f"{name}: {image.width}x{image.height}, {len(colours)} colours",
                flush=True,
            )
            root.tk.call("destroy", dialog)
        except Exception as exc:  # noqa: BLE001 - surface callback failures after wait_window
            error.append(exc)
            for child in descendants(root):
                if child.endswith(".__tk__messagebox"):
                    root.tk.call("destroy", child)

    root.after(300, capture_and_close)
    button.invoke()
    if error:
        raise error[0]


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    with tempfile.TemporaryDirectory(prefix="ai-loop-handbook-") as temporary:
        os.environ["AI_LOOP_DB"] = str(Path(temporary) / "capture.sqlite3")
        os.environ["AI_LOOP_RUNS_DIR"] = str(Path(temporary) / "runs")
        module = load_application()
        from ai_loop import specification_gui

        module.AiLoopGui._sample_redis_status = lambda self: None
        module.AiLoopGui._start_mail_access_check = lambda self: None
        app = module.AiLoopGui()
        app.geometry("1280x820+20+20")
        app.auto_refresh.set(False)
        app.status_var.set("Manual screenshot capture")

        def run_immediately(
            work: Callable[[], Any], done: Callable[[Any, str | None], None], **_kwargs: Any
        ) -> None:
            try:
                done(work(), None)
            except Exception as exc:  # noqa: BLE001 - match AiLoopGui._run_bg
                done(None, str(exc) or repr(exc))

        app._run_bg = run_immediately
        try:
            app.repo_var.set(str(ROOT))
            app.open_formal_specification()
            wait_for(
                app,
                lambda: app._embedded_specification_editor is not None,
                "the Specification editor",
            )
            editor = app._embedded_specification_editor
            app.update()

            capture(app, "specification-empty-new.png")

            editor.load_example_button.invoke()
            select_stage(app, editor, "Overview")
            capture(app, "specification-overview.png")

            editor.additional_fields_buttons["Overview"].invoke()
            capture(app, "specification-overview-more-fields.png")

            select_stage(app, editor, "Scope")
            capture(app, "specification-scope.png")

            select_stage(app, editor, "Requirements")
            capture(app, "specification-requirements.png")

            requirement = editor.record["requirements"][0]
            dialog = specification_gui._RecordDialog(
                editor.window,
                "Edit Requirement",
                specification_gui.REQUIREMENT_FIELDS,
                requirement,
                field_path_prefix="requirements",
                feedback_provider=lambda draft: editor._collection_record_feedback(
                    "requirements", 0, draft
                ),
            )
            dialog.window.geometry("720x700+300+70")
            capture(dialog.window, "specification-requirement-dialog.png")
            capture_messagebox(
                app, dialog.help_buttons["title"], "specification-field-help.png"
            )
            dialog.window.destroy()

            capture_messagebox(
                app, editor.process_help_button, "specification-process-help.png"
            )

            select_stage(app, editor, "Choices")
            capture(app, "specification-choices.png")

            select_stage(app, editor, "Review")
            capture(app, "specification-review.png")
        finally:
            app.destroy()

    missing = [name for name in SCREENSHOTS if not (OUTPUT / name).is_file()]
    if missing:
        raise RuntimeError("missing screenshots: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
