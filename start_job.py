from __future__ import annotations

import argparse
import subprocess
import sys
import uuid
from pathlib import Path

from redis.exceptions import ConnectionError, TimeoutError

from ai_loop import db
from ai_loop.config import CLAUDE_REQUEST_STREAM, load_settings
from ai_loop.queues import redis_client, xadd_json


DEFAULT_CONSTRAINTS = [
    "Make small incremental changes.",
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
    parser.add_argument("--max-iterations", type=int, default=10, help="Maximum Codex iterations.")
    parser.add_argument("--base-ref", default="HEAD", help="Git ref used for the isolated worktree.")
    parser.add_argument("--no-worktree", action="store_true", help="Run directly in --repo instead of a Git worktree.")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

