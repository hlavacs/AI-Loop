#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

db_path="${AI_LOOP_DB:-./ai_loop.sqlite3}"

usage() {
  echo "usage: $0 [job-id]" >&2
  echo "       AI_LOOP_DB=/path/to/ai_loop.sqlite3 $0 [job-id]" >&2
}

if [ "$#" -gt 1 ]; then
  usage
  exit 2
fi

if [ "${1:-}" = "--yes" ] || [ "${1:-}" = "--dry-run" ]; then
  echo "'$1' is for ./clear_db.bash, not ./check_job.bash" >&2
  echo "to clear the database, run: ./clear_db.bash $1" >&2
  exit 2
fi

if [ "${1:-}" != "" ] && [[ "${1:-}" == -* ]]; then
  usage
  exit 2
fi

if [ ! -f "$db_path" ]; then
  echo "job database not found: $db_path" >&2
  exit 1
fi

job_id="${1:-}"

python3 - "$db_path" "$job_id" <<'PY'
import sqlite3
import sys

db_path = sys.argv[1]
job_id = sys.argv[2]

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

if job_id:
    job = conn.execute(
        """
        SELECT
            j.id,
            j.status,
            j.updated_at,
            j.worktree_path,
            j.goal,
            (
                SELECT COUNT(*)
                FROM tasks t
                WHERE t.job_id = j.id
            ) AS task_count,
            (
                SELECT COUNT(*)
                FROM runs r
                WHERE r.job_id = j.id
            ) AS run_count
        FROM jobs j
        WHERE j.id = ?
        """,
        (job_id,),
    ).fetchone()

    if job is None:
        print(f"job {job_id} is not in the system")
        sys.exit(1)

    print(f"job {job['id']} is in the system")
    print(f"status: {job['status']}")
    print(f"updated_at: {job['updated_at']}")
    print(f"tasks: {job['task_count']}")
    print(f"runs: {job['run_count']}")
    print(f"worktree: {job['worktree_path']}")
    print(f"goal: {job['goal']}")
    sys.exit(0)

rows = conn.execute(
    """
    SELECT id, status, updated_at, goal
    FROM jobs
    ORDER BY updated_at DESC
    """
).fetchall()

if not rows:
    print("no jobs are in the system")
    sys.exit(1)

print("jobs in the system:")
for row in rows:
    print(f"job {row['id']}")
    print(f"status: {row['status']}")
    print(f"updated_at: {row['updated_at']}")
    print(f"goal: {row['goal']}")
    print()
PY
