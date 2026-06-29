#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <job-id>" >&2
  exit 2
fi

job_id="$1"

cd "$(dirname "${BASH_SOURCE[0]}")"
source ./ai_loop_python.bash
db_path="${AI_LOOP_DB:-$(pwd)/ai_loop.sqlite3}"

python_bin="$(choose_ai_loop_python)"
ensure_ai_loop_python_redis "$python_bin"

if [ ! -f "$db_path" ]; then
  echo "job database not found: $db_path" >&2
  exit 1
fi

"$python_bin" - "$db_path" "$job_id" <<'PY'
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
