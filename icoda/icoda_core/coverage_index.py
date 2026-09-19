"""Pure recorded-test reachability projection from the derived model and step log."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from icoda_core import test_selection
from icoda_core.model import CALLABLE_KINDS, DerivedModel, EdgeKind, Entity
from icoda_core.steplog import APPROACH_ROUND, StepLog, StepRecord


@dataclass(frozen=True)
class CoverageEvidence:
    """One successful step-log entry whose named test identifiers structurally reach a callable."""

    step: int
    title: str
    time: str
    tests: tuple[str, ...]


@dataclass(frozen=True)
class CoverageEntry:
    """The stable recorded-test reachability row for one analysed callable entity."""

    usr: str
    qualified_name: str
    signature: str
    file: str
    line: int
    evidence: tuple[CoverageEvidence, ...] = ()
    tests: tuple[str, ...] = ()

    @property
    def covered(self) -> bool:
        return bool(self.evidence)


@dataclass(frozen=True)
class CoverageIndex:
    """All analysed callable rows and the subset with no recorded reaching test identifier."""

    entries: tuple[CoverageEntry, ...] = ()
    uncovered: tuple[str, ...] = ()

    @property
    def covered(self) -> tuple[str, ...]:
        return tuple(entry.usr for entry in self.entries if entry.covered)

    def entry_map(self) -> dict[str, CoverageEntry]:
        return {entry.usr: entry for entry in self.entries}


def build_index(model: DerivedModel,
                log: StepLog | Iterable[StepRecord]) -> CoverageIndex:
    """Map analysed callables to successful records and structurally reaching test identifiers.

    The index projects recorded identifiers through the model's static call edges. It does
    not execute tests or measure assertions, runtime behavior, statements, or branches.
    """
    records = log.records() if isinstance(log, StepLog) else list(log)
    successful = sorted(_successful_records(records), key=_record_key)
    candidates_by_record = [
        (record, tuple(sorted(set(test_selection.record_test_identifiers(record)))))
        for record in successful
    ]
    reachable_by_candidate = _candidate_reachability(
        model, (candidate for _record, candidates in candidates_by_record for candidate in candidates))
    evidence_by_usr: dict[str, list[CoverageEvidence]] = {}
    for record, candidates in candidates_by_record:
        tests_by_usr: dict[str, set[str]] = {}
        for candidate in candidates:
            for usr in reachable_by_candidate[candidate]:
                tests_by_usr.setdefault(usr, set()).add(candidate)
        for usr, tests in tests_by_usr.items():
            evidence_by_usr.setdefault(usr, []).append(CoverageEvidence(
                record.number, record.title, record.time, tuple(sorted(tests))))
    entries = tuple(_entry(entity, evidence_by_usr.get(entity.usr, ()))
                    for entity in sorted(_callables(model), key=_entity_key))
    return CoverageIndex(entries, tuple(entry.usr for entry in entries if not entry.covered))


def _entry(entity: Entity, evidence: Iterable[CoverageEvidence]) -> CoverageEntry:
    evidence = tuple(evidence)
    all_tests = tuple(sorted({test for item in evidence for test in item.tests}))
    return CoverageEntry(entity.usr, entity.qualified_name, entity.signature,
                         entity.file, entity.line, evidence, all_tests)


def _candidate_reachability(model: DerivedModel,
                            candidates: Iterable[str]) -> dict[str, frozenset[str]]:
    """Index every recorded identifier to entities it can reach through calls."""
    exact_sources: dict[str, set[str]] = {}
    file_sources: dict[str, set[str]] = {}
    for entity in model.entities.values():
        for identifier in (entity.usr, entity.name, entity.qualified_name):
            exact_sources.setdefault(identifier, set()).add(entity.usr)
        file_sources.setdefault(entity.file.replace("\\", "/"), set()).add(entity.usr)

    callees_by_source: dict[str, list[str]] = {}
    for edge in model.edges:
        if edge.kind == EdgeKind.CALLS:
            callees_by_source.setdefault(edge.source, []).append(edge.target)

    result: dict[str, frozenset[str]] = {}
    for candidate in set(candidates):
        reachable = set(exact_sources.get(candidate, ()))
        reachable.update(file_sources.get(candidate.replace("\\", "/"), ()))
        pending = list(reachable)
        while pending:
            for target in callees_by_source.get(pending.pop(), ()):
                if target not in reachable:
                    reachable.add(target)
                    pending.append(target)
        result[candidate] = frozenset(reachable)
    return result


def _successful_records(records: Iterable[StepRecord]) -> list[StepRecord]:
    records = list(records)
    undone = {record.undoes for record in records if record.decision == "undone"}
    return [record for record in records
            if record.number not in undone
            and record.round != APPROACH_ROUND
            and record.decision in ("approved", "manual")
            and (record.test_ok is True or (record.test_ok is None and record.tests_passed))]


def _callables(model: DerivedModel) -> list[Entity]:
    return [entity for entity in model.entities.values() if entity.kind in CALLABLE_KINDS]


def _entity_key(entity: Entity) -> tuple[str, str, str, int, str]:
    return (entity.qualified_name, entity.signature, entity.file, entity.line, entity.usr)


def _record_key(record: StepRecord) -> tuple[int, str, str, str]:
    return (record.number, record.time, record.title, record.decision)
