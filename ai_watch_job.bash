#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi
source ./ai_loop_python.bash

python_bin="$(choose_ai_loop_python)"
ensure_ai_loop_python_redis "$python_bin"

db_path="${AI_LOOP_DB:-./ai_loop.sqlite3}"
interval="${AI_LOOP_WATCH_INTERVAL:-10}"
limit="${AI_LOOP_WATCH_LOG_LIMIT:-20}"

if [ ! -f "$db_path" ]; then
  echo "job database not found: $db_path" >&2
  exit 1
fi

if [ "$#" -gt 0 ]; then
  echo "usage: $0" >&2
  echo "this watcher picks the newest active job automatically" >&2
  exit 2
fi

pick_active_job() {
  job_id="$("$python_bin" - "$db_path" <<'PY'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
row = conn.execute(
    """
    SELECT id
    FROM jobs
    WHERE status IN ('implementing', 'fixing', 'queued', 'planning', 'waiting_tokens')
    ORDER BY updated_at DESC
    LIMIT 1
    """
).fetchone()
if row is not None:
    print(row[0])
PY
)"
}

while true; do
  pick_active_job
  clear 2>/dev/null || true
  date '+%Y-%m-%d %H:%M:%S'
  echo
  echo "interval: ${interval}s"
  echo "log limit: $limit"
  if [ "$job_id" = "" ]; then
    echo
    echo "no active job found"
    echo
    ./ai_check_job.bash || true
  else
    echo "watching job: $job_id"
    echo
    ./ai_check_job.bash "$job_id"
    echo
    ./ai_print_log.bash --job "$job_id" --limit "$limit" --no-process-logs
  fi
  sleep "$interval"
done
