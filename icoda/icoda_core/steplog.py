"""The step log ``.icoda/steps.jsonl`` and the function statuses derived from it.

One JSON record per line: approved, rejected, failed, undone and manual steps. The log is committed with the code
so that the history travels with it; a record's own commit hash cannot be inside the commit that contains it, so
``commit`` is filled only in memory.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

from icoda_core.model import CALLABLE_KINDS, DerivedModel, Entity

ARCHITECTURE = "architecture"
IMPLEMENTATION = "implementation"
PHASES = (ARCHITECTURE, IMPLEMENTATION)
STATUS_BY_PHASE = {ARCHITECTURE: "stub", IMPLEMENTATION: "implemented"}


@dataclass
class StepRecord:
    """One line of ``steps.jsonl``."""

    number: int
    phase: str
    decision: str  # approved | rejected | failed | undone | manual | phase
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
    body_hashes: dict[str, str] = field(default_factory=dict)
    test_files: dict[str, list[str]] = field(default_factory=dict)
    build_passed: bool = False
    tests_passed: bool = False
    undoes: int | None = None
    time: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> StepRecord:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})  # type: ignore[arg-type]


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
        numbers = [r.number for r in self.records() if r.decision in ("approved", "manual")]
        return max(numbers, default=-1) + 1

    def approved(self) -> list[StepRecord]:
        """Approved steps that are still in effect, in order."""
        undone = {r.undoes for r in self.records() if r.decision == "undone"}
        return [r for r in self.records() if r.decision == "approved" and r.number not in undone]

    def status_records(self) -> list[StepRecord]:
        """Code-changing records still in effect; manual edits participate but cannot become ``tested``."""
        records = self.records()
        undone = {record.undoes for record in records if record.decision == "undone"}
        return [record for record in records
                if record.decision == "manual" or (record.decision == "approved" and record.number not in undone)]

    def rejections(self, number: int) -> tuple[str, ...]:
        return tuple(r.reason for r in self.records() if r.decision == "rejected" and r.number == number and r.reason)

    def current_phase(self) -> str:
        """The latest explicit or step-implied phase; old logs naturally start in architecture."""
        phases = [record.phase for record in self.records() if record.phase in PHASES]
        return phases[-1] if phases else ARCHITECTURE


def apply_statuses(model: DerivedModel, log: StepLog) -> None:
    """Function statuses from the log: stub after an architecture step, implemented or tested after implementation."""
    for entity in model.entities.values():
        if entity.kind in CALLABLE_KINDS:
            entity.status = "implemented"
    for record in log.status_records():
        for usr in (*record.entities_added, *record.entities_changed):
            affected = model.entities.get(usr)
            if affected is not None and affected.kind in CALLABLE_KINDS:
                affected.status = _status(record, affected)


def _status(record: StepRecord, entity: Entity) -> str:
    status = STATUS_BY_PHASE.get(record.phase, "implemented")
    if status != "implemented":
        return status
    same_body = bool(entity.body_hash and record.body_hashes.get(entity.usr) == entity.body_hash)
    has_test = bool(set(record.test_files.get(entity.usr, ())) & set(entity.test_files))
    return "tested" if record.build_passed and record.tests_passed and same_body and has_test else status
