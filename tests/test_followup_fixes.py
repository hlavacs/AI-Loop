from __future__ import annotations

import json
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace

from ai_loop import db
from ai_loop.email_commands import EmailCommand, apply_email_command, reply_command


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


if __name__ == "__main__":
    unittest.main()
