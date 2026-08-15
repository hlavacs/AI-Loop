from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import resume_job

try:  # ai_loop_gui needs tkinter, which some test environments lack
    import ai_loop_gui
except Exception:  # pragma: no cover - environment-dependent
    ai_loop_gui = None

from ai_loop import db
from ai_loop.email_commands import EmailCommand, apply_email_command, reply_command
from ai_loop.queues import claim_pending


def make_job(path: Path, job_id: str, directory: str, token: str | None) -> None:
    db.init_db(path)
    with db.transaction(path) as conn:
        db.create_job(
            conn,
            job_id=job_id,
            repo_path=directory,
            worktree_path=directory,
            branch=None,
            base_ref="HEAD",
            goal="Follow-up fix tests",
            constraints=[],
            acceptance=[],
            test_cmd="true",
            max_iterations=10,
            use_worktree=False,
            email_token=token,
        )


def event_rows(path: Path, job_id: str) -> list[tuple[str, dict]]:
    with db.transaction(path) as conn:
        rows = conn.execute(
            "SELECT kind, payload_json FROM events WHERE job_id = ? ORDER BY id",
            (job_id,),
        ).fetchall()
    return [(row["kind"], json.loads(row["payload_json"])) for row in rows]


class OutlookQuoteStrippingTests(unittest.TestCase):
    def test_underscore_separator_stops_extraction(self) -> None:
        message = EmailMessage()
        message.set_content(
            "Use option B.\n"
            "________________________________\n"
            "From: AI-Loop <loop@example.invalid>\n"
            "Sent: Thursday\n"
            "Command token: tok-secret-9\n"
            "Job: J1\n"
        )
        self.assertEqual(reply_command(message), "Use option B.")

    def test_five_underscores_is_enough_and_trailing_spaces_are_allowed(self) -> None:
        message = EmailMessage()
        message.set_content(
            "Retry the flaky test.\n"
            "_____   \n"
            "Command token: tok-secret-9\n"
        )
        self.assertEqual(reply_command(message), "Retry the flaky test.")

    def test_short_underscore_run_is_kept_as_reply_text(self) -> None:
        message = EmailMessage()
        message.set_content("Rename the field to __x__.\n____\nstill part of the reply\n")
        self.assertIn("still part of the reply", reply_command(message))

    def test_original_message_separator_still_stops_extraction(self) -> None:
        message = EmailMessage()
        message.set_content(
            "Use option C.\n"
            "-----Original Message-----\n"
            "Command token: tok-secret-9\n"
        )
        self.assertEqual(reply_command(message), "Use option C.")


class TokenBeforeTruncationTests(unittest.TestCase):
    def test_long_reply_with_token_at_the_end_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loop.sqlite3"
            make_job(path, "J-long", directory, "tok-secret-9")
            long_body = "x" * 25000
            settings = SimpleNamespace(db_path=path, root_dir=Path(directory))
            resumed = apply_email_command(
                settings,
                "J-long",
                EmailCommand(
                    "<reply-long-1>",
                    "recipient@example.invalid",
                    f"{long_body}\nCommand token: tok-secret-9",
                    "Re: J-long",
                ),
            )
            self.assertFalse(resumed)
            events = event_rows(path, "J-long")
            kinds = [kind for kind, _ in events]
            self.assertEqual(kinds, ["email_command_received", "email_command_applied"])
            with db.transaction(path) as conn:
                job = db.get_job(conn, "J-long")
            self.assertEqual(len(job["constraints"]), 1)
            stored = job["constraints"][0]
            self.assertTrue(stored.startswith("New command received by email: xxx"))
            self.assertNotIn("tok-secret-9", stored)
            # the stored command is still truncated for storage
            self.assertLessEqual(len(stored), len("New command received by email: ") + 20000)

    def test_stored_command_is_truncated_after_token_stripping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loop.sqlite3"
            make_job(path, "J-trunc", directory, "tok-secret-9")
            settings = SimpleNamespace(db_path=path, root_dir=Path(directory))
            apply_email_command(
                settings,
                "J-trunc",
                EmailCommand(
                    "<reply-long-2>",
                    "recipient@example.invalid",
                    "y" * 30000 + "\nCommand token: tok-secret-9",
                    "Re: J-trunc",
                ),
            )
            events = event_rows(path, "J-trunc")
            received = next(payload for kind, payload in events if kind == "email_command_received")
            self.assertEqual(len(received["command"]), 20000)


class TokenOnlyReplyTests(unittest.TestCase):
    def test_token_only_reply_is_rejected_and_not_applied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loop.sqlite3"
            make_job(path, "J-empty", directory, "tok-secret-9")
            settings = SimpleNamespace(db_path=path, root_dir=Path(directory))
            resumed = apply_email_command(
                settings,
                "J-empty",
                EmailCommand(
                    "<reply-empty-1>",
                    "recipient@example.invalid",
                    "Command token: tok-secret-9",
                    "Re: J-empty",
                ),
            )
            self.assertFalse(resumed)
            events = event_rows(path, "J-empty")
            self.assertEqual([kind for kind, _ in events], ["email_command_rejected"])
            payload = events[0][1]
            self.assertEqual(payload["message_id"], "<reply-empty-1>")
            self.assertIn("empty command after token removal", payload["reason"])
            with db.transaction(path) as conn:
                job = db.get_job(conn, "J-empty")
            self.assertEqual(job["constraints"], [])

    def test_whitespace_around_token_is_still_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loop.sqlite3"
            make_job(path, "J-empty2", directory, "tok-secret-9")
            settings = SimpleNamespace(db_path=path, root_dir=Path(directory))
            resumed = apply_email_command(
                settings,
                "J-empty2",
                EmailCommand(
                    "<reply-empty-2>",
                    "recipient@example.invalid",
                    "\n  Command token: tok-secret-9  \n\n",
                    "Re: J-empty2",
                ),
            )
            self.assertFalse(resumed)
            events = event_rows(path, "J-empty2")
            self.assertEqual([kind for kind, _ in events], ["email_command_rejected"])
            self.assertIn("empty command after token removal", events[0][1]["reason"])


class TerminatePidValidationTests(unittest.TestCase):
    def _runtime_dir(self, root: Path, job_id: str) -> Path:
        runtime_dir = root / "run" / "jobs" / job_id
        runtime_dir.mkdir(parents=True)
        return runtime_dir

    def test_invalid_self_and_garbage_pids_are_never_signalled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_dir = self._runtime_dir(root, "J-pids")
            (runtime_dir / "controller.pid").write_text("-1\n", encoding="utf-8")
            (runtime_dir / "worker.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
            (runtime_dir / "watcher.pid").write_text("garbage\n", encoding="utf-8")
            printed: list[str] = []
            with patch.object(resume_job, "_signal_process") as signal_mock, patch(
                "builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))
            ):
                resume_job.terminate_previous_job_processes(root, "J-pids")
            signal_mock.assert_not_called()
            output = "\n".join(printed)
            self.assertIn("skipped stale controller pid file (pid -1", output)
            self.assertIn("resume's own/parent process", output)
            # the termination pass removes the pid files so a later resume
            # cannot signal a recycled PID
            for name in ("controller", "worker", "watcher"):
                self.assertFalse((runtime_dir / f"{name}.pid").exists())

    def test_parent_pid_is_skipped_as_own_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_dir = self._runtime_dir(root, "J-parent")
            (runtime_dir / "watcher.pid").write_text(f"{os.getppid()}\n", encoding="utf-8")
            printed: list[str] = []
            with patch.object(resume_job, "_signal_process") as signal_mock, patch(
                "builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))
            ):
                resume_job.terminate_previous_job_processes(root, "J-parent")
            signal_mock.assert_not_called()
            self.assertIn("resume's own/parent process", "\n".join(printed))

    def test_pid_identity_check_accepts_python_and_rejects_reused_pid(self) -> None:
        self.assertTrue(resume_job._pid_identity_ok(os.getpid()))
        sleeper = subprocess.Popen(["sleep", "60"])
        try:
            self.assertFalse(resume_job._pid_identity_ok(sleeper.pid))
        finally:
            sleeper.kill()
            sleeper.wait()

    def test_reused_pid_is_skipped_by_terminate(self) -> None:
        sleeper = subprocess.Popen(["sleep", "60"])
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                runtime_dir = self._runtime_dir(root, "J-reuse")
                (runtime_dir / "worker.pid").write_text(f"{sleeper.pid}\n", encoding="utf-8")
                printed: list[str] = []
                with patch.object(resume_job, "_signal_process") as signal_mock, patch(
                    "builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))
                ):
                    resume_job.terminate_previous_job_processes(root, "J-reuse")
                signal_mock.assert_not_called()
                self.assertIn("PID reused by another process", "\n".join(printed))
            self.assertIsNone(sleeper.poll())
        finally:
            sleeper.kill()
            sleeper.wait()


class GroupAliveTests(unittest.TestCase):
    def test_dead_pid_is_not_alive_and_own_process_is(self) -> None:
        proc = subprocess.Popen(["sleep", "0.05"], start_new_session=True)
        proc.wait()
        self.assertFalse(resume_job._group_alive(proc.pid))
        # Under some launchers the test process is not its own group leader;
        # probe whichever of pid/pgid names our (definitely alive) group.
        own = os.getpid() if os.getpgid(0) == os.getpid() else os.getpgid(0)
        self.assertTrue(resume_job._group_alive(own))

    @unittest.skipUnless(hasattr(os, "killpg"), "os.killpg not available")
    def test_session_leader_group_alive_then_dead_after_killpg(self) -> None:
        try:
            proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
        except (AttributeError, OSError) as exc:
            self.skipTest(f"cannot spawn session leader: {exc}")
        try:
            self.assertTrue(resume_job._group_alive(proc.pid))
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except AttributeError:
                self.skipTest("os.killpg not available")
            proc.wait()
            self.assertFalse(resume_job._group_alive(proc.pid))
        finally:
            try:
                proc.kill()
            except OSError:
                pass
            proc.wait()


def _wait_for_process_state(pid: int, prefix: str, timeout: float = 5.0) -> bool:
    """Poll ps until the process state starts with ``prefix`` (e.g. \"Z\")."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "state="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if (result.stdout or "").strip().startswith(prefix):
            return True
        time.sleep(0.05)
    return False


def _wait_for_group_dead(pgid: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and resume_job._group_alive(pgid):
        time.sleep(0.05)


@unittest.skipUnless(hasattr(os, "killpg"), "os.killpg not available")
class GroupHasLiveMemberTests(unittest.TestCase):
    def test_live_session_leader_group_has_live_member(self) -> None:
        proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
        try:
            self.assertTrue(resume_job._group_has_live_member(proc.pid))
            self.assertTrue(resume_job._group_alive(proc.pid))
        finally:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        _wait_for_group_dead(proc.pid)
        self.assertFalse(resume_job._group_alive(proc.pid))

    def test_zombie_only_group_counts_as_dead(self) -> None:
        # Do NOT reap: without wait()/poll() the exited leader stays a zombie
        # and is the group's only member. killpg(pid, 0) still succeeds on it,
        # so only the group-wide member state check reports it as dead.
        # The assertFalse holds on both platforms through two different paths:
        # on Linux, pgrep lists the zombie (rc==0) and the ps state filter
        # sees only "Z" states; on macOS, pgrep does not list zombies at all,
        # so it exits with rc==1 ("no matches"), which is now trusted as "no
        # live members" instead of falling into the conservative True branch.
        proc = subprocess.Popen(["sleep", "0.05"], start_new_session=True)
        try:
            self.assertTrue(
                _wait_for_process_state(proc.pid, "Z"), "leader never became a zombie"
            )
            self.assertFalse(resume_job._group_has_live_member(proc.pid))
            self.assertFalse(resume_job._group_alive(proc.pid))
        finally:
            proc.wait()

    @unittest.skipUnless(shutil.which("bash"), "bash unavailable")
    def test_zombie_leader_with_live_child_keeps_group_alive(self) -> None:
        # V5-1 regression: the leader exits (and stays an unreaped zombie)
        # while a child it spawned into the same group keeps running. A
        # leader-only zombie check would wrongly report the group dead and
        # skip the SIGKILL escalation the surviving child needs.
        proc = subprocess.Popen(
            ["bash", "-c", "sleep 60 & disown; exit 0"], start_new_session=True
        )
        killed = False
        try:
            self.assertTrue(
                _wait_for_process_state(proc.pid, "Z"), "leader never became a zombie"
            )
            self.assertTrue(resume_job._group_has_live_member(proc.pid))
            self.assertTrue(resume_job._group_alive(proc.pid))
            os.killpg(proc.pid, signal.SIGKILL)
            killed = True
            proc.wait()
            _wait_for_group_dead(proc.pid)
            self.assertFalse(resume_job._group_alive(proc.pid))
        finally:
            if not killed:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                proc.wait()

    @unittest.skipUnless(shutil.which("bash"), "bash unavailable")
    def test_reaped_leader_with_live_child_keeps_group_alive(self) -> None:
        # Same shape but the leader is fully reaped: the pgid persists while
        # the child lives, so killpg(pid, 0) succeeds and the member scan must
        # find the live child.
        proc = subprocess.Popen(
            ["bash", "-c", "sleep 60 & disown; exit 0"], start_new_session=True
        )
        proc.wait()
        try:
            self.assertTrue(resume_job._group_has_live_member(proc.pid))
            self.assertTrue(resume_job._group_alive(proc.pid))
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        _wait_for_group_dead(proc.pid)
        self.assertFalse(resume_job._group_alive(proc.pid))


@unittest.skipUnless(ai_loop_gui is not None, "ai_loop_gui (tkinter) not importable")
class ExclusiveConflictTests(unittest.TestCase):
    """Pure-logic tests: _exclusive_conflict reads only _active_operations,
    so an __init__-less (no Tk) instance is enough."""

    def _gui(self, active: set[str]):
        gui = ai_loop_gui.AiLoopGui.__new__(ai_loop_gui.AiLoopGui)
        gui._active_operations = set(active)
        return gui

    def test_idle_gui_has_no_conflicts(self) -> None:
        gui = self._gui(set())
        self.assertIsNone(gui._exclusive_conflict("maintenance"))
        self.assertIsNone(gui._exclusive_conflict("job"))

    def test_job_operation_blocks_maintenance_but_not_other_jobs(self) -> None:
        gui = self._gui({"Create Job"})
        self.assertEqual(gui._exclusive_conflict("maintenance"), "Create Job")
        self.assertIsNone(gui._exclusive_conflict("job"))

    def test_maintenance_blocks_jobs_and_other_maintenance(self) -> None:
        gui = self._gui({"Full Reset"})
        self.assertEqual(gui._exclusive_conflict("job"), "Full Reset")
        self.assertEqual(gui._exclusive_conflict("maintenance"), "Full Reset")

    def test_harmless_operations_never_conflict(self) -> None:
        gui = self._gui({"Start Redis", "Hibernation change"})
        self.assertIsNone(gui._exclusive_conflict("maintenance"))
        self.assertIsNone(gui._exclusive_conflict("job"))

    def test_first_conflict_is_reported_deterministically(self) -> None:
        gui = self._gui({"Resume Job", "Fix It", "Start Redis"})
        self.assertEqual(gui._exclusive_conflict("maintenance"), "Fix It")
        self.assertIsNone(gui._exclusive_conflict("job"))

    def test_auth_recovery_blocks_maintenance_and_vice_versa(self) -> None:
        gui = self._gui({"Auth Recovery"})
        self.assertEqual(gui._exclusive_conflict("maintenance"), "Auth Recovery")
        self.assertIsNone(gui._exclusive_conflict("job"))
        gui = self._gui({"Full Reset"})
        self.assertEqual(gui._exclusive_conflict("Auth Recovery"), "Full Reset")


class ClaimPendingTombstoneTests(unittest.TestCase):
    def test_xack_failure_on_tombstone_keeps_real_claimed_messages(self) -> None:
        from redis.exceptions import ConnectionError as RedisConnectionError

        class FakeClient:
            def __init__(self) -> None:
                self.xack_calls: list[tuple] = []

            def xautoclaim(self, stream, group, consumer, min_idle_time, start_id):
                return ("0-0", [("1-1", None), ("2-2", {"task": "real"})], [])

            def xack(self, stream, group, message_id):
                self.xack_calls.append((stream, group, message_id))
                raise RedisConnectionError("redis went away during tombstone ack")

        client = FakeClient()
        claimed = claim_pending(client, "stream", "group", "consumer")
        self.assertEqual(claimed, [("2-2", {"task": "real"})])
        self.assertEqual(client.xack_calls, [("stream", "group", "1-1")])


if __name__ == "__main__":
    unittest.main()
