from __future__ import annotations

import os
import argparse
import platform
import shutil
import signal
import subprocess
import sys
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any
from urllib.parse import urlparse

def bootstrap_python_dependencies() -> None:
    try:
        import redis  # noqa: F401

        return
    except ModuleNotFoundError:
        pass

    if os.environ.get("AI_LOOP_GUI_BOOTSTRAPPED") == "1":
        return

    root_dir = Path(__file__).resolve().parent
    venv_dir = root_dir / ".gui-venv"
    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not venv_python.exists():
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
    subprocess.check_call([str(venv_python), "-m", "pip", "install", "redis"])
    env = os.environ.copy()
    env["AI_LOOP_GUI_BOOTSTRAPPED"] = "1"
    os.execve(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]], env)


bootstrap_python_dependencies()

from redis.exceptions import ConnectionError, TimeoutError

from ai_loop import db
from ai_loop.config import (
    CLAUDE_REQUEST_STREAM,
    CODEX_TASK_STREAM,
    CONTROLLERS,
    WORKERS,
    load_settings,
    normalize_controller,
    normalize_worker,
)
from ai_loop.progress import estimate_progress
from ai_loop.queues import ensure_group, redis_client, xadd_json
from start_job import (
    CAPABLE_WORKERS,
    COMMON_CONSTRAINTS,
    DEFAULT_ACCEPTANCE,
    LARGE_TASK_CONSTRAINTS,
    SMALL_TASK_CONSTRAINTS,
    active_jobs,
    copy_checkout_overlay,
    create_pre_job_commit,
    create_worktree,
    detect_test_cmd,
    timestamp_id,
)


ACTIVE_STATUSES = {"planning", "queued", "implementing", "fixing"}
TERMINAL_STATUSES = {"done", "human_needed", "dead"}
PROCESS_NAMES = ("claude_controller", "codex_worker", "watcher")
APP_WINDOW_TITLE = "AI-LOOP - Prof. Helmut Hlavacs, University of Vienna and Robimo GmbH (https://robimo.at/), Vienna, Austria"


@dataclass
class ModelDefaults:
    fable_model: str
    opus_model: str
    controller_model: str
    codex_bin: str
    claude_bin: str
    codex_bypass_sandbox: bool


class LoopBackend:
    def __init__(self) -> None:
        self.settings = load_settings()
        db.init_db(self.settings.db_path)

    @property
    def root_dir(self) -> Path:
        return self.settings.root_dir

    def model_defaults(self) -> ModelDefaults:
        return ModelDefaults(
            fable_model=self.settings.fable_model,
            opus_model=self.settings.opus_model,
            controller_model=self.settings.controller_model,
            codex_bin=self.settings.codex_bin,
            claude_bin=self.settings.claude_bin,
            codex_bypass_sandbox=self.settings.codex_bypass_sandbox,
        )

    def redis_running(self) -> bool:
        try:
            redis_client(self.settings.redis_url).ping()
            return True
        except Exception:
            return False

    def start_redis_server(self) -> int:
        parsed = urlparse(self.settings.redis_url)
        host = parsed.hostname or "localhost"
        if host not in {"localhost", "127.0.0.1", "::1"}:
            raise RuntimeError(f"cannot auto-start non-local Redis URL: {self.settings.redis_url}")
        redis_bin = shutil.which("redis-server")
        if redis_bin is None:
            raise RuntimeError("redis-server is not on PATH; install Redis or set REDIS_URL to a running server")

        run_dir = self.root_dir / "run"
        log_dir = self.root_dir / "logs"
        run_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        pid_file = run_dir / "redis.pid"
        old_pid = self.read_pid(pid_file)
        if self.pid_running(old_pid):
            return int(old_pid)

        log_file = (log_dir / "redis.log").open("a", encoding="utf-8")
        kwargs: dict[str, Any] = {
            "cwd": str(self.root_dir),
            "stdout": log_file,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen([redis_bin, "--save", "", "--appendonly", "no"], **kwargs)
        log_file.close()
        pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")
        for _ in range(40):
            if self.redis_running():
                return proc.pid
            time.sleep(0.25)
        raise RuntimeError("redis-server was started but did not answer PING")

    def ensure_redis_running(self) -> None:
        if self.redis_running():
            return
        self.start_redis_server()

    def list_jobs(self) -> list[dict[str, Any]]:
        with db.transaction(self.settings.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    j.*,
                    (SELECT COUNT(*) FROM tasks t WHERE t.job_id = j.id) AS task_count,
                    (SELECT COUNT(*) FROM runs r WHERE r.job_id = j.id) AS run_count
                FROM jobs j
                ORDER BY updated_at DESC
                """
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = db.row_to_job(row)
                item["task_count"] = int(row["task_count"])
                item["run_count"] = int(row["run_count"])
                task = db.latest_task(conn, str(row["id"]))
                percent, remaining = estimate_progress(
                    conn,
                    job_id=str(row["id"]),
                    status=str(row["status"]),
                    created_at=str(row["created_at"]),
                    run_count=int(row["run_count"]),
                    task_count=int(row["task_count"]),
                    has_active_task=task is not None and str(task["status"]) in {"queued", "running"},
                )
                item["percent"] = percent
                item["remaining"] = remaining
                item["latest_task"] = task
                result.append(item)
            return result

    def job_details(self, job_id: str) -> dict[str, Any]:
        with db.transaction(self.settings.db_path) as conn:
            job = db.get_job(conn, job_id)
            tasks = [
                db.row_to_task(row)
                for row in conn.execute(
                    "SELECT * FROM tasks WHERE job_id = ? ORDER BY iteration DESC LIMIT 20",
                    (job_id,),
                )
            ]
            runs = [
                db.row_to_run(row)
                for row in conn.execute(
                    "SELECT * FROM runs WHERE job_id = ? ORDER BY iteration DESC LIMIT 20",
                    (job_id,),
                )
            ]
            decisions = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM decisions WHERE job_id = ? ORDER BY created_at DESC LIMIT 10",
                    (job_id,),
                )
            ]
            events = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM events WHERE job_id = ? ORDER BY created_at DESC LIMIT 20",
                    (job_id,),
                )
            ]
            return {
                "job": job,
                "tasks": tasks,
                "runs": runs,
                "decisions": decisions,
                "events": events,
                "processes": self.process_status(job_id),
            }

    def process_status(self, job_id: str) -> dict[str, dict[str, Any]]:
        runtime_dir = self.runtime_dir(job_id)
        status: dict[str, dict[str, Any]] = {}
        for name in PROCESS_NAMES:
            pid_file = runtime_dir / f"{name}.pid"
            pid = self.read_pid(pid_file)
            status[name] = {
                "pid": pid,
                "pid_file": str(pid_file),
                "running": self.pid_running(pid),
            }
        return status

    def runtime_dir(self, job_id: str) -> Path:
        return self.root_dir / "run" / "jobs" / job_id

    def log_dir(self, job_id: str) -> Path:
        return self.root_dir / "logs" / "jobs" / job_id

    @staticmethod
    def read_pid(path: Path) -> int | None:
        try:
            text = path.read_text(encoding="utf-8").strip()
            return int(text) if text else None
        except (OSError, ValueError):
            return None

    @staticmethod
    def pid_running(pid: int | None) -> bool:
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def env_for_processes(self, job_id: str, models: ModelDefaults) -> dict[str, str]:
        env = os.environ.copy()
        env["AI_LOOP_JOB_ID"] = job_id
        env["AI_LOOP_RUNTIME_DIR"] = str(self.runtime_dir(job_id))
        env["AI_LOOP_LOG_DIR"] = str(self.log_dir(job_id))
        env["CODEX_BIN"] = models.codex_bin
        env["CLAUDE_BIN"] = models.claude_bin
        env["AI_LOOP_FABLE_MODEL"] = models.fable_model
        env["AI_LOOP_OPUS_MODEL"] = models.opus_model
        env["AI_LOOP_CONTROLLER_MODEL"] = models.controller_model
        env["CODEX_BYPASS_SANDBOX"] = "1" if models.codex_bypass_sandbox else "0"
        return env

    def launch_processes(self, job_id: str, models: ModelDefaults) -> dict[str, int]:
        runtime_dir = self.runtime_dir(job_id)
        log_dir = self.log_dir(job_id)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        env = self.env_for_processes(job_id, models)
        scripts = {
            "claude_controller": "claude_controller.py",
            "codex_worker": "codex_worker.py",
            "watcher": "watcher.py",
        }
        pids: dict[str, int] = {}
        for name, script in scripts.items():
            old_pid = self.read_pid(runtime_dir / f"{name}.pid")
            if self.pid_running(old_pid):
                pids[name] = int(old_pid)
                continue
            log_path = log_dir / f"{name}.log"
            log_file = log_path.open("a", encoding="utf-8")
            kwargs: dict[str, Any] = {
                "cwd": str(self.root_dir),
                "env": env,
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
            }
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                kwargs["start_new_session"] = True
            proc = subprocess.Popen([sys.executable, script], **kwargs)
            log_file.close()
            pids[name] = proc.pid
            (runtime_dir / f"{name}.pid").write_text(f"{proc.pid}\n", encoding="utf-8")
        return pids

    def stop_processes(self, job_id: str) -> dict[str, str]:
        runtime_dir = self.runtime_dir(job_id)
        results: dict[str, str] = {}
        for name in PROCESS_NAMES:
            pid_file = runtime_dir / f"{name}.pid"
            pid = self.read_pid(pid_file)
            if not pid:
                results[name] = "no pid"
                continue
            if self.pid_running(pid):
                self.terminate_pid(pid)
                results[name] = f"stopped pid={pid}"
            else:
                results[name] = f"stale pid={pid}"
            try:
                pid_file.unlink()
            except OSError:
                pass
        return results

    @staticmethod
    def terminate_pid(pid: int) -> None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    def queue_plan(self, job_id: str) -> None:
        self.ensure_redis_running()
        client = redis_client(self.settings.redis_url)
        ensure_group(client, CLAUDE_REQUEST_STREAM, f"claude-controllers:{job_id}", start_id="$")
        ensure_group(client, CODEX_TASK_STREAM, f"codex-workers:{job_id}", start_id="$")
        xadd_json(client, CLAUDE_REQUEST_STREAM, "request", {"type": "PLAN", "job_id": job_id, "scope": "job"})

    def create_job(
        self,
        *,
        repo: Path,
        goal: str,
        test_cmd: str,
        constraints: list[str],
        acceptance: list[str],
        max_iterations: int,
        base_ref: str,
        use_worktree: bool,
        allow_parallel: bool,
        worker: str,
        controller: str,
        models: ModelDefaults,
    ) -> str:
        repo = repo.expanduser().resolve()
        if not repo.exists():
            raise ValueError(f"repo does not exist: {repo}")
        worker = normalize_worker(worker)
        controller = normalize_controller(controller)
        detected_test_cmd = detect_test_cmd(repo, test_cmd)

        current_active = active_jobs(self.settings.db_path)
        if current_active and not allow_parallel:
            raise RuntimeError("another job is active; enable Allow parallel to create a new one anyway")

        job_id = timestamp_id("J")
        sizing_constraints = LARGE_TASK_CONSTRAINTS if worker in CAPABLE_WORKERS else SMALL_TASK_CONSTRAINTS
        all_constraints = [*sizing_constraints, *COMMON_CONSTRAINTS, *constraints]
        all_acceptance = [*DEFAULT_ACCEPTANCE, *acceptance]
        worktree = repo
        branch: str | None = None
        overlay_files: list[str] = []
        pre_job_commit: dict[str, str | bool | None]

        pre_job_commit = create_pre_job_commit(repo, job_id)
        if use_worktree:
            worktree, branch = create_worktree(repo, self.settings.runs_dir, job_id, base_ref)
            overlay_files = copy_checkout_overlay(repo, worktree)

        with db.transaction(self.settings.db_path) as conn:
            db.create_job(
                conn,
                job_id=job_id,
                repo_path=str(repo),
                worktree_path=str(worktree),
                branch=branch,
                base_ref=base_ref,
                goal=goal,
                constraints=all_constraints,
                acceptance=all_acceptance,
                test_cmd=detected_test_cmd,
                max_iterations=max_iterations,
                use_worktree=use_worktree,
                worker=worker,
                controller=controller,
            )
            db.add_event(
                conn,
                job_id=job_id,
                kind="job_created_from_gui",
                payload={
                    "job_id": job_id,
                    "worktree_path": str(worktree),
                    "worker": worker,
                    "controller": controller,
                    "pre_job_commit": pre_job_commit,
                    "checkout_overlay_files": overlay_files,
                },
            )

        self.queue_plan(job_id)
        pids = self.launch_processes(job_id, models)
        with db.transaction(self.settings.db_path) as conn:
            db.add_event(
                conn,
                job_id=job_id,
                kind="job_processes_started_from_gui",
                payload={"pids": pids},
            )
        return job_id

    def resume_job(
        self,
        job_id: str,
        *,
        worker: str | None,
        controller: str | None,
        models: ModelDefaults,
        extra_constraint: str = "",
        extra_acceptance: str = "",
    ) -> None:
        with db.transaction(self.settings.db_path) as conn:
            job = db.get_job(conn, job_id)
            constraints = list(job["constraints"])
            acceptance = list(job["acceptance"])
            if extra_constraint.strip():
                constraints.append(extra_constraint.strip())
            if extra_acceptance.strip():
                acceptance.append(extra_acceptance.strip())
            new_worker = normalize_worker(worker or str(job["worker"]))
            new_controller = normalize_controller(controller or str(job["controller"]))
            conn.execute(
                """
                UPDATE jobs
                SET worker = ?, controller = ?, constraints_json = ?, acceptance_json = ?,
                    status = 'planning', updated_at = ?
                WHERE id = ?
                """,
                (
                    new_worker,
                    new_controller,
                    db.to_json(constraints),
                    db.to_json(acceptance),
                    db.utc_now(),
                    job_id,
                ),
            )
            db.add_event(
                conn,
                job_id=job_id,
                kind="job_resumed_from_gui",
                payload={"worker": new_worker, "controller": new_controller},
            )
        self.queue_plan(job_id)
        self.launch_processes(job_id, models)

    def mark_stopped(self, job_id: str) -> None:
        with db.transaction(self.settings.db_path) as conn:
            job = db.get_job(conn, job_id)
            if str(job["status"]) in ACTIVE_STATUSES:
                db.update_job_status(
                    conn,
                    job_id,
                    "human_needed",
                    f"Stopped from Tkinter GUI while job was {job['status']}. Resume to continue.",
                )
                db.add_event(conn, job_id=job_id, kind="job_stopped_from_gui", payload={})

    def delete_job(self, job_id: str) -> None:
        self.stop_processes(job_id)
        with db.transaction(self.settings.db_path) as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def reset_loop(self) -> None:
        for job in self.list_jobs():
            self.stop_processes(str(job["id"]))
        with db.transaction(self.settings.db_path) as conn:
            conn.execute("DELETE FROM events")
            conn.execute("DELETE FROM decisions")
            conn.execute("DELETE FROM runs")
            conn.execute("DELETE FROM tasks")
            conn.execute("DELETE FROM jobs")
        with db.connect(self.settings.db_path) as conn:
            conn.execute("VACUUM")

    def known_repo_paths(self) -> list[Path]:
        paths: list[Path] = []
        if not self.settings.db_path.is_file():
            return paths
        with db.transaction(self.settings.db_path) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT repo_path
                FROM jobs
                WHERE repo_path IS NOT NULL AND repo_path != ''
                ORDER BY repo_path
                """
            ).fetchall()
        for row in rows:
            path = Path(str(row["repo_path"])).expanduser()
            if path not in paths:
                paths.append(path)
        return paths

    def remove_ai_worktrees(self, force: bool = True) -> dict[str, Any]:
        runs_dir = self.settings.runs_dir.resolve()
        repos = self.known_repo_paths()
        removed_worktrees: list[str] = []
        pruned_repos: list[str] = []
        skipped_repos: list[str] = []
        leftover_folders: list[str] = []

        for repo in repos:
            if not ((repo / ".git").exists() or (repo / ".git").is_file()):
                skipped_repos.append(str(repo))
                continue
            worktree_output = subprocess.run(
                ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                text=True,
                capture_output=True,
                check=False,
            )
            if worktree_output.returncode != 0:
                skipped_repos.append(f"{repo}: {worktree_output.stderr.strip() or worktree_output.stdout.strip()}")
                continue
            worktrees: list[Path] = []
            for line in worktree_output.stdout.splitlines():
                if not line.startswith("worktree "):
                    continue
                worktree = Path(line[len("worktree ") :]).expanduser().resolve()
                try:
                    worktree.relative_to(runs_dir)
                except ValueError:
                    continue
                worktrees.append(worktree)

            remove_args = ["git", "-C", str(repo), "worktree", "remove"]
            if force:
                remove_args.append("--force")
            for worktree in worktrees:
                result = subprocess.run(
                    [*remove_args, str(worktree)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"failed to remove worktree {worktree}: {result.stderr.strip() or result.stdout.strip()}"
                    )
                removed_worktrees.append(str(worktree))

            subprocess.run(["git", "-C", str(repo), "worktree", "prune"], check=False)
            pruned_repos.append(str(repo))

        if runs_dir.is_dir():
            for child in sorted(runs_dir.iterdir()):
                if not child.is_dir():
                    continue
                resolved = child.resolve()
                try:
                    resolved.relative_to(runs_dir)
                except ValueError as exc:
                    raise RuntimeError(f"refusing to delete path outside runs dir: {resolved}") from exc
                shutil.rmtree(resolved)
                leftover_folders.append(str(resolved))

        return {
            "runs_dir": str(runs_dir),
            "removed_worktrees": removed_worktrees,
            "leftover_folders": leftover_folders,
            "pruned_repos": pruned_repos,
            "skipped_repos": skipped_repos,
        }

    def full_reset(self) -> dict[str, Any]:
        reset_summary: dict[str, Any] = {"stopped_jobs": []}
        for job in self.list_jobs():
            job_id = str(job["id"])
            self.stop_processes(job_id)
            reset_summary["stopped_jobs"].append(job_id)
        reset_summary["worktrees"] = self.remove_ai_worktrees(force=True)
        self.reset_loop()
        return reset_summary

    def log_text(self, job_id: str, name: str, max_bytes: int = 60000) -> str:
        path = self.log_dir(job_id) / f"{name}.log"
        if not path.is_file():
            return f"No log file: {path}"
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                prefix = f"... truncated to last {max_bytes} bytes ...\n"
            else:
                prefix = ""
            data = handle.read().decode("utf-8", errors="replace")
        return prefix + data


class AiLoopGui(tk.Tk):
    def __init__(self, theme: str = "default") -> None:
        super().__init__()
        self.title(APP_WINDOW_TITLE)
        self.geometry("1280x820")
        self.apply_theme(theme)
        self.backend = LoopBackend()
        self.model_defaults = self.backend.model_defaults()
        self.selected_job_id: str | None = None
        self.watch_job_id: str | None = None
        self.last_status_by_job: dict[str, str] = {}
        self.alerted_human_needed: set[str] = set()
        self.auto_refresh = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value=f"DB: {self.backend.settings.db_path}")
        self._build_ui()
        self.refresh_all()
        self.after(3000, self._auto_refresh_tick)

    def apply_theme(self, theme: str) -> None:
        if theme in {"", "default", "native", "current"}:
            return
        style = ttk.Style(self)
        available = tuple(style.theme_names())
        if theme not in available:
            raise ValueError(f"unknown Tk theme: {theme!r}; available themes: {', '.join(available)}")
        style.theme_use(theme)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Button(toolbar, text="Refresh", command=self.refresh_all).grid(row=0, column=0, padx=(0, 6))
        ttk.Checkbutton(toolbar, text="Auto refresh", variable=self.auto_refresh).grid(row=0, column=1, padx=(0, 14))
        ttk.Button(toolbar, text="Start Redis", command=self.start_redis).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(toolbar, text="Stop Job", command=self.stop_selected_job).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(toolbar, text="Resume Job", command=self.resume_selected_job).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(toolbar, text="Wait/Notify", command=self.watch_selected_job).grid(row=0, column=5, padx=(0, 6))
        ttk.Button(toolbar, text="Delete Job", command=self.delete_selected_job).grid(row=0, column=6, padx=(0, 6))
        ttk.Button(toolbar, text="Clear Worktrees", command=self.clear_worktrees).grid(row=0, column=7, padx=(0, 6))
        ttk.Button(toolbar, text="Reset DB", command=self.reset_loop).grid(row=0, column=8, padx=(0, 6))
        ttk.Button(toolbar, text="Full Reset", command=self.full_reset).grid(row=0, column=9, padx=(0, 14))
        ttk.Button(toolbar, text="Hibernation", command=self.open_hibernation_window).grid(row=0, column=10, padx=(0, 14))
        toolbar.columnconfigure(0, weight=0)
        toolbar.columnconfigure(10, weight=1)
        ttk.Label(toolbar, text="Status:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        status_label = ttk.Label(toolbar, textvariable=self.status_var, anchor="w")
        status_label.grid(row=1, column=1, columnspan=10, sticky="ew", pady=(6, 0))

        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.grid(row=1, column=0, sticky="nsew")

        left = ttk.Frame(paned, padding=8)
        right = ttk.Frame(paned, padding=8)
        paned.add(left, weight=1)
        paned.add(right, weight=2)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self._build_create_frame(left)
        self._build_jobs_frame(left)
        self._build_detail_frame(right)

    def _build_create_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Create Job", padding=8)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(1, weight=1)

        self.repo_var = tk.StringVar(value=str(Path.cwd()))
        self.test_cmd_var = tk.StringVar(value="auto")
        self.base_ref_var = tk.StringVar(value="HEAD")
        self.max_iterations_var = tk.IntVar(value=50000)
        self.worker_var = tk.StringVar(value=self.backend.settings.worker_default)
        self.controller_var = tk.StringVar(value=self.backend.settings.controller_default)
        self.no_worktree_var = tk.BooleanVar(value=False)
        self.allow_parallel_var = tk.BooleanVar(value=False)
        self.fable_model_var = tk.StringVar(value=self.model_defaults.fable_model)
        self.opus_model_var = tk.StringVar(value=self.model_defaults.opus_model)
        self.controller_model_var = tk.StringVar(value=self.model_defaults.controller_model)
        self.codex_bin_var = tk.StringVar(value=self.model_defaults.codex_bin)
        self.claude_bin_var = tk.StringVar(value=self.model_defaults.claude_bin)
        self.bypass_var = tk.BooleanVar(value=self.model_defaults.codex_bypass_sandbox)

        ttk.Label(frame, text="Repo").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.repo_var).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(frame, text="Browse", command=self.browse_repo_or_goal_file).grid(row=0, column=2)

        ttk.Label(frame, text="Goal").grid(row=1, column=0, sticky="nw", pady=(6, 0))
        self.goal_text = tk.Text(frame, height=5, wrap="word")
        self.goal_text.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(6, 0))

        ttk.Label(frame, text="Test").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(frame, textvariable=self.test_cmd_var).grid(row=2, column=1, columnspan=2, sticky="ew", pady=(6, 0))

        settings = ttk.Frame(frame)
        settings.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)

        label_width = 17
        ttk.Label(settings, text="Controller", width=label_width).grid(row=0, column=0, sticky="w")
        ttk.Combobox(settings, textvariable=self.controller_var, values=sorted(CONTROLLERS), width=12, state="readonly").grid(
            row=0, column=1, sticky="ew", padx=(4, 10)
        )
        ttk.Label(settings, text="Worker", width=label_width).grid(row=0, column=2, sticky="w")
        ttk.Combobox(settings, textvariable=self.worker_var, values=sorted(WORKERS), width=12, state="readonly").grid(
            row=0, column=3, sticky="ew", padx=(4, 0)
        )

        ttk.Label(settings, text="Base ref", width=label_width).grid(row=1, column=0, sticky="w", pady=(5, 0))
        ttk.Entry(settings, textvariable=self.base_ref_var).grid(row=1, column=1, sticky="ew", padx=(4, 10), pady=(5, 0))
        ttk.Label(settings, text="Max iterations", width=label_width).grid(row=1, column=2, sticky="w", pady=(5, 0))
        ttk.Spinbox(settings, from_=1, to=50000, textvariable=self.max_iterations_var).grid(
            row=1, column=3, sticky="ew", padx=(4, 0), pady=(5, 0)
        )

        ttk.Label(settings, text="Fable model", width=label_width).grid(row=2, column=0, sticky="w", pady=(5, 0))
        ttk.Entry(settings, textvariable=self.fable_model_var).grid(
            row=2, column=1, columnspan=3, sticky="ew", padx=(4, 0), pady=(5, 0)
        )
        ttk.Label(settings, text="Opus model", width=label_width).grid(row=3, column=0, sticky="w", pady=(5, 0))
        ttk.Entry(settings, textvariable=self.opus_model_var).grid(
            row=3, column=1, columnspan=3, sticky="ew", padx=(4, 0), pady=(5, 0)
        )
        ttk.Label(settings, text="Controller model", width=label_width).grid(row=4, column=0, sticky="w", pady=(5, 0))
        ttk.Entry(settings, textvariable=self.controller_model_var).grid(
            row=4, column=1, columnspan=3, sticky="ew", padx=(4, 0), pady=(5, 0)
        )

        ttk.Label(settings, text="Codex binary", width=label_width).grid(row=5, column=0, sticky="w", pady=(5, 0))
        ttk.Entry(settings, textvariable=self.codex_bin_var).grid(
            row=5, column=1, columnspan=3, sticky="ew", padx=(4, 0), pady=(5, 0)
        )
        ttk.Label(settings, text="Claude binary", width=label_width).grid(row=6, column=0, sticky="w", pady=(5, 0))
        ttk.Entry(settings, textvariable=self.claude_bin_var).grid(
            row=6, column=1, columnspan=3, sticky="ew", padx=(4, 0), pady=(5, 0)
        )

        toggles = ttk.Frame(settings)
        toggles.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        ttk.Checkbutton(toggles, text="Codex bypass sandbox", variable=self.bypass_var).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(toggles, text="No worktree", variable=self.no_worktree_var).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(toggles, text="Allow parallel", variable=self.allow_parallel_var).pack(side="left")
        ttk.Button(toggles, text="Create Job", command=self.create_job).pack(side="right")

    def _build_jobs_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Jobs", padding=6)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        columns = ("status", "progress", "controller", "worker", "tasks", "runs", "updated")
        self.jobs_tree = ttk.Treeview(frame, columns=columns, show="tree headings", selectmode="browse")
        self.jobs_tree.heading("#0", text="Job")
        self.jobs_tree.column("#0", width=190, stretch=False)
        for name, width in (
            ("status", 95),
            ("progress", 70),
            ("controller", 80),
            ("worker", 70),
            ("tasks", 55),
            ("runs", 55),
            ("updated", 145),
        ):
            self.jobs_tree.heading(name, text=name.title())
            self.jobs_tree.column(name, width=width, stretch=False)
        self.jobs_tree.grid(row=0, column=0, sticky="nsew")
        self.jobs_tree.tag_configure("planning", background="#e8f1ff")
        self.jobs_tree.tag_configure("queued", background="#f2f2f2")
        self.jobs_tree.tag_configure("implementing", background="#ffe6bf")
        self.jobs_tree.tag_configure("fixing", background="#fff4db")
        self.jobs_tree.tag_configure("human_needed", background="#ffe1df")
        self.jobs_tree.tag_configure("dead", background="#f2d3d3")
        self.jobs_tree.tag_configure("done", background="#dff3df")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.jobs_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.jobs_tree.configure(yscrollcommand=scrollbar.set)
        self.jobs_tree.bind("<<TreeviewSelect>>", self.on_job_selected)

    def _build_detail_frame(self, parent: ttk.Frame) -> None:
        notebook = ttk.Notebook(parent)
        notebook.grid(row=0, column=0, sticky="nsew")

        overview = ttk.Frame(notebook, padding=8)
        logs = ttk.Frame(notebook, padding=8)
        history = ttk.Frame(notebook, padding=8)
        notebook.add(overview, text="Overview")
        notebook.add(logs, text="Logs")
        notebook.add(history, text="Tasks/Runs")

        overview.rowconfigure(1, weight=1)
        overview.columnconfigure(0, weight=1)
        self.summary_var = tk.StringVar(value="Select a job.")
        self.summary_label = ttk.Label(
            overview,
            textvariable=self.summary_var,
            font=("", 12, "bold"),
            justify="left",
            anchor="w",
        )
        self.summary_label.grid(row=0, column=0, sticky="ew")
        overview.bind("<Configure>", self.update_summary_wrap)
        self.detail_text = tk.Text(overview, wrap="word")
        self.detail_text.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

        resume_frame = ttk.LabelFrame(overview, text="Resume / Change Controller", padding=8)
        resume_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        for column in range(6):
            resume_frame.columnconfigure(column, weight=1)
        self.resume_controller_var = tk.StringVar(value=self.controller_var.get())
        self.resume_worker_var = tk.StringVar(value=self.worker_var.get())
        self.extra_constraint_var = tk.StringVar()
        self.extra_acceptance_var = tk.StringVar()
        ttk.Label(resume_frame, text="Controller").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            resume_frame,
            textvariable=self.resume_controller_var,
            values=sorted(CONTROLLERS),
            width=10,
            state="readonly",
        ).grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Label(resume_frame, text="Worker").grid(row=0, column=2, sticky="w")
        ttk.Combobox(resume_frame, textvariable=self.resume_worker_var, values=sorted(WORKERS), width=10, state="readonly").grid(
            row=0, column=3, sticky="ew", padx=3
        )
        ttk.Button(resume_frame, text="Apply + Resume", command=self.resume_selected_job).grid(row=0, column=4, columnspan=2, sticky="e")
        ttk.Label(resume_frame, text="Extra constraint").grid(row=1, column=0, sticky="w", pady=(5, 0))
        ttk.Entry(resume_frame, textvariable=self.extra_constraint_var).grid(row=1, column=1, columnspan=5, sticky="ew", pady=(5, 0))
        ttk.Label(resume_frame, text="Extra acceptance").grid(row=2, column=0, sticky="w", pady=(5, 0))
        ttk.Entry(resume_frame, textvariable=self.extra_acceptance_var).grid(row=2, column=1, columnspan=5, sticky="ew", pady=(5, 0))

        logs.rowconfigure(1, weight=1)
        logs.columnconfigure(0, weight=1)
        log_bar = ttk.Frame(logs)
        log_bar.grid(row=0, column=0, sticky="ew")
        self.log_name_var = tk.StringVar(value="codex_worker")
        ttk.Combobox(log_bar, textvariable=self.log_name_var, values=list(PROCESS_NAMES), state="readonly", width=20).grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(log_bar, text="Refresh Log", command=self.refresh_log).grid(row=0, column=1)
        self.log_text = tk.Text(logs, wrap="none")
        self.log_text.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

        history.rowconfigure(0, weight=1)
        history.columnconfigure(0, weight=1)
        self.history_text = tk.Text(history, wrap="word")
        self.history_text.grid(row=0, column=0, sticky="nsew")

    def current_models(self) -> ModelDefaults:
        return ModelDefaults(
            fable_model=self.fable_model_var.get().strip() or "claude-fable-5",
            opus_model=self.opus_model_var.get().strip() or "opus",
            controller_model=self.controller_model_var.get().strip(),
            codex_bin=self.codex_bin_var.get().strip() or "codex",
            claude_bin=self.claude_bin_var.get().strip() or "claude",
            codex_bypass_sandbox=bool(self.bypass_var.get()),
        )

    def browse_repo_or_goal_file(self) -> None:
        selected = filedialog.askopenfilename(
            initialdir=self.repo_var.get() or str(Path.home()),
            title="Choose a goal text file, or cancel to choose a repository folder",
            filetypes=(("Text files", "*.txt *.md *.rst *.adoc"), ("All files", "*")),
        )
        if selected:
            path = Path(selected)
            self.repo_var.set(str(path.parent))
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = path.read_text(errors="replace")
            self.goal_text.delete("1.0", "end")
            self.goal_text.insert("1.0", content)
            return

        selected_dir = filedialog.askdirectory(initialdir=self.repo_var.get() or str(Path.home()), title="Choose repository folder")
        if selected_dir:
            self.repo_var.set(selected_dir)

    def create_job(self) -> None:
        goal = self.goal_text.get("1.0", "end").strip()
        if not goal:
            messagebox.showerror("Missing Goal", "Enter a job goal.")
            return
        try:
            job_id = self.backend.create_job(
                repo=Path(self.repo_var.get()),
                goal=goal,
                test_cmd=self.test_cmd_var.get().strip() or "auto",
                constraints=[],
                acceptance=[],
                max_iterations=int(self.max_iterations_var.get()),
                base_ref=self.base_ref_var.get().strip() or "HEAD",
                use_worktree=not self.no_worktree_var.get(),
                allow_parallel=self.allow_parallel_var.get(),
                worker=self.worker_var.get(),
                controller=self.controller_var.get(),
                models=self.current_models(),
            )
        except Exception as exc:
            messagebox.showerror("Create Job Failed", str(exc))
            return
        self.watch_job_id = job_id
        self.refresh_all(select_job_id=job_id)

    def refresh_all(self, select_job_id: str | None = None) -> None:
        try:
            jobs = self.backend.list_jobs()
        except Exception as exc:
            self.status_var.set(f"Refresh failed: {exc}")
            return

        selected = select_job_id or self.selected_job_id
        self.jobs_tree.delete(*self.jobs_tree.get_children())
        for job in jobs:
            job_id = str(job["id"])
            task = job.get("latest_task") or {}
            values = (
                job["status"],
                f"{job['percent']}%",
                job["controller"],
                job["worker"],
                job["task_count"],
                job["run_count"],
                job["updated_at"],
            )
            status = str(job["status"])
            self.jobs_tree.insert("", "end", iid=job_id, text=job_id, values=values, tags=(status,))
            previous = self.last_status_by_job.get(job_id)
            self.last_status_by_job[job_id] = status
            if status != "human_needed":
                self.alerted_human_needed.discard(job_id)
            if status == "human_needed" and job_id not in self.alerted_human_needed:
                self.alerted_human_needed.add(job_id)
                self.show_human_needed_alert(job)
            if self.watch_job_id == job_id and status in TERMINAL_STATUSES and previous and previous != status:
                messagebox.showinfo("Watched Job Finished", f"{job_id} is now {status}.")
            if task:
                self.jobs_tree.insert(
                    job_id,
                    "end",
                    text=str(task.get("id")),
                    values=(task.get("status"), "", "", "", "", "", task.get("updated_at")),
                    tags=(status,),
                )

        if selected and self.jobs_tree.exists(selected):
            self.jobs_tree.selection_set(selected)
            self.jobs_tree.focus(selected)
            self.selected_job_id = selected
            self.show_job(selected)
        elif jobs:
            first = str(jobs[0]["id"])
            self.jobs_tree.selection_set(first)
            self.jobs_tree.focus(first)
            self.selected_job_id = first
            self.show_job(first)
        else:
            self.selected_job_id = None
            self.summary_var.set("No jobs.")
            self.set_text(self.detail_text, "")
            self.set_text(self.history_text, "")
            self.set_text(self.log_text, "")
        self.update_system_status(jobs)

    def update_system_status(self, jobs: list[dict[str, Any]] | None = None) -> None:
        try:
            if jobs is None:
                jobs = self.backend.list_jobs()
            active = sum(1 for job in jobs if str(job["status"]) in ACTIVE_STATUSES)
            human_needed = sum(1 for job in jobs if str(job["status"]) == "human_needed")
            dead = sum(1 for job in jobs if str(job["status"]) == "dead")
            done = sum(1 for job in jobs if str(job["status"]) == "done")
            running_processes = 0
            stale_processes = 0
            for job in jobs:
                for info in self.backend.process_status(str(job["id"])).values():
                    if info["running"]:
                        running_processes += 1
                    elif info["pid"]:
                        stale_processes += 1
            redis_state = "online" if self.backend.redis_running() else "offline"
            self.status_var.set(
                f"Redis {redis_state} | jobs {len(jobs)} | active {active} | "
                f"human needed {human_needed} | dead {dead} | done {done} | "
                f"processes running {running_processes}, stale {stale_processes}"
            )
        except Exception as exc:
            self.status_var.set(f"System status unavailable: {exc}")

    def start_redis(self) -> None:
        try:
            pid = self.backend.start_redis_server()
        except Exception as exc:
            messagebox.showerror("Start Redis Failed", str(exc))
            return
        self.refresh_all()

    def _auto_refresh_tick(self) -> None:
        if self.auto_refresh.get():
            self.refresh_all()
        self.after(3000, self._auto_refresh_tick)

    def on_job_selected(self, _event: object) -> None:
        item = self.jobs_tree.focus()
        if not item:
            return
        parent = self.jobs_tree.parent(item)
        job_id = parent or item
        self.selected_job_id = job_id
        self.show_job(job_id)

    def show_job(self, job_id: str) -> None:
        try:
            details = self.backend.job_details(job_id)
        except Exception as exc:
            self.summary_var.set(f"Could not load {job_id}: {exc}")
            return
        job = details["job"]
        self.resume_controller_var.set(str(job["controller"]))
        self.resume_worker_var.set(str(job["worker"]))
        self.summary_var.set(
            f"{job_id}  {job['status']}  controller={job['controller']} worker={job['worker']} updated={job['updated_at']}"
        )
        process_lines = [
            f"{name}: {'running' if info['running'] else 'stopped'} pid={info['pid'] or '-'}"
            for name, info in details["processes"].items()
        ]
        latest_decision = details["decisions"][0] if details["decisions"] else None
        text = [
            f"Repo: {job['repo_path']}",
            f"Worktree: {job['worktree_path']}",
            f"Branch: {job['branch'] or '-'}",
            f"Base ref: {job['base_ref']}",
            f"Test command: {job['test_cmd']}",
            "",
            "Processes:",
            *process_lines,
            "",
            "History summary:",
            str(job["history_summary"] or ""),
            "",
            "Goal:",
            str(job["goal"]),
        ]
        if latest_decision:
            text.extend(["", "Latest decision:", f"{latest_decision['action']}: {latest_decision['reason']}"])
        if str(job["status"]) == "human_needed":
            text.extend(["", "Suggested actions:", *self.human_needed_actions(job, details)])
        self.set_text(self.detail_text, "\n".join(text))

        history_lines: list[str] = ["Tasks:"]
        for task in details["tasks"]:
            history_lines.append(f"- iter {task['iteration']} {task['id']} {task['status']} updated={task['updated_at']}")
            history_lines.append(f"  {task['goal']}")
        history_lines.append("")
        history_lines.append("Runs:")
        for run in details["runs"]:
            history_lines.append(
                f"- iter {run['iteration']} {run['id']} {run['status']} codex_rc={run['codex_rc']} test_rc={run['test_rc']} finished={run['finished_at']}"
            )
            if run.get("error"):
                history_lines.append(f"  error: {run['error']}")
            if run.get("diff_stat"):
                history_lines.append(f"  diff: {run['diff_stat'].strip()}")
        history_lines.append("")
        history_lines.append("Recent events:")
        for event in details["events"]:
            history_lines.append(f"- {event['created_at']} {event['kind']} {event['payload_json']}")
        self.set_text(self.history_text, "\n".join(history_lines))
        self.refresh_log()

    def update_summary_wrap(self, event: tk.Event) -> None:
        width = max(240, int(getattr(event, "width", 600)) - 20)
        self.summary_label.configure(wraplength=width)

    def human_needed_actions(self, job: dict[str, Any], details: dict[str, Any]) -> list[str]:
        actions = [
            "- Inspect the latest controller and worker logs in the Logs tab.",
            "- Read the latest decision reason and history summary above.",
            "- Choose controller/worker values in Resume / Change Controller, then click Apply + Resume.",
            "- Add an extra constraint or acceptance criterion before resuming if the next step needs correction.",
            "- Click Stop Job if stale processes are still running.",
            "- Click Clear Worktrees if generated worktrees are no longer needed.",
            "- Use Full Reset only when you want to stop everything, remove worktrees, and clear all job records.",
        ]
        processes = details.get("processes", {})
        if any(info.get("running") for info in processes.values()):
            actions.insert(0, "- Some job processes appear to be running; stop them before manual cleanup if they look stuck.")
        latest_run = details["runs"][0] if details.get("runs") else None
        if latest_run and (latest_run.get("codex_rc") not in {0, None} or latest_run.get("test_rc") not in {0, None}):
            actions.insert(0, "- Latest run or test command failed; inspect the latest run output in Tasks/Runs and worker log.")
        if str(job.get("controller")) != "opus":
            actions.append("- Consider switching the controller to opus before resuming.")
        return actions

    def show_human_needed_alert(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        summary = str(job.get("history_summary") or "").strip()
        if len(summary) > 700:
            summary = summary[:697] + "..."
        actions = [
            "1. Inspect the Logs tab for controller/worker output.",
            "2. Select controller/worker choices and click Apply + Resume.",
            "3. Add a constraint or acceptance criterion if needed.",
            "4. Stop stale processes or run Full Reset if the loop is unrecoverable.",
        ]
        message = f"Job {job_id} needs human input.\n\n"
        if summary:
            message += f"Reason/history:\n{summary}\n\n"
        message += "Possible actions:\n" + "\n".join(actions)
        messagebox.showwarning("Human Needed", message)

    def refresh_log(self) -> None:
        if not self.selected_job_id:
            return
        try:
            text = self.backend.log_text(self.selected_job_id, self.log_name_var.get())
        except Exception as exc:
            text = f"Could not read log: {exc}"
        self.set_text(self.log_text, text)
        self.log_text.see("end")

    @staticmethod
    def set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)

    def selected_job_or_error(self) -> str | None:
        if not self.selected_job_id:
            messagebox.showerror("No Job Selected", "Select a job first.")
            return None
        return self.selected_job_id

    def stop_selected_job(self) -> None:
        job_id = self.selected_job_or_error()
        if not job_id:
            return
        try:
            results = self.backend.stop_processes(job_id)
            self.backend.mark_stopped(job_id)
        except Exception as exc:
            messagebox.showerror("Stop Failed", str(exc))
            return
        self.refresh_all(select_job_id=job_id)

    def resume_selected_job(self) -> None:
        job_id = self.selected_job_or_error()
        if not job_id:
            return
        try:
            self.backend.resume_job(
                job_id,
                worker=self.resume_worker_var.get(),
                controller=self.resume_controller_var.get(),
                models=self.current_models(),
                extra_constraint=self.extra_constraint_var.get(),
                extra_acceptance=self.extra_acceptance_var.get(),
            )
        except Exception as exc:
            messagebox.showerror("Resume Failed", str(exc))
            return
        self.watch_job_id = job_id
        self.refresh_all(select_job_id=job_id)

    def watch_selected_job(self) -> None:
        job_id = self.selected_job_or_error()
        if job_id:
            self.watch_job_id = job_id
            self.status_var.set(f"Watching {job_id}")

    def delete_selected_job(self) -> None:
        job_id = self.selected_job_or_error()
        if not job_id:
            return
        if not messagebox.askyesno("Delete Job", f"Delete job record {job_id}? Worktree files are not removed."):
            return
        try:
            self.backend.delete_job(job_id)
        except Exception as exc:
            messagebox.showerror("Delete Failed", str(exc))
            return
        self.selected_job_id = None
        self.refresh_all()

    def reset_loop(self) -> None:
        if not messagebox.askyesno("Reset Loop", "Stop all job processes and clear all ai-loop database records?"):
            return
        try:
            self.backend.reset_loop()
        except Exception as exc:
            messagebox.showerror("Reset Failed", str(exc))
            return
        self.selected_job_id = None
        self.watch_job_id = None
        self.refresh_all()

    def clear_worktrees(self) -> None:
        runs_dir = self.backend.settings.runs_dir
        if not messagebox.askyesno(
            "Clear Worktrees",
            f"Remove all registered ai-loop worktrees and leftover folders under:\n\n{runs_dir}\n\nDatabase records are not deleted.",
        ):
            return
        try:
            summary = self.backend.remove_ai_worktrees(force=True)
        except Exception as exc:
            messagebox.showerror("Clear Worktrees Failed", str(exc))
            return
        removed = len(summary["removed_worktrees"])
        leftovers = len(summary["leftover_folders"])
        skipped = len(summary["skipped_repos"])
        messagebox.showinfo(
            "Clear Worktrees Complete",
            f"Runs dir: {summary['runs_dir']}\nRemoved worktrees: {removed}\nDeleted leftover folders: {leftovers}\nSkipped repos: {skipped}",
        )
        self.refresh_all()

    def full_reset(self) -> None:
        if not messagebox.askyesno(
            "Full Reset",
            "Stop all job processes, remove ai-loop worktrees, and clear all database records?",
        ):
            return
        try:
            summary = self.backend.full_reset()
        except Exception as exc:
            messagebox.showerror("Full Reset Failed", str(exc))
            return
        worktrees = summary["worktrees"]
        self.selected_job_id = None
        self.watch_job_id = None
        self.refresh_all()

    def hibernation_status_text(self) -> str:
        if platform.system() != "Darwin":
            return "Hibernation control is only available on macOS."
        pmset = shutil.which("pmset")
        if pmset is None:
            return "pmset was not found."
        result = subprocess.run([pmset, "-g"], text=True, capture_output=True, check=False)
        if result.returncode != 0:
            return result.stderr.strip() or result.stdout.strip() or "pmset failed."
        mode = "unavailable"
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "hibernatemode":
                mode = parts[1]
                break
        descriptions = {
            "0": "disabled",
            "3": "enabled (default portable mode)",
            "25": "enabled (deep hibernation mode)",
        }
        return f"hibernatemode: {mode}\nhibernation: {descriptions.get(mode, 'custom mode')}"

    def set_hibernation_mode(self, mode: int, parent: tk.Toplevel) -> None:
        if platform.system() != "Darwin":
            messagebox.showerror("Unsupported", "Hibernation control is only available on macOS.", parent=parent)
            return
        pmset = shutil.which("pmset")
        if pmset is None:
            messagebox.showerror("Missing pmset", "pmset was not found.", parent=parent)
            return
        action = "disable hibernation" if mode == 0 else "enable hibernation"
        if not messagebox.askyesno(
            "Confirm Hibernation Change",
            f"This will run:\n\nsudo pmset -a hibernatemode {mode}\n\nContinue to {action}?",
            parent=parent,
        ):
            return
        result = subprocess.run(
            ["sudo", pmset, "-a", "hibernatemode", str(mode)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            messagebox.showerror("Hibernation Change Failed", result.stderr.strip() or result.stdout.strip(), parent=parent)
            return
        self.open_hibernation_window(parent)
        self.refresh_all()

    def open_hibernation_window(self, existing: tk.Toplevel | None = None) -> None:
        if existing is not None:
            try:
                existing.destroy()
            except tk.TclError:
                pass
        window = tk.Toplevel(self)
        window.title("macOS Hibernation")
        window.geometry("460x220")
        window.columnconfigure(0, weight=1)
        text = tk.Text(window, height=6, wrap="word")
        text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        text.insert("1.0", self.hibernation_status_text())
        controls = ttk.Frame(window, padding=(10, 0, 10, 10))
        controls.grid(row=1, column=0, sticky="ew")
        ttk.Button(controls, text="Refresh", command=lambda: self.open_hibernation_window(window)).pack(side="left")
        ttk.Button(controls, text="Disable", command=lambda: self.set_hibernation_mode(0, window)).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="Enable Deep", command=lambda: self.set_hibernation_mode(25, window)).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="Close", command=window.destroy).pack(side="right")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the ai-loop Tkinter GUI.")
    parser.add_argument(
        "--theme",
        default="default",
        help="Tk/ttk theme name. Use 'default' to keep the platform-native/current theme.",
    )
    parser.add_argument("--list-themes", action="store_true", help="Print available Tk/ttk themes and exit.")
    return parser.parse_args()


def list_themes() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        style = ttk.Style(root)
        print("\n".join(style.theme_names()))
    finally:
        root.destroy()


def main() -> int:
    args = parse_args()
    if args.list_themes:
        list_themes()
        return 0
    try:
        app = AiLoopGui(theme=args.theme)
    except Exception as exc:
        messagebox.showerror("ai-loop GUI failed to start", str(exc))
        return 1
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
