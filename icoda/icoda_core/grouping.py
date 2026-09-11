"""Pure selection and size validation for deliberate few-line function groups."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from icoda_core.model import DerivedModel, Entity, Kind


class Mode(str, Enum):
    """Developer-selected granularity for an implementation step."""

    SINGLE_ENTITY = "single_entity"
    FEW_LINE_GROUP = "few_line_group"


GROUPING_LABELS = (
    (Mode.SINGLE_ENTITY, "One entity"),
    (Mode.FEW_LINE_GROUP, "Few-line group"),
)


@dataclass(frozen=True)
class GroupedEntity:
    """Stable identity and readable name of one accepted group member."""

    usr: str
    qualified_name: str
    lines: int


@dataclass(frozen=True)
class Result:
    """The accepted entities, profile budgets, and exact reason grouping stopped."""

    entities: tuple[GroupedEntity, ...] = ()
    max_entity_lines: int = 0
    max_total_lines: int = 0
    total_lines: int = 0
    refusal_reason: str = ""

    @property
    def grouped(self) -> bool:
        return len(self.entities) > 1 and not self.refusal_reason


def derive(
    implementation_queue: Sequence[str],
    model: DerivedModel,
    code_profile: Mapping[str, object],
) -> Result:
    """Select and validate the queue head's adjacent accessor or overload family.

    A group stays in one project-relative file and one enclosing class (file-scope
    functions share the absence of a class). Each current entity span must fit
    ``max_function_lines`` and their total must fit ``hard_max_function_lines``.
    """
    queue = tuple(implementation_queue)
    max_entity = _positive_budget(code_profile, "max_function_lines")
    max_total = _positive_budget(code_profile, "hard_max_function_lines")
    if not queue:
        return Result(max_entity_lines=max_entity, max_total_lines=max_total,
                      refusal_reason="cannot form a few-line group: the implementation queue is empty")
    head = model.entities.get(queue[0])
    if head is None:
        return Result(max_entity_lines=max_entity, max_total_lines=max_total,
                      refusal_reason=f"cannot form a few-line group: queue entity {queue[0]!r} is absent")
    single = (_grouped_entity(head),)
    if len(queue) < 2:
        return Result(single, max_entity, max_total, single[0].lines,
                      "cannot group the only remaining implementation entity")
    partner = model.entities.get(queue[1])
    if partner is None:
        return Result(single, max_entity, max_total, single[0].lines,
                      f"cannot form a few-line group: queue entity {queue[1]!r} is absent")
    refusal = _compatibility_refusal(head, partner, model)
    if refusal:
        return Result(single, max_entity, max_total, single[0].lines, refusal)

    members = [head, partner]
    for usr in queue[2:]:
        candidate = model.entities.get(usr)
        if candidate is None or _compatibility_refusal(head, candidate, model):
            break
        members.append(candidate)
    ordered = tuple(_grouped_entity(entity) for entity in sorted(members, key=_entity_key))
    oversize = next((entity for entity in ordered if entity.lines > max_entity), None)
    if oversize is not None:
        reason = (f"cannot group {oversize.qualified_name}: its {oversize.lines}-line span exceeds "
                  f"code_profile max_function_lines={max_entity}")
        return Result(single, max_entity, max_total, single[0].lines, reason)
    total = sum(entity.lines for entity in ordered)
    if total > max_total:
        names = ", ".join(entity.qualified_name for entity in ordered)
        reason = (f"cannot group {names}: total span {total} exceeds "
                  f"code_profile hard_max_function_lines={max_total}")
        return Result(single, max_entity, max_total, single[0].lines, reason)
    return Result(ordered, max_entity, max_total, total)


def _positive_budget(profile: Mapping[str, object], key: str) -> int:
    value = profile.get(key)
    try:
        return max(1, int(value)) if isinstance(value, (int, str)) else 1
    except ValueError:
        return 1


def _compatibility_refusal(head: Entity, candidate: Entity, model: DerivedModel) -> str:
    if candidate.file != head.file:
        return (f"cannot group {candidate.qualified_name} with {head.qualified_name}: "
                "entities are in different files")
    if _enclosing_class(model, candidate) != _enclosing_class(model, head):
        return (f"cannot group {candidate.qualified_name} with {head.qualified_name}: "
                "entities have different enclosing classes")
    if _family(candidate.name) != _family(head.name):
        return (f"cannot group {candidate.qualified_name} with {head.qualified_name}: "
                "entities are neither one accessor pair nor one overload set")
    return ""


def _family(name: str) -> tuple[str, str]:
    snake = re.fullmatch(r"(get|set)_([^_].*)", name)
    if snake:
        return ("accessor", snake.group(2))
    camel = re.fullmatch(r"(get|set)([A-Z].*)", name)
    if camel:
        return ("accessor", camel.group(2))
    return ("overload", name)


def _enclosing_class(model: DerivedModel, entity: Entity) -> str | None:
    parent = entity.parent
    while parent is not None:
        owner = model.entities.get(parent)
        if owner is None:
            return None
        if owner.kind in (Kind.CLASS, Kind.STRUCT):
            return owner.usr
        parent = owner.parent
    return None


def _grouped_entity(entity: Entity) -> GroupedEntity:
    lines = entity.end_line - entity.line + 1 if entity.end_line >= entity.line else 0
    return GroupedEntity(entity.usr, entity.qualified_name, lines)


def _entity_key(entity: Entity) -> tuple[str, str, str, int, str]:
    return (entity.qualified_name, entity.signature, entity.file, entity.line, entity.usr)
