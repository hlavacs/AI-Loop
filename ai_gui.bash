#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
source ./ai_loop_python.bash

python_bin="$(choose_ai_loop_python)"
exec "$python_bin" ai_loop_gui.py "$@"
