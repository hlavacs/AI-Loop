"""Mail account access checks and authenticated job notifications."""

from __future__ import annotations

import imaplib
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any


@dataclass(frozen=True)
class MailAccessStatus:
    enabled: bool
    ok: bool
    detail: str
    smtp_detail: str
    mailbox_detail: str


def mail_enabled(settings: Any) -> bool:
    return bool(settings.smtp_host.strip() and settings.smtp_password)


def delivery_outcome(sent: bool, detail: str) -> str:
    if sent:
        return "sent"
    if detail.startswith("email disabled:"):
        return "skipped"
    return "failed"


def _smtp_connection(settings: Any):
    smtp_type = smtplib.SMTP_SSL if settings.smtp_ssl else smtplib.SMTP
    return smtp_type(settings.smtp_host, settings.smtp_port, timeout=30)


def check_mail_access(settings: Any) -> MailAccessStatus:
    if not settings.smtp_host.strip():
        detail = "disabled: AI_LOOP_SMTP_HOST is empty; startup check skipped and no email will be sent"
        return MailAccessStatus(False, True, detail, "disabled", "disabled")
    if not settings.smtp_password:
        detail = "disabled: AI_LOOP_SMTP_PASSWORD is empty; startup check skipped and no email will be sent"
        return MailAccessStatus(False, True, detail, "disabled", "disabled")
    if not settings.smtp_user.strip():
        detail = "error: AI_LOOP_SMTP_USER is empty"
        return MailAccessStatus(True, False, detail, detail, "not checked")
    if not settings.notify_email.strip():
        detail = "error: AI_LOOP_NOTIFY_EMAIL is empty"
        return MailAccessStatus(True, False, detail, "not checked", "not checked")

    try:
        with _smtp_connection(settings) as smtp:
            if settings.smtp_starttls and not settings.smtp_ssl:
                smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.noop()
        smtp_detail = f"SMTP account accessible at {settings.smtp_host}:{settings.smtp_port}"
    except Exception as exc:
        detail = f"error: SMTP account access failed: {exc!r}"
        return MailAccessStatus(True, False, detail, detail, "not checked")

    if not settings.imap_host.strip():
        mailbox_detail = "IMAP mailbox access not configured; emailed commands are disabled"
        return MailAccessStatus(True, True, f"{smtp_detail}; {mailbox_detail}", smtp_detail, mailbox_detail)
    if not settings.imap_user.strip():
        mailbox_detail = "error: AI_LOOP_IMAP_USER is empty"
        return MailAccessStatus(True, False, f"{smtp_detail}; {mailbox_detail}", smtp_detail, mailbox_detail)
    if not settings.imap_password:
        mailbox_detail = "error: AI_LOOP_IMAP_PASSWORD is empty"
        return MailAccessStatus(True, False, f"{smtp_detail}; {mailbox_detail}", smtp_detail, mailbox_detail)

    try:
        imap_type = imaplib.IMAP4_SSL if settings.imap_ssl else imaplib.IMAP4
        with imap_type(settings.imap_host, settings.imap_port, timeout=30) as mailbox:
            if settings.imap_starttls and not settings.imap_ssl:
                mailbox.starttls()
            mailbox.login(settings.imap_user, settings.imap_password)
            status, _ = mailbox.select(settings.imap_mailbox, readonly=True)
            if status != "OK":
                raise RuntimeError(f"could not select mailbox {settings.imap_mailbox!r}")
        mailbox_detail = (
            f"IMAP mailbox accessible at {settings.imap_host}:{settings.imap_port} "
            f"({settings.imap_mailbox})"
        )
    except Exception as exc:
        mailbox_detail = f"error: IMAP mailbox access failed: {exc!r}"
        return MailAccessStatus(True, False, f"{smtp_detail}; {mailbox_detail}", smtp_detail, mailbox_detail)

    return MailAccessStatus(True, True, f"{smtp_detail}; {mailbox_detail}", smtp_detail, mailbox_detail)


def job_thread_message_id(settings: Any, job_id: str) -> str:
    sender = (settings.smtp_from or settings.smtp_user or settings.notify_email).strip()
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else "ai-loop.local"
    safe_job_id = "".join(character for character in job_id if character.isalnum() or character in ".-_")
    return f"<ai-loop-{safe_job_id}@{domain}>"


def thread_job_message(settings: Any, message: EmailMessage, job_id: str, *, root: bool = False) -> None:
    thread_id = job_thread_message_id(settings, job_id)
    message["X-AI-Loop-Notification"] = job_id
    if root:
        message["Message-ID"] = thread_id
    else:
        message["In-Reply-To"] = thread_id
        message["References"] = thread_id


def deliver_email(settings: Any, message: EmailMessage) -> tuple[bool, str]:
    if not settings.smtp_host.strip():
        return False, "email disabled: AI_LOOP_SMTP_HOST is empty"
    if not settings.smtp_password:
        return False, "email disabled: AI_LOOP_SMTP_PASSWORD is empty"
    recipient = settings.notify_email.strip()
    if not recipient:
        return False, "AI_LOOP_NOTIFY_EMAIL is empty"
    if not settings.smtp_user.strip():
        return False, "AI_LOOP_SMTP_USER is empty"

    try:
        with _smtp_connection(settings) as smtp:
            if settings.smtp_starttls and not settings.smtp_ssl:
                smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
        return True, f"sent through {settings.smtp_host}:{settings.smtp_port}"
    except Exception as exc:
        return False, repr(exc)


def job_started_email(settings: Any, *, job: dict[str, Any]) -> tuple[bool, str]:
    recipient = settings.notify_email.strip()
    message = EmailMessage()
    message["To"] = recipient
    message["From"] = settings.smtp_from or settings.smtp_user or recipient
    message["Subject"] = f"AI-Loop job {job['id']} started"
    thread_job_message(settings, message, str(job["id"]), root=True)
    message.set_content(
        "\n".join(
            [
                f"Job: {job['id']}",
                "Status: started",
                f"Repository: {job['repo_path']}",
                f"Worktree: {job['worktree_path']}",
                f"Controller: {job['controller']}",
                f"Worker: {job['worker']}",
                "",
                "Goal:",
                str(job["goal"]),
                "",
                "Reply to this email with a new command for this job.",
                "If the job is waiting for human input, AI-Loop will resume it automatically.",
            ]
        )
    )
    return deliver_email(settings, message)


def terminal_email(
    settings: Any,
    *,
    job: dict[str, Any],
    status: str,
    reason: str,
) -> tuple[bool, str]:
    recipient = settings.notify_email.strip()
    message = EmailMessage()
    message["To"] = recipient
    message["From"] = settings.smtp_from or settings.smtp_user or recipient
    message["Subject"] = f"AI-Loop job {job['id']}: {status}"
    thread_job_message(settings, message, str(job["id"]))
    message.set_content(
        "\n".join(
            [
                f"Job: {job['id']}",
                f"Status: {status}",
                f"Repository: {job['repo_path']}",
                f"Worktree: {job['worktree_path']}",
                "",
                f"Reason: {reason}",
                "",
                "Goal:",
                str(job["goal"]),
                "",
                "Reply to this email with a new command for this job.",
            ]
        )
    )
    return deliver_email(settings, message)


def status_email(
    settings: Any,
    *,
    job: dict[str, Any],
    percent: int,
    task_count: int,
    run_count: int,
    current_task: str,
    remaining_seconds: int | None,
) -> tuple[bool, str]:
    recipient = settings.notify_email.strip()
    if remaining_seconds is None:
        remaining = "unknown"
    elif remaining_seconds < 3600:
        remaining = f"{max(1, remaining_seconds // 60)} minutes"
    else:
        hours = remaining_seconds // 3600
        minutes = (remaining_seconds % 3600) // 60
        remaining = f"{hours} hours {minutes} minutes"

    message = EmailMessage()
    message["To"] = recipient
    message["From"] = settings.smtp_from or settings.smtp_user or recipient
    message["Subject"] = f"AI-Loop job {job['id']} update: {percent}%"
    thread_job_message(settings, message, str(job["id"]))
    message.set_content(
        "\n".join(
            [
                f"Job: {job['id']}",
                f"Status: {job['status']}",
                f"Progress: {percent}%",
                f"Estimated time remaining: {remaining}",
                f"Controller: {job['controller']}",
                f"Worker: {job['worker']}",
                f"Tasks: {task_count}",
                f"Completed runs: {run_count}",
                f"Current task: {current_task or 'none'}",
                f"Repository: {job['repo_path']}",
                f"Worktree: {job['worktree_path']}",
                "",
                "Latest summary:",
                str(job.get("history_summary") or "No controller summary is available yet."),
                "",
                "Goal:",
                str(job["goal"]),
                "",
                "Reply to this email with a new command for this job.",
            ]
        )
    )
    return deliver_email(settings, message)
