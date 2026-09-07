"""Verification realization checks and bounded runtime orchestration.

Static checks determine whether immutable manifest cases have concrete
repository infrastructure.  Runtime orchestration independently repeats path
containment checks, selects cases by task traceability, executes every declared
repetition, evaluates numeric metrics, and appends bounded database records.
Structured evidence retention, generic coverage enforcement, deterministic
failure analysis, metric trends, and bounded escalation reports live here.

Repository code can declare dry, domain-neutral realization signals with
single-line JSON envelopes::

    AI_LOOP_CASE={"verification_id":"VT1"}
    AI_LOOP_FIXTURE_GENERATOR={"verification_id":"VT1","fixtures":["seed-data"]}
    AI_LOOP_METRIC_EMITTER={"verification_id":"VT1","metrics":["latency_ms"]}
    AI_LOOP_EVIDENCE_PRODUCER={"verification_id":"VT1","kinds":["test log"]}

An adapter may provide the equivalent :class:`RealizationSignals` directly.
The case marker is mandatory: a broad command being resolvable (or eventually
exiting zero) is not proof that it executed the intended verification case.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import shlex
import shutil
import time
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from ai_loop import db
from ai_loop.config import sanitized_child_env
from ai_loop.process_runner import run_bounded_process
from ai_loop.specifications import (
    CoverageTarget,
    EvidenceKind,
    MetricAssertion,
    SpecificationError,
    canonical_json,
    validate_working_directory,
)


MAX_DISCOVERY_FILE_BYTES = 1_000_000
MAX_METRIC_SCAN_CHARACTERS = 1_000_000
MAX_DATABASE_OUTPUT_CHARACTERS = 20_000
MAX_EVIDENCE_ARTIFACT_BYTES = 25_000_000
MAX_INLINE_EVIDENCE_BYTES = 64_000
MAX_EVIDENCE_PREVIEW_CHARACTERS = 4_000
MAX_FAILURE_OUTPUT_TAIL_CHARACTERS = 4_000
MAX_PROCESS_OUTPUT_BYTES = 2 * MAX_METRIC_SCAN_CHARACTERS
VERIFICATION_DASHBOARD_ENFORCEMENT = frozenset(
    {"DESCRIPTIVE", "REALIZED", "MACHINE-ENFORCED"}
)
EVIDENCE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")
DISCOVERY_EXCLUDED_DIRECTORIES = frozenset(
    {".git", ".hg", ".svn", ".gui-venv", ".venv", "node_modules", "artifacts"}
)
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_ENVELOPE = re.compile(
    r"AI_LOOP_(CASE|FIXTURE_GENERATOR|METRIC_EMITTER|EVIDENCE_PRODUCER|"
    r"REALIZATION|METRICS|EVIDENCE)\s*="
)
_PYTEST_COUNT = re.compile(
    r"(?<![\w.])(?P<count>\d+)\s+"
    r"(?P<kind>passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b",
    re.IGNORECASE,
)
_PYTEST_COLLECTED = re.compile(r"\bcollected\s+(\d+)\s+items?\b", re.IGNORECASE)
_PYTEST_SELECTED = re.compile(r"\b(\d+)\s+selected\b", re.IGNORECASE)
_PYTEST_NO_TESTS = re.compile(r"\bno tests? ran\b", re.IGNORECASE)
_UNITTEST_RAN = re.compile(r"\bRan\s+(\d+)\s+tests?\b", re.IGNORECASE)
_UNITTEST_SKIPPED = re.compile(r"\bskipped\s*=\s*(\d+)\b", re.IGNORECASE)


class RealizationState(str, Enum):
    """First-class aggregate states shared with later verification milestones."""

    UNREALIZED = "unrealized"
    EXECUTABLE_BUT_FAILING = "executable_but_failing"
    PASSING = "passing"
    STAGNATED = "stagnated"
    ESCALATED = "escalated"
    MANUAL_PENDING = "manual_pending"


AUTOMATED_REALIZATION_STATES = frozenset(
    {
        RealizationState.UNREALIZED,
        RealizationState.EXECUTABLE_BUT_FAILING,
        RealizationState.PASSING,
        RealizationState.STAGNATED,
        RealizationState.ESCALATED,
    }
)


@dataclass(frozen=True)
class RealizationSignals:
    """Explicit producer declarations returned by discovery or an adapter."""

    verification_id: str
    case_marker: bool = False
    fixture_generators: tuple[str, ...] = ()
    metric_emitters: tuple[str, ...] = ()
    evidence_producers: tuple[str, ...] = ()


@dataclass(frozen=True)
class RealizationCheck:
    """Deterministic dry-check result for one immutable manifest case."""

    verification_id: str
    automation: str
    blocking: bool
    state: RealizationState
    command_resolved: bool
    resolved_executable: str | None
    working_directory: str | None
    case_marker: bool
    missing_fixtures: tuple[str, ...]
    missing_metric_emitters: tuple[str, ...]
    missing_evidence_producers: tuple[str, ...]
    issues: tuple[str, ...]

    @property
    def realized(self) -> bool:
        return self.state not in {
            RealizationState.UNREALIZED,
            RealizationState.MANUAL_PENDING,
        }

    @property
    def missing_infrastructure(self) -> tuple[str, ...]:
        return self.issues

    def to_summary(self) -> dict[str, Any]:
        return {
            "verification_id": self.verification_id,
            "realization_state": self.state.value,
            "realized": self.realized,
            "command_resolved": self.command_resolved,
            "resolved_executable": self.resolved_executable,
            "working_directory": self.working_directory,
            "case_marker": self.case_marker,
            "missing_fixtures": list(self.missing_fixtures),
            "missing_metric_emitters": list(self.missing_metric_emitters),
            "missing_evidence_producers": list(self.missing_evidence_producers),
            "missing_infrastructure": list(self.issues),
        }


class VerificationExecutionError(ValueError):
    """A formal runtime contract is unsafe, inconsistent, or unexecutable."""


class RepetitionStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    LAUNCH_ERROR = "launch_error"


@dataclass(frozen=True)
class RunnerResult:
    """Domain-neutral result from one bounded command launch."""

    output: str
    return_code: int | None
    elapsed_seconds: float
    timed_out: bool = False
    launch_error: str | None = None
    termination_details: str | None = None
    output_truncated: bool = False
    selected_case_count: int | None = None
    executed_case_count: int | None = None
    skipped_case_count: int | None = None


@dataclass(frozen=True)
class RuntimeExecutionProof:
    """Positive runtime evidence that a verification did substantive work."""

    selected_case_count: int | None
    executed_case_count: int | None
    skipped_case_count: int | None
    assertion_record_count: int
    observation_record_count: int
    sources: tuple[str, ...]
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_case_count": self.selected_case_count,
            "executed_case_count": self.executed_case_count,
            "skipped_case_count": self.skipped_case_count,
            "assertion_record_count": self.assertion_record_count,
            "observation_record_count": self.observation_record_count,
            "sources": list(self.sources),
            "passed": self.passed,
            "error": self.error,
        }


class VerificationRunner(Protocol):
    """Runner boundary used by production subprocesses and deterministic fakes."""

    def run(
        self,
        *,
        command: str,
        worktree: str | Path,
        working_directory: str,
        timeout: int,
    ) -> RunnerResult:
        """Execute one command after independently validating its directory."""


@dataclass(frozen=True)
class EvidenceArtifact:
    """Trusted metadata calculated by the orchestrator from one evidence item."""

    name: str
    kind: str
    media_type: str
    description: str
    requirement_ids: tuple[str, ...]
    verification_id: str
    comparison: dict[str, Any] | None
    size: int
    sha256: str
    artifact_path: str | None
    inline_value: Any | None
    preview: str | None
    measurements: dict[str, float]
    scenarios: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = {
            "name": self.name,
            "kind": self.kind,
            "media_type": self.media_type,
            "description": self.description,
            "requirement_ids": list(self.requirement_ids),
            "verification_id": self.verification_id,
            "comparison": self.comparison,
            "size": self.size,
            "sha256": self.sha256,
            "artifact_path": self.artifact_path,
            "preview": self.preview,
            "measurements": self.measurements,
            "scenarios": list(self.scenarios),
        }
        if self.artifact_path is None:
            value["inline_value"] = self.inline_value
        return value


@dataclass(frozen=True)
class CoverageResult:
    name: str
    coverage_type: str
    enforcement: str
    status: str
    measurement_key: str | None
    operator: str | None
    threshold: int | float | None
    tolerance: int | float | None
    actual: float | None
    evidence_names: tuple[str, ...]
    missing_scenarios: tuple[str, ...]
    error: str | None

    @property
    def passed(self) -> bool:
        return self.status in {"descriptive", "passed"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "coverage_type": self.coverage_type,
            "enforcement": self.enforcement,
            "status": self.status,
            "measurement_key": self.measurement_key,
            "operator": self.operator,
            "threshold": self.threshold,
            "tolerance": self.tolerance,
            "actual": self.actual,
            "evidence_names": list(self.evidence_names),
            "missing_scenarios": list(self.missing_scenarios),
            "error": self.error,
        }


@dataclass(frozen=True)
class EvidenceAdapterResult:
    """Generic output from an external, domain-specific evidence adapter."""

    passed: bool
    metrics: Mapping[str, int | float]
    evidence: tuple[Mapping[str, Any], ...] = ()
    error: str | None = None
    realization_signals: tuple[RealizationSignals, ...] = ()


class EvidenceAdapter(Protocol):
    def evaluate(
        self,
        evidence: EvidenceArtifact,
        *,
        worktree: Path,
    ) -> EvidenceAdapterResult | None:
        """Return generic metrics/evidence, or ``None`` when unsupported."""


@dataclass(frozen=True)
class AssertionResult:
    metric: str
    operator: str
    threshold: int | float
    tolerance: int | float | None
    actual: float | None
    passed: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "operator": self.operator,
            "threshold": self.threshold,
            "tolerance": self.tolerance,
            "actual": self.actual,
            "passed": self.passed,
            "error": self.error,
        }


@dataclass(frozen=True)
class VerificationRepetitionResult:
    verification_id: str
    attempt: int
    repetition: int
    command: str
    working_directory: str
    timeout: int
    status: RepetitionStatus
    return_code: int | None
    output: str
    output_truncated: bool
    metrics: dict[str, float] | None
    assertion_results: tuple[AssertionResult, ...]
    evidence: tuple[EvidenceArtifact, ...]
    coverage_results: tuple[CoverageResult, ...]
    execution_proof: RuntimeExecutionProof
    elapsed_seconds: float
    timed_out: bool
    errors: tuple[str, ...]
    termination_details: str | None
    started_at: str
    finished_at: str
    record_id: int | None = None

    @property
    def passed(self) -> bool:
        return self.status == RepetitionStatus.PASSED


@dataclass(frozen=True)
class CaseAttemptResult:
    verification_id: str
    attempt: int | None
    status: str
    repetitions: tuple[VerificationRepetitionResult, ...]

    @property
    def passed(self) -> bool:
        return self.status == "passed"


@dataclass(frozen=True)
class CompletionGate:
    """Formal completion readiness for one worker run under review."""

    ready: bool
    status: str
    worker_run_id: str | None
    blocking_verification_ids: tuple[str, ...]
    pending_verification_ids: tuple[str, ...]
    stale_verification_ids: tuple[str, ...]
    failing_verification_ids: tuple[str, ...]
    escalated_verification_ids: tuple[str, ...]
    required_requirement_ids: tuple[str, ...]
    missing_requirement_ids: tuple[str, ...]
    unautomated_requirement_ids: tuple[str, ...]

    def to_summary(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "status": self.status,
            "worker_run_id": self.worker_run_id,
            "blocking_verification_ids": list(self.blocking_verification_ids),
            "pending_verification_ids": list(self.pending_verification_ids),
            "stale_verification_ids": list(self.stale_verification_ids),
            "failing_verification_ids": list(self.failing_verification_ids),
            "escalated_verification_ids": list(self.escalated_verification_ids),
            "required_requirement_ids": list(self.required_requirement_ids),
            "missing_requirement_ids": list(self.missing_requirement_ids),
            "unautomated_requirement_ids": list(self.unautomated_requirement_ids),
        }


@dataclass(frozen=True)
class FailureAnalysis:
    fingerprint: str
    identity: dict[str, Any]
    output_tail: str


_VOLATILE_TIMESTAMP = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}[T ][0-9:.+-]+Z?|\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)\b",
    re.IGNORECASE,
)
_VOLATILE_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_VOLATILE_ADDRESS = re.compile(r"\b0x[0-9a-f]+\b", re.IGNORECASE)
_VOLATILE_DURATION = re.compile(r"\b\d+(?:\.\d+)?\s*(?:ms|milliseconds?|s|seconds?)\b", re.IGNORECASE)
_DIAGNOSTIC_LINE = re.compile(
    r"\b(?:assert|error|exception|fail(?:ed|ure)?|fatal|missing|panic|timeout|"
    r"timed out|traceback|expected|actual|denied|unavailable)\b",
    re.IGNORECASE,
)


def _normalize_failure_text(value: str) -> str:
    text = _VOLATILE_TIMESTAMP.sub("<timestamp>", value)
    text = _VOLATILE_UUID.sub("<uuid>", text)
    text = _VOLATILE_ADDRESS.sub("<address>", text)
    text = _VOLATILE_DURATION.sub("<duration>", text)
    return " ".join(text.strip().split()).lower()


def _diagnostic_output_tail(value: str) -> str:
    bounded, _ = _bounded_tail(value, MAX_FAILURE_OUTPUT_TAIL_CHARACTERS)
    diagnostic = [
        _normalize_failure_text(line)
        for line in bounded.splitlines()
        if _DIAGNOSTIC_LINE.search(line)
    ]
    diagnostic = [line for line in diagnostic if line]
    if diagnostic:
        return "\n".join(diagnostic[-20:])
    return ""


def _failed_assertion_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "metric": str(value.get("metric") or ""),
        "operator": str(value.get("operator") or ""),
        "threshold": value.get("threshold"),
        "tolerance": value.get("tolerance"),
    }


def analyze_failure(
    *,
    return_codes: Sequence[int | None],
    failed_assertions: Sequence[Mapping[str, Any]],
    errors: Sequence[str],
    selected_metrics: Mapping[str, int | float],
    output: str,
) -> FailureAnalysis:
    """Return a deterministic, meaning-preserving failure signature."""

    assertion_identities = sorted(
        (_failed_assertion_identity(item) for item in failed_assertions),
        key=lambda item: canonical_json(item),
    )
    normalized_errors = sorted(
        {normalized for item in errors if (normalized := _normalize_failure_text(str(item)))}
    )
    metric_values: dict[str, float] = {}
    for name, value in selected_metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        numeric = float(value)
        if math.isfinite(numeric):
            metric_values[str(name)] = numeric
    output_tail = _diagnostic_output_tail(output)
    identity = {
        "return_codes": [item for item in return_codes],
        "failed_assertions": assertion_identities,
        "normalized_errors": normalized_errors,
        "diagnostic_output_tail": output_tail,
    }
    fingerprint_payload = {**identity, "selected_metrics": metric_values}
    fingerprint = hashlib.sha256(
        canonical_json(fingerprint_payload).encode("utf-8")
    ).hexdigest()
    return FailureAnalysis(fingerprint, identity, output_tail)


def compute_failure_fingerprint(
    *,
    return_codes: Sequence[int | None],
    failed_assertions: Sequence[Mapping[str, Any]],
    errors: Sequence[str],
    selected_metrics: Mapping[str, int | float],
    output: str,
) -> str:
    return analyze_failure(
        return_codes=return_codes,
        failed_assertions=failed_assertions,
        errors=errors,
        selected_metrics=selected_metrics,
        output=output,
    ).fingerprint


def _metric_score(
    value: float, assertion: Mapping[str, Any] | None
) -> float:
    if assertion is None:
        return value
    threshold = assertion.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        return value
    target = float(threshold)
    operator = assertion.get("operator")
    if operator in {"<", "<="}:
        return target - value
    if operator in {">", ">="}:
        return value - target
    if operator == "==":
        return -abs(value - target)
    if operator == "!=":
        return abs(value - target)
    return value


def classify_metric_trend(
    metric_history: Sequence[Mapping[str, Any]],
    assertions: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Classify comparable attempt metrics; malformed or conflicting data is non-deterministic."""

    if len(metric_history) < 2:
        return "insufficient"
    keysets = [set(item) for item in metric_history]
    if not keysets[0] or any(keys != keysets[0] for keys in keysets[1:]):
        return "non-deterministic"
    parsed: list[dict[str, float]] = []
    for item in metric_history:
        values: dict[str, float] = {}
        for name in sorted(keysets[0]):
            value = item.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return "non-deterministic"
            numeric = float(value)
            if not math.isfinite(numeric):
                return "non-deterministic"
            values[str(name)] = numeric
        parsed.append(values)
    assertion_by_metric = {
        str(item.get("metric")): item
        for item in assertions
        if isinstance(item, Mapping) and isinstance(item.get("metric"), str)
    }
    movements: list[int] = []
    for previous, current in zip(parsed, parsed[1:]):
        step: set[int] = set()
        for name in sorted(previous):
            before = _metric_score(previous[name], assertion_by_metric.get(name))
            after = _metric_score(current[name], assertion_by_metric.get(name))
            delta = after - before
            step.add(0 if math.isclose(delta, 0.0, rel_tol=1e-12, abs_tol=1e-12) else (1 if delta > 0 else -1))
        nonzero = step - {0}
        if len(nonzero) > 1:
            return "non-deterministic"
        movements.append(next(iter(nonzero), 0))
    if all(item == 0 for item in movements):
        return "unchanged"
    nonzero_movements = [item for item in movements if item]
    if 1 in nonzero_movements and -1 in nonzero_movements:
        return "oscillating"
    if all(item >= 0 for item in movements) and 1 in movements:
        return "improving"
    if all(item <= 0 for item in movements) and -1 in movements:
        return "regressing"
    return "non-deterministic"


def transition_realization_state(
    previous: str | RealizationState | None,
    *,
    realized: bool,
    manual: bool,
) -> RealizationState:
    """Apply the static realization transition without inventing runtime results.

    A newly realized case is executable but has not passed yet.  Later runtime
    terminal/progress states survive a dry refresh while their infrastructure
    remains valid.  Removing infrastructure deterministically returns an
    automated case to ``unrealized``.
    """

    if manual:
        return RealizationState.MANUAL_PENDING
    if not realized:
        return RealizationState.UNREALIZED
    if previous is None:
        return RealizationState.EXECUTABLE_BUT_FAILING
    try:
        current = RealizationState(previous)
    except ValueError as exc:
        raise ValueError(f"unsupported verification state: {previous}") from exc
    if current in {
        RealizationState.PASSING,
        RealizationState.STAGNATED,
        RealizationState.ESCALATED,
    }:
        return current
    return RealizationState.EXECUTABLE_BUT_FAILING


def _manifest_payload(manifest: Any) -> Mapping[str, Any]:
    if isinstance(manifest, Mapping):
        return manifest
    to_dict = getattr(manifest, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return payload
    raise ValueError("realization checking requires a verification manifest object")


def _specification_payload(specification: Any) -> Mapping[str, Any]:
    if isinstance(specification, Mapping):
        return specification
    to_dict = getattr(specification, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return payload
    raise VerificationExecutionError(
        "completion coverage requires a specification document object"
    )


def _completion_requirement_links(
    specification: Any | None,
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, tuple[str, ...]]]:
    """Map mandatory/high-risk requirements onto their linked verification cases."""

    if specification is None:
        return {}
    payload = _specification_payload(specification)
    raw_requirements = payload.get("requirements")
    raw_risks = payload.get("risks")
    if not isinstance(raw_requirements, list) or not isinstance(raw_risks, list):
        raise VerificationExecutionError(
            "specification completion coverage requires requirement and risk arrays"
        )

    mandatory_ids = {
        str(item.get("id"))
        for item in raw_requirements
        if isinstance(item, Mapping)
        and isinstance(item.get("id"), str)
        and item.get("priority") == "must"
    }
    high_risk_verification_ids: set[str] = set()
    for risk in raw_risks:
        if not isinstance(risk, Mapping):
            raise VerificationExecutionError("specification risks must be objects")
        if risk.get("severity") not in {"high", "critical"} and risk.get(
            "uncertainty"
        ) != "high":
            continue
        verification_ids = risk.get("verification_ids")
        if not isinstance(verification_ids, list) or any(
            not isinstance(item, str) for item in verification_ids
        ):
            raise VerificationExecutionError(
                "high-risk specification entries require verification ID arrays"
            )
        high_risk_verification_ids.update(verification_ids)

    high_risk_requirement_ids: set[str] = set()
    for case in cases:
        if str(case.get("verification_id")) not in high_risk_verification_ids:
            continue
        requirement_ids = case.get("requirement_ids")
        if not isinstance(requirement_ids, list) or any(
            not isinstance(item, str) for item in requirement_ids
        ):
            raise VerificationExecutionError(
                "manifest verification cases require requirement ID arrays"
            )
        high_risk_requirement_ids.update(requirement_ids)

    links: dict[str, dict[str, tuple[str, ...]]] = {}
    for case in cases:
        verification_id = str(case.get("verification_id"))
        requirement_ids = case.get("requirement_ids")
        if not isinstance(requirement_ids, list):
            raise VerificationExecutionError(
                f"manifest verification {verification_id} requires a requirement ID array"
            )
        mandatory = tuple(item for item in requirement_ids if item in mandatory_ids)
        high_risk = tuple(
            item for item in requirement_ids if item in high_risk_requirement_ids
        )
        links[verification_id] = {
            "mandatory_requirement_ids": mandatory,
            "high_risk_requirement_ids": high_risk,
        }
    return links


def _contained_path(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("path resolves outside the worktree") from exc
    return resolved


def validate_execution_working_directory(
    worktree: str | Path,
    working_directory: str,
) -> Path:
    """Resolve a live execution directory without trusting stored validation."""

    root = Path(worktree).expanduser().resolve()
    if not root.is_dir():
        raise VerificationExecutionError(
            f"worktree does not exist or is not a directory: {root}"
        )
    try:
        validate_working_directory(working_directory, root)
        resolved = _contained_path(root, root / working_directory)
    except (SpecificationError, ValueError) as exc:
        raise VerificationExecutionError(str(exc)) from exc
    if not resolved.exists():
        raise VerificationExecutionError("working directory does not exist")
    if not resolved.is_dir():
        raise VerificationExecutionError("working directory is not a directory")
    return resolved


def _combined_process_output(stdout: Any, stderr: Any) -> str:
    def text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    return (text(stdout) + "\n" + text(stderr)).strip()


class SubprocessVerificationRunner:
    """Production runner following AI-Loop's established bash process shape."""

    def run(
        self,
        *,
        command: str,
        worktree: str | Path,
        working_directory: str,
        timeout: int,
    ) -> RunnerResult:
        directory = validate_execution_working_directory(worktree, working_directory)
        if not isinstance(command, str) or not command.strip():
            raise VerificationExecutionError("verification command must be non-empty")
        if command.strip().lower() == "auto":
            raise VerificationExecutionError("verification command is unresolved 'auto'")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
            raise VerificationExecutionError("verification timeout must be a positive integer")
        started = time.monotonic()
        try:
            process = run_bounded_process(
                ["bash", "-lc", command],
                cwd=str(directory),
                timeout=timeout,
                env=sanitized_child_env(),
                max_output_bytes=MAX_PROCESS_OUTPUT_BYTES,
            )
            if process.timed_out:
                return _normalized_runner_result(
                    RunnerResult(
                        output=_combined_process_output(process.stdout, process.stderr),
                        return_code=None,
                        elapsed_seconds=max(0.0, time.monotonic() - started),
                        timed_out=True,
                        termination_details=f"timed out after {timeout} seconds",
                        output_truncated=process.output_truncated,
                    )
                )
            return _normalized_runner_result(
                RunnerResult(
                    output=_combined_process_output(process.stdout, process.stderr),
                    return_code=process.returncode,
                    elapsed_seconds=max(0.0, time.monotonic() - started),
                    output_truncated=process.output_truncated,
                )
            )
        except OSError as exc:
            return RunnerResult(
                output="",
                return_code=None,
                elapsed_seconds=max(0.0, time.monotonic() - started),
                launch_error=f"{type(exc).__name__}: {exc}",
                termination_details="process launch failed before command execution",
            )


def _case_working_directory(worktree: Path, value: Any) -> tuple[Path | None, str | None]:
    try:
        validate_working_directory(value, worktree)
    except SpecificationError as exc:
        return None, str(exc)
    candidate = _contained_path(worktree, worktree / str(value))
    if not candidate.exists():
        return None, "working directory does not exist"
    if not candidate.is_dir():
        return None, "working directory is not a directory"
    return candidate, None


def _command_tokens(command: str) -> list[str]:
    try:
        tokens = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return []
    while tokens and _ENV_ASSIGNMENT.fullmatch(tokens[0]):
        tokens.pop(0)
    if tokens and tokens[0] == "env":
        tokens.pop(0)
        while tokens and (_ENV_ASSIGNMENT.fullmatch(tokens[0]) or tokens[0].startswith("-")):
            tokens.pop(0)
    return tokens


def resolve_command(
    command: Any,
    working_directory: Path,
    *,
    worktree: Path | None = None,
    executable_search_path: str | None = None,
) -> tuple[bool, str | None, str | None]:
    """Resolve a command executable without launching it."""

    if not isinstance(command, str) or not command.strip():
        return False, None, "verification command is empty"
    if command.strip().lower() == "auto":
        return False, None, "verification command is unresolved 'auto'"
    tokens = _command_tokens(command)
    if not tokens:
        return False, None, "verification command cannot be parsed"
    executable = tokens[0]
    if executable in {"&&", "||", ";", "|"}:
        return False, None, "verification command has no executable"
    posix = PurePosixPath(executable)
    windows = PureWindowsPath(executable)
    has_path = (
        len(posix.parts) > 1
        or len(windows.parts) > 1
        or posix.is_absolute()
        or windows.is_absolute()
    )
    if has_path:
        candidate = Path(executable)
        if not candidate.is_absolute():
            candidate = working_directory / candidate
            try:
                candidate = _contained_path(worktree or working_directory, candidate)
            except ValueError:
                return False, None, "relative command executable escapes the worktree"
        candidate = candidate.resolve(strict=False)
        if not candidate.is_file():
            return False, None, f"command executable does not exist: {executable}"
        if not os.access(candidate, os.X_OK):
            return False, None, f"command executable is not executable: {executable}"
        return True, str(candidate), None
    resolved = shutil.which(executable, path=executable_search_path)
    if resolved is None:
        return False, None, f"command executable is unavailable: {executable}"
    return True, str(Path(resolved).resolve()), None


def _iter_source_files(worktree: Path) -> Iterable[Path]:
    for path in sorted(worktree.rglob("*"), key=lambda item: item.as_posix()):
        if any(part in DISCOVERY_EXCLUDED_DIRECTORIES for part in path.relative_to(worktree).parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        try:
            if path.stat().st_size > MAX_DISCOVERY_FILE_BYTES:
                continue
            _contained_path(worktree, path)
        except (OSError, ValueError):
            continue
        yield path


def _json_envelopes(text: str) -> Iterable[tuple[str, Mapping[str, Any]]]:
    decoder = json.JSONDecoder()
    for match in _ENVELOPE.finditer(text):
        try:
            payload, _end = decoder.raw_decode(text, match.end())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, Mapping):
            yield match.group(1), payload


def _string_values(payload: Mapping[str, Any], plural: str, singular: str) -> set[str]:
    value = payload.get(plural, payload.get(singular, []))
    if isinstance(value, str):
        return {value}
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str)}


def discover_realization_signals(worktree: str | Path) -> tuple[RealizationSignals, ...]:
    """Discover valid, bounded JSON realization envelopes in repository files."""

    root = Path(worktree).resolve()
    if not root.is_dir():
        raise ValueError(f"worktree does not exist or is not a directory: {root}")
    combined: dict[str, dict[str, Any]] = {}

    def signals_for(verification_id: str) -> dict[str, Any]:
        return combined.setdefault(
            verification_id,
            {"case_marker": False, "fixtures": set(), "metrics": set(), "evidence": set()},
        )

    for path in _iter_source_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        envelopes = list(_json_envelopes(text))
        file_case_ids = {
            str(payload["verification_id"])
            for kind, payload in envelopes
            if kind == "CASE" and isinstance(payload.get("verification_id"), str)
        }
        for verification_id in file_case_ids:
            signals_for(verification_id)["case_marker"] = True
        for kind, payload in envelopes:
            raw_id = payload.get("verification_id")
            target_ids = {raw_id} if isinstance(raw_id, str) else set(file_case_ids)
            for verification_id in target_ids:
                target = signals_for(verification_id)
                if kind == "FIXTURE_GENERATOR":
                    target["fixtures"].update(_string_values(payload, "fixtures", "fixture"))
                elif kind == "METRIC_EMITTER":
                    target["metrics"].update(_string_values(payload, "metrics", "metric"))
                elif kind == "EVIDENCE_PRODUCER":
                    target["evidence"].update(_string_values(payload, "kinds", "kind"))
                elif kind == "REALIZATION":
                    target["case_marker"] = bool(payload.get("case_marker", True))
                    target["fixtures"].update(_string_values(payload, "fixtures", "fixture"))
                    target["metrics"].update(_string_values(payload, "metrics", "metric"))
                    target["evidence"].update(_string_values(payload, "evidence", "evidence_kind"))
                elif kind == "METRICS" and isinstance(payload.get("metrics"), Mapping):
                    target["metrics"].update(
                        key for key in payload["metrics"] if isinstance(key, str)
                    )
                elif kind == "EVIDENCE":
                    items = payload.get("items", [payload])
                    if isinstance(items, list):
                        target["evidence"].update(
                            str(item["kind"])
                            for item in items
                            if isinstance(item, Mapping) and isinstance(item.get("kind"), str)
                        )
    return tuple(
        RealizationSignals(
            verification_id=verification_id,
            case_marker=bool(values["case_marker"]),
            fixture_generators=tuple(sorted(values["fixtures"])),
            metric_emitters=tuple(sorted(values["metrics"])),
            evidence_producers=tuple(sorted(values["evidence"])),
        )
        for verification_id, values in sorted(combined.items())
    )


def _merge_signals(signals: Iterable[RealizationSignals]) -> dict[str, RealizationSignals]:
    merged: dict[str, dict[str, Any]] = {}
    for item in signals:
        target = merged.setdefault(
            item.verification_id,
            {"case_marker": False, "fixtures": set(), "metrics": set(), "evidence": set()},
        )
        target["case_marker"] = target["case_marker"] or item.case_marker
        target["fixtures"].update(item.fixture_generators)
        target["metrics"].update(item.metric_emitters)
        target["evidence"].update(item.evidence_producers)
    return {
        verification_id: RealizationSignals(
            verification_id=verification_id,
            case_marker=bool(values["case_marker"]),
            fixture_generators=tuple(sorted(values["fixtures"])),
            metric_emitters=tuple(sorted(values["metrics"])),
            evidence_producers=tuple(sorted(values["evidence"])),
        )
        for verification_id, values in merged.items()
    }


def _fixture_exists(fixture: str, worktree: Path, working_directory: Path) -> bool:
    if not fixture.strip() or "\x00" in fixture:
        return False
    posix = PurePosixPath(fixture)
    windows = PureWindowsPath(fixture)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        return False
    if ".." in posix.parts or ".." in windows.parts:
        return False
    for base in (working_directory, worktree):
        try:
            candidate = _contained_path(worktree, base / fixture)
        except ValueError:
            continue
        if candidate.exists():
            return True
    return False


def check_manifest_realization(
    manifest: Any,
    worktree: str | Path,
    *,
    previous_states: Mapping[str, str] | None = None,
    adapter_results: Sequence[RealizationSignals] = (),
    executable_search_path: str | None = None,
) -> tuple[RealizationCheck, ...]:
    """Compute each case's dry realization state without running commands."""

    payload = _manifest_payload(manifest)
    raw_cases = payload.get("verification")
    if not isinstance(raw_cases, list):
        raise ValueError("verification manifest must contain a verification array")
    root = Path(worktree).resolve()
    if not root.is_dir():
        raise ValueError(f"worktree does not exist or is not a directory: {root}")
    discovered = discover_realization_signals(root)
    signals = _merge_signals((*discovered, *adapter_results))
    previous = previous_states or {}
    results: list[RealizationCheck] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, Mapping):
            raise ValueError("verification manifest cases must be objects")
        verification_id = raw_case.get("verification_id")
        automation = raw_case.get("automation")
        blocking = raw_case.get("blocking")
        if not isinstance(verification_id, str) or not isinstance(automation, str):
            raise ValueError("verification cases require string IDs and automation values")
        if not isinstance(blocking, bool):
            raise ValueError(f"verification {verification_id} blocking must be boolean")
        if automation == "manual":
            if blocking:
                raise ValueError(f"manual verification {verification_id} cannot block completion")
            results.append(
                RealizationCheck(
                    verification_id=verification_id,
                    automation=automation,
                    blocking=False,
                    state=RealizationState.MANUAL_PENDING,
                    command_resolved=False,
                    resolved_executable=None,
                    working_directory=None,
                    case_marker=False,
                    missing_fixtures=(),
                    missing_metric_emitters=(),
                    missing_evidence_producers=(),
                    issues=(),
                )
            )
            continue

        issues: list[str] = []
        working_directory, directory_error = _case_working_directory(
            root, raw_case.get("working_directory")
        )
        if directory_error:
            issues.append(directory_error)
        command_ok = False
        resolved_executable: str | None = None
        if working_directory is not None:
            command_ok, resolved_executable, command_error = resolve_command(
                raw_case.get("command"),
                working_directory,
                worktree=root,
                executable_search_path=executable_search_path,
            )
            if command_error:
                issues.append(command_error)
        else:
            issues.append(
                "verification command cannot be resolved without a safe working directory"
            )

        case_signals = signals.get(verification_id, RealizationSignals(verification_id))
        if not case_signals.case_marker:
            issues.append(f"missing AI_LOOP_CASE marker for {verification_id}")
        fixtures = raw_case.get("fixtures", [])
        metrics = raw_case.get("metrics", [])
        required_evidence = raw_case.get("required_evidence", [])
        if not all(isinstance(value, list) for value in (fixtures, metrics, required_evidence)):
            raise ValueError(
                f"verification {verification_id} infrastructure declarations must be arrays"
            )
        if any(not isinstance(item, str) for item in (*fixtures, *metrics)) or any(
            not isinstance(item, (str, Mapping)) for item in required_evidence
        ):
            raise ValueError(
                f"verification {verification_id} infrastructure declarations are malformed"
            )
        missing_fixtures = tuple(
            fixture
            for fixture in fixtures
            if fixture not in case_signals.fixture_generators
            and (
                working_directory is None
                or not _fixture_exists(fixture, root, working_directory)
            )
        )
        missing_metrics = tuple(
            metric for metric in metrics if metric not in case_signals.metric_emitters
        )
        missing_evidence = tuple(
            (item if isinstance(item, str) else str(item.get("kind", "")))
            for item in required_evidence
            if (item if isinstance(item, str) else str(item.get("kind", "")))
            not in case_signals.evidence_producers
        )
        issues.extend(
            f"missing fixture or deterministic generator: {item}"
            for item in missing_fixtures
        )
        issues.extend(f"missing metric emitter: {item}" for item in missing_metrics)
        issues.extend(f"missing evidence producer: {item}" for item in missing_evidence)
        realized = not issues and command_ok and case_signals.case_marker
        state = transition_realization_state(
            previous.get(verification_id), realized=realized, manual=False
        )
        results.append(
            RealizationCheck(
                verification_id=verification_id,
                automation=automation,
                blocking=blocking,
                state=state,
                command_resolved=command_ok,
                resolved_executable=resolved_executable,
                working_directory=None if working_directory is None else str(working_directory),
                case_marker=case_signals.case_marker,
                missing_fixtures=missing_fixtures,
                missing_metric_emitters=missing_metrics,
                missing_evidence_producers=missing_evidence,
                issues=tuple(issues),
            )
        )
    return tuple(results)


def persist_realization_checks(
    db_path: str | Path,
    job_id: str,
    checks: Sequence[RealizationCheck],
) -> None:
    """Persist aggregate states only, leaving immutable artifacts untouched."""

    check_by_id = {item.verification_id: item for item in checks}
    if len(check_by_id) != len(checks):
        raise ValueError("realization checks contain duplicate verification IDs")
    with db.transaction(db_path) as conn:
        job = db.get_job(conn, job_id)
        if job.get("specification_id") is None or job.get("specification_version") is None:
            if checks:
                raise ValueError("Quick Goal jobs cannot receive realization state")
            return
        manifest_exists = conn.execute(
            "SELECT 1 FROM verification_manifests WHERE job_id = ?", (job_id,)
        ).fetchone()
        if manifest_exists is None:
            raise ValueError("formal job realization requires a persisted manifest")
        rows = conn.execute(
            "SELECT * FROM job_verification_states WHERE job_id = ?", (job_id,)
        ).fetchall()
        row_by_id = {
            str(row["verification_id"]): row
            for row in rows
            if str(row["verification_id"]) in check_by_id
        }
        if set(row_by_id) != set(check_by_id):
            raise ValueError("realization checks differ from active manifest case state")
        now = db.utc_now()
        changed: list[dict[str, Any]] = []
        for verification_id, check in check_by_id.items():
            row = row_by_id[verification_id]
            if row["automation"] != check.automation or bool(row["blocking"]) != check.blocking:
                raise ValueError(
                    f"verification state metadata differs from manifest case {verification_id}"
                )
            if row["status"] == check.state.value:
                continue
            conn.execute(
                """
                UPDATE job_verification_states SET status = ?, updated_at = ?
                WHERE job_id = ? AND verification_id = ?
                """,
                (check.state.value, now, job_id, verification_id),
            )
            changed.append(
                {
                    "verification_id": verification_id,
                    "previous_state": row["status"],
                    "state": check.state.value,
                    "missing_infrastructure": list(check.missing_infrastructure),
                }
            )
        if changed:
            db.add_event(
                conn,
                job_id=job_id,
                kind="verification_realization_updated",
                payload={"changes": changed},
            )


def refresh_job_realization(
    specification_service: Any,
    job_id: str,
    *,
    adapter_results: Sequence[RealizationSignals] = (),
    executable_search_path: str | None = None,
) -> tuple[RealizationCheck, ...] | None:
    """Integrity-load and refresh a formal job; return ``None`` for Quick Goal."""

    stored = specification_service.load_job_manifest(job_id)
    if stored is None:
        with db.transaction(specification_service.db_path) as conn:
            state_count = conn.execute(
                "SELECT COUNT(*) FROM job_verification_states WHERE job_id = ?", (job_id,)
            ).fetchone()[0]
        if state_count:
            raise ValueError("Quick Goal job unexpectedly has verification state")
        return None
    with db.transaction(specification_service.db_path) as conn:
        job = db.get_job(conn, job_id)
        previous = {
            str(row["verification_id"]): str(row["status"])
            for row in conn.execute(
                "SELECT verification_id, status FROM job_verification_states WHERE job_id = ?",
                (job_id,),
            )
        }
    checks = check_manifest_realization(
        stored.manifest,
        str(job["worktree_path"]),
        previous_states=previous,
        adapter_results=adapter_results,
        executable_search_path=executable_search_path,
    )
    persist_realization_checks(specification_service.db_path, job_id, checks)
    return checks


def build_runtime_verification_summary(
    db_path: str | Path,
    job_id: str,
    manifest: Any | None,
    *,
    worker_run_id: str | None = None,
    specification: Any | None = None,
) -> tuple[dict[str, Any], ...] | None:
    """Build trusted aggregate/runtime state for a formal controller prompt.

    Freshness is deliberately scoped to the worker run currently under
    review.  A prior passing attempt remains append-only history, but cannot
    satisfy the current completion gate.
    """

    with db.transaction(db_path) as conn:
        job = db.get_job(conn, job_id)
        formal = job.get("specification_id") is not None
        states = conn.execute(
            """
            SELECT *
            FROM job_verification_states WHERE job_id = ?
            """,
            (job_id,),
        ).fetchall()
        repetitions = db.list_verification_repetitions(conn, job_id)
        corrections = db.list_verification_correction_attempts(conn, job_id)
    if not formal:
        if manifest is not None or states or repetitions or corrections:
            raise VerificationExecutionError(
                "Quick Goal job unexpectedly has formal verification runtime state"
            )
        return None
    if manifest is None:
        raise VerificationExecutionError(
            "formal runtime verification summary requires its immutable manifest"
        )

    payload = _manifest_payload(manifest)
    cases = payload.get("verification")
    if not isinstance(cases, list):
        raise VerificationExecutionError(
            "verification manifest must contain a verification array"
        )
    coverage_links = _completion_requirement_links(specification, cases)
    state_by_id = {str(row["verification_id"]): dict(row) for row in states}
    repetitions_by_id: dict[str, list[dict[str, Any]]] = {}
    for repetition in repetitions:
        repetitions_by_id.setdefault(str(repetition["verification_id"]), []).append(
            repetition
        )
    corrections_by_id: dict[str, list[dict[str, Any]]] = {}
    for correction in corrections:
        corrections_by_id.setdefault(str(correction["verification_id"]), []).append(
            correction
        )

    summary: list[dict[str, Any]] = []
    manifest_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping) or not isinstance(
            case.get("verification_id"), str
        ):
            raise VerificationExecutionError(
                "manifest verification cases require string IDs"
            )
        verification_id = str(case["verification_id"])
        if verification_id in manifest_ids:
            raise VerificationExecutionError(
                f"manifest contains duplicate verification ID: {verification_id}"
            )
        manifest_ids.add(verification_id)
        state = state_by_id.get(verification_id)
        if state is None:
            raise VerificationExecutionError(
                f"formal verification state is missing for {verification_id}"
            )
        if (
            state["automation"] != case.get("automation")
            or bool(state["blocking"]) != bool(case.get("blocking"))
        ):
            raise VerificationExecutionError(
                f"verification state metadata differs from manifest case {verification_id}"
            )
        loop = case.get("validation_loop")
        if not isinstance(loop, Mapping):
            raise VerificationExecutionError(
                f"verification {verification_id} validation loop must be an object"
            )
        attempt_offset = int(state.get("attempt_offset") or 0)
        case_repetitions = [
            item
            for item in repetitions_by_id.get(verification_id, [])
            if int(item["attempt"]) > attempt_offset
        ]
        case_corrections = [
            item
            for item in corrections_by_id.get(verification_id, [])
            if int(item["attempt"]) > attempt_offset
        ]
        latest_global_attempt = max(
            (int(item["attempt"]) for item in case_repetitions),
            default=attempt_offset,
        )
        attempts_completed = max(0, latest_global_attempt - attempt_offset)
        latest_attempt = [
            item
            for item in case_repetitions
            if int(item["attempt"]) == latest_global_attempt
        ]
        latest_row = latest_attempt[-1] if latest_attempt else None
        latest_metrics = next(
            (
                item["metrics"]
                for item in reversed(latest_attempt)
                if item.get("metrics") is not None
            ),
            None,
        )
        latest_evidence = next(
            (
                item["evidence"]
                for item in reversed(latest_attempt)
                if item.get("evidence")
            ),
            [],
        )
        latest_coverage = next(
            (
                item["coverage_results"]
                for item in reversed(latest_attempt)
                if item.get("coverage_results")
            ),
            [],
        )
        failed_assertions = [
            assertion
            for item in latest_attempt
            for assertion in item.get("assertion_results", [])
            if isinstance(assertion, Mapping) and assertion.get("passed") is False
        ]
        last_error = next(
            (
                str(item["error"])
                for item in reversed(latest_attempt)
                if item.get("error")
            ),
            None,
        )
        state_last_error = state.get("last_error")
        if state_last_error:
            last_error = str(state_last_error)
        automation = str(state["automation"])
        aggregate_status = str(state["status"])
        required_repetitions = loop.get("repetitions_per_attempt")
        attempt_limit = loop.get("maximum_correction_attempts")
        remaining_attempt_budget = (
            max(0, int(attempt_limit) - attempts_completed)
            if isinstance(attempt_limit, int) and not isinstance(attempt_limit, bool)
            else 0
        )
        latest_failed_row = next(
            (item for item in reversed(latest_attempt) if item["status"] != RepetitionStatus.PASSED.value),
            None,
        )
        latest_failed_repetition = None
        if latest_failed_row is not None:
            latest_failed_repetition = {
                "repetition": int(latest_failed_row["repetition"]),
                "status": str(latest_failed_row["status"]),
                "return_code": latest_failed_row.get("return_code"),
                "expected_vs_actual": [
                    {
                        "metric": item.get("metric"),
                        "operator": item.get("operator"),
                        "threshold": item.get("threshold"),
                        "tolerance": item.get("tolerance"),
                        "actual": item.get("actual"),
                    }
                    for item in latest_failed_row.get("assertion_results", [])
                    if isinstance(item, Mapping) and item.get("passed") is False
                ],
                "error": latest_failed_row.get("error"),
                "evidence_paths": [
                    str(item.get("artifact_path"))
                    for item in latest_failed_row.get("evidence", [])
                    if isinstance(item, Mapping) and item.get("artifact_path")
                ],
            }
        metric_history = [dict(item.get("metric_values") or {}) for item in case_corrections]
        previous_repair_goals = [
            str(item.get("repair_goal") or "")
            for item in case_corrections
            if str(item.get("repair_goal") or "").strip()
        ]
        escalation_report = db.from_json(state.get("escalation_report_json"), None)
        latest_is_complete_pass = (
            isinstance(required_repetitions, int)
            and not isinstance(required_repetitions, bool)
            and len(latest_attempt) == required_repetitions
            and bool(latest_attempt)
            and all(item["status"] == RepetitionStatus.PASSED.value for item in latest_attempt)
        )
        if automation == "manual":
            freshness = "not_applicable"
        elif worker_run_id is None:
            freshness = "not_under_review"
        elif (
            aggregate_status == RealizationState.PASSING.value
            and latest_is_complete_pass
            and all(item.get("worker_run_id") == worker_run_id for item in latest_attempt)
        ):
            freshness = "fresh"
        elif aggregate_status == RealizationState.PASSING.value and latest_attempt:
            freshness = "stale"
        else:
            freshness = "pending"
        summary_item = {
                "verification_id": verification_id,
                "title": str(case.get("title") or ""),
                "requirement_ids": list(case.get("requirement_ids") or []),
                "blocking": bool(state["blocking"]),
                "automation": automation,
                "status": aggregate_status,
                "attempts_completed": attempts_completed,
                "attempt_limit": attempt_limit,
                "repetitions_per_attempt": required_repetitions,
                "stagnation_limit": loop.get("stagnation_limit"),
                "latest_metrics": latest_metrics,
                "latest_evidence": latest_evidence,
                "coverage_results": latest_coverage,
                "execution_proof": (
                    {} if latest_row is None else latest_row.get("execution_proof", {})
                ),
                "failed_assertions": failed_assertions,
                "last_error": last_error,
                "last_task": None if latest_row is None else latest_row.get("task_id"),
                "last_worker_run": (
                    None if latest_row is None else latest_row.get("worker_run_id")
                ),
                "worker_run_under_review": worker_run_id,
                "evidence_freshness": freshness,
                "evidence_fresh": freshness == "fresh",
                "updated_at": state["updated_at"],
            }
        if verification_id in coverage_links:
            summary_item.update(coverage_links[verification_id])
        if case_corrections:
            summary_item.update(
                {
                    "remaining_attempt_budget": remaining_attempt_budget,
                    "consecutive_failures": int(state.get("consecutive_failures") or 0),
                    "stagnation_count": int(state.get("stagnation_count") or 0),
                    "stagnation_series": int(state.get("stagnation_series") or 0),
                    "failure_fingerprint": state.get("failure_fingerprint"),
                    "metric_trend": str(state.get("metric_trend") or "insufficient"),
                    "metric_history": metric_history,
                    "latest_failed_repetition": latest_failed_repetition,
                    "previous_repair_goals": previous_repair_goals,
                    "escalation_report": escalation_report,
                    "finished_at": state.get("finished_at"),
                }
            )
        summary.append(summary_item)
    # Retargeting keeps removed-case state and evidence append-only.  Active
    # summaries project only IDs present in the current immutable manifest.
    return tuple(summary)


def evaluate_completion_gate(
    verification_summary: Sequence[Mapping[str, Any]] | None,
    *,
    worker_run_id: str | None,
) -> CompletionGate | None:
    """Evaluate the formal fresh-run completion contract; ``None`` is Quick Goal."""

    if verification_summary is None:
        return None
    explicitly_blocking = tuple(
        item
        for item in verification_summary
        if bool(item.get("blocking")) and item.get("automation") != "manual"
    )
    explicit_ids = tuple(
        str(item.get("verification_id")) for item in explicitly_blocking
    )
    required_requirement_ids = tuple(
        dict.fromkeys(
            str(requirement_id)
            for item in verification_summary
            for field in (
                "mandatory_requirement_ids",
                "high_risk_requirement_ids",
            )
            for requirement_id in item.get(field, ())
            if isinstance(requirement_id, str)
        )
    )

    def has_positive_execution_proof(item: Mapping[str, Any]) -> bool:
        proof = item.get("execution_proof")
        if not isinstance(proof, Mapping) or proof.get("passed") is not True:
            return False
        selected = proof.get("selected_case_count")
        executed = proof.get("executed_case_count")
        skipped = proof.get("skipped_case_count")
        if selected == 0 or executed == 0:
            return False
        if (
            executed is None
            and isinstance(selected, int)
            and isinstance(skipped, int)
            and skipped >= selected
        ):
            return False
        assertions = proof.get("assertion_record_count")
        observations = proof.get("observation_record_count")
        return bool(
            (isinstance(executed, int) and executed > 0)
            or (isinstance(selected, int) and selected > 0)
            or (isinstance(assertions, int) and assertions > 0)
            or (isinstance(observations, int) and observations > 0)
        )

    def fresh_runtime_pass(item: Mapping[str, Any]) -> bool:
        return (
            item.get("automation") != "manual"
            and item.get("status") == RealizationState.PASSING.value
            and has_positive_execution_proof(item)
            and item.get("evidence_freshness") == "fresh"
            and item.get("worker_run_under_review") == worker_run_id
            and worker_run_id is not None
        )

    def fresh_automated_pass(item: Mapping[str, Any]) -> bool:
        return item.get("automation") == "automated" and fresh_runtime_pass(item)

    automated_candidates: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for requirement_id in required_requirement_ids:
        automated_candidates[requirement_id] = tuple(
            item
            for item in verification_summary
            if item.get("automation") == "automated"
            and requirement_id in item.get("requirement_ids", ())
        )
    missing_requirement_ids = tuple(
        requirement_id
        for requirement_id in required_requirement_ids
        if not any(
            fresh_automated_pass(item)
            for item in automated_candidates[requirement_id]
        )
    )
    unautomated_requirement_ids = tuple(
        requirement_id
        for requirement_id in missing_requirement_ids
        if not automated_candidates[requirement_id]
    )

    needed_coverage_ids: set[str] = set()
    for requirement_id in missing_requirement_ids:
        candidates = automated_candidates[requirement_id]
        non_escalated = tuple(
            item
            for item in candidates
            if item.get("status") != RealizationState.ESCALATED.value
        )
        needed_coverage_ids.update(
            str(item.get("verification_id"))
            for item in (non_escalated or candidates)
        )
    blocking_ids = tuple(
        str(item.get("verification_id"))
        for item in verification_summary
        if str(item.get("verification_id")) in set(explicit_ids) | needed_coverage_ids
    )
    blocking = tuple(
        item
        for item in verification_summary
        if str(item.get("verification_id")) in blocking_ids
    )
    escalated = tuple(
        str(item.get("verification_id"))
        for item in blocking
        if item.get("status") == RealizationState.ESCALATED.value
    )
    fresh = {
        str(item.get("verification_id"))
        for item in explicitly_blocking
        if fresh_runtime_pass(item)
    }
    stale = tuple(
        str(item.get("verification_id"))
        for item in blocking
        if item.get("status") == RealizationState.PASSING.value
        and has_positive_execution_proof(item)
        and str(item.get("verification_id")) not in fresh
    )
    failing = tuple(
        str(item.get("verification_id"))
        for item in blocking
        if (
            item.get("status")
            in {
                RealizationState.EXECUTABLE_BUT_FAILING.value,
                RealizationState.STAGNATED.value,
            }
            or (
                item.get("status") == RealizationState.PASSING.value
                and not has_positive_execution_proof(item)
            )
        )
        and int(item.get("attempts_completed") or 0) > 0
    )
    pending = tuple(
        verification_id
        for verification_id in blocking_ids
        if verification_id not in fresh
        and verification_id not in stale
        and verification_id not in failing
        and verification_id not in escalated
    )
    ready = (
        len(fresh) == len(explicit_ids)
        and not missing_requirement_ids
        and not escalated
    )
    if escalated:
        status = "escalated"
    elif ready:
        status = "ready"
    elif unautomated_requirement_ids:
        status = "unautomated"
    elif failing:
        status = "failing"
    elif stale:
        status = "stale"
    else:
        status = "pending"
    return CompletionGate(
        ready=ready,
        status=status,
        worker_run_id=worker_run_id,
        blocking_verification_ids=blocking_ids,
        pending_verification_ids=pending,
        stale_verification_ids=stale,
        failing_verification_ids=failing,
        escalated_verification_ids=escalated,
        required_requirement_ids=required_requirement_ids,
        missing_requirement_ids=missing_requirement_ids,
        unautomated_requirement_ids=unautomated_requirement_ids,
    )


def _bounded_tail(value: str, maximum: int) -> tuple[str, bool]:
    if len(value) <= maximum:
        return value, False
    return value[-maximum:], True


def _numeric_metric_payload(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping) or not isinstance(value.get("metrics"), Mapping):
        return None
    metrics: dict[str, float] = {}
    for name, raw in value["metrics"].items():
        if not isinstance(name, str) or not name.strip():
            return None
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        try:
            number = float(raw)
        except (OverflowError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        metrics[name] = number
    return metrics


def parse_numeric_metrics(
    output: str,
    *,
    max_characters: int = MAX_METRIC_SCAN_CHARACTERS,
) -> dict[str, float] | None:
    """Return the last valid bounded metrics payload from combined output."""

    if not isinstance(output, str):
        raise TypeError("verification output must be text")
    if (
        isinstance(max_characters, bool)
        or not isinstance(max_characters, int)
        or max_characters <= 0
    ):
        raise ValueError("metric scan bound must be positive")
    bounded, _truncated = _bounded_tail(output, max_characters)
    latest: dict[str, float] | None = None
    markers = ("AI_LOOP_METRICS=", "AI_LOOP_EVIDENCE=")
    for raw_line in bounded.splitlines():
        line = raw_line.strip()
        candidates: list[str] = []
        for marker in markers:
            marker_index = line.find(marker)
            if marker_index >= 0:
                candidates.append(line[marker_index + len(marker) :].strip())
        if not candidates and line.startswith("{"):
            candidates.append(line)
        for candidate in candidates:
            try:
                payload = json.loads(candidate)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            metrics = _numeric_metric_payload(payload)
            if metrics is not None:
                latest = metrics
    return latest


def _json_bytes(value: Any, path: str) -> bytes:
    if not isinstance(value, (dict, list)):
        raise VerificationExecutionError(
            f"{path} must be an inline structured object or array"
        )
    try:
        return canonical_json(value).encode("utf-8")
    except (SpecificationError, TypeError, ValueError) as exc:
        raise VerificationExecutionError(f"{path} is not supported JSON data: {exc}") from exc


def _evidence_measurements(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    raw = value.get("measurements", value.get("metrics"))
    if raw is None:
        return {}
    parsed = _numeric_metric_payload({"metrics": raw})
    if parsed is None:
        raise VerificationExecutionError("coverage evidence measurements must be finite numbers")
    return parsed


def _evidence_scenarios(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Mapping) or "scenarios" not in value:
        return ()
    scenarios = value["scenarios"]
    if not isinstance(scenarios, list) or any(
        not isinstance(item, str) or not item.strip() for item in scenarios
    ):
        raise VerificationExecutionError(
            "coverage evidence scenarios must be an array of non-empty strings"
        )
    if len(scenarios) != len(set(scenarios)):
        raise VerificationExecutionError("coverage evidence scenarios contain duplicates")
    return tuple(scenarios)


def _safe_evidence_source(
    path_value: Any,
    *,
    worktree: Path,
    working_directory: Path,
    case_output_directory: Path | None,
) -> Path:
    if not isinstance(path_value, str) or not path_value.strip() or "\x00" in path_value:
        raise VerificationExecutionError("evidence path must be a non-empty relative path")
    posix = PurePosixPath(path_value)
    windows = PureWindowsPath(path_value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or path_value.startswith(("//", "\\\\"))
    ):
        raise VerificationExecutionError("evidence path must not be absolute")
    if ".." in posix.parts or ".." in windows.parts:
        raise VerificationExecutionError("evidence path must not contain parent traversal")
    candidates: list[tuple[Path, Path]] = [
        (worktree, working_directory / path_value),
        (worktree, worktree / path_value),
    ]
    if case_output_directory is not None:
        output_root = case_output_directory.resolve()
        candidates.insert(0, (output_root, output_root / path_value))
    escaped = False
    for allowed_root, candidate in candidates:
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(allowed_root.resolve())
        except (OSError, ValueError):
            escaped = True
            continue
        if resolved.exists():
            if not resolved.is_file():
                raise VerificationExecutionError("evidence path is not a regular file")
            return resolved
    if escaped:
        raise VerificationExecutionError("evidence path resolves outside its allowed root")
    raise VerificationExecutionError(f"evidence file does not exist: {path_value}")


def _preview(payload: bytes, media_type: str) -> str | None:
    textual = media_type.startswith("text/") or media_type in {
        "application/json",
        "application/xml",
        "application/yaml",
    }
    if not textual:
        return None
    text = payload.decode("utf-8", errors="replace")
    if len(text) <= MAX_EVIDENCE_PREVIEW_CHARACTERS:
        return text
    return text[:MAX_EVIDENCE_PREVIEW_CHARACTERS]


def _store_evidence_payload(
    payload: bytes,
    *,
    artifact_directory: Path | None,
    index: int,
    name: str,
    suffix: str,
    source_path: Path,
) -> str:
    if artifact_directory is None:
        return str(source_path)
    artifact_directory.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-") or "evidence"
    destination = artifact_directory / f"{index:04d}-{safe_name}{suffix}"
    try:
        with destination.open("xb") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise VerificationExecutionError(
            f"immutable evidence artifact already exists: {destination}"
        ) from exc
    except OSError as exc:
        raise VerificationExecutionError(f"failed to store evidence artifact: {exc}") from exc
    return str(destination)


def _evidence_artifact_from_item(
    item_value: Any,
    *,
    index: int,
    verification_id: str,
    allowed_requirement_ids: set[str],
    worktree: Path,
    working_directory: Path,
    artifact_directory: Path | None,
    case_output_directory: Path | None,
    max_artifact_bytes: int,
    max_inline_bytes: int,
) -> EvidenceArtifact:
    if not isinstance(item_value, Mapping):
        raise VerificationExecutionError(f"evidence item {index} must be an object")
    allowed_fields = {
        "name",
        "kind",
        "path",
        "inline",
        "media_type",
        "description",
        "requirement_ids",
        "verification_id",
        "comparison",
        "sha256",
        "size",
    }
    unknown = sorted(set(item_value) - allowed_fields)
    if unknown:
        raise VerificationExecutionError(
            f"evidence item {index} contains unknown fields: {', '.join(unknown)}"
        )
    required = {
        "name",
        "kind",
        "media_type",
        "description",
        "requirement_ids",
        "verification_id",
    }
    missing = sorted(required - set(item_value))
    if missing:
        raise VerificationExecutionError(
            f"evidence item {index} is missing fields: {', '.join(missing)}"
        )
    name = item_value["name"]
    if not isinstance(name, str) or not EVIDENCE_NAME_PATTERN.fullmatch(name):
        raise VerificationExecutionError(f"evidence item {index} has an invalid stable name")
    kind = item_value["kind"]
    if not isinstance(kind, str) or kind not in {entry.value for entry in EvidenceKind}:
        raise VerificationExecutionError(f"evidence item {index} has an unsupported kind")
    for field_name in ("media_type", "description"):
        if not isinstance(item_value[field_name], str) or not item_value[field_name].strip():
            raise VerificationExecutionError(
                f"evidence item {index} {field_name} must be a non-empty string"
            )
    if item_value["verification_id"] != verification_id:
        raise VerificationExecutionError(
            f"evidence item {index} verification_id does not match {verification_id}"
        )
    requirement_ids = item_value["requirement_ids"]
    if not isinstance(requirement_ids, list) or any(
        not isinstance(value, str) for value in requirement_ids
    ):
        raise VerificationExecutionError(
            f"evidence item {index} requirement_ids must be a string array"
        )
    if len(requirement_ids) != len(set(requirement_ids)):
        raise VerificationExecutionError(
            f"evidence item {index} requirement_ids contains duplicates"
        )
    unknown_requirements = sorted(set(requirement_ids) - allowed_requirement_ids)
    if unknown_requirements:
        raise VerificationExecutionError(
            f"evidence item {index} has unlinked requirement IDs: "
            + ", ".join(unknown_requirements)
        )
    comparison = item_value.get("comparison")
    if comparison is not None:
        if not isinstance(comparison, Mapping):
            raise VerificationExecutionError(
                f"evidence item {index} comparison must be an object or null"
            )
        _json_bytes(dict(comparison), f"evidence item {index} comparison")
        comparison = dict(comparison)

    has_path = "path" in item_value and item_value.get("path") is not None
    has_inline = "inline" in item_value and item_value.get("inline") is not None
    if has_path == has_inline:
        raise VerificationExecutionError(
            f"evidence item {index} must define exactly one of path or inline"
        )
    artifact_path: str | None = None
    source_path: Path | None = None
    source_suffix = ""
    inline_value: Any | None = None
    structured_value: Any | None = None
    if has_inline:
        inline_value = item_value["inline"]
        payload = _json_bytes(inline_value, f"evidence item {index} inline")
        if len(payload) > max_inline_bytes:
            raise VerificationExecutionError(
                f"evidence item {index} inline data exceeds {max_inline_bytes} bytes"
            )
        structured_value = inline_value
    else:
        source = _safe_evidence_source(
            item_value["path"],
            worktree=worktree,
            working_directory=working_directory,
            case_output_directory=case_output_directory,
        )
        try:
            size = source.stat().st_size
        except OSError as exc:
            raise VerificationExecutionError(f"cannot stat evidence file: {exc}") from exc
        if size > max_artifact_bytes:
            raise VerificationExecutionError(
                f"evidence artifact exceeds {max_artifact_bytes} bytes"
            )
        try:
            payload = source.read_bytes()
        except OSError as exc:
            raise VerificationExecutionError(f"cannot read evidence file: {exc}") from exc
        if len(payload) > max_artifact_bytes:
            raise VerificationExecutionError(
                f"evidence artifact exceeds {max_artifact_bytes} bytes"
            )
        source_path = source
        source_suffix = source.suffix if len(source.suffix) <= 16 else ""
        if item_value["media_type"] == "application/json":
            try:
                structured_value = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise VerificationExecutionError(
                    f"evidence item {index} declares invalid JSON data"
                ) from exc

    size = len(payload)
    digest = hashlib.sha256(payload).hexdigest()
    claimed_size = item_value.get("size")
    if claimed_size is not None and (
        isinstance(claimed_size, bool) or not isinstance(claimed_size, int) or claimed_size != size
    ):
        raise VerificationExecutionError(
            f"evidence item {index} untrusted claimed size does not match orchestrator value"
        )
    claimed_hash = item_value.get("sha256")
    if claimed_hash is not None and claimed_hash != digest:
        raise VerificationExecutionError(
            f"evidence item {index} untrusted claimed hash does not match orchestrator SHA-256"
        )
    if source_path is not None:
        artifact_path = _store_evidence_payload(
            payload,
            artifact_directory=artifact_directory,
            index=index,
            name=name,
            suffix=source_suffix,
            source_path=source_path,
        )
    return EvidenceArtifact(
        name=name,
        kind=kind,
        media_type=str(item_value["media_type"]),
        description=str(item_value["description"]),
        requirement_ids=tuple(requirement_ids),
        verification_id=verification_id,
        comparison=comparison,
        size=size,
        sha256=digest,
        artifact_path=artifact_path,
        inline_value=inline_value,
        preview=_preview(payload, str(item_value["media_type"])),
        measurements=_evidence_measurements(structured_value),
        scenarios=_evidence_scenarios(structured_value),
    )


def parse_structured_evidence(
    output: str,
    *,
    verification_id: str,
    requirement_ids: Sequence[str],
    worktree: str | Path,
    working_directory: str = ".",
    artifact_directory: str | Path | None = None,
    case_output_directory: str | Path | None = None,
    max_characters: int = MAX_METRIC_SCAN_CHARACTERS,
    max_artifact_bytes: int = MAX_EVIDENCE_ARTIFACT_BYTES,
    max_inline_bytes: int = MAX_INLINE_EVIDENCE_BYTES,
) -> tuple[EvidenceArtifact, ...]:
    """Parse and secure every bounded ``AI_LOOP_EVIDENCE`` item."""

    if not isinstance(output, str):
        raise TypeError("verification output must be text")
    for name, value in (
        ("evidence scan bound", max_characters),
        ("evidence artifact limit", max_artifact_bytes),
        ("inline evidence limit", max_inline_bytes),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be positive")
    root = Path(worktree).resolve()
    live_working_directory = validate_execution_working_directory(root, working_directory)
    artifact_root = None if artifact_directory is None else Path(artifact_directory).resolve()
    output_root = (
        None if case_output_directory is None else Path(case_output_directory).resolve()
    )
    bounded, _truncated = _bounded_tail(output, max_characters)
    marker = "AI_LOOP_EVIDENCE="
    artifacts: list[EvidenceArtifact] = []
    names: set[str] = set()
    for raw_line in bounded.splitlines():
        marker_index = raw_line.find(marker)
        if marker_index < 0:
            continue
        candidate = raw_line[marker_index + len(marker) :].strip()
        try:
            envelope = json.loads(candidate)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise VerificationExecutionError(f"malformed AI_LOOP_EVIDENCE envelope: {exc}") from exc
        if not isinstance(envelope, Mapping):
            raise VerificationExecutionError("AI_LOOP_EVIDENCE envelope must be an object")
        unknown = sorted(set(envelope) - {"items", "metrics"})
        if unknown:
            raise VerificationExecutionError(
                "AI_LOOP_EVIDENCE envelope contains unknown fields: " + ", ".join(unknown)
            )
        items = envelope.get("items", [])
        if not isinstance(items, list):
            raise VerificationExecutionError("AI_LOOP_EVIDENCE items must be an array")
        if "metrics" in envelope and _numeric_metric_payload(envelope) is None:
            raise VerificationExecutionError(
                "AI_LOOP_EVIDENCE metrics must contain finite numeric values"
            )
        for item in items:
            artifact = _evidence_artifact_from_item(
                item,
                index=len(artifacts) + 1,
                verification_id=verification_id,
                allowed_requirement_ids=set(requirement_ids),
                worktree=root,
                working_directory=live_working_directory,
                artifact_directory=artifact_root,
                case_output_directory=output_root,
                max_artifact_bytes=max_artifact_bytes,
                max_inline_bytes=max_inline_bytes,
            )
            if artifact.name in names:
                raise VerificationExecutionError(
                    f"AI_LOOP_EVIDENCE contains duplicate name: {artifact.name}"
                )
            names.add(artifact.name)
            artifacts.append(artifact)
    return tuple(artifacts)


def evaluate_coverage_targets(
    targets: Sequence[str | Mapping[str, Any] | CoverageTarget],
    evidence: Sequence[EvidenceArtifact],
) -> tuple[CoverageResult, ...]:
    """Classify prose targets honestly and enforce structured coverage evidence."""

    results: list[CoverageResult] = []
    for index, target_value in enumerate(targets):
        if isinstance(target_value, str):
            results.append(
                CoverageResult(
                    name=target_value,
                    coverage_type="descriptive",
                    enforcement="descriptive",
                    status="descriptive",
                    measurement_key=None,
                    operator=None,
                    threshold=None,
                    tolerance=None,
                    actual=None,
                    evidence_names=(),
                    missing_scenarios=(),
                    error=None,
                )
            )
            continue
        try:
            target = (
                target_value
                if isinstance(target_value, CoverageTarget)
                else CoverageTarget.from_dict(dict(target_value), f"coverage_targets[{index}]")
            )
        except (SpecificationError, TypeError, ValueError) as exc:
            raise VerificationExecutionError(f"invalid coverage target: {exc}") from exc
        supplied = tuple(
            value is not None
            for value in (
                target.measurement_key,
                target.operator,
                target.threshold,
                target.evidence_kind,
            )
        )
        if any(supplied) and not all(supplied):
            raise VerificationExecutionError(
                f"coverage target {target.name} has a partial machine-enforcement contract"
            )
        if target.machine_enforced and target.evidence_kind != EvidenceKind.COVERAGE:
            raise VerificationExecutionError(
                f"coverage target {target.name} does not map to coverage evidence"
            )
        if not target.machine_enforced:
            results.append(
                CoverageResult(
                    name=target.name,
                    coverage_type=target.coverage_type.value,
                    enforcement="descriptive",
                    status="descriptive",
                    measurement_key=target.measurement_key,
                    operator=target.operator,
                    threshold=target.threshold,
                    tolerance=target.tolerance,
                    actual=None,
                    evidence_names=(),
                    missing_scenarios=(),
                    error=None,
                )
            )
            continue
        matching = [item for item in evidence if item.kind == target.evidence_kind.value]
        evidence_names = tuple(item.name for item in matching)
        scenario_set = {scenario for item in matching for scenario in item.scenarios}
        missing_scenarios = tuple(
            scenario for scenario in target.required_scenarios if scenario not in scenario_set
        )
        actual: float | None = None
        for item in matching:
            if target.measurement_key in item.measurements:
                actual = item.measurements[target.measurement_key]
        assertion = MetricAssertion(
            metric=target.measurement_key or "",
            operator=target.operator or "",
            threshold=target.threshold if target.threshold is not None else 0,
            tolerance=target.tolerance,
        )
        assertion_result = evaluate_metric_assertion(assertion, actual)
        errors: list[str] = []
        if not matching:
            errors.append("missing emitted coverage evidence")
        if not assertion_result.passed:
            errors.append(assertion_result.error or "coverage assertion failed")
        if missing_scenarios:
            errors.append("missing required scenarios: " + ", ".join(missing_scenarios))
        results.append(
            CoverageResult(
                name=target.name,
                coverage_type=target.coverage_type.value,
                enforcement="machine_enforced",
                status="passed" if not errors else "failed",
                measurement_key=target.measurement_key,
                operator=target.operator,
                threshold=target.threshold,
                tolerance=target.tolerance,
                actual=actual,
                evidence_names=evidence_names,
                missing_scenarios=missing_scenarios,
                error="; ".join(errors) or None,
            )
        )
    return tuple(results)


def evaluate_metric_assertion(
    assertion: MetricAssertion | Mapping[str, Any],
    actual: Any,
) -> AssertionResult:
    """Evaluate one assertion and retain its complete expected/actual contract."""

    try:
        parsed = (
            assertion
            if isinstance(assertion, MetricAssertion)
            else MetricAssertion.from_dict(dict(assertion), "metric_assertion")
        )
    except (SpecificationError, TypeError, ValueError) as exc:
        return AssertionResult(
            metric=str(assertion.get("metric", "") if isinstance(assertion, Mapping) else ""),
            operator=str(
                assertion.get("operator", "") if isinstance(assertion, Mapping) else ""
            ),
            threshold=(
                assertion.get("threshold", 0)
                if isinstance(assertion, Mapping)
                and isinstance(assertion.get("threshold"), (int, float))
                and not isinstance(assertion.get("threshold"), bool)
                else 0
            ),
            tolerance=(
                assertion.get("tolerance") if isinstance(assertion, Mapping) else None
            ),
            actual=None,
            passed=False,
            error=f"invalid metric assertion: {exc}",
        )
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return AssertionResult(
            metric=parsed.metric,
            operator=parsed.operator,
            threshold=parsed.threshold,
            tolerance=parsed.tolerance,
            actual=None,
            passed=False,
            error=f"missing metric key: {parsed.metric}",
        )
    value = float(actual)
    if not math.isfinite(value):
        return AssertionResult(
            metric=parsed.metric,
            operator=parsed.operator,
            threshold=parsed.threshold,
            tolerance=parsed.tolerance,
            actual=None,
            passed=False,
            error=f"metric {parsed.metric} is not finite",
        )
    try:
        passed = parsed.evaluate(value)
    except SpecificationError as exc:
        return AssertionResult(
            metric=parsed.metric,
            operator=parsed.operator,
            threshold=parsed.threshold,
            tolerance=parsed.tolerance,
            actual=value,
            passed=False,
            error=str(exc),
        )
    return AssertionResult(
        metric=parsed.metric,
        operator=parsed.operator,
        threshold=parsed.threshold,
        tolerance=parsed.tolerance,
        actual=value,
        passed=passed,
        error=None if passed else f"metric assertion failed: {parsed.metric}",
    )


def _task_ids(task: Mapping[str, Any], field: str) -> list[str]:
    value = task.get(field, [])
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise VerificationExecutionError(f"task.{field} must contain only string IDs")
    result = list(value)
    duplicates = sorted({item for item in result if result.count(item) > 1})
    if duplicates:
        raise VerificationExecutionError(
            f"task.{field} contains duplicate IDs: {', '.join(duplicates)}"
        )
    return result


def select_task_verification_cases(
    manifest: Any | None,
    task: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Select explicit and requirement-linked cases before any command runs."""

    requirement_ids = _task_ids(task, "requirement_ids")
    verification_ids = _task_ids(task, "verification_ids")
    if manifest is None:
        if requirement_ids or verification_ids:
            raise VerificationExecutionError(
                "Quick Goal tasks cannot select formal verification cases"
            )
        return ()
    if not requirement_ids and not verification_ids:
        raise VerificationExecutionError(
            "formal task verification requires a requirement_id or verification_id"
        )
    payload = _manifest_payload(manifest)
    work_items = payload.get("work_items")
    cases = payload.get("verification")
    if not isinstance(work_items, list) or not isinstance(cases, list):
        raise VerificationExecutionError(
            "verification manifest requires work_items and verification arrays"
        )
    requirement_set: set[str] = set()
    for item in work_items:
        if not isinstance(item, Mapping) or not isinstance(item.get("requirement_id"), str):
            raise VerificationExecutionError("manifest work items require requirement IDs")
        requirement_set.add(str(item["requirement_id"]))
    case_by_id: dict[str, dict[str, Any]] = {}
    case_order: list[str] = []
    for item in cases:
        if not isinstance(item, Mapping) or not isinstance(item.get("verification_id"), str):
            raise VerificationExecutionError("manifest verification cases require IDs")
        verification_id = str(item["verification_id"])
        if verification_id in case_by_id:
            raise VerificationExecutionError(
                f"manifest contains duplicate verification ID: {verification_id}"
            )
        case_by_id[verification_id] = dict(item)
        case_order.append(verification_id)
    unknown_requirements = sorted(set(requirement_ids) - requirement_set)
    unknown_verifications = sorted(set(verification_ids) - set(case_by_id))
    if unknown_requirements:
        raise VerificationExecutionError(
            "task requirement IDs are absent from the manifest: "
            + ", ".join(unknown_requirements)
        )
    if unknown_verifications:
        raise VerificationExecutionError(
            "task verification IDs are absent from the manifest: "
            + ", ".join(unknown_verifications)
        )
    selected = set(verification_ids)
    for verification_id, case in case_by_id.items():
        linked = case.get("requirement_ids")
        if not isinstance(linked, list) or any(not isinstance(item, str) for item in linked):
            raise VerificationExecutionError(
                f"manifest verification {verification_id} has invalid requirement IDs"
            )
        if set(requirement_ids).intersection(linked):
            selected.add(verification_id)
    return tuple(case_by_id[item] for item in case_order if item in selected)


def _normalized_runner_result(value: Any) -> RunnerResult:
    if not isinstance(value, RunnerResult):
        raise TypeError("verification runner must return RunnerResult")
    if not isinstance(value.output, str):
        raise TypeError("verification runner output must be text")
    if value.return_code is not None and (
        isinstance(value.return_code, bool) or not isinstance(value.return_code, int)
    ):
        raise TypeError("verification runner return code must be an integer or null")
    if (
        isinstance(value.elapsed_seconds, bool)
        or not isinstance(value.elapsed_seconds, (int, float))
        or not math.isfinite(float(value.elapsed_seconds))
        or value.elapsed_seconds < 0
    ):
        raise TypeError("verification runner elapsed time must be finite and non-negative")
    for name in (
        "selected_case_count",
        "executed_case_count",
        "skipped_case_count",
    ):
        count = getattr(value, name)
        if count is not None and (
            isinstance(count, bool) or not isinstance(count, int) or count < 0
        ):
            raise TypeError(f"verification runner {name} must be a non-negative integer or null")
    detected = _detect_test_execution_counts(value.output)
    output_proves_no_execution = detected[0] == 0 or detected[1] == 0
    selected = (
        detected[0]
        if output_proves_no_execution and detected[0] is not None
        else value.selected_case_count
        if value.selected_case_count is not None
        else detected[0]
    )
    executed = (
        detected[1]
        if output_proves_no_execution and detected[1] is not None
        else value.executed_case_count
        if value.executed_case_count is not None
        else detected[1]
    )
    skipped = (
        detected[2]
        if output_proves_no_execution and detected[2] is not None
        else value.skipped_case_count
        if value.skipped_case_count is not None
        else detected[2]
    )
    if selected is not None and skipped is not None and skipped > selected:
        raise TypeError("verification runner skipped count cannot exceed selected count")
    if (
        selected is not None
        and executed is not None
        and skipped is not None
        and executed + skipped > selected
    ):
        raise TypeError(
            "verification runner executed and skipped counts cannot exceed selected count"
        )
    return replace(
        value,
        selected_case_count=selected,
        executed_case_count=executed,
        skipped_case_count=skipped,
    )


def _detect_test_execution_counts(
    output: str,
) -> tuple[int | None, int | None, int | None]:
    """Extract conservative pytest/unittest counts from actual command output."""

    scan = output[-MAX_METRIC_SCAN_CHARACTERS:]
    unittest_runs = list(_UNITTEST_RAN.finditer(scan))
    if unittest_runs:
        selected = int(unittest_runs[-1].group(1))
        skipped_matches = list(_UNITTEST_SKIPPED.finditer(scan))
        skipped = int(skipped_matches[-1].group(1)) if skipped_matches else 0
        return selected, max(0, selected - skipped), skipped

    counts: dict[str, int] = {}
    for match in _PYTEST_COUNT.finditer(scan):
        kind = match.group("kind").lower()
        if kind == "error":
            kind = "errors"
        counts[kind] = int(match.group("count"))
    collected_matches = list(_PYTEST_COLLECTED.finditer(scan))
    selected_matches = list(_PYTEST_SELECTED.finditer(scan))
    if not counts and not collected_matches and not selected_matches:
        if _PYTEST_NO_TESTS.search(scan):
            return 0, 0, 0
        return None, None, None

    skipped = counts.get("skipped", 0)
    executed = sum(
        counts.get(kind, 0)
        for kind in ("passed", "failed", "errors", "xfailed", "xpassed")
    )
    summarized = executed + skipped
    if selected_matches:
        selected = int(selected_matches[-1].group(1))
    elif summarized:
        selected = summarized
    elif collected_matches:
        selected = int(collected_matches[-1].group(1)) - counts.get("deselected", 0)
        selected = max(0, selected)
    else:
        selected = 0
    return selected, executed, skipped


def _runtime_execution_proof(
    runner_result: RunnerResult,
    *,
    assertion_record_count: int,
    observation_record_count: int,
) -> RuntimeExecutionProof:
    selected = runner_result.selected_case_count
    executed = runner_result.executed_case_count
    skipped = runner_result.skipped_case_count
    sources: list[str] = []
    if any(item is not None for item in (selected, executed, skipped)):
        sources.append("test-runner-counts")
    if assertion_record_count:
        sources.append("assertion-records")
    if observation_record_count:
        sources.append("observation-records")

    error: str | None = None
    if selected == 0:
        error = (
            "runtime execution proof missing: the verification command selected zero "
            "test cases; fix its test target or selection filters so the intended case runs"
        )
    elif executed == 0:
        if skipped and (selected is None or skipped >= selected):
            error = (
                "runtime execution proof missing: all selected test cases were skipped "
                f"(selected={selected if selected is not None else skipped}, skipped={skipped}); "
                "satisfy the skip prerequisites and rerun the intended case"
            )
        else:
            error = (
                "runtime execution proof missing: the verification command executed zero "
                "test cases; run the intended case instead of a collection-only or no-op command"
            )
    elif (
        executed is None
        and selected is not None
        and skipped is not None
        and skipped >= selected
    ):
        error = (
            "runtime execution proof missing: all selected test cases were skipped "
            f"(selected={selected}, skipped={skipped}); satisfy the skip prerequisites "
            "and rerun the intended case"
        )
    elif executed is None and selected is None and not (
        assertion_record_count or observation_record_count
    ):
        error = (
            "runtime execution proof missing: the verification command reported no executed "
            "or selected test cases and emitted no explicit structured assertion or observation "
            "records; run the intended case and report its runtime result"
        )
    return RuntimeExecutionProof(
        selected_case_count=selected,
        executed_case_count=executed,
        skipped_case_count=skipped,
        assertion_record_count=assertion_record_count,
        observation_record_count=observation_record_count,
        sources=tuple(sources),
        error=error,
    )


def _evaluate_repetition(
    case: Mapping[str, Any],
    runner_result: RunnerResult,
    *,
    attempt: int,
    repetition: int,
    started_at: str,
    finished_at: str,
    worktree: Path,
    evidence_artifact_directory: Path | None,
    log_path: Path | None,
    adapters: Sequence[EvidenceAdapter],
) -> VerificationRepetitionResult:
    verification_id = str(case["verification_id"])
    errors: list[str] = []
    if runner_result.launch_error:
        errors.append(f"launch exception: {runner_result.launch_error}")
    if runner_result.timed_out:
        errors.append(f"command timed out after {case['timeout']} seconds")
    if runner_result.return_code != 0 and not runner_result.timed_out and not runner_result.launch_error:
        errors.append(f"command exited with return code {runner_result.return_code}")

    metrics = parse_numeric_metrics(runner_result.output)
    evidence: list[EvidenceArtifact] = []
    try:
        evidence.extend(
            parse_structured_evidence(
                runner_result.output,
                verification_id=verification_id,
                requirement_ids=case.get("requirement_ids", []),
                worktree=worktree,
                working_directory=str(case["working_directory"]),
                artifact_directory=evidence_artifact_directory,
                case_output_directory=(
                    None
                    if evidence_artifact_directory is None
                    else evidence_artifact_directory.parent / "outputs"
                ),
            )
        )
    except VerificationExecutionError as exc:
        errors.append(str(exc))

    # Execution proof is based only on records emitted by the verification
    # command. Adapter-derived metrics/evidence may satisfy domain coverage,
    # but cannot prove that the intended command actually executed work.
    command_observation_count = len(evidence) + (1 if metrics is not None else 0)
    command_metric_names = frozenset(metrics or {})
    adapter_metrics: dict[str, float] = {}
    adapter_evidence: list[EvidenceArtifact] = []
    for adapter_index, adapter in enumerate(adapters, 1):
        for artifact in tuple(evidence):
            try:
                adapter_result = adapter.evaluate(artifact, worktree=worktree)
            except Exception as exc:
                errors.append(f"evidence adapter raised: {type(exc).__name__}: {exc}")
                continue
            if adapter_result is None:
                continue
            if not isinstance(adapter_result, EvidenceAdapterResult):
                errors.append("evidence adapter returned an unsupported result")
                continue
            parsed_adapter_metrics = _numeric_metric_payload(
                {"metrics": dict(adapter_result.metrics)}
            )
            if parsed_adapter_metrics is None:
                errors.append("evidence adapter returned invalid numeric metrics")
            else:
                for name, value in parsed_adapter_metrics.items():
                    if name in adapter_metrics and adapter_metrics[name] != value:
                        errors.append(f"evidence adapters returned conflicting metric: {name}")
                    adapter_metrics[name] = value
            if not adapter_result.passed:
                errors.append(adapter_result.error or "evidence adapter reported failure")
            if adapter_result.evidence:
                try:
                    envelope = json.dumps(
                        {"items": [dict(item) for item in adapter_result.evidence]},
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    adapter_evidence.extend(
                        parse_structured_evidence(
                            f"AI_LOOP_EVIDENCE={envelope}",
                            verification_id=verification_id,
                            requirement_ids=case.get("requirement_ids", []),
                            worktree=worktree,
                            working_directory=str(case["working_directory"]),
                            artifact_directory=(
                                None
                                if evidence_artifact_directory is None
                                else evidence_artifact_directory / f"adapter-{adapter_index:04d}"
                            ),
                        )
                    )
                except (VerificationExecutionError, TypeError, ValueError) as exc:
                    errors.append(f"invalid evidence adapter output: {exc}")
    evidence.extend(adapter_evidence)
    duplicate_evidence_names = sorted(
        {item.name for item in evidence if sum(other.name == item.name for other in evidence) > 1}
    )
    if duplicate_evidence_names:
        errors.append(
            "duplicate evidence names after adapter evaluation: "
            + ", ".join(duplicate_evidence_names)
        )
    if adapter_metrics:
        metrics = dict(metrics or {})
        for name, value in adapter_metrics.items():
            if name in metrics and metrics[name] != value:
                errors.append(f"adapter metric conflicts with command metric: {name}")
            metrics[name] = value

    if log_path is not None:
        payload = runner_result.output.encode("utf-8")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with log_path.open("xb") as handle:
                handle.write(payload)
        except OSError as exc:
            errors.append(f"failed to retain command output evidence: {exc}")
        else:
            evidence.append(
                EvidenceArtifact(
                    name="command-output",
                    kind=EvidenceKind.LOG.value,
                    media_type="text/plain; charset=utf-8",
                    description="Combined verification command output retained by AI-Loop",
                    requirement_ids=tuple(case.get("requirement_ids", [])),
                    verification_id=verification_id,
                    comparison=None,
                    size=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest(),
                    artifact_path=str(log_path),
                    inline_value=None,
                    preview=_preview(payload, "text/plain"),
                    measurements={},
                    scenarios=(),
                )
            )
    declared = case.get("metrics", [])
    assertions = case.get("metric_assertions", [])
    if not isinstance(declared, list) or any(not isinstance(item, str) for item in declared):
        raise VerificationExecutionError(
            f"verification {verification_id} metrics must be a string array"
        )
    if not isinstance(assertions, list):
        raise VerificationExecutionError(
            f"verification {verification_id} metric_assertions must be an array"
        )
    if declared and metrics is None:
        errors.append("missing required metrics object")
    if metrics is not None:
        for metric in declared:
            if metric not in metrics:
                errors.append(f"missing declared metric key: {metric}")

    assertion_results: list[AssertionResult] = []
    for assertion in assertions:
        if not isinstance(assertion, Mapping):
            raise VerificationExecutionError(
                f"verification {verification_id} metric assertions must be objects"
            )
        metric = assertion.get("metric")
        actual = None if metrics is None or not isinstance(metric, str) else metrics.get(metric)
        result = evaluate_metric_assertion(assertion, actual)
        assertion_results.append(result)
        if not result.passed:
            errors.append(result.error or f"metric assertion failed: {result.metric}")

    required_evidence = case.get("required_evidence", [])
    if not isinstance(required_evidence, list):
        raise VerificationExecutionError(
            f"verification {verification_id} required_evidence must be an array"
        )
    for declaration in required_evidence:
        if isinstance(declaration, str):
            continue
        if not isinstance(declaration, Mapping):
            raise VerificationExecutionError(
                f"verification {verification_id} evidence declarations must be strings or objects"
            )
        name = declaration.get("name")
        kind = declaration.get("kind")
        media_type = declaration.get("media_type")
        declared_requirements = declaration.get("requirement_ids", [])
        if not any(
            item.name == name
            and item.kind == kind
            and item.media_type == media_type
            and set(declared_requirements).issubset(item.requirement_ids)
            for item in evidence
        ):
            errors.append(f"missing required evidence item: {name}")

    coverage_targets = case.get("coverage_targets", [])
    if not isinstance(coverage_targets, list):
        raise VerificationExecutionError(
            f"verification {verification_id} coverage_targets must be an array"
        )
    coverage_results = evaluate_coverage_targets(coverage_targets, evidence)
    for coverage_result in coverage_results:
        if not coverage_result.passed:
            errors.append(
                coverage_result.error
                or f"coverage target failed: {coverage_result.name}"
            )

    execution_proof = _runtime_execution_proof(
        runner_result,
        assertion_record_count=sum(
            1 for item in assertion_results if item.metric in command_metric_names
        ),
        observation_record_count=command_observation_count,
    )
    if execution_proof.error:
        errors.append(execution_proof.error)

    output, database_output_truncated = _bounded_tail(
        runner_result.output, MAX_DATABASE_OUTPUT_CHARACTERS
    )
    output_truncated = runner_result.output_truncated or database_output_truncated
    if runner_result.launch_error:
        status = RepetitionStatus.LAUNCH_ERROR
    elif runner_result.timed_out:
        status = RepetitionStatus.TIMED_OUT
    elif errors:
        status = RepetitionStatus.FAILED
    else:
        status = RepetitionStatus.PASSED
    return VerificationRepetitionResult(
        verification_id=verification_id,
        attempt=attempt,
        repetition=repetition,
        command=str(case["command"]),
        working_directory=str(case["working_directory"]),
        timeout=int(case["timeout"]),
        status=status,
        return_code=runner_result.return_code,
        output=output,
        output_truncated=output_truncated,
        metrics=metrics,
        assertion_results=tuple(assertion_results),
        evidence=tuple(evidence),
        coverage_results=coverage_results,
        execution_proof=execution_proof,
        elapsed_seconds=float(runner_result.elapsed_seconds),
        timed_out=runner_result.timed_out,
        errors=tuple(errors),
        termination_details=runner_result.termination_details,
        started_at=started_at,
        finished_at=finished_at,
    )


def run_case_attempt(
    case: Mapping[str, Any],
    worktree: str | Path,
    runner: VerificationRunner,
    *,
    attempt: int = 1,
    clock: Callable[[], str] = db.utc_now,
    persist_repetition: Callable[[VerificationRepetitionResult], int | None] | None = None,
    artifact_directory: str | Path | None = None,
    adapters: Sequence[EvidenceAdapter] = (),
) -> CaseAttemptResult:
    """Run all declared repetitions, even when an earlier repetition fails."""

    verification_id = case.get("verification_id")
    if not isinstance(verification_id, str) or not verification_id:
        raise VerificationExecutionError("verification case requires an ID")
    if case.get("automation") == "manual":
        return CaseAttemptResult(verification_id, None, "manual_pending", ())
    command = case.get("command")
    working_directory = case.get("working_directory")
    timeout = case.get("timeout")
    loop = case.get("validation_loop")
    if not isinstance(command, str) or not command.strip() or command.strip().lower() == "auto":
        raise VerificationExecutionError(
            f"verification {verification_id} has no concrete command"
        )
    if not isinstance(working_directory, str):
        raise VerificationExecutionError(
            f"verification {verification_id} working directory must be a string"
        )
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise VerificationExecutionError(
            f"verification {verification_id} timeout must be positive"
        )
    if not isinstance(loop, Mapping):
        raise VerificationExecutionError(
            f"verification {verification_id} validation loop must be an object"
        )
    repetitions = loop.get("repetitions_per_attempt")
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions <= 0:
        raise VerificationExecutionError(
            f"verification {verification_id} repetitions must be positive"
        )
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt <= 0:
        raise VerificationExecutionError("verification attempt must be positive")
    # This check protects fake/injected runners; the production runner repeats
    # it immediately before subprocess launch to defend against live symlink changes.
    validate_execution_working_directory(worktree, working_directory)

    results: list[VerificationRepetitionResult] = []
    artifact_root = None if artifact_directory is None else Path(artifact_directory).resolve()
    for repetition in range(1, repetitions + 1):
        started_at = clock()
        try:
            raw_result = runner.run(
                command=command,
                worktree=worktree,
                working_directory=working_directory,
                timeout=timeout,
            )
            runner_result = _normalized_runner_result(raw_result)
        except Exception as exc:
            runner_result = RunnerResult(
                output="",
                return_code=None,
                elapsed_seconds=0.0,
                launch_error=f"{type(exc).__name__}: {exc}",
                termination_details="runner raised before returning a command result",
            )
        finished_at = clock()
        attempt_directory = (
            None if artifact_root is None else artifact_root / f"attempt-{attempt:04d}"
        )
        evidence_directory = (
            None
            if attempt_directory is None
            else attempt_directory / f"repetition-{repetition:04d}-evidence"
        )
        retain_output = bool(loop.get("retain_evidence"))
        log_path = (
            None
            if attempt_directory is None or not retain_output
            else attempt_directory / f"repetition-{repetition:04d}.log"
        )
        result = _evaluate_repetition(
            case,
            runner_result,
            attempt=attempt,
            repetition=repetition,
            started_at=started_at,
            finished_at=finished_at,
            worktree=Path(worktree).resolve(),
            evidence_artifact_directory=evidence_directory,
            log_path=log_path,
            adapters=adapters,
        )
        if persist_repetition is not None:
            result = replace(result, record_id=persist_repetition(result))
        results.append(result)
    status = "passed" if all(item.passed for item in results) else "failed"
    return CaseAttemptResult(verification_id, attempt, status, tuple(results))


def _latest_attempt_metrics(attempt: CaseAttemptResult) -> dict[str, float]:
    for repetition in reversed(attempt.repetitions):
        if repetition.metrics is not None:
            return dict(repetition.metrics)
    return {}


def _attempt_failed_assertions(attempt: CaseAttemptResult) -> list[dict[str, Any]]:
    return [
        assertion.to_dict()
        for repetition in attempt.repetitions
        for assertion in repetition.assertion_results
        if not assertion.passed
    ]


def _attempt_evidence_paths(attempt: CaseAttemptResult) -> list[str]:
    return sorted(
        {
            str(evidence.artifact_path)
            for repetition in attempt.repetitions
            for evidence in repetition.evidence
            if evidence.artifact_path
        }
    )


def _requirement_contracts(
    manifest_payload: Mapping[str, Any], requirement_ids: Sequence[str]
) -> list[dict[str, Any]]:
    wanted = set(requirement_ids)
    return [
        {
            "requirement_id": str(item.get("requirement_id") or ""),
            "title": str(item.get("title") or ""),
            "statement": str(item.get("statement") or ""),
        }
        for item in manifest_payload.get("work_items", [])
        if isinstance(item, Mapping) and item.get("requirement_id") in wanted
    ]


def build_escalation_report(
    *,
    job_id: str,
    case: Mapping[str, Any],
    attempt: CaseAttemptResult,
    requirement_contracts: Sequence[Mapping[str, Any]],
    correction_history: Sequence[Mapping[str, Any]],
    metric_history: Sequence[Mapping[str, Any]],
    failure_analysis: FailureAnalysis,
    failed_assertions: Sequence[Mapping[str, Any]],
    evidence_paths: Sequence[str],
    attempts_completed: int,
    stagnation_count: int,
    exhausted_by: Sequence[str],
    repair_goal: str,
) -> dict[str, Any]:
    """Build a complete, domain-neutral handoff when automated bounds are hard-stopped."""

    loop = case.get("validation_loop")
    if not isinstance(loop, Mapping):
        raise VerificationExecutionError("escalation requires a validation loop")
    errors = [
        error
        for repetition in attempt.repetitions
        for error in repetition.errors
    ]
    failed_repetition = next(
        (item.repetition for item in attempt.repetitions if not item.passed), None
    )
    attempted_corrections = [
        {
            "attempt": int(item.get("attempt") or 0),
            "repair_goal": str(item.get("repair_goal") or ""),
            "fingerprint": item.get("failure_fingerprint"),
            "metric_trend": str(item.get("metric_trend") or "insufficient"),
        }
        for item in correction_history
    ]
    attempted_corrections.append(
        {
            "attempt": int(attempt.attempt or attempts_completed),
            "repair_goal": repair_goal,
            "fingerprint": failure_analysis.fingerprint,
            "metric_trend": classify_metric_trend(
                metric_history,
                [item for item in case.get("metric_assertions", []) if isinstance(item, Mapping)],
            ),
        }
    )
    all_evidence_paths = sorted(
        {
            str(path)
            for item in correction_history
            for path in item.get("evidence_paths", [])
            if path
        }
        | {str(path) for path in evidence_paths if path}
    )
    request = str(loop.get("escalation_condition") or "").strip()
    if not request:
        request = (
            "Provide the concrete decision, resource, credential, hardware access, "
            "or domain judgment required to unblock this verification."
        )
    return {
        "schema_version": "1",
        "job_id": job_id,
        "requirement_at_risk": [dict(item) for item in requirement_contracts],
        "failed_verification": {
            "verification_id": str(case.get("verification_id") or ""),
            "title": str(case.get("title") or ""),
            "blocking": bool(case.get("blocking")),
            "failed_repetition": failed_repetition,
            "failure_fingerprint": failure_analysis.fingerprint,
        },
        "observed_behavior": {
            "status": attempt.status,
            "return_codes": [item.return_code for item in attempt.repetitions],
            "failed_assertions": [dict(item) for item in failed_assertions],
            "errors": errors,
            "latest_metrics": _latest_attempt_metrics(attempt),
            "diagnostic_output_tail": failure_analysis.output_tail,
        },
        "attempted_corrections": attempted_corrections,
        "metric_history": [dict(item) for item in metric_history],
        "retained_evidence": all_evidence_paths,
        "policy_exhaustion": {
            "exhausted_by": list(exhausted_by),
            "attempts_completed": attempts_completed,
            "attempt_limit": int(loop["maximum_correction_attempts"]),
            "stagnation_count": stagnation_count,
            "stagnation_limit": int(loop["stagnation_limit"]),
        },
        "human_input_needed": {
            "request": request,
            "acceptable_input_types": [
                "decision",
                "resource",
                "credential",
                "hardware access",
                "domain judgment",
            ],
        },
    }


def _persist_correction_result(
    conn: Any,
    *,
    job_id: str,
    task_id: str,
    worker_run_id: str | None,
    case: Mapping[str, Any],
    attempt: CaseAttemptResult,
    manifest_payload: Mapping[str, Any],
    now: str,
) -> str:
    verification_id = str(case["verification_id"])
    history = db.list_verification_correction_attempts(
        conn, job_id, verification_id=verification_id
    )
    state_row = conn.execute(
        "SELECT * FROM job_verification_states WHERE job_id = ? AND verification_id = ?",
        (job_id, verification_id),
    ).fetchone()
    if state_row is None:
        raise VerificationExecutionError(
            f"formal verification state is missing for {verification_id}"
        )
    attempt_offset = int(state_row["attempt_offset"] or 0)
    history = [item for item in history if int(item["attempt"]) > attempt_offset]
    policy_attempt = max(0, int(attempt.attempt or 0) - attempt_offset)
    task = db.get_task(conn, task_id)
    repair_goal = str(task.get("goal") or "")
    metrics = _latest_attempt_metrics(attempt)
    metric_history = [dict(item.get("metric_values") or {}) for item in history]
    metric_history.append(metrics)
    assertions = [
        item for item in case.get("metric_assertions", []) if isinstance(item, Mapping)
    ]
    metric_trend = classify_metric_trend(metric_history, assertions)
    failed_assertions = _attempt_failed_assertions(attempt)
    evidence_paths = _attempt_evidence_paths(attempt)
    combined_output = "\n".join(item.output for item in attempt.repetitions)
    errors = [error for item in attempt.repetitions for error in item.errors]
    previous_identity = next(
        (
            item.get("failure_identity")
            for item in reversed(history)
            if item.get("status") != "passed" and item.get("failure_identity") is not None
        ),
        None,
    )
    max_series = max((int(item.get("stagnation_series") or 0) for item in history), default=0)
    failure_analysis: FailureAnalysis | None = None
    meaningful_change = False
    escalation_report: dict[str, Any] | None = None
    if attempt.passed:
        status = RealizationState.PASSING.value
        consecutive_failures = 0
        stagnation_count = 0
        stagnation_series = 0
        failure_fingerprint = None
        failure_identity = None
        finished_at = now
    else:
        failure_analysis = analyze_failure(
            return_codes=[item.return_code for item in attempt.repetitions],
            failed_assertions=failed_assertions,
            errors=errors,
            selected_metrics=metrics,
            output=combined_output,
        )
        failure_fingerprint = failure_analysis.fingerprint
        failure_identity = failure_analysis.identity
        meaningful_change = previous_identity is not None and previous_identity != failure_identity
        previous_consecutive = int(state_row["consecutive_failures"] or 0)
        previous_series = int(state_row["stagnation_series"] or 0)
        if previous_consecutive == 0 or previous_series == 0 or meaningful_change:
            stagnation_series = max_series + 1
            stagnation_count = 0
        elif metric_trend == "improving":
            stagnation_series = previous_series
            stagnation_count = 0
        else:
            stagnation_series = previous_series
            stagnation_count = int(state_row["stagnation_count"] or 0) + 1
        consecutive_failures = previous_consecutive + 1
        loop = case["validation_loop"]
        attempt_exhausted = policy_attempt >= int(loop["maximum_correction_attempts"])
        stagnation_exhausted = stagnation_count >= int(loop["stagnation_limit"])
        exhausted_by = [
            name
            for name, exhausted in (
                ("attempt_limit", attempt_exhausted),
                ("stagnation_limit", stagnation_exhausted),
            )
            if exhausted
        ]
        if exhausted_by and bool(case.get("blocking")):
            status = RealizationState.ESCALATED.value
            escalation_report = build_escalation_report(
                job_id=job_id,
                case=case,
                attempt=attempt,
                requirement_contracts=_requirement_contracts(
                    manifest_payload, list(case.get("requirement_ids") or [])
                ),
                correction_history=history,
                metric_history=metric_history,
                failure_analysis=failure_analysis,
                failed_assertions=failed_assertions,
                evidence_paths=evidence_paths,
                attempts_completed=policy_attempt,
                stagnation_count=stagnation_count,
                exhausted_by=exhausted_by,
                repair_goal=repair_goal,
            )
            finished_at = now
        elif exhausted_by:
            status = RealizationState.STAGNATED.value
            finished_at = now
        else:
            status = RealizationState.EXECUTABLE_BUT_FAILING.value
            finished_at = None
    db.create_verification_correction_attempt(
        conn,
        job_id=job_id,
        task_id=task_id,
        worker_run_id=worker_run_id,
        verification_id=verification_id,
        attempt=int(attempt.attempt or 0),
        status=status,
        failure_fingerprint=failure_fingerprint,
        failure_identity=failure_identity,
        metric_values=metrics,
        metric_trend=metric_trend,
        consecutive_failures=consecutive_failures,
        stagnation_count=stagnation_count,
        stagnation_series=stagnation_series,
        meaningful_change=meaningful_change,
        failed_assertions=failed_assertions,
        observed_error="; ".join(errors) or None,
        output_tail="" if failure_analysis is None else failure_analysis.output_tail,
        evidence_paths=evidence_paths,
        repair_goal=repair_goal,
        escalation_report=escalation_report,
        created_at=now,
    )
    conn.execute(
        """
        UPDATE job_verification_states SET
            status = ?, attempts_completed = ?, consecutive_failures = ?,
            stagnation_count = ?, stagnation_series = ?, failure_fingerprint = ?,
            latest_metrics_json = ?, metric_trend = ?, last_error = ?,
            last_task_id = ?, last_worker_run_id = ?, finished_at = ?,
            escalation_report_json = ?, updated_at = ?
        WHERE job_id = ? AND verification_id = ? AND automation != 'manual'
        """,
        (
            status,
            policy_attempt,
            consecutive_failures,
            stagnation_count,
            stagnation_series,
            failure_fingerprint,
            db.to_json(metrics) if metrics else None,
            metric_trend,
            "; ".join(errors) or None,
            task_id,
            worker_run_id,
            finished_at,
            None if escalation_report is None else db.to_json(escalation_report),
            now,
            job_id,
            verification_id,
        ),
    )
    return status


def run_task_verification(
    db_path: str | Path,
    job_id: str,
    task_id: str,
    manifest: Any | None,
    runner: VerificationRunner,
    *,
    worker_run_id: str | None = None,
    clock: Callable[[], str] = db.utc_now,
    adapters: Sequence[EvidenceAdapter] | None = None,
) -> tuple[CaseAttemptResult, ...]:
    """Execute and persist selected formal cases; Quick Goal is a strict no-op."""

    if adapters is None:
        from ai_loop.evidence_adapters import load_evidence_adapters

        def audit_adapter(item: Any) -> None:
            with db.transaction(db_path) as audit_conn:
                db.add_event(
                    audit_conn,
                    job_id=job_id,
                    kind="evidence_adapter_error",
                    payload=item.to_dict(),
                )

        adapters = load_evidence_adapters(audit=audit_adapter).adapters

    with db.transaction(db_path) as conn:
        job = db.get_job(conn, job_id)
        task = db.get_task(conn, task_id)
        if task["job_id"] != job_id:
            raise VerificationExecutionError("verification task belongs to a different job")
        if worker_run_id is not None:
            worker_run = db.get_run(conn, worker_run_id)
            if (
                worker_run["job_id"] != job_id
                or worker_run["task_id"] != task_id
            ):
                raise VerificationExecutionError(
                    "verification worker run belongs to a different job or task"
                )
        formal = job.get("specification_id") is not None
        if not formal:
            selected = select_task_verification_cases(None, task)
            if manifest is not None:
                raise VerificationExecutionError(
                    "Quick Goal jobs cannot receive a verification manifest"
                )
            state_count = conn.execute(
                "SELECT COUNT(*) FROM job_verification_states WHERE job_id = ?", (job_id,)
            ).fetchone()[0]
            repetition_count = conn.execute(
                "SELECT COUNT(*) FROM verification_repetitions WHERE job_id = ?", (job_id,)
            ).fetchone()[0]
            if state_count or repetition_count:
                raise VerificationExecutionError(
                    "Quick Goal job unexpectedly has formal verification runtime state"
                )
            return selected
        if manifest is None:
            raise VerificationExecutionError("formal task verification requires its manifest")
        if job.get("specification_version") is None or job.get("specification_content_hash") is None:
            raise VerificationExecutionError("formal job has an incomplete specification pin")
        manifest_row = db.active_verification_manifest_row(conn, job_id)
        if manifest_row is None:
            raise VerificationExecutionError("formal task verification requires a persisted manifest")
        if canonical_json(_manifest_payload(manifest)) != manifest_row["canonical_json"]:
            raise VerificationExecutionError(
                "runtime verification manifest differs from the persisted immutable manifest"
            )
        selected = select_task_verification_cases(manifest, task)

    results: list[CaseAttemptResult] = []
    for case in selected:
        if case.get("automation") == "manual":
            results.append(
                CaseAttemptResult(str(case["verification_id"]), None, "manual_pending", ())
            )
            continue
        verification_id = str(case["verification_id"])
        with db.transaction(db_path) as conn:
            attempt = db.next_verification_attempt(conn, job_id, verification_id)
            state_row = conn.execute(
                """
                SELECT status, blocking, stagnation_count, attempt_offset
                FROM job_verification_states
                WHERE job_id = ? AND verification_id = ?
                """,
                (job_id, verification_id),
            ).fetchone()
            if state_row is None:
                raise VerificationExecutionError(
                    f"formal verification state is missing for {verification_id}"
                )
            loop = case.get("validation_loop")
            if not isinstance(loop, Mapping):
                raise VerificationExecutionError(
                    f"verification {verification_id} validation loop must be an object"
                )
            if bool(state_row["blocking"]) and (
                state_row["status"] == RealizationState.ESCALATED.value
                or attempt - int(state_row["attempt_offset"] or 0)
                > int(loop["maximum_correction_attempts"])
                or int(state_row["stagnation_count"] or 0) >= int(loop["stagnation_limit"])
            ):
                raise VerificationExecutionError(
                    f"blocking verification {verification_id} exhausted its correction "
                    "policy and requires HUMAN_NEEDED"
                )

        def persist(result: VerificationRepetitionResult) -> int:
            with db.transaction(db_path) as conn:
                return db.create_verification_repetition(
                    conn,
                    job_id=job_id,
                    task_id=task_id,
                    worker_run_id=worker_run_id,
                    verification_id=result.verification_id,
                    attempt=result.attempt,
                    repetition=result.repetition,
                    command=result.command,
                    working_directory=result.working_directory,
                    timeout_seconds=result.timeout,
                    status=result.status.value,
                    return_code=result.return_code,
                    output=result.output,
                    output_truncated=result.output_truncated,
                    metrics=result.metrics,
                    assertion_results=[item.to_dict() for item in result.assertion_results],
                    evidence=[item.to_dict() for item in result.evidence],
                    coverage_results=[item.to_dict() for item in result.coverage_results],
                    execution_proof=result.execution_proof.to_dict(),
                    elapsed_seconds=result.elapsed_seconds,
                    timed_out=result.timed_out,
                    error="; ".join(result.errors) or None,
                    termination_details=result.termination_details,
                    started_at=result.started_at,
                    finished_at=result.finished_at,
                )

        attempt_result = run_case_attempt(
            case,
            str(job["worktree_path"]),
            runner,
            attempt=attempt,
            clock=clock,
            persist_repetition=persist,
            artifact_directory=(
                Path(str(manifest_row["artifact_path"])).parent.parent
                / "verification"
                / verification_id
            ),
            adapters=adapters,
        )
        with db.transaction(db_path) as conn:
            _persist_correction_result(
                conn,
                job_id=job_id,
                task_id=task_id,
                worker_run_id=worker_run_id,
                case=case,
                attempt=attempt_result,
                manifest_payload=_manifest_payload(manifest),
                now=clock(),
            )
        results.append(attempt_result)
    return tuple(results)


from ai_loop.verification_dashboard import (
    build_verification_dashboard_projection,
    load_verification_dashboard_projection,
    record_manual_verification_acknowledgement,
    shape_dashboard_evidence,
)

__all__ = [
    "AUTOMATED_REALIZATION_STATES",
    "AssertionResult",
    "CaseAttemptResult",
    "CompletionGate",
    "FailureAnalysis",
    "CoverageResult",
    "EvidenceAdapter",
    "EvidenceAdapterResult",
    "EvidenceArtifact",
    "MAX_DATABASE_OUTPUT_CHARACTERS",
    "MAX_EVIDENCE_ARTIFACT_BYTES",
    "MAX_EVIDENCE_PREVIEW_CHARACTERS",
    "MAX_INLINE_EVIDENCE_BYTES",
    "MAX_FAILURE_OUTPUT_TAIL_CHARACTERS",
    "MAX_METRIC_SCAN_CHARACTERS",
    "VERIFICATION_DASHBOARD_ENFORCEMENT",
    "RealizationCheck",
    "RealizationSignals",
    "RealizationState",
    "RepetitionStatus",
    "RunnerResult",
    "RuntimeExecutionProof",
    "SubprocessVerificationRunner",
    "VerificationExecutionError",
    "VerificationRepetitionResult",
    "VerificationRunner",
    "check_manifest_realization",
    "build_runtime_verification_summary",
    "build_verification_dashboard_projection",
    "build_escalation_report",
    "classify_metric_trend",
    "compute_failure_fingerprint",
    "discover_realization_signals",
    "evaluate_metric_assertion",
    "evaluate_coverage_targets",
    "evaluate_completion_gate",
    "parse_numeric_metrics",
    "parse_structured_evidence",
    "persist_realization_checks",
    "refresh_job_realization",
    "load_verification_dashboard_projection",
    "record_manual_verification_acknowledgement",
    "resolve_command",
    "run_case_attempt",
    "run_task_verification",
    "select_task_verification_cases",
    "shape_dashboard_evidence",
    "transition_realization_state",
    "validate_execution_working_directory",
]
