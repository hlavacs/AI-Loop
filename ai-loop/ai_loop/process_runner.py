"""Bounded, process-tree-aware subprocess execution.

The standard ``subprocess.run(capture_output=True)`` API buffers complete
stdout and stderr streams before returning.  Commands executed on behalf of a
job are not trusted to keep that output small, so this module drains both
streams continuously while retaining only a fixed-size tail.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


DEFAULT_MAX_OUTPUT_BYTES = 2_000_000
_READ_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class BoundedProcessResult:
    """Completed process data whose captured output is bounded in memory."""

    args: Sequence[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    output_truncated: bool = False


class _SharedTailBuffers:
    """Keep stdout/stderr tails within one shared byte budget.

    Each stream gets half of the budget when both are noisy, but may borrow
    unused capacity from the other.  This avoids a chatty stderr stream
    completely erasing a structured stdout response (and vice versa).
    """

    def __init__(self, maximum: int) -> None:
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
            raise ValueError("max_output_bytes must be a positive integer")
        self.maximum = maximum
        self.stdout = bytearray()
        self.stderr = bytearray()
        self.truncated = False
        self._lock = threading.Lock()

    def append(self, stream: str, chunk: bytes) -> None:
        if not chunk:
            return
        with self._lock:
            target = self.stdout if stream == "stdout" else self.stderr
            target.extend(chunk)
            self._rebalance()

    def _trim_left(self, value: bytearray, amount: int) -> None:
        if amount <= 0:
            return
        del value[:amount]
        self.truncated = True

    def _rebalance(self) -> None:
        excess = len(self.stdout) + len(self.stderr) - self.maximum
        if excess <= 0:
            return

        stdout_floor = (self.maximum + 1) // 2
        stderr_floor = self.maximum // 2
        stdout_borrowed = max(0, len(self.stdout) - stdout_floor)
        stderr_borrowed = max(0, len(self.stderr) - stderr_floor)

        trim_stdout = min(excess, stdout_borrowed)
        self._trim_left(self.stdout, trim_stdout)
        excess -= trim_stdout

        trim_stderr = min(excess, stderr_borrowed)
        self._trim_left(self.stderr, trim_stderr)
        excess -= trim_stderr

        # The floor sizes sum to the maximum, so this is only a defensive
        # fallback for unusual interleavings or future allocation changes.
        if excess > 0:
            target = self.stdout if len(self.stdout) >= len(self.stderr) else self.stderr
            self._trim_left(target, excess)

    def decoded(self) -> tuple[str, str, bool]:
        with self._lock:
            return (
                bytes(self.stdout).decode("utf-8", errors="replace"),
                bytes(self.stderr).decode("utf-8", errors="replace"),
                self.truncated,
            )


def _drain_stream(stream, buffers: _SharedTailBuffers, name: str) -> None:
    try:
        while True:
            chunk = stream.read(_READ_CHUNK_BYTES)
            if not chunk:
                return
            buffers.append(name, chunk)
    except (OSError, ValueError):
        # Closing a pipe during timeout cleanup can race with the reader.
        return
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _write_input(stream, value: bytes) -> None:
    try:
        stream.write(value)
        stream.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _kill_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Forcefully terminate the isolated process group when available."""

    if os.name == "posix":
        try:
            # A child started with start_new_session has pgid == pid.  Using
            # that known id still works if the session leader exited while a
            # grandchild kept an inherited output pipe open.
            os.killpg(process.pid, signal.SIGKILL)
            return
        except (OSError, ProcessLookupError):
            pass
    try:
        process.kill()
    except OSError:
        pass


def run_bounded_process(
    args: Sequence[str],
    *,
    cwd: str | Path | None = None,
    input_text: str | None = None,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> BoundedProcessResult:
    """Run a command in an isolated session with bounded output retention.

    On POSIX, the child becomes a new session leader.  A timeout sends SIGKILL
    to that process group so descendants that inherited the group cannot leak.
    Other platforms fall back to killing the direct child.
    """

    buffers = _SharedTailBuffers(max_output_bytes)
    popen_kwargs: dict[str, object] = {
        "cwd": str(cwd) if cwd is not None else None,
        "env": dict(env) if env is not None else None,
        "stdin": subprocess.PIPE if input_text is not None else None,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(list(args), **popen_kwargs)  # type: ignore[arg-type]
    assert process.stdout is not None
    assert process.stderr is not None
    readers = [
        threading.Thread(
            target=_drain_stream,
            args=(process.stdout, buffers, "stdout"),
            daemon=True,
        ),
        threading.Thread(
            target=_drain_stream,
            args=(process.stderr, buffers, "stderr"),
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()

    writer: threading.Thread | None = None
    if input_text is not None:
        assert process.stdin is not None
        writer = threading.Thread(
            target=_write_input,
            args=(process.stdin, input_text.encode("utf-8")),
            daemon=True,
        )
        writer.start()

    timed_out = False
    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_tree(process)
        process.wait()

    threads = [*readers, *([writer] if writer is not None else [])]
    for thread in threads:
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        thread.join(timeout=remaining)
    if any(thread.is_alive() for thread in threads):
        timed_out = True
        _kill_process_tree(process)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        for thread in threads:
            thread.join(timeout=1.0)

    stdout, stderr, output_truncated = buffers.decoded()
    return BoundedProcessResult(
        args=tuple(args),
        returncode=int(process.returncode),
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        output_truncated=output_truncated,
    )


def read_bounded_text_tail(
    path: str | Path,
    *,
    max_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> tuple[str, bool]:
    """Read only a bounded tail from a subprocess-managed output file."""

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    with Path(path).open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        truncated = size > max_bytes
        if truncated:
            handle.seek(size - max_bytes)
        else:
            handle.seek(0)
        return handle.read(max_bytes).decode("utf-8", errors="replace"), truncated
