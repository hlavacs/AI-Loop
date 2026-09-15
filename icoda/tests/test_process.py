"""run_bounded: exit codes, bounded output, stdin, timeout with process-tree kill."""

from __future__ import annotations

import sys

import pytest

from icoda_core.process import run_bounded

PY = sys.executable


def test_captures_stdout_stderr_and_returncode() -> None:
    result = run_bounded([PY, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"])
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"
    assert result.returncode == 3 and not result.ok and not result.timed_out


def test_keeps_only_the_tail_of_large_output() -> None:
    result = run_bounded([PY, "-c", "print('x' * 5000 + 'END')"], max_output=100)
    assert result.truncated
    assert result.stdout.endswith("END\n") and len(result.stdout) <= 100


def test_passes_stdin() -> None:
    result = run_bounded([PY, "-c", "import sys; print(sys.stdin.read().upper())"], input_text="abc")
    assert result.stdout.strip() == "ABC"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_timeout_kills_the_child_and_its_children() -> None:
    script = "import subprocess, time; subprocess.Popen(['sleep', '30']); time.sleep(30)"
    result = run_bounded([PY, "-c", script], timeout=0.5)
    assert result.timed_out and not result.ok
    assert result.duration < 5


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
