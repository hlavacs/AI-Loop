"""Instrumented-build runtime generation and isolated CMake configuration."""

import json
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
    assert json.dumps(str((tmp_path / "traces/calls.tsv").resolve())) in runtime
    assert "if (!trace_output)" in runtime and "elapsed > trace_duration_ns" in runtime
    assert "std::setvbuf(trace_output, nullptr, _IOLBF, BUFSIZ)" in runtime
    assert "std::fflush(trace_output)" in runtime
    assert "__cyg_profile_func_enter" in runtime and "__cyg_profile_func_exit" in runtime
    assert "add_compile_options(-finstrument-functions)" in injection
    assert "add_library(icoda_call_trace_runtime SHARED" in injection
    assert f'ICODA_CALL_TRACE_CACHE_VERSION "{instrumentation.CACHE_VERSION}"' in injection
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
    recorded_cmake = tmp_path / "cmake-4.3/bin/cmake"
    recorded_cmake.parent.mkdir(parents=True)
    recorded_cmake.touch()
    (ordinary / "CMakeCache.txt").write_text(
        f"CMAKE_HOME_DIRECTORY:INTERNAL={tmp_path}\n"
        f"CMAKE_COMMAND:INTERNAL={recorded_cmake}\n"
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
    assert command[0] == str(recorded_cmake)
    assert "-DCMAKE_BUILD_TYPE=Debug" in command
    assert "-DKEEP_SETTING:BOOL=retained" in command
    assert not any(part == "-DCMAKE_BUILD_TYPE:STRING=Release" for part in command)
    assert "-DICODA_CALL_TRACE_ENABLED=ON" in command
    normal_directory, normal_command, _ = cmake.clang_configuration(tmp_path)
    assert normal_directory == tmp_path / "build/debug-clang"
    assert not any("ICODA_CALL_TRACE" in part or "call-instrumentation" in part for part in normal_command)


def test_instrumented_configuration_refreshes_a_partial_failed_cache(tmp_path: Path, monkeypatch) -> None:
    ordinary = tmp_path / "build/debug"
    ordinary.mkdir(parents=True)
    compiler = tmp_path / "clang++"
    recorded_cmake = tmp_path / "cmake-4.3/bin/cmake"
    recorded_cmake.parent.mkdir(parents=True)
    recorded_cmake.touch()
    (ordinary / "CMakeCache.txt").write_text(
        f"CMAKE_HOME_DIRECTORY:INTERNAL={tmp_path}\n"
        f"CMAKE_COMMAND:INTERNAL={recorded_cmake}\n"
        f"CMAKE_CXX_COMPILER:FILEPATH={compiler}\n"
        "CMAKE_GENERATOR:INTERNAL=Ninja\n",
        encoding="utf-8",
    )
    (ordinary / "build.ninja").touch()
    failed = tmp_path / ".icoda/cache/instrumented-debug-build"
    failed.mkdir(parents=True)
    (failed / "CMakeCache.txt").write_text(
        f"CMAKE_CXX_COMPILER:UNINITIALIZED={compiler}\n", encoding="utf-8")
    with (ordinary / "CMakeCache.txt").open("a", encoding="utf-8") as cache:
        cache.write("CMAKE_CXX_FLAGS:STRING=-stdlib=libc++\n"
                    "CMAKE_EXE_LINKER_FLAGS:STRING=-stdlib=libc++\n"
                    "CMAKE_CXX_STDLIB_MODULES_JSON:FILEPATH=/llvm/libc++.modules.json\n")
    environment = {"CC": str(tmp_path / "clang"), "CXX": str(compiler), "PATH": "tools"}
    monkeypatch.setattr(cmake, "_instrumented_build_environment", lambda _preferred: environment)
    monkeypatch.setattr(cmake.shutil, "which", lambda name, **_kwargs: name)

    directory, command, _actual_environment, _files = cmake.instrumented_clang_configuration(
        tmp_path, instrumentation.InstrumentationOptions(enabled=True))

    assert directory == failed
    assert command[:2] == [str(recorded_cmake), "--fresh"]
    assert "-DCMAKE_CXX_FLAGS:STRING=-stdlib=libc++" in command
    assert "-DCMAKE_EXE_LINKER_FLAGS:STRING=-stdlib=libc++" in command
    assert "-DCMAKE_CXX_STDLIB_MODULES_JSON:FILEPATH=/llvm/libc++.modules.json" in command


@pytest.mark.skipif(_CMAKE is None or _CXX is None, reason="cmake and clang++/g++ are required")
def test_real_instrumented_cmake_run_records_playable_call_sequence(tmp_path: Path) -> None:
    root = tmp_path / "project with spaces"
    root.mkdir()
    source = root / "main.cpp"
    source.write_text(
        "volatile int result = 0;\n"
        "__attribute__((noinline)) void helper() { ++result; }\n"
        "namespace demo { __attribute__((noinline)) void work() { helper(); } }\n"
        "__attribute__((noinline)) void after() { ++result; }\n"
        "int main() { demo::work(); after(); return result == 2 ? 0 : 1; }\n",
        encoding="utf-8",
    )
    (root / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20)\n"
        "project(InstrumentedDemo LANGUAGES CXX)\n"
        "add_executable(demo main.cpp)\n",
        encoding="utf-8",
    )
    model = DerivedModel(str(root), files={"main.cpp": FileInfo("main.cpp")})
    model.add_entity(Entity("main", Kind.FUNCTION, "main", "main", "main.cpp", 5,
                            signature="int main()"))
    model.add_entity(Entity("work", Kind.FUNCTION, "work", "demo::work", "main.cpp", 3,
                            signature="void work()"))
    model.add_entity(Entity("helper", Kind.FUNCTION, "helper", "helper", "main.cpp", 2,
                            signature="void helper()"))
    model.add_entity(Entity("after", Kind.FUNCTION, "after", "after", "main.cpp", 4,
                            signature="void after()"))
    regular_directory = root / "build/debug"
    regular_directory.mkdir(parents=True)
    marker = regular_directory / "untouched"
    marker.write_text("ordinary build", encoding="utf-8")
    target = executables.Target(
        "demo", "Debug", regular_directory, regular_directory / "demo",
        frozenset({str(source.resolve())}),
    )
    entry = executables.Entry("main", "main.cpp", 5, target)

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
    assert playback.status == "call 3 of 4: helper"
    assert playback.next_call() is model.entities["after"]
    assert playback.next_call() is None
    playback.seek_first_call("helper")
    assert playback.step_out() is model.entities["after"]
    assert playback.step_out() is None
    assert playback.current_entity is model.entities["after"]
    playback.reset()
    assert playback.step_into() is model.entities["main"]
    assert playback.step_into() is model.entities["work"]
    assert playback.step_over() is model.entities["after"]
    assert playback.status == "call 4 of 4: after"
    assert playback.step_into() is None
    assert not playback.can_step("into")
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
    directory.mkdir(parents=True)
    (directory / "icoda_call_trace_runtime.dll").write_bytes(b"updated runtime")
    deployed = tmp_path / "icoda_call_trace_runtime.dll"
    deployed.write_bytes(b"stale runtime")
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
        if command == [str(target.artifact)]:
            assert deployed.read_bytes() == b"updated runtime"
        return process.ProcessResult(command, 0, "ok\n", "")

    monkeypatch.setattr(process, "run_bounded", run)
    model = DerivedModel(str(tmp_path), files={"m.cpp": FileInfo("m.cpp")})
    model.add_entity(Entity("main", Kind.FUNCTION, "main", "main", "m.cpp", 1))
    outcome = executables.operate(
        tmp_path, model, selected, "run", lambda: False, options)

    assert len(calls) == 3 and all(env["PATH"].startswith(str(directory)) for _, env in calls)
    loader_path = "PATH" if executables.sys.platform == "win32" else (
        "DYLD_LIBRARY_PATH" if executables.sys.platform == "darwin" else "LD_LIBRARY_PATH")
    assert all(env[loader_path].startswith(str(directory)) for _, env in calls)
    assert outcome.message.endswith(f"call trace: {files.trace_file}")
    assert outcome.trace_file == files.trace_file
    assert executables.Outcome((), None, "", "ordinary run").trace_file is None
