"""Instrumented-build runtime generation and isolated CMake configuration."""

import os
import shutil
from pathlib import Path

import pytest

from icoda_core import call_trace, cmake, executables, instrumentation, process
from icoda_core.model import DerivedModel, Entity, FileInfo, Kind

_CMAKE = shutil.which("cmake")
_CXX = shutil.which("clang++") or shutil.which("g++")


def test_prepare_instrumentation_generates_bounded_failure_safe_runtime(tmp_path: Path) -> None:
    options = instrumentation.InstrumentationOptions(
        enabled=True, duration_seconds=2.5, trace_file=Path("traces/calls.tsv"))

    files = instrumentation.prepare_instrumentation(tmp_path, options)

    runtime = files.runtime_source.read_text(encoding="utf-8")
    injection = files.cmake_include.read_text(encoding="utf-8")
    assert "trace_duration_ns = UINT64_C(2500000000)" in runtime
    assert str((tmp_path / "traces/calls.tsv").resolve()) in runtime
    assert "if (!trace_output)" in runtime and "elapsed > trace_duration_ns" in runtime
    assert "__cyg_profile_func_enter" in runtime and "__cyg_profile_func_exit" in runtime
    assert "add_compile_options(-finstrument-functions)" in injection
    assert "add_library(icoda_call_trace_runtime SHARED" in injection
    assert files.build_directory == tmp_path / ".icoda/cache/instrumented-debug-build"
    assert files.cmake_arguments[0] == "-DICODA_CALL_TRACE_ENABLED=ON"
    assert files.cmake_arguments[1].startswith("-DCMAKE_PROJECT_INCLUDE=")


@pytest.mark.parametrize("seconds", [0, -1, float("inf"), float("nan")])
def test_instrumentation_duration_must_be_positive_and_finite(tmp_path: Path, seconds: float) -> None:
    with pytest.raises(ValueError, match="positive finite"):
        instrumentation.prepare_instrumentation(
            tmp_path, instrumentation.InstrumentationOptions(True, seconds))


def test_instrumented_cmake_configuration_is_debug_and_isolated(tmp_path: Path, monkeypatch) -> None:
    ordinary = tmp_path / "build/release"
    ordinary.mkdir(parents=True)
    (ordinary / "CMakeCache.txt").write_text(
        f"CMAKE_HOME_DIRECTORY:INTERNAL={tmp_path}\n"
        "CMAKE_CXX_COMPILER:FILEPATH=g++\n"
        "CMAKE_GENERATOR:INTERNAL=Ninja\n"
        "CMAKE_BUILD_TYPE:STRING=Release\n"
        "KEEP_SETTING:BOOL=retained\n",
        encoding="utf-8",
    )
    (ordinary / "build.ninja").touch()
    environment = {"CC": "clang", "CXX": "clang++", "PATH": os.environ.get("PATH", "")}
    monkeypatch.setattr(cmake.toolchain, "clang_build_environment", lambda *_args: environment)
    monkeypatch.setattr(cmake.shutil, "which", lambda name, **_kwargs: name)

    directory, command, actual_environment, files = cmake.instrumented_clang_configuration(
        tmp_path, instrumentation.InstrumentationOptions(enabled=True, duration_seconds=3))

    assert directory == tmp_path / ".icoda/cache/instrumented-debug-build"
    assert files.build_directory == directory and actual_environment == environment
    assert "-DCMAKE_BUILD_TYPE=Debug" in command
    assert "-DKEEP_SETTING:BOOL=retained" in command
    assert not any(part == "-DCMAKE_BUILD_TYPE:STRING=Release" for part in command)
    assert "-DICODA_CALL_TRACE_ENABLED=ON" in command
    normal_directory, normal_command, _ = cmake.clang_configuration(tmp_path)
    assert normal_directory == tmp_path / "build/debug-clang"
    assert not any("ICODA_CALL_TRACE" in part or "call-instrumentation" in part for part in normal_command)


@pytest.mark.skipif(_CMAKE is None or _CXX is None, reason="cmake and clang++/g++ are required")
def test_real_instrumented_cmake_run_records_playable_call_sequence(tmp_path: Path) -> None:
    root = tmp_path / "project with spaces"
    root.mkdir()
    source = root / "main.cpp"
    source.write_text(
        "volatile int result = 0;\n"
        "__attribute__((noinline)) void helper() { ++result; }\n"
        "namespace demo { __attribute__((noinline)) void work() { helper(); } }\n"
        "int main() { demo::work(); return result == 1 ? 0 : 1; }\n",
        encoding="utf-8",
    )
    (root / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20)\n"
        "project(InstrumentedDemo LANGUAGES CXX)\n"
        "add_executable(demo main.cpp)\n",
        encoding="utf-8",
    )
    model = DerivedModel(str(root), files={"main.cpp": FileInfo("main.cpp")})
    model.add_entity(Entity("main", Kind.FUNCTION, "main", "main", "main.cpp", 4,
                            signature="int main()"))
    model.add_entity(Entity("work", Kind.FUNCTION, "work", "demo::work", "main.cpp", 3,
                            signature="void work()"))
    model.add_entity(Entity("helper", Kind.FUNCTION, "helper", "helper", "main.cpp", 2,
                            signature="void helper()"))
    regular_directory = root / "build/debug"
    regular_directory.mkdir(parents=True)
    marker = regular_directory / "untouched"
    marker.write_text("ordinary build", encoding="utf-8")
    target = executables.Target(
        "demo", "Debug", regular_directory, regular_directory / "demo",
        frozenset({str(source.resolve())}),
    )
    entry = executables.Entry("main", "main.cpp", 4, target)

    outcome = executables.operate(
        root, model, entry, "run", lambda: False,
        instrumentation_options=instrumentation.InstrumentationOptions(
            enabled=True, duration_seconds=2.0),
    )

    assert outcome.trace_file is not None and outcome.trace_file.is_file()
    assert outcome.trace_file.read_text(encoding="utf-8").startswith("# icoda-call-trace-v1\n")
    assert outcome.message.endswith(f"; call trace: {outcome.trace_file}")
    playback = call_trace.CallPlayback(call_trace.load_trace(outcome.trace_file, model))
    assert playback.next_call() is model.entities["main"]
    assert playback.next_call() is model.entities["work"]
    assert playback.next_call() is model.entities["helper"]
    assert playback.status == "call 3 of 3: helper"
    assert playback.next_call() is None
    instrumented_directory = root / ".icoda/cache/instrumented-debug-build"
    assert outcome.selected is not None and outcome.selected.target is not None
    assert outcome.selected.target.build_dir == instrumented_directory
    assert instrumented_directory.is_dir()
    configured_compiler = cmake.cache_values(instrumented_directory)["CMAKE_CXX_COMPILER"][1]
    assert Path(configured_compiler).resolve() == Path(_CXX).resolve()
    assert list(regular_directory.iterdir()) == [marker]
    assert marker.read_text(encoding="utf-8") == "ordinary build"


def test_target_operation_selects_instrumented_configuration_only_when_enabled(tmp_path: Path, monkeypatch) -> None:
    directory = tmp_path / ".icoda/cache/instrumented-debug-build"
    target = executables.Target("demo", "Debug", directory, tmp_path / "demo", frozenset({str(tmp_path / "m.cpp")}))
    selected = executables.Entry("main", "m.cpp", 1, target)
    options = instrumentation.InstrumentationOptions(enabled=True)
    files = instrumentation.InstrumentationFiles(
        tmp_path / "runtime.cpp", tmp_path / "inject.cmake", directory,
        tmp_path / "calls.tsv", ("-DICODA_CALL_TRACE_ENABLED=ON",))
    monkeypatch.setattr(cmake, "instrumented_clang_configuration", lambda root, value: (
        directory, ["cmake", "-S", str(root), "-B", str(directory)],
        {"PATH": "tools", "CXX": "clang++"}, files))
    monkeypatch.setattr(cmake, "clang_configuration", lambda _root: pytest.fail("ordinary build selected"))
    monkeypatch.setattr(cmake, "verify_compiler", lambda _directory, _expected: None)
    monkeypatch.setattr(executables, "read_targets", lambda *_args: (target,))
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs["env"]))
        return process.ProcessResult(command, 0, "ok\n", "")

    monkeypatch.setattr(process, "run_bounded", run)
    model = DerivedModel(str(tmp_path), files={"m.cpp": FileInfo("m.cpp")})
    model.add_entity(Entity("main", Kind.FUNCTION, "main", "main", "m.cpp", 1))
    outcome = executables.operate(
        tmp_path, model, selected, "run", lambda: False, options)

    assert len(calls) == 3 and all(env["PATH"].startswith(str(directory)) for _, env in calls)
    assert outcome.message.endswith(f"call trace: {files.trace_file}")
    assert outcome.trace_file == files.trace_file
    assert executables.Outcome((), None, "", "ordinary run").trace_file is None
