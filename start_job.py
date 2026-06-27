from __future__ import annotations

import argparse
import time
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from textwrap import wrap

from redis.exceptions import ConnectionError, TimeoutError

from ai_loop import db
from ai_loop.config import CLAUDE_REQUEST_STREAM, load_settings
from ai_loop.queues import redis_client, xadd_json


DEFAULT_CONSTRAINTS = [
    "Make small incremental changes.",
    "Prefer many tiny, specific tasklets over fewer broad tasks.",
    "Each tasklet should have one concrete objective and a clear stop point.",
    "Do not commit changes.",
    "Do not merge branches.",
    "Keep the repository buildable after each iteration.",
]

DEFAULT_ACCEPTANCE = [
    "The implementation satisfies the stated goal.",
    "The requested test command passes.",
    "No unrelated files are changed.",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a generic AI loop job.")
    parser.add_argument("--repo", required=True, help="Repository path to modify.")
    parser.add_argument("--goal", required=True, help="Overall development goal.")
    parser.add_argument("--test-cmd", default="pytest -q", help="Command run after each Codex task.")
    parser.add_argument("--constraint", action="append", default=[], help="Additional job constraint.")
    parser.add_argument("--acceptance", action="append", default=[], help="Additional acceptance criterion.")
    parser.add_argument("--max-iterations", type=int, default=1000, help="Maximum Codex iterations.")
    parser.add_argument("--base-ref", default="HEAD", help="Git ref used for the isolated worktree.")
    parser.add_argument("--no-worktree", action="store_true", help="Run directly in --repo instead of a Git worktree.")
    parser.add_argument("--wait", action="store_true", help="Wait for the job to reach a terminal status.")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Seconds between status checks with --wait.")
    parser.add_argument("--timeout", type=int, default=7200, help="Maximum seconds to wait with --wait.")
    return parser.parse_args()


def run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def create_worktree(repo: Path, runs_dir: Path, job_id: str, base_ref: str) -> tuple[Path, str]:
    runs_dir.mkdir(parents=True, exist_ok=True)
    worktree = runs_dir / job_id
    branch = f"ai/{job_id}"
    run_git(["worktree", "add", "-b", branch, str(worktree), base_ref], cwd=repo)
    return worktree, branch


def job_status(db_path: Path, job_id: str) -> str:
    with db.transaction(db_path) as conn:
        return str(db.get_job(conn, job_id)["status"])


def job_state(db_path: Path, job_id: str) -> dict[str, str | int | None]:
    with db.transaction(db_path) as conn:
        job = db.get_job(conn, job_id)
        task = db.latest_task(conn, job_id)
    state: dict[str, str | int | None] = {"status": str(job["status"])}
    if task is not None:
        state.update(
            {
                "task_id": str(task["id"]),
                "task_status": str(task["status"]),
                "task_iteration": int(task["iteration"]),
                "task_updated_at": str(task["updated_at"]),
                "task_goal": str(task["goal"]),
            }
        )
    return state


def age_text(value: str | None) -> str:
    if not value:
        return "unknown age"
    seconds = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(value)).total_seconds()))
    if seconds < 90:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m"
    return f"{minutes // 60}h{minutes % 60}m"


def print_status_update(
    job_id: str,
    state: dict[str, str | int | None],
    status_count: int,
    status_note: str,
) -> None:
    print(f"job {job_id} status update")
    print(f"  - status: {state['status']} step {status_count} - {status_note}")

    task_id = state.get("task_id")
    if task_id is None:
        print("  - task: none queued yet")
        return

    print(
        f"  - task: {task_id} iter {state.get('task_iteration')} "
        f"{state.get('task_status')} age {age_text(state.get('task_updated_at'))}"
    )
    goal_lines = wrap(str(state.get("task_goal", "")), width=88)
    if not goal_lines:
        print("  - task_goal:")
        return
    print(f"  - task_goal: {goal_lines[0]}")
    for line in goal_lines[1:]:
        print(f"               {line}")


def describe_status(status: str, index: int) -> str:
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


def print_inspect_commands(job_id: str) -> None:
    print()
    print("Inspect with:")
    print(f"./check_job.bash {job_id}")
    print(f"./print_log.bash --job {job_id} --limit 120")


def wait_for_job(db_path: Path, job_id: str, worktree: Path, timeout: int, poll_interval: float) -> int:
    print(f"waiting for job {job_id}")
    deadline = time.monotonic() + timeout
    status = ""
    status_line = 0
    status_counts: dict[str, int] = {}

    while time.monotonic() < deadline:
        state = job_state(db_path, job_id)
        status = str(state["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        print_status_update(job_id, state, status_counts[status], describe_status(status, status_line))
        status_line += 1
        if status == "done":
            print()
            print("AI loop job done")
            print(f"job: {job_id}")
            print(f"worktree: {worktree}")
            print_inspect_commands(job_id)
            return 0
        if status in {"human_needed", "dead"}:
            print()
            print(f"AI loop job {status}")
            print(f"job: {job_id}")
            print(f"worktree: {worktree}")
            print_inspect_commands(job_id)
            return 1
        time.sleep(poll_interval)

    print(
        f"timed out waiting for job {job_id}; last status: {status} - "
        "the loop may still be running in the background",
        file=sys.stderr,
    )
    print_inspect_commands(job_id)
    return 1


def main() -> int:
    args = parse_args()
    settings = load_settings()

    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists():
        print(f"repo does not exist: {repo}", file=sys.stderr)
        return 2

    db.init_db(settings.db_path)
    job_id = uuid.uuid4().hex[:12]
    constraints = [*DEFAULT_CONSTRAINTS, *args.constraint]
    acceptance = [*DEFAULT_ACCEPTANCE, *args.acceptance]

    use_worktree = not args.no_worktree
    branch: str | None = None
    worktree = repo

    try:
        if use_worktree:
            worktree, branch = create_worktree(repo, settings.runs_dir, job_id, args.base_ref)

        with db.transaction(settings.db_path) as conn:
            db.create_job(
                conn,
                job_id=job_id,
                repo_path=str(repo),
                worktree_path=str(worktree),
                branch=branch,
                base_ref=args.base_ref,
                goal=args.goal,
                constraints=constraints,
                acceptance=acceptance,
                test_cmd=args.test_cmd,
                max_iterations=args.max_iterations,
                use_worktree=use_worktree,
            )
            db.add_event(
                conn,
                job_id=job_id,
                kind="job_created",
                payload={"job_id": job_id, "worktree_path": str(worktree), "goal": args.goal},
            )

        client = redis_client(settings.redis_url)
        xadd_json(
            client,
            CLAUDE_REQUEST_STREAM,
            "request",
            {"type": "PLAN", "job_id": job_id},
        )
    except (ConnectionError, TimeoutError) as exc:
        print(f"job {job_id} created, but Redis activation failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"could not create job: {exc}", file=sys.stderr)
        return 1

    print(f"created job {job_id}")
    print(f"repo: {repo}")
    print(f"worktree: {worktree}")
    print(f"db: {settings.db_path}")
    print(f"queued PLAN on {CLAUDE_REQUEST_STREAM}")
    if args.wait:
        return wait_for_job(settings.db_path, job_id, worktree, args.timeout, args.poll_interval)
    print_inspect_commands(job_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
