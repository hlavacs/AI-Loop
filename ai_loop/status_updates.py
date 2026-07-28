"""Durable periodic status-email scheduling for active jobs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ai_loop import db
from ai_loop.notifications import status_email
from ai_loop.progress import estimate_progress


ACTIVE_STATUSES = {"planning", "queued", "implementing", "fixing", "waiting_tokens"}
STATUS_EMAIL_INTERVAL = timedelta(hours=12)


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def maybe_send_status_email(
    settings: Any,
    job_id: str,
    *,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(timezone.utc)
    with db.transaction(settings.db_path) as conn:
        job = db.get_job(conn, job_id)
        if str(job["status"]) not in ACTIVE_STATUSES:
            return False

        last_attempt = conn.execute(
            """
            SELECT created_at
            FROM events
            WHERE job_id = ? AND kind IN ('email_status_sent', 'email_status_failed')
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
        schedule_from = (
            str(last_attempt["created_at"])
            if last_attempt is not None
            else str(job["created_at"])
        )
        if now - parse_timestamp(schedule_from) < STATUS_EMAIL_INTERVAL:
            return False

        task_count = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM tasks WHERE job_id = ?",
                (job_id,),
            ).fetchone()["count"]
        )
        run_count = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM runs WHERE job_id = ?",
                (job_id,),
            ).fetchone()["count"]
        )
        current_task = db.latest_task(conn, job_id)
        has_active_task = current_task is not None and str(current_task["status"]) in {
            "queued",
            "running",
            "waiting_tokens",
        }
        percent, remaining_seconds = estimate_progress(
            conn,
            job_id=job_id,
            status=str(job["status"]),
            created_at=str(job["created_at"]),
            run_count=run_count,
            task_count=task_count,
            has_active_task=has_active_task,
        )

    sent, detail = status_email(
        settings,
        job=job,
        percent=percent,
        task_count=task_count,
        run_count=run_count,
        current_task=str(current_task["goal"]) if current_task else "",
        remaining_seconds=remaining_seconds,
    )
    with db.transaction(settings.db_path) as conn:
        db.add_event(
            conn,
            job_id=job_id,
            kind="email_status_sent" if sent else "email_status_failed",
            payload={
                "status": job["status"],
                "recipient": settings.notify_email,
                "detail": detail,
                "percent": percent,
                "task_count": task_count,
                "run_count": run_count,
            },
        )
    print(
        f"job {job_id}: 12-hour status email "
        f"{'sent' if sent else 'failed'} - {detail}"
    )
    return True
