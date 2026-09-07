"""Redis Stream handoff integration tests against a real throwaway server.

Starts a private redis-server subprocess on a random high port (no
persistence, bound to localhost) and exercises the ai_loop.queues helpers the
controller/worker handoff relies on: xadd_json -> ensure_group -> read_group
round trip, pending-entry invisibility to other '>' readers, claim_pending
reclaim, and xack removal. Skips cleanly when redis-server is not installed.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

import redis as redis_module

from ai_loop.config import CLAUDE_REQUEST_STREAM, CODEX_TASK_STREAM
from ai_loop.queues import (
    claim_pending,
    decode,
    ensure_group,
    publish_controller_plan,
    publish_worker_task,
    read_group,
    xadd_json,
)


def _free_port() -> int:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


@unittest.skipUnless(shutil.which("redis-server"), "redis-server not installed")
class RedisHandoffTests(unittest.TestCase):
    server: subprocess.Popen
    client: redis_module.Redis

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.port = _free_port()
        cls.server = subprocess.Popen(
            [
                "redis-server",
                "--port",
                str(cls.port),
                "--bind",
                "127.0.0.1",
                "--save",
                "",
                "--appendonly",
                "no",
                "--dir",
                cls._tmpdir.name,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cls.client = redis_module.Redis(
            host="127.0.0.1",
            port=cls.port,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=10,
        )
        deadline = time.monotonic() + 10.0
        while True:
            if cls.server.poll() is not None:
                raise RuntimeError(f"redis-server exited early with rc={cls.server.returncode}")
            try:
                cls.client.ping()
                break
            except redis_module.exceptions.RedisError:
                if time.monotonic() >= deadline:
                    cls.server.terminate()
                    cls.server.wait(timeout=5)
                    raise
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.client.close()
        finally:
            cls.server.terminate()
            try:
                cls.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.server.kill()
                cls.server.wait()
            cls._tmpdir.cleanup()

    def test_handoff_round_trip_claim_and_ack(self) -> None:
        stream = f"test:handoff:{uuid.uuid4().hex}"
        group = "test-workers"
        payload = {"type": "PLAN", "job_id": "J-handoff", "scope": "job"}

        message_id = xadd_json(self.client, stream, "request", payload)
        ensure_group(self.client, stream, group, start_id="0")
        # ensure_group swallows BUSYGROUP: a second call must be a no-op.
        ensure_group(self.client, stream, group, start_id="0")

        # Round trip: the first '>' reader receives the JSON payload intact.
        messages = read_group(self.client, group, "consumer-a", stream)
        self.assertTrue(messages)
        stream_name, entries = messages[0]
        self.assertEqual(stream_name, stream)
        self.assertEqual(len(entries), 1)
        got_id, fields = entries[0]
        self.assertEqual(got_id, message_id)
        self.assertEqual(decode(fields["request"]), payload)

        # Unacked message: pending for consumer-a, invisible to another '>'
        # read. READ_BLOCK_MS is shrunk so the empty blocking read is quick.
        with patch("ai_loop.queues.READ_BLOCK_MS", 200):
            second = read_group(self.client, group, "consumer-b", stream)
        self.assertFalse(second)

        # claim_pending reclaims the pending entry for the new consumer
        # (min_idle_ms=0 explicitly: the entry is only milliseconds old).
        claimed = claim_pending(self.client, stream, group, "consumer-b", min_idle_ms=0)
        self.assertEqual([mid for mid, _fields in claimed], [message_id])
        self.assertEqual(decode(claimed[0][1]["request"]), payload)
        self.assertEqual(self.client.xpending(stream, group)["pending"], 1)

        # ack removes the entry from the pending list for good.
        self.client.xack(stream, group, message_id)
        self.assertEqual(self.client.xpending(stream, group)["pending"], 0)
        self.assertEqual(claim_pending(self.client, stream, group, "consumer-b", min_idle_ms=0), [])

    def test_formal_plan_and_worker_task_publications_are_idempotent(self) -> None:
        job_id = f"J-{uuid.uuid4().hex}"
        task_id = f"T-{uuid.uuid4().hex}"
        plan_key = f"formal-job:{job_id}"
        task = {
            "id": task_id,
            "job_id": job_id,
            "iteration": 7,
            "created_by": "specification_change_impact",
            "constraints": ["Use the persisted impact boundary."],
            "acceptance": ["Affected verification is fresh and passing."],
            "requirement_ids": ["R1"],
            "verification_ids": ["VT1"],
        }

        self.assertTrue(
            publish_controller_plan(
                self.client, job_id, publication_key=plan_key
            )
        )
        self.assertFalse(
            publish_controller_plan(
                self.client, job_id, publication_key=plan_key
            )
        )
        self.assertTrue(publish_worker_task(self.client, task, scoped=True))
        self.assertFalse(publish_worker_task(self.client, task, scoped=True))

        plan_messages = [
            fields
            for _message_id, fields in self.client.xrange(CLAUDE_REQUEST_STREAM)
            if decode(fields["request"]).get("job_id") == job_id
        ]
        task_messages = [
            fields
            for _message_id, fields in self.client.xrange(CODEX_TASK_STREAM)
            if decode(fields["task"]).get("task_id") == task_id
        ]
        self.assertEqual(len(plan_messages), 1)
        self.assertEqual(len(task_messages), 1)
        self.assertEqual(
            decode(task_messages[0]["task"]),
            {
                "created_by": "specification_change_impact",
                "iteration": 7,
                "job_id": job_id,
                "constraints": ["Use the persisted impact boundary."],
                "acceptance": ["Affected verification is fresh and passing."],
                "requirement_ids": ["R1"],
                "verification_ids": ["VT1"],
                "scope": "job",
                "task_id": task_id,
            },
        )


if __name__ == "__main__":
    unittest.main()
