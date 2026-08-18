from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

import worker
from ai_loop.process_runner import run_bounded_process


def test_large_output_is_discarded_during_capture() -> None:
    maximum = 4096
    result = run_bounded_process(
        [
            sys.executable,
            "-c",
            "import os; os.write(1, b'A' * 2000000); os.write(2, b'B' * 2000000)",
        ],
        timeout=10,
        max_output_bytes=maximum,
    )

    retained_bytes = len(result.stdout.encode()) + len(result.stderr.encode())
    assert result.returncode == 0
    assert result.timed_out is False
    assert result.output_truncated is True
    assert retained_bytes <= maximum
    assert result.stdout.endswith("A")
    assert result.stderr.endswith("B")


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
def test_timeout_kills_descendant_process_group(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "child.pid"
    parent_code = (
        "import pathlib, subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid)); "
        "time.sleep(60)"
    )

    result = run_bounded_process(
        [sys.executable, "-c", parent_code],
        timeout=0.5,
        max_output_bytes=4096,
    )

    assert result.timed_out is True
    child_pid = int(child_pid_path.read_text())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{child_pid}/stat").read_text().split()[2]
        except (FileNotFoundError, ProcessLookupError):
            break
        if state == "Z":
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"descendant process {child_pid} survived its parent's timeout")


def test_worker_command_keeps_sensitive_environment_out_of_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_LOOP_SMTP_PASSWORD", "must-not-leak")

    result = worker.run_command(
        [sys.executable, "-c", "import os; print(os.getenv('AI_LOOP_SMTP_PASSWORD', 'missing'))"],
        str(tmp_path),
        10,
    )

    assert result["rc"] == 0
    assert result["output"] == "missing"
