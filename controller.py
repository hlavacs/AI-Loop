from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from redis.exceptions import ConnectionError, TimeoutError

from ai_loop import db
from ai_loop.auth import auth_failure_decision, is_auth_failure
from ai_loop.config import (
    CLAUDE_REQUEST_STREAM,
    CODEX_TASK_STREAM,
    DEAD_STREAM,
    DONE_STREAM,
    HUMAN_STREAM,
    load_settings,
)
from ai_loop.queues import consumer_name, decode, ensure_group, redis_client, read_group, xadd_json
from ai_loop.notifications import terminal_email
from ai_loop.planning import normalize_granularity
from ai_loop.recovery import attempt_auto_recovery
from ai_loop.token_wait import is_token_limit, replenishment_time, wait_until


GROUP = "claude-controllers"
ACTIONS = {"CONTINUE", "REPAIR", "DONE", "HUMAN_NEEDED"}
OUTPUT_LIMIT = 20000
INSTRUCTION_FILE_LIMIT = 10
INSTRUCTION_FILE_BYTES = 12000
TERMINAL_STATUSES = {"done", "human_needed", "dead"}
CLAUDE_JSON_REMAKE_ATTEMPTS = 2
CLAUDE_TRANSIENT_RETRY_BACKOFF_SECONDS = float(os.getenv("AI_LOOP_CLAUDE_TRANSIENT_BACKOFF_SECONDS", "5"))
CLAUDE_TRANSIENT_RETRY_MAX_BACKOFF_SECONDS = float(
    os.getenv("AI_LOOP_CLAUDE_TRANSIENT_MAX_BACKOFF_SECONDS", "60")
)
PROMPT_ARG_LIMIT = 100000

CLAUDE_TRANSIENT_FAILURE_PATTERNS = (
    "api error",
    "connection closed",
    "connection lost",
    "connection reset",
    "econnreset",
    "econnaborted",
    "enotfound",
    "etimedout",
    "network",
    "offline",
    "socket hang up",
    "temporary failure",
    "temporarily unavailable",
    "tls",
    "timeout",
    "timed out",
    "overloaded",
    "rate limit",
    "try again",
)


def scoped_job_id() -> str | None:
    value = os.getenv("AI_LOOP_JOB_ID")
    return value if value else None


def scoped_group(base_group: str, job_id: str | None) -> str:
    return f"{base_group}:{job_id}" if job_id else base_group


def prompt_arg_or_file(prompt: str, label: str) -> tuple[str, Path | None]:
    if len(prompt.encode("utf-8")) < PROMPT_ARG_LIMIT:
        return prompt, None
    handle = tempfile.NamedTemporaryFile(
        "w",
        prefix=".ai-loop-",
        suffix=f"-{label}-prompt.txt",
        dir=Path.cwd(),
        delete=False,
    )
    with handle:
        handle.write(prompt)
    path = Path(handle.name)
    return f"Read the full prompt from this file, follow it exactly, and produce the requested response: {path}", path


def is_terminal_job(settings, job_id: str) -> bool:
    with db.transaction(settings.db_path) as conn:
        job = db.get_job(conn, job_id)
        return str(job["status"]) in TERMINAL_STATUSES


class PromotionError(RuntimeError):
    pass


def timestamp_id(prefix: str) -> str:
    return f"{prefix}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}"


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"Claude did not return JSON: {text[:1000]}")
        parsed = json.loads(text[start : end + 1])

    if isinstance(parsed, dict) and isinstance(parsed.get("structured_output"), dict):
        return parsed["structured_output"]
    if isinstance(parsed, dict):
        for key in ("result", "response", "text", "content", "output"):
            if isinstance(parsed.get(key), str):
                return extract_json(parsed[key])
    if not isinstance(parsed, dict):
        raise ValueError("Claude output JSON is not an object")
    return parsed


def validate_decision(decision: dict[str, Any]) -> None:
    action = decision.get("action")
    if action not in ACTIONS:
        raise ValueError(f"invalid action: {action}")
    if not isinstance(decision.get("reason"), str):
        raise ValueError("decision.reason must be a string")
    if not isinstance(decision.get("history_summary"), str):
        raise ValueError("decision.history_summary must be a string")
    progress = decision.get("progress")
    if progress is None:
        progress = {
            "completed_work_units": 0,
            "remaining_work_units": 1,
            "remaining_minutes": None,
        }
        decision["progress"] = progress
    if not isinstance(progress, dict):
        raise ValueError("decision.progress must be an object")
    for key in ("completed_work_units", "remaining_work_units"):
        if not isinstance(progress.get(key), int) or progress[key] < 0:
            raise ValueError(f"decision.progress.{key} must be a non-negative integer")
    remaining_minutes = progress.get("remaining_minutes")
    if remaining_minutes is not None and (
        not isinstance(remaining_minutes, int) or remaining_minutes < 0
    ):
        raise ValueError("decision.progress.remaining_minutes must be null or a non-negative integer")
    if action in {"CONTINUE", "REPAIR"}:
        next_task = decision.get("next_task")
        if not isinstance(next_task, dict):
            raise ValueError(f"{action} requires next_task")
        for key in ("goal", "constraints", "acceptance", "test_cmd"):
            if key not in next_task:
                raise ValueError(f"next_task missing {key}")
        if not isinstance(next_task["constraints"], list):
            raise ValueError("next_task.constraints must be a list")
        if not isinstance(next_task["acceptance"], list):
            raise ValueError("next_task.acceptance must be a list")


def validate_json_round_trip(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, sort_keys=True)
    parsed = json.loads(text)
    if parsed != payload:
        raise ValueError("decision JSON failed round-trip validation")


def parse_and_validate_decision(text: str) -> dict[str, Any]:
    decision = extract_json(text)
    validate_decision(decision)
    validate_json_round_trip(decision)
    return decision


def decision_json_schema() -> str:
    schema_path = Path(__file__).with_name("decision.schema.json")
    return json.dumps(json.loads(schema_path.read_text(encoding="utf-8")), separators=(",", ":"))


def is_transient_claude_cli_failure(output: str) -> bool:
    lowered = output.lower()
    return any(pattern in lowered for pattern in CLAUDE_TRANSIENT_FAILURE_PATTERNS)


def claude_transient_retry_delay(attempt: int) -> float:
    delay = CLAUDE_TRANSIENT_RETRY_BACKOFF_SECONDS * (2**attempt)
    return min(delay, CLAUDE_TRANSIENT_RETRY_MAX_BACKOFF_SECONDS)


def json_remake_prompt(original_prompt: str, invalid_output: str, error: Exception, sizing: str = "normal") -> str:
    return f"""Your previous response could not be accepted because it was not valid decision JSON.

JSON/parser/schema error:
{error}

Invalid response tail:
{invalid_output[-6000:]}

Remake the response now. Return one valid JSON object only, with no prose before or after it.
The JSON must parse with json.loads and must satisfy this schema:
{schema_text(sizing)}

Use the same planning/review context as before:
{original_prompt}
"""


def text_fields(*items: Any) -> str:
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


def referenced_file_candidates(job: dict[str, Any], task: dict[str, Any] | None = None) -> list[str]:
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


def refreshed_instruction_files(job: dict[str, Any], task: dict[str, Any] | None = None) -> list[dict[str, Any]]:
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

    snapshots: list[dict[str, Any]] = []
    for path in found:
        relative = str(path.relative_to(worktree.resolve()))
        stat = path.stat()
        try:
            content = path.read_text(encoding="utf-8")[:INSTRUCTION_FILE_BYTES]
            truncated = stat.st_size > INSTRUCTION_FILE_BYTES
        except UnicodeDecodeError:
            content = "<binary or non-UTF-8 file not included>"
            truncated = True
        snapshots.append(
            {
                "path": relative,
                "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
                "size": stat.st_size,
                "truncated": truncated,
                "content": content,
            }
        )
    return snapshots


def run_claude(claude_bin: str, prompt: str, model: str = "", sizing: str = "normal") -> dict[str, Any]:
    if shutil.which(claude_bin) is None:
        return {
            "action": "HUMAN_NEEDED",
            "reason": f"missing Claude binary: {claude_bin}",
            "history_summary": "Claude controller could not run because the Claude CLI is missing.",
        }

    claude_cmd = [
        claude_bin,
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        decision_json_schema(),
    ]
    if model:
        claude_cmd.extend(["--model", model])

    current_prompt = prompt
    last_output = ""
    last_error: Exception | None = None
    for attempt in range(CLAUDE_JSON_REMAKE_ATTEMPTS + 1):
        label = "running Claude controller" if attempt == 0 else f"remaking Claude JSON decision attempt {attempt}"
        print(label)
        proc: subprocess.CompletedProcess[str] | None = None
        output = ""
        cli_attempt = 0
        while True:
            prompt_arg, prompt_file = prompt_arg_or_file(current_prompt, "claude-controller")
            try:
                proc = subprocess.run(
                    [*claude_cmd, prompt_arg],
                    text=True,
                    capture_output=True,
                    timeout=7200,
                )
                output = (proc.stdout + "\n" + proc.stderr).strip()
                last_output = output
                if proc.returncode == 0:
                    break
                if is_auth_failure(output):
                    break
                if is_token_limit(output):
                    break
                if not is_transient_claude_cli_failure(output):
                    break
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout or ""
                stderr = exc.stderr or ""
                output = f"Claude CLI timed out after {exc.timeout:g}s\n{stdout}\n{stderr}".strip()
                last_output = output
                proc = None
            finally:
                if prompt_file is not None:
                    prompt_file.unlink(missing_ok=True)

            delay = claude_transient_retry_delay(cli_attempt)
            print(
                "Claude CLI transient failure "
                f"rc={proc.returncode if proc else 'timeout'}; retry {cli_attempt + 1} "
                f"in {delay:g}s"
            )
            time.sleep(delay)
            cli_attempt += 1

        if proc is None:
            raise RuntimeError("Claude CLI subprocess was not started")
        if proc.returncode != 0:
            reason = f"Claude CLI failed with rc={proc.returncode}: {output[-4000:]}"
            if is_auth_failure(output):
                return auth_failure_decision("claude", reason)
            return {
                "action": "HUMAN_NEEDED",
                "reason": reason,
                "history_summary": "Claude controller failed before producing a usable decision.",
            }
        try:
            return parse_and_validate_decision(proc.stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt >= CLAUDE_JSON_REMAKE_ATTEMPTS:
                break
            current_prompt = json_remake_prompt(prompt, output, exc, sizing)

    raise ValueError(
        "Claude did not produce valid decision JSON after "
        f"{CLAUDE_JSON_REMAKE_ATTEMPTS + 1} attempts: {last_error}; output tail={last_output[-4000:]!r}"
    )


def run_codex_controller(codex_bin: str, prompt: str, workdir: str, model: str = "", sizing: str = "normal") -> dict[str, Any]:
    if shutil.which(codex_bin) is None:
        return {
            "action": "HUMAN_NEEDED",
            "reason": f"missing Codex binary: {codex_bin}",
            "history_summary": "Codex controller could not run because the Codex CLI is missing.",
        }

    current_prompt = prompt
    last_output = ""
    last_error: Exception | None = None
    for attempt in range(CLAUDE_JSON_REMAKE_ATTEMPTS + 1):
        label = "running Codex controller" if attempt == 0 else f"remaking Codex JSON decision attempt {attempt}"
        print(label)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            last_message_path = Path(handle.name)
        try:
            try:
                cmd = [
                    codex_bin,
                    "exec",
                    "--cd",
                    workdir,
                    "--sandbox",
                    "read-only",
                    "--output-last-message",
                    str(last_message_path),
                ]
                if model:
                    cmd.extend(["-m", model])
                cmd.append("-")
                proc = subprocess.run(
                    cmd,
                    input=current_prompt,
                    text=True,
                    capture_output=True,
                    timeout=7200,
                )
            except subprocess.TimeoutExpired as exc:
                return {
                    "action": "HUMAN_NEEDED",
                    "reason": f"Codex CLI timed out after {exc.timeout:g}s",
                    "history_summary": "Codex controller timed out before producing a usable decision.",
                }
            output = (proc.stdout + "\n" + proc.stderr).strip()
            last_output = output
            try:
                last_message = last_message_path.read_text(encoding="utf-8").strip()
            except OSError:
                last_message = ""
        finally:
            last_message_path.unlink(missing_ok=True)

        if proc.returncode != 0:
            reason = f"Codex CLI failed with rc={proc.returncode}: {output[-4000:]}"
            if is_auth_failure(output):
                return auth_failure_decision("codex", reason)
            return {
                "action": "HUMAN_NEEDED",
                "reason": reason,
                "history_summary": "Codex controller failed before producing a usable decision.",
            }
        try:
            return parse_and_validate_decision(last_message or output)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt >= CLAUDE_JSON_REMAKE_ATTEMPTS:
                break
            current_prompt = json_remake_prompt(prompt, last_message or output, exc, sizing)

    raise ValueError(
        "Codex did not produce valid decision JSON after "
        f"{CLAUDE_JSON_REMAKE_ATTEMPTS + 1} attempts: {last_error}; output tail={last_output[-4000:]!r}"
    )


def run_gemini_controller(gemini_bin: str, prompt: str, workdir: str, model: str = "", sizing: str = "normal") -> dict[str, Any]:
    if shutil.which(gemini_bin) is None:
        return {
            "action": "HUMAN_NEEDED",
            "reason": f"missing Gemini binary: {gemini_bin}",
            "history_summary": "Gemini controller could not run because the Gemini CLI is missing.",
        }

    gemini_cmd = [gemini_bin]
    if model:
        gemini_cmd.extend(["-m", model])
    gemini_cmd.extend(["-p", "", "--output-format", "json"])

    current_prompt = prompt
    last_output = ""
    last_error: Exception | None = None
    for attempt in range(CLAUDE_JSON_REMAKE_ATTEMPTS + 1):
        label = "running Gemini controller" if attempt == 0 else f"remaking Gemini JSON decision attempt {attempt}"
        print(label)
        try:
            cmd = [*gemini_cmd]
            cmd[cmd.index("-p") + 1] = current_prompt
            proc = subprocess.run(
                cmd,
                cwd=workdir,
                text=True,
                capture_output=True,
                timeout=7200,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "action": "HUMAN_NEEDED",
                "reason": f"Gemini CLI timed out after {exc.timeout:g}s",
                "history_summary": "Gemini controller timed out before producing a usable decision.",
            }

        output = (proc.stdout + "\n" + proc.stderr).strip()
        last_output = output
        if proc.returncode != 0:
            reason = f"Gemini CLI failed with rc={proc.returncode}: {output[-4000:]}"
            if is_auth_failure(output):
                return auth_failure_decision("gemini", reason)
            return {
                "action": "HUMAN_NEEDED",
                "reason": reason,
                "history_summary": "Gemini controller failed before producing a usable decision.",
            }
        try:
            return parse_and_validate_decision(proc.stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt >= CLAUDE_JSON_REMAKE_ATTEMPTS:
                break
            current_prompt = json_remake_prompt(prompt, output, exc, sizing)

    raise ValueError(
        "Gemini did not produce valid decision JSON after "
        f"{CLAUDE_JSON_REMAKE_ATTEMPTS + 1} attempts: {last_error}; output tail={last_output[-4000:]!r}"
    )


def job_controller(settings, job: dict[str, Any]) -> str:
    controller = str(job.get("controller") or "").strip().lower()
    if controller not in {"claude", "fable", "opus", "codex", "gemini"}:
        controller = settings.controller_default
    return controller


def controller_decision(settings, job: dict[str, Any], prompt: str) -> dict[str, Any]:
    while True:
        controller = job_controller(settings, job)
        sizing = job_sizing(job)
        if controller == "codex":
            decision = run_codex_controller(
                settings.codex_bin,
                prompt,
                str(job["worktree_path"]),
                settings.codex_model,
                sizing,
            )
        elif controller == "gemini":
            decision = run_gemini_controller(
                settings.gemini_bin,
                prompt,
                str(job["worktree_path"]),
                settings.gemini_model,
                sizing,
            )
        else:
            if controller == "fable":
                model = settings.fable_model
            elif controller == "opus":
                model = settings.opus_model
            else:
                model = settings.controller_model
            decision = run_claude(settings.claude_bin, prompt, model, sizing)

        reason = str(decision.get("reason") or "")
        retry_at = replenishment_time(reason)
        if decision.get("action") != "HUMAN_NEEDED" or retry_at is None:
            return decision

        waiting_until = retry_at.isoformat(timespec="seconds")
        with db.transaction(settings.db_path) as conn:
            db.set_waiting_for_tokens(conn, str(job["id"]), waiting_until)
            db.add_event(
                conn,
                job_id=str(job["id"]),
                kind="waiting_for_tokens",
                payload={"role": "controller", "waiting_until": waiting_until},
            )
        print(f"job {job['id']}: waiting for controller tokens until {waiting_until}")
        wait_until(
            retry_at,
            on_tick=lambda remaining: print(
                f"job {job['id']}: controller token wait, {remaining}s remaining"
            ),
        )
        with db.transaction(settings.db_path) as conn:
            db.set_waiting_for_tokens(conn, str(job["id"]), None, resume_status="planning")
            db.add_event(
                conn,
                job_id=str(job["id"]),
                kind="token_wait_finished",
                payload={"role": "controller", "waiting_until": waiting_until},
            )
            job = db.get_job(conn, str(job["id"]))


def job_sizing(job: dict[str, Any]) -> str:
    return normalize_granularity(str(job.get("granularity") or "normal"))


def sizing_rules(sizing: str) -> str:
    if sizing == "coarse":
        return """- Minimize controller round trips with a small number of substantial, coherent tasks.
- Combine related discovery, implementation, documentation, and verification in one task when they serve the same outcome.
- Split only at genuine architecture, dependency, or risk boundaries; never split merely per file or function.
- Maintain the same quality, reviewability, and test coverage as smaller tasks."""
    if sizing == "fine":
        return """- Prefer focused tasklets so the controller retains close control.
- Give each tasklet one narrow objective, one primary file or tightly related file cluster, and a clear stop point.
- Split at natural behavior boundaries and keep acceptance provable in a short run."""
    return """- Prefer medium-sized coherent tasks with one outcome and a testable stop point.
- Group closely related discovery and implementation, but split independent features or risky migrations.
- Keep acceptance provable in one worker run without turning each file into a separate task."""


def schema_text(sizing: str = "normal") -> str:
    return """Return JSON only with this schema:
{
  "action": "CONTINUE | REPAIR | DONE | HUMAN_NEEDED",
  "reason": "string",
  "history_summary": "string",
  "progress": {
    "completed_work_units": 0,
    "remaining_work_units": 1,
    "remaining_minutes": 30
  },
  "next_task": {
    "goal": "string",
    "constraints": ["string"],
    "acceptance": ["string"],
    "test_cmd": "string"
  }
}

Rules:
- next_task is required for CONTINUE and REPAIR.
- progress is required for every action. Estimate logical work units already completed, units still remaining, and remaining wall-clock minutes. Keep the work-unit scale consistent with earlier decisions so the estimate remains comparable. Use null only when time cannot yet be estimated.
- You are controller/planner/reviewer only, never a code editor.
""" + sizing_rules(sizing) + """
- Write next_task.goal as a specific imperative, not a project summary. Name the exact directory, file, symbol, or test target when known.
- Project instruction files such as AGENTS.md are optional. If they exist and are relevant, require the worker to follow them; if they are absent, continue using the job goal, constraints, local code patterns, and tests.
- File-like paths mentioned in the original job description, job constraints, or job acceptance criteria may be live guidance files. The prompt includes a refreshed snapshot of those files when they exist. Treat that snapshot as current guidance and prefer it over earlier summaries if it changed.
- If a next_task depends on a mentioned guidance file, tell the worker to re-read that file at the start of the task and again before finalizing if the task runs long.
- During REVIEW, assess code quality and guideline compliance, not just whether files changed. Check visible changes against project instructions when present, local architecture, naming/style patterns, scope control, maintainability, test coverage proportional to risk, and avoidance of unrelated refactors.
- Avoid HUMAN_NEEDED at all costs. Treat it as the last resort, not a normal blocker state.
- Before HUMAN_NEEDED, analyze the problem, identify concrete solution paths, and choose an automated diagnostic or fix task whenever any safe one exists.
- Return REPAIR when the next task is meant to fix a known problem, including code defects, guideline violations, missing build wiring, bad test commands, fixable environment/tool configuration, or recoverable promotion/build failures.
- For REPAIR, write next_task.goal so it says exactly what is being fixed and why; include acceptance that proves the problem is gone or narrowed.
- Return REPAIR when the worker visibly violates coding guidelines, ignores existing project patterns, changes unrelated behavior, leaves brittle or duplicated code without cause, omits necessary tests for risky changes, or satisfies the task only superficially.
- Return HUMAN_NEEDED only after at least one concrete automated diagnostic/fix path has been tried or ruled out, and only when the remaining action truly requires a person, credentials, paid installation, physical device/display access, or a destructive choice that cannot be safely automated.
- For GUI/display/window tasks, ask the worker to verify DISPLAY, WAYLAND_DISPLAY, XDG_SESSION_TYPE, SDL video backends, Vulkan presentation support, and visible windows from the same process environment before deciding the display is unavailable.
- If the worker failed because of sandboxing, a missing tool, or permissions, first prefer REPAIR with a precise command, install step, configuration change, or diagnostic unless the loop demonstrably cannot perform it.
- If a target executable prints a scene/asset load failure such as "scene load failed: error=io_error", first treat it as a likely working-directory or asset-path problem. Prefer REPAIR asking the worker to run the executable from the repository/worktree root, inspect the expected asset path, and fix path resolution or launch documentation as appropriate.
- If tests fail due to code, return REPAIR.
- If tests pass but the goal is incomplete, return CONTINUE.
- If the goal and acceptance criteria are satisfied, return DONE.
- Return JSON only. Do not use Markdown."""


def plan_prompt(job: dict[str, Any]) -> str:
    instruction_files = refreshed_instruction_files(job)
    sizing = job_sizing(job)
    intro = f"Create exactly one {sizing}-granularity first task for this job."
    tail = """For PLAN, choose action CONTINUE unless the job is impossible or requires a human before any code work.
Use the immutable overall plan as milestone guidance; do not rewrite or replace it.
Preserve the job's constraints and acceptance criteria, and keep task acceptance provable by the test command."""
    return f"""You are the controller/planner in a generic continuous development loop.

{intro}

{schema_text(sizing)}

Job state:
{json.dumps(job, indent=2)}

Refreshed referenced guidance files:
{json.dumps(instruction_files, indent=2)}

{tail}
"""


def review_prompt(job: dict[str, Any], task: dict[str, Any], run: dict[str, Any]) -> str:
    review_state = {
        "job": job,
        "task": task,
        "refreshed_referenced_guidance_files": refreshed_instruction_files(job, task),
        "run": {
            **run,
            "codex_output": run["codex_output"][-OUTPUT_LIMIT:],
            "test_output": run["test_output"][-OUTPUT_LIMIT:],
            "diff": run["diff"][-80000:],
        },
    }
    sizing = job_sizing(job)
    guidance = f"""Review the worker output, test output, git diff, and durable job state. Decide the next loop action.
When continuing, create the next {sizing}-granularity task according to the sizing rules.
The immutable overall plan is milestone guidance and must not be rewritten."""
    if job.get("finish_requested"):
        guidance += """
Finish-soon mode is active. Drop optional polish and speculative follow-up work. If the core goal and acceptance criteria are met, return DONE now; otherwise create at most one consolidated final task containing only the work required for acceptance."""
    return f"""You are the controller/reviewer in a generic continuous development loop.

{guidance}

{schema_text(sizing)}

State to review:
{json.dumps(review_state, indent=2)}
"""


def next_iteration(conn, job_id: str) -> int:
    task = db.latest_task(conn, job_id)
    return 0 if task is None else int(task["iteration"]) + 1


def terminal_payload(job_id: str, decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "action": decision["action"],
        "reason": decision["reason"],
        "history_summary": decision.get("history_summary", ""),
    }


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=300,
    )


def status_paths(worktree: Path) -> list[tuple[str, str | None]]:
    proc = run_git(["status", "--porcelain=v1", "-z"], worktree)
    if proc.returncode != 0:
        raise PromotionError(f"could not inspect worktree git status: {proc.stderr.strip()}")

    paths: list[tuple[str, str | None]] = []
    items = proc.stdout.split("\0")
    index = 0
    while index < len(items):
        item = items[index]
        index += 1
        if not item:
            continue
        code = item[:2]
        path = item[3:]
        if code[0] in {"R", "C"} or code[1] in {"R", "C"}:
            if index >= len(items):
                raise PromotionError(f"malformed rename/copy status entry for {path}")
            new_path = items[index]
            index += 1
            paths.append((code, new_path))
        else:
            paths.append((code, path))
    return paths


def repo_has_local_change(repo: Path, relative_path: str) -> bool:
    proc = run_git(["status", "--porcelain=v1", "--", relative_path], repo)
    if proc.returncode != 0:
        raise PromotionError(f"could not inspect target repo status: {proc.stderr.strip()}")
    return bool(proc.stdout.strip())


def promote_successful_worktree(job: dict[str, Any]) -> dict[str, Any]:
    repo = Path(str(job["repo_path"]))
    worktree = Path(str(job["worktree_path"]))
    if not bool(job["use_worktree"]) or repo.resolve() == worktree.resolve():
        return {"promoted": False, "reason": "job already ran in the target repository", "files": []}

    changes = status_paths(worktree)
    changed_paths = sorted({path for _code, path in changes if path})
    if not changed_paths:
        return {"promoted": False, "reason": "job worktree had no changed files", "files": []}

    conflicting = [path for path in changed_paths if repo_has_local_change(repo, path)]
    if conflicting:
        preview = ", ".join(conflicting[:20])
        extra = "" if len(conflicting) <= 20 else f", ... and {len(conflicting) - 20} more"
        raise PromotionError(f"target repo has local changes in promoted paths: {preview}{extra}")

    copied: list[str] = []
    removed: list[str] = []
    for code, relative_path in changes:
        if relative_path is None:
            continue
        source = worktree / relative_path
        target = repo / relative_path
        if "D" in code and not source.exists():
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            removed.append(relative_path)
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

    return {
        "promoted": True,
        "reason": "copied successful worktree changes to target repository",
        "files": sorted(copied + removed),
        "copied": sorted(copied),
        "removed": sorted(removed),
    }


def create_next_task(settings, client, job: dict[str, Any], decision: dict[str, Any], created_by: str) -> str:
    next_task = decision["next_task"]
    task_id = timestamp_id("T")
    action = str(decision["action"])
    next_status = "fixing" if action == "REPAIR" else "queued"
    job_test_cmd = str(job["test_cmd"])
    proposed_test_cmd = str(next_task["test_cmd"])
    acceptance: list[str] = []
    replaced_test_acceptance = False
    for item in next_task["acceptance"]:
        text = str(item)
        lowered = text.lower()
        if proposed_test_cmd != job_test_cmd and (
            "test command" in lowered or "pytest" in lowered or "rc=5" in lowered or "no tests ran" in lowered
        ):
            if not replaced_test_acceptance:
                acceptance.append(f"The job test command passes: {job_test_cmd}")
                replaced_test_acceptance = True
            continue
        acceptance.append(text)
    if not replaced_test_acceptance and proposed_test_cmd != job_test_cmd:
        acceptance.append(f"The job test command passes: {job_test_cmd}")
    with db.transaction(settings.db_path) as conn:
        iteration = next_iteration(conn, job["id"])
        db.create_task(
            conn,
            task_id=task_id,
            job_id=job["id"],
            iteration=iteration,
            goal=str(next_task["goal"]),
            constraints=[str(item) for item in next_task["constraints"]],
            acceptance=acceptance,
            test_cmd=job_test_cmd,
            created_by=created_by,
        )
        db.update_job_status(conn, job["id"], next_status, decision["history_summary"])
        db.add_event(
            conn,
            job_id=job["id"],
            kind="task_queued",
            payload={
                "task_id": task_id,
                "iteration": iteration,
                "action": action,
                "status": next_status,
                "reason": decision["reason"],
                "goal": str(next_task["goal"]),
                "test_cmd": str(job["test_cmd"]),
            },
        )
    task_payload = {"task_id": task_id, "job_id": job["id"]}
    if scoped_job_id():
        task_payload["scope"] = "job"
    xadd_json(client, CODEX_TASK_STREAM, "task", task_payload)
    if next_status == "fixing":
        print(f"job {job['id']}: fixing - {decision['reason']}")
        print(f"job {job['id']}: fixing task {task_id} - {next_task['goal']}")
    else:
        print(f"queued Codex task {task_id} for job {job['id']}")
    return task_id


def finish_job(settings, client, job_id: str, stream: str, status: str, decision: dict[str, Any]) -> None:
    payload = terminal_payload(job_id, decision)
    with db.transaction(settings.db_path) as conn:
        db.update_job_status(conn, job_id, status, decision.get("history_summary", ""))
        db.add_event(conn, job_id=job_id, kind=status, payload=payload)
    xadd_json(client, stream, "event", payload)
    print(f"job {job_id}: {status} - {decision['reason']}")
    notify_terminal(settings, job_id, status, str(decision["reason"]))


def notify_terminal(settings, job_id: str, status: str, reason: str) -> None:
    with db.transaction(settings.db_path) as conn:
        job = db.get_job(conn, job_id)
    sent, detail = terminal_email(settings, job=job, status=status, reason=reason)
    with db.transaction(settings.db_path) as conn:
        db.add_event(
            conn,
            job_id=job_id,
            kind="email_notification_sent" if sent else "email_notification_failed",
            payload={"status": status, "recipient": settings.notify_email, "detail": detail},
        )
    print(f"job {job_id}: email notification {'sent' if sent else 'failed'} - {detail}")


def finish_done_job(settings, client, job: dict[str, Any], decision: dict[str, Any]) -> None:
    try:
        promotion = promote_successful_worktree(job)
    except PromotionError as exc:
        human_decision = {
            "action": "HUMAN_NEEDED",
            "reason": f"job completed, but promotion to target repository failed: {exc}",
            "history_summary": decision.get("history_summary", ""),
        }
        with db.transaction(settings.db_path) as conn:
            db.add_event(
                conn,
                job_id=job["id"],
                kind="promotion_failed",
                payload={"job_id": job["id"], "error": str(exc)},
            )
        finish_job(settings, client, job["id"], HUMAN_STREAM, "human_needed", human_decision)
        return

    done_payload = {
        **terminal_payload(job["id"], decision),
        "promotion": promotion,
    }
    with db.transaction(settings.db_path) as conn:
        db.update_job_status(conn, job["id"], "done", decision.get("history_summary", ""))
        db.add_event(conn, job_id=job["id"], kind="promotion_completed", payload=promotion)
        db.add_event(conn, job_id=job["id"], kind="done", payload=done_payload)
    xadd_json(client, DONE_STREAM, "event", done_payload)
    print(f"job {job['id']}: done - {decision['reason']}")
    notify_terminal(settings, str(job["id"]), "done", str(decision["reason"]))
    if promotion["promoted"]:
        print(f"job {job['id']}: promoted {len(promotion['files'])} changed files to {job['repo_path']}")


def handle_request(settings, client, request: dict[str, Any]) -> None:
    request_type = request["type"]
    job_id = request["job_id"]

    with db.transaction(settings.db_path) as conn:
        job = db.get_job(conn, job_id)
        task = db.get_task(conn, request["task_id"]) if request_type == "REVIEW" else None
        run = db.get_run(conn, request["run_id"]) if request_type == "REVIEW" else None

    print(f"Claude request: {request_type} job={job_id}")

    if request_type == "PLAN":
        decision = controller_decision(settings, job, plan_prompt(job))
        task_id = None
        run_id = None
    elif request_type == "REVIEW":
        if task is None or run is None:
            raise ValueError("REVIEW requires task_id and run_id")
        decision = controller_decision(settings, job, review_prompt(job, task, run))
        task_id = task["id"]
        run_id = run["id"]
    else:
        raise ValueError(f"unknown Claude request type: {request_type}")

    validate_decision(decision)

    with db.transaction(settings.db_path) as conn:
        db.create_decision(
            conn,
            decision_id=uuid.uuid4().hex[:12],
            job_id=job_id,
            task_id=task_id,
            run_id=run_id,
            request_type=request_type,
            action=decision["action"],
            reason=decision["reason"],
            history_summary=decision["history_summary"],
            decision=decision,
        )
        db.add_event(
            conn,
            job_id=job_id,
            kind="claude_decision",
            payload={"request_type": request_type, "action": decision["action"], "reason": decision["reason"]},
        )
        progress = decision["progress"]
        remaining_minutes = progress.get("remaining_minutes")
        db.update_job_estimate(
            conn,
            job_id,
            completed_units=int(progress["completed_work_units"]),
            remaining_units=int(progress["remaining_work_units"]),
            remaining_seconds=None if remaining_minutes is None else int(remaining_minutes) * 60,
        )

    action = decision["action"]
    if action in {"CONTINUE", "REPAIR"}:
        with db.transaction(settings.db_path) as conn:
            fresh_job = db.get_job(conn, job_id)
            if next_iteration(conn, job_id) >= int(fresh_job["max_iterations"]):
                human_decision = {
                    "action": "HUMAN_NEEDED",
                    "reason": "maximum iteration count reached",
                    "history_summary": decision["history_summary"],
                }
                finish_job(settings, client, job_id, HUMAN_STREAM, "human_needed", human_decision)
                return
        task_creator = "claude:repair" if action == "REPAIR" else f"claude:{request_type.lower()}"
        create_next_task(settings, client, fresh_job, decision, task_creator)
    elif action == "DONE":
        finish_done_job(settings, client, job, decision)
    elif action == "HUMAN_NEEDED":
        finish_job(settings, client, job_id, HUMAN_STREAM, "human_needed", decision)


def record_dead(settings, client, job_id: str | None, payload: dict[str, Any]) -> None:
    with db.transaction(settings.db_path) as conn:
        db.add_event(conn, job_id=job_id, kind="dead", payload=payload)
        if job_id:
            db.update_job_status(conn, job_id, "dead")
    xadd_json(client, DEAD_STREAM, "event", payload)
    if job_id:
        notify_terminal(settings, job_id, "dead", str(payload.get("error") or payload))


def main() -> int:
    settings = load_settings()
    db.init_db(settings.db_path)
    client = redis_client(settings.redis_url)
    job_scope = scoped_job_id()
    group = scoped_group(GROUP, job_scope)
    ensure_group(client, CLAUDE_REQUEST_STREAM, group, start_id="$" if job_scope else "0")
    consumer = consumer_name("claude")

    print("AI loop controller started")
    print(f"db: {settings.db_path}")
    print(f"redis: {settings.redis_url}")
    if job_scope:
        print(f"job_scope: {job_scope}")
    print(f"listening: {CLAUDE_REQUEST_STREAM} group={group} consumer={consumer}")

    while True:
        try:
            messages = read_group(client, group, consumer, CLAUDE_REQUEST_STREAM)
        except (TimeoutError, ConnectionError) as exc:
            print(f"Redis read problem, retrying: {exc}")
            time.sleep(1)
            continue

        if not messages:
            if job_scope and is_terminal_job(settings, job_scope):
                print(f"job {job_scope}: terminal; Claude controller exiting")
                return 0
            continue

        _, entries = messages[0]
        for message_id, fields in entries:
            job_id = None
            try:
                request = decode(fields["request"])
                job_id = request.get("job_id")
                if not job_scope and request.get("scope") == "job":
                    client.xack(CLAUDE_REQUEST_STREAM, group, message_id)
                    continue
                if job_scope and job_id != job_scope:
                    client.xack(CLAUDE_REQUEST_STREAM, group, message_id)
                    continue
                handle_request(settings, client, request)
                client.xack(CLAUDE_REQUEST_STREAM, group, message_id)
                if job_scope and is_terminal_job(settings, job_scope):
                    print(f"job {job_scope}: terminal; Claude controller exiting")
                    return 0
            except Exception as exc:
                print(f"controller error: {exc}")
                if attempt_auto_recovery(settings, job_id, "controller", repr(exc), fields):
                    client.xack(CLAUDE_REQUEST_STREAM, group, message_id)
                    print(f"job {job_id}: auto recovery launched; Claude controller exiting")
                    return 0
                payload = {"where": "controller", "error": repr(exc), "fields": fields}
                try:
                    record_dead(settings, client, job_id, payload)
                    client.xack(CLAUDE_REQUEST_STREAM, group, message_id)
                except Exception as inner:
                    print(f"could not record dead event: {inner}")


if __name__ == "__main__":
    raise SystemExit(main())
