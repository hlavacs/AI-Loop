"""Specification schema validation and the Code Profile.

The specification is one of the two truths (with the source code). It lives in ``.icoda/specification.json``,
follows ``specification.schema.json``, and is sent to the LLM in the compact text form of :func:`compact`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import jsonschema

SCHEMA_PATH = Path(__file__).with_name("specification.schema.json")
LIST_SECTIONS = ("objectives", "in_scope", "out_of_scope", "stakeholders", "assumptions", "constraints",
                 "dependencies", "open_questions")
RECORD_SECTIONS = {"use_cases": "UC", "requirements": "R", "decisions": "D", "risks": "RK", "verification": "V"}

Specification = dict[str, Any]


def default_code_profile() -> dict[str, Any]:
    return {
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
            "Prefer STL algorithms to hand-written loops; lambdas where they make sense; templates for reuse.",
            "Every entity carries a Doxygen comment with @brief and, where a requirement applies, @satisfies.",
            "Platform independence: no platform API without a portable wrapper.",
        ],
    }


def default_specification(title: str) -> Specification:
    spec: Specification = {"schema_version": 1, "title": title, "summary": ""}
    for section in LIST_SECTIONS:
        spec[section] = []
    for section in RECORD_SECTIONS:
        spec[section] = []
    spec["code_profile"] = default_code_profile()
    return spec


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


SECTION_LABELS = {"use_cases": "Use cases", "requirements": "Requirements", "decisions": "Decisions",
                  "risks": "Risks", "verification": "Verification", "code_profile": "Code profile"}


def validate(spec: Specification) -> list[str]:
    """Human-readable problems; an empty list means the specification is valid."""
    validator = jsonschema.Draft202012Validator(load_schema())
    problems = []
    for error in sorted(validator.iter_errors(spec), key=lambda e: [str(p) for p in e.absolute_path]):
        problems.append(describe_problem(spec, error))
    problems.extend(_cross_reference_problems(spec))
    return problems


def describe_problem(spec: Specification, error: jsonschema.ValidationError) -> str:
    """``Use cases UC-1: title is missing`` rather than a JSON pointer, where the schema error allows it."""
    parts = [str(p) for p in error.absolute_path]
    where = "/".join(parts) or "(root)"
    if error.validator == "required":
        missing = str(error.message).split("'")[1] if "'" in str(error.message) else "a field"
        return f"{_place(spec, parts)}: {missing} is missing"
    if error.validator == "minLength":
        return f"{_place(spec, parts[:-1])}: {parts[-1] if parts else 'value'} must not be empty"
    return f"{where}: {error.message}"


def _place(spec: Specification, parts: list[str]) -> str:
    """Where a problem is, in the words of the editor: the section and the record id."""
    if not parts:
        return "Overview"
    label = SECTION_LABELS.get(parts[0], parts[0].replace("_", " ").capitalize())
    if len(parts) >= 2 and parts[1].isdigit():
        records = spec.get(parts[0], [])
        index = int(parts[1])
        record_id = records[index].get("id", "") if index < len(records) and isinstance(records[index], dict) else ""
        return f"{label} {record_id or '#' + str(index + 1)}"
    return label


def _cross_reference_problems(spec: Specification) -> list[str]:
    known_requirements = {r.get("id") for r in spec.get("requirements", [])}
    known_use_cases = {u.get("id") for u in spec.get("use_cases", [])}
    problems = []
    for entry in spec.get("verification", []):
        if entry.get("requirement") not in known_requirements:
            problems.append(f"verification {entry.get('id')}: unknown requirement {entry.get('requirement')}")
    for requirement in spec.get("requirements", []):
        for use_case in requirement.get("use_cases", []):
            if use_case not in known_use_cases:
                problems.append(f"requirement {requirement.get('id')}: unknown use case {use_case}")
    for section in RECORD_SECTIONS:
        ids = [r.get("id") for r in spec.get(section, [])]
        if len(ids) != len(set(ids)):
            problems.append(f"{section}: duplicate ids")
    return problems


def next_id(spec: Specification, section: str) -> str:
    prefix = RECORD_SECTIONS[section]
    numbers = [int(m.group(1)) for r in spec.get(section, [])
               if (m := re.fullmatch(rf"{prefix}-(\d+)", str(r.get("id", ""))))]
    return f"{prefix}-{max(numbers, default=0) + 1}"


def load(path: Path) -> Specification:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, spec: Specification) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def compact(spec: Specification, sections: Sequence[str] | None = None) -> str:
    """The specification as compact text for a prompt: numbered records, one line each where possible."""
    lines = [f"# {spec.get('title', '')}", spec.get("summary", "").strip(), ""]
    for section in sections or (*LIST_SECTIONS[:-1], *RECORD_SECTIONS, "open_questions"):
        entries = spec.get(section, [])
        if not entries:
            continue
        lines.append(f"## {section.replace('_', ' ')}")
        for entry in entries:
            lines.append(f"- {entry}" if isinstance(entry, str) else _record_line(entry))
        lines.append("")
    lines.append("## code profile")
    lines.extend(_profile_lines(spec.get("code_profile", {})))
    return "\n".join(lines).strip() + "\n"


def _record_line(record: dict[str, Any]) -> str:
    head = f"- {record.get('id', '?')}: {record.get('title', record.get('requirement', ''))}"
    extras = []
    for key in ("actor", "priority", "category", "severity", "method", "use_cases"):
        if record.get(key):
            value = record[key]
            extras.append(f"{key}={', '.join(value) if isinstance(value, list) else value}")
    for key in ("description", "rationale", "mitigation"):
        if record.get(key):
            extras.append(str(record[key]).strip())
    return head + (" — " + "; ".join(extras) if extras else "")


def _profile_lines(profile: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, value in profile.items():
        if key == "style_notes":
            lines.extend(f"- {note}" for note in value)
        else:
            lines.append(f"- {key.replace('_', ' ')}: {', '.join(value) if isinstance(value, list) else value}")
    return lines
