import json
import time

import redis
from redis.exceptions import TimeoutError, ConnectionError


REDIS_URL = "redis://localhost:6379/0"
READ_BLOCK_MS = 5000

r = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=10,
    health_check_interval=30,
    retry_on_timeout=True,
)

streams = {
    "ai:done": "$",
    "ai:human": "$",
    "ai:dead": "$",
}

print("Watching ai:done, ai:human, ai:dead...")

while True:
    try:
        messages = r.xread(
            streams,
            block=READ_BLOCK_MS,
            count=1,
        )
    except (TimeoutError, ConnectionError) as e:
        print(f"Redis read problem, retrying: {e}")
        time.sleep(1)
        continue

    if not messages:
        continue

    for stream, entries in messages:
        for message_id, fields in entries:
            print()
            print("=" * 80)
            print(f"STREAM: {stream}")
            print(f"ID: {message_id}")

            for key, value in fields.items():
                try:
                    parsed = json.loads(value)
                    print(json.dumps(parsed, indent=2))
                except Exception:
                    print(f"{key}: {value}")

            streams[stream] = message_id

