"""Keep the two independent applications isolated when pytest starts at the repository root."""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent


def _real_tkinter_modules() -> dict[str, types.ModuleType]:
    """Load the real Tk modules before ICODA installs its collection stub."""
    names = (
        "tkinter",
        "tkinter.filedialog",
        "tkinter.font",
        "tkinter.messagebox",
        "tkinter.scrolledtext",
        "tkinter.simpledialog",
        "tkinter.ttk",
    )
    try:
        return {name: importlib.import_module(name) for name in names}
    except ImportError:
        for name in tuple(sys.modules):
            if name == "tkinter" or name.startswith("tkinter."):
                sys.modules.pop(name)
        return {}


REAL_TKINTER_MODULES = _real_tkinter_modules()
ICODA_TKINTER_MODULES: dict[str, types.ModuleType] = {}


def _replace_tkinter_modules(modules: dict[str, types.ModuleType]) -> None:
    for name in tuple(sys.modules):
        if name == "tkinter" or name.startswith("tkinter."):
            sys.modules.pop(name)
    sys.modules.update(modules)


def pytest_collection_finish() -> None:
    """Restore real Tk for AI-Loop after ICODA's stub-backed collection."""
    ICODA_TKINTER_MODULES.update(
        (name, module)
        for name, module in sys.modules.items()
        if name == "tkinter" or name.startswith("tkinter.")
    )
    _replace_tkinter_modules(REAL_TKINTER_MODULES)


@pytest.fixture(autouse=True)
def isolate_application(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Give each application's tests its expected cwd and Tk implementation."""
    test_path = Path(str(request.path))
    if not test_path.is_absolute():
        test_path = Path(str(request.config.rootpath)) / test_path
    test_path = test_path.resolve()
    for application in (ROOT / "ai-loop", ROOT / "icoda"):
        if test_path.is_relative_to(application):
            modules = ICODA_TKINTER_MODULES if application.name == "icoda" else REAL_TKINTER_MODULES
            _replace_tkinter_modules(modules)
            monkeypatch.chdir(application)
            break
    try:
        yield
    finally:
        _replace_tkinter_modules(REAL_TKINTER_MODULES)
