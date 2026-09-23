"""Startup chooses the Clang build and displays work while the child is running."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from icoda_core import analysis, persistence, session


def database(root: Path, folder: str, compiler: str, timestamp: int, command: bool = False) -> Path:
    path = root / folder / "compile_commands.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    args = [compiler, "-c", "main.cpp"]
    entry = {"directory": str(path.parent), "file": "main.cpp"}
    entry.update({"command": subprocess.list2cmdline(args)} if command else {"arguments": args})
    path.write_text(json.dumps([entry]), encoding="utf-8")
    os.utime(path, (timestamp, timestamp))
    return path


@pytest.mark.parametrize("compiler", ["clang++", "clang++-22", "clang-cl.exe", "CLANG_~1.EXE"])
@pytest.mark.parametrize("command", [False, True])
def test_clang_build_wins_over_newer_msvc_database(tmp_path, compiler, command):
    expected = database(tmp_path, "build/llvm", compiler, 100, command)
    database(tmp_path, "build/debug-windows", "cl.exe", 200, command)
    assert analysis.find_compile_commands(tmp_path) == expected


def test_newest_database_within_the_same_toolchain_wins(tmp_path):
    database(tmp_path, "build/old", "clang++", 100)
    expected = database(tmp_path, "build/new", "clang++", 200)
    assert analysis.find_compile_commands(tmp_path) == expected


def test_msvc_only_project_can_still_be_analysed(tmp_path):
    expected = database(tmp_path, "build/debug", "cl.exe", 100)
    assert analysis.find_compile_commands(tmp_path) == expected


def test_progress_shows_source_and_module_without_long_compiler_flags(tmp_path):
    assert session.analysis_progress(tmp_path) == ""
    session.log_event("opening: analysis started", tmp_path)
    assert session.analysis_progress(tmp_path) == "Starting analysis"
    session.log_event("preparing Clang analysis module engine:render", tmp_path)
    assert session.analysis_progress(tmp_path) == "Preparing Clang analysis module engine:render"
    source = tmp_path / "src" / "engine.cpp"
    session.log_event(f"parsing {source} with -std=c++23 -Iprivate/path", tmp_path)
    assert session.analysis_progress(tmp_path) == f"Parsing {Path('src/engine.cpp')}"
    session.log_event("analysis: arranging diagram", tmp_path)
    assert session.analysis_progress(tmp_path) == "Arranging diagram"


def test_waiting_window_displays_analysis_progress(app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.project = tmp_path
    app._pending_analyses = 1
    session.log_event(f"parsing {tmp_path / 'main.cpp'} with -std=c++23", tmp_path)
    app._poll()
    assert app.status.get() == f"Analysing {tmp_path.name}: Parsing main.cpp"
    assert app._pending_analyses == 1
