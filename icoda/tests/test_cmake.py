"""Opening existing builds must preserve their settings and supply analysis metadata."""

import json
import shutil
from pathlib import Path

import pytest

from icoda_core import cmake, executables, process, steps
from icoda_core.model import DerivedModel


def test_build_tree_prefers_database_then_completed_config_and_checks_source_root(tmp_path: Path) -> None:
    for name in ("debug", "release", "foreign"):
        directory = tmp_path / "build" / name
        directory.mkdir(parents=True)
        source = tmp_path if name != "foreign" else tmp_path / "another-project"
        (directory / "CMakeCache.txt").write_text(f"CMAKE_HOME_DIRECTORY:INTERNAL={source}\n")
        if name != "debug":
            (directory / "build.ninja").touch()
    assert cmake.build_directory(tmp_path) == tmp_path / "build/release"
    (tmp_path / "build/debug/compile_commands.json").write_text("[]")
    assert cmake.build_directory(tmp_path) == tmp_path / "build/debug"
    (tmp_path / "build/debug/CMakeCache.txt").write_text("CMAKE_HOME_DIRECTORY:INTERNAL=/another-project\n")
    assert cmake.build_directory(tmp_path) == tmp_path / "build/release"


def test_existing_project_build_and_refresh_preserve_toolchain_and_export_metadata(tmp_path: Path, monkeypatch):
    if not shutil.which("cmake"):
        pytest.skip("CMake unavailable")
    (tmp_path / "main.cpp").write_text("int main() { return 0; }\n")
    (tmp_path / "CMakeLists.txt").write_text('''cmake_minimum_required(VERSION 3.20)
project(Existing LANGUAGES CXX)
if(NOT KEEP_SETTING STREQUAL "retained")
    message(FATAL_ERROR "Lost project configuration")
endif()
add_executable(example main.cpp)
''')
    directory = tmp_path / "build/custom-release"
    result = process.run_bounded(["cmake", "-S", str(tmp_path), "-B", str(directory), "-G", "Ninja",
                                  "-DKEEP_SETTING=retained", "-DCMAKE_EXPORT_COMPILE_COMMANDS=OFF"])
    assert result.ok, result.stdout + result.stderr
    assert not (directory / "compile_commands.json").exists()
    cache = (directory / "CMakeCache.txt").read_text()
    compiler = next(line for line in cache.splitlines() if line.startswith("CMAKE_CXX_COMPILER:FILEPATH="))

    build = steps.build_project(tmp_path)
    assert build.ok, build.output
    assert compiler in (directory / "CMakeCache.txt").read_text()
    active = cmake.build_directory(tmp_path)
    assert active is not None
    cmake.verify_clang(active)
    database = json.loads((active / "compile_commands.json").read_text())
    assert any(Path(entry["file"]) == tmp_path / "main.cpp" for entry in database)
    targets = executables.read_targets(tmp_path)
    assert [target.name for target in targets] == ["example"]
    assert targets[0].artifact.is_file()
    refreshed = executables.operate(tmp_path, DerivedModel(str(tmp_path)), None, "refresh", lambda: False)
    assert "refreshed" in refreshed.message
    assert compiler in (directory / "CMakeCache.txt").read_text()
