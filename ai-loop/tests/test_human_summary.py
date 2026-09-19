from __future__ import annotations

from ai_loop.human_summary import human_text, status_summary, task_summary


def details(*, status: str = "implementing") -> dict[str, object]:
    return {
        "job": {"id": "J-private", "status": status},
        "percent": 42,
        "remaining": 600,
        "runs": [],
    }


def current_task() -> dict[str, object]:
    return {
        "id": "T-secret",
        "iteration": 7,
        "status": "running",
        "updated_at": "2026-09-19T12:34:56Z",
        "goal": "Improve the export flow",
        "constraints": ["Preserve existing files", "Avoid unrelated changes"],
        "acceptance": [
            "Exports finish successfully",
            "Existing projects continue to open",
            "Every internal diagnostic field has an exact value",
        ],
        "test_cmd": "pytest -q tests/test_export.py",
    }


def test_task_summary_keeps_outcome_but_omits_internal_details() -> None:
    rendered = task_summary(details(), current_task())

    assert "carrying out this task now" in rendered
    assert "Improve the export flow" in rendered
    assert "Exports finish successfully" in rendered
    assert "2 recorded instructions" in rendered
    assert "T-secret" not in rendered
    assert "2026-09-19" not in rendered
    assert "pytest" not in rendered
    assert "Every internal diagnostic field" not in rendered


def test_status_summary_is_prose_and_only_surfaces_actionable_health() -> None:
    rendered = status_summary(
        details(),
        current_task(),
        [],
        remaining_text="10 minutes",
    )

    assert "worker is making the requested changes" in rendered
    assert "estimated at 42%" in rendered
    assert "estimated time remaining is 10 minutes" in rendered
    assert "current focus is to Improve the export flow" in rendered
    assert "No action is needed right now" in rendered
    assert "J-private" not in rendered
    assert "Redis" not in rendered
    assert "Process:" not in rendered


def test_status_summary_shows_one_clear_problem_and_next_step() -> None:
    rendered = status_summary(
        details(status="human_needed"),
        None,
        [
            ("A credential has expired.", "Sign in again, then resume the job."),
            ("Worker is stopped.", "Restart it."),
        ],
        remaining_text="unknown",
    )

    assert "Attention is needed: A credential has expired." in rendered
    assert "Suggested next step: Sign in again, then resume the job." in rendered
    assert "1 additional warnings" in rendered
    assert "Worker is stopped" not in rendered


def test_structured_model_text_is_reduced_to_its_description() -> None:
    raw = '{"verification_id":"VT1","description":"The export remains compatible.","metrics":{"count":3}}'

    assert human_text(raw) == "The export remains compatible."


def test_task_summary_explains_when_no_task_is_active() -> None:
    assert "job is complete" in task_summary(details(status="done"), None)
