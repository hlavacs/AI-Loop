"""The step 0 skeleton: files, identifiers, and — where a toolchain exists — a real build and an ICODA analysis."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from icoda_core import analysis, generator, persistence, session, toolchain


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
    assert generator.write_skeleton(tmp_path, "Demo App") == []          # existing files are left alone
    assert (tmp_path / "build.sh").stat().st_mode & 0o111


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
