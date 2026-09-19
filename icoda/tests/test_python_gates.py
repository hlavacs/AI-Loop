"""Real build and test gates for a generated Python project."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from icoda_core import generator, persistence, python_analysis, specification, steps


def test_python_skeleton_real_build_and_targeted_test_gates(tmp_path: Path) -> None:
    profile = {
        **specification.default_code_profile("Python"),
        "test_runner": f"{sys.executable} -m pytest -q",
    }
    root = tmp_path / "demo-service"
    generator.write_skeleton(root, "Demo Service", profile)
    spec = specification.default_specification("Demo Service", "Python")
    spec["code_profile"] = profile
    specification.save(persistence.ProjectStore(root).specification_path, spec)
    selected = ("tests/test_demo_service.py",)

    build = steps.build_project(root)
    assert build.ok is True, build.output
    commands = steps.gate_commands(root, persistence.DEFAULT_TEST_COMMAND, selected)
    assert commands.test == (sys.executable, "-m", "pytest", "-q", "tests/test_demo_service.py")
    passing = steps.test_project(root, commands.test)
    assert passing.ok is True, passing.output

    test_file = root / selected[0]
    broken_test = test_file.read_text(encoding="utf-8").replace("== 0", "== 1") + "\n# force pyc refresh\n"
    test_file.write_text(broken_test, encoding="utf-8")
    failing = steps.test_project(root, commands.test)
    assert failing.ok is False
    assert "FAILED tests/test_demo_service.py::test_demo_service_runs" in failing.output
    assert "assert 0 == 1" in failing.output


def test_python_build_gate_compiles_flat_and_non_src_layouts(tmp_path: Path) -> None:
    flat = tmp_path / "flat"
    (flat / "flat_package").mkdir(parents=True)
    (flat / "flat_package/__init__.py").write_text("answer = 42\n", encoding="utf-8")
    app = tmp_path / "application"
    (app / "app").mkdir(parents=True)
    (app / "app/main.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    profile = specification.default_code_profile("Python")

    flat_commands = steps.gate_commands(flat, (), code_profile=profile)
    app_commands = steps.gate_commands(app, (), code_profile=profile)

    assert flat_commands.build[0][-1] == "flat_package"
    assert app_commands.build[0][-1] == "app"
    assert steps.build_project(flat, code_profile=profile).ok is True
    assert steps.build_project(app, code_profile=profile).ok is True


def test_python_build_gate_rejects_broken_module_outside_src(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/good.py").write_text("answer = 42\n", encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app/broken.py").write_text("def broken(:\n", encoding="utf-8")

    build = steps.build_project(tmp_path, code_profile=specification.default_code_profile("Python"))

    assert build.ok is False
    assert "SyntaxError" in build.output


def test_python_build_gate_keeps_src_layout_outcome(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/service.py").write_text("answer = 42\n", encoding="utf-8")
    profile = specification.default_code_profile("Python")

    commands = steps.gate_commands(tmp_path, (), code_profile=profile)

    assert commands.build[0][-1] == "src"
    assert steps.build_project(tmp_path, code_profile=profile).ok is True


def test_python_build_gate_excludes_hidden_state_and_build_output(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("answer = 42\n", encoding="utf-8")
    excluded = (".icoda", ".git", ".icoda-venv", ".venv", "build", "dist")
    for directory in excluded:
        path = tmp_path / directory
        path.mkdir()
        (path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    profile = specification.default_code_profile("Python")

    commands = steps.gate_commands(tmp_path, (), code_profile=profile)
    build = steps.build_project(tmp_path, code_profile=profile)

    assert python_analysis.find_python_sources(tmp_path) == (source,)
    assert commands.build[0][-1] == "."
    assert build.ok is True, build.output


def test_python_sources_and_gate_accept_a_symlinked_parent(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    root = real_parent / "project"
    (root / "package").mkdir(parents=True)
    (root / "service.py").write_text("answer = 42\n", encoding="utf-8")
    (root / "package/feature.py").write_text("def feature():\n    return 1\n", encoding="utf-8")
    linked_parent = tmp_path / "linked"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError:
        if sys.platform == "win32":
            pytest.skip("creating directory symlinks is not available")
        raise
    linked_root = linked_parent / "project"
    profile = specification.default_code_profile("Python")

    real_model = python_analysis.parse_project(root)
    linked_model = python_analysis.parse_project(linked_root)
    real_sources = tuple(path.relative_to(root) for path in python_analysis.find_python_sources(root))
    linked_sources = tuple(
        path.relative_to(linked_root) for path in python_analysis.find_python_sources(linked_root)
    )

    assert linked_sources == real_sources == (Path("service.py"), Path("package/feature.py"))
    assert tuple(linked_model.files) == tuple(real_model.files) == (
        "service.py", "package/feature.py",
    )
    assert steps.gate_commands(linked_root, (), code_profile=profile) == steps.gate_commands(
        root, (), code_profile=profile,
    )


def test_python_build_gate_excludes_nonstandard_virtual_environment(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("answer = 42\n", encoding="utf-8")
    environment = tmp_path / "myenv"
    environment.mkdir()
    (environment / "pyvenv.cfg").write_text("home = /python\n", encoding="utf-8")
    broken = environment / "broken.py"
    broken.write_text("def broken(:\n", encoding="utf-8")
    profile = specification.default_code_profile("Python")

    sources = python_analysis.find_python_sources(tmp_path)
    build = steps.build_project(tmp_path, code_profile=profile)

    assert broken not in sources
    assert sources == (source,)
    assert build.ok is True, build.output


def test_python_build_gate_excludes_tool_caches_and_vendored_code(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("answer = 42\n", encoding="utf-8")
    for directory in (".tox", ".mypy_cache", "node_modules"):
        path = tmp_path / directory
        path.mkdir()
        (path / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    build = steps.build_project(
        tmp_path, code_profile=specification.default_code_profile("Python"),
    )

    assert build.ok is True, build.output


def test_python_build_gate_compiles_top_level_bin_directory(tmp_path: Path) -> None:
    scripts = tmp_path / "bin"
    scripts.mkdir()
    broken = scripts / "broken.py"
    broken.write_text("def broken(:\n", encoding="utf-8")
    profile = specification.default_code_profile("Python")

    sources = python_analysis.find_python_sources(tmp_path)
    build = steps.build_project(tmp_path, code_profile=profile)

    assert sources == (broken,)
    assert build.ok is False
    assert "SyntaxError" in build.output


def test_python_build_gate_falls_back_to_project_root_without_sources(tmp_path: Path) -> None:
    commands = steps.gate_commands(
        tmp_path, (), code_profile=specification.default_code_profile("Python"),
    )

    assert commands.build[0][-1] == "."
