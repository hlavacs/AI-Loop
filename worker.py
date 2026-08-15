from __future__ import annotations

import re
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from redis.exceptions import ConnectionError, TimeoutError

from ai_loop import db
from ai_loop.config import (
    CLAUDE_REQUEST_STREAM,
    CODEX_TASK_STREAM,
    DEAD_STREAM,
    HUMAN_STREAM,
    load_settings,
    sanitized_child_env,
)
from ai_loop.notifications import delivery_outcome, terminal_email
from ai_loop.planning import normalize_granularity
from ai_loop.queues import claim_pending, consumer_name, decode, ensure_group, redis_client, read_group, xadd_json
from ai_loop.recovery import attempt_auto_recovery
from ai_loop.token_wait import replenishment_time, wait_until


GROUP = "codex-workers"
OUTPUT_LIMIT = 20000
DIFF_LIMIT = 80000
INSTRUCTION_FILE_LIMIT = 10
TERMINAL_STATUSES = {"done", "human_needed", "dead"}
PROMPT_ARG_LIMIT = 100000


def scoped_job_id() -> str | None:
    value = os.getenv("AI_LOOP_JOB_ID")
    return value if value else None


def scoped_group(base_group: str, job_id: str | None) -> str:
    return f"{base_group}:{job_id}" if job_id else base_group


def is_terminal_job(settings, job_id: str) -> bool:
    with db.transaction(settings.db_path) as conn:
        job = db.get_job(conn, job_id)
        return str(job["status"]) in TERMINAL_STATUSES


def prompt_arg_or_file(prompt: str, label: str) -> str:
    if len(prompt.encode("utf-8")) < PROMPT_ARG_LIMIT:
        return prompt
    handle = tempfile.NamedTemporaryFile("w", suffix=f"-{label}-prompt.txt", delete=False)
    with handle:
        handle.write(prompt)
    return f"Read the full prompt from this file, follow it exactly, and complete the requested task: {handle.name}"


def run_command(cmd: list[str], cwd: str, timeout: int, input_text: str | None = None) -> dict[str, object]:
    display_cmd = [*cmd]
    if input_text is not None and display_cmd and display_cmd[-1] == "-":
        display_cmd[-1] = "<stdin>"
    print(f"running: {' '.join(display_cmd)}")
    print(f"cwd: {cwd}")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=sanitized_child_env(),
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


def build_codex_command(codex_bin: str, cwd: str, prompt: str, model: str, bypass_sandbox: bool) -> list[str]:
    cmd = [codex_bin, "exec", "--cd", cwd]
    if model:
        cmd.extend(["-m", model])
    if bypass_sandbox:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        cmd.extend(["--sandbox", "workspace-write"])
    cmd.append("-")
    return cmd


FABLE_ALLOWED_TOOLS = "Bash,Edit,Write,MultiEdit,NotebookEdit"


def build_fable_command(claude_bin: str, prompt: str, model: str, bypass_sandbox: bool) -> list[str]:
    cmd = [claude_bin, "-p"]
    if model:
        cmd.extend(["--model", model])
    if bypass_sandbox:
        cmd.append("--dangerously-skip-permissions")
    else:
        cmd.extend(["--permission-mode", "acceptEdits", "--allowedTools", FABLE_ALLOWED_TOOLS])
    cmd.append(prompt_arg_or_file(prompt, "fable-worker"))
    return cmd


def build_gemini_command(gemini_bin: str, prompt: str, model: str, bypass_sandbox: bool) -> list[str]:
    cmd = [gemini_bin]
    if model:
        cmd.extend(["-m", model])
    if bypass_sandbox:
        cmd.append("--yolo")
    else:
        # Sandboxed mode auto-approves edits only, mirroring the Claude
        # worker's acceptEdits permission mode; --yolo is reserved for an
        # explicit sandbox bypass.
        cmd.extend(["--sandbox", "--approval-mode", "auto_edit"])
    cmd.extend(["-p", prompt_arg_or_file(prompt, "gemini-worker")])
    return cmd


def job_worker(settings, job: dict) -> str:
    worker = str(job.get("worker") or "").strip().lower()
    return worker if worker in {"claude", "codex", "fable", "opus", "gemini"} else settings.worker_default


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


WORKER_NAMES = {"claude": "Claude CLI", "fable": "Claude Fable", "opus": "Claude Opus", "codex": "Codex CLI", "gemini": "Gemini CLI"}
WORKER_LABELS = {"claude": "Claude", "fable": "Fable", "opus": "Opus", "codex": "Codex", "gemini": "Gemini"}


def codex_prompt(job: dict, task: dict, worker: str = "codex") -> str:
    guidance_files = referenced_existing_files(job, task)
    crash_safe_runner = Path(__file__).resolve().parent / "ai_run_crash_safe.bash"
    worker_name = WORKER_NAMES.get(worker, "Codex CLI")
    granularity = normalize_granularity(str(job.get("granularity") or "normal"))
    if granularity == "coarse":
        scope_rules = """- Complete this substantial task as one coherent unit, including its related discovery, implementation, documentation, and verification.
- Do not split work merely per file or function, and do not leave obvious in-scope follow-up tasklets.
- Preserve code quality, reviewability, and test coverage while reducing controller round trips."""
    elif granularity == "fine":
        scope_rules = """- Implement only this focused tasklet.
- Keep the change narrow and stop at its explicit acceptance boundary.
- Do not expand into adjacent cleanup or follow-up milestones."""
    else:
        scope_rules = """- Implement this medium-sized coherent task completely.
- Group directly related changes, but do not expand into independent features or broad cleanup.
- Stop once this task's acceptance criteria are met."""
    return f"""You are {worker_name}, the implementation worker in a controller-managed loop.

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
{scope_rules}
- Follow project instruction files when they exist, such as AGENTS.md or equivalent local guidelines. If no such files exist, infer style and architecture from nearby code instead of treating their absence as a blocker.
- The listed referenced guidance files may have changed since the job started. Re-read each existing listed file at the start of the task and use the current content, not stale summaries.
- If the task runs long or your plan depends on those files, check their modification time and re-read them before finalizing.
- Match existing project patterns, naming, module boundaries, error handling, formatting, and test style unless the task explicitly asks for a change.
- Keep code maintainable: avoid unrelated refactors, avoid unnecessary abstractions, and avoid duplicated logic when a local helper or established pattern exists.
- Add or update tests only when useful for this task.
- When running a target-project executable that may crash or open a platform crash dialog, run it through the ai-loop crash-safe wrapper when available: {crash_safe_runner} -- <executable> [args...]. Treat crashes as normal diagnostic output to fix, not as a reason for the user to click through an OS crash dialog.
- If an executable reports a scene or asset load failure such as "scene load failed: error=io_error", compare behavior from the repository/worktree root and from the failing launch directory before assuming the asset is missing. Treat relative working-directory and asset path bugs as fixable code or launch-command issues.
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

    worker = job_worker(settings, job)
    if worker in {"claude", "fable", "opus"}:
        worker_bin = settings.claude_bin
    elif worker == "gemini":
        worker_bin = settings.gemini_bin
    else:
        worker_bin = settings.codex_bin
    worker_label = WORKER_LABELS.get(worker, "Codex")

    if shutil.which(worker_bin) is None:
        error = f"missing {worker_label} binary: {worker_bin}"
        status = "human_needed"
        print(error)
    else:
        prompt = codex_prompt(job, task, worker)
        bypass_sandbox = settings.codex_bypass_sandbox
        if bypass_sandbox:
            print("sandbox bypass enabled via CODEX_BYPASS_SANDBOX")
        if worker in {"claude", "fable", "opus"}:
            legacy_claude_model = (
                settings.opus_model
                if worker == "opus"
                else settings.fable_model
                if worker == "fable"
                else settings.controller_model
            )
            codex_cmd = build_fable_command(
                settings.claude_bin,
                prompt,
                settings.worker_role_model or legacy_claude_model,
                bypass_sandbox,
            )
        elif worker == "gemini":
            codex_cmd = build_gemini_command(
                settings.gemini_bin,
                prompt,
                settings.worker_role_model or settings.gemini_model,
                bypass_sandbox,
            )
        else:
            codex_cmd = build_codex_command(
                settings.codex_bin,
                worktree_path,
                prompt,
                settings.worker_role_model or settings.codex_model,
                bypass_sandbox,
            )
        worker_stage = "fixing" if str(task["created_by"]) == "claude:repair" else "implementing"
        log_worker_stage(job["id"], task_id, worker_stage, f"{worker_label} process started; source changes may not exist until it finishes")
        codex_input = prompt if worker == "codex" else None
        while True:
            codex = run_command(codex_cmd, worktree_path, 7200, input_text=codex_input)
            codex_rc = int(codex["rc"])
            codex_output = str(codex["output"])[-OUTPUT_LIMIT:]
            retry_at = replenishment_time(codex_output) if codex_rc != 0 else None
            if retry_at is None:
                break
            waiting_until = retry_at.isoformat(timespec="seconds")
            with db.transaction(settings.db_path) as conn:
                db.set_waiting_for_tokens(
                    conn,
                    str(job["id"]),
                    waiting_until,
                    task_id=task_id,
                )
                db.add_event(
                    conn,
                    job_id=str(job["id"]),
                    kind="waiting_for_tokens",
                    payload={"role": "worker", "task_id": task_id, "waiting_until": waiting_until},
                )
            print(f"job {job['id']}: waiting for worker tokens until {waiting_until}")
            wait_until(
                retry_at,
                on_tick=lambda remaining: print(
                    f"job {job['id']}: worker token wait, {remaining}s remaining"
                ),
            )
            with db.transaction(settings.db_path) as conn:
                db.set_waiting_for_tokens(
                    conn,
                    str(job["id"]),
                    None,
                    task_id=task_id,
                    resume_status=running_status,
                )
                db.add_event(
                    conn,
                    job_id=str(job["id"]),
                    kind="token_wait_finished",
                    payload={"role": "worker", "task_id": task_id, "waiting_until": waiting_until},
                )
            print(f"job {job['id']}: token wait finished; retrying task {task_id}")
        log_worker_stage(job["id"], task_id, "codex_done", f"{worker_label} finished rc={codex_rc}; running task test command")

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
                "Implementation worker could not run the task.",
            )
        else:
            db.update_job_status(conn, job["id"], "planning")
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
            "reason": error or "Implementation worker could not complete the task.",
        }
        xadd_json(client, HUMAN_STREAM, "event", payload)
        notify_terminal(settings, str(job["id"]), "human_needed", str(payload["reason"]))
        print(f"task {task_id}: reported HUMAN_NEEDED")
        return

    review_payload = {"type": "REVIEW", "job_id": job["id"], "task_id": task_id, "run_id": run_id}
    if scoped_job_id():
        review_payload["scope"] = "job"
    xadd_json(client, CLAUDE_REQUEST_STREAM, "request", review_payload)
    print(f"task {task_id}: queued REVIEW for run {run_id}")


def notify_terminal(settings, job_id: str, status: str, reason: str) -> None:
    with db.transaction(settings.db_path) as conn:
        job = db.get_job(conn, job_id)
    sent, detail = terminal_email(settings, job=job, status=status, reason=reason)
    outcome = delivery_outcome(sent, detail)
    with db.transaction(settings.db_path) as conn:
        db.add_event(
            conn,
            job_id=job_id,
            kind=f"email_notification_{outcome}",
            payload={"status": status, "recipient": settings.notify_email, "detail": detail},
        )
    print(f"job {job_id}: email notification {outcome} - {detail}")


def process_message(settings, client, group, job_scope, message_id, fields) -> bool:
    job_id = None
    task_id = None
    try:
        payload = decode(fields["task"])
        task_id = payload["task_id"]
        with db.transaction(settings.db_path) as conn:
            job_id = db.get_task(conn, task_id)["job_id"]
        if not job_scope and payload.get("scope") == "job":
            client.xack(CODEX_TASK_STREAM, group, message_id)
            return False
        if job_scope and job_id != job_scope:
            client.xack(CODEX_TASK_STREAM, group, message_id)
            return False
        process_task(settings, client, task_id)
        client.xack(CODEX_TASK_STREAM, group, message_id)
        # The message is handled and acked: a failure in the terminal-status
        # check below must not reach the auto-recovery/record_dead path and
        # mark a successful run dead. The next loop iteration retries the check.
        try:
            if job_scope and is_terminal_job(settings, job_scope):
                print(f"job {job_scope}: terminal; Codex worker exiting")
                return True
        except Exception as check_exc:
            print(f"warning: terminal-status check failed after ack, retrying next loop: {check_exc}")
            return False
    except Exception as exc:
        print(f"worker error: {exc}")
        if attempt_auto_recovery(settings, job_id, "worker", repr(exc), fields):
            client.xack(CODEX_TASK_STREAM, group, message_id)
            print(f"job {job_id}: auto recovery launched; Codex worker exiting")
            return True
        payload = {"where": "worker", "error": repr(exc), "fields": fields}
        try:
            record_dead(settings, client, job_id, payload, task_id)
            if job_id:
                notify_terminal(settings, job_id, "dead", repr(exc))
            client.xack(CODEX_TASK_STREAM, group, message_id)
        except Exception as inner:
            print(f"could not record dead event: {inner}")
    return False


def main() -> int:
    settings = load_settings()
    db.init_db(settings.db_path)
    client = redis_client(settings.redis_url)
    job_scope = scoped_job_id()
    group = scoped_group(GROUP, job_scope)
    ensure_group(client, CODEX_TASK_STREAM, group, start_id="$" if job_scope else "0")
    consumer = consumer_name("codex")

    print("AI loop worker started")
    print(f"db: {settings.db_path}")
    print(f"redis: {settings.redis_url}")
    if job_scope:
        print(f"job_scope: {job_scope}")
    print(f"listening: {CODEX_TASK_STREAM} group={group} consumer={consumer}")

    pending = claim_pending(client, CODEX_TASK_STREAM, group, consumer)
    if pending:
        print(f"reclaimed {len(pending)} pending message(s)")
    for message_id, fields in pending:
        if process_message(settings, client, group, job_scope, message_id, fields):
            return 0

    idle_reads = 0
    while True:
        try:
            messages = read_group(client, group, consumer, CODEX_TASK_STREAM)
        except (TimeoutError, ConnectionError) as exc:
            print(f"Redis read problem, retrying: {exc}")
            time.sleep(1)
            continue

        if not messages:
            if job_scope and is_terminal_job(settings, job_scope):
                print(f"job {job_scope}: terminal; Codex worker exiting")
                return 0
            # Startup-only reclaim misses messages delivered <30 s before a
            # hard kill; retry after ~12 consecutive empty reads while idle.
            # Only when job_scope is set: scoped per-job groups have exactly
            # one consumer, so reclaim is safe; in unscoped mode the group is
            # shared across hosts and reclaim would steal in-flight tasks
            # from live remote consumers.
            idle_reads += 1
            if job_scope and idle_reads >= 12:
                idle_reads = 0
                pending = claim_pending(client, CODEX_TASK_STREAM, group, consumer)
                if pending:
                    print(f"reclaimed {len(pending)} pending message(s)")
                for message_id, fields in pending:
                    if process_message(settings, client, group, job_scope, message_id, fields):
                        return 0
            continue

        idle_reads = 0
        _, entries = messages[0]
        for message_id, fields in entries:
            if process_message(settings, client, group, job_scope, message_id, fields):
                return 0


if __name__ == "__main__":
    raise SystemExit(main())
