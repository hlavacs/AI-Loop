#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: $0 <repo-path> <job-description>" >&2
  echo "example: $0 /path/to/your/project \"Implement the requested feature in small safe steps.\"" >&2
  exit 2
fi

repo_path="$1"
shift
job_description="$*"

cd "$(dirname "${BASH_SOURCE[0]}")"
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi
source ./ai_loop_python.bash

python_bin="$(choose_ai_loop_python)"
ensure_ai_loop_python_redis "$python_bin"

cmd=(
  "$python_bin" start_job.py
  --repo "$repo_path"
  --goal "$job_description"
  --constraint "Keep changes small and reviewable."
  --constraint "Do not modify unrelated files."
  --acceptance "The requested feature works."
  --acceptance "The test command passes."
  --wait
)

if [ "${AI_LOOP_TEST_CMD:-}" != "" ]; then
  cmd+=(--test-cmd "$AI_LOOP_TEST_CMD")
fi

"${cmd[@]}"
