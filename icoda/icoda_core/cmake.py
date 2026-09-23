"""Reuse a project's configured CMake tree and request metadata needed for analysis."""

import shutil
import subprocess
from pathlib import Path

from icoda_core import analysis, toolchain


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
    cmake_exe = shutil.which("cmake", path=environment.get("PATH"))
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
    cmake_options = {"CMAKE_BUILD_TYPE", "CMAKE_TOOLCHAIN_FILE", "CMAKE_PREFIX_PATH", "CMAKE_MODULE_PATH",
                     "CMAKE_OSX_ARCHITECTURES", "CMAKE_OSX_SYSROOT", "CMAKE_OSX_DEPLOYMENT_TARGET"}
    command += [f"-D{name}:{kind}={value}" for name, (kind, value) in cached.items()
                if kind not in ("INTERNAL", "STATIC") and (not name.startswith("CMAKE_") or name in cmake_options)]
    command += ["-G", "Ninja", f"-DCMAKE_MAKE_PROGRAM={ninja}",
                f"-DCMAKE_C_COMPILER={environment['CC']}", f"-DCMAKE_CXX_COMPILER={environment['CXX']}"]
    if "CMAKE_BUILD_TYPE" not in cached:
        command.append("-DCMAKE_BUILD_TYPE=Debug")
    return directory, command, environment


def verify_clang(directory: Path) -> None:
    """Catch toolchain files that override the requested compiler instead of silently building with it."""
    compiler = cache_values(directory).get("CMAKE_CXX_COMPILER", ("", ""))[1]
    if not compiler or "clang" not in Path(compiler).resolve().name.lower():
        raise RuntimeError("The project's CMake toolchain overrode Clang. Update its compiler settings and retry Build.")
