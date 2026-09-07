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
cmake --preset "$preset"
cmake --build --preset "$preset"
ctest --preset "$preset"
