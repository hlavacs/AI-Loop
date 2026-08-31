#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

source ./ai_loop_python.bash

python_bin="$(choose_ai_loop_python 2>/dev/null)" || {
  echo "could not find a runnable Python 3.10 or newer interpreter" >&2
  exit 1
}

exec "$python_bin" "$script_dir/start_ai_loop_with_email.py" "$@"
