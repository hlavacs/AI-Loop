"""Reuse a project's configured CMake tree and request metadata needed for analysis."""

from pathlib import Path

from icoda_core import analysis


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
