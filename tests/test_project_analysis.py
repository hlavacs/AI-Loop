from __future__ import annotations

import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

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
    named = next(item for item in python_file["classes"] if item["name"] == "Named")
    assert [member["name"] for member in named["data_members"]] == ["name"]
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


def test_analyze_project_attributes_python_calls_between_project_classes(
    tmp_path: Path,
) -> None:
    (tmp_path / "calls.py").write_text(
        "class Service:\n"
        "    def ping(self) -> str:\n"
        "        return 'pong'\n"
        "\n"
        "\n"
        "class Client:\n"
        "    def run(self, service: Service) -> str:\n"
        "        external.notify()\n"
        "        return service.ping()\n",
        encoding="utf-8",
    )

    model = analyze_project(tmp_path)

    assert model["call_relationships"] == [
        {
            "caller_class": "Client",
            "callee_class": "Service",
            "caller_method": "Client.run",
            "callee_method": "Service.ping",
            "caller_path": "calls.py",
            "callee_path": "calls.py",
            "call_path": "calls.py",
            "callee_method_path": "calls.py",
            "line": 9,
            "callee_line": 2,
        }
    ]


def test_analyze_project_attributes_calls_between_methods_of_same_class(
    tmp_path: Path,
) -> None:
    (tmp_path / "workflow.py").write_text(
        "class Workflow:\n"
        "    def run(self) -> str:\n"
        "        return self.finish()\n"
        "\n"
        "    def finish(self) -> str:\n"
        "        return 'done'\n",
        encoding="utf-8",
    )

    model = analyze_project(tmp_path)

    assert model["call_relationships"] == [
        {
            "caller_class": "Workflow",
            "callee_class": "Workflow",
            "caller_method": "Workflow.run",
            "callee_method": "Workflow.finish",
            "caller_path": "workflow.py",
            "callee_path": "workflow.py",
            "call_path": "workflow.py",
            "callee_method_path": "workflow.py",
            "line": 3,
            "callee_line": 5,
        }
    ]
    diagram = ProjectAnalysisController(model).call_graph_diagram()
    nodes_by_label = {node["label"]: node for node in diagram["nodes"]}
    assert set(nodes_by_label) == {"run", "finish"}
    assert diagram["edges"][0]["source"] == nodes_by_label["run"]["id"]
    assert diagram["edges"][0]["target"] == nodes_by_label["finish"]["id"]
    assert [group["label"] for group in diagram["groups"]] == ["Workflow"]


def test_analyze_project_discovers_slots_destructured_and_augmented_members(
    tmp_path: Path,
) -> None:
    (tmp_path / "members.py").write_text(
        "class Slotted:\n"
        "    __slots__ = ('name', 'count')\n"
        "\n"
        "class Measurements:\n"
        "    def update(self) -> None:\n"
        "        self.left, self.right = (1, 2)\n"
        "        self.total += 1\n",
        encoding="utf-8",
    )

    model = analyze_project(tmp_path)
    classes = {
        class_model["name"]: class_model
        for class_model in model["files"][0]["classes"]
    }

    assert [
        member["name"] for member in classes["Slotted"]["data_members"]
    ] == ["name", "count"]
    assert [
        member["name"] for member in classes["Measurements"]["data_members"]
    ] == ["left", "right", "total"]


def test_analyze_project_discovers_cpp_brace_initialized_members(
    tmp_path: Path,
) -> None:
    (tmp_path / "sample.hpp").write_text(
        "class Sample {\n"
        "public:\n"
        "    int count{0};\n"
        "    std::string name{\"ready\"};\n"
        "};\n",
        encoding="utf-8",
    )

    model = analyze_project(tmp_path)
    sample = model["files"][0]["classes"][0]

    assert [member["name"] for member in sample["data_members"]] == [
        "count",
        "name",
    ]


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
    point = next(item for item in header["classes"] if item["name"] == "Point")
    assert [member["name"] for member in point["data_members"]] == ["x", "y"]
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
        "Functions (2)",
        "Data Types (2)",
    ]
    assert [node.label for node in python_file.children[0].children] == [
        "Named",
        "Greeter",
    ]
    named, greeter = python_file.children[0].children
    assert [(node.kind, node.label) for node in named.children] == [
        ("data_member", "name")
    ]
    assert [(node.kind, node.label) for node in greeter.children] == [
        ("method", "greet")
    ]
    assert named.summary == ("Named — sample.py, lines 6–7; 1 data member, 0 methods")
    assert greeter.summary == (
        "Greeter — sample.py, lines 10–12; 0 data members, 1 method"
    )
    assert [node.label for node in python_file.children[1].children] == [
        "format_message",
        "load_greeter",
    ]


def test_project_analysis_controller_lists_cpp_methods_only_under_their_class() -> None:
    controller = ProjectAnalysisController(analyze_project(FIXTURE_PROJECT))
    header, _, implementation = controller.root_node.children

    assert [node.label for node in header.children[1].children] == ["add"]
    assert [node.label for node in implementation.children[0].children] == ["add"]
    assert not any(
        node.kind == "method"
        for file_node in controller.root_node.children
        for group in file_node.children
        if group.kind == "group" and group.label.startswith("Functions")
        for node in group.children
    )


def test_project_analysis_controller_descriptions_have_two_to_five_sentences() -> None:
    model = analyze_project(FIXTURE_PROJECT)
    python_file = _file_by_path(model, "sample.py")
    greeter_symbol = next(
        symbol for symbol in python_file["classes"] if symbol["name"] == "Greeter"
    )
    greet_symbol = next(
        symbol for symbol in python_file["functions"] if symbol["name"] == "greet"
    )
    greeter_symbol["docstring"] = (
        "Creates greeting objects. It coordinates inherited naming behavior."
    )
    greet_symbol["leading_comment"] = "# Produces a greeting for one recipient."

    controller = ProjectAnalysisController(model)
    greeter = _find_node(controller.root_node, kind="class", label="Greeter")

    assert greeter is not None
    method = next(node for node in greeter.children if node.kind == "method")
    assert greeter.description.startswith("Creates greeting objects.")
    assert method.description.startswith("Produces a greeting for one recipient.")
    for node in (greeter, method):
        sentence_count = len(re.findall(r"[.!?](?=\s|$)", node.description))
        assert 2 <= sentence_count <= 5


def test_analyzer_uses_source_documentation_for_hover_descriptions(
    tmp_path: Path,
) -> None:
    assert ProjectAnalysisController._clean_documentation(
        "Uses ``items`` through :meth:`run`."
    ) == "Uses items through run."

    (tmp_path / "documented.py").write_text(
        "class ReportBuilder:\n"
        "    \"\"\"Builds reports from stored job data. It formats a concise result.\"\"\"\n"
        "    def render(self, job_id: str) -> str:\n"
        "        \"\"\"Renders one job as readable text.\"\"\"\n"
        "        return job_id\n",
        encoding="utf-8",
    )
    (tmp_path / "documented.hpp").write_text(
        "/** Represents one queued operation. */\n"
        "class Operation {\n"
        "public:\n"
        "    // Executes the queued operation.\n"
        "    void execute();\n"
        "};\n",
        encoding="utf-8",
    )

    model = analyze_project(tmp_path)
    python_model = _file_by_path(model, "documented.py")
    cpp_model = _file_by_path(model, "documented.hpp")
    assert python_model["classes"][0]["docstring"].startswith("Builds reports")
    assert python_model["functions"][0]["docstring"].startswith("Renders one job")
    assert cpp_model["classes"][0]["leading_comment"].startswith("/**")
    assert cpp_model["functions"][0]["leading_comment"].lstrip().startswith("//")

    controller = ProjectAnalysisController(model)
    report = _find_node(controller.root_node, kind="class", label="ReportBuilder")
    operation = _find_node(controller.root_node, kind="class", label="Operation")
    assert report is not None and operation is not None
    render = next(node for node in report.children if node.kind == "method")
    execute = next(node for node in operation.children if node.kind == "method")
    assert report.description.startswith("Builds reports from stored job data.")
    assert render.description.startswith("Renders one job as readable text.")
    assert operation.description.startswith("Represents one queued operation.")
    assert execute.description.startswith("Executes the queued operation.")
    for node in (report, render, operation, execute):
        sentence_count = len(re.findall(r"[.!?](?=\s|$)", node.description))
        assert 2 <= sentence_count <= 5

    diagram_node = next(
        node
        for node in controller.class_diagram()["nodes"]
        if node["label"] == "ReportBuilder"
    )
    assert diagram_node["description"] == report.description


def test_project_analysis_controller_navigates_cpp_method_to_definition() -> None:
    controller = ProjectAnalysisController(analyze_project(FIXTURE_PROJECT))
    widget = _find_node(controller.root_node, kind="class", label="Widget")

    assert widget is not None
    assert controller.resolve_selection(widget.node_id).line_range == (10, 14)
    methods = {node.label: node for node in widget.children}
    constructor_location = controller.resolve_selection(methods["Widget"].node_id)
    name_location = controller.resolve_selection(methods["name"].node_id)

    assert constructor_location is not None
    assert constructor_location.path == (FIXTURE_PROJECT / "src/widget.cpp").resolve()
    assert constructor_location.line_range == (3, 3)
    assert name_location is not None
    assert name_location.path == (FIXTURE_PROJECT / "src/widget.cpp").resolve()
    assert name_location.line_range == (5, 7)


def test_project_analysis_gui_click_navigation() -> None:
    from ai_loop_gui import AiLoopGui

    controller = ProjectAnalysisController(analyze_project(FIXTURE_PROJECT))
    widget = _find_node(controller.root_node, kind="class", label="Widget")
    assert widget is not None
    method = next(node for node in widget.children if node.kind == "method")

    class FakeTree:
        def __init__(self) -> None:
            self.rows = {1: widget.node_id, 2: method.node_id}
            self.selected: list[str] = []
            self.focused: list[str] = []

        def identify_row(self, y: int) -> str:
            return self.rows.get(y, "")

        def selection_set(self, node_id: str) -> None:
            self.selected.append(node_id)

        def focus(self, node_id: str) -> None:
            self.focused.append(node_id)

    class FakeNotebook:
        def __init__(self) -> None:
            self.selected: list[object] = []

        def select(self, tab: object) -> None:
            self.selected.append(tab)

    gui = AiLoopGui.__new__(AiLoopGui)
    gui._analysis_controller = controller
    gui.analysis_tree = FakeTree()
    gui.analysis_detail_notebook = FakeNotebook()
    gui.analysis_source_frame = object()
    gui.analysis_member_frame = object()
    gui._analysis_member_class_id = None
    gui._refresh_analysis_member_diagram = lambda: None
    shown: list[str] = []
    gui._show_analysis_tree_node = shown.append

    gui.on_analysis_tree_clicked(SimpleNamespace(y=1))
    double_click_result = gui.on_analysis_tree_double_clicked(SimpleNamespace(y=2))

    assert shown == [widget.node_id, method.node_id]
    assert gui.analysis_tree.selected == [widget.node_id, method.node_id]
    assert gui.analysis_tree.focused == [widget.node_id, method.node_id]
    assert gui.analysis_detail_notebook.selected == [
        gui.analysis_member_frame,
        gui.analysis_source_frame,
    ]
    assert double_click_result == "break"


def test_project_analysis_gui_hover_uses_controller_descriptions() -> None:
    from ai_loop_gui import AiLoopGui

    controller = ProjectAnalysisController(analyze_project(FIXTURE_PROJECT))
    widget = _find_node(controller.root_node, kind="class", label="Widget")
    assert widget is not None
    method = next(node for node in widget.children if node.kind == "method")
    group = controller.root_node.children[0].children[0]

    class FakeTree:
        def identify_row(self, y: int) -> str:
            return {1: widget.node_id, 2: method.node_id, 3: group.node_id}.get(
                y, ""
            )

    class FakeTooltip:
        def __init__(self) -> None:
            self.hidden = 0
            self.scheduled: list[tuple[object, str]] = []

        def hide(self) -> None:
            self.hidden += 1

        def _schedule_show(self, tree: object, text: str) -> None:
            self.scheduled.append((tree, text))

    gui = AiLoopGui.__new__(AiLoopGui)
    gui._analysis_controller = controller
    gui._analysis_tooltip_node_id = None
    gui.analysis_tree = FakeTree()
    gui.help_tooltip = FakeTooltip()

    gui.on_analysis_tree_hover(SimpleNamespace(y=1))
    gui.on_analysis_tree_hover(SimpleNamespace(y=1))
    gui.on_analysis_tree_hover(SimpleNamespace(y=2))
    gui.on_analysis_tree_hover(SimpleNamespace(y=3))

    assert gui.help_tooltip.scheduled == [
        (gui.analysis_tree, widget.description),
        (gui.analysis_tree, method.description),
    ]
    assert gui._analysis_tooltip_node_id is None


def test_project_analysis_gui_class_selection_focuses_member_graph() -> None:
    from ai_loop_gui import AiLoopGui

    controller = ProjectAnalysisController(analyze_project(FIXTURE_PROJECT))
    widget = _find_node(controller.root_node, kind="class", label="Widget")
    assert widget is not None

    class FakeTree:
        def selection(self) -> tuple[str, ...]:
            return (widget.node_id,)

    gui = AiLoopGui.__new__(AiLoopGui)
    gui._analysis_controller = controller
    gui._analysis_member_class_id = None
    gui.analysis_tree = FakeTree()
    refreshed: list[str | None] = []
    shown: list[str] = []
    gui._refresh_analysis_member_diagram = lambda: refreshed.append(
        gui._analysis_member_class_id
    )
    gui._show_analysis_tree_node = shown.append

    gui.on_analysis_tree_selected()
    gui._show_all_analysis_class_members()

    assert refreshed == [widget.node_id, None]
    assert shown == [widget.node_id]
    assert gui._analysis_member_class_id is None


def test_project_analysis_controller_orders_class_members_by_source(
    tmp_path: Path,
) -> None:
    (tmp_path / "mixed.py").write_text(
        "class Mixed:\n"
        "    first: int\n"
        "    def convert(self) -> str:\n"
        "        return str(self.first)\n"
        "    second: str\n",
        encoding="utf-8",
    )
    controller = ProjectAnalysisController(analyze_project(tmp_path))
    class_node = _find_node(controller.root_node, kind="class", label="Mixed")

    assert class_node is not None
    assert [(node.kind, node.label) for node in class_node.children] == [
        ("data_member", "first"),
        ("method", "convert"),
        ("data_member", "second"),
    ]
    assert class_node.summary == (
        "Mixed — mixed.py, lines 1–5; 2 data members, 1 method"
    )
    assert [
        controller.resolve_selection(node.node_id).line for node in class_node.children
    ] == [2, 3, 5]


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
    greeter_description = nodes_by_label["Greeter"]["description"]
    assert "Greeter is a class" in greeter_description
    assert 2 <= len(re.findall(r"[.!?](?=\s|$)", greeter_description)) <= 5


def test_project_analysis_controller_builds_serializable_call_graph(
    tmp_path: Path,
) -> None:
    (tmp_path / "calls.py").write_text(
        "class Service:\n"
        "    def ping(self) -> str:\n"
        "        return 'pong'\n"
        "\n"
        "    def idle(self) -> None:\n"
        "        pass\n"
        "\n"
        "class Client:\n"
        "    def run(self, service: Service) -> str:\n"
        "        return service.ping()\n",
        encoding="utf-8",
    )
    controller = ProjectAnalysisController(analyze_project(tmp_path))

    diagram = controller.call_graph_diagram()
    nodes_by_label = {node["label"]: node for node in diagram["nodes"]}

    assert json.loads(json.dumps(diagram)) == diagram
    assert set(nodes_by_label) == {"ping", "idle", "run"}
    assert {node["kind"] for node in diagram["nodes"]} == {"method"}
    assert diagram["total_member_count"] == 3
    assert diagram["total_class_count"] == 2
    assert diagram["shown_member_count"] == 3
    assert diagram["summary"] == (
        "Showing 3 members across 2 classes and 1 resolved call."
    )
    assert {group["label"] for group in diagram["groups"]} == {
        "Service",
        "Client",
    }
    service_description = nodes_by_label["ping"]["description"]
    assert "Service.ping is a method" in service_description
    assert 2 <= len(re.findall(r"[.!?](?=\s|$)", service_description)) <= 5
    assert nodes_by_label["ping"]["subtitle"] == (
        "1 incoming · 0 outgoing"
    )
    assert nodes_by_label["run"]["subtitle"] == (
        "0 incoming · 1 outgoing"
    )
    assert ":member:" in nodes_by_label["ping"]["tree_node_id"]
    assert nodes_by_label["ping"]["source_location"] == {
        "path": "calls.py",
        "line": 2,
        "end_line": 3,
    }
    assert {
        "source": nodes_by_label["run"]["id"],
        "target": nodes_by_label["ping"]["id"],
        "kind": "calls",
        "callee_method": "Service.ping",
        "call_line": 10,
        "callee_line": 2,
    } in diagram["edges"]

    client_group = next(
        group for group in diagram["groups"] if group["label"] == "Client"
    )
    focused = controller.member_graph_diagram(
        selected_class_id=client_group["tree_node_id"]
    )
    assert {node["label"] for node in focused["nodes"]} == {"run", "ping"}
    assert {group["label"] for group in focused["groups"]} == {
        "Client",
        "Service",
    }
    assert focused["summary"] == (
        "Client: 1 direct member; 1 called member in 1 other class."
    )


def test_call_graph_can_reveal_methods_when_no_calls_are_resolved(
    tmp_path: Path,
) -> None:
    (tmp_path / "utility.py").write_text(
        "class Utility:\n"
        "    def idle(self) -> None:\n"
        "        pass\n",
        encoding="utf-8",
    )
    controller = ProjectAnalysisController(analyze_project(tmp_path))

    diagram = controller.member_graph_diagram()

    assert [node["label"] for node in diagram["nodes"]] == ["idle"]
    assert diagram["summary"] == (
        "Showing 1 member across 1 class and 0 resolved calls."
    )


def test_member_graph_includes_fields_and_focuses_outgoing_class_calls(
    tmp_path: Path,
) -> None:
    (tmp_path / "store.py").write_text(
        "class Store:\n"
        "    items: list\n"
        "    def add(self) -> None:\n"
        "        pass\n"
        "\n"
        "class View:\n"
        "    title: str\n"
        "    def __init__(self, store: Store) -> None:\n"
        "        self.store = store\n"
        "    def render(self) -> None:\n"
        "        self.store.add()\n",
        encoding="utf-8",
    )
    controller = ProjectAnalysisController(analyze_project(tmp_path))

    all_members = controller.member_graph_diagram()
    nodes = {
        (node["group"], node["label"]): node for node in all_members["nodes"]
    }
    groups = {group["label"]: group for group in all_members["groups"]}

    assert len(nodes) == 6
    assert nodes[(groups["Store"]["id"], "items")]["kind"] == "data_member"
    assert nodes[(groups["View"]["id"], "title")]["kind"] == "data_member"
    assert nodes[(groups["View"]["id"], "store")]["subtitle"] == "type: Store"
    field_description = nodes[(groups["View"]["id"], "title")]["description"]
    assert "View.title stores title state" in field_description
    assert len(re.findall(r"[.!?](?=\s|$)", field_description)) == 2

    focused = controller.member_graph_diagram(
        selected_class_id=groups["View"]["tree_node_id"]
    )
    focused_nodes = {
        (node["group"], node["label"]) for node in focused["nodes"]
    }
    focused_groups = {group["label"]: group for group in focused["groups"]}
    assert focused_nodes == {
        (focused_groups["View"]["id"], "title"),
        (focused_groups["View"]["id"], "store"),
        (focused_groups["View"]["id"], "__init__"),
        (focused_groups["View"]["id"], "render"),
        (focused_groups["Store"]["id"], "add"),
    }
    assert focused["summary"] == (
        "View: 4 direct members; 1 called member in 1 other class."
    )


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
