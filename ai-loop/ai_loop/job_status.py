"""Derive user-facing job activity from task execution state."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


ACTIVE_TASK_STATUSES = {"queued", "running", "waiting_tokens"}


def active_job_status(tasks: Iterable[Mapping[str, Any]]) -> str | None:
    """Return the status that best describes work happening right now.

    A repair task keeps its provenance in ``created_by``, but once a worker is
    executing it the user-visible activity is implementation.  Running work
    also takes precedence over a newer queued task so that queueing the next
    repair cannot hide productive work already in progress.
    """

    active = [task for task in tasks if str(task.get("status")) in ACTIVE_TASK_STATUSES]
    if any(str(task.get("status")) == "running" for task in active):
        return "implementing"
    if any(str(task.get("status")) == "waiting_tokens" for task in active):
        return "waiting_tokens"
    if active:
        newest = max(active, key=lambda task: int(task.get("iteration") or -1))
        return "fixing" if str(newest.get("created_by")) == "claude:repair" else "queued"
    return None


def current_active_task(tasks: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """Choose the task that represents current work, preferring execution."""

    active = [task for task in tasks if str(task.get("status")) in ACTIVE_TASK_STATUSES]
    for status in ("running", "waiting_tokens", "queued"):
        matching = [task for task in active if str(task.get("status")) == status]
        if matching:
            return max(matching, key=lambda task: int(task.get("iteration") or -1))
    return None
