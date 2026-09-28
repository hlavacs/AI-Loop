"""Finding and loading libclang, its version, and the compiler's resource directory."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

# Apple's clang numbering differs from LLVM's; this table maps the Apple major version to the LLVM major
# version it was branched from (Xcode 13 -> LLVM 12, Xcode 14 -> 14, Xcode 15 -> 16, Xcode 16 -> 17,
# Xcode 16.3+ -> 19). Unknown majors fall back to the Apple number itself.
APPLE_TO_LLVM_MAJOR = {12: 10, 13: 12, 14: 14, 15: 16, 16: 17, 17: 19}


def clang_build_environment(preferred: str | None = None, *, environ: Mapping[str, str] | None = None,
                            preferred_only: bool = False, cancel_event: threading.Event | None = None) -> dict[str, str]:
    """Select module-capable Clang on every host, including the Windows SDK environment."""
    environment = dict(os.environ if environ is None else environ)
    if sys.platform == "win32" and environ is None:
        environment = _windows_build_environment(environment, **({"cancel_event": cancel_event} if cancel_event else {}))
    choices = [preferred] if preferred_only else _clang_choices(preferred, environment, cancel_event)
    for choice in dict.fromkeys(choices):
        if not choice:
            continue
        resolved = shutil.which(choice, path=environment.get("PATH"))
        if resolved is None:
            continue
        compiler = Path(resolved)
        if sys.platform == "win32":
            compiler = compiler.resolve()  # Expand CMake's Windows short paths.
        if not re.fullmatch(r"clang\+\+(?:-[0-9]+)?(?:\.exe)?", compiler.name, re.IGNORECASE):
            continue
        suffix = compiler.stem.removeprefix("clang++") if sys.platform == "win32" else compiler.name.removeprefix("clang++")
        extension = ".exe" if sys.platform == "win32" else ""
        scanner = next((compiler.with_name(f"clang-scan-deps{s}{extension}") for s in (suffix, "")
                        if compiler.with_name(f"clang-scan-deps{s}{extension}").is_file()), None)
        c_compiler = compiler.with_name(f"clang{suffix}{extension}")
        if scanner is None or not c_compiler.is_file():
            continue
        result = _probe([str(compiler), "--version"], environment, 30, cancel_event)
        match = re.search(r"clang version (\d+)", result.stdout + result.stderr)
        if result.returncode or match is None or int(match.group(1)) < 16:
            continue
        environment.update(CC=str(c_compiler), CXX=str(compiler))
        environment["PATH"] = str(compiler.parent) + os.pathsep + environment.get("PATH", "")
        return environment
    raise RuntimeError("Clang 16+ with clang-scan-deps is required to build C++. Install LLVM "
                       "(Homebrew LLVM on macOS, the Visual Studio LLVM component on Windows).")


def _clang_choices(preferred: str | None, environment: Mapping[str, str],
                   cancel_event: threading.Event | None = None) -> list[str | None]:
    """Share the desktop's compiler preference and installed-tool discovery order."""
    choices = [preferred, environment.get("CXX")]
    if sys.platform == "darwin" and shutil.which("brew", path=environment.get("PATH")):
        result = _probe(["brew", "--prefix", "llvm"], environment, 30, cancel_event)
        if result.returncode == 0:
            choices.append(str(Path(result.stdout.strip()) / "bin/clang++"))
    choices.append(shutil.which("clang++", path=environment.get("PATH")))
    if sys.platform.startswith("linux"):
        versioned = [path for directory in os.get_exec_path(environment)
                     for path in Path(directory).glob("clang++-[0-9]*")]
        choices.extend(str(path) for path in sorted(versioned, key=lambda p: _version_key(p.name), reverse=True))
    for candidate in candidates(platform=sys.platform, environ=environment):
        directory = Path(candidate.path).parent
        choices.append(str(directory / ("clang++.exe" if sys.platform == "win32" else "../bin/clang++")))
    return choices


def _windows_build_environment(environment: dict[str, str], *,
                               cancel_event: threading.Event | None = None) -> dict[str, str]:
    """Load Visual Studio's SDK paths even when ICODA starts outside a developer prompt."""
    base = environment.get("ProgramFiles(x86)", environment.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    vswhere = Path(base) / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.is_file():
        return environment
    result = _probe([str(vswhere), "-latest", "-prerelease", "-products", "*", "-requires",
                             "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
                    environment, 30, cancel_event)
    if result.returncode or not result.stdout.strip():
        return environment
    install = Path(result.stdout.strip().splitlines()[-1])
    vcvars = install / "VC/Auxiliary/Build/vcvars64.bat"
    # Expand the quoted batch path inside cmd; avoid embedded quotes in Windows argv serialization.
    probe_env = {**environment, "ICODA_VCVARS_COMMAND": f'"{vcvars}"'}
    result = _probe([environment.get("COMSPEC", "cmd.exe"), "/d", "/c", "call %ICODA_VCVARS_COMMAND% >nul && set"],
                    probe_env, 60, cancel_event)
    if result.returncode:
        raise RuntimeError("Could not initialize Visual Studio's C++ environment: " + result.stderr.strip())
    previous_command = environment.get("ICODA_VCVARS_COMMAND")
    environment = {key.upper(): value for line in result.stdout.splitlines()
                   if "=" in line and not line.startswith("=") for key, value in [line.split("=", 1)]}
    environment.pop("ICODA_VCVARS_COMMAND", None)
    if previous_command is not None:
        environment["ICODA_VCVARS_COMMAND"] = previous_command
    directories = [install / "VC/Tools/Llvm/x64/bin",
                   install / "Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin",
                   install / "Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja"]
    environment["PATH"] = os.pathsep.join(map(str, directories)) + os.pathsep + environment.get("PATH", "")
    return environment


TOOL_SETTINGS = {"cmake": "cmakePath", "ninja": "ninjaPath", "clang": "clangPath",
                 "llvm-symbolizer": "llvmSymbolizerPath"}


def inspect_tools(overrides: Mapping[str, str], *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
    """Inspect independent tools and a child-only environment; never alter the process environment."""
    original = dict(os.environ)
    environment, diagnostics = dict(original), []
    if sys.platform == "win32":
        try:
            environment = _windows_build_environment(environment, **({"cancel_event": cancel_event} if cancel_event else {}))
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            diagnostics.append(str(exc))
    compiler = None
    try:
        environment = clang_build_environment(overrides.get("clangPath"), environ=environment,
                                              preferred_only=bool(overrides.get("clangPath")),
                                              **({"cancel_event": cancel_event} if cancel_event else {}))
        compiler = environment["CXX"]
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        diagnostics.append(str(exc))
    tools = [_inspect_tool(name, overrides.get(key), compiler, environment, original)
             for name, key in TOOL_SETTINGS.items()]
    directories = list(dict.fromkeys(str(Path(tool["path"]).parent) for tool in tools if tool["path"]))
    if directories:
        environment["PATH"] = os.pathsep.join([*directories, environment.get("PATH", "")])
    baseline = {key.upper() if sys.platform == "win32" else key: value for key, value in original.items()}
    additions = {key: value for key, value in environment.items() if baseline.get(key) != value}
    return {"tools": tools, "environment": additions, "diagnostics": diagnostics}


def _probe(command: list[str], environment: Mapping[str, str], timeout: float,
           cancel_event: threading.Event | None) -> subprocess.CompletedProcess[str]:
    """Give service discovery probes the same request ownership as builds."""
    if cancel_event is None:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                              check=False, env=environment)
    from icoda_core import process

    result = process.run_bounded(command, env=environment, timeout=timeout, cancel_event=cancel_event)
    if result.cancelled:
        raise InterruptedError("Tool discovery cancelled.")
    if result.timed_out:
        raise subprocess.TimeoutExpired(command, timeout)
    return subprocess.CompletedProcess(command, result.returncode, result.stdout, result.stderr)


def _inspect_tool(name: str, override: str | None, compiler: str | None,
                  environment: Mapping[str, str], original: Mapping[str, str]) -> dict[str, Any]:
    """Resolve explicit overrides first, retaining provenance and independent missing results."""
    command = "clang++" if name == "clang" else name
    path = compiler if name == "clang" else shutil.which(override or command, path=environment.get("PATH"))
    if path is None and name == "llvm-symbolizer" and not override:
        suffix = ".exe" if sys.platform == "win32" else ""
        path = next((str(tool) for candidate in candidates(platform=sys.platform, environ=environment)
                     if (tool := Path(candidate.path).parent / ("" if suffix else "../bin")
                         / (command + suffix)).is_file()), None)
    inherited = shutil.which(command, path=original.get("PATH", ""))
    source = "missing" if path is None else "override" if override else (
        "path" if inherited and os.path.abspath(path) == os.path.abspath(inherited) else "discovered")
    return {"name": name, "path": os.path.abspath(path) if path else None, "source": source}


@dataclass(frozen=True)
class Candidate:
    """A libclang library that might be usable, and where the guess comes from."""

    path: str
    source: str


@dataclass(frozen=True)
class Selection:
    """The deterministic active candidate and the developer-visible reason for it."""

    candidates: tuple[Candidate, ...]
    active: Candidate | None
    preferred_path: str | None
    reason: str


@dataclass(frozen=True)
class Loaded:
    """The libclang in use, once loaded and self-tested."""

    path: str
    version: str
    llvm_major: int
    apple: bool

    def describe(self) -> str:
        flavour = "Apple clang" if self.apple else "clang"
        return f"libclang: {flavour} {self.version} (LLVM {self.llvm_major}) — {self.path}"


def _mac_candidates(globber: Callable[[str], Iterable[str]]) -> list[Candidate]:
    xcode = "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/libclang.dylib"
    found: list[Candidate] = []
    for pattern in ("/opt/homebrew/opt/llvm*/lib/libclang.dylib", "/usr/local/opt/llvm*/lib/libclang.dylib"):
        found.extend(Candidate(p, "homebrew") for p in sorted(globber(pattern), reverse=True))
    found.extend([Candidate(xcode, "xcode"),
                  Candidate("/Library/Developer/CommandLineTools/usr/lib/libclang.dylib", "clt")])
    return found


def _windows_candidates(environ: Mapping[str, str], globber: Callable[[str], Iterable[str]]) -> list[Candidate]:
    found: list[Candidate] = []
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        base = environ.get(var) or environ.get(var.upper())
        if not base:
            continue
        pattern = os.path.join(base, "Microsoft Visual Studio", "*", "*", "VC", "Tools", "Llvm", "x64", "bin",
                               "libclang.dll")
        found.extend(Candidate(p, "vs") for p in sorted(globber(pattern), reverse=True))
        found.append(Candidate(os.path.join(base, "LLVM", "bin", "libclang.dll"), "llvm"))
    return found


def _linux_candidates(globber: Callable[[str], Iterable[str]]) -> list[Candidate]:
    found: list[Candidate] = []
    for pattern in ("/usr/lib/llvm-*/lib/libclang.so.1", "/usr/lib/llvm-*/lib/libclang.so",
                    "/usr/lib/*/libclang-*.so.1", "/usr/lib64/libclang.so*", "/usr/lib/libclang.so*"):
        found.extend(Candidate(p, "linux") for p in sorted(globber(pattern), key=_version_key, reverse=True))
    return found


def _version_key(path: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", path))


def library_beside(compiler: str) -> str | None:
    """The libclang shipped with ``compiler`` (``<prefix>/bin/clang++`` -> ``<prefix>/lib/libclang.*``), if any."""
    prefix = Path(compiler).resolve().parent.parent
    for name in ("libclang.dylib", "libclang.so", "libclang.dll", "libclang.so.1"):
        candidate = prefix / ("bin" if name.endswith(".dll") else "lib") / name
        if candidate.exists():
            return str(candidate)
    return None


def wheel_library() -> Candidate | None:
    """The library bundled in the ``libclang`` pip wheel, if that wheel is installed."""
    try:
        import clang
    except ImportError:
        return None
    native = Path(clang.__file__).parent / "native"
    for name in ("libclang.dylib", "libclang.so", "libclang.dll"):
        if (native / name).exists():
            return Candidate(str(native / name), "wheel")
    return None


def candidates(platform: str = sys.platform, environ: Mapping[str, str] | None = None,
               exists: Callable[[str], bool] = os.path.exists,
               globber: Callable[[str], Iterable[str]] | None = None) -> list[Candidate]:
    """Usable libclang libraries in preference order: ICODA_LIBCLANG, the toolchain, then the pip wheel."""
    import glob as glob_module

    environ = os.environ if environ is None else environ
    globber = globber or glob_module.glob
    found: list[Candidate] = []
    if environ.get("ICODA_LIBCLANG"):
        found.append(Candidate(environ["ICODA_LIBCLANG"], "env"))
    if platform == "darwin":
        found.extend(_mac_candidates(globber))
    elif platform == "win32":
        found.extend(_windows_candidates(environ, globber))
    else:
        found.extend(_linux_candidates(globber))
    wheel = wheel_library()
    if wheel is not None:
        found.append(wheel)
    return [c for c in found if exists(c.path)]


def select_candidate(detected: Iterable[Candidate], preferred_path: str | None) -> Selection:
    """Choose the persisted preference when detected, otherwise the first detected candidate."""
    unique: dict[str, Candidate] = {}
    for candidate in detected:
        unique.setdefault(candidate.path, candidate)
    choices = tuple(unique.values())
    preferred = next((candidate for candidate in choices if candidate.path == preferred_path), None)
    if preferred is not None:
        return Selection(choices, preferred, preferred_path, "Using the developer-selected libclang library.")
    active = choices[0] if choices else None
    if preferred_path is not None:
        if active is None:
            reason = (f"The preferred libclang library {preferred_path} is no longer detected; "
                      "no libclang libraries were detected.")
        else:
            reason = (f"The preferred libclang library {preferred_path} is no longer detected; "
                      f"automatically selected {active.path}.")
    elif active is None:
        reason = "No libclang libraries were detected."
    else:
        reason = "Automatically selected the first detected libclang library."
    return Selection(choices, active, preferred_path, reason)


def parse_version(text: str) -> tuple[str, int, bool]:
    """Return (version, llvm major, is Apple) from a ``clang --version``-style string."""
    apple = "Apple" in text
    match = re.search(r"version (\d+)\.(\d+)\.(\d+)", text)
    if not match:
        return (text.strip(), 0, apple)
    version = ".".join(match.groups())
    major = int(match.group(1))
    return (version, APPLE_TO_LLVM_MAJOR.get(major, major) if apple else major, apple)


def load(path: str) -> Loaded:
    """Point the bindings at ``path`` (once per process), read the version and parse a probe."""
    from clang import cindex

    if cindex.Config.loaded:
        current = cindex.conf.lib._name  # type: ignore[attr-defined]
        if os.path.realpath(current) != os.path.realpath(path):
            raise RuntimeError(f"libclang already loaded from {current}; restart ICODA to switch to {path}")
    else:
        # The bindings belong to one LLVM release; an older library (Apple's) lacks a few of the functions
        # they register. ICODA uses none of those, so missing functions must not abort the load.
        cindex.Config.set_compatibility_check(False)
        cindex.Config.set_library_file(path)
    version_text = _version_string(cindex)
    if not _self_test(cindex):
        raise RuntimeError(f"libclang at {path} loaded but could not parse a probe translation unit")
    version, major, apple = parse_version(version_text)
    return Loaded(path, version, major, apple)


def _version_string(cindex) -> str:  # type: ignore[no-untyped-def]
    function = cindex.conf.lib.clang_getClangVersion
    function.restype = cindex._CXString
    return str(cindex._CXString.from_result(function()))


def _self_test(cindex) -> bool:  # type: ignore[no-untyped-def]
    unit = cindex.Index.create().parse("icoda_probe.cpp", args=["-std=c++20"],
                                       unsaved_files=[("icoda_probe.cpp", "int icoda_probe() { return 1; }\n")])
    return any(c.kind == cindex.CursorKind.FUNCTION_DECL and c.spelling == "icoda_probe"
               for c in unit.cursor.get_children())


@lru_cache(maxsize=1)
def default_sysroot(platform: str = sys.platform) -> str | None:
    """On macOS, the SDK the compiler would use by itself (``SDKROOT`` or ``xcrun --show-sdk-path``)."""
    if platform != "darwin":
        return None
    if os.environ.get("SDKROOT"):
        return os.environ["SDKROOT"]
    try:
        result = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    path = result.stdout.strip()
    return path if result.returncode == 0 and path else None


@lru_cache(maxsize=16)
def resource_dir(compiler: str) -> str | None:
    """The compiler's builtin-header directory, passed to libclang as ``-resource-dir``."""
    try:
        result = subprocess.run([compiler, "-print-resource-dir"], capture_output=True, text=True, timeout=30,
                                check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    line = result.stdout.strip().splitlines()
    return line[-1] if result.returncode == 0 and line else None
