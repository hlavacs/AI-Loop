"""Best-effort terminal email notifications."""

from __future__ import annotations

import shutil
import smtplib
import subprocess
from email.message import EmailMessage
from typing import Any


def deliver_email(settings: Any, message: EmailMessage) -> tuple[bool, str]:
    recipient = settings.notify_email.strip()
    if not recipient:
        return False, "AI_LOOP_NOTIFY_EMAIL is empty"

    try:
        if settings.smtp_host:
            smtp_type = smtplib.SMTP_SSL if settings.smtp_ssl else smtplib.SMTP
            with smtp_type(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
                if settings.smtp_starttls and not settings.smtp_ssl:
                    smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(message)
            return True, f"sent through {settings.smtp_host}:{settings.smtp_port}"

        sendmail = shutil.which("sendmail")
        if sendmail:
            proc = subprocess.run(
                [sendmail, "-t", "-i"],
                input=message.as_string(),
                text=True,
                capture_output=True,
                timeout=30,
            )
            if proc.returncode == 0:
                return True, f"sent through {sendmail}"
            return False, proc.stderr.strip() or f"sendmail exited {proc.returncode}"

        return False, "configure AI_LOOP_SMTP_HOST or install a sendmail-compatible command"
    except Exception as exc:
        return False, repr(exc)


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
            ]
        )
    )
    return deliver_email(settings, message)
