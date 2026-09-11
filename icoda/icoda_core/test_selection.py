"""Select previously known tests that reach an implementation target."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from icoda_core.model import DerivedModel, Entity
from icoda_core.steplog import StepLog, StepRecord


def select_tests(model: DerivedModel, log: StepLog | Iterable[StepRecord], target_usr: str) -> tuple[str, ...]:
    """Return known test files or identifiers with a call path to ``target_usr``."""
    if target_usr not in model.entities:
        return ()
    reachable = caller_reachable(model, target_usr)
    records = log.records() if isinstance(log, StepLog) else log
    candidates = _log_candidates(records)
    candidates.extend(model_test_identifiers(model))
    selected: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen and identifier_reaches(model, candidate, reachable):
            selected.append(candidate)
        seen.add(candidate)
    return tuple(selected)


def command(test_command: Sequence[str], selection: Sequence[str]) -> tuple[str, ...]:
    """Append a non-empty targeted selection, preserving the full command as the fallback."""
    configured = tuple(test_command)
    return (*configured, *selection) if selection else configured


def caller_reachable(model: DerivedModel, target_usr: str) -> set[str]:
    """Return ``target_usr`` and every callable that reaches it through call edges."""
    reachable = {target_usr}
    pending = [target_usr]
    while pending:
        for edge in model.callers(pending.pop()):
            if edge.source not in reachable:
                reachable.add(edge.source)
                pending.append(edge.source)
    return reachable


def _log_candidates(records: Iterable[StepRecord]) -> list[str]:
    candidates: list[str] = []
    for record in records:
        candidates.extend(record_test_identifiers(record))
    return candidates


def record_test_identifiers(record: StepRecord) -> tuple[str, ...]:
    """Return the test identifiers named by one record, using selection's existing heuristics."""
    paths = (path for path in (*record.expected_files, *record.files) if _looks_like_test_file(path))
    return (*record.selected_tests, *paths)


def model_test_identifiers(model: DerivedModel) -> tuple[str, ...]:
    """Return stable test identifiers discoverable from a derived model."""
    candidates: set[str] = set()
    for entity in model.entities.values():
        if _looks_like_test_file(entity.file):
            candidates.add(entity.file)
        elif _looks_like_test_name(entity):
            candidates.add(entity.qualified_name)
    return tuple(sorted(candidates))


def identifier_reaches(model: DerivedModel, candidate: str, reachable: set[str]) -> bool:
    """Whether ``candidate`` identifies a callable in a precomputed caller-reachable set."""
    return any(entity.usr in reachable and _matches(candidate, entity) for entity in model.entities.values())


def _matches(candidate: str, entity: Entity) -> bool:
    normalized = candidate.replace("\\", "/")
    return normalized == entity.file.replace("\\", "/") or candidate in {
        entity.usr, entity.name, entity.qualified_name,
    }


def _looks_like_test_file(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    parts = normalized.split("/")
    stem = parts[-1].rsplit(".", 1)[0]
    return stem in ("test", "tests") or any(part in ("test", "tests") for part in parts[:-1]) \
        or stem.startswith("test_") \
        or stem.endswith(("_test", "_tests"))


def _looks_like_test_name(entity: Entity) -> bool:
    name = entity.name.lower()
    return name.startswith("test_") or name.endswith(("_test", "_tests"))
