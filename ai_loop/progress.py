"""Progress and ETA estimates for AI loop jobs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


SMOOTHING_ALPHA = 0.35


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def ensure_progress_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS progress_estimates (
            job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
            last_percent INTEGER NOT NULL,
            last_progress_at TEXT NOT NULL,
            smoothed_rate REAL,
            predicted_end_at TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )


def heuristic_percent(
    *,
    status: str,
    run_count: int,
    task_count: int,
    has_active_task: bool,
) -> int:
    if status == "done":
        return 100

    active_credit = 0.5 if has_active_task and task_count > run_count else 0.0
    work_units = run_count + active_credit
    percent = max(1, min(99, round(100 * work_units / (work_units + 25))))
    if run_count >= 5:
        percent = max(percent, 20)
    if run_count >= 20:
        percent = max(percent, 45)
    if run_count >= 75:
        percent = max(percent, 65)
    if run_count >= 150:
        percent = max(percent, 75)
    return percent


def estimate_progress(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    status: str,
    created_at: str | None,
    run_count: int,
    task_count: int,
    has_active_task: bool,
) -> tuple[int, int | None]:
    ensure_progress_table(conn)
    now = utc_now()
    estimate_row = conn.execute(
        """
        SELECT estimated_completed_units, estimated_remaining_units,
               estimated_remaining_seconds
        FROM jobs WHERE id = ?
        """,
        (job_id,),
    ).fetchone()
    completed_units = int(estimate_row["estimated_completed_units"] or 0) if estimate_row else 0
    remaining_units = int(estimate_row["estimated_remaining_units"] or 0) if estimate_row else 0
    explicit_remaining = estimate_row["estimated_remaining_seconds"] if estimate_row else None
    if completed_units + remaining_units > 0:
        percent = round(100 * completed_units / (completed_units + remaining_units))
        percent = max(1, min(99, percent))
    else:
        percent = heuristic_percent(
            status=status,
            run_count=run_count,
            task_count=task_count,
            has_active_task=has_active_task,
        )

    if status == "done":
        conn.execute(
            """
            INSERT INTO progress_estimates (
                job_id, last_percent, last_progress_at, smoothed_rate,
                predicted_end_at, updated_at
            )
            VALUES (?, 100, ?, NULL, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                last_percent = 100,
                last_progress_at = excluded.last_progress_at,
                smoothed_rate = NULL,
                predicted_end_at = excluded.predicted_end_at,
                updated_at = excluded.updated_at
            """,
            (job_id, format_time(now), format_time(now), format_time(now)),
        )
        return 100, 0

    row = conn.execute(
        """
        SELECT last_percent, last_progress_at, smoothed_rate, predicted_end_at
        FROM progress_estimates
        WHERE job_id = ?
        """,
        (job_id,),
    ).fetchone()

    if explicit_remaining is not None:
        if row is not None and int(row["last_percent"]) == percent and row["predicted_end_at"]:
            predicted = parse_time(row["predicted_end_at"])
            if predicted is not None:
                return percent, max(0, round((predicted - now).total_seconds()))
        remaining = max(0, int(explicit_remaining))
        predicted = datetime.fromtimestamp(now.timestamp() + remaining, timezone.utc)
        conn.execute(
            """
            INSERT INTO progress_estimates (
                job_id, last_percent, last_progress_at, smoothed_rate,
                predicted_end_at, updated_at
            )
            VALUES (?, ?, ?, NULL, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                last_percent = excluded.last_percent,
                last_progress_at = excluded.last_progress_at,
                predicted_end_at = excluded.predicted_end_at,
                updated_at = excluded.updated_at
            """,
            (job_id, percent, format_time(now), format_time(predicted), format_time(now)),
        )
        return percent, remaining

    if row is None:
        start = parse_time(created_at) or now
        conn.execute(
            """
            INSERT INTO progress_estimates (
                job_id, last_percent, last_progress_at, smoothed_rate,
                predicted_end_at, updated_at
            )
            VALUES (?, 0, ?, NULL, NULL, ?)
            """,
            (job_id, format_time(start), format_time(now)),
        )
        row = {
            "last_percent": 0,
            "last_progress_at": format_time(start),
            "smoothed_rate": None,
            "predicted_end_at": None,
        }

    last_percent = int(row["last_percent"])
    last_progress_at = parse_time(row["last_progress_at"]) or now
    smoothed_rate = row["smoothed_rate"]
    smoothed_rate = float(smoothed_rate) if smoothed_rate is not None else None
    predicted_end_at = parse_time(row["predicted_end_at"])

    display_percent = max(percent, last_percent)
    if percent > last_percent:
        elapsed = max(1.0, (now - last_progress_at).total_seconds())
        measured_rate = (percent - last_percent) / elapsed
        if smoothed_rate is None:
            smoothed_rate = measured_rate
        else:
            smoothed_rate = (SMOOTHING_ALPHA * measured_rate) + ((1.0 - SMOOTHING_ALPHA) * smoothed_rate)

        remaining = round((100 - percent) / smoothed_rate) if smoothed_rate > 0 else None
        predicted_end_at = None if remaining is None else datetime.fromtimestamp(now.timestamp() + remaining, timezone.utc)
        conn.execute(
            """
            UPDATE progress_estimates
            SET last_percent = ?,
                last_progress_at = ?,
                smoothed_rate = ?,
                predicted_end_at = ?,
                updated_at = ?
            WHERE job_id = ?
            """,
            (
                percent,
                format_time(now),
                smoothed_rate,
                format_time(predicted_end_at) if predicted_end_at else None,
                format_time(now),
                job_id,
            ),
        )
        return percent, remaining

    conn.execute(
        "UPDATE progress_estimates SET updated_at = ? WHERE job_id = ?",
        (format_time(now), job_id),
    )
    if predicted_end_at is None:
        return display_percent, None
    remaining = round((predicted_end_at - now).total_seconds())
    return display_percent, remaining
