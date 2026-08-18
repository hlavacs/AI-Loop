from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import controller
import worker
from ai_loop import db
from ai_loop.config import CLAUDE_REQUEST_STREAM, CODEX_TASK_STREAM, DONE_STREAM
from ai_loop.queues import decode
from ai_loop.specification_gui import document_to_record, open_specification_editor
from ai_loop.specifications import SpecificationService
from ai_loop.verification_orchestrator import evaluate_completion_gate
from tests.test_completion_enforcement import FakeRunner, done_decision, passing_result
from tests.test_specification_compiler import document
from tests.test_task_traceability import FakeRedis


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a Tk display")
def test_start_implementation_gui_reaches_verified_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the approved GUI action through queue, worker, and DONE gate."""

    try:
        import tkinter as tk
    except ImportError:
        pytest.skip("Tk is not installed")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk cannot connect to a display")
    root.withdraw()

    import ai_loop.specification_gui as specification_gui
    import ai_loop_gui

    database = tmp_path / "loop.sqlite3"
    service = SpecificationService(database, tmp_path / "artifacts")
    redis = FakeRedis()
    settings = SimpleNamespace(
        db_path=database,
        runs_dir=tmp_path / "runs",
        redis_url="redis://unused/0",
        notify_email="",
        worker_default="codex",
        controller_default="claude",
        codex_bin="codex",
        claude_bin="claude",
        gemini_bin="gemini",
        codex_model="",
        fable_model="",
        opus_model="",
        gemini_model="",
        controller_model="",
        worker_role_model="",
        controller_role_model="",
        codex_bypass_sandbox=False,
    )
    models = ai_loop_gui.ModelDefaults(
        codex_model="",
        fable_model="",
        opus_model="",
        gemini_model="",
        controller_model="",
        codex_bin="codex",
        claude_bin="claude",
        gemini_bin="gemini",
        codex_bypass_sandbox=False,
    )

    backend = ai_loop_gui.LoopBackend.__new__(ai_loop_gui.LoopBackend)
    backend.settings = settings
    backend.ensure_provider_clis = lambda **_kwargs: None
    backend.ensure_redis_running = lambda: None
    backend.launch_processes = lambda _job_id, _models: {}

    app = object.__new__(ai_loop_gui.AiLoopGui)
    app.backend = backend
    app._exclusive_conflict = lambda _operation: None
    app.current_models = lambda: models
    app.worker_var = SimpleNamespace(get=lambda: "codex")
    app.controller_var = SimpleNamespace(get=lambda: "claude")
    app.test_cmd_var = SimpleNamespace(get=lambda: "pytest -q")
    app.max_iterations_var = SimpleNamespace(get=lambda: "3")
    app.base_ref_var = SimpleNamespace(get=lambda: "HEAD")
    app.no_worktree_var = SimpleNamespace(get=lambda: True)
    app.allow_parallel_var = SimpleNamespace(get=lambda: False)
    app.granularity_var = SimpleNamespace(get=lambda: "normal")

    message_errors: list[str] = []
    monkeypatch.setattr(ai_loop_gui, "active_jobs", lambda _path: [])
    monkeypatch.setattr(ai_loop_gui, "timestamp_id", lambda _prefix: "J-GUI-E2E")
    monkeypatch.setattr(
        ai_loop_gui,
        "create_pre_job_commit",
        lambda _repo, _job_id: {"created": False},
    )
    monkeypatch.setattr(ai_loop_gui, "redis_client", lambda _url: redis)
    monkeypatch.setattr(
        ai_loop_gui, "job_started_email", lambda *_args, **_kwargs: (False, "off")
    )
    monkeypatch.setattr(
        specification_gui.messagebox,
        "showinfo",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        specification_gui.messagebox,
        "showerror",
        lambda _title, message, **_kwargs: message_errors.append(str(message)),
    )

    plan_decision = {
        "action": "CONTINUE",
        "reason": "implement and verify the approved contract",
        "history_summary": "approved formal work is queued",
        "progress": {
            "completed_work_units": 0,
            "remaining_work_units": 1,
            "remaining_minutes": 1,
        },
        "next_task": {
            "goal": "Implement and verify requirements R1 and R2 through VT1",
            "constraints": ["Keep the approved specification pin unchanged"],
            "acceptance": ["VT1 executes and passes with runtime proof"],
            "test_cmd": "pytest -q",
            "requirement_ids": ["R1", "R2"],
            "verification_ids": ["VT1"],
        },
    }
    decisions = iter((plan_decision, done_decision()))
    controller_calls: list[dict[str, Any]] = []

    def controller_decision(*args: Any, **kwargs: Any) -> dict[str, Any]:
        controller_calls.append({"args": args, "kwargs": kwargs})
        return next(decisions)

    monkeypatch.setattr(controller, "controller_decision", controller_decision)
    monkeypatch.setattr(controller, "timestamp_id", lambda _prefix: "T-GUI-E2E")
    monkeypatch.setattr(
        controller, "terminal_email", lambda *_args, **_kwargs: (False, "off")
    )
    monkeypatch.setattr(
        worker.shutil, "which", lambda _binary, **_kwargs: "/usr/bin/fake"
    )
    monkeypatch.setattr(
        worker,
        "run_command",
        lambda *_args, **_kwargs: {"rc": 0, "output": "implementation complete"},
    )
    monkeypatch.setattr(
        worker,
        "run_shell",
        lambda *_args, **_kwargs: {"rc": 0, "output": "1 passed in 0.01s"},
    )
    monkeypatch.setattr(
        worker,
        "git_snapshot",
        lambda _path: {
            "git_status": "",
            "diff_stat": "",
            "diff": "",
            "changed_files": [],
        },
    )
    verification_runner = FakeRunner(passing_result())
    monkeypatch.setattr(
        worker, "SubprocessVerificationRunner", lambda: verification_runner
    )

    def immediate_runner(work, done, **_kwargs):
        try:
            done(work(), None)
        except Exception as exc:  # pragma: no cover - surfaced by message_errors
            done(None, str(exc))

    # Static realization declarations make VT1 fully wired before the worker
    # executes it; the runner result below supplies the independent runtime proof.
    (tmp_path / "formal-verification.signals").write_text(
        "\n".join(
            [
                'AI_LOOP_CASE={"verification_id":"VT1"}',
                'AI_LOOP_FIXTURE_GENERATOR={"verification_id":"VT1","fixtures":["A valid and an invalid input"]}',
                'AI_LOOP_METRIC_EMITTER={"verification_id":"VT1","metrics":["duration_seconds"]}',
                'AI_LOOP_EVIDENCE_PRODUCER={"verification_id":"VT1","kinds":["Focused test log"]}',
            ]
        ),
        encoding="utf-8",
    )

    try:
        editor = open_specification_editor(
            root,
            service=service,
            repository_path=tmp_path,
            run_background=immediate_runner,
            implementation_work_factory=app._formal_implementation_work,
        )
        editor.record = document_to_record(document())
        editor._load_record_into_widgets()
        editor._refresh_assessment()
        editor.save_draft()
        editor.submit_for_review()
        editor.approve()

        approved = editor.snapshot
        assert approved is not None and approved.status == "approved"
        assert not editor._has_unsaved_edits()
        assert str(editor.start_button.cget("state")) == "normal"

        # This is the same Tk command dispatch a user click performs.
        editor.start_button.invoke()
        assert message_errors == []

        plan_payloads = [
            decode(fields["request"])
            for stream, fields in redis.messages
            if stream == CLAUDE_REQUEST_STREAM
            and "request" in fields
            and decode(fields["request"]).get("type") == "PLAN"
        ]
        assert plan_payloads == [
            {"type": "PLAN", "job_id": "J-GUI-E2E", "scope": "job"}
        ]
        with db.transaction(database) as conn:
            created_job = db.get_job(conn, "J-GUI-E2E")
        assert (
            created_job["specification_id"],
            created_job["specification_version"],
            created_job["specification_content_hash"],
        ) == (
            approved.specification_id,
            approved.version,
            approved.canonical_content_hash,
        )
        stored_manifest = service.load_job_manifest("J-GUI-E2E")
        assert stored_manifest is not None
        assert stored_manifest.manifest.specification == {
            "id": approved.specification_id,
            "version": approved.version,
            "schema_version": approved.document.schema_version,
            "content_hash": approved.canonical_content_hash,
        }

        controller.handle_request(settings, redis, plan_payloads[0])
        task_payloads = [
            decode(fields["task"])
            for stream, fields in redis.messages
            if stream == CODEX_TASK_STREAM and "task" in fields
        ]
        assert len(task_payloads) == 1
        task_id = task_payloads[0]["task_id"]

        worker.process_task(settings, redis, task_id)
        review_payloads = [
            decode(fields["request"])
            for stream, fields in redis.messages
            if stream == CLAUDE_REQUEST_STREAM
            and "request" in fields
            and decode(fields["request"]).get("type") == "REVIEW"
        ]
        assert len(review_payloads) == 1
        controller.handle_request(settings, redis, review_payloads[0])

        with db.transaction(database) as conn:
            completed_job = db.get_job(conn, "J-GUI-E2E")
            completed_task = db.get_task(conn, task_id)
            completed_run = db.get_run(conn, review_payloads[0]["run_id"])
            decisions_recorded = conn.execute(
                "SELECT action FROM decisions WHERE job_id = ? ORDER BY rowid",
                ("J-GUI-E2E",),
            ).fetchall()
        assert completed_job["status"] == "done"
        assert completed_task["status"] == "completed"
        assert completed_run["status"] == "completed"
        assert [row["action"] for row in decisions_recorded] == ["CONTINUE", "DONE"]
        assert len(controller_calls) == 2

        prompt_context = service.load_job_prompt_context(
            "J-GUI-E2E", worker_run_id=completed_run["id"]
        )
        gate = evaluate_completion_gate(
            prompt_context.runtime_verification_summary,
            worker_run_id=completed_run["id"],
        )
        assert gate is not None and gate.ready is True
        assert gate.required_requirement_ids == ("R1", "R2")
        assert gate.missing_requirement_ids == ()
        automated = prompt_context.runtime_verification_summary[0]
        assert automated["status"] == "passing"
        assert automated["evidence_freshness"] == "fresh"
        assert automated["execution_proof"]["passed"] is True
        assert automated["execution_proof"]["executed_case_count"] == 1
        assert len(verification_runner.calls) == 1

        done_payloads = [
            decode(fields["event"])
            for stream, fields in redis.messages
            if stream == DONE_STREAM and "event" in fields
        ]
        assert len(done_payloads) == 1
        assert done_payloads[0]["job_id"] == "J-GUI-E2E"
        editor.window.destroy()
    finally:
        root.destroy()
