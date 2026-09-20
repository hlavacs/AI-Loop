"""Verify exclusive executable and library views in native Tk using a real CMake C++ project."""
from __future__ import annotations

import argparse
import json
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gui_acceptance import load_application

from icoda_core import persistence, process, session
from tools.capture_cpp_tutorial import capture_window


def fixture(root: Path) -> None:
    files = {
        "include/shared.hpp": "#pragma once\nclass Shared { public: int value() const; };\nint unused_api();\n",
        "src/shared.cpp": '#include "shared.hpp"\nint Shared::value() const { return 42; }\n'
                          'int unused_api() { return 7; }\n',
        "examples/basic/main.cpp": '#include "shared.hpp"\nclass BasicExample {};\n'
                                   'int main() { return Shared{}.value() == 42 ? 0 : 1; }\n',
        "examples/basic/helper.cpp": "class BasicHelper {};\n",
        "tests/smoke_test.cpp": '#include "shared.hpp"\nclass SmokeTest {};\n'
                                'int main() { return Shared{}.value() == 42 ? 0 : 1; }\n',
        "CMakeLists.txt": '''cmake_minimum_required(VERSION 3.20)
project(ExclusiveViews LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
add_library(shared STATIC src/shared.cpp)
target_include_directories(shared PUBLIC include)
add_executable(basic examples/basic/main.cpp examples/basic/helper.cpp)
target_link_libraries(basic PRIVATE shared)
add_executable(smoke_test tests/smoke_test.cpp)
target_link_libraries(smoke_test PRIVATE shared)
''',
    }
    for file, content in files.items():
        path = root / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    query = root / "build/.cmake/api/v1/query/client-icoda/codemodel-v2"
    query.parent.mkdir(parents=True, exist_ok=True)
    query.touch()
    for command in (["cmake", "-S", str(root), "-B", str(root / "build"),
                     "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", "-DCMAKE_BUILD_TYPE=Debug"],
                    ["cmake", "--build", str(root / "build")]):
        result = process.run_bounded(command, cwd=root)
        assert result.ok, result.stdout + result.stderr


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    project = output / "project"
    fixture(project)
    config = persistence.UserConfig()
    opened = session.open_project(project, config)
    original = opened.model.to_json()
    module = load_application()
    root = tk.Tk()
    try:
        app = module.App(root, config=config, config_path=output / "settings.json")
        app.show(opened)
        root.update()
        selector = app.executables
        assert len(selector.choices) == 3 and selector.selected is None
        assert not app.view.layout.nodes and not app.class_view.model.files and not app.call_view.model.files
        observed = {}
        for name, main_file, classes in (
                ("basic", "examples/basic/main.cpp", {"BasicExample", "BasicHelper", "Shared"}),
                ("smoke_test", "tests/smoke_test.cpp", {"SmokeTest", "Shared"}),
                ("shared", "", {"Shared"})):
            app.views.select(app.class_view.frame)
            index = next(i for i, choice in enumerate(selector.choices) if choice.target.name == name)
            selector.combo.current(index)
            selector.combo.event_generate("<<ComboboxSelected>>")
            root.update()
            assert app.views.select() == str(app.class_view.frame)
            expected = {"src/shared.cpp", "include/shared.hpp"}
            if main_file:
                expected.add(main_file)
            if name == "basic":
                expected.add("examples/basic/helper.cpp")
            model = app.displayed.model
            assert set(model.files) == expected, model.files
            assert set(app.call_view.model.files) == set(app.class_view.model.files) == expected
            assert {entity.name for entity in model.entities.values()
                    if entity.kind.value == "class"} == classes
            assert all(issue.file in expected for issue in app.issue_view.issues)
            assert all(entry.file in expected for entry in app.coverage_view.index.entries)
            assert not selector.buttons["Build"].instate(["disabled"])
            assert selector.buttons["Run"].instate(["disabled"]) == (name == "shared")
            if main_file:
                assert app.source_editor.document.relative == main_file
            else:
                assert app.source_editor.document is None
                assert app.call_view.library_mode and app.call_view.root_usr is None
                call_names = {node.label for node in app.call_view.layout.nodes.values()}
                assert {"Shared::value", "unused_api"} <= call_names
                assert "main" not in call_names
                app.views.select(app.call_view.frame)
                root.update()
                capture_window(root, output / "shared-call.png")
                api = next(entity for entity in model.entities.values() if entity.name == "unused_api")
                app.call_view.set_root(api.usr)
                assert set(app.call_view.layout.nodes) == {api.usr}
                app.call_view.toolbar_controls["from-main"].invoke()
                assert {node.label for node in app.call_view.layout.nodes.values()} == call_names
                app.views.select(app.class_view.frame)
                root.update()
            assert set(opened.model.files) > expected and opened.model.to_json() == original
            capture_window(root, output / f"{name}-class.png")
            app.views.select(0)
            root.update()
            assert set(app.view.layout.nodes) == expected
            capture_window(root, output / f"{name}-files.png")
            observed[name] = sorted(model.files)
        app.show(opened)
        assert selector.selected.target.name == "shared"
        assert set(app.displayed.model.files) == set(observed["shared"])
        assert selector.buttons["Run"].instate(["disabled"])
        (output / "scope-gui.json").write_text(json.dumps({"passed": True, "views": observed,
                                                          "restored": selector.selected.label}, indent=2) + "\n")
        print("PASS: native executable/library selection, all scoped views, API roots, Build/Run controls, and reload")
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
