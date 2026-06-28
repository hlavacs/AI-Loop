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
  echo "'$1' is for ./ai_clear_db.bash, not ./ai_check_job.bash" >&2
  echo "to clear the database, run: ./ai_clear_db.bash $1" >&2
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
from datetime import datetime, timezone

db_path = sys.argv[1]
job_id = sys.argv[2]

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

def describe_status(status, index=0):
    descriptions = {
        "planning": [
            "Claude is choosing the next implementation task.",
            "Planner is reading the job history and constraints.",
            "Planning pass is deciding what Codex should change next.",
        ],
        "implementing": [
            "Codex is applying the current task in the worktree.",
            "Implementation worker is editing and validating the task.",
            "Worker is turning the plan into a concrete code change.",
        ],
        "fixing": [
            "Codex is fixing a reviewed problem in the worktree.",
            "Repair task is applying a focused correction.",
            "Worker is resolving the current blocker one step at a time.",
        ],
        "queued": [
            "The next Codex task is waiting for the worker.",
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
        "dead": [
            "The loop stopped after an unrecoverable error.",
            "Worker/controller flow reached a failed terminal state.",
            "The job cannot continue without repair.",
        ],
    }
    variants = descriptions.get(status, ["The loop is moving through this job state."])
    return variants[index % len(variants)]

def parse_time(value):
    if not value:
        return None
    return datetime.fromisoformat(value)

def age_text(value):
    parsed = parse_time(value)
    if parsed is None:
        return "unknown age"
    seconds = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
    if seconds < 90:
        return f"{seconds}s old"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m old"
    return f"{minutes // 60}h {minutes % 60}m old"

def latest_task(job_id):
    return conn.execute(
        """
        SELECT id, status, iteration, updated_at, goal
        FROM tasks
        WHERE job_id = ?
        ORDER BY iteration DESC, created_at DESC
        LIMIT 1
        """,
        (job_id,),
    ).fetchone()

def print_task_diagnosis(job_id, job_status):
    task = latest_task(job_id)
    if task is None:
        if job_status == "planning":
            print("diagnosis: no task exists yet; controller is still planning or has not queued work")
        else:
            print("diagnosis: no task exists yet")
        return

    print(f"latest_task: {task['id']}")
    print(f"task_status: {task['status']} - {age_text(task['updated_at'])}")
    print(f"task_iteration: {task['iteration']}")
    print(f"task_goal: {task['goal']}")
    if job_status == "queued" and task["status"] == "queued":
        print("diagnosis: task is queued; worker has not picked it up yet")
    elif job_status == "implementing" and task["status"] == "running":
        print("diagnosis: worker picked up the task and is running Codex or tests")
    elif job_status == "fixing" and task["status"] == "running":
        print("diagnosis: worker picked up a repair task and is running Codex or tests")
    elif job_status == "queued" and task["status"] == "running":
        print("diagnosis: task says running but job says queued; status is inconsistent")
    elif job_status == "implementing" and task["status"] == "queued":
        print("diagnosis: job says implementing but latest task is still queued; status is inconsistent")

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
    print(f"status: {job['status']} - {describe_status(job['status'])}")
    print(f"updated_at: {job['updated_at']}")
    print(f"tasks: {job['task_count']}")
    print(f"runs: {job['run_count']}")
    print(f"worktree: {job['worktree_path']}")
    print(f"goal: {job['goal']}")
    print_task_diagnosis(job["id"], job["status"])
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
for index, row in enumerate(rows):
    print(f"job {row['id']}")
    print(f"status: {row['status']} - {describe_status(row['status'], index)}")
    print(f"updated_at: {row['updated_at']}")
    print(f"goal: {row['goal']}")
    print()
PY
