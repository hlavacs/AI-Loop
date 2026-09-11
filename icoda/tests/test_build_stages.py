"""Build and test gates have independently trustworthy outcomes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from icoda_core import steps
from icoda_core.process import ProcessResult


def _result(command: list[str], returncode: int, stdout: str) -> ProcessResult:
    return ProcessResult(command, returncode, stdout, "")


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
    assert calls == [["cmake", "--preset", "debug"], ["cmake", "--build", "--preset", "debug"],
                     ["ctest", "--preset", "debug"]]
    assert build.ok is True and build.output == "okok"
    assert test.ok is True and test.output == "ok"
