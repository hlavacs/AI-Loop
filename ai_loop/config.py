"""Runtime configuration for the AI development loop."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


CLAUDE_REQUEST_STREAM = "ai:claude:requests"
CODEX_TASK_STREAM = "ai:codex:tasks"
DONE_STREAM = "ai:done"
HUMAN_STREAM = "ai:human"
DEAD_STREAM = "ai:dead"

READ_BLOCK_MS = 5000

WORKERS = {"claude", "codex", "fable", "opus", "gemini"}
CONTROLLERS = {"claude", "fable", "opus", "codex", "gemini"}


def normalize_worker(value: str) -> str:
    worker = value.strip().lower()
    if worker not in WORKERS:
        raise ValueError(f"unknown worker: {value!r}; expected one of {sorted(WORKERS)}")
    return worker


def normalize_controller(value: str) -> str:
    controller = value.strip().lower()
    if controller not in CONTROLLERS:
        raise ValueError(f"unknown controller: {value!r}; expected one of {sorted(CONTROLLERS)}")
    return controller


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    db_path: Path
    redis_url: str
    runs_dir: Path
    codex_bin: str
    claude_bin: str
    gemini_bin: str
    codex_model: str
    codex_bypass_sandbox: bool
    codex_systemd_sandbox: bool
    worker_default: str
    fable_model: str
    controller_default: str
    controller_model: str
    opus_model: str
    gemini_model: str
    controller_role_model: str
    worker_role_model: str
    notify_email: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_starttls: bool
    smtp_ssl: bool
    imap_host: str
    imap_port: int
    imap_user: str
    imap_password: str
    imap_mailbox: str
    imap_ssl: bool
    imap_starttls: bool
    email_poll_seconds: int


SENSITIVE_ENV_KEYS = ("AI_LOOP_SMTP_PASSWORD", "AI_LOOP_IMAP_PASSWORD")


def sanitized_child_env() -> dict[str, str]:
    """Environment for AI-CLI and test-command subprocesses.

    The worker's children (the coding-agent CLI and the repository's own test
    command) must not inherit mail credentials: an unsandboxed agent or an
    untrusted test script could read them with a single `env` call. Mail is
    sent only by the controller/worker/watcher Python processes themselves,
    which keep the full environment.
    """
    env = os.environ.copy()
    for key in list(env):
        if key in SENSITIVE_ENV_KEYS or (key.startswith("AI_LOOP_") and "PASSWORD" in key):
            env.pop(key, None)
    return env


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    root_dir = Path(__file__).resolve().parent.parent
    db_path = Path(os.getenv("AI_LOOP_DB", root_dir / "ai_loop.sqlite3")).expanduser()
    runs_dir = Path(os.getenv("AI_LOOP_RUNS_DIR", root_dir.parent / "ai-runs")).expanduser()
    return Settings(
        root_dir=root_dir,
        db_path=db_path,
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        runs_dir=runs_dir,
        codex_bin=os.getenv("CODEX_BIN", "codex"),
        claude_bin=os.getenv("CLAUDE_BIN", "claude"),
        gemini_bin=os.getenv("GEMINI_BIN", "gemini"),
        codex_model=os.getenv("AI_LOOP_CODEX_MODEL", ""),
        codex_bypass_sandbox=env_bool("CODEX_BYPASS_SANDBOX", False),
        codex_systemd_sandbox=env_bool("AI_LOOP_CODEX_SYSTEMD_SANDBOX", False),
        worker_default=normalize_worker(os.getenv("AI_LOOP_WORKER", "codex")),
        fable_model=os.getenv("AI_LOOP_FABLE_MODEL", "").strip(),
        controller_default=normalize_controller(os.getenv("AI_LOOP_CONTROLLER", "opus")),
        controller_model=os.getenv("AI_LOOP_CONTROLLER_MODEL", ""),
        opus_model=os.getenv("AI_LOOP_OPUS_MODEL", "").strip(),
        gemini_model=os.getenv("AI_LOOP_GEMINI_MODEL", ""),
        controller_role_model=os.getenv("AI_LOOP_CONTROLLER_ROLE_MODEL", "").strip(),
        worker_role_model=os.getenv("AI_LOOP_WORKER_ROLE_MODEL", "").strip(),
        notify_email=os.getenv("AI_LOOP_NOTIFY_EMAIL", ""),
        smtp_host=os.getenv("AI_LOOP_SMTP_HOST", "").strip(),
        smtp_port=int(os.getenv("AI_LOOP_SMTP_PORT", "465" if env_bool("AI_LOOP_SMTP_SSL") else "587")),
        smtp_user=os.getenv("AI_LOOP_SMTP_USER", "").strip(),
        smtp_password=os.getenv("AI_LOOP_SMTP_PASSWORD", ""),
        smtp_from=os.getenv("AI_LOOP_SMTP_FROM", "").strip(),
        smtp_starttls=env_bool("AI_LOOP_SMTP_STARTTLS", True),
        smtp_ssl=env_bool("AI_LOOP_SMTP_SSL", False),
        imap_host=os.getenv("AI_LOOP_IMAP_HOST", "").strip(),
        imap_port=int(os.getenv("AI_LOOP_IMAP_PORT", "993" if env_bool("AI_LOOP_IMAP_SSL", True) else "143")),
        imap_user=os.getenv("AI_LOOP_IMAP_USER", os.getenv("AI_LOOP_SMTP_USER", "")).strip(),
        imap_password=os.getenv("AI_LOOP_IMAP_PASSWORD", os.getenv("AI_LOOP_SMTP_PASSWORD", "")),
        imap_mailbox=os.getenv("AI_LOOP_IMAP_MAILBOX", "INBOX").strip() or "INBOX",
        imap_ssl=env_bool("AI_LOOP_IMAP_SSL", True),
        imap_starttls=env_bool("AI_LOOP_IMAP_STARTTLS", True),
        email_poll_seconds=max(5, int(os.getenv("AI_LOOP_EMAIL_POLL_SECONDS", "30"))),
    )
