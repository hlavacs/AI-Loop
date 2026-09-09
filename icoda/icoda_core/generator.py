"""Skeleton and code generation for new projects.

Step 0 of every ICODA project is the same: a module-based CMake project that builds, runs and tests
before the first architecture step. The build scripts carry the toolchain logic proven on the sample
project (Homebrew LLVM on macOS, a cache from another checkout discarded).
"""

from __future__ import annotations

import re
from pathlib import Path

CXX_STANDARD = "23"


def project_identifier(name: str) -> str:
    """A CMake/C++-safe identifier from a project name."""
    identifier = re.sub(r"[^A-Za-z0-9_]+", "_", name.strip()).strip("_") or "project"
    return identifier if not identifier[0].isdigit() else f"p_{identifier}"


def skeleton_files(name: str) -> dict[str, str]:
    """Relative path -> content of the step 0 skeleton for a project called ``name``."""
    ident = project_identifier(name)
    return {
        "CMakeLists.txt": _cmake_lists(ident),
        "CMakePresets.json": PRESETS,
        "build.sh": BUILD_SH,
        "build.cmd": BUILD_CMD,
        "vcpkg.json": _vcpkg_manifest(ident),
        "Doxyfile": _doxyfile(ident),
        ".gitignore": GITIGNORE,
        "README.md": _readme(name, ident),
        "src/main.cpp": MAIN_CPP,
        "src/app/app.cppm": APP_MODULE,
        "tests/smoke_test.cpp": SMOKE_TEST,
    }


def write_skeleton(root: Path, name: str) -> list[str]:
    """Write the skeleton under ``root`` (created if needed); existing files are left alone."""
    written = []
    for relative, content in skeleton_files(name).items():
        target = root / relative
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if relative.endswith(".sh"):
            target.chmod(0o755)
        written.append(relative)
    return written


def module_unit(module: str, brief: str, body: str = "") -> str:
    """A module interface unit with the standard library in the global module fragment."""
    return (f"module;\n#include <string>\n#include <vector>\nexport module {module};\n\n"
            f"/// @brief {brief}\n{body}")


def _cmake_lists(ident: str) -> str:
    return f"""cmake_minimum_required(VERSION 3.28)
if(DEFINED ENV{{VCPKG_ROOT}} AND NOT CMAKE_TOOLCHAIN_FILE AND EXISTS "$ENV{{VCPKG_ROOT}}/scripts/buildsystems/vcpkg.cmake")
  set(CMAKE_TOOLCHAIN_FILE "$ENV{{VCPKG_ROOT}}/scripts/buildsystems/vcpkg.cmake" CACHE STRING "vcpkg toolchain")
endif()
project({ident} VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD {CXX_STANDARD})
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_CXX_SCAN_FOR_MODULES ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${{CMAKE_SOURCE_DIR}}/bin/${{CMAKE_BUILD_TYPE}}")
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${{CMAKE_SOURCE_DIR}}/bin/${{CMAKE_BUILD_TYPE}}")

# One C++20 module per concept; the library holds everything except main().
add_library({ident}_lib STATIC)
target_sources({ident}_lib PUBLIC FILE_SET CXX_MODULES FILES
    src/app/app.cppm
)

add_executable({ident} src/main.cpp)
target_link_libraries({ident} PRIVATE {ident}_lib)

enable_testing()
add_executable(smoke_test tests/smoke_test.cpp)
target_link_libraries(smoke_test PRIVATE {ident}_lib)
add_test(NAME smoke COMMAND smoke_test)
"""


PRESETS = """{
  "version": 6,
  "cmakeMinimumRequired": { "major": 3, "minor": 28, "patch": 0 },
  "configurePresets": [
    {
      "name": "base",
      "hidden": true,
      "generator": "Ninja",
      "binaryDir": "${sourceDir}/build/${presetName}",
      "cacheVariables": { "CMAKE_EXPORT_COMPILE_COMMANDS": "ON" }
    },
    { "name": "debug", "inherits": "base", "cacheVariables": { "CMAKE_BUILD_TYPE": "Debug" } },
    { "name": "release", "inherits": "base", "cacheVariables": { "CMAKE_BUILD_TYPE": "Release" } }
  ],
  "buildPresets": [
    { "name": "debug", "configurePreset": "debug" },
    { "name": "release", "configurePreset": "release" }
  ],
  "testPresets": [
    { "name": "debug", "configurePreset": "debug", "output": { "outputOnFailure": true } },
    { "name": "release", "configurePreset": "release", "output": { "outputOnFailure": true } }
  ]
}
"""

BUILD_SH = """#!/usr/bin/env bash
# Configure/build and normally test one preset. Usage: ./build.sh [debug|release] [build-only]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
preset="${1:-debug}"
mode="${2:-all}"
# A cache created from another checkout (or another machine) makes CMake refuse to configure; start fresh then.
cache="build/$preset/CMakeCache.txt"
if [ -f "$cache" ] && ! grep -qx "CMAKE_HOME_DIRECTORY:INTERNAL=$PWD" "$cache"; then
  echo "build.sh: build/$preset was configured for another source directory; removing it" >&2
  rm -rf "build/$preset"
fi
extra=()
if [ "$(uname -s)" = "Darwin" ] && [ -z "${CXX:-}" ]; then
  # CMake cannot build C++20 modules with Apple's clang (its AppleClang configuration has no module scanning),
  # so use Homebrew's LLVM when it is installed.
  llvm_prefix="$(brew --prefix llvm 2>/dev/null || true)"
  if [ -x "$llvm_prefix/bin/clang++" ]; then
    export CC="$llvm_prefix/bin/clang" CXX="$llvm_prefix/bin/clang++"
    echo "build.sh: using Homebrew LLVM at $llvm_prefix" >&2
  else
    echo "build.sh: Apple's clang cannot build C++20 modules with CMake; install LLVM with 'brew install llvm'" >&2
  fi
fi
cmake --preset "$preset" ${extra[@]+"${extra[@]}"}
cmake --build --preset "$preset"
if [ "$mode" != "build-only" ]; then
  ctest --preset "$preset"
fi
"""

BUILD_CMD = """@echo off
rem Configure/build and normally test one preset. Usage: build.cmd [debug|release] [build-only]
setlocal
cd /d "%~dp0"
set "PRESET=%~1"
if "%PRESET%"=="" set "PRESET=debug"
set "MODE=%~2"
if exist "build\\%PRESET%\\CMakeCache.txt" (
    findstr /x /c:"CMAKE_HOME_DIRECTORY:INTERNAL=%CD:\\=/%" "build\\%PRESET%\\CMakeCache.txt" >nul || (
        echo build.cmd: build\\%PRESET% was configured for another source directory; removing it 1>&2
        rmdir /s /q "build\\%PRESET%"
    )
)
if "%CXX%"=="" (
    where clang-cl >nul 2>nul && set "CC=clang-cl" && set "CXX=clang-cl"
)
cmake --preset %PRESET% || exit /b 1
cmake --build --preset %PRESET% || exit /b 1
if /i "%MODE%"=="build-only" exit /b 0
ctest --preset %PRESET% || exit /b 1
"""

GITIGNORE = """build/
bin/
vcpkg_installed/
.icoda/cache/
.icoda/ui.json
.icoda/icoda.log
docs/html/
.DS_Store
.vscode/
.idea/
"""

MAIN_CPP = """/// @file main.cpp
/// @brief Entry point: hands over to the application module.
import app;

/// @brief Program entry.
int main() {
    return app::run();
}
"""

APP_MODULE = """module;
#include <string>
export module app;

/// @brief The application; grows one architecture step at a time.
export namespace app {

/// @brief Runs the application; empty until the first step fills it in.
int run() {
    return 0;
}

}  // namespace app
"""

SMOKE_TEST = """/// @brief Smoke test: the application runs and returns success.
import app;

int main() {
    return app::run() == 0 ? 0 : 1;
}
"""


def _vcpkg_manifest(ident: str) -> str:
    return f'{{\n  "name": "{ident.lower().replace("_", "-")}",\n  "version-string": "0.1.0",\n  "dependencies": []\n}}\n'


def _doxyfile(ident: str) -> str:
    return f"""PROJECT_NAME           = "{ident}"
INPUT                  = src
RECURSIVE              = YES
FILE_PATTERNS          = *.cpp *.cppm *.h *.hpp
EXTENSION_MAPPING      = cppm=C++
OUTPUT_DIRECTORY       = docs
GENERATE_LATEX         = NO
EXTRACT_ALL            = YES
QUIET                  = YES
ALIASES                = "satisfies=\\\\par Satisfies:^^"
"""


def _readme(name: str, ident: str) -> str:
    return f"""# {name}

Generated by ICODA as the step 0 skeleton: a C++{CXX_STANDARD} project built from C++20 modules with CMake presets.

Build and test with `./build.sh` (macOS, Linux) or `build.cmd` (Windows); binaries land in `bin/<config>/`,
build artefacts in `build/<preset>/`. Libraries are declared in `vcpkg.json`; set `VCPKG_ROOT` to use them.
The target `{ident}` is the program, `{ident}_lib` holds every module, `smoke_test` runs through CTest.
"""
