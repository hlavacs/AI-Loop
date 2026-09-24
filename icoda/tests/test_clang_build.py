"""Build always selects Clang and preserves existing non-Clang build trees."""

import os
import shutil
import sys
from pathlib import Path

import pytest

from icoda_core import cmake, executables, process, steps, toolchain
from icoda_core.model import DerivedModel


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_clang_selection_ignores_non_clang_cxx(platform, tmp_path, monkeypatch):
    suffix = ".exe" if platform == "win32" else ""
    compiler = tmp_path / ("clang++" + suffix)
    for name in ("clang++", "clang", "clang-scan-deps"):
        path = tmp_path / (name + suffix)
        path.touch()
        path.chmod(0o755)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("CXX", "g++")
    monkeypatch.setattr(toolchain, "_windows_build_environment", lambda env: env)
    monkeypatch.setattr(toolchain, "candidates", lambda **_kwargs: [])
    monkeypatch.setattr(toolchain.shutil, "which", lambda name, **kwargs: (
        str(compiler) if name in ("clang++", str(compiler)) else None))
    monkeypatch.setattr(toolchain.subprocess, "run", lambda *args, **kwargs:
                        toolchain.subprocess.CompletedProcess(args, 0, "clang version 22.1.3", ""))
    environment = toolchain.clang_build_environment("cl.exe")
    assert Path(environment["CXX"]) == compiler
    assert Path(environment["CC"]) == tmp_path / ("clang" + suffix)


def test_missing_clang_fails_build_without_running_cmake(tmp_path, monkeypatch):
    def unavailable(*_args):
        raise RuntimeError("Clang 16+ with clang-scan-deps is required")

    monkeypatch.setattr(toolchain, "clang_build_environment", unavailable)
    monkeypatch.setattr(steps, "run_bounded", lambda *a, **k: pytest.fail("must not use the default compiler"))
    result = steps.build_project(tmp_path, code_profile={"language": "C++"})
    assert result.ok is False and "Clang" in result.output


def test_migration_retains_project_options_but_not_old_compiler_flags(tmp_path, monkeypatch):
    old = tmp_path / "build/msvc"
    old.mkdir(parents=True)
    contents = (f"CMAKE_HOME_DIRECTORY:INTERNAL={tmp_path}\nCMAKE_CXX_COMPILER:FILEPATH=cl.exe\n"
                "CMAKE_GENERATOR:INTERNAL=Ninja\nCMAKE_CXX_FLAGS:STRING=/EHsc\n"
                "CMAKE_BUILD_TYPE:STRING=Release\nKEEP_SETTING:BOOL=ON\n"
                "CMAKE_PREFIX_PATH:PATH=C:/dependencies\n")
    (old / "CMakeCache.txt").write_text(contents)
    monkeypatch.setattr(toolchain, "clang_build_environment", lambda *args:
                        {"CXX": str(tmp_path / "clang++"), "CC": str(tmp_path / "clang"), "PATH": ""})
    monkeypatch.setattr(cmake.shutil, "which", lambda name, **kwargs: name)
    directory, command, env = cmake.clang_configuration(tmp_path)
    assert directory == tmp_path / "build/debug-clang"
    assert "-DKEEP_SETTING:BOOL=ON" in command
    assert "-DCMAKE_BUILD_TYPE:STRING=Release" in command
    assert "-DCMAKE_PREFIX_PATH:PATH=C:/dependencies" in command
    assert not any("/EHsc" in part or "cl.exe" in part for part in command)
    assert f"-DCMAKE_CXX_COMPILER={env['CXX']}" in command
    assert (old / "CMakeCache.txt").read_text() == contents


def test_existing_clang_tree_reuses_its_recorded_cmake(tmp_path, monkeypatch):
    directory = tmp_path / "build/debug"
    directory.mkdir(parents=True)
    compiler = tmp_path / "clang++"
    recorded_cmake = tmp_path / "cmake-4.3/bin/cmake"
    recorded_cmake.parent.mkdir(parents=True)
    recorded_cmake.touch()
    (directory / "CMakeCache.txt").write_text(
        f"CMAKE_HOME_DIRECTORY:INTERNAL={tmp_path}\n"
        f"CMAKE_COMMAND:INTERNAL={recorded_cmake}\n"
        f"CMAKE_CXX_COMPILER:FILEPATH={compiler}\n"
        "CMAKE_GENERATOR:INTERNAL=Ninja\n"
    )
    monkeypatch.setattr(toolchain, "clang_build_environment", lambda *_args: {
        "CXX": str(compiler), "CC": str(tmp_path / "clang"), "PATH": "",
    })

    selected, command, _environment = cmake.clang_configuration(tmp_path)

    assert selected == directory
    assert command[0] == str(recorded_cmake)


def test_toolchain_override_is_rejected(tmp_path):
    (tmp_path / "CMakeCache.txt").write_text("CMAKE_CXX_COMPILER:FILEPATH=g++\n")
    with pytest.raises(RuntimeError, match="overrode Clang"):
        cmake.verify_clang(tmp_path)


def test_selected_target_build_uses_clang_environment(tmp_path, monkeypatch):
    directory = tmp_path / "build/clang"
    target = executables.Target("engine", "Debug", directory, None, frozenset(), kind="STATIC_LIBRARY")
    entry = executables.Entry("", "", 0, target)
    environment = {"CC": "clang", "CXX": "clang++", "PATH": os.environ.get("PATH", "")}
    monkeypatch.setattr(cmake, "clang_configuration", lambda root:
                        (directory, ["cmake", "-S", str(root), "-B", str(directory)], environment))
    monkeypatch.setattr(cmake, "verify_clang", lambda path: None)
    monkeypatch.setattr(executables, "read_targets", lambda *args: (target,))
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs["env"]))
        return process.ProcessResult(command, 0, "ok", "")

    monkeypatch.setattr(process, "run_bounded", run)
    outcome = executables.operate(tmp_path, DerivedModel(str(tmp_path)), entry, "build", lambda: False)
    assert "build passed" in outcome.message
    assert len(calls) == 2 and all(env == environment for _, env in calls)
    assert calls[-1][0][:5] == ["cmake", "--build", str(directory), "--target", "engine"]


def test_real_non_clang_build_migrates_without_rewriting_old_cache(tmp_path):
    environment = toolchain.clang_build_environment()
    original = shutil.which("cl" if sys.platform == "win32" else "g++", path=environment["PATH"])
    if original is None:
        pytest.skip("No second compiler is installed for the migration test")
    cmake_exe = shutil.which("cmake", path=environment["PATH"])
    (tmp_path / "main.cpp").write_text("#include <vector>\nint main() { return std::vector<int>{}.size(); }\n")
    (tmp_path / "CMakeLists.txt").write_text(
        'cmake_minimum_required(VERSION 3.28)\nproject(Migration LANGUAGES CXX)\n'
        'if(NOT KEEP_SETTING STREQUAL "retained")\nmessage(FATAL_ERROR "Lost setting")\nendif()\n'
        'add_executable(example main.cpp)\n')
    old = tmp_path / "build/original"
    result = process.run_bounded([cmake_exe, "-S", str(tmp_path), "-B", str(old), "-G", "Ninja",
                                  f"-DCMAKE_CXX_COMPILER={original}", "-DKEEP_SETTING=retained"],
                                 env=environment)
    assert result.ok, result.stdout + result.stderr
    before = (old / "CMakeCache.txt").read_bytes()
    result = steps.build_project(tmp_path)
    assert result.ok, result.output
    assert (old / "CMakeCache.txt").read_bytes() == before
    active = cmake.build_directory(tmp_path)
    assert active == tmp_path / "build/debug-clang"
    cmake.verify_clang(active)
    assert (active / "compile_commands.json").is_file()
