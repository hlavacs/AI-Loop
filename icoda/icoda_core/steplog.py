"""The step log ``.icoda/steps.jsonl`` and the function statuses derived from it.

One JSON record per line: approved, rejected, failed, undone, manual and phase-transition events. The log is committed with the code
so that the history travels with it; a record's own commit hash cannot be inside the commit that contains it, so
``commit`` is filled only in memory.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

from icoda_core import bodyhash
from icoda_core.model import CALLABLE_KINDS, DerivedModel

ARCHITECTURE = "architecture"
IMPLEMENTATION = "implementation"
PHASES = (ARCHITECTURE, IMPLEMENTATION)
STATUS_BY_PHASE = {ARCHITECTURE: "stub", IMPLEMENTATION: "implemented"}
CODE_ROUND = "code"
APPROACH_ROUND = "approach"

@dataclass
class StepRecord:
    """One line of ``steps.jsonl``."""

    number: int
    phase: str
    decision: str  # approved | rejected | failed | undone | manual | phase_transition
    round: str = CODE_ROUND
    title: str = ""
    request: str = ""
    rationale: str = ""
    reason: str = ""
    commit: str = ""
    provider: str = ""
    binary: str = ""
    model: str = ""
    attempts: int = 0
    files: list[str] = field(default_factory=list)
    entities_added: list[str] = field(default_factory=list)
    entities_changed: list[str] = field(default_factory=list)
    entities_renamed: list[tuple[str, str]] = field(default_factory=list)
    entity_body_hashes: dict[str, str] = field(default_factory=dict)
    # Compatibility with the short-lived M3 log schema merged into this branch.
    body_hashes: dict[str, str] = field(default_factory=dict)
    test_files: dict[str, list[str]] = field(default_factory=dict)
    expected_entities: list[str] = field(default_factory=list)
    expected_files: list[str] = field(default_factory=list)
    build_ok: bool | None = None
    build_passed: bool = False
    build_output: str = ""
    test_ok: bool | None = None
    test_output: str = ""
    selected_tests: list[str] = field(default_factory=list)
    batch: list[str] = field(default_factory=list)
    # Kept only so logs written before build/test results were split still load.
    tests_passed: bool = False
    undoes: int | None = None
    previous_phase: str = ""
    time: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> StepRecord:
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        values["entities_renamed"] = _rename_pairs(data.get("entities_renamed"))
        values["entity_body_hashes"] = _hashes(data.get("entity_body_hashes"))
        values["body_hashes"] = _hashes(data.get("body_hashes"))
        values["selected_tests"] = _strings(data.get("selected_tests"))
        values["batch"] = _strings(data.get("batch"))
        return cls(**values)  # type: ignore[arg-type]


def _rename_pairs(value: object) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []
    return [(str(pair[0]), str(pair[1])) for pair in value
            if isinstance(pair, (list, tuple)) and len(pair) == 2]


def _strings(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _hashes(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(usr): str(digest) for usr, digest in value.items() if digest}


class StepLog:
    """Append-only reader and writer of ``steps.jsonl``."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def records(self) -> list[StepRecord]:
        if not self.path.is_file():
            return []
        return [StepRecord.from_dict(json.loads(line)) for line in self.path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def append(self, record: StepRecord) -> StepRecord:
        record.time = record.time or datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.to_json() + "\n")
        return record

    def next_number(self) -> int:
        numbers = [r.number for r in self.records()
                   if r.round != APPROACH_ROUND and r.decision in ("approved", "manual")]
        return max(numbers, default=-1) + 1

    def approved(self) -> list[StepRecord]:
        """Approved steps that are still in effect, in order."""
        undone = {r.undoes for r in self.records() if r.decision == "undone"}
        return [r for r in self.records()
                if r.round != APPROACH_ROUND and r.decision == "approved" and r.number not in undone]

    def status_records(self) -> list[StepRecord]:
        """Code-changing records still in effect; manual edits participate but cannot become ``tested``."""
        records = self.records()
        undone = {record.undoes for record in records if record.decision == "undone"}
        return [record for record in records
                if record.round != APPROACH_ROUND and
                (record.decision == "manual" or (record.decision == "approved" and record.number not in undone))]

    def rejections(self, number: int, round: str = CODE_ROUND) -> tuple[str, ...]:
        return tuple(r.reason for r in self.records()
                     if r.round == round and r.decision == "rejected" and r.number == number and r.reason)

    def current_phase(self) -> str:
        """The latest explicit or step-implied phase; old logs naturally start in architecture."""
        phases = [record.phase for record in self.records() if record.phase in PHASES]
        return phases[-1] if phases else ARCHITECTURE


def apply_statuses(model: DerivedModel, log: StepLog) -> None:
    """Apply effective status history and demote tested callables when their evidence is stale."""
    statuses: dict[str, tuple[str, str, tuple[str, ...]]] = {}
    for record in log.status_records():
        status = "implemented" if record.decision == "manual" else STATUS_BY_PHASE.get(
            record.phase, "implemented")
        for previous, current in record.entities_renamed:
            if previous in statuses:
                previous_status, previous_hash, previous_tests = statuses[previous]
                digest = _record_hash(record, current) if previous_status == "tested" else ""
                statuses[current] = (previous_status, digest or previous_hash, previous_tests)
        for usr in (*record.entities_added, *record.entities_changed):
            resolved_usr = model.resolve_legacy_main(usr, record.files)
            entity = model.entities.get(resolved_usr)
            legacy_tests = tuple(record.test_files.get(usr, ()))
            tested = status == "implemented" and (
                record.test_ok is True
                or (record.build_passed and record.tests_passed and entity is not None
                    and bool(set(legacy_tests) & set(entity.test_files)))
            )
            effective_status = "tested" if tested else status
            digest = _record_hash(record, usr) if effective_status == "tested" else ""
            statuses[resolved_usr] = (effective_status, digest, legacy_tests)
    for usr, (status, tested_hash, required_tests) in statuses.items():
        entity = model.entities.get(usr)
        if entity is not None and entity.kind in CALLABLE_KINDS:
            stale_body = status == "tested" and bodyhash.changed(tested_hash, entity.body_hash)
            missing_legacy_test = status == "tested" and bool(required_tests) and not (
                set(required_tests) & set(entity.test_files))
            entity.status = "implemented" if stale_body or missing_legacy_test else status


def _record_hash(record: StepRecord, usr: str) -> str:
    return record.entity_body_hashes.get(usr, "") or record.body_hashes.get(usr, "")


def last_entity_body_hashes(records: list[StepRecord]) -> dict[str, str]:
    """Return each entity's latest available body hash from effective persisted records."""
    undone = {record.undoes for record in records if record.decision == "undone"}
    hashes: dict[str, str] = {}
    for record in records:
        if record.number in undone or record.round == APPROACH_ROUND \
                or record.decision not in ("approved", "manual"):
            continue
        for previous, current in record.entities_renamed:
            if previous in hashes:
                hashes[current] = hashes.pop(previous)
        touched = (*record.entities_added, *record.entities_changed,
                   *(current for _previous, current in record.entities_renamed))
        for usr in touched:
            if digest := _record_hash(record, usr):
                hashes[usr] = digest
    return hashes
