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

python_bin="${AI_LOOP_PYTHON:-python}"

"$python_bin" start_job.py \
  --repo "$repo_path" \
  --goal "$job_description" \
  --test-cmd "${AI_LOOP_TEST_CMD:-python -m pytest -q}" \
  --constraint "Keep changes small and reviewable." \
  --constraint "Do not modify unrelated files." \
  --acceptance "The requested feature works." \
  --acceptance "The test command passes." \
  --wait
