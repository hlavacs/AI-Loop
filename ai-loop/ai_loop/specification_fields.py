"""ICODA-compatible specification fields, independent of either application's UI."""

from __future__ import annotations

import copy
from typing import Any, Mapping

CODE_PROFILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["language", "standard"],
    "properties": {
        "language": {"enum": ["C++", "Python"]},
        "standard": {"type": "string"},
        "modules": {"type": "boolean"},
        "build": {"type": "string"},
        "platforms": {
            "type": "array",
            "items": {"enum": ["macOS", "Linux", "Windows"]},
        },
        "test_framework": {"type": "string"},
        "test_runner": {"type": "string"},
        "test_file_convention": {"type": "string"},
        "source_file_extension": {"type": "string"},
        "module_naming": {"type": "string"},
        "class_naming": {"type": "string"},
        "function_naming": {"type": "string"},
        "library_policy": {"type": "string"},
        "max_function_lines": {"type": "integer", "minimum": 1},
        "hard_max_function_lines": {"type": "integer", "minimum": 1},
        "max_data_members": {"type": "integer", "minimum": 1},
        "max_methods": {"type": "integer", "minimum": 1},
        "style_notes": {"type": "array", "items": {"type": "string"}},
    },
}

_DEFAULT_PROFILES: dict[str, dict[str, Any]] = {
    "C++": {
        "language": "C++",
        "standard": "23",
        "modules": True,
        "build": "CMake with Ninja; presets debug and release; build/ for artefacts, bin/ for binaries",
        "platforms": ["macOS", "Linux", "Windows"],
        "test_framework": "doctest",
        "library_policy": "vcpkg manifest; single-header libraries vendored under third_party/",
        "max_function_lines": 30,
        "hard_max_function_lines": 50,
        "max_data_members": 10,
        "max_methods": 15,
        "style_notes": [
            "Prefer STL algorithms to hand-written loops; lambdas where they make sense; "
            "templates for reuse.",
            "Every entity carries a Doxygen comment with @brief and, where a requirement "
            "applies, @satisfies.",
            "Platform independence: no platform API without a portable wrapper.",
            "Place all example and demo source files in the project-root examples/ "
            "directory; use examples/<name>/ for multi-file examples. Keep reusable "
            "library code in src/ and have examples use it.",
        ],
    },
    "Python": {
        "language": "Python",
        "standard": "3.12",
        "modules": False,
        "build": "Python source; no compilation step",
        "platforms": ["macOS", "Linux", "Windows"],
        "test_framework": "pytest",
        "test_runner": "python -m pytest",
        "test_file_convention": "tests/test_<module>.py",
        "source_file_extension": ".py",
        "module_naming": "snake_case",
        "class_naming": "PascalCase",
        "function_naming": "snake_case",
        "library_policy": "PyPI dependencies declared in pyproject.toml",
        "max_function_lines": 30,
        "hard_max_function_lines": 50,
        "max_data_members": 10,
        "max_methods": 15,
        "style_notes": [
            "Use type annotations for public functions and methods.",
            "Every entity carries a docstring and, where a requirement applies, an "
            "@satisfies tag.",
            "Platform independence: no platform API without a portable wrapper.",
            "Place all example and demo source files in the project-root examples/ "
            "directory; use examples/<name>/ for multi-file examples. Keep reusable "
            "library code in src/ and have examples use it.",
        ],
    },
}


def default_code_profile(language: str = "C++") -> dict[str, Any]:
    return copy.deepcopy(_DEFAULT_PROFILES[language])


def code_profile_problems(profile: Any) -> list[tuple[str, str]]:
    if not isinstance(profile, dict):
        return [("code_profile", "must be an object")]
    problems = []
    properties = CODE_PROFILE_SCHEMA["properties"]
    for key in set(profile) - set(properties):
        problems.append((f"code_profile.{key}", "unknown code profile field"))
    for key in CODE_PROFILE_SCHEMA["required"]:
        if key not in profile:
            problems.append((f"code_profile.{key}", "is required"))
    for key, value in profile.items():
        if key not in properties:
            continue
        rule = properties[key]
        path = f"code_profile.{key}"
        kind = rule.get("type")
        if "enum" in rule and value not in rule["enum"]:
            problems.append((path, "must be one of: " + ", ".join(rule["enum"])))
        elif kind == "string" and not isinstance(value, str):
            problems.append((path, "must be text"))
        elif kind == "boolean" and not isinstance(value, bool):
            problems.append((path, "must be true or false"))
        elif kind == "integer" and (type(value) is not int or value < 1):
            problems.append((path, "must be a positive integer"))
        elif kind == "array":
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                problems.append((path, "must be a list of text items"))
            elif "enum" in rule["items"] and any(
                item not in rule["items"]["enum"] for item in value
            ):
                problems.append((path, "contains an unsupported platform"))
    return problems


def profile_instructions(profile: Mapping[str, Any]) -> list[str]:
    instructions = []
    for key, value in profile.items():
        rendered = (
            "; ".join(str(item) for item in value)
            if isinstance(value, list)
            else str(value)
        )
        instructions.append(f"[Code profile: {key.replace('_', ' ')}] {rendered}")
    return instructions


CORE_ROOT_FIELDS = frozenset(
    (
        "schema_version",
        "title",
        "summary",
        "goals",
        "out_of_scope",
        "not_allowed",
        "done_when",
        "use_cases",
        "requirements",
        "decisions",
        "code_profile",
    )
)
LEGACY_ROOT_DEFAULTS: dict[str, list[Any]] = {
    key: []
    for key in (
        "objectives",
        "in_scope",
        "stakeholders",
        "assumptions",
        "constraints",
        "dependencies",
        "risks",
        "verification",
        "open_questions",
    )
}
LEGACY_RECORD_DEFAULTS: dict[str, dict[str, Any]] = {
    "use_cases": {
        "actors": [],
        "preconditions": [],
        "trigger": "",
        "main_flow": [],
        "alternate_flows": [],
        "postconditions": [],
        "error_and_edge_cases": [],
        "requirement_ids": [],
    },
    "requirements": {
        "category": "functional",
        "statement": "",
        "rationale": "",
        "acceptance_criteria": [],
        "source": "",
    },
    "decisions": {
        "topic": "",
        "selected_decision": "",
        "rationale": "",
        "rejected_alternatives": [],
        "consequences": [],
    },
}


def expand_aligned_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Add empty execution/legacy fields to a 1.1 authoring document."""
    result = {**copy.deepcopy(LEGACY_ROOT_DEFAULTS), **copy.deepcopy(dict(record))}
    for group, defaults in LEGACY_RECORD_DEFAULTS.items():
        if isinstance(result.get(group), list):
            result[group] = [
                {**copy.deepcopy(defaults), **item} if isinstance(item, dict) else item
                for item in result[group]
            ]
    return result


def editor_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Upgrade an editable copy; never alter stored revisions or their hashes.

    No code profile is inferred for legacy projects: they must explicitly choose
    their language and conventions before approving the upgraded draft.
    """
    result = copy.deepcopy(dict(record))
    if result.get("schema_version") == "1.0":
        result["schema_version"] = "1.1"
        result["goals"] = list(result.get("objectives", []))
        result["not_allowed"] = []
        result["done_when"] = []
        result["code_profile"] = {"language": "", "standard": ""}
        for use_case in result["use_cases"]:
            use_case["description"] = "\n".join(use_case.get("main_flow", []))
        for requirement in result["requirements"]:
            requirement["description"] = requirement.get("statement", "")
            requirement["use_cases"] = [
                use_case["id"]
                for use_case in result["use_cases"]
                if requirement["id"] in use_case.get("requirement_ids", [])
            ]
        occupied = {
            item.get("id")
            for group in ("use_cases", "requirements", "risks", "verification")
            for item in result[group]
        }
        for decision in result["decisions"]:
            number = 1
            while f"D-{number}" in occupied:
                number += 1
            decision["id"] = f"D-{number}"
            occupied.add(decision["id"])
            decision["title"] = decision.get("selected_decision") or decision.get(
                "topic", ""
            )
    return expand_aligned_record(result)
