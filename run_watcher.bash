#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi

python_bin="${AI_LOOP_PYTHON:-python}"

log_dir="${AI_LOOP_LOG_DIR:-./logs}"
mkdir -p "$log_dir"
exec >> "$log_dir/watcher.log" 2>&1

export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
exec "$python_bin" watcher.py
