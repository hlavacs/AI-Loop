"""The scaffold imports, the application constructs headless, and the command line is parsed."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

MODULES = ["model", "analysis", "clusters", "views", "specification", "git", "process", "steps",
           "generator", "agent", "implementation", "persistence"]


@pytest.mark.parametrize("name", MODULES)
def test_core_modules_import(name: str) -> None:
    module = importlib.import_module(f"icoda_core.{name}")
    assert module.__doc__, f"icoda_core.{name} needs a docstring"


def test_app_constructs_without_project(app_module) -> None:
    root = app_module.tk.Tk()
    app = app_module.App(root)
    assert app.project is None
    assert app.status.get() == "No project open"
    assert root.title() == "ICODA"


def test_app_opens_project_directory(app_module, tmp_path: Path) -> None:
    root = app_module.tk.Tk()
    app = app_module.App(root, tmp_path)
    assert app.project == tmp_path.resolve()
    assert root.title() == f"ICODA — {tmp_path.name}"
    assert str(tmp_path.resolve()) in app.status.get()


def test_parse_args(app_module, tmp_path: Path) -> None:
    assert app_module.parse_args([]) is None
    assert app_module.parse_args([str(tmp_path)]) == tmp_path
    with pytest.raises(SystemExit):
        app_module.parse_args(["a", "b"])
