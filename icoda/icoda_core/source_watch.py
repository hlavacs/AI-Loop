"""Pure snapshots used to detect external edits to analysed source files."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from icoda_core import git


@dataclass(frozen=True, order=True)
class FileStamp:
    """One analysed file's identity and inexpensive filesystem fingerprint."""

    path: str
    mtime_ns: int | None
    size: int | None


Snapshot = tuple[FileStamp, ...]


def snapshot_project(root: Path) -> Snapshot | None:
    """Include tracked and new files so CLI renames are detected, excluding caches and ignored builds."""
    try:
        result = git.run_git(["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                             root, check=False) if git.is_own_repository(root) else None
    except OSError:
        return None
    if result is None or result.returncode:
        # A new project can use Prompt before its first specification save creates Git.
        paths: list[str] = []
        excluded = {".git", ".icoda", ".venv", "venv", ".icoda-venv", "__pycache__",
                    ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist", "node_modules"}
        for directory, children, files in os.walk(root):
            children[:] = [name for name in children if name not in excluded]
            paths.extend(str((Path(directory) / name).relative_to(root)) for name in files)
        return snapshot_files(root, paths)
    return snapshot_files(root, (path for path in result.stdout.split("\0")
                                 if path and ".icoda" not in Path(path).parts))


def snapshot_files(root: Path, paths: Iterable[str]) -> Snapshot:
    """Return a stable snapshot for project-relative analysed file paths."""
    entries = []
    for relative in sorted(set(paths)):
        try:
            stat = (root / relative).stat()
        except OSError:
            entries.append(FileStamp(relative, None, None))
        else:
            entries.append(FileStamp(relative, stat.st_mtime_ns, stat.st_size))
    return tuple(entries)


def changed_files(previous: Snapshot, current: Snapshot) -> frozenset[str]:
    """Report exactly the paths whose presence, modification time, or size changed."""
    before = {entry.path: (entry.mtime_ns, entry.size) for entry in previous}
    after = {entry.path: (entry.mtime_ns, entry.size) for entry in current}
    return frozenset(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
