"""Tk-neutral verification dashboard projection and acknowledgement service."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from ai_loop import db
from ai_loop.verification_orchestrator import (
    MAX_EVIDENCE_PREVIEW_CHARACTERS,
    RealizationState,
    RepetitionStatus,
    VerificationExecutionError,
    _manifest_payload,
)


def _dashboard_text_preview(value: Any, maximum: int) -> tuple[str, bool]:
    text = value if isinstance(value, str) else ""
    text = text.replace("\x00", "\ufffd")
    if len(text) <= maximum:
        return text, False
    return text[:maximum], True


def _textual_media_type(value: Any) -> bool:
    media_type = str(value or "").split(";", 1)[0].strip().lower()
    return media_type.startswith("text/") or media_type in {
        "application/json",
        "application/xml",
        "application/yaml",
        "application/x-yaml",
    }


def shape_dashboard_evidence(
    evidence: Mapping[str, Any],
    *,
    preview_limit: int = MAX_EVIDENCE_PREVIEW_CHARACTERS,
) -> dict[str, Any]:
    """Return display-safe evidence metadata without opening artifact files.

    Binary evidence deliberately exposes only metadata.  Text previews use the
    bounded preview already persisted by the trusted orchestrator; this
    projection never follows an artifact path or reads large content for Tk.
    """

    if not isinstance(evidence, Mapping):
        raise VerificationExecutionError("dashboard evidence must be an object")
    if (
        isinstance(preview_limit, bool)
        or not isinstance(preview_limit, int)
        or preview_limit <= 0
    ):
        raise ValueError("dashboard evidence preview limit must be positive")
    size = evidence.get("size")
    digest = evidence.get("sha256")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise VerificationExecutionError("dashboard evidence has an invalid size")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise VerificationExecutionError("dashboard evidence has an invalid SHA-256")
    artifact_path = evidence.get("artifact_path")
    if artifact_path is not None and (
        not isinstance(artifact_path, str) or not artifact_path.strip()
    ):
        raise VerificationExecutionError(
            "dashboard evidence has an invalid artifact path"
        )
    textual = _textual_media_type(evidence.get("media_type"))
    preview = ""
    preview_truncated = False
    if textual:
        raw_preview = evidence.get("preview")
        if (
            not isinstance(raw_preview, str)
            and artifact_path is None
            and "inline_value" in evidence
        ):
            try:
                raw_preview = json.dumps(
                    evidence["inline_value"],
                    sort_keys=True,
                    indent=2,
                    ensure_ascii=False,
                    allow_nan=False,
                )
            except (TypeError, ValueError):
                raw_preview = ""
        preview, preview_truncated = _dashboard_text_preview(raw_preview, preview_limit)
    return {
        "name": str(evidence.get("name") or ""),
        "kind": str(evidence.get("kind") or ""),
        "media_type": str(evidence.get("media_type") or ""),
        "description": str(evidence.get("description") or ""),
        "requirement_ids": list(evidence.get("requirement_ids") or []),
        "verification_id": str(evidence.get("verification_id") or ""),
        "comparison": evidence.get("comparison"),
        "size": size,
        "sha256": digest,
        "artifact_path": artifact_path,
        "text_preview": preview if textual else None,
        "preview_truncated": preview_truncated,
        "preview_available": bool(textual and preview),
        "binary_or_large_metadata_only": not textual,
        "measurements": dict(evidence.get("measurements") or {}),
        "scenarios": list(evidence.get("scenarios") or []),
    }


def _shape_dashboard_repetition(value: Mapping[str, Any]) -> dict[str, Any]:
    output_preview, output_preview_truncated = _dashboard_text_preview(
        value.get("output"), MAX_EVIDENCE_PREVIEW_CHARACTERS
    )
    evidence = value.get("evidence", [])
    if not isinstance(evidence, list):
        raise VerificationExecutionError(
            "dashboard repetition evidence must be an array"
        )
    return {
        "record_id": value.get("id"),
        "task_id": value.get("task_id"),
        "worker_run_id": value.get("worker_run_id"),
        "attempt": int(value.get("attempt") or 0),
        "repetition": int(value.get("repetition") or 0),
        "command": str(value.get("command") or ""),
        "working_directory": str(value.get("working_directory") or ""),
        "timeout_seconds": value.get("timeout_seconds"),
        "status": str(value.get("status") or ""),
        "return_code": value.get("return_code"),
        "output_preview": output_preview,
        "output_preview_truncated": bool(
            value.get("output_truncated") or output_preview_truncated
        ),
        "metrics": value.get("metrics"),
        "assertion_results": list(value.get("assertion_results") or []),
        "evidence": [shape_dashboard_evidence(item) for item in evidence],
        "coverage_results": list(value.get("coverage_results") or []),
        "elapsed_seconds": value.get("elapsed_seconds"),
        "timed_out": bool(value.get("timed_out")),
        "error": value.get("error"),
        "termination_details": value.get("termination_details"),
        "started_at": value.get("started_at"),
        "finished_at": value.get("finished_at"),
    }


def _dashboard_contracts(
    case: Mapping[str, Any], summary: Mapping[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    realization = str(
        summary.get("realization_state") or summary.get("status") or "unrealized"
    )
    case_realized = realization not in {
        RealizationState.UNREALIZED.value,
        RealizationState.MANUAL_PENDING.value,
    }
    latest_coverage = {
        str(item.get("name")): item
        for item in summary.get("coverage_results", [])
        if isinstance(item, Mapping)
    }
    latest_evidence = {
        str(item.get("name")): item
        for item in summary.get("latest_evidence", [])
        if isinstance(item, Mapping)
    }
    oracle = str(case.get("oracle") or "")
    oracle_entries = [
        {
            "name": "Independent oracle",
            "description": oracle,
            "enforcement": "DESCRIPTIVE",
            "detail": (
                "The manifest oracle is prose and has no explicit machine linkage; "
                "AI-Loop does not infer enforcement from it."
            ),
        }
    ]

    coverage_entries: list[dict[str, Any]] = []
    for index, target in enumerate(case.get("coverage_targets", []), 1):
        if isinstance(target, str):
            coverage_entries.append(
                {
                    "name": target or f"Coverage target {index}",
                    "description": target,
                    "enforcement": "DESCRIPTIVE",
                    "runtime": None,
                }
            )
            continue
        if not isinstance(target, Mapping):
            raise VerificationExecutionError(
                "dashboard coverage target must be text or an object"
            )
        name = str(target.get("name") or f"Coverage target {index}")
        machine_contract = all(
            target.get(field) is not None
            for field in ("measurement_key", "operator", "threshold", "evidence_kind")
        )
        runtime = latest_coverage.get(name)
        if (
            machine_contract
            and isinstance(runtime, Mapping)
            and runtime.get("enforcement") == "machine_enforced"
        ):
            enforcement = "MACHINE-ENFORCED"
        elif machine_contract and case_realized:
            enforcement = "REALIZED"
        else:
            enforcement = "DESCRIPTIVE"
        coverage_entries.append(
            {
                "name": name,
                "description": str(target.get("description") or ""),
                "enforcement": enforcement,
                "runtime": None if runtime is None else dict(runtime),
            }
        )

    missing_producers = set(summary.get("missing_evidence_producers") or [])
    evidence_entries: list[dict[str, Any]] = []
    for index, declaration in enumerate(case.get("required_evidence", []), 1):
        if isinstance(declaration, str):
            evidence_entries.append(
                {
                    "name": declaration or f"Evidence requirement {index}",
                    "description": declaration,
                    "kind": "",
                    "enforcement": "DESCRIPTIVE",
                    "runtime": None,
                }
            )
            continue
        if not isinstance(declaration, Mapping):
            raise VerificationExecutionError(
                "dashboard evidence requirement must be text or an object"
            )
        name = str(declaration.get("name") or f"Evidence requirement {index}")
        kind = str(declaration.get("kind") or "")
        emitted = latest_evidence.get(name)
        if emitted is not None:
            enforcement = "MACHINE-ENFORCED"
        elif case_realized and kind and kind not in missing_producers:
            enforcement = "REALIZED"
        else:
            enforcement = "DESCRIPTIVE"
        evidence_entries.append(
            {
                "name": name,
                "description": str(declaration.get("description") or ""),
                "kind": kind,
                "enforcement": enforcement,
                "runtime": None
                if emitted is None
                else shape_dashboard_evidence(emitted),
            }
        )
    return {
        "oracle": oracle_entries,
        "coverage_targets": coverage_entries,
        "evidence_requirements": evidence_entries,
    }


def build_verification_dashboard_projection(
    manifest: Any,
    runtime_summary: Sequence[Mapping[str, Any]],
    *,
    repetitions: Sequence[Mapping[str, Any]] = (),
    manual_acknowledgements: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], ...]:
    """Project trusted formal state into deterministic, Tk-neutral case rows."""

    payload = _manifest_payload(manifest)
    cases = payload.get("verification")
    if not isinstance(cases, list):
        raise VerificationExecutionError(
            "dashboard manifest must contain verification cases"
        )
    summary_by_id: dict[str, Mapping[str, Any]] = {}
    for item in runtime_summary:
        verification_id = (
            item.get("verification_id") if isinstance(item, Mapping) else None
        )
        if not isinstance(verification_id, str) or not verification_id:
            raise VerificationExecutionError(
                "dashboard summary requires verification IDs"
            )
        if verification_id in summary_by_id:
            raise VerificationExecutionError(
                f"dashboard summary contains duplicate verification ID: {verification_id}"
            )
        summary_by_id[verification_id] = item

    repetitions_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for item in repetitions:
        verification_id = (
            item.get("verification_id") if isinstance(item, Mapping) else None
        )
        if not isinstance(verification_id, str):
            raise VerificationExecutionError(
                "dashboard repetition requires a verification ID"
            )
        repetitions_by_id.setdefault(verification_id, []).append(item)
    acknowledgements_by_id: dict[str, list[dict[str, Any]]] = {}
    for item in manual_acknowledgements:
        verification_id = (
            item.get("verification_id") if isinstance(item, Mapping) else None
        )
        if not isinstance(verification_id, str):
            raise VerificationExecutionError(
                "dashboard acknowledgement requires a verification ID"
            )
        acknowledgements_by_id.setdefault(verification_id, []).append(dict(item))

    rows: list[dict[str, Any]] = []
    manifest_ids: set[str] = set()
    for raw_case in cases:
        if not isinstance(raw_case, Mapping) or not isinstance(
            raw_case.get("verification_id"), str
        ):
            raise VerificationExecutionError(
                "dashboard manifest cases require verification IDs"
            )
        verification_id = str(raw_case["verification_id"])
        if verification_id in manifest_ids:
            raise VerificationExecutionError(
                f"dashboard manifest contains duplicate verification ID: {verification_id}"
            )
        manifest_ids.add(verification_id)
        summary = summary_by_id.get(verification_id)
        if summary is None:
            raise VerificationExecutionError(
                f"dashboard runtime summary is missing {verification_id}"
            )
        automation = str(raw_case.get("automation") or "")
        blocking = bool(raw_case.get("blocking"))
        if automation != summary.get("automation") or blocking != bool(
            summary.get("blocking")
        ):
            raise VerificationExecutionError(
                f"dashboard summary metadata differs from manifest case {verification_id}"
            )
        acknowledgements = acknowledgements_by_id.get(verification_id, [])
        if acknowledgements and (automation != "manual" or blocking):
            raise VerificationExecutionError(
                f"invalid manual acknowledgement history for {verification_id}"
            )
        shaped_repetitions = [
            _shape_dashboard_repetition(item)
            for item in repetitions_by_id.get(verification_id, [])
        ]
        attempts: list[dict[str, Any]] = []
        for attempt_number in sorted({item["attempt"] for item in shaped_repetitions}):
            attempt_repetitions = [
                item for item in shaped_repetitions if item["attempt"] == attempt_number
            ]
            attempts.append(
                {
                    "attempt": attempt_number,
                    "status": (
                        "passed"
                        if attempt_repetitions
                        and all(
                            item["status"] == RepetitionStatus.PASSED.value
                            for item in attempt_repetitions
                        )
                        else "failed"
                    ),
                    "repetitions": attempt_repetitions,
                }
            )
        latest_repetitions = attempts[-1]["repetitions"] if attempts else []
        realization = str(
            summary.get("realization_state") or summary.get("status") or "unrealized"
        )
        if realization not in {item.value for item in RealizationState}:
            raise VerificationExecutionError(
                f"dashboard summary has unsupported realization state: {realization}"
            )
        rows.append(
            {
                "verification_id": verification_id,
                "title": str(raw_case.get("title") or ""),
                "requirement_ids": list(raw_case.get("requirement_ids") or []),
                "blocking": blocking,
                "automation": automation,
                "realization_state": realization,
                "runtime_status": str(summary.get("status") or realization),
                "attempt_count": int(summary.get("attempts_completed") or 0),
                "repetitions": len(latest_repetitions),
                "repetitions_per_attempt": summary.get("repetitions_per_attempt"),
                "latest_metrics": summary.get("latest_metrics"),
                "failed_assertions": list(summary.get("failed_assertions") or []),
                "stagnation_count": int(summary.get("stagnation_count") or 0),
                "stagnation_series": int(summary.get("stagnation_series") or 0),
                "metric_trend": str(summary.get("metric_trend") or "insufficient"),
                "escalation": summary.get("escalation_report"),
                "last_error": summary.get("last_error"),
                "evidence_freshness": summary.get("evidence_freshness"),
                "contracts": _dashboard_contracts(raw_case, summary),
                "attempts": attempts,
                "manual_acknowledgements": acknowledgements,
                "can_acknowledge_manual": automation == "manual" and not blocking,
                "manual_acknowledgement_changes_status": False,
            }
        )
    extras = (
        set(summary_by_id) | set(repetitions_by_id) | set(acknowledgements_by_id)
    ) - manifest_ids
    if extras:
        raise VerificationExecutionError(
            "dashboard data contains cases absent from the manifest: "
            + ", ".join(sorted(extras))
        )
    return tuple(rows)


def load_verification_dashboard_projection(
    db_path: str | Path,
    job_id: str,
) -> tuple[dict[str, Any], ...] | None:
    """Integrity-check and load a formal dashboard; Quick Goal is ``None``."""

    from ai_loop.specification_compiler import VerificationManifestService
    from ai_loop.specifications import SpecificationService

    service = SpecificationService(db_path)
    manifests = VerificationManifestService(service)
    stored = manifests.load_for_job(job_id)
    if stored is None:
        with db.transaction(db_path) as conn:
            if db.list_verification_manual_acknowledgements(conn, job_id):
                raise VerificationExecutionError(
                    "Quick Goal job unexpectedly has manual verification acknowledgements"
                )
        return None
    context = manifests.load_prompt_context(job_id)
    if context is None:  # pragma: no cover - stored was loaded above
        raise VerificationExecutionError("formal dashboard lost its immutable manifest")
    with db.transaction(db_path) as conn:
        repetitions = db.list_verification_repetitions(conn, job_id)
        acknowledgements = db.list_verification_manual_acknowledgements(conn, job_id)
    active_ids = {str(item["verification_id"]) for item in stored.manifest.verification}
    active_manual_ids = {
        str(item["verification_id"])
        for item in stored.manifest.verification
        if item.get("automation") == "manual" and not bool(item.get("blocking"))
    }
    return build_verification_dashboard_projection(
        context.manifest,
        context.runtime_verification_summary,
        repetitions=[
            item for item in repetitions if str(item["verification_id"]) in active_ids
        ],
        manual_acknowledgements=[
            item
            for item in acknowledgements
            if str(item["verification_id"]) in active_manual_ids
        ],
    )


def record_manual_verification_acknowledgement(
    db_path: str | Path,
    job_id: str,
    verification_id: str,
    *,
    acknowledged_by: str,
    note: str,
) -> dict[str, Any]:
    """Integrity-check a formal job, then append a non-state-changing note."""

    from ai_loop.specification_compiler import VerificationManifestService
    from ai_loop.specifications import SpecificationService

    service = SpecificationService(db_path)
    stored = VerificationManifestService(service).load_for_job(job_id)
    if stored is None:
        raise VerificationExecutionError(
            "Quick Goal jobs cannot receive manual verification acknowledgements"
        )
    with db.transaction(db_path) as conn:
        try:
            return db.create_verification_manual_acknowledgement(
                conn,
                job_id=job_id,
                verification_id=verification_id,
                acknowledged_by=acknowledged_by,
                note=note,
            )
        except ValueError as exc:
            raise VerificationExecutionError(str(exc)) from exc
