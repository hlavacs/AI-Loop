import json
import sys
import uuid
import redis

r = redis.Redis.from_url("redis://localhost:6379/0", decode_responses=True)

repo_path = sys.argv[1]
goal = " ".join(sys.argv[2:])

job_id = str(uuid.uuid4())[:8]

task = {
    "job_id": job_id,
    "iteration": 0,
    "repo_path": repo_path,
    "goal": goal,
    "constraints": [
        "Make small incremental changes.",
        "Do not rewrite unrelated code.",
        "Do not commit.",
        "Keep the project buildable after each iteration."
    ],
    "acceptance": [
        "Relevant tests pass.",
        "Implementation matches the stated goal.",
        "No unrelated files are changed."
    ],
    "test_cmd": "pytest -q"
}

r.xadd("ai:codex:tasks", {"task": json.dumps(task)})
print(f"started job {job_id}")

