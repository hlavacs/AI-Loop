"""Pure specification coverage projected from the model's existing ``@satisfies`` tags.

Only an exact specification identifier in ``Entity.satisfies`` is implementation
evidence.  Goals have no stored identifiers in schema version 2, so their deterministic
display/tag identifiers are their one-based specification positions (``G-1``,
``G-2``, ...).  No text similarity or test-reachability inference is made.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from icoda_core.model import DerivedModel


@dataclass(frozen=True)
class ImplementingEntity:
    """Stable identity and readable name of one explicitly tagged model entity."""

    usr: str
    qualified_name: str


@dataclass(frozen=True)
class RequirementCoverage:
    """One goal or requirement and the code entities explicitly implementing it."""

    kind: str
    identifier: str
    title: str
    implementing_entities: tuple[ImplementingEntity, ...] = ()
    uncovered: bool = True


def project(specification: Mapping[str, Any], model: DerivedModel) -> tuple[RequirementCoverage, ...]:
    """Return goals and requirements in deterministic identifier order.

    Coverage means that at least one current derived-model entity has an exact
    matching identifier in its already-parsed ``@satisfies`` tags.
    """
    entities_by_tag: dict[str, list[ImplementingEntity]] = {}
    for entity in model.entities.values():
        reference = ImplementingEntity(entity.usr, entity.qualified_name)
        for tag in entity.satisfies:
            entities_by_tag.setdefault(tag, []).append(reference)

    entries: list[RequirementCoverage] = []
    goals = specification.get("goals", ())
    if isinstance(goals, Sequence) and not isinstance(goals, (str, bytes)):
        for index, goal in enumerate(goals, 1):
            identifier = f"G-{index}"
            entries.append(_coverage("goal", identifier, str(goal), entities_by_tag))

    requirements = specification.get("requirements", ())
    if isinstance(requirements, Sequence) and not isinstance(requirements, (str, bytes)):
        for requirement in requirements:
            if not isinstance(requirement, Mapping):
                continue
            identifier = str(requirement.get("id", ""))
            entries.append(_coverage(
                "requirement", identifier, str(requirement.get("title", "")), entities_by_tag))
    return tuple(sorted(entries, key=_coverage_key))


def _coverage(
    kind: str,
    identifier: str,
    title: str,
    entities_by_tag: Mapping[str, Sequence[ImplementingEntity]],
) -> RequirementCoverage:
    entities = tuple(sorted(
        set(entities_by_tag.get(identifier, ())),
        key=lambda entity: (entity.qualified_name.casefold(), entity.qualified_name, entity.usr),
    ))
    return RequirementCoverage(kind, identifier, title, entities, not entities)


def _coverage_key(entry: RequirementCoverage) -> tuple[int, int, str, str]:
    prefix, separator, suffix = entry.identifier.partition("-")
    number = int(suffix) if separator and suffix.isdigit() else 0
    return (0 if entry.kind == "goal" else 1, number, prefix, entry.identifier)
