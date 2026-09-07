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
