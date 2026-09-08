"""Diagnostic for the Mac: parse one consumer unit of the sample project with several argument variants.

Run from icoda/:  ./.icoda-venv/bin/python tests/diag_apple.py
Writes tests/sample_project/.icoda/diag.log, which ICODA's author reads from the connected folder.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from icoda_core import analysis, toolchain

ROOT = Path(__file__).resolve().parent / "sample_project"
OUT = ROOT / ".icoda" / "diag.log"


def run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout.strip()
    except OSError as exc:
        return f"<{exc}>"


def main() -> None:
    lines = [run(["clang++", "--version"]).splitlines()[0] if run(["clang++", "--version"]) else "no clang++",
             run(["cmake", "--version"]).splitlines()[0] if run(["cmake", "--version"]) else "no cmake",
             "sdk: " + (toolchain.default_sysroot() or "none")]
    commands = analysis.load_compile_commands(ROOT)
    smoke = next(c for c in commands if c.file.endswith("smoke_test.cpp"))
    beside = toolchain.library_beside(smoke.compiler)
    lines.append(f"library beside {smoke.compiler}: {beside}")
    lines.append(f"candidates: {[c.path for c in toolchain.candidates()]}")
    loaded = toolchain.load(beside or toolchain.candidates()[0].path)
    lines.append(loaded.describe())
    lines.append(f"compile command: {smoke.compiler} {' '.join(smoke.arguments)}")
    pcms = sorted(str(p) for p in Path(smoke.directory).rglob("*.pcm"))
    lines.append(f"pcm files: {pcms}")
    resource = {smoke.compiler: r} if (r := toolchain.resource_dir(smoke.compiler)) else {}
    parser = analysis.Parser(resource, toolchain.default_sysroot(), loaded.apple)
    base = parser.arguments(smoke)
    lines.append(f"icoda arguments: {base}")
    from clang import cindex

    explicit = [f"-fmodule-file={Path(p).stem}={p}" for p in pcms]
    variants = {
        "as icoda": base,
        "+ -fmodules": [*base, "-fmodules"],
        "+ -fcxx-modules": [*base, "-fcxx-modules"],
        "+ -x c++": ["-x", "c++", *base],
        "explicit -fmodule-file": [a for a in base if not a.startswith("-fprebuilt")] + explicit,
        "-std=c++20 only": [a if not a.startswith("-std=") else "-std=c++20" for a in base],
        "no -arch": [a for i, a in enumerate(base) if a != "-arch" and (i == 0 or base[i - 1] != "-arch")],
    }
    for name, args in variants.items():
        unit = parser.index.parse(smoke.file, args=args)
        errors = [d.spelling for d in unit.diagnostics if d.severity >= cindex.Diagnostic.Error]
        lines.append(f"[{name}] errors: {errors[:3]}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
