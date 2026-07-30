from __future__ import annotations

import json
import os
import time

from redis.exceptions import ConnectionError, TimeoutError

from ai_loop import db
from ai_loop.config import DEAD_STREAM, DONE_STREAM, HUMAN_STREAM, READ_BLOCK_MS, load_settings
from ai_loop.email_commands import apply_email_command, poll_job_commands, processed_message_ids
from ai_loop.queues import redis_client
from ai_loop.status_updates import maybe_send_status_email


def scoped_job_id() -> str | None:
    value = os.getenv("AI_LOOP_JOB_ID")
    return value if value else None


def main() -> int:
    settings = load_settings()
    db.init_db(settings.db_path)
    client = redis_client(settings.redis_url)
    streams = {DONE_STREAM: "$", HUMAN_STREAM: "$", DEAD_STREAM: "$"}
    job_scope = scoped_job_id()

    print("AI loop watcher started")
    print(f"redis: {settings.redis_url}")
    if job_scope:
        print(f"job_scope: {job_scope}")
    print(f"watching: {', '.join(streams)}")
    if job_scope and settings.imap_host:
        print(f"email commands: {settings.imap_user}@{settings.imap_host} mailbox={settings.imap_mailbox}")
    next_email_poll = 0.0
    waiting_for_human = False
    if job_scope:
        with db.transaction(settings.db_path) as conn:
            waiting_for_human = str(db.get_job(conn, job_scope)["status"]) == "human_needed"

    while True:
        if job_scope:
            if waiting_for_human:
                with db.transaction(settings.db_path) as conn:
                    current_status = str(db.get_job(conn, job_scope)["status"])
                if current_status != "human_needed":
                    print(f"job {job_scope}: resumed elsewhere; old watcher exiting")
                    return 0
            try:
                maybe_send_status_email(settings, job_scope)
            except Exception as exc:
                print(f"job {job_scope}: status email check failed: {exc!r}")
            if time.monotonic() >= next_email_poll:
                next_email_poll = time.monotonic() + settings.email_poll_seconds
                try:
                    with db.transaction(settings.db_path) as conn:
                        processed = processed_message_ids(conn, job_scope)
                    for incoming in poll_job_commands(settings, job_scope, processed):
                        processed.add(incoming.message_id)
                        if apply_email_command(settings, job_scope, incoming):
                            print(f"job {job_scope}: replacement watcher launched; old watcher exiting")
                            return 0
                except Exception as exc:
                    print(f"job {job_scope}: email command check failed: {exc!r}")
        try:
            messages = client.xread(streams, block=READ_BLOCK_MS, count=1)
        except (TimeoutError, ConnectionError) as exc:
            print(f"Redis read problem, retrying: {exc}")
            time.sleep(1)
            continue

        if not messages:
            continue

        for stream, entries in messages:
            for message_id, fields in entries:
                decoded_fields: dict[str, object] = {}
                for key, value in fields.items():
                    try:
                        decoded_fields[key] = json.loads(value)
                    except json.JSONDecodeError:
                        decoded_fields[key] = value
                event_job_id = None
                for value in decoded_fields.values():
                    if isinstance(value, dict) and isinstance(value.get("job_id"), str):
                        event_job_id = value["job_id"]
                        break
                streams[stream] = message_id
                if job_scope and event_job_id != job_scope:
                    continue
                print()
                print("=" * 80)
                print(f"{stream} {message_id}")
                for key, value in decoded_fields.items():
                    if isinstance(value, dict):
                        print(json.dumps(value, indent=2))
                    else:
                        print(f"{key}: {value}")
                if job_scope and stream != HUMAN_STREAM:
                    print(f"job {job_scope}: terminal event observed; watcher exiting")
                    return 0
                if job_scope and stream == HUMAN_STREAM:
                    waiting_for_human = True
                    print(f"job {job_scope}: waiting for a command by email or a manual resume")


if __name__ == "__main__":
    raise SystemExit(main())
