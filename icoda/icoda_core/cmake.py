"""Reuse a project's configured CMake tree and request metadata needed for analysis."""

import os
import shutil
import subprocess
from pathlib import Path

from icoda_core import analysis, instrumentation, toolchain

_PRESERVED_OPTIONS = {"CMAKE_BUILD_TYPE", "CMAKE_TOOLCHAIN_FILE", "CMAKE_PREFIX_PATH", "CMAKE_MODULE_PATH",
                      "CMAKE_OSX_ARCHITECTURES", "CMAKE_OSX_SYSROOT", "CMAKE_OSX_DEPLOYMENT_TARGET"}


def build_directory(root: Path) -> Path | None:
    """Prefer the analysed tree, then a completed configuration over a failed one."""
    database = analysis.find_compile_commands(root)
    analysed = [database.parent] if database else []
    if database:
        for command in analysis.load_compile_commands(database):
            directory = Path(command.directory)
            analysed.extend((directory, *directory.parents))
    candidates = [root / "build/debug", root / "build", *sorted(root.glob("build/*")), root]
    candidates.sort(key=lambda path: not any((path / name).is_file()
                    for name in ("build.ninja", "Makefile", "cmake_install.cmake")))
    for directory in dict.fromkeys([*analysed, *candidates]):
        cache = directory / "CMakeCache.txt"
        if cache.is_file():
            for line in cache.read_text(encoding="utf-8").splitlines():
                if line.startswith("CMAKE_HOME_DIRECTORY:INTERNAL="):
                    if Path(line.split("=", 1)[1]).resolve() == root.resolve():
                        return directory.resolve()
                    break
    return None


def configure_command(root: Path, directory: Path) -> list[str]:
    """Request targets and compiler commands while preserving cached toolchain settings."""
    query = directory / ".cmake/api/v1/query/client-icoda/codemodel-v2"
    query.parent.mkdir(parents=True, exist_ok=True)
    query.touch()
    return ["cmake", "-S", str(root), "-B", str(directory), "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]


def cache_values(directory: Path) -> dict[str, tuple[str, str]]:
    """Read typed cache entries without copying CMake's derived compiler settings."""
    path = directory / "CMakeCache.txt"
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(("//", "#")) or "=" not in line or ":" not in line.split("=", 1)[0]:
            continue
        declaration, value = line.split("=", 1)
        name, kind = declaration.split(":", 1)
        values[name] = (kind, value)
    return values


def clang_configuration(root: Path) -> tuple[Path, list[str], dict[str, str]]:
    """Reuse a Clang tree or configure an isolated one with the project's existing options."""
    previous = build_directory(root)
    cached = cache_values(previous) if previous else {}
    environment = toolchain.clang_build_environment(cached.get("CMAKE_CXX_COMPILER", ("", ""))[1])
    compiler = Path(environment["CXX"]).resolve()
    recorded_cmake = cached.get("CMAKE_COMMAND", ("", ""))[1]
    cmake_exe = recorded_cmake if recorded_cmake and Path(recorded_cmake).is_file() else (
        shutil.which("cmake", path=environment.get("PATH")))
    if cmake_exe is None:
        raise RuntimeError("CMake is required to build this project.")
    directories = [previous] if previous else []
    directories += [root / "build/debug-clang", *sorted(root.glob("build/*"))]
    for directory in dict.fromkeys(directories):
        values = cache_values(directory)
        configured = values.get("CMAKE_CXX_COMPILER", ("", ""))[1]
        source = values.get("CMAKE_HOME_DIRECTORY", ("", ""))[1]
        generator = values.get("CMAKE_GENERATOR", ("", ""))[1]
        if (configured and Path(configured).resolve() == compiler and source
                and Path(source).resolve() == root.resolve() and ("Ninja" in generator or "Makefiles" in generator)):
            command = configure_command(root, directory)
            command[0] = cmake_exe
            return directory, command, environment
    directory = root / "build" / ("debug-clang" if previous else "debug")
    if (directory / "CMakeCache.txt").exists():
        raise RuntimeError(f"{directory} already uses a different toolchain. Choose a new build directory "
                           "or move that build aside before building with Clang.")
    ninja = shutil.which("ninja", path=environment.get("PATH"))
    if ninja is None:
        raise RuntimeError("Ninja is required to create the Clang build. Install Ninja and retry Build.")
    command = configure_command(root, directory)
    command[0] = cmake_exe
    if previous is None and (root / "CMakePresets.json").is_file():
        presets = subprocess.run([cmake_exe, "--list-presets"], cwd=root, env=environment,
                                 capture_output=True, text=True, timeout=30, check=False)
        preset = next((name for name in ("debug-clang", "debug") if f'"{name}"' in presets.stdout), None)
        if presets.returncode == 0 and preset:
            command[1:1] = ["--preset", preset]
    # Project/dependency options survive migration; compiler flags and generated paths do not.
    command += [f"-D{name}:{kind}={value}" for name, (kind, value) in cached.items()
                if kind not in ("INTERNAL", "STATIC")
                and (not name.startswith("CMAKE_") or name in _PRESERVED_OPTIONS)]
    command += ["-G", "Ninja", f"-DCMAKE_MAKE_PROGRAM={ninja}",
                f"-DCMAKE_C_COMPILER={environment['CC']}", f"-DCMAKE_CXX_COMPILER={environment['CXX']}"]
    if "CMAKE_BUILD_TYPE" not in cached:
        command.append("-DCMAKE_BUILD_TYPE=Debug")
    return directory, command, environment


def instrumented_clang_configuration(
        root: Path, options: instrumentation.InstrumentationOptions,
) -> tuple[Path, list[str], dict[str, str], instrumentation.InstrumentationFiles]:
    """Configure the opt-in instrumented Debug tree without changing the ordinary build tree."""
    files = instrumentation.prepare_instrumentation(root, options)
    previous = build_directory(root)
    cached = cache_values(previous) if previous else {}
    environment = _instrumented_build_environment(cached.get("CMAKE_CXX_COMPILER", ("", ""))[1])
    compiler = Path(environment["CXX"]).resolve()
    cmake_exe = shutil.which("cmake", path=environment.get("PATH"))
    if cmake_exe is None:
        raise RuntimeError("CMake is required to build this project.")

    directory = files.build_directory
    values = cache_values(directory)
    if values:
        configured = values.get("CMAKE_CXX_COMPILER", ("", ""))[1]
        source = values.get("CMAKE_HOME_DIRECTORY", ("", ""))[1]
        generator = values.get("CMAKE_GENERATOR", ("", ""))[1]
        if (not configured or Path(configured).resolve() != compiler or not source
                or Path(source).resolve() != root.resolve() or "Ninja" not in generator):
            raise RuntimeError(f"ICODA's generated instrumented build at {directory} is stale. "
                               "Remove that cache directory and retry.")
        command = configure_command(root, directory)
        command[0] = cmake_exe
    else:
        ninja = shutil.which("ninja", path=environment.get("PATH"))
        if ninja is None:
            raise RuntimeError("Ninja is required to create the instrumented build.")
        command = configure_command(root, directory)
        command[0] = cmake_exe
        if previous is None and (root / "CMakePresets.json").is_file():
            presets = subprocess.run([cmake_exe, "--list-presets"], cwd=root, env=environment,
                                     capture_output=True, text=True, timeout=30, check=False)
            preset = next((name for name in ("debug-clang", "debug") if f'"{name}"' in presets.stdout), None)
            if presets.returncode == 0 and preset:
                command[1:1] = ["--preset", preset]
        command += [f"-D{name}:{kind}={value}" for name, (kind, value) in cached.items()
                    if kind not in ("INTERNAL", "STATIC") and name != "CMAKE_BUILD_TYPE"
                    and (not name.startswith("CMAKE_") or name in _PRESERVED_OPTIONS)]
        command += ["-G", "Ninja", f"-DCMAKE_MAKE_PROGRAM={ninja}",
                    f"-DCMAKE_C_COMPILER={environment['CC']}",
                    f"-DCMAKE_CXX_COMPILER={environment['CXX']}"]
    command += ["-DCMAKE_BUILD_TYPE=Debug", *files.cmake_arguments]
    return directory, command, environment, files


def _instrumented_build_environment(preferred: str | None) -> dict[str, str]:
    """Select Clang when directly available, otherwise GCC for function instrumentation."""
    clang_error: RuntimeError | None = None
    if preferred and "clang" in Path(preferred).name.lower():
        try:
            return toolchain.clang_build_environment(preferred)
        except RuntimeError as exc:
            clang_error = exc
    clang = shutil.which("clang++")
    if clang is not None:
        try:
            return toolchain.clang_build_environment(clang)
        except RuntimeError as exc:
            clang_error = exc

    environment = dict(os.environ)
    gnu_preferred = preferred if preferred and "clang" not in Path(preferred).name.lower() else None
    compiler = None
    for choice in (gnu_preferred, environment.get("CXX"), "g++"):
        if choice and "clang" not in Path(choice).name.lower():
            compiler = shutil.which(choice, path=environment.get("PATH"))
            if compiler is not None:
                break
    if compiler is None:
        # Retain the regular selector's versioned-Clang discovery and actionable error.
        if clang_error is not None:
            raise clang_error
        return toolchain.clang_build_environment(preferred)
    compiler_path = Path(compiler)
    c_name = compiler_path.name.replace("g++", "gcc")
    c_compiler = None
    for choice in (environment.get("CC"), str(compiler_path.with_name(c_name)), "gcc", "cc"):
        if choice:
            c_compiler = shutil.which(choice, path=environment.get("PATH"))
            if c_compiler is not None:
                break
    c_compiler = c_compiler or compiler
    environment.update(CC=c_compiler, CXX=compiler)
    environment["PATH"] = str(compiler_path.parent) + os.pathsep + environment.get("PATH", "")
    return environment


def verify_compiler(directory: Path, expected: str) -> None:
    """Catch toolchain files that override the requested compiler."""
    compiler = cache_values(directory).get("CMAKE_CXX_COMPILER", ("", ""))[1]
    if not compiler or Path(compiler).resolve() != Path(expected).resolve():
        raise RuntimeError("The project's CMake toolchain overrode the requested compiler. "
                           "Update its compiler settings and retry Build.")


def verify_clang(directory: Path) -> None:
    """Catch toolchain files that override the requested compiler instead of silently building with it."""
    compiler = cache_values(directory).get("CMAKE_CXX_COMPILER", ("", ""))[1]
    if not compiler or "clang" not in Path(compiler).resolve().name.lower():
        raise RuntimeError("The project's CMake toolchain overrode Clang. Update its compiler settings and retry Build.")
