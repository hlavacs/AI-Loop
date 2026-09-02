from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import ai_loop_gui
from ai_loop import db
from ai_loop.job_status import active_job_status, current_active_task


def task(iteration: int, status: str, created_by: str = "claude:repair") -> dict[str, object]:
    return {"iteration": iteration, "status": status, "created_by": created_by}


def test_running_repair_is_reported_as_implementing() -> None:
    assert active_job_status([task(1, "running")]) == "implementing"


def test_running_task_takes_precedence_over_newer_queued_repair() -> None:
    tasks = [task(1, "running"), task(2, "queued")]
    assert active_job_status(tasks) == "implementing"
    assert current_active_task(tasks) == tasks[0]


def test_queued_repair_remains_fixing_until_execution_starts() -> None:
    assert active_job_status([task(1, "queued")]) == "fixing"


def test_gui_backend_reconciles_running_repair_to_implementing() -> None:
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "loop.sqlite3"
        db.init_db(db_path)
        with db.transaction(db_path) as conn:
            db.create_job(
                conn,
                job_id="J-status",
                repo_path=directory,
                worktree_path=directory,
                branch=None,
                base_ref="HEAD",
                goal="Render videos",
                constraints=[],
                acceptance=[],
                test_cmd="true",
                max_iterations=10,
                use_worktree=False,
            )
            db.create_task(
                conn,
                task_id="T-running",
                job_id="J-status",
                iteration=1,
                goal="Render a video",
                constraints=[],
                acceptance=[],
                test_cmd="true",
                created_by="claude:repair",
            )
            db.update_task_status(conn, "T-running", "running")
            db.create_task(
                conn,
                task_id="T-queued",
                job_id="J-status",
                iteration=2,
                goal="Render the next video",
                constraints=[],
                acceptance=[],
                test_cmd="true",
                created_by="claude:repair",
            )
            db.update_job_status(conn, "J-status", "fixing")

        backend = ai_loop_gui.LoopBackend.__new__(ai_loop_gui.LoopBackend)
        backend.settings = SimpleNamespace(db_path=db_path)
        backend.process_status = lambda _job_id: {"worker": {"running": True}}

        jobs = backend.list_jobs()
        assert jobs[0]["status"] == "implementing"
        assert jobs[0]["latest_task"]["id"] == "T-running"
        with db.transaction(db_path) as conn:
            assert db.get_job(conn, "J-status")["status"] == "implementing"
