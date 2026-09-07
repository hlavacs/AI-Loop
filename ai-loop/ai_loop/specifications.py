"""Formal specification models, validation, immutable revisions, and integrity.

The JSON schema is a portable description of the format.  This module remains
the authoritative validator for every document accepted by AI-Loop.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass, fields
from decimal import Decimal
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping, Sequence

from ai_loop import db


SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})
CURRENT_SCHEMA_VERSION = "1.0"
STABLE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)*$")
MAX_STABLE_ID_LENGTH = 64
EVIDENCE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")


class RequirementCategory(str, Enum):
    FUNCTIONAL = "functional"
    QUALITY = "quality"
    INTERFACE = "interface"
    DATA = "data"
    OPERATIONAL = "operational"
    COMPLIANCE = "compliance"


class RequirementPriority(str, Enum):
    MUST = "must"
    SHOULD = "should"
    COULD = "could"


class RiskSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskUncertainty(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TestLevel(str, Enum):
    STATIC = "static"
    UNIT = "unit"
    INTEGRATION = "integration"
    SYSTEM = "system"
    ACCEPTANCE = "acceptance"
    PROPERTY = "property"
    PERFORMANCE = "performance"
    SECURITY = "security"
    VISUAL = "visual"


class VerificationMethod(str, Enum):
    DETERMINISTIC = "deterministic"
    DIFFERENTIAL = "differential"
    METAMORPHIC = "metamorphic"
    STATISTICAL = "statistical"
    SNAPSHOT = "snapshot"
    MANUAL = "manual"
    HYBRID = "hybrid"


class AutomationLevel(str, Enum):
    AUTOMATED = "automated"
    MANUAL = "manual"
    HYBRID = "hybrid"


class EvidenceKind(str, Enum):
    LOG = "log"
    STRUCTURED_DATA = "structured-data"
    INTERMEDIATE_STATE = "intermediate-state"
    TRACE = "trace"
    IMAGE = "image"
    SNAPSHOT = "snapshot"
    BENCHMARK = "benchmark"
    COVERAGE = "coverage"
    REFERENCE_OUTPUT = "reference-output"
    COMPARISON_RESULT = "comparison-result"


class CoverageType(str, Enum):
    SOURCE_LINE = "source-line"
    BRANCH = "branch"
    INTERFACE = "interface"
    SCENARIO = "scenario"
    STATE_TRANSITION = "state-transition"
    REQUIREMENT = "requirement"
    FIXTURE = "fixture"
    INVARIANT = "invariant"
    PLATFORM = "platform"


METRIC_OPERATORS = frozenset({"<", "<=", "==", "!=", ">=", ">"})
SPECIFICATION_STATUSES = frozenset({"draft", "review", "approved", "superseded"})


@dataclass(frozen=True)
class ValidationIssue:
    stage: str
    path: str
    severity: str
    message: str


class SpecificationError(ValueError):
    """Base error for formal specification operations."""


class SpecificationValidationError(SpecificationError):
    def __init__(self, issues: Sequence[ValidationIssue]):
        self.issues = tuple(issues)
        detail = "; ".join(f"{issue.path}: {issue.message}" for issue in self.issues)
        super().__init__(detail or "specification validation failed")


class SpecificationStateError(SpecificationError):
    pass


class SpecificationIntegrityError(SpecificationError):
    pass


def _tuple_of_strings(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SpecificationError(f"{path} must be an array")
    if any(not isinstance(item, str) for item in value):
        raise SpecificationError(f"{path} must contain strings only")
    return tuple(value)


def _strict_mapping(data: Any, expected: set[str], path: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise SpecificationError(f"{path} must be an object")
    actual = set(data)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown:
        raise SpecificationError(f"{path} contains unknown fields: {', '.join(unknown)}")
    if missing:
        raise SpecificationError(f"{path} is missing fields: {', '.join(missing)}")
    return data


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise SpecificationError(f"{path} must be a string")
    return value


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise SpecificationError(f"{path} must be a boolean")
    return value


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SpecificationError(f"{path} must be an integer")
    return value


def _finite_number(value: Any, path: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecificationError(f"{path} must be a number, not a boolean or string")
    try:
        finite = math.isfinite(float(value))
    except (OverflowError, ValueError):
        finite = False
    if not finite:
        raise SpecificationError(f"{path} must be finite")
    return value


def _optional_finite_number(value: Any, path: str) -> int | float | None:
    return None if value is None else _finite_number(value, path)


def _enum(enum_type: type[Enum], value: Any, path: str) -> Enum:
    if not isinstance(value, str):
        raise SpecificationError(f"{path} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise SpecificationError(f"{path} must be one of: {allowed}") from exc


@dataclass(frozen=True)
class UseCase:
    id: str
    title: str
    actors: tuple[str, ...]
    preconditions: tuple[str, ...]
    trigger: str
    main_flow: tuple[str, ...]
    alternate_flows: tuple[str, ...]
    postconditions: tuple[str, ...]
    error_and_edge_cases: tuple[str, ...]
    requirement_ids: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: Any, path: str = "use_case") -> UseCase:
        keys = {field.name for field in fields(cls)}
        item = _strict_mapping(data, keys, path)
        return cls(
            id=_string(item["id"], f"{path}.id"),
            title=_string(item["title"], f"{path}.title"),
            actors=_tuple_of_strings(item["actors"], f"{path}.actors"),
            preconditions=_tuple_of_strings(item["preconditions"], f"{path}.preconditions"),
            trigger=_string(item["trigger"], f"{path}.trigger"),
            main_flow=_tuple_of_strings(item["main_flow"], f"{path}.main_flow"),
            alternate_flows=_tuple_of_strings(item["alternate_flows"], f"{path}.alternate_flows"),
            postconditions=_tuple_of_strings(item["postconditions"], f"{path}.postconditions"),
            error_and_edge_cases=_tuple_of_strings(
                item["error_and_edge_cases"], f"{path}.error_and_edge_cases"
            ),
            requirement_ids=_tuple_of_strings(item["requirement_ids"], f"{path}.requirement_ids"),
        )


@dataclass(frozen=True)
class Requirement:
    id: str
    category: RequirementCategory
    priority: RequirementPriority
    title: str
    statement: str
    rationale: str
    acceptance_criteria: tuple[str, ...]
    source: str

    @classmethod
    def from_dict(cls, data: Any, path: str = "requirement") -> Requirement:
        keys = {field.name for field in fields(cls)}
        item = _strict_mapping(data, keys, path)
        return cls(
            id=_string(item["id"], f"{path}.id"),
            category=_enum(RequirementCategory, item["category"], f"{path}.category"),  # type: ignore[arg-type]
            priority=_enum(RequirementPriority, item["priority"], f"{path}.priority"),  # type: ignore[arg-type]
            title=_string(item["title"], f"{path}.title"),
            statement=_string(item["statement"], f"{path}.statement"),
            rationale=_string(item["rationale"], f"{path}.rationale"),
            acceptance_criteria=_tuple_of_strings(
                item["acceptance_criteria"], f"{path}.acceptance_criteria"
            ),
            source=_string(item["source"], f"{path}.source"),
        )


@dataclass(frozen=True)
class SpecificationDecision:
    topic: str
    selected_decision: str
    rationale: str
    rejected_alternatives: tuple[str, ...]
    consequences: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: Any, path: str = "decision") -> SpecificationDecision:
        keys = {field.name for field in fields(cls)}
        item = _strict_mapping(data, keys, path)
        return cls(
            topic=_string(item["topic"], f"{path}.topic"),
            selected_decision=_string(item["selected_decision"], f"{path}.selected_decision"),
            rationale=_string(item["rationale"], f"{path}.rationale"),
            rejected_alternatives=_tuple_of_strings(
                item["rejected_alternatives"], f"{path}.rejected_alternatives"
            ),
            consequences=_tuple_of_strings(item["consequences"], f"{path}.consequences"),
        )


@dataclass(frozen=True)
class Risk:
    id: str
    title: str
    description: str
    severity: RiskSeverity
    uncertainty: RiskUncertainty
    failure_modes: tuple[str, ...]
    detection_signals: tuple[str, ...]
    mitigations: tuple[str, ...]
    verification_ids: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: Any, path: str = "risk") -> Risk:
        keys = {field.name for field in fields(cls)}
        item = _strict_mapping(data, keys, path)
        return cls(
            id=_string(item["id"], f"{path}.id"),
            title=_string(item["title"], f"{path}.title"),
            description=_string(item["description"], f"{path}.description"),
            severity=_enum(RiskSeverity, item["severity"], f"{path}.severity"),  # type: ignore[arg-type]
            uncertainty=_enum(RiskUncertainty, item["uncertainty"], f"{path}.uncertainty"),  # type: ignore[arg-type]
            failure_modes=_tuple_of_strings(item["failure_modes"], f"{path}.failure_modes"),
            detection_signals=_tuple_of_strings(
                item["detection_signals"], f"{path}.detection_signals"
            ),
            mitigations=_tuple_of_strings(item["mitigations"], f"{path}.mitigations"),
            verification_ids=_tuple_of_strings(
                item["verification_ids"], f"{path}.verification_ids"
            ),
        )


@dataclass(frozen=True)
class ValidationLoop:
    maximum_correction_attempts: int
    repetitions_per_attempt: int
    stagnation_limit: int
    escalation_condition: str
    retain_evidence: bool

    @classmethod
    def from_dict(cls, data: Any, path: str = "validation_loop") -> ValidationLoop:
        keys = {field.name for field in fields(cls)}
        item = _strict_mapping(data, keys, path)
        return cls(
            maximum_correction_attempts=_integer(
                item["maximum_correction_attempts"], f"{path}.maximum_correction_attempts"
            ),
            repetitions_per_attempt=_integer(
                item["repetitions_per_attempt"], f"{path}.repetitions_per_attempt"
            ),
            stagnation_limit=_integer(item["stagnation_limit"], f"{path}.stagnation_limit"),
            escalation_condition=_string(
                item["escalation_condition"], f"{path}.escalation_condition"
            ),
            retain_evidence=_boolean(item["retain_evidence"], f"{path}.retain_evidence"),
        )


@dataclass(frozen=True)
class MetricAssertion:
    metric: str
    operator: str
    threshold: int | float
    tolerance: int | float | None

    @classmethod
    def from_dict(cls, data: Any, path: str = "metric_assertion") -> MetricAssertion:
        keys = {field.name for field in fields(cls)}
        item = _strict_mapping(data, keys, path)
        return cls(
            metric=_string(item["metric"], f"{path}.metric"),
            operator=_string(item["operator"], f"{path}.operator"),
            threshold=_finite_number(item["threshold"], f"{path}.threshold"),
            tolerance=_optional_finite_number(item["tolerance"], f"{path}.tolerance"),
        )

    def evaluate(self, actual: int | float) -> bool:
        value = Decimal(str(_finite_number(actual, "actual metric value")))
        threshold = Decimal(str(_finite_number(self.threshold, "metric threshold")))
        tolerance = Decimal(0) if self.tolerance is None else Decimal(
            str(_finite_number(self.tolerance, "metric tolerance"))
        )
        if tolerance < 0:
            raise SpecificationError("metric tolerance must be non-negative")
        operations = {
            "<": value < threshold + tolerance,
            "<=": value <= threshold + tolerance,
            "==": abs(value - threshold) <= tolerance,
            "!=": abs(value - threshold) > tolerance,
            ">=": value >= threshold - tolerance,
            ">": value > threshold - tolerance,
        }
        if self.operator not in operations:
            raise SpecificationError(f"unsupported metric operator: {self.operator}")
        return operations[self.operator]


@dataclass(frozen=True)
class EvidenceDeclaration:
    """Portable declaration of one expected domain-neutral evidence item."""

    name: str
    kind: EvidenceKind
    media_type: str
    description: str
    requirement_ids: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: Any, path: str = "evidence_declaration") -> EvidenceDeclaration:
        keys = {field.name for field in fields(cls)}
        item = _strict_mapping(data, keys, path)
        return cls(
            name=_string(item["name"], f"{path}.name"),
            kind=_enum(EvidenceKind, item["kind"], f"{path}.kind"),  # type: ignore[arg-type]
            media_type=_string(item["media_type"], f"{path}.media_type"),
            description=_string(item["description"], f"{path}.description"),
            requirement_ids=_tuple_of_strings(
                item["requirement_ids"], f"{path}.requirement_ids"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


@dataclass(frozen=True)
class CoverageTarget:
    """Named coverage contract; incomplete measurement fields remain descriptive."""

    name: str
    coverage_type: CoverageType
    description: str
    measurement_key: str | None
    operator: str | None
    threshold: int | float | None
    tolerance: int | float | None
    required_scenarios: tuple[str, ...]
    evidence_kind: EvidenceKind | None

    @classmethod
    def from_dict(cls, data: Any, path: str = "coverage_target") -> CoverageTarget:
        keys = {field.name for field in fields(cls)}
        item = _strict_mapping(data, keys, path)
        measurement_key = item["measurement_key"]
        operator = item["operator"]
        if measurement_key is not None and not isinstance(measurement_key, str):
            raise SpecificationError(f"{path}.measurement_key must be a string or null")
        if operator is not None and not isinstance(operator, str):
            raise SpecificationError(f"{path}.operator must be a string or null")
        evidence_kind = item["evidence_kind"]
        return cls(
            name=_string(item["name"], f"{path}.name"),
            coverage_type=_enum(CoverageType, item["coverage_type"], f"{path}.coverage_type"),  # type: ignore[arg-type]
            description=_string(item["description"], f"{path}.description"),
            measurement_key=measurement_key,
            operator=operator,
            threshold=_optional_finite_number(item["threshold"], f"{path}.threshold"),
            tolerance=_optional_finite_number(item["tolerance"], f"{path}.tolerance"),
            required_scenarios=_tuple_of_strings(
                item["required_scenarios"], f"{path}.required_scenarios"
            ),
            evidence_kind=(
                None
                if evidence_kind is None
                else _enum(EvidenceKind, evidence_kind, f"{path}.evidence_kind")
            ),  # type: ignore[arg-type]
        )

    @property
    def machine_enforced(self) -> bool:
        return all(
            value is not None
            for value in (
                self.measurement_key,
                self.operator,
                self.threshold,
                self.evidence_kind,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


def _coverage_targets(value: Any, path: str) -> tuple[CoverageTarget | str, ...]:
    if not isinstance(value, list):
        raise SpecificationError(f"{path} must be an array")
    return tuple(
        item
        if isinstance(item, str)
        else CoverageTarget.from_dict(item, f"{path}[{index}]")
        for index, item in enumerate(value)
    )


def _evidence_declarations(value: Any, path: str) -> tuple[EvidenceDeclaration | str, ...]:
    if not isinstance(value, list):
        raise SpecificationError(f"{path} must be an array")
    return tuple(
        item
        if isinstance(item, str)
        else EvidenceDeclaration.from_dict(item, f"{path}[{index}]")
        for index, item in enumerate(value)
    )


@dataclass(frozen=True)
class VerificationCase:
    id: str
    title: str
    requirement_ids: tuple[str, ...]
    test_level: TestLevel
    method: VerificationMethod
    oracle: str
    fixtures: tuple[str, ...]
    procedure: tuple[str, ...]
    pass_criteria: tuple[str, ...]
    declared_metrics: tuple[str, ...]
    metric_assertions: tuple[MetricAssertion, ...]
    coverage_targets: tuple[CoverageTarget | str, ...]
    automation: AutomationLevel
    blocking: bool
    validation_loop: ValidationLoop
    command_override: str | None
    working_directory: str
    timeout: int
    required_evidence: tuple[EvidenceDeclaration | str, ...]

    @classmethod
    def from_dict(cls, data: Any, path: str = "verification") -> VerificationCase:
        keys = {field.name for field in fields(cls)}
        item = _strict_mapping(data, keys, path)
        command = item["command_override"]
        if command is not None and not isinstance(command, str):
            raise SpecificationError(f"{path}.command_override must be a string or null")
        assertions = item["metric_assertions"]
        if not isinstance(assertions, list):
            raise SpecificationError(f"{path}.metric_assertions must be an array")
        return cls(
            id=_string(item["id"], f"{path}.id"),
            title=_string(item["title"], f"{path}.title"),
            requirement_ids=_tuple_of_strings(item["requirement_ids"], f"{path}.requirement_ids"),
            test_level=_enum(TestLevel, item["test_level"], f"{path}.test_level"),  # type: ignore[arg-type]
            method=_enum(VerificationMethod, item["method"], f"{path}.method"),  # type: ignore[arg-type]
            oracle=_string(item["oracle"], f"{path}.oracle"),
            fixtures=_tuple_of_strings(item["fixtures"], f"{path}.fixtures"),
            procedure=_tuple_of_strings(item["procedure"], f"{path}.procedure"),
            pass_criteria=_tuple_of_strings(item["pass_criteria"], f"{path}.pass_criteria"),
            declared_metrics=_tuple_of_strings(
                item["declared_metrics"], f"{path}.declared_metrics"
            ),
            metric_assertions=tuple(
                MetricAssertion.from_dict(assertion, f"{path}.metric_assertions[{index}]")
                for index, assertion in enumerate(assertions)
            ),
            coverage_targets=_coverage_targets(
                item["coverage_targets"], f"{path}.coverage_targets"
            ),
            automation=_enum(AutomationLevel, item["automation"], f"{path}.automation"),  # type: ignore[arg-type]
            blocking=_boolean(item["blocking"], f"{path}.blocking"),
            validation_loop=ValidationLoop.from_dict(
                item["validation_loop"], f"{path}.validation_loop"
            ),
            command_override=command,
            working_directory=_string(item["working_directory"], f"{path}.working_directory"),
            timeout=_integer(item["timeout"], f"{path}.timeout"),
            required_evidence=_evidence_declarations(
                item["required_evidence"], f"{path}.required_evidence"
            ),
        )


@dataclass(frozen=True)
class SpecificationDocument:
    schema_version: str
    title: str
    summary: str
    objectives: tuple[str, ...]
    in_scope: tuple[str, ...]
    out_of_scope: tuple[str, ...]
    stakeholders: tuple[str, ...]
    assumptions: tuple[str, ...]
    constraints: tuple[str, ...]
    dependencies: tuple[str, ...]
    use_cases: tuple[UseCase, ...]
    requirements: tuple[Requirement, ...]
    decisions: tuple[SpecificationDecision, ...]
    risks: tuple[Risk, ...]
    verification: tuple[VerificationCase, ...]
    open_questions: tuple[str, ...]

    @classmethod
    def empty(cls, *, title: str = "", summary: str = "") -> SpecificationDocument:
        return cls(
            schema_version=CURRENT_SCHEMA_VERSION,
            title=title,
            summary=summary,
            objectives=(),
            in_scope=(),
            out_of_scope=(),
            stakeholders=(),
            assumptions=(),
            constraints=(),
            dependencies=(),
            use_cases=(),
            requirements=(),
            decisions=(),
            risks=(),
            verification=(),
            open_questions=(),
        )

    @classmethod
    def from_dict(
        cls,
        data: Any,
        *,
        worktree: str | Path | None = None,
        validate: bool = True,
    ) -> SpecificationDocument:
        keys = {field.name for field in fields(cls)}
        item = _strict_mapping(data, keys, "specification")
        collection_types = {
            "use_cases": UseCase,
            "requirements": Requirement,
            "decisions": SpecificationDecision,
            "risks": Risk,
            "verification": VerificationCase,
        }
        parsed_collections: dict[str, tuple[Any, ...]] = {}
        for name, model in collection_types.items():
            values = item[name]
            if not isinstance(values, list):
                raise SpecificationError(f"specification.{name} must be an array")
            parsed_collections[name] = tuple(
                model.from_dict(value, f"specification.{name}[{index}]")
                for index, value in enumerate(values)
            )
        document = cls(
            schema_version=_string(item["schema_version"], "specification.schema_version"),
            title=_string(item["title"], "specification.title"),
            summary=_string(item["summary"], "specification.summary"),
            objectives=_tuple_of_strings(item["objectives"], "specification.objectives"),
            in_scope=_tuple_of_strings(item["in_scope"], "specification.in_scope"),
            out_of_scope=_tuple_of_strings(item["out_of_scope"], "specification.out_of_scope"),
            stakeholders=_tuple_of_strings(item["stakeholders"], "specification.stakeholders"),
            assumptions=_tuple_of_strings(item["assumptions"], "specification.assumptions"),
            constraints=_tuple_of_strings(item["constraints"], "specification.constraints"),
            dependencies=_tuple_of_strings(item["dependencies"], "specification.dependencies"),
            use_cases=parsed_collections["use_cases"],
            requirements=parsed_collections["requirements"],
            decisions=parsed_collections["decisions"],
            risks=parsed_collections["risks"],
            verification=parsed_collections["verification"],
            open_questions=_tuple_of_strings(
                item["open_questions"], "specification.open_questions"
            ),
        )
        if validate:
            validate_structural(document, worktree=worktree)
        return document

    @classmethod
    def from_json(
        cls,
        text: str,
        *,
        worktree: str | Path | None = None,
        validate: bool = True,
    ) -> SpecificationDocument:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SpecificationError(f"invalid specification JSON: {exc}") from exc
        return cls.from_dict(data, worktree=worktree, validate=validate)

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def content_hash(self) -> str:
        return sha256_text(self.canonical_json())

    def pretty_json(self) -> str:
        return json.dumps(
            normalize_numeric_values(self.to_dict()),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        ) + "\n"

    def validate_structural(self, *, worktree: str | Path | None = None) -> None:
        validate_structural(self, worktree=worktree)

    def validate_for_approval(self, *, unresolved_blocking_decisions: int = 0) -> None:
        validate_for_approval(
            self,
            unresolved_blocking_decisions=unresolved_blocking_decisions,
        )


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def normalize_numeric_values(value: Any) -> Any:
    """Return JSON data with finite, integral floats represented as integers."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SpecificationError("canonical JSON cannot contain NaN or infinity")
        if value == 0 or value.is_integer():
            return int(value)
        return value
    if isinstance(value, list):
        return [normalize_numeric_values(item) for item in value]
    if isinstance(value, tuple):
        return [normalize_numeric_values(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalize_numeric_values(item) for key, item in value.items()}
    raise SpecificationError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        normalize_numeric_values(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def _nonempty(value: str) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def validate_working_directory(value: str, worktree: str | Path | None = None) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SpecificationError("working directory must be a non-empty relative path")
    if "\x00" in value:
        raise SpecificationError("working directory contains a NUL byte")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or value.startswith(("//", "\\\\")):
        raise SpecificationError("working directory must not be an absolute POSIX or Windows path")
    if ".." in posix.parts or ".." in windows.parts:
        raise SpecificationError("working directory must not contain parent traversal")
    if worktree is not None:
        root = Path(worktree).resolve()
        candidate = (root / Path(value)).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise SpecificationError("working directory resolves outside the worktree") from exc


def structural_issues(
    document: SpecificationDocument,
    *,
    worktree: str | Path | None = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def add(path: str, message: str) -> None:
        issues.append(ValidationIssue("structure", path, "error", message))

    if not isinstance(document.schema_version, str) or document.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        add("schema_version", f"unsupported schema version: {document.schema_version}")

    def require_enum(path: str, value: Any, enum_type: type[Enum]) -> None:
        allowed = {item.value for item in enum_type}
        raw = value.value if isinstance(value, enum_type) else value
        if not isinstance(raw, str) or raw not in allowed:
            add(path, f"must be one of: {', '.join(sorted(allowed))}")

    entity_groups: tuple[tuple[str, Sequence[Any]], ...] = (
        ("use_cases", document.use_cases),
        ("requirements", document.requirements),
        ("risks", document.risks),
        ("verification", document.verification),
    )
    all_ids: list[tuple[str, str]] = []
    for group_name, entities in entity_groups:
        for index, entity in enumerate(entities):
            entity_id = entity.id
            path = f"{group_name}[{index}].id"
            if (
                not isinstance(entity_id, str)
                or len(entity_id) > MAX_STABLE_ID_LENGTH
                or not STABLE_ID_PATTERN.fullmatch(entity_id)
            ):
                add(path, "must be a stable uppercase identifier")
            if isinstance(entity_id, str):
                all_ids.append((entity_id, path))
        for duplicate in sorted(_duplicates(entity.id for entity in entities)):
            add(group_name, f"duplicate identifier: {duplicate}")
    global_duplicates = _duplicates(entity_id for entity_id, _path in all_ids)
    for duplicate in sorted(global_duplicates):
        add("identifiers", f"identifier is reused by different entities: {duplicate}")

    requirement_ids = {requirement.id for requirement in document.requirements}
    verification_ids = {case.id for case in document.verification}
    for index, requirement in enumerate(document.requirements):
        require_enum(f"requirements[{index}].category", requirement.category, RequirementCategory)
        require_enum(f"requirements[{index}].priority", requirement.priority, RequirementPriority)
    for index, use_case in enumerate(document.use_cases):
        for requirement_id in use_case.requirement_ids:
            if requirement_id not in requirement_ids:
                add(
                    f"use_cases[{index}].requirement_ids",
                    f"unknown requirement identifier: {requirement_id}",
                )
        for duplicate in sorted(_duplicates(use_case.requirement_ids)):
            add(f"use_cases[{index}].requirement_ids", f"duplicate reference: {duplicate}")
    for index, risk in enumerate(document.risks):
        require_enum(f"risks[{index}].severity", risk.severity, RiskSeverity)
        require_enum(f"risks[{index}].uncertainty", risk.uncertainty, RiskUncertainty)
        for verification_id in risk.verification_ids:
            if verification_id not in verification_ids:
                add(
                    f"risks[{index}].verification_ids",
                    f"unknown verification identifier: {verification_id}",
                )
        for duplicate in sorted(_duplicates(risk.verification_ids)):
            add(f"risks[{index}].verification_ids", f"duplicate reference: {duplicate}")
    for index, case in enumerate(document.verification):
        base = f"verification[{index}]"
        require_enum(f"{base}.test_level", case.test_level, TestLevel)
        require_enum(f"{base}.method", case.method, VerificationMethod)
        require_enum(f"{base}.automation", case.automation, AutomationLevel)
        for requirement_id in case.requirement_ids:
            if requirement_id not in requirement_ids:
                add(f"{base}.requirement_ids", f"unknown requirement identifier: {requirement_id}")
        for duplicate in sorted(_duplicates(case.requirement_ids)):
            add(f"{base}.requirement_ids", f"duplicate reference: {duplicate}")
        loop = case.validation_loop
        for name in (
            "maximum_correction_attempts",
            "repetitions_per_attempt",
            "stagnation_limit",
        ):
            value = getattr(loop, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                add(f"{base}.validation_loop.{name}", "must be a positive integer")
        if isinstance(case.timeout, bool) or not isinstance(case.timeout, int) or case.timeout <= 0:
            add(f"{base}.timeout", "must be a positive integer")
        if case.command_override is not None and (
            not isinstance(case.command_override, str) or not case.command_override.strip()
        ):
            add(
                f"{base}.command_override",
                "must be null or a non-empty command string",
            )
        try:
            validate_working_directory(case.working_directory, worktree)
        except SpecificationError as exc:
            add(f"{base}.working_directory", str(exc))
        assertion_names: list[str] = []
        for assertion_index, assertion in enumerate(case.metric_assertions):
            assertion_path = f"{base}.metric_assertions[{assertion_index}]"
            if not _nonempty(assertion.metric):
                add(f"{assertion_path}.metric", "metric name must not be empty")
            assertion_names.append(assertion.metric)
            if assertion.operator not in METRIC_OPERATORS:
                add(f"{assertion_path}.operator", f"unsupported operator: {assertion.operator}")
            for name in ("threshold", "tolerance"):
                value = getattr(assertion, name)
                if value is None and name == "tolerance":
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    add(f"{assertion_path}.{name}", "must be numeric and not boolean")
                elif not math.isfinite(float(value)):
                    add(f"{assertion_path}.{name}", "must be finite")
                elif name == "tolerance" and value < 0:
                    add(f"{assertion_path}.{name}", "must be non-negative")
        for duplicate in sorted(_duplicates(assertion_names)):
            add(f"{base}.metric_assertions", f"duplicate assertion for metric: {duplicate}")
        declared_metric_names: set[str] = set()
        for metric_index, metric_name in enumerate(case.declared_metrics):
            if not _nonempty(metric_name):
                add(
                    f"{base}.declared_metrics[{metric_index}]",
                    "metric name must be a non-empty string",
                )
            elif metric_name in declared_metric_names:
                add(f"{base}.declared_metrics", f"duplicate declared metric: {metric_name}")
            declared_metric_names.add(metric_name)
        for assertion_name in assertion_names:
            if assertion_name and assertion_name not in declared_metric_names:
                add(
                    f"{base}.metric_assertions",
                    f"asserted metric is not declared: {assertion_name}",
                )
        coverage_names: list[str] = []
        for target_index, target in enumerate(case.coverage_targets):
            target_path = f"{base}.coverage_targets[{target_index}]"
            if isinstance(target, str):
                if not _nonempty(target):
                    add(target_path, "descriptive coverage target must not be empty")
                continue
            coverage_names.append(target.name)
            if not isinstance(target.name, str) or not EVIDENCE_NAME_PATTERN.fullmatch(target.name):
                add(f"{target_path}.name", "must be a stable evidence name")
            if not _nonempty(target.description):
                add(f"{target_path}.description", "coverage target description must not be empty")
            require_enum(f"{target_path}.coverage_type", target.coverage_type, CoverageType)
            supplied = (
                target.measurement_key is not None,
                target.operator is not None,
                target.threshold is not None,
                target.evidence_kind is not None,
            )
            if any(supplied) and not all(supplied):
                add(
                    target_path,
                    "machine coverage requires measurement_key, operator, threshold, and evidence_kind together",
                )
            if target.machine_enforced:
                if not _nonempty(target.measurement_key or ""):
                    add(f"{target_path}.measurement_key", "measurement key must not be empty")
                if target.operator not in METRIC_OPERATORS:
                    add(f"{target_path}.operator", f"unsupported operator: {target.operator}")
                if target.evidence_kind != EvidenceKind.COVERAGE:
                    add(
                        f"{target_path}.evidence_kind",
                        "machine-enforced coverage must map to emitted coverage evidence",
                    )
            for name in ("threshold", "tolerance"):
                value = getattr(target, name)
                if value is None:
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    add(f"{target_path}.{name}", "must be numeric and not boolean")
                elif not math.isfinite(float(value)):
                    add(f"{target_path}.{name}", "must be finite")
                elif name == "tolerance" and value < 0:
                    add(f"{target_path}.{name}", "must be non-negative")
            if len(target.required_scenarios) != len(set(target.required_scenarios)):
                add(f"{target_path}.required_scenarios", "contains duplicate scenarios")
            if any(not _nonempty(item) for item in target.required_scenarios):
                add(f"{target_path}.required_scenarios", "scenario names must not be empty")
        for duplicate in sorted(_duplicates(coverage_names)):
            add(f"{base}.coverage_targets", f"duplicate coverage target name: {duplicate}")

        evidence_names: list[str] = []
        for declaration_index, declaration in enumerate(case.required_evidence):
            declaration_path = f"{base}.required_evidence[{declaration_index}]"
            if isinstance(declaration, str):
                if not _nonempty(declaration):
                    add(declaration_path, "descriptive evidence declaration must not be empty")
                continue
            evidence_names.append(declaration.name)
            if not isinstance(declaration.name, str) or not EVIDENCE_NAME_PATTERN.fullmatch(
                declaration.name
            ):
                add(f"{declaration_path}.name", "must be a stable evidence name")
            for name in ("media_type", "description"):
                if not _nonempty(getattr(declaration, name)):
                    add(f"{declaration_path}.{name}", "must not be empty")
            require_enum(f"{declaration_path}.kind", declaration.kind, EvidenceKind)
            for requirement_id in declaration.requirement_ids:
                if requirement_id not in requirement_ids:
                    add(
                        f"{declaration_path}.requirement_ids",
                        f"unknown requirement identifier: {requirement_id}",
                    )
                elif requirement_id not in case.requirement_ids:
                    add(
                        f"{declaration_path}.requirement_ids",
                        f"requirement {requirement_id} is not linked to this verification case",
                    )
            if len(declaration.requirement_ids) != len(set(declaration.requirement_ids)):
                add(f"{declaration_path}.requirement_ids", "contains duplicate references")
        for duplicate in sorted(_duplicates(evidence_names)):
            add(f"{base}.required_evidence", f"duplicate evidence declaration name: {duplicate}")
        manual_case = case.automation == AutomationLevel.MANUAL or case.method == VerificationMethod.MANUAL
        if case.method == VerificationMethod.MANUAL and case.automation != AutomationLevel.MANUAL:
            add(f"{base}.automation", "the manual method requires manual automation")
        if case.automation == AutomationLevel.MANUAL and case.method != VerificationMethod.MANUAL:
            add(f"{base}.method", "manual automation requires the manual method")
        if manual_case:
            if case.blocking:
                add(f"{base}.blocking", "manual verification cannot block autonomous completion")
            if isinstance(case.command_override, str) and case.command_override.strip():
                add(f"{base}.command_override", "manual verification cannot define a command")
            if case.metric_assertions:
                add(f"{base}.metric_assertions", "manual verification cannot define metric assertions")
            if any(
                isinstance(target, CoverageTarget) and target.machine_enforced
                for target in case.coverage_targets
            ):
                add(
                    f"{base}.coverage_targets",
                    "manual verification cannot define machine-enforced coverage",
                )
    return issues


def validate_structural(
    document: SpecificationDocument,
    *,
    worktree: str | Path | None = None,
) -> None:
    issues = structural_issues(document, worktree=worktree)
    if issues:
        raise SpecificationValidationError(issues)


def approval_issues(
    document: SpecificationDocument,
    *,
    unresolved_blocking_decisions: int = 0,
) -> list[ValidationIssue]:
    issues = structural_issues(document)

    def add(path: str, message: str) -> None:
        issues.append(ValidationIssue("approval", path, "error", message))

    for path, value in (("title", document.title), ("summary", document.summary)):
        if not _nonempty(value):
            add(path, "is required for approval")
    for path, values in (
        ("objectives", document.objectives),
        ("in_scope", document.in_scope),
        ("out_of_scope", document.out_of_scope),
        ("stakeholders", document.stakeholders),
    ):
        if not values or any(not _nonempty(value) for value in values):
            add(path, "must contain at least one non-empty item for approval")
    if not document.use_cases:
        add("use_cases", "at least one complete use case is required")
    for index, use_case in enumerate(document.use_cases):
        base = f"use_cases[{index}]"
        if not _nonempty(use_case.title):
            add(f"{base}.title", "is required")
        if not use_case.actors:
            add(f"{base}.actors", "at least one actor is required")
        if not use_case.preconditions:
            add(f"{base}.preconditions", "preconditions must be stated explicitly")
        if not _nonempty(use_case.trigger):
            add(f"{base}.trigger", "is required")
        if not use_case.main_flow:
            add(f"{base}.main_flow", "main behavior is required")
        if not use_case.postconditions:
            add(f"{base}.postconditions", "postconditions are required")
        if not use_case.error_and_edge_cases:
            add(f"{base}.error_and_edge_cases", "failure and edge behavior is required")
        if not use_case.requirement_ids:
            add(f"{base}.requirement_ids", "every use case must reference requirements")

    categories = {requirement.category for requirement in document.requirements}
    if RequirementCategory.FUNCTIONAL not in categories:
        add("requirements", "at least one functional requirement is required")
    if RequirementCategory.QUALITY not in categories:
        add("requirements", "at least one quality requirement is required")
    coverage: dict[str, set[str]] = {requirement.id: set() for requirement in document.requirements}
    for case in document.verification:
        for requirement_id in case.requirement_ids:
            if requirement_id in coverage:
                coverage[requirement_id].add(case.id)
    for index, requirement in enumerate(document.requirements):
        base = f"requirements[{index}]"
        for name in ("title", "statement", "rationale", "source"):
            if not _nonempty(getattr(requirement, name)):
                add(f"{base}.{name}", "is required for approval")
        if not requirement.acceptance_criteria or any(
            not _nonempty(item) for item in requirement.acceptance_criteria
        ):
            add(f"{base}.acceptance_criteria", "measurable acceptance criteria are required")
        if not coverage.get(requirement.id):
            priority = requirement.priority.value
            add(
                f"{base}.id",
                f"{priority} requirement {requirement.id} is not covered by verification",
            )

    for index, case in enumerate(document.verification):
        if not case.blocking:
            continue
        base = f"verification[{index}]"
        if case.automation != AutomationLevel.AUTOMATED:
            add(f"{base}.automation", "blocking verification must be automated")
        if not _nonempty(case.oracle):
            add(f"{base}.oracle", "blocking verification requires an independent oracle")
        if not case.procedure:
            add(f"{base}.procedure", "blocking verification requires an ordered procedure")
        if not case.pass_criteria:
            add(f"{base}.pass_criteria", "blocking verification requires pass criteria")
        if not case.coverage_targets:
            add(f"{base}.coverage_targets", "blocking verification requires a coverage target")
        if not _nonempty(case.validation_loop.escalation_condition):
            add(
                f"{base}.validation_loop.escalation_condition",
                "blocking verification requires an escalation condition",
            )

    verification_by_id = {case.id: case for case in document.verification}
    for index, risk in enumerate(document.risks):
        high_assurance = risk.severity in {RiskSeverity.HIGH, RiskSeverity.CRITICAL} or (
            risk.uncertainty == RiskUncertainty.HIGH
        )
        if not high_assurance:
            continue
        base = f"risks[{index}]"
        for field_name in ("failure_modes", "detection_signals", "mitigations", "verification_ids"):
            if not getattr(risk, field_name):
                add(
                    f"{base}.{field_name}",
                    f"{field_name} is required for high-severity or high-uncertainty risk",
                )
        for verification_id in risk.verification_ids:
            case = verification_by_id.get(verification_id)
            if case is None:
                continue
            case_path = f"verification[{document.verification.index(case)}]"
            if not case.declared_metrics or not case.metric_assertions:
                add(f"{case_path}.metric_assertions", f"risk {risk.id} requires explicit metrics and assertions")
            loop = case.validation_loop
            if loop.maximum_correction_attempts <= 1 and loop.repetitions_per_attempt <= 1:
                add(
                    f"{case_path}.validation_loop",
                    f"risk {risk.id} requires multiple attempts or repetitions",
                )
            if not loop.retain_evidence:
                add(f"{case_path}.validation_loop.retain_evidence", f"risk {risk.id} requires evidence retention")
            if not _nonempty(loop.escalation_condition):
                add(f"{case_path}.validation_loop.escalation_condition", f"risk {risk.id} requires escalation")
            if not case.required_evidence:
                add(f"{case_path}.required_evidence", f"risk {risk.id} requires declared evidence")

    if document.open_questions:
        add("open_questions", "all open questions must be resolved or explicitly deferred")
    if unresolved_blocking_decisions:
        add(
            "choices",
            f"{unresolved_blocking_decisions} blocking suggested decision(s) remain unresolved",
        )
    return issues


def validate_for_approval(
    document: SpecificationDocument,
    *,
    unresolved_blocking_decisions: int = 0,
) -> None:
    issues = approval_issues(
        document,
        unresolved_blocking_decisions=unresolved_blocking_decisions,
    )
    if issues:
        raise SpecificationValidationError(issues)


@dataclass(frozen=True)
class StoredSpecificationVersion:
    specification_id: str
    repository_path: str
    status: str
    current_version: int
    version: int
    document: SpecificationDocument
    canonical_content_hash: str
    artifact_path: Path
    artifact_hash: str
    change_summary: str
    creator: str
    created_at: str
    approved_at: str | None
    approved_by: str | None


@dataclass(frozen=True)
class StoredSpecificationAnalysis:
    """One immutable model analysis bound to an exact specification version."""

    analysis_id: str
    specification_id: str
    source_version: int
    provider: str
    model: str
    status: str
    prompt_hash: str
    validated_result: dict[str, Any] | None
    artifact_path: Path | None
    artifact_hash: str | None
    error: str | None
    application_metadata: dict[str, Any]
    created_at: str
    updated_at: str


def _additive_changes(source: Any, target: Any, path: str = "specification") -> list[dict[str, Any]]:
    """Describe fills and appends between already validated additive documents."""

    changes: list[dict[str, Any]] = []
    if isinstance(source, dict) and isinstance(target, dict):
        for key in source:
            changes.extend(_additive_changes(source[key], target[key], f"{path}.{key}"))
    elif isinstance(source, list) and isinstance(target, list):
        for index, value in enumerate(source):
            changes.extend(
                _additive_changes(value, target[index], f"{path}[{index}]")
            )
        for index, value in enumerate(target[len(source) :], len(source)):
            changes.append(
                {
                    "path": f"{path}[{index}]",
                    "operation": "append",
                    "value": normalize_numeric_values(value),
                }
            )
    elif isinstance(source, str) and source == "" and target != "":
        changes.append({"path": path, "operation": "fill", "value": target})
    return changes


class SpecificationService:
    """Persistence boundary for formal specifications and their state machine."""

    def __init__(self, db_path: str | Path, artifacts_root: str | Path | None = None):
        self.db_path = Path(db_path).expanduser().resolve()
        self.artifacts_root = (
            Path(artifacts_root).expanduser().resolve()
            if artifacts_root
            else self.db_path.parent / "artifacts"
        )
        db.init_db(self.db_path)

    def create(
        self,
        repository_path: str | Path,
        document: SpecificationDocument,
        *,
        creator: str,
        change_summary: str = "Initial draft",
        specification_id: str | None = None,
    ) -> StoredSpecificationVersion:
        repository = Path(repository_path).expanduser().resolve()
        validate_structural(document, worktree=repository)
        spec_id = specification_id or f"SPEC-{uuid.uuid4().hex.upper()}"
        if not STABLE_ID_PATTERN.fullmatch(spec_id) or len(spec_id) > MAX_STABLE_ID_LENGTH:
            raise SpecificationError("specification_id must be a stable uppercase identifier")
        now = db.utc_now()
        artifact_path, artifact_hash = self._write_version_artifact(spec_id, 1, document)
        try:
            with db.transaction(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO specifications (
                        id, repository_path, status, current_version, title,
                        created_at, updated_at
                    ) VALUES (?, ?, 'draft', 1, ?, ?, ?)
                    """,
                    (spec_id, str(repository), document.title, now, now),
                )
                self._insert_version(
                    conn,
                    spec_id,
                    1,
                    document,
                    artifact_path,
                    artifact_hash,
                    change_summary,
                    creator,
                    now,
                )
        except Exception:
            artifact_path.unlink(missing_ok=True)
            raise
        self._write_latest(spec_id, document)
        return self.load(spec_id, 1)

    def list(self, repository_path: str | Path | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM specifications"
        parameters: tuple[Any, ...] = ()
        if repository_path is not None:
            query += " WHERE repository_path = ?"
            parameters = (str(Path(repository_path).expanduser().resolve()),)
        query += " ORDER BY updated_at DESC, id"
        with db.transaction(self.db_path) as conn:
            return [dict(row) for row in conn.execute(query, parameters)]

    def load(self, specification_id: str, version: int | None = None) -> StoredSpecificationVersion:
        return self.verify_integrity(specification_id, version)

    def list_analyses(self, specification_id: str) -> list[StoredSpecificationAnalysis]:
        """Return immutable analyses after verifying each stored result and artifact."""

        with db.transaction(self.db_path) as conn:
            self._identity(conn, specification_id)
            analysis_ids = [
                str(row["id"])
                for row in conn.execute(
                    """
                    SELECT id FROM specification_analyses
                    WHERE specification_id = ?
                    ORDER BY created_at, id
                    """,
                    (specification_id,),
                )
            ]
        return [self.load_analysis(analysis_id) for analysis_id in analysis_ids]

    def store_analysis(
        self,
        *,
        analysis_id: str,
        specification_id: str,
        source_version: int,
        source_content_hash: str,
        provider: str,
        model: str,
        prompt_hash: str,
        validated_result: Mapping[str, Any],
        application_metadata: Mapping[str, Any] | None = None,
    ) -> StoredSpecificationAnalysis:
        """Persist a validated analysis without allowing stale-source writes.

        Semantic validation of ``validated_result`` belongs to the elicitation
        engine.  This service owns freshness, canonicalization, immutable
        artifact creation, hashes, and the database transaction.
        """

        self._validate_analysis_identity(analysis_id, provider, prompt_hash)
        result = dict(validated_result)
        result_json = canonical_json(result)
        payload = (
            json.dumps(
                normalize_numeric_values(result),
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        artifact_path = self._analysis_directory(specification_id) / f"{analysis_id}.json"
        artifact_hash = self._write_immutable_artifact(
            artifact_path, payload, description="analysis artifact"
        )
        now = db.utc_now()
        try:
            with db.transaction(self.db_path) as conn:
                identity = self._identity(conn, specification_id)
                if int(identity["current_version"]) != source_version:
                    raise SpecificationStateError(
                        "specification changed after elicitation began; analysis source is stale"
                    )
                source = conn.execute(
                    """
                    SELECT canonical_content_hash FROM specification_versions
                    WHERE specification_id = ? AND version = ?
                    """,
                    (specification_id, source_version),
                ).fetchone()
                if source is None:
                    raise KeyError(
                        f"Unknown specification version: {specification_id} v{source_version}"
                    )
                if source["canonical_content_hash"] != source_content_hash:
                    raise SpecificationIntegrityError(
                        "elicitation source content hash does not match the immutable version"
                    )
                conn.execute(
                    """
                    INSERT INTO specification_analyses (
                        id, specification_id, source_version, provider, model,
                        status, prompt_hash, validated_result_json, artifact_path,
                        artifact_hash, error, application_metadata_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'validated', ?, ?, ?, ?, NULL, ?, ?, ?)
                    """,
                    (
                        analysis_id,
                        specification_id,
                        source_version,
                        provider,
                        model,
                        prompt_hash,
                        result_json,
                        str(artifact_path),
                        artifact_hash,
                        db.to_json(dict(application_metadata or {})),
                        now,
                        now,
                    ),
                )
        except Exception:
            artifact_path.unlink(missing_ok=True)
            raise
        return self.load_analysis(analysis_id)

    def record_analysis_failure(
        self,
        *,
        analysis_id: str,
        specification_id: str,
        source_version: int,
        provider: str,
        model: str,
        prompt_hash: str,
        error: str,
        status: str = "failed",
    ) -> StoredSpecificationAnalysis:
        """Record an exhausted or stale analysis attempt without an artifact."""

        self._validate_analysis_identity(analysis_id, provider, prompt_hash)
        if status not in {"failed", "stale"}:
            raise SpecificationError("analysis failure status must be failed or stale")
        now = db.utc_now()
        with db.transaction(self.db_path) as conn:
            self._identity(conn, specification_id)
            source = conn.execute(
                """
                SELECT 1 FROM specification_versions
                WHERE specification_id = ? AND version = ?
                """,
                (specification_id, source_version),
            ).fetchone()
            if source is None:
                raise KeyError(
                    f"Unknown specification version: {specification_id} v{source_version}"
                )
            conn.execute(
                """
                INSERT INTO specification_analyses (
                    id, specification_id, source_version, provider, model,
                    status, prompt_hash, validated_result_json, artifact_path,
                    artifact_hash, error, application_metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, '{}', ?, ?)
                """,
                (
                    analysis_id,
                    specification_id,
                    source_version,
                    provider,
                    model,
                    status,
                    prompt_hash,
                    error,
                    now,
                    now,
                ),
            )
        return self.load_analysis(analysis_id)

    def load_analysis(self, analysis_id: str) -> StoredSpecificationAnalysis:
        """Load an analysis and verify its source, canonical JSON, and artifact."""

        with db.transaction(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM specification_analyses WHERE id = ?", (analysis_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown specification analysis: {analysis_id}")
            analysis = dict(row)
        self.verify_integrity(analysis["specification_id"], int(analysis["source_version"]))

        result_text = analysis["validated_result_json"]
        artifact_path_text = analysis["artifact_path"]
        artifact_hash = analysis["artifact_hash"]
        result: dict[str, Any] | None = None
        artifact_path: Path | None = None
        if analysis["status"] == "validated":
            if not isinstance(result_text, str) or not result_text:
                raise SpecificationIntegrityError("validated analysis has no result JSON")
            try:
                parsed = json.loads(result_text)
            except json.JSONDecodeError as exc:
                raise SpecificationIntegrityError(
                    f"stored analysis result JSON is invalid: {exc}"
                ) from exc
            if not isinstance(parsed, dict) or canonical_json(parsed) != result_text:
                raise SpecificationIntegrityError(
                    "stored analysis result is not its canonical representation"
                )
            if not isinstance(artifact_path_text, str) or not isinstance(artifact_hash, str):
                raise SpecificationIntegrityError("validated analysis has incomplete artifact metadata")
            artifact_path = Path(artifact_path_text)
            try:
                artifact_bytes = artifact_path.read_bytes()
            except OSError as exc:
                raise SpecificationIntegrityError(
                    f"analysis artifact is unavailable: {exc}"
                ) from exc
            if sha256_bytes(artifact_bytes) != artifact_hash:
                raise SpecificationIntegrityError("analysis artifact hash mismatch")
            try:
                artifact_result = json.loads(artifact_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SpecificationIntegrityError(f"analysis artifact is invalid: {exc}") from exc
            if not isinstance(artifact_result, dict) or canonical_json(artifact_result) != result_text:
                raise SpecificationIntegrityError(
                    "analysis artifact content differs from stored result JSON"
                )
            result = parsed
        elif result_text is not None or artifact_path_text is not None or artifact_hash is not None:
            raise SpecificationIntegrityError("failed analysis unexpectedly contains a validated artifact")

        metadata = db.from_json(analysis["application_metadata_json"], {})
        if not isinstance(metadata, dict):
            raise SpecificationIntegrityError("analysis application metadata must be an object")
        return StoredSpecificationAnalysis(
            analysis_id=analysis["id"],
            specification_id=analysis["specification_id"],
            source_version=int(analysis["source_version"]),
            provider=analysis["provider"],
            model=analysis["model"],
            status=analysis["status"],
            prompt_hash=analysis["prompt_hash"],
            validated_result=result,
            artifact_path=artifact_path,
            artifact_hash=artifact_hash,
            error=analysis["error"],
            application_metadata=metadata,
            created_at=analysis["created_at"],
            updated_at=analysis["updated_at"],
        )

    def list_decisions(self, specification_id: str) -> list[dict[str, Any]]:
        """Return suggested choices without exposing SQLite formatting to frontends."""

        with db.transaction(self.db_path) as conn:
            self._identity(conn, specification_id)
            rows = conn.execute(
                """
                SELECT * FROM specification_decisions
                WHERE specification_id = ?
                ORDER BY source_version, created_at, id
                """,
                (specification_id,),
            )
            decisions: list[dict[str, Any]] = []
            for row in rows:
                decision = dict(row)
                decision["options"] = db.from_json(decision.pop("options_json"), [])
                decision["blocking"] = bool(decision["blocking"])
                decisions.append(decision)
            return decisions

    def apply_analysis(
        self,
        analysis_id: str,
        *,
        application_mode: str,
        document: SpecificationDocument,
        choices: Sequence[Mapping[str, Any]],
        creator: str,
    ) -> tuple[StoredSpecificationVersion, StoredSpecificationAnalysis]:
        """Atomically apply a validated analysis as a new immutable draft revision.

        ``application_mode`` is either ``choices_only`` (the new revision is
        content-identical to the source) or ``apply_all`` (the stored additive
        suggestion becomes the new revision).  The immutable analysis is the
        authority for both the expected document and choices; callers cannot
        substitute GUI-edited data.  Freshness is checked before artifact
        creation and again in the committing transaction.
        """

        if application_mode not in {"choices_only", "apply_all"}:
            raise SpecificationError(
                "analysis application_mode must be choices_only or apply_all"
            )
        if not isinstance(creator, str) or not creator.strip():
            raise SpecificationError("analysis application creator must not be empty")

        analysis = self.load_analysis(analysis_id)
        if analysis.status != "validated" or analysis.validated_result is None:
            raise SpecificationStateError("only a validated analysis can be applied")
        source = self.load(analysis.specification_id, analysis.source_version)
        result = analysis.validated_result
        suggestion_value = result.get("suggested_specification")
        expected_choices = result.get("choices")
        if not isinstance(suggestion_value, Mapping) or not isinstance(expected_choices, list):
            raise SpecificationIntegrityError(
                "validated analysis does not contain an applicable specification and choices"
            )
        suggested_document = SpecificationDocument.from_dict(
            suggestion_value,
            worktree=source.repository_path,
        )
        expected_document = source.document if application_mode == "choices_only" else suggested_document
        if document.canonical_json() != expected_document.canonical_json():
            raise SpecificationIntegrityError(
                "analysis application document differs from the immutable validated result"
            )
        choice_payloads = [dict(choice) for choice in choices]
        if canonical_json({"choices": choice_payloads}) != canonical_json(
            {"choices": expected_choices}
        ):
            raise SpecificationIntegrityError(
                "analysis application choices differ from the immutable validated result"
            )
        validate_structural(document, worktree=source.repository_path)

        with db.transaction(self.db_path) as conn:
            identity = self._identity(conn, analysis.specification_id)
            if int(identity["current_version"]) != analysis.source_version:
                raise SpecificationStateError(
                    f"Cannot apply analysis {analysis_id}: it was created from version "
                    f"{analysis.source_version}, but the current stored draft is version "
                    f"{identity['current_version']}. Run Analyze again from the current draft."
                )
            if identity["status"] != "draft":
                raise SpecificationStateError(
                    "analysis can only be applied while its source specification is a draft"
                )
        if analysis.application_metadata.get("applied_version") is not None:
            raise SpecificationStateError(
                f"analysis {analysis_id} was already applied to version "
                f"{analysis.application_metadata['applied_version']}"
            )

        version = analysis.source_version + 1
        added = _additive_changes(source.document.to_dict(), document.to_dict())
        now = db.utc_now()
        decision_rows = [
            (f"DECISION-{uuid.uuid4().hex.upper()}", choice) for choice in choice_payloads
        ]
        change_summary = (
            f"Applied AI analysis {analysis_id} ({application_mode}): "
            f"{len(added)} specification addition(s), {len(decision_rows)} choice(s)"
        )
        artifact_path, artifact_hash = self._write_version_artifact(
            analysis.specification_id, version, document
        )
        metadata = dict(analysis.application_metadata)
        metadata.update(
            {
                "applied_analysis_id": analysis_id,
                "application_mode": application_mode,
                "applied_version": version,
                "added": added,
                "decisions_created": len(decision_rows),
                "applied_by": creator,
                "applied_at": now,
            }
        )
        try:
            with db.transaction(self.db_path) as conn:
                identity = self._identity(conn, analysis.specification_id)
                if (
                    int(identity["current_version"]) != analysis.source_version
                    or identity["status"] != "draft"
                ):
                    raise SpecificationStateError(
                        f"Cannot apply analysis {analysis_id}: the stored draft changed after "
                        "analysis began. Run Analyze again from the current draft."
                    )
                analysis_row = conn.execute(
                    "SELECT application_metadata_json FROM specification_analyses WHERE id = ?",
                    (analysis_id,),
                ).fetchone()
                if analysis_row is None:
                    raise SpecificationIntegrityError("analysis disappeared during application")
                current_metadata = db.from_json(analysis_row["application_metadata_json"], {})
                if not isinstance(current_metadata, dict):
                    raise SpecificationIntegrityError(
                        "analysis application metadata must be an object"
                    )
                if current_metadata.get("applied_version") is not None:
                    raise SpecificationStateError(
                        f"analysis {analysis_id} was already applied to version "
                        f"{current_metadata['applied_version']}"
                    )
                self._insert_version(
                    conn,
                    analysis.specification_id,
                    version,
                    document,
                    artifact_path,
                    artifact_hash,
                    change_summary,
                    creator,
                    now,
                )
                for decision_id, choice in decision_rows:
                    conn.execute(
                        """
                        INSERT INTO specification_decisions (
                            id, specification_id, source_version, topic, question,
                            context, options_json, recommendation, blocking, status,
                            selected_option, rationale, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'unresolved', NULL, NULL, ?, ?)
                        """,
                        (
                            decision_id,
                            analysis.specification_id,
                            analysis.source_version,
                            choice["topic"],
                            choice["question"],
                            choice["context"],
                            db.to_json(choice["options"]),
                            choice["recommendation"],
                            1 if choice["blocking"] else 0,
                            now,
                            now,
                        ),
                    )
                conn.execute(
                    """
                    UPDATE specifications
                    SET status = 'draft', current_version = ?, title = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (version, document.title, now, analysis.specification_id),
                )
                conn.execute(
                    """
                    UPDATE specification_analyses
                    SET application_metadata_json = ?, updated_at = ? WHERE id = ?
                    """,
                    (db.to_json(metadata), now, analysis_id),
                )
        except Exception:
            artifact_path.unlink(missing_ok=True)
            raise
        self._write_latest(analysis.specification_id, document)
        return self.load(analysis.specification_id, version), self.load_analysis(analysis_id)

    def revise(
        self,
        specification_id: str,
        document: SpecificationDocument,
        *,
        change_summary: str,
        creator: str,
    ) -> StoredSpecificationVersion:
        with db.transaction(self.db_path) as conn:
            identity = self._identity(conn, specification_id)
        if identity["status"] not in {"draft", "approved"}:
            raise SpecificationStateError("only a draft or approved specification can be revised")
        validate_structural(document, worktree=identity["repository_path"])
        version = int(identity["current_version"]) + 1
        now = db.utc_now()
        artifact_path, artifact_hash = self._write_version_artifact(specification_id, version, document)
        try:
            with db.transaction(self.db_path) as conn:
                current = self._identity(conn, specification_id)
                if int(current["current_version"]) != version - 1 or current["status"] not in {
                    "draft",
                    "approved",
                }:
                    raise SpecificationStateError("specification changed while the revision was being saved")
                self._insert_version(
                    conn,
                    specification_id,
                    version,
                    document,
                    artifact_path,
                    artifact_hash,
                    change_summary,
                    creator,
                    now,
                )
                conn.execute(
                    """
                    UPDATE specifications
                    SET status = 'draft', current_version = ?, title = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (version, document.title, now, specification_id),
                )
        except Exception:
            artifact_path.unlink(missing_ok=True)
            raise
        self._write_latest(specification_id, document)
        return self.load(specification_id, version)

    def submit_for_review(self, specification_id: str) -> StoredSpecificationVersion:
        with db.transaction(self.db_path) as conn:
            identity = self._identity(conn, specification_id)
            if identity["status"] != "draft":
                raise SpecificationStateError("only a draft can be submitted for review")
            conn.execute(
                "UPDATE specifications SET status = 'review', updated_at = ? WHERE id = ?",
                (db.utc_now(), specification_id),
            )
            version = int(identity["current_version"])
        return self.load(specification_id, version)

    def return_to_draft(self, specification_id: str) -> StoredSpecificationVersion:
        with db.transaction(self.db_path) as conn:
            identity = self._identity(conn, specification_id)
            if identity["status"] != "review":
                raise SpecificationStateError("only a specification under review can return to draft")
            conn.execute(
                "UPDATE specifications SET status = 'draft', updated_at = ? WHERE id = ?",
                (db.utc_now(), specification_id),
            )
            version = int(identity["current_version"])
        return self.load(specification_id, version)

    def approve(self, specification_id: str, *, approved_by: str) -> StoredSpecificationVersion:
        if not _nonempty(approved_by):
            raise SpecificationError("approved_by must identify the approving user")
        with db.transaction(self.db_path) as conn:
            identity = self._identity(conn, specification_id)
            if identity["status"] != "review":
                raise SpecificationStateError("only a submitted specification can be approved")
            version = int(identity["current_version"])
            unresolved = conn.execute(
                """
                SELECT COUNT(*) FROM specification_decisions
                WHERE specification_id = ? AND source_version <= ?
                  AND blocking = 1 AND status = 'unresolved'
                """,
                (specification_id, version),
            ).fetchone()[0]
        stored = self.verify_integrity(specification_id, version)
        validate_for_approval(
            stored.document,
            unresolved_blocking_decisions=int(unresolved),
        )
        now = db.utc_now()
        with db.transaction(self.db_path) as conn:
            current = self._identity(conn, specification_id)
            if current["status"] != "review" or int(current["current_version"]) != version:
                raise SpecificationStateError("specification changed while approval was being recorded")
            current_unresolved = conn.execute(
                """
                SELECT COUNT(*) FROM specification_decisions
                WHERE specification_id = ? AND source_version <= ?
                  AND blocking = 1 AND status = 'unresolved'
                """,
                (specification_id, version),
            ).fetchone()[0]
            if current_unresolved:
                raise SpecificationStateError("a blocking suggested decision appeared during approval")
            conn.execute(
                """
                UPDATE specification_versions SET approved_at = ?, approved_by = ?
                WHERE specification_id = ? AND version = ?
                """,
                (now, approved_by, specification_id, version),
            )
            conn.execute(
                """
                UPDATE specifications
                SET status = 'approved', approved_version = ?, approved_at = ?,
                    approved_by = ?, updated_at = ? WHERE id = ?
                """,
                (version, now, approved_by, now, specification_id),
            )
        return self.load(specification_id, version)

    def supersede(self, specification_id: str) -> StoredSpecificationVersion:
        with db.transaction(self.db_path) as conn:
            identity = self._identity(conn, specification_id)
            if identity["status"] != "approved":
                raise SpecificationStateError("only an approved specification can be superseded")
            conn.execute(
                "UPDATE specifications SET status = 'superseded', updated_at = ? WHERE id = ?",
                (db.utc_now(), specification_id),
            )
            version = int(identity["current_version"])
        return self.load(specification_id, version)

    def resolve_decision(
        self,
        specification_id: str,
        decision_id: str,
        *,
        selected_option: str,
        rationale: str,
        deferred: bool = False,
    ) -> dict[str, Any]:
        with db.transaction(self.db_path) as conn:
            self._identity(conn, specification_id)
            row = conn.execute(
                """
                SELECT * FROM specification_decisions
                WHERE id = ? AND specification_id = ?
                """,
                (decision_id, specification_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown suggested decision: {decision_id}")
            if row["status"] != "unresolved":
                raise SpecificationStateError("suggested decision is already resolved")
            options = db.from_json(row["options_json"], [])
            option_names = {
                str(option.get("name", option.get("label", "")))
                for option in options
                if isinstance(option, dict)
            }
            if options and selected_option not in option_names:
                raise SpecificationError("selected option is not one of the proposed choices")
            if deferred and bool(row["blocking"]):
                raise SpecificationStateError("a blocking decision cannot be deferred")
            status = "deferred" if deferred else "resolved"
            conn.execute(
                """
                UPDATE specification_decisions
                SET status = ?, selected_option = ?, rationale = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, selected_option, rationale, db.utc_now(), decision_id),
            )
            updated = conn.execute(
                "SELECT * FROM specification_decisions WHERE id = ?",
                (decision_id,),
            ).fetchone()
            return dict(updated)

    def attach_to_job(
        self,
        specification_id: str,
        version: int,
        job_id: str,
    ) -> StoredSpecificationVersion:
        stored = self.verify_integrity(specification_id, version)
        if stored.approved_at is None:
            raise SpecificationStateError("only an approved immutable version can be attached to a job")
        # Local import keeps the specification model independent of the
        # compiler while making attachment use the exact same compilation,
        # persistence, and integrity path as initial formal-job creation.
        from ai_loop.specification_compiler import VerificationManifestService

        VerificationManifestService(self).attach_approved_specification(
            job_id, specification_id, version
        )
        return stored

    def attach_newer_approved_revision(
        self,
        job_id: str,
        specification_id: str,
        version: int,
        *,
        task_publisher: Callable[[str], bool],
    ) -> Any:
        """Retarget a formal job and publish its task through the queue boundary."""

        from ai_loop.specification_compiler import VerificationManifestService

        result = VerificationManifestService(self).retarget_approved_revision(
            job_id, specification_id, version
        )
        if result.task_id is not None:
            try:
                task_publisher(result.task_id)
            except Exception as exc:
                with db.transaction(self.db_path) as conn:
                    db.add_event(
                        conn,
                        job_id=job_id,
                        kind="task_queue_publication_failed",
                        payload={"task_id": result.task_id, "error": str(exc)},
                    )
                raise SpecificationStateError(
                    f"retarget task {result.task_id} was persisted but queue publication "
                    "failed; retry publication with LoopBackend.publish_task"
                ) from exc
        return result

    def verify_job_change_impact(self, impact_id: str) -> Any:
        """Integrity-load an immutable formal-job change-impact artifact."""

        from ai_loop.specification_compiler import VerificationManifestService

        return VerificationManifestService(self).verify_change_impact(impact_id)

    def create_formal_job(self, **job: Any) -> Any:
        """Create a pinned ordinary job through the manifest service boundary."""

        from ai_loop.specification_compiler import VerificationManifestService

        return VerificationManifestService(self).create_formal_job(**job)

    def load_job_manifest(self, job_id: str, *, backfill: bool = True) -> Any:
        """Integrity-load or lazily backfill a formal job's immutable manifest."""

        from ai_loop.specification_compiler import VerificationManifestService

        return VerificationManifestService(self).load_for_job(job_id, backfill=backfill)

    def load_job_prompt_context(
        self,
        job_id: str,
        *,
        backfill: bool = True,
        worker_run_id: str | None = None,
    ) -> Any:
        """Load the integrity-checked formal prompt contract, or ``None`` for Quick Goal."""

        from ai_loop.specification_compiler import VerificationManifestService

        return VerificationManifestService(self).load_prompt_context(
            job_id,
            backfill=backfill,
            worker_run_id=worker_run_id,
        )

    def verify_integrity(
        self,
        specification_id: str,
        version: int | None = None,
    ) -> StoredSpecificationVersion:
        with db.transaction(self.db_path) as conn:
            identity = self._identity(conn, specification_id)
            selected_version = int(identity["current_version"]) if version is None else version
            row = conn.execute(
                """
                SELECT * FROM specification_versions
                WHERE specification_id = ? AND version = ?
                """,
                (specification_id, selected_version),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown specification version: {specification_id} v{selected_version}")
            version_row = dict(row)
        canonical_text = version_row["canonical_json"]
        try:
            document = SpecificationDocument.from_json(
                canonical_text,
                worktree=identity["repository_path"],
            )
        except SpecificationError as exc:
            raise SpecificationIntegrityError(f"stored specification JSON is invalid: {exc}") from exc
        if document.schema_version != version_row["schema_version"]:
            raise SpecificationIntegrityError("stored schema version does not match canonical JSON")
        if document.canonical_json() != canonical_text:
            raise SpecificationIntegrityError("stored specification JSON is not its canonical representation")
        actual_content_hash = sha256_text(canonical_text)
        if actual_content_hash != version_row["canonical_content_hash"]:
            raise SpecificationIntegrityError("canonical specification content hash mismatch")
        artifact_path = Path(version_row["artifact_path"])
        try:
            artifact_bytes = artifact_path.read_bytes()
        except OSError as exc:
            raise SpecificationIntegrityError(f"specification artifact is unavailable: {exc}") from exc
        if sha256_bytes(artifact_bytes) != version_row["artifact_hash"]:
            raise SpecificationIntegrityError("specification artifact hash mismatch")
        try:
            artifact_document = SpecificationDocument.from_json(
                artifact_bytes.decode("utf-8"),
                worktree=identity["repository_path"],
            )
        except (UnicodeDecodeError, SpecificationError) as exc:
            raise SpecificationIntegrityError(f"specification artifact is invalid: {exc}") from exc
        if artifact_document.canonical_json() != canonical_text:
            raise SpecificationIntegrityError("specification artifact content differs from canonical JSON")
        return StoredSpecificationVersion(
            specification_id=specification_id,
            repository_path=identity["repository_path"],
            status=identity["status"],
            current_version=int(identity["current_version"]),
            version=selected_version,
            document=document,
            canonical_content_hash=version_row["canonical_content_hash"],
            artifact_path=artifact_path,
            artifact_hash=version_row["artifact_hash"],
            change_summary=version_row["change_summary"],
            creator=version_row["creator"],
            created_at=version_row["created_at"],
            approved_at=version_row["approved_at"],
            approved_by=version_row["approved_by"],
        )

    @staticmethod
    def _identity(conn: sqlite3.Connection, specification_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM specifications WHERE id = ?", (specification_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown specification: {specification_id}")
        identity = dict(row)
        if identity["status"] not in SPECIFICATION_STATUSES:
            raise SpecificationIntegrityError(f"invalid specification status: {identity['status']}")
        return identity

    @staticmethod
    def _insert_version(
        conn: sqlite3.Connection,
        specification_id: str,
        version: int,
        document: SpecificationDocument,
        artifact_path: Path,
        artifact_hash: str,
        change_summary: str,
        creator: str,
        created_at: str,
    ) -> None:
        canonical_text = document.canonical_json()
        conn.execute(
            """
            INSERT INTO specification_versions (
                specification_id, version, schema_version, canonical_json,
                canonical_content_hash, artifact_path, artifact_hash,
                change_summary, creator, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                specification_id,
                version,
                document.schema_version,
                canonical_text,
                sha256_text(canonical_text),
                str(artifact_path),
                artifact_hash,
                change_summary,
                creator,
                created_at,
            ),
        )

    def _version_directory(self, specification_id: str) -> Path:
        return self.artifacts_root / "specifications" / specification_id / "versions"

    def _analysis_directory(self, specification_id: str) -> Path:
        return self.artifacts_root / "specifications" / specification_id / "analyses"

    def _write_version_artifact(
        self,
        specification_id: str,
        version: int,
        document: SpecificationDocument,
    ) -> tuple[Path, str]:
        path = self._version_directory(specification_id) / f"{version:04d}.json"
        payload = document.pretty_json().encode("utf-8")
        artifact_hash = self._write_immutable_artifact(
            path, payload, description="version artifact"
        )
        return path, artifact_hash

    def _write_immutable_artifact(
        self, path: Path, payload: bytes, *, description: str = "artifact"
    ) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise SpecificationIntegrityError(f"immutable {description} already exists: {path}")
        temporary = self._atomic_temporary(path.parent, path.name)
        try:
            temporary.write_bytes(payload)
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise SpecificationIntegrityError(
                    f"immutable {description} already exists: {path}"
                ) from exc
        finally:
            temporary.unlink(missing_ok=True)
        return sha256_bytes(payload)

    @staticmethod
    def _validate_analysis_identity(analysis_id: str, provider: str, prompt_hash: str) -> None:
        if (
            not isinstance(analysis_id, str)
            or len(analysis_id) > MAX_STABLE_ID_LENGTH
            or not STABLE_ID_PATTERN.fullmatch(analysis_id)
        ):
            raise SpecificationError("analysis_id must be a stable uppercase identifier")
        if not isinstance(provider, str) or not provider.strip():
            raise SpecificationError("analysis provider must not be empty")
        if not isinstance(prompt_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", prompt_hash):
            raise SpecificationError("analysis prompt_hash must be a lowercase SHA-256 hash")

    def _write_latest(self, specification_id: str, document: SpecificationDocument) -> None:
        directory = self._version_directory(specification_id).parent
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "latest.json"
        temporary = self._atomic_temporary(directory, path.name)
        try:
            temporary.write_text(document.pretty_json(), encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _atomic_temporary(directory: Path, destination_name: str) -> Path:
        handle, name = tempfile.mkstemp(prefix=f".{destination_name}.", suffix=".tmp", dir=directory)
        os.close(handle)
        return Path(name)


__all__ = [
    "AutomationLevel",
    "CoverageTarget",
    "CoverageType",
    "CURRENT_SCHEMA_VERSION",
    "EvidenceDeclaration",
    "EvidenceKind",
    "EVIDENCE_NAME_PATTERN",
    "MetricAssertion",
    "Requirement",
    "RequirementCategory",
    "RequirementPriority",
    "Risk",
    "RiskSeverity",
    "RiskUncertainty",
    "SpecificationDecision",
    "SpecificationDocument",
    "SpecificationError",
    "SpecificationIntegrityError",
    "SpecificationService",
    "SpecificationStateError",
    "SpecificationValidationError",
    "StoredSpecificationVersion",
    "StoredSpecificationAnalysis",
    "TestLevel",
    "UseCase",
    "ValidationIssue",
    "ValidationLoop",
    "VerificationCase",
    "VerificationMethod",
    "approval_issues",
    "canonical_json",
    "normalize_numeric_values",
    "structural_issues",
    "validate_for_approval",
    "validate_structural",
    "validate_working_directory",
]
