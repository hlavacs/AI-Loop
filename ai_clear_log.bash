#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

db_path="${AI_LOOP_DB:-./ai_loop.sqlite3}"
log_dir="${AI_LOOP_LOG_DIR:-./logs}"
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

python3 - "$db_path" "$mode" <<'PY'
import sqlite3
import sys

db_path = sys.argv[1]
mode = sys.argv[2]

conn = sqlite3.connect(db_path)
conn.execute("PRAGMA foreign_keys = ON")

tables = ["runs", "decisions", "events"]
counts = {
    table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    for table in tables
}

print(f"database: {db_path}")
for table in tables:
    print(f"{table}: {counts[table]}")

jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
print(f"jobs kept: {jobs}")
print(f"tasks kept: {tasks}")

if mode == "--dry-run":
    print("dry run: no log rows deleted")
    sys.exit(0)

with conn:
    conn.execute("DELETE FROM events")
    conn.execute("DELETE FROM decisions")
    conn.execute("DELETE FROM runs")

conn.execute("VACUUM")
print("log cleared")
PY

if [ -d "$log_dir" ]; then
  echo "process log files: $log_dir"
  while IFS= read -r file; do
    if [ ! -f "$file" ]; then
      continue
    fi
    if [ "$mode" = "--dry-run" ]; then
      bytes="$(wc -c < "$file")"
      echo "$file: $bytes bytes"
    else
      : > "$file"
      echo "cleared $file"
    fi
  done < <(find "$log_dir" -type f -name '*.log' | sort)
elif [ "$mode" = "--dry-run" ]; then
  echo "process log directory not found: $log_dir"
fi
