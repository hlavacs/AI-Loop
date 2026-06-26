from __future__ import annotations

import json
import time

from redis.exceptions import ConnectionError, TimeoutError

from ai_loop.config import DEAD_STREAM, DONE_STREAM, HUMAN_STREAM, READ_BLOCK_MS, load_settings
from ai_loop.queues import redis_client


def main() -> int:
    settings = load_settings()
    client = redis_client(settings.redis_url)
    streams = {DONE_STREAM: "$", HUMAN_STREAM: "$", DEAD_STREAM: "$"}

    print("AI loop watcher started")
    print(f"redis: {settings.redis_url}")
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
                print()
                print("=" * 80)
                print(f"{stream} {message_id}")
                for key, value in fields.items():
                    try:
                        print(json.dumps(json.loads(value), indent=2))
                    except json.JSONDecodeError:
                        print(f"{key}: {value}")
                streams[stream] = message_id


if __name__ == "__main__":
    raise SystemExit(main())

