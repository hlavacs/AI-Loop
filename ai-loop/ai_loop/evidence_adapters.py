"""Configuration and safe loading for domain-specific evidence adapters.

``AI_LOOP_EVIDENCE_ADAPTERS`` is a JSON array. Each item is either a
``"package.module:Factory"`` string or an object with ``id``, ``adapter``,
optional constructor ``options``, and optional ``enabled`` fields.
"""

from __future__ import annotations

import importlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ai_loop.config import sanitized_child_env
from ai_loop.process_runner import (
    DEFAULT_MAX_OUTPUT_BYTES,
    BoundedProcessResult,
    run_bounded_process,
)


EVIDENCE_ADAPTERS_ENV = "AI_LOOP_EVIDENCE_ADAPTERS"


@dataclass(frozen=True)
class EvidenceAdapterConfig:
    """One enabled adapter factory, addressed by registry key or import path."""

    identifier: str
    adapter: str
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceAdapterAudit:
    adapter: str
    stage: str
    error: str
    verification_id: str | None = None
    evidence_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "stage": self.stage,
            "error": self.error,
            "verification_id": self.verification_id,
            "evidence_name": self.evidence_name,
        }


@dataclass(frozen=True)
class LoadedEvidenceAdapters:
    adapters: tuple[Any, ...]
    audits: tuple[EvidenceAdapterAudit, ...]


AdapterFactory = Callable[..., Any]
AdapterAuditSink = Callable[[EvidenceAdapterAudit], None]
_REGISTERED_ADAPTERS: dict[str, AdapterFactory] = {}


def register_evidence_adapter(key: str, factory: AdapterFactory) -> None:
    """Register a process-local adapter factory under a stable configuration key."""

    normalized = key.strip()
    if not normalized:
        raise ValueError("evidence adapter registry key must be non-empty")
    if not callable(factory):
        raise TypeError("evidence adapter factory must be callable")
    _REGISTERED_ADAPTERS[normalized] = factory


def run_evidence_adapter_process(
    command: Sequence[str],
    *,
    cwd: str | Path,
    timeout: float,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> BoundedProcessResult:
    """The required bounded, credential-sanitized subprocess boundary for adapters."""

    return run_bounded_process(
        command,
        cwd=cwd,
        timeout=timeout,
        env=sanitized_child_env(),
        max_output_bytes=max_output_bytes,
    )


def parse_evidence_adapter_config(
    raw: str | None = None,
) -> tuple[EvidenceAdapterConfig, ...]:
    """Parse ``AI_LOOP_EVIDENCE_ADAPTERS`` as a bounded, explicit JSON array."""

    value = os.getenv(EVIDENCE_ADAPTERS_ENV, "") if raw is None else raw
    if not value.strip():
        return ()
    payload = json.loads(value)
    if not isinstance(payload, list):
        raise ValueError(f"{EVIDENCE_ADAPTERS_ENV} must be a JSON array")
    if len(payload) > 32:
        raise ValueError(f"{EVIDENCE_ADAPTERS_ENV} may configure at most 32 adapters")
    configs: list[EvidenceAdapterConfig] = []
    for index, item in enumerate(payload):
        if isinstance(item, str):
            adapter = item.strip()
            identifier = adapter
            options: Mapping[str, Any] = {}
        elif isinstance(item, Mapping):
            if item.get("enabled", True) is False:
                continue
            adapter = str(item.get("adapter", "")).strip()
            identifier = str(item.get("id", adapter)).strip()
            raw_options = item.get("options", {})
            if not isinstance(raw_options, Mapping):
                raise ValueError(f"evidence adapter entry {index} options must be an object")
            options = dict(raw_options)
        else:
            raise ValueError(f"evidence adapter entry {index} must be a string or object")
        if not adapter or not identifier:
            raise ValueError(f"evidence adapter entry {index} requires adapter and id")
        configs.append(EvidenceAdapterConfig(identifier, adapter, options))
    return tuple(configs)


def _import_factory(import_path: str) -> AdapterFactory:
    module_name, separator, attribute = import_path.partition(":")
    if not separator or not module_name or not attribute or ":" in attribute:
        raise ValueError("adapter import paths must use 'module:attribute'")
    target: Any = importlib.import_module(module_name)
    for part in attribute.split("."):
        target = getattr(target, part)
    if not callable(target):
        raise TypeError("configured adapter target is not callable")
    return target


class _AuditedAdapter:
    def __init__(self, identifier: str, adapter: Any, audit: AdapterAuditSink | None):
        self.identifier = identifier
        self._adapter = adapter
        self._audit = audit

    def evaluate(self, evidence: Any, *, worktree: Path) -> Any:
        try:
            return self._adapter.evaluate(evidence, worktree=worktree)
        except Exception as exc:
            if self._audit is not None:
                self._audit(
                    EvidenceAdapterAudit(
                        adapter=self.identifier,
                        stage="evaluate",
                        error=f"{type(exc).__name__}: {exc}",
                        verification_id=str(getattr(evidence, "verification_id", "")) or None,
                        evidence_name=str(getattr(evidence, "name", "")) or None,
                    )
                )
            return None


def load_evidence_adapters(
    raw: str | None = None,
    *,
    registry: Mapping[str, AdapterFactory] | None = None,
    audit: AdapterAuditSink | None = None,
) -> LoadedEvidenceAdapters:
    """Instantiate configured adapters; bad entries are audited and skipped."""

    audits: list[EvidenceAdapterAudit] = []

    def report(item: EvidenceAdapterAudit) -> None:
        audits.append(item)
        if audit is not None:
            audit(item)

    try:
        configs = parse_evidence_adapter_config(raw)
    except Exception as exc:
        report(
            EvidenceAdapterAudit(
                "configuration", "parse", f"{type(exc).__name__}: {exc}"
            )
        )
        return LoadedEvidenceAdapters((), tuple(audits))
    factories = {**_REGISTERED_ADAPTERS, **dict(registry or {})}
    loaded: list[Any] = []
    for config in configs:
        try:
            factory = factories.get(config.adapter) or _import_factory(config.adapter)
            instance = factory(**dict(config.options))
            if not callable(getattr(instance, "evaluate", None)):
                raise TypeError("configured adapter instance has no callable evaluate method")
            loaded.append(_AuditedAdapter(config.identifier, instance, report))
        except Exception as exc:
            report(
                EvidenceAdapterAudit(
                    config.identifier,
                    "load",
                    f"{type(exc).__name__}: {exc}",
                )
            )
    return LoadedEvidenceAdapters(tuple(loaded), tuple(audits))


def result_realization_signals(result: Any, evidence: Any) -> tuple[Any, ...]:
    """Convert a successful adapter result into conservative realization signals.

    Metrics and produced evidence kinds are inferred. A case marker or fixture
    generator must be explicitly supplied in ``result.realization_signals``;
    successful external analysis alone never invents them.
    """

    from ai_loop.verification_orchestrator import (
        EvidenceAdapterResult,
        RealizationSignals,
    )

    if not isinstance(result, EvidenceAdapterResult) or not result.passed or result.error:
        return ()
    verification_id = str(getattr(evidence, "verification_id", ""))
    if not verification_id:
        return ()
    metrics = tuple(sorted(key for key in result.metrics if isinstance(key, str) and key))
    kinds = tuple(
        sorted(
            {
                str(item["kind"])
                for item in result.evidence
                if isinstance(item, Mapping) and isinstance(item.get("kind"), str)
            }
        )
    )
    signals: list[RealizationSignals] = [
        RealizationSignals(
            verification_id=verification_id,
            metric_emitters=metrics,
            evidence_producers=kinds,
        )
    ]
    for item in result.realization_signals:
        if isinstance(item, RealizationSignals) and item.verification_id == verification_id:
            signals.append(item)
    return tuple(signals)


def collect_realization_signals(
    adapters: Sequence[Any],
    evidence: Sequence[Any],
    *,
    worktree: Path,
    audit: AdapterAuditSink | None = None,
) -> tuple[Any, ...]:
    """Evaluate every configured adapter/artifact pair and collect safe signals."""

    from ai_loop.verification_orchestrator import EvidenceAdapterResult

    signals: list[Any] = []
    for adapter in adapters:
        identifier = str(getattr(adapter, "identifier", type(adapter).__name__))
        for artifact in evidence:
            try:
                result = adapter.evaluate(artifact, worktree=worktree)
            except Exception as exc:  # also protects callers passing an unwrapped adapter
                if audit is not None:
                    audit(
                        EvidenceAdapterAudit(
                            identifier,
                            "evaluate",
                            f"{type(exc).__name__}: {exc}",
                            str(getattr(artifact, "verification_id", "")) or None,
                            str(getattr(artifact, "name", "")) or None,
                        )
                    )
                continue
            if result is None:
                continue
            if not isinstance(result, EvidenceAdapterResult):
                if audit is not None:
                    audit(
                        EvidenceAdapterAudit(
                            identifier,
                            "result",
                            "adapter returned an unsupported result",
                            str(getattr(artifact, "verification_id", "")) or None,
                            str(getattr(artifact, "name", "")) or None,
                        )
                    )
                continue
            signals.extend(result_realization_signals(result, artifact))
    return tuple(signals)


def evidence_artifact_from_mapping(value: Mapping[str, Any]) -> Any:
    """Rehydrate orchestrator-owned persisted evidence for adapter evaluation."""

    from ai_loop.verification_orchestrator import EvidenceArtifact

    return EvidenceArtifact(
        name=str(value["name"]),
        kind=str(value["kind"]),
        media_type=str(value["media_type"]),
        description=str(value.get("description", "")),
        requirement_ids=tuple(str(item) for item in value.get("requirement_ids", ())),
        verification_id=str(value["verification_id"]),
        comparison=(
            dict(value["comparison"])
            if isinstance(value.get("comparison"), Mapping)
            else None
        ),
        size=int(value["size"]),
        sha256=str(value["sha256"]),
        artifact_path=(
            str(value["artifact_path"])
            if value.get("artifact_path") is not None
            else None
        ),
        inline_value=value.get("inline_value"),
        preview=str(value["preview"]) if value.get("preview") is not None else None,
        measurements={
            str(key): float(number)
            for key, number in dict(value.get("measurements", {})).items()
        },
        scenarios=tuple(str(item) for item in value.get("scenarios", ())),
    )


__all__ = [
    "EVIDENCE_ADAPTERS_ENV",
    "EvidenceAdapterAudit",
    "EvidenceAdapterConfig",
    "LoadedEvidenceAdapters",
    "collect_realization_signals",
    "evidence_artifact_from_mapping",
    "load_evidence_adapters",
    "parse_evidence_adapter_config",
    "register_evidence_adapter",
    "result_realization_signals",
    "run_evidence_adapter_process",
]
