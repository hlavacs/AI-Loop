#!/usr/bin/env bash
# Configure, build and test one preset (default: debug). Usage: ./build.sh [debug|release]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
preset="${1:-debug}"
cmake --preset "$preset"
cmake --build --preset "$preset"
ctest --preset "$preset"
