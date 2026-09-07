"""Bounded subprocess execution with timeout, output limits and process-tree kill."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO


@dataclass
class ProcessResult:
    """Outcome of :func:`run_bounded`; stdout and stderr hold at most the last ``max_output`` bytes."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    truncated: bool = False
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


@dataclass
class _Tail:
    """Keeps the last ``limit`` bytes of a stream."""

    limit: int
    data: bytearray = field(default_factory=bytearray)
    truncated: bool = False

    def append(self, chunk: bytes) -> None:
        self.data.extend(chunk)
        if len(self.data) > self.limit:
            del self.data[: len(self.data) - self.limit]
            self.truncated = True

    def text(self) -> str:
        return self.data.decode("utf-8", errors="replace")


def _pump(stream: IO[bytes], tail: _Tail) -> None:
    for chunk in iter(lambda: stream.read(4096), b""):
        tail.append(chunk)
    stream.close()


def kill_tree(process: subprocess.Popen[bytes]) -> None:
    """Kill the process and everything it started (its session on POSIX, its tree on Windows)."""
    if process.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, check=False)
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        process.kill()


def run_bounded(
    command: Sequence[str],
    *,
    cwd: Path | str | None = None,
    timeout: float = 600.0,
    max_output: int = 200_000,
    input_text: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ProcessResult:
    """Run ``command`` to completion or until ``timeout`` seconds, keeping bounded output."""
    started = time.monotonic()
    process = subprocess.Popen(
        list(command),
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(env) if env is not None else None,
        start_new_session=sys.platform != "win32",
    )
    out, err = _Tail(max_output), _Tail(max_output)
    assert process.stdout is not None and process.stderr is not None
    threads = [threading.Thread(target=_pump, args=(process.stdout, out), daemon=True),
               threading.Thread(target=_pump, args=(process.stderr, err), daemon=True)]
    for thread in threads:
        thread.start()
    timed_out = _feed_and_wait(process, input_text, timeout)
    for thread in threads:
        thread.join(timeout=5)
    return ProcessResult(list(command), process.returncode if process.returncode is not None else -1,
                         out.text(), err.text(), timed_out, out.truncated or err.truncated,
                         time.monotonic() - started)


def _feed_and_wait(process: subprocess.Popen[bytes], input_text: str | None, timeout: float) -> bool:
    """Write stdin, wait for exit; on timeout kill the tree and return True."""
    if input_text is not None and process.stdin is not None:
        try:
            process.stdin.write(input_text.encode("utf-8"))
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
    try:
        process.wait(timeout=timeout)
        return False
    except subprocess.TimeoutExpired:
        kill_tree(process)
        process.wait()
        return True
