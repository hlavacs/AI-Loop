from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ai_loop import db
from ai_loop.planning import (
    build_static_plan,
    granularity_constraints,
    normalize_granularity,
    replace_granularity_constraints,
)
from ai_loop.notifications import terminal_email
from ai_loop.progress import estimate_progress
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

    def test_decision_schema_requires_progress(self) -> None:
        schema = json.loads(Path("decision.schema.json").read_text(encoding="utf-8"))
        self.assertIn("progress", schema["required"])


class NotificationTests(unittest.TestCase):
    @patch("ai_loop.notifications.smtplib.SMTP")
    def test_ready_email_uses_configured_recipient(self, smtp_class: MagicMock) -> None:
        smtp = smtp_class.return_value.__enter__.return_value
        settings = SimpleNamespace(
            notify_email="helmut.hlavacs@univie.ac.at",
            smtp_from="loop@example.invalid",
            smtp_user="",
            smtp_password="",
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
        self.assertEqual(message["To"], "helmut.hlavacs@univie.ac.at")
        smtp.starttls.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
