from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import time
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from textwrap import wrap

from redis.exceptions import ConnectionError, TimeoutError

from ai_loop import db
from ai_loop.config import (
    CLAUDE_REQUEST_STREAM,
    CODEX_TASK_STREAM,
    load_settings,
    normalize_controller,
    normalize_worker,
)
from ai_loop.progress import estimate_progress
from ai_loop.queues import ensure_group, redis_client, xadd_json


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
ACTIVE_STATUSES = {"planning", "queued", "implementing", "fixing"}
CLAUDE_GROUP = "claude-controllers"
CODEX_GROUP = "codex-workers"


def timestamp_id(prefix: str) -> str:
    return f"{prefix}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a generic AI loop job.")
    parser.add_argument("--repo", required=True, help="Repository path to modify.")
    parser.add_argument("--goal", required=True, help="Overall development goal.")
    parser.add_argument("--test-cmd", default="auto", help="Command run after each Codex task, or 'auto' to infer one.")
    parser.add_argument("--constraint", action="append", default=[], help="Additional job constraint.")
    parser.add_argument("--acceptance", action="append", default=[], help="Additional acceptance criterion.")
    parser.add_argument("--max-iterations", type=int, default=50000, help="Maximum Codex iterations.")
    parser.add_argument("--base-ref", default="HEAD", help="Git ref used for the isolated worktree.")
    parser.add_argument("--no-worktree", action="store_true", help="Run directly in --repo instead of a Git worktree.")
    parser.add_argument(
        "--worker",
        default=os.getenv("AI_LOOP_WORKER", "codex"),
        help="Implementation worker: 'codex', 'fable' (alias 'claude'), or 'opus'. Default from AI_LOOP_WORKER or 'codex'.",
    )
    parser.add_argument(
        "--controller",
        default=os.getenv("AI_LOOP_CONTROLLER", "claude"),
        help="Controller: 'claude' (CLI default model), 'fable', 'opus', or 'codex'. Default from AI_LOOP_CONTROLLER or 'claude'.",
    )
    parser.add_argument("--allow-parallel", action="store_true", help="Allow creating this job while another job is active.")
    parser.add_argument("--wait", action="store_true", help="Wait for the job to reach a terminal status.")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Seconds between status checks with --wait.")
    parser.add_argument("--timeout", type=int, default=0, help="Maximum seconds to wait with --wait; 0 waits forever.")
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


def run_git_raw(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def git_quiet(args: list[str], cwd: Path) -> int:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=120,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.returncode


def create_pre_job_commit(repo: Path, job_id: str) -> dict[str, str | bool | None]:
    before = run_git(["rev-parse", "HEAD"], cwd=repo)
    run_git(["add", "-A"], cwd=repo)
    if git_quiet(["diff", "--cached", "--quiet"], cwd=repo) == 0:
        return {
            "created": False,
            "before": before,
            "after": before,
            "message": None,
        }

    message = f"AI loop snapshot before job {job_id}"
    run_git(["commit", "-m", message], cwd=repo)
    after = run_git(["rev-parse", "HEAD"], cwd=repo)
    return {
        "created": True,
        "before": before,
        "after": after,
        "message": message,
    }


def create_worktree(repo: Path, runs_dir: Path, job_id: str, base_ref: str) -> tuple[Path, str]:
    runs_dir.mkdir(parents=True, exist_ok=True)
    worktree = runs_dir / job_id
    branch = f"ai/{job_id}"
    run_git(["worktree", "add", "-b", branch, str(worktree), base_ref], cwd=repo)
    return worktree, branch


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def load_cmake_preset_data(presets_path: Path, seen: set[Path] | None = None) -> dict:
    seen = seen or set()
    try:
        resolved = presets_path.resolve()
    except OSError:
        resolved = presets_path
    if resolved in seen:
        return {}
    seen.add(resolved)

    try:
        data = json.loads(presets_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    merged: dict = {}
    includes = data.get("include", [])
    if isinstance(includes, str):
        includes = [includes]
    if isinstance(includes, list):
        for include in includes:
            if not isinstance(include, str):
                continue
            child = presets_path.parent / include
            child_data = load_cmake_preset_data(child, seen)
            for key, value in child_data.items():
                if isinstance(value, list):
                    merged.setdefault(key, [])
                    merged[key].extend(value)
                elif key not in merged:
                    merged[key] = value

    for key, value in data.items():
        if isinstance(value, list):
            merged.setdefault(key, [])
            merged[key].extend(value)
        else:
            merged[key] = value

    return merged


def visible_named_presets(data: dict, key: str) -> list[dict]:
    presets = data.get(key)
    if not isinstance(presets, list):
        return []
    return [
        preset
        for preset in presets
        if isinstance(preset, dict)
        and isinstance(preset.get("name"), str)
        and not bool(preset.get("hidden"))
    ]


def preset_score(name: str) -> tuple[int, int, int]:
    lowered = name.lower()
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        platform_score = 0 if "macos" in lowered or "darwin" in lowered or "osx" in lowered else 1
    elif sys.platform.startswith("linux"):
        platform_score = 0 if "linux" in lowered else 1
    elif sys.platform.startswith(("win32", "cygwin", "msys")):
        platform_score = 0 if "windows" in lowered or "win" in lowered else 1
    else:
        platform_score = 1
    arch_score = 0 if machine and machine in lowered else 1
    build_type_score = 0 if "debug" in lowered else 1 if "release" in lowered else 2
    return (platform_score, arch_score, build_type_score, len(name))


def select_cmake_presets(presets_path: Path) -> tuple[str | None, str | None]:
    data = load_cmake_preset_data(presets_path)
    configure_presets = visible_named_presets(data, "configurePresets")
    if not configure_presets:
        return None, None

    configure_name = str(sorted(configure_presets, key=lambda item: preset_score(str(item["name"])))[0]["name"])
    build_name = None
    build_presets = visible_named_presets(data, "buildPresets")
    matching_builds = [
        preset
        for preset in build_presets
        if preset.get("configurePreset") == configure_name
    ]
    if matching_builds:
        build_name = str(sorted(matching_builds, key=lambda item: preset_score(str(item["name"])))[0]["name"])
    elif build_presets:
        build_name = str(sorted(build_presets, key=lambda item: preset_score(str(item["name"])))[0]["name"])
    return configure_name, build_name


def detect_test_cmd(repo: Path, requested: str) -> str:
    if requested != "auto":
        return requested

    presets = repo / "CMakePresets.json"
    if presets.is_file():
        configure, build = select_cmake_presets(presets)
        if configure and build:
            return f"cmake --preset {shell_quote(configure)} && cmake --build --preset {shell_quote(build)}"
        if configure:
            return f"cmake --preset {shell_quote(configure)} && cmake --build --preset {shell_quote(configure)}"

    if (repo / "CMakeLists.txt").is_file():
        return "cmake -S . -B build/ai-loop && cmake --build build/ai-loop"

    if (repo / "package.json").is_file():
        return "npm test"

    if any((repo / name).is_file() for name in ("pyproject.toml", "pytest.ini", "setup.cfg", "setup.py")):
        return "pytest -q"

    return "true"


def allow_parallel_jobs(args: argparse.Namespace) -> bool:
    if os.environ.get("AI_LOOP_SINGLE_ACTIVE_JOB") == "1":
        return bool(args.allow_parallel or os.environ.get("AI_LOOP_ALLOW_PARALLEL_JOBS") == "1")
    return True


def scoped_group(base_group: str, job_id: str) -> str:
    return f"{base_group}:{job_id}"


def prepare_job_consumer_groups(client, job_id: str) -> None:
    ensure_group(client, CLAUDE_REQUEST_STREAM, scoped_group(CLAUDE_GROUP, job_id), start_id="$")
    ensure_group(client, CODEX_TASK_STREAM, scoped_group(CODEX_GROUP, job_id), start_id="$")


def launch_job_processes(root_dir: Path, job_id: str) -> dict[str, int]:
    runtime_dir = root_dir / "run" / "jobs" / job_id
    log_dir = root_dir / "logs" / "jobs" / job_id
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["AI_LOOP_JOB_ID"] = job_id
    env["AI_LOOP_RUNTIME_DIR"] = str(runtime_dir)
    env["AI_LOOP_LOG_DIR"] = str(log_dir)

    processes = {
        "claude_controller": "./ai_run_claude.bash",
        "codex_worker": "./ai_run_codex.bash",
        "watcher": "./ai_run_watcher.bash",
    }
    pids: dict[str, int] = {}
    for name, wrapper in processes.items():
        proc = subprocess.Popen(
            [wrapper],
            cwd=str(root_dir),
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pids[name] = proc.pid
        (runtime_dir / f"{name}.pid").write_text(f"{proc.pid}\n", encoding="utf-8")
    return pids


def active_jobs(db_path: Path) -> list[dict[str, str]]:
    placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
    with db.transaction(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT id, status, updated_at, goal
            FROM jobs
            WHERE status IN ({placeholders})
            ORDER BY updated_at DESC
            """,
            tuple(sorted(ACTIVE_STATUSES)),
        ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "status": str(row["status"]),
            "updated_at": str(row["updated_at"]),
            "goal": str(row["goal"]),
        }
        for row in rows
    ]


def print_active_job_warning(jobs: list[dict[str, str]]) -> None:
    print("warning: an AI loop job is already active; refusing to start another job by default", file=sys.stderr)
    print("active jobs:", file=sys.stderr)
    for job in jobs[:10]:
        goal = job["goal"].replace("\n", " ")
        if len(goal) > 140:
            goal = goal[:137] + "..."
        print(
            f"  - {job['id']}: {job['status']} updated_at={job['updated_at']} goal={goal}",
            file=sys.stderr,
        )
    if len(jobs) > 10:
        print(f"  - ... and {len(jobs) - 10} more", file=sys.stderr)
    print("options:", file=sys.stderr)
    print("  - inspect active jobs: ./ai_check_job.bash", file=sys.stderr)
    print("  - watch the active job: ./ai_watch_job.bash", file=sys.stderr)
    print("  - start anyway once: AI_LOOP_ALLOW_PARALLEL_JOBS=1 ./ai_job.bash <repo-path> \"<job-description>\"", file=sys.stderr)
    print("  - start anyway with Python: python3 start_job.py --allow-parallel --repo <repo-path> --goal \"<job-description>\"", file=sys.stderr)
    print("  - delete an old job record: ./ai_delete_job.bash <job-id>", file=sys.stderr)
    print("  - clear all job records: ./ai_clear_db.bash --yes", file=sys.stderr)


def dirty_paths(repo: Path) -> list[tuple[str, str]]:
    output = run_git_raw(["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=repo)
    entries = output.split("\0")
    paths: list[tuple[str, str]] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        code = entry[:2]
        path = entry[3:]
        if code[0] in {"R", "C"} or code[1] in {"R", "C"}:
            if index < len(entries):
                path = entries[index]
                index += 1
        paths.append((code, path))
    return paths


def copy_checkout_overlay(repo: Path, worktree: Path) -> list[str]:
    copied: list[str] = []
    for code, relative_path in dirty_paths(repo):
        if not relative_path:
            continue
        source = repo / relative_path
        target = worktree / relative_path
        if "D" in code and not source.exists():
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            copied.append(relative_path)
            continue
        if not source.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        copied.append(relative_path)
    return sorted(set(copied))


def job_status(db_path: Path, job_id: str) -> str:
    with db.transaction(db_path) as conn:
        return str(db.get_job(conn, job_id)["status"])


def job_state(db_path: Path, job_id: str) -> dict[str, str | int | None]:
    with db.transaction(db_path) as conn:
        job = db.get_job(conn, job_id)
        task = db.latest_task(conn, job_id)
        task_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE job_id = ?", (job_id,)).fetchone()[0]
        run_count = conn.execute("SELECT COUNT(*) FROM runs WHERE job_id = ?", (job_id,)).fetchone()[0]
        percent, remaining = estimate_progress(
            conn,
            job_id=job_id,
            status=str(job["status"]),
            created_at=str(job["created_at"]),
            run_count=int(run_count),
            task_count=int(task_count),
            has_active_task=task is not None and str(task["status"]) in {"queued", "running"},
        )
    state: dict[str, str | int | None] = {
        "status": str(job["status"]),
        "created_at": str(job["created_at"]),
        "task_count": int(task_count),
        "run_count": int(run_count),
        "percent": percent,
        "remaining": remaining,
    }
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


def duration_text(seconds: int | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = max(0, seconds)
    if seconds < 90:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h{minutes % 60}m"
    days = hours // 24
    return f"{days}d{hours % 24}h"


def print_status_update(
    job_id: str,
    state: dict[str, str | int | None],
    status_count: int,
    status_note: str,
) -> None:
    print(f"job {job_id} status update")
    print(f"  - status: {state['status']} step {status_count} - {status_note}")
    percent = int(state["percent"] or 0)
    remaining = int(state["remaining"]) if state["remaining"] is not None else None
    print(f"  - estimate: {percent}% done, about {duration_text(remaining)} remaining")

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


def print_inspect_commands(job_id: str) -> None:
    print()
    print("Inspect with:")
    print(f"./ai_check_job.bash {job_id}")
    print(f"./ai_print_log.bash --job {job_id} --limit 120")


def wait_for_job(db_path: Path, job_id: str, worktree: Path, timeout: int, poll_interval: float) -> int:
    print(f"waiting for job {job_id}")
    deadline = None if timeout <= 0 else time.monotonic() + timeout
    status = ""
    status_line = 0
    status_counts: dict[str, int] = {}

    while deadline is None or time.monotonic() < deadline:
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
    try:
        worker = normalize_worker(args.worker)
        controller = normalize_controller(args.controller)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    test_cmd = detect_test_cmd(repo, args.test_cmd)

    db.init_db(settings.db_path)
    current_active_jobs = active_jobs(settings.db_path)
    if current_active_jobs and not allow_parallel_jobs(args):
        print_active_job_warning(current_active_jobs)
        return 2

    job_id = timestamp_id("J")
    constraints = [*DEFAULT_CONSTRAINTS, *args.constraint]
    acceptance = [*DEFAULT_ACCEPTANCE, *args.acceptance]

    use_worktree = not args.no_worktree
    branch: str | None = None
    worktree = repo
    overlay_files: list[str] = []
    pre_job_commit: dict[str, str | bool | None] = {}
    job_processes: dict[str, int] = {}

    try:
        pre_job_commit = create_pre_job_commit(repo, job_id)

        if use_worktree:
            worktree, branch = create_worktree(repo, settings.runs_dir, job_id, args.base_ref)
            overlay_files = copy_checkout_overlay(repo, worktree)

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
                test_cmd=test_cmd,
                max_iterations=args.max_iterations,
                use_worktree=use_worktree,
                worker=worker,
                controller=controller,
            )
            db.add_event(
                conn,
                job_id=job_id,
                kind="job_created",
                payload={
                    "job_id": job_id,
                    "worktree_path": str(worktree),
                    "goal": args.goal,
                    "test_cmd": test_cmd,
                    "worker": worker,
                    "controller": controller,
                    "pre_job_commit": pre_job_commit,
                    "checkout_overlay_files": overlay_files,
                },
            )

        client = redis_client(settings.redis_url)
        prepare_job_consumer_groups(client, job_id)
        job_processes = launch_job_processes(settings.root_dir, job_id)
        with db.transaction(settings.db_path) as conn:
            db.add_event(
                conn,
                job_id=job_id,
                kind="job_processes_started",
                payload={
                    "job_id": job_id,
                    "pids": job_processes,
                    "runtime_dir": str(settings.root_dir / "run" / "jobs" / job_id),
                    "log_dir": str(settings.root_dir / "logs" / "jobs" / job_id),
                },
            )
        xadd_json(
            client,
            CLAUDE_REQUEST_STREAM,
            "request",
            {"type": "PLAN", "job_id": job_id, "scope": "job"},
        )
    except (ConnectionError, TimeoutError) as exc:
        print(f"job {job_id} created, but Redis activation failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"could not create job: {exc}", file=sys.stderr)
        return 1

    print(f"created job {job_id}")
    print(f"repo: {repo}")
    print(f"worker: {worker}")
    print(f"controller: {controller}")
    if pre_job_commit.get("created"):
        print(f"pre-job commit: {pre_job_commit.get('after')}")
    else:
        print("pre-job commit: none needed")
    print(f"worktree: {worktree}")
    if use_worktree:
        print(f"checkout overlay files: {len(overlay_files)}")
    print(f"db: {settings.db_path}")
    print(f"processes: {job_processes}")
    print(f"queued PLAN on {CLAUDE_REQUEST_STREAM}")
    if args.wait:
        return wait_for_job(settings.db_path, job_id, worktree, args.timeout, args.poll_interval)
    print_inspect_commands(job_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
