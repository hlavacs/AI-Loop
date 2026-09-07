"""Finding and loading libclang, its version, and the compiler's resource directory."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Apple's clang numbering differs from LLVM's; this table maps the Apple major version to the LLVM major
# version it was branched from (Xcode 13 -> LLVM 12, Xcode 14 -> 14, Xcode 15 -> 16, Xcode 16 -> 17,
# Xcode 16.3+ -> 19). Unknown majors fall back to the Apple number itself.
APPLE_TO_LLVM_MAJOR = {12: 10, 13: 12, 14: 14, 15: 16, 16: 17, 17: 19}


@dataclass(frozen=True)
class Candidate:
    """A libclang library that might be usable, and where the guess comes from."""

    path: str
    source: str


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
    found = [Candidate(xcode, "xcode"),
             Candidate("/Library/Developer/CommandLineTools/usr/lib/libclang.dylib", "clt")]
    for pattern in ("/opt/homebrew/opt/llvm*/lib/libclang.dylib", "/usr/local/opt/llvm*/lib/libclang.dylib"):
        found.extend(Candidate(p, "homebrew") for p in sorted(globber(pattern), reverse=True))
    return found


def _windows_candidates(environ: Mapping[str, str], globber: Callable[[str], Iterable[str]]) -> list[Candidate]:
    found: list[Candidate] = []
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        base = environ.get(var)
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
