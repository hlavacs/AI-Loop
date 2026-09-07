"""Deterministic verification-manifest compilation and persistence.

The compiler consumes one approved immutable specification snapshot and a
concrete job test command.  The persistence service owns job pinning,
immutable manifest artifacts, hash verification, state initialization, and
legacy formal-job backfill.  Controller and worker prompt integration is
deliberately outside this module.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ai_loop import db
from ai_loop.specifications import (
    AutomationLevel,
    CoverageType,
    EvidenceKind,
    EVIDENCE_NAME_PATTERN,
    METRIC_OPERATORS,
    MAX_STABLE_ID_LENGTH,
    RequirementCategory,
    RequirementPriority,
    STABLE_ID_PATTERN,
    SpecificationError,
    SpecificationIntegrityError,
    SpecificationService,
    SpecificationStateError,
    StoredSpecificationVersion,
    TestLevel,
    VerificationMethod,
    canonical_json,
    normalize_numeric_values,
    sha256_bytes,
    sha256_text,
    validate_working_directory,
)


CURRENT_MANIFEST_SCHEMA_VERSION = "1.0"
SUPPORTED_MANIFEST_SCHEMA_VERSIONS = frozenset({CURRENT_MANIFEST_SCHEMA_VERSION})
COMMAND_SOURCES = frozenset({"specification", "job_default", "manual"})
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

_ROOT_FIELDS = frozenset({"schema_version", "specification", "work_items", "verification"})
_SPECIFICATION_FIELDS = frozenset({"id", "version", "schema_version", "content_hash"})
_WORK_ITEM_FIELDS = frozenset(
    {
        "requirement_id",
        "category",
        "priority",
        "title",
        "statement",
        "acceptance_criteria",
        "linked_use_case_ids",
        "linked_risk_ids",
        "linked_verification_ids",
    }
)
_VERIFICATION_FIELDS = frozenset(
    {
        "verification_id",
        "title",
        "requirement_ids",
        "risk_ids",
        "test_level",
        "method",
        "automation",
        "blocking",
        "command",
        "command_source",
        "working_directory",
        "timeout",
        "oracle",
        "fixtures",
        "procedure",
        "pass_criteria",
        "metrics",
        "metric_assertions",
        "coverage_targets",
        "required_evidence",
        "validation_loop",
    }
)
_ASSERTION_FIELDS = frozenset({"metric", "operator", "threshold", "tolerance"})
_COVERAGE_TARGET_FIELDS = frozenset(
    {
        "name",
        "coverage_type",
        "description",
        "measurement_key",
        "operator",
        "threshold",
        "tolerance",
        "required_scenarios",
        "evidence_kind",
    }
)
_EVIDENCE_DECLARATION_FIELDS = frozenset(
    {"name", "kind", "media_type", "description", "requirement_ids"}
)
_LOOP_FIELDS = frozenset(
    {
        "maximum_correction_attempts",
        "repetitions_per_attempt",
        "stagnation_limit",
        "escalation_condition",
        "retain_evidence",
    }
)


class ManifestCompilationError(SpecificationError):
    """An approved specification cannot produce an executable manifest."""


class ManifestIntegrityError(SpecificationIntegrityError):
    """Persisted manifest content or metadata failed an integrity check."""


def _strict_object(value: Any, expected: frozenset[str], path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestCompilationError(f"{path} must be an object")
    actual = set(value)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown:
        raise ManifestCompilationError(f"{path} contains unknown fields: {', '.join(unknown)}")
    if missing:
        raise ManifestCompilationError(f"{path} is missing fields: {', '.join(missing)}")
    return value


def _string(value: Any, path: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        qualifier = "non-empty " if nonempty else ""
        raise ManifestCompilationError(f"{path} must be a {qualifier}string")
    return value


def _positive_integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ManifestCompilationError(f"{path} must be a positive integer")
    return value


def _stable_id(value: Any, path: str) -> str:
    identifier = _string(value, path, nonempty=True)
    if len(identifier) > MAX_STABLE_ID_LENGTH or not STABLE_ID_PATTERN.fullmatch(identifier):
        raise ManifestCompilationError(f"{path} must be a stable uppercase identifier")
    return identifier


def _string_array(value: Any, path: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ManifestCompilationError(f"{path} must be an array")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_string(item, f"{path}[{index}]", nonempty=nonempty))
    return result


def _stable_id_array(value: Any, path: str) -> list[str]:
    if not isinstance(value, list):
        raise ManifestCompilationError(f"{path} must be an array")
    result = [_stable_id(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ManifestCompilationError(f"{path} contains duplicate identifiers")
    return result


def _finite_number(value: Any, path: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestCompilationError(f"{path} must be a number, not a boolean or string")
    try:
        finite = math.isfinite(float(value))
    except (OverflowError, ValueError):
        finite = False
    if not finite:
        raise ManifestCompilationError(f"{path} must be finite")
    return value


def _enum(value: Any, allowed: set[str], path: str) -> str:
    result = _string(value, path)
    if result not in allowed:
        raise ManifestCompilationError(f"{path} must be one of: {', '.join(sorted(allowed))}")
    return result


def _coverage_target(value: Any, path: str) -> str | dict[str, Any]:
    if isinstance(value, str):
        return value
    item = _strict_object(value, _COVERAGE_TARGET_FIELDS, path)
    measurement_key = item["measurement_key"]
    operator = item["operator"]
    threshold = item["threshold"]
    tolerance = item["tolerance"]
    evidence_kind = item["evidence_kind"]
    if measurement_key is not None:
        measurement_key = _string(measurement_key, f"{path}.measurement_key", nonempty=True)
    if operator is not None:
        operator = _enum(operator, set(METRIC_OPERATORS), f"{path}.operator")
    if threshold is not None:
        threshold = _finite_number(threshold, f"{path}.threshold")
    if tolerance is not None:
        tolerance = _finite_number(tolerance, f"{path}.tolerance")
        if tolerance < 0:
            raise ManifestCompilationError(f"{path}.tolerance must be non-negative")
    if evidence_kind is not None:
        evidence_kind = _enum(
            evidence_kind, {entry.value for entry in EvidenceKind}, f"{path}.evidence_kind"
        )
    supplied = tuple(
        value is not None for value in (measurement_key, operator, threshold, evidence_kind)
    )
    if any(supplied) and not all(supplied):
        raise ManifestCompilationError(
            f"{path} machine coverage requires measurement_key, operator, threshold, and evidence_kind together"
        )
    if all(supplied) and evidence_kind != EvidenceKind.COVERAGE.value:
        raise ManifestCompilationError(
            f"{path}.evidence_kind must be coverage for machine enforcement"
        )
    scenarios = _string_array(
        item["required_scenarios"], f"{path}.required_scenarios", nonempty=True
    )
    if len(scenarios) != len(set(scenarios)):
        raise ManifestCompilationError(f"{path}.required_scenarios contains duplicates")
    return {
        "name": _evidence_name(item["name"], f"{path}.name"),
        "coverage_type": _enum(
            item["coverage_type"], {entry.value for entry in CoverageType}, f"{path}.coverage_type"
        ),
        "description": _string(item["description"], f"{path}.description", nonempty=True),
        "measurement_key": measurement_key,
        "operator": operator,
        "threshold": threshold,
        "tolerance": tolerance,
        "required_scenarios": scenarios,
        "evidence_kind": evidence_kind,
    }


def _evidence_declaration(value: Any, path: str) -> str | dict[str, Any]:
    if isinstance(value, str):
        return value
    item = _strict_object(value, _EVIDENCE_DECLARATION_FIELDS, path)
    return {
        "name": _evidence_name(item["name"], f"{path}.name"),
        "kind": _enum(item["kind"], {entry.value for entry in EvidenceKind}, f"{path}.kind"),
        "media_type": _string(item["media_type"], f"{path}.media_type", nonempty=True),
        "description": _string(item["description"], f"{path}.description", nonempty=True),
        "requirement_ids": _stable_id_array(
            item["requirement_ids"], f"{path}.requirement_ids"
        ),
    }


def _evidence_name(value: Any, path: str) -> str:
    name = _string(value, path, nonempty=True)
    if not EVIDENCE_NAME_PATTERN.fullmatch(name):
        raise ManifestCompilationError(f"{path} must be a stable evidence name")
    return name


def _validate_manifest_payload(value: Any) -> dict[str, Any]:
    root = _strict_object(value, _ROOT_FIELDS, "manifest")
    schema_version = _string(root["schema_version"], "manifest.schema_version")
    if schema_version not in SUPPORTED_MANIFEST_SCHEMA_VERSIONS:
        raise ManifestCompilationError(f"unsupported manifest schema version: {schema_version}")

    specification = _strict_object(
        root["specification"], _SPECIFICATION_FIELDS, "manifest.specification"
    )
    specification_id = _stable_id(specification["id"], "manifest.specification.id")
    specification_version = _positive_integer(
        specification["version"], "manifest.specification.version"
    )
    specification_schema_version = _string(
        specification["schema_version"],
        "manifest.specification.schema_version",
        nonempty=True,
    )
    specification_hash = _string(
        specification["content_hash"], "manifest.specification.content_hash"
    )
    if not SHA256_PATTERN.fullmatch(specification_hash):
        raise ManifestCompilationError(
            "manifest.specification.content_hash must be a lowercase SHA-256 hash"
        )

    raw_work_items = root["work_items"]
    if not isinstance(raw_work_items, list):
        raise ManifestCompilationError("manifest.work_items must be an array")
    work_items: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_work_items):
        path = f"manifest.work_items[{index}]"
        item = _strict_object(raw, _WORK_ITEM_FIELDS, path)
        work_items.append(
            {
                "requirement_id": _stable_id(item["requirement_id"], f"{path}.requirement_id"),
                "category": _enum(
                    item["category"], {entry.value for entry in RequirementCategory}, f"{path}.category"
                ),
                "priority": _enum(
                    item["priority"], {entry.value for entry in RequirementPriority}, f"{path}.priority"
                ),
                "title": _string(item["title"], f"{path}.title"),
                "statement": _string(item["statement"], f"{path}.statement"),
                "acceptance_criteria": _string_array(
                    item["acceptance_criteria"], f"{path}.acceptance_criteria"
                ),
                "linked_use_case_ids": _stable_id_array(
                    item["linked_use_case_ids"], f"{path}.linked_use_case_ids"
                ),
                "linked_risk_ids": _stable_id_array(
                    item["linked_risk_ids"], f"{path}.linked_risk_ids"
                ),
                "linked_verification_ids": _stable_id_array(
                    item["linked_verification_ids"], f"{path}.linked_verification_ids"
                ),
            }
        )
    requirement_ids = [item["requirement_id"] for item in work_items]
    if len(requirement_ids) != len(set(requirement_ids)):
        raise ManifestCompilationError("manifest.work_items contains duplicate requirements")
    requirement_id_set = set(requirement_ids)

    raw_verification = root["verification"]
    if not isinstance(raw_verification, list):
        raise ManifestCompilationError("manifest.verification must be an array")
    verification: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_verification):
        path = f"manifest.verification[{index}]"
        item = _strict_object(raw, _VERIFICATION_FIELDS, path)
        assertions_value = item["metric_assertions"]
        if not isinstance(assertions_value, list):
            raise ManifestCompilationError(f"{path}.metric_assertions must be an array")
        assertions: list[dict[str, Any]] = []
        asserted_metrics: list[str] = []
        for assertion_index, raw_assertion in enumerate(assertions_value):
            assertion_path = f"{path}.metric_assertions[{assertion_index}]"
            assertion = _strict_object(raw_assertion, _ASSERTION_FIELDS, assertion_path)
            metric = _string(assertion["metric"], f"{assertion_path}.metric", nonempty=True)
            tolerance_value = assertion["tolerance"]
            tolerance = (
                None
                if tolerance_value is None
                else _finite_number(tolerance_value, f"{assertion_path}.tolerance")
            )
            if tolerance is not None and tolerance < 0:
                raise ManifestCompilationError(f"{assertion_path}.tolerance must be non-negative")
            assertions.append(
                {
                    "metric": metric,
                    "operator": _enum(
                        assertion["operator"], set(METRIC_OPERATORS), f"{assertion_path}.operator"
                    ),
                    "threshold": _finite_number(
                        assertion["threshold"], f"{assertion_path}.threshold"
                    ),
                    "tolerance": tolerance,
                }
            )
            asserted_metrics.append(metric)
        if len(asserted_metrics) != len(set(asserted_metrics)):
            raise ManifestCompilationError(f"{path}.metric_assertions contains duplicate metrics")

        loop = _strict_object(item["validation_loop"], _LOOP_FIELDS, f"{path}.validation_loop")
        if not isinstance(loop["retain_evidence"], bool):
            raise ManifestCompilationError(
                f"{path}.validation_loop.retain_evidence must be a boolean"
            )
        requirement_references = _stable_id_array(
            item["requirement_ids"], f"{path}.requirement_ids"
        )
        unknown_requirements = sorted(set(requirement_references) - requirement_id_set)
        if unknown_requirements:
            raise ManifestCompilationError(
                f"{path}.requirement_ids contains unknown requirements: {', '.join(unknown_requirements)}"
            )
        automation = _enum(
            item["automation"], {entry.value for entry in AutomationLevel}, f"{path}.automation"
        )
        method = _enum(
            item["method"], {entry.value for entry in VerificationMethod}, f"{path}.method"
        )
        if not isinstance(item["blocking"], bool):
            raise ManifestCompilationError(f"{path}.blocking must be a boolean")
        command_source = _enum(item["command_source"], set(COMMAND_SOURCES), f"{path}.command_source")
        command_value = item["command"]
        if automation == AutomationLevel.MANUAL.value or method == VerificationMethod.MANUAL.value:
            if automation != AutomationLevel.MANUAL.value or method != VerificationMethod.MANUAL.value:
                raise ManifestCompilationError(f"{path} has incompatible manual method and automation")
            if command_value is not None or command_source != "manual":
                raise ManifestCompilationError(f"{path} manual verification must use no command")
            if assertions:
                raise ManifestCompilationError(f"{path} manual verification cannot assert metrics")
            if item["blocking"]:
                raise ManifestCompilationError(f"{path} manual verification cannot block completion")
            command = None
        else:
            command = _string(command_value, f"{path}.command", nonempty=True)
            if command_source not in {"specification", "job_default"}:
                raise ManifestCompilationError(
                    f"{path}.command_source must identify an executable command source"
                )

        metrics = _string_array(item["metrics"], f"{path}.metrics", nonempty=True)
        if len(metrics) != len(set(metrics)):
            raise ManifestCompilationError(f"{path}.metrics contains duplicate names")
        undeclared = sorted(set(asserted_metrics) - set(metrics))
        if undeclared:
            raise ManifestCompilationError(
                f"{path}.metric_assertions contains undeclared metrics: {', '.join(undeclared)}"
            )
        working_directory = _string(
            item["working_directory"], f"{path}.working_directory", nonempty=True
        )
        try:
            validate_working_directory(working_directory)
        except SpecificationError as exc:
            raise ManifestCompilationError(f"{path}.working_directory: {exc}") from exc
        raw_coverage_targets = item["coverage_targets"]
        if not isinstance(raw_coverage_targets, list):
            raise ManifestCompilationError(f"{path}.coverage_targets must be an array")
        coverage_targets = [
            _coverage_target(value, f"{path}.coverage_targets[{target_index}]")
            for target_index, value in enumerate(raw_coverage_targets)
        ]
        structured_coverage_names = [
            value["name"] for value in coverage_targets if isinstance(value, dict)
        ]
        if len(structured_coverage_names) != len(set(structured_coverage_names)):
            raise ManifestCompilationError(f"{path}.coverage_targets contains duplicate names")
        if automation == AutomationLevel.MANUAL.value and any(
            isinstance(value, dict) and value.get("measurement_key") is not None
            for value in coverage_targets
        ):
            raise ManifestCompilationError(
                f"{path}.coverage_targets manual verification cannot enforce coverage"
            )

        raw_evidence = item["required_evidence"]
        if not isinstance(raw_evidence, list):
            raise ManifestCompilationError(f"{path}.required_evidence must be an array")
        required_evidence = [
            _evidence_declaration(value, f"{path}.required_evidence[{declaration_index}]")
            for declaration_index, value in enumerate(raw_evidence)
        ]
        structured_evidence_names = [
            value["name"] for value in required_evidence if isinstance(value, dict)
        ]
        if len(structured_evidence_names) != len(set(structured_evidence_names)):
            raise ManifestCompilationError(f"{path}.required_evidence contains duplicate names")
        for declaration in required_evidence:
            if not isinstance(declaration, dict):
                continue
            unknown = sorted(set(declaration["requirement_ids"]) - set(requirement_references))
            if unknown:
                raise ManifestCompilationError(
                    f"{path}.required_evidence requirement IDs are not linked to the case: "
                    + ", ".join(unknown)
                )

        verification.append(
            {
                "verification_id": _stable_id(
                    item["verification_id"], f"{path}.verification_id"
                ),
                "title": _string(item["title"], f"{path}.title"),
                "requirement_ids": requirement_references,
                "risk_ids": _stable_id_array(item["risk_ids"], f"{path}.risk_ids"),
                "test_level": _enum(
                    item["test_level"], {entry.value for entry in TestLevel}, f"{path}.test_level"
                ),
                "method": method,
                "automation": automation,
                "blocking": item["blocking"],
                "command": command,
                "command_source": command_source,
                "working_directory": working_directory,
                "timeout": _positive_integer(item["timeout"], f"{path}.timeout"),
                "oracle": _string(item["oracle"], f"{path}.oracle"),
                "fixtures": _string_array(item["fixtures"], f"{path}.fixtures"),
                "procedure": _string_array(item["procedure"], f"{path}.procedure"),
                "pass_criteria": _string_array(item["pass_criteria"], f"{path}.pass_criteria"),
                "metrics": metrics,
                "metric_assertions": assertions,
                "coverage_targets": coverage_targets,
                "required_evidence": required_evidence,
                "validation_loop": {
                    "maximum_correction_attempts": _positive_integer(
                        loop["maximum_correction_attempts"],
                        f"{path}.validation_loop.maximum_correction_attempts",
                    ),
                    "repetitions_per_attempt": _positive_integer(
                        loop["repetitions_per_attempt"],
                        f"{path}.validation_loop.repetitions_per_attempt",
                    ),
                    "stagnation_limit": _positive_integer(
                        loop["stagnation_limit"], f"{path}.validation_loop.stagnation_limit"
                    ),
                    "escalation_condition": _string(
                        loop["escalation_condition"],
                        f"{path}.validation_loop.escalation_condition",
                    ),
                    "retain_evidence": loop["retain_evidence"],
                },
            }
        )

    verification_ids = [entry["verification_id"] for entry in verification]
    if len(verification_ids) != len(set(verification_ids)):
        raise ManifestCompilationError("manifest.verification contains duplicate identifiers")
    verification_by_id = {entry["verification_id"]: entry for entry in verification}
    all_risk_ids = {risk_id for entry in verification for risk_id in entry["risk_ids"]}
    for index, item in enumerate(work_items):
        path = f"manifest.work_items[{index}]"
        unknown_verification = sorted(
            set(item["linked_verification_ids"]) - set(verification_ids)
        )
        if unknown_verification:
            raise ManifestCompilationError(
                f"{path}.linked_verification_ids contains unknown cases: "
                f"{', '.join(unknown_verification)}"
            )
        unknown_risks = sorted(set(item["linked_risk_ids"]) - all_risk_ids)
        if unknown_risks:
            raise ManifestCompilationError(
                f"{path}.linked_risk_ids contains unknown risks: {', '.join(unknown_risks)}"
            )
        expected_cases = [
            entry["verification_id"]
            for entry in verification
            if item["requirement_id"] in entry["requirement_ids"]
        ]
        if item["linked_verification_ids"] != expected_cases:
            raise ManifestCompilationError(
                f"{path}.linked_verification_ids is not bidirectionally consistent"
            )
        expected_risks: list[str] = []
        for verification_id in expected_cases:
            for risk_id in verification_by_id[verification_id]["risk_ids"]:
                if risk_id not in expected_risks:
                    expected_risks.append(risk_id)
        if item["linked_risk_ids"] != expected_risks:
            raise ManifestCompilationError(f"{path}.linked_risk_ids is not traceably derived")

    return {
        "schema_version": schema_version,
        "specification": {
            "id": specification_id,
            "version": specification_version,
            "schema_version": specification_schema_version,
            "content_hash": specification_hash,
        },
        "work_items": work_items,
        "verification": verification,
    }


@dataclass(frozen=True)
class VerificationManifest:
    """An immutable manifest represented by its authoritative canonical JSON."""

    _canonical_json: str

    @classmethod
    def from_dict(cls, value: Any) -> VerificationManifest:
        return cls(canonical_json(_validate_manifest_payload(value)))

    @classmethod
    def from_json(cls, text: str) -> VerificationManifest:
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ManifestCompilationError(f"invalid verification manifest JSON: {exc}") from exc
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        value = json.loads(self._canonical_json)
        if not isinstance(value, dict):  # pragma: no cover - construction guarantees this
            raise AssertionError("verification manifest root ceased to be an object")
        return value

    def canonical_json(self) -> str:
        return self._canonical_json

    def content_hash(self) -> str:
        return sha256_text(self._canonical_json)

    def pretty_json(self) -> str:
        return json.dumps(
            normalize_numeric_values(self.to_dict()),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        ) + "\n"

    @property
    def schema_version(self) -> str:
        return str(self.to_dict()["schema_version"])

    @property
    def specification(self) -> dict[str, Any]:
        return dict(self.to_dict()["specification"])

    @property
    def work_items(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self.to_dict()["work_items"])

    @property
    def verification(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self.to_dict()["verification"])


def _resolved_command(case: Any, job_test_command: str) -> tuple[str | None, str]:
    if case.automation == AutomationLevel.MANUAL:
        return None, "manual"
    override = (case.command_override or "").strip()
    if override:
        return override, "specification"
    default = str(job_test_command).strip()
    if not default or default.lower() == "auto":
        raise ManifestCompilationError(
            f"automated verification {case.id} has no specification command and the "
            "formal job test command is unresolved 'auto'"
        )
    return default, "job_default"


def compile_verification_manifest(
    snapshot: StoredSpecificationVersion,
    job_test_command: str,
) -> VerificationManifest:
    """Compile one approved immutable snapshot into a deterministic manifest."""

    if snapshot.approved_at is None or snapshot.approved_by is None:
        raise SpecificationStateError(
            "verification manifest compilation requires an approved immutable version"
        )
    document = snapshot.document
    if document.content_hash() != snapshot.canonical_content_hash:
        raise ManifestIntegrityError(
            "approved snapshot content does not match its canonical specification hash"
        )
    verification_entries: list[dict[str, Any]] = []
    for case in document.verification:
        command, command_source = _resolved_command(case, job_test_command)
        risk_ids = [risk.id for risk in document.risks if case.id in risk.verification_ids]
        verification_entries.append(
            {
                "verification_id": case.id,
                "title": case.title,
                "requirement_ids": list(case.requirement_ids),
                "risk_ids": risk_ids,
                "test_level": case.test_level.value,
                "method": case.method.value,
                "automation": case.automation.value,
                "blocking": case.blocking,
                "command": command,
                "command_source": command_source,
                "working_directory": case.working_directory,
                "timeout": case.timeout,
                "oracle": case.oracle,
                "fixtures": list(case.fixtures),
                "procedure": list(case.procedure),
                "pass_criteria": list(case.pass_criteria),
                "metrics": list(case.declared_metrics),
                "metric_assertions": [
                    {
                        "metric": assertion.metric,
                        "operator": assertion.operator,
                        "threshold": assertion.threshold,
                        "tolerance": assertion.tolerance,
                    }
                    for assertion in case.metric_assertions
                ],
                "coverage_targets": [
                    item if isinstance(item, str) else item.to_dict()
                    for item in case.coverage_targets
                ],
                "required_evidence": [
                    item if isinstance(item, str) else item.to_dict()
                    for item in case.required_evidence
                ],
                "validation_loop": {
                    "maximum_correction_attempts": case.validation_loop.maximum_correction_attempts,
                    "repetitions_per_attempt": case.validation_loop.repetitions_per_attempt,
                    "stagnation_limit": case.validation_loop.stagnation_limit,
                    "escalation_condition": case.validation_loop.escalation_condition,
                    "retain_evidence": case.validation_loop.retain_evidence,
                },
            }
        )

    work_items: list[dict[str, Any]] = []
    for requirement in document.requirements:
        linked_verification_ids = [
            case.id for case in document.verification if requirement.id in case.requirement_ids
        ]
        linked_risk_ids: list[str] = []
        for entry in verification_entries:
            if entry["verification_id"] not in linked_verification_ids:
                continue
            for risk_id in entry["risk_ids"]:
                if risk_id not in linked_risk_ids:
                    linked_risk_ids.append(risk_id)
        work_items.append(
            {
                "requirement_id": requirement.id,
                "category": requirement.category.value,
                "priority": requirement.priority.value,
                "title": requirement.title,
                "statement": requirement.statement,
                "acceptance_criteria": list(requirement.acceptance_criteria),
                "linked_use_case_ids": [
                    use_case.id
                    for use_case in document.use_cases
                    if requirement.id in use_case.requirement_ids
                ],
                "linked_risk_ids": linked_risk_ids,
                "linked_verification_ids": linked_verification_ids,
            }
        )
    return VerificationManifest.from_dict(
        {
            "schema_version": CURRENT_MANIFEST_SCHEMA_VERSION,
            "specification": {
                "id": snapshot.specification_id,
                "version": snapshot.version,
                "schema_version": document.schema_version,
                "content_hash": snapshot.canonical_content_hash,
            },
            "work_items": work_items,
            "verification": verification_entries,
        }
    )


@dataclass(frozen=True)
class StoredVerificationManifest:
    job_id: str
    manifest: VerificationManifest
    specification_id: str
    specification_version: int
    specification_content_hash: str
    canonical_content_hash: str
    artifact_path: Path
    artifact_hash: str
    created_at: str


@dataclass(frozen=True)
class StoredSpecificationChangeImpact:
    id: str
    job_id: str
    previous_specification_version: int
    new_specification_version: int
    result: dict[str, Any]
    canonical_content_hash: str
    artifact_path: Path
    artifact_hash: str
    task_id: str | None
    created_at: str


@dataclass(frozen=True)
class SpecificationRetargetResult:
    manifest: StoredVerificationManifest
    impact: StoredSpecificationChangeImpact
    task_id: str | None


@dataclass(frozen=True)
class FormalJobPromptContext:
    """Integrity-checked formal contract supplied to controller and worker prompts."""

    specification: dict[str, Any]
    manifest: dict[str, Any]
    runtime_verification_summary: tuple[dict[str, Any], ...]


class VerificationManifestService:
    """Persistence and integrity boundary for immutable per-job manifests."""

    def __init__(self, specification_service: SpecificationService):
        self.specifications = specification_service
        self.db_path = specification_service.db_path
        self.artifacts_root = specification_service.artifacts_root
        db.init_db(self.db_path)

    def create_formal_job(
        self,
        *,
        specification_id: str,
        specification_version: int,
        job_id: str,
        repo_path: str,
        worktree_path: str,
        branch: str | None,
        base_ref: str,
        test_cmd: str,
        max_iterations: int,
        use_worktree: bool,
        worker: str = "codex",
        controller: str = "claude",
        granularity: str = "normal",
        plan: list[str] | None = None,
        email_token: str | None = None,
        models: dict[str, Any] | None = None,
        additional_constraints: Sequence[str] = (),
        additional_acceptance: Sequence[str] = (),
    ) -> StoredVerificationManifest:
        """Compile first, then atomically commit a pinned ordinary job and manifest."""

        snapshot = self._approved_snapshot(specification_id, specification_version)
        if Path(repo_path).expanduser().resolve() != Path(snapshot.repository_path).resolve():
            raise SpecificationStateError(
                "formal job repository must match the approved specification repository"
            )
        manifest = compile_verification_manifest(snapshot, test_cmd)
        from ai_loop.specification_workflow import derive_formal_job_inputs

        inputs = derive_formal_job_inputs(snapshot)
        artifact_path, artifact_hash = self._write_manifest_artifact(job_id, manifest)
        try:
            with db.transaction(self.db_path) as conn:
                db.create_job(
                    conn,
                    job_id=job_id,
                    repo_path=str(Path(repo_path).expanduser().resolve()),
                    worktree_path=str(Path(worktree_path).expanduser().resolve()),
                    branch=branch,
                    base_ref=base_ref,
                    goal=inputs.goal,
                    constraints=[*inputs.constraints, *map(str, additional_constraints)],
                    acceptance=[*inputs.acceptance, *map(str, additional_acceptance)],
                    test_cmd=test_cmd,
                    max_iterations=max_iterations,
                    use_worktree=use_worktree,
                    worker=worker,
                    controller=controller,
                    granularity=granularity,
                    plan=plan,
                    email_token=email_token,
                    models=models,
                    specification_id=specification_id,
                    specification_version=specification_version,
                    specification_content_hash=snapshot.canonical_content_hash,
                )
                self._insert_manifest(
                    conn, job_id, snapshot, manifest, artifact_path, artifact_hash
                )
                db.add_event(
                    conn,
                    job_id=job_id,
                    kind="formal_job_created",
                    payload={
                        "specification_id": specification_id,
                        "specification_version": specification_version,
                        "specification_content_hash": snapshot.canonical_content_hash,
                        "manifest_content_hash": manifest.content_hash(),
                    },
                )
        except Exception:
            artifact_path.unlink(missing_ok=True)
            raise
        stored = self.verify_integrity(job_id)
        if stored is None:  # pragma: no cover - the job was just committed as formal
            raise AssertionError("formal job did not retain its verification manifest")
        return stored

    def attach_approved_specification(
        self,
        job_id: str,
        specification_id: str,
        specification_version: int,
    ) -> StoredVerificationManifest:
        """Turn an existing Quick Goal job into a pinned formal job."""

        snapshot = self._approved_snapshot(specification_id, specification_version)
        with db.transaction(self.db_path) as conn:
            job = db.get_job(conn, job_id)
            manifest_exists = conn.execute(
                "SELECT 1 FROM verification_manifests WHERE job_id = ?", (job_id,)
            ).fetchone() is not None
        self._validate_job_repository(job, snapshot)
        self._validate_existing_pin(job, specification_id, specification_version)
        if manifest_exists:
            stored = self.verify_integrity(job_id)
            if stored is None:  # pragma: no cover - row existence checked above
                raise ManifestIntegrityError("manifest row disappeared during attachment")
            return stored
        if job.get("specification_content_hash") not in {None, snapshot.canonical_content_hash}:
            raise ManifestIntegrityError("job specification content hash does not match its pin")
        manifest = compile_verification_manifest(snapshot, str(job["test_cmd"]))
        artifact_path, artifact_hash = self._write_manifest_artifact(job_id, manifest)
        try:
            with db.transaction(self.db_path) as conn:
                current = db.get_job(conn, job_id)
                self._validate_existing_pin(current, specification_id, specification_version)
                if conn.execute(
                    "SELECT 1 FROM verification_manifests WHERE job_id = ?", (job_id,)
                ).fetchone() is not None:
                    raise SpecificationStateError("job manifest appeared during attachment")
                conn.execute(
                    """
                    UPDATE jobs SET specification_id = ?, specification_version = ?,
                        specification_content_hash = ?, updated_at = ? WHERE id = ?
                    """,
                    (
                        specification_id,
                        specification_version,
                        snapshot.canonical_content_hash,
                        db.utc_now(),
                        job_id,
                    ),
                )
                self._insert_manifest(
                    conn, job_id, snapshot, manifest, artifact_path, artifact_hash
                )
                db.add_event(
                    conn,
                    job_id=job_id,
                    kind="approved_specification_attached",
                    payload={
                        "specification_id": specification_id,
                        "specification_version": specification_version,
                        "specification_content_hash": snapshot.canonical_content_hash,
                        "manifest_content_hash": manifest.content_hash(),
                    },
                )
        except Exception:
            artifact_path.unlink(missing_ok=True)
            raise
        stored = self.verify_integrity(job_id)
        if stored is None:  # pragma: no cover - the attachment was just committed
            raise AssertionError("attached job did not retain its verification manifest")
        return stored

    def retarget_approved_revision(
        self,
        job_id: str,
        specification_id: str,
        specification_version: int,
    ) -> SpecificationRetargetResult:
        """Pin a newer approved revision without rewriting prior manifest history."""

        current_manifest = self.verify_integrity(job_id)
        if current_manifest is None:
            raise SpecificationStateError(
                "Quick Goal jobs cannot use specification change-impact retargeting"
            )
        if current_manifest.specification_id != specification_id:
            raise SpecificationStateError(
                "a formal job can only retarget within its attached specification identity"
            )
        newer = self._approved_snapshot(specification_id, specification_version)
        if specification_version <= current_manifest.specification_version:
            raise SpecificationStateError("retarget requires a newer approved version")
        previous = self._approved_snapshot(
            current_manifest.specification_id, current_manifest.specification_version
        )
        with db.transaction(self.db_path) as conn:
            job = db.get_job(conn, job_id)
            latest_revision = int(
                conn.execute(
                    """
                    SELECT COALESCE(MAX(revision), 0)
                    FROM verification_manifest_revisions WHERE job_id = ?
                    """,
                    (job_id,),
                ).fetchone()[0]
            )
        self._validate_job_repository(job, newer)
        new_manifest = compile_verification_manifest(newer, str(job["test_cmd"]))
        from ai_loop.specification_workflow import analyze_specification_change

        analysis = analyze_specification_change(
            previous,
            newer,
            previous_manifest=current_manifest.manifest,
            newer_manifest=new_manifest,
        )
        affected_verification_ids = list(analysis["impact"]["affected_verification_ids"])
        affected_requirement_ids = list(analysis["impact"]["affected_requirement_ids"])
        revision = latest_revision + 1
        task_id = (
            f"{job_id}:SPEC-RETARGET:{specification_version}"
            if affected_verification_ids
            else None
        )
        impact_id = f"{job_id}:IMPACT:{previous.version}:{newer.version}"
        impact_payload = {
            **analysis,
            "manifest_transition": {
                "previous_content_hash": current_manifest.canonical_content_hash,
                "new_content_hash": new_manifest.content_hash(),
                "revision": revision,
            },
            "retarget_task": {
                "task_id": task_id,
                "requirement_ids": affected_requirement_ids,
                "verification_ids": affected_verification_ids,
            },
        }
        manifest_path, manifest_artifact_hash = self._write_manifest_revision_artifact(
            job_id, newer.version, new_manifest
        )
        try:
            impact_path, impact_artifact_hash = self._write_impact_artifact(
                job_id, previous.version, newer.version, impact_payload
            )
        except Exception:
            manifest_path.unlink(missing_ok=True)
            raise
        now = db.utc_now()
        try:
            with db.transaction(self.db_path) as conn:
                current_job = db.get_job(conn, job_id)
                active_row = db.active_verification_manifest_row(conn, job_id)
                if active_row is None or (
                    current_job.get("specification_id") != previous.specification_id
                    or int(current_job.get("specification_version") or 0) != previous.version
                    or current_job.get("specification_content_hash")
                    != previous.canonical_content_hash
                    or str(active_row["canonical_content_hash"])
                    != current_manifest.canonical_content_hash
                ):
                    raise SpecificationStateError("formal job pin changed during impact analysis")
                self._insert_manifest_revision(
                    conn,
                    job_id,
                    revision,
                    newer,
                    new_manifest,
                    manifest_path,
                    manifest_artifact_hash,
                    now,
                )
                self._retarget_verification_states(
                    conn,
                    job_id,
                    new_manifest,
                    set(affected_verification_ids),
                    now,
                )
                if task_id is not None:
                    next_iteration = int(
                        conn.execute(
                            "SELECT COALESCE(MAX(iteration), 0) + 1 FROM tasks WHERE job_id = ?",
                            (job_id,),
                        ).fetchone()[0]
                    )
                    db.create_task(
                        conn,
                        task_id=task_id,
                        job_id=job_id,
                        iteration=next_iteration,
                        goal=(
                            f"Implement and verify only the contracts affected by approved "
                            f"specification version {newer.version}."
                        ),
                        constraints=[
                            "Use the persisted change-impact analysis as the scope boundary.",
                            "Do not replan or modify contracts proven unaffected by traceability.",
                        ],
                        acceptance=[
                            f"Affected verification {verification_id} has fresh passing evidence."
                            for verification_id in affected_verification_ids
                        ],
                        test_cmd=str(job["test_cmd"]),
                        created_by="specification_change_impact",
                        requirement_ids=affected_requirement_ids,
                        verification_ids=affected_verification_ids,
                    )
                    db.add_event(
                        conn,
                        job_id=job_id,
                        kind="task_queued",
                        payload={
                            "task_id": task_id,
                            "iteration": next_iteration,
                            "action": "RETARGET",
                            "status": "queued",
                            "reason": (
                                f"Approved specification version {newer.version} "
                                "changed verified contracts."
                            ),
                            "goal": (
                                f"Implement and verify only the contracts affected by approved "
                                f"specification version {newer.version}."
                            ),
                            "test_cmd": str(job["test_cmd"]),
                            "requirement_ids": affected_requirement_ids,
                            "verification_ids": affected_verification_ids,
                            "created_by": "specification_change_impact",
                        },
                    )
                impact_canonical = canonical_json(impact_payload)
                conn.execute(
                    """
                    INSERT INTO specification_change_impacts (
                        id, job_id, previous_specification_id,
                        previous_specification_version, previous_specification_hash,
                        new_specification_id, new_specification_version,
                        new_specification_hash, manifest_revision, canonical_json,
                        canonical_content_hash, artifact_path, artifact_hash,
                        task_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        impact_id,
                        job_id,
                        previous.specification_id,
                        previous.version,
                        previous.canonical_content_hash,
                        newer.specification_id,
                        newer.version,
                        newer.canonical_content_hash,
                        revision,
                        impact_canonical,
                        sha256_text(impact_canonical),
                        str(impact_path),
                        impact_artifact_hash,
                        task_id,
                        now,
                    ),
                )
                conn.execute(
                    """
                    UPDATE jobs SET specification_version = ?,
                        specification_content_hash = ?,
                        status = CASE WHEN ? IS NULL THEN status ELSE 'planning' END,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        newer.version,
                        newer.canonical_content_hash,
                        task_id,
                        now,
                        job_id,
                    ),
                )
                db.add_event(
                    conn,
                    job_id=job_id,
                    kind="approved_specification_retargeted",
                    payload={
                        "impact_id": impact_id,
                        "previous_specification_version": previous.version,
                        "new_specification_version": newer.version,
                        "impact_content_hash": sha256_text(impact_canonical),
                        "impact_artifact_hash": impact_artifact_hash,
                        "manifest_content_hash": new_manifest.content_hash(),
                        "affected_requirement_ids": affected_requirement_ids,
                        "affected_verification_ids": affected_verification_ids,
                        "task_id": task_id,
                    },
                )
        except Exception:
            manifest_path.unlink(missing_ok=True)
            impact_path.unlink(missing_ok=True)
            raise
        stored_manifest = self.verify_integrity(job_id)
        if stored_manifest is None:  # pragma: no cover - pin remains formal
            raise AssertionError("retargeted job lost its manifest")
        stored_impact = self.verify_change_impact(impact_id)
        return SpecificationRetargetResult(stored_manifest, stored_impact, task_id)

    def verify_change_impact(self, impact_id: str) -> StoredSpecificationChangeImpact:
        """Integrity-check one immutable change-impact record and artifact."""

        with db.transaction(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM specification_change_impacts WHERE id = ?", (impact_id,)
            ).fetchone()
            revision_row = (
                None
                if row is None
                else conn.execute(
                    """
                    SELECT * FROM verification_manifest_revisions
                    WHERE job_id = ? AND revision = ?
                    """,
                    (row["job_id"], row["manifest_revision"]),
                ).fetchone()
            )
        if row is None:
            raise KeyError(f"Unknown specification change impact: {impact_id}")
        if revision_row is None:
            raise ManifestIntegrityError("change-impact manifest revision is unavailable")
        data = dict(row)
        canonical_text = str(data["canonical_json"])
        if sha256_text(canonical_text) != data["canonical_content_hash"]:
            raise ManifestIntegrityError("change-impact canonical content hash mismatch")
        try:
            result = json.loads(canonical_text)
        except json.JSONDecodeError as exc:
            raise ManifestIntegrityError("change-impact canonical JSON is invalid") from exc
        if canonical_json(result) != canonical_text:
            raise ManifestIntegrityError("change-impact JSON is not canonical")
        path = Path(str(data["artifact_path"]))
        expected_path = self._impact_artifact_path(
            str(data["job_id"]),
            int(data["previous_specification_version"]),
            int(data["new_specification_version"]),
        )
        if path.resolve(strict=False) != expected_path.resolve(strict=False):
            raise ManifestIntegrityError("change-impact artifact path is not immutable")
        previous_reference = result.get("previous_specification")
        new_reference = result.get("new_specification")
        transition = result.get("manifest_transition")
        if not isinstance(previous_reference, Mapping) or not isinstance(
            new_reference, Mapping
        ) or not isinstance(transition, Mapping):
            raise ManifestIntegrityError("change-impact source metadata is missing")
        if (
            previous_reference.get("id") != data["previous_specification_id"]
            or int(previous_reference.get("version") or 0)
            != int(data["previous_specification_version"])
            or previous_reference.get("content_hash")
            != data["previous_specification_hash"]
            or new_reference.get("id") != data["new_specification_id"]
            or int(new_reference.get("version") or 0)
            != int(data["new_specification_version"])
            or new_reference.get("content_hash") != data["new_specification_hash"]
            or int(transition.get("revision") or 0) != int(data["manifest_revision"])
            or transition.get("new_content_hash")
            != revision_row["canonical_content_hash"]
            or revision_row["specification_id"] != data["new_specification_id"]
            or int(revision_row["specification_version"])
            != int(data["new_specification_version"])
        ):
            raise ManifestIntegrityError("change-impact metadata differs from its record")
        try:
            artifact_bytes = path.read_bytes()
        except OSError as exc:
            raise ManifestIntegrityError("change-impact artifact is unavailable") from exc
        if sha256_bytes(artifact_bytes) != data["artifact_hash"]:
            raise ManifestIntegrityError("change-impact artifact hash mismatch")
        try:
            artifact_result = json.loads(artifact_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ManifestIntegrityError("change-impact artifact is invalid") from exc
        if canonical_json(artifact_result) != canonical_text:
            raise ManifestIntegrityError("change-impact artifact differs from canonical JSON")
        return StoredSpecificationChangeImpact(
            id=str(data["id"]),
            job_id=str(data["job_id"]),
            previous_specification_version=int(data["previous_specification_version"]),
            new_specification_version=int(data["new_specification_version"]),
            result=result,
            canonical_content_hash=str(data["canonical_content_hash"]),
            artifact_path=path,
            artifact_hash=str(data["artifact_hash"]),
            task_id=data["task_id"],
            created_at=str(data["created_at"]),
        )

    def load_for_job(
        self, job_id: str, *, backfill: bool = True
    ) -> StoredVerificationManifest | None:
        """Load a manifest, lazily compiling only a consistently pinned formal job."""

        with db.transaction(self.db_path) as conn:
            job = db.get_job(conn, job_id)
            row = conn.execute(
                "SELECT 1 FROM verification_manifests WHERE job_id = ?", (job_id,)
            ).fetchone()
        pin = (job.get("specification_id"), job.get("specification_version"))
        if pin == (None, None):
            if job.get("specification_content_hash") is not None:
                raise ManifestIntegrityError("Quick Goal job has an orphan specification hash")
            if row is not None:
                raise ManifestIntegrityError("Quick Goal job unexpectedly has a verification manifest")
            return None
        if pin[0] is None or pin[1] is None or job.get("specification_content_hash") is None:
            raise ManifestIntegrityError("formal job has an incomplete specification pin")
        if row is not None:
            return self.verify_integrity(job_id)
        if not backfill:
            return None
        return self._backfill(job)

    def load_prompt_context(
        self,
        job_id: str,
        *,
        backfill: bool = True,
        worker_run_id: str | None = None,
    ) -> FormalJobPromptContext | None:
        """Load the complete trusted formal contract without exposing SQL to callers."""

        stored = self.load_for_job(job_id, backfill=backfill)
        if stored is None:
            return None
        snapshot = self.specifications.verify_integrity(
            stored.specification_id, stored.specification_version
        )
        with db.transaction(self.db_path) as conn:
            job = db.get_job(conn, job_id)
            rows = conn.execute(
                """
                SELECT verification_id, automation, blocking, status, updated_at
                FROM job_verification_states
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchall()
            repetitions = db.list_verification_repetitions(conn, job_id)
        # This is a dry repository inspection only.  Keeping it behind the
        # trusted manifest-loading boundary ensures Quick Goal jobs never
        # receive realization state and immutable manifest bytes are untouched.
        from ai_loop.verification_orchestrator import (
            build_runtime_verification_summary,
            check_manifest_realization,
            persist_realization_checks,
        )
        from ai_loop.evidence_adapters import (
            EvidenceAdapterAudit,
            collect_realization_signals,
            evidence_artifact_from_mapping,
            load_evidence_adapters,
        )

        def audit_adapter(item: EvidenceAdapterAudit) -> None:
            with db.transaction(self.db_path) as audit_conn:
                db.add_event(
                    audit_conn,
                    job_id=job_id,
                    kind="evidence_adapter_error",
                    payload=item.to_dict(),
                )

        loaded_adapters = load_evidence_adapters(audit=audit_adapter)
        adapter_artifacts = []
        for repetition in repetitions:
            for value in repetition.get("evidence", ()):
                if not isinstance(value, Mapping):
                    continue
                try:
                    adapter_artifacts.append(evidence_artifact_from_mapping(value))
                except (KeyError, TypeError, ValueError) as exc:
                    audit_adapter(
                        EvidenceAdapterAudit(
                            adapter="persisted-evidence",
                            stage="rehydrate",
                            error=f"{type(exc).__name__}: {exc}",
                            verification_id=str(repetition.get("verification_id", "")) or None,
                            evidence_name=str(value.get("name", "")) or None,
                        )
                    )
        adapter_results = collect_realization_signals(
            loaded_adapters.adapters,
            adapter_artifacts,
            worktree=Path(str(job["worktree_path"])).resolve(),
            audit=audit_adapter,
        )

        previous_states = {
            str(row["verification_id"]): str(row["status"]) for row in rows
        }
        realization_checks = check_manifest_realization(
            stored.manifest,
            str(job["worktree_path"]),
            previous_states=previous_states,
            adapter_results=adapter_results,
        )
        persist_realization_checks(self.db_path, job_id, realization_checks)
        realization_by_id = {
            item.verification_id: item for item in realization_checks
        }
        runtime_summary = build_runtime_verification_summary(
            self.db_path,
            job_id,
            stored.manifest,
            worker_run_id=worker_run_id,
            specification=snapshot.document,
        )
        if runtime_summary is None:  # pragma: no cover - stored is formal above
            raise ManifestIntegrityError("formal job lost its verification runtime state")
        summary = [
            {
                **realization_by_id[str(item["verification_id"])].to_summary(),
                **item,
            }
            for item in runtime_summary
        ]
        return FormalJobPromptContext(
            specification=snapshot.document.to_dict(),
            manifest=stored.manifest.to_dict(),
            runtime_verification_summary=tuple(summary),
        )

    def verify_integrity(self, job_id: str) -> StoredVerificationManifest | None:
        with db.transaction(self.db_path) as conn:
            job = db.get_job(conn, job_id)
            row = db.active_verification_manifest_row(conn, job_id)
        if row is None:
            return None
        manifest_row = dict(row)
        specification_id = job.get("specification_id")
        specification_version = job.get("specification_version")
        specification_hash = job.get("specification_content_hash")
        if specification_id is None or specification_version is None or specification_hash is None:
            raise ManifestIntegrityError("manifest is attached to a job without a complete formal pin")
        if (
            manifest_row["specification_id"] != specification_id
            or int(manifest_row["specification_version"]) != int(specification_version)
            or manifest_row["specification_content_hash"] != specification_hash
        ):
            raise ManifestIntegrityError("manifest source metadata differs from the job pin")
        canonical_text = manifest_row["canonical_json"]
        try:
            manifest = VerificationManifest.from_json(canonical_text)
        except ManifestCompilationError as exc:
            raise ManifestIntegrityError(f"stored verification manifest JSON is invalid: {exc}") from exc
        if manifest.canonical_json() != canonical_text:
            raise ManifestIntegrityError("stored verification manifest is not canonical JSON")
        if manifest.schema_version != manifest_row["manifest_schema_version"]:
            raise ManifestIntegrityError("stored manifest schema version does not match its JSON")
        if sha256_text(canonical_text) != manifest_row["canonical_content_hash"]:
            raise ManifestIntegrityError("canonical verification manifest hash mismatch")
        source = manifest.specification
        if (
            source["id"] != specification_id
            or int(source["version"]) != int(specification_version)
            or source["content_hash"] != specification_hash
        ):
            raise ManifestIntegrityError("manifest JSON source differs from the job pin")

        snapshot = self._approved_snapshot(str(specification_id), int(specification_version))
        self._validate_job_repository(job, snapshot)
        if snapshot.canonical_content_hash != specification_hash:
            raise ManifestIntegrityError("job pin differs from the approved specification hash")
        expected = compile_verification_manifest(snapshot, str(job["test_cmd"]))
        if expected.canonical_json() != canonical_text:
            raise ManifestIntegrityError("stored manifest differs from deterministic compilation")

        artifact_path = Path(manifest_row["artifact_path"])
        active_revision = int(manifest_row.get("active_revision") or 0)
        expected_path = (
            self._manifest_artifact_path(job_id)
            if active_revision == 0
            else self._manifest_revision_artifact_path(
                job_id, int(manifest_row["specification_version"])
            )
        )
        if artifact_path.resolve(strict=False) != expected_path.resolve(strict=False):
            raise ManifestIntegrityError("manifest artifact path is not the immutable job path")
        try:
            artifact_bytes = artifact_path.read_bytes()
        except OSError as exc:
            raise ManifestIntegrityError(f"verification manifest artifact is unavailable: {exc}") from exc
        if sha256_bytes(artifact_bytes) != manifest_row["artifact_hash"]:
            raise ManifestIntegrityError("verification manifest artifact hash mismatch")
        try:
            artifact_manifest = VerificationManifest.from_json(artifact_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ManifestCompilationError) as exc:
            raise ManifestIntegrityError(f"verification manifest artifact is invalid: {exc}") from exc
        if artifact_manifest.canonical_json() != canonical_text:
            raise ManifestIntegrityError(
                "verification manifest artifact differs from stored canonical JSON"
            )
        return StoredVerificationManifest(
            job_id=job_id,
            manifest=manifest,
            specification_id=str(specification_id),
            specification_version=int(specification_version),
            specification_content_hash=str(specification_hash),
            canonical_content_hash=manifest_row["canonical_content_hash"],
            artifact_path=artifact_path,
            artifact_hash=manifest_row["artifact_hash"],
            created_at=manifest_row["created_at"],
        )

    def _backfill(self, job: Mapping[str, Any]) -> StoredVerificationManifest:
        job_id = str(job["id"])
        specification_id = str(job["specification_id"])
        specification_version = int(job["specification_version"])
        snapshot = self._approved_snapshot(specification_id, specification_version)
        self._validate_job_repository(job, snapshot)
        if job["specification_content_hash"] != snapshot.canonical_content_hash:
            raise ManifestIntegrityError("legacy formal job pin has a mismatched specification hash")
        manifest = compile_verification_manifest(snapshot, str(job["test_cmd"]))
        artifact_path, artifact_hash = self._write_manifest_artifact(job_id, manifest)
        try:
            with db.transaction(self.db_path) as conn:
                current = db.get_job(conn, job_id)
                if (
                    current.get("specification_id") != specification_id
                    or int(current.get("specification_version") or 0) != specification_version
                    or current.get("specification_content_hash") != snapshot.canonical_content_hash
                ):
                    raise SpecificationStateError("formal job pin changed during manifest backfill")
                if conn.execute(
                    "SELECT 1 FROM verification_manifests WHERE job_id = ?", (job_id,)
                ).fetchone() is not None:
                    raise SpecificationStateError("job manifest appeared during backfill")
                self._insert_manifest(
                    conn, job_id, snapshot, manifest, artifact_path, artifact_hash
                )
                db.add_event(
                    conn,
                    job_id=job_id,
                    kind="verification_manifest_backfilled",
                    payload={
                        "specification_id": specification_id,
                        "specification_version": specification_version,
                        "manifest_content_hash": manifest.content_hash(),
                    },
                )
        except Exception:
            artifact_path.unlink(missing_ok=True)
            raise
        stored = self.verify_integrity(job_id)
        if stored is None:  # pragma: no cover - backfill just committed it
            raise AssertionError("backfilled manifest was not persisted")
        return stored

    def _approved_snapshot(
        self, specification_id: str, specification_version: int
    ) -> StoredSpecificationVersion:
        snapshot = self.specifications.verify_integrity(
            specification_id, specification_version
        )
        if snapshot.approved_at is None or snapshot.approved_by is None:
            raise SpecificationStateError(
                "only an approved immutable specification version can be used by a formal job"
            )
        return snapshot

    @staticmethod
    def _validate_existing_pin(
        job: Mapping[str, Any], specification_id: str, specification_version: int
    ) -> None:
        existing = (job.get("specification_id"), job.get("specification_version"))
        requested = (specification_id, specification_version)
        if existing != (None, None) and existing != requested:
            raise SpecificationStateError("job already has a different immutable specification pin")

    @staticmethod
    def _validate_job_repository(
        job: Mapping[str, Any], snapshot: StoredSpecificationVersion
    ) -> None:
        if Path(str(job["repo_path"])).expanduser().resolve() != Path(
            snapshot.repository_path
        ).expanduser().resolve():
            raise ManifestIntegrityError(
                "job repository differs from the approved specification repository"
            )

    def _insert_manifest(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        snapshot: StoredSpecificationVersion,
        manifest: VerificationManifest,
        artifact_path: Path,
        artifact_hash: str,
    ) -> None:
        now = db.utc_now()
        canonical_text = manifest.canonical_json()
        conn.execute(
            """
            INSERT INTO verification_manifests (
                job_id, manifest_schema_version, specification_id,
                specification_version, specification_content_hash, canonical_json,
                canonical_content_hash, artifact_path, artifact_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                manifest.schema_version,
                snapshot.specification_id,
                snapshot.version,
                snapshot.canonical_content_hash,
                canonical_text,
                sha256_text(canonical_text),
                str(artifact_path),
                artifact_hash,
                now,
            ),
        )
        for case in manifest.verification:
            status = (
                "manual_pending"
                if case["automation"] == AutomationLevel.MANUAL.value
                else "unrealized"
            )
            conn.execute(
                """
                INSERT INTO job_verification_states (
                    job_id, verification_id, automation, blocking, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    case["verification_id"],
                    case["automation"],
                    1 if case["blocking"] else 0,
                    status,
                    now,
                    now,
                ),
            )

    def _insert_manifest_revision(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        revision: int,
        snapshot: StoredSpecificationVersion,
        manifest: VerificationManifest,
        artifact_path: Path,
        artifact_hash: str,
        created_at: str,
    ) -> None:
        canonical_text = manifest.canonical_json()
        conn.execute(
            """
            INSERT INTO verification_manifest_revisions (
                job_id, revision, manifest_schema_version, specification_id,
                specification_version, specification_content_hash, canonical_json,
                canonical_content_hash, artifact_path, artifact_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                revision,
                manifest.schema_version,
                snapshot.specification_id,
                snapshot.version,
                snapshot.canonical_content_hash,
                canonical_text,
                sha256_text(canonical_text),
                str(artifact_path),
                artifact_hash,
                created_at,
            ),
        )

    @staticmethod
    def _initial_case_status(case: Mapping[str, Any]) -> str:
        return (
            "manual_pending"
            if case["automation"] == AutomationLevel.MANUAL.value
            else "unrealized"
        )

    def _retarget_verification_states(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        manifest: VerificationManifest,
        affected_ids: set[str],
        now: str,
    ) -> None:
        new_cases = {str(case["verification_id"]): case for case in manifest.verification}
        rows = {
            str(row["verification_id"]): row
            for row in conn.execute(
                "SELECT * FROM job_verification_states WHERE job_id = ?", (job_id,)
            )
        }
        for verification_id in sorted(set(rows) - set(new_cases)):
            conn.execute(
                """
                UPDATE job_verification_states
                SET status = 'retired', updated_at = ?
                WHERE job_id = ? AND verification_id = ?
                """,
                (now, job_id, verification_id),
            )
        for verification_id, case in new_cases.items():
            row = rows.get(verification_id)
            status = self._initial_case_status(case)
            if row is None:
                conn.execute(
                    """
                    INSERT INTO job_verification_states (
                        job_id, verification_id, automation, blocking, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        verification_id,
                        case["automation"],
                        1 if case["blocking"] else 0,
                        status,
                        now,
                        now,
                    ),
                )
                continue
            if verification_id not in affected_ids:
                continue
            offset = int(
                conn.execute(
                    """
                    SELECT COALESCE(MAX(attempt), 0) FROM verification_repetitions
                    WHERE job_id = ? AND verification_id = ?
                    """,
                    (job_id, verification_id),
                ).fetchone()[0]
            )
            conn.execute(
                """
                UPDATE job_verification_states SET
                    automation = ?, blocking = ?, status = ?, attempts_completed = 0,
                    consecutive_failures = 0, stagnation_count = 0,
                    stagnation_series = 0, failure_fingerprint = NULL,
                    latest_metrics_json = NULL, metric_trend = NULL,
                    last_error = NULL, last_task_id = NULL,
                    last_worker_run_id = NULL, finished_at = NULL,
                    escalation_report_json = NULL, attempt_offset = ?, updated_at = ?
                WHERE job_id = ? AND verification_id = ?
                """,
                (
                    case["automation"],
                    1 if case["blocking"] else 0,
                    status,
                    offset,
                    now,
                    job_id,
                    verification_id,
                ),
            )

    def _manifest_artifact_path(self, job_id: str) -> Path:
        return (
            self.artifacts_root
            / "jobs"
            / job_id
            / "specification"
            / "verification-manifest.json"
        )

    def _manifest_revision_artifact_path(self, job_id: str, version: int) -> Path:
        return (
            self.artifacts_root
            / "jobs"
            / job_id
            / "specification"
            / f"verification-manifest-v{version:04d}.json"
        )

    def _impact_artifact_path(
        self, job_id: str, previous_version: int, new_version: int
    ) -> Path:
        return (
            self.artifacts_root
            / "jobs"
            / job_id
            / "specification"
            / f"change-impact-v{previous_version:04d}-to-v{new_version:04d}.json"
        )

    @staticmethod
    def _write_immutable_json_artifact(
        path: Path, payload: bytes, *, description: str
    ) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise ManifestIntegrityError(f"immutable {description} already exists: {path}")
        handle, name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        os.close(handle)
        temporary = Path(name)
        try:
            temporary.write_bytes(payload)
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise ManifestIntegrityError(
                    f"immutable {description} already exists: {path}"
                ) from exc
        finally:
            temporary.unlink(missing_ok=True)
        return sha256_bytes(payload)

    def _write_manifest_revision_artifact(
        self, job_id: str, version: int, manifest: VerificationManifest
    ) -> tuple[Path, str]:
        path = self._manifest_revision_artifact_path(job_id, version)
        return path, self._write_immutable_json_artifact(
            path, manifest.pretty_json().encode("utf-8"), description="manifest revision artifact"
        )

    def _write_impact_artifact(
        self,
        job_id: str,
        previous_version: int,
        new_version: int,
        result: Mapping[str, Any],
    ) -> tuple[Path, str]:
        path = self._impact_artifact_path(job_id, previous_version, new_version)
        payload = (
            json.dumps(
                normalize_numeric_values(dict(result)),
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        return path, self._write_immutable_json_artifact(
            path, payload, description="change-impact artifact"
        )

    def _write_manifest_artifact(
        self, job_id: str, manifest: VerificationManifest
    ) -> tuple[Path, str]:
        path = self._manifest_artifact_path(job_id)
        payload = manifest.pretty_json().encode("utf-8")
        return path, self._write_immutable_json_artifact(
            path, payload, description="manifest artifact"
        )


def create_formal_job(
    specification_service: SpecificationService, **job: Any
) -> StoredVerificationManifest:
    """Convenience entry point for frontend-neutral formal job creation."""

    return VerificationManifestService(specification_service).create_formal_job(**job)


def attach_approved_specification(
    specification_service: SpecificationService,
    job_id: str,
    specification_id: str,
    specification_version: int,
) -> StoredVerificationManifest:
    return VerificationManifestService(specification_service).attach_approved_specification(
        job_id, specification_id, specification_version
    )


def load_job_manifest(
    specification_service: SpecificationService,
    job_id: str,
    *,
    backfill: bool = True,
) -> StoredVerificationManifest | None:
    return VerificationManifestService(specification_service).load_for_job(
        job_id, backfill=backfill
    )


__all__ = [
    "CURRENT_MANIFEST_SCHEMA_VERSION",
    "FormalJobPromptContext",
    "ManifestCompilationError",
    "ManifestIntegrityError",
    "SpecificationRetargetResult",
    "StoredSpecificationChangeImpact",
    "StoredVerificationManifest",
    "VerificationManifest",
    "VerificationManifestService",
    "attach_approved_specification",
    "compile_verification_manifest",
    "create_formal_job",
    "load_job_manifest",
]
