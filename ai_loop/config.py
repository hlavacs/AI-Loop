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


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    db_path: Path
    redis_url: str
    runs_dir: Path
    codex_bin: str
    claude_bin: str
    codex_bypass_sandbox: bool


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
    )

