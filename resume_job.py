from __future__ import annotations

import argparse
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resume an AI loop job with optional corrections.")
    parser.add_argument("job_id", help="Job id to resume.")
    parser.add_argument("--goal", help="Replacement goal for the resumed job.")
    parser.add_argument("--constraint", action="append", default=[], help="Additional constraint for future tasks.")
    parser.add_argument("--acceptance", action="append", default=[], help="Additional acceptance criterion.")
    parser.add_argument("--test-cmd", help="Replacement test command for future tasks.")
    parser.add_argument("--max-iterations", type=int, help="Replacement maximum Codex iteration count.")
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
    from start_job import wait_for_job

    settings = load_settings()
    db.init_db(settings.db_path)

    try:
        with db.transaction(settings.db_path) as conn:
            job = db.get_job(conn, args.job_id)
            goal = args.goal if args.goal is not None else job["goal"]
            test_cmd = args.test_cmd if args.test_cmd is not None else job["test_cmd"]
            max_iterations = args.max_iterations if args.max_iterations is not None else int(job["max_iterations"])
            constraints = [*job["constraints"], *args.constraint]
            acceptance = [*job["acceptance"], *args.acceptance]
            conn.execute(
                """
                UPDATE jobs
                SET goal = ?, constraints_json = ?, acceptance_json = ?,
                    test_cmd = ?, max_iterations = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    goal,
                    db.to_json(constraints),
                    db.to_json(acceptance),
                    test_cmd,
                    max_iterations,
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
                    "added_constraints": args.constraint,
                    "added_acceptance": args.acceptance,
                    "previous_status": job["status"],
                },
            )

        client = redis_client(settings.redis_url)
        xadd_json(client, CLAUDE_REQUEST_STREAM, "request", {"type": "PLAN", "job_id": args.job_id})
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
    print(f"status: planning - Claude is choosing the next implementation task.")
    print(f"goal: {goal}")
    print(f"test_cmd: {test_cmd}")
    print(f"max_iterations: {max_iterations}")
    print(f"queued PLAN on {CLAUDE_REQUEST_STREAM}")
    if args.wait:
        return wait_for_job(settings.db_path, args.job_id, job["worktree_path"], args.timeout, args.poll_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
