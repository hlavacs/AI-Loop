#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

db_path="${AI_LOOP_DB:-./ai_loop.sqlite3}"
log_dir="${AI_LOOP_LOG_DIR:-./logs}"

usage() {
  echo "usage: $0 [--job JOB_ID] [--limit N] [--no-process-logs]" >&2
  echo "       AI_LOOP_DB=/path/to/ai_loop.sqlite3 $0 [--job JOB_ID] [--limit N] [--no-process-logs]" >&2
}

job_id=""
limit="100"
process_logs=1

while [ "$#" -gt 0 ]; do
  case "$1" in
    --job)
      if [ "$#" -lt 2 ]; then
        usage
        exit 2
      fi
      job_id="$2"
      shift 2
      ;;
    --limit)
      if [ "$#" -lt 2 ]; then
        usage
        exit 2
      fi
      limit="$2"
      shift 2
      ;;
    --no-process-logs)
      process_logs=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

if [ ! -f "$db_path" ]; then
  echo "job database not found: $db_path" >&2
  exit 1
fi

python3 - "$db_path" "$job_id" "$limit" <<'PY'
import json
import sqlite3
import sys
from textwrap import shorten
from ai_loop.db import init_db
from ai_loop.progress import estimate_progress

db_path = sys.argv[1]
job_id = sys.argv[2] or None

try:
    limit = int(sys.argv[3])
except ValueError:
    print("limit must be an integer", file=sys.stderr)
    sys.exit(2)

if limit < 1:
    print("limit must be greater than zero", file=sys.stderr)
    sys.exit(2)

init_db(db_path)
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

def load_json(value, default):
    if value in (None, ""):
        return default
    return json.loads(value)

def short(value, width=220):
    return shorten(str(value).replace("\n", " "), width=width, placeholder="...")

def describe_status(status, index=0):
    descriptions = {
        "planning": [
            "The controller is choosing the next implementation task.",
            "Planner is reading the job history and constraints.",
            "Planning pass is deciding what the worker should change next.",
        ],
        "implementing": [
            "The worker is applying the current task in the worktree.",
            "Implementation worker is editing and validating the task.",
            "Worker is turning the plan into a concrete code change.",
        ],
        "fixing": [
            "The worker is fixing a reviewed problem in the worktree.",
            "Repair task is applying a focused correction.",
            "Worker is resolving the current blocker one step at a time.",
        ],
        "queued": [
            "The next task is waiting for the worker.",
            "Task is ready and pending worker pickup.",
            "Queue has the next implementation request.",
        ],
        "done": [
            "The job met its acceptance criteria.",
            "Review accepted the latest implementation.",
            "The loop has reached a successful terminal state.",
        ],
        "human_needed": [
            "The loop needs a person to resolve the next step.",
            "Automation paused because manual input is required.",
            "A human decision is needed before continuing.",
        ],
        "waiting_tokens": [
            "The loop is waiting for model tokens to replenish and will resume automatically.",
        ],
        "dead": [
            "The loop stopped after an unrecoverable error.",
            "Worker/controller flow reached a failed terminal state.",
            "The job cannot continue without repair.",
        ],
    }
    variants = descriptions.get(status, ["The loop is moving through this job state."])
    return variants[index % len(variants)]

def duration_text(seconds):
    if seconds is None:
        return "unknown"
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h {minutes % 60}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"

def latest_task(target_job_id):
    return conn.execute(
        """
        SELECT id, status
        FROM tasks
        WHERE job_id = ?
        ORDER BY iteration DESC, created_at DESC
        LIMIT 1
        """,
        (target_job_id,),
    ).fetchone()

def job_progress(job):
    task = latest_task(job["id"])
    result = estimate_progress(
        conn,
        job_id=job["id"],
        status=job["status"],
        created_at=job["created_at"],
        run_count=int(job["run_count"]),
        task_count=int(job["task_count"]),
        has_active_task=task is not None and task["status"] in {"queued", "running", "waiting_tokens"},
    )
    conn.commit()
    return result

where = "WHERE job_id = ?" if job_id else ""
params = (job_id,) if job_id else ()

if job_id:
    job = conn.execute(
        """
        SELECT
            j.id,
            j.status,
            j.created_at,
            j.updated_at,
            j.goal,
            j.estimated_completed_units,
            j.estimated_remaining_units,
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
        print(f"job {job_id} is not in the system", file=sys.stderr)
        sys.exit(1)
    percent, remaining = job_progress(job)
    print(f"database: {db_path}")
    print(f"job: {job['id']}")
    print(f"status: {job['status']} - {describe_status(job['status'])}")
    print(f"updated_at: {job['updated_at']}")
    print(f"estimate: {percent}% done, about {duration_text(remaining)} remaining")
    print(f"work_estimate: {job['estimated_completed_units']} logical units completed, {job['estimated_remaining_units']} remaining")
    print(f"goal: {job['goal']}")
    print()
else:
    print(f"database: {db_path}")
    print()

events = conn.execute(
    f"""
    SELECT created_at AS ts, 'event' AS kind, job_id, NULL AS task_id, NULL AS run_id,
           kind AS action, payload_json AS detail
    FROM events
    {where}

    UNION ALL

    SELECT created_at AS ts, 'decision' AS kind, job_id, task_id, run_id,
           action, reason AS detail
    FROM decisions
    {where}

    UNION ALL

    SELECT finished_at AS ts, 'run' AS kind, job_id, task_id, id AS run_id,
           status AS action,
           'codex_rc=' || COALESCE(codex_rc, 'null') ||
           ' test_rc=' || COALESCE(test_rc, 'null') ||
           ' changed=' || changed_files_json ||
           CASE WHEN error IS NULL THEN '' ELSE ' error=' || error END AS detail
    FROM runs
    {where}

    ORDER BY ts DESC
    LIMIT ?
    """,
    (*params, *params, *params, limit),
).fetchall()

if not events:
    print("no log entries")
    sys.exit(0)

for row in reversed(events):
    parts = [
        row["ts"],
        row["kind"],
        f"job={row['job_id']}" if row["job_id"] else None,
        f"task={row['task_id']}" if row["task_id"] else None,
        f"run={row['run_id']}" if row["run_id"] else None,
        row["action"],
    ]
    print(" | ".join(part for part in parts if part))
    detail = row["detail"]
    if row["kind"] == "event":
        payload = load_json(detail, {})
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"  {short(detail)}")
    print()
PY

if [ "$process_logs" -eq 0 ]; then
  exit 0
fi

if [ "$job_id" != "" ] && [ -d "$log_dir/jobs/$job_id" ]; then
  log_dir="$log_dir/jobs/$job_id"
fi

echo "process log files: $log_dir"
if [ ! -d "$log_dir" ]; then
  echo "no process log directory"
  exit 0
fi

found=0
for file in "$log_dir"/*.log; do
  if [ ! -f "$file" ]; then
    continue
  fi
  found=1
  echo
  echo "==> $file <=="
  tail -n "$limit" "$file"
done

if [ "$found" -eq 0 ]; then
  echo "no process log files"
fi
