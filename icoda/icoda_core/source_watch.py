"""Pure snapshots used to detect external edits to analysed source files."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, order=True)
class FileStamp:
    """One analysed file's identity and inexpensive filesystem fingerprint."""

    path: str
    mtime_ns: int | None
    size: int | None


Snapshot = tuple[FileStamp, ...]


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
