"""Configuration-driven, task-scoped additions to controller and worker prompts.

``AI_LOOP_PROMPT_PROFILES`` is a JSON array of profile objects.  Each profile
has an ``id``, a ``match`` object keyed by task metadata, and a ``guidance``
object containing one or more of ``worker``, ``plan``, and ``review``.

Profiles only append guidance.  They cannot replace the built-in prompt, so a
bad or missing configuration can never remove the loop's core instructions.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence


PROMPT_PROFILES_ENV = "AI_LOOP_PROMPT_PROFILES"
PROMPT_PROFILE_STAGES = ("worker", "plan", "review")
MAX_PROMPT_PROFILES = 32
MAX_GUIDANCE_BYTES = 20_000
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromptProfile:
    """One optional guidance profile selected by task/job metadata."""

    identifier: str
    match: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    guidance: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptProfileAudit:
    profile: str
    stage: str
    error: str

    def to_dict(self) -> dict[str, str]:
        return {
            "profile": self.profile,
            "stage": self.stage,
            "error": self.error,
        }


@dataclass(frozen=True)
class LoadedPromptProfiles:
    profiles: tuple[PromptProfile, ...]
    audits: tuple[PromptProfileAudit, ...]


PromptProfileAuditSink = Callable[[PromptProfileAudit], None]

_MATCH_KEYS = {
    "goal_contains",
    "constraints_contain",
    "acceptance_contain",
    "requirement_ids_any",
    "verification_ids_any",
}


def _string_tuple(value: Any, *, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        items: Sequence[Any] = (value,)
    elif isinstance(value, list):
        items = value
    else:
        raise ValueError(f"{field_name} must be a string or array of strings")
    if any(not isinstance(item, str) or not item.strip() for item in items):
        raise ValueError(f"{field_name} must contain only non-empty strings")
    return tuple(item.strip() for item in items)


def parse_prompt_profile_config(raw: str | None = None) -> tuple[PromptProfile, ...]:
    """Parse the bounded prompt-profile registry from configuration."""

    value = os.getenv(PROMPT_PROFILES_ENV, "") if raw is None else raw
    if not value.strip():
        return ()
    payload = json.loads(value)
    if not isinstance(payload, list):
        raise ValueError(f"{PROMPT_PROFILES_ENV} must be a JSON array")
    if len(payload) > MAX_PROMPT_PROFILES:
        raise ValueError(
            f"{PROMPT_PROFILES_ENV} may configure at most {MAX_PROMPT_PROFILES} profiles"
        )

    profiles: list[PromptProfile] = []
    identifiers: set[str] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise ValueError(f"prompt profile entry {index} must be an object")
        if item.get("enabled", True) is False:
            continue
        identifier = str(item.get("id", "")).strip()
        if not identifier:
            raise ValueError(f"prompt profile entry {index} requires id")
        if identifier in identifiers:
            raise ValueError(f"duplicate prompt profile id: {identifier}")

        raw_match = item.get("match", {})
        if not isinstance(raw_match, Mapping):
            raise ValueError(f"prompt profile {identifier} match must be an object")
        unknown_match = sorted(set(raw_match) - _MATCH_KEYS)
        if unknown_match:
            raise ValueError(
                f"prompt profile {identifier} has unknown match fields: "
                + ", ".join(unknown_match)
            )
        match = {
            str(key): _string_tuple(
                value, field_name=f"prompt profile {identifier} match.{key}"
            )
            for key, value in raw_match.items()
        }

        raw_guidance = item.get("guidance")
        if not isinstance(raw_guidance, Mapping):
            raise ValueError(f"prompt profile {identifier} guidance must be an object")
        unknown_stages = sorted(set(raw_guidance) - set(PROMPT_PROFILE_STAGES))
        if unknown_stages:
            raise ValueError(
                f"prompt profile {identifier} has unknown guidance stages: "
                + ", ".join(unknown_stages)
            )
        guidance: dict[str, str] = {}
        for stage, text in raw_guidance.items():
            if not isinstance(text, str) or not text.strip():
                raise ValueError(
                    f"prompt profile {identifier} guidance.{stage} must be a non-empty string"
                )
            normalized = text.strip()
            if len(normalized.encode("utf-8")) > MAX_GUIDANCE_BYTES:
                raise ValueError(
                    f"prompt profile {identifier} guidance.{stage} exceeds "
                    f"{MAX_GUIDANCE_BYTES} bytes"
                )
            guidance[str(stage)] = normalized
        if not guidance:
            raise ValueError(
                f"prompt profile {identifier} requires at least one guidance stage"
            )
        identifiers.add(identifier)
        profiles.append(PromptProfile(identifier, match, guidance))
    return tuple(profiles)


def load_prompt_profiles(
    raw: str | None = None,
    *,
    audit: PromptProfileAuditSink | None = None,
) -> LoadedPromptProfiles:
    """Load configured profiles; malformed configuration is audited and ignored."""

    audits: list[PromptProfileAudit] = []

    def report(item: PromptProfileAudit) -> None:
        audits.append(item)
        if audit is not None:
            audit(item)

    try:
        profiles = parse_prompt_profile_config(raw)
    except Exception as exc:
        report(
            PromptProfileAudit(
                "configuration", "parse", f"{type(exc).__name__}: {exc}"
            )
        )
        profiles = ()
    return LoadedPromptProfiles(profiles, tuple(audits))


def _metadata_values(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value)
    return (str(value),)


def task_prompt_metadata(job: Mapping[str, Any], task: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the exact task input represented at this prompt stage.

    PLAN has no persisted task yet, so its task input is the job's goal,
    constraints, acceptance criteria, and any traceability IDs supplied by a
    caller.  Worker and REVIEW stages use the persisted task values.
    """

    source = task if task is not None else job
    return {
        "goal": str(source.get("goal") or ""),
        "constraints": list(_metadata_values(source.get("constraints"))),
        "acceptance": list(_metadata_values(source.get("acceptance"))),
        "requirement_ids": list(_metadata_values(source.get("requirement_ids"))),
        "verification_ids": list(_metadata_values(source.get("verification_ids"))),
    }


def _profile_matches(
    profile: PromptProfile,
    job: Mapping[str, Any],
    task: Mapping[str, Any] | None,
) -> bool:
    task_metadata = task_prompt_metadata(job, task)
    job_metadata = task_prompt_metadata(job, None)
    goals = (task_metadata["goal"], job_metadata["goal"])
    constraints = (*task_metadata["constraints"], *job_metadata["constraints"])
    acceptance = (*task_metadata["acceptance"], *job_metadata["acceptance"])
    requirement_ids = {
        *task_metadata["requirement_ids"],
        *job_metadata["requirement_ids"],
    }
    verification_ids = {
        *task_metadata["verification_ids"],
        *job_metadata["verification_ids"],
    }
    for key, candidates in profile.match.items():
        if key == "goal_contains" and not any(
            candidate.casefold() in goal.casefold()
            for candidate in candidates
            for goal in goals
        ):
            return False
        if key == "constraints_contain" and not any(
            candidate.casefold() in value.casefold()
            for candidate in candidates
            for value in constraints
        ):
            return False
        if key == "acceptance_contain" and not any(
            candidate.casefold() in value.casefold()
            for candidate in candidates
            for value in acceptance
        ):
            return False
        if key == "requirement_ids_any" and requirement_ids.isdisjoint(candidates):
            return False
        if key == "verification_ids_any" and verification_ids.isdisjoint(candidates):
            return False
    return True


def configured_prompt_guidance(
    stage: str,
    job: Mapping[str, Any],
    task: Mapping[str, Any] | None = None,
    *,
    raw: str | None = None,
    audit: PromptProfileAuditSink | None = None,
) -> str:
    """Render matching additions, or an empty string for the exact default."""

    if stage not in PROMPT_PROFILE_STAGES:
        raise ValueError(f"unknown prompt profile stage: {stage}")

    def report(item: PromptProfileAudit) -> None:
        if audit is not None:
            audit(item)
        else:
            LOGGER.warning("prompt profile audit: %s", item.to_dict())

    loaded = load_prompt_profiles(raw, audit=report)
    selected = [
        profile
        for profile in loaded.profiles
        if stage in profile.guidance and _profile_matches(profile, job, task)
    ]
    if not selected:
        return ""

    metadata = json.dumps(task_prompt_metadata(job, task), indent=2)
    sections = [
        f"Profile {profile.identifier}:\n{profile.guidance[stage]}"
        for profile in selected
    ]
    return (
        "\nConfigured task-scoped guidance:\n\n"
        + "\n\n".join(sections)
        + "\n\nTask metadata for this guidance:\n"
        + metadata
        + "\n"
    )
