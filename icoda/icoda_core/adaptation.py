"""Pure, deterministic editing support for a proposal's structured entity summary."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

ENTITY_KINDS = (
    "module", "namespace", "struct", "class", "enum", "function", "method", "alias", "variable",
)
FIELDS = ("name", "kind", "file", "signature", "satisfies")
NO_USABLE_PROPOSAL = "Structured adaptation is unavailable because there is no usable proposal."
NO_ENTITY_SUMMARY = "Structured adaptation is unavailable because this proposal has no entity summary."
HISTORICAL_UNAVAILABLE = "Structured adaptation is unavailable for historical step-log records."
UNCHANGED_SUMMARY = "The structured entity summary is unchanged."
INSTRUCTION_PREFIX = "Correct the proposal's structured entity summary: "


@dataclass(frozen=True)
class EntitySummary:
    """One immutable, normalized entity in the provider's optional summary."""

    name: str
    kind: str
    file: str = ""
    signature: str = ""
    satisfies: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParseResult:
    """Parsed entities or deterministic, developer-readable problems."""

    entities: tuple[EntitySummary, ...] = ()
    problems: tuple[str, ...] = ()


def from_mapping(value: Mapping[str, Any]) -> EntitySummary:
    """Normalize a schema-validated response entity."""
    satisfies = value.get("satisfies", ())
    return EntitySummary(
        str(value["name"]), str(value["kind"]), str(value.get("file", "")),
        str(value.get("signature", "")), tuple(str(item) for item in satisfies),
    )


def render_summary(entities: Sequence[EntitySummary]) -> str:
    """Render canonical editable JSON with stable entity and field ordering."""
    values = [_as_dict(entity) for entity in entities]
    return json.dumps(values, ensure_ascii=False, indent=2) + "\n"


def parse_summary(text: str) -> ParseResult:
    """Parse edited canonical text without raising on ordinary developer mistakes."""
    if not text.strip():
        return ParseResult(problems=("summary: enter a JSON array of entities",))
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        problem = f"summary: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        return ParseResult(problems=(problem,))
    if not isinstance(value, list):
        return ParseResult(problems=("summary: must be a JSON array",))
    entities: list[EntitySummary] = []
    problems: list[str] = []
    for index, item in enumerate(value, 1):
        entity, item_problems = _parse_entity(index, item)
        problems.extend(item_problems)
        if entity is not None:
            entities.append(entity)
    return ParseResult(tuple(entities) if not problems else (), tuple(problems))


def describe_changes(before: Sequence[EntitySummary], after: Sequence[EntitySummary]) -> str:
    """Describe positional edits in a stable order for the existing prompt feedback channel."""
    changes: list[str] = []
    shared = min(len(before), len(after))
    for index in range(shared):
        for field in FIELDS:
            old, new = getattr(before[index], field), getattr(after[index], field)
            if old != new:
                changes.append(f"entity {index + 1} {field} changed from {_shown(old)} to {_shown(new)}")
    for index in range(shared, len(before)):
        changes.append(f"entity {index + 1} removed ({_compact(before[index])})")
    for index in range(shared, len(after)):
        changes.append(f"entity {index + 1} added ({_compact(after[index])})")
    return INSTRUCTION_PREFIX + "; ".join(changes) + "." if changes else UNCHANGED_SUMMARY


def problems_text(problems: Sequence[str]) -> str:
    """One owning presentation for parse failures shown by the panel and status bar."""
    return "Structured entity summary is not usable: " + "; ".join(problems)


def _parse_entity(index: int, value: Any) -> tuple[EntitySummary | None, tuple[str, ...]]:
    if not isinstance(value, dict):
        return None, (f"entity {index}: must be an object",)
    problems = [f"entity {index}: unknown field {field!r}" for field in sorted(set(value) - set(FIELDS))]
    name = _required_string(index, "name", value, problems)
    kind = _required_string(index, "kind", value, problems)
    if kind and kind not in ENTITY_KINDS:
        problems.append(f"entity {index}/kind: must be one of {', '.join(ENTITY_KINDS)}")
    file = _optional_string(index, "file", value, problems)
    signature = _optional_string(index, "signature", value, problems)
    satisfies = _satisfies(index, value, problems)
    if problems:
        return None, tuple(problems)
    return EntitySummary(name, kind, file, signature, satisfies), ()


def _required_string(index: int, field: str, value: Mapping[str, Any], problems: list[str]) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        problems.append(f"entity {index}/{field}: must be a non-empty string")
        return ""
    return item


def _optional_string(index: int, field: str, value: Mapping[str, Any], problems: list[str]) -> str:
    item = value.get(field, "")
    if not isinstance(item, str):
        problems.append(f"entity {index}/{field}: must be a string")
        return ""
    return item


def _satisfies(index: int, value: Mapping[str, Any], problems: list[str]) -> tuple[str, ...]:
    items = value.get("satisfies", [])
    if not isinstance(items, list):
        problems.append(f"entity {index}/satisfies: must be an array of strings")
        return ()
    result: list[str] = []
    for item_index, item in enumerate(items, 1):
        if not isinstance(item, str) or not item.strip():
            problems.append(f"entity {index}/satisfies/{item_index}: must be a non-empty string")
        else:
            result.append(item)
    return tuple(result)


def _as_dict(entity: EntitySummary) -> dict[str, Any]:
    return {"name": entity.name, "kind": entity.kind, "file": entity.file,
            "signature": entity.signature, "satisfies": list(entity.satisfies)}


def _compact(entity: EntitySummary) -> str:
    return json.dumps(_as_dict(entity), ensure_ascii=False, separators=(",", ":"))


def _shown(value: str | tuple[str, ...]) -> str:
    return json.dumps(list(value) if isinstance(value, tuple) else value, ensure_ascii=False)
