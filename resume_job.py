from __future__ import annotations

import argparse
import os
import signal
import sys
import time


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        # The process exists but belongs to someone else; treat it as alive.
        return True
    except OSError:
        return False
    return True


def terminate_previous_job_processes(root_dir, job_id: str) -> None:
    """Kill the job's previous controller/worker/watcher trio before relaunch.

    Without this, resuming leaves the old trio running: two consumers per
    stream fight over messages and the old processes keep mutating job state.
    Every per-PID step is exception-guarded so a stale or garbage PID file can
    never abort the resume.
    """
    runtime_dir = root_dir / "run" / "jobs" / job_id
    terminated: list[tuple[str, int]] = []
    for name in ("controller", "worker", "watcher"):
        pid_file = runtime_dir / f"{name}.pid"
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        try:
            if not _pid_alive(pid):
                continue
            os.kill(pid, signal.SIGTERM)
            terminated.append((name, pid))
        except (ProcessLookupError, PermissionError, ValueError, OSError):
            continue
    if not terminated:
        return
    deadline = time.monotonic() + 5.0
    survivors = list(terminated)
    while survivors and time.monotonic() < deadline:
        time.sleep(0.2)
        survivors = [(name, pid) for name, pid in survivors if _pid_alive(pid)]
    # SIGKILL does not exist on Windows; fall back to a second SIGTERM there.
    force_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
    for name, pid in survivors:
        try:
            os.kill(pid, force_signal)
        except (ProcessLookupError, PermissionError, ValueError, OSError):
            pass
    forced = {pid for _name, pid in survivors}
    for name, pid in terminated:
        how = "SIGKILL" if pid in forced else "SIGTERM"
        print(f"terminated previous {name} process (pid {pid}) with {how}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resume an AI loop job with optional corrections.")
    parser.add_argument("job_id", help="Job id to resume.")
    parser.add_argument("--goal", help="Replacement goal for the resumed job.")
    parser.add_argument("--constraint", action="append", default=[], help="Additional constraint for future tasks.")
    parser.add_argument("--acceptance", action="append", default=[], help="Additional acceptance criterion.")
    parser.add_argument("--test-cmd", help="Replacement test command for future tasks.")
    parser.add_argument("--max-iterations", type=int, help="Replacement maximum Codex iteration count.")
    parser.add_argument("--granularity", choices=("fine", "normal", "coarse"), help="Replacement task granularity.")
    parser.add_argument("--wait", action="store_true", help="Wait for the job to reach a terminal status.")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Seconds between status checks with --wait.")
    parser.add_argument("--timeout", type=int, default=0, help="Maximum seconds to wait with --wait; 0 waits forever.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    from redis.exceptions import ConnectionError, TimeoutError

    from ai_loop import db
    from ai_loop.config import CLAUDE_REQUEST_STREAM, load_settings
    from ai_loop.queues import redis_client, xadd_json
    from ai_loop.planning import normalize_granularity, replace_granularity_constraints
    from start_job import launch_job_processes, prepare_job_consumer_groups, wait_for_job

    settings = load_settings()
    db.init_db(settings.db_path)

    try:
        with db.transaction(settings.db_path) as conn:
            job = db.get_job(conn, args.job_id)
            goal = args.goal if args.goal is not None else job["goal"]
            test_cmd = args.test_cmd if args.test_cmd is not None else job["test_cmd"]
            max_iterations = args.max_iterations if args.max_iterations is not None else int(job["max_iterations"])
            granularity = normalize_granularity(args.granularity or str(job["granularity"]))
            constraints = [*job["constraints"], *args.constraint]
            constraints = replace_granularity_constraints(constraints, granularity)
            acceptance = [*job["acceptance"], *args.acceptance]
            conn.execute(
                """
                UPDATE jobs
                SET goal = ?, constraints_json = ?, acceptance_json = ?,
                    test_cmd = ?, max_iterations = ?, granularity = ?, status = ?, waiting_until = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    goal,
                    db.to_json(constraints),
                    db.to_json(acceptance),
                    test_cmd,
                    max_iterations,
                    granularity,
                    "planning",
                    db.utc_now(),
                    args.job_id,
                ),
            )
            db.add_event(
                conn,
                job_id=args.job_id,
                kind="job_resumed",
                payload={
                    "job_id": args.job_id,
                    "goal": goal,
                    "test_cmd": test_cmd,
                    "max_iterations": max_iterations,
                    "granularity": granularity,
                    "added_constraints": args.constraint,
                    "added_acceptance": args.acceptance,
                    "previous_status": job["status"],
                },
            )

        client = redis_client(settings.redis_url)
        prepare_job_consumer_groups(client, args.job_id)
        terminate_previous_job_processes(settings.root_dir, args.job_id)
        job_processes = launch_job_processes(settings.root_dir, args.job_id)
        with db.transaction(settings.db_path) as conn:
            db.add_event(
                conn,
                job_id=args.job_id,
                kind="job_processes_started",
                payload={
                    "job_id": args.job_id,
                    "resumed": True,
                    "pids": job_processes,
                    "runtime_dir": str(settings.root_dir / "run" / "jobs" / args.job_id),
                    "log_dir": str(settings.root_dir / "logs" / "jobs" / args.job_id),
                },
            )
        xadd_json(client, CLAUDE_REQUEST_STREAM, "request", {"type": "PLAN", "job_id": args.job_id, "scope": "job"})
    except KeyError:
        print(f"job {args.job_id} is not in the system", file=sys.stderr)
        return 1
    except (ConnectionError, TimeoutError) as exc:
        print(f"job {args.job_id} updated, but Redis activation failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"could not resume job {args.job_id}: {exc}", file=sys.stderr)
        return 1

    print(f"resumed job {args.job_id}")
    print("status: planning - the controller is choosing the next implementation task.")
    print(f"goal: {goal}")
    print(f"test_cmd: {test_cmd}")
    print(f"max_iterations: {max_iterations}")
    print(f"granularity: {granularity}")
    print(f"processes: {job_processes}")
    print(f"queued PLAN on {CLAUDE_REQUEST_STREAM}")
    if args.wait:
        return wait_for_job(settings.db_path, args.job_id, job["worktree_path"], args.timeout, args.poll_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
