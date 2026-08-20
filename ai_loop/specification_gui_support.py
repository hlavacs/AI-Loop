"""Tk-independent parsing and analysis for the specification editor.

Persistence, validation, integrity, and lifecycle rules remain authoritative
in :mod:`ai_loop.specifications` and :mod:`ai_loop.specification_workflow`.
"""

from __future__ import annotations

import copy
import difflib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ai_loop.elicitation import (
    DecisionProposal,
)
from ai_loop.specification_workflow import (
    EDITOR_STAGES,
    StageAssessment,
    WorkflowIssue,
    assess_specification,
)
from ai_loop.specifications import (
    AutomationLevel,
    MetricAssertion,
    RequirementCategory,
    RequirementPriority,
    RiskSeverity,
    RiskUncertainty,
    SpecificationDocument,
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
            raise MetricAssertionParseError(
                line_number, "tolerance must be non-negative"
            )
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


def format_metric_assertions(
    assertions: Iterable[MetricAssertion | Mapping[str, Any]],
) -> str:
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

    return SpecificationDocument.from_dict(
        copy.deepcopy(dict(record)), worktree=worktree
    )


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
        text = (
            bytes(content).decode("utf-8") if not isinstance(content, str) else content
        )
    except UnicodeDecodeError as exc:
        raise SpecificationSavefileError(
            "Specification file must be UTF-8 encoded JSON"
        ) from exc
    try:
        envelope = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SpecificationSavefileError(
            f"Malformed specification JSON: {exc}"
        ) from exc
    if not isinstance(envelope, Mapping):
        raise SpecificationSavefileError(
            "Specification file must contain a JSON object"
        )
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
    for key in (
        "objectives",
        "in_scope",
        "out_of_scope",
        "stakeholders",
        "assumptions",
        "constraints",
        "dependencies",
        "open_questions",
    ):
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
        return not value or all(
            _is_empty_semantic_value(item) for item in value.values()
        )
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
            count = (
                len(value)
                if isinstance(value, Sequence) and not isinstance(value, str)
                else None
            )
            populated = (
                f"{count} item(s)" if count is not None else "meaningful content"
            )
            feedback[path] = FieldSemanticFeedback(
                "healthy",
                f"Looks good — populated with {populated}; no current workflow issue.",
            )

    optional_roots = {
        "assumptions",
        "constraints",
        "dependencies",
        "risks",
        "decisions",
        "open_questions",
    }
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
        if not isinstance(values, Sequence) or isinstance(
            values, (str, bytes, bytearray)
        ):
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
                    value = (
                        loop.get(field.key, field.default)
                        if isinstance(loop, Mapping)
                        else field.default
                    )
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
            lines.append(
                f"  - {option_value.get('name', '')}: {option_value.get('description', '')}"
            )
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
    _Field(
        "category",
        "Category",
        "enum",
        tuple(item.value for item in RequirementCategory),
        "functional",
    ),
    _Field(
        "priority",
        "Priority",
        "enum",
        tuple(item.value for item in RequirementPriority),
        "must",
    ),
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
    _Field(
        "severity",
        "Severity",
        "enum",
        tuple(item.value for item in RiskSeverity),
        "low",
    ),
    _Field(
        "uncertainty",
        "Uncertainty",
        "enum",
        tuple(item.value for item in RiskUncertainty),
        "low",
    ),
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
    _Field(
        "test_level",
        "Test level",
        "enum",
        tuple(item.value for item in TestLevel),
        "unit",
    ),
    _Field(
        "method",
        "Method",
        "enum",
        tuple(item.value for item in VerificationMethod),
        "deterministic",
    ),
    _Field("oracle", "Independent oracle", "text"),
    _Field("fixtures", "Fixtures", "list"),
    _Field("procedure", "Ordered procedure", "list"),
    _Field("pass_criteria", "Pass criteria", "list"),
    _Field("declared_metrics", "Declared metric names", "list"),
    _Field(
        "metric_assertions",
        "Metric assertions: name operator threshold [tolerance]",
        "metrics",
    ),
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
    _Field(
        "automation",
        "Automation",
        "enum",
        tuple(item.value for item in AutomationLevel),
        "automated",
    ),
    _Field("blocking", "Blocks autonomous completion", "bool", default=False),
    _Field(
        "command_override",
        "Command override",
        group="Advanced execution and validation loop",
    ),
    _Field(
        "working_directory",
        "Working directory",
        default=".",
        group="Advanced execution and validation loop",
    ),
    _Field(
        "timeout",
        "Timeout (seconds)",
        "positive_int",
        default=300,
        group="Advanced execution and validation loop",
    ),
    _Field(
        "maximum_correction_attempts",
        "Maximum correction attempts",
        "positive_int",
        default=1,
        group="Advanced execution and validation loop",
    ),
    _Field(
        "repetitions_per_attempt",
        "Repetitions per attempt",
        "positive_int",
        default=1,
        group="Advanced execution and validation loop",
    ),
    _Field(
        "stagnation_limit",
        "Stagnation limit",
        "positive_int",
        default=1,
        group="Advanced execution and validation loop",
    ),
    _Field(
        "escalation_condition",
        "Escalation condition",
        "text",
        group="Advanced execution and validation loop",
    ),
    _Field(
        "retain_evidence",
        "Retain evidence",
        "bool",
        default=True,
        group="Advanced execution and validation loop",
    ),
)
