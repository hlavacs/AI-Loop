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

from icoda_core.model import CALLABLE_KINDS, DerivedModel

ARCHITECTURE = "architecture"
IMPLEMENTATION = "implementation"
STATUS_BY_PHASE = {ARCHITECTURE: "stub", IMPLEMENTATION: "implemented"}



@dataclass
class StepRecord:
    """One line of ``steps.jsonl``."""

    number: int
    phase: str
    decision: str  # approved | rejected | failed | undone | manual
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

    def rejections(self, number: int) -> tuple[str, ...]:
        return tuple(r.reason for r in self.records() if r.decision == "rejected" and r.number == number and r.reason)


def apply_statuses(model: DerivedModel, log: StepLog) -> None:
    """Function statuses from the log: stub after an architecture step, implemented or tested after implementation."""
    for record in log.approved():
        status = STATUS_BY_PHASE.get(record.phase, "implemented")
        if status == "implemented" and record.tests_passed:
            status = "tested"
        for usr in (*record.entities_added, *record.entities_changed):
            entity = model.entities.get(usr)
            if entity is not None and entity.kind in CALLABLE_KINDS:
                entity.status = status


