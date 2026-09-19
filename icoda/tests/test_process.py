"""run_bounded: exit codes, bounded output, stdin, timeout with process-tree kill."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from icoda_core import process
from icoda_core.process import run_bounded

PY = sys.executable


def test_captures_stdout_stderr_and_returncode() -> None:
    result = run_bounded([PY, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"])
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"
    assert result.returncode == 3 and not result.ok and not result.timed_out


def test_keeps_only_the_tail_of_large_output() -> None:
    script = "import sys; print('x' * 5000 + 'OUT_END'); print('y' * 5000 + 'ERR_END', file=sys.stderr)"
    result = run_bounded([PY, "-c", script], max_output=100)
    assert result.truncated
    assert result.stdout.startswith("[output truncated]\n")
    assert result.stderr.startswith("[output truncated]\n")
    assert result.stdout.endswith("OUT_END\n") and len(result.stdout.encode()) <= 100
    assert result.stderr.endswith("ERR_END\n") and len(result.stderr.encode()) <= 100


def test_passes_stdin() -> None:
    result = run_bounded([PY, "-c", "import sys; print(sys.stdin.read().upper())"], input_text="abc")
    assert result.stdout.strip() == "ABC"


def test_does_not_inherit_parent_stdin() -> None:
    result = run_bounded([PY, "-c", "input('prompt: ')"], timeout=0.5)
    assert not result.ok
    assert result.duration < 2
    assert result.returncode != 0 or result.timed_out


def test_blocked_stdin_write_does_not_delay_timeout() -> None:
    result = run_bounded([PY, "-c", "import time; time.sleep(30)"],
                         input_text="x" * 1_000_000, timeout=0.25)
    assert result.timed_out and not result.ok
    assert result.duration < 2


@pytest.mark.parametrize("command", [f"{PY} -c 'print(1)'", b"python -c 'print(1)'"])
def test_rejects_shell_command_strings(command: str | bytes) -> None:
    with pytest.raises(TypeError, match="argument sequence"):
        run_bounded(command)


def test_child_exiting_before_stdin_write_finishes_is_not_a_runner_failure() -> None:
    result = run_bounded([PY, "-c", "pass"], input_text="x" * 1_000_000)

    assert result.returncode == 0
    assert result.ok and not result.timed_out


def test_appending_empty_chunk_to_truncated_tail_needs_no_second_trim() -> None:
    tail = process._Tail(40)
    tail.append(b"x" * 80)
    retained = bytes(tail.data)

    tail.append(b"")

    assert bytes(tail.data) == retained
    assert tail.text().startswith("[output truncated]\n")


def test_windows_kill_tree_handles_exited_and_failed_taskkill(monkeypatch: pytest.MonkeyPatch) -> None:
    taskkill_commands: list[list[str]] = []
    killed: list[int] = []
    monkeypatch.setattr(process.sys, "platform", "win32")

    exited = SimpleNamespace(pid=40, poll=lambda: 0, kill=lambda: killed.append(40))
    monkeypatch.setattr(
        process.subprocess, "run",
        lambda *_args, **_kwargs: pytest.fail("an exited process must not invoke taskkill"),
    )
    process.kill_tree(exited)

    successful = SimpleNamespace(pid=39, poll=lambda: None, kill=lambda: killed.append(39))

    def taskkill(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        taskkill_commands.append(command)
        return subprocess.CompletedProcess(command, int(command[-1] == "41"))

    running = SimpleNamespace(pid=41, poll=lambda: None, kill=lambda: killed.append(41))
    monkeypatch.setattr(process.subprocess, "run", taskkill)
    process.kill_tree(successful)
    process.kill_tree(running)

    assert taskkill_commands == [
        ["taskkill", "/F", "/T", "/PID", "39"],
        ["taskkill", "/F", "/T", "/PID", "41"],
    ]
    assert killed == [41]


def test_windows_kill_tree_falls_back_when_taskkill_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[int] = []
    running = SimpleNamespace(pid=42, poll=lambda: None, kill=lambda: killed.append(42))
    monkeypatch.setattr(process.sys, "platform", "win32")
    monkeypatch.setattr(
        process.subprocess, "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("taskkill unavailable")),
    )

    process.kill_tree(running)

    assert killed == [42]


def test_posix_kill_tree_escalates_after_group_probe_permission_error(
        monkeypatch: pytest.MonkeyPatch) -> None:
    signals: list[int] = []
    moments = iter((0.0, 0.0))
    running = SimpleNamespace(pid=43, poll=lambda: None, kill=lambda: pytest.fail("unexpected fallback"))

    def killpg(_pid: int, sent_signal: int) -> None:
        signals.append(sent_signal)
        if sent_signal == 0:
            raise PermissionError("probe refused")

    monkeypatch.setattr(process.sys, "platform", "linux")
    monkeypatch.setattr(process.os, "killpg", killpg)
    monkeypatch.setattr(process.time, "monotonic", lambda: next(moments))
    monkeypatch.setattr(process.time, "sleep", lambda _delay: pytest.fail("probe failure must break"))

    process.kill_tree(running)

    assert signals == [signal.SIGTERM, 0, signal.SIGKILL]


def test_posix_kill_tree_uses_process_kill_when_sigkill_fails(
        monkeypatch: pytest.MonkeyPatch) -> None:
    signals: list[int] = []
    killed: list[int] = []
    moments = iter((0.0, 1.0))
    running = SimpleNamespace(pid=44, poll=lambda: None, kill=lambda: killed.append(44))

    def killpg(_pid: int, sent_signal: int) -> None:
        signals.append(sent_signal)
        if sent_signal == signal.SIGKILL:
            raise ProcessLookupError("group vanished")

    monkeypatch.setattr(process.sys, "platform", "linux")
    monkeypatch.setattr(process.os, "killpg", killpg)
    monkeypatch.setattr(process.time, "monotonic", lambda: next(moments))

    process.kill_tree(running)

    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert killed == [44]


def test_process_kill_and_stdin_close_errors_are_secondary() -> None:
    class RefusingInput:
        def __init__(self) -> None:
            self.written = b""

        def write(self, data: bytes) -> None:
            self.written = data

        def close(self) -> None:
            raise OSError("close refused")

    stdin = RefusingInput()
    running = SimpleNamespace(
        stdin=stdin,
        poll=lambda: None,
        kill=lambda: (_ for _ in ()).throw(OSError("kill refused")),
    )

    process._kill_process(running)
    writer = process._feed_stdin(running, "payload")
    assert writer is not None
    writer.join(timeout=1)

    assert not writer.is_alive()
    assert stdin.written == b"payload"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_timeout_kills_the_child_and_its_children(tmp_path: Path) -> None:
    pid_path = tmp_path / "grandchild.pid"
    child = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
    script = ("import pathlib, subprocess, time; "
              f"child = subprocess.Popen([{PY!r}, '-c', {child!r}]); "
              f"pathlib.Path({str(pid_path)!r}).write_text(str(child.pid)); time.sleep(30)")
    result = run_bounded([PY, "-c", script], timeout=0.5)
    assert result.timed_out and not result.ok
    assert result.duration < 5
    grandchild = int(pid_path.read_text())
    deadline = time.monotonic() + 2
    while _pid_is_running(grandchild) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _pid_is_running(grandchild)


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    status = Path(f"/proc/{pid}/stat")
    if not status.parent.parent.is_dir():
        return True
    try:
        return status.read_text().split()[2] != "Z"
    except FileNotFoundError:
        return False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_cancel_running_kills_the_waiting_process_and_marks_the_result() -> None:
    import threading
    import time

    from icoda_core import process

    results: list[process.ProcessResult] = []
    script = "import time; time.sleep(30)  # cancel test"
    thread = threading.Thread(target=lambda: results.append(run_bounded([PY, "-c", script], timeout=60)))
    thread.start()
    deadline = time.monotonic() + 5

    def registered() -> bool:
        return any(list(child.args)[-1] == script for child in list(process._running.values()))

    while not registered() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert registered()
    assert process.cancel_running() >= 1  # other tests' background processes may be waiting too
    thread.join(timeout=10)
    assert results and results[0].cancelled and not results[0].ok and results[0].duration < 5
    assert results[0].command[0] == PY and results[0].returncode != 0
    assert not registered()  # the registry forgot the killed process
