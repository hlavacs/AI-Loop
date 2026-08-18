"""Tk presenter for the formal-specification draft workflow.

The module deliberately keeps conversion and parsing helpers independent of
Tk so they can be imported and tested on machines without a display.  The
authoritative persistence, validation, integrity, and lifecycle rules remain
in :mod:`ai_loop.specifications` and :mod:`ai_loop.specification_workflow`.
"""

from __future__ import annotations

import copy
import difflib
import json
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

try:  # Importing this module must remain safe in headless/minimal environments.
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except (ImportError, RuntimeError):  # pragma: no cover - platform dependent
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    filedialog = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]

from ai_loop.elicitation import (
    CompletedElicitation,
    DecisionProposal,
    ElicitationEngine,
    StructuredOutputProvider,
    apply_elicitation_analysis,
)
from ai_loop.specification_workflow import (
    EDITOR_STAGES,
    StageAssessment,
    WorkflowIssue,
    approve,
    assess_specification,
    create_draft,
    return_to_draft,
    save_draft,
    submit_for_review,
)
from ai_loop.specifications import (
    AutomationLevel,
    MetricAssertion,
    RequirementCategory,
    RequirementPriority,
    RiskSeverity,
    RiskUncertainty,
    SpecificationDocument,
    SpecificationService,
    StoredSpecificationVersion,
    TestLevel,
    VerificationMethod,
)


METRIC_EXPRESSION_RE = re.compile(
    r"^(?P<name>\S+)\s+(?P<operator><=|>=|==|!=|<|>)\s+"
    r"(?P<threshold>\S+)(?:\s+(?P<tolerance>\S+))?$"
)

SPECIFICATION_SAVEFILE_SCHEMA = "ai-loop/specification-draft"
SPECIFICATION_SAVEFILE_VERSION = 1

PROCESS_OVERVIEW_TEXT = (
    "How ai-loop turns this specification into verified work:\n"
    "1. Author the specification and use elicitation to clarify gaps.  "
    "2. Save the draft and submit it for review.  "
    "3. Resolve Review issues and choices, then approve the exact version.  "
    "4. Click Start Implementation; ai-loop pins the approved version and enqueues a PLAN.  "
    "5. A worker implements the planned requirements.  "
    "6. Verification runs the linked cases and records runtime proof that the intended cases executed.  "
    "7. The controller reaches DONE only after every blocking completion gate passes."
)


SPECIFICATION_FIELD_GUIDANCE = {
    "title": (
        "A short name for this deliverable. It identifies the draft during review and the exact "
        "approved version later pinned to implementation."
    ),
    "summary": (
        "Explain the user problem and desired result in plain language. The controller uses this "
        "context when turning approved requirements into a PLAN."
    ),
    "objectives": (
        "List measurable outcomes, one per line. Requirements should realize these outcomes and "
        "verification cases should prove them."
    ),
    "stakeholders": (
        "Name the people or roles affected, one per line. Use cases identify how these actors "
        "interact with the result and whose expectations require verification."
    ),
    "in_scope": (
        "State what the worker is expected to implement, one boundary per line. Requirements must "
        "stay inside this boundary."
    ),
    "out_of_scope": (
        "State what this delivery intentionally excludes. This prevents the PLAN and completion "
        "review from treating excluded work as missing."
    ),
    "assumptions": (
        "Record facts treated as true, one per line. Turn uncertain or failure-prone assumptions "
        "into risks or verification fixtures."
    ),
    "constraints": (
        "Record non-negotiable technical, policy, or schedule limits. Requirements and the worker's "
        "implementation must honor them."
    ),
    "dependencies": (
        "List external systems, libraries, data, or teams needed for delivery. Verification fixtures "
        "should make those dependencies reproducible."
    ),
    "use_cases": (
        "Describe complete user journeys. Link every journey to requirement IDs so review can trace "
        "user behavior to implementation work and verification coverage."
    ),
    "requirements": (
        "Define the implementation contract. Stable IDs connect use cases, risks, and verification; "
        "mandatory and high-risk work needs blocking automated coverage before DONE."
    ),
    "risks": (
        "Describe credible failures and mitigations. High-severity or high-uncertainty risks must "
        "link to verification with metrics, retained evidence, and a bounded correction loop."
    ),
    "verification": (
        "Define how linked requirements are proven. Blocking automated cases gate completion and "
        "must produce runtime evidence that the intended procedure actually executed."
    ),
    "decisions": (
        "Record choices already made and their trade-offs. Decisions constrain requirements and "
        "keep the controller from silently choosing a different design."
    ),
    "open_questions": (
        "List unresolved questions, one per line. They appear in Review and must be resolved or "
        "explicitly deferred before approval."
    ),
    "use_cases.id": "A stable uppercase ID such as UC1; requirement and review traceability refer to it.",
    "use_cases.title": "A concise name for the user journey and the behavior it demonstrates.",
    "use_cases.actors": "One actor or role per line; these should come from, or refine, Stakeholders.",
    "use_cases.preconditions": "One required starting state per line so tests can establish the scenario.",
    "use_cases.trigger": "The event that starts this journey and the corresponding verification scenario.",
    "use_cases.main_flow": "One ordered success step per line; requirements describe what implements these steps.",
    "use_cases.alternate_flows": "One valid variation per line so expected alternatives are not treated as failures.",
    "use_cases.postconditions": "One observable final state per line; these become useful test oracles.",
    "use_cases.error_and_edge_cases": "One failure or boundary behavior per line to cover in risks or verification.",
    "use_cases.requirement_ids": "One linked requirement ID per line; links provide journey-to-test traceability.",
    "requirements.id": "A stable uppercase ID such as R1, used by use cases, risks, evidence, and verification.",
    "requirements.category": "Classify the contract; approval requires both functional and quality requirements.",
    "requirements.priority": "Must items are mandatory completion work; should/could express lower priority.",
    "requirements.title": "A concise, unique description of the capability or quality contract.",
    "requirements.statement": "Write one unambiguous normative statement describing what the result shall do.",
    "requirements.rationale": "Explain why the contract matters and which objective or stakeholder it supports.",
    "requirements.acceptance_criteria": "One measurable outcome per line; verification cases must prove these outcomes.",
    "requirements.source": "Name the stakeholder, policy, issue, or other authority behind the requirement.",
    "risks.id": "A stable uppercase ID such as RISK1 for review and verification traceability.",
    "risks.title": "A concise name for the uncertain failure that needs mitigation.",
    "risks.description": "Explain the cause, affected requirement or dependency, and likely impact.",
    "risks.severity": "Rate impact; high and critical risks trigger stronger automated completion gates.",
    "risks.uncertainty": "Rate confidence in the risk; high uncertainty also triggers stronger verification.",
    "risks.failure_modes": "One concrete way the system could fail per line.",
    "risks.detection_signals": "One observable log, metric, state, or symptom per line for runtime detection.",
    "risks.mitigations": "One prevention or recovery measure per line; requirements should implement them.",
    "risks.verification_ids": "One verification ID per line showing which runtime proof covers this risk.",
    "decisions.topic": "The stable subject of the decision, such as retry policy or storage format.",
    "decisions.selected_decision": "State the chosen option precisely enough to constrain implementation.",
    "decisions.rationale": "Explain why the chosen option best satisfies objectives, constraints, and risks.",
    "decisions.rejected_alternatives": "One considered alternative per line so review preserves the trade-off.",
    "decisions.consequences": "One expected benefit, cost, or follow-up constraint per line.",
    "verification.id": "A stable uppercase ID such as VT1, linked from risks and runtime evidence.",
    "verification.title": "Name the behavior or quality this case proves.",
    "verification.requirement_ids": "One requirement ID per line; every requirement needs at least one linked case.",
    "verification.test_level": "Choose where the proof runs, from unit through system, performance, or visual testing.",
    "verification.method": "Choose how results are judged; deterministic cases compare against a fixed oracle.",
    "verification.oracle": "Describe the independent expected result used to decide pass or fail.",
    "verification.fixtures": "One reproducible input, state, stub, or dataset per line.",
    "verification.procedure": "One ordered execution step per line; runtime proof must show this case executed.",
    "verification.pass_criteria": "One observable pass condition per line, tied to acceptance criteria.",
    "verification.declared_metrics": "One emitted metric name per line; assertions may reference only these names.",
    "verification.metric_assertions": "One 'name operator threshold [tolerance]' gate per line, for example sent == 1.",
    "verification.coverage_targets": "One scenario or coverage target per line showing what this case exercises.",
    "verification.required_evidence": "One required log, report, or structured proof per line for completion review.",
    "verification.automation": "Automated cases can gate autonomous completion; manual cases cannot be blocking.",
    "verification.blocking": "When selected, the controller cannot reach DONE until trusted runtime proof passes.",
    "verification.command_override": "Optional command for this case; otherwise the job's normal test command is used.",
    "verification.working_directory": "Repository-relative directory in which the isolated verification command runs.",
    "verification.timeout": "Maximum runtime in seconds before this verification attempt fails safely.",
    "verification.maximum_correction_attempts": "Maximum implementation/verification correction cycles before escalation.",
    "verification.repetitions_per_attempt": "Runs per attempt; repeated runs help expose flaky or high-risk behavior.",
    "verification.stagnation_limit": "Consecutive attempts without improvement before the loop escalates.",
    "verification.escalation_condition": "Explain when the bounded loop stops and requires human attention.",
    "verification.retain_evidence": "Keep attempt evidence so review can audit execution and the final completion gate.",
}

SPECIFICATION_FIELD_EXAMPLES = {
    "title": "Reliable appointment reminders",
    "summary": "Send one reminder 24 hours before an appointment and prove retries cannot send duplicates.",
    "objectives": "Reduce missed appointments with timely reminders",
    "stakeholders": "Patients receiving reminders",
    "in_scope": "Schedule and send email reminders for confirmed appointments",
    "out_of_scope": "SMS and push notifications",
    "assumptions": "Appointment timestamps and email addresses are already validated",
    "constraints": "Never send more than one reminder for the same appointment",
    "dependencies": "Email gateway test double",
    "use_cases": "UC1 — A scheduled worker sends one due reminder and stores its receipt",
    "requirements": "R2 — Reprocessing the same appointment shall not send a duplicate reminder",
    "risks": "RISK1 — A retry after an ambiguous gateway response sends a duplicate",
    "verification": "VT1 — Run the same reminder three times and assert notifications_sent == 1",
    "decisions": "Reminder idempotency key — use appointment ID plus reminder-window date",
    "open_questions": "Should a later release add SMS as a separate optional requirement?",
    "use_cases.id": "UC1",
    "use_cases.title": "Send a due appointment reminder",
    "use_cases.actors": "Patient\nReminder worker",
    "use_cases.preconditions": "A confirmed appointment is due in 24 hours\nNo reminder receipt exists",
    "use_cases.trigger": "The scheduled worker scans due appointments",
    "use_cases.main_flow": "Load due appointments\nSend the email\nStore one delivery receipt",
    "use_cases.alternate_flows": "Skip an appointment that already has a successful receipt",
    "use_cases.postconditions": "One email is sent and one auditable receipt is stored",
    "use_cases.error_and_edge_cases": "A gateway failure stores a failed attempt without a success receipt",
    "use_cases.requirement_ids": "R1\nR2",
    "requirements.id": "R2",
    "requirements.category": "quality",
    "requirements.priority": "must",
    "requirements.title": "Prevent duplicate reminders",
    "requirements.statement": "The worker shall remain idempotent when the same appointment is processed repeatedly.",
    "requirements.rationale": "Duplicate reminders confuse patients and erode trust.",
    "requirements.acceptance_criteria": "Three repeated scans send one email and store one success receipt",
    "requirements.source": "Patient support policy",
    "risks.id": "RISK1",
    "risks.title": "Duplicate reminder delivery",
    "risks.description": "A retry after an ambiguous response could send a second email.",
    "risks.severity": "high",
    "risks.uncertainty": "medium",
    "risks.failure_modes": "The gateway accepts an email before the worker records its receipt",
    "risks.detection_signals": "duplicate_notifications is greater than zero",
    "risks.mitigations": "Enforce a persistent unique idempotency key before delivery",
    "risks.verification_ids": "VT1",
    "decisions.topic": "Reminder idempotency key",
    "decisions.selected_decision": "Use appointment ID plus reminder-window date",
    "decisions.rationale": "The key is deterministic across retries.",
    "decisions.rejected_alternatives": "Use a process-local in-memory sent set",
    "decisions.consequences": "Delivery receipts need a persistent unique-key constraint",
    "verification.id": "VT1",
    "verification.title": "Due reminder retry remains idempotent",
    "verification.requirement_ids": "R1\nR2",
    "verification.test_level": "integration",
    "verification.method": "deterministic",
    "verification.oracle": "The outbox and receipt store each contain exactly one matching record.",
    "verification.fixtures": "One confirmed appointment due in 24 hours\nA deterministic email gateway",
    "verification.procedure": "Run the scan three times\nRead the outbox and receipts\nEmit the VT1 marker and metrics",
    "verification.pass_criteria": "Exactly one email and one success receipt exist after all scans",
    "verification.declared_metrics": "notifications_sent\nduplicate_notifications",
    "verification.metric_assertions": "notifications_sent == 1 0\nduplicate_notifications == 0 0",
    "verification.coverage_targets": "Due-reminder success and repeated-scan idempotency paths",
    "verification.required_evidence": "VT1 execution marker, emitted metrics, test log, and receipt snapshot",
    "verification.automation": "automated",
    "verification.blocking": "selected",
    "verification.command_override": "python -m pytest -q tests/test_appointment_reminders.py",
    "verification.working_directory": ".",
    "verification.timeout": "60",
    "verification.maximum_correction_attempts": "2",
    "verification.repetitions_per_attempt": "3",
    "verification.stagnation_limit": "1",
    "verification.escalation_condition": "Escalate when duplicate delivery persists after two corrections",
    "verification.retain_evidence": "selected",
}


def _field_guidance(path: str) -> str:
    """Return permanent inline help plus a concrete value for one input."""

    return f"{SPECIFICATION_FIELD_GUIDANCE[path]}\nExample: {SPECIFICATION_FIELD_EXAMPLES[path]}"


class MetricAssertionParseError(ValueError):
    """A metric expression error carrying its one-based source line."""

    def __init__(self, line_number: int, message: str):
        self.line_number = line_number
        self.detail = message
        super().__init__(f"line {line_number}: {message}")


class StructuredRecordParseError(ValueError):
    """A structured-list error carrying its one-based source line."""

    def __init__(self, line_number: int, message: str):
        self.line_number = line_number
        self.detail = message
        super().__init__(f"line {line_number}: {message}")


class SpecificationSavefileError(ValueError):
    """Raised when an imported specification save file is not compatible."""


def parse_list_text(value: str) -> tuple[str, ...]:
    """Return one exact item per non-empty line, stripping only line endings."""

    return tuple(line for line in value.splitlines() if line != "")


def format_list_text(values: Iterable[str]) -> str:
    return "\n".join(values)


def parse_structured_records(value: str) -> tuple[str | dict[str, Any], ...]:
    """Parse one descriptive string or JSON object per non-empty line."""

    records: list[str | dict[str, Any]] = []
    for line_number, raw_line in enumerate(value.splitlines(), 1):
        if raw_line == "":
            continue
        candidate = raw_line.strip()
        if not candidate.startswith(("{", '"')):
            records.append(raw_line)
            continue
        try:
            parsed = json.loads(raw_line)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise StructuredRecordParseError(
                line_number,
                f"expected a valid JSON object or descriptive text: {exc}",
            ) from exc
        if not isinstance(parsed, (str, dict)):
            raise StructuredRecordParseError(
                line_number, "expected a JSON object or descriptive string"
            )
        records.append(parsed)
    return tuple(records)


def format_structured_records(values: Iterable[str | Mapping[str, Any]]) -> str:
    """Render mixed prose/structured records without dropping object fields."""

    lines: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            lines.append(
                json.dumps(
                    dict(value),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                )
            )
            continue
        if not isinstance(value, str):
            raise TypeError("structured record must be a string or object")
        stripped = value.strip()
        if (
            any(character in value for character in "\r\n")
            or not stripped
            or stripped.startswith(("{", '"'))
        ):
            lines.append(json.dumps(value, ensure_ascii=False))
        else:
            lines.append(value)
    return "\n".join(lines)


def _parse_finite_number(token: str, *, line_number: int, field: str) -> int | float:
    try:
        value = float(token)
    except ValueError as exc:
        raise MetricAssertionParseError(
            line_number, f"{field} must be a finite number; got {token!r}"
        ) from exc
    if not math.isfinite(value):
        raise MetricAssertionParseError(
            line_number, f"{field} must be finite; got {token!r}"
        )
    return int(value) if value.is_integer() else value


def parse_metric_assertions(value: str) -> tuple[MetricAssertion, ...]:
    """Parse ``name operator threshold [tolerance]`` expressions.

    Blank lines are ignored.  Every failure identifies the exact one-based
    line so a record dialog can direct the user to the source expression.
    Structural validation still remains authoritative after parsing.
    """

    assertions: list[MetricAssertion] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(value.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        match = METRIC_EXPRESSION_RE.fullmatch(line)
        if match is None:
            raise MetricAssertionParseError(
                line_number,
                "expected: name operator threshold [tolerance]",
            )
        name = match.group("name")
        if name in seen:
            raise MetricAssertionParseError(
                line_number, f"metric {name!r} already has an assertion in this case"
            )
        threshold = _parse_finite_number(
            match.group("threshold"), line_number=line_number, field="threshold"
        )
        tolerance_token = match.group("tolerance")
        tolerance = (
            None
            if tolerance_token is None
            else _parse_finite_number(
                tolerance_token, line_number=line_number, field="tolerance"
            )
        )
        if tolerance is not None and tolerance < 0:
            raise MetricAssertionParseError(line_number, "tolerance must be non-negative")
        assertions.append(
            MetricAssertion(
                metric=name,
                operator=match.group("operator"),
                threshold=threshold,
                tolerance=tolerance,
            )
        )
        seen.add(name)
    return tuple(assertions)


def format_metric_assertions(assertions: Iterable[MetricAssertion | Mapping[str, Any]]) -> str:
    lines: list[str] = []
    for assertion in assertions:
        if isinstance(assertion, Mapping):
            metric = assertion["metric"]
            operator = assertion["operator"]
            threshold = assertion["threshold"]
            tolerance = assertion.get("tolerance")
        else:
            metric = assertion.metric
            operator = assertion.operator
            threshold = assertion.threshold
            tolerance = assertion.tolerance
        line = f"{metric} {operator} {threshold}"
        if tolerance is not None:
            line += f" {tolerance}"
        lines.append(line)
    return "\n".join(lines)


def document_to_record(document: SpecificationDocument) -> dict[str, Any]:
    """Create an editable deep copy without rewriting any authored content."""

    return copy.deepcopy(document.to_dict())


def record_to_document(
    record: Mapping[str, Any], *, worktree: str | Path | None = None
) -> SpecificationDocument:
    """Convert an editor record through the strict authoritative model parser."""

    return SpecificationDocument.from_dict(copy.deepcopy(dict(record)), worktree=worktree)


def specification_to_savefile_bytes(record: Mapping[str, Any]) -> bytes:
    """Serialize an editable specification record in a versioned JSON envelope."""

    envelope = {
        "schema": SPECIFICATION_SAVEFILE_SCHEMA,
        "version": SPECIFICATION_SAVEFILE_VERSION,
        "specification": copy.deepcopy(dict(record)),
    }
    try:
        return (
            json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SpecificationSavefileError(
            f"Specification record cannot be saved as JSON: {exc}"
        ) from exc


def savefile_to_record(content: bytes | bytearray | str) -> dict[str, Any]:
    """Load an editable record from a compatible specification save file."""

    try:
        text = bytes(content).decode("utf-8") if not isinstance(content, str) else content
    except UnicodeDecodeError as exc:
        raise SpecificationSavefileError(
            "Specification file must be UTF-8 encoded JSON"
        ) from exc
    try:
        envelope = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SpecificationSavefileError(f"Malformed specification JSON: {exc}") from exc
    if not isinstance(envelope, Mapping):
        raise SpecificationSavefileError("Specification file must contain a JSON object")
    schema = envelope.get("schema")
    if schema != SPECIFICATION_SAVEFILE_SCHEMA:
        raise SpecificationSavefileError(
            "Incompatible specification file schema: "
            f"expected {SPECIFICATION_SAVEFILE_SCHEMA!r}, got {schema!r}"
        )
    version = envelope.get("version")
    if version != SPECIFICATION_SAVEFILE_VERSION or isinstance(version, bool):
        raise SpecificationSavefileError(
            "Unsupported specification file version: "
            f"expected {SPECIFICATION_SAVEFILE_VERSION}, got {version!r}"
        )
    record = envelope.get("specification")
    if not isinstance(record, Mapping):
        raise SpecificationSavefileError(
            "Specification file field 'specification' must contain a JSON object"
        )
    template = SpecificationDocument.empty().to_dict()
    missing = sorted(set(template) - set(record))
    unexpected = sorted(set(record) - set(template))
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected fields: {', '.join(unexpected)}")
        raise SpecificationSavefileError(
            "Specification file has an incompatible editable shape ("
            + "; ".join(details)
            + ")"
        )
    for key, default in template.items():
        value = record[key]
        if isinstance(default, str) and not isinstance(value, str):
            raise SpecificationSavefileError(
                f"Specification file field {key!r} must contain text"
            )
        if isinstance(default, list) and not isinstance(value, list):
            raise SpecificationSavefileError(
                f"Specification file field {key!r} must contain a list"
            )
    for key in ("objectives", "in_scope", "out_of_scope", "stakeholders", "assumptions", "constraints", "dependencies", "open_questions"):
        if not all(isinstance(item, str) for item in record[key]):
            raise SpecificationSavefileError(
                f"Specification file field {key!r} must contain only text items"
            )
    for key in ("use_cases", "requirements", "decisions", "risks", "verification"):
        if not all(isinstance(item, Mapping) for item in record[key]):
            raise SpecificationSavefileError(
                f"Specification file field {key!r} must contain only record objects"
            )
    return copy.deepcopy(dict(record))


def worked_example_document(
    *, worktree: str | Path | None = None
) -> SpecificationDocument:
    """Return one coherent editable example accepted by the authoritative parser."""

    payload = SpecificationDocument.empty().to_dict()
    payload.update(
        {
            "title": "Reliable appointment reminders",
            "summary": (
                "Add an appointment-reminder service that sends one email 24 hours before an "
                "appointment and records enough evidence to prove duplicate reminders are prevented."
            ),
            "objectives": [
                "Reduce missed appointments with timely reminders",
                "Prevent duplicate notifications while retaining an auditable delivery record",
            ],
            "in_scope": [
                "Schedule and send email reminders for confirmed appointments",
                "Record delivery outcomes and idempotency decisions",
            ],
            "out_of_scope": [
                "SMS and push notifications",
                "Changes to appointment booking or cancellation",
            ],
            "stakeholders": [
                "Patients receiving reminders",
                "Clinic staff monitoring delivery",
            ],
            "assumptions": [
                "Appointment timestamps and recipient email addresses are already validated",
            ],
            "constraints": [
                "Do not send more than one reminder for the same appointment",
                "Use the repository's existing email gateway abstraction",
            ],
            "dependencies": [
                "Appointment data store",
                "Email gateway test double",
            ],
            "use_cases": [
                {
                    "id": "UC1",
                    "title": "Send a due appointment reminder",
                    "actors": ["Patient", "Reminder worker"],
                    "preconditions": [
                        "A confirmed appointment is due in 24 hours",
                        "No reminder receipt exists for the appointment",
                    ],
                    "trigger": "The scheduled reminder worker scans due appointments",
                    "main_flow": [
                        "Load due appointments",
                        "Send the reminder through the email gateway",
                        "Store one successful reminder receipt",
                    ],
                    "alternate_flows": [
                        "Skip an appointment that already has a successful reminder receipt",
                    ],
                    "postconditions": [
                        "The patient receives one reminder and an auditable receipt is stored",
                    ],
                    "error_and_edge_cases": [
                        "A gateway failure stores a failed attempt without a successful receipt",
                    ],
                    "requirement_ids": ["R1", "R2"],
                }
            ],
            "requirements": [
                {
                    "id": "R1",
                    "category": "functional",
                    "priority": "must",
                    "title": "Send due reminders",
                    "statement": (
                        "The reminder worker shall send an email for each confirmed appointment "
                        "that becomes due within the 24-hour reminder window."
                    ),
                    "rationale": "Timely reminders reduce missed appointments.",
                    "acceptance_criteria": [
                        "A due appointment causes exactly one email to be sent",
                    ],
                    "source": "Clinic operations owner",
                },
                {
                    "id": "R2",
                    "category": "quality",
                    "priority": "must",
                    "title": "Prevent duplicate reminders",
                    "statement": (
                        "The reminder worker shall remain idempotent when the same due appointment "
                        "is processed repeatedly."
                    ),
                    "rationale": "Duplicate reminders confuse patients and erode trust.",
                    "acceptance_criteria": [
                        "Three repeated scans produce one successful delivery receipt and no duplicate email",
                    ],
                    "source": "Patient support policy",
                },
            ],
            "decisions": [
                {
                    "topic": "Reminder idempotency key",
                    "selected_decision": "Use the appointment ID plus reminder-window date",
                    "rationale": "The key is deterministic across retries and changes for later reminders.",
                    "rejected_alternatives": ["Use a process-local in-memory sent set"],
                    "consequences": [
                        "Delivery receipts require a unique persistent idempotency-key constraint",
                    ],
                }
            ],
            "risks": [
                {
                    "id": "RISK1",
                    "title": "Duplicate reminder delivery",
                    "description": (
                        "A retry after an ambiguous gateway response could send a second email for "
                        "the same appointment."
                    ),
                    "severity": "high",
                    "uncertainty": "medium",
                    "failure_modes": [
                        "The gateway accepts an email before the worker records its receipt",
                    ],
                    "detection_signals": [
                        "duplicate_notifications is greater than zero",
                    ],
                    "mitigations": [
                        "Enforce a persistent unique idempotency key before gateway delivery",
                    ],
                    "verification_ids": ["VT1"],
                }
            ],
            "verification": [
                {
                    "id": "VT1",
                    "title": "Due reminder retry remains idempotent",
                    "requirement_ids": ["R1", "R2"],
                    "test_level": "integration",
                    "method": "deterministic",
                    "oracle": (
                        "The fixture's expected outbox contains one email and the receipt store "
                        "contains one successful idempotency key."
                    ),
                    "fixtures": [
                        "One confirmed appointment due in 24 hours",
                        "A deterministic email gateway test double",
                    ],
                    "procedure": [
                        "Run the reminder scan three times for the same appointment",
                        "Read the gateway outbox and persisted reminder receipts",
                        "Emit the notification-count metrics and execution marker",
                    ],
                    "pass_criteria": [
                        "Exactly one email and one successful receipt exist after all scans",
                        "Runtime evidence identifies VT1 as executed",
                    ],
                    "declared_metrics": [
                        "notifications_sent",
                        "duplicate_notifications",
                    ],
                    "metric_assertions": [
                        {
                            "metric": "notifications_sent",
                            "operator": "==",
                            "threshold": 1,
                            "tolerance": 0,
                        },
                        {
                            "metric": "duplicate_notifications",
                            "operator": "==",
                            "threshold": 0,
                            "tolerance": 0,
                        },
                    ],
                    "coverage_targets": [
                        "Due appointment success path and repeated-scan idempotency path",
                    ],
                    "automation": "automated",
                    "blocking": True,
                    "validation_loop": {
                        "maximum_correction_attempts": 2,
                        "repetitions_per_attempt": 3,
                        "stagnation_limit": 1,
                        "escalation_condition": (
                            "Escalate when duplicate delivery persists or two correction attempts fail"
                        ),
                        "retain_evidence": True,
                    },
                    "command_override": (
                        "python -m pytest -q tests/test_appointment_reminders.py"
                    ),
                    "working_directory": ".",
                    "timeout": 60,
                    "required_evidence": [
                        "VT1 execution marker, emitted metrics, test log, and receipt-store snapshot",
                    ],
                }
            ],
            "open_questions": [
                "Should a later slice add SMS reminders as a separate optional requirement?",
            ],
        }
    )
    return record_to_document(payload, worktree=worktree)


# Explicit aliases make the helper vocabulary discoverable to other frontends.
model_to_record = document_to_record
record_to_model = record_to_document


def issues_by_tab(
    issues: StageAssessment | Iterable[WorkflowIssue],
) -> dict[str, tuple[WorkflowIssue, ...]]:
    """Route every workflow issue to a stable editor-tab bucket."""

    values = issues.issues if isinstance(issues, StageAssessment) else tuple(issues)
    routed: dict[str, list[WorkflowIssue]] = {stage: [] for stage in EDITOR_STAGES}
    for issue in values:
        stage = issue.owning_stage if issue.owning_stage in routed else "Review"
        routed[stage].append(issue)
    return {stage: tuple(routed[stage]) for stage in EDITOR_STAGES}


route_issues_to_tabs = issues_by_tab


@dataclass(frozen=True)
class FieldSemanticFeedback:
    """Advisory semantic health rendered beside one specification input."""

    health: str
    message: str


@dataclass(frozen=True)
class SpecificationSuggestion:
    """One display-neutral result from testing the complete specification draft."""

    severity: str
    field: str
    tab: str
    message: str


_PLACEHOLDER_RE = re.compile(
    r"^(?:todo|tbd|tbc|n/?a|none|unknown|placeholder|example|sample|lorem(?: ipsum)?|"
    r"fill (?:this|me) in|to be (?:decided|defined|confirmed)|\?+)$",
    re.IGNORECASE,
)
_DESCRIPTIVE_LEAVES = {
    "title",
    "summary",
    "objectives",
    "stakeholders",
    "in_scope",
    "out_of_scope",
    "assumptions",
    "constraints",
    "dependencies",
    "actors",
    "preconditions",
    "trigger",
    "main_flow",
    "alternate_flows",
    "postconditions",
    "error_and_edge_cases",
    "statement",
    "rationale",
    "acceptance_criteria",
    "source",
    "description",
    "failure_modes",
    "detection_signals",
    "mitigations",
    "oracle",
    "fixtures",
    "procedure",
    "pass_criteria",
    "coverage_targets",
    "required_evidence",
    "selected_decision",
    "rejected_alternatives",
    "consequences",
    "open_questions",
    "escalation_condition",
}


def _semantic_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(text for item in value.values() for text in _semantic_values(item))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(text for item in value for text in _semantic_values(item))
    return ()


def _is_empty_semantic_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, Mapping):
        return not value or all(_is_empty_semantic_value(item) for item in value.values())
    if isinstance(value, Sequence):
        return not value or all(_is_empty_semantic_value(item) for item in value)
    return False


def _looks_like_placeholder(path: str, value: Any) -> bool:
    leaf = path.rsplit(".", 1)[-1].split("[", 1)[0]
    if leaf not in _DESCRIPTIVE_LEAVES:
        return False
    values = tuple(text.strip() for text in _semantic_values(value) if text.strip())
    if not values:
        return False
    return any(_PLACEHOLDER_RE.fullmatch(text) for text in values) or (
        len(values) == 1 and len(values[0]) < 4
    )


def _issues_for_feedback_path(
    assessment: StageAssessment,
    path: str,
) -> tuple[WorkflowIssue, ...]:
    prefixes = (f"{path}.", f"{path}[")
    return tuple(
        issue
        for issue in assessment.issues
        if issue.path == path or issue.path.startswith(prefixes)
    )


def _summarize_feedback_issues(issues: Sequence[WorkflowIssue]) -> str:
    messages: list[str] = []
    for issue in issues:
        message = f"{issue.path}: {issue.actionable_message}"
        if message not in messages:
            messages.append(message)
    shown = messages[:2]
    summary = "; ".join(shown)
    if len(messages) > len(shown):
        summary += f"; plus {len(messages) - len(shown)} more issue(s)"
    return summary


def compute_field_feedback(
    record: Mapping[str, Any],
    *,
    worktree: str | Path | None = None,
    assessment: StageAssessment | None = None,
) -> dict[str, FieldSemanticFeedback]:
    """Compute synchronous, user-facing semantic feedback for editor fields.

    Authoritative findings come from :func:`assess_specification`.  Two small
    advisory checks complement that model: obvious placeholder prose and
    automated verification cases with no metric assertion that runtime proof
    can evaluate.  The input record is copied and never changed.
    """

    source = copy.deepcopy(dict(record))
    if assessment is None:
        try:
            document = record_to_document(source, worktree=worktree)
            assessment = assess_specification(document, worktree=worktree)
        except Exception as exc:
            assessment = StageAssessment(
                issues=(WorkflowIssue("Review", "editor", "error", str(exc)),),
                structurally_valid=False,
                approval_ready=False,
            )

    feedback: dict[str, FieldSemanticFeedback] = {}

    def add(path: str, value: Any, *, optional: bool = False) -> None:
        issues = _issues_for_feedback_path(assessment, path)
        if _is_empty_semantic_value(value):
            if issues:
                detail = _summarize_feedback_issues(issues)
                message = f"Empty — add meaningful content. {detail}"
            elif optional:
                message = "Empty — optional for approval, but add it when it clarifies the contract."
            else:
                message = "Empty — add meaningful content before review."
            feedback[path] = FieldSemanticFeedback("empty", message)
        elif _looks_like_placeholder(path, value):
            feedback[path] = FieldSemanticFeedback(
                "weak",
                "Needs detail — replace placeholder or overly short text with a concrete, "
                "testable description.",
            )
        elif issues:
            feedback[path] = FieldSemanticFeedback(
                "needs_attention",
                f"Needs attention — {_summarize_feedback_issues(issues)}",
            )
        else:
            count = len(value) if isinstance(value, Sequence) and not isinstance(value, str) else None
            populated = f"{count} item(s)" if count is not None else "meaningful content"
            feedback[path] = FieldSemanticFeedback(
                "healthy", f"Looks good — populated with {populated}; no current workflow issue."
            )

    optional_roots = {"assumptions", "constraints", "dependencies", "risks", "decisions", "open_questions"}
    top_level_fields = (
        "title",
        "summary",
        "objectives",
        "stakeholders",
        "in_scope",
        "out_of_scope",
        "assumptions",
        "constraints",
        "dependencies",
        "use_cases",
        "requirements",
        "risks",
        "verification",
        "decisions",
        "open_questions",
    )
    for path in top_level_fields:
        add(path, source.get(path), optional=path in optional_roots)

    collection_fields = {
        "use_cases": USE_CASE_FIELDS,
        "requirements": REQUIREMENT_FIELDS,
        "risks": RISK_FIELDS,
        "verification": VERIFICATION_FIELDS,
        "decisions": DECISION_FIELDS,
    }
    for group, fields in collection_fields.items():
        values = source.get(group, ())
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
            continue
        for index, item in enumerate(values):
            if not isinstance(item, Mapping):
                continue
            for field in fields:
                model_path = f"{group}[{index}].{field.key}"
                value = item.get(field.key, field.default)
                if group == "verification" and field.key in {
                    "maximum_correction_attempts",
                    "repetitions_per_attempt",
                    "stagnation_limit",
                    "escalation_condition",
                    "retain_evidence",
                }:
                    model_path = f"{group}[{index}].validation_loop.{field.key}"
                    loop = item.get("validation_loop", {})
                    value = loop.get(field.key, field.default) if isinstance(loop, Mapping) else field.default
                add(model_path, value, optional=True)

            if group == "verification":
                automation = str(item.get("automation", ""))
                assertions = item.get("metric_assertions", ())
                assertion_path = f"verification[{index}].metric_assertions"
                if automation == AutomationLevel.AUTOMATED.value and not assertions:
                    existing = _issues_for_feedback_path(assessment, assertion_path)
                    suffix = (
                        f" {_summarize_feedback_issues(existing)}" if existing else ""
                    )
                    feedback[assertion_path] = FieldSemanticFeedback(
                        "needs_attention",
                        "Needs attention — this automated case lacks runtime-provable metric "
                        f"assertions, so passing output cannot prove its intended claim.{suffix}",
                    )

        child_attention = [
            (path, item)
            for path, item in feedback.items()
            if path.startswith(f"{group}[")
            and (
                item.health in {"weak", "needs_attention"}
                or (
                    item.health == "empty"
                    and bool(_issues_for_feedback_path(assessment, path))
                )
            )
        ]
        if child_attention and feedback[group].health == "healthy":
            path, item = child_attention[0]
            feedback[group] = FieldSemanticFeedback(
                "needs_attention",
                f"Needs attention in {path} — {item.message}",
            )

    return feedback


_SUGGESTION_TAB_BY_ROOT = {
    "title": "Overview",
    "summary": "Overview",
    "objectives": "Overview",
    "stakeholders": "Overview",
    "in_scope": "Scope",
    "out_of_scope": "Scope",
    "assumptions": "Scope",
    "constraints": "Scope",
    "dependencies": "Scope",
    "use_cases": "Use Cases",
    "requirements": "Requirements",
    "risks": "Risks",
    "verification": "Verification",
    "decisions": "Choices",
    "choices": "Choices",
    "open_questions": "Choices",
}


def _suggestion_tab_for_path(path: str) -> str:
    root = path.removeprefix("specification.").split(".", 1)[0].split("[", 1)[0]
    return _SUGGESTION_TAB_BY_ROOT.get(root, "Review")


def analyze_specification(
    record: Mapping[str, Any],
    *,
    worktree: str | Path | None = None,
    unresolved_blocking_decisions: int = 0,
) -> tuple[SpecificationSuggestion, ...]:
    """Return ranked, deduplicated suggestions for the entire current draft.

    This function deliberately has no Tk dependency and never mutates ``record``.
    Authoritative workflow issues are blocking suggestions.  Additional semantic
    findings are ranked as traceability/runtime-proof improvements or advisory
    prose polish.  A clean result is explicit so a caller never has to display
    an empty review.
    """

    source = copy.deepcopy(dict(record))
    try:
        document = record_to_document(source, worktree=worktree)
        assessment = assess_specification(
            document,
            worktree=worktree,
            unresolved_blocking_decisions=unresolved_blocking_decisions,
        )
    except Exception as exc:
        assessment = StageAssessment(
            issues=(WorkflowIssue("Review", "editor", "error", str(exc)),),
            structurally_valid=False,
            approval_ready=False,
        )

    suggestions: list[SpecificationSuggestion] = []
    workflow_paths: list[str] = []
    for tab, issues in route_issues_to_tabs(assessment).items():
        for issue in issues:
            workflow_paths.append(issue.path)
            suggestions.append(
                SpecificationSuggestion(
                    severity="blocking",
                    field=issue.path,
                    tab=tab,
                    message=f"Resolve before approval: {issue.actionable_message}",
                )
            )

    feedback = compute_field_feedback(source, worktree=worktree, assessment=assessment)

    def covered_by_workflow_issue(path: str) -> bool:
        return any(
            issue_path == path
            or issue_path.startswith((f"{path}.", f"{path}["))
            or path.startswith((f"{issue_path}.", f"{issue_path}["))
            for issue_path in workflow_paths
        )

    important_terms = (
        "trace",
        "linked requirement",
        "covered by verification",
        "runtime",
        "metric assertion",
        "execution proof",
        "intended claim",
    )
    collection_roots = {
        "use_cases",
        "requirements",
        "risks",
        "verification",
        "decisions",
    }
    for path, item in feedback.items():
        if item.health == "healthy" or covered_by_workflow_issue(path):
            continue
        if path in collection_roots and any(
            child_path.startswith(f"{path}[") and child.health != "healthy"
            for child_path, child in feedback.items()
        ):
            # Collection-root feedback summarizes its first child finding; the
            # child carries the concrete field location and is more useful.
            continue
        # Optional empty fields are already described by their permanent field
        # guidance.  Repeating every one here would obscure concrete findings.
        if item.health == "empty" and "optional for approval" in item.message:
            continue
        normalized = item.message.casefold()
        severity = (
            "important"
            if any(term in normalized for term in important_terms)
            else "advisory"
        )
        suggestions.append(
            SpecificationSuggestion(
                severity=severity,
                field=path,
                tab=_suggestion_tab_for_path(path),
                message=item.message,
            )
        )

    unique: list[SpecificationSuggestion] = []
    seen: set[tuple[str, str]] = set()
    for suggestion in suggestions:
        key = (suggestion.field, suggestion.message.casefold())
        if key in seen:
            continue
        seen.add(key)
        unique.append(suggestion)

    severity_order = {"blocking": 0, "important": 1, "advisory": 2}
    stage_order = {stage: index for index, stage in enumerate(EDITOR_STAGES)}
    unique.sort(
        key=lambda item: (
            severity_order[item.severity],
            stage_order.get(item.tab, len(stage_order)),
            item.field,
            item.message,
        )
    )
    if not any(item.severity == "blocking" for item in unique):
        summary = (
            "No blocking issues found. Review the prioritized improvements below."
            if unique
            else "No blocking issues found. The specification is ready for workflow review."
        )
        unique.insert(
            0,
            SpecificationSuggestion(
                severity="clear",
                field="specification",
                tab="Review",
                message=summary,
            ),
        )
    return tuple(unique)


# Keep the older descriptive name for callers that adopted it while the wizard
# work was in progress.  ``analyze_specification`` is the public headless action
# named by the GUI and can be reused by non-Tk frontends.
analyze_specification_suggestions = analyze_specification


def render_specification_json_diff(
    source: SpecificationDocument,
    suggestion: SpecificationDocument,
    *,
    source_label: str = "stored-draft.json",
    suggestion_label: str = "suggested-specification.json",
) -> str:
    """Return an exact deterministic unified diff of the two pretty JSON documents."""

    return "".join(
        difflib.unified_diff(
            source.pretty_json().splitlines(keepends=True),
            suggestion.pretty_json().splitlines(keepends=True),
            fromfile=source_label,
            tofile=suggestion_label,
            lineterm="\n",
        )
    )


def render_choice_summary(
    choices: Iterable[DecisionProposal | Mapping[str, Any]],
) -> str:
    """Render proposed decisions separately from specification-field changes."""

    sections: list[str] = []
    for index, choice_value in enumerate(choices, 1):
        choice = (
            choice_value.to_dict()
            if isinstance(choice_value, DecisionProposal)
            else dict(choice_value)
        )
        options = choice.get("options", ())
        lines = [
            f"Choice {index}",
            f"Topic: {choice.get('topic', '')}",
            f"Question: {choice.get('question', '')}",
            f"Context: {choice.get('context', '')}",
            f"Recommendation: {choice.get('recommendation', '')}",
            f"Blocking: {'yes' if choice.get('blocking') else 'no'}",
            "Options:",
        ]
        for option_value in options if isinstance(options, Sequence) else ():
            if not isinstance(option_value, Mapping):
                continue
            lines.append(f"  - {option_value.get('name', '')}: {option_value.get('description', '')}")
            tradeoffs = option_value.get("tradeoffs", ())
            for tradeoff in tradeoffs if isinstance(tradeoffs, Sequence) else ():
                lines.append(f"      Tradeoff: {tradeoff}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections) if sections else "No choices were proposed."


@dataclass(frozen=True)
class _Field:
    key: str
    label: str
    kind: str = "entry"
    values: tuple[str, ...] = ()
    default: Any = ""
    group: str = "Common"


USE_CASE_FIELDS = (
    _Field("id", "Stable ID"),
    _Field("title", "Title"),
    _Field("actors", "Actors", "list"),
    _Field("preconditions", "Preconditions", "list"),
    _Field("trigger", "Trigger", "text"),
    _Field("main_flow", "Ordered main flow", "list"),
    _Field("alternate_flows", "Alternate flows", "list"),
    _Field("postconditions", "Postconditions", "list"),
    _Field("error_and_edge_cases", "Errors and edge cases", "list"),
    _Field("requirement_ids", "Linked requirement IDs", "list"),
)

REQUIREMENT_FIELDS = (
    _Field("id", "Stable ID"),
    _Field("category", "Category", "enum", tuple(item.value for item in RequirementCategory), "functional"),
    _Field("priority", "Priority", "enum", tuple(item.value for item in RequirementPriority), "must"),
    _Field("title", "Title"),
    _Field("statement", "Normative statement", "text"),
    _Field("rationale", "Rationale", "text"),
    _Field("acceptance_criteria", "Measurable acceptance criteria", "list"),
    _Field("source", "Source"),
)

RISK_FIELDS = (
    _Field("id", "Stable ID"),
    _Field("title", "Title"),
    _Field("description", "Description", "text"),
    _Field("severity", "Severity", "enum", tuple(item.value for item in RiskSeverity), "low"),
    _Field("uncertainty", "Uncertainty", "enum", tuple(item.value for item in RiskUncertainty), "low"),
    _Field("failure_modes", "Failure modes", "list"),
    _Field("detection_signals", "Observable detection signals", "list"),
    _Field("mitigations", "Mitigations", "list"),
    _Field("verification_ids", "Linked verification IDs", "list"),
)

DECISION_FIELDS = (
    _Field("topic", "Topic"),
    _Field("selected_decision", "Selected decision", "text"),
    _Field("rationale", "Rationale", "text"),
    _Field("rejected_alternatives", "Rejected alternatives", "list"),
    _Field("consequences", "Consequences", "list"),
)

VERIFICATION_FIELDS = (
    _Field("id", "Stable ID"),
    _Field("title", "Title"),
    _Field("requirement_ids", "Requirement IDs", "list"),
    _Field("test_level", "Test level", "enum", tuple(item.value for item in TestLevel), "unit"),
    _Field("method", "Method", "enum", tuple(item.value for item in VerificationMethod), "deterministic"),
    _Field("oracle", "Independent oracle", "text"),
    _Field("fixtures", "Fixtures", "list"),
    _Field("procedure", "Ordered procedure", "list"),
    _Field("pass_criteria", "Pass criteria", "list"),
    _Field("declared_metrics", "Declared metric names", "list"),
    _Field("metric_assertions", "Metric assertions: name operator threshold [tolerance]", "metrics"),
    _Field(
        "coverage_targets",
        "Coverage targets: prose or one JSON object per line",
        "records",
    ),
    _Field(
        "required_evidence",
        "Required evidence: prose or one JSON object per line",
        "records",
    ),
    _Field("automation", "Automation", "enum", tuple(item.value for item in AutomationLevel), "automated"),
    _Field("blocking", "Blocks autonomous completion", "bool", default=False),
    _Field("command_override", "Command override", group="Advanced execution and validation loop"),
    _Field("working_directory", "Working directory", default=".", group="Advanced execution and validation loop"),
    _Field("timeout", "Timeout (seconds)", "positive_int", default=300, group="Advanced execution and validation loop"),
    _Field("maximum_correction_attempts", "Maximum correction attempts", "positive_int", default=1, group="Advanced execution and validation loop"),
    _Field("repetitions_per_attempt", "Repetitions per attempt", "positive_int", default=1, group="Advanced execution and validation loop"),
    _Field("stagnation_limit", "Stagnation limit", "positive_int", default=1, group="Advanced execution and validation loop"),
    _Field("escalation_condition", "Escalation condition", "text", group="Advanced execution and validation loop"),
    _Field("retain_evidence", "Retain evidence", "bool", default=True, group="Advanced execution and validation loop"),
)


def _verification_for_dialog(record: Mapping[str, Any] | None) -> dict[str, Any]:
    result = copy.deepcopy(dict(record or {}))
    loop = result.pop("validation_loop", {})
    result.update(loop)
    result["metric_assertions"] = format_metric_assertions(result.get("metric_assertions", ()))
    result["coverage_targets"] = format_structured_records(
        result.get("coverage_targets", ())
    )
    result["required_evidence"] = format_structured_records(
        result.get("required_evidence", ())
    )
    return result


def _verification_from_dialog(record: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(record))
    if isinstance(result.get("metric_assertions"), str):
        result["metric_assertions"] = [
            item.__dict__ for item in parse_metric_assertions(result["metric_assertions"])
        ]
    for key in ("coverage_targets", "required_evidence"):
        if isinstance(result.get(key), str):
            result[key] = list(parse_structured_records(result[key]))
    loop_keys = (
        "maximum_correction_attempts",
        "repetitions_per_attempt",
        "stagnation_limit",
        "escalation_condition",
        "retain_evidence",
    )
    result["validation_loop"] = {key: result.pop(key) for key in loop_keys}
    result["command_override"] = result.get("command_override") or None
    return result


class _RecordDialog:
    """Scrollable record dialog with lossless nested verification records."""

    def __init__(
        self,
        parent: Any,
        title: str,
        fields: Sequence[_Field],
        initial: Mapping[str, Any] | None = None,
        *,
        field_path_prefix: str | None = None,
        feedback_provider: (
            Callable[[Mapping[str, Any]], Mapping[str, FieldSemanticFeedback]] | None
        ) = None,
    ) -> None:
        assert tk is not None and ttk is not None
        self.result: dict[str, Any] | None = None
        self._feedback_provider = feedback_provider
        self._feedback_after_id: str | None = None
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.geometry("720x700")
        self.window.minsize(520, 420)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)

        outer = ttk.Frame(self.window, padding=(10, 10, 10, 0))
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)
        canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        body = ttk.Frame(canvas, padding=(0, 0, 8, 8))
        body.columnconfigure(1, weight=1)
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_id, width=event.width))

        initial_values = dict(initial or {})
        self._controls: dict[str, tuple[_Field, Any]] = {}
        self.guidance_labels: dict[str, Any] = {}
        self._guidance_text: dict[str, str] = {}
        row = 0
        current_group = ""
        for field in fields:
            if field.group != current_group:
                ttk.Separator(body).grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 5))
                row += 1
                ttk.Label(body, text=field.group).grid(row=row, column=0, columnspan=2, sticky="w")
                row += 1
                current_group = field.group
            label_frame = ttk.Frame(body)
            label_frame.grid(row=row, column=0, sticky="new", padx=(0, 12), pady=4)
            ttk.Label(label_frame, text=field.label).pack(anchor="w")
            guidance_key = (
                f"{field_path_prefix}.{field.key}" if field_path_prefix else ""
            )
            guidance = _field_guidance(guidance_key) if guidance_key else ""
            if guidance:
                guidance_label = ttk.Label(
                    label_frame,
                    text=guidance,
                    wraplength=245,
                    justify="left",
                )
                guidance_label.pack(anchor="w", pady=(2, 0))
                self.guidance_labels[field.key] = guidance_label
                self._guidance_text[field.key] = guidance
            value = initial_values.get(field.key, field.default)
            control: Any
            if field.kind in {"text", "list", "metrics", "records"}:
                control = tk.Text(body, height=4 if field.kind == "text" else 5, wrap="word")
                if isinstance(value, str):
                    rendered = value
                elif field.kind == "metrics":
                    rendered = format_metric_assertions(value or ())
                elif field.kind == "records":
                    rendered = format_structured_records(value or ())
                else:
                    rendered = format_list_text(value or ())
                control.insert("1.0", rendered)
            elif field.kind == "enum":
                variable = tk.StringVar(value=str(value or field.default))
                control = ttk.Combobox(
                    body, textvariable=variable, values=field.values, state="readonly"
                )
            elif field.kind == "bool":
                variable = tk.BooleanVar(value=bool(value))
                control = ttk.Checkbutton(body, variable=variable)
            elif field.kind == "positive_int":
                variable = tk.IntVar(value=int(value or field.default))
                control = ttk.Spinbox(body, from_=1, to=1_000_000, textvariable=variable)
            else:
                variable = tk.StringVar(value="" if value is None else str(value))
                control = ttk.Entry(body, textvariable=variable)
            control.grid(row=row, column=1, sticky="ew", pady=4)
            self._controls[field.key] = (field, control)
            row += 1

        if self._feedback_provider is not None:
            self.window.bind("<KeyRelease>", self._schedule_feedback, add="+")
            self.window.bind("<<ComboboxSelected>>", self._schedule_feedback, add="+")
            self.window.bind("<ButtonRelease-1>", self._schedule_feedback, add="+")
            for field, control in self._controls.values():
                if field.kind in {"text", "list", "metrics", "records"}:
                    control.edit_modified(False)
                    control.bind("<<Modified>>", self._on_text_modified, add="+")

        actions = ttk.Frame(self.window, padding=10)
        actions.grid(row=1, column=0, sticky="ew")
        ttk.Button(actions, text="Cancel", command=self.window.destroy).pack(side="right")
        ttk.Button(actions, text="Apply", command=self._accept).pack(side="right", padx=(0, 8))
        self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)
        self._refresh_feedback()

    def _collect_values(self) -> tuple[dict[str, Any], dict[str, str]]:
        result: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for key, (field, control) in self._controls.items():
            try:
                if field.kind in {"text", "list", "metrics", "records"}:
                    value: Any = control.get("1.0", "end-1c")
                    if field.kind == "list":
                        value = list(parse_list_text(value))
                    elif field.kind == "metrics":
                        value = [item.__dict__ for item in parse_metric_assertions(value)]
                    elif field.kind == "records":
                        value = list(parse_structured_records(value))
                elif field.kind == "positive_int":
                    value = int(control.get())
                    if value <= 0:
                        raise ValueError(f"{field.label} must be positive")
                elif field.kind == "bool":
                    raw = control.getvar(control.cget("variable"))
                    value = str(raw).lower() in {"1", "true", "yes", "on"}
                else:
                    value = control.get()
                result[key] = value
            except (ValueError, tk.TclError) as exc:
                errors[key] = str(exc)
        return result, errors

    def _schedule_feedback(self, _event: Any = None) -> None:
        if self._feedback_provider is None:
            return
        if self._feedback_after_id is not None:
            try:
                self.window.after_cancel(self._feedback_after_id)
            except tk.TclError:
                pass
        self._feedback_after_id = self.window.after(100, self._finish_scheduled_feedback)

    def _on_text_modified(self, event: Any) -> None:
        if event.widget.edit_modified():
            event.widget.edit_modified(False)
            self._schedule_feedback(event)

    def _finish_scheduled_feedback(self) -> None:
        self._feedback_after_id = None
        self._refresh_feedback()

    def _refresh_feedback(self) -> None:
        if self._feedback_provider is None:
            return
        values, errors = self._collect_values()
        feedback = self._feedback_provider(values) if not errors else {}
        for key, label in self.guidance_labels.items():
            if key in errors:
                message = f"Needs attention — {errors[key]}"
            elif key in feedback:
                message = feedback[key].message
            else:
                message = "Waiting for the other record fields to become valid."
            label.configure(text=f"{self._guidance_text[key]}\n\nLive feedback: {message}")

    def _accept(self) -> None:
        result, errors = self._collect_values()
        if errors:
            assert messagebox is not None
            messagebox.showerror(
                "Invalid record",
                next(iter(errors.values())),
                parent=self.window,
            )
            return
        self.result = result
        self.window.destroy()

    def show(self) -> dict[str, Any] | None:
        self.window.wait_window()
        return self.result


class _SpecificationSuggestionsDialog:
    """Modal, scrollable presentation of a read-only holistic draft test."""

    def __init__(
        self,
        parent: Any,
        suggestions: Sequence[SpecificationSuggestion],
    ) -> None:
        assert tk is not None and ttk is not None
        self.window = tk.Toplevel(parent)
        self.window.title("Specification test results")
        self.window.geometry("860x620")
        self.window.minsize(600, 400)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        blocking_count = sum(item.severity == "blocking" for item in suggestions)
        ttk.Label(
            self.window,
            text=(
                f"Holistic review of the current draft: {blocking_count} blocking issue(s). "
                "Suggestions are ordered by completion risk, then verification traceability "
                "and runtime proof, then advisory polish. Nothing was changed."
            ),
            wraplength=820,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        frame = ttk.Frame(self.window)
        frame.grid(row=1, column=0, sticky="nsew", padx=10)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        results = tk.Text(frame, wrap="word", undo=False)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=results.yview)
        results.configure(yscrollcommand=scrollbar.set)
        results.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        rendered = []
        for index, suggestion in enumerate(suggestions, 1):
            rendered.append(
                f"{index}. [{suggestion.severity.upper()}] "
                f"{suggestion.tab} · {suggestion.field}\n{suggestion.message}"
            )
        results.insert("1.0", "\n\n".join(rendered))
        results.configure(state="disabled")
        self.results_text = results

        actions = ttk.Frame(self.window, padding=10)
        actions.grid(row=2, column=0, sticky="ew")
        ttk.Button(actions, text="Close", command=self.window.destroy).pack(side="right")
        self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)

    def show(self) -> None:
        self.window.wait_window()


class _ElicitationReviewDialog:
    """Modal review that keeps JSON additions and unresolved choices distinct."""

    def __init__(
        self,
        parent: Any,
        *,
        completed: CompletedElicitation,
        source: StoredSpecificationVersion,
    ) -> None:
        assert tk is not None and ttk is not None
        self.result: str | None = None
        self.window = tk.Toplevel(parent)
        self.window.title("Review AI Specification Analysis")
        self.window.geometry("1040x780")
        self.window.minsize(700, 500)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        summary_frame = ttk.LabelFrame(self.window, text="Analysis summary", padding=8)
        summary_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        summary_frame.columnconfigure(0, weight=1)
        ttk.Label(
            summary_frame,
            text=completed.result.summary,
            wraplength=950,
            justify="left",
        ).grid(row=0, column=0, sticky="ew")
        if completed.result.warnings:
            ttk.Label(
                summary_frame,
                text="Warnings:\n" + "\n".join(f"• {item}" for item in completed.result.warnings),
                wraplength=950,
                justify="left",
            ).grid(row=1, column=0, sticky="ew", pady=(6, 0))

        notebook = ttk.Notebook(self.window)
        notebook.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        diff_frame = ttk.Frame(notebook, padding=7)
        choices_frame = ttk.Frame(notebook, padding=7)
        notebook.add(diff_frame, text="Exact JSON Diff")
        notebook.add(choices_frame, text=f"Proposed Choices ({len(completed.result.choices)})")
        for frame in (diff_frame, choices_frame):
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(1, weight=1)

        diff = render_specification_json_diff(
            source.document,
            completed.result.suggested_specification,
            source_label=f"{source.specification_id}-v{source.version}-stored.json",
            suggestion_label=f"{completed.stored.analysis_id}-suggested.json",
        )
        ttk.Label(
            diff_frame,
            text=(
                "Unified diff of the exact stored draft JSON and the complete additive suggestion."
                if diff
                else "The analysis proposed no specification-field additions."
            ),
        ).grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.diff_text = self._readonly_text(diff_frame, diff, wrap="none")

        ttk.Label(
            choices_frame,
            text=(
                "These are unresolved proposals. Recommendations are not materialized decisions."
            ),
        ).grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.choice_text = self._readonly_text(
            choices_frame,
            render_choice_summary(completed.result.choices),
            wrap="word",
        )

        actions = ttk.Frame(self.window, padding=10)
        actions.grid(row=2, column=0, sticky="ew")
        ttk.Button(actions, text="Cancel", command=self._cancel).pack(side="right")
        ttk.Button(
            actions,
            text="Apply All",
            command=lambda: self._choose("apply_all"),
        ).pack(side="right", padx=(0, 7))
        ttk.Button(
            actions,
            text="Choices Only",
            command=lambda: self._choose("choices_only"),
        ).pack(side="right", padx=(0, 7))
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)

    @staticmethod
    def _readonly_text(parent: Any, value: str, *, wrap: str) -> Any:
        assert tk is not None and ttk is not None
        frame = ttk.Frame(parent)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        text_widget = tk.Text(frame, wrap=wrap, undo=False)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=vertical.set)
        text_widget.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        if wrap == "none":
            horizontal = ttk.Scrollbar(frame, orient="horizontal", command=text_widget.xview)
            text_widget.configure(xscrollcommand=horizontal.set)
            horizontal.grid(row=1, column=0, sticky="ew")
        text_widget.insert("1.0", value)
        text_widget.configure(state="disabled")
        return text_widget

    def _choose(self, action: str) -> None:
        self.result = action
        self.window.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.window.destroy()

    def show(self) -> str | None:
        self.window.wait_window()
        return self.result


class VerificationDashboardView:
    """Tk-only renderer for GUI-neutral formal verification dashboard rows."""

    def __init__(
        self,
        parent: Any,
        *,
        refresh_command: Callable[[], None],
        acknowledge_command: Callable[[str, str, str], None],
        default_actor: str,
    ) -> None:
        if tk is None or ttk is None or messagebox is None:
            raise RuntimeError("Tkinter is not available; the verification dashboard cannot open")
        self.frame = ttk.Frame(parent, padding=7)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        self._refresh_command = refresh_command
        self._acknowledge_command = acknowledge_command
        self._rows: dict[str, Mapping[str, Any]] = {}
        self._selected_repetitions: dict[str, Mapping[str, Any]] = {}
        self._selected_evidence: dict[str, Mapping[str, Any]] = {}

        bar = ttk.Frame(self.frame)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        bar.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Select a formal job to inspect verification.")
        ttk.Label(bar, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.refresh_button = ttk.Button(bar, text="Refresh", command=refresh_command)
        self.refresh_button.grid(row=0, column=1, sticky="e")

        split = ttk.PanedWindow(self.frame, orient="vertical")
        split.grid(row=1, column=0, sticky="nsew")
        cases_frame = ttk.LabelFrame(split, text="Formal verification cases", padding=5)
        details_frame = ttk.Frame(split)
        split.add(cases_frame, weight=3)
        split.add(details_frame, weight=4)

        cases_frame.columnconfigure(0, weight=1)
        cases_frame.rowconfigure(0, weight=1)
        case_columns = (
            "title",
            "requirements",
            "blocking",
            "automation",
            "realization",
            "runtime",
            "attempts",
            "repetitions",
            "metrics",
            "failed",
            "stagnation",
            "escalation",
        )
        self.case_tree = ttk.Treeview(
            cases_frame,
            columns=case_columns,
            show="tree headings",
            selectmode="browse",
        )
        self.case_tree.heading("#0", text="Verification ID")
        self.case_tree.column("#0", width=105, stretch=False)
        widths = {
            "title": 190,
            "requirements": 120,
            "blocking": 70,
            "automation": 90,
            "realization": 155,
            "runtime": 155,
            "attempts": 65,
            "repetitions": 85,
            "metrics": 150,
            "failed": 150,
            "stagnation": 95,
            "escalation": 85,
        }
        for column in case_columns:
            self.case_tree.heading(column, text=column.replace("_", " ").title())
            self.case_tree.column(column, width=widths[column], stretch=column == "title")
        case_y = ttk.Scrollbar(cases_frame, orient="vertical", command=self.case_tree.yview)
        case_x = ttk.Scrollbar(cases_frame, orient="horizontal", command=self.case_tree.xview)
        self.case_tree.configure(yscrollcommand=case_y.set, xscrollcommand=case_x.set)
        self.case_tree.grid(row=0, column=0, sticky="nsew")
        case_y.grid(row=0, column=1, sticky="ns")
        case_x.grid(row=1, column=0, sticky="ew")
        self.case_tree.bind("<<TreeviewSelect>>", self._on_case_selected)

        details_frame.columnconfigure(0, weight=1)
        details_frame.rowconfigure(0, weight=1)
        self.detail_notebook = ttk.Notebook(details_frame)
        self.detail_notebook.grid(row=0, column=0, sticky="nsew")
        contract_tab = ttk.Frame(self.detail_notebook, padding=5)
        attempts_tab = ttk.Frame(self.detail_notebook, padding=5)
        notes_tab = ttk.Frame(self.detail_notebook, padding=5)
        self.detail_notebook.add(contract_tab, text="Contract enforcement")
        self.detail_notebook.add(attempts_tab, text="Attempts and retained evidence")
        self.detail_notebook.add(notes_tab, text="Manual acknowledgements")
        self._build_contract_tab(contract_tab)
        self._build_attempts_tab(attempts_tab)
        self._build_notes_tab(notes_tab, default_actor)

    @staticmethod
    def _compact(value: Any, *, limit: int = 120) -> str:
        if value in (None, "", [], {}):
            return "—"
        if isinstance(value, Mapping):
            text = ", ".join(f"{key}={item}" for key, item in value.items())
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            text = ", ".join(str(item.get("metric") if isinstance(item, Mapping) else item) for item in value)
        else:
            text = str(value)
        return text if len(text) <= limit else text[: limit - 1] + "…"

    @staticmethod
    def _readonly_text(parent: Any, *, height: int = 8) -> Any:
        widget = tk.Text(parent, height=height, wrap="word", undo=False)
        widget.configure(state="disabled")
        return widget

    @staticmethod
    def _set_text(widget: Any, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _build_contract_tab(self, tab: Any) -> None:
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        ttk.Label(
            tab,
            text=(
                "DESCRIPTIVE means prose only; REALIZED means infrastructure exists; "
                "MACHINE-ENFORCED means the runtime evaluator consumed emitted evidence."
            ),
            wraplength=1000,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.contract_tree = ttk.Treeview(
            tab,
            columns=("name", "enforcement", "description", "runtime"),
            show="tree headings",
        )
        self.contract_tree.heading("#0", text="Contract type")
        self.contract_tree.column("#0", width=145, stretch=False)
        for column, width in (
            ("name", 190),
            ("enforcement", 145),
            ("description", 440),
            ("runtime", 240),
        ):
            self.contract_tree.heading(column, text=column.title())
            self.contract_tree.column(column, width=width, stretch=column == "description")
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.contract_tree.yview)
        self.contract_tree.configure(yscrollcommand=scrollbar.set)
        self.contract_tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

    def _build_attempts_tab(self, tab: Any) -> None:
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        split = ttk.PanedWindow(tab, orient="horizontal")
        split.grid(row=0, column=0, sticky="nsew")
        history = ttk.LabelFrame(split, text="Repetitions", padding=5)
        inspection = ttk.LabelFrame(split, text="Selected repetition", padding=5)
        split.add(history, weight=2)
        split.add(inspection, weight=3)
        history.columnconfigure(0, weight=1)
        history.rowconfigure(0, weight=1)
        self.repetition_tree = ttk.Treeview(
            history,
            columns=("attempt", "repetition", "status", "return", "elapsed", "task", "run"),
            show="headings",
            selectmode="browse",
        )
        for column, width in (
            ("attempt", 55),
            ("repetition", 70),
            ("status", 95),
            ("return", 55),
            ("elapsed", 65),
            ("task", 105),
            ("run", 105),
        ):
            self.repetition_tree.heading(column, text=column.title())
            self.repetition_tree.column(column, width=width, stretch=False)
        repetition_scroll = ttk.Scrollbar(history, orient="vertical", command=self.repetition_tree.yview)
        self.repetition_tree.configure(yscrollcommand=repetition_scroll.set)
        self.repetition_tree.grid(row=0, column=0, sticky="nsew")
        repetition_scroll.grid(row=0, column=1, sticky="ns")
        self.repetition_tree.bind("<<TreeviewSelect>>", self._on_repetition_selected)

        inspection.columnconfigure(0, weight=1)
        inspection.rowconfigure(1, weight=1)
        inspection.rowconfigure(3, weight=1)
        ttk.Label(inspection, text="Bounded output and assertion details").grid(row=0, column=0, sticky="w")
        self.repetition_text = self._readonly_text(inspection, height=7)
        self.repetition_text.grid(row=1, column=0, sticky="nsew", pady=(3, 6))
        evidence_bar = ttk.Frame(inspection)
        evidence_bar.grid(row=2, column=0, sticky="ew")
        ttk.Label(evidence_bar, text="Retained evidence (binary/large content is metadata-only)").pack(side="left")
        self.preview_button = ttk.Button(
            evidence_bar,
            text="Open bounded text preview",
            command=self.open_selected_evidence_preview,
            state="disabled",
        )
        self.preview_button.pack(side="right")
        self.evidence_tree = ttk.Treeview(
            inspection,
            columns=("kind", "media", "size", "path", "sha256"),
            show="tree headings",
            selectmode="browse",
        )
        self.evidence_tree.heading("#0", text="Name")
        self.evidence_tree.column("#0", width=130, stretch=False)
        for column, width in (
            ("kind", 110),
            ("media", 135),
            ("size", 80),
            ("path", 260),
            ("sha256", 260),
        ):
            self.evidence_tree.heading(column, text=column.title())
            self.evidence_tree.column(column, width=width, stretch=column == "path")
        evidence_y = ttk.Scrollbar(inspection, orient="vertical", command=self.evidence_tree.yview)
        evidence_x = ttk.Scrollbar(inspection, orient="horizontal", command=self.evidence_tree.xview)
        self.evidence_tree.configure(yscrollcommand=evidence_y.set, xscrollcommand=evidence_x.set)
        self.evidence_tree.grid(row=3, column=0, sticky="nsew", pady=(3, 0))
        evidence_y.grid(row=3, column=1, sticky="ns")
        evidence_x.grid(row=4, column=0, sticky="ew")
        self.evidence_tree.bind("<<TreeviewSelect>>", self._on_evidence_selected)

    def _build_notes_tab(self, tab: Any, default_actor: str) -> None:
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        self.manual_note_status_var = tk.StringVar(
            value="Manual notes are available only for a selected non-blocking manual case."
        )
        ttk.Label(tab, textvariable=self.manual_note_status_var, wraplength=1000).grid(
            row=0, column=0, sticky="ew", pady=(0, 5)
        )
        self.ack_tree = ttk.Treeview(
            tab,
            columns=("who", "when", "note"),
            show="headings",
        )
        for column, width in (("who", 150), ("when", 180), ("note", 650)):
            self.ack_tree.heading(column, text=column.title())
            self.ack_tree.column(column, width=width, stretch=column == "note")
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.ack_tree.yview)
        self.ack_tree.configure(yscrollcommand=scrollbar.set)
        self.ack_tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        controls = ttk.Frame(tab)
        controls.grid(row=2, column=0, sticky="ew", pady=(7, 0))
        controls.columnconfigure(3, weight=1)
        ttk.Label(controls, text="Who").grid(row=0, column=0, sticky="w")
        self.ack_actor_var = tk.StringVar(value=default_actor)
        self.ack_actor_entry = ttk.Entry(controls, textvariable=self.ack_actor_var, width=18)
        self.ack_actor_entry.grid(row=0, column=1, sticky="ew", padx=(4, 10))
        ttk.Label(controls, text="Note").grid(row=0, column=2, sticky="w")
        self.ack_note_var = tk.StringVar()
        self.ack_note_entry = ttk.Entry(controls, textvariable=self.ack_note_var)
        self.ack_note_entry.grid(row=0, column=3, sticky="ew", padx=4)
        self.ack_button = ttk.Button(
            controls,
            text="Record manual acknowledgement",
            command=self._record_manual_acknowledgement,
            state="disabled",
        )
        self.ack_button.grid(row=0, column=4, sticky="e", padx=(6, 0))

    def set_loading(self, loading: bool, message: str | None = None) -> None:
        self.refresh_button.configure(state="disabled" if loading else "normal")
        if message:
            self.status_var.set(message)
        if loading:
            self.ack_button.configure(state="disabled")
        else:
            self._update_manual_controls()

    def clear(self, message: str = "Select a formal job to inspect verification.") -> None:
        self._rows.clear()
        self._selected_repetitions.clear()
        self._selected_evidence.clear()
        for tree in (self.case_tree, self.contract_tree, self.repetition_tree, self.evidence_tree, self.ack_tree):
            tree.delete(*tree.get_children())
        self._set_text(self.repetition_text, "")
        self.preview_button.configure(state="disabled")
        self.status_var.set(message)
        self.manual_note_status_var.set(
            "Manual notes are available only for a selected non-blocking manual case."
        )
        self._update_manual_controls()

    def show_rows(self, job_id: str, rows: Sequence[Mapping[str, Any]]) -> None:
        selected = self.case_tree.focus()
        self.clear(f"Formal job {job_id}: {len(rows)} verification case(s)")
        self._rows = {str(row["verification_id"]): row for row in rows}
        for verification_id, row in self._rows.items():
            escalation = "YES" if row.get("escalation") else "no"
            self.case_tree.insert(
                "",
                "end",
                iid=verification_id,
                text=verification_id,
                values=(
                    row.get("title"),
                    ", ".join(row.get("requirement_ids") or []),
                    "yes" if row.get("blocking") else "no",
                    row.get("automation"),
                    row.get("realization_state"),
                    row.get("runtime_status"),
                    row.get("attempt_count"),
                    f"{row.get('repetitions')}/{row.get('repetitions_per_attempt')}",
                    self._compact(row.get("latest_metrics")),
                    self._compact(row.get("failed_assertions")),
                    f"{row.get('stagnation_count')}/{row.get('stagnation_series')}",
                    escalation,
                ),
            )
        target = selected if selected in self._rows else next(iter(self._rows), "")
        if target:
            self.case_tree.selection_set(target)
            self.case_tree.focus(target)
            self._render_case(self._rows[target])

    def _on_case_selected(self, _event: Any) -> None:
        verification_id = self.case_tree.focus()
        row = self._rows.get(verification_id)
        if row is not None:
            self._render_case(row)

    def _render_case(self, row: Mapping[str, Any]) -> None:
        self.contract_tree.delete(*self.contract_tree.get_children())
        contracts = row.get("contracts") or {}
        for group, label in (
            ("oracle", "Oracle"),
            ("coverage_targets", "Coverage target"),
            ("evidence_requirements", "Evidence requirement"),
        ):
            for index, item in enumerate(contracts.get(group, []), 1):
                runtime = item.get("runtime") if isinstance(item, Mapping) else None
                self.contract_tree.insert(
                    "",
                    "end",
                    text=label,
                    values=(
                        item.get("name"),
                        item.get("enforcement"),
                        item.get("description"),
                        self._compact(runtime, limit=220),
                    ),
                )

        self.repetition_tree.delete(*self.repetition_tree.get_children())
        self._selected_repetitions.clear()
        for attempt in row.get("attempts", []):
            for repetition in attempt.get("repetitions", []):
                iid = f"{repetition.get('record_id')}-{attempt.get('attempt')}-{repetition.get('repetition')}"
                self._selected_repetitions[iid] = repetition
                self.repetition_tree.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        attempt.get("attempt"),
                        repetition.get("repetition"),
                        repetition.get("status"),
                        repetition.get("return_code"),
                        repetition.get("elapsed_seconds"),
                        repetition.get("task_id"),
                        repetition.get("worker_run_id"),
                    ),
                )
        self._set_text(self.repetition_text, "No retained repetition is selected.")
        self.evidence_tree.delete(*self.evidence_tree.get_children())
        self._selected_evidence.clear()
        self.preview_button.configure(state="disabled")

        self.ack_tree.delete(*self.ack_tree.get_children())
        for item in row.get("manual_acknowledgements", []):
            self.ack_tree.insert(
                "",
                "end",
                values=(item.get("acknowledged_by"), item.get("created_at"), item.get("note")),
            )
        self._update_manual_controls()

    def _on_repetition_selected(self, _event: Any) -> None:
        repetition = self._selected_repetitions.get(self.repetition_tree.focus())
        if repetition is None:
            return
        details = [
            f"Status: {repetition.get('status')}",
            f"Return code: {repetition.get('return_code')}",
            f"Command: {repetition.get('command')}",
            f"Working directory: {repetition.get('working_directory')}",
            f"Timeout: {repetition.get('timeout_seconds')} seconds",
            f"Metrics: {repetition.get('metrics')}",
            f"Assertions: {repetition.get('assertion_results')}",
            f"Error: {repetition.get('error') or '—'}",
            f"Termination: {repetition.get('termination_details') or '—'}",
            "",
            "Bounded output preview" + (" (truncated)" if repetition.get("output_preview_truncated") else ""),
            str(repetition.get("output_preview") or ""),
        ]
        self._set_text(self.repetition_text, "\n".join(details))
        self.evidence_tree.delete(*self.evidence_tree.get_children())
        self._selected_evidence.clear()
        for index, evidence in enumerate(repetition.get("evidence", []), 1):
            iid = f"evidence-{index}"
            self._selected_evidence[iid] = evidence
            self.evidence_tree.insert(
                "",
                "end",
                iid=iid,
                text=evidence.get("name"),
                values=(
                    evidence.get("kind"),
                    evidence.get("media_type"),
                    evidence.get("size"),
                    evidence.get("artifact_path") or "inline structured value",
                    evidence.get("sha256"),
                ),
            )
        self.preview_button.configure(state="disabled")

    def _on_evidence_selected(self, _event: Any) -> None:
        evidence = self._selected_evidence.get(self.evidence_tree.focus())
        self.preview_button.configure(
            state="normal" if evidence and evidence.get("preview_available") else "disabled"
        )

    def open_selected_evidence_preview(self) -> None:
        evidence = self._selected_evidence.get(self.evidence_tree.focus())
        if evidence is None or not evidence.get("preview_available"):
            messagebox.showinfo(
                "Evidence preview",
                "This artifact is binary or has no bounded text preview. Use the displayed path and SHA-256 metadata.",
                parent=self.frame.winfo_toplevel(),
            )
            return
        window = tk.Toplevel(self.frame)
        window.title(f"Bounded evidence preview — {evidence.get('name')}")
        window.geometry("820x560")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        ttk.Label(
            window,
            text=(
                f"Path: {evidence.get('artifact_path') or 'inline'}\n"
                f"SHA-256: {evidence.get('sha256')}\n"
                f"Size: {evidence.get('size')} bytes"
            ),
        ).grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        preview = self._readonly_text(window, height=20)
        preview.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        suffix = "\n\n[Preview truncated by AI-Loop.]" if evidence.get("preview_truncated") else ""
        self._set_text(preview, str(evidence.get("text_preview") or "") + suffix)

    def _update_manual_controls(self) -> None:
        row = self._rows.get(self.case_tree.focus())
        allowed = bool(row and row.get("can_acknowledge_manual"))
        state = "normal" if allowed else "disabled"
        for widget in (self.ack_actor_entry, self.ack_note_entry, self.ack_button):
            widget.configure(state=state)
        if allowed:
            self.manual_note_status_var.set(
                "This append-only acknowledgement records who/when/note. It does not mark the case passed and does not change manual_pending."
            )
        elif row is not None:
            self.manual_note_status_var.set(
                "Acknowledgement is disabled: automated and blocking cases can only advance through trusted runtime evidence."
            )

    def _record_manual_acknowledgement(self) -> None:
        row = self._rows.get(self.case_tree.focus())
        if row is None or not row.get("can_acknowledge_manual"):
            messagebox.showerror(
                "Manual acknowledgement",
                "Only a non-blocking manual case can receive an acknowledgement note.",
                parent=self.frame.winfo_toplevel(),
            )
            return
        actor = self.ack_actor_var.get().strip()
        note = self.ack_note_var.get().strip()
        if not actor or not note:
            messagebox.showerror(
                "Manual acknowledgement",
                "Enter both who acknowledged the case and an audit note.",
                parent=self.frame.winfo_toplevel(),
            )
            return
        self._acknowledge_command(str(row["verification_id"]), actor, note)


class SpecificationEditor:
    """Resizable staged editor delegating all durable actions to the service."""

    def __init__(
        self,
        parent: Any,
        *,
        service: SpecificationService,
        repository_path: str | Path,
        initial_goal: str = "",
        creator: str = "gui-user",
        run_background: Callable[..., None] | None = None,
        elicitation_provider_factory: Callable[[], StructuredOutputProvider] | None = None,
        implementation_work_factory: (
            Callable[[StoredSpecificationVersion], Callable[[], str]] | None
        ) = None,
        on_implementation_started: Callable[[str], None] | None = None,
        on_close: Callable[[SpecificationEditor], None] | None = None,
    ) -> None:
        if tk is None or ttk is None or filedialog is None or messagebox is None:
            raise RuntimeError("Tkinter is not available; the formal editor cannot be opened")
        self.parent = parent
        self.service = service
        self.repository_path = Path(repository_path).expanduser().resolve()
        self.creator = creator
        self._run_background = run_background
        self._elicitation_provider_factory = elicitation_provider_factory
        self._implementation_work_factory = implementation_work_factory
        self._on_implementation_started = on_implementation_started
        self._on_close_callback = on_close
        self.snapshot: StoredSpecificationVersion | None = None
        self.suggested_choices: list[dict[str, Any]] = []
        self.record = document_to_record(
            SpecificationDocument.empty(summary=initial_goal if initial_goal else "")
        )
        self._busy = False
        self._implementation_job_id: str | None = None
        self._implementation_start_in_flight = False
        self._selector_rows: dict[str, dict[str, Any]] = {}
        self.guidance_labels: dict[str, Any] = {}
        self._guidance_text: dict[str, str] = {}

        self.window = tk.Toplevel(parent)
        self.window.title("Formal Specification")
        self.window.geometry("1120x820")
        self.window.minsize(780, 560)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        self._build_header()
        self._build_tabs()
        self._build_actions()
        self._load_record_into_widgets()
        self._assessment_after_id: str | None = None
        self.window.bind("<KeyRelease>", self._schedule_assessment, add="+")
        self.title_var.trace_add("write", self._schedule_assessment)
        for widget in (
            self.summary_text,
            self.objectives_text,
            self.stakeholders_text,
            *self.scope_widgets.values(),
            self.open_questions_text,
        ):
            widget.edit_modified(False)
            widget.bind("<<Modified>>", self._on_text_modified, add="+")
        self._refresh_assessment()
        self.refresh_specifications()

    def _build_header(self) -> None:
        header = ttk.Frame(self.window, padding=10)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Repository").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.repository_var = tk.StringVar(value=str(self.repository_path))
        ttk.Entry(header, textvariable=self.repository_var, state="readonly").grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Label(header, text="Open specification").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=(7, 0)
        )
        self.selector_var = tk.StringVar(value="New specification")
        self.selector = ttk.Combobox(
            header, textvariable=self.selector_var, state="readonly", values=("New specification",)
        )
        self.selector.grid(row=1, column=1, sticky="ew", pady=(7, 0))
        self.selector.bind("<<ComboboxSelected>>", self._on_selector_changed)
        file_actions = ttk.Frame(header)
        file_actions.grid(row=1, column=2, sticky="e", padx=(8, 0), pady=(7, 0))
        self.load_example_button = ttk.Button(
            file_actions,
            text="Load example",
            command=self.load_example,
        )
        self.load_example_button.pack(side="left")
        self.test_specification_button = ttk.Button(
            file_actions,
            text="Test specification",
            command=self.test_specification,
        )
        self.test_specification_button.pack(side="left", padx=(6, 0))
        self.save_specification_button = ttk.Button(
            file_actions,
            text="Save specification",
            command=self.save_specification,
        )
        self.save_specification_button.pack(side="left", padx=(6, 0))
        self.load_specification_button = ttk.Button(
            file_actions,
            text="Load specification",
            command=self.load_specification,
        )
        self.load_specification_button.pack(side="left", padx=(6, 0))
        self.status_var = tk.StringVar(value="New unsaved draft")
        ttk.Label(header, textvariable=self.status_var).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(7, 0)
        )
        process_frame = ttk.LabelFrame(header, text="From specification to DONE", padding=7)
        process_frame.grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )
        process_frame.columnconfigure(0, weight=1)
        self.process_overview_label = ttk.Label(
            process_frame,
            text=PROCESS_OVERVIEW_TEXT,
            wraplength=1040,
            justify="left",
        )
        self.process_overview_label.grid(row=0, column=0, sticky="ew")

    def _build_tabs(self) -> None:
        self.notebook = ttk.Notebook(self.window)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=10)
        self.tabs: dict[str, Any] = {}
        for stage in EDITOR_STAGES:
            frame = ttk.Frame(self.notebook, padding=10)
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            self.notebook.add(frame, text=f"  {stage}")
            self.tabs[stage] = frame
        self._build_overview_tab()
        self._build_scope_tab()
        self._build_collection_tab("Use Cases", "use_cases", USE_CASE_FIELDS, ("id", "title"))
        self._build_collection_tab(
            "Requirements", "requirements", REQUIREMENT_FIELDS, ("id", "priority", "title")
        )
        self._build_collection_tab("Risks", "risks", RISK_FIELDS, ("id", "severity", "title"))
        self._build_collection_tab(
            "Verification", "verification", VERIFICATION_FIELDS, ("id", "automation", "title")
        )
        self._build_choices_tab()
        self._build_review_tab()

    def _field_label(self, parent: Any, row: int, key: str, label: str) -> None:
        label_frame = ttk.Frame(parent)
        label_frame.grid(row=row, column=0, sticky="new", padx=(0, 12), pady=4)
        ttk.Label(label_frame, text=label).pack(anchor="w")
        guidance = ttk.Label(
            label_frame,
            text=_field_guidance(key),
            wraplength=260,
            justify="left",
        )
        guidance.pack(anchor="w", pady=(2, 0))
        self.guidance_labels[key] = guidance
        self._guidance_text[key] = _field_guidance(key)

    def _labeled_text(
        self,
        parent: Any,
        row: int,
        key: str,
        label: str,
        *,
        height: int = 4,
    ) -> Any:
        self._field_label(parent, row, key, label)
        widget = tk.Text(parent, height=height, wrap="word")
        widget.grid(row=row, column=1, sticky="nsew", pady=4)
        parent.rowconfigure(row, weight=1)
        return widget

    def _build_overview_tab(self) -> None:
        tab = self.tabs["Overview"]
        tab.columnconfigure(1, weight=1)
        self._field_label(tab, 0, "title", "Title")
        self.title_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.title_var).grid(row=0, column=1, sticky="ew", pady=4)
        self.summary_text = self._labeled_text(tab, 1, "summary", "Summary", height=7)
        self.objectives_text = self._labeled_text(
            tab, 2, "objectives", "Objectives (one per line)"
        )
        self.stakeholders_text = self._labeled_text(
            tab, 3, "stakeholders", "Stakeholders (one per line)"
        )

    def _build_scope_tab(self) -> None:
        tab = self.tabs["Scope"]
        tab.columnconfigure(1, weight=1)
        self.scope_widgets: dict[str, Any] = {}
        for row, (key, label) in enumerate(
            (
                ("in_scope", "Included scope"),
                ("out_of_scope", "Excluded scope"),
                ("assumptions", "Assumptions"),
                ("constraints", "Constraints"),
                ("dependencies", "Dependencies"),
            )
        ):
            self.scope_widgets[key] = self._labeled_text(
                tab, row, key, f"{label} (one per line)"
            )

    def _build_collection_tab(
        self,
        stage: str,
        key: str,
        fields: Sequence[_Field],
        columns: Sequence[str],
    ) -> None:
        tab = self.tabs[stage]
        tab.rowconfigure(0, weight=0)
        tab.rowconfigure(1, weight=1)
        guidance = ttk.Label(
            tab,
            text=_field_guidance(key),
            wraplength=1000,
            justify="left",
        )
        guidance.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.guidance_labels[key] = guidance
        self._guidance_text[key] = _field_guidance(key)
        table_frame = ttk.Frame(tab)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(table_frame, columns=tuple(columns), show="headings", selectmode="browse")
        for column in columns:
            tree.heading(column, text=column.replace("_", " ").title())
            tree.column(column, width=130 if column != "title" else 300, stretch=True)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        actions = ttk.Frame(table_frame)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(
            actions, text="Add", command=lambda: self._edit_collection(key, fields, None)
        ).pack(side="left")
        ttk.Button(
            actions, text="Edit", command=lambda: self._edit_selected_collection(key, fields)
        ).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Remove", command=lambda: self._remove_selected(key)).pack(
            side="left", padx=(6, 0)
        )
        tree.bind("<Double-1>", lambda _event: self._edit_selected_collection(key, fields))
        self.collection_trees[key] = (tree, tuple(columns))

    def _build_choices_tab(self) -> None:
        tab = self.tabs["Choices"]
        tab.rowconfigure(0, weight=0)
        tab.rowconfigure(1, weight=2)
        tab.rowconfigure(2, weight=1)
        choices_guidance = ttk.Label(
            tab,
            text=(
                _field_guidance("decisions")
                + "  "
                + _field_guidance("open_questions")
            ),
            wraplength=1000,
            justify="left",
        )
        choices_guidance.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.guidance_labels["decisions"] = choices_guidance
        self.guidance_labels["open_questions"] = choices_guidance
        self._guidance_text["decisions"] = _field_guidance("decisions")
        self._guidance_text["open_questions"] = _field_guidance("open_questions")
        materialized = ttk.LabelFrame(tab, text="User-resolved specification decisions", padding=6)
        materialized.grid(row=1, column=0, sticky="nsew")
        materialized.columnconfigure(0, weight=1)
        materialized.rowconfigure(0, weight=1)
        tree = ttk.Treeview(
            materialized, columns=("topic", "decision"), show="headings", selectmode="browse"
        )
        tree.heading("topic", text="Topic")
        tree.heading("decision", text="Selected decision")
        tree.column("topic", width=180)
        tree.column("decision", width=500)
        tree.grid(row=0, column=0, sticky="nsew")
        actions = ttk.Frame(materialized)
        actions.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(actions, text="Add", command=lambda: self._edit_collection("decisions", DECISION_FIELDS, None)).pack(side="left")
        ttk.Button(actions, text="Edit", command=lambda: self._edit_selected_collection("decisions", DECISION_FIELDS)).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Remove", command=lambda: self._remove_selected("decisions")).pack(side="left", padx=(6, 0))
        self.collection_trees["decisions"] = (tree, ("topic", "selected_decision"))

        lower = ttk.PanedWindow(tab, orient="horizontal")
        lower.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        questions = ttk.LabelFrame(lower, text="Open questions (one per line)", padding=6)
        suggested = ttk.LabelFrame(lower, text="Suggested choices", padding=6)
        lower.add(questions, weight=1)
        lower.add(suggested, weight=2)
        self.open_questions_text = tk.Text(questions, height=7, wrap="word")
        self.open_questions_text.pack(fill="both", expand=True)
        suggested.columnconfigure(0, weight=1)
        suggested.rowconfigure(0, weight=1)
        self.suggested_tree = ttk.Treeview(
            suggested,
            columns=("status", "blocking", "topic", "question"),
            show="headings",
            selectmode="browse",
        )
        for column in ("status", "blocking", "topic", "question"):
            self.suggested_tree.heading(column, text=column.title())
        self.suggested_tree.column("status", width=80)
        self.suggested_tree.column("blocking", width=70)
        self.suggested_tree.column("topic", width=130)
        self.suggested_tree.column("question", width=320)
        self.suggested_tree.grid(row=0, column=0, sticky="nsew")
        self.resolve_button = ttk.Button(
            suggested, text="Resolve selected choice", command=self._resolve_selected_choice
        )
        self.resolve_button.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(
            suggested,
            text="Analyze a clean stored draft to discover additional unresolved choices.",
        ).grid(row=2, column=0, sticky="w", pady=(5, 0))

    def _build_review_tab(self) -> None:
        tab = self.tabs["Review"]
        tab.rowconfigure(0, weight=0)
        tab.rowconfigure(1, weight=1)
        ttk.Label(
            tab,
            text=(
                "Review lists structural and approval issues by owning stage. Resolve each issue, "
                "save the draft, submit it for review, and approve only when the completion contract "
                "is accurate. Approval itself does not start implementation."
            ),
            wraplength=1000,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.review_tree = ttk.Treeview(
            tab,
            columns=("owning_stage", "path", "severity", "message"),
            show="headings",
        )
        for column, width in (
            ("owning_stage", 110),
            ("path", 240),
            ("severity", 80),
            ("message", 560),
        ):
            self.review_tree.heading(column, text=column.replace("_", " ").title())
            self.review_tree.column(column, width=width, stretch=column == "message")
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.review_tree.yview)
        self.review_tree.configure(yscrollcommand=scrollbar.set)
        self.review_tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

    def _build_actions(self) -> None:
        footer = ttk.Frame(self.window, padding=10)
        footer.grid(row=2, column=0, sticky="ew")
        self.deferred_var = tk.StringVar(
            value=(
                "Approve the specification to enable implementation. Starting compiles and "
                "pins this exact version before the controller plans any work."
            )
        )
        ttk.Label(footer, textvariable=self.deferred_var).pack(side="left")
        self.close_button = ttk.Button(footer, text="Close", command=self.close)
        self.close_button.pack(side="right")
        self.start_button = ttk.Button(
            footer,
            text="Start Implementation",
            command=self.start_implementation,
            state="disabled",
        )
        self.start_button.pack(side="right", padx=(0, 6))
        self.approve_button = ttk.Button(footer, text="Approve", command=self.approve)
        self.approve_button.pack(side="right", padx=(0, 6))
        self.return_button = ttk.Button(footer, text="Return to Draft", command=self.return_to_draft)
        self.return_button.pack(side="right", padx=(0, 6))
        self.submit_button = ttk.Button(footer, text="Submit for Review", command=self.submit_for_review)
        self.submit_button.pack(side="right", padx=(0, 6))
        self.analyze_button = ttk.Button(footer, text="Analyze", command=self.analyze)
        self.analyze_button.pack(side="right", padx=(0, 6))
        self.save_button = ttk.Button(footer, text="Save Draft", command=self.save_draft)
        self.save_button.pack(side="right", padx=(0, 6))
        self.action_buttons = (
            self.save_button,
            self.submit_button,
            self.return_button,
            self.approve_button,
            self.analyze_button,
            self.start_button,
        )

    @property
    def collection_trees(self) -> dict[str, tuple[Any, tuple[str, ...]]]:
        if not hasattr(self, "_collection_trees"):
            self._collection_trees: dict[str, tuple[Any, tuple[str, ...]]] = {}
        return self._collection_trees

    def _set_text(self, widget: Any, value: str) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", value)

    def _load_record_into_widgets(self) -> None:
        self.title_var.set(self.record["title"])
        self._set_text(self.summary_text, self.record["summary"])
        self._set_text(self.objectives_text, format_list_text(self.record["objectives"]))
        self._set_text(self.stakeholders_text, format_list_text(self.record["stakeholders"]))
        for key, widget in self.scope_widgets.items():
            self._set_text(widget, format_list_text(self.record[key]))
        self._set_text(self.open_questions_text, format_list_text(self.record["open_questions"]))
        self._refresh_collection_trees()

    def _collect_record(self) -> dict[str, Any]:
        result = copy.deepcopy(self.record)
        result["title"] = self.title_var.get()
        result["summary"] = self.summary_text.get("1.0", "end-1c")
        result["objectives"] = list(parse_list_text(self.objectives_text.get("1.0", "end-1c")))
        result["stakeholders"] = list(parse_list_text(self.stakeholders_text.get("1.0", "end-1c")))
        for key, widget in self.scope_widgets.items():
            result[key] = list(parse_list_text(widget.get("1.0", "end-1c")))
        result["open_questions"] = list(
            parse_list_text(self.open_questions_text.get("1.0", "end-1c"))
        )
        return result

    def _current_document(self) -> SpecificationDocument:
        return record_to_document(self._collect_record(), worktree=self.repository_path)

    def _edit_collection(
        self, key: str, fields: Sequence[_Field], index: int | None
    ) -> None:
        initial = None if index is None else self.record[key][index]
        if key == "verification":
            initial = _verification_for_dialog(initial)
        dialog = _RecordDialog(
            self.window,
            f"Edit {key.replace('_', ' ').title()}",
            fields,
            initial,
            field_path_prefix=key,
            feedback_provider=lambda draft: self._collection_record_feedback(
                key, index, draft
            ),
        )
        result = dialog.show()
        if result is None:
            return
        if key == "verification":
            result = _verification_from_dialog(result)
        if index is None:
            self.record[key].append(result)
        else:
            self.record[key][index] = result
        self._refresh_collection_trees()
        self._refresh_assessment()

    def _selected_index(self, key: str) -> int | None:
        tree, _columns = self.collection_trees[key]
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("Select a record", "Select a record first.", parent=self.window)
            return None
        return int(selected[0])

    def _edit_selected_collection(self, key: str, fields: Sequence[_Field]) -> None:
        index = self._selected_index(key)
        if index is not None:
            self._edit_collection(key, fields, index)

    def _remove_selected(self, key: str) -> None:
        index = self._selected_index(key)
        if index is None:
            return
        del self.record[key][index]
        self._refresh_collection_trees()
        self._refresh_assessment()

    def _refresh_collection_trees(self) -> None:
        for key, (tree, columns) in self.collection_trees.items():
            tree.delete(*tree.get_children())
            for index, record in enumerate(self.record[key]):
                values = tuple(record.get(column, "") for column in columns)
                tree.insert("", "end", iid=str(index), values=values)

    def _refresh_suggested_choices(self) -> None:
        self.suggested_tree.delete(*self.suggested_tree.get_children())
        for decision in self.suggested_choices:
            self.suggested_tree.insert(
                "",
                "end",
                iid=decision["id"],
                values=(
                    decision["status"],
                    "yes" if decision["blocking"] else "no",
                    decision["topic"],
                    decision["question"],
                ),
            )

    def _unresolved_blocking_count(self) -> int:
        return sum(
            1
            for choice in self.suggested_choices
            if choice.get("blocking") and choice.get("status") == "unresolved"
        )

    def _refresh_assessment(self) -> None:
        record = self._collect_record()
        try:
            document = record_to_document(record, worktree=self.repository_path)
            assessment = assess_specification(
                document,
                worktree=self.repository_path,
                unresolved_blocking_decisions=self._unresolved_blocking_count(),
            )
        except Exception as exc:
            assessment = StageAssessment(
                issues=(WorkflowIssue("Review", "editor", "error", str(exc)),),
                structurally_valid=False,
                approval_ready=False,
            )
        self.assessment = assessment
        routed = route_issues_to_tabs(assessment)
        self.field_feedback = compute_field_feedback(
            record,
            worktree=self.repository_path,
            assessment=assessment,
        )
        self._render_field_feedback()
        feedback_keys_by_stage = {
            "Overview": ("title", "summary", "objectives", "stakeholders"),
            "Scope": ("in_scope", "out_of_scope", "assumptions", "constraints", "dependencies"),
            "Use Cases": ("use_cases",),
            "Requirements": ("requirements",),
            "Risks": ("risks",),
            "Verification": ("verification",),
            "Choices": ("decisions", "open_questions"),
            "Review": (),
        }
        for stage, frame in self.tabs.items():
            advisory_attention = any(
                self.field_feedback[key].health in {"weak", "needs_attention"}
                for key in feedback_keys_by_stage[stage]
            )
            marker = "!" if routed[stage] or advisory_attention else " "
            self.notebook.tab(frame, text=f"{marker} {stage}")
        self.review_tree.delete(*self.review_tree.get_children())
        for index, issue in enumerate(assessment.issues):
            self.review_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(issue.owning_stage, issue.path, issue.severity, issue.message),
            )
        self._update_actions()

    def _render_field_feedback(self) -> None:
        rendered_widgets: set[str] = set()
        for key, label in self.guidance_labels.items():
            widget_name = str(label)
            if widget_name in rendered_widgets:
                continue
            rendered_widgets.add(widget_name)
            related_keys = tuple(
                candidate
                for candidate, candidate_label in self.guidance_labels.items()
                if candidate_label is label
            )
            guidance = "  ".join(self._guidance_text[candidate] for candidate in related_keys)
            messages = [
                self.field_feedback[candidate].message
                for candidate in related_keys
                if candidate in self.field_feedback
            ]
            feedback_text = "  ".join(messages)
            label.configure(
                text=f"{guidance}\n\nLive feedback: {feedback_text}" if feedback_text else guidance
            )

    def _collection_record_feedback(
        self,
        key: str,
        index: int | None,
        dialog_record: Mapping[str, Any],
    ) -> dict[str, FieldSemanticFeedback]:
        candidate = self._collect_record()
        item = dict(dialog_record)
        if key == "verification":
            item = _verification_from_dialog(item)
        values = list(candidate[key])
        target_index = len(values) if index is None else index
        if index is None:
            values.append(item)
        else:
            values[index] = item
        candidate[key] = values
        computed = compute_field_feedback(candidate, worktree=self.repository_path)
        prefix = f"{key}[{target_index}]."
        return {
            path.removeprefix(prefix).removeprefix("validation_loop."): feedback
            for path, feedback in computed.items()
            if path.startswith(prefix)
        }

    def _schedule_assessment(self, *_event: Any) -> None:
        if self._assessment_after_id is not None:
            try:
                self.window.after_cancel(self._assessment_after_id)
            except tk.TclError:
                pass
        self._assessment_after_id = self.window.after(100, self._finish_scheduled_assessment)

    def _on_text_modified(self, event: Any) -> None:
        if event.widget.edit_modified():
            event.widget.edit_modified(False)
            self._schedule_assessment(event)

    def _finish_scheduled_assessment(self) -> None:
        self._assessment_after_id = None
        self._refresh_assessment()

    def _has_unsaved_edits(self) -> bool:
        if self.snapshot is None:
            return True
        try:
            return self._current_document().canonical_json() != self.snapshot.document.canonical_json()
        except Exception:
            return True

    def _update_actions(self) -> None:
        status = self.snapshot.status if self.snapshot else "new"
        dirty = self._has_unsaved_edits()
        states = {
            self.save_button: status in {"new", "draft", "approved"},
            self.submit_button: status == "draft" and not dirty,
            self.return_button: status == "review",
            self.approve_button: (
                status == "review" and not dirty and self.assessment.approval_ready
            ),
            self.analyze_button: (
                status == "draft"
                and not dirty
                and self._elicitation_provider_factory is not None
            ),
            self.start_button: (
                status == "approved"
                and not dirty
                and self._implementation_work_factory is not None
                and self._implementation_job_id is None
                and not self._implementation_start_in_flight
            ),
        }
        for button, enabled in states.items():
            button.configure(state="normal" if enabled and not self._busy else "disabled")
        self.selector.configure(state="disabled" if self._busy else "readonly")
        for button in (
            self.load_example_button,
            self.test_specification_button,
            self.save_specification_button,
            self.load_specification_button,
        ):
            button.configure(state="disabled" if self._busy else "normal")
        self.resolve_button.configure(
            state="normal"
            if not self._busy and any(c.get("status") == "unresolved" for c in self.suggested_choices)
            else "disabled"
        )

    def _set_busy(self, busy: bool, status: str | None = None) -> None:
        self._busy = busy
        if status:
            self.status_var.set(status)
        self._update_actions()

    def _background(
        self,
        work: Callable[[], Any],
        done: Callable[[Any, str | None], None],
        *,
        label: str,
    ) -> None:
        self._set_busy(True, f"{label}…")

        def finish(result: Any, error: str | None) -> None:
            self._set_busy(False)
            done(result, error)

        if self._run_background is not None:
            self._run_background(
                work,
                finish,
                name=f"ai-loop-spec-{label.lower().replace(' ', '-')}",
                label=label,
            )
            return

        def runner() -> None:
            try:
                result, error = work(), None
            except Exception as exc:  # pragma: no cover - exercised through injected runners
                result, error = None, str(exc) or repr(exc)
            try:
                self.window.after(0, lambda: finish(result, error))
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(target=runner, name="ai-loop-specification", daemon=True).start()

    def refresh_specifications(self, *, select_id: str | None = None) -> None:
        repository = self.repository_path

        def done(result: Any, error: str | None) -> None:
            if error:
                messagebox.showerror("Specification list failed", error, parent=self.window)
                self._show_snapshot_status()
                return
            rows = list(result)
            self._selector_rows = {
                self._selector_label(row): row for row in rows
            }
            values = ("New specification", *self._selector_rows)
            self.selector.configure(values=values)
            if select_id is not None:
                for label, row in self._selector_rows.items():
                    if row["id"] == select_id:
                        self.selector_var.set(label)
                        break
            self._show_snapshot_status()

        self._background(
            lambda: self.service.list(repository),
            done,
            label="Loading formal specifications",
        )

    @staticmethod
    def _selector_label(row: Mapping[str, Any]) -> str:
        return f"{row['title'] or '(untitled)'} — {row['id']} v{row['current_version']} [{row['status']}]"

    def load_example(self) -> None:
        """Replace the editor contents with a new, unsaved worked example."""

        self.snapshot = None
        self._implementation_job_id = None
        self.suggested_choices = []
        self.selector_var.set("New specification")
        self.record = document_to_record(
            worked_example_document(worktree=self.repository_path)
        )
        self._load_record_into_widgets()
        self._refresh_suggested_choices()
        self.status_var.set(
            "Worked example loaded — editable, unsaved, and not submitted or approved"
        )
        self.deferred_var.set(
            "Save this example as a draft, resolve Review issues, submit it, and approve it "
            "before Start Implementation can be enabled."
        )
        self._refresh_assessment()

    def test_specification(self) -> None:
        """Analyze the complete current draft without changing workflow state."""

        record = self._collect_record()
        suggestions = analyze_specification(
            record,
            worktree=self.repository_path,
            unresolved_blocking_decisions=self._unresolved_blocking_count(),
        )
        _SpecificationSuggestionsDialog(self.window, suggestions).show()

    def save_specification(self) -> None:
        """Save the current editor draft to a user-selected JSON file."""

        selected = filedialog.asksaveasfilename(
            parent=self.window,
            title="Save specification",
            defaultextension=".json",
            filetypes=(("JSON files", "*.json"), ("All files", "*")),
            initialfile="specification.json",
        )
        if not selected:
            return
        try:
            # A disk save is a user checkpoint, not a workflow transition.  It
            # must preserve an unfinished draft even while live validation is
            # still reporting required fields or semantic issues.
            record = self._collect_record()
            Path(selected).write_bytes(specification_to_savefile_bytes(record))
        except Exception as exc:
            messagebox.showerror(
                "Save specification failed", str(exc), parent=self.window
            )
            return
        self.status_var.set(f"Specification saved to {selected}")

    def load_specification(self) -> None:
        """Load a saved draft into the editor without changing workflow state."""

        selected = filedialog.askopenfilename(
            parent=self.window,
            title="Load specification",
            filetypes=(("JSON files", "*.json"), ("All files", "*")),
        )
        if not selected:
            return
        try:
            record = savefile_to_record(Path(selected).read_bytes())
        except Exception as exc:
            messagebox.showerror(
                "Load specification failed", str(exc), parent=self.window
            )
            return

        self.snapshot = None
        self._implementation_job_id = None
        self.suggested_choices = []
        self.selector_var.set("New specification")
        self.record = record
        self._load_record_into_widgets()
        self._refresh_suggested_choices()
        self.status_var.set(
            "Specification loaded from file — editable, unsaved, and not submitted or approved"
        )
        self.deferred_var.set(
            "Save this imported specification as a draft, resolve Review issues, submit it, "
            "and approve it before Start Implementation can be enabled."
        )
        self._refresh_assessment()

    def _on_selector_changed(self, _event: Any = None) -> None:
        label = self.selector_var.get()
        if label == "New specification":
            self.snapshot = None
            self._implementation_job_id = None
            self.suggested_choices = []
            self.record = document_to_record(SpecificationDocument.empty())
            self._load_record_into_widgets()
            self._refresh_suggested_choices()
            self.status_var.set("New unsaved draft")
            self._refresh_assessment()
            return
        row = self._selector_rows.get(label)
        if row is None:
            return

        def work() -> tuple[StoredSpecificationVersion, list[dict[str, Any]]]:
            return self.service.load(row["id"]), self.service.list_decisions(row["id"])

        def done(result: Any, error: str | None) -> None:
            if error:
                messagebox.showerror("Open specification failed", error, parent=self.window)
                self._show_snapshot_status()
                return
            self.snapshot, self.suggested_choices = result
            self._implementation_job_id = None
            self.record = document_to_record(self.snapshot.document)
            self._load_record_into_widgets()
            self._refresh_suggested_choices()
            self._show_snapshot_status()
            self._refresh_assessment()

        self._background(work, done, label="Opening formal specification")

    def _show_snapshot_status(self) -> None:
        if self.snapshot is None:
            self.status_var.set("New unsaved draft")
        else:
            self.status_var.set(
                f"{self.snapshot.specification_id} · version {self.snapshot.version} · "
                f"status {self.snapshot.status} · SHA-256 {self.snapshot.canonical_content_hash[:12]}…"
            )
        self._update_actions()

    def save_draft(self) -> None:
        try:
            document = self._current_document()
        except Exception as exc:
            messagebox.showerror("Save Draft", str(exc), parent=self.window)
            self._refresh_assessment()
            return
        current_id = self.snapshot.specification_id if self.snapshot else None

        def work() -> StoredSpecificationVersion:
            if current_id is None:
                return create_draft(
                    self.service,
                    self.repository_path,
                    document,
                    creator=self.creator,
                    change_summary="Initial GUI draft",
                )
            return save_draft(
                self.service,
                current_id,
                document,
                creator=self.creator,
                change_summary="GUI draft revision",
            )

        self._run_lifecycle(work, "Save Draft")

    def analyze(self) -> None:
        """Run read-only elicitation away from Tk, then open the modal review."""

        if self.snapshot is None:
            messagebox.showerror(
                "Analyze",
                "Save this specification as a draft before running AI analysis.",
                parent=self.window,
            )
            return
        if self.snapshot.status != "draft":
            messagebox.showerror(
                "Analyze",
                "AI analysis requires a stored draft. Return to Draft before analyzing.",
                parent=self.window,
            )
            return
        if self._has_unsaved_edits():
            messagebox.showerror(
                "Analyze",
                "Save the current editor content as a draft revision before analyzing it.",
                parent=self.window,
            )
            return
        if self._elicitation_provider_factory is None:
            messagebox.showerror(
                "Analyze",
                "No structured-output controller provider is configured for this editor.",
                parent=self.window,
            )
            return
        try:
            # Provider settings are a Tk-owned snapshot and must be read before
            # the background thread starts.
            provider = self._elicitation_provider_factory()
        except Exception as exc:
            messagebox.showerror("Analyze", str(exc), parent=self.window)
            return
        source = self.snapshot

        def work() -> CompletedElicitation:
            return ElicitationEngine(self.service, provider).analyze(
                source.specification_id,
                source.version,
            )

        def done(result: Any, error: str | None) -> None:
            if error:
                messagebox.showerror(
                    "AI analysis failed",
                    f"{error}\n\nThe stored draft was not changed. Correct the issue and run Analyze again.",
                    parent=self.window,
                )
                self._show_snapshot_status()
                return
            completed = result
            action = _ElicitationReviewDialog(
                self.window,
                completed=completed,
                source=source,
            ).show()
            if action is None:
                self.status_var.set(
                    f"Analysis {completed.stored.analysis_id} retained without application"
                )
                self._update_actions()
                return
            self._apply_elicitation(completed, action)

        self._background(work, done, label="Analyzing formal specification")

    def _apply_elicitation(
        self,
        completed: CompletedElicitation,
        application_mode: str,
    ) -> None:
        def work() -> tuple[Any, list[dict[str, Any]]]:
            applied = apply_elicitation_analysis(
                self.service,
                completed.stored.analysis_id,
                application_mode=application_mode,
                creator=self.creator,
            )
            choices = self.service.list_decisions(applied.snapshot.specification_id)
            return applied, choices

        def done(result: Any, error: str | None) -> None:
            if error:
                messagebox.showerror(
                    "Apply AI analysis",
                    f"{error}\n\nNo analysis changes were applied. Reopen the current draft "
                    "and run Analyze again if it changed.",
                    parent=self.window,
                )
                self._show_snapshot_status()
                self._refresh_assessment()
                return
            applied, choices = result
            self.snapshot = applied.snapshot
            self.suggested_choices = choices
            self.record = document_to_record(applied.snapshot.document)
            self._load_record_into_widgets()
            self._refresh_suggested_choices()
            self._show_snapshot_status()
            self._refresh_assessment()
            mode_label = "Choices Only" if application_mode == "choices_only" else "Apply All"
            messagebox.showinfo(
                "AI analysis applied",
                f"{mode_label} created draft version {applied.snapshot.version}.\n"
                f"Analysis: {applied.analysis.analysis_id}\n"
                f"Specification additions: {len(applied.additions)}\n"
                f"Proposed choices created: {applied.decisions_created}",
                parent=self.window,
            )
            self.refresh_specifications(select_id=applied.snapshot.specification_id)

        self._background(work, done, label="Applying AI analysis")

    def submit_for_review(self) -> None:
        if self.snapshot is None:
            return
        if self._has_unsaved_edits():
            messagebox.showerror(
                "Submit for Review",
                "Save the current draft revision before submitting it for review.",
                parent=self.window,
            )
            return
        self._run_lifecycle(
            lambda: submit_for_review(self.service, self.snapshot.specification_id),
            "Submit for Review",
        )

    def return_to_draft(self) -> None:
        if self.snapshot is None:
            return
        self._run_lifecycle(
            lambda: return_to_draft(self.service, self.snapshot.specification_id),
            "Return to Draft",
        )

    def approve(self) -> None:
        self._refresh_assessment()
        if self.snapshot is None or not self.assessment.approval_ready:
            messagebox.showerror(
                "Approve",
                "Resolve every Review issue and blocking suggested choice before approval.",
                parent=self.window,
            )
            return
        if self._has_unsaved_edits():
            messagebox.showerror(
                "Approve",
                "The review version differs from the editor. Return to Draft and save a revision first.",
                parent=self.window,
            )
            return
        self._run_lifecycle(
            lambda: approve(
                self.service, self.snapshot.specification_id, approved_by=self.creator
            ),
            "Approve",
        )

    def start_implementation(self) -> None:
        """Compile, pin, and enqueue the approved snapshot through the GUI job path."""

        if self._implementation_start_in_flight:
            messagebox.showinfo(
                "Start Implementation",
                "Implementation is already being created; wait for it to finish.",
                parent=self.window,
            )
            return
        if self._implementation_job_id is not None:
            messagebox.showinfo(
                "Start Implementation",
                f"Implementation already started as {self._implementation_job_id}.",
                parent=self.window,
            )
            return
        if (
            self.snapshot is None
            or self.snapshot.status != "approved"
            or self._implementation_work_factory is None
        ):
            messagebox.showerror(
                "Start Implementation",
                "Approve this specification before starting implementation.",
                parent=self.window,
            )
            return
        if self._has_unsaved_edits():
            messagebox.showerror(
                "Start Implementation",
                "The approved version differs from the editor. Reload it before starting.",
                parent=self.window,
            )
            return
        snapshot = self.snapshot
        self._implementation_start_in_flight = True
        self._update_actions()
        try:
            work = self._implementation_work_factory(snapshot)
        except Exception as exc:
            self._implementation_start_in_flight = False
            self._update_actions()
            messagebox.showerror(
                "Start Implementation", str(exc), parent=self.window
            )
            return

        def done(job_id: Any, error: str | None) -> None:
            self._implementation_start_in_flight = False
            if error:
                messagebox.showerror(
                    "Start Implementation", error, parent=self.window
                )
                self._show_snapshot_status()
                return
            self._implementation_job_id = str(job_id)
            self.status_var.set(
                f"Implementation started as {self._implementation_job_id}; "
                f"{snapshot.specification_id} v{snapshot.version} is pinned."
            )
            self.deferred_var.set(
                f"Implementation job {self._implementation_job_id} is queued for controller planning."
            )
            self._update_actions()
            if self._on_implementation_started is not None:
                self._on_implementation_started(self._implementation_job_id)
            messagebox.showinfo(
                "Implementation started",
                f"Created {self._implementation_job_id} and queued its initial PLAN task.",
                parent=self.window,
            )

        self._background(work, done, label="Start Implementation")

    def _run_lifecycle(
        self, work: Callable[[], StoredSpecificationVersion], label: str
    ) -> None:
        def done(result: Any, error: str | None) -> None:
            if error:
                messagebox.showerror(label, error, parent=self.window)
                self._show_snapshot_status()
                self._refresh_assessment()
                return
            self.snapshot = result
            self.record = document_to_record(result.document)
            self._load_record_into_widgets()
            self._show_snapshot_status()
            self._refresh_assessment()
            self.refresh_specifications(select_id=result.specification_id)

        self._background(work, done, label=label)

    def _resolve_selected_choice(self) -> None:
        selected = self.suggested_tree.selection()
        if not selected or self.snapshot is None:
            messagebox.showinfo("Resolve choice", "Select an unresolved choice first.", parent=self.window)
            return
        decision = next(
            (item for item in self.suggested_choices if item["id"] == selected[0]), None
        )
        if decision is None or decision["status"] != "unresolved":
            return
        options = decision.get("options", [])
        option_names = tuple(
            str(item.get("name", item.get("label", "")))
            for item in options
            if isinstance(item, Mapping)
        )
        fields = (
            _Field("selected_option", "Selected option", "enum", option_names, option_names[0] if option_names else ""),
            _Field("rationale", "Rationale", "text"),
            _Field("deferred", "Defer as non-blocking", "bool", default=False),
        )
        result = _RecordDialog(self.window, f"Resolve: {decision['topic']}", fields).show()
        if result is None:
            return

        def work() -> tuple[StoredSpecificationVersion, list[dict[str, Any]]]:
            self.service.resolve_decision(
                self.snapshot.specification_id,
                decision["id"],
                selected_option=result["selected_option"],
                rationale=result["rationale"],
                deferred=result["deferred"],
            )
            return (
                self.service.load(self.snapshot.specification_id),
                self.service.list_decisions(self.snapshot.specification_id),
            )

        def done(value: Any, error: str | None) -> None:
            if error:
                messagebox.showerror("Resolve choice", error, parent=self.window)
                self._show_snapshot_status()
                return
            self.snapshot, self.suggested_choices = value
            self._refresh_suggested_choices()
            self._show_snapshot_status()
            self._refresh_assessment()

        self._background(work, done, label="Resolve formal choice")

    def close(self) -> None:
        if self._busy:
            messagebox.showinfo(
                "Formal Specification",
                "Wait for the current specification operation to finish.",
                parent=self.window,
            )
            return
        self.window.destroy()
        if self._on_close_callback is not None:
            self._on_close_callback(self)


def open_specification_editor(
    parent: Any,
    *,
    service: SpecificationService,
    repository_path: str | Path,
    initial_goal: str = "",
    creator: str = "gui-user",
    run_background: Callable[..., None] | None = None,
    elicitation_provider_factory: Callable[[], StructuredOutputProvider] | None = None,
    implementation_work_factory: (
        Callable[[StoredSpecificationVersion], Callable[[], str]] | None
    ) = None,
    on_implementation_started: Callable[[str], None] | None = None,
    on_close: Callable[[SpecificationEditor], None] | None = None,
) -> SpecificationEditor:
    """Open and return a formal editor initialized from the Quick Goal fields."""

    return SpecificationEditor(
        parent,
        service=service,
        repository_path=repository_path,
        initial_goal=initial_goal,
        creator=creator,
        run_background=run_background,
        elicitation_provider_factory=elicitation_provider_factory,
        implementation_work_factory=implementation_work_factory,
        on_implementation_started=on_implementation_started,
        on_close=on_close,
    )


__all__ = [
    "FieldSemanticFeedback",
    "MetricAssertionParseError",
    "PROCESS_OVERVIEW_TEXT",
    "SPECIFICATION_FIELD_EXAMPLES",
    "SPECIFICATION_FIELD_GUIDANCE",
    "SPECIFICATION_SAVEFILE_SCHEMA",
    "SPECIFICATION_SAVEFILE_VERSION",
    "SpecificationSavefileError",
    "SpecificationEditor",
    "SpecificationSuggestion",
    "StructuredRecordParseError",
    "VerificationDashboardView",
    "analyze_specification",
    "analyze_specification_suggestions",
    "compute_field_feedback",
    "document_to_record",
    "format_list_text",
    "format_metric_assertions",
    "format_structured_records",
    "issues_by_tab",
    "model_to_record",
    "open_specification_editor",
    "parse_list_text",
    "parse_metric_assertions",
    "parse_structured_records",
    "record_to_document",
    "record_to_model",
    "render_choice_summary",
    "render_specification_json_diff",
    "savefile_to_record",
    "specification_to_savefile_bytes",
    "route_issues_to_tabs",
    "worked_example_document",
]
