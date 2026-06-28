from __future__ import annotations

import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from redis.exceptions import ConnectionError, TimeoutError

from ai_loop import db
from ai_loop.config import CLAUDE_REQUEST_STREAM, CODEX_TASK_STREAM, DEAD_STREAM, HUMAN_STREAM, load_settings
from ai_loop.queues import consumer_name, decode, ensure_group, redis_client, read_group, xadd_json


GROUP = "codex-workers"
OUTPUT_LIMIT = 20000
DIFF_LIMIT = 80000
INSTRUCTION_FILE_LIMIT = 10


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


def run_command_allow_rc(cmd: list[str], cwd: str, timeout: int, allowed_rc: set[int]) -> dict[str, object]:
    result = run_command(cmd, cwd, timeout)
    if int(result["rc"]) not in allowed_rc:
        return result
    return result


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


def text_fields(*items: object) -> str:
    parts: list[str] = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, dict):
            parts.extend(str(value) for value in item.values())
        elif isinstance(item, list):
            parts.extend(str(value) for value in item)
        else:
            parts.append(str(item))
    return "\n".join(parts)


def referenced_file_candidates(job: dict, task: dict) -> list[str]:
    text = text_fields(
        job.get("goal"),
        job.get("constraints"),
        job.get("acceptance"),
    )
    candidates: list[str] = []
    patterns = [
        r"`([^`\n]+\.[A-Za-z0-9_+-]+)`",
        r"['\"]([^'\"\n]+\.[A-Za-z0-9_+-]+)['\"]",
        r"\b([A-Za-z0-9_./@+-]+\.(?:md|txt|rst|adoc|toml|ya?ml|json|ini|cfg|cmake|cmakelists|ixx|cpp|hpp|h|c|cc|hh))\b",
        r"\b(CMakeLists\.txt|Makefile|AGENTS\.md)\b",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            value = match.strip().strip(".,;:)")
            if value.startswith(("http://", "https://")):
                continue
            if value and value not in candidates:
                candidates.append(value)
    return candidates


def safe_relative_path(worktree: Path, value: str) -> Path | None:
    raw = Path(value).expanduser()
    if raw.is_absolute():
        try:
            raw.relative_to(worktree)
            return raw
        except ValueError:
            return None
    if any(part == ".." for part in raw.parts):
        return None
    return worktree / raw


def referenced_existing_files(job: dict, task: dict) -> list[str]:
    worktree = Path(str(job["worktree_path"]))
    found: list[Path] = []
    for candidate in referenced_file_candidates(job, task):
        path = safe_relative_path(worktree, candidate)
        if path is None:
            continue
        matches: list[Path] = []
        if path.is_file():
            matches = [path]
        elif "/" not in candidate and "\\" not in candidate:
            matches = [item for item in worktree.rglob(candidate) if item.is_file()]
        for match in matches:
            resolved = match.resolve()
            try:
                resolved.relative_to(worktree.resolve())
            except ValueError:
                continue
            if resolved not in found:
                found.append(resolved)
            if len(found) >= INSTRUCTION_FILE_LIMIT:
                break
        if len(found) >= INSTRUCTION_FILE_LIMIT:
            break
    return [str(path.relative_to(worktree.resolve())) for path in found]


def codex_prompt(job: dict, task: dict) -> str:
    guidance_files = referenced_existing_files(job, task)
    crash_safe_runner = Path(__file__).resolve().parent / "ai_run_crash_safe.bash"
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

Referenced guidance files to refresh before work:
{db.to_json(guidance_files)}

Rules:
- Implement only this task.
- Treat this as a tasklet: keep changes as small and specific as possible.
- Do not expand the task into adjacent cleanup, broad audits, or follow-up milestones.
- Stop once this tasklet's acceptance criteria are met.
- Follow project instruction files when they exist, such as AGENTS.md or equivalent local guidelines. If no such files exist, infer style and architecture from nearby code instead of treating their absence as a blocker.
- The listed referenced guidance files may have changed since the job started. Re-read each existing listed file at the start of the task and use the current content, not stale summaries.
- If the task runs long or your plan depends on those files, check their modification time and re-read them before finalizing.
- Match existing project patterns, naming, module boundaries, error handling, formatting, and test style unless the task explicitly asks for a change.
- Keep code maintainable: avoid unrelated refactors, avoid unnecessary abstractions, and avoid duplicated logic when a local helper or established pattern exists.
- Add or update tests only when useful for this task.
- When running a target-project executable that may crash or open a platform crash dialog, run it through the ai-loop crash-safe wrapper when available: {crash_safe_runner} -- <executable> [args...]. Treat crashes as normal diagnostic output to fix, not as a reason for the user to click through an OS crash dialog.
- Do not commit changes.
- Do not merge branches.
- If blocked by missing tools, sandboxing, permissions, or unclear requirements, stop and explain the blocker.
"""


def git_snapshot(cwd: str) -> dict[str, object]:
    status = run_command(["git", "status", "--short"], cwd, 300)
    diff_stat = run_command(["git", "diff", "--stat"], cwd, 300)
    diff = run_command(["git", "diff"], cwd, 300)
    porcelain = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=300,
    )
    if porcelain.returncode != 0:
        porcelain_output = (porcelain.stdout + "\n" + porcelain.stderr).strip()
    else:
        porcelain_output = porcelain.stdout

    changed: list[str] = []
    untracked: list[str] = []
    entries = porcelain_output.split("\0")
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
        changed.append(path)
        if code == "??":
            untracked.append(path)

    extra_diffs: list[str] = []
    for path in untracked:
        untracked_diff = run_command_allow_rc(["git", "diff", "--no-index", "--", "/dev/null", path], cwd, 300, {0, 1})
        output = str(untracked_diff["output"]).strip()
        if output:
            extra_diffs.append(output)

    combined_diff = str(diff["output"])
    if extra_diffs:
        combined_diff = "\n\n".join([combined_diff, *extra_diffs]).strip()
    return {
        "git_status": str(status["output"])[-OUTPUT_LIMIT:],
        "diff_stat": str(diff_stat["output"])[-OUTPUT_LIMIT:],
        "diff": combined_diff[-DIFF_LIMIT:],
        "changed_files": sorted(set(changed)),
    }


def record_dead(settings, client, job_id: str | None, payload: dict, task_id: str | None = None) -> None:
    with db.transaction(settings.db_path) as conn:
        db.add_event(conn, job_id=job_id, kind="dead", payload=payload)
        if task_id:
            db.update_task_status(conn, task_id, "dead")
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
        running_status = "fixing" if str(task["created_by"]) == "claude:repair" else "implementing"
        db.update_job_status(conn, job["id"], running_status)

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
        worker_stage = "fixing" if str(task["created_by"]) == "claude:repair" else "implementing"
        log_worker_stage(job["id"], task_id, worker_stage, "Codex process started; source changes may not exist until it finishes")
        codex = run_command(codex_cmd, worktree_path, 7200)
        codex_rc = int(codex["rc"])
        codex_output = str(codex["output"])[-OUTPUT_LIMIT:]
        log_worker_stage(job["id"], task_id, "codex_done", f"Codex finished rc={codex_rc}; running task test command")

        with db.transaction(settings.db_path) as conn:
            refreshed_task = db.get_task(conn, task_id)
        task_test_cmd = str(refreshed_task["test_cmd"])
        tests = run_shell(task_test_cmd, worktree_path, 1800)
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
            task_id = None
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
                    record_dead(settings, client, job_id, payload, task_id)
                    client.xack(CODEX_TASK_STREAM, GROUP, message_id)
                except Exception as inner:
                    print(f"could not record dead event: {inner}")


if __name__ == "__main__":
    raise SystemExit(main())
