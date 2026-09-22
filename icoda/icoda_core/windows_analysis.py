"""Prepare Clang-readable analysis modules for projects compiled with MSVC.

MSVC's IFC files cannot be read by libclang. Build separate PCM files in ICODA's
cache using the Clang installation that supplies libclang; never change the build.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from icoda_core import analysis, toolchain


def is_msvc(command: analysis.CompileCommand) -> bool:
    return Path(command.compiler).name.lower() in {"cl", "cl.exe"}


def clang_arguments(command: analysis.CompileCommand) -> list[str]:
    """Translate preprocessing/language settings, excluding MSVC output and IFC flags."""
    result = ["-x", "c++", "-D_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH"]
    arguments = iter(command.arguments)
    for argument in arguments:
        option = "-" + argument[1:] if argument.startswith("/") else argument
        if option in ("-reference", "-ifcOutput", "-Fo", "-Fd"):
            next(arguments, None)
        elif option.startswith("-external:I"):
            result += ["-isystem", option[len("-external:I"):] or next(arguments)]
        elif option.startswith(("-D", "-I", "-U")):
            result.append(option)
            if option in ("-D", "-I", "-U"):
                result.append(next(arguments))
        elif option.startswith("-FI"):
            result += ["-include", option[3:] or next(arguments)]
        elif option.startswith("-std:"):
            standard = option[5:]
            # MSVC uses latest for CMake's C++23 mode.
            result.append("-std=" + ("c++23" if standard == "c++latest" else standard))
        elif option in ("-MD", "-MDd", "-MT", "-MTd"):
            runtime = {"-MD": "dll", "-MDd": "dll_dbg", "-MT": "static", "-MTd": "static_dbg"}
            result.append("-fms-runtime-lib=" + runtime[option])
        elif option == "-TC":
            result[1] = "c"
    return result


def references(command: analysis.CompileCommand) -> tuple[str, ...]:
    arguments = iter(command.arguments)
    return tuple(next(arguments).split("=", 1)[0] for argument in arguments
                 if argument in ("-reference", "/reference"))


def _stamp(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _current(manifest: Path, invocation: list[str]) -> bool:
    try:
        saved = json.loads(manifest.read_text(encoding="utf-8"))
        return saved["command"] == invocation and all(
            list(_stamp(Path(path))) == stamp for path, stamp in saved["inputs"].items())
    except (OSError, ValueError, KeyError):
        return False


def prepare(commands: Sequence[analysis.CompileCommand], loaded: toolchain.Loaded,
            cache: Path, progress: Callable[[str], None]) -> list[analysis.CompileCommand]:
    """Translate MSVC commands and build their referenced modules in dependency order."""
    if not any(is_msvc(command) for command in commands):
        return list(commands)
    compiler = Path(loaded.path).with_name("clang++.exe")
    if not compiler.is_file():
        raise RuntimeError(f"MSVC analysis requires clang++.exe beside {loaded.path}")
    cache = cache / "clang-modules"
    cache.mkdir(parents=True, exist_ok=True)
    modules: dict[str, analysis.CompileCommand] = {}
    for command in commands:
        if is_msvc(command) and command.module_unit:
            name, kind = analysis.module_declaration(Path(command.file).read_text(encoding="utf-8"))
            if kind == "interface":
                modules[name] = command
    built: dict[str, Path] = {}
    visiting: set[str] = set()

    def build(name: str) -> Path:
        if name in built:
            return built[name]
        if name in visiting:
            raise RuntimeError(f"Cyclic MSVC module references: {name}")
        if name not in modules:
            raise RuntimeError(f"No source compile command for MSVC module {name}")
        visiting.add(name)
        command = modules[name]
        dependencies = {dependency: build(dependency) for dependency in references(command)}
        flags = [f"-fmodule-file={dependency}={path}" for dependency, path in dependencies.items()]
        output = cache / (hashlib.sha256(name.encode()).hexdigest()[:20] + ".pcm")
        manifest, depfile = output.with_suffix(".json"), output.with_suffix(".d")
        args = clang_arguments(command)
        args[1] = "c++-module"
        invocation = [str(compiler), *args, *flags, "-Wno-include-angled-in-module-purview",
                      "--precompile", command.file, "-o", str(output), "-MD", "-MF", str(depfile)]
        if not output.is_file() or not _current(manifest, invocation):
            progress(f"preparing Clang analysis module {name}")
            result = subprocess.run(invocation, cwd=command.directory, capture_output=True,
                                    text=True, errors="replace", timeout=180, check=False)
            if result.returncode:
                raise RuntimeError(f"Could not prepare analysis module {name}:\n{result.stderr[-6000:]}")
            # Clang escapes spaces in makefile paths, but Windows separators stay literal.
            dependency_text = depfile.read_text(encoding="utf-8").replace("\\\n", " ")
            dependency_text = re.split(r":\s", dependency_text, maxsplit=1)[1]
            paths = re.findall(r"(?:\\[ #]|[^\s])+", dependency_text)
            inputs = {Path(command.directory) / path.replace("\\ ", " ").replace("\\#", "#")
                      for path in paths}
            inputs.update((compiler, Path(loaded.path), Path(command.file), *dependencies.values()))
            manifest.write_text(json.dumps({"command": invocation,
                                           "inputs": {str(path): _stamp(path) for path in inputs}}),
                                encoding="utf-8")
        visiting.remove(name)
        built[name] = output
        return output

    prepared = []
    for command in commands:
        if not is_msvc(command):
            prepared.append(command)
            continue
        flags = [f"-fmodule-file={name}={build(name)}" for name in references(command)]
        args = clang_arguments(command) + flags
        prepared.append(replace(command, compiler=str(compiler), arguments=tuple(args)))
    return prepared
