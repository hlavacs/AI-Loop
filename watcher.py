from __future__ import annotations

import json
import os
import time

from redis.exceptions import ConnectionError, TimeoutError

from ai_loop.config import DEAD_STREAM, DONE_STREAM, HUMAN_STREAM, READ_BLOCK_MS, load_settings
from ai_loop.queues import redis_client


def scoped_job_id() -> str | None:
    value = os.getenv("AI_LOOP_JOB_ID")
    return value if value else None


def main() -> int:
    settings = load_settings()
    client = redis_client(settings.redis_url)
    streams = {DONE_STREAM: "$", HUMAN_STREAM: "$", DEAD_STREAM: "$"}
    job_scope = scoped_job_id()

    print("AI loop watcher started")
    print(f"redis: {settings.redis_url}")
    if job_scope:
        print(f"job_scope: {job_scope}")
    print(f"watching: {', '.join(streams)}")

    while True:
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
                if job_scope:
                    print(f"job {job_scope}: terminal event observed; watcher exiting")
                    return 0


if __name__ == "__main__":
    raise SystemExit(main())
