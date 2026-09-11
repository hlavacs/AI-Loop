"""Host-independent checks for explicit platform-selection seams."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from icoda_core import steps


def _fail_linux_path_scan() -> list[str]:
    raise AssertionError("non-Linux build selection must not scan the Linux executable path")


def test_build_environment_macos_without_homebrew_uses_inherited_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    looked_up: list[str] = []

    def find_executable(name: str) -> str | None:
        looked_up.append(name)
        return None

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("CXX", raising=False)
    monkeypatch.setattr(shutil, "which", find_executable)
    monkeypatch.setattr(os, "get_exec_path", _fail_linux_path_scan)

    assert steps.build_environment(tmp_path) is None
    assert looked_up == ["brew"]


def test_build_environment_windows_without_clang_cl_uses_inherited_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    looked_up: list[str] = []

    def find_executable(name: str) -> str | None:
        looked_up.append(name)
        return None

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("CXX", raising=False)
    monkeypatch.setattr(shutil, "which", find_executable)
    monkeypatch.setattr(os, "get_exec_path", _fail_linux_path_scan)

    assert steps.build_environment(tmp_path) is None
    assert looked_up == ["clang-cl"]
