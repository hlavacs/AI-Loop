#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi
source ./ai_loop_python.bash

python_bin="$(choose_ai_loop_python)"
ensure_ai_loop_python_redis "$python_bin"

if [ "$#" -lt 1 ]; then
  db_path="${AI_LOOP_DB:-./ai_loop.sqlite3}"
  if [ ! -f "$db_path" ]; then
    echo "job database not found: $db_path" >&2
    exit 1
  fi

  job_id="$("$python_bin" - "$db_path" <<'PY'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
row = conn.execute(
    """
    SELECT id
    FROM jobs
    WHERE status = 'human_needed'
    ORDER BY updated_at DESC
    LIMIT 1
    """
).fetchone()
if row is not None:
    print(row[0])
PY
)"

  if [ "$job_id" = "" ]; then
    job_id="$("$python_bin" - "$db_path" <<'PY'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
row = conn.execute(
    """
    SELECT id
    FROM jobs
    WHERE status = 'planning'
    ORDER BY updated_at DESC
    LIMIT 1
    """
).fetchone()
if row is not None:
    print(row[0])
PY
)"
  fi

  if [ "$job_id" = "" ]; then
    "$python_bin" - "$db_path" <<'PY'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
rows = conn.execute(
    """
    SELECT id, status, updated_at, goal
    FROM jobs
    ORDER BY updated_at DESC
    """
).fetchall()

active = [row for row in rows if row[1] in {"queued", "implementing"}]
if active:
    print("no paused job needs resuming; active jobs are already queued or implementing")
    for job_id, status, updated_at, goal in active:
        print(f"  - {job_id}: {status} updated_at={updated_at}")
        print(f"    goal: {goal}")
else:
    print("no human_needed or planning job found; pass a job id explicitly")
PY
    exit 0
  fi

  max_iterations="${AI_LOOP_RESUME_MAX_ITERATIONS:-50000}"
  echo "resuming latest resumable job: $job_id"
  set -- "$job_id" --max-iterations "$max_iterations"
fi

"$python_bin" resume_job.py "$@"
