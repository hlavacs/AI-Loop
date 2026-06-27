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

if [ "${AI_LOOP_TEST_CMD:-}" = "" ]; then
  test_python_bin="$(resolve_ai_loop_python "$python_bin")"
  quoted_test_python_bin="$(quote_ai_loop_shell_word "$test_python_bin")"
  if [ "${PYTHONPATH:-}" != "" ]; then
    quoted_pythonpath="$(quote_ai_loop_shell_word "$PYTHONPATH")"
    test_cmd="PYTHONPATH=$quoted_pythonpath $quoted_test_python_bin -m pytest -q"
  else
    test_cmd="$quoted_test_python_bin -m pytest -q"
  fi
else
  test_cmd="$AI_LOOP_TEST_CMD"
fi

"$python_bin" start_job.py \
  --repo "$repo_path" \
  --goal "$job_description" \
  --test-cmd "$test_cmd" \
  --constraint "Keep changes small and reviewable." \
  --constraint "Do not modify unrelated files." \
  --acceptance "The requested feature works." \
  --acceptance "The test command passes." \
  --wait
