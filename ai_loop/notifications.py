"""Best-effort terminal email notifications."""

from __future__ import annotations

import shutil
import smtplib
import subprocess
from email.message import EmailMessage
from typing import Any


def terminal_email(
    settings: Any,
    *,
    job: dict[str, Any],
    status: str,
    reason: str,
) -> tuple[bool, str]:
    recipient = settings.notify_email.strip()
    if not recipient:
        return False, "AI_LOOP_NOTIFY_EMAIL is empty"

    message = EmailMessage()
    message["To"] = recipient
    message["From"] = settings.smtp_from or settings.smtp_user or recipient
    message["Subject"] = f"ai-loop job {job['id']}: {status}"
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
