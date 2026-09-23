"""Build and test gates have independently trustworthy outcomes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from icoda_core import cmake, steps
from icoda_core.process import ProcessResult


def _result(command: list[str], returncode: int, stdout: str) -> ProcessResult:
    return ProcessResult(command, returncode, stdout, "")


@pytest.fixture(autouse=True)
def configured_clang_plan(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(cmake, "clang_configuration", lambda _root: (
        tmp_path / "build/debug", ["cmake", "--preset", "debug"], {}))
    monkeypatch.setattr(cmake, "verify_clang", lambda _directory: None)


def test_cmake_gate_uses_the_assumed_debug_preset(tmp_path: Path) -> None:
    commands = steps.gate_commands(tmp_path, ("ctest",), code_profile={"language": "C++"})

    assert commands.build == [
        ["cmake", "--preset", steps.CMAKE_PRESET],
        ["cmake", "--build", "--preset", steps.CMAKE_PRESET],
    ]
    assert steps.CMAKE_PRESET == "debug"


def test_build_failure_stops_the_build_gate(tmp_path: Path, monkeypatch: Any) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: Any) -> ProcessResult:
        commands.append(command)
        return _result(command, 1, "compiler error")

    monkeypatch.setattr(steps, "run_bounded", run)
    monkeypatch.setattr(steps, "build_environment", lambda _root: None)
    result = steps.build_project(tmp_path, code_profile={"language": "C++"})
    assert commands == [["cmake", "--preset", "debug"]]
    assert result.ok is False and result.output == "compiler error"


def test_compile_failure_stops_after_configuration(tmp_path: Path, monkeypatch: Any) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: Any) -> ProcessResult:
        commands.append(command)
        return _result(command, int(command[:2] == ["cmake", "--build"]),
                       "compiler error" if "--build" in command else "configured\n")

    monkeypatch.setattr(steps, "run_bounded", run)
    monkeypatch.setattr(steps, "build_environment", lambda _root: None)

    result = steps.build_project(tmp_path, code_profile={"language": "C++"})

    assert commands == [["cmake", "--preset", "debug"], ["cmake", "--build", str(tmp_path / "build/debug")]]
    assert result == steps.BuildResult(False, "configured\ncompiler error")


def test_missing_test_command_is_a_distinct_not_run_gate(tmp_path: Path) -> None:
    assert steps.test_project(tmp_path, ()) == steps.TestResult(
        None, "No project test command is configured.")


def test_test_failure_is_distinct_from_a_successful_build(tmp_path: Path, monkeypatch: Any) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: Any) -> ProcessResult:
        commands.append(command)
        return _result(command, 1 if command[0] == "ctest" else 0,
                       "assertion failed" if command[0] == "ctest" else "linked")

    monkeypatch.setattr(steps, "run_bounded", run)
    monkeypatch.setattr(steps, "build_environment", lambda _root: None)
    build = steps.build_project(tmp_path, code_profile={"language": "C++"})
    test = steps.test_project(tmp_path, ["ctest", "--preset", "debug"])
    assert commands[-1] == ["ctest", "--preset", "debug"]
    assert build.ok is True and build.output == "linkedlinked"
    assert test.ok is False and test.output == "assertion failed"


def test_build_and_test_gates_can_both_pass(tmp_path: Path, monkeypatch: Any) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: Any) -> ProcessResult:
        calls.append(command)
        return _result(command, 0, "ok")

    monkeypatch.setattr(steps, "run_bounded", run)
    monkeypatch.setattr(steps, "build_environment", lambda _root: None)
    build = steps.build_project(tmp_path, code_profile={"language": "C++"})
    test = steps.test_project(tmp_path, ["ctest", "--preset", "debug"])
    assert calls == [["cmake", "--preset", "debug"], ["cmake", "--build", str(tmp_path / "build/debug")],
                     ["ctest", "--preset", "debug"]]
    assert build.ok is True and build.output == "okok"
    assert test.ok is True and test.output == "ok"
