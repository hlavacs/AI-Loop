"""Redis Stream helpers used only for activation and terminal notifications."""

from __future__ import annotations

import json
import socket
from typing import Any

import redis

from .config import (
    CLAUDE_REQUEST_STREAM,
    CODEX_TASK_STREAM,
    READ_BLOCK_MS,
)


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


_XADD_ONCE_SCRIPT = """
local prior = redis.call('HGET', KEYS[2], ARGV[1])
if prior then
    local separator = string.find(prior, string.char(10), 1, true)
    local prior_id = string.sub(prior, 1, separator - 1)
    local prior_payload = string.sub(prior, separator + 1)
    if prior_payload ~= ARGV[3] then
        return redis.error_reply('publication key reused with different payload')
    end
    return {prior_id, 0}
end
local message_id = redis.call('XADD', KEYS[1], '*', ARGV[2], ARGV[3])
redis.call('HSET', KEYS[2], ARGV[1], message_id .. string.char(10) .. ARGV[3])
return {message_id, 1}
"""


def xadd_json_once(
    client: redis.Redis,
    stream: str,
    field: str,
    payload: dict[str, Any],
    *,
    publication_key: str,
) -> tuple[str, bool]:
    """Atomically publish one logical message at most once.

    Redis Streams can redeliver an unacknowledged message, but a producer retry
    must not append a second message for the same durable task.  The Lua script
    records the canonical payload and stream ID in the same Redis transaction
    as XADD.  Reusing a key with a different payload is rejected rather than
    silently publishing corrupt metadata.
    """

    if not publication_key:
        raise ValueError("publication_key must not be empty")
    encoded = encode(payload)
    decode(encoded)
    result = client.eval(
        _XADD_ONCE_SCRIPT,
        2,
        stream,
        f"{stream}:publication-ids",
        publication_key,
        field,
        encoded,
    )
    if not isinstance(result, (list, tuple)) or len(result) != 2:
        raise RuntimeError("atomic stream publication returned an invalid result")
    return str(result[0]), bool(int(result[1]))


def publish_controller_plan(
    client: redis.Redis,
    job_id: str,
    *,
    publication_key: str | None = None,
) -> bool:
    """Publish a PLAN request through the ordinary controller stream."""

    ensure_group(
        client,
        CLAUDE_REQUEST_STREAM,
        f"claude-controllers:{job_id}",
        start_id="$",
    )
    ensure_group(
        client,
        CODEX_TASK_STREAM,
        f"codex-workers:{job_id}",
        start_id="$",
    )
    payload = {"type": "PLAN", "job_id": job_id, "scope": "job"}
    if publication_key is None:
        xadd_json(client, CLAUDE_REQUEST_STREAM, "request", payload)
        return True
    _message_id, created = xadd_json_once(
        client,
        CLAUDE_REQUEST_STREAM,
        "request",
        payload,
        publication_key=publication_key,
    )
    return created


def publish_worker_task(
    client: redis.Redis,
    task: dict[str, Any],
    *,
    scoped: bool = False,
) -> bool:
    """Publish one persisted task through the normal Codex worker stream."""

    task_id = str(task["id"])
    job_id = str(task["job_id"])
    payload: dict[str, Any] = {
        "task_id": task_id,
        "job_id": job_id,
        "iteration": int(task["iteration"]),
        "created_by": str(task["created_by"]),
        "constraints": [str(item) for item in task["constraints"]],
        "acceptance": [str(item) for item in task["acceptance"]],
        "requirement_ids": [str(item) for item in task.get("requirement_ids", [])],
        "verification_ids": [str(item) for item in task.get("verification_ids", [])],
    }
    if scoped:
        payload["scope"] = "job"
    ensure_group(
        client,
        CODEX_TASK_STREAM,
        f"codex-workers:{job_id}",
        start_id="$",
    )
    _message_id, created = xadd_json_once(
        client,
        CODEX_TASK_STREAM,
        "task",
        payload,
        publication_key=f"task:{task_id}",
    )
    return created


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
