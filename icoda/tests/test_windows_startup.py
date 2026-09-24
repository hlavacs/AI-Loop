"""Desktop startup discovers installed Windows build tools before reporting missing ones."""
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest


def test_main_initializes_tools_before_checks_and_app_start(app_module, monkeypatch, capsys):
    environment = {"PATH": "ordinary-shell", "VCPKG_ROOT": "vcpkg"}
    monkeypatch.setattr(os, "environ", environment)
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    monkeypatch.setattr(app_module.toolchain, "_windows_build_environment",
                        lambda env: dict(env, PATH="visual-studio-tools", INCLUDE="windows-sdk", LIB="sdk-libs"))
    looked_up = []

    def which(name):
        looked_up.append((name, os.environ["PATH"]))
        return "installed-tool" if os.environ["PATH"] == "visual-studio-tools" else None

    monkeypatch.setattr(shutil, "which", which)
    started = []

    def app(*args, **kwargs):
        started.append(dict(os.environ))
        return SimpleNamespace(config=SimpleNamespace(last_project=""))

    monkeypatch.setattr(app_module, "App", app)
    assert app_module.main([]) == 0
    assert started[0]["PATH"] == "visual-studio-tools"
    assert started[0]["INCLUDE"] == "windows-sdk" and started[0]["LIB"] == "sdk-libs"
    assert looked_up == [(name, "visual-studio-tools") for name in ("cmake", "ninja", "clang-cl")]
    assert not capsys.readouterr().err


def test_only_tools_still_missing_after_discovery_are_reported(app_module, monkeypatch, capsys):
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    monkeypatch.setattr(os, "environ", {"PATH": "existing"})
    monkeypatch.setattr(app_module.toolchain, "_windows_build_environment", lambda env: env)
    monkeypatch.setattr(shutil, "which", lambda name: "installed" if name == "cmake" else None)
    app_module.configure_windows_toolchain()
    output = capsys.readouterr().err
    assert "ninja not found" in output and "clang-cl not found" in output
    assert "cmake not found" not in output and "VCPKG_ROOT is not set" in output


@pytest.mark.parametrize("error", [RuntimeError("SDK initialization failed"),
                                  subprocess.TimeoutExpired("vcvars64.bat", 60), OSError("cannot start vswhere")])
def test_toolchain_initialization_failure_keeps_viewer_usable(app_module, monkeypatch, capsys, error):
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    monkeypatch.setattr(os, "environ", {"PATH": "existing", "VCPKG_ROOT": "vcpkg"})

    def fail(env):
        raise error

    monkeypatch.setattr(app_module.toolchain, "_windows_build_environment", fail)
    monkeypatch.setattr(shutil, "which", lambda name: "installed")
    app_module.configure_windows_toolchain()
    assert os.environ["PATH"] == "existing"
    assert str(error) in capsys.readouterr().err


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_other_platforms_do_not_initialize_windows_tools(app_module, monkeypatch, capsys, platform):
    monkeypatch.setattr(app_module.sys, "platform", platform)
    monkeypatch.setattr(app_module.toolchain, "_windows_build_environment",
                        lambda env: pytest.fail("Windows discovery on another platform"))
    app_module.configure_windows_toolchain()
    assert not capsys.readouterr().err
