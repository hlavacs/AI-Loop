"""Python projects opened through the real application and shared GUI surfaces."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from icoda_core import analysis, persistence, session, specification, steplog
from icoda_core.model import DerivedModel
from icoda_gui import graph_canvas


def _write_python_project(root: Path) -> str:
    root.mkdir(parents=True)
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
    tests.mkdir()
    (tests / "test_service.py").write_text(
        """from service import Store, main

def test_main() -> None:
    assert main(Store()) == 'item'
""",
        encoding="utf-8",
    )
    return "python:service:main"


class _ImmediateThread:
    def __init__(self, *, target: Any, args: tuple[Any, ...], daemon: bool) -> None:
        self.target, self.args = target, args

    def start(self) -> None:
        self.target(*self.args)


def _app(app_module: Any, tmp_path: Path, monkeypatch: Any) -> Any:
    original = session.open_project
    monkeypatch.setattr(app_module.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(
        app_module.session,
        "open_project",
        lambda root, config: original(root, config, in_process=True),
    )
    return app_module.App(
        app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "config.json"
    )


def _open(app: Any, root: Path) -> None:
    app.open_project(root)
    app._poll()
    assert app.opened is not None and app.opened.root == root.resolve()


def test_python_project_drives_every_existing_view_and_shared_control(
    app_module: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    project = tmp_path / "python-project"
    target = _write_python_project(project)
    store = persistence.ProjectStore(project)
    store.ensure()
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE))
    steplog.StepLog(store.steps_path).append(
        steplog.StepRecord(
            1,
            "architecture",
            "approved",
            title="Add Python service",
            files=["service.py", "tests/test_service.py"],
            entities_added=[target],
            selected_tests=["tests/test_service.py"],
            test_ok=True,
        )
    )
    app = _app(app_module, tmp_path, monkeypatch)

    _open(app, project)

    assert app.language_var.get() == "Language: Python"
    assert app.opened.libclang == "Python ast"
    assert set(app.opened.model.files) == {"service.py", "tests/test_service.py"}
    assert app.view.layout is not None and app.view.layout.nodes and app.view.item_nodes
    assert app.call_view.layout is not None and app.call_view.layout.nodes and app.call_view.item_nodes
    assert app.class_view.graph.nodes and app.class_view.item_nodes
    assert app.mind_map_view.tree is not None and app.mind_map_view.tree.nodes()
    assert app.mind_map_view.item_nodes
    assert app.coverage_view.index.entries
    assert app.issue_view.issues
    assert app.panel.phase_var.get() == "architecture"
    assert app.panel.title_var.get() == "No proposal"
    assert app.graph_filter_entry.kwargs["textvariable"] is app.graph_filter_var
    assert app.neighborhood_spinbox.kwargs["textvariable"] is app.neighborhood_depth_var
    app.edit_specification()
    assert app.spec_editor.to_specification()["code_profile"] == specification.default_code_profile("Python")

    app.coverage_mode_var.set(True)
    app.toggle_coverage_mode()
    assert all(canvas.coverage_mode for canvas in app._diagram_canvases())
    assert all(canvas.node_fill(target) == graph_canvas.NODE_COLOURS["covered"]
               for canvas in app._diagram_canvases())

    app.graph_filter_var.set("name:normalize")
    assert all(canvas.node_visible("python:service:normalize") for canvas in app._diagram_canvases())
    assert all(not canvas.node_visible(target) for canvas in app._diagram_canvases())
    app.clear_graph_filter()
    app.focus_graph_node(target)
    app.neighborhood_depth_var.set(1)
    assert all(canvas.node_dimmed("python:service:normalize") for canvas in app._diagram_canvases())

    app.neighborhood_depth_var.set(0)
    app.focus_graph_node(None)
    app.collapse_all()
    collapsed = app.view.rendered_expansion_nodes()
    item, key = next(iter(app.view.expansion_items.items()))
    app.view.canvas.find_overlapping = lambda *_args: (item,)
    app.view.on_release(SimpleNamespace(x=10, y=10, num=1))
    assert key in app.expansion_state
    assert len(app.view.rendered_expansion_nodes()) > len(collapsed)
    app.collapse_all_button.kwargs["command"]()
    assert app.expansion_state == frozenset()


def test_python_node_action_menu_resolves_all_actions_and_step_panel(
    app_module: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    project = tmp_path / "python-actions"
    target = _write_python_project(project)
    store = persistence.ProjectStore(project)
    store.ensure()
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE))
    steplog.StepLog(store.steps_path).append(
        steplog.StepRecord(
            3,
            "architecture",
            "approved",
            title="Introduce main",
            entities_added=[target],
            files=["service.py", "tests/test_service.py"],
            selected_tests=["tests/test_service.py"],
            test_ok=True,
        )
    )
    app = _app(app_module, tmp_path, monkeypatch)
    _open(app, project)
    menu = app.call_view.action_menu
    menu.hit_test = lambda _x, _y: target
    event = SimpleNamespace(x=10, y=10, x_root=20, y_root=20)

    assert menu.open(event) == "break"
    architecture = menu.context
    assert architecture is not None
    assert architecture.introducing_iteration == 3
    assert architecture.can_propose and architecture.tests == ("tests/test_service.py",)
    menu._dispatch(graph_canvas.SHOW_STEP)
    assert app.panel.selected_iteration == 3
    dispatched: list[tuple[Any, ...]] = []
    monkeypatch.setattr(app.steps, "action", lambda *args: dispatched.append(args))
    menu._dispatch(graph_canvas.PROPOSE_HERE)

    app.opened.model.entities[target].status = "stub"
    store.save_state(
        persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION, (target,), 0)
    )
    app.show(app.opened)
    assert menu.open(event) == "break"
    implementation = menu.context
    assert implementation is not None and implementation.can_implement
    assert implementation.tests == ("tests/test_service.py",)
    menu._dispatch(graph_canvas.IMPLEMENT_HERE)
    menu._dispatch(graph_canvas.RUN_TESTS)

    assert dispatched == [
        ("propose_here", target),
        ("implement_here", target),
        ("run_tests", ("tests/test_service.py",)),
    ]
    assert app.panel.phase_var.get() == "implementation"
    assert target in store.load_state().implementation_queue


def test_degenerate_project_opens_are_non_raising(
    app_module: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    app = _app(app_module, tmp_path, monkeypatch)
    neither = tmp_path / "neither"
    neither.mkdir()
    (neither / "README.txt").write_text("no source\n", encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    _open(app, neither)
    assert app.opened.model.files == {} and app.language_var.get() == "Language: C++"
    _open(app, empty)
    assert app.opened.model.files == {} and app.language_var.get() == "Language: C++"
    _open(app, invalid)
    assert app.language_var.get() == "Language: Python"
    assert app.opened.model.files["broken.py"].errors
    assert "parse errors" in app.status.get()


def test_switches_from_cpp_to_python_in_one_app_session(
    app_module: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    cpp = tmp_path / "cpp"
    cpp.mkdir()
    (cpp / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    python = tmp_path / "python"
    target = _write_python_project(python)
    app = _app(app_module, tmp_path, monkeypatch)

    _open(app, cpp)
    assert app.language_var.get() == "Language: C++"
    _open(app, python)
    assert app.language_var.get() == "Language: Python"
    assert app.panel.title_var.get() == "No proposal"
    assert target in app.opened.model.entities
    assert all(entity.usr.startswith("python:") for entity in app.opened.model.entities.values())


def test_dispatch_defaults_mixed_and_source_free_projects_to_cpp(
    tmp_path: Path, monkeypatch: Any
) -> None:
    python = tmp_path / "python"
    python.mkdir()
    (python / "app.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    assert analysis.detect_language(python) == analysis.PYTHON_LANGUAGE
    assert "python:app:main" in analysis.parse_project_for_root(python, []).entities

    mixed = tmp_path / "mixed"
    mixed.mkdir()
    (mixed / "build.py").write_text("pass\n", encoding="utf-8")
    (mixed / "main.cpp").write_text("int main() {}\n", encoding="utf-8")
    expected = DerivedModel(str(mixed))
    calls: list[tuple[Any, ...]] = []

    def cpp_parser(root: Path, commands: Any, **kwargs: Any) -> DerivedModel:
        calls.append((root, commands, kwargs))
        return expected

    monkeypatch.setattr(analysis, "parse_project", cpp_parser)
    assert analysis.detect_language(mixed) == analysis.CPP_LANGUAGE
    assert analysis.parse_project_for_root(mixed, [], libclang_version="same") is expected
    assert calls == [(mixed, [], {
        "resource_dirs": None,
        "cache_dir": None,
        "previous": None,
        "libclang_version": "same",
        "sysroot": None,
        "apple": False,
        "notes": None,
        "progress": None,
    })]
    assert analysis.detect_language(tmp_path / "missing") == analysis.CPP_LANGUAGE
