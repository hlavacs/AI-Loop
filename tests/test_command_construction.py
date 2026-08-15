"""Integration-style tests for provider command construction and GUI stop.

Covers:
- worker.build_codex_command / build_fable_command / build_gemini_command for
  both sandbox-bypass values, asserting the exact flags.
- controller.run_claude / run_codex_controller / run_gemini_controller: the
  command lists are built inline right before subprocess.run, so the smallest
  seam available is patching controller.subprocess.run to capture the argv
  (and returning a canned valid decision) - no real subprocess ever runs.
- LoopBackend.stop_processes sequencing with REAL dummy processes (bash
  session leaders plus pid files in a temp runtime dir): SIGTERM, group poll,
  SIGKILL escalation, and per-process result reporting, all without Tk
  (LoopBackend is Tk-free; only the AiLoopGui class touches tkinter).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import controller
import worker
from ai_loop import db

try:  # ai_loop_gui needs tkinter (or the AILOOP_TK_STUB), which may be absent
    import ai_loop_gui
except Exception:  # pragma: no cover - environment-dependent
    ai_loop_gui = None


class WorkerCommandConstructionTests(unittest.TestCase):
    def test_codex_command_bypass_uses_dangerous_flag_and_stdin(self) -> None:
        cmd = worker.build_codex_command("codex", "/wt", "PROMPT", "gpt-5-codex", True)
        self.assertEqual(
            cmd,
            [
                "codex",
                "exec",
                "--cd",
                "/wt",
                "-m",
                "gpt-5-codex",
                "--dangerously-bypass-approvals-and-sandbox",
                "-",
            ],
        )

    def test_codex_command_sandboxed_uses_workspace_write(self) -> None:
        cmd = worker.build_codex_command("codex", "/wt", "PROMPT", "gpt-5-codex", False)
        self.assertEqual(
            cmd,
            ["codex", "exec", "--cd", "/wt", "-m", "gpt-5-codex", "--sandbox", "workspace-write", "-"],
        )
        # The prompt is delivered via stdin ("-" placeholder), never as argv.
        self.assertNotIn("PROMPT", cmd)

    def test_codex_command_omits_model_flag_when_model_empty(self) -> None:
        cmd = worker.build_codex_command("codex", "/wt", "PROMPT", "", False)
        self.assertNotIn("-m", cmd)
        self.assertEqual(cmd[-1], "-")

    def test_fable_command_bypass_skips_permissions(self) -> None:
        cmd = worker.build_fable_command("claude", "PROMPT", "claude-model", True)
        self.assertEqual(
            cmd,
            ["claude", "-p", "--model", "claude-model", "--dangerously-skip-permissions", "PROMPT"],
        )

    def test_fable_command_sandboxed_uses_accept_edits_and_allowed_tools(self) -> None:
        cmd = worker.build_fable_command("claude", "PROMPT", "claude-model", False)
        self.assertEqual(
            cmd,
            [
                "claude",
                "-p",
                "--model",
                "claude-model",
                "--permission-mode",
                "acceptEdits",
                "--allowedTools",
                worker.FABLE_ALLOWED_TOOLS,
                "PROMPT",
            ],
        )

    def test_fable_command_omits_model_flag_when_model_empty(self) -> None:
        cmd = worker.build_fable_command("claude", "PROMPT", "", True)
        self.assertNotIn("--model", cmd)

    def test_gemini_command_bypass_uses_yolo(self) -> None:
        cmd = worker.build_gemini_command("gemini", "PROMPT", "gemini-model", True)
        self.assertEqual(cmd, ["gemini", "-m", "gemini-model", "--yolo", "-p", "PROMPT"])

    def test_gemini_command_sandboxed_uses_sandbox_auto_edit(self) -> None:
        cmd = worker.build_gemini_command("gemini", "PROMPT", "gemini-model", False)
        self.assertEqual(
            cmd,
            ["gemini", "-m", "gemini-model", "--sandbox", "--approval-mode", "auto_edit", "-p", "PROMPT"],
        )

    def test_gemini_command_omits_model_flag_when_model_empty(self) -> None:
        cmd = worker.build_gemini_command("gemini", "PROMPT", "", False)
        self.assertNotIn("-m", cmd)


DECISION_JSON = json.dumps(
    {"action": "DONE", "reason": "test decision", "history_summary": "history"}
)


class ControllerCommandConstructionTests(unittest.TestCase):
    """The controller cmd lists are built inline inside run_* right before
    subprocess.run, so there is no extractable builder; capturing the argv via
    a patched controller.subprocess.run is the smallest available seam."""

    def _capture(self, fn, *args, **kwargs):
        calls: list[tuple[list[str], dict]] = []

        def fake_run(cmd, **run_kwargs):
            calls.append((list(cmd), run_kwargs))
            return subprocess.CompletedProcess(cmd, 0, stdout=DECISION_JSON, stderr="")

        with patch.object(controller.shutil, "which", return_value="/usr/bin/fake"), patch.object(
            controller.subprocess, "run", side_effect=fake_run
        ):
            decision = fn(*args, **kwargs)
        self.assertEqual(decision["action"], "DONE")
        self.assertEqual(len(calls), 1)
        return calls[0]

    def test_run_claude_command_flags(self) -> None:
        cmd, kwargs = self._capture(controller.run_claude, "claude", "PROMPT", model="test-model")
        self.assertEqual(cmd[:5], ["claude", "-p", "--output-format", "json", "--json-schema"])
        self.assertEqual(cmd[5], controller.decision_json_schema())
        self.assertEqual(cmd[6:8], ["--model", "test-model"])
        # The prompt is passed as the final argument, not on stdin.
        self.assertEqual(cmd[-1], "PROMPT")
        self.assertNotIn("input", kwargs)

    def test_run_claude_omits_model_flag_when_model_empty(self) -> None:
        cmd, _kwargs = self._capture(controller.run_claude, "claude", "PROMPT")
        self.assertNotIn("--model", cmd)

    def test_run_codex_controller_command_flags(self) -> None:
        cmd, kwargs = self._capture(
            controller.run_codex_controller, "codex", "PROMPT", "/workdir", model="codex-model"
        )
        self.assertEqual(cmd[:6], ["codex", "exec", "--cd", "/workdir", "--sandbox", "read-only"])
        self.assertEqual(cmd[6], "--output-last-message")
        # cmd[7] is the throwaway last-message temp file path.
        self.assertEqual(cmd[8:10], ["-m", "codex-model"])
        self.assertEqual(cmd[-1], "-")
        # The controller runs read-only: the prompt goes in via stdin.
        self.assertEqual(kwargs.get("input"), "PROMPT")

    def test_run_gemini_controller_command_flags(self) -> None:
        cmd, kwargs = self._capture(
            controller.run_gemini_controller, "gemini", "PROMPT", "/workdir", model="gemini-model"
        )
        self.assertEqual(cmd, ["gemini", "-m", "gemini-model", "-p", "PROMPT", "--output-format", "json"])
        self.assertEqual(kwargs.get("cwd"), "/workdir")


@unittest.skipUnless(ai_loop_gui is not None, "ai_loop_gui (tkinter or stub) not importable")
@unittest.skipUnless(hasattr(os, "killpg"), "requires POSIX process groups")
class GuiStopProcessesSequencingTests(unittest.TestCase):
    """stop_processes with real dummy session leaders: SIGTERM, then a group
    poll, then SIGKILL escalation for signal-resistant groups, with results
    reported per process. LoopBackend is Tk-free, so no Tk loop is needed."""

    def _backend(self, root: Path):
        backend = ai_loop_gui.LoopBackend.__new__(ai_loop_gui.LoopBackend)
        db_path = root / "loop.sqlite3"
        db.init_db(db_path)
        backend.settings = SimpleNamespace(root_dir=root, db_path=db_path)
        return backend

    def _spawn(self, script: Path) -> subprocess.Popen:
        return subprocess.Popen(
            ["bash", str(script)],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def test_stop_terminates_escalates_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = self._backend(root)
            runtime_dir = backend.runtime_dir("J-stop")
            runtime_dir.mkdir(parents=True)

            # Script names carry the trio markers so pid_identity_ok accepts
            # them (the command line shows "bash .../controller.py").
            polite = root / "controller.py"
            polite.write_text("sleep 60\n", encoding="utf-8")
            stubborn = root / "worker.py"
            stubborn.write_text('trap "" TERM\nwhile true; do sleep 1; done\n', encoding="utf-8")

            polite_proc = self._spawn(polite)
            stubborn_proc = self._spawn(stubborn)
            # An unrelated process holding the watcher pid must be skipped by
            # the identity check, never signalled.
            foreign_proc = subprocess.Popen(
                ["sleep", "60"],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            (runtime_dir / "controller.pid").write_text(f"{polite_proc.pid}\n", encoding="utf-8")
            (runtime_dir / "worker.pid").write_text(f"{stubborn_proc.pid}\n", encoding="utf-8")
            (runtime_dir / "watcher.pid").write_text(f"{foreign_proc.pid}\n", encoding="utf-8")

            try:
                started = time.monotonic()
                results = backend.stop_processes("J-stop")
                elapsed = time.monotonic() - started

                self.assertEqual(results["controller"], f"stopped pid={polite_proc.pid}")
                self.assertIn(f"stopped pid={stubborn_proc.pid}", results["worker"])
                self.assertIn("escalated to SIGKILL", results["worker"])
                self.assertEqual(results["watcher"], f"pid reused, skipped pid={foreign_proc.pid}")
                # The SIGTERM-resistant group forced the full grace period.
                self.assertGreaterEqual(elapsed, 4.5)

                # Both trio groups are gone; the foreign process survived.
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline and (
                    backend.group_alive(polite_proc.pid) or backend.group_alive(stubborn_proc.pid)
                ):
                    time.sleep(0.1)
                self.assertFalse(backend.group_alive(polite_proc.pid))
                self.assertFalse(backend.group_alive(stubborn_proc.pid))
                self.assertIsNone(foreign_proc.poll())
                # PID files are removed so a later resume cannot signal a
                # recycled PID.
                for name in ("controller", "worker", "watcher"):
                    self.assertFalse((runtime_dir / f"{name}.pid").exists())
            finally:
                for proc in (polite_proc, stubborn_proc, foreign_proc):
                    try:
                        os.killpg(proc.pid, 9)
                    except OSError:
                        pass
                    proc.wait()

    def test_group_alive_tracks_dummy_session_leader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = self._backend(root)
            script = root / "watcher.py"
            script.write_text("sleep 60\n", encoding="utf-8")
            proc = self._spawn(script)
            try:
                self.assertTrue(backend.group_alive(proc.pid))
            finally:
                os.killpg(proc.pid, 9)
                proc.wait()
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and backend.group_alive(proc.pid):
                time.sleep(0.05)
            self.assertFalse(backend.group_alive(proc.pid))


if __name__ == "__main__":
    unittest.main()
