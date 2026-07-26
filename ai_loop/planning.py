"""Immutable high-level job plans and task-granularity policy."""

from __future__ import annotations

import re


GRANULARITIES = ("fine", "normal", "coarse")


def normalize_granularity(value: str) -> str:
    granularity = value.strip().lower()
    if granularity not in GRANULARITIES:
        raise ValueError(
            f"unknown granularity: {value!r}; expected one of {GRANULARITIES}"
        )
    return granularity


def _goal_summary(goal: str, limit: int = 240) -> str:
    summary = re.sub(r"\s+", " ", goal).strip()
    if len(summary) <= limit:
        return summary
    return summary[: limit - 1].rstrip() + "…"


def build_static_plan(
    goal: str,
    acceptance: list[str],
    test_cmd: str,
) -> list[str]:
    """Create the immutable, high-level plan stored at job creation."""

    acceptance_summary = "; ".join(item.strip() for item in acceptance if item.strip())
    if len(acceptance_summary) > 240:
        acceptance_summary = acceptance_summary[:239].rstrip() + "…"
    return [
        "Inspect the repository, its local instructions, and the current implementation before changing it.",
        f"Implement the requested outcome: {_goal_summary(goal)}",
        f"Validate the result with `{test_cmd}` and focused checks for the changed behavior.",
        (
            "Review the complete result against the acceptance criteria"
            + (f": {acceptance_summary}" if acceptance_summary else ".")
        ),
    ]


def granularity_constraints(granularity: str) -> list[str]:
    granularity = normalize_granularity(granularity)
    if granularity == "fine":
        return [
            "Use focused tasklets with one narrow objective and a clear stop point.",
            "Split at natural file or behavior boundaries so the controller retains close control.",
        ]
    if granularity == "coarse":
        return [
            "Use a small number of substantial, coherent tasks that combine related discovery, implementation, documentation, and verification.",
            "Do not split work per file or function; split only at genuine architectural or risk boundaries.",
            "Preserve code quality and test coverage while minimizing controller/worker round trips.",
        ]
    return [
        "Use medium-sized coherent tasks with one outcome and a testable stop point.",
        "Group closely related changes, but split independent features or risky migrations.",
    ]


def replace_granularity_constraints(
    constraints: list[str],
    granularity: str,
) -> list[str]:
    policies = {
        item
        for choice in GRANULARITIES
        for item in granularity_constraints(choice)
    }
    retained = [item for item in constraints if item not in policies]
    return [*granularity_constraints(granularity), *retained]
