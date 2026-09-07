from __future__ import annotations

import json
import unittest
from pathlib import Path

import controller


def valid_next_task() -> dict:
    return {
        "goal": "Implement the widget",
        "constraints": ["Keep public APIs stable"],
        "acceptance": ["Widget renders"],
        "test_cmd": "pytest -q",
    }


def valid_decision(action: str = "CONTINUE", **overrides) -> dict:
    decision = {
        "action": action,
        "reason": "work remains",
        "history_summary": "did some work",
        "progress": {
            "completed_work_units": 1,
            "remaining_work_units": 2,
            "remaining_minutes": 30,
        },
    }
    if action in {"CONTINUE", "REPAIR"}:
        decision["next_task"] = valid_next_task()
    decision.update(overrides)
    return decision


class ExtractJsonTests(unittest.TestCase):
    def test_strict_json_object_is_returned_as_is(self) -> None:
        payload = {"action": "DONE", "reason": "ok"}
        self.assertEqual(controller.extract_json(json.dumps(payload)), payload)

    def test_json_embedded_in_prose_uses_first_brace_to_last_brace(self) -> None:
        payload = {"action": "DONE", "reason": "ok"}
        text = f"Sure, here is the decision:\n{json.dumps(payload)}\nHope that helps."
        self.assertEqual(controller.extract_json(text), payload)

    def test_structured_output_envelope_is_unwrapped(self) -> None:
        inner = {"action": "DONE", "reason": "finished"}
        envelope = {"type": "result", "structured_output": inner, "result": "ignored text"}
        self.assertEqual(controller.extract_json(json.dumps(envelope)), inner)

    def test_nested_string_envelopes_recurse_to_inner_decision(self) -> None:
        inner = {"action": "DONE", "reason": "finished", "history_summary": "done"}
        # Inner-most envelope carries the decision as a JSON string in "result";
        # the outer envelope wraps that (with prose noise) in "response".
        level1 = {"result": json.dumps(inner), "is_error": False}
        level2 = {"response": "Here is my answer: " + json.dumps(level1) + " -- end"}
        self.assertEqual(controller.extract_json(json.dumps(level2)), inner)

    def test_output_key_envelope_recurses(self) -> None:
        inner = {"action": "HUMAN_NEEDED", "reason": "stuck"}
        envelope = {"output": json.dumps(inner)}
        self.assertEqual(controller.extract_json(json.dumps(envelope)), inner)

    def test_garbage_without_braces_raises_value_error(self) -> None:
        # Contract read from the code: no "{" ... "}" span -> ValueError with
        # "Claude did not return JSON" prefix.
        with self.assertRaises(ValueError) as ctx:
            controller.extract_json("no json here at all")
        self.assertIn("did not return JSON", str(ctx.exception))

    def test_non_object_json_raises_value_error(self) -> None:
        # A JSON array parses fine but is not an object -> ValueError.
        with self.assertRaises(ValueError) as ctx:
            controller.extract_json("[1, 2, 3]")
        self.assertIn("not an object", str(ctx.exception))

    def test_unparseable_brace_span_raises(self) -> None:
        # json.JSONDecodeError is a ValueError subclass; extract_json lets it
        # propagate when the brace-to-brace substring is not valid JSON.
        with self.assertRaises(ValueError):
            controller.extract_json("prefix {not: valid json} suffix")


class ValidateDecisionTests(unittest.TestCase):
    def test_valid_continue_with_next_task_passes(self) -> None:
        decision = valid_decision("CONTINUE")
        controller.validate_decision(decision)  # must not raise
        self.assertEqual(decision["action"], "CONTINUE")

    def test_continue_without_next_task_is_rejected(self) -> None:
        decision = valid_decision("CONTINUE")
        del decision["next_task"]
        with self.assertRaises(ValueError) as ctx:
            controller.validate_decision(decision)
        self.assertIn("requires next_task", str(ctx.exception))

    def test_repair_without_next_task_is_rejected(self) -> None:
        decision = valid_decision("REPAIR")
        del decision["next_task"]
        with self.assertRaises(ValueError):
            controller.validate_decision(decision)

    def test_done_and_human_needed_without_next_task_are_accepted(self) -> None:
        for action in ("DONE", "HUMAN_NEEDED"):
            decision = valid_decision(action)
            self.assertNotIn("next_task", decision)
            controller.validate_decision(decision)  # must not raise

    def test_action_outside_enum_is_rejected(self) -> None:
        decision = valid_decision("DONE")
        decision["action"] = "SHIP_IT"
        with self.assertRaises(ValueError) as ctx:
            controller.validate_decision(decision)
        self.assertIn("invalid action", str(ctx.exception))

    def test_missing_progress_is_injected_with_conservative_default(self) -> None:
        decision = valid_decision("DONE")
        del decision["progress"]
        controller.validate_decision(decision)
        # Code injects: 0 completed, 1 remaining, unknown time.
        self.assertEqual(
            decision["progress"],
            {
                "completed_work_units": 0,
                "remaining_work_units": 1,
                "remaining_minutes": None,
            },
        )

    def test_non_string_reason_and_history_summary_are_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            controller.validate_decision(valid_decision("DONE", reason=42))
        self.assertIn("reason must be a string", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            controller.validate_decision(valid_decision("DONE", history_summary=None))
        self.assertIn("history_summary must be a string", str(ctx.exception))

    def test_negative_or_non_int_work_units_are_rejected(self) -> None:
        bad = valid_decision("DONE")
        bad["progress"]["completed_work_units"] = -1
        with self.assertRaises(ValueError):
            controller.validate_decision(bad)
        bad = valid_decision("DONE")
        bad["progress"]["remaining_work_units"] = "many"
        with self.assertRaises(ValueError):
            controller.validate_decision(bad)

    def test_remaining_minutes_may_be_null_but_not_negative(self) -> None:
        ok = valid_decision("DONE")
        ok["progress"]["remaining_minutes"] = None
        controller.validate_decision(ok)  # must not raise
        bad = valid_decision("DONE")
        bad["progress"]["remaining_minutes"] = -5
        with self.assertRaises(ValueError):
            controller.validate_decision(bad)

    def test_next_task_missing_required_key_is_rejected(self) -> None:
        decision = valid_decision("CONTINUE")
        del decision["next_task"]["test_cmd"]
        with self.assertRaises(ValueError) as ctx:
            controller.validate_decision(decision)
        self.assertIn("next_task missing test_cmd", str(ctx.exception))

    def test_next_task_constraints_and_acceptance_must_be_lists(self) -> None:
        decision = valid_decision("CONTINUE")
        decision["next_task"]["constraints"] = "not a list"
        with self.assertRaises(ValueError):
            controller.validate_decision(decision)
        decision = valid_decision("CONTINUE")
        decision["next_task"]["acceptance"] = {"a": 1}
        with self.assertRaises(ValueError):
            controller.validate_decision(decision)


class ParseAndValidateDecisionTests(unittest.TestCase):
    def test_round_trip_from_envelope_with_prose(self) -> None:
        decision = valid_decision("CONTINUE")
        envelope = {"result": json.dumps(decision)}
        text = "Claude says:\n" + json.dumps(envelope) + "\n(end of transcript)"
        parsed = controller.parse_and_validate_decision(text)
        self.assertEqual(parsed, decision)

    def test_round_trip_injects_default_progress(self) -> None:
        decision = valid_decision("DONE")
        del decision["progress"]
        parsed = controller.parse_and_validate_decision(json.dumps(decision))
        self.assertEqual(parsed["progress"]["remaining_work_units"], 1)

    def test_round_trip_rejects_invalid_decision(self) -> None:
        with self.assertRaises(ValueError):
            controller.parse_and_validate_decision(json.dumps({"action": "CONTINUE"}))


class PromptSafeJobTests(unittest.TestCase):
    def test_email_token_is_removed_and_other_keys_kept(self) -> None:
        job = {"id": "J-1", "goal": "ship", "email_token": "secret-token"}
        safe = controller.prompt_safe_job(job)
        self.assertNotIn("email_token", safe)
        self.assertEqual(safe["id"], "J-1")
        self.assertEqual(safe["goal"], "ship")

    def test_input_job_is_not_mutated(self) -> None:
        job = {"id": "J-1", "email_token": "secret-token"}
        controller.prompt_safe_job(job)
        self.assertEqual(job["email_token"], "secret-token")

    def test_job_without_token_is_a_no_op_copy(self) -> None:
        job = {"id": "J-2"}
        safe = controller.prompt_safe_job(job)
        self.assertEqual(safe, job)
        self.assertIsNot(safe, job)


class JsonRemakePromptTests(unittest.TestCase):
    def test_prompt_contains_error_output_tail_and_schema(self) -> None:
        error = ValueError("decision.reason must be a string")
        invalid = "x" * 7000 + "TAIL-MARKER-XYZ"
        prompt = controller.json_remake_prompt("ORIGINAL-PROMPT-BODY", invalid, error)
        self.assertIn("decision.reason must be a string", prompt)
        self.assertIn("TAIL-MARKER-XYZ", prompt)
        # Only the last 6000 chars of the invalid output are included.
        self.assertNotIn(invalid, prompt)
        self.assertIn(invalid[-6000:], prompt)
        self.assertIn(controller.schema_text("normal"), prompt)
        self.assertIn("ORIGINAL-PROMPT-BODY", prompt)


class DecisionSchemaTests(unittest.TestCase):
    def schema(self) -> dict:
        path = Path(__file__).resolve().parents[1] / "decision.schema.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_schema_root_is_strict_and_requires_core_keys(self) -> None:
        schema = self.schema()
        self.assertIs(schema["additionalProperties"], False)
        for key in ("action", "reason", "history_summary", "progress"):
            self.assertIn(key, schema["required"])

    def test_schema_enum_matches_controller_actions_and_prose_schema(self) -> None:
        schema = self.schema()
        enum_actions = set(schema["properties"]["action"]["enum"])
        self.assertEqual(enum_actions, controller.ACTIONS)
        prose = controller.schema_text("normal")
        for action in enum_actions:
            self.assertIn(action, prose)

    def test_decision_json_schema_helper_serializes_the_same_schema(self) -> None:
        self.assertEqual(json.loads(controller.decision_json_schema()), self.schema())


class CreateNextTaskTests(unittest.TestCase):
    # create_next_task ends with xadd_json(client, CODEX_TASK_STREAM, "task",
    # {...}), i.e. it publishes the queued task to a Redis stream inside the
    # function body. Per test policy (never touch Redis, no mocks) the
    # test-command laundering path cannot be exercised standalone, so this
    # documented skip records the gap instead of faking a Redis client.
    @unittest.skip(
        "create_next_task publishes to Redis via xadd_json before returning; "
        "not testable without a Redis client and mocking is out of scope"
    )
    def test_test_command_laundering(self) -> None:
        pass


if __name__ == "__main__":
    unittest.main()
