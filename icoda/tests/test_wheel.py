"""The built wheel contains every module and runtime resource needed after installation."""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ICODA_DIR = Path(__file__).resolve().parent.parent
PACKAGES = ("icoda_core", "icoda_gui")
RUNTIME_DATA = (
    "icoda_core/providers.json",
    "icoda_core/response.schema.json",
    "icoda_core/specification.schema.json",
)
TOP_LEVEL_MODULES = ("icoda.py",)


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build once, offline, from a clean copy so build metadata stays in pytest's temporary directory."""
    temporary = tmp_path_factory.mktemp("wheel")
    source = temporary / "source"
    source.mkdir()
    shutil.copy2(ICODA_DIR / "pyproject.toml", source / "pyproject.toml")
    for module in TOP_LEVEL_MODULES:
        shutil.copy2(ICODA_DIR / module, source / module)
    for package in PACKAGES:
        shutil.copytree(ICODA_DIR / package, source / package,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    output = temporary / "dist"
    output.mkdir()
    environment = dict(os.environ, PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-w", str(output),
         str(source)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, (
        "The wheel build backend is missing from the running interpreter; "
        "`pip install -e './icoda[dev]'` provides it.\n"
        f"{result.stdout}{result.stderr}"
    )
    wheels = list(output.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


@pytest.fixture(scope="module")
def installed_wheel(built_wheel: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    destination = tmp_path_factory.mktemp("installed-wheel")
    with zipfile.ZipFile(built_wheel) as archive:
        archive.extractall(destination)
    return destination


def _entry_points(archive: zipfile.ZipFile) -> configparser.ConfigParser:
    entry_points_files = [name for name in archive.namelist() if name.endswith(".dist-info/entry_points.txt")]
    assert len(entry_points_files) == 1
    parser = configparser.ConfigParser()
    parser.read_string(archive.read(entry_points_files[0]).decode("utf-8"))
    return parser


def _isolated_python(installed_wheel: Path, script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("DISPLAY", None)
    return subprocess.run(
        [sys.executable, "-I", "-c", script, str(installed_wheel), *arguments],
        cwd=installed_wheel,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_wheel_contains_packages_runtime_data_and_entry_module(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        contents = set(archive.namelist())

    for package in PACKAGES:
        assert f"{package}/__init__.py" in contents
    for path in (*RUNTIME_DATA, *TOP_LEVEL_MODULES):
        assert path in contents


def test_wheel_declares_importable_console_entry_point_without_starting_tk(
        built_wheel: Path, installed_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        entry_points = _entry_points(archive)
    assert entry_points["console_scripts"]["icoda"] == "icoda:main"

    script = """
import importlib
import sys
import tkinter

sys.path.insert(0, sys.argv[1])

def fail_if_tk_starts(*args, **kwargs):
    raise AssertionError("importing the console entry point constructed a Tk root")

tkinter.Tk = fail_if_tk_starts
module_name, attribute = sys.argv[2].split(":", 1)
value = importlib.import_module(module_name)
for component in attribute.split("."):
    value = getattr(value, component)
assert callable(value)
"""
    result = _isolated_python(installed_wheel, script, entry_points["console_scripts"]["icoda"])
    assert result.returncode == 0, result.stdout + result.stderr


def test_specification_schema_resolves_from_unpacked_wheel(installed_wheel: Path) -> None:
    script = """
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from icoda_core import specification

installed = Path(sys.argv[1]).resolve()
assert Path(specification.__file__).resolve().is_relative_to(installed)
assert specification.SCHEMA_PATH.resolve().is_relative_to(installed)
assert specification.SCHEMA_PATH.is_file()
assert specification.validate(specification.default_specification("Installed wheel")) == []
"""
    result = _isolated_python(installed_wheel, script)
    assert result.returncode == 0, result.stdout + result.stderr
