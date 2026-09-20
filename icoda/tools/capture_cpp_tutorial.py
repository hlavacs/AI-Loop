"""Capture the handbook's C++ tutorial with real builds, tests, analysis, and Tk.

The provider replies are deterministic reference files; no provider service is called.
Run from icoda with --project pointing to a new empty directory and --output to a
capture directory. The output includes red-rectangle coordinates for the PDF builder.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import os
import plistlib
import subprocess
import sys
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from gui_acceptance import capture, load_application

from icoda_core import generator, implementation_queue, persistence, prompt, session, specification, steps


def capture_window(root: tk.Tk, path: Path) -> dict[str, int]:
    """Capture only this process's Tk window, even when another app covers it."""
    # Let Tk and the compositor publish newly created/resized windows, including dialogs.
    for _ in range(15):
        root.update()
        time.sleep(0.02)
    if sys.platform != "darwin":
        capture(root, path)
        return {"X": root.winfo_rootx(), "Y": root.winfo_rooty(),
                "Width": root.winfo_width(), "Height": root.winfo_height()}
    graphics = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
    foundation = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
    graphics.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    graphics.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
    foundation.CFPropertyListCreateData.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                  ctypes.c_long, ctypes.c_ulong, ctypes.c_void_p]
    foundation.CFPropertyListCreateData.restype = ctypes.c_void_p
    foundation.CFDataGetLength.argtypes = [ctypes.c_void_p]
    foundation.CFDataGetLength.restype = ctypes.c_long
    foundation.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
    foundation.CFDataGetBytePtr.restype = ctypes.c_void_p
    foundation.CFRelease.argtypes = [ctypes.c_void_p]
    windows = graphics.CGWindowListCopyWindowInfo(0, 0)
    data = foundation.CFPropertyListCreateData(None, windows, 100, 0, None)
    try:
        descriptions = plistlib.loads(ctypes.string_at(
            foundation.CFDataGetBytePtr(data), foundation.CFDataGetLength(data)))
    finally:
        foundation.CFRelease(data)
        foundation.CFRelease(windows)
    own = [window for window in descriptions if window.get("kCGWindowOwnerPID") == os.getpid()
           and window.get("kCGWindowAlpha", 1) > 0]
    if not own:
        raise RuntimeError("Could not locate this process's ICODA window for capture.")
    named = [window for window in own if window.get("kCGWindowName") == root.title()]
    visible = [window for window in own if window.get("kCGWindowIsOnscreen")]
    window = min(named or visible or own, key=lambda item: (
        abs(item["kCGWindowBounds"]["Width"] - root.winfo_width())
        + abs(item["kCGWindowBounds"]["Height"] - root.winfo_height())))
    subprocess.run(["screencapture", "-x", "-o", "-l", str(window["kCGWindowNumber"]), str(path)],
                   check=True)
    with Image.open(path) as screenshot:
        if screenshot.height < 500 or max(ImageStat.Stat(screenshot.convert("RGB")).var) < 20:
            raise RuntimeError(f"Invalid ICODA window capture: {path.name} ({root.title()})")
    return {key: int(value) for key, value in window["kCGWindowBounds"].items()}


def reference_specification() -> dict[str, Any]:
    spec = specification.default_specification("ScoreClamp")
    spec["summary"] = "Clamp integer scores to 0 through 100 and demonstrate three inputs."
    spec["goals"] = ["Keep every returned score within 0 through 100."]
    spec["out_of_scope"] = ["Interactive input, files, networking, and floating-point scores."]
    spec["not_allowed"] = ["Third-party runtime or test libraries; platform-specific APIs."]
    spec["done_when"] = ["Both CTests pass, output is scores: 0 42 100, and the queue is empty."]
    spec["use_cases"] = [
        {"id": "UC-1", "title": "Clamp a score", "description": "Clamp any int to 0 through 100."},
        {"id": "UC-2", "title": "Run the demonstration", "description": "Print three clamped scores."},
    ]
    requirements = [
        ("Clamp low scores", "Negative values, including minimum int, return 0."),
        ("Preserve valid scores", "Values from 0 through 100 stay unchanged; clamping is idempotent."),
        ("Clamp high scores", "Values above 100, including maximum int, return 100."),
        ("Print the demonstration", "Print scores: 0 42 100 and a newline; return 0."),
    ]
    spec["requirements"] = [
        {"id": f"R-{i}", "title": title, "description": description, "priority": "must",
         "use_cases": ["UC-2" if i == 4 else "UC-1"]}
        for i, (title, description) in enumerate(requirements, 1)
    ]
    spec["decisions"] = [
        {"id": "D-1", "title": "Standard library only", "rationale": "Use std::clamp without dependencies."},
        {"id": "D-2", "title": "One application module", "rationale": "Keep the example small."},
        {"id": "D-3", "title": "Standalone C++ tests", "rationale": "CTest checks executable exit codes."},
    ]
    spec["code_profile"].update({
        "test_framework": "CTest with standalone C++ test executables",
        "test_runner": "ctest --preset debug",
        "test_file_convention": "tests/<subsystem>_test.cpp",
        "source_file_extension": ".cppm",
        "module_naming": "snake_case", "class_naming": "PascalCase", "function_naming": "snake_case",
        "library_policy": "C++ standard library only; no external dependencies",
    })
    assert not specification.validate(spec), specification.validate(spec)
    return spec


def capture_completed_views(root: tk.Tk, app: Any,
                            snap: Callable[[str, list[tuple[Any, str]]], None]) -> None:
    """Give the completed-project views room to show their full content."""
    app.panel.frame.master.sashpos(0, int(root.winfo_height() * 0.68))
    app.views.select(0)
    root.update()
    app.fit_view()
    snap("cpp-file-view.png", [(app.view.canvas, "C++ module, entry point, and test-file structure")])
    app.show_class_view()
    app.class_view.expansion_layer_enabled = False
    app.class_view.show(app.opened.model)
    snap("cpp-class-view.png", [(app.class_view.canvas, "ScoreClamp class and implemented static method")])
    app.show_coverage_view()
    snap("cpp-terminal-overview.png", [
        (app.panel.queue_label, "Empty C++ implementation queue"),
        (app.coverage_view.frame, "Requirement links and recorded test reachability"),
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project, output = args.project.resolve(), args.output.resolve()
    if project.exists() and any(project.iterdir()):
        raise ValueError("The capture project must be empty.")
    output.mkdir(parents=True, exist_ok=True)
    generator.write_skeleton(project, "ScoreClamp")
    store = persistence.ProjectStore(project)
    specification.save(store.specification_path, reference_specification())
    reference = ROOT / "docs/examples/score-clamp"
    final_module = (reference / "src/app/app.cppm").read_text()
    final_main = (reference / "src/main.cpp").read_text()
    final_test = (reference / "tests/smoke_test.cpp").read_text()
    run_body = ('    std::cout << "scores: " << ScoreClamp::clamp(-5) << \' \'\n'
                "              << ScoreClamp::clamp(42) << ' '\n"
                "              << ScoreClamp::clamp(120) << '\\n';\n")
    clamp_module = final_module.replace(run_body, "")
    architecture_module = clamp_module.replace("return std::clamp(value, 0, 100);", "return 0;")
    cmake = (project / "CMakeLists.txt").read_text()
    demo = ('\nadd_test(NAME demo COMMAND ScoreClamp)\n'
            'set_tests_properties(demo PROPERTIES PASS_REGULAR_EXPRESSION "scores: 0 42 100")\n')
    pending: list[str] = []
    config = persistence.UserConfig()
    runner = steps.StepRunner(project, config, invoke=lambda _prompt, _cwd: pending.pop(0),
                              attempts=1, progress=lambda message: print(message, flush=True))
    root = tk.Tk()
    root.geometry("1360x720+10+30")
    app = load_application().App(root, config=config, config_path=output / "user-config.json")
    root.geometry("1360x720+10+30")
    annotations: dict[str, Any] = {}

    def refresh() -> None:
        app.project = project
        app.show(session.open_project(project, config))
        app.panel.show(None)
        root.update()
        vertical = app.panel.frame.master
        vertical.sashpos(0, int(root.winfo_height() * 0.48))
        root.update()
        print("Refreshed: " + app.panel.queue_var.get(), flush=True)

    def box(widget: Any, bounds: dict[str, int]) -> list[int]:
        left = widget.winfo_rootx() - bounds["X"]
        top = widget.winfo_rooty() - bounds["Y"]
        return [max(1, left - 3), max(1, top - 3),
                min(bounds["Width"] - 1, left + widget.winfo_width() + 3),
                min(bounds["Height"] - 1, top + widget.winfo_height() + 3)]

    def snap(name: str, targets: list[tuple[Any, str]]) -> None:
        root.update()
        bounds = capture_window(root, output / name)
        annotations[name] = {"size": [bounds["Width"], bounds["Height"]],
                             "regions": [{"box": box(widget, bounds), "focus": focus}
                                         for widget, focus in targets]}
        for region in annotations[name]["regions"]:
            left, top, right, bottom = region["box"]
            assert 0 <= left < right <= bounds["Width"]
            assert 0 <= top < bottom <= bounds["Height"]
        (output / "highlights.json").write_text(json.dumps(annotations, indent=2) + "\n")
        print("Captured " + name, flush=True)

    def propose(title: str, files: dict[str, str]) -> steps.Proposal:
        pending.append(json.dumps({"title": title,
                                   "rationale": "Keep the C++ example small and verify each requirement with CTest.",
                                   "files": [{"path": path, "content": content} for path, content in files.items()]}))
        runner.prepare()
        proposal = runner.propose(prompt.StepRequest(runner.current_phase().value, 0, max_entities=5))
        if not proposal.ok:
            raise RuntimeError(proposal.error + "\n" + proposal.build.output + "\n" + proposal.test.output)
        app.panel.show(proposal)
        app.panel.detail_notebook.select(app.panel.details.master)
        root.update()
        return proposal

    try:
        runner.prepare()
        refresh()
        architecture = propose("Add ScoreClamp architecture", {"src/app/app.cppm": architecture_module})
        snap("cpp-architecture-proposal.png", [
            (app.panel.detail_notebook, "ScoreClamp type and method in the architecture delta"),
            (app.panel.signature_label.master, "Architecture build and test gates"),
        ])
        rejected = runner.reject(architecture, "Keep clamp as a stub until its implementation round.")
        app.panel.show_step(rejected)
        snap("cpp-architecture-rejected.png", [
            (app.panel.rationale, "Recorded rejection reason"),
            (app.panel.detail_notebook, "Retained C++ review evidence"),
        ])
        architecture = propose("Add ScoreClamp architecture", {"src/app/app.cppm": architecture_module})
        runner.approve(architecture)
        runner.approve_architecture()
        refresh()
        snap("cpp-architecture-gate.png", [
            (app.panel.phase_label, "Implementation phase after explicit architecture approval"),
            (app.panel.queue_label, "Current C++ callable and remaining queue"),
            (app.panel.buttons["propose_approach"], "Begin the first implementation approach"),
        ])
        while (target := implementation_queue.target_usr(store.load_state())) is not None:
            entity = runner.current_model().entities[target]
            name = entity.qualified_name
            if name.endswith("ScoreClamp::clamp"):
                plan = "Use std::clamp(value, 0, 100). Test nine boundary/extreme values and idempotence."
                files = {"src/app/app.cppm": clamp_module, "tests/smoke_test.cpp": final_test}
            elif name == "app::run":
                plan = "Print the three clamped values, return 0, and add the executable demo CTest."
                files = {"src/app/app.cppm": final_module, "CMakeLists.txt": cmake + demo}
            elif name == "main" and entity.file == "src/main.cpp":
                plan = "Call app::run and convert its result to process status 0 or 1. Retain the demo CTest."
                files = {"src/main.cpp": final_main}
            else:
                raise RuntimeError(f"Unexpected tutorial target {name} in {entity.file}")
            print("Implementation target: " + name, flush=True)
            pending.append(json.dumps({"plan": plan, "entities": [name], "files": list(files)}))
            approach = runner.propose_approach(prompt.StepRequest(prompt.IMPLEMENTATION, 0))
            assert approach.ok, approach.error
            app.panel.show_approach(approach)
            app.panel.detail_notebook.select(app.panel.approach_text.master)
            if name.endswith("ScoreClamp::clamp"):
                snap("cpp-implementation-approach.png", [
                    (app.panel.queue_label, "Current clamp implementation target"),
                    (app.panel.buttons["approve_approach"], "Approve the prose approach"),
                    (app.panel.detail_notebook, "Plan, expected entities, and files"),
                ])
            runner.approve_approach(approach)
            app.panel.show_approach(approach, approved=True)
            proposal = propose("Implement " + name, files)
            if name.endswith("ScoreClamp::clamp"):
                snap("cpp-implementation-tests.png", [
                    (app.panel.signature_label.master, "C++ implementation build and test gates"),
                    (app.panel.detail_notebook, "Method and C++ boundary-test delta"),
                    (app.panel.buttons["approve"], "Approve the implementation after passing gates"),
                ])
            runner.approve(proposal)
            refresh()
        capture_completed_views(root, app, snap)
        assert not pending
        print("C++ tutorial lifecycle completed with real build, CTest, and libclang gates.", flush=True)
    finally:
        root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
