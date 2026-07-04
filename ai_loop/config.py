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

WORKERS = {"codex", "fable", "opus"}
CONTROLLERS = {"claude", "fable", "opus", "codex"}


def normalize_worker(value: str) -> str:
    worker = value.strip().lower()
    if worker == "claude":
        worker = "fable"
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
    codex_bypass_sandbox: bool
    worker_default: str
    fable_model: str
    controller_default: str
    controller_model: str
    opus_model: str


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
        codex_bypass_sandbox=env_bool("CODEX_BYPASS_SANDBOX", False),
        worker_default=normalize_worker(os.getenv("AI_LOOP_WORKER", "codex")),
        fable_model=os.getenv("AI_LOOP_FABLE_MODEL", "claude-fable-5"),
        controller_default=normalize_controller(os.getenv("AI_LOOP_CONTROLLER", "opus")),
        controller_model=os.getenv("AI_LOOP_CONTROLLER_MODEL", ""),
        opus_model=os.getenv("AI_LOOP_OPUS_MODEL", "opus"),
    )
