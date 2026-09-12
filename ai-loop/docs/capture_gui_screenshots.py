"""Capture the GUI screenshots used by the AI-Loop introduction video.

Run from ``ai-loop`` with a real display::

    python3 docs/capture_gui_screenshots.py

On a headless Linux host, prefix the same command with ``xvfb-run -a``.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from typing import Any

from PIL import Image, ImageGrab, ImageStat

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "images"
SCREENSHOTS = {
    "s11": "s11-gui-jobs-status.png",
    "s12": "s12-gui-plan.png",
    "s13": "s13-gui-task-controller.png",
    "s14": "s14-gui-worker-details.png",
    "s15": "s15-gui-logs-controls.png",
    "s16": "s16-gui-provider-repair.png",
    "s17": "s17-quick-job-form.png",
    "s18": "s18-quick-job-complete.png",
}
ACTIVE_JOB = "demo-active-001"
AUTH_JOB = "demo-auth-002"
QUICK_JOB = "demo-quick-fix-003"
DEMO_REPOSITORY = "/tmp/ai-loop-demo/one-failing-test"


def ensure_gui_dependencies() -> None:
    if importlib.util.find_spec("redis") is not None:
        return
    sites = list((ROOT / ".gui-venv" / "lib").glob("python*/site-packages"))
    if not sites:
        subprocess.run(
            [sys.executable, str(ROOT / "ai_loop_gui.py"), "--help"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        sites = list((ROOT / ".gui-venv" / "lib").glob("python*/site-packages"))
    for site_packages in sites:
        sys.path.insert(0, str(site_packages))
        if importlib.util.find_spec("redis") is not None:
            return
        sys.path.pop(0)
    raise RuntimeError("the GUI dependency environment does not provide redis")


def load_application() -> Any:
    ensure_gui_dependencies()
    spec = importlib.util.spec_from_file_location(
        "ai_loop_video_capture_app", ROOT / "ai_loop_gui.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load ai_loop_gui.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture(window: Any, name: str, *, lift: bool = True) -> None:
    if lift:
        window.lift()
        window.attributes("-topmost", True)
    window.update()
    time.sleep(0.2)
    left, top = window.winfo_rootx(), window.winfo_rooty()
    width, height = window.winfo_width(), window.winfo_height()
    image = ImageGrab.grab(bbox=(left, top, left + width, top + height))
    sample = image.convert("RGB").resize((96, 64))
    colours = sample.getcolors(maxcolors=96 * 64) or []
    variance = max(ImageStat.Stat(sample).var)
    if (len(colours) < 8 or variance < 20) and shutil.which("xwd"):
        xwd_path = OUTPUT / name.replace(".png", ".xwd")
        try:
            image = capture_xwd(int(window.winfo_id()), xwd_path)
        finally:
            xwd_path.unlink(missing_ok=True)
        sample = image.resize((96, 64))
        colours = sample.getcolors(maxcolors=96 * 64) or []
        variance = max(ImageStat.Stat(sample).var)
    if width < 1200 or height < 400 or len(colours) < 8 or variance < 20:
        raise RuntimeError(
            f"invalid screenshot {name}: {width}x{height}, "
            f"{len(colours)} colours, variance {variance:.1f}"
        )
    image.save(OUTPUT / name)
    if lift:
        window.attributes("-topmost", False)
    print(f"{name}: {image.width}x{image.height}, {len(colours)} colours")


def capture_xwd(window_id: int, path: Path) -> Image.Image:
    subprocess.run(
        ["xwd", "-silent", "-id", str(window_id), "-out", str(path)], check=True
    )
    data = path.read_bytes()
    header = struct.unpack(">25I", data[:100])
    width, height, bits, stride = header[4], header[5], header[11], header[12]
    if bits not in {24, 32} or len(data) < stride * height:
        raise RuntimeError(f"unsupported XWD format: {width}x{height}x{bits}")
    pixels = data[-stride * height :]
    raw_mode = "BGRX" if bits == 32 else "BGR"
    return Image.frombytes("RGB", (width, height), pixels, "raw", raw_mode, stride, 1)


def select_detail_tab(app: Any, label: str) -> None:
    for tab_id in app.detail_notebook.tabs():
        if app.detail_notebook.tab(tab_id, "text") == label:
            app.detail_notebook.select(tab_id)
            app.update()
            return
    raise RuntimeError(f"missing detail tab: {label}")


def seed_demo_jobs(database: Path) -> None:
    from ai_loop import db

    plan = [
        "Reproduce the single failing test and identify its cause.",
        "Apply the smallest focused correction to the affected function.",
        "Run the targeted test, then run the complete test suite.",
        "Review the evidence and validate the clean target checkout.",
    ]
    with db.transaction(database) as conn:
        db.create_job(
            conn,
            job_id=ACTIVE_JOB,
            repo_path=DEMO_REPOSITORY,
            worktree_path="/tmp/ai-loop-demo/worktrees/active-001",
            branch="ai-loop/demo-active-001",
            base_ref="HEAD",
            goal="Repair the one failing test with the smallest correct change.",
            constraints=[
                "Keep the public API unchanged.",
                "Do not modify unrelated files.",
            ],
            acceptance=[
                "The failing test passes.",
                "The complete test suite passes.",
            ],
            test_cmd="python -m pytest -q",
            max_iterations=12,
            use_worktree=True,
            worker="codex",
            controller="claude",
            granularity="normal",
            plan=plan,
            email_token="demo-only",
        )
        db.create_task(
            conn,
            task_id="demo-task-001",
            job_id=ACTIVE_JOB,
            iteration=1,
            goal="Reproduce the failing test and isolate the faulty comparison.",
            constraints=["Inspect only the relevant module and its tests."],
            acceptance=["The cause is explained with a reproducible failing command."],
            test_cmd="python -m pytest tests/test_totals.py -q",
            created_by="controller",
        )
        db.update_task_status(conn, "demo-task-001", "completed")
        db.create_run(
            conn,
            run_id="demo-run-001",
            task_id="demo-task-001",
            job_id=ACTIVE_JOB,
            iteration=1,
            codex_rc=0,
            codex_output=(
                "Reproduced the failing boundary case and traced it to one comparison.\n"
                "No repository files were changed during diagnosis."
            ),
            test_rc=1,
            test_output="1 failed, 11 passed — expected boundary value to be included",
            git_status="clean",
            diff_stat="",
            diff="",
            changed_files=[],
            status="completed",
            error=None,
            started_at="2026-09-12T12:01:00+00:00",
            finished_at="2026-09-12T12:02:00+00:00",
        )
        db.create_task(
            conn,
            task_id="demo-task-002",
            job_id=ACTIVE_JOB,
            iteration=2,
            goal="Correct the boundary comparison and prove the focused repair.",
            constraints=[
                "Change only the comparison responsible for the failure.",
                "Preserve behavior for all existing passing cases.",
            ],
            acceptance=[
                "The targeted boundary test passes.",
                "All twelve tests pass without warnings.",
            ],
            test_cmd="python -m pytest -q",
            created_by="controller",
        )
        db.update_task_status(conn, "demo-task-002", "running")
        db.create_decision(
            conn,
            decision_id="demo-decision-001",
            job_id=ACTIVE_JOB,
            task_id="demo-task-002",
            run_id="demo-run-001",
            request_type="worker_result",
            action="CONTINUE",
            reason="The diagnosis is complete; apply and validate the narrow repair.",
            history_summary="One failing boundary test was reproduced and isolated.",
            decision={
                "action": "CONTINUE",
                "next_task": {
                    "goal": "Correct the boundary comparison and prove the focused repair.",
                    "acceptance": [
                        "The targeted test passes.",
                        "The complete suite passes.",
                    ],
                    "test_cmd": "python -m pytest -q",
                },
            },
        )
        db.update_job_estimate(
            conn,
            ACTIVE_JOB,
            completed_units=2,
            remaining_units=2,
            remaining_seconds=420,
        )
        db.update_job_status(
            conn,
            ACTIVE_JOB,
            "implementing",
            "The failure is isolated and the focused correction is in progress.",
        )

        db.create_job(
            conn,
            job_id=AUTH_JOB,
            repo_path=DEMO_REPOSITORY,
            worktree_path="/tmp/ai-loop-demo/worktrees/auth-002",
            branch="ai-loop/demo-auth-002",
            base_ref="HEAD",
            goal="Continue the same demo job after provider sign-in.",
            constraints=["Preserve the existing worktree and job history."],
            acceptance=["Authentication succeeds and the same job resumes."],
            test_cmd="python -m pytest -q",
            max_iterations=12,
            use_worktree=True,
            worker="codex",
            controller="claude",
            granularity="normal",
            plan=plan,
            email_token="demo-only",
        )
        db.create_decision(
            conn,
            decision_id="demo-decision-auth",
            job_id=AUTH_JOB,
            task_id=None,
            run_id=None,
            request_type="controller_status",
            action="HUMAN_NEEDED",
            reason="Claude authentication is required for this fictional demo job.",
            history_summary="Provider sign-in is required; the worktree is preserved.",
            decision={
                "action": "HUMAN_NEEDED",
                "error_code": "provider_auth_required",
                "provider": "claude",
                "reason": "Authentication required for the demo provider.",
            },
        )
        db.update_job_status(
            conn,
            AUTH_JOB,
            "human_needed",
            "Provider sign-in is required; the worktree is preserved.",
        )

        db.create_job(
            conn,
            job_id=QUICK_JOB,
            repo_path=DEMO_REPOSITORY,
            worktree_path="/tmp/ai-loop-demo/worktrees/quick-fix-003",
            branch="ai-loop/demo-quick-fix-003",
            base_ref="HEAD",
            goal=(
                "Diagnose the failure, make the smallest correct repair, and make "
                "the test suite pass."
            ),
            constraints=["Keep the change focused and preserve the public API."],
            acceptance=[
                "The original failing test passes.",
                "The target checkout passes the complete test command.",
            ],
            test_cmd="python -m pytest -q",
            max_iterations=12,
            use_worktree=True,
            worker="codex",
            controller="claude",
            granularity="normal",
            plan=plan,
            email_token="demo-only",
        )
        db.create_task(
            conn,
            task_id="quick-task-001",
            job_id=QUICK_JOB,
            iteration=1,
            goal="Repair the inclusive boundary check and validate the repository.",
            constraints=["Make one focused source change."],
            acceptance=["All twelve tests pass in both worktree and target checkout."],
            test_cmd="python -m pytest -q",
            created_by="controller",
        )
        db.update_task_status(conn, "quick-task-001", "completed")
        db.create_run(
            conn,
            run_id="quick-run-001",
            task_id="quick-task-001",
            job_id=QUICK_JOB,
            iteration=1,
            codex_rc=0,
            codex_output=(
                "Current task completed: repaired the inclusive boundary check.\n"
                "Target-checkout validation: PASSED\n"
                "Command: python -m pytest -q\n"
                "Result: 12 passed"
            ),
            test_rc=0,
            test_output="12 passed in 0.18s",
            git_status="M src/totals.py",
            diff_stat="src/totals.py | 2 +-, 1 file changed",
            diff="sanitized demo diff",
            changed_files=["src/totals.py"],
            status="completed",
            error=None,
            started_at="2026-09-12T12:10:00+00:00",
            finished_at="2026-09-12T12:11:00+00:00",
        )
        db.create_decision(
            conn,
            decision_id="quick-decision-done",
            job_id=QUICK_JOB,
            task_id="quick-task-001",
            run_id="quick-run-001",
            request_type="worker_result",
            action="DONE",
            reason="The focused test and target-checkout validation both passed.",
            history_summary="The minimal repair passed all acceptance checks.",
            decision={"action": "DONE"},
        )
        db.update_job_status(
            conn,
            QUICK_JOB,
            "done",
            "The minimal repair passed all tests and target-checkout validation.",
        )


def find_widget(parent: tk.Misc, widget_type: type[Any], text: str) -> Any:
    for widget in parent.winfo_children():
        if isinstance(widget, widget_type) and str(widget.cget("text")) == text:
            return widget
        try:
            return find_widget(widget, widget_type, text)
        except LookupError:
            pass
    raise LookupError(text)


def capture_job_actions_menu(app: Any, name: str) -> None:
    from tkinter import ttk

    button = find_widget(app, ttk.Menubutton, "Job Actions")
    menu = app.nametowidget(str(button.cget("menu")))
    app.lift()
    app.attributes("-topmost", True)
    app.update()
    menu.post(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
    app.update()
    capture(app, name, lift=False)
    menu.unpost()
    app.attributes("-topmost", False)


def capture_provider_dialog(app: Any, name: str) -> None:
    details = app.backend.job_details(AUTH_JOB)
    app.show_human_needed_alert(details["job"])
    dialog = app.human_needed_windows[AUTH_JOB]
    dialog.geometry("720x430+300+220")
    app.lift()
    app.update()
    dialog.lift()
    dialog.attributes("-topmost", True)
    dialog.update()
    capture(app, name, lift=False)
    dialog.attributes("-topmost", False)
    dialog.destroy()
    app.human_needed_windows.pop(AUTH_JOB, None)


def fill_quick_job_form(app: Any) -> None:
    app.repo_var.set(DEMO_REPOSITORY)
    app.goal_text.configure(state="normal")
    app.goal_text.delete("1.0", "end")
    app.goal_text.insert(
        "1.0",
        "Diagnose the failure, make the smallest correct repair, and make the "
        "test suite pass.",
    )
    app.test_cmd_var.set("python -m pytest -q")
    app.base_ref_var.set("HEAD")
    app.max_iterations_var.set(12)
    app.controller_var.set("claude")
    app.worker_var.set("codex")
    app.granularity_var.set("normal")
    app.no_worktree_var.set(False)
    app.allow_parallel_var.set(False)
    app.bypass_var.set(False)
    app.update()


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    with tempfile.TemporaryDirectory(prefix="ai-loop-gui-capture-") as temporary:
        database = Path(temporary) / "capture.sqlite3"
        os.environ["AI_LOOP_DB"] = str(database)
        os.environ["AI_LOOP_RUNS_DIR"] = str(Path(temporary) / "runs")
        for name in (
            "AI_LOOP_NOTIFY_EMAIL",
            "AI_LOOP_SMTP_HOST",
            "AI_LOOP_SMTP_USER",
            "AI_LOOP_SMTP_PASSWORD",
            "AI_LOOP_SMTP_FROM",
            "AI_LOOP_IMAP_HOST",
            "AI_LOOP_IMAP_USER",
            "AI_LOOP_IMAP_PASSWORD",
        ):
            os.environ[name] = ""

        module = load_application()
        module.AiLoopGui._sample_redis_status = lambda self: None
        module.AiLoopGui._start_mail_access_check = lambda self: None
        app = module.AiLoopGui()
        app.geometry("1280x820+20+20")
        app.title("AI-LOOP — sanitized GUI demonstration")
        app.auto_refresh.set(False)
        app.status_var.set("Sanitized GUI demonstration")
        app.backend.log_text = lambda _job_id, _name: (
            "12:01 Controller queued demo-task-002\n"
            "12:02 Worker started the focused repair\n"
            "12:03 Running python -m pytest -q\n"
            "12:04 Validation passed: 12 tests\n"
            "12:05 Awaiting controller review"
        )
        try:
            seed_demo_jobs(database)
            fill_quick_job_form(app)
            app.alerted_human_needed.add(AUTH_JOB)
            app.refresh_all(select_job_id=ACTIVE_JOB)
            app.update()

            select_detail_tab(app, "Status")
            capture(app, SCREENSHOTS["s11"])

            select_detail_tab(app, "Plan")
            capture(app, SCREENSHOTS["s12"])

            select_detail_tab(app, "Task")
            capture(app, SCREENSHOTS["s13"])

            select_detail_tab(app, "Worker")
            capture(app, SCREENSHOTS["s14"])

            select_detail_tab(app, "Logs")
            app.refresh_log()
            capture_job_actions_menu(app, SCREENSHOTS["s15"])

            app.refresh_all(select_job_id=AUTH_JOB)
            select_detail_tab(app, "Status")
            capture_provider_dialog(app, SCREENSHOTS["s16"])

            fill_quick_job_form(app)
            capture(app, SCREENSHOTS["s17"])

            app.refresh_all(select_job_id=QUICK_JOB)
            select_detail_tab(app, "Worker")
            capture(app, SCREENSHOTS["s18"])
        finally:
            app.destroy()

    missing = [name for name in SCREENSHOTS.values() if not (OUTPUT / name).is_file()]
    if missing:
        raise RuntimeError("missing screenshots: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
