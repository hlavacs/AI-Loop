import json
import os
import pathlib
import socket
import subprocess
import time

import redis
from redis.exceptions import TimeoutError, ConnectionError


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

TASK_STREAM = "ai:codex:tasks"
RESULT_STREAM = "ai:codex:results"
DEAD_STREAM = "ai:dead"

GROUP = "codex-workers"
CONSUMER = socket.gethostname() + "-codex"

READ_BLOCK_MS = 5000


r = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=10,
    health_check_interval=30,
    retry_on_timeout=True,
)


def ensure_group(stream: str, group: str) -> None:
    try:
        r.xgroup_create(stream, group, id="0", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def run(cmd: list[str], cwd: str | None = None, timeout: int = 3600) -> dict:
    print(f"\n--- running: {' '.join(cmd)}")
    if cwd:
        print(f"--- cwd: {cwd}")

    p = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
    )

    return {
        "rc": p.returncode,
        "stdout": p.stdout[-20000:],
        "stderr": p.stderr[-20000:],
    }


def shell(cmd: str, cwd: str, timeout: int = 1800) -> dict:
    return run(["bash", "-lc", cmd], cwd=cwd, timeout=timeout)


def process(task: dict) -> dict:
    repo = pathlib.Path(task["repo_path"]).resolve()

    if not repo.exists():
        return {
            "job_id": task.get("job_id", "unknown"),
            "iteration": task.get("iteration", -1),
            "repo_path": str(repo),
            "status": "failed",
            "error": f"repo_path does not exist: {repo}",
        }

    job_id = task["job_id"]
    iteration = task.get("iteration", 0)
    test_cmd = task.get("test_cmd", "true")

    prompt = f"""
You are Codex, the implementation worker.

Job: {job_id}
Iteration: {iteration}

Goal:
{task["goal"]}

Constraints:
{json.dumps(task.get("constraints", []), indent=2)}

Acceptance criteria:
{json.dumps(task.get("acceptance", []), indent=2)}

Rules:
- Implement only this task.
- Keep the change small.
- Add or adjust tests if needed.
- Do not commit.
- Do not broaden the architecture.
- If impossible, explain the blocker in the final response.
"""

    codex = run(
        [
            "codex",
            "exec",
            "--cd",
            str(repo),
            "--dangerously-bypass-approvals-and-sandbox",
            prompt,
        ],
        cwd=str(repo),
        timeout=7200,
    )

    tests = shell(test_cmd, cwd=str(repo), timeout=1800)

    diff = run(["git", "diff"], cwd=str(repo), timeout=300)
    stat = run(["git", "diff", "--stat"], cwd=str(repo), timeout=300)
    files = run(["git", "diff", "--name-only"], cwd=str(repo), timeout=300)
    status = run(["git", "status", "--short"], cwd=str(repo), timeout=300)

    return {
        "job_id": job_id,
        "iteration": iteration,
        "repo_path": str(repo),
        
        "global_goal": task.get("global_goal", task.get("goal", "")),
        "loop_plan": task.get("loop_plan", []),
        "current_step": task.get("current_step", 1),
    
        "goal": task["goal"],
        "test_cmd": test_cmd,
        "codex_rc": codex["rc"],
        "codex_output": (codex["stdout"] + "\n" + codex["stderr"])[-12000:],
        "test_rc": tests["rc"],
        "test_output": (tests["stdout"] + "\n" + tests["stderr"])[-12000:],
        "changed_files": files["stdout"].splitlines(),
        "git_status": status["stdout"],
        "diff_stat": stat["stdout"],
        "diff": diff["stdout"][-50000:],
    }


def main() -> None:
    ensure_group(TASK_STREAM, GROUP)

    print("Codex worker started.")
    print(f"Listening on Redis stream: {TASK_STREAM}")
    print(f"Consumer group: {GROUP}")
    print(f"Consumer: {CONSUMER}")

    while True:
        try:
            messages = r.xreadgroup(
                GROUP,
                CONSUMER,
                {TASK_STREAM: ">"},
                count=1,
                block=READ_BLOCK_MS,
            )
        except (TimeoutError, ConnectionError) as e:
            print(f"Redis read problem, retrying: {e}")
            time.sleep(1)
            continue

        if not messages:
            continue

        _, entries = messages[0]

        for message_id, fields in entries:
            try:
                task = json.loads(fields["task"])

                print()
                print("=" * 80)
                print(f"Received task {task.get('job_id')} iteration {task.get('iteration')}")
                print(task.get("goal"))
                print("=" * 80)

                result = process(task)

                r.xadd(RESULT_STREAM, {"result": json.dumps(result)})
                r.xack(TASK_STREAM, GROUP, message_id)

                print(f"Finished task {result.get('job_id')} iteration {result.get('iteration')}")
                print(f"Codex rc: {result.get('codex_rc')}")
                print(f"Test rc: {result.get('test_rc')}")

            except Exception as e:
                print(f"Worker error: {e}")

                try:
                    r.xadd(
                        DEAD_STREAM,
                        {
                            "where": "codex_worker",
                            "error": repr(e),
                            "fields": json.dumps(fields),
                        },
                    )
                    r.xack(TASK_STREAM, GROUP, message_id)
                except Exception as inner:
                    print(f"Could not write to dead stream: {inner}")


if __name__ == "__main__":
    main()

