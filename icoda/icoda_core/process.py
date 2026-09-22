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

_TRUNCATION_MARKER = b"[output truncated]\n"
_TERMINATE_GRACE = 0.25


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
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.cancelled


@dataclass
class _Tail:
    """Keeps the last ``limit`` bytes of a stream."""

    limit: int
    data: bytearray = field(default_factory=bytearray)
    truncated: bool = False

    def append(self, chunk: bytes) -> None:
        self.data.extend(chunk)
        if self.truncated or len(self.data) > self.limit:
            self.truncated = True
            payload_limit = max(0, self.limit - len(_TRUNCATION_MARKER))
            if len(self.data) > payload_limit:
                del self.data[: len(self.data) - payload_limit]

    def text(self) -> str:
        marker = _TRUNCATION_MARKER[:self.limit] if self.truncated else b""
        return (marker + self.data).decode("utf-8", errors="replace")


def _pump(stream: IO[bytes], tail: _Tail) -> None:
    for chunk in iter(lambda: stream.read(4096), b""):
        tail.append(chunk)
    stream.close()


_running: dict[int, subprocess.Popen[bytes]] = {}
_cancelled: set[int] = set()
_registry_lock = threading.Lock()


def cancel_running() -> int:
    """Kill every process that :func:`run_bounded` is still waiting for; return how many were killed.

    The affected results come back with ``cancelled`` set, so callers can tell a cancel from a failure.
    """
    with _registry_lock:
        processes = list(_running.items())
        _cancelled.update(pid for pid, _process in processes)
    for _pid, process in processes:
        kill_tree(process)
    return len(processes)


def _register(process: subprocess.Popen[bytes]) -> None:
    with _registry_lock:
        _running[process.pid] = process


def _unregister(process: subprocess.Popen[bytes]) -> bool:
    """Forget the process; True when it was killed through :func:`cancel_running`."""
    with _registry_lock:
        _running.pop(process.pid, None)
        was_cancelled = process.pid in _cancelled
        _cancelled.discard(process.pid)
    return was_cancelled


def kill_tree(process: subprocess.Popen[bytes]) -> None:
    """Terminate the process tree, escalating to a forced kill after a short grace period."""
    if sys.platform == "win32":
        if process.poll() is not None:
            return
        try:
            result = subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                                    stdin=subprocess.DEVNULL, capture_output=True, timeout=5, check=False)
            if result.returncode != 0:
                _kill_process(process)
        except (OSError, subprocess.SubprocessError):
            _kill_process(process)
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        _kill_process(process)
        return
    deadline = time.monotonic() + _TERMINATE_GRACE
    while time.monotonic() < deadline:
        process.poll()
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        except (PermissionError, OSError):
            break
        time.sleep(0.01)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        _kill_process(process)


def _kill_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def run_bounded(
    command: Sequence[str],
    *,
    cwd: Path | str | None = None,
    timeout: float = 600.0,
    max_output: int = 200_000,
    input_text: str | None = None,
    env: Mapping[str, str] | None = None,
    cancel_event: threading.Event | None = None,
) -> ProcessResult:
    """Run a bounded command; an explicit cancel event isolates it from foreground cancellation."""
    if isinstance(command, (str, bytes)):
        raise TypeError("command must be an argument sequence, not a shell command string")
    if cancel_event is not None and cancel_event.is_set():
        return ProcessResult(list(command), -1, "", "", cancelled=True)
    started = time.monotonic()
    process = subprocess.Popen(
        list(command),
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(env) if env is not None else None,
        shell=False,
        start_new_session=sys.platform != "win32",
        creationflags=int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) if sys.platform == "win32" else 0,
    )
    if cancel_event is None:
        _register(process)
    out, err = _Tail(max_output), _Tail(max_output)
    assert process.stdout is not None and process.stderr is not None
    threads = [threading.Thread(target=_pump, args=(process.stdout, out), daemon=True),
               threading.Thread(target=_pump, args=(process.stderr, err), daemon=True)]
    for thread in threads:
        thread.start()
    writer = _feed_stdin(process, input_text)
    timed_out = _wait(process, max(0.0, timeout - (time.monotonic() - started)), cancel_event)
    if writer is not None:
        writer.join(timeout=1)
    for thread in threads:
        thread.join(timeout=5)
    cancelled = _unregister(process) if cancel_event is None else cancel_event.is_set()
    return ProcessResult(list(command), process.returncode if process.returncode is not None else -1,
                         out.text(), err.text(), timed_out, out.truncated or err.truncated,
                         time.monotonic() - started, cancelled)


def _feed_stdin(process: subprocess.Popen[bytes], input_text: str | None) -> threading.Thread | None:
    """Write and close piped stdin without delaying enforcement of the process timeout."""
    stdin = process.stdin
    if input_text is None or stdin is None:
        return None

    def write() -> None:
        try:
            stdin.write(input_text.encode("utf-8"))
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                stdin.close()
            except OSError:
                pass

    thread = threading.Thread(target=write, daemon=True)
    thread.start()
    return thread


def _wait(process: subprocess.Popen[bytes], timeout: float,
          cancel_event: threading.Event | None = None) -> bool:
    """Wait for exit; on timeout terminate the process tree and return True."""
    if cancel_event is not None:
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if cancel_event.is_set():
                kill_tree(process)
                process.wait()
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            cancel_event.wait(min(remaining, 0.1))
        timeout = 0
    try:
        process.wait(timeout=timeout)
        return False
    except subprocess.TimeoutExpired:
        kill_tree(process)
        process.wait()
        return True
