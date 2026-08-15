"""SQLite persistence for jobs, tasks, runs, decisions, and events."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_json(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True)


def from_json(value: str | None, default: JsonValue = None) -> JsonValue:
    if value is None or value == "":
        return default
    return json.loads(value)


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def transaction(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | Path) -> None:
    with transaction(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                repo_path TEXT NOT NULL,
                worktree_path TEXT NOT NULL,
                branch TEXT,
                base_ref TEXT NOT NULL,
                goal TEXT NOT NULL,
                constraints_json TEXT NOT NULL,
                acceptance_json TEXT NOT NULL,
                test_cmd TEXT NOT NULL,
                max_iterations INTEGER NOT NULL,
                use_worktree INTEGER NOT NULL,
                worker TEXT NOT NULL DEFAULT 'codex',
                controller TEXT NOT NULL DEFAULT 'claude',
                granularity TEXT NOT NULL DEFAULT 'normal',
                plan_json TEXT NOT NULL DEFAULT '[]',
                finish_requested INTEGER NOT NULL DEFAULT 0,
                estimated_completed_units INTEGER NOT NULL DEFAULT 0,
                estimated_remaining_units INTEGER NOT NULL DEFAULT 0,
                estimated_remaining_seconds INTEGER,
                waiting_until TEXT,
                email_token TEXT,
                status TEXT NOT NULL,
                history_summary TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                iteration INTEGER NOT NULL,
                goal TEXT NOT NULL,
                constraints_json TEXT NOT NULL,
                acceptance_json TEXT NOT NULL,
                test_cmd TEXT NOT NULL,
                status TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                iteration INTEGER NOT NULL,
                codex_rc INTEGER,
                codex_output TEXT NOT NULL,
                test_rc INTEGER,
                test_output TEXT NOT NULL,
                git_status TEXT NOT NULL,
                diff_stat TEXT NOT NULL,
                diff TEXT NOT NULL,
                changed_files_json TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
                request_type TEXT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT NOT NULL,
                history_summary TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS progress_estimates (
                job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                last_percent INTEGER NOT NULL,
                last_progress_at TEXT NOT NULL,
                smoothed_rate REAL,
                predicted_end_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_job_iteration ON tasks(job_id, iteration);
            CREATE INDEX IF NOT EXISTS idx_runs_job_iteration ON runs(job_id, iteration);
            CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, created_at);
            """
        )
        ensure_column(conn, "jobs", "worker", "worker TEXT NOT NULL DEFAULT 'codex'")
        ensure_column(conn, "jobs", "controller", "controller TEXT NOT NULL DEFAULT 'claude'")
        ensure_column(conn, "jobs", "granularity", "granularity TEXT NOT NULL DEFAULT 'normal'")
        ensure_column(conn, "jobs", "plan_json", "plan_json TEXT NOT NULL DEFAULT '[]'")
        ensure_column(conn, "jobs", "finish_requested", "finish_requested INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "jobs", "estimated_completed_units", "estimated_completed_units INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "jobs", "estimated_remaining_units", "estimated_remaining_units INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "jobs", "estimated_remaining_seconds", "estimated_remaining_seconds INTEGER")
        ensure_column(conn, "jobs", "waiting_until", "waiting_until TEXT")
        ensure_column(conn, "jobs", "email_token", "email_token TEXT")


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["constraints"] = from_json(data.pop("constraints_json"), [])
    data["acceptance"] = from_json(data.pop("acceptance_json"), [])
    data["plan"] = from_json(data.pop("plan_json"), [])
    data["use_worktree"] = bool(data["use_worktree"])
    data["finish_requested"] = bool(data["finish_requested"])
    return data


def row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["constraints"] = from_json(data.pop("constraints_json"), [])
    data["acceptance"] = from_json(data.pop("acceptance_json"), [])
    return data


def row_to_run(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["changed_files"] = from_json(data.pop("changed_files_json"), [])
    return data


def create_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    repo_path: str,
    worktree_path: str,
    branch: str | None,
    base_ref: str,
    goal: str,
    constraints: list[str],
    acceptance: list[str],
    test_cmd: str,
    max_iterations: int,
    use_worktree: bool,
    worker: str = "codex",
    controller: str = "claude",
    granularity: str = "normal",
    plan: list[str] | None = None,
    email_token: str | None = None,
) -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO jobs (
            id, repo_path, worktree_path, branch, base_ref, goal, constraints_json,
            acceptance_json, test_cmd, max_iterations, use_worktree, worker,
            controller, granularity, plan_json, estimated_remaining_units,
            email_token, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planning', ?, ?)
        """,
        (
            job_id,
            repo_path,
            worktree_path,
            branch,
            base_ref,
            goal,
            to_json(constraints),
            to_json(acceptance),
            test_cmd,
            max_iterations,
            1 if use_worktree else 0,
            worker,
            controller,
            granularity,
            to_json(plan or []),
            len(plan or []),
            email_token,
            now,
            now,
        ),
    )
    conn.execute("DELETE FROM progress_estimates WHERE job_id = ?", (job_id,))


def update_job_estimate(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    completed_units: int,
    remaining_units: int,
    remaining_seconds: int | None,
) -> None:
    current = conn.execute(
        "SELECT estimated_completed_units FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    if current is not None:
        completed_units = max(completed_units, int(current["estimated_completed_units"] or 0))
    conn.execute(
        """
        UPDATE jobs
        SET estimated_completed_units = ?, estimated_remaining_units = ?,
            estimated_remaining_seconds = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            max(0, completed_units),
            max(0, remaining_units),
            None if remaining_seconds is None else max(0, remaining_seconds),
            utc_now(),
            job_id,
        ),
    )
    conn.execute("DELETE FROM progress_estimates WHERE job_id = ?", (job_id,))


def set_waiting_for_tokens(
    conn: sqlite3.Connection,
    job_id: str,
    waiting_until: str | None,
    *,
    task_id: str | None = None,
    resume_status: str | None = None,
) -> None:
    status = "waiting_tokens" if waiting_until else (resume_status or "planning")
    conn.execute(
        "UPDATE jobs SET status = ?, waiting_until = ?, updated_at = ? WHERE id = ?",
        (status, waiting_until, utc_now(), job_id),
    )
    if task_id is not None:
        conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            ("waiting_tokens" if waiting_until else "running", utc_now(), task_id),
        )


def get_job(conn: sqlite3.Connection, job_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise KeyError(f"Unknown job: {job_id}")
    return row_to_job(row)


def update_job_status(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    history_summary: str | None = None,
) -> None:
    if history_summary is None:
        conn.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, utc_now(), job_id),
        )
    else:
        conn.execute(
            "UPDATE jobs SET status = ?, history_summary = ?, updated_at = ? WHERE id = ?",
            (status, history_summary, utc_now(), job_id),
        )


def create_task(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    job_id: str,
    iteration: int,
    goal: str,
    constraints: list[str],
    acceptance: list[str],
    test_cmd: str,
    created_by: str,
) -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO tasks (
            id, job_id, iteration, goal, constraints_json, acceptance_json,
            test_cmd, status, created_by, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
        """,
        (
            task_id,
            job_id,
            iteration,
            goal,
            to_json(constraints),
            to_json(acceptance),
            test_cmd,
            created_by,
            now,
            now,
        ),
    )


def get_task(conn: sqlite3.Connection, task_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise KeyError(f"Unknown task: {task_id}")
    return row_to_task(row)


def update_task_status(conn: sqlite3.Connection, task_id: str, status: str) -> None:
    conn.execute(
        "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
        (status, utc_now(), task_id),
    )


def latest_task(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM tasks WHERE job_id = ? ORDER BY iteration DESC, created_at DESC LIMIT 1",
        (job_id,),
    ).fetchone()
    return row_to_task(row) if row else None


def create_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    task_id: str,
    job_id: str,
    iteration: int,
    codex_rc: int | None,
    codex_output: str,
    test_rc: int | None,
    test_output: str,
    git_status: str,
    diff_stat: str,
    diff: str,
    changed_files: list[str],
    status: str,
    error: str | None,
    started_at: str,
    finished_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO runs (
            id, task_id, job_id, iteration, codex_rc, codex_output, test_rc,
            test_output, git_status, diff_stat, diff, changed_files_json,
            status, error, started_at, finished_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            task_id,
            job_id,
            iteration,
            codex_rc,
            codex_output,
            test_rc,
            test_output,
            git_status,
            diff_stat,
            diff,
            to_json(changed_files),
            status,
            error,
            started_at,
            finished_at,
        ),
    )


def get_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(f"Unknown run: {run_id}")
    return row_to_run(row)


def latest_run(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM runs WHERE job_id = ? ORDER BY iteration DESC, finished_at DESC LIMIT 1",
        (job_id,),
    ).fetchone()
    return row_to_run(row) if row else None


def create_decision(
    conn: sqlite3.Connection,
    *,
    decision_id: str,
    job_id: str,
    task_id: str | None,
    run_id: str | None,
    request_type: str,
    action: str,
    reason: str,
    history_summary: str,
    decision: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO decisions (
            id, job_id, task_id, run_id, request_type, action, reason,
            history_summary, decision_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision_id,
            job_id,
            task_id,
            run_id,
            request_type,
            action,
            reason,
            history_summary,
            to_json(decision),
            utc_now(),
        ),
    )


def add_event(
    conn: sqlite3.Connection,
    *,
    job_id: str | None,
    kind: str,
    payload: dict[str, Any],
) -> None:
    conn.execute(
        "INSERT INTO events (job_id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
        (job_id, kind, to_json(payload), utc_now()),
    )
