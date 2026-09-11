"""The step 0 skeleton: files, identifiers, and — where a toolchain exists — a real build and an ICODA analysis."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from icoda_core import analysis, generator, persistence, python_analysis, session, specification, toolchain


def test_identifier_and_files(tmp_path: Path) -> None:
    assert generator.project_identifier("My Cool-App 2") == "My_Cool_App_2"
    assert generator.project_identifier("3d viewer") == "p_3d_viewer"
    files = generator.skeleton_files("Demo App")
    assert "src/app/app.cppm" in files and "export module app;" in files["src/app/app.cppm"]
    assert "add_executable(Demo_App src/main.cpp)" in files["CMakeLists.txt"]
    assert 'mode="${2:-all}"' in files["build.sh"] and 'if [ "$mode" != "build-only" ]' in files["build.sh"]
    assert 'set "MODE=%~2"' in files["build.cmd"] and 'if /i "%MODE%"=="build-only"' in files["build.cmd"]
    written = generator.write_skeleton(tmp_path, "Demo App")
    assert sorted(written) == sorted(files)
    assert persistence.ProjectStore(tmp_path).load_state().phase == persistence.ProjectPhase.ARCHITECTURE
    assert generator.write_skeleton(tmp_path, "Demo App") == []          # existing files are left alone
    assert (tmp_path / "build.sh").stat().st_mode & 0o111


def test_python_skeleton_files_follow_the_code_profile() -> None:
    profile = specification.default_code_profile("Python")

    files = generator.skeleton_files("Demo Service", profile)

    assert set(files) == {
        ".gitignore",
        "README.md",
        "pyproject.toml",
        "src/demo_service.py",
        "tests/test_demo_service.py",
    }
    assert "class DemoService:" in files["src/demo_service.py"]
    assert "def run(self) -> int:" in files["src/demo_service.py"]
    assert "def main() -> int:" in files["src/demo_service.py"]
    assert "def test_demo_service_runs() -> None:" in files["tests/test_demo_service.py"]
    assert profile["test_framework"] in files["README.md"]
    assert profile["test_runner"] in files["README.md"]

    custom = {
        **profile,
        "source_file_extension": ".pyw",
        "module_naming": "PascalCase",
        "class_naming": "snake_case",
        "function_naming": "PascalCase",
        "test_framework": "customtest",
        "test_runner": "python -m customtest",
        "test_file_convention": "checks/check_<module>.py",
    }
    custom_files = generator.skeleton_files("Demo Service", custom)
    assert "src/DemoService.pyw" in custom_files
    assert "checks/check_DemoService.py" in custom_files
    assert "class demo_service:" in custom_files["src/DemoService.pyw"]
    assert "def Run(self) -> int:" in custom_files["src/DemoService.pyw"]
    assert "def TestDemoServiceRuns() -> None:" in custom_files["checks/check_DemoService.py"]
    assert "customtest" in custom_files["README.md"]
    assert "python -m customtest" in custom_files["README.md"]


def test_generated_python_skeleton_is_analysable(tmp_path: Path) -> None:
    profile = specification.default_code_profile("Python")
    root = tmp_path / "demo-service"
    generator.write_skeleton(root, "Demo Service", profile)

    model = python_analysis.parse_project(root)

    assert set(model.entities) == {
        "python:src.demo_service:DemoService",
        "python:src.demo_service:DemoService.run",
        "python:src.demo_service:main",
        "python:tests.test_demo_service:test_demo_service_runs",
    }
    assert not any(file.errors for file in model.files.values())


@pytest.mark.skipif(shutil.which("cmake") is None or shutil.which("ninja") is None, reason="no cmake/ninja")
def test_skeleton_builds_and_is_analysable(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    generator.write_skeleton(root, "demo")
    env = {**__import__("os").environ}
    if sys.platform == "darwin":
        env.pop("CC", None)
        env.pop("CXX", None)
    else:
        env.setdefault("CC", "clang")
        env.setdefault("CXX", "clang++")
    if sys.platform != "darwin" and shutil.which(env["CXX"]) is None:
        pytest.skip("no clang++")
    completed = subprocess.run(["bash", "build.sh", "debug"], cwd=root, env=env, capture_output=True, text=True,
                               check=False)
    assert completed.returncode == 0, completed.stdout[-800:] + completed.stderr[-800:]
    assert analysis.find_compile_commands(root) is not None
    if not toolchain.candidates():
        return
    opened = session.open_project(root, persistence.UserConfig(), in_process=True)
    names = {e.qualified_name for e in opened.model.entities.values()}
    assert {"main", "app::run"} <= names
    assert not any(f.errors for f in opened.model.files.values())
