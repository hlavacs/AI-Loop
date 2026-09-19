"""Specification schema validation and the Code Profile.

The specification is one of the two truths (with the source code). It lives in ``.icoda/specification.json``,
follows ``specification.schema.json`` (version 2: title, description, goals, what is left out, what must not be
used, when the project is done, use cases, requirements, decisions, code profile), and is sent to the LLM in the
compact text form of :func:`compact`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import jsonschema

from icoda_core import persistence

SCHEMA_PATH = Path(__file__).with_name("specification.schema.json")
SCHEMA_VERSION = 2
LIST_SECTIONS = ("goals", "out_of_scope", "not_allowed", "done_when")
RECORD_SECTIONS = {"use_cases": "UC", "requirements": "R", "decisions": "D"}
SECTION_LABELS = {"goals": "Goals", "out_of_scope": "Not in scope", "not_allowed": "Not allowed",
                  "done_when": "Done when", "use_cases": "Use cases", "requirements": "Requirements",
                  "decisions": "Decisions", "code_profile": "Code profile"}

Specification = dict[str, Any]


def default_code_profile(language: str = "C++") -> dict[str, Any]:
    if language == "Python":
        return {
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
                "Every entity carries a docstring and, where a requirement applies, an @satisfies tag.",
                "Platform independence: no platform API without a portable wrapper.",
            ],
        }
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


def default_specification(title: str, language: str = "C++") -> Specification:
    spec: Specification = {"schema_version": SCHEMA_VERSION, "title": title, "summary": ""}
    for section in LIST_SECTIONS:
        spec[section] = []
    for section in RECORD_SECTIONS:
        spec[section] = []
    spec["code_profile"] = default_code_profile(language)
    return spec


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


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
    known_use_cases = {u.get("id") for u in spec.get("use_cases", [])}
    problems = []
    for requirement in spec.get("requirements", []):
        for use_case in requirement.get("use_cases", []):
            if use_case not in known_use_cases:
                problems.append(f"Requirements {requirement.get('id')}: unknown use case {use_case}")
    for section in RECORD_SECTIONS:
        ids = [r.get("id") for r in spec.get(section, [])]
        if len(ids) != len(set(ids)):
            problems.append(f"{SECTION_LABELS[section]}: duplicate ids")
    return problems


def next_id(spec: Specification, section: str) -> str:
    prefix = RECORD_SECTIONS[section]
    numbers = [int(m.group(1)) for r in spec.get(section, [])
               if (m := re.fullmatch(rf"{prefix}-(\d+)", str(r.get("id", ""))))]
    return f"{prefix}-{max(numbers, default=0) + 1}"


def load(path: Path) -> Specification:
    """Read a specification; older versions are upgraded in memory (saved in the current version)."""
    return upgrade(json.loads(path.read_text(encoding="utf-8")))


def save(path: Path, spec: Specification) -> None:
    persistence._atomic_write_text(path, json.dumps(spec, indent=2, ensure_ascii=False) + "\n")


def upgrade(spec: Specification) -> Specification:
    """Version 1 (many sections) to version 2: goals from objectives and scope, records without extra fields.

    A version 2 file is completed in place: list sections added later start out empty.
    """
    if spec.get("schema_version", SCHEMA_VERSION) >= SCHEMA_VERSION:
        for section in LIST_SECTIONS:
            spec.setdefault(section, [])
        spec.setdefault("code_profile", default_code_profile())
        return spec
    upgraded = default_specification(str(spec.get("title", "")))
    upgraded["summary"] = str(spec.get("summary", ""))
    upgraded["goals"] = [*spec.get("objectives", []), *spec.get("in_scope", [])]
    upgraded["out_of_scope"] = list(spec.get("out_of_scope", []))
    upgraded["use_cases"] = [_keep(r, ("id", "title", "description"), actor=r.get("actor"))
                             for r in spec.get("use_cases", [])]
    upgraded["requirements"] = [_keep(r, ("id", "title", "priority", "use_cases", "description"))
                                for r in spec.get("requirements", [])]
    upgraded["decisions"] = [_keep(r, ("id", "title", "rationale")) for r in spec.get("decisions", [])]
    upgraded["code_profile"] = {**default_code_profile(), **spec.get("code_profile", {})}
    return upgraded


def _keep(record: dict[str, Any], keys: Sequence[str], actor: str | None = None) -> dict[str, Any]:
    kept = {key: record[key] for key in keys if key in record}
    if actor:
        kept["description"] = (f"Actor: {actor}. " + str(kept.get("description", ""))).strip()
    return kept


def compact(spec: Specification, sections: Sequence[str] | None = None) -> str:
    """The specification as compact text for a prompt: numbered records, one line each where possible."""
    lines = [f"# {spec.get('title', '')}", spec.get("summary", "").strip(), ""]
    for section in sections or (*LIST_SECTIONS, *RECORD_SECTIONS):
        entries = spec.get(section, [])
        if not entries:
            continue
        lines.append(f"## {SECTION_LABELS.get(section, section).lower()}")
        for entry in entries:
            lines.append(f"- {entry}" if isinstance(entry, str) else _record_line(entry))
        lines.append("")
    lines.append("## code profile")
    lines.extend(_profile_lines(spec.get("code_profile", {})))
    return "\n".join(lines).strip() + "\n"


def _record_line(record: dict[str, Any]) -> str:
    head = f"- {record.get('id', '?')}: {record.get('title', '')}"
    extras = []
    for key in ("priority", "use_cases"):
        if record.get(key):
            value = record[key]
            extras.append(f"{key}={', '.join(value) if isinstance(value, list) else value}")
    for key in ("description", "rationale"):
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
