"""Build and CTest are separate stages with independently trustworthy outcomes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from icoda_core import steps
from icoda_core.process import ProcessResult


def _result(command: list[str], returncode: int, stdout: str) -> ProcessResult:
    return ProcessResult(command, returncode, stdout, "")


def test_build_failure_skips_tests(tmp_path: Path) -> None:
    (tmp_path / "build.sh").write_text("", encoding="utf-8")
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: Any) -> ProcessResult:
        commands.append(command)
        return _result(command, 1, "compiler error")

    result = steps.build_project(tmp_path, runner=run)
    assert commands == [["bash", "build.sh", "debug", "build-only"]]
    assert not result.build_passed and result.tests_passed is None
    assert result.build_output == "compiler error" and result.test_output == ""


def test_test_failure_is_distinct_from_a_successful_build(tmp_path: Path) -> None:
    (tmp_path / "build.sh").write_text("", encoding="utf-8")
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: Any) -> ProcessResult:
        commands.append(command)
        return _result(command, 1 if command[0] == "ctest" else 0,
                       "assertion failed" if command[0] == "ctest" else "linked")

    result = steps.build_project(tmp_path, runner=run)
    assert commands[-1] == ["ctest", "--preset", "debug"]
    assert result.build_passed and result.tests_passed is False and not result.ok
    assert result.build_output == "linked" and result.test_output == "assertion failed"


def test_build_and_tests_must_both_pass() -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: Any) -> ProcessResult:
        calls.append(command)
        return _result(command, 0, "ok")

    result = steps.build_project(Path("/project"), runner=run)
    assert calls == [["cmake", "--preset", "debug"], ["cmake", "--build", "--preset", "debug"],
                     ["ctest", "--preset", "debug"]]
    assert result.ok and result.build_output == "okok" and result.test_output == "ok"
