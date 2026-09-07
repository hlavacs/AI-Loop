"""Test configuration: install the tkinter stub unless ICODA_TK_STUB=0."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ICODA_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ICODA_DIR))

if os.environ.get("ICODA_TK_STUB", "1") != "0":
    from tk_stub import install  # type: ignore[import-not-found]

    install()


def load_app_module():
    """Import icoda.py as a module (it is a script next to the icoda_core package)."""
    spec = importlib.util.spec_from_file_location("icoda_app", ICODA_DIR / "icoda.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def app_module():
    return load_app_module()
