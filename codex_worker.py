from __future__ import annotations

import shutil
import subprocess
import time
import uuid

from redis.exceptions import ConnectionError, TimeoutError

from ai_loop import db
from ai_loop.config import CLAUDE_REQUEST_STREAM, CODEX_TASK_STREAM, DEAD_STREAM, HUMAN_STREAM, load_settings
from ai_loop.queues import consumer_name, decode, ensure_group, redis_client, read_group, xadd_json


GROUP = "codex-workers"
OUTPUT_LIMIT = 20000
DIFF_LIMIT = 80000


def run_command(cmd: list[str], cwd: str, timeout: int) -> dict[str, object]:
    print(f"running: {' '.join(cmd)}")
    print(f"cwd: {cwd}")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        output = (proc.stdout + "\n" + proc.stderr).strip()
        return {"rc": proc.returncode, "output": output, "elapsed": round(time.monotonic() - started, 2)}
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") + "\n" + (exc.stderr or "")).strip()
        return {"rc": 124, "output": f"command timed out after {timeout}s\n{output}", "elapsed": timeout}


def run_shell(command: str, cwd: str, timeout: int) -> dict[str, object]:
    return run_command(["bash", "-lc", command], cwd, timeout)


def log_worker_stage(job_id: str, task_id: str, stage: str, detail: str) -> None:
    print(f"job {job_id} task {task_id}: {stage} - {detail}")


def build_codex_command(codex_bin: str, cwd: str, prompt: str, bypass_sandbox: bool) -> list[str]:
    cmd = [codex_bin, "exec", "--cd", cwd]
    if bypass_sandbox:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        cmd.extend(["--sandbox", "workspace-write"])
    cmd.append(prompt)
    return cmd


def codex_prompt(job: dict, task: dict) -> str:
    return f"""You are Codex CLI, the implementation worker in a Claude-controlled loop.

Repository: {job["worktree_path"]}
Job: {job["id"]}
Iteration: {task["iteration"]}

Overall goal:
{job["goal"]}

This task:
{task["goal"]}

Task constraints:
{db.to_json(task["constraints"])}

Task acceptance criteria:
{db.to_json(task["acceptance"])}

Rules:
- Implement only this task.
- Treat this as a tasklet: keep changes as small and specific as possible.
- Do not expand the task into adjacent cleanup, broad audits, or follow-up milestones.
- Stop once this tasklet's acceptance criteria are met.
- Add or update tests only when useful for this task.
- Do not commit changes.
- Do not merge branches.
- If blocked by missing tools, sandboxing, permissions, or unclear requirements, stop and explain the blocker.
"""


def git_snapshot(cwd: str) -> dict[str, object]:
    status = run_command(["git", "status", "--short"], cwd, 300)
    diff_stat = run_command(["git", "diff", "--stat"], cwd, 300)
    diff = run_command(["git", "diff"], cwd, 300)
    files = run_command(["git", "diff", "--name-only"], cwd, 300)
    changed = [line for line in str(files["output"]).splitlines() if line.strip()]
    return {
        "git_status": str(status["output"])[-OUTPUT_LIMIT:],
        "diff_stat": str(diff_stat["output"])[-OUTPUT_LIMIT:],
        "diff": str(diff["output"])[-DIFF_LIMIT:],
        "changed_files": changed,
    }


def record_dead(settings, client, job_id: str | None, payload: dict) -> None:
    with db.transaction(settings.db_path) as conn:
        db.add_event(conn, job_id=job_id, kind="dead", payload=payload)
        if job_id:
            db.update_job_status(conn, job_id, "dead")
    xadd_json(client, DEAD_STREAM, "event", payload)


def process_task(settings, client, task_id: str) -> None:
    started_at = db.utc_now()
    run_id = uuid.uuid4().hex[:12]

    with db.transaction(settings.db_path) as conn:
        task = db.get_task(conn, task_id)
        job = db.get_job(conn, task["job_id"])
        db.update_task_status(conn, task_id, "running")
        db.update_job_status(conn, job["id"], "implementing")

    print(f"task {task_id}: job {job['id']} iteration {task['iteration']}")
    print(f"goal: {task['goal']}")

    codex_rc: int | None = None
    codex_output = ""
    test_rc: int | None = None
    test_output = ""
    error: str | None = None
    status = "completed"
    worktree_path = job["worktree_path"]

    if shutil.which(settings.codex_bin) is None:
        error = f"missing Codex binary: {settings.codex_bin}"
        status = "human_needed"
        print(error)
    else:
        prompt = codex_prompt(job, task)
        codex_cmd = build_codex_command(
            settings.codex_bin,
            worktree_path,
            prompt,
            settings.codex_bypass_sandbox,
        )
        log_worker_stage(job["id"], task_id, "implementing", "Codex process started; source changes may not exist until it finishes")
        codex = run_command(codex_cmd, worktree_path, 7200)
        codex_rc = int(codex["rc"])
        codex_output = str(codex["output"])[-OUTPUT_LIMIT:]
        log_worker_stage(job["id"], task_id, "codex_done", f"Codex finished rc={codex_rc}; running task test command")

        tests = run_shell(task["test_cmd"], worktree_path, 1800)
        test_rc = int(tests["rc"])
        test_output = str(tests["output"])[-OUTPUT_LIMIT:]
        log_worker_stage(job["id"], task_id, "tests_done", f"test command finished rc={test_rc}; capturing git diff")

    snapshot = git_snapshot(worktree_path)
    changed_files = list(snapshot["changed_files"])
    log_worker_stage(
        job["id"],
        task_id,
        "snapshot",
        f"changed_files={changed_files if changed_files else 'none'}",
    )
    finished_at = db.utc_now()

    with db.transaction(settings.db_path) as conn:
        db.create_run(
            conn,
            run_id=run_id,
            task_id=task_id,
            job_id=job["id"],
            iteration=int(task["iteration"]),
            codex_rc=codex_rc,
            codex_output=codex_output,
            test_rc=test_rc,
            test_output=test_output,
            git_status=str(snapshot["git_status"]),
            diff_stat=str(snapshot["diff_stat"]),
            diff=str(snapshot["diff"]),
            changed_files=changed_files,
            status=status,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
        )
        db.update_task_status(conn, task_id, status)
        if status == "human_needed":
            db.update_job_status(
                conn,
                job["id"],
                "human_needed",
                "Codex worker could not run the implementation task.",
            )
        db.add_event(
            conn,
            job_id=job["id"],
            kind="codex_run_finished",
            payload={"run_id": run_id, "task_id": task_id, "status": status, "error": error},
        )

    if status == "human_needed":
        payload = {
            "job_id": job["id"],
            "task_id": task_id,
            "run_id": run_id,
            "action": "HUMAN_NEEDED",
            "reason": error or "Codex worker could not complete the task.",
        }
        xadd_json(client, HUMAN_STREAM, "event", payload)
        print(f"task {task_id}: reported HUMAN_NEEDED")
        return

    xadd_json(
        client,
        CLAUDE_REQUEST_STREAM,
        "request",
        {"type": "REVIEW", "job_id": job["id"], "task_id": task_id, "run_id": run_id},
    )
    print(f"task {task_id}: queued REVIEW for run {run_id}")


def main() -> int:
    settings = load_settings()
    db.init_db(settings.db_path)
    client = redis_client(settings.redis_url)
    ensure_group(client, CODEX_TASK_STREAM, GROUP)
    consumer = consumer_name("codex")

    print("Codex worker started")
    print(f"db: {settings.db_path}")
    print(f"redis: {settings.redis_url}")
    print(f"listening: {CODEX_TASK_STREAM} group={GROUP} consumer={consumer}")

    while True:
        try:
            messages = read_group(client, GROUP, consumer, CODEX_TASK_STREAM)
        except (TimeoutError, ConnectionError) as exc:
            print(f"Redis read problem, retrying: {exc}")
            time.sleep(1)
            continue

        if not messages:
            continue

        _, entries = messages[0]
        for message_id, fields in entries:
            job_id = None
            try:
                payload = decode(fields["task"])
                task_id = payload["task_id"]
                with db.transaction(settings.db_path) as conn:
                    job_id = db.get_task(conn, task_id)["job_id"]
                process_task(settings, client, task_id)
                client.xack(CODEX_TASK_STREAM, GROUP, message_id)
            except Exception as exc:
                print(f"worker error: {exc}")
                payload = {"where": "codex_worker", "error": repr(exc), "fields": fields}
                try:
                    record_dead(settings, client, job_id, payload)
                    client.xack(CODEX_TASK_STREAM, GROUP, message_id)
                except Exception as inner:
                    print(f"could not record dead event: {inner}")


if __name__ == "__main__":
    raise SystemExit(main())
