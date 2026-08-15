"""Read job-specific commands from replies to AI-Loop notification emails."""

from __future__ import annotations

import email
import imaplib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from email.message import Message
from email.policy import default
from email.utils import parseaddr
from typing import Any

from ai_loop import db
from ai_loop.notifications import job_thread_message_id, mail_enabled


@dataclass(frozen=True)
class EmailCommand:
    message_id: str
    sender: str
    command: str
    subject: str


def verify_command_token(command: str, email_token: str | None) -> str | None:
    """Check a reply against the job's secret token.

    Returns the command with the token (and any ``Command token:`` prefix)
    stripped when verification succeeds, or None when the job has a token and
    the reply does not contain it. Jobs without a token (legacy rows) accept
    every reply unchanged.
    """
    token = str(email_token or "").strip()
    if not token:
        return command.strip()
    if token not in command:
        return None
    cleaned = re.sub(rf"(?i:command\s+token\s*:?\s*)?{re.escape(token)}", "", command)
    cleaned = "\n".join(line.rstrip() for line in cleaned.splitlines()).strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def apply_email_command(settings: Any, job_id: str, incoming: EmailCommand) -> bool:
    """Apply a command; return True when a replacement watcher was launched."""
    command = incoming.command[:20000]
    with db.transaction(settings.db_path) as conn:
        job = db.get_job(conn, job_id)
        status = str(job["status"])
        verified = verify_command_token(command, job.get("email_token"))
        if verified is None:
            db.add_event(
                conn,
                job_id=job_id,
                kind="email_command_rejected",
                payload={
                    "message_id": incoming.message_id,
                    "sender": incoming.sender,
                    "subject": incoming.subject,
                    "status": status,
                    "reason": "reply does not contain the job's command token",
                },
            )
            print(f"job {job_id}: rejected emailed command without a valid command token")
            return False
        command = verified
        db.add_event(
            conn,
            job_id=job_id,
            kind="email_command_received",
            payload={
                "message_id": incoming.message_id,
                "sender": incoming.sender,
                "subject": incoming.subject,
                "command": command,
                "status": status,
            },
        )

        if status != "human_needed":
            constraints = [*job["constraints"], f"New command received by email: {command}"]
            conn.execute(
                "UPDATE jobs SET constraints_json = ?, updated_at = ? WHERE id = ?",
                (db.to_json(constraints), db.utc_now(), job_id),
            )
            db.add_event(
                conn,
                job_id=job_id,
                kind="email_command_applied",
                payload={
                    "message_id": incoming.message_id,
                    "command": command,
                    "resumed": False,
                    "status": status,
                },
            )
            print(f"job {job_id}: added emailed command to future task constraints")
            return False

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(settings.root_dir / "resume_job.py"),
                job_id,
                "--constraint",
                f"New command received by email: {command}",
            ],
            cwd=str(settings.root_dir),
            text=True,
            capture_output=True,
            timeout=180,
        )
        returncode = result.returncode
        output = result.stdout + result.stderr
    except Exception as exc:
        returncode = -1
        output = repr(exc)
    with db.transaction(settings.db_path) as conn:
        if returncode != 0:
            db.update_job_status(conn, job_id, "human_needed")
        db.add_event(
            conn,
            job_id=job_id,
            kind="email_command_applied" if returncode == 0 else "email_command_failed",
            payload={
                "message_id": incoming.message_id,
                "command": command,
                "resumed": returncode == 0,
                "returncode": returncode,
                "output": output[-4000:],
            },
        )
    if returncode != 0:
        print(f"job {job_id}: emailed command could not resume job: {output.strip()}")
        return False
    print(f"job {job_id}: resumed with emailed command")
    return True


def reply_command(message: Message) -> str:
    bodies: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() != "text/plain" or part.get_content_disposition() == "attachment":
                continue
            try:
                bodies.append(part.get_content())
            except (LookupError, UnicodeDecodeError):
                continue
    elif message.get_content_type() == "text/plain":
        try:
            bodies.append(message.get_content())
        except (LookupError, UnicodeDecodeError):
            pass

    text = "\n".join(bodies).replace("\r\n", "\n")
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        if re.match(r"^On .+wrote:\s*$", stripped, flags=re.IGNORECASE):
            break
        if re.match(r"^-{2,}\s*(Original Message|Forwarded message)\s*-{2,}$", stripped, flags=re.IGNORECASE):
            break
        lines.append(line.rstrip())

    command = "\n".join(lines).strip()
    command = re.sub(r"^(?:new\s+)?command\s*:\s*", "", command, count=1, flags=re.IGNORECASE)
    return command.strip()


def is_job_reply(settings: Any, message: Message, job_id: str) -> bool:
    if message.get("X-AI-Loop-Notification") is not None:
        return False
    expected_sender = settings.notify_email.strip().lower()
    sender = parseaddr(str(message.get("From", "")))[1].strip().lower()
    if not expected_sender or sender != expected_sender:
        return False

    thread_id = job_thread_message_id(settings, job_id).lower()
    references = " ".join(
        [
            str(message.get("In-Reply-To", "")),
            str(message.get("References", "")),
        ]
    ).lower()
    subject = str(message.get("Subject", ""))
    reply_subject = re.match(r"^\s*(?:re|aw|sv|fwd?)\s*:", subject, flags=re.IGNORECASE) is not None
    subject_matches = re.search(rf"(?<![\w-]){re.escape(job_id)}(?![\w-])", subject) is not None
    return thread_id in references or (reply_subject and subject_matches)


def processed_message_ids(conn: Any, job_id: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT payload_json
        FROM events
        WHERE job_id = ? AND kind IN ('email_command_received', 'email_command_applied', 'email_command_rejected')
        ORDER BY id DESC
        LIMIT 1000
        """,
        (job_id,),
    ).fetchall()
    result: set[str] = set()
    for row in rows:
        try:
            value = json.loads(row["payload_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        message_id = value.get("message_id")
        if isinstance(message_id, str):
            result.add(message_id)
    return result


def poll_job_commands(settings: Any, job_id: str, already_processed: set[str]) -> list[EmailCommand]:
    if not mail_enabled(settings) or not settings.imap_host or not settings.imap_user or not settings.imap_password or not settings.notify_email:
        return []

    imap_type = imaplib.IMAP4_SSL if settings.imap_ssl else imaplib.IMAP4
    with imap_type(settings.imap_host, settings.imap_port, timeout=30) as mailbox:
        if settings.imap_starttls and not settings.imap_ssl:
            mailbox.starttls()
        mailbox.login(settings.imap_user, settings.imap_password)
        status, _ = mailbox.select(settings.imap_mailbox, readonly=True)
        if status != "OK":
            raise RuntimeError(f"could not select IMAP mailbox {settings.imap_mailbox!r}")
        status, data = mailbox.uid("search", None, "ALL")
        if status != "OK" or not data:
            return []

        commands: list[EmailCommand] = []
        for uid in data[0].split()[-100:]:
            status, fetched = mailbox.uid("fetch", uid, "(BODY.PEEK[])")
            if status != "OK" or not fetched:
                continue
            raw = next((item[1] for item in fetched if isinstance(item, tuple) and len(item) > 1), None)
            if not isinstance(raw, bytes):
                continue
            message = email.message_from_bytes(raw, policy=default)
            message_id = str(message.get("Message-ID", "")).strip() or f"imap-uid:{uid.decode()}"
            if message_id in already_processed or not is_job_reply(settings, message, job_id):
                continue
            command = reply_command(message)
            if not command:
                continue
            commands.append(
                EmailCommand(
                    message_id=message_id,
                    sender=parseaddr(str(message.get("From", "")))[1],
                    command=command,
                    subject=str(message.get("Subject", "")),
                )
            )
        return commands
