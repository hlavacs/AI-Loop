from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ai_loop import db
from ai_loop.auth import (
    authenticate_provider,
    auth_failure_decision,
    find_auth_requirement,
    is_auth_failure,
    provider_for_role,
)
from ai_loop.config import load_settings, normalize_worker
from ai_loop.email_commands import EmailCommand, apply_email_command, is_job_reply, reply_command
from ai_loop.planning import (
    build_static_plan,
    granularity_constraints,
    normalize_granularity,
    replace_granularity_constraints,
)
from ai_loop.notifications import (
    check_mail_access,
    job_started_email,
    job_thread_message_id,
    status_email,
    terminal_email,
)
from ai_loop.progress import estimate_progress
from ai_loop.status_updates import maybe_send_status_email
from ai_loop.token_wait import is_token_limit, replenishment_time


class PlanningTests(unittest.TestCase):
    def test_static_plan_is_enumerable_and_goal_specific(self) -> None:
        plan = build_static_plan("Add a visible Clear Goal button", ["Tests pass"], "pytest -q")
        self.assertEqual(len(plan), 4)
        self.assertIn("Clear Goal", plan[1])
        self.assertIn("pytest -q", plan[2])

    def test_granularity_is_explicit_and_quality_preserving(self) -> None:
        self.assertEqual(normalize_granularity(" Coarse "), "coarse")
        self.assertIn("test coverage", " ".join(granularity_constraints("coarse")))
        with self.assertRaises(ValueError):
            normalize_granularity("huge")

    def test_changing_granularity_removes_the_old_policy(self) -> None:
        fine = [*granularity_constraints("fine"), "Keep public APIs stable."]
        coarse = replace_granularity_constraints(fine, "coarse")
        self.assertNotIn(granularity_constraints("fine")[0], coarse)
        self.assertIn(granularity_constraints("coarse")[0], coarse)
        self.assertIn("Keep public APIs stable.", coarse)


class RoleSelectionTests(unittest.TestCase):
    def test_claude_is_a_first_class_worker_binary(self) -> None:
        self.assertEqual(normalize_worker("Claude"), "claude")

    def test_controller_and_worker_models_are_independent(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AI_LOOP_CONTROLLER_ROLE_MODEL": "controller-model",
                "AI_LOOP_WORKER_ROLE_MODEL": "worker-model",
            },
        ):
            settings = load_settings()
        self.assertEqual(settings.controller_role_model, "controller-model")
        self.assertEqual(settings.worker_role_model, "worker-model")


class TokenWaitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc)

    def test_iso_reset_adds_one_minute(self) -> None:
        target = replenishment_time(
            "usage limit reached; available 2026-07-26T11:30:00Z",
            now=self.now,
        )
        self.assertEqual(target, datetime(2026, 7, 26, 11, 31, tzinfo=timezone.utc))

    def test_relative_reset_adds_one_minute(self) -> None:
        target = replenishment_time("quota exhausted; try again in 2 hours 5 minutes", now=self.now)
        self.assertEqual(target, self.now + timedelta(hours=2, minutes=6))

    def test_non_limit_is_not_treated_as_wait(self) -> None:
        self.assertFalse(is_token_limit("ordinary compiler error"))
        self.assertIsNone(replenishment_time("ordinary compiler error", now=self.now))


class AuthenticationRecoveryTests(unittest.TestCase):
    def test_claude_auth_failure_is_classified(self) -> None:
        output = "Failed to authenticate: OAuth session expired and could not be refreshed"
        self.assertTrue(is_auth_failure(output))
        self.assertEqual(provider_for_role("opus"), "claude")
        decision = auth_failure_decision("claude", output)
        self.assertEqual(decision["error_code"], "provider_auth_required")
        self.assertEqual(decision["provider"], "claude")

    def test_existing_unstructured_decision_is_recognized(self) -> None:
        details = {
            "job": {"status": "human_needed", "controller": "opus", "worker": "codex"},
            "decisions": [
                {
                    "reason": "Claude CLI failed: OAuth session expired and could not be refreshed",
                    "decision_json": "{}",
                }
            ],
            "runs": [],
            "events": [],
        }
        requirement = find_auth_requirement(details)
        self.assertIsNotNone(requirement)
        assert requirement is not None
        self.assertEqual(requirement.provider, "claude")
        self.assertEqual(requirement.role, "controller")

    def test_authentication_logs_in_verifies_and_reports_success(self) -> None:
        responses = iter(
            [
                subprocess.CompletedProcess(["claude", "auth", "status"], 1, "logged out", ""),
                subprocess.CompletedProcess(["claude", "auth", "login"], 0, "login complete", ""),
                subprocess.CompletedProcess(["claude", "auth", "status"], 0, "logged in", ""),
            ]
        )
        commands: list[list[str]] = []

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return next(responses)

        result = authenticate_provider("claude", "claude", runner=runner)
        self.assertFalse(result.already_authenticated)
        self.assertEqual(
            commands,
            [
                ["claude", "auth", "status"],
                ["claude", "auth", "login"],
                ["claude", "auth", "status"],
            ],
        )

    def test_authentication_skips_login_when_status_is_healthy(self) -> None:
        commands: list[list[str]] = []

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "logged in", "")

        result = authenticate_provider("claude", "claude", runner=runner)
        self.assertTrue(result.already_authenticated)
        self.assertEqual(commands, [["claude", "auth", "status"]])

    def test_failed_verification_does_not_report_success(self) -> None:
        responses = iter(
            [
                subprocess.CompletedProcess(["claude", "auth", "status"], 1, "", ""),
                subprocess.CompletedProcess(["claude", "auth", "login"], 0, "", ""),
                subprocess.CompletedProcess(["claude", "auth", "status"], 1, "logged out", ""),
            ]
        )

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return next(responses)

        with self.assertRaisesRegex(RuntimeError, "could not be verified"):
            authenticate_provider("claude", "claude", runner=runner)

class PersistenceAndEstimateTests(unittest.TestCase):
    def test_job_plan_granularity_and_controller_estimate_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loop.sqlite3"
            db.init_db(path)
            with db.transaction(path) as conn:
                db.create_job(
                    conn,
                    job_id="J-test",
                    repo_path=directory,
                    worktree_path=directory,
                    branch=None,
                    base_ref="HEAD",
                    goal="Test goal",
                    constraints=[],
                    acceptance=["Pass"],
                    test_cmd="true",
                    max_iterations=10,
                    use_worktree=False,
                    granularity="coarse",
                    plan=["Inspect", "Implement", "Verify"],
                )
                job = db.get_job(conn, "J-test")
                self.assertEqual(job["granularity"], "coarse")
                self.assertEqual(job["plan"], ["Inspect", "Implement", "Verify"])
                db.update_job_estimate(
                    conn,
                    "J-test",
                    completed_units=3,
                    remaining_units=1,
                    remaining_seconds=600,
                )
                percent, remaining = estimate_progress(
                    conn,
                    job_id="J-test",
                    status="implementing",
                    created_at=job["created_at"],
                    run_count=3,
                    task_count=4,
                    has_active_task=True,
                )
                self.assertEqual(percent, 75)
                self.assertEqual(remaining, 600)

    def test_progress_reloads_from_durable_activity_after_gui_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loop.sqlite3"
            db.init_db(path)
            with db.transaction(path) as conn:
                db.create_job(
                    conn,
                    job_id="J-restart",
                    repo_path=directory,
                    worktree_path=directory,
                    branch=None,
                    base_ref="HEAD",
                    goal="Test restart progress",
                    constraints=[],
                    acceptance=["Pass"],
                    test_cmd="true",
                    max_iterations=10,
                    use_worktree=False,
                )
                db.update_job_estimate(
                    conn,
                    "J-restart",
                    completed_units=0,
                    remaining_units=6,
                    remaining_seconds=12600,
                )

            for _restart in range(2):
                with db.transaction(path) as conn:
                    percent, remaining = estimate_progress(
                        conn,
                        job_id="J-restart",
                        status="fixing",
                        created_at=db.get_job(conn, "J-restart")["created_at"],
                        run_count=1,
                        task_count=2,
                        has_active_task=True,
                    )
                    self.assertEqual(percent, 6)
                    self.assertIsNotNone(remaining)

    def test_create_job_without_email_token_auto_generates_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loop.sqlite3"
            db.init_db(path)
            with db.transaction(path) as conn:
                db.create_job(
                    conn,
                    job_id="J-auto-token",
                    repo_path=directory,
                    worktree_path=directory,
                    branch=None,
                    base_ref="HEAD",
                    goal="Test token auto-generation",
                    constraints=[],
                    acceptance=[],
                    test_cmd="true",
                    max_iterations=10,
                    use_worktree=False,
                )
                job = db.get_job(conn, "J-auto-token")
            self.assertIsInstance(job["email_token"], str)
            self.assertGreater(len(job["email_token"]), 0)

    def test_decision_schema_requires_progress(self) -> None:
        schema = json.loads(Path("decision.schema.json").read_text(encoding="utf-8"))
        self.assertIn("progress", schema["required"])


class NotificationTests(unittest.TestCase):
    @patch("ai_loop.notifications.smtplib.SMTP")
    def test_job_start_email_opens_a_replyable_job_thread(self, smtp_class: MagicMock) -> None:
        smtp = smtp_class.return_value.__enter__.return_value
        settings = SimpleNamespace(
            notify_email="recipient@example.invalid",
            smtp_from="loop@example.invalid",
            smtp_user="loop-user",
            smtp_password="secret",
            smtp_host="smtp.example.invalid",
            smtp_port=587,
            smtp_starttls=True,
            smtp_ssl=False,
        )
        sent, _detail = job_started_email(
            settings,
            job={
                "id": "J-start",
                "repo_path": "/repo",
                "worktree_path": "/work",
                "goal": "Ship it",
                "controller": "opus",
                "worker": "codex",
                "email_token": "tok-start-1",
            },
        )
        self.assertTrue(sent)
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["Message-ID"], job_thread_message_id(settings, "J-start"))
        self.assertIn("Reply to this email", message.get_content())
        self.assertIn("Command token: tok-start-1", message.get_content())

    @patch("ai_loop.notifications.smtplib.SMTP")
    def test_done_email_uses_configured_recipient(self, smtp_class: MagicMock) -> None:
        smtp = smtp_class.return_value.__enter__.return_value
        settings = SimpleNamespace(
            notify_email="recipient@example.invalid",
            smtp_from="loop@example.invalid",
            smtp_user="loop-user",
            smtp_password="secret",
            smtp_host="smtp.example.invalid",
            smtp_port=587,
            smtp_starttls=True,
            smtp_ssl=False,
        )
        sent, _detail = terminal_email(
            settings,
            job={"id": "J1", "repo_path": "/repo", "worktree_path": "/work", "goal": "Ship it"},
            status="done",
            reason="ready",
        )
        self.assertTrue(sent)
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["To"], "recipient@example.invalid")
        self.assertEqual(message["Subject"], "AI-Loop job J1: done")
        self.assertIn("Status: done", message.get_content())
        smtp.starttls.assert_called_once_with()

    @patch("ai_loop.notifications.smtplib.SMTP")
    def test_status_email_contains_current_progress(self, smtp_class: MagicMock) -> None:
        smtp = smtp_class.return_value.__enter__.return_value
        settings = SimpleNamespace(
            notify_email="recipient@example.invalid",
            smtp_from="loop@example.invalid",
            smtp_user="loop-user",
            smtp_password="secret",
            smtp_host="smtp.example.invalid",
            smtp_port=587,
            smtp_starttls=True,
            smtp_ssl=False,
        )
        sent, _detail = status_email(
            settings,
            job={
                "id": "J1",
                "status": "implementing",
                "controller": "claude",
                "worker": "codex",
                "repo_path": "/repo",
                "worktree_path": "/work",
                "history_summary": "Core implementation is in progress.",
                "goal": "Ship it",
                "email_token": "tok-status-1",
            },
            percent=42,
            task_count=4,
            run_count=3,
            current_task="Add integration tests",
            remaining_seconds=5400,
        )
        self.assertTrue(sent)
        message = smtp.send_message.call_args.args[0]
        self.assertIn("42%", message["Subject"])
        self.assertIn("Current task: Add integration tests", message.get_content())
        self.assertIn("Command token: tok-status-1", message.get_content())

    @patch("ai_loop.notifications.smtplib.SMTP")
    def test_empty_password_disables_email_without_connecting(self, smtp_class: MagicMock) -> None:
        settings = SimpleNamespace(
            notify_email="recipient@example.invalid",
            smtp_from="loop@example.invalid",
            smtp_user="loop-user",
            smtp_password="",
            smtp_host="smtp.example.invalid",
            smtp_port=587,
            smtp_starttls=True,
            smtp_ssl=False,
        )
        sent, detail = terminal_email(
            settings,
            job={"id": "J1", "repo_path": "/repo", "worktree_path": "/work", "goal": "Ship it"},
            status="done",
            reason="ready",
        )
        self.assertFalse(sent)
        self.assertIn("disabled", detail)
        smtp_class.assert_not_called()

    @patch("ai_loop.notifications.imaplib.IMAP4_SSL")
    @patch("ai_loop.notifications.smtplib.SMTP_SSL")
    def test_startup_check_verifies_smtp_and_mailbox_access(
        self,
        smtp_class: MagicMock,
        imap_class: MagicMock,
    ) -> None:
        smtp = smtp_class.return_value.__enter__.return_value
        mailbox = imap_class.return_value.__enter__.return_value
        mailbox.select.return_value = ("OK", [b"1"])
        settings = SimpleNamespace(
            notify_email="recipient@example.invalid",
            smtp_host="smtp.example.invalid",
            smtp_port=465,
            smtp_user="loop-user",
            smtp_password="secret",
            smtp_starttls=False,
            smtp_ssl=True,
            imap_host="imap.example.invalid",
            imap_port=993,
            imap_user="loop-user",
            imap_password="secret",
            imap_mailbox="INBOX",
            imap_ssl=True,
            imap_starttls=False,
        )
        status = check_mail_access(settings)
        self.assertTrue(status.enabled)
        self.assertTrue(status.ok)
        self.assertIn("SMTP account accessible", status.smtp_detail)
        self.assertIn("IMAP mailbox accessible", status.mailbox_detail)
        smtp.login.assert_called_once_with("loop-user", "secret")
        smtp.noop.assert_called_once_with()
        mailbox.login.assert_called_once_with("loop-user", "secret")
        mailbox.select.assert_called_once_with("INBOX", readonly=True)

    @patch("ai_loop.notifications.smtplib.SMTP")
    def test_startup_check_skips_when_server_is_missing(self, smtp_class: MagicMock) -> None:
        settings = SimpleNamespace(smtp_host="", smtp_password="")
        status = check_mail_access(settings)
        self.assertFalse(status.enabled)
        self.assertTrue(status.ok)
        self.assertIn("startup check skipped", status.detail)
        smtp_class.assert_not_called()

    @patch("ai_loop.notifications.smtplib.SMTP")
    def test_startup_check_skips_when_password_is_empty(self, smtp_class: MagicMock) -> None:
        settings = SimpleNamespace(smtp_host="smtp.example.invalid", smtp_password="")
        status = check_mail_access(settings)
        self.assertFalse(status.enabled)
        self.assertTrue(status.ok)
        self.assertIn("AI_LOOP_SMTP_PASSWORD is empty", status.detail)
        smtp_class.assert_not_called()

    @patch("ai_loop.notifications.smtplib.SMTP")
    def test_startup_check_reports_account_access_error(self, smtp_class: MagicMock) -> None:
        smtp = smtp_class.return_value.__enter__.return_value
        smtp.login.side_effect = OSError("authentication rejected")
        settings = SimpleNamespace(
            notify_email="recipient@example.invalid",
            smtp_host="smtp.example.invalid",
            smtp_port=587,
            smtp_user="loop-user",
            smtp_password="wrong",
            smtp_starttls=True,
            smtp_ssl=False,
        )
        status = check_mail_access(settings)
        self.assertTrue(status.enabled)
        self.assertFalse(status.ok)
        self.assertIn("SMTP account access failed", status.detail)


class EmailCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = SimpleNamespace(
            notify_email="recipient@example.invalid",
            smtp_from="loop@example.invalid",
            smtp_user="",
        )

    def test_extracts_new_text_and_ignores_quoted_notification(self) -> None:
        message = EmailMessage()
        message.set_content(
            "Command: Try the alternate renderer and rerun the visual test.\n\n"
            "On Thu, AI-Loop wrote:\n"
            "> Job: J1\n"
            "> Status: human_needed\n"
        )
        self.assertEqual(
            reply_command(message),
            "Try the alternate renderer and rerun the visual test.",
        )

    def test_accepts_only_the_configured_user_and_matching_job_thread(self) -> None:
        message = EmailMessage()
        message["From"] = "User <recipient@example.invalid>"
        message["In-Reply-To"] = job_thread_message_id(self.settings, "J1")
        message["Subject"] = "Re: AI-Loop job J1"
        message.set_content("Continue with option B.")
        self.assertTrue(is_job_reply(self.settings, message, "J1"))
        self.assertFalse(is_job_reply(self.settings, message, "J2"))
        message.replace_header("From", "attacker@example.invalid")
        self.assertFalse(is_job_reply(self.settings, message, "J1"))

    def test_outbound_notification_cannot_be_treated_as_a_command(self) -> None:
        message = EmailMessage()
        message["From"] = "recipient@example.invalid"
        message["Subject"] = "AI-Loop job J1: human_needed"
        message["In-Reply-To"] = job_thread_message_id(self.settings, "J1")
        message["X-AI-Loop-Notification"] = "J1"
        message.set_content("Reply to this email with a command.")
        self.assertFalse(is_job_reply(self.settings, message, "J1"))

    def test_active_job_stores_emailed_command_for_future_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loop.sqlite3"
            db.init_db(path)
            with db.transaction(path) as conn:
                db.create_job(
                    conn,
                    job_id="J-command",
                    repo_path=directory,
                    worktree_path=directory,
                    branch=None,
                    base_ref="HEAD",
                    goal="Test commands",
                    constraints=[],
                    acceptance=[],
                    test_cmd="true",
                    max_iterations=10,
                    use_worktree=False,
                )
                # This test exercises command storage, not token auth: strip the
                # auto-generated token so the tokenless command is accepted.
                conn.execute("UPDATE jobs SET email_token = NULL WHERE id = ?", ("J-command",))
            settings = SimpleNamespace(db_path=path, root_dir=Path(directory))
            resumed = apply_email_command(
                settings,
                "J-command",
                EmailCommand("<reply-1>", "recipient@example.invalid", "Use option B.", "Re: J-command"),
            )
            self.assertFalse(resumed)
            with db.transaction(path) as conn:
                job = db.get_job(conn, "J-command")
                kinds = [
                    row["kind"]
                    for row in conn.execute(
                        "SELECT kind FROM events WHERE job_id = ? ORDER BY id",
                        ("J-command",),
                    )
                ]
            self.assertIn("New command received by email: Use option B.", job["constraints"])
            self.assertEqual(kinds, ["email_command_received", "email_command_applied"])

    def test_reply_with_correct_token_is_accepted_and_token_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loop.sqlite3"
            db.init_db(path)
            with db.transaction(path) as conn:
                db.create_job(
                    conn,
                    job_id="J-token",
                    repo_path=directory,
                    worktree_path=directory,
                    branch=None,
                    base_ref="HEAD",
                    goal="Test token acceptance",
                    constraints=[],
                    acceptance=[],
                    test_cmd="true",
                    max_iterations=10,
                    use_worktree=False,
                    email_token="tok-secret-9",
                )
            settings = SimpleNamespace(db_path=path, root_dir=Path(directory))
            resumed = apply_email_command(
                settings,
                "J-token",
                EmailCommand(
                    "<reply-token-1>",
                    "recipient@example.invalid",
                    "Command token: tok-secret-9\nUse option B.",
                    "Re: J-token",
                ),
            )
            self.assertFalse(resumed)
            with db.transaction(path) as conn:
                job = db.get_job(conn, "J-token")
                kinds = [
                    row["kind"]
                    for row in conn.execute(
                        "SELECT kind FROM events WHERE job_id = ? ORDER BY id",
                        ("J-token",),
                    )
                ]
            self.assertIn("New command received by email: Use option B.", job["constraints"])
            self.assertNotIn("tok-secret-9", json.dumps(job["constraints"]))
            self.assertEqual(kinds, ["email_command_received", "email_command_applied"])

    def test_reply_without_token_is_rejected_when_job_has_a_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loop.sqlite3"
            db.init_db(path)
            with db.transaction(path) as conn:
                db.create_job(
                    conn,
                    job_id="J-reject",
                    repo_path=directory,
                    worktree_path=directory,
                    branch=None,
                    base_ref="HEAD",
                    goal="Test token rejection",
                    constraints=[],
                    acceptance=[],
                    test_cmd="true",
                    max_iterations=10,
                    use_worktree=False,
                    email_token="tok-secret-9",
                )
            settings = SimpleNamespace(db_path=path, root_dir=Path(directory))
            resumed = apply_email_command(
                settings,
                "J-reject",
                EmailCommand("<reply-token-2>", "recipient@example.invalid", "Use option B.", "Re: J-reject"),
            )
            self.assertFalse(resumed)
            with db.transaction(path) as conn:
                job = db.get_job(conn, "J-reject")
                events = conn.execute(
                    "SELECT kind, payload_json FROM events WHERE job_id = ? ORDER BY id",
                    ("J-reject",),
                ).fetchall()
            self.assertEqual(job["constraints"], [])
            self.assertEqual([row["kind"] for row in events], ["email_command_rejected"])
            payload = json.loads(events[0]["payload_json"])
            self.assertEqual(payload["message_id"], "<reply-token-2>")
            self.assertIn("command token", payload["reason"])

    def test_legacy_job_without_token_still_accepts_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loop.sqlite3"
            db.init_db(path)
            with db.transaction(path) as conn:
                db.create_job(
                    conn,
                    job_id="J-legacy",
                    repo_path=directory,
                    worktree_path=directory,
                    branch=None,
                    base_ref="HEAD",
                    goal="Test legacy acceptance",
                    constraints=[],
                    acceptance=[],
                    test_cmd="true",
                    max_iterations=10,
                    use_worktree=False,
                )
                # Simulate a legacy row created before token support:
                # create_job now always auto-generates a token, so remove it.
                conn.execute("UPDATE jobs SET email_token = NULL WHERE id = ?", ("J-legacy",))
            settings = SimpleNamespace(db_path=path, root_dir=Path(directory))
            resumed = apply_email_command(
                settings,
                "J-legacy",
                EmailCommand("<reply-token-3>", "recipient@example.invalid", "Use option B.", "Re: J-legacy"),
            )
            self.assertFalse(resumed)
            with db.transaction(path) as conn:
                job = db.get_job(conn, "J-legacy")
                kinds = [
                    row["kind"]
                    for row in conn.execute(
                        "SELECT kind FROM events WHERE job_id = ? ORDER BY id",
                        ("J-legacy",),
                    )
                ]
            self.assertIn("New command received by email: Use option B.", job["constraints"])
            self.assertEqual(kinds, ["email_command_received", "email_command_applied"])

    @patch("ai_loop.email_commands.subprocess.run")
    def test_human_blocked_job_is_resumed_with_emailed_command(self, run: MagicMock) -> None:
        run.return_value = subprocess.CompletedProcess(["resume"], 0, "resumed", "")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "loop.sqlite3"
            db.init_db(path)
            with db.transaction(path) as conn:
                db.create_job(
                    conn,
                    job_id="J-blocked",
                    repo_path=directory,
                    worktree_path=directory,
                    branch=None,
                    base_ref="HEAD",
                    goal="Test resume",
                    constraints=[],
                    acceptance=[],
                    test_cmd="true",
                    max_iterations=10,
                    use_worktree=False,
                )
                db.update_job_status(conn, "J-blocked", "human_needed", "Choose a rendering path.")
                # This test exercises resume-on-command, not token auth: strip
                # the auto-generated token so the tokenless command is accepted.
                conn.execute("UPDATE jobs SET email_token = NULL WHERE id = ?", ("J-blocked",))
            resumed = apply_email_command(
                SimpleNamespace(db_path=path, root_dir=root),
                "J-blocked",
                EmailCommand("<reply-2>", "recipient@example.invalid", "Use option B.", "Re: J-blocked"),
            )
        self.assertTrue(resumed)
        command = run.call_args.args[0]
        self.assertEqual(command[2], "J-blocked")
        self.assertEqual(command[-1], "New command received by email: Use option B.")


class PeriodicStatusEmailTests(unittest.TestCase):
    def test_active_job_gets_one_email_after_twelve_hours(self) -> None:
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loop.sqlite3"
            db.init_db(path)
            with db.transaction(path) as conn:
                db.create_job(
                    conn,
                    job_id="J-email",
                    repo_path="/repo",
                    worktree_path="/work",
                    branch=None,
                    base_ref="HEAD",
                    goal="Long job",
                    constraints=[],
                    acceptance=[],
                    test_cmd="true",
                    max_iterations=10,
                    use_worktree=False,
                )
                conn.execute(
                    "UPDATE jobs SET created_at = ? WHERE id = ?",
                    ((now - timedelta(hours=13)).isoformat(timespec="seconds"), "J-email"),
                )

            settings = SimpleNamespace(
                db_path=path,
                notify_email="recipient@example.invalid",
            )
            with patch("ai_loop.status_updates.status_email", return_value=(True, "sent")) as send:
                self.assertTrue(maybe_send_status_email(settings, "J-email", now=now))
                self.assertFalse(maybe_send_status_email(settings, "J-email", now=now))
            send.assert_called_once()

            with db.transaction(path) as conn:
                event = conn.execute(
                    "SELECT kind FROM events WHERE job_id = ? ORDER BY id DESC LIMIT 1",
                    ("J-email",),
                ).fetchone()
            self.assertEqual(event["kind"], "email_status_sent")

            with db.transaction(path) as conn:
                db.update_job_status(conn, "J-email", "done")
            with patch("ai_loop.status_updates.status_email") as terminal_send:
                self.assertFalse(
                    maybe_send_status_email(
                        settings,
                        "J-email",
                        now=now + timedelta(hours=13),
                    )
                )
            terminal_send.assert_not_called()

    def test_disabled_mail_records_status_attempt_as_skipped(self) -> None:
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loop.sqlite3"
            db.init_db(path)
            with db.transaction(path) as conn:
                db.create_job(
                    conn,
                    job_id="J-no-mail",
                    repo_path="/repo",
                    worktree_path="/work",
                    branch=None,
                    base_ref="HEAD",
                    goal="Long job without mail",
                    constraints=[],
                    acceptance=[],
                    test_cmd="true",
                    max_iterations=10,
                    use_worktree=False,
                )
                conn.execute(
                    "UPDATE jobs SET created_at = ? WHERE id = ?",
                    ((now - timedelta(hours=13)).isoformat(timespec="seconds"), "J-no-mail"),
                )
            settings = SimpleNamespace(
                db_path=path,
                notify_email="",
                smtp_host="",
                smtp_password="",
                smtp_from="",
                smtp_user="",
                smtp_port=587,
                smtp_starttls=True,
                smtp_ssl=False,
            )
            self.assertTrue(maybe_send_status_email(settings, "J-no-mail", now=now))
            self.assertFalse(maybe_send_status_email(settings, "J-no-mail", now=now))
            with db.transaction(path) as conn:
                event = conn.execute(
                    "SELECT kind FROM events WHERE job_id = ? ORDER BY id DESC LIMIT 1",
                    ("J-no-mail",),
                ).fetchone()
            self.assertEqual(event["kind"], "email_status_skipped")


if __name__ == "__main__":
    unittest.main()
