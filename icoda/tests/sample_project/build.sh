#!/usr/bin/env bash
# Configure, build and test one preset (default: debug). Usage: ./build.sh [debug|release]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
preset="${1:-debug}"
# A cache created from another checkout (or another machine) makes CMake refuse to configure; start fresh then.
cache="build/$preset/CMakeCache.txt"
if [ -f "$cache" ] && ! grep -qx "CMAKE_HOME_DIRECTORY:INTERNAL=$PWD" "$cache"; then
  echo "build.sh: build/$preset was configured for another source directory; removing it" >&2
  rm -rf "build/$preset"
fi
extra=()
if [ "$(uname -s)" = "Darwin" ] && [ -z "${CMAKE_CXX_COMPILER_CLANG_SCAN_DEPS:-}" ]; then
  # Apple's clang keeps clang-scan-deps inside the Xcode toolchain, where CMake does not look for it.
  scan_deps="$(xcrun --find clang-scan-deps 2>/dev/null || true)"
  if [ -z "$scan_deps" ]; then
    # The Command Line Tools ship clang-scan-deps only in some versions; look in the usual places.
    for candidate in /Library/Developer/CommandLineTools/usr/bin/clang-scan-deps \
                     /Applications/Xcode*.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang-scan-deps \
                     "$(brew --prefix llvm 2>/dev/null)/bin/clang-scan-deps"; do
      if [ -x "$candidate" ]; then scan_deps="$candidate"; break; fi
    done
  fi
  if [ -n "$scan_deps" ]; then
    extra+=("-DCMAKE_CXX_COMPILER_CLANG_SCAN_DEPS=$scan_deps")
  else
    echo "build.sh: clang-scan-deps not found; C++20 modules need it. Either install Xcode (full) or" >&2
    echo "build.sh: 'brew install llvm' and run: CC=\$(brew --prefix llvm)/bin/clang CXX=\$(brew --prefix llvm)/bin/clang++ ./build.sh" >&2
  fi
fi
cmake --preset "$preset" ${extra[@]+"${extra[@]}"}
cmake --build --preset "$preset"
ctest --preset "$preset"
