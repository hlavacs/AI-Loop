"""Exercise source navigation, native Text editing, Unicode search, undo and disk saves in real Tk."""
from __future__ import annotations

import argparse
import json
import sys
import time
import tkinter as tk
from itertools import pairwise
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gui_acceptance import capture, load_application, require_visible

from icoda_core import clusters, persistence, session, views
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind, merge_external_names

SOURCE = """// Score Clamp: a small C++ example. 🎯
class ScoreClamp {
public:
    int clamp(int score) const {
        if (score < 0) return 0;
        if (score > 100) return 100;
        return score;
    }
};

int main() {
    ScoreClamp clamp;
    return clamp.clamp(42) == 42 ? 0 : 1;
}
"""


def click_node(root: tk.Tk, view: Any, node: str) -> None:
    root.update()
    for item, identity in view.item_nodes.items():
        if identity == node and view.canvas.type(item) == "rectangle":
            left, top, right, bottom = view.canvas.coords(item)
            x, y = int((left + right) / 2), int((top + bottom) / 2)
            view.canvas.event_generate("<ButtonPress-1>", x=x, y=y)
            view.canvas.event_generate("<ButtonRelease-1>", x=x, y=y)
            root.update()
            return
    raise AssertionError(f"no visible node for {node}")


def verify_file_boxes(root: tk.Tk, app: Any, output: Path) -> None:
    """A Worktrees-shaped model must stay visible beside the fixed hierarchy, even after repeated Fit."""
    project = output.resolve() / "four-files"
    files = ("src/app/app.cppm", "src/main.cpp", "src/work_tree/work_tree.cppm", "tests/smoke_test.cpp")
    model = DerivedModel(str(project))
    for file in files:
        path = project / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// source\n", encoding="utf-8")
        model.files[file] = FileInfo(file)
    for source, target in pairwise(files):
        model.add_edge(Edge(EdgeKind.IMPORTS, source, target, source, 1))
    merge_external_names(model, "std", ["vector"])
    model.add_edge(Edge(EdgeKind.USES_TYPE, files[2], "external:std", files[2], 1))
    clustering = clusters.cluster_files(model)
    root.update()
    geometry = root.geometry()
    root.geometry("1200x760")
    app.show(session.OpenedProject(project, model, clustering, views.layout_file_view(model, clustering), None, []))
    root.update()
    for _ in range(5):
        app.view.fit()
        boxes = app.view.node_boxes
        assert set(files) <= boxes.keys()
        for file in files:
            left, top, right, bottom = boxes[file]
            assert left >= 0 and top >= 44 and bottom < app.canvas.winfo_height()
            assert right < app.canvas.winfo_width() - 294, (file, boxes[file])
            assert right - left >= 40 and bottom - top >= 20
        for index, file in enumerate(files):
            a = boxes[file]
            for other in files[index + 1:]:
                b = boxes[other]
                assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
    before = {file: boxes[file] for file in files}
    app.view.fit()
    assert all(abs(a - b) < 2 for file in files for a, b in zip(before[file], app.view.node_boxes[file]))
    for file in files:
        click_node(root, app.view, file)
        assert app.source_editor.document.relative == file
    capture(root, output / "file-boxes.png")
    app.source_editor.clear()
    root.geometry(geometry)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project = args.output.resolve() / "score-clamp"
    project.mkdir(parents=True, exist_ok=True)
    source = project / "main.cpp"
    source.write_text(SOURCE, encoding="utf-8")
    model = DerivedModel(str(project))
    model.files["main.cpp"] = FileInfo("main.cpp", unit="source")
    model.add_entity(Entity("clamp", Kind.CLASS, "ScoreClamp", "ScoreClamp", "main.cpp", 2))
    model.add_entity(Entity("clamp::clamp", Kind.METHOD, "clamp", "ScoreClamp::clamp", "main.cpp", 4,
                            parent="clamp", signature="int clamp(int score) const"))
    model.add_entity(Entity("main", Kind.FUNCTION, "main", "main", "main.cpp", 11))
    model.add_edge(Edge(EdgeKind.CALLS, "main", "clamp::clamp", "main.cpp", 13))
    clustering = clusters.cluster_files(model)
    opened = session.OpenedProject(project, model, clustering, views.layout_file_view(model, clustering), None, [])
    root = tk.Tk()
    try:
        app = load_application().App(root, config=persistence.UserConfig(), config_path=args.output / "config.json")
        verify_file_boxes(root, app, args.output)
        app.show(opened)
        root.update()
        for _ in range(12):
            app.view.fit()
        assert 0 < app.view.scale <= 2.5
        left, top, right, bottom = app.view.node_boxes["main.cpp"]
        assert 0 <= left < right < app.canvas.winfo_width() - 294
        assert 44 <= top < bottom < app.canvas.winfo_height()
        refreshes = []
        app.reload = lambda: refreshes.append(True)
        pane = app.source_editor
        click_node(root, app.view, "main.cpp")
        assert app.side_views.select() == str(pane.frame) and pane.text.index("insert") == "1.0"
        app.views.select(app.class_view.frame)
        click_node(root, app.class_view, "clamp")
        assert pane.text.index("insert") == "2.0"
        app.call_view.set_root("main")
        app.views.select(app.call_view.frame)
        click_node(root, app.call_view, "clamp::clamp")
        assert pane.text.index("insert") == "4.0"

        # Unicode before the match must not shift the Text selection on Tcl 8 or 9.
        pane.query.set("score")
        pane.match_case.set(True)
        pane.replacement.set("value")
        pane.goto(1)
        pane.buttons["Next"].invoke()
        start, end = pane.text.tag_ranges("match")
        assert pane.text.get(start, end) == "score" and str(start) == "4.18"
        pane.buttons["Replace"].invoke()
        root.update()
        replaced_one = pane.content()
        assert "int value" in replaced_one
        pane.buttons["Undo"].invoke()
        assert pane.content() == SOURCE
        pane.buttons["Redo"].invoke()
        assert pane.content() == replaced_one
        pane.buttons["Undo"].invoke()
        pane.buttons["All"].invoke()
        root.update()
        replaced_all = pane.content()
        assert "score" not in replaced_all and "ScoreClamp" in replaced_all
        pane.buttons["Undo"].invoke()
        assert pane.content() == SOURCE
        pane.buttons["Redo"].invoke()
        assert pane.content() == replaced_all
        app.open_editor("main.cpp", 4)
        assert pane.dirty and pane.content() == replaced_all

        pane.buttons["Save"].invoke()
        deadline = time.monotonic() + 2
        while not refreshes and time.monotonic() < deadline:
            root.update()
            time.sleep(.02)
        assert refreshes and not pane.dirty and source.read_text(encoding="utf-8") == replaced_all
        # Reload really reads the current disk version.
        source.write_text(replaced_all + "// Disk change\n", encoding="utf-8")
        pane.buttons["Reload"].invoke()
        assert pane.content().endswith("// Disk change\n") and not pane.dirty
        pane.goto(4)
        pane.query.set("value")
        pane.find()
        require_visible(root, pane.buttons)
        bounds = capture(root, args.output / "source-editor.png")
        (args.output / "editor-gui.json").write_text(json.dumps({
            "passed": True, "bounds": bounds, "saved_source": str(source),
            "checks": ["visible file boxes", "repeated Fit", "file/class/function clicks", "Unicode find", "literal replace", "replace all",
                       "undo/redo", "unsaved navigation", "save", "analysis refresh", "reload"]}, indent=2) + "\n")
        print("PASS: real Tk source navigation, search/replace, undo/redo, save/reload, visible controls, screenshot")
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
