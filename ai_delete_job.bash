#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -gt 1 ]; then
  echo "usage: $0 [job-id]" >&2
  exit 2
fi

job_id="${1:-}"

cd "$(dirname "${BASH_SOURCE[0]}")"
source ./ai_loop_python.bash
db_path="${AI_LOOP_DB:-$(pwd)/ai_loop.sqlite3}"
runtime_dir="${AI_LOOP_RUNTIME_DIR:-./run}"

python_bin="$(choose_ai_loop_python)"
ensure_ai_loop_python_redis "$python_bin"

if [ ! -f "$db_path" ]; then
  echo "job database not found: $db_path" >&2
  exit 1
fi

stop_job_processes() {
  local target_job_id="$1"
  local job_dir="$runtime_dir/jobs/$target_job_id"
  local name file pid

  if [ ! -d "$job_dir" ]; then
    return
  fi

  for name in watcher codex_worker claude_controller; do
    file="$job_dir/$name.pid"
    [ -f "$file" ] || continue
    pid="$(cat "$file" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" || true
      echo "stopped job $target_job_id $name pid=$pid"
    fi
    rm -f "$file"
  done
}

resolved_job_id="$("$python_bin" - "$db_path" "$job_id" <<'PY'
import sqlite3
import sys

db_path = sys.argv[1]
job_id = sys.argv[2]
active_statuses = ("implementing", "fixing", "queued", "planning")

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys=ON")

if not job_id:
    placeholders = ", ".join("?" for _ in active_statuses)
    job = conn.execute(
        f"""
        SELECT id, status, worktree_path, goal
        FROM jobs
        WHERE status IN ({placeholders})
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        active_statuses,
    ).fetchone()
    if job is None:
        print("no active job is in the system", file=sys.stderr)
        sys.exit(1)
    job_id = str(job["id"])
else:
    job = conn.execute(
        "SELECT id, status, worktree_path, goal FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()

if job is None:
    print(f"job {job_id} is not in the system", file=sys.stderr)
    sys.exit(1)

print(job_id)
PY
)"

stop_job_processes "$resolved_job_id"

"$python_bin" - "$db_path" "$resolved_job_id" <<'PY'
import sqlite3
import sys

db_path = sys.argv[1]
job_id = sys.argv[2]

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys=ON")

job = conn.execute(
    "SELECT id, status, worktree_path, goal FROM jobs WHERE id = ?",
    (job_id,),
).fetchone()

if job is None:
    print(f"job {job_id} is not in the system", file=sys.stderr)
    sys.exit(1)

conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
conn.commit()

print(f"deleted job record: {job['id']}")
print(f"previous status: {job['status']}")
print(f"worktree path was: {job['worktree_path']}")
print("note: this deletes the database record only; use ./ai_remove_worktrees.bash to remove AI worktree folders")
PY
