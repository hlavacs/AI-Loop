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


def ensure_group(client: redis.Redis, stream: str, group: str) -> None:
    try:
        client.xgroup_create(stream, group, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def encode(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


def decode(value: str) -> dict[str, Any]:
    return json.loads(value)


def xadd_json(client: redis.Redis, stream: str, field: str, payload: dict[str, Any]) -> str:
    return client.xadd(stream, {field: encode(payload)})


def read_group(client: redis.Redis, group: str, consumer: str, stream: str):
    return client.xreadgroup(
        group,
        consumer,
        {stream: ">"},
        count=1,
        block=READ_BLOCK_MS,
    )

