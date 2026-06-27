#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi
source ./ai_loop_python.bash

python_bin="$(choose_ai_loop_python)"
ensure_ai_loop_python_redis "$python_bin"

log_dir="${AI_LOOP_LOG_DIR:-./logs}"
mkdir -p "$log_dir"
exec >> "$log_dir/watcher.log" 2>&1

export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
exec "$python_bin" watcher.py
