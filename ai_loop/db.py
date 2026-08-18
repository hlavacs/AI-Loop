"""SQLite persistence for jobs, tasks, runs, decisions, and events."""

from __future__ import annotations

import hashlib
import json
import secrets
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
                models_json TEXT,
                specification_id TEXT,
                specification_version INTEGER,
                specification_content_hash TEXT,
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
                requirement_ids_json TEXT NOT NULL DEFAULT '[]',
                verification_ids_json TEXT NOT NULL DEFAULT '[]',
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

            CREATE TABLE IF NOT EXISTS specifications (
                id TEXT PRIMARY KEY,
                repository_path TEXT NOT NULL,
                status TEXT NOT NULL,
                current_version INTEGER NOT NULL,
                title TEXT NOT NULL,
                approved_version INTEGER,
                approved_at TEXT,
                approved_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS specification_versions (
                specification_id TEXT NOT NULL REFERENCES specifications(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                schema_version TEXT NOT NULL,
                canonical_json TEXT NOT NULL,
                canonical_content_hash TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                artifact_hash TEXT NOT NULL,
                change_summary TEXT NOT NULL,
                creator TEXT NOT NULL,
                created_at TEXT NOT NULL,
                approved_at TEXT,
                approved_by TEXT,
                PRIMARY KEY (specification_id, version)
            );

            CREATE TABLE IF NOT EXISTS specification_decisions (
                id TEXT PRIMARY KEY,
                specification_id TEXT NOT NULL REFERENCES specifications(id) ON DELETE CASCADE,
                source_version INTEGER NOT NULL,
                topic TEXT NOT NULL,
                question TEXT NOT NULL,
                context TEXT NOT NULL,
                options_json TEXT NOT NULL,
                recommendation TEXT,
                blocking INTEGER NOT NULL,
                status TEXT NOT NULL,
                selected_option TEXT,
                rationale TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (specification_id, source_version)
                    REFERENCES specification_versions(specification_id, version)
            );

            CREATE TABLE IF NOT EXISTS specification_analyses (
                id TEXT PRIMARY KEY,
                specification_id TEXT NOT NULL REFERENCES specifications(id) ON DELETE CASCADE,
                source_version INTEGER NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL,
                prompt_hash TEXT NOT NULL,
                validated_result_json TEXT,
                artifact_path TEXT,
                artifact_hash TEXT,
                error TEXT,
                application_metadata_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (specification_id, source_version)
                    REFERENCES specification_versions(specification_id, version)
            );

            CREATE TABLE IF NOT EXISTS verification_manifests (
                job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                manifest_schema_version TEXT NOT NULL,
                specification_id TEXT NOT NULL,
                specification_version INTEGER NOT NULL,
                specification_content_hash TEXT NOT NULL,
                canonical_json TEXT NOT NULL,
                canonical_content_hash TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                artifact_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (specification_id, specification_version)
                    REFERENCES specification_versions(specification_id, version)
            );

            CREATE TABLE IF NOT EXISTS verification_manifest_revisions (
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                revision INTEGER NOT NULL,
                manifest_schema_version TEXT NOT NULL,
                specification_id TEXT NOT NULL,
                specification_version INTEGER NOT NULL,
                specification_content_hash TEXT NOT NULL,
                canonical_json TEXT NOT NULL,
                canonical_content_hash TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                artifact_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (job_id, revision),
                UNIQUE (job_id, specification_id, specification_version),
                FOREIGN KEY (specification_id, specification_version)
                    REFERENCES specification_versions(specification_id, version)
            );

            CREATE TABLE IF NOT EXISTS specification_change_impacts (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                previous_specification_id TEXT NOT NULL,
                previous_specification_version INTEGER NOT NULL,
                previous_specification_hash TEXT NOT NULL,
                new_specification_id TEXT NOT NULL,
                new_specification_version INTEGER NOT NULL,
                new_specification_hash TEXT NOT NULL,
                manifest_revision INTEGER NOT NULL,
                canonical_json TEXT NOT NULL,
                canonical_content_hash TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                artifact_hash TEXT NOT NULL,
                task_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (job_id, new_specification_id, new_specification_version),
                FOREIGN KEY (job_id, manifest_revision)
                    REFERENCES verification_manifest_revisions(job_id, revision)
            );

            CREATE TABLE IF NOT EXISTS job_verification_states (
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                verification_id TEXT NOT NULL,
                automation TEXT NOT NULL,
                blocking INTEGER NOT NULL,
                status TEXT NOT NULL,
                attempts_completed INTEGER NOT NULL DEFAULT 0,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                stagnation_count INTEGER NOT NULL DEFAULT 0,
                stagnation_series INTEGER NOT NULL DEFAULT 0,
                failure_fingerprint TEXT,
                latest_metrics_json TEXT,
                metric_trend TEXT,
                last_error TEXT,
                last_task_id TEXT,
                last_worker_run_id TEXT,
                finished_at TEXT,
                escalation_report_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (job_id, verification_id)
            );

            CREATE TABLE IF NOT EXISTS verification_repetitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                worker_run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
                verification_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                repetition INTEGER NOT NULL,
                command TEXT NOT NULL,
                working_directory TEXT NOT NULL,
                timeout_seconds INTEGER NOT NULL,
                status TEXT NOT NULL,
                return_code INTEGER,
                output TEXT NOT NULL,
                output_truncated INTEGER NOT NULL,
                metrics_json TEXT,
                assertion_results_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL DEFAULT '[]',
                coverage_results_json TEXT NOT NULL DEFAULT '[]',
                execution_proof_json TEXT NOT NULL DEFAULT '{}',
                elapsed_seconds REAL NOT NULL,
                timed_out INTEGER NOT NULL,
                error TEXT,
                termination_details TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                UNIQUE (job_id, verification_id, attempt, repetition)
            );

            CREATE TABLE IF NOT EXISTS verification_correction_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                worker_run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
                verification_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                status TEXT NOT NULL,
                failure_fingerprint TEXT,
                failure_identity_json TEXT,
                metric_values_json TEXT NOT NULL,
                metric_trend TEXT NOT NULL,
                consecutive_failures INTEGER NOT NULL,
                stagnation_count INTEGER NOT NULL,
                stagnation_series INTEGER NOT NULL,
                meaningful_change INTEGER NOT NULL,
                failed_assertions_json TEXT NOT NULL,
                observed_error TEXT,
                output_tail TEXT NOT NULL,
                evidence_paths_json TEXT NOT NULL,
                repair_goal TEXT NOT NULL,
                escalation_report_json TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (job_id, verification_id, attempt)
            );

            CREATE TABLE IF NOT EXISTS verification_manual_acknowledgements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                verification_id TEXT NOT NULL,
                acknowledged_by TEXT NOT NULL,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_job_iteration ON tasks(job_id, iteration);
            CREATE INDEX IF NOT EXISTS idx_runs_job_iteration ON runs(job_id, iteration);
            CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_specifications_repository
                ON specifications(repository_path, updated_at);
            CREATE INDEX IF NOT EXISTS idx_specification_decisions_source
                ON specification_decisions(specification_id, source_version, status);
            CREATE INDEX IF NOT EXISTS idx_specification_analyses_source
                ON specification_analyses(specification_id, source_version, created_at);
            CREATE INDEX IF NOT EXISTS idx_verification_manifests_specification
                ON verification_manifests(specification_id, specification_version);
            CREATE INDEX IF NOT EXISTS idx_verification_manifest_revisions_specification
                ON verification_manifest_revisions(specification_id, specification_version);
            CREATE INDEX IF NOT EXISTS idx_specification_change_impacts_job
                ON specification_change_impacts(job_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_verification_repetitions_task
                ON verification_repetitions(job_id, task_id, verification_id, attempt);
            CREATE INDEX IF NOT EXISTS idx_verification_corrections_case
                ON verification_correction_attempts(job_id, verification_id, attempt);
            CREATE INDEX IF NOT EXISTS idx_verification_manual_acknowledgements_case
                ON verification_manual_acknowledgements(job_id, verification_id, created_at);

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
        ensure_column(conn, "jobs", "models_json", "models_json TEXT")
        ensure_column(conn, "jobs", "specification_id", "specification_id TEXT")
        ensure_column(conn, "jobs", "specification_version", "specification_version INTEGER")
        ensure_column(conn, "jobs", "specification_content_hash", "specification_content_hash TEXT")
        ensure_column(
            conn,
            "tasks",
            "requirement_ids_json",
            "requirement_ids_json TEXT NOT NULL DEFAULT '[]'",
        )
        ensure_column(
            conn,
            "tasks",
            "verification_ids_json",
            "verification_ids_json TEXT NOT NULL DEFAULT '[]'",
        )
        ensure_column(
            conn,
            "verification_repetitions",
            "evidence_json",
            "evidence_json TEXT NOT NULL DEFAULT '[]'",
        )
        ensure_column(
            conn,
            "verification_repetitions",
            "coverage_results_json",
            "coverage_results_json TEXT NOT NULL DEFAULT '[]'",
        )
        ensure_column(
            conn,
            "verification_repetitions",
            "execution_proof_json",
            "execution_proof_json TEXT NOT NULL DEFAULT '{}'",
        )
        ensure_column(
            conn,
            "job_verification_states",
            "attempts_completed",
            "attempts_completed INTEGER NOT NULL DEFAULT 0",
        )
        ensure_column(
            conn,
            "job_verification_states",
            "consecutive_failures",
            "consecutive_failures INTEGER NOT NULL DEFAULT 0",
        )
        ensure_column(
            conn,
            "job_verification_states",
            "stagnation_count",
            "stagnation_count INTEGER NOT NULL DEFAULT 0",
        )
        ensure_column(
            conn,
            "job_verification_states",
            "stagnation_series",
            "stagnation_series INTEGER NOT NULL DEFAULT 0",
        )
        ensure_column(conn, "job_verification_states", "failure_fingerprint", "failure_fingerprint TEXT")
        ensure_column(conn, "job_verification_states", "latest_metrics_json", "latest_metrics_json TEXT")
        ensure_column(conn, "job_verification_states", "metric_trend", "metric_trend TEXT")
        ensure_column(conn, "job_verification_states", "last_error", "last_error TEXT")
        ensure_column(conn, "job_verification_states", "last_task_id", "last_task_id TEXT")
        ensure_column(conn, "job_verification_states", "last_worker_run_id", "last_worker_run_id TEXT")
        ensure_column(conn, "job_verification_states", "finished_at", "finished_at TEXT")
        ensure_column(conn, "job_verification_states", "escalation_report_json", "escalation_report_json TEXT")
        ensure_column(
            conn,
            "job_verification_states",
            "attempt_offset",
            "attempt_offset INTEGER NOT NULL DEFAULT 0",
        )


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def active_verification_manifest_row(
    conn: sqlite3.Connection, job_id: str
) -> sqlite3.Row | None:
    """Return the latest immutable manifest revision, or the original manifest.

    The Milestone-4 row is never updated during retargeting.  New approved pins
    are represented by additive revision rows and selected explicitly here.
    """

    row = conn.execute(
        """
        SELECT *, revision AS active_revision
        FROM verification_manifest_revisions
        WHERE job_id = ?
        ORDER BY revision DESC LIMIT 1
        """,
        (job_id,),
    ).fetchone()
    if row is not None:
        return row
    return conn.execute(
        """
        SELECT *, 0 AS active_revision
        FROM verification_manifests WHERE job_id = ?
        """,
        (job_id,),
    ).fetchone()


def row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["constraints"] = from_json(data.pop("constraints_json"), [])
    data["acceptance"] = from_json(data.pop("acceptance_json"), [])
    data["plan"] = from_json(data.pop("plan_json"), [])
    data["models"] = from_json(data.pop("models_json", None), None)
    data["use_worktree"] = bool(data["use_worktree"])
    data["finish_requested"] = bool(data["finish_requested"])
    return data


def row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["constraints"] = from_json(data.pop("constraints_json"), [])
    data["acceptance"] = from_json(data.pop("acceptance_json"), [])
    data["requirement_ids"] = from_json(data.pop("requirement_ids_json", None), [])
    data["verification_ids"] = from_json(data.pop("verification_ids_json", None), [])
    return data


def row_to_run(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["changed_files"] = from_json(data.pop("changed_files_json"), [])
    return data


def row_to_verification_repetition(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["output_truncated"] = bool(data["output_truncated"])
    data["timed_out"] = bool(data["timed_out"])
    data["metrics"] = from_json(data.pop("metrics_json"), None)
    data["assertion_results"] = from_json(data.pop("assertion_results_json"), [])
    data["evidence"] = from_json(data.pop("evidence_json", None), [])
    data["coverage_results"] = from_json(data.pop("coverage_results_json", None), [])
    data["execution_proof"] = from_json(data.pop("execution_proof_json", None), {})
    _verify_evidence_metadata(data["evidence"])
    return data


def row_to_verification_correction_attempt(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["meaningful_change"] = bool(data["meaningful_change"])
    data["failure_identity"] = from_json(data.pop("failure_identity_json"), None)
    data["metric_values"] = from_json(data.pop("metric_values_json"), {})
    data["failed_assertions"] = from_json(data.pop("failed_assertions_json"), [])
    data["evidence_paths"] = from_json(data.pop("evidence_paths_json"), [])
    data["escalation_report"] = from_json(data.pop("escalation_report_json"), None)
    return data


def _verify_evidence_metadata(value: Any) -> None:
    """Detect tampering before persisted evidence is returned as trusted data."""

    if not isinstance(value, list):
        raise ValueError("persisted verification evidence must be an array")
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"persisted verification evidence {index} must be an object")
        size = item.get("size")
        digest = item.get("sha256")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError(f"persisted verification evidence {index} has invalid size")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError(f"persisted verification evidence {index} has invalid SHA-256")
        artifact_path = item.get("artifact_path")
        if artifact_path is not None:
            if not isinstance(artifact_path, str) or not artifact_path:
                raise ValueError(f"persisted verification evidence {index} has invalid path")
            try:
                payload = Path(artifact_path).read_bytes()
            except OSError as exc:
                raise ValueError(
                    f"persisted verification evidence artifact is unavailable: {artifact_path}"
                ) from exc
        elif "inline_value" in item:
            try:
                payload = json.dumps(
                    item["inline_value"],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"persisted verification evidence {index} has invalid inline data"
                ) from exc
        else:
            raise ValueError(
                f"persisted verification evidence {index} has neither artifact nor inline data"
            )
        if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError(f"persisted verification evidence {index} integrity mismatch")


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
    models: dict | None = None,
    specification_id: str | None = None,
    specification_version: int | None = None,
    specification_content_hash: str | None = None,
) -> None:
    # Every new job gets an email command token, regardless of which entry
    # point (CLI, GUI, tests) created it. Callers may still pass their own.
    if not email_token:
        email_token = secrets.token_urlsafe(9)
    now = utc_now()
    conn.execute(
        """
        INSERT INTO jobs (
            id, repo_path, worktree_path, branch, base_ref, goal, constraints_json,
            acceptance_json, test_cmd, max_iterations, use_worktree, worker,
            controller, granularity, plan_json, estimated_remaining_units,
            email_token, models_json, specification_id, specification_version,
            specification_content_hash, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planning', ?, ?)
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
            None if models is None else to_json(models),
            specification_id,
            specification_version,
            specification_content_hash,
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
    requirement_ids: list[str] | None = None,
    verification_ids: list[str] | None = None,
) -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO tasks (
            id, job_id, iteration, goal, constraints_json, acceptance_json,
            test_cmd, requirement_ids_json, verification_ids_json, status,
            created_by, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
        """,
        (
            task_id,
            job_id,
            iteration,
            goal,
            to_json(constraints),
            to_json(acceptance),
            test_cmd,
            to_json(requirement_ids or []),
            to_json(verification_ids or []),
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


def next_verification_attempt(
    conn: sqlite3.Connection,
    job_id: str,
    verification_id: str,
) -> int:
    row = conn.execute(
        """
        SELECT MAX(attempt) AS latest_attempt
        FROM verification_repetitions
        WHERE job_id = ? AND verification_id = ?
        """,
        (job_id, verification_id),
    ).fetchone()
    return 1 if row is None or row["latest_attempt"] is None else int(row["latest_attempt"]) + 1


def create_verification_repetition(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    task_id: str,
    worker_run_id: str | None,
    verification_id: str,
    attempt: int,
    repetition: int,
    command: str,
    working_directory: str,
    timeout_seconds: int,
    status: str,
    return_code: int | None,
    output: str,
    output_truncated: bool,
    metrics: dict[str, float] | None,
    assertion_results: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    coverage_results: list[dict[str, Any]],
    elapsed_seconds: float,
    timed_out: bool,
    error: str | None,
    termination_details: str | None,
    started_at: str,
    finished_at: str,
    execution_proof: dict[str, Any] | None = None,
) -> int:
    """Append one immutable formal-verification repetition row."""

    job = get_job(conn, job_id)
    if job.get("specification_id") is None or job.get("specification_version") is None:
        raise ValueError("Quick Goal jobs cannot receive verification repetitions")
    task = get_task(conn, task_id)
    if task["job_id"] != job_id:
        raise ValueError("verification repetition task belongs to a different job")
    if worker_run_id is not None:
        worker_run = get_run(conn, worker_run_id)
        if worker_run["job_id"] != job_id or worker_run["task_id"] != task_id:
            raise ValueError(
                "verification repetition worker run belongs to a different job or task"
            )
    state = conn.execute(
        """
        SELECT 1 FROM job_verification_states
        WHERE job_id = ? AND verification_id = ?
        """,
        (job_id, verification_id),
    ).fetchone()
    if state is None:
        raise ValueError(
            f"verification repetition case is absent from formal job state: {verification_id}"
        )
    cursor = conn.execute(
        """
        INSERT INTO verification_repetitions (
            job_id, task_id, worker_run_id, verification_id, attempt,
            repetition, command, working_directory, timeout_seconds, status,
            return_code, output, output_truncated, metrics_json,
            assertion_results_json, evidence_json, coverage_results_json,
            execution_proof_json, elapsed_seconds, timed_out, error,
            termination_details, started_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            task_id,
            worker_run_id,
            verification_id,
            attempt,
            repetition,
            command,
            working_directory,
            timeout_seconds,
            status,
            return_code,
            output,
            1 if output_truncated else 0,
            None if metrics is None else to_json(metrics),
            to_json(assertion_results),
            to_json(evidence),
            to_json(coverage_results),
            to_json(execution_proof or {}),
            elapsed_seconds,
            1 if timed_out else 0,
            error,
            termination_details,
            started_at,
            finished_at,
        ),
    )
    return int(cursor.lastrowid)


def list_verification_repetitions(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    task_id: str | None = None,
    verification_id: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["job_id = ?"]
    values: list[Any] = [job_id]
    if task_id is not None:
        clauses.append("task_id = ?")
        values.append(task_id)
    if verification_id is not None:
        clauses.append("verification_id = ?")
        values.append(verification_id)
    rows = conn.execute(
        f"""
        SELECT * FROM verification_repetitions
        WHERE {' AND '.join(clauses)}
        ORDER BY id
        """,
        values,
    ).fetchall()
    return [row_to_verification_repetition(row) for row in rows]


def create_verification_correction_attempt(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    task_id: str,
    worker_run_id: str | None,
    verification_id: str,
    attempt: int,
    status: str,
    failure_fingerprint: str | None,
    failure_identity: dict[str, Any] | None,
    metric_values: dict[str, float],
    metric_trend: str,
    consecutive_failures: int,
    stagnation_count: int,
    stagnation_series: int,
    meaningful_change: bool,
    failed_assertions: list[dict[str, Any]],
    observed_error: str | None,
    output_tail: str,
    evidence_paths: list[str],
    repair_goal: str,
    escalation_report: dict[str, Any] | None,
    created_at: str,
) -> int:
    """Append one immutable adaptive-correction result for a case attempt."""

    job = get_job(conn, job_id)
    if job.get("specification_id") is None:
        raise ValueError("Quick Goal jobs cannot receive correction-loop history")
    task = get_task(conn, task_id)
    if task["job_id"] != job_id:
        raise ValueError("correction attempt task belongs to a different job")
    if worker_run_id is not None:
        worker_run = get_run(conn, worker_run_id)
        if worker_run["job_id"] != job_id or worker_run["task_id"] != task_id:
            raise ValueError(
                "correction attempt worker run belongs to a different job or task"
            )
    cursor = conn.execute(
        """
        INSERT INTO verification_correction_attempts (
            job_id, task_id, worker_run_id, verification_id, attempt, status,
            failure_fingerprint, failure_identity_json, metric_values_json,
            metric_trend, consecutive_failures, stagnation_count,
            stagnation_series, meaningful_change, failed_assertions_json,
            observed_error, output_tail, evidence_paths_json, repair_goal,
            escalation_report_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            task_id,
            worker_run_id,
            verification_id,
            attempt,
            status,
            failure_fingerprint,
            None if failure_identity is None else to_json(failure_identity),
            to_json(metric_values),
            metric_trend,
            consecutive_failures,
            stagnation_count,
            stagnation_series,
            1 if meaningful_change else 0,
            to_json(failed_assertions),
            observed_error,
            output_tail,
            to_json(evidence_paths),
            repair_goal,
            None if escalation_report is None else to_json(escalation_report),
            created_at,
        ),
    )
    return int(cursor.lastrowid)


def list_verification_correction_attempts(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    verification_id: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["job_id = ?"]
    values: list[Any] = [job_id]
    if verification_id is not None:
        clauses.append("verification_id = ?")
        values.append(verification_id)
    rows = conn.execute(
        f"""
        SELECT * FROM verification_correction_attempts
        WHERE {' AND '.join(clauses)}
        ORDER BY id
        """,
        values,
    ).fetchall()
    return [row_to_verification_correction_attempt(row) for row in rows]


def create_verification_manual_acknowledgement(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    verification_id: str,
    acknowledged_by: str,
    note: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Append an auditable note for one non-blocking manual case.

    The persisted immutable manifest is authoritative.  This operation never
    updates aggregate verification state and therefore cannot turn either a
    manual or automated case into a passing case.
    """

    actor = acknowledged_by.strip() if isinstance(acknowledged_by, str) else ""
    acknowledgement_note = note.strip() if isinstance(note, str) else ""
    if not actor:
        raise ValueError("manual acknowledgement requires who acknowledged it")
    if not acknowledgement_note:
        raise ValueError("manual acknowledgement requires a note")
    job = get_job(conn, job_id)
    if job.get("specification_id") is None or job.get("specification_version") is None:
        raise ValueError("Quick Goal jobs cannot receive manual verification acknowledgements")
    manifest_row = active_verification_manifest_row(conn, job_id)
    if manifest_row is None:
        raise ValueError("formal manual acknowledgement requires a persisted manifest")
    try:
        manifest = json.loads(str(manifest_row["canonical_json"]))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("persisted verification manifest JSON is invalid") from exc
    cases = manifest.get("verification") if isinstance(manifest, dict) else None
    if not isinstance(cases, list):
        raise ValueError("persisted verification manifest has no verification cases")
    matching = [
        item
        for item in cases
        if isinstance(item, dict) and item.get("verification_id") == verification_id
    ]
    if len(matching) != 1:
        raise ValueError(f"unknown verification case: {verification_id}")
    case = matching[0]
    if case.get("automation") != "manual":
        raise ValueError("automated verification cases cannot be manually acknowledged")
    if bool(case.get("blocking")):
        raise ValueError("blocking verification cases cannot be manually acknowledged")
    timestamp = created_at or utc_now()
    cursor = conn.execute(
        """
        INSERT INTO verification_manual_acknowledgements (
            job_id, verification_id, acknowledged_by, note, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (job_id, verification_id, actor, acknowledgement_note, timestamp),
    )
    acknowledgement = {
        "id": int(cursor.lastrowid),
        "job_id": job_id,
        "verification_id": verification_id,
        "acknowledged_by": actor,
        "note": acknowledgement_note,
        "created_at": timestamp,
    }
    add_event(
        conn,
        job_id=job_id,
        kind="manual_verification_acknowledged",
        payload={
            "acknowledgement_id": acknowledgement["id"],
            "verification_id": verification_id,
            "acknowledged_by": actor,
            "note": acknowledgement_note,
            "does_not_change_runtime_status": True,
        },
    )
    return acknowledgement


def list_verification_manual_acknowledgements(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    verification_id: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["job_id = ?"]
    values: list[Any] = [job_id]
    if verification_id is not None:
        clauses.append("verification_id = ?")
        values.append(verification_id)
    rows = conn.execute(
        f"""
        SELECT * FROM verification_manual_acknowledgements
        WHERE {' AND '.join(clauses)}
        ORDER BY id
        """,
        values,
    ).fetchall()
    return [dict(row) for row in rows]


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
