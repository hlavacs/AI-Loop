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


@pytest.fixture
def visual_studio_tools(tmp_path, monkeypatch):
    from pathlib import Path

    from icoda_core import toolchain

    install = tmp_path / "Visual Studio"
    llvm = install / "VC/Tools/Llvm/x64/bin"
    cmake = install / "Common7/IDE/CommonExtensions/Microsoft/CMake"
    tools = {"cmake": cmake / "CMake/bin/cmake.exe", "ninja": cmake / "Ninja/ninja.exe",
             "clang": llvm / "clang++.exe", "llvm-symbolizer": llvm / "llvm-symbolizer.exe"}
    vswhere = tmp_path / "Microsoft Visual Studio/Installer/vswhere.exe"
    for path in (*tools.values(), vswhere, llvm / "clang.exe", llvm / "clang-scan-deps.exe"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.setattr(toolchain.sys, "platform", "win32")
    monkeypatch.setattr(os, "environ", {"PATH": "", "ProgramFiles(x86)": str(tmp_path), "KEEP": "original"})
    monkeypatch.setattr(toolchain, "candidates", lambda **_kwargs: [])

    def which(name, *, path=None):
        candidates = [Path(name)] if Path(name).is_absolute() else [
            Path(directory) / (name + ".exe") for directory in (path or "").split(os.pathsep) if directory]
        return next((str(candidate) for candidate in candidates if candidate.is_file()), None)

    monkeypatch.setattr(toolchain.shutil, "which", which)
    return install, tools, vswhere


def test_service_finds_vs_bundled_tools_without_path(visual_studio_tools, monkeypatch):
    from icoda_core import toolchain
    from icoda_core.service import Service

    install, tools, vswhere = visual_studio_tools
    before, calls = dict(os.environ), []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "cmd.exe":
            assert command[1:3] == ["/d", "/c"]
            assert command[3] == "call %ICODA_VCVARS_COMMAND% >nul && set"
            assert kwargs["env"]["ICODA_VCVARS_COMMAND"] == f'"{install / "VC/Auxiliary/Build/vcvars64.bat"}"'
            output = "Path=\nINCLUDE=windows-sdk\nLIB=sdk-libs\nKEEP=original\n"
        elif command[0] == str(vswhere):
            output = str(install) + "\n"
        else:
            assert command == [str(tools["clang"]), "--version"]
            assert kwargs["env"]["INCLUDE"] == "windows-sdk" and kwargs["env"]["LIB"] == "sdk-libs"
            output = "clang version 18.1.8"
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(toolchain.subprocess, "run", run)
    backend = Service()
    backend.initialize({"protocolVersion": 1})
    report = backend.dispatch({"method": "toolchain.inspect", "params": {}})
    assert report["tools"] == [{"name": name, "path": str(path), "source": "discovered"}
                               for name, path in tools.items()]
    assert not report["errors"] and not report["diagnostics"]
    assert report["environment"]["INCLUDE"] == "windows-sdk" and report["environment"]["LIB"] == "sdk-libs"
    assert report["environment"]["CXX"] == str(tools["clang"])
    assert "KEEP" not in report["environment"] and len(calls) == 3 and os.environ == before
