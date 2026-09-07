#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

db_path="${AI_LOOP_DB:-./ai_loop.sqlite3}"
mode="${1:-}"

usage() {
  echo "usage: $0 --yes" >&2
  echo "       $0 --dry-run" >&2
  echo "       AI_LOOP_DB=/path/to/ai_loop.sqlite3 $0 --yes" >&2
}

if [ "$mode" != "--yes" ] && [ "$mode" != "--dry-run" ]; then
  usage
  exit 2
fi

if [ ! -f "$db_path" ]; then
  echo "job database not found: $db_path" >&2
  exit 1
fi

active_job_ids() {
  python3 - "$db_path" <<'PY'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
rows = conn.execute(
    """
    SELECT id
    FROM jobs
    WHERE status IN ('implementing', 'fixing', 'queued', 'planning', 'waiting_tokens')
    ORDER BY updated_at DESC
    """
).fetchall()
for row in rows:
    print(row[0])
PY
}

echo "database: $db_path"
echo "active jobs:"
active_jobs="$(active_job_ids)"
if [ -z "$active_jobs" ]; then
  echo "  none"
else
  printf '%s\n' "$active_jobs" | sed 's/^/  /'
fi

if [ "$mode" = "--dry-run" ]; then
  echo
  echo "dry run: would stop controller, worker, and watcher"
  echo "dry run: would delete active job records"
  echo "dry run: would clear the database"
  exit 0
fi

echo
echo "stopping controller, worker, and watcher"
./ai_loopctl.bash stop

if [ -n "$active_jobs" ]; then
  echo
  echo "deleting active job records"
  while IFS= read -r job_id; do
    [ -n "$job_id" ] || continue
    ./ai_delete_job.bash "$job_id"
  done <<< "$active_jobs"
fi

echo
echo "clearing database"
./ai_clear_db.bash --yes

echo
echo "reset complete; new jobs start their own controller, worker, and watcher"
./ai_loopctl.bash status
