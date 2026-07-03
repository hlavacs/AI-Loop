#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 [--worker codex|fable|opus] [--controller claude|fable|opus|codex] <repo-path> <job-description>" >&2
  echo "       $0 [--worker codex|fable|opus] [--controller claude|fable|opus|codex] <job-description-file>" >&2
  echo "example: $0 /path/to/your/project \"Implement the requested feature in small safe steps.\"" >&2
  echo "example: $0 --worker fable --controller fable /path/to/your/project/job.txt" >&2
}

worker="${AI_LOOP_WORKER:-}"
controller="${AI_LOOP_CONTROLLER:-}"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --worker)
      if [ "$#" -lt 2 ]; then usage; exit 2; fi
      worker="$2"
      shift 2
      ;;
    --controller)
      if [ "$#" -lt 2 ]; then usage; exit 2; fi
      controller="$2"
      shift 2
      ;;
    *)
      break
      ;;
  esac
done

if [ "$#" -eq 1 ]; then
  job_file="$1"
  if [ ! -f "$job_file" ]; then
    echo "job description file not found: $job_file" >&2
    usage
    exit 2
  fi
  repo_path="$(cd "$(dirname "$job_file")" && pwd -P)"
  job_description="$(<"$job_file")"
  if [ -z "${job_description//[[:space:]]/}" ]; then
    echo "job description file is empty: $job_file" >&2
    exit 2
  fi
elif [ "$#" -ge 2 ]; then
  repo_path="$1"
  shift
  job_description="$*"
else
  usage
  exit 2
fi

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

if [ "$worker" != "" ]; then
  cmd+=(--worker "$worker")
fi

if [ "$controller" != "" ]; then
  cmd+=(--controller "$controller")
fi

if [ "${AI_LOOP_ALLOW_PARALLEL_JOBS:-}" = "1" ]; then
  cmd+=(--allow-parallel)
fi

"${cmd[@]}"
