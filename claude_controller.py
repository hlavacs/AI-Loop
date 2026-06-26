import json
import os
import socket
import subprocess
import time

import redis
from redis.exceptions import TimeoutError, ConnectionError


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

RESULT_STREAM = "ai:codex:results"
TASK_STREAM = "ai:codex:tasks"
DONE_STREAM = "ai:done"
HUMAN_STREAM = "ai:human"
DEAD_STREAM = "ai:dead"

GROUP = "claude-controllers"
CONSUMER = socket.gethostname() + "-claude"

READ_BLOCK_MS = 5000
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "20"))


r = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=10,
    health_check_interval=30,
    retry_on_timeout=True,
)


def ensure_group(stream: str, group: str) -> None:
    try:
        r.xgroup_create(stream, group, id="0", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def extract_json(text: str) -> dict:
    """
    Claude CLI may return either:
    1. plain JSON decision
    2. a JSON wrapper containing a 'result' string
    3. text that contains a JSON object

    This function extracts the actual decision object.
    """

    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"Could not find JSON object in Claude output:\n{text}")

    return json.loads(text[start : end + 1])


def validate_decision(decision: dict) -> None:
    if not isinstance(decision, dict):
        raise ValueError("Claude decision is not a JSON object")

    action = decision.get("action")

    if action not in {"CONTINUE", "REPAIR", "DONE", "HUMAN_NEEDED"}:
        raise ValueError(f"Invalid Claude action: {action}")

    if "reason" not in decision:
        raise ValueError("Claude decision has no reason")

    if action in {"CONTINUE", "REPAIR"}:
        next_task = decision.get("next_task")

        if not isinstance(next_task, dict):
            raise ValueError(f"Action {action} requires next_task")

        required = ["goal", "constraints", "acceptance", "test_cmd"]

        for key in required:
            if key not in next_task:
                raise ValueError(f"next_task is missing required field: {key}")

        if not isinstance(next_task["constraints"], list):
            raise ValueError("next_task.constraints must be a list")

        if not isinstance(next_task["acceptance"], list):
            raise ValueError("next_task.acceptance must be a list")


def get_planned_step(loop_plan: list, step_number: int) -> dict | None:
    for step in loop_plan:
        if int(step.get("step", -1)) == step_number:
            return step
    return None


def normalize_decision_with_plan(result: dict, decision: dict) -> dict:
    """
    For staged demo jobs, enforce one planned milestone per iteration.

    This keeps the loop predictable:
    - failed tests => REPAIR same step
    - passed non-final step => CONTINUE next step
    - passed final step => DONE
    """

    loop_plan = result.get("loop_plan", [])
    if not loop_plan:
        return decision

    current_step = int(result.get("current_step", 1))
    final_step = max(int(step["step"]) for step in loop_plan)
    test_rc = int(result.get("test_rc", 1))
    codex_rc = int(result.get("codex_rc", 1))

    if codex_rc != 0 or test_rc != 0:
        step = get_planned_step(loop_plan, current_step)
        if step is None:
            return {
                "action": "HUMAN_NEEDED",
                "reason": f"Current step {current_step} is missing from loop_plan.",
            }

        return {
            "action": "REPAIR",
            "reason": (
                f"Step {current_step} failed. Codex must repair the same milestone "
                f"before the loop can continue. Claude reason was: {decision.get('reason', '')}"
            ),
            "next_task": {
                "goal": step["goal"],
                "constraints": step["constraints"],
                "acceptance": step["acceptance"],
                "test_cmd": step["test_cmd"],
            },
        }

    if current_step >= final_step:
        return {
            "action": "DONE",
            "reason": (
                f"Final planned step {current_step} passed. "
                f"Claude reason was: {decision.get('reason', '')}"
            ),
        }

    next_step_number = current_step + 1
    next_step = get_planned_step(loop_plan, next_step_number)

    if next_step is None:
        return {
            "action": "HUMAN_NEEDED",
            "reason": f"Next planned step {next_step_number} is missing from loop_plan.",
        }

    return {
        "action": "CONTINUE",
        "reason": (
            f"Step {current_step} passed. Continue with planned step {next_step_number}. "
            f"Claude reason was: {decision.get('reason', '')}"
        ),
        "next_task": {
            "goal": next_step["goal"],
            "constraints": next_step["constraints"],
            "acceptance": next_step["acceptance"],
            "test_cmd": next_step["test_cmd"],
        },
    }


def run_claude_review(result: dict) -> dict:
    prompt = f"""
You are Claude, the planner and reviewer in a continuous development loop.

Codex has completed one implementation iteration.

Your job:
1. Review the changed files, diff, and test output.
2. Decide whether the current step is correct.
3. Return ONLY valid JSON.
4. Do not wrap the JSON in Markdown.
5. Do not add explanations outside the JSON.

Allowed actions:
- CONTINUE: current step is correct; Codex should do the next step.
- REPAIR: current step failed or is suspicious; Codex should fix it.
- DONE: all required work is complete.
- HUMAN_NEEDED: the issue cannot safely be resolved automatically.

Required JSON shape:

{{
  "action": "CONTINUE | REPAIR | DONE | HUMAN_NEEDED",
  "reason": "short explanation",
  "next_task": {{
    "goal": "specific next implementation step",
    "constraints": ["..."],
    "acceptance": ["..."],
    "test_cmd": "..."
  }}
}}

Rules:
- If action is CONTINUE or REPAIR, next_task is required.
- If action is DONE or HUMAN_NEEDED, next_task may be omitted.
- Prefer REPAIR if tests failed.
- Prefer HUMAN_NEEDED for sandbox failures, missing tools, destructive changes, unclear requirements, or security risk.

Global goal:
{result.get("global_goal", result.get("goal", ""))}

Loop plan:
{json.dumps(result.get("loop_plan", []), indent=2)}

Current step:
{result.get("current_step", 1)}

Loop-plan rules:
- If loop_plan is non-empty, this is a staged multi-iteration demo.
- If the current step's tests passed and current_step is less than the number of planned steps, return CONTINUE.
- For CONTINUE, choose the next numbered step from loop_plan as next_task.
- If the current step's tests failed, return REPAIR for the same step.
- Only return DONE when the final planned step has passed.

Current task goal:
{result.get("goal", "")}

Changed files:
{json.dumps(result.get("changed_files", []), indent=2)}

Git status:
{result.get("git_status", "")}

Diff stat:
{result.get("diff_stat", "")}

Test command:
{result.get("test_cmd", "")}

Test return code:
{result.get("test_rc", "")}

Test output:
{result.get("test_output", "")}

Codex return code:
{result.get("codex_rc", "")}

Codex output:
{result.get("codex_output", "")}

Diff:
{result.get("diff", "")}
"""

    cmd = [
        "claude",
        "-p",
        "--output-format",
        "json",
        prompt,
    ]

    print("\n--- running Claude reviewer")

    p = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=7200,
    )

    if p.returncode != 0:
        raise RuntimeError(
            f"Claude failed:\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}"
        )

    raw = p.stdout.strip()

    parsed = extract_json(raw)

    # Claude CLI with --output-format json often wraps the real answer in "result".
    if isinstance(parsed, dict) and "result" in parsed and isinstance(parsed["result"], str):
        parsed = extract_json(parsed["result"])

    # For staged demo jobs, make the loop deterministic.
    parsed = normalize_decision_with_plan(result, parsed)

    validate_decision(parsed)

    return parsed


def main() -> None:
    ensure_group(RESULT_STREAM, GROUP)

    print("Claude controller started.")
    print(f"Listening on Redis stream: {RESULT_STREAM}")
    print(f"Consumer group: {GROUP}")
    print(f"Consumer: {CONSUMER}")
    print(f"Max iterations: {MAX_ITERATIONS}")

    while True:
        try:
            messages = r.xreadgroup(
                GROUP,
                CONSUMER,
                {RESULT_STREAM: ">"},
                count=1,
                block=READ_BLOCK_MS,
            )
        except (TimeoutError, ConnectionError) as e:
            print(f"Redis read problem, retrying: {e}")
            time.sleep(1)
            continue

        if not messages:
            continue

        _, entries = messages[0]

        for message_id, fields in entries:
            try:
                result = json.loads(fields["result"])

                print()
                print("=" * 80)
                print(
                    f"Reviewing job {result.get('job_id')} "
                    f"iteration {result.get('iteration')} "
                    f"step {result.get('current_step', '?')}"
                )
                print(result.get("goal"))
                print("=" * 80)

                decision = run_claude_review(result)

                action = decision["action"]
                iteration = int(result.get("iteration", 0)) + 1
                current_step = int(result.get("current_step", 1))

                if action == "REPAIR":
                    next_current_step = current_step
                else:
                    next_current_step = current_step + 1

                envelope = {
                    "job_id": result["job_id"],
                    "iteration": iteration,
                    "repo_path": result["repo_path"],
                    "global_goal": result.get("global_goal", result.get("goal", "")),
                    "loop_plan": result.get("loop_plan", []),
                    "current_step": result.get("current_step", 1),
                    "previous_result": {
                        "test_rc": result.get("test_rc"),
                        "codex_rc": result.get("codex_rc"),
                        "changed_files": result.get("changed_files", []),
                        "diff_stat": result.get("diff_stat", ""),
                    },
                    "claude_decision": decision,
                }

                print(f"Claude action: {action}")
                print(f"Reason: {decision.get('reason')}")

                if iteration >= MAX_ITERATIONS:
                    r.xadd(
                        HUMAN_STREAM,
                        {
                            "event": json.dumps(
                                {
                                    **envelope,
                                    "reason": "maximum iteration count reached",
                                }
                            )
                        },
                    )
                    print("Job requires human input: max iterations reached")

                elif action in {"CONTINUE", "REPAIR"}:
                    next_task = decision["next_task"]

                    task = {
                        "job_id": result["job_id"],
                        "iteration": iteration,
                        "repo_path": result["repo_path"],

                        "global_goal": result.get("global_goal", result.get("goal", "")),
                        "loop_plan": result.get("loop_plan", []),
                        "current_step": next_current_step,

                        "goal": next_task["goal"],
                        "constraints": next_task["constraints"],
                        "acceptance": next_task["acceptance"],
                        "test_cmd": next_task["test_cmd"],
                    }

                    r.xadd(TASK_STREAM, {"task": json.dumps(task)})
                    print(
                        f"Queued next Codex task, iteration {iteration}, "
                        f"step {next_current_step}"
                    )

                elif action == "DONE":
                    r.xadd(DONE_STREAM, {"event": json.dumps(envelope)})
                    print("Job marked DONE")

                elif action == "HUMAN_NEEDED":
                    r.xadd(HUMAN_STREAM, {"event": json.dumps(envelope)})
                    print("Job requires human input")

                r.xack(RESULT_STREAM, GROUP, message_id)

            except Exception as e:
                print(f"Controller error: {e}")

                try:
                    r.xadd(
                        DEAD_STREAM,
                        {
                            "where": "claude_controller",
                            "error": repr(e),
                            "fields": json.dumps(fields),
                        },
                    )
                    r.xack(RESULT_STREAM, GROUP, message_id)
                except Exception as inner:
                    print(f"Could not write to dead stream: {inner}")


if __name__ == "__main__":
    main()
    
    
