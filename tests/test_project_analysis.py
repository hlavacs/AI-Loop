from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ai_loop.project_analysis import analyze_project
from ai_loop.project_analysis_view import (
    ProjectAnalysisController,
    add_project_analysis_exclusion,
    remove_project_analysis_exclusion,
)

FIXTURE_PROJECT = Path(__file__).parent / "fixtures" / "project_analysis"


def _file_by_path(model: dict, path: str) -> dict:
    return next(
        file_model for file_model in model["files"] if file_model["path"] == path
    )


def test_analyze_project_discovers_python_hierarchy() -> None:
    model = analyze_project(FIXTURE_PROJECT)
    python_file = _file_by_path(model, "sample.py")

    assert {item["name"] for item in python_file["classes"]} == {"Named", "Greeter"}
    assert {item["name"] for item in python_file["functions"]} == {
        "greet",
        "format_message",
        "load_greeter",
    }
    greeter = next(item for item in python_file["classes"] if item["name"] == "Greeter")
    assert greeter["bases"] == ["Named"]
    assert greeter["methods"] == ["Greeter.greet"]
    assert any(
        relationship
        == {
            "kind": "member_of",
            "source": "Greeter.greet",
            "target": "Greeter",
        }
        for relationship in python_file["relationships"]
    )
    assert {item["name"] for item in python_file["data_types"]} >= {
        "Identifier",
        "name",
    }


def test_analyze_project_discovers_cpp_hierarchy_and_metadata() -> None:
    model = analyze_project(FIXTURE_PROJECT)
    header = _file_by_path(model, "include/widget.hpp")
    implementation = _file_by_path(model, "src/widget.cpp")

    assert {item["name"] for item in header["classes"]} == {
        "Component",
        "Widget",
        "Point",
    }
    assert {item["name"] for item in header["functions"]} >= {"name", "Widget", "add"}
    assert {item["name"] for item in implementation["functions"]} == {
        "Widget",
        "name",
        "add",
    }
    widget = next(item for item in header["classes"] if item["name"] == "Widget")
    assert widget["bases"] == ["Component"]
    assert {item["name"] for item in header["data_types"]} >= {
        "Point",
        "Mode",
        "WidgetId",
    }

    assert model["file_count"] == 3
    assert model["languages"] == {"python": 1, "cpp": 2}
    assert model["line_count"] == sum(item["line_count"] for item in model["files"])
    assert json.loads(json.dumps(model)) == model


def test_analyze_project_discovers_all_cpp_file_extensions(tmp_path: Path) -> None:
    cpp_extensions = (
        ".h",
        ".h++",
        ".hh",
        ".hpp",
        ".hxx",
        ".cc",
        ".cpp",
        ".cxx",
        ".c++",
        ".ixx",
        ".ccm",
        ".cppm",
        ".cxxm",
        ".c++m",
        ".mpp",
        ".mxx",
    )
    for index, extension in enumerate(cpp_extensions):
        (tmp_path / f"source_{index}{extension}").write_text(
            f"int function_{index}();\n", encoding="utf-8"
        )

    model = analyze_project(tmp_path)

    assert {Path(file_model["path"]).suffix for file_model in model["files"]} == set(
        cpp_extensions
    )
    assert {file_model["language"] for file_model in model["files"]} == {"cpp"}
    assert model["languages"] == {"python": 0, "cpp": len(cpp_extensions)}


def test_analyze_project_aggregates_insights_and_platform_capabilities() -> None:
    model = analyze_project(FIXTURE_PROJECT)
    insights = model["insights"]

    assert insights["file_count"] == 3
    assert insights["line_count"] == model["line_count"]
    assert insights["per_language"]["python"] == {
        "file_count": 1,
        "line_count": 20,
    }
    assert insights["per_language"]["cpp"]["file_count"] == 2
    assert insights["class_count"] == 5
    assert insights["function_count"] == 9
    assert insights["data_type_count"] == 5
    assert insights["issue_count"] == 0
    assert insights["files_with_issues"] == 0
    assert insights["multiplatform_capable"] is True
    assert set(insights["detected_platforms"]) >= {
        "windows",
        "linux",
        "macos",
    }
    assert insights["platforms"]["windows"]["file_count"] == 2


def test_analyze_project_records_python_and_cpp_platform_markers() -> None:
    model = analyze_project(FIXTURE_PROJECT)
    python_markers = _file_by_path(model, "sample.py")["platform_markers"]
    cpp_markers = _file_by_path(model, "include/widget.hpp")["platform_markers"]

    assert any(
        marker["platform"] == "windows" and marker["kind"] == "branch"
        for marker in python_markers
    )
    assert {marker["marker"] for marker in python_markers} >= {
        "sys.platform",
        "os.name",
        "platform.system()",
    }
    assert any(
        marker["marker"] == "_WIN32" and marker["kind"] == "preprocessor_guard"
        for marker in cpp_markers
    )
    assert any(
        marker["marker"] == "windows.h" and marker["kind"] == "platform_include"
        for marker in cpp_markers
    )
    assert {marker["platform"] for marker in cpp_markers} >= {
        "windows",
        "linux",
        "macos",
    }


def test_analyze_project_rejects_invalid_roots(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        analyze_project(missing)

    source_file = tmp_path / "single.py"
    source_file.write_text("pass\n", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        analyze_project(source_file)


def test_analyze_project_excludes_folder_subtrees(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    generated = tmp_path / "generated"
    (generated / "cache" / "nested").mkdir(parents=True)
    (generated / "keep.py").write_text("KEEP = True\n", encoding="utf-8")
    (generated / "cache" / "skip.py").write_text("SKIP = True\n", encoding="utf-8")
    (generated / "cache" / "nested" / "skip.cpp").write_text(
        "int skipped();\n", encoding="utf-8"
    )
    (tmp_path / "other" / "cache").mkdir(parents=True)
    (tmp_path / "other" / "cache" / "included.py").write_text(
        "INCLUDED = True\n", encoding="utf-8"
    )

    model = analyze_project(tmp_path, exclude_folders=["generated/cache/"])

    assert {file_model["path"] for file_model in model["files"]} == {
        "generated/keep.py",
        "main.py",
        "other/cache/included.py",
    }
    assert model["file_count"] == 3
    assert model["languages"] == {"python": 3, "cpp": 0}
    assert model["insights"]["file_count"] == 3
    assert model["insights"]["per_language"]["cpp"]["file_count"] == 0


def test_analyze_project_default_matches_explicit_no_exclusions(tmp_path: Path) -> None:
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "included.py").write_text(
        "INCLUDED = True\n", encoding="utf-8"
    )

    default_model = analyze_project(tmp_path)

    assert default_model == analyze_project(tmp_path, exclude_folders=None)
    assert [file_model["path"] for file_model in default_model["files"]] == [
        "source/included.py"
    ]


def test_project_analysis_exclusion_selection_is_relative_unique_and_removable(
    tmp_path: Path,
) -> None:
    excluded = tmp_path / "generated" / "cache"
    excluded.mkdir(parents=True)

    selection = add_project_analysis_exclusion((), tmp_path, excluded)

    assert selection == ("generated/cache",)
    assert (
        add_project_analysis_exclusion(
            selection, tmp_path, excluded.parent / "nested" / ".." / "cache"
        )
        == selection
    )
    assert remove_project_analysis_exclusion(selection, "generated/cache") == ()


def test_project_analysis_exclusion_rejects_folder_outside_project(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ValueError, match="outside project directory"):
        add_project_analysis_exclusion((), project, tmp_path / "outside")


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a Tk display")
def test_project_analysis_excluded_folder_names_populate_listbox() -> None:
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        pytest.skip("Tk is not installed")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk cannot connect to a display")
    root.withdraw()

    try:
        from ai_loop_gui import AiLoopGui

        gui = AiLoopGui.__new__(AiLoopGui)
        gui.help_widget = lambda widget, _text: widget
        parent = ttk.Frame(root)
        gui._build_project_analysis_frame(parent)

        gui._set_analysis_excluded_folder_values(
            ("generated/cache", "build/output")
        )
        root.update_idletasks()

        assert gui.analysis_excluded_folders_var.get() == (
            "generated/cache",
            "build/output",
        )
        assert gui._analysis_excluded_folder_values() == (
            "generated/cache",
            "build/output",
        )
        assert gui.analysis_excluded_folders_listbox.get(0, tk.END) == (
            "generated/cache",
            "build/output",
        )
    finally:
        root.destroy()


def _find_node(root, *, kind: str, label: str):
    if root.kind == kind and root.label == label:
        return root
    for child in root.children:
        if found := _find_node(child, kind=kind, label=label):
            return found
    return None


def test_project_analysis_controller_builds_file_and_symbol_tree() -> None:
    controller = ProjectAnalysisController(analyze_project(FIXTURE_PROJECT))

    assert controller.root_node.kind == "project"
    assert controller.root_node.label == "project_analysis"
    assert [node.label for node in controller.root_node.children] == [
        "include/widget.hpp",
        "sample.py",
        "src/widget.cpp",
    ]
    python_file = controller.root_node.children[1]
    assert [node.label for node in python_file.children] == [
        "Classes (2)",
        "Functions (3)",
        "Data Types (2)",
    ]
    assert [node.label for node in python_file.children[0].children] == [
        "Named",
        "Greeter",
    ]


@pytest.mark.parametrize(
    ("kind", "label", "relative_path", "line_range"),
    [
        ("class", "Greeter", "sample.py", (10, 12)),
        ("function", "format_message", "sample.py", (15, 16)),
        ("type_alias", "Identifier", "sample.py", (3, 3)),
        ("enum", "Mode", "include/widget.hpp", (21, 21)),
    ],
)
def test_project_analysis_controller_resolves_symbol_source_ranges(
    kind: str, label: str, relative_path: str, line_range: tuple[int, int]
) -> None:
    controller = ProjectAnalysisController(analyze_project(FIXTURE_PROJECT))
    node = _find_node(controller.root_node, kind=kind, label=label)

    assert node is not None
    location = controller.resolve_selection(node.node_id)
    assert location is not None
    assert location.path == (FIXTURE_PROJECT / relative_path).resolve()
    assert location.line_range == line_range


def test_project_analysis_controller_resolves_file_and_ignores_groups() -> None:
    controller = ProjectAnalysisController(analyze_project(FIXTURE_PROJECT))
    python_file = controller.root_node.children[1]

    file_location = controller.resolve_selection(python_file.node_id)
    assert file_location is not None
    assert file_location.path == (FIXTURE_PROJECT / "sample.py").resolve()
    assert file_location.line_range == (1, 20)
    assert controller.resolve_selection(python_file.children[0].node_id) is None


def test_project_analysis_controller_exposes_navigable_issue_nodes(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "broken.py"
    source_path.write_text("valid = True\nif valid print('broken')\n", encoding="utf-8")
    controller = ProjectAnalysisController(analyze_project(tmp_path))
    file_node = controller.root_node.children[0]
    issue_group = file_node.children[0]
    issue_node = issue_group.children[0]

    assert issue_group.node_id == "file:0:issues"
    assert issue_node.node_id == "file:0:issues:0"
    assert issue_node.kind == "syntax_error"
    assert issue_node.label
    assert controller.node(issue_node.node_id) is issue_node
    location = controller.resolve_selection(issue_node.node_id)
    assert location is not None
    assert location.path == source_path.resolve()
    assert location.line_range == (2, 2)


def test_project_analysis_controller_exposes_gui_independent_summaries() -> None:
    controller = ProjectAnalysisController(analyze_project(FIXTURE_PROJECT))

    assert controller.insights["class_count"] == 5
    assert controller.platform_summary["windows"]["file_count"] == 2
    assert "Symbols: 5 classes, 9 functions, 5 data types" in (
        controller.insights_summary
    )
    assert "Windows (2 files" in controller.insights_summary
    assert "multiplatform signals detected" in controller.insights_summary


def test_project_analysis_controller_builds_serializable_class_diagram() -> None:
    controller = ProjectAnalysisController(analyze_project(FIXTURE_PROJECT))
    diagram = controller.class_diagram()
    nodes_by_label = {node["label"]: node for node in diagram["nodes"]}

    assert json.loads(json.dumps(diagram)) == diagram
    assert {"Named", "Greeter", "Component", "Widget"} <= nodes_by_label.keys()
    assert {
        "source": nodes_by_label["Greeter"]["id"],
        "target": nodes_by_label["Named"]["id"],
        "kind": "inherits",
    } in diagram["edges"]
    assert {
        "source": nodes_by_label["Widget"]["id"],
        "target": nodes_by_label["Component"]["id"],
        "kind": "inherits",
    } in diagram["edges"]
    assert (
        nodes_by_label["Greeter"]["tree_node_id"]
        == nodes_by_label["Greeter"]["id"]
    )
    assert nodes_by_label["Greeter"]["source_location"] == {
        "path": "sample.py",
        "line": 10,
        "end_line": 12,
    }


def test_project_analysis_controller_builds_local_dependency_diagram() -> None:
    controller = ProjectAnalysisController(analyze_project(FIXTURE_PROJECT))
    diagram = controller.dependency_diagram()
    nodes_by_label = {node["label"]: node for node in diagram["nodes"]}

    assert json.loads(json.dumps(diagram)) == diagram
    assert {
        "source": nodes_by_label["src/widget.cpp"]["id"],
        "target": nodes_by_label["include/widget.hpp"]["id"],
        "kind": "includes",
    } in diagram["edges"]
    assert nodes_by_label["src/widget.cpp"]["source_location"]["line"] == 1
    assert all(
        {"id", "label", "kind", "source_location", "x", "y"} <= node.keys()
        for node in diagram["nodes"]
    )


def test_dependency_diagram_resolves_project_local_python_import(
    tmp_path: Path,
) -> None:
    (tmp_path / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("import helper\n", encoding="utf-8")
    controller = ProjectAnalysisController(analyze_project(tmp_path))
    diagram = controller.dependency_diagram()
    nodes_by_label = {node["label"]: node for node in diagram["nodes"]}

    assert {
        "source": nodes_by_label["main.py"]["id"],
        "target": nodes_by_label["helper.py"]["id"],
        "kind": "imports",
    } in diagram["edges"]
