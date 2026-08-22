from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pytest

import controller
import worker
from ai_loop.prompt_profiles import load_prompt_profiles


def job() -> dict:
    return {
        "id": "J-PROMPT",
        "worktree_path": "/definitely/missing/prompt-worktree",
        "goal": "Ship the prompt feature",
        "constraints": ["Keep defaults exact"],
        "acceptance": ["All builders are covered"],
        "test_cmd": "pytest -q",
        "granularity": "normal",
        "email_token": "secret",
        "finish_requested": 0,
    }


def task() -> dict:
    return {
        "id": "T-PROMPT",
        "iteration": 3,
        "goal": "Implement profiles",
        "constraints": ["Append only"],
        "acceptance": ["Guidance appears"],
        "test_cmd": "pytest -q",
        "requirement_ids": ["R7"],
        "verification_ids": ["V7"],
    }


def run() -> dict:
    return {
        "codex_output": "worker output",
        "test_output": "test output",
        "diff": "diff output",
        "status": "completed",
    }


def configured_profiles() -> str:
    return json.dumps(
        [
            {
                "id": "traceable-prompt-work",
                "match": {
                    "goal_contains": "prompt",
                    "constraints_contain": "defaults",
                    "acceptance_contain": "covered",
                    "requirement_ids_any": ["R7"],
                    "verification_ids_any": ["V7"],
                },
                "guidance": {
                    "worker": "WORKER PROFILE: retain a requirement-to-test map.",
                    "plan": "PLAN PROFILE: create a traceable first task.",
                    "review": "REVIEW PROFILE: reject untraceable follow-up work.",
                },
            }
        ]
    )


def test_configuration_loads_task_scoped_prompt_profile() -> None:
    loaded = load_prompt_profiles(configured_profiles())

    assert loaded.audits == ()
    assert len(loaded.profiles) == 1
    assert loaded.profiles[0].identifier == "traceable-prompt-work"
    assert loaded.profiles[0].match["requirement_ids_any"] == ("R7",)
    assert loaded.profiles[0].guidance["review"].startswith("REVIEW PROFILE")


def test_configured_profile_injects_all_prompt_builders_with_task_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_job = job()
    # PLAN has no persisted task yet, so these are its task-planning inputs.
    configured_job["requirement_ids"] = ["R7"]
    configured_job["verification_ids"] = ["V7"]
    monkeypatch.setenv("AI_LOOP_PROMPT_PROFILES", configured_profiles())

    worker_prompt = worker.codex_prompt(configured_job, task())
    plan = controller.plan_prompt(configured_job)
    review = controller.review_prompt(configured_job, task(), run())

    assert "WORKER PROFILE: retain a requirement-to-test map." in worker_prompt
    assert "PLAN PROFILE: create a traceable first task." in plan
    assert "REVIEW PROFILE: reject untraceable follow-up work." in review
    for prompt in (worker_prompt, plan, review):
        assert "Configured task-scoped guidance" in prompt
        assert "Profile traceable-prompt-work" in prompt
        assert '"requirement_ids": [' in prompt
        assert '"R7"' in prompt
        assert '"verification_ids": [' in prompt
        assert '"V7"' in prompt

    for prompt in (worker_prompt, review):
        assert '"goal": "Implement profiles"' in prompt
        assert '"constraints": [\n    "Append only"' in prompt
        assert '"acceptance": [\n    "Guidance appears"' in prompt
    assert '"goal": "Ship the prompt feature"' in plan
    assert '"constraints": [\n    "Keep defaults exact"' in plan
    assert '"acceptance": [\n    "All builders are covered"' in plan


def test_plan_prompt_ignores_tilde_prefixed_numeric_approximations(
    tmp_path: Path,
) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "Follow the repository instructions.\n", encoding="utf-8"
    )
    shader = tmp_path / "src" / "versions" / "simple" / "shaders"
    shader.mkdir(parents=True)
    (shader / "simple_forward.slang").write_text(
        "// forward shader guidance\n", encoding="utf-8"
    )
    configured_job = job()
    configured_job["worktree_path"] = str(tmp_path)
    configured_job["goal"] = (
        "Read `AGENTS.md` and update "
        "`src/versions/simple/shaders/simple_forward.slang`. "
        "Reduce the compare bias to `~0.0005`."
    )

    candidates = controller.referenced_file_candidates(configured_job)
    prompt = controller.plan_prompt(configured_job)

    assert "~0.0005" not in candidates
    assert candidates == [
        "AGENTS.md",
        "src/versions/simple/shaders/simple_forward.slang",
    ]
    assert controller.safe_relative_path(tmp_path, "~0.0005") is None
    assert controller.safe_relative_path(tmp_path, "~/AGENTS.md") is None
    assert "Follow the repository instructions." in prompt
    assert "// forward shader guidance" in prompt


def test_plan_prompt_survives_optional_guidance_path_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_job = job()
    configured_job["worktree_path"] = str(tmp_path)
    configured_job["goal"] = "Read `AGENTS.md` before implementation."

    def fail_path_resolution(_worktree: Path, _value: str) -> Path | None:
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(controller, "safe_relative_path", fail_path_resolution)

    prompt = controller.plan_prompt(configured_job)

    assert "Read `AGENTS.md` before implementation." in prompt
    assert "Refreshed referenced guidance files:\n[]" in prompt


def test_no_profile_preserves_exact_existing_prompt_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AI_LOOP_PROMPT_PROFILES", raising=False)
    prompts = {
        "worker": worker.codex_prompt(job(), task()),
        "plan": controller.plan_prompt(job()),
        "review": controller.review_prompt(job(), task(), run()),
    }
    # The worker prompt intentionally includes the absolute location of the
    # crash-safe launcher. Normalize only that runtime path so this byte-level
    # regression remains stable in linked worktrees and CI checkouts.
    prompts["worker"] = prompts["worker"].replace(
        str(Path(worker.__file__).resolve().parent),
        "<AI_LOOP_ROOT>",
    )

    assert {
        name: hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        for name, prompt in prompts.items()
    } == {
        "worker": "d40a411d338cec185899763adefdf365c4f1c0d8e963036191a2b0e8aa2b4509",
        "plan": "647a3aae85b3bd97c64f803f421fde5bf17789b7e992befcd558f1194d151588",
        "review": "7bef9f9e02399a254f95688591a9b86a24695735ef7b3f85399957d144896f74",
    }


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        '[{"match":{"goal_contains":"prompt"},"guidance":{"worker":"extra"}}]',
        '[{"id":"broken","match":{"unknown":"value"},"guidance":{"worker":"extra"}}]',
    ],
)
def test_missing_or_misconfigured_profile_is_audited_without_dropping_core_prompt(
    raw: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("AI_LOOP_PROMPT_PROFILES", raw)
    caplog.set_level(logging.WARNING, logger="ai_loop.prompt_profiles")

    worker_prompt = worker.codex_prompt(job(), task())
    plan = controller.plan_prompt(job())
    review = controller.review_prompt(job(), task(), run())

    assert "Overall goal:\nShip the prompt feature" in worker_prompt
    assert "This task:\nImplement profiles" in worker_prompt
    assert "Job state:" in plan
    assert "State to review:" in review
    assert "Configured task-scoped guidance" not in worker_prompt + plan + review
    assert "prompt profile audit" in caplog.text
    assert "parse" in caplog.text
