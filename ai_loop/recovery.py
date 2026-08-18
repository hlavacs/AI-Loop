"""Automatic recovery for internal ai-loop controller/worker failures."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ai_loop import db
from ai_loop.config import sanitized_child_env
from ai_loop.process_runner import run_bounded_process


def _tail(path: Path, max_bytes: int = 20000) -> str:
    if not path.is_file():
        return f"missing log: {path}"
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
        return handle.read().decode("utf-8", errors="replace")


def attempt_auto_recovery(settings: Any, job_id: str | None, where: str, error: str, fields: Any) -> bool:
    # Auto-recovery lets an unsandboxed agent edit the ai-loop source itself,
    # so it is opt-in: it runs only when AI_LOOP_AUTO_RECOVER is explicitly enabled.
    if not job_id or os.getenv("AI_LOOP_AUTO_RECOVER", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        return False

    codex_bin = os.getenv("AI_LOOP_RECOVERY_BIN", settings.codex_bin or "codex")
    if shutil.which(codex_bin) is None:
        return False

    runtime_dir = settings.root_dir / "run" / "jobs" / job_id
    recovery_flag = runtime_dir / "auto_recovery.running"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    if recovery_flag.exists():
        return False
    recovery_flag.write_text(f"{where}: {error}\n", encoding="utf-8")

    try:
        log_dir = settings.root_dir / "logs" / "jobs" / job_id
        prompt = f"""You are Codex repairing the ai-loop automation after an internal process error.

Job id: {job_id}
Failure location: {where}
Error: {error}
Message fields: {fields}

Controller log tail:
{_tail(log_dir / 'controller.log')}

Worker log tail:
{_tail(log_dir / 'worker.log')}

Watcher log tail:
{_tail(log_dir / 'watcher.log')}

Task:
1. Diagnose the immediate internal ai-loop failure.
2. If it is fixable in this repository, make the smallest code change.
3. Run syntax checks for edited Python/shell files.
4. Do not alter the target job worktree unless the failure is clearly there.
5. If the blocker is quota, credentials, or external service availability, do not fabricate a fix; explain it.
"""
        proc = run_bounded_process(
            [codex_bin, "exec", "--cd", str(settings.root_dir), "--dangerously-bypass-approvals-and-sandbox", "-"],
            input_text=prompt,
            timeout=7200,
            # The recovery agent runs unsandboxed; never hand it mail passwords.
            env=sanitized_child_env(),
            max_output_bytes=40_000,
        )
        if proc.timed_out:
            raise TimeoutError("auto-recovery command timed out after 7200 seconds")
        output = (proc.stdout + "\n" + proc.stderr).strip()
        with db.transaction(settings.db_path) as conn:
            db.add_event(
                conn,
                job_id=job_id,
                kind="auto_recovery_finished",
                payload={"where": where, "returncode": proc.returncode, "output_tail": output[-4000:]},
            )
        if proc.returncode != 0:
            return False

        env = os.environ.copy()
        subprocess.Popen(
            [str(settings.root_dir / "ai_resume_job.bash"), job_id],
            cwd=str(settings.root_dir),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=(os.name != "nt"),
        )
        return True
    except Exception as exc:
        try:
            with db.transaction(settings.db_path) as conn:
                db.add_event(
                    conn,
                    job_id=job_id,
                    kind="auto_recovery_failed",
                    payload={"where": where, "error": repr(exc)},
                )
        except Exception:
            pass
        return False
    finally:
        try:
            recovery_flag.unlink()
        except OSError:
            pass
