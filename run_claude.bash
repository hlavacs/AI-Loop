#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
source .venv/bin/activate

log_dir="${AI_LOOP_LOG_DIR:-./logs}"
mkdir -p "$log_dir"
exec > >(tee -a "$log_dir/claude_controller.log") 2>&1

export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
exec python claude_controller.py
