"""Redis Stream helpers used only for activation and terminal notifications."""

from __future__ import annotations

import json
import socket
from typing import Any

import redis

from .config import READ_BLOCK_MS


def redis_client(redis_url: str) -> redis.Redis:
    return redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=10,
        health_check_interval=30,
        retry_on_timeout=True,
    )


def consumer_name(role: str) -> str:
    return f"{socket.gethostname()}-{role}"


def ensure_group(client: redis.Redis, stream: str, group: str, start_id: str = "0") -> None:
    try:
        client.xgroup_create(stream, group, id=start_id, mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def encode(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True)
    parsed = json.loads(text)
    if parsed != payload:
        raise ValueError("outbound JSON payload failed round-trip validation")
    return text


def decode(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        preview = value[:1000]
        raise ValueError(f"inbound JSON payload is invalid: {exc}; payload prefix={preview!r}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"inbound JSON payload must be an object, got {type(payload).__name__}")
    return payload


def xadd_json(client: redis.Redis, stream: str, field: str, payload: dict[str, Any]) -> str:
    encoded = encode(payload)
    decode(encoded)
    return client.xadd(stream, {field: encoded})


def claim_pending(client, stream: str, group: str, consumer: str, min_idle_ms: int = 30_000) -> list[tuple[str, dict]]:
    # Default min_idle_ms of 30 s: a just-crashed job is resumed minutes later,
    # so its pending entries are comfortably idle by then, while a concurrently
    # starting duplicate consumer will not steal a freshly delivered message
    # that another consumer is actively working on.
    claimed: list[tuple[str, dict]] = []
    start = "0-0"
    try:
        # Hard safety cap against pathological servers that keep advancing the
        # cursor forever.
        for _ in range(10_000):
            reply = client.xautoclaim(stream, group, consumer, min_idle_time=min_idle_ms, start_id=start)
            next_start, messages = reply[0], reply[1]
            for message_id, fields in messages:
                if fields is None:
                    # Deleted-entry tombstone: ack it so it stops reappearing
                    # in the pending list on every startup.
                    try:
                        client.xack(stream, group, message_id)
                    except Exception:
                        # A failed tombstone ack must not discard the real
                        # messages already claimed or crash the caller.
                        pass
                else:
                    claimed.append((message_id, fields))
            # Keep paging while the cursor advances, even if this page had no
            # usable messages (e.g. it was all tombstones).
            if next_start in ("0-0", "0") or next_start == start:
                break
            start = next_start
    except redis.ResponseError as exc:
        print(f"XAUTOCLAIM unavailable, skipping pending reclaim: {exc}")
        return []
    return claimed


def read_group(client: redis.Redis, group: str, consumer: str, stream: str):
    return client.xreadgroup(
        group,
        consumer,
        {stream: ">"},
        count=1,
        block=READ_BLOCK_MS,
    )
