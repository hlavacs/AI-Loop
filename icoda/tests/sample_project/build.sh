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
ctest --preset "$preset"
