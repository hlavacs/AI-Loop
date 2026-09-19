"""Concise, human-readable summaries for the main job views."""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

_PREFERRED_TEXT_KEYS = (
    "summary",
    "description",
    "goal",
    "title",
    "message",
    "reason",
    "text",
    "name",
)


def _structured_value(value: str) -> Any:
    """Decode model-produced JSON/Python containers without executing code."""

    stripped = value.strip()
    if not stripped.startswith(("{", "[", "(")):
        return value
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(stripped)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, (Mapping, list, tuple)):
            return parsed
    return value


def human_text(value: Any, *, fallback: str = "", limit: int = 420) -> str:
    """Turn loose controller data into one short piece of readable prose."""

    if value is None:
        return fallback
    if isinstance(value, str):
        parsed = _structured_value(value)
        if parsed is not value:
            return human_text(parsed, fallback=fallback, limit=limit)
        text = re.sub(r"\s+", " ", value).strip()
    elif isinstance(value, Mapping):
        preferred = [value[key] for key in _PREFERRED_TEXT_KEYS if value.get(key)]
        candidates = preferred or [item for item in value.values() if item]
        parts = [human_text(item, limit=limit) for item in candidates[:2]]
        text = "; ".join(part for part in parts if part)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        parts = [human_text(item, limit=limit) for item in value[:2]]
        text = "; ".join(part for part in parts if part)
    else:
        text = str(value).strip()

    if not text:
        return fallback
    if len(text) <= limit:
        return text
    shortened = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return (shortened or text[: limit - 1]).rstrip() + "…"


def _human_items(value: Any, *, maximum: int = 2, item_limit: int = 220) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result: list[str] = []
    for item in value:
        text = human_text(item, limit=item_limit)
        if text and text not in result:
            result.append(text)
        if len(result) == maximum:
            break
    return result


def task_summary(
    details: Mapping[str, Any],
    task: Mapping[str, Any] | None,
) -> str:
    """Describe the current task without exposing orchestration internals."""

    job_data = details.get("job")
    job: Mapping[str, Any] = job_data if isinstance(job_data, Mapping) else {}
    job_status = str(job.get("status") or "unknown")
    if task is None:
        messages = {
            "planning": "The controller is preparing the next task. No worker action is active yet.",
            "done": "The job is complete, so there is no active task.",
            "human_needed": "Work is paused because the job needs human input before another task can start.",
            "dead": "The job has stopped after a failure, so there is no active task.",
            "waiting_tokens": "Work is paused while model capacity replenishes. It should resume automatically.",
        }
        return "Task summary\n\n" + messages.get(
            job_status,
            "There is no active worker task. The controller may be preparing the next step.",
        )

    task_status = str(task.get("status") or "unknown")
    state_text = {
        "queued": "This task is ready and waiting for the worker to begin.",
        "running": "The worker is carrying out this task now.",
        "waiting_tokens": "This task is paused until model capacity replenishes, then it should resume automatically.",
        "completed": "The worker has finished this task and returned its result for review.",
        "failed": "This task stopped with a failure and is waiting for review or repair.",
    }.get(task_status, "The task is currently being managed by the loop.")
    goal = human_text(task.get("goal"), fallback="No clear task description was recorded.", limit=520)
    paragraphs = ["Task summary", "", f"{state_text} Its goal is to {goal.rstrip('.')}."]

    acceptance = _human_items(task.get("acceptance"))
    if acceptance:
        outcome = "; and ".join(item.rstrip(".") for item in acceptance)
        paragraphs.extend(["", f"The main signs of completion are that {outcome}."])

    constraints = task.get("constraints")
    if isinstance(constraints, Sequence) and not isinstance(constraints, (str, bytes, bytearray)):
        extra = len(constraints)
        if extra:
            noun = "instruction" if extra == 1 else "instructions"
            paragraphs.extend(["", f"The worker also has {extra} recorded {noun} to follow."])

    matching_run = next(
        (
            run
            for run in details.get("runs", [])
            if isinstance(run, Mapping) and run.get("task_id") == task.get("id")
        ),
        None,
    )
    if matching_run:
        test_rc = matching_run.get("test_rc")
        if test_rc == 0:
            result = "The latest validation passed."
        elif test_rc is None:
            result = "No validation result has been recorded yet."
        else:
            result = "The latest validation failed and needs attention."
        changed = matching_run.get("changed_files")
        if isinstance(changed, Sequence) and not isinstance(changed, (str, bytes, bytearray)) and changed:
            count = len(changed)
            result += f" The task changed {count} {'file' if count == 1 else 'files'}."
        error = human_text(matching_run.get("error"), limit=240)
        if error:
            result += f" The reported problem is: {error}"
        paragraphs.extend(["", result])

    return "\n".join(paragraphs)


def status_summary(
    details: Mapping[str, Any],
    task: Mapping[str, Any] | None,
    blockers: Sequence[tuple[str, str]],
    *,
    remaining_text: str,
) -> str:
    """Describe job health and the next user action in compact prose."""

    job_data = details.get("job")
    job: Mapping[str, Any] = job_data if isinstance(job_data, Mapping) else {}
    status = str(job.get("status") or "unknown")
    state_text = {
        "planning": "The controller is deciding what should happen next.",
        "queued": "The next task is ready and waiting for the worker.",
        "implementing": "The worker is making the requested changes.",
        "fixing": "The loop is diagnosing or repairing a failed result.",
        "waiting_tokens": "Work is temporarily paused until model capacity replenishes.",
        "human_needed": "Automation is paused because a person needs to intervene.",
        "dead": "The loop stopped after a failure.",
        "done": "The controller has confirmed that the job is complete.",
    }.get(status, "The loop is processing the job.")

    percent = details.get("percent")
    progress = ""
    if isinstance(percent, (int, float)):
        progress = f" Progress is estimated at {round(percent)}%."
        if status not in {"done", "human_needed", "dead"} and remaining_text:
            progress += f" The estimated time remaining is {remaining_text}."

    paragraphs = ["Status summary", "", state_text + progress]
    if task is not None and status not in {"done", "human_needed", "dead"}:
        goal = human_text(task.get("goal"), limit=300)
        if goal:
            paragraphs.extend(["", f"The current focus is to {goal.rstrip('.')}."])

    if blockers:
        problem, solution = blockers[0]
        problem_text = human_text(problem, fallback="The job cannot continue automatically.", limit=320)
        solution_text = human_text(solution, fallback="Review the job and resume it when the issue is resolved.", limit=320)
        paragraphs.extend(
            [
                "",
                f"Attention is needed: {problem_text}",
                "",
                f"Suggested next step: {solution_text}",
            ]
        )
        if len(blockers) > 1:
            paragraphs.extend(["", f"There are {len(blockers) - 1} additional warnings in the Details and Logs tabs."])
    elif status == "done":
        paragraphs.extend(["", "No further action is needed."])
    else:
        paragraphs.extend(["", "No action is needed right now; the loop can continue automatically."])

    return "\n".join(paragraphs)
