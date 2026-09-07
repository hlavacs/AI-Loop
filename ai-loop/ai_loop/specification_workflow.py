"""Frontend-neutral workflow helpers for formal specifications.

This module adapts the authoritative models, validators, integrity checks, and
state machine in :mod:`ai_loop.specifications` for presentation layers.  It
does not persist specification data or make lifecycle decisions itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ai_loop.specifications import (
    SpecificationDocument,
    SpecificationService,
    SpecificationStateError,
    StoredSpecificationVersion,
    ValidationIssue,
    approval_issues,
    structural_issues,
)


EDITOR_STAGES = (
    "Overview",
    "Scope",
    "Use Cases",
    "Requirements",
    "Risks",
    "Verification",
    "Choices",
    "Review",
)

_ROOT_PATH_STAGES = {
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


@dataclass(frozen=True)
class WorkflowIssue:
    """A validator issue routed to the editor stage that can resolve it."""

    owning_stage: str
    path: str
    severity: str
    message: str

    @property
    def actionable_message(self) -> str:
        """Return the authoritative validator message presented to the user."""

        return self.message


@dataclass(frozen=True)
class StageAssessment:
    """Structural validity and approval readiness for a specification draft."""

    issues: tuple[WorkflowIssue, ...]
    structurally_valid: bool
    approval_ready: bool

    def issues_for_stage(self, stage: str) -> tuple[WorkflowIssue, ...]:
        if stage not in EDITOR_STAGES:
            raise ValueError(f"unknown specification editor stage: {stage}")
        return tuple(issue for issue in self.issues if issue.owning_stage == stage)

    def issues_by_stage(self) -> dict[str, tuple[WorkflowIssue, ...]]:
        return {stage: self.issues_for_stage(stage) for stage in EDITOR_STAGES}


@dataclass(frozen=True)
class FormalJobInputs:
    """Ordinary job fields derived from one approved immutable specification."""

    goal: str
    constraints: tuple[str, ...]
    acceptance: tuple[str, ...]
    specification_id: str
    specification_version: int
    specification_content_hash: str
    requirement_ids: tuple[str, ...]
    verification_ids: tuple[str, ...]

    def as_job_inputs(self) -> dict[str, Any]:
        """Return the existing mutable goal/constraints/acceptance input shape."""

        return {
            "goal": self.goal,
            "constraints": list(self.constraints),
            "acceptance": list(self.acceptance),
        }


def _manifest_dict(value: Any | None) -> dict[str, Any] | None:
    if value is None:
        return None
    payload = value.to_dict() if hasattr(value, "to_dict") else value
    if not isinstance(payload, Mapping):
        raise ValueError("verification manifest must be an object")
    return dict(payload)


def _stable_contract_index(
    values: Sequence[Mapping[str, Any]],
    identity: Callable[[Mapping[str, Any]], str],
    category: str,
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for value in values:
        stable_id = identity(value)
        if not stable_id:
            raise ValueError(f"{category} contract has no stable identity")
        if stable_id in indexed:
            raise ValueError(f"duplicate {category} stable identity: {stable_id}")
        indexed[stable_id] = dict(value)
    return indexed


def _contract_delta(
    before: Mapping[str, Mapping[str, Any]],
    after: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    before_ids = set(before)
    after_ids = set(after)
    return {
        "added": [
            {"stable_id": stable_id, "after": after[stable_id]}
            for stable_id in sorted(after_ids - before_ids)
        ],
        "removed": [
            {"stable_id": stable_id, "before": before[stable_id]}
            for stable_id in sorted(before_ids - after_ids)
        ],
        "changed": [
            {
                "stable_id": stable_id,
                "before": before[stable_id],
                "after": after[stable_id],
            }
            for stable_id in sorted(before_ids & after_ids)
            if before[stable_id] != after[stable_id]
        ],
    }


def _changed_ids(delta: Mapping[str, Sequence[Mapping[str, Any]]]) -> set[str]:
    return {
        str(item["stable_id"])
        for operation in ("added", "removed", "changed")
        for item in delta[operation]
    }


def analyze_specification_change(
    previous: StoredSpecificationVersion,
    newer: StoredSpecificationVersion,
    *,
    previous_manifest: Any | None = None,
    newer_manifest: Any | None = None,
) -> dict[str, Any]:
    """Compare two approved immutable versions by stable contract identity.

    Decisions use their schema-defined stable topic because schema version 1.0
    deliberately has no synthetic decision ID.  Nested execution contracts use
    ``verification-id:metric/name`` identities, preserving their owning case
    and requirement/risk links instead of flattening them into prose.
    """

    if previous.approved_at is None or previous.approved_by is None:
        raise SpecificationStateError("previous specification version must be approved")
    if newer.approved_at is None or newer.approved_by is None:
        raise SpecificationStateError("new specification version must be approved")
    if previous.specification_id != newer.specification_id:
        raise SpecificationStateError("a job can only retarget within one specification identity")
    if newer.version <= previous.version:
        raise SpecificationStateError("retarget version must be newer than the attached version")

    old_document = previous.document.to_dict()
    new_document = newer.document.to_dict()
    old_manifest = _manifest_dict(previous_manifest)
    new_manifest = _manifest_dict(newer_manifest)

    def index_root(document: Mapping[str, Any], key: str, identity: str) -> dict[str, dict[str, Any]]:
        values = document.get(key)
        if not isinstance(values, list) or not all(isinstance(item, Mapping) for item in values):
            raise ValueError(f"specification.{key} must contain objects")
        return _stable_contract_index(values, lambda item: str(item.get(identity) or ""), key)

    old_requirements = index_root(old_document, "requirements", "id")
    new_requirements = index_root(new_document, "requirements", "id")
    old_decisions = index_root(old_document, "decisions", "topic")
    new_decisions = index_root(new_document, "decisions", "topic")
    old_risks = index_root(old_document, "risks", "id")
    new_risks = index_root(new_document, "risks", "id")
    old_cases = index_root(old_document, "verification", "id")
    new_cases = index_root(new_document, "verification", "id")

    def manifest_cases(
        payload: dict[str, Any] | None,
        document_cases: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        if payload is None:
            return {
                verification_id: {
                    "verification_id": verification_id,
                    "command": case.get("command_override"),
                    "command_source": (
                        "specification" if case.get("command_override") else
                        ("manual" if case.get("automation") == "manual" else "job_default")
                    ),
                    "requirement_ids": list(case.get("requirement_ids") or []),
                    "risk_ids": [],
                }
                for verification_id, case in document_cases.items()
            }
        values = payload.get("verification")
        if not isinstance(values, list) or not all(isinstance(item, Mapping) for item in values):
            raise ValueError("verification manifest must contain case objects")
        return _stable_contract_index(
            values, lambda item: str(item.get("verification_id") or ""), "manifest verification"
        )

    old_manifest_cases = manifest_cases(old_manifest, old_cases)
    new_manifest_cases = manifest_cases(new_manifest, new_cases)

    old_commands = {
        verification_id: {
            "verification_id": verification_id,
            "command": case.get("command"),
            "command_source": case.get("command_source"),
            "working_directory": case.get("working_directory", old_cases[verification_id].get("working_directory")),
            "timeout": case.get("timeout", old_cases[verification_id].get("timeout")),
        }
        for verification_id, case in old_manifest_cases.items()
    }
    new_commands = {
        verification_id: {
            "verification_id": verification_id,
            "command": case.get("command"),
            "command_source": case.get("command_source"),
            "working_directory": case.get("working_directory", new_cases[verification_id].get("working_directory")),
            "timeout": case.get("timeout", new_cases[verification_id].get("timeout")),
        }
        for verification_id, case in new_manifest_cases.items()
    }

    def nested_index(
        cases: Mapping[str, Mapping[str, Any]], key: str, nested_identity: Callable[[Any], str]
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for verification_id, case in cases.items():
            values = case.get(key, [])
            if not isinstance(values, list):
                raise ValueError(f"verification {verification_id}.{key} must be an array")
            for value in values:
                local_id = nested_identity(value)
                stable_id = f"{verification_id}:{local_id}"
                if not local_id or stable_id in result:
                    raise ValueError(f"duplicate or missing {key} identity in {verification_id}")
                result[stable_id] = {
                    "verification_id": verification_id,
                    "requirement_ids": list(case.get("requirement_ids") or []),
                    "risk_ids": list(case.get("risk_ids") or []),
                    "contract": value,
                }
        return result

    changes = {
        "requirements": _contract_delta(old_requirements, new_requirements),
        "decisions": _contract_delta(old_decisions, new_decisions),
        "risks": _contract_delta(old_risks, new_risks),
        "verification_cases": _contract_delta(old_cases, new_cases),
        "commands": _contract_delta(old_commands, new_commands),
        "metric_assertions": _contract_delta(
            nested_index(old_manifest_cases, "metric_assertions", lambda item: str(item.get("metric") or "") if isinstance(item, Mapping) else ""),
            nested_index(new_manifest_cases, "metric_assertions", lambda item: str(item.get("metric") or "") if isinstance(item, Mapping) else ""),
        ),
        "coverage_targets": _contract_delta(
            nested_index(old_manifest_cases, "coverage_targets", lambda item: str(item.get("name") or "") if isinstance(item, Mapping) else str(item)),
            nested_index(new_manifest_cases, "coverage_targets", lambda item: str(item.get("name") or "") if isinstance(item, Mapping) else str(item)),
        ),
    }

    changed_requirement_ids = _changed_ids(changes["requirements"])
    changed_risk_ids = _changed_ids(changes["risks"])
    changed_case_ids = _changed_ids(changes["verification_cases"])
    changed_nested_case_ids = {
        stable_id.split(":", 1)[0]
        for category in ("commands", "metric_assertions", "coverage_targets")
        for stable_id in _changed_ids(changes[category])
    }
    decision_changed = bool(_changed_ids(changes["decisions"]))
    affected_verification_ids: set[str] = set()
    for verification_id, case in new_manifest_cases.items():
        requirement_ids = set(map(str, case.get("requirement_ids") or []))
        risk_ids = set(map(str, case.get("risk_ids") or []))
        if (
            verification_id in changed_case_ids
            or verification_id in changed_nested_case_ids
            or requirement_ids & changed_requirement_ids
            or risk_ids & changed_risk_ids
            or decision_changed
        ):
            affected_verification_ids.add(verification_id)
    for verification_id, case in old_manifest_cases.items():
        if (
            verification_id in new_manifest_cases
            and set(map(str, case.get("risk_ids") or [])) & changed_risk_ids
        ):
            affected_verification_ids.add(verification_id)
    affected_requirement_ids = {
        requirement_id
        for requirement_id in changed_requirement_ids
        if requirement_id in new_requirements
    }
    for verification_id in affected_verification_ids:
        affected_requirement_ids.update(
            map(str, new_manifest_cases[verification_id].get("requirement_ids") or [])
        )

    return {
        "schema_version": "1.0",
        "previous_specification": {
            "id": previous.specification_id,
            "version": previous.version,
            "content_hash": previous.canonical_content_hash,
        },
        "new_specification": {
            "id": newer.specification_id,
            "version": newer.version,
            "content_hash": newer.canonical_content_hash,
        },
        "changes": changes,
        "impact": {
            "affected_requirement_ids": sorted(affected_requirement_ids),
            "affected_verification_ids": sorted(affected_verification_ids),
            "removed_verification_ids": sorted(set(old_cases) - set(new_cases)),
            "decision_change_requires_conservative_revalidation": decision_changed,
        },
    }


def owning_stage_for_path(path: str) -> str:
    """Map an authoritative validation path to its owning editor stage."""

    normalized = path.removeprefix("specification.")
    root = normalized.split(".", 1)[0].split("[", 1)[0]
    return _ROOT_PATH_STAGES.get(root, "Review")


def route_validation_issue(issue: ValidationIssue) -> WorkflowIssue:
    """Adapt a model-layer issue without changing its path or message."""

    return WorkflowIssue(
        owning_stage=owning_stage_for_path(issue.path),
        path=issue.path,
        severity=issue.severity,
        message=issue.message,
    )


def assess_specification(
    document: SpecificationDocument,
    *,
    worktree: str | Path | None = None,
    unresolved_blocking_decisions: int = 0,
) -> StageAssessment:
    """Run existing structural and approval validation and route every issue.

    Approval validation includes structural findings by design.  Exact
    duplicates are collapsed for presentation while readiness is calculated
    from the complete authoritative validator results.
    """

    structure = structural_issues(document, worktree=worktree)
    approval = approval_issues(
        document,
        unresolved_blocking_decisions=unresolved_blocking_decisions,
    )
    routed: list[WorkflowIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in (*structure, *approval):
        key = (issue.path, issue.severity, issue.message)
        if key in seen:
            continue
        seen.add(key)
        routed.append(route_validation_issue(issue))
    return StageAssessment(
        issues=tuple(routed),
        structurally_valid=not structure,
        approval_ready=not structure and not approval,
    )


def create_draft(
    service: SpecificationService,
    repository_path: str | Path,
    document: SpecificationDocument,
    *,
    creator: str,
    change_summary: str = "Initial draft",
    specification_id: str | None = None,
) -> StoredSpecificationVersion:
    """Create the first draft through the authoritative service boundary."""

    return service.create(
        repository_path,
        document,
        creator=creator,
        change_summary=change_summary,
        specification_id=specification_id,
    )


def save_draft(
    service: SpecificationService,
    specification_id: str,
    document: SpecificationDocument,
    *,
    creator: str,
    change_summary: str,
) -> StoredSpecificationVersion:
    """Save an immutable draft revision through ``SpecificationService``."""

    return service.revise(
        specification_id,
        document,
        creator=creator,
        change_summary=change_summary,
    )


def submit_for_review(
    service: SpecificationService,
    specification_id: str,
) -> StoredSpecificationVersion:
    return service.submit_for_review(specification_id)


def return_to_draft(
    service: SpecificationService,
    specification_id: str,
) -> StoredSpecificationVersion:
    return service.return_to_draft(specification_id)


def approve(
    service: SpecificationService,
    specification_id: str,
    *,
    approved_by: str,
) -> StoredSpecificationVersion:
    return service.approve(specification_id, approved_by=approved_by)


def derive_formal_job_inputs(snapshot: StoredSpecificationVersion) -> FormalJobInputs:
    """Derive ordinary job inputs from an approved immutable version snapshot.

    Callers should obtain ``snapshot`` from ``SpecificationService.load`` (or
    use :func:`load_formal_job_inputs`) so integrity is checked before use.
    Version-specific approval metadata is authoritative even if a newer draft
    has changed the specification identity's current status.
    """

    if snapshot.approved_at is None or snapshot.approved_by is None:
        raise SpecificationStateError(
            "formal job inputs require an approved immutable specification version"
        )
    document = snapshot.document
    contract = (
        f"{snapshot.specification_id} version {snapshot.version} "
        f"(content SHA-256 {snapshot.canonical_content_hash})"
    )
    goal = f'Implement the approved formal specification "{document.title}" from {contract}.'
    if document.summary:
        goal = f"{goal}\n\n{document.summary}"

    constraints = [
        f"Treat the pinned formal specification {contract} as authoritative; "
        "do not silently change its scope, requirements, decisions, or exclusions."
    ]
    constraints.extend(f"[Out of scope] {item}" for item in document.out_of_scope)
    constraints.extend(f"[Assumption] {item}" for item in document.assumptions)
    constraints.extend(
        f"[Implementation constraint or compatibility boundary] {item}"
        for item in document.constraints
    )
    for decision in document.decisions:
        constraints.append(
            f"[Approved decision: {decision.topic}] {decision.selected_decision}"
        )
        if decision.rationale:
            constraints.append(
                f"[Approved decision rationale: {decision.topic}] {decision.rationale}"
            )
        constraints.extend(
            f"[Approved decision consequence: {decision.topic}] {consequence}"
            for consequence in decision.consequences
        )

    acceptance = [
        f"[Requirement {requirement.id}] {criterion}"
        for requirement in document.requirements
        for criterion in requirement.acceptance_criteria
    ]
    blocking_cases = tuple(case for case in document.verification if case.blocking)
    acceptance.extend(
        f"[Blocking verification {case.id}] {criterion}"
        for case in blocking_cases
        for criterion in case.pass_criteria
    )
    return FormalJobInputs(
        goal=goal,
        constraints=tuple(constraints),
        acceptance=tuple(acceptance),
        specification_id=snapshot.specification_id,
        specification_version=snapshot.version,
        specification_content_hash=snapshot.canonical_content_hash,
        requirement_ids=tuple(requirement.id for requirement in document.requirements),
        verification_ids=tuple(case.id for case in document.verification),
    )


def load_formal_job_inputs(
    service: SpecificationService,
    specification_id: str,
    version: int,
) -> FormalJobInputs:
    """Integrity-check an immutable version and derive its formal job inputs."""

    return derive_formal_job_inputs(service.load(specification_id, version))


__all__ = [
    "EDITOR_STAGES",
    "FormalJobInputs",
    "StageAssessment",
    "WorkflowIssue",
    "analyze_specification_change",
    "approve",
    "assess_specification",
    "create_draft",
    "derive_formal_job_inputs",
    "load_formal_job_inputs",
    "owning_stage_for_path",
    "return_to_draft",
    "route_validation_issue",
    "save_draft",
    "submit_for_review",
]
