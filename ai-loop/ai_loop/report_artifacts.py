"""Keep transient LLM worker reports outside project repositories."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import TypedDict


class ReportMove(TypedDict):
    source: str
    destination: str


class ReportFailure(TypedDict):
    source: str
    error: str


class ReportRelocation(TypedDict):
    directory: str
    moved: list[ReportMove]
    failures: list[ReportFailure]


def is_worker_report_path(value: str | Path) -> bool:
    """Return whether a path uses AI Loop's reserved transient report name."""

    name = Path(value).name
    return name == ".ai-loop-worker-report.md" or (
        name.startswith(".ai-loop-worker-report-") and name.endswith(".md")
    )


def worker_report_directory(job_id: str, *, temp_root: Path | None = None) -> Path:
    """Return a filesystem-safe per-job directory below the system temp root."""

    safe_job_id = re.sub(r"[^A-Za-z0-9._-]+", "_", job_id).strip("._-") or "unknown-job"
    root = Path(tempfile.gettempdir()) if temp_root is None else temp_root
    return root / "ai-loop-worker-reports" / safe_job_id


def relocate_worker_reports(
    worktree: Path,
    job_id: str,
    *,
    temp_root: Path | None = None,
) -> ReportRelocation:
    """Move reserved reports out of a worktree without overwriting older reports."""

    destination_dir = worker_report_directory(job_id, temp_root=temp_root)
    moved: list[ReportMove] = []
    failures: list[ReportFailure] = []
    candidates: list[Path] = []
    for directory, child_directories, filenames in os.walk(worktree):
        child_directories[:] = [name for name in child_directories if name != ".git"]
        for filename in filenames:
            if is_worker_report_path(filename):
                candidates.append(Path(directory) / filename)
    candidates.sort()
    if candidates:
        destination_dir.mkdir(parents=True, exist_ok=True)

    for source in candidates:
        relative = str(source.relative_to(worktree))
        destination = destination_dir / source.name
        if destination.exists() or destination.is_symlink():
            destination = destination.with_name(
                f"{destination.stem}-{uuid.uuid4().hex[:8]}{destination.suffix}"
            )
        try:
            shutil.move(str(source), str(destination))
        except OSError as exc:
            failures.append({"source": relative, "error": str(exc)})
            continue
        moved.append({"source": relative, "destination": str(destination)})

    return {
        "directory": str(destination_dir),
        "moved": moved,
        "failures": failures,
    }
