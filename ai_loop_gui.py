from __future__ import annotations

import sys

if sys.version_info < (3, 10):
    sys.stderr.write("ai_loop_gui.py requires Python 3.10 or newer; you are running Python %d.%d.\n" % sys.version_info[:2])
    sys.exit(1)

import os
import argparse
import json
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from dataclasses import asdict
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
        raise RuntimeError(
            "ai-loop GUI restarted after dependency installation, but Python still cannot import 'redis'.\n"
            f"Usual manual fix: {sys.executable} -m pip install redis"
        )

    root_dir = Path(__file__).resolve().parent
    venv_dir = root_dir / ".gui-venv"
    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def venv_python_works() -> bool:
        if not venv_python.exists():
            return False
        try:
            subprocess.run(
                [str(venv_python), "-c", "import sys"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            return True
        except (OSError, subprocess.SubprocessError):
            return False

    def create_venv(*, clear: bool = False) -> None:
        cmd = [sys.executable, "-m", "venv"]
        if clear:
            cmd.append("--clear")
        cmd.append(str(venv_dir))
        subprocess.check_call(cmd)

    def venv_has_redis() -> bool:
        if not venv_python_works():
            return False
        try:
            subprocess.run(
                [str(venv_python), "-c", "import redis"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            return True
        except (OSError, subprocess.SubprocessError):
            return False

    manual_command = f"{venv_python} -m pip install redis"
    try:
        if not venv_python.exists():
            create_venv()
        elif not venv_python_works():
            create_venv(clear=True)

        if not venv_has_redis():
            subprocess.check_call([str(venv_python), "-m", "ensurepip", "--upgrade"])
            subprocess.check_call([str(venv_python), "-m", "pip", "install", "redis"])
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "ai-loop GUI could not install the Python 'redis' package.\n"
            f"Error: {exc}\n"
            f"Usual manual fix: {manual_command}"
        ) from exc
    env = os.environ.copy()
    env["AI_LOOP_GUI_BOOTSTRAPPED"] = "1"
    os.execve(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]], env)


bootstrap_python_dependencies()

import redis as redis_module


from ai_loop import db
from ai_loop.auth import (
    AuthRecoveryResult,
    AuthRequirement,
    authenticate_provider,
    find_auth_requirement,
    provider_display_name,
    provider_for_role,
)
from ai_loop.config import (
    load_settings,
    normalize_controller,
    normalize_worker,
    sanitized_child_env,
)
from ai_loop.progress import estimate_progress
from ai_loop.elicitation import CliStructuredOutputProvider
from ai_loop.specification_gui import VerificationDashboardView, open_specification_editor
from ai_loop.specification_workflow import derive_formal_job_inputs
from ai_loop.gui_components import HoverTooltip, ModelDefaults
from ai_loop.project_analysis_view import (
    ProjectAnalysisController,
    ProjectTreeNode,
    add_project_analysis_exclusion,
    remove_project_analysis_exclusion,
)
from ai_loop.project_qa import (
    AvailableLlm,
    ask_project_question,
    discover_available_llms,
)
from ai_loop.systemd_sandbox import wrap_with_systemd_sandbox
from ai_loop.specifications import SpecificationService, StoredSpecificationVersion
from ai_loop.verification_orchestrator import (
    load_verification_dashboard_projection,
    record_manual_verification_acknowledgement,
)
from ai_loop.planning import (
    GRANULARITIES,
    build_static_plan,
    granularity_constraints,
    normalize_granularity,
    replace_granularity_constraints,
)
from ai_loop.queues import publish_controller_plan, publish_worker_task, redis_client
from ai_loop.notifications import MailAccessStatus, check_mail_access, delivery_outcome, job_started_email
from start_job import (
    COMMON_CONSTRAINTS,
    DEFAULT_ACCEPTANCE,
    active_jobs,
    copy_checkout_overlay,
    create_pre_job_commit,
    create_worktree,
    detect_test_cmd,
    timestamp_id,
)


ACTIVE_STATUSES = {"planning", "queued", "implementing", "fixing", "waiting_tokens"}
TERMINAL_STATUSES = {"done", "human_needed", "dead"}
PROCESS_NAMES = ("controller", "worker", "watcher")
PROVIDER_NPM_PACKAGES = {
    "codex": "@openai/codex",
    "claude": "@anthropic-ai/claude-code",
    "gemini": "@google/gemini-cli",
}
PROCESS_LABELS = {
    "controller": "controller",
    "worker": "worker",
    "watcher": "watcher",
}
LEGACY_PROCESS_NAMES = {"controller": "claude_controller", "worker": "codex_worker"}
PROCESS_KEYS_BY_LABEL = {label: name for name, label in PROCESS_LABELS.items()}
LOG_LABELS = tuple(PROCESS_LABELS[name] for name in PROCESS_NAMES)
JOB_STATUS_COLORS = {
    "planning": "#e8f1ff",
    "queued": "#f2f2f2",
    "implementing": "#ffe6bf",
    "fixing": "#fff4db",
    "waiting_tokens": "#e7def8",
    "human_needed": "#ffe1df",
    "dead": "#f2d3d3",
    "done": "#dff3df",
}
APP_WINDOW_TITLE = "AI-LOOP - Prof. Helmut Hlavacs, University of Vienna and Robimo GmbH (https://robimo.at/), Vienna, Austria"
BINARY_CHOICES = ("codex", "claude", "gemini")


class LoopBackend:
    def __init__(self) -> None:
        self.settings = load_settings()
        db.init_db(self.settings.db_path)
        # Cached short-timeout Redis client plus the last known reachability
        # sample. The Tk main thread must only ever read the sample; the real
        # network PING happens in background threads (see redis_running).
        self._redis_client: redis_module.Redis | None = None
        self._redis_lock = threading.Lock()
        self._redis_last_ok = False
        self._redis_last_checked = 0.0

    @property
    def root_dir(self) -> Path:
        return self.settings.root_dir

    def model_defaults(self) -> ModelDefaults:
        return ModelDefaults(
            codex_model=self.settings.codex_model,
            fable_model=self.settings.fable_model,
            opus_model=self.settings.opus_model,
            gemini_model=self.settings.gemini_model,
            controller_model=self.settings.controller_model,
            codex_bin=self.settings.codex_bin,
            claude_bin=self.settings.claude_bin,
            gemini_bin=self.settings.gemini_bin,
            codex_bypass_sandbox=self.settings.codex_bypass_sandbox,
            controller_role_model=self.settings.controller_role_model,
            worker_role_model=self.settings.worker_role_model,
        )

    @staticmethod
    def _command_error(command: list[str], result: subprocess.CompletedProcess[str]) -> str:
        output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part and part.strip())
        if len(output) > 2000:
            output = output[-2000:]
        detail = output or f"command exited with status {result.returncode}"
        return f"{shlex.join(command)}: {detail}"

    @staticmethod
    def _privileged_command(command: list[str]) -> list[str]:
        if os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0):
            return command
        sudo = shutil.which("sudo")
        return [sudo, *command] if sudo else command

    @classmethod
    def install_npm(cls) -> None:
        if shutil.which("npm"):
            return
        system = platform.system()
        if system == "Darwin" and shutil.which("brew"):
            command = ["brew", "install", "node"]
            manual = "brew install node"
        elif shutil.which("apt-get"):
            command = cls._privileged_command(["apt-get", "install", "-y", "npm"])
            manual = "sudo apt-get update && sudo apt-get install -y npm"
        elif shutil.which("dnf"):
            command = cls._privileged_command(["dnf", "install", "-y", "npm"])
            manual = "sudo dnf install -y npm"
        elif shutil.which("pacman"):
            command = cls._privileged_command(["pacman", "-S", "--needed", "--noconfirm", "npm"])
            manual = "sudo pacman -S --needed npm"
        elif system == "Windows" and shutil.which("winget"):
            command = ["winget", "install", "--id", "OpenJS.NodeJS.LTS", "-e"]
            manual = "winget install --id OpenJS.NodeJS.LTS -e"
        else:
            raise RuntimeError(
                "npm is required to install the selected AI provider CLI, but no supported "
                "package manager was found.\nUsual manual fix: install Node.js from https://nodejs.org/"
            )
        result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=600)
        if result.returncode != 0 or not shutil.which("npm"):
            raise RuntimeError(
                "ai-loop GUI could not install npm.\n"
                f"Error: {cls._command_error(command, result)}\n"
                f"Usual manual fix: {manual}"
            )

    @classmethod
    def ensure_provider_cli(cls, provider: str, binary: str) -> None:
        if shutil.which(binary):
            return
        package = PROVIDER_NPM_PACKAGES[provider]
        manual = f"npm install -g {package}"
        if Path(binary).name != provider:
            raise RuntimeError(
                f"configured {provider} executable was not found: {binary}\n"
                f"Usual manual fix: {manual}, or correct the executable setting."
            )

        cls.install_npm()
        npm = shutil.which("npm") or "npm"
        command = [npm, "install", "-g", package]
        result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=600)
        if result.returncode != 0 or not shutil.which(binary):
            raise RuntimeError(
                f"ai-loop GUI could not install the {provider} CLI.\n"
                f"Error: {cls._command_error(command, result)}\n"
                f"Usual manual fix: {manual}"
            )

    @classmethod
    def ensure_provider_clis(
        cls,
        *,
        worker: str,
        controller: str,
        models: ModelDefaults,
    ) -> None:
        providers: dict[str, str] = {}
        for role in (worker, controller):
            provider = "claude" if role in {"fable", "opus", "claude"} else role
            if provider == "codex":
                providers[provider] = models.codex_bin
            elif provider == "claude":
                providers[provider] = models.claude_bin
            elif provider == "gemini":
                providers[provider] = models.gemini_bin
        for provider, binary in providers.items():
            cls.ensure_provider_cli(provider, binary)

    def ensure_worker_runtime(
        self,
        *,
        worker: str,
        models: ModelDefaults,
        writable_path: Path,
    ) -> None:
        """Fail before job creation if external worker confinement cannot exec."""

        if not getattr(self.settings, "codex_systemd_sandbox", False):
            return
        provider = provider_for_role(worker)
        binary = self.provider_binary(provider, models)
        command = wrap_with_systemd_sandbox(
            [binary, "--version"], writable_paths=[writable_path]
        )
        result = subprocess.run(
            command,
            cwd=str(writable_path),
            env=sanitized_child_env(),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            output = (result.stdout + "\n" + result.stderr).strip() or "<empty>"
            raise RuntimeError(
                "the external systemd worker sandbox could not start "
                f"{provider} (status {result.returncode}): {output[-4000:]}"
            )

    @staticmethod
    def provider_binary(provider: str, models: ModelDefaults) -> str:
        if provider == "claude":
            return models.claude_bin
        if provider == "codex":
            return models.codex_bin
        if provider == "gemini":
            return models.gemini_bin
        raise RuntimeError(f"unknown authentication provider: {provider}")

    def auth_requirement(self, job_id: str) -> AuthRequirement | None:
        return find_auth_requirement(self.job_details(job_id))

    def recover_provider_auth(
        self,
        job_id: str,
        requirement: AuthRequirement,
        models: ModelDefaults,
    ) -> AuthRecoveryResult:
        with db.transaction(self.settings.db_path) as conn:
            job = db.get_job(conn, job_id)
            selected_role = job["worker"] if requirement.role == "worker" else job["controller"]
            current_provider = provider_for_role(str(selected_role))
            if current_provider != requirement.provider:
                raise RuntimeError(
                    f"The job's {requirement.role} changed while authentication was pending. "
                    "Review the selected provider and try again."
                )
            db.add_event(
                conn,
                job_id=job_id,
                kind="provider_authentication_started",
                payload={"provider": requirement.provider, "role": requirement.role},
            )

        binary = self.provider_binary(requirement.provider, models)
        try:
            result = authenticate_provider(requirement.provider, binary)
        except Exception as exc:
            with db.transaction(self.settings.db_path) as conn:
                db.add_event(
                    conn,
                    job_id=job_id,
                    kind="provider_authentication_failed",
                    payload={
                        "provider": requirement.provider,
                        "role": requirement.role,
                        "error": str(exc),
                    },
                )
            raise

        with db.transaction(self.settings.db_path) as conn:
            db.add_event(
                conn,
                job_id=job_id,
                kind="provider_authentication_succeeded",
                payload={
                    "provider": requirement.provider,
                    "role": requirement.role,
                    "already_authenticated": result.already_authenticated,
                },
            )
        self.resume_job(
            job_id,
            worker=None,
            controller=None,
            granularity=None,
            models=models,
        )
        return result

    def _cached_redis_client(self) -> redis_module.Redis:
        with self._redis_lock:
            if self._redis_client is None:
                # One client (and connection pool) per backend instead of a new
                # pool per call; short timeouts so an unreachable-but-routable
                # Redis cannot stall a caller for the default 5-10 seconds.
                self._redis_client = redis_module.Redis.from_url(
                    self.settings.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=1,
                    socket_timeout=1,
                )
            return self._redis_client

    def _invalidate_redis_client(self, failed_client: Any = None) -> None:
        """Drop (and close) the cached Redis client after a failure.

        ``failed_client`` is the client the caller was actually using when it
        observed the failure. If the cache already holds a DIFFERENT client,
        another thread has invalidated and replaced it in the meantime, and
        closing the current one would kill a healthy fresh client mid-ping;
        in that case do nothing. ``None`` invalidates unconditionally.
        """
        with self._redis_lock:
            client = self._redis_client
            if failed_client is not None and client is not failed_client:
                return
            self._redis_client = None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    def redis_running(self) -> bool:
        """PING Redis (blocks up to ~2 s). Call from a background thread only."""
        client = None
        try:
            client = self._cached_redis_client()
            client.ping()
            ok = True
        except Exception:
            self._invalidate_redis_client(client)
            ok = False
        self._redis_last_ok = ok
        self._redis_last_checked = time.time()
        return ok

    def redis_sample(self) -> tuple[bool, float]:
        """Last known Redis reachability without touching the network."""
        return self._redis_last_ok, self._redis_last_checked

    def start_redis_server(self) -> int:
        parsed = urlparse(self.settings.redis_url)
        host = parsed.hostname or "localhost"
        if host not in {"localhost", "127.0.0.1", "::1"}:
            raise RuntimeError(f"cannot auto-start non-local Redis URL: {self.settings.redis_url}")
        redis_bin = shutil.which("redis-server")
        if redis_bin is None:
            if platform.system() == "Darwin":
                manual = "brew install redis"
            elif shutil.which("apt-get"):
                manual = "sudo apt-get install -y redis-server"
            elif shutil.which("dnf"):
                manual = "sudo dnf install -y redis"
            elif shutil.which("pacman"):
                manual = "sudo pacman -S --needed redis"
            else:
                manual = "install Redis with your operating system's package manager"
            raise RuntimeError(
                "redis-server is not on PATH and automatic installation was unavailable.\n"
                f"Usual manual fix: {manual}\n"
                "Alternatively, set REDIS_URL to an existing Redis server."
            )

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
                status = str(row["status"])
                if task is not None and status in ACTIVE_STATUSES:
                    task_status = str(task["status"])
                    if task_status == "running":
                        expected = "fixing" if str(task["created_by"]) == "claude:repair" else "implementing"
                    elif task_status == "waiting_tokens":
                        expected = "waiting_tokens"
                    elif task_status == "queued":
                        expected = "fixing" if str(task["created_by"]) == "claude:repair" else "queued"
                    else:
                        expected = status
                    if expected != status:
                        db.update_job_status(conn, str(row["id"]), expected)
                        status = expected
                        item["status"] = expected
                percent, remaining = estimate_progress(
                    conn,
                    job_id=str(row["id"]),
                    status=status,
                    created_at=str(row["created_at"]),
                    run_count=int(row["run_count"]),
                    task_count=int(row["task_count"]),
                    has_active_task=task is not None and str(task["status"]) in {"queued", "running", "waiting_tokens"},
                )
                item["percent"] = percent
                item["remaining"] = remaining
                item["latest_task"] = task
                worker_info = self.process_status(str(row["id"]))["worker"]
                item["status_display"] = (
                    "queued / worker offline"
                    if status == "queued" and not worker_info["running"]
                    else status
                )
                result.append(item)
            return result

    def job_details(self, job_id: str) -> dict[str, Any]:
        with db.transaction(self.settings.db_path) as conn:
            job = db.get_job(conn, job_id)
            task_count = int(conn.execute("SELECT COUNT(*) FROM tasks WHERE job_id = ?", (job_id,)).fetchone()[0])
            run_count = int(conn.execute("SELECT COUNT(*) FROM runs WHERE job_id = ?", (job_id,)).fetchone()[0])
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
            latest = db.latest_task(conn, job_id)
            percent, remaining = estimate_progress(
                conn,
                job_id=job_id,
                status=str(job["status"]),
                created_at=str(job["created_at"]),
                run_count=run_count,
                task_count=task_count,
                has_active_task=latest is not None and str(latest["status"]) in {"queued", "running", "waiting_tokens"},
            )
            return {
                "job": job,
                "tasks": tasks,
                "runs": runs,
                "decisions": decisions,
                "events": events,
                "processes": self.process_status(job_id),
                # Cached sample only: job_details runs on the Tk main thread
                # (refresh tick) and must never touch the network.
                # redis_checked == 0.0 means "no PING has completed yet":
                # readers must present that as unknown/checking, not offline.
                "redis_running": self._redis_last_ok,
                "redis_checked": self._redis_last_checked,
                "task_count": task_count,
                "run_count": run_count,
                "percent": percent,
                "remaining": remaining,
            }

    def verification_dashboard(self, job_id: str) -> tuple[dict[str, Any], ...] | None:
        """Blocking integrity/data projection; call only from a background thread."""

        return load_verification_dashboard_projection(self.settings.db_path, job_id)

    def acknowledge_manual_verification(
        self,
        job_id: str,
        verification_id: str,
        *,
        acknowledged_by: str,
        note: str,
    ) -> dict[str, Any]:
        """Blocking audited write; call only from a background thread."""

        return record_manual_verification_acknowledgement(
            self.settings.db_path,
            job_id,
            verification_id,
            acknowledged_by=acknowledged_by,
            note=note,
        )

    def process_status(self, job_id: str) -> dict[str, dict[str, Any]]:
        runtime_dir = self.runtime_dir(job_id)
        status: dict[str, dict[str, Any]] = {}
        for name in PROCESS_NAMES:
            pid_file = runtime_dir / f"{name}.pid"
            if not pid_file.exists() and name in LEGACY_PROCESS_NAMES:
                pid_file = runtime_dir / f"{LEGACY_PROCESS_NAMES[name]}.pid"
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
        if os.name != "nt":
            stat_path = Path("/proc") / str(pid) / "stat"
            try:
                stat = stat_path.read_text(encoding="utf-8")
                after_name = stat.rsplit(")", 1)[1].strip()
                if after_name.startswith("Z"):
                    return False
            except OSError:
                pass
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @staticmethod
    def pid_identity_ok(pid: int) -> bool:
        """Best-effort guard against PID reuse before adopting or signalling a stored PID.

        Returns False only when ``ps`` positively reports a command line that
        looks unrelated to the AI-Loop trio. Any ps failure, timeout, or empty
        output returns True: this check must never abort or block an action.
        Both launch paths exec/argv the script names, so real AI-Loop
        processes always contain one of the markers below; a bare "python" is
        NOT accepted, because any unrelated Python process would then be
        adoptable or signallable.
        Intentionally duplicated from resume_job._pid_identity_ok so the GUI
        stays self-contained (mirroring the existing duplication convention).
        """
        try:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = (result.stdout or "").strip()
        except Exception:
            return True
        if not output:
            return True
        return any(marker in output for marker in ("controller.py", "worker.py", "watcher.py", "ai_loop"))

    def env_for_processes(
        self,
        job_id: str,
        models: ModelDefaults,
        base_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        env = dict(base_env) if base_env is not None else os.environ.copy()
        env["AI_LOOP_JOB_ID"] = job_id
        env["AI_LOOP_RUNTIME_DIR"] = str(self.runtime_dir(job_id))
        env["AI_LOOP_LOG_DIR"] = str(self.log_dir(job_id))
        env["CODEX_BIN"] = models.codex_bin
        env["CLAUDE_BIN"] = models.claude_bin
        env["GEMINI_BIN"] = models.gemini_bin
        env["AI_LOOP_CODEX_MODEL"] = models.codex_model
        env["AI_LOOP_FABLE_MODEL"] = models.fable_model
        env["AI_LOOP_OPUS_MODEL"] = models.opus_model
        env["AI_LOOP_GEMINI_MODEL"] = models.gemini_model
        env["AI_LOOP_CONTROLLER_MODEL"] = models.controller_model
        env["AI_LOOP_CONTROLLER_ROLE_MODEL"] = models.controller_role_model
        env["AI_LOOP_WORKER_ROLE_MODEL"] = models.worker_role_model
        env["CODEX_BYPASS_SANDBOX"] = "1" if models.codex_bypass_sandbox else "0"
        env["AI_LOOP_CODEX_SYSTEMD_SANDBOX"] = (
            "1"
            if models.codex_bypass_sandbox
            and getattr(self.settings, "codex_systemd_sandbox", False)
            else "0"
        )
        return env

    def launch_processes(self, job_id: str, models: ModelDefaults) -> dict[str, int]:
        runtime_dir = self.runtime_dir(job_id)
        log_dir = self.log_dir(job_id)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        env = self.env_for_processes(job_id, models)
        scripts = {
            "controller": "controller.py",
            "worker": "worker.py",
            "watcher": "watcher.py",
        }
        pids: dict[str, int] = {}
        for name, script in scripts.items():
            pid_file = runtime_dir / f"{name}.pid"
            old_pid = self.read_pid(pid_file)
            if not self.pid_running(old_pid) and name in LEGACY_PROCESS_NAMES:
                old_pid = self.read_pid(runtime_dir / f"{LEGACY_PROCESS_NAMES[name]}.pid")
            # A live-but-foreign old PID (the number was recycled by an
            # unrelated process) must never be adopted as the job's process;
            # treat it as stale and launch a fresh one instead.
            if self.pid_running(old_pid) and self.pid_identity_ok(int(old_pid)):
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
            pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")
        return pids

    def stop_processes(self, job_id: str) -> dict[str, str]:
        """SIGTERM the job's trio, then poll the process GROUPS and escalate.

        A single SIGTERM is not enough: a signal-resistant provider child
        (codex/claude CLI) can survive it and keep editing the worktree while
        resume_job launches a replacement worker into the same worktree. After
        the SIGTERM pass, the terminated pids' whole process groups are polled
        for up to ~5 s; groups that are still alive get SIGKILL, and the
        results dict notes the escalation. Called from background threads
        (resume via _run_bg, delete/reset/finish via their _run_bg wrappers),
        so the 5 s poll never blocks the Tk main thread.
        """
        runtime_dir = self.runtime_dir(job_id)
        results: dict[str, str] = {}
        terminated: list[tuple[str, int]] = []
        for name in PROCESS_NAMES:
            pid_file = runtime_dir / f"{name}.pid"
            if not pid_file.exists() and name in LEGACY_PROCESS_NAMES:
                pid_file = runtime_dir / f"{LEGACY_PROCESS_NAMES[name]}.pid"
            pid = self.read_pid(pid_file)
            if not pid:
                results[name] = "no pid"
                continue
            if self.pid_running(pid):
                if self.pid_identity_ok(pid):
                    self.terminate_pid(pid)
                    results[name] = f"stopped pid={pid}"
                    terminated.append((name, pid))
                else:
                    # The stored PID was recycled by an unrelated process;
                    # never killpg it. The stale pid file is still removed.
                    results[name] = f"pid reused, skipped pid={pid}"
            else:
                results[name] = f"stale pid={pid}"
            try:
                pid_file.unlink()
            except OSError:
                pass
        if terminated:
            deadline = time.monotonic() + 5.0
            survivors = list(terminated)
            while survivors and time.monotonic() < deadline:
                time.sleep(0.2)
                # The whole process GROUP must be gone, not just the leader:
                # a SIGTERM-trapping CLI child keeps the group alive after the
                # leader exits and still needs the SIGKILL escalation below.
                survivors = [(name, pid) for name, pid in survivors if self.group_alive(pid)]
            for name, pid in survivors:
                self.kill_pid(pid)
                results[name] = f"stopped pid={pid} (escalated to SIGKILL after SIGTERM grace period)"
        return results

    @staticmethod
    def group_alive(pid: int) -> bool:
        """True while any process in ``pid``'s process group is still alive.

        killpg(pid, 0) probes group existence, but succeeds against a group
        whose remaining members are all zombies; parsed ``ps -Ao pgid=,state=``
        output (portable across BSD/macOS and procps, ``=`` suppresses the
        headers) filters those out. No rows for the group means it is gone;
        ps failure/timeout/unparseable output conservatively counts as alive.
        Intentionally duplicated from resume_job._group_alive /
        _group_has_live_member so the GUI stays self-contained (mirroring the
        existing duplication convention). pgrep is deliberately not used: on
        macOS ``pgrep -g`` was observed returning exit 1 for a live group.
        """
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # The group exists but belongs to someone else; treat it as alive.
            return True
        except (AttributeError, OSError):
            # No killpg (Windows): fall back to a single-PID liveness probe.
            return LoopBackend.pid_running(pid)
        try:
            result = subprocess.run(
                ["ps", "-Ao", "pgid=,state="],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return True
            rows: list[tuple[str, str]] = []
            for line in (result.stdout or "").splitlines():
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                rows.append((parts[0].strip(), parts[1].strip()))
        except Exception:
            return True
        if not rows:
            return True
        states = [state for row_pgid, state in rows if row_pgid == str(pid)]
        if not states:
            return False
        return any(not state.startswith("Z") for state in states)

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

    @staticmethod
    def kill_pid(pid: int) -> None:
        """Forcefully kill ``pid``'s whole process group.

        SIGKILL escalation for groups that survived the SIGTERM grace period
        in stop_processes; same killpg-with-os.kill-fallback guards as
        terminate_pid. On Windows terminate_pid's taskkill /F is already
        forceful, so it is simply reused there.
        """
        if os.name == "nt":
            LoopBackend.terminate_pid(pid)
            return
        force_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
        try:
            os.killpg(pid, force_signal)
        except OSError:
            try:
                os.kill(pid, force_signal)
            except OSError:
                pass

    def queue_plan(self, job_id: str, *, publication_key: str | None = None) -> None:
        self.ensure_redis_running()
        client = redis_client(self.settings.redis_url)
        publish_controller_plan(client, job_id, publication_key=publication_key)

    def publish_task(self, task_id: str) -> bool:
        """Publish a persisted task through the same queue as controller tasks."""

        self.ensure_redis_running()
        with db.transaction(self.settings.db_path) as conn:
            task = db.get_task(conn, task_id)
        client = redis_client(self.settings.redis_url)
        return publish_worker_task(client, task, scoped=True)

    def retarget_formal_job(
        self,
        job_id: str,
        specification_id: str,
        specification_version: int,
    ) -> Any:
        """Retarget and publish its impact task through the controller task queue."""

        service = SpecificationService(self.settings.db_path)
        return service.attach_newer_approved_revision(
            job_id,
            specification_id,
            specification_version,
            task_publisher=self.publish_task,
        )

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
        granularity: str,
        models: ModelDefaults,
        specification_id: str | None = None,
        specification_version: int | None = None,
    ) -> str:
        repo = repo.expanduser().resolve()
        if not repo.exists():
            raise ValueError(f"repo does not exist: {repo}")
        worker = normalize_worker(worker)
        controller = normalize_controller(controller)
        granularity = normalize_granularity(granularity)
        self.ensure_provider_clis(worker=worker, controller=controller, models=models)
        self.ensure_worker_runtime(
            worker=worker, models=models, writable_path=repo
        )
        detected_test_cmd = detect_test_cmd(repo, test_cmd)

        current_active = active_jobs(self.settings.db_path)
        if current_active and not allow_parallel:
            raise RuntimeError("another job is active; enable Allow parallel to create a new one anyway")

        if (specification_id is None) != (specification_version is None):
            raise ValueError("formal job creation requires both specification ID and version")
        specification_service: SpecificationService | None = None
        formal_inputs = None
        if specification_id is not None and specification_version is not None:
            specification_service = SpecificationService(self.settings.db_path)
            approved = specification_service.verify_integrity(
                specification_id, specification_version
            )
            formal_inputs = derive_formal_job_inputs(approved)
            if repo != Path(approved.repository_path).expanduser().resolve():
                raise ValueError(
                    "approved specification repository differs from the job repository"
                )

        job_id = timestamp_id("J")
        all_constraints = [*granularity_constraints(granularity), *COMMON_CONSTRAINTS, *constraints]
        all_acceptance = [*DEFAULT_ACCEPTANCE, *acceptance]
        plan_goal = formal_inputs.goal if formal_inputs is not None else goal
        plan_acceptance = (
            [*formal_inputs.acceptance, *all_acceptance]
            if formal_inputs is not None
            else all_acceptance
        )
        plan = build_static_plan(plan_goal, plan_acceptance, detected_test_cmd)
        worktree = repo
        branch: str | None = None
        overlay_files: list[str] = []
        pre_job_commit: dict[str, str | bool | None]

        pre_job_commit = create_pre_job_commit(repo, job_id)
        if use_worktree:
            worktree, branch = create_worktree(repo, self.settings.runs_dir, job_id, base_ref)
            overlay_files = copy_checkout_overlay(repo, worktree)

        if specification_service is not None:
            specification_service.create_formal_job(
                specification_id=specification_id,
                specification_version=specification_version,
                job_id=job_id,
                repo_path=str(repo),
                worktree_path=str(worktree),
                branch=branch,
                base_ref=base_ref,
                test_cmd=detected_test_cmd,
                max_iterations=max_iterations,
                use_worktree=use_worktree,
                worker=worker,
                controller=controller,
                granularity=granularity,
                plan=plan,
                models=asdict(models),
                additional_constraints=all_constraints,
                additional_acceptance=all_acceptance,
            )
        else:
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
                    granularity=granularity,
                    plan=plan,
                    # Persist the model/binary selections as durable job state so
                    # a resume after a GUI restart can restore the original
                    # choices instead of silently using whatever the form shows.
                    models=asdict(models),
                )

        with db.transaction(self.settings.db_path) as conn:
            db.add_event(
                conn,
                job_id=job_id,
                kind="job_created_from_gui",
                payload={
                    "job_id": job_id,
                    "worktree_path": str(worktree),
                    "worker": worker,
                    "controller": controller,
                    "granularity": granularity,
                    "plan": plan,
                    "specification_id": specification_id,
                    "specification_version": specification_version,
                    "pre_job_commit": pre_job_commit,
                    "checkout_overlay_files": overlay_files,
                },
            )

        pids = self.launch_processes(job_id, models)
        self.queue_plan(
            job_id,
            publication_key=(
                f"formal-job:{job_id}" if specification_service is not None else None
            ),
        )
        with db.transaction(self.settings.db_path) as conn:
            db.add_event(
                conn,
                job_id=job_id,
                kind="job_processes_started_from_gui",
                payload={"pids": pids},
            )
            started_job = db.get_job(conn, job_id)
        sent, detail = job_started_email(self.settings, job=started_job)
        outcome = delivery_outcome(sent, detail)
        with db.transaction(self.settings.db_path) as conn:
            db.add_event(
                conn,
                job_id=job_id,
                kind=f"email_started_{outcome}",
                payload={"recipient": self.settings.notify_email, "detail": detail},
            )
        return job_id

    def resume_job(
        self,
        job_id: str,
        *,
        worker: str | None,
        controller: str | None,
        granularity: str | None,
        models: ModelDefaults,
        extra_constraint: str = "",
        extra_acceptance: str = "",
    ) -> None:
        # Terminate the whole previous trio BEFORE the status update: reusing
        # live PIDs would keep the old human-wait watcher, which exits as soon
        # as the status leaves human_needed ("resumed elsewhere"), leaving the
        # job with no watcher at all. A full stop also removes the duplicate
        # controller/worker hazard, mirroring the CLI resume's
        # terminate_previous_job_processes. stop_processes skips recycled PIDs
        # via the identity check, so this can never kill a foreign process.
        with db.transaction(self.settings.db_path) as conn:
            preflight_job = db.get_job(conn, job_id)
        preflight_worker = normalize_worker(worker or str(preflight_job["worker"]))
        preflight_controller = normalize_controller(
            controller or str(preflight_job["controller"])
        )
        self.ensure_provider_clis(
            worker=preflight_worker,
            controller=preflight_controller,
            models=models,
        )
        self.ensure_worker_runtime(
            worker=preflight_worker,
            models=models,
            writable_path=Path(str(preflight_job["worktree_path"])),
        )
        self.stop_processes(job_id)
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
            new_granularity = normalize_granularity(granularity or str(job["granularity"]))
            constraints = replace_granularity_constraints(constraints, new_granularity)
            # models_json is refreshed to the models actually being applied to
            # this resume (same asdict(models) shape as create_job) so a later
            # GUI restart restores the settings the job is really running
            # with, not the ones from job creation.
            conn.execute(
                """
                UPDATE jobs
                SET worker = ?, controller = ?, granularity = ?, constraints_json = ?, acceptance_json = ?,
                    models_json = ?, status = 'planning', updated_at = ?
                WHERE id = ?
                """,
                (
                    new_worker,
                    new_controller,
                    new_granularity,
                    db.to_json(constraints),
                    db.to_json(acceptance),
                    db.to_json(asdict(models)),
                    db.utc_now(),
                    job_id,
                ),
            )
            db.add_event(
                conn,
                job_id=job_id,
                kind="job_resumed_from_gui",
                payload={"worker": new_worker, "controller": new_controller, "granularity": new_granularity},
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

    def finish_job(self, job_id: str) -> None:
        self.stop_processes(job_id)
        with db.transaction(self.settings.db_path) as conn:
            db.update_job_status(
                conn,
                job_id,
                "human_needed",
                "Finished manually from the GUI. Progress is preserved in the job worktree and database; resume if more work is needed.",
            )
            db.add_event(conn, job_id=job_id, kind="job_finished_from_gui", payload={})

    def request_finish_soon(self, job_id: str) -> None:
        with db.transaction(self.settings.db_path) as conn:
            job = db.get_job(conn, job_id)
            if str(job["status"]) in TERMINAL_STATUSES:
                raise RuntimeError(f"job is already {job['status']}")
            conn.execute(
                """
                UPDATE jobs
                SET finish_requested = 1, granularity = 'coarse', constraints_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    db.to_json(replace_granularity_constraints(list(job["constraints"]), "coarse")),
                    db.utc_now(),
                    job_id,
                ),
            )
            db.add_event(
                conn,
                job_id=job_id,
                kind="finish_soon_requested",
                payload={"previous_granularity": job["granularity"]},
            )

    def fix_job_with_binary(self, job_id: str, binary: str, models: ModelDefaults) -> subprocess.CompletedProcess[str]:
        details = self.job_details(job_id)
        job = details["job"]
        binary = binary.strip() or models.codex_bin or "codex"
        prompt = self.fix_prompt(details)
        # The fix-it binary works inside the target worktree. When configured,
        # systemd supplies the external write boundary; mail credentials are always stripped.
        env = self.env_for_processes(job_id, models, base_env=sanitized_child_env())
        env["CODEX_BYPASS_SANDBOX"] = "1"
        if Path(binary).name.startswith("codex") or binary == "codex":
            cmd = [binary, "exec", "--cd", str(job["worktree_path"]), "--dangerously-bypass-approvals-and-sandbox", "-"]
            if getattr(self.settings, "codex_systemd_sandbox", False):
                cmd = wrap_with_systemd_sandbox(cmd, writable_paths=[job["worktree_path"]])
            proc = subprocess.run(cmd, input=prompt, text=True, capture_output=True, timeout=7200, env=env)
        else:
            cmd = [binary, "-"]
            if getattr(self.settings, "codex_systemd_sandbox", False):
                cmd = wrap_with_systemd_sandbox(cmd, writable_paths=[job["worktree_path"]])
            proc = subprocess.run(cmd, input=prompt, text=True, capture_output=True, timeout=7200, env=env, cwd=str(job["worktree_path"]))
        with db.transaction(self.settings.db_path) as conn:
            db.add_event(
                conn,
                job_id=job_id,
                kind="manual_fix_binary_finished",
                payload={
                    "binary": binary,
                    "returncode": proc.returncode,
                    "output_tail": (proc.stdout + "\n" + proc.stderr)[-4000:],
                },
            )
        if proc.returncode == 0:
            self.resume_job(job_id, worker=str(job["worker"]), controller=str(job["controller"]), models=models)
        return proc

    def fix_prompt(self, details: dict[str, Any]) -> str:
        job = details["job"]
        latest_task = details["tasks"][0] if details.get("tasks") else None
        latest_run = details["runs"][0] if details.get("runs") else None
        latest_decision = details["decisions"][0] if details.get("decisions") else None
        return f"""You are repairing the local ai-loop job runner or the target worktree so the job can continue.

Job: {job['id']}
Status: {job['status']}
Repo: {job['repo_path']}
Worktree: {job['worktree_path']}
Current goal: {job['goal'][:4000]}
History summary: {str(job.get('history_summary') or '')[-4000:]}
Latest task: {latest_task}
Latest run: {latest_run}
Latest decision: {latest_decision}

Diagnose the immediate blocker, make the smallest safe fix, run relevant syntax/build checks, and leave the worktree resumable. Do not commit or merge. If the blocker is quota or credentials, explain that clearly and do not fabricate a fix.
"""

    def log_text(self, job_id: str, name: str, max_bytes: int = 60000) -> str:
        path = self.log_dir(job_id) / f"{name}.log"
        if not path.is_file() and name in LEGACY_PROCESS_NAMES:
            path = self.log_dir(job_id) / f"{LEGACY_PROCESS_NAMES[name]}.log"
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
        self.mail_access_status: MailAccessStatus = MailAccessStatus(
            False, True, "mail: checking…", "checking…", "checking…"
        )
        self._mail_check_done = False
        self.model_defaults = self.backend.model_defaults()
        self.help_tooltip = HoverTooltip(self)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.selected_job_id: str | None = None
        self.resume_fields_job_id: str | None = None
        self._refreshing_jobs = False
        self._refresh_all_active = False
        self._fix_job_running = False
        self._create_job_running = False
        self._resume_job_running = False
        self._redis_action_running = False
        self._maintenance_running = False
        self._hibernation_running = False
        # Stop/Delete/Finish call backend.stop_processes, whose SIGTERM->poll
        # ->SIGKILL escalation waits up to ~5 s; they run via _run_bg so that
        # poll never blocks the Tk main thread.
        self._stop_job_running = False
        self._delete_job_running = False
        self._finish_job_running = False
        # Human-readable labels of operations currently running on background
        # threads. Additive bookkeeping next to the busy flags above: _run_bg
        # adds the label before its thread starts and the finisher/fallback
        # removes it. Read by on_close (warn before killing daemon threads
        # mid-destructive-work) and _exclusive_conflict.
        self._active_operations: set[str] = set()
        self._embedded_specification_editor: Any | None = None
        self._specification_tab_loading = False
        self._verification_load_running = False
        self._verification_request_serial = 0
        self._verification_last_loaded_at = 0.0
        self._verification_last_loaded_job: str | None = None
        self._analysis_controller: ProjectAnalysisController | None = None
        self._analysis_member_class_id: str | None = None
        self._analysis_tooltip_node_id: str | None = None
        self._analysis_running = False
        self._qa_running = False
        self._qa_history: list[tuple[str, str]] = []
        self._qa_llms_by_label: dict[str, AvailableLlm] = {}
        self._redis_sampler_inflight = False
        self.watch_job_id: str | None = None
        self.last_status_by_job: dict[str, str] = {}
        self.alerted_human_needed: set[str] = set()
        self.human_needed_windows: dict[str, tk.Toplevel] = {}
        self.auth_recovery_jobs: set[str] = set()
        self.auto_refresh = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value=f"DB: {self.backend.settings.db_path}")
        self._build_ui()
        self.install_default_help(self)
        self._sample_redis_status()
        self.refresh_all()
        self._start_mail_access_check()
        self.after(1500, self._auto_refresh_tick)

    def _run_bg(
        self,
        work: Any,
        on_done: Any,
        *,
        name: str = "ai-loop-bg",
        busy_attr: str | None = None,
        label: str | None = None,
    ) -> None:
        """Run work() on a daemon thread and marshal (result, error) back to
        on_done on the Tk main thread. on_done must reset the busy flag on all
        paths; the direct reset here only covers a destroyed Tk loop.

        label, when given, is a human-readable operation name kept in
        self._active_operations while the work runs (added before the thread
        starts, removed just before on_done or in the destroyed-Tk fallback);
        on_close and _exclusive_conflict read that set."""
        if label is not None:
            self._active_operations.add(label)

        def finish(result: Any, error: str | None) -> None:
            if label is not None:
                self._active_operations.discard(label)
            on_done(result, error)

        def runner() -> None:
            result: Any = None
            error: str | None = None
            try:
                result = work()
            except Exception as exc:
                error = str(exc) or repr(exc)
            try:
                self.after(0, lambda: finish(result, error))
            except (tk.TclError, RuntimeError):
                if busy_attr is not None:
                    setattr(self, busy_attr, False)
                if label is not None:
                    self._active_operations.discard(label)

        threading.Thread(target=runner, name=name, daemon=True).start()

    # Destructive maintenance labels (stop processes / delete worktrees /
    # clear database) as passed to _run_bg via label=.
    _MAINTENANCE_OPERATIONS = frozenset({"Reset Loop", "Clear Worktrees", "Full Reset"})
    # Harmless operations that never participate in cross-exclusion (they are
    # still tracked in _active_operations so on_close can name them).
    _NON_EXCLUSIVE_OPERATIONS = frozenset(
        {"Start Redis", "Hibernation change", "AI-Loop Q&A"}
    )

    def _exclusive_conflict(self, kind: str) -> str | None:
        """Return the label of a running operation that forbids starting an
        operation of category ``kind``, or None when there is no conflict.

        kind is "maintenance" (Reset Loop / Clear Worktrees / Full Reset) or
        a job-actions kind such as "job" or "Auth Recovery" (Create Job /
        Resume Job / Fix It / Auth Recovery). Exclusion matrix: starting
        maintenance conflicts with ANY running exclusive operation (a reset
        must not delete worktrees or database rows under a job being created,
        resumed, fixed, or auth-recovered); starting a job operation conflicts with running
        maintenance only (create/resume/fix may coexist with each other, and
        same-kind reentry is already guarded by the busy flags). Start Redis
        and hibernation changes are harmless and never conflict.

        Reads only self._active_operations (a plain set, no Tk state) so it
        is unit-testable on an AiLoopGui.__new__-created instance.
        """
        active = self._active_operations - self._NON_EXCLUSIVE_OPERATIONS
        if kind != "maintenance":
            active = active & self._MAINTENANCE_OPERATIONS
        for operation in sorted(active):
            return operation
        return None

    def _sample_redis_status(self) -> None:
        # Ping Redis in a background thread at most once every 3 seconds and
        # store the result in the backend; the refresh tick and job_details
        # read that cached sample and never touch the network themselves.
        if not self._redis_sampler_inflight:
            self._redis_sampler_inflight = True

            def sample() -> None:
                try:
                    self.backend.redis_running()
                finally:
                    # Plain attribute write, no Tk access: safe from the thread.
                    self._redis_sampler_inflight = False

            threading.Thread(target=sample, name="ai-loop-redis-sample", daemon=True).start()
        try:
            self.after(3000, self._sample_redis_status)
        except tk.TclError:
            pass

    def _start_mail_access_check(self) -> None:
        def check() -> None:
            try:
                status = check_mail_access(self.backend.settings)
            except Exception as exc:
                detail = f"error: mail account check failed: {exc!r}"
                status = MailAccessStatus(True, False, detail, detail, detail)
            try:
                self.after(0, lambda: self._finish_mail_access_check(status))
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(
            target=check,
            name="ai-loop-mail-check",
            daemon=True,
        ).start()

    def _finish_mail_access_check(self, status: MailAccessStatus) -> None:
        self.mail_access_status = status
        self._mail_check_done = True
        self.refresh_all()
        if status.enabled and not status.ok:
            messagebox.showerror("Mail Account Access Failed", status.detail)

    def apply_theme(self, theme: str) -> None:
        if theme in {"", "default", "native", "current"}:
            return
        style = ttk.Style(self)
        available = tuple(style.theme_names())
        if theme not in available:
            raise ValueError(f"unknown Tk theme: {theme!r}; available themes: {', '.join(available)}")
        style.theme_use(theme)

    def on_close(self) -> None:
        # Destructive work (full reset mid-rmtree, create_job between the
        # `git add -A` and the snapshot commit, ...) runs on daemon threads,
        # which die silently with the window. Never close over them without
        # an explicit user confirmation.
        busy = (
            self._create_job_running
            or self._resume_job_running
            or self._fix_job_running
            or self._maintenance_running
            or self._hibernation_running
            or self._redis_action_running
            or self._stop_job_running
            or self._delete_job_running
            or self._finish_job_running
            or bool(self._active_operations)
        )
        if busy:
            names = sorted(self._active_operations)
            listed = ", ".join(names) if names else "A background operation"
            verb = "are" if len(names) > 1 else "is"
            if not messagebox.askyesno(
                "Operation in progress",
                f"{listed} {verb} still running. Closing now may leave it half-finished. Close anyway?",
            ):
                return
        self.auto_refresh.set(False)
        self.help_tooltip.hide()
        self.quit()
        self.destroy()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.grid(row=0, column=0, sticky="ew")
        self.help_widget(ttk.Button(toolbar, text="Refresh", command=self.refresh_all), "Reload the full job list, selected-job details, logs, and live process snapshot.").grid(row=0, column=0, padx=(0, 6))
        self.help_widget(ttk.Checkbutton(toolbar, text="Auto refresh", variable=self.auto_refresh), "Keep refreshing the dashboard automatically so changing task and job states stay current.").grid(row=0, column=1, padx=(0, 12))
        self.help_widget(ttk.Button(toolbar, text="Stop", command=self.stop_selected_job), "Stop the controller, worker, and watcher for the selected job without deleting its records.").grid(row=0, column=2, padx=(0, 6))
        self.help_widget(ttk.Button(toolbar, text="Finish Soon", command=self.finish_soon_selected_job), "Keep the job running but switch it to coarse tasks, discard optional work, and ask the controller to reach acceptance in at most one consolidated final task.").grid(row=0, column=3, padx=(0, 6))
        self.help_widget(ttk.Button(toolbar, text="Resume", command=self.resume_selected_job), "Resume the selected job with the current controller, worker, granularity, and optional extra criteria.").grid(row=0, column=4, padx=(0, 6))

        job_actions = self.help_widget(
            ttk.Menubutton(toolbar, text="Job Actions"),
            "Open less-frequent selected-job actions: status details, notifications, immediate finish, or deletion.",
        )
        job_menu = tk.Menu(self, tearoff=False)
        job_menu.add_command(label="Status Details", command=self.explain_selected_status)
        job_menu.add_command(label="Wait / Notify", command=self.watch_selected_job)
        job_menu.add_command(label="Sign In + Resume", command=self.recover_selected_auth)
        job_menu.add_separator()
        job_menu.add_command(label="Finish Early", command=self.finish_selected_job)
        job_menu.add_command(label="Delete Job", command=self.delete_selected_job)
        job_actions.configure(menu=job_menu)
        job_actions.grid(row=0, column=5, padx=(0, 6))

        system_actions = self.help_widget(
            ttk.Menubutton(toolbar, text="System"),
            "Open Redis, worktree cleanup, database reset, full reset, and macOS hibernation actions.",
        )
        system_menu = tk.Menu(self, tearoff=False)
        system_menu.add_command(label="Start Redis", command=self.start_redis)
        system_menu.add_command(label="Clear Worktrees", command=self.clear_worktrees)
        system_menu.add_separator()
        system_menu.add_command(label="Reset DB", command=self.reset_loop)
        system_menu.add_command(label="Full Reset", command=self.full_reset)
        system_menu.add_separator()
        system_menu.add_command(label="Hibernation", command=self.open_hibernation_window)
        system_actions.configure(menu=system_menu)
        system_actions.grid(row=0, column=6, padx=(0, 12))

        ttk.Label(toolbar, text="Status:").grid(row=0, column=7, sticky="e", padx=(0, 4))
        status_label = self.help_widget(ttk.Label(toolbar, textvariable=self.status_var, anchor="w", width=1), "Live loop status, including Redis and mailbox connectivity, job counts, and running or stale processes.")
        status_label.grid(row=0, column=8, sticky="ew")
        toolbar.columnconfigure(8, weight=1)

        workspace = ttk.Notebook(self)
        workspace.grid(row=1, column=0, sticky="nsew")
        self.workspace = workspace
        dashboard = ttk.Frame(workspace)
        specification_tab = ttk.Frame(workspace)
        analysis_tab = ttk.Frame(workspace, padding=8)
        qa_tab = ttk.Frame(workspace, padding=8)
        workspace.add(dashboard, text="Jobs")
        workspace.add(specification_tab, text="Specification")
        workspace.add(analysis_tab, text="Project Analysis")
        workspace.add(qa_tab, text="Ask AI-Loop")
        self.specification_tab = specification_tab
        self.qa_tab = qa_tab
        workspace.bind(
            "<<NotebookTabChanged>>", self._on_workspace_tab_changed, add="+"
        )
        dashboard.rowconfigure(0, weight=1)
        dashboard.columnconfigure(0, weight=1)

        paned = ttk.PanedWindow(dashboard, orient=tk.HORIZONTAL)
        paned.grid(row=0, column=0, sticky="nsew")

        left = ttk.Frame(paned, padding=8)
        right = ttk.Frame(paned, padding=8)
        paned.add(left, weight=6)
        paned.add(right, weight=5)
        def set_initial_pane_split(event: tk.Event) -> None:
            if getattr(paned, "_ai_loop_split_initialized", False) or event.width <= 1:
                return
            paned._ai_loop_split_initialized = True
            paned.sashpos(0, int(event.width * 0.55))

        paned.bind("<Configure>", set_initial_pane_split, add="+")
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self._build_create_frame(left)
        self._build_jobs_frame(left)
        self._build_detail_frame(right)
        self._build_specification_tab(specification_tab)
        self._build_project_analysis_frame(analysis_tab)
        self._build_ai_loop_qa_tab(qa_tab)

    def _build_specification_tab(self, parent: ttk.Frame) -> None:
        """Build a lazy host for the staged specification workflow."""

        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        self.specification_tab_status_var = tk.StringVar(
            value=(
                "Open this tab to edit, validate, save, load, review, and approve "
                "formal specifications."
            )
        )
        ttk.Label(
            parent,
            textvariable=self.specification_tab_status_var,
            anchor="w",
            padding=12,
        ).grid(row=0, column=0, sticky="ew")
        self.specification_editor_host = ttk.Frame(parent)
        self.specification_editor_host.grid(row=1, column=0, sticky="nsew")
        self.specification_editor_host.columnconfigure(0, weight=1)
        self.specification_tab_open_button = self.help_widget(
            ttk.Button(
                self.specification_editor_host,
                text="Open Specification Workflow",
                command=self._ensure_specification_tab_editor,
            ),
            "Initialize the staged editor using the current Quick Job repository and goal.",
        )
        self.specification_tab_open_button.grid(
            row=0, column=0, pady=24, sticky="n"
        )

    def _on_workspace_tab_changed(self, _event: tk.Event | None = None) -> None:
        selected = self.workspace.select()
        if selected == str(self.specification_tab):
            self._ensure_specification_tab_editor()
        elif selected == str(self.qa_tab):
            self.refresh_qa_llms()

    def _ensure_specification_tab_editor(self) -> None:
        """Initialize the embedded specification editor once, on demand."""

        if self._embedded_specification_editor is not None or self._specification_tab_loading:
            return
        try:
            repository = Path(self.repo_var.get()).expanduser().resolve()
            goal = self.goal_text.get("1.0", "end-1c")
        except Exception as exc:
            messagebox.showerror("Formal Specification", str(exc))
            return
        if not repository.is_dir():
            messagebox.showerror(
                "Formal Specification", "Choose an existing repository directory first."
            )
            return
        self._specification_tab_loading = True
        self.specification_tab_open_button.configure(state="disabled")
        self.specification_tab_status_var.set("Opening specification workflow…")
        self._run_bg(
            lambda: SpecificationService(self.backend.settings.db_path),
            lambda service, error: self._finish_embedded_specification_editor(
                service, error, repository=repository, goal=goal
            ),
            name="ai-loop-open-specification-tab",
            label="Opening Formal Spec",
        )

    def _finish_embedded_specification_editor(
        self,
        service: SpecificationService | None,
        error: str | None,
        *,
        repository: Path,
        goal: str,
    ) -> None:
        self._specification_tab_loading = False
        if error is not None or service is None:
            self.specification_tab_open_button.configure(state="normal")
            self.specification_tab_status_var.set(
                f"Could not open specification workflow: {error or 'service failed'}"
            )
            messagebox.showerror(
                "Formal Specification", error or "Service initialization failed"
            )
            return
        try:
            editor = open_specification_editor(
                self.specification_editor_host,
                service=service,
                repository_path=repository,
                initial_goal=goal,
                creator=os.environ.get("USER")
                or os.environ.get("USERNAME")
                or "gui-user",
                run_background=self._run_bg,
                elicitation_provider_factory=self._formal_elicitation_provider,
                implementation_work_factory=self._formal_implementation_work,
                on_implementation_started=self._formal_implementation_started,
                embedded=True,
            )
        except Exception as exc:
            self.specification_tab_open_button.configure(state="normal")
            self.specification_tab_status_var.set(
                f"Could not display specification workflow: {exc}"
            )
            messagebox.showerror("Formal Specification", str(exc))
            return
        self.specification_tab_open_button.destroy()
        self.specification_tab_status_var.set(
            "Specification files can be stored and loaded with Save JSON and Load JSON."
        )
        self._embedded_specification_editor = editor

    def _build_ai_loop_qa_tab(self, parent: ttk.Frame) -> None:
        """Build a conversational, read-only interface to installed LLM CLIs."""

        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        controls = ttk.Frame(parent)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="LLM").grid(row=0, column=0, sticky="w")
        self.qa_llm_var = tk.StringVar()
        self.qa_llm_combo = self.help_widget(
            ttk.Combobox(
                controls,
                textvariable=self.qa_llm_var,
                state="readonly",
            ),
            "Select an installed Codex, Claude, or Gemini CLI with one of the configured model names.",
        )
        self.qa_llm_combo.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        self.help_widget(
            ttk.Button(
                controls,
                text="Refresh LLMs",
                command=self.refresh_qa_llms,
            ),
            "Rescan the configured provider executables and update the available LLM list.",
        ).grid(row=0, column=2, sticky="e")

        transcript_frame = ttk.LabelFrame(
            parent, text="Conversation", padding=6
        )
        transcript_frame.grid(row=1, column=0, sticky="nsew")
        transcript_frame.columnconfigure(0, weight=1)
        transcript_frame.rowconfigure(0, weight=1)
        self.qa_transcript_text = self.help_widget(
            self.add_scrolled_text(transcript_frame, 0, 0, wrap="word"),
            "Read-only conversation with answers grounded in the current AI-Loop source tree.",
        )
        self.set_text(
            self.qa_transcript_text,
            "Select an available LLM, enter a question below, and click Ask.",
        )

        question_frame = ttk.LabelFrame(parent, text="Question", padding=6)
        question_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        question_frame.columnconfigure(0, weight=1)
        self.qa_question_text = self.help_widget(
            tk.Text(question_frame, height=5, wrap="word"),
            "Ask about AI-Loop's architecture, behavior, configuration, workflows, or current source code. Ctrl+Enter sends the question.",
        )
        question_scrollbar = ttk.Scrollbar(
            question_frame,
            orient="vertical",
            command=self.qa_question_text.yview,
        )
        self.qa_question_text.configure(yscrollcommand=question_scrollbar.set)
        self.qa_question_text.grid(row=0, column=0, sticky="ew")
        question_scrollbar.grid(row=0, column=1, sticky="ns")
        self.qa_question_text.bind(
            "<Control-Return>", self._on_qa_question_shortcut, add="+"
        )
        question_actions = ttk.Frame(question_frame)
        question_actions.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )
        self.qa_ask_button = self.help_widget(
            ttk.Button(
                question_actions,
                text="Ask",
                command=self.ask_ai_loop_question,
            ),
            "Send the question to the selected LLM in a background process with read-only repository access.",
        )
        self.qa_ask_button.pack(side="right")
        self.qa_clear_button = self.help_widget(
            ttk.Button(
                question_actions,
                text="Clear conversation",
                command=self.clear_qa_conversation,
            ),
            "Clear the visible transcript and conversation context.",
        )
        self.qa_clear_button.pack(side="right", padx=(0, 6))

        self.qa_status_var = tk.StringVar(value="Scanning configured LLMs…")
        ttk.Label(
            parent,
            textvariable=self.qa_status_var,
            anchor="w",
        ).grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.refresh_qa_llms()

    def _qa_llm_configurations(self) -> tuple[tuple[str, str, str], ...]:
        """Return configured provider/model combinations shown when installed."""

        models = self.current_models()
        configurations = [
            ("codex", models.codex_bin, models.codex_model),
            ("claude", models.claude_bin, models.controller_model),
            ("claude", models.claude_bin, models.fable_model),
            ("claude", models.claude_bin, models.opus_model),
            ("gemini", models.gemini_bin, models.gemini_model),
        ]
        for provider, model in (
            (provider_for_role(self.controller_var.get()), self.controller_role_model_var.get()),
            (provider_for_role(self.worker_var.get()), self.worker_role_model_var.get()),
        ):
            if provider in BINARY_CHOICES:
                configurations.append(
                    (provider, self.backend.provider_binary(provider, models), model)
                )
        return tuple(configurations)

    def refresh_qa_llms(self) -> None:
        """Refresh the selector with configured LLMs whose CLI is installed."""

        if self._qa_running:
            return
        previous = self.qa_llm_var.get()
        llms = discover_available_llms(self._qa_llm_configurations())
        by_label: dict[str, AvailableLlm] = {}
        for llm in llms:
            label = llm.label
            if label in by_label and by_label[label] != llm:
                label = f"{label} ({Path(llm.binary).name})"
            by_label[label] = llm
        self._qa_llms_by_label = by_label
        labels = tuple(by_label)
        self.qa_llm_combo.configure(values=labels)
        if previous in by_label:
            self.qa_llm_var.set(previous)
        elif labels:
            self.qa_llm_var.set(labels[0])
        else:
            self.qa_llm_var.set("")
        self.qa_ask_button.configure(state="normal" if labels else "disabled")
        if labels:
            self.qa_status_var.set(
                f"{len(labels)} configured LLM option(s) available. Questions run read-only in {self.backend.root_dir}."
            )
        else:
            self.qa_status_var.set(
                "No configured LLM CLI was found. Install or configure Codex, Claude, or Gemini, then refresh."
            )

    def _on_qa_question_shortcut(self, _event: tk.Event) -> str:
        self.ask_ai_loop_question()
        return "break"

    def _append_qa_transcript(self, heading: str, content: str) -> None:
        transcript = self.qa_transcript_text
        existing = transcript.get("1.0", "end-1c")
        placeholder = "Select an available LLM, enter a question below, and click Ask."
        transcript.configure(state="normal")
        if existing == placeholder:
            transcript.delete("1.0", "end")
        elif existing:
            transcript.insert("end", "\n\n")
        transcript.insert("end", f"{heading}\n{content.strip()}")
        transcript.configure(state="disabled")
        transcript.see("end")

    def ask_ai_loop_question(self) -> None:
        """Send the current question to the selected LLM without blocking Tk."""

        if self._qa_running:
            return
        question = self.qa_question_text.get("1.0", "end-1c").strip()
        if not question:
            messagebox.showinfo("Ask AI-Loop", "Enter a question first.")
            return
        selected_label = self.qa_llm_var.get()
        llm = self._qa_llms_by_label.get(selected_label)
        if llm is None:
            messagebox.showerror(
                "Ask AI-Loop", "Select an available LLM before asking."
            )
            return

        history = tuple(self._qa_history)
        self._qa_running = True
        self.qa_ask_button.configure(state="disabled")
        self.qa_clear_button.configure(state="disabled")
        self.qa_llm_combo.configure(state="disabled")
        self.qa_question_text.delete("1.0", "end")
        self._append_qa_transcript(f"You · {selected_label}", question)
        self.qa_status_var.set(f"Asking {selected_label}…")
        self._run_bg(
            lambda: ask_project_question(
                self.backend.root_dir,
                llm,
                question,
                history=history,
            ),
            lambda answer, error: self._finish_ai_loop_question(
                answer,
                error,
                question=question,
                selected_label=selected_label,
            ),
            name="ai-loop-project-question",
            label="AI-Loop Q&A",
        )

    def _finish_ai_loop_question(
        self,
        answer: str | None,
        error: str | None,
        *,
        question: str,
        selected_label: str,
    ) -> None:
        self._qa_running = False
        self.qa_clear_button.configure(state="normal")
        self.qa_llm_combo.configure(state="readonly")
        self.qa_ask_button.configure(
            state="normal" if self._qa_llms_by_label else "disabled"
        )
        if error is not None or answer is None:
            detail = error or "The selected LLM returned no answer."
            self._append_qa_transcript("Error", detail)
            self.qa_status_var.set(f"Question failed: {detail}")
            return
        self._qa_history.append((question, answer))
        self._qa_history = self._qa_history[-12:]
        self._append_qa_transcript(f"AI-Loop answer · {selected_label}", answer)
        self.qa_status_var.set(f"Answered by {selected_label}.")

    def clear_qa_conversation(self) -> None:
        if self._qa_running:
            return
        self._qa_history.clear()
        self.set_text(
            self.qa_transcript_text,
            "Select an available LLM, enter a question below, and click Ask.",
        )
        self.qa_status_var.set("Conversation cleared.")

    def _build_project_analysis_frame(self, parent: ttk.Frame) -> None:
        """Build the opt-in project browser without starting an analysis."""

        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        vertical_paned = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        vertical_paned.grid(row=0, column=0, sticky="nsew")
        upper_pane = ttk.Frame(vertical_paned)
        lower_pane = ttk.Frame(vertical_paned)
        upper_pane.columnconfigure(0, weight=1)
        lower_pane.rowconfigure(0, weight=1)
        lower_pane.columnconfigure(0, weight=1)
        vertical_paned.add(upper_pane, weight=0)
        vertical_paned.add(lower_pane, weight=1)
        self.analysis_vertical_paned = vertical_paned
        self.analysis_upper_pane = upper_pane
        self.analysis_lower_pane = lower_pane

        def set_initial_vertical_split(event: tk.Event) -> None:
            if (
                getattr(vertical_paned, "_ai_loop_split_initialized", False)
                or event.height <= 1
            ):
                return
            vertical_paned._ai_loop_split_initialized = True
            requested = upper_pane.winfo_reqheight()
            maximum = max(80, event.height - 180)
            vertical_paned.sashpos(0, min(max(80, requested), maximum))

        vertical_paned.bind("<Configure>", set_initial_vertical_split, add="+")

        controls = ttk.Frame(upper_pane)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="Project directory").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.analysis_path_var = tk.StringVar(value=str(Path.cwd()))
        self.help_widget(
            ttk.Entry(controls, textvariable=self.analysis_path_var),
            "Directory containing the Python or C++ project to analyze.",
        ).grid(row=0, column=1, sticky="ew")
        self.help_widget(
            ttk.Button(
                controls,
                text="Browse…",
                command=self.browse_analysis_project,
            ),
            "Choose a project directory without changing the active ai-loop job.",
        ).grid(row=0, column=2, padx=(6, 0))
        self.analysis_run_button = self.help_widget(
            ttk.Button(
                controls,
                text="Analyze",
                command=self.analyze_selected_project,
            ),
            "Analyze the chosen directory in the background and populate the source browser.",
        )
        self.analysis_run_button.grid(row=0, column=3, padx=(6, 0))
        ttk.Label(controls, text="Excluded folders").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        excluded_controls = ttk.Frame(controls)
        excluded_controls.grid(
            row=1, column=1, columnspan=3, sticky="ew", pady=(6, 0)
        )
        excluded_controls.columnconfigure(0, weight=1)
        self.analysis_excluded_folders_var = tk.Variable(value=())
        self.analysis_excluded_folders_listbox = self.help_widget(
            tk.Listbox(
                excluded_controls,
                height=3,
                exportselection=False,
                listvariable=self.analysis_excluded_folders_var,
            ),
            "Project-relative folders that will be skipped by the next analysis.",
        )
        self.analysis_excluded_folders_listbox.grid(
            row=0, column=0, rowspan=2, sticky="ew"
        )
        excluded_scroll = ttk.Scrollbar(
            excluded_controls,
            orient="vertical",
            command=self.analysis_excluded_folders_listbox.yview,
        )
        excluded_scroll.grid(row=0, column=1, rowspan=2, sticky="ns")
        self.analysis_excluded_folders_listbox.configure(
            yscrollcommand=excluded_scroll.set
        )
        self.help_widget(
            ttk.Button(
                excluded_controls,
                text="Exclude folder…",
                command=self.browse_analysis_excluded_folder,
            ),
            "Choose a folder inside the project to exclude from analysis.",
        ).grid(row=0, column=2, padx=(6, 0), sticky="ew")
        self.help_widget(
            ttk.Button(
                excluded_controls,
                text="Remove",
                command=self.remove_selected_analysis_excluded_folder,
            ),
            "Remove the selected exclusion so that folder is analyzed again.",
        ).grid(row=1, column=2, padx=(6, 0), pady=(4, 0), sticky="ew")
        self.analysis_status_var = tk.StringVar(
            value="Choose a directory and click Analyze."
        )
        ttk.Label(
            controls,
            textvariable=self.analysis_status_var,
            anchor="w",
        ).grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))

        summary_frame = ttk.LabelFrame(
            upper_pane, text="Insights and Platform Capability"
        )
        summary_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        summary_frame.columnconfigure(0, weight=1)
        self.analysis_summary_var = tk.StringVar(
            value="Run an analysis to see project counts, potential problems, and platform signals."
        )
        ttk.Label(
            summary_frame,
            textvariable=self.analysis_summary_var,
            anchor="nw",
            justify="left",
            padding=6,
        ).grid(row=0, column=0, sticky="ew")

        paned = ttk.PanedWindow(lower_pane, orient=tk.HORIZONTAL)
        paned.grid(row=0, column=0, sticky="nsew")
        tree_frame = ttk.Frame(paned)
        detail_notebook = ttk.Notebook(paned)
        source_frame = ttk.Frame(detail_notebook)
        class_diagram_frame = ttk.Frame(detail_notebook)
        call_graph_frame = ttk.Frame(detail_notebook)
        dependency_diagram_frame = ttk.Frame(detail_notebook)
        paned.add(tree_frame, weight=2)
        paned.add(detail_notebook, weight=3)
        detail_notebook.add(source_frame, text="Source")
        detail_notebook.add(class_diagram_frame, text="Class Diagram")
        detail_notebook.add(call_graph_frame, text="Class Members")
        detail_notebook.add(dependency_diagram_frame, text="File Dependencies")
        self.analysis_detail_notebook = detail_notebook
        self.analysis_source_frame = source_frame
        self.analysis_member_frame = call_graph_frame
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        source_frame.rowconfigure(1, weight=1)
        source_frame.columnconfigure(0, weight=1)

        self.analysis_tree = ttk.Treeview(
            tree_frame,
            columns=("kind", "lines"),
            show="tree headings",
            selectmode="browse",
        )
        self.analysis_tree.heading("#0", text="Project / Source")
        self.analysis_tree.heading("kind", text="Kind")
        self.analysis_tree.heading("lines", text="Lines")
        self.analysis_tree.column("#0", width=300, minwidth=160)
        self.analysis_tree.column("kind", width=100, stretch=False)
        self.analysis_tree.column("lines", width=75, stretch=False, anchor="e")
        self.analysis_tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.analysis_tree.yview
        )
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.analysis_tree.configure(yscrollcommand=tree_scroll.set)
        self.analysis_tree.bind(
            "<<TreeviewSelect>>", self.on_analysis_tree_selected
        )
        self.analysis_tree.bind(
            "<ButtonRelease-1>", self.on_analysis_tree_clicked, add="+"
        )
        self.analysis_tree.bind(
            "<Double-1>", self.on_analysis_tree_double_clicked, add="+"
        )
        self.analysis_tree.bind(
            "<Motion>", self.on_analysis_tree_hover, add="+"
        )
        self.analysis_tree.bind(
            "<Leave>", self.on_analysis_tree_leave, add="+"
        )
        self.analysis_tree.bind(
            "<ButtonPress>", self.on_analysis_tree_leave, add="+"
        )

        self.analysis_source_var = tk.StringVar(value="No source selected")
        ttk.Label(
            source_frame,
            textvariable=self.analysis_source_var,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.analysis_source_text = self.help_widget(
            self.add_scrolled_text(source_frame, 1, 0, wrap="none"),
            "Read-only source code. Selecting a symbol scrolls to and highlights its line range.",
        )
        self.analysis_source_text.configure(font="TkFixedFont")
        self.analysis_source_text.tag_configure(
            "analysis_selection",
            background="#fff0a8",
            foreground="#202020",
        )
        class_diagram_frame.rowconfigure(1, weight=1)
        class_diagram_frame.columnconfigure(0, weight=1)
        class_legend = ttk.Frame(class_diagram_frame)
        class_legend.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        for label, kind in (
            ("Class", "class"),
            ("Struct", "struct"),
            ("Templated class", "templated_class"),
            ("Templated struct", "templated_struct"),
        ):
            fill, outline = self._analysis_diagram_node_colors(kind)
            tk.Label(
                class_legend,
                text=label,
                background=fill,
                foreground="#17293c",
                highlightbackground=outline,
                highlightthickness=1,
                padx=5,
                pady=2,
            ).pack(side="left", padx=(0, 6))
        class_canvas_frame = ttk.Frame(class_diagram_frame)
        class_canvas_frame.grid(row=1, column=0, sticky="nsew")
        self.analysis_class_canvas = self._build_analysis_diagram_canvas(
            class_canvas_frame,
            "Run an analysis to see class inheritance.",
        )
        self._build_analysis_zoom_controls(
            class_legend, self.analysis_class_canvas
        ).pack(side="right")
        call_graph_frame.rowconfigure(2, weight=1)
        call_graph_frame.columnconfigure(0, weight=1)
        call_graph_controls = ttk.Frame(call_graph_frame)
        call_graph_controls.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        call_graph_controls.columnconfigure(0, weight=1)
        self.analysis_call_summary_var = tk.StringVar(
            value="Run an analysis to see class fields, methods, and calls."
        )
        ttk.Label(
            call_graph_controls,
            textvariable=self.analysis_call_summary_var,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        self.help_widget(
            ttk.Button(
                call_graph_controls,
                text="Show all classes",
                command=self._show_all_analysis_class_members,
            ),
            "Clear the selected-class focus and display members of every class.",
        ).grid(row=0, column=2, padx=(8, 0), sticky="e")
        member_legend = ttk.Frame(call_graph_frame)
        member_legend.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        for label, kind in (("Method", "method"), ("Data member", "data_member")):
            fill, outline = self._analysis_diagram_node_colors(kind)
            tk.Label(
                member_legend,
                text=label,
                background=fill,
                foreground="#17293c",
                highlightbackground=outline,
                highlightthickness=1,
                padx=5,
                pady=2,
            ).pack(side="left", padx=(0, 6))
        ttk.Label(
            member_legend,
            text="Arrow: caller → callee",
        ).pack(side="left", padx=(4, 0))
        ttk.Label(
            member_legend,
            text=" · Class ring: external calls · dashed oval: member calls",
        ).pack(side="left")
        call_graph_canvas_frame = ttk.Frame(call_graph_frame)
        call_graph_canvas_frame.grid(row=2, column=0, sticky="nsew")
        self.analysis_call_canvas = self._build_analysis_diagram_canvas(
            call_graph_canvas_frame,
            "Run an analysis to see class fields, methods, and calls.",
        )
        self._build_analysis_zoom_controls(
            call_graph_controls, self.analysis_call_canvas
        ).grid(row=0, column=1, padx=(8, 0), sticky="e")
        self.analysis_dependency_canvas = self._build_analysis_diagram_canvas(
            dependency_diagram_frame,
            "Run an analysis to see project-local file dependencies.",
        )

    @staticmethod
    def _analysis_diagram_node_colors(kind: str) -> tuple[str, str]:
        """Return accessible fill and outline colors for one diagram node kind."""

        return {
            "class": ("#e7f0fb", "#315c8a"),
            "struct": ("#fff1dc", "#a46318"),
            "templated_class": ("#f2e8fb", "#74479a"),
            "templated_struct": ("#e3f6f3", "#24776f"),
            "method": ("#edf7e9", "#47723d"),
            "data_member": ("#f4edfb", "#73528d"),
            "file": ("#fff4df", "#8a652f"),
        }.get(kind, ("#e7f0fb", "#315c8a"))

    def _build_analysis_diagram_canvas(
        self, parent: ttk.Frame, placeholder: str
    ) -> tk.Canvas:
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        canvas = tk.Canvas(
            parent,
            background="#f7f8fa",
            highlightthickness=0,
        )
        horizontal = ttk.Scrollbar(parent, orient="horizontal", command=canvas.xview)
        vertical = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        canvas.create_text(
            24,
            24,
            text=placeholder,
            anchor="nw",
            fill="#59636e",
        )
        canvas._analysis_zoom = 1.0
        canvas._analysis_text_items = {}
        canvas._analysis_edge_items = []
        canvas.bind(
            "<Control-MouseWheel>",
            lambda event: self._on_analysis_diagram_zoom_wheel(canvas, event),
            add="+",
        )
        canvas.bind(
            "<Control-Button-4>",
            lambda event: self._on_analysis_diagram_zoom_wheel(canvas, event),
            add="+",
        )
        canvas.bind(
            "<Control-Button-5>",
            lambda event: self._on_analysis_diagram_zoom_wheel(canvas, event),
            add="+",
        )
        return canvas

    def _build_analysis_zoom_controls(
        self, parent: ttk.Frame, canvas: tk.Canvas
    ) -> ttk.Frame:
        controls = ttk.Frame(parent)
        self.help_widget(
            ttk.Button(
                controls,
                text="−",
                width=3,
                command=lambda: self._zoom_analysis_diagram(canvas, 0.8),
            ),
            "Zoom out. You can also hold Ctrl and scroll down over the diagram.",
        ).pack(side="left")
        self.help_widget(
            ttk.Button(
                controls,
                text="Fit",
                width=4,
                command=lambda: self._fit_analysis_diagram(canvas),
            ),
            "Fit the complete diagram into the currently visible canvas area.",
        ).pack(side="left", padx=(3, 0))
        self.help_widget(
            ttk.Button(
                controls,
                text="100%",
                width=5,
                command=lambda: self._reset_analysis_diagram_zoom(canvas),
            ),
            "Reset this diagram to its original zoom level.",
        ).pack(side="left", padx=3)
        self.help_widget(
            ttk.Button(
                controls,
                text="+",
                width=3,
                command=lambda: self._zoom_analysis_diagram(canvas, 1.25),
            ),
            "Zoom in. You can also hold Ctrl and scroll up over the diagram.",
        ).pack(side="left")
        return controls

    def _on_analysis_diagram_zoom_wheel(
        self, canvas: tk.Canvas, event: tk.Event
    ) -> str:
        zoom_in = getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0
        self._zoom_analysis_diagram(canvas, 1.25 if zoom_in else 0.8)
        return "break"

    @staticmethod
    def _zoom_analysis_diagram(canvas: tk.Canvas, factor: float) -> None:
        current = float(getattr(canvas, "_analysis_zoom", 1.0))
        minimum_zoom = AiLoopGui._analysis_fit_zoom(canvas)
        target = min(2.5, max(minimum_zoom, current * factor))
        actual_factor = target / current
        if abs(actual_factor - 1.0) < 0.001:
            return
        canvas.scale("all", 0, 0, actual_factor, actual_factor)
        canvas._analysis_zoom = target
        for item_id, text_style in getattr(
            canvas, "_analysis_text_items", {}
        ).items():
            base_size, style, base_width = text_style
            scaled_size = max(3, round(float(base_size) * target))
            font = (
                ("TkDefaultFont", scaled_size, style)
                if style
                else ("TkDefaultFont", scaled_size)
            )
            options: dict[str, Any] = {"font": font}
            options["state"] = "hidden" if target < 0.08 else "normal"
            if base_width is not None:
                options["width"] = max(12, round(float(base_width) * target))
            canvas.itemconfigure(item_id, **options)
        edge_width = max(1, round(2 * target))
        arrow_shape = tuple(max(2, round(value * target)) for value in (10, 12, 5))
        for item_id in getattr(canvas, "_analysis_edge_items", ()):
            canvas.itemconfigure(
                item_id,
                width=edge_width,
                arrowshape=arrow_shape,
            )
        bounds = canvas.bbox("all")
        if bounds is not None:
            canvas.configure(scrollregion=bounds)

    @staticmethod
    def _analysis_fit_zoom(canvas: tk.Canvas) -> float:
        """Return the smallest zoom that keeps the whole diagram visible."""

        bounds = getattr(canvas, "_analysis_base_bounds", None)
        if not isinstance(bounds, (tuple, list)) or len(bounds) != 4:
            return 0.05
        diagram_width = max(1.0, float(bounds[2]) - float(bounds[0]))
        diagram_height = max(1.0, float(bounds[3]) - float(bounds[1]))
        try:
            available_width = max(1.0, float(canvas.winfo_width()) - 12)
            available_height = max(1.0, float(canvas.winfo_height()) - 12)
        except (AttributeError, TypeError, ValueError, tk.TclError):
            return 0.05
        return min(
            1.0,
            max(
                0.01,
                min(available_width / diagram_width, available_height / diagram_height),
            ),
        )

    @classmethod
    def _fit_analysis_diagram(cls, canvas: tk.Canvas) -> None:
        """Zoom the diagram so its complete base bounds fit in the canvas."""

        current = float(getattr(canvas, "_analysis_zoom", 1.0))
        if current:
            cls._zoom_analysis_diagram(
                canvas, cls._analysis_fit_zoom(canvas) / current
            )

    @classmethod
    def _reset_analysis_diagram_zoom(cls, canvas: tk.Canvas) -> None:
        current = float(getattr(canvas, "_analysis_zoom", 1.0))
        if current:
            cls._zoom_analysis_diagram(canvas, 1.0 / current)

    def browse_analysis_project(self) -> None:
        selected = filedialog.askdirectory(
            initialdir=self.analysis_path_var.get() or str(Path.home()),
            title="Choose project directory to analyze",
        )
        if selected:
            self.analysis_path_var.set(selected)

    def _analysis_excluded_folder_values(self) -> tuple[str, ...]:
        return tuple(self.analysis_excluded_folders_listbox.get(0, tk.END))

    def _set_analysis_excluded_folder_values(
        self, excluded_folders: tuple[str, ...]
    ) -> None:
        # Updating the bound Tcl list atomically keeps the listbox display in
        # sync with the exclusion model. Direct widget mutations could leave
        # selected folder paths present in the model but absent from the view.
        self.analysis_excluded_folders_var.set(excluded_folders)
        if excluded_folders:
            self.analysis_excluded_folders_listbox.see(tk.END)

    def browse_analysis_excluded_folder(self) -> None:
        selected_project = self.analysis_path_var.get().strip()
        if not selected_project:
            messagebox.showerror(
                "Project Analysis", "Choose a project directory first."
            )
            return
        project_root = Path(selected_project).expanduser()
        if not project_root.is_dir():
            messagebox.showerror(
                "Project Analysis", "Choose an existing project directory first."
            )
            return
        selected_folder = filedialog.askdirectory(
            initialdir=str(project_root.resolve()),
            title="Choose folder to exclude from analysis",
            mustexist=True,
        )
        if not selected_folder:
            return
        try:
            excluded_folders = add_project_analysis_exclusion(
                self._analysis_excluded_folder_values(),
                project_root,
                selected_folder,
            )
        except ValueError:
            messagebox.showwarning(
                "Project Analysis",
                "The excluded folder must be inside the selected project directory.",
            )
            return
        self._set_analysis_excluded_folder_values(excluded_folders)

    def remove_selected_analysis_excluded_folder(self) -> None:
        selection = self.analysis_excluded_folders_listbox.curselection()
        if not selection:
            return
        selected_folder = self.analysis_excluded_folders_listbox.get(selection[0])
        excluded_folders = remove_project_analysis_exclusion(
            self._analysis_excluded_folder_values(), selected_folder
        )
        self._set_analysis_excluded_folder_values(excluded_folders)

    def analyze_selected_project(self) -> None:
        if self._analysis_running:
            return
        selected_path = self.analysis_path_var.get().strip()
        if not selected_path:
            messagebox.showerror(
                "Project Analysis", "Choose a project directory first."
            )
            return
        target = Path(selected_path).expanduser()
        excluded_folders = list(self._analysis_excluded_folder_values())
        self._analysis_running = True
        self.analysis_run_button.configure(state="disabled")
        self.analysis_status_var.set(f"Analyzing {target}…")

        def work() -> dict[str, Any]:
            # Keep the backend lazy: opening the GUI or tab does not import or
            # run project analysis until the user explicitly clicks Analyze.
            from ai_loop.project_analysis import analyze_project

            return analyze_project(
                target,
                exclude_folders=excluded_folders or None,
            )

        self._run_bg(
            work,
            self._finish_project_analysis,
            name="ai-loop-project-analysis",
            busy_attr="_analysis_running",
        )

    def _finish_project_analysis(
        self, model: dict[str, Any] | None, error: str | None
    ) -> None:
        self._analysis_running = False
        self.analysis_run_button.configure(state="normal")
        if error is not None or model is None:
            self.analysis_status_var.set(f"Analysis failed: {error or 'no result'}")
            messagebox.showerror(
                "Project Analysis Failed", error or "Analysis returned no result."
            )
            return
        try:
            controller = ProjectAnalysisController(model)
        except Exception as exc:
            self.analysis_status_var.set(f"Could not display analysis: {exc}")
            messagebox.showerror("Project Analysis Failed", str(exc))
            return
        self._analysis_controller = controller
        self._analysis_member_class_id = None
        self.on_analysis_tree_leave()
        for item in self.analysis_tree.get_children(""):
            self.analysis_tree.delete(item)
        self._insert_analysis_node("", controller.root_node)
        self.analysis_status_var.set(controller.root_node.summary)
        self.analysis_summary_var.set(controller.insights_summary)
        self.analysis_source_var.set("Select a file or symbol to view its source")
        self.set_text(self.analysis_source_text, "")
        self._render_analysis_diagram(
            self.analysis_class_canvas, controller.class_diagram()
        )
        self._refresh_analysis_member_diagram()
        self._render_analysis_diagram(
            self.analysis_dependency_canvas, controller.dependency_diagram()
        )

    def _refresh_analysis_member_diagram(self) -> None:
        """Refresh all class members or the currently focused class."""

        controller = self._analysis_controller
        if controller is None:
            return
        diagram = controller.member_graph_diagram(
            selected_class_id=self._analysis_member_class_id
        )
        self.analysis_call_summary_var.set(str(diagram.get("summary", "")))
        self._render_analysis_diagram(self.analysis_call_canvas, diagram)

    def _focus_analysis_member_class(self, node_id: str) -> None:
        """Focus the member graph on one selected class."""

        if node_id == getattr(self, "_analysis_member_class_id", None):
            return
        self._analysis_member_class_id = node_id
        self._refresh_analysis_member_diagram()

    def _show_all_analysis_class_members(self) -> None:
        """Clear class focus and restore the complete member diagram."""

        self._analysis_member_class_id = None
        self._refresh_analysis_member_diagram()

    def _render_analysis_diagram(
        self, canvas: tk.Canvas, diagram: dict[str, Any]
    ) -> None:
        """Draw prepared geometry; graph derivation stays in the controller."""

        self.help_tooltip.hide()
        canvas.delete("all")
        canvas._analysis_zoom = 1.0
        canvas._analysis_text_items = {}
        canvas._analysis_edge_items = []
        nodes = {
            str(node["id"]): node
            for node in diagram.get("nodes", ())
            if isinstance(node, dict) and "id" in node
        }
        for index, group in enumerate(diagram.get("groups", ())):
            if not isinstance(group, dict):
                continue
            x = int(group.get("x", 0))
            y = int(group.get("y", 0))
            width = int(group.get("width", 1))
            height = int(group.get("height", 1))
            group_tag = f"analysis_diagram_group_{index}"
            canvas.create_rectangle(
                x,
                y,
                x + width,
                y + height,
                fill="#f1f4f8",
                outline="#8796a8",
                width=2,
                tags=(group_tag,),
            )
            dependency_area = group.get("dependency_area")
            if isinstance(dependency_area, dict):
                area_x = int(dependency_area.get("x", x))
                area_y = int(dependency_area.get("y", y))
                area_width = max(1, int(dependency_area.get("width", 1)))
                area_height = max(1, int(dependency_area.get("height", 1)))
                canvas.create_oval(
                    area_x,
                    area_y,
                    area_x + area_width,
                    area_y + area_height,
                    outline="#74a6cf",
                    width=2,
                    dash=(7, 5),
                    tags=(group_tag,),
                )
            group_text = canvas.create_text(
                x + 14,
                y + 19,
                text=str(group.get("label", "Class")),
                anchor="w",
                fill="#26384b",
                font=("TkDefaultFont", 10, "bold"),
                tags=(group_tag,),
            )
            canvas._analysis_text_items[group_text] = (10, "bold", None)
            tree_node_id = str(group.get("tree_node_id", group.get("id", "")))
            description = str(group.get("description", ""))
            canvas.tag_bind(
                group_tag,
                "<Button-1>",
                lambda _event, selected=tree_node_id: (
                    self._select_analysis_diagram_node(selected)
                ),
            )
            canvas.tag_bind(
                group_tag,
                "<Enter>",
                lambda _event, text=description: (
                    self._enter_analysis_diagram_node(canvas, text)
                ),
            )
            canvas.tag_bind(
                group_tag,
                "<Leave>",
                lambda _event: self._leave_analysis_diagram_node(canvas),
            )
        for edge in diagram.get("edges", ()):
            if not isinstance(edge, dict):
                continue
            source = nodes.get(str(edge.get("source", "")))
            target = nodes.get(str(edge.get("target", "")))
            if source is None or target is None:
                continue
            source_x = int(source["x"]) + int(source["width"]) // 2
            source_y = int(source["y"]) + int(source["height"]) // 2
            target_x = int(target["x"]) + int(target["width"]) // 2
            target_y = int(target["y"]) + int(target["height"]) // 2
            delta_x = target_x - source_x
            delta_y = target_y - source_y
            if delta_x or delta_y:
                source_scale = max(
                    abs(delta_x) / max(1, int(source["width"]) / 2),
                    abs(delta_y) / max(1, int(source["height"]) / 2),
                )
                target_scale = max(
                    abs(delta_x) / max(1, int(target["width"]) / 2),
                    abs(delta_y) / max(1, int(target["height"]) / 2),
                )
                line_start_x = source_x + delta_x / source_scale
                line_start_y = source_y + delta_y / source_scale
                line_end_x = target_x - delta_x / target_scale
                line_end_y = target_y - delta_y / target_scale
                line_coordinates = (
                    line_start_x,
                    line_start_y,
                    line_end_x,
                    line_end_y,
                )
                edge_label_x = (line_start_x + line_end_x) / 2
                edge_label_y = (line_start_y + line_end_y) / 2 - 9
                smooth_edge = False
            else:
                node_right = source_x + int(source["width"]) / 2
                loop_reach = max(42, int(source["width"]) // 4)
                line_coordinates = (
                    node_right,
                    source_y - 12,
                    node_right + loop_reach,
                    source_y - int(source["height"]),
                    node_right + loop_reach,
                    source_y + int(source["height"]),
                    node_right,
                    source_y + 12,
                )
                edge_label_x = node_right + loop_reach
                edge_label_y = source_y - int(source["height"]) - 9
                smooth_edge = True
            edge_line = canvas.create_line(
                *line_coordinates,
                arrow=tk.LAST,
                width=2,
                arrowshape=(10, 12, 5),
                fill="#1f5f99",
                smooth=smooth_edge,
            )
            canvas._analysis_edge_items.append(edge_line)
            if callee_method := str(edge.get("callee_method", "")):
                method_name = callee_method.rsplit(".", 1)[-1].rsplit("::", 1)[-1]
                call_line = edge.get("call_line")
                try:
                    call_count = max(1, int(edge.get("call_count", 1)))
                except (TypeError, ValueError):
                    call_count = 1
                if source.get("kind") == target.get("kind") == "method":
                    if call_count > 1:
                        edge_label = f"{call_count} calls"
                        if call_line is not None:
                            edge_label += f" · first line {call_line}"
                    else:
                        edge_label = (
                            f"line {call_line}"
                            if call_line is not None
                            else "calls"
                        )
                else:
                    edge_label = (
                        f"{method_name} · line {call_line}"
                        if call_line is not None
                        else method_name
                    )
                edge_text = canvas.create_text(
                    edge_label_x,
                    edge_label_y,
                    text=edge_label,
                    fill="#40566e",
                    font=("TkDefaultFont", 8),
                )
                canvas._analysis_text_items[edge_text] = (8, "", None)

        for index, node in enumerate(nodes.values()):
            x = int(node["x"])
            y = int(node["y"])
            width = int(node["width"])
            height = int(node["height"])
            node_tag = f"analysis_diagram_node_{index}"
            kind = str(node.get("kind", ""))
            fill, outline = self._analysis_diagram_node_colors(kind)
            canvas.create_rectangle(
                x,
                y,
                x + width,
                y + height,
                fill=fill,
                outline=outline,
                width=2,
                tags=(node_tag,),
            )
            subtitle = str(node.get("subtitle", ""))
            title_y = y + height // 2 - (9 if subtitle else 0)
            title_text = canvas.create_text(
                x + width // 2,
                title_y,
                text=str(node.get("label", node["id"])),
                width=width - 12,
                justify="center",
                fill="#17293c",
                font=("TkDefaultFont", 10),
                tags=(node_tag,),
            )
            canvas._analysis_text_items[title_text] = (10, "", width - 12)
            if subtitle:
                subtitle_text = canvas.create_text(
                    x + width // 2,
                    y + height // 2 + 14,
                    text=subtitle,
                    width=width - 12,
                    justify="center",
                    fill="#506273",
                    font=("TkDefaultFont", 8),
                    tags=(node_tag,),
                )
                canvas._analysis_text_items[subtitle_text] = (
                    8,
                    "",
                    width - 12,
                )
            tree_node_id = str(node.get("tree_node_id", node["id"]))
            description = str(node.get("description", ""))
            canvas.tag_bind(
                node_tag,
                "<Button-1>",
                lambda _event, selected=tree_node_id: (
                    self._select_analysis_diagram_node(selected)
                ),
            )
            canvas.tag_bind(
                node_tag,
                "<Enter>",
                lambda _event, text=description: (
                    self._enter_analysis_diagram_node(canvas, text)
                ),
            )
            canvas.tag_bind(
                node_tag,
                "<Leave>",
                lambda _event: self._leave_analysis_diagram_node(canvas),
            )

        width = max(1, int(diagram.get("width", 1)))
        height = max(1, int(diagram.get("height", 1)))
        bounds = canvas.bbox("all")
        scrollregion = (
            (
                min(0, bounds[0]),
                min(0, bounds[1]),
                max(width, bounds[2]),
                max(height, bounds[3]),
            )
            if bounds is not None
            else (0, 0, width, height)
        )
        canvas._analysis_base_bounds = scrollregion
        canvas.configure(scrollregion=scrollregion)
        canvas.xview_moveto(0)
        canvas.yview_moveto(0)

    def _enter_analysis_diagram_node(
        self, canvas: tk.Canvas, description: str
    ) -> None:
        canvas.configure(cursor="hand2")
        if description:
            self.help_tooltip._schedule_show(canvas, description)

    def _leave_analysis_diagram_node(self, canvas: tk.Canvas) -> None:
        canvas.configure(cursor="")
        self.help_tooltip.hide()

    def _select_analysis_diagram_node(self, node_id: str) -> None:
        self.help_tooltip.hide()
        if not self.analysis_tree.exists(node_id):
            return
        self.analysis_tree.selection_set(node_id)
        self.analysis_tree.focus(node_id)
        self.analysis_tree.see(node_id)
        self.on_analysis_tree_selected()
        controller = self._analysis_controller
        node = controller.node(node_id) if controller is not None else None
        target_frame = (
            self.analysis_member_frame
            if node is not None and node.kind == "class"
            else self.analysis_source_frame
        )
        self.analysis_detail_notebook.select(target_frame)

    def _insert_analysis_node(self, parent_id: str, node: ProjectTreeNode) -> None:
        if node.line is None:
            lines = ""
        elif node.end_line is None or node.end_line == node.line:
            lines = str(node.line)
        else:
            lines = f"{node.line}–{node.end_line}"
        self.analysis_tree.insert(
            parent_id,
            "end",
            iid=node.node_id,
            text=node.label,
            values=(node.kind.replace("_", " "), lines),
            open=node.kind == "project",
        )
        for child in node.children:
            self._insert_analysis_node(node.node_id, child)

    def on_analysis_tree_selected(self, _event: tk.Event | None = None) -> None:
        selected = self.analysis_tree.selection()
        if not selected:
            return
        node_id = selected[0]
        controller = self._analysis_controller
        node = controller.node(node_id) if controller is not None else None
        if (
            node is not None
            and node.kind == "class"
            and node_id != getattr(self, "_analysis_member_class_id", None)
        ):
            self._focus_analysis_member_class(node_id)
        self._show_analysis_tree_node(node_id)

    def on_analysis_tree_clicked(self, event: tk.Event) -> None:
        node_id = self.analysis_tree.identify_row(event.y)
        controller = self._analysis_controller
        node = (
            controller.node(node_id)
            if controller is not None and node_id
            else None
        )
        if node is None or node.kind != "class":
            return
        self.analysis_tree.selection_set(node_id)
        self.analysis_tree.focus(node_id)
        self._focus_analysis_member_class(node_id)
        self._show_analysis_tree_node(node_id)
        self.analysis_detail_notebook.select(self.analysis_member_frame)

    def on_analysis_tree_double_clicked(self, event: tk.Event) -> str | None:
        node_id = self.analysis_tree.identify_row(event.y)
        controller = self._analysis_controller
        node = (
            controller.node(node_id)
            if controller is not None and node_id
            else None
        )
        if node is None or node.kind != "method":
            return None
        self.analysis_tree.selection_set(node_id)
        self.analysis_tree.focus(node_id)
        self._show_analysis_tree_node(node_id)
        self.analysis_detail_notebook.select(self.analysis_source_frame)
        return "break"

    def on_analysis_tree_hover(self, event: tk.Event) -> None:
        node_id = self.analysis_tree.identify_row(event.y)
        controller = self._analysis_controller
        node = (
            controller.node(node_id)
            if controller is not None and node_id
            else None
        )
        if (
            node is None
            or node.kind not in {"class", "method"}
            or not node.description
        ):
            self.on_analysis_tree_leave()
            return
        if node_id == getattr(self, "_analysis_tooltip_node_id", None):
            return
        self.help_tooltip.hide()
        self._analysis_tooltip_node_id = node_id
        self.help_tooltip._schedule_show(self.analysis_tree, node.description)

    def on_analysis_tree_leave(self, _event: tk.Event | None = None) -> None:
        self._analysis_tooltip_node_id = None
        self.help_tooltip.hide()

    def _show_analysis_tree_node(self, node_id: str) -> None:
        controller = self._analysis_controller
        if controller is None:
            return
        node = controller.node(node_id)
        if node is None:
            return
        self.analysis_status_var.set(
            f"{node.label}: {node.summary}" if node.summary else node.label
        )
        location = controller.resolve_selection(node.node_id)
        if location is None:
            return
        try:
            source = location.path.read_text(encoding="utf-8", errors="replace")
            display_path = location.path.relative_to(controller.project_path)
        except (OSError, ValueError) as exc:
            self.analysis_source_var.set(f"Could not read source: {exc}")
            return

        self.set_text(self.analysis_source_text, source)
        self.analysis_source_text.configure(state="normal")
        self.analysis_source_text.tag_remove("analysis_selection", "1.0", "end")
        start = f"{location.line}.0"
        end = f"{location.end_line + 1}.0"
        self.analysis_source_text.tag_add("analysis_selection", start, end)
        self.analysis_source_text.mark_set("insert", start)
        self.analysis_source_text.see(start)
        self.analysis_source_text.configure(state="disabled")
        self.analysis_source_var.set(
            f"{display_path.as_posix()} — lines {location.line}–{location.end_line}"
        )

    def _build_create_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Create Job", padding=8)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(1, weight=1)

        self.repo_var = tk.StringVar(value=str(Path.cwd()))
        self.test_cmd_var = tk.StringVar(value="auto")
        self.base_ref_var = tk.StringVar(value="HEAD")
        self.max_iterations_var = tk.IntVar(value=50000)
        worker_default = self.backend.settings.worker_default
        controller_default = self.backend.settings.controller_default
        self.worker_var = tk.StringVar(value=provider_for_role(worker_default) or "codex")
        self.controller_var = tk.StringVar(value=provider_for_role(controller_default) or "claude")
        self.granularity_var = tk.StringVar(value="normal")
        self.no_worktree_var = tk.BooleanVar(value=False)
        self.allow_parallel_var = tk.BooleanVar(value=False)
        self.codex_model_var = tk.StringVar(value=self.model_defaults.codex_model)
        self.fable_model_var = tk.StringVar(value=self.model_defaults.fable_model)
        self.opus_model_var = tk.StringVar(value=self.model_defaults.opus_model)
        self.gemini_model_var = tk.StringVar(value=self.model_defaults.gemini_model)
        self.controller_model_var = tk.StringVar(value=self.model_defaults.controller_model)
        self.codex_bin_var = tk.StringVar(value=self.model_defaults.codex_bin)
        self.claude_bin_var = tk.StringVar(value=self.model_defaults.claude_bin)
        self.gemini_bin_var = tk.StringVar(value=self.model_defaults.gemini_bin)
        self.bypass_var = tk.BooleanVar(value=self.model_defaults.codex_bypass_sandbox)
        self.role_model_values = {
            "controller": {
                "codex": self.model_defaults.codex_model,
                "claude": self.configured_model_for_role(controller_default),
                "gemini": self.model_defaults.gemini_model,
            },
            "worker": {
                "codex": self.model_defaults.codex_model,
                "claude": self.configured_model_for_role(worker_default),
                "gemini": self.model_defaults.gemini_model,
            },
        }
        self.role_model_values["controller"][self.controller_var.get()] = (
            self.model_defaults.controller_role_model
            or self.role_model_values["controller"][self.controller_var.get()]
        )
        self.role_model_values["worker"][self.worker_var.get()] = (
            self.model_defaults.worker_role_model
            or self.role_model_values["worker"][self.worker_var.get()]
        )
        self.role_binary_previous = {
            "controller": self.controller_var.get(),
            "worker": self.worker_var.get(),
        }
        self.controller_role_model_var = tk.StringVar(
            value=self.role_model_values["controller"][self.controller_var.get()]
        )
        self.worker_role_model_var = tk.StringVar(
            value=self.role_model_values["worker"][self.worker_var.get()]
        )

        ttk.Label(frame, text="Repo").grid(row=0, column=0, sticky="w")
        self.help_widget(ttk.Entry(frame, textvariable=self.repo_var, width=12), "Repository root for the job. The selected path is where the job will read and write.").grid(row=0, column=1, sticky="ew", padx=4)
        browse_buttons = ttk.Frame(frame)
        browse_buttons.grid(row=0, column=2, sticky="e")
        self.help_widget(ttk.Button(browse_buttons, text="Goal File", command=self.browse_goal_file), "Pick a text file and load its contents into the goal box while setting the repo path to that file's parent directory.").pack(side="left")
        self.help_widget(
            ttk.Button(browse_buttons, text="Clear Goal", command=self.clear_goal),
            "Remove all text from the Goal field so that a new job description can be entered.",
        ).pack(side="left", padx=(4, 0))
        self.help_widget(ttk.Button(browse_buttons, text="Repo Folder", command=self.browse_repo_folder), "Choose the repository folder that the job should modify.").pack(side="left", padx=(4, 0))

        ttk.Label(frame, text="Goal").grid(row=1, column=0, sticky="nw", pady=(6, 0))
        self.goal_text = self.help_widget(tk.Text(frame, height=12, width=24, wrap="word"), "Describe the work the loop should do. This is the main job goal and should be specific enough to test.")
        self.goal_text.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(6, 0))

        ttk.Label(frame, text="Test").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.help_widget(ttk.Entry(frame, textvariable=self.test_cmd_var, width=12), "Validation command run after each worker task. Use auto to infer a command from the target repository.").grid(row=2, column=1, columnspan=2, sticky="ew", pady=(6, 0))

        settings = ttk.Frame(frame)
        settings.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)

        ttk.Label(settings, text="Controller binary").grid(row=0, column=0, sticky="w")
        controller_binary = self.help_widget(
            ttk.Combobox(settings, textvariable=self.controller_var, values=BINARY_CHOICES, width=8, state="readonly"),
            "CLI binary used by the controller that plans and reviews the job. Changing it loads the model last entered for that binary.",
        )
        controller_binary.grid(row=0, column=1, sticky="ew", padx=(3, 6))
        controller_binary.bind("<<ComboboxSelected>>", lambda _event: self.on_role_binary_selected("controller"))
        ttk.Label(settings, text="Controller model").grid(row=0, column=2, sticky="w")
        self.help_widget(ttk.Entry(settings, textvariable=self.controller_role_model_var, width=12), "Optional model for the selected controller binary. Leave blank to use that CLI's configured default.").grid(
            row=0, column=3, sticky="ew", padx=(4, 0)
        )

        ttk.Label(settings, text="Worker binary").grid(row=1, column=0, sticky="w", pady=(5, 0))
        worker_binary = self.help_widget(
            ttk.Combobox(settings, textvariable=self.worker_var, values=BINARY_CHOICES, width=8, state="readonly"),
            "CLI binary used by the worker that edits the worktree and runs the task. Changing it loads the model last entered for that binary.",
        )
        worker_binary.grid(row=1, column=1, sticky="ew", padx=(3, 6), pady=(5, 0))
        worker_binary.bind("<<ComboboxSelected>>", lambda _event: self.on_role_binary_selected("worker"))
        ttk.Label(settings, text="Worker model").grid(row=1, column=2, sticky="w", pady=(5, 0))
        self.help_widget(ttk.Entry(settings, textvariable=self.worker_role_model_var, width=12), "Optional model for the selected worker binary. Leave blank to use that CLI's configured default.").grid(
            row=1, column=3, sticky="ew", padx=(4, 0), pady=(5, 0)
        )

        ttk.Label(settings, text="Base ref").grid(row=2, column=0, sticky="w", pady=(5, 0))
        self.help_widget(ttk.Entry(settings, textvariable=self.base_ref_var, width=10), "Git ref used when creating the isolated worktree.").grid(row=2, column=1, sticky="ew", padx=(3, 6), pady=(5, 0))
        ttk.Label(settings, text="Max iterations").grid(row=2, column=2, sticky="w", pady=(5, 0))
        self.help_widget(ttk.Spinbox(settings, from_=1, to=50000, width=8, textvariable=self.max_iterations_var), "Upper bound for job iterations. Lower values cut the remaining workload sooner.").grid(
            row=2, column=3, sticky="ew", padx=(4, 0), pady=(5, 0)
        )

        toggles = ttk.Frame(settings)
        toggles.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        self.help_widget(ttk.Label(toggles, text="Granularity"), "Task sizing policy used for new jobs and when resuming the selected job.").pack(side="left", padx=(0, 4))
        self.help_widget(
            ttk.Combobox(toggles, textvariable=self.granularity_var, values=GRANULARITIES, width=8, state="readonly"),
            "Fine uses narrow tasklets and frequent controller review. Normal groups closely related changes into medium-sized, testable tasks. Coarse combines related discovery, implementation, documentation, and verification into a few substantial tasks. All choices keep the same acceptance and test-quality requirements.",
        ).pack(side="left", padx=(0, 12))
        self.help_widget(ttk.Checkbutton(toggles, text="Bypass worker sandbox", variable=self.bypass_var), "Run the worker without sandbox restrictions. Leave this off unless you need to debug or the environment is trusted.").pack(side="left", padx=(0, 12))
        create_actions = ttk.Frame(settings)
        create_actions.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(5, 0))
        self.help_widget(ttk.Checkbutton(create_actions, text="No worktree", variable=self.no_worktree_var), "Run directly in the target repository instead of creating an isolated Git worktree.").pack(side="left", padx=(0, 12))
        self.help_widget(ttk.Checkbutton(create_actions, text="Allow parallel", variable=self.allow_parallel_var), "Allow this job to start even if another job is already active.").pack(side="left")
        self.help_widget(ttk.Button(create_actions, text="Quick Job", command=self.create_job), "Immediately create a normal text-goal job with the current goal, static plan, granularity, test command, controller, worker, and environment settings.").pack(side="right")

    def _build_jobs_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Jobs", padding=6)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        columns = ("status", "progress", "controller", "worker", "tasks", "runs", "updated")
        self.jobs_tree = self.help_widget(ttk.Treeview(frame, columns=columns, show="tree headings", selectmode="browse", style="Jobs.Treeview"), "Job list with the current status, progress estimate, and latest task row for each job.")
        self.jobs_tree.heading("#0", text="Job")
        self.jobs_tree.column("#0", width=150, stretch=False)
        for name, width in (
            ("status", 110),
            ("progress", 55),
            ("controller", 55),
            ("worker", 55),
            ("tasks", 40),
            ("runs", 40),
            ("updated", 90),
        ):
            self.jobs_tree.heading(name, text=name.title())
            self.jobs_tree.column(name, width=width, stretch=False)
        self.jobs_tree.grid(row=0, column=0, sticky="nsew")
        self.configure_job_status_tags()
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.jobs_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.jobs_tree.configure(yscrollcommand=scrollbar.set)
        self.jobs_tree.bind("<<TreeviewSelect>>", self.on_job_selected)

    def add_scrolled_text(self, parent: ttk.Frame, row: int, column: int, *, wrap: str = "word") -> tk.Text:
        holder = ttk.Frame(parent)
        holder.grid(row=row, column=column, sticky="nsew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        text = tk.Text(holder, width=40, wrap=wrap, font=("TkDefaultFont", 11), padx=8, pady=8, spacing1=2, spacing3=4)
        y_scroll = ttk.Scrollbar(holder, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=y_scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        if wrap == "none":
            x_scroll = ttk.Scrollbar(holder, orient="horizontal", command=text.xview)
            text.configure(xscrollcommand=x_scroll.set)
            x_scroll.grid(row=1, column=0, sticky="ew")
        setattr(text, "_ai_loop_read_only", True)
        text.configure(state="disabled")
        return text

    def _build_detail_frame(self, parent: ttk.Frame) -> None:
        notebook = self.help_widget(
            ttk.Notebook(parent),
            "Switch between the plain-language plan, current task, system status, controller messages, worker reports, formal verification, database details, and raw process logs.",
        )
        self.detail_notebook = notebook
        notebook.grid(row=0, column=0, sticky="nsew")
        plan_tab = ttk.Frame(notebook, padding=8)
        task_tab = ttk.Frame(notebook, padding=8)
        status_tab = ttk.Frame(notebook, padding=8)
        controller_tab = ttk.Frame(notebook, padding=8)
        worker_tab = ttk.Frame(notebook, padding=8)
        details_tab = ttk.Frame(notebook, padding=8)
        verification_tab = ttk.Frame(notebook)
        logs = ttk.Frame(notebook, padding=8)
        for tab, label in (
            (plan_tab, "Plan"),
            (task_tab, "Task"),
            (status_tab, "Status"),
            (controller_tab, "Controller"),
            (worker_tab, "Worker"),
            (details_tab, "Details"),
            (verification_tab, "Verification"),
            (logs, "Logs"),
        ):
            notebook.add(tab, text=label)
            tab.rowconfigure(0, weight=1)
            tab.columnconfigure(0, weight=1)
        self.verification_tab = verification_tab
        notebook.tab(verification_tab, state="hidden")
        self.verification_dashboard_view = VerificationDashboardView(
            verification_tab,
            refresh_command=lambda: self.refresh_verification_dashboard(force=True),
            acknowledge_command=self.acknowledge_selected_manual_verification,
            default_actor=os.environ.get("USER") or os.environ.get("USERNAME") or "gui-user",
        )
        self.verification_dashboard_view.frame.grid(row=0, column=0, sticky="nsew")
        self.plan_text = self.help_widget(
            self.add_scrolled_text(plan_tab, 0, 0),
            "The fixed overall job plan in simple language. The highlighted line is the plan item most closely matching the current task.",
        )
        self.plan_text.tag_configure("current_plan_item", background="#fff0a8", foreground="#202020", font=("TkDefaultFont", 11, "bold"))
        self.task_text = self.help_widget(
            self.add_scrolled_text(task_tab, 0, 0),
            "The current task followed by a detailed explanation of its goal, progress, constraints, checks, and expected result.",
        )
        self.status_text = self.help_widget(
            self.add_scrolled_text(status_tab, 0, 0),
            "Current controller, worker, Redis, SMTP delivery, mailbox access, process, blocker, and suggested-solution status in plain language.",
        )
        self.controller_text = self.help_widget(
            self.add_scrolled_text(controller_tab, 0, 0),
            "Recent instructions and explanations sent by the controller, with the newest message first and raw JSON omitted.",
        )
        self.worker_text = self.help_widget(
            self.add_scrolled_text(worker_tab, 0, 0),
            "What the worker is doing now and the recent results it returned to the controller, including tests and changed files.",
        )
        self.detail_text = self.help_widget(
            self.add_scrolled_text(details_tab, 0, 0),
            "Extensive diagnostic details assembled from SQLite, process state, Redis state, progress estimates, tasks, runs, decisions, and events.",
        )
        resume_frame = ttk.LabelFrame(parent, text="Resume Job", padding=8)
        resume_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        for column in range(6):
            resume_frame.columnconfigure(column, weight=1)
        self.extra_constraint_var = tk.StringVar()
        self.extra_acceptance_var = tk.StringVar()
        ttk.Label(resume_frame, text="Uses the controller, worker, models, and granularity selected above.").grid(row=0, column=0, columnspan=4, sticky="w")
        self.help_widget(ttk.Button(resume_frame, text="Apply + Resume", command=self.resume_selected_job), "Apply the controller binary/model, worker binary/model, and granularity selected above, then queue a new plan for the job.").grid(row=0, column=4, columnspan=2, sticky="e")
        ttk.Label(resume_frame, text="Extra constraint").grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.help_widget(ttk.Entry(resume_frame, textvariable=self.extra_constraint_var), "Optional extra constraint to add before resuming the job.").grid(row=1, column=1, columnspan=5, sticky="ew", pady=(5, 0))
        ttk.Label(resume_frame, text="Extra acceptance").grid(row=2, column=0, sticky="w", pady=(5, 0))
        self.help_widget(ttk.Entry(resume_frame, textvariable=self.extra_acceptance_var), "Optional extra acceptance criterion to add before resuming the job.").grid(row=2, column=1, columnspan=5, sticky="ew", pady=(5, 0))
        self.fix_binary_var = tk.StringVar(value=self.codex_bin_var.get() or "codex")
        ttk.Label(resume_frame, text="Fix binary").grid(row=3, column=0, sticky="w", pady=(5, 0))
        self.help_widget(
            ttk.Combobox(
                resume_frame,
                textvariable=self.fix_binary_var,
                values=(self.codex_bin_var.get() or "codex", self.claude_bin_var.get() or "claude", self.gemini_bin_var.get() or "gemini"),
                width=18,
            ),
            "CLI binary to use for the repair helper when the selected job needs a manual or assisted fix.",
        ).grid(row=3, column=1, columnspan=3, sticky="ew", pady=(5, 0))
        self.help_widget(ttk.Button(resume_frame, text="Fix It", command=self.fix_selected_job), "Run the selected binary to diagnose or repair the job, then resume it if successful.").grid(row=3, column=4, columnspan=2, sticky="e", pady=(5, 0))
        logs.rowconfigure(0, weight=0)
        logs.rowconfigure(1, weight=1)
        logs.columnconfigure(0, weight=1)
        log_bar = ttk.Frame(logs)
        log_bar.grid(row=0, column=0, sticky="ew")
        self.log_name_var = tk.StringVar(value=PROCESS_LABELS["worker"])
        self.help_widget(
            ttk.Combobox(log_bar, textvariable=self.log_name_var, values=list(LOG_LABELS), state="readonly", width=20),
            "Choose which process log to view: controller, worker, or watcher.",
        ).grid(row=0, column=0, padx=(0, 6))
        self.help_widget(ttk.Button(log_bar, text="Refresh Log", command=self.refresh_log), "Reload the selected log file from disk and jump to the end if it changed.").grid(row=0, column=1)
        self.log_text = self.help_widget(self.add_scrolled_text(logs, 1, 0), "Selected process log file, including controller, worker, or watcher output. Long lines wrap at the right edge so all text remains readable.")

    def current_models(self) -> ModelDefaults:
        return ModelDefaults(
            codex_model=self.codex_model_var.get().strip(),
            fable_model=self.fable_model_var.get().strip(),
            opus_model=self.opus_model_var.get().strip(),
            gemini_model=self.gemini_model_var.get().strip(),
            controller_model=self.controller_model_var.get().strip(),
            codex_bin=self.codex_bin_var.get().strip() or "codex",
            claude_bin=self.claude_bin_var.get().strip() or "claude",
            gemini_bin=self.gemini_bin_var.get().strip() or "gemini",
            codex_bypass_sandbox=bool(self.bypass_var.get()),
            controller_role_model=self.controller_role_model_var.get().strip(),
            worker_role_model=self.worker_role_model_var.get().strip(),
        )

    def configured_model_for_role(self, role: str) -> str:
        role = role.strip().lower()
        if role == "codex":
            return self.model_defaults.codex_model
        if role == "gemini":
            return self.model_defaults.gemini_model
        if role == "opus":
            return self.model_defaults.opus_model
        if role == "fable":
            return self.model_defaults.fable_model
        return self.model_defaults.controller_model

    def on_role_binary_selected(self, role: str) -> None:
        binary_var = self.controller_var if role == "controller" else self.worker_var
        model_var = (
            self.controller_role_model_var
            if role == "controller"
            else self.worker_role_model_var
        )
        previous_binary = self.role_binary_previous[role]
        self.role_model_values[role][previous_binary] = model_var.get()
        selected_binary = binary_var.get()
        model_var.set(self.role_model_values[role][selected_binary])
        self.role_binary_previous[role] = selected_binary

    def browse_goal_file(self) -> None:
        selected = filedialog.askopenfilename(
            initialdir=self.repo_var.get() or str(Path.home()),
            title="Choose a goal text file",
            filetypes=(("Text files", "*.txt *.md *.rst *.adoc"), ("All files", "*")),
        )
        if selected:
            path = Path(selected)
            self.repo_var.set(str(path.parent))
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = path.read_text(errors="replace")
            self.set_text(self.goal_text, content)

    def clear_goal(self) -> None:
        self.set_text(self.goal_text, "")
        self.goal_text.focus_set()

    def browse_repo_folder(self) -> None:
        selected_dir = filedialog.askdirectory(initialdir=self.repo_var.get() or str(Path.home()), title="Choose repository folder")
        if selected_dir:
            self.repo_var.set(selected_dir)

    def open_formal_specification(self) -> None:
        """Select and initialize the dedicated specification workspace tab."""

        self.workspace.select(self.specification_tab)
        self._ensure_specification_tab_editor()

    def _formal_elicitation_provider(self) -> CliStructuredOutputProvider:
        """Snapshot the currently selected controller CLI/model on the Tk thread."""

        provider = self.controller_var.get().strip().lower()
        models = self.current_models()
        return CliStructuredOutputProvider(
            provider=provider,
            binary=self.backend.provider_binary(provider, models),
            model=models.controller_role_model,
        )

    def _formal_implementation_work(
        self, snapshot: StoredSpecificationVersion
    ) -> Any:
        """Snapshot Quick Job settings and return its formal creation operation."""

        conflict = self._exclusive_conflict("job")
        if conflict is not None:
            raise RuntimeError(
                f"cannot start implementation while {conflict} is running"
            )
        worker = normalize_worker(self.worker_var.get())
        controller = normalize_controller(self.controller_var.get())
        models = self.current_models()
        repo = Path(snapshot.repository_path)
        test_cmd = self.test_cmd_var.get().strip() or "auto"
        max_iterations = int(self.max_iterations_var.get())
        base_ref = self.base_ref_var.get().strip() or "HEAD"
        use_worktree = not self.no_worktree_var.get()
        allow_parallel = bool(self.allow_parallel_var.get())
        granularity = self.granularity_var.get()

        def work() -> str:
            return self.backend.create_job(
                repo=repo,
                goal=snapshot.document.summary,
                test_cmd=test_cmd,
                constraints=[],
                acceptance=[],
                max_iterations=max_iterations,
                base_ref=base_ref,
                use_worktree=use_worktree,
                allow_parallel=allow_parallel,
                worker=worker,
                controller=controller,
                granularity=granularity,
                models=models,
                specification_id=snapshot.specification_id,
                specification_version=snapshot.version,
            )

        return work

    def _formal_implementation_started(self, job_id: str) -> None:
        self.watch_job_id = job_id
        self.refresh_all(select_job_id=job_id)

    def create_job(self) -> None:
        goal = self.goal_text.get("1.0", "end").strip()
        if not goal:
            messagebox.showerror("Missing Goal", "Enter a job goal.")
            return
        if self._create_job_running:
            messagebox.showinfo("Create Job", "A job is already being created; wait for it to finish.")
            return
        conflict = self._exclusive_conflict("job")
        if conflict is not None:
            messagebox.showinfo("Create Job", f"Cannot start Create Job while {conflict} is running.")
            return
        try:
            worker = normalize_worker(self.worker_var.get())
            controller = normalize_controller(self.controller_var.get())
        except Exception as exc:
            messagebox.showerror("Create Job Failed", str(exc))
            return
        models = self.current_models()
        # Snapshot every form value at click time so edits made while the
        # provider-CLI check runs in the background cannot mix into this job.
        try:
            repo = Path(self.repo_var.get())
            test_cmd = self.test_cmd_var.get().strip() or "auto"
            max_iterations = int(self.max_iterations_var.get())
            base_ref = self.base_ref_var.get().strip() or "HEAD"
            use_worktree = not self.no_worktree_var.get()
            allow_parallel = bool(self.allow_parallel_var.get())
            granularity = self.granularity_var.get()
        except Exception as exc:
            messagebox.showerror("Create Job Failed", str(exc))
            return
        self._create_job_running = True
        # The provider-CLI check below runs on a raw thread, not _run_bg, so
        # track the label manually; finish_create_job's _run_bg call re-adds
        # the same label (set semantics) and its finisher removes it.
        self._active_operations.add("Create Job")
        self.status_var.set("Checking AI provider command-line tools…")

        def ensure_clis() -> None:
            try:
                self.backend.ensure_provider_clis(worker=worker, controller=controller, models=models)
            except Exception as exc:
                try:
                    self.after(
                        0,
                        lambda error=str(exc): self.finish_create_job(
                            goal,
                            worker,
                            controller,
                            models,
                            repo=repo,
                            test_cmd=test_cmd,
                            max_iterations=max_iterations,
                            base_ref=base_ref,
                            use_worktree=use_worktree,
                            allow_parallel=allow_parallel,
                            granularity=granularity,
                            error=error,
                        ),
                    )
                except (tk.TclError, RuntimeError):
                    pass
                return
            try:
                self.after(
                    0,
                    lambda: self.finish_create_job(
                        goal,
                        worker,
                        controller,
                        models,
                        repo=repo,
                        test_cmd=test_cmd,
                        max_iterations=max_iterations,
                        base_ref=base_ref,
                        use_worktree=use_worktree,
                        allow_parallel=allow_parallel,
                        granularity=granularity,
                        error=None,
                    ),
                )
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(
            target=ensure_clis,
            name="ai-loop-provider-cli",
            daemon=True,
        ).start()

    def finish_create_job(
        self,
        goal: str,
        worker: str,
        controller: str,
        models: ModelDefaults,
        *,
        repo: Path,
        test_cmd: str,
        max_iterations: int,
        base_ref: str,
        use_worktree: bool,
        allow_parallel: bool,
        granularity: str,
        error: str | None,
    ) -> None:
        if error is not None:
            self._create_job_running = False
            self._active_operations.discard("Create Job")
            messagebox.showerror("Create Job Failed", error)
            return
        # Keep the busy flag set: backend.create_job (pre-job git commit,
        # worktree add, checkout overlay copy, process launch, notification
        # email) can take a long time on big repos, so it runs in a second
        # background thread. All values were snapshotted at click time.
        self.status_var.set("Creating job (snapshot commit, worktree, processes)…")
        self._run_bg(
            lambda: self.backend.create_job(
                repo=repo,
                goal=goal,
                test_cmd=test_cmd,
                constraints=[],
                acceptance=[],
                max_iterations=max_iterations,
                base_ref=base_ref,
                use_worktree=use_worktree,
                allow_parallel=allow_parallel,
                worker=worker,
                controller=controller,
                granularity=granularity,
                models=models,
            ),
            self._finish_create_job_done,
            name="ai-loop-create-job",
            busy_attr="_create_job_running",
            label="Create Job",
        )

    def _finish_create_job_done(self, job_id: str | None, error: str | None) -> None:
        self._create_job_running = False
        if error is not None:
            messagebox.showerror("Create Job Failed", error)
            return
        self.watch_job_id = job_id
        self.refresh_all(select_job_id=job_id)

    def configure_job_status_tags(self) -> None:
        for status, color in JOB_STATUS_COLORS.items():
            self.jobs_tree.tag_configure(status, background=color)
        self.update_jobs_selection_style()

    def update_jobs_selection_style(self) -> None:
        selected = self.jobs_tree.selection()
        status = ""
        if selected:
            tags = self.jobs_tree.item(selected[0], "tags")
            status = str(tags[0]) if tags else ""
        selected_color = JOB_STATUS_COLORS.get(status, "#d9e8ff")
        style = ttk.Style(self)
        style.map("Jobs.Treeview", background=[("selected", selected_color)], foreground=[("selected", "black")])

    def refresh_all(self, select_job_id: str | None = None) -> None:
        if self._refresh_all_active:
            return
        self._refresh_all_active = True
        try:
            self._refresh_all_body(select_job_id)
        finally:
            self._refresh_all_active = False
            if self._refreshing_jobs:
                # _refresh_all_body normally clears the flag via after_idle; if
                # it raised before scheduling that reset, job-row clicks would
                # stay ignored forever. Scheduling a second reset is harmless.
                try:
                    self.after_idle(lambda: setattr(self, "_refreshing_jobs", False))
                except (tk.TclError, RuntimeError):
                    self._refreshing_jobs = False

    def _refresh_all_body(self, select_job_id: str | None = None) -> None:
        try:
            jobs = self.backend.list_jobs()
        except Exception as exc:
            self.status_var.set(f"Refresh failed: {exc}")
            return
        selected = select_job_id or self.selected_job_id
        self._refreshing_jobs = True
        finished_watch_notices: list[str] = []
        expanded = {
            item
            for item in self.jobs_tree.get_children()
            if bool(self.jobs_tree.item(item, "open"))
        }
        self.configure_job_status_tags()
        self.jobs_tree.delete(*self.jobs_tree.get_children())
        for job in jobs:
            job_id = str(job["id"])
            task = job.get("latest_task") or {}
            values = (
                job.get("status_display", job["status"]),
                f"{job['percent']}%",
                job["controller"],
                job["worker"],
                job["task_count"],
                job["run_count"],
                job["updated_at"],
            )
            status = str(job["status"])
            self.jobs_tree.insert(
                "",
                "end",
                iid=job_id,
                text=job_id,
                values=values,
                tags=(status,),
                open=job_id in expanded,
            )
            previous = self.last_status_by_job.get(job_id)
            self.last_status_by_job[job_id] = status
            if status != "human_needed":
                self.alerted_human_needed.discard(job_id)
                alert = self.human_needed_windows.pop(job_id, None)
                if alert is not None and alert.winfo_exists():
                    alert.destroy()
            if status == "human_needed" and job_id not in self.alerted_human_needed:
                self.alerted_human_needed.add(job_id)
                self.show_human_needed_alert(job)
            if (
                self.watch_job_id == job_id
                and status in TERMINAL_STATUSES
                and status != "human_needed"
                and previous
                and previous != status
            ):
                finished_watch_notices.append(f"{job_id} is now {status}.")
            if task:
                task_status = str(task.get("status"))
                if task_status == "queued" and job.get("status_display") == "queued / worker offline":
                    task_status = "queued / worker offline"
                self.jobs_tree.insert(
                    job_id,
                    "end",
                    text=str(task.get("id")),
                    values=(task_status, "", "", "", "", "", task.get("updated_at")),
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
            self._set_verification_dashboard_visible(False)
            for widget in (
                self.plan_text,
                self.task_text,
                self.status_text,
                self.controller_text,
                self.worker_text,
                self.detail_text,
                self.log_text,
            ):
                self.set_text(widget, "")
            self.set_text(
                self.status_text,
                "\n".join(
                    [
                        "SYSTEM STATUS",
                        "No job is selected.",
                        "",
                        f"Email delivery: {self.mail_access_status.smtp_detail}",
                        f"Mailbox access: {self.mail_access_status.mailbox_detail}",
                    ]
                ),
            )
        self.update_system_status(jobs)
        self.update_jobs_selection_style()
        self.jobs_tree.update_idletasks()
        for notice in finished_watch_notices:
            self.after_idle(lambda message=notice: messagebox.showinfo("Watched Job Finished", message))
        self.after_idle(lambda: setattr(self, "_refreshing_jobs", False))

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
            redis_ok, redis_checked = self.backend.redis_sample()
            redis_state = "checking…" if not redis_checked else ("online" if redis_ok else "offline")
            if not self._mail_check_done:
                mailbox_state = "checking…"
            elif not self.mail_access_status.enabled:
                mailbox_state = "disabled"
            elif not self.mail_access_status.ok:
                mailbox_state = "error"
            elif self.backend.settings.imap_host:
                mailbox_state = "accessible"
            else:
                mailbox_state = "not configured"
            self.status_var.set(
                f"Redis {redis_state} | jobs {len(jobs)} | active {active} | "
                f"human needed {human_needed} | dead {dead} | done {done} | "
                f"mailbox {mailbox_state} | processes running {running_processes}, stale {stale_processes}"
            )
        except Exception as exc:
            self.status_var.set(f"System status unavailable: {exc}")

    def start_redis(self) -> None:
        if self._redis_action_running:
            messagebox.showinfo("Start Redis", "Redis is already being started; wait for it to finish.")
            return
        self._redis_action_running = True
        self.status_var.set("Starting Redis server…")
        self._run_bg(
            self.backend.start_redis_server,
            self._finish_start_redis,
            name="ai-loop-start-redis",
            busy_attr="_redis_action_running",
            label="Start Redis",
        )

    def _finish_start_redis(self, pid: Any, error: str | None) -> None:
        self._redis_action_running = False
        if error is not None:
            messagebox.showerror("Start Redis Failed", error)
            return
        self.status_var.set(f"Redis server is running (pid {pid})")
        self.refresh_all()

    def _auto_refresh_tick(self) -> None:
        try:
            if self.auto_refresh.get():
                self.refresh_all()
            elif self.human_needed_windows:
                try:
                    with db.transaction(self.backend.settings.db_path) as conn:
                        for job_id, alert in list(self.human_needed_windows.items()):
                            if str(db.get_job(conn, job_id)["status"]) == "human_needed":
                                continue
                            self.human_needed_windows.pop(job_id, None)
                            self.alerted_human_needed.discard(job_id)
                            if alert.winfo_exists():
                                alert.destroy()
                except (KeyError, tk.TclError):
                    pass
        except Exception:
            traceback.print_exc(file=sys.stderr)
        finally:
            try:
                self.after(1500, self._auto_refresh_tick)
            except tk.TclError:
                pass

    def on_job_selected(self, _event: object) -> None:
        if self._refreshing_jobs:
            return
        item = self.jobs_tree.focus()
        if not item:
            return
        parent = self.jobs_tree.parent(item)
        job_id = parent or item
        self.selected_job_id = job_id
        self.update_jobs_selection_style()
        self.show_job(job_id)
        self.populate_form_models_from_job(job_id)

    def populate_form_models_from_job(self, job_id: str) -> None:
        """Populate the form's binary/model fields from the job's stored models_json.

        Always applied on selection: Resume applies the form's selections, so
        loading the job's stored choices into the form makes the shown values
        BE the ones the job was created with (instead of whatever the form
        happened to show after a GUI restart). Edits made after selecting the
        job still override before resuming. Jobs without stored models (older
        jobs, CLI-created before this column) leave the form untouched.
        """
        try:
            with db.transaction(self.backend.settings.db_path) as conn:
                job = db.get_job(conn, job_id)
        except Exception:
            return
        models = job.get("models")
        if not isinstance(models, dict):
            return
        for var, key in (
            (self.codex_model_var, "codex_model"),
            (self.fable_model_var, "fable_model"),
            (self.opus_model_var, "opus_model"),
            (self.gemini_model_var, "gemini_model"),
            (self.controller_model_var, "controller_model"),
            (self.codex_bin_var, "codex_bin"),
            (self.claude_bin_var, "claude_bin"),
            (self.gemini_bin_var, "gemini_bin"),
        ):
            value = models.get(key)
            if isinstance(value, str):
                var.set(value)
        if isinstance(models.get("codex_bypass_sandbox"), bool):
            self.bypass_var.set(models["codex_bypass_sandbox"])
        # Restore the role binary comboboxes and their visible model entries
        # the same way on_role_binary_selected does when switching a binary:
        # remember the model under role_model_values for that binary, set the
        # tk vars, and keep role_binary_previous consistent so a later manual
        # binary switch saves/restores the correct per-binary model.
        for role, role_var, model_var, model_key, job_key in (
            ("controller", self.controller_var, self.controller_role_model_var, "controller_role_model", "controller"),
            ("worker", self.worker_var, self.worker_role_model_var, "worker_role_model", "worker"),
        ):
            binary = provider_for_role(str(job.get(job_key) or "")) or role_var.get()
            role_var.set(binary)
            stored_model = models.get(model_key)
            if isinstance(stored_model, str) and binary in self.role_model_values[role]:
                self.role_model_values[role][binary] = stored_model
                model_var.set(stored_model)
            else:
                model_var.set(self.role_model_values[role].get(binary, ""))
            self.role_binary_previous[role] = binary

    def current_task(self, details: dict[str, Any]) -> dict[str, Any] | None:
        tasks = details.get("tasks", [])
        active = next(
            (task for task in tasks if str(task.get("status")) in {"queued", "running", "waiting_tokens"}),
            None,
        )
        if active is not None:
            return active
        if str(details["job"].get("status")) in {"implementing", "fixing"} and tasks:
            return tasks[0]
        return None

    def current_plan_index(self, details: dict[str, Any]) -> int | None:
        job = details["job"]
        if str(job.get("status")) == "done":
            return None
        task = self.current_task(details)
        goal = str(task.get("goal") if task else "").lower()
        if any(word in goal for word in ("inspect", "investigate", "audit", "analyze", "analyse", "discover")):
            return 0
        if any(word in goal for word in ("test", "validate", "verify", "pytest", "ctest", "cmake")):
            return 2
        if any(word in goal for word in ("final review", "acceptance", "finish", "release readiness")):
            return 3
        percent = int(details.get("percent", 0))
        if percent < 15:
            return 0
        if percent < 75:
            return 1
        if percent < 92:
            return 2
        return 3

    def plan_view_text(self, details: dict[str, Any]) -> tuple[str, int | None]:
        job = details["job"]
        plan = list(job.get("plan") or [])
        if not plan:
            return "No overall plan was recorded for this older job.", None
        current = self.current_plan_index(details)
        current = min(current, len(plan) - 1) if current is not None else None
        lines: list[str] = []
        for index, item in enumerate(plan):
            if str(job.get("status")) == "done" or (current is not None and index < current):
                marker, suffix = "✓", " — completed"
            elif index == current:
                marker, suffix = "▶", " — CURRENTLY WORKING HERE"
            else:
                marker, suffix = "○", ""
            lines.append(f"{marker} {index + 1}. {item}{suffix}")
        lines.extend(["", "Legend: ▶ current step    ✓ completed step    ○ later step"])
        return "\n\n".join(lines), current

    def task_view_text(self, details: dict[str, Any]) -> str:
        task = self.current_task(details)
        if task is None:
            status = str(details["job"].get("status"))
            return f"There is no current worker task.\n\nThe job status is {status}. The controller may still be preparing the next instruction."
        status = str(task.get("status"))
        explanations = {
            "queued": "The task is ready and waiting for the worker to start.",
            "running": "The worker is carrying out this task now.",
            "waiting_tokens": "Work is paused until model tokens replenish; it will resume automatically.",
            "completed": "The worker finished this task and returned the result to the controller.",
            "failed": "The task stopped with a failure and needs controller review or repair.",
        }
        lines = [
            "CURRENT TASK",
            str(task.get("goal") or "No task goal was recorded."),
            "",
            "What is happening",
            explanations.get(status, f"The task is in state {status}."),
            f"Task number: {task.get('iteration')}",
            f"Task id: {task.get('id')}",
            f"Last update: {task.get('updated_at')}",
            "",
            "Detailed instructions",
        ]
        constraints = list(task.get("constraints") or [])
        lines.extend([f"{index}. {item}" for index, item in enumerate(constraints, start=1)] or ["No extra constraints were recorded."])
        lines.extend(["", "How completion will be checked"])
        acceptance = list(task.get("acceptance") or [])
        lines.extend([f"{index}. {item}" for index, item in enumerate(acceptance, start=1)] or ["No task-specific acceptance checks were recorded."])
        lines.extend(["", f"Validation command: {task.get('test_cmd') or 'none'}"])
        matching_run = next((run for run in details.get("runs", []) if run.get("task_id") == task.get("id")), None)
        if matching_run:
            changed = ", ".join(matching_run.get("changed_files") or []) or "none recorded"
            test_result = "passed" if matching_run.get("test_rc") == 0 else "failed or did not run"
            lines.extend([
                "",
                "Latest result for this task",
                f"Worker result: {matching_run.get('status')}",
                f"Tests: {test_result}",
                f"Changed files: {changed}",
            ])
            if matching_run.get("error"):
                lines.append(f"Problem reported: {matching_run.get('error')}")
        return "\n".join(lines)

    def blockers(self, details: dict[str, Any]) -> list[tuple[str, str]]:
        job = details["job"]
        status = str(job.get("status"))
        processes = details.get("processes", {})
        latest_run = details.get("runs", [None])[0] if details.get("runs") else None
        latest_decision = details.get("decisions", [None])[0] if details.get("decisions") else None
        result: list[tuple[str, str]] = []
        # Before the first background PING completes (redis_checked == 0) the
        # reachability is unknown, not offline: suppress the blocker instead
        # of flashing a false "Redis is offline" during the first ~1.5 s.
        if (
            not details.get("redis_running", False)
            and details.get("redis_checked", 0)
            and status in ACTIVE_STATUSES
        ):
            result.append(("Redis is offline, so controller and worker messages cannot be delivered.", "Open System and choose Start Redis, or start the configured Redis service."))
        if status == "waiting_tokens":
            until = job.get("waiting_until") or "the recorded reset time"
            result.append((f"The selected model has temporarily run out of tokens. Waiting until {until} plus one minute.", "No action is normally needed; the loop resumes automatically."))
        if status == "human_needed":
            reason = str(latest_decision.get("reason") if latest_decision else job.get("history_summary") or "Human input was requested.")
            result.append((reason, "Read the suggested actions below, correct the external problem, then use Apply + Resume."))
        if status == "dead":
            result.append(("The loop stopped after an internal or process failure.", "Inspect Controller, Worker, Details, and Logs; fix the reported cause and then resume."))
        controller = processes.get("controller", {})
        worker = processes.get("worker", {})
        if status == "planning" and not controller.get("running"):
            result.append(("The job is planning but the controller process is not running.", "Use Resume. If it stops again, inspect the Controller tab and controller log."))
        if status in {"queued", "implementing", "fixing"} and not worker.get("running"):
            result.append(("Worker work is pending but the worker process is not running.", "Use Resume. If the worker exits again, inspect the Worker tab and worker log."))
        if latest_run and latest_run.get("error"):
            result.append((f"The latest worker run reported: {latest_run.get('error')}", "Inspect the Worker and Logs tabs, then let the controller create a repair or use Fix It."))
        elif latest_run and latest_run.get("test_rc") not in {None, 0}:
            result.append(("The latest validation command failed.", "Read the Worker test result and let the controller issue a repair task."))
        return result

    def plain_status_text(self, details: dict[str, Any]) -> str:
        job = details["job"]
        task = self.current_task(details)
        status = str(job.get("status"))
        status_explanations = {
            "planning": "The controller is deciding what the worker should do next.",
            "queued": "A task is ready and waiting for the worker.",
            "implementing": "The worker is changing the repository and will run the configured checks.",
            "fixing": "The worker is repairing or diagnosing a failed result.",
            "waiting_tokens": "Work is paused until model tokens replenish, then it will resume automatically.",
            "human_needed": "Automation cannot continue safely without human input.",
            "dead": "The loop stopped after an internal failure.",
            "done": "The controller confirmed that the job is complete.",
        }
        lines = [
            "SYSTEM STATUS",
            f"Job: {job.get('id')}",
            f"State: {status}",
            status_explanations.get(status, f"The job is in state {status}."),
            f"Progress: {details.get('percent')}% complete; about {self.duration_text(details.get('remaining'))} remaining.",
            "Redis message service: " + (
                "checking…" if not details.get("redis_checked", 0)
                else ("online" if details.get("redis_running") else "offline")
            ),
            f"Email delivery: {self.mail_access_status.smtp_detail}",
            f"Mailbox access: {self.mail_access_status.mailbox_detail}",
            "",
            "CONTROLLER",
            f"Selected controller: {job.get('controller')}",
        ]
        controller_info = details.get("processes", {}).get("controller", {})
        lines.append(f"Process: {'running' if controller_info.get('running') else 'stopped'}; pid {controller_info.get('pid') or '-'}")
        lines.append("Role: reviews worker results and sends the next task or marks the job complete.")
        lines.extend(["", "WORKER", f"Selected worker: {job.get('worker')}"])
        worker_info = details.get("processes", {}).get("worker", {})
        lines.append(f"Process: {'running' if worker_info.get('running') else 'stopped'}; pid {worker_info.get('pid') or '-'}")
        lines.append(f"Current task: {task.get('goal') if task else 'none'}")
        lines.extend(["", "BLOCKERS AND SOLUTIONS"])
        blockers = self.blockers(details)
        if blockers:
            for index, (problem, solution) in enumerate(blockers, start=1):
                lines.extend([f"{index}. Problem: {problem}", f"   Solution: {solution}"])
        else:
            lines.append("No blocker is currently visible. The loop can continue automatically.")
        return "\n".join(lines)

    def compact_output(self, value: Any, limit: int = 1800) -> str:
        lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
        text = "\n".join(lines)
        if len(text) > limit:
            return "…\n" + text[-limit:]
        return text or "No written report was recorded."

    def controller_view_text(self, details: dict[str, Any]) -> str:
        decisions = details.get("decisions", [])
        if not decisions:
            return "No controller message has been recorded yet. The controller may still be preparing the first task."
        lines = ["CONTROLLER MESSAGES — NEWEST FIRST", ""]
        action_text = {
            "CONTINUE": "Continue with another task.",
            "REPAIR": "Repair a problem found in the previous result.",
            "DONE": "The job is complete; no more worker task is needed.",
            "HUMAN_NEEDED": "Automation needs human help before it can continue.",
        }
        for index, decision in enumerate(decisions, start=1):
            try:
                payload = json.loads(str(decision.get("decision_json") or "{}"))
            except (TypeError, json.JSONDecodeError):
                payload = {}
            action = str(decision.get("action") or "unknown")
            next_task = payload.get("next_task") if isinstance(payload, dict) else None
            lines.extend([
                f"MESSAGE {index} — {decision.get('created_at')}",
                action_text.get(action, f"Controller action: {action}."),
                f"Why: {decision.get('reason') or 'No explanation was recorded.'}",
            ])
            if isinstance(next_task, dict):
                lines.extend(["Instruction sent to the worker:", str(next_task.get("goal") or "No task goal was recorded.")])
                acceptance = list(next_task.get("acceptance") or [])
                if acceptance:
                    lines.append("The controller will accept this task when:")
                    lines.extend(f"- {item}" for item in acceptance)
                lines.append(f"Validation command: {next_task.get('test_cmd') or 'none'}")
            else:
                lines.append("No new worker instruction was sent with this message.")
            lines.append("")
        return "\n".join(lines).rstrip()

    def worker_view_text(self, details: dict[str, Any]) -> str:
        task = self.current_task(details)
        lines = ["WORKER ACTIVITY", f"Worker: {details['job'].get('worker')}"]
        if task and str(task.get("status")) in {"queued", "running", "waiting_tokens"}:
            lines.extend([f"Current task state: {task.get('status')}", f"What it is doing: {task.get('goal')}"])
        else:
            lines.append("The worker has no active task right now.")
        runs = details.get("runs", [])
        if not runs:
            lines.extend(["", "No worker result has been returned yet."])
            return "\n".join(lines)
        lines.extend(["", "RESULTS SENT BACK TO THE CONTROLLER — NEWEST FIRST"])
        for index, run in enumerate(runs[:5], start=1):
            worker_ok = run.get("codex_rc") == 0
            test_rc = run.get("test_rc")
            test_text = "passed" if test_rc == 0 else ("failed" if test_rc is not None else "not run")
            changed = ", ".join(run.get("changed_files") or []) or "none recorded"
            lines.extend([
                "",
                f"RESULT {index} — task {run.get('task_id')}",
                f"Worker execution: {'completed' if worker_ok else 'failed'}",
                f"Validation: {test_text}",
                f"Changed files: {changed}",
            ])
            if run.get("diff_stat"):
                lines.append(f"Change summary: {str(run.get('diff_stat')).strip()}")
            if run.get("error"):
                lines.append(f"Problem: {run.get('error')}")
            lines.extend(["Worker report:", self.compact_output(run.get("codex_output"))])
            if test_rc not in {None, 0}:
                lines.extend(["Validation output:", self.compact_output(run.get("test_output"), 1200)])
        return "\n".join(lines)

    def details_view_text(self, details: dict[str, Any]) -> str:
        snapshot = {
            "computed": {
                "percent": details.get("percent"),
                "remaining_seconds": details.get("remaining"),
                "task_count": details.get("task_count"),
                "run_count": details.get("run_count"),
                "redis_running": details.get("redis_running"),
                "current_plan_index": self.current_plan_index(details),
            },
            "processes": details.get("processes"),
            "job": details.get("job"),
            "tasks": details.get("tasks"),
            "runs": details.get("runs"),
            "decisions": details.get("decisions"),
            "events": details.get("events"),
        }
        return "EXTENSIVE DIAGNOSTIC DETAILS\nNewest tasks, runs, decisions, and events are listed first.\n\n" + json.dumps(snapshot, indent=2, ensure_ascii=False, default=str)

    def explain_selected_status(self) -> None:
        job_id = self.selected_job_or_error()
        if not job_id:
            return
        try:
            details = self.backend.job_details(job_id)
        except Exception as exc:
            messagebox.showerror("Status Failed", str(exc))
            return
        self.set_text(self.status_text, self.plain_status_text(details))
        self.status_var.set(f"Status explanation refreshed for {job_id}")

    def show_job(self, job_id: str) -> None:
        try:
            details = self.backend.job_details(job_id)
        except Exception as exc:
            self.status_var.set(f"Could not load {job_id}: {exc}")
            return
        job = details["job"]
        if self.resume_fields_job_id != job_id:
            self.extra_constraint_var.set("")
            self.extra_acceptance_var.set("")
            self.resume_fields_job_id = job_id
        plan_text, current_plan = self.plan_view_text(details)
        self.set_text(self.plan_text, plan_text)
        self.plan_text.tag_remove("current_plan_item", "1.0", "end")
        if current_plan is not None:
            line = 1 + (current_plan * 2)
            self.plan_text.tag_add("current_plan_item", f"{line}.0", f"{line}.end")
        self.set_text(self.task_text, self.task_view_text(details))
        self.set_text(self.status_text, self.plain_status_text(details))
        self.set_text(self.controller_text, self.controller_view_text(details))
        self.set_text(self.worker_text, self.worker_view_text(details))
        self.set_text(self.detail_text, self.details_view_text(details))
        formal = job.get("specification_id") is not None
        self._set_verification_dashboard_visible(formal)
        if formal:
            self.refresh_verification_dashboard(job_id)
        self.refresh_log()

    def _set_verification_dashboard_visible(self, visible: bool) -> None:
        state = "normal" if visible else "hidden"
        try:
            self.detail_notebook.tab(self.verification_tab, state=state)
        except tk.TclError:
            return
        if not visible:
            self._verification_request_serial += 1
            self._verification_last_loaded_job = None
            self.verification_dashboard_view.clear(
                "Quick Goal job selected. Formal verification does not apply."
            )

    def refresh_verification_dashboard(
        self,
        job_id: str | None = None,
        *,
        force: bool = False,
    ) -> None:
        selected = job_id or self.selected_job_id
        if not selected or self._verification_load_running:
            return
        if (
            not force
            and self._verification_last_loaded_job == selected
            and time.monotonic() - self._verification_last_loaded_at < 3.0
        ):
            return
        self._verification_load_running = True
        self._verification_request_serial += 1
        request_serial = self._verification_request_serial
        self.verification_dashboard_view.set_loading(
            True, f"Loading trusted verification data for {selected}…"
        )

        def done(rows: Any, error: str | None) -> None:
            self._verification_load_running = False
            if request_serial != self._verification_request_serial or selected != self.selected_job_id:
                return
            self.verification_dashboard_view.set_loading(False)
            if error is not None:
                self.verification_dashboard_view.status_var.set(
                    f"Could not load formal verification: {error}"
                )
                return
            if rows is None:
                self._set_verification_dashboard_visible(False)
                return
            self._verification_last_loaded_job = selected
            self._verification_last_loaded_at = time.monotonic()
            self.verification_dashboard_view.show_rows(selected, rows)

        self._run_bg(
            lambda: self.backend.verification_dashboard(selected),
            done,
            name=f"ai-loop-verification-dashboard-{selected}",
            busy_attr="_verification_load_running",
            label="Loading Formal Verification",
        )

    def acknowledge_selected_manual_verification(
        self,
        verification_id: str,
        acknowledged_by: str,
        note: str,
    ) -> None:
        job_id = self.selected_job_id
        if not job_id or self._verification_load_running:
            return
        self._verification_load_running = True
        self.verification_dashboard_view.set_loading(
            True, f"Recording audited acknowledgement for {verification_id}…"
        )

        def done(_result: Any, error: str | None) -> None:
            self._verification_load_running = False
            self.verification_dashboard_view.set_loading(False)
            if error is not None:
                messagebox.showerror("Manual Acknowledgement Failed", error)
                return
            self.verification_dashboard_view.ack_note_var.set("")
            self._verification_last_loaded_at = 0.0
            self.refresh_verification_dashboard(job_id, force=True)

        self._run_bg(
            lambda: self.backend.acknowledge_manual_verification(
                job_id,
                verification_id,
                acknowledged_by=acknowledged_by,
                note=note,
            ),
            done,
            name=f"ai-loop-manual-verification-{job_id}-{verification_id}",
            busy_attr="_verification_load_running",
            label="Recording Manual Verification Acknowledgement",
        )

    def human_needed_actions(self, job: dict[str, Any], details: dict[str, Any]) -> list[str]:
        requirement = find_auth_requirement(details)
        if requirement:
            return [f"- Use Job Actions → Sign In + Resume to authenticate {provider_display_name(requirement.provider)} and continue this same job."]
        actions = [
            "- Inspect the latest controller and worker logs in the Logs tab.",
            "- Read the controller explanation in Controller and the stored history in Details.",
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
            actions.insert(0, "- Latest run or test command failed; inspect the latest run output in Worker and Details and worker log.")
        if str(job.get("controller")) != "opus":
            actions.append("- Consider switching the controller to opus before resuming.")
        return actions

    def show_human_needed_alert(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        try:
            requirement = self.backend.auth_requirement(job_id)
        except Exception:
            requirement = None

        summary = str(job.get("history_summary") or "").strip()
        if len(summary) > 700:
            summary = summary[:697] + "..."
        if requirement is not None:
            actions = [
                f"1. Click Sign In + Resume to authenticate {provider_display_name(requirement.provider)}.",
                "2. Or reply to the job email with a different command if authentication is not required for the new path.",
            ]
        else:
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
        message += "\n\nYou can also reply to this job's email with a new command. The window will close when the job resumes."

        existing = self.human_needed_windows.get(job_id)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        window = tk.Toplevel(self)
        self.human_needed_windows[job_id] = window
        window.title("Human Needed")
        window.transient(self)
        window.resizable(True, True)
        window.geometry("720x430")
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Human Needed", font=("TkDefaultFont", 15, "bold")).pack(anchor="w")
        text = tk.Text(frame, wrap="word", height=16)
        text.pack(fill="both", expand=True, pady=(10, 12))
        text.insert("1.0", message)
        text.configure(state="disabled")

        def close_alert() -> None:
            self.human_needed_windows.pop(job_id, None)
            if window.winfo_exists():
                window.destroy()

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Dismiss", command=close_alert).pack(side="right")
        if requirement is not None:
            ttk.Button(
                buttons,
                text="Sign In + Resume",
                command=lambda: (close_alert(), self.start_auth_recovery(job_id, requirement, ask=False)),
            ).pack(side="right", padx=(0, 8))
        window.protocol("WM_DELETE_WINDOW", close_alert)

    def recover_selected_auth(self) -> None:
        job_id = self.selected_job_or_error()
        if not job_id:
            return
        try:
            requirement = self.backend.auth_requirement(job_id)
        except Exception as exc:
            messagebox.showerror("Authentication Check Failed", str(exc))
            return
        if requirement is None:
            messagebox.showinfo(
                "No Authentication Error",
                "The selected job is not stopped by a recognized provider authentication error.",
            )
            return
        self.start_auth_recovery(job_id, requirement, ask=True)

    def start_auth_recovery(
        self,
        job_id: str,
        requirement: AuthRequirement,
        *,
        ask: bool,
    ) -> None:
        if job_id in self.auth_recovery_jobs:
            self.status_var.set(f"Authentication is already running for {job_id}")
            return
        conflict = self._exclusive_conflict("Auth Recovery")
        if conflict is not None:
            messagebox.showinfo(
                "Auth Recovery",
                f"Cannot start authentication recovery while {conflict} is running.",
            )
            return
        display = provider_display_name(requirement.provider)
        if requirement.provider == "gemini":
            messagebox.showwarning(
                "Gemini Sign-in Required",
                "The Gemini CLI does not expose the verified login/status flow used by "
                "Claude and Codex.\n\nAuthenticate Gemini in a terminal, then click "
                "Apply + Resume. The job and worktree remain preserved.",
            )
            self.status_var.set(f"Gemini sign-in is required for {job_id}")
            return
        if ask and not messagebox.askyesno(
            f"{display} Sign-in Required",
            f"Job {job_id} stopped because its {requirement.role} is not authenticated.\n\n"
            f"Start `{self.backend.provider_binary(requirement.provider, self.current_models())} "
            f"{'auth login' if requirement.provider == 'claude' else 'login'}` now?\n\n"
            "A browser or provider login window may open. After successful sign-in, "
            "ai-loop will verify authentication and resume this same job automatically.",
        ):
            self.status_var.set(f"{display} sign-in is still required for {job_id}")
            return

        models = self.current_models()
        self.auth_recovery_jobs.add(job_id)
        # recover() uses a raw thread, not _run_bg, so track the label manually;
        # finish_auth_recovery discards it on every main-thread path, and the
        # destroyed-Tk except branches below discard it when after() fails.
        self._active_operations.add("Auth Recovery")
        self.status_var.set(f"Waiting for {display} sign-in for {job_id}…")

        def recover() -> None:
            try:
                result = self.backend.recover_provider_auth(job_id, requirement, models)
            except Exception as exc:
                try:
                    self.after(
                        0,
                        lambda error=str(exc): self.finish_auth_recovery(
                            job_id,
                            requirement,
                            result=None,
                            error=error,
                        ),
                    )
                except (tk.TclError, RuntimeError):
                    # Tk is destroyed: finish_auth_recovery never runs, so
                    # drop the operation label here (plain set, no Tk access).
                    self._active_operations.discard("Auth Recovery")
                return
            try:
                self.after(
                    0,
                    lambda: self.finish_auth_recovery(
                        job_id,
                        requirement,
                        result=result,
                        error=None,
                    ),
                )
            except (tk.TclError, RuntimeError):
                self._active_operations.discard("Auth Recovery")

        threading.Thread(
            target=recover,
            name=f"ai-loop-auth-{job_id}",
            daemon=True,
        ).start()

    def finish_auth_recovery(
        self,
        job_id: str,
        requirement: AuthRequirement,
        *,
        result: AuthRecoveryResult | None,
        error: str | None,
    ) -> None:
        self.auth_recovery_jobs.discard(job_id)
        self._active_operations.discard("Auth Recovery")
        display = provider_display_name(requirement.provider)
        if error is not None:
            self.status_var.set(f"{display} sign-in failed for {job_id}")
            messagebox.showerror(
                f"{display} Sign-in Failed",
                f"{error}\n\nThe job was preserved and was not resumed.",
            )
            return
        self.alerted_human_needed.discard(job_id)
        self.watch_job_id = job_id
        self.status_var.set(f"{display} authenticated; resumed {job_id}")
        messagebox.showinfo(
            f"{display} Sign-in Complete",
            f"{result.detail if result else f'{display} authentication succeeded.'}\n\n"
            f"Job {job_id} has been resumed.",
        )
        self.refresh_all(select_job_id=job_id)

    def refresh_log(self) -> None:
        if not self.selected_job_id:
            return
        log_name = PROCESS_KEYS_BY_LABEL.get(self.log_name_var.get(), self.log_name_var.get())
        try:
            text = self.backend.log_text(self.selected_job_id, log_name)
        except Exception as exc:
            text = f"Could not read log: {exc}"
        if self.set_text(self.log_text, text):
            self.log_text.see("end")

    def add_help(self, widget: tk.Widget, text: str) -> None:
        self.help_tooltip.attach(widget, text)

    def help_widget(self, widget: tk.Widget, text: str) -> tk.Widget:
        self.add_help(widget, text)
        return widget

    def install_default_help(self, parent: tk.Misc) -> None:
        """Ensure even passive labels, scrollbars, and containers explain themselves."""

        for widget in parent.winfo_children():
            if not getattr(widget, "_ai_loop_help_attached", False):
                widget_class = widget.winfo_class()
                try:
                    visible_text = str(widget.cget("text")).strip()
                except tk.TclError:
                    visible_text = ""
                if widget_class in {"TLabel", "Label"} and visible_text:
                    help_text = f"{visible_text}: label for the value or control beside it."
                elif "Scrollbar" in widget_class:
                    help_text = "Scroll the associated content to reach information outside the visible area."
                elif "Frame" in widget_class:
                    help_text = "Groups the related controls and information shown in this section."
                elif "Panedwindow" in widget_class:
                    help_text = "Drag the divider to resize the job list and selected-job details."
                else:
                    help_text = f"{visible_text or widget_class}: interface element used in the ai-loop dashboard."
                self.add_help(widget, help_text)
            self.install_default_help(widget)

    @staticmethod
    def set_text(widget: tk.Text, text: str) -> bool:
        current = widget.get("1.0", "end-1c")
        if current == text:
            return False
        yview = widget.yview()
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        if yview:
            widget.yview_moveto(yview[0])
        if getattr(widget, "_ai_loop_read_only", False):
            widget.configure(state="disabled")
        return True
    @staticmethod

    def duration_text(seconds: int | None) -> str:
        if seconds is None:
            return "unknown time"
        seconds = max(0, int(seconds))
        if seconds < 90:
            return f"{seconds} seconds"
        minutes = seconds // 60
        if minutes < 90:
            return f"{minutes} minutes"
        hours = minutes // 60
        if hours < 48:
            return f"{hours}h {minutes % 60}m"
        return f"{hours // 24}d {hours % 24}h"

    def selected_job_or_error(self) -> str | None:
        if not self.selected_job_id:
            messagebox.showerror("No Job Selected", "Select a job first.")
            return None
        return self.selected_job_id

    def stop_selected_job(self) -> None:
        job_id = self.selected_job_or_error()
        if not job_id:
            return
        if self._stop_job_running:
            messagebox.showinfo("Stop Job", "A stop is already in progress; wait for it to finish.")
            return
        conflict = self._exclusive_conflict("job")
        if conflict is not None:
            messagebox.showinfo("Stop Job", f"Cannot start Stop Job while {conflict} is running.")
            return

        # stop_processes escalates SIGTERM->SIGKILL with an up-to-5 s group
        # poll, so it must never run on the Tk main thread.
        def work() -> dict[str, str]:
            results = self.backend.stop_processes(job_id)
            self.backend.mark_stopped(job_id)
            return results

        self._stop_job_running = True
        self.status_var.set(f"Stopping {job_id}…")
        self._run_bg(
            work,
            lambda results, error: self._finish_stop_job(job_id, results, error),
            name=f"ai-loop-stop-{job_id}",
            busy_attr="_stop_job_running",
            label="Stop Job",
        )

    def _finish_stop_job(self, job_id: str, results: dict[str, str] | None, error: str | None) -> None:
        self._stop_job_running = False
        if error is not None:
            messagebox.showerror("Stop Failed", error)
            return
        summary = "\n".join(f"{name}: {outcome}" for name, outcome in (results or {}).items())
        self.status_var.set(f"Stopped {job_id}")
        messagebox.showinfo("Stop Job", f"Stopped processes for {job_id}:\n\n{summary}")
        self.refresh_all(select_job_id=job_id)

    def resume_selected_job(self) -> None:
        job_id = self.selected_job_or_error()
        if not job_id:
            return
        if self._resume_job_running:
            messagebox.showinfo("Resume", "A resume is already in progress; wait for it to finish.")
            return
        conflict = self._exclusive_conflict("job")
        if conflict is not None:
            messagebox.showinfo("Resume", f"Cannot start Resume Job while {conflict} is running.")
            return
        # Snapshot all Tk values on the main thread; backend.resume_job may
        # auto-start Redis (up to ~10 s of polling), so it runs in a thread.
        worker = self.worker_var.get()
        controller = self.controller_var.get()
        granularity = self.granularity_var.get()
        models = self.current_models()
        extra_constraint = self.extra_constraint_var.get()
        extra_acceptance = self.extra_acceptance_var.get()
        self._resume_job_running = True
        self.status_var.set(f"Resuming {job_id}…")
        self._run_bg(
            lambda: self.backend.resume_job(
                job_id,
                worker=worker,
                controller=controller,
                granularity=granularity,
                models=models,
                extra_constraint=extra_constraint,
                extra_acceptance=extra_acceptance,
            ),
            lambda _result, error: self._finish_resume_job(job_id, error),
            name=f"ai-loop-resume-{job_id}",
            busy_attr="_resume_job_running",
            label="Resume Job",
        )

    def _finish_resume_job(self, job_id: str, error: str | None) -> None:
        self._resume_job_running = False
        if error is not None:
            messagebox.showerror("Resume Failed", error)
            return
        self.watch_job_id = job_id
        self.refresh_all(select_job_id=job_id)

    def finish_soon_selected_job(self) -> None:
        job_id = self.selected_job_or_error()
        if not job_id:
            return
        if not messagebox.askyesno(
            "Finish Soon",
            "Keep the job running, switch to coarse tasks, omit optional work, and ask the controller to reach acceptance with at most one consolidated final task?",
        ):
            return
        try:
            self.backend.request_finish_soon(job_id)
        except Exception as exc:
            messagebox.showerror("Finish Soon Failed", str(exc))
            return
        self.granularity_var.set("coarse")
        self.refresh_all(select_job_id=job_id)

    def finish_selected_job(self) -> None:
        job_id = self.selected_job_or_error()
        if not job_id:
            return
        if self._finish_job_running:
            messagebox.showinfo("Finish Job", "A finish is already in progress; wait for it to finish.")
            return
        conflict = self._exclusive_conflict("job")
        if conflict is not None:
            messagebox.showinfo("Finish Job", f"Cannot start Finish Job while {conflict} is running.")
            return
        if not messagebox.askyesno("Finish Job", "Stop the loop and preserve current worktree/database progress for this job?"):
            return
        # backend.finish_job runs stop_processes (up to ~5 s of SIGKILL
        # escalation polling), so it must never run on the Tk main thread.
        self._finish_job_running = True
        self.status_var.set(f"Finishing {job_id}…")
        self._run_bg(
            lambda: self.backend.finish_job(job_id),
            lambda _result, error: self._finish_finish_job(job_id, error),
            name=f"ai-loop-finish-{job_id}",
            busy_attr="_finish_job_running",
            label="Finish Job",
        )

    def _finish_finish_job(self, job_id: str, error: str | None) -> None:
        self._finish_job_running = False
        if error is not None:
            messagebox.showerror("Finish Failed", error)
            return
        self.refresh_all(select_job_id=job_id)

    def fix_selected_job(self) -> None:
        job_id = self.selected_job_or_error()
        if not job_id:
            return
        if self._fix_job_running:
            messagebox.showinfo("Fix It", "A Fix It run is already in progress; wait for it to finish.")
            return
        conflict = self._exclusive_conflict("job")
        if conflict is not None:
            messagebox.showinfo("Fix It", f"Cannot start Fix It while {conflict} is running.")
            return
        binary = self.fix_binary_var.get().strip() or "codex"
        if not messagebox.askyesno("Fix It", f"Run {binary!r} to diagnose/fix and then resume this job if successful?"):
            return
        self._fix_job_running = True
        # run_fix uses a raw thread, not _run_bg, so track the label manually;
        # finish_fix_job discards it on every path.
        self._active_operations.add("Fix It")
        self.status_var.set(f"Running {binary} to fix {job_id}…")
        models = self.current_models()

        def run_fix() -> None:
            try:
                proc = self.backend.fix_job_with_binary(job_id, binary, models)
            except Exception as exc:
                try:
                    self.after(
                        0,
                        lambda error=str(exc): self.finish_fix_job(
                            job_id,
                            binary,
                            proc=None,
                            error=error,
                        ),
                    )
                except (tk.TclError, RuntimeError):
                    pass
                return
            try:
                self.after(
                    0,
                    lambda: self.finish_fix_job(
                        job_id,
                        binary,
                        proc=proc,
                        error=None,
                    ),
                )
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(
            target=run_fix,
            name=f"ai-loop-fix-{job_id}",
            daemon=True,
        ).start()

    def finish_fix_job(
        self,
        job_id: str,
        binary: str,
        *,
        proc: subprocess.CompletedProcess[str] | None,
        error: str | None,
    ) -> None:
        self._fix_job_running = False
        self._active_operations.discard("Fix It")
        if error is not None:
            self.status_var.set(f"Fix It failed for {job_id}")
            messagebox.showerror("Fix It Failed", error)
            return
        output = (proc.stdout + "\n" + proc.stderr).strip()
        if proc.returncode == 0:
            messagebox.showinfo("Fix It", f"{binary} finished successfully and the job was resumed.\n\n{output[-1200:]}")
        else:
            messagebox.showerror("Fix It Failed", f"{binary} exited with rc={proc.returncode}.\n\n{output[-2000:]}")
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
        if self._delete_job_running:
            messagebox.showinfo("Delete Job", "A delete is already in progress; wait for it to finish.")
            return
        conflict = self._exclusive_conflict("job")
        if conflict is not None:
            messagebox.showinfo("Delete Job", f"Cannot start Delete Job while {conflict} is running.")
            return
        if not messagebox.askyesno("Delete Job", f"Delete job record {job_id}? Worktree files are not removed."):
            return
        # backend.delete_job runs stop_processes (up to ~5 s of SIGKILL
        # escalation polling), so it must never run on the Tk main thread.
        self._delete_job_running = True
        self.status_var.set(f"Deleting {job_id}…")
        self._run_bg(
            lambda: self.backend.delete_job(job_id),
            lambda _result, error: self._finish_delete_job(error),
            name=f"ai-loop-delete-{job_id}",
            busy_attr="_delete_job_running",
            label="Delete Job",
        )

    def _finish_delete_job(self, error: str | None) -> None:
        self._delete_job_running = False
        if error is not None:
            messagebox.showerror("Delete Failed", error)
            return
        self.selected_job_id = None
        self.refresh_all()

    def _maintenance_busy(self, title: str) -> bool:
        if self._maintenance_running:
            messagebox.showinfo(title, "Another cleanup or reset is still running; wait for it to finish.")
            return True
        return False

    def reset_loop(self) -> None:
        if self._maintenance_busy("Reset Loop"):
            return
        conflict = self._exclusive_conflict("maintenance")
        if conflict is not None:
            messagebox.showinfo("Reset Loop", f"Cannot start Reset Loop while {conflict} is running.")
            return
        if not messagebox.askyesno("Reset Loop", "Stop all job processes and clear all ai-loop database records?"):
            return
        self._maintenance_running = True
        self.status_var.set("Resetting ai-loop database…")
        self._run_bg(
            self.backend.reset_loop,
            lambda _result, error: self._finish_reset_loop(error),
            name="ai-loop-reset-db",
            busy_attr="_maintenance_running",
            label="Reset Loop",
        )

    def _finish_reset_loop(self, error: str | None) -> None:
        self._maintenance_running = False
        if error is not None:
            messagebox.showerror("Reset Failed", error)
            return
        self.selected_job_id = None
        self.watch_job_id = None
        self.refresh_all()

    def clear_worktrees(self) -> None:
        if self._maintenance_busy("Clear Worktrees"):
            return
        conflict = self._exclusive_conflict("maintenance")
        if conflict is not None:
            messagebox.showinfo("Clear Worktrees", f"Cannot start Clear Worktrees while {conflict} is running.")
            return
        runs_dir = self.backend.settings.runs_dir
        if not messagebox.askyesno(
            "Clear Worktrees",
            f"Remove all registered ai-loop worktrees and leftover folders under:\n\n{runs_dir}\n\nDatabase records are not deleted.",
        ):
            return
        self._maintenance_running = True
        self.status_var.set("Removing ai-loop worktrees…")
        self._run_bg(
            lambda: self.backend.remove_ai_worktrees(force=True),
            self._finish_clear_worktrees,
            name="ai-loop-clear-worktrees",
            busy_attr="_maintenance_running",
            label="Clear Worktrees",
        )

    def _finish_clear_worktrees(self, summary: dict[str, Any] | None, error: str | None) -> None:
        self._maintenance_running = False
        if error is not None:
            messagebox.showerror("Clear Worktrees Failed", error)
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
        if self._maintenance_busy("Full Reset"):
            return
        conflict = self._exclusive_conflict("maintenance")
        if conflict is not None:
            messagebox.showinfo("Full Reset", f"Cannot start Full Reset while {conflict} is running.")
            return
        # Confirmation stays on the main thread BEFORE the worker thread runs:
        # full_reset deletes worktrees and database rows.
        if not messagebox.askyesno(
            "Full Reset",
            "Stop all job processes, remove ai-loop worktrees, and clear all database records?",
        ):
            return
        self._maintenance_running = True
        self.status_var.set("Running full reset…")
        self._run_bg(
            self.backend.full_reset,
            self._finish_full_reset,
            name="ai-loop-full-reset",
            busy_attr="_maintenance_running",
            label="Full Reset",
        )

    def _finish_full_reset(self, summary: dict[str, Any] | None, error: str | None) -> None:
        self._maintenance_running = False
        if error is not None:
            messagebox.showerror("Full Reset Failed", error)
            return
        worktrees = summary.get("worktrees", {})
        messagebox.showinfo(
            "Full Reset Complete",
            f"Stopped jobs: {len(summary.get('stopped_jobs', []))}\n"
            f"Removed worktrees: {len(worktrees.get('removed_worktrees', []))}\n"
            f"Deleted leftover folders: {len(worktrees.get('leftover_folders', []))}\n"
            "All database records were cleared.",
        )
        self.selected_job_id = None
        self.watch_job_id = None
        self.refresh_all()

    def hibernation_status_text(self) -> str:
        """Blocking (runs pmset); call from a background thread."""
        if platform.system() != "Darwin":
            return "Hibernation control works on macOS only."
        pmset = shutil.which("pmset")
        if pmset is None:
            return "pmset was not found."
        try:
            result = subprocess.run([pmset, "-g"], text=True, capture_output=True, check=False, timeout=10)
        except subprocess.TimeoutExpired:
            return "pmset -g did not answer within 10 seconds."
        if result.returncode != 0:
            return result.stderr.strip() or result.stdout.strip() or "pmset failed."
        mode = "unavailable"
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "hibernatemode":
                mode = parts[1]
                break
        return f"works on: macOS only\nhibernatemode: {mode}\nhibernation: {self.hibernation_mode_description(mode)}"

    def hibernation_mode_description(self, mode: str | int) -> str:
        descriptions = {
            "0": "disabled",
            "3": "enabled (default portable mode)",
            "25": "enabled (deep hibernation mode)",
        }
        return descriptions.get(str(mode), "custom mode")

    def set_hibernation_mode(self, mode: int, parent: tk.Toplevel) -> None:
        if platform.system() != "Darwin":
            messagebox.showerror("Unsupported", "Hibernation control works on macOS only.", parent=parent)
            return
        pmset = shutil.which("pmset")
        if pmset is None:
            messagebox.showerror("Missing pmset", "pmset was not found.", parent=parent)
            return
        if self._hibernation_running:
            messagebox.showinfo("Hibernation", "A hibernation change is already running; wait for it to finish.", parent=parent)
            return
        if not messagebox.askyesno(
            "Confirm Hibernation Change",
            f"This will run:\n\nsudo -n pmset -a hibernatemode {mode}\n\n"
            f"Mode {mode}: {self.hibernation_mode_description(mode)}\n\nContinue?",
            parent=parent,
        ):
            return
        self._hibernation_running = True

        def apply_mode() -> None:
            # sudo -n: never prompt for a password. A password prompt would
            # otherwise block this call (and, before, the whole GUI) forever.
            try:
                result = subprocess.run(
                    ["sudo", "-n", pmset, "-a", "hibernatemode", str(mode)],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError("sudo pmset did not finish within 10 seconds.")
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or f"sudo pmset exited with status {result.returncode}"
                if "password" in detail.lower():
                    detail += (
                        "\n\nsudo needs a password, which the GUI cannot enter. "
                        "Run ai_hibernation.bash from a terminal instead."
                    )
                raise RuntimeError(detail)

        self._run_bg(
            apply_mode,
            lambda _result, error: self._finish_set_hibernation(parent, error),
            name="ai-loop-hibernation",
            busy_attr="_hibernation_running",
            label="Hibernation change",
        )

    def _finish_set_hibernation(self, parent: tk.Toplevel, error: str | None) -> None:
        self._hibernation_running = False
        dialog_parent: tk.Misc = self
        try:
            if parent.winfo_exists():
                dialog_parent = parent
        except tk.TclError:
            pass
        if error is not None:
            messagebox.showerror("Hibernation Change Failed", error, parent=dialog_parent)
            return
        self.open_hibernation_window(parent if dialog_parent is parent else None)
        self.refresh_all()

    def open_hibernation_window(self, existing: tk.Toplevel | None = None) -> None:
        if existing is not None:
            try:
                existing.destroy()
            except tk.TclError:
                pass
        window = tk.Toplevel(self)
        window.title("macOS Hibernation")
        window.geometry("520x300")
        window.columnconfigure(0, weight=1)
        text = self.help_widget(tk.Text(window, height=8, wrap="word"), "Read-only summary of the current macOS hibernation state and the available hibernatemode values.")
        text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        mode_help = (
            "\n\nSelectable modes:\n"
            "0: disabled\n"
            "3: enabled (default portable mode)\n"
            "25: enabled (deep hibernation mode)"
        )
        text.insert("1.0", "Loading hibernation status…" + mode_help)
        text.configure(state="disabled")

        def show_status(status: str | None, error: str | None) -> None:
            content = (status if error is None else f"Could not read hibernation status: {error}") + mode_help
            try:
                if not text.winfo_exists():
                    return
                text.configure(state="normal")
                text.delete("1.0", "end")
                text.insert("1.0", content)
                text.configure(state="disabled")
            except tk.TclError:
                pass

        # pmset runs in a background thread so opening/refreshing this window
        # never blocks the GUI.
        self._run_bg(self.hibernation_status_text, show_status, name="ai-loop-hibernation-status")
        controls = ttk.Frame(window, padding=(10, 0, 10, 10))
        controls.grid(row=1, column=0, sticky="ew")
        selected_mode = tk.StringVar(value="3")
        mode_select = self.help_widget(ttk.Combobox(controls, textvariable=selected_mode, values=("0", "3", "25"), width=4, state="readonly"), "Choose the hibernatemode value to apply on this Mac.")
        mode_select.pack(side="left")
        self.help_widget(ttk.Button(controls, text="Refresh", command=lambda: self.open_hibernation_window(window)), "Reload the current hibernation status from pmset.").pack(side="left")
        self.help_widget(ttk.Button(controls, text="Apply", command=lambda: self.set_hibernation_mode(int(selected_mode.get()), window)), "Run sudo pmset to apply the selected hibernatemode.").pack(side="left", padx=(8, 0))
        self.help_widget(ttk.Button(controls, text="Close", command=window.destroy), "Close the hibernation helper window.").pack(side="right")
        self.install_default_help(window)
        window.protocol("WM_DELETE_WINDOW", window.destroy)


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
