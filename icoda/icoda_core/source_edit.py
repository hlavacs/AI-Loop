"""Small, loss-aware source documents and literal search for the built-in editor."""
from __future__ import annotations

import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024


class FileChangedError(OSError):
    """The file changed outside the editor; keep both versions until the developer decides."""


def relative_path(root: Path, file: str) -> str:
    """Normalize spelling while retaining in-project symlinks for save-time checks."""
    logical = Path(os.path.abspath(root / file))
    for base in (Path(os.path.abspath(root)), root.resolve()):
        try:
            return str(logical.relative_to(base))
        except ValueError:
            continue
    raise ValueError("The source editor opens files inside the selected project or worktree.")


def source_path(root: Path, relative: str) -> Path:
    base = root.resolve()
    path = (base / relative).resolve()
    try:
        parts = path.relative_to(base).parts
    except ValueError as exc:
        raise ValueError("The source editor opens files inside the selected project or worktree.") from exc
    if not parts or any(part in {".git", ".icoda"} for part in parts):
        raise ValueError("Project metadata cannot be edited in the source editor.")
    return path


def _read(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("This file exceeds the source editor's 2 MiB limit. Use an external editor.")
    return data


@dataclass
class Document:
    root: Path
    relative: str
    path: Path
    original: bytes
    text: str
    newline: str
    bom: bool

    @classmethod
    def load(cls, root: Path, relative: str) -> Document:
        relative = relative_path(root, relative)
        path = source_path(root, relative)
        data = _read(path)
        if b"\0" in data:
            raise ValueError("This is a binary file. The source editor opens UTF-8 text files.")
        try:
            decoded = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("This file is not UTF-8. Use an external editor to preserve its encoding.") from exc
        newline = "\r\n" if "\r\n" in decoded else "\r" if "\r" in decoded else "\n"
        text = decoded.replace("\r\n", "\n").replace("\r", "\n")
        return cls(root.resolve(), relative, path, data, text, newline, data.startswith(b"\xef\xbb\xbf"))

    def save(self, text: str) -> None:
        """Atomically replace the file, preserving mode/format and refusing external changes."""
        if source_path(self.root, self.relative) != self.path or _read(self.path) != self.original:
            raise FileChangedError("The file changed on disk. Your edits are still in the editor. "
                                   "Use Reload to inspect the disk version, or copy your edits before merging.")
        if text == self.text:
            return
        mode = stat.S_IMODE(self.path.stat().st_mode)
        if not mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            raise PermissionError("The source file is read-only. Your edits remain in the editor.")
        data = text.replace("\n", self.newline).encode("utf-8")
        if self.bom:
            data = b"\xef\xbb\xbf" + data
        temporary: str | None = None
        try:
            fd, temporary = tempfile.mkstemp(prefix="." + self.path.name + ".", suffix=".tmp",
                                             dir=self.path.parent)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            if source_path(self.root, self.relative) != self.path or _read(self.path) != self.original:
                raise FileChangedError("The file changed while saving. Your editor buffer has been preserved.")
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
        self.original, self.text = data, text


def matches(text: str, needle: str, match_case: bool = False) -> list[tuple[int, int]]:
    """Literal, non-overlapping character ranges; empty searches never match."""
    if not needle:
        return []
    return [(match.start(), match.end()) for match in re.finditer(
        re.escape(needle), text, flags=0 if match_case else re.IGNORECASE)]
