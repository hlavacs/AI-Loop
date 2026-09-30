"""Headless protocol v1 service: ``python -m icoda_core.service``.

State changes run sequentially; cancellation bypasses the worker queue. Explicit operations start children;
opening reads cached project data and never remembers or reopens a desktop project.
See docs/VSCODE_MIGRATION.md for the wire contract and this slice's limitations.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import shutil
import signal
import sys
import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, TextIO
from uuid import uuid4

from icoda_core import __version__

if TYPE_CHECKING:
    from icoda_core.call_trace import CallPlayback
    from icoda_core.class_view import ClassMember, ClassNode
    from icoda_core.clusters import Clustering, Layout
    from icoda_core.documentation import Completion
    from icoda_core.executables import Entry, Outcome
    from icoda_core.instrumentation import InstrumentationOptions
    from icoda_core.mind_map import MindMapNode, MindMapViewState
    from icoda_core.model import DerivedModel
    from icoda_core.persistence import ProjectState, ProjectStore
    from icoda_core.prompt import StepRequest
    from icoda_core.recovery import Diagnosis
    from icoda_core.steplog import StepRecord
    from icoda_core.steps import Approach, Proposal, StepError, StepRunner
    from icoda_core.views import CallNode, ClassNodeLayout, MindMapNodeLayout, Node

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1024 * 1024
ANALYSIS_TIMEOUT = 1800.0
OPERATIONS = {"targets.refresh": "refresh", "build.run": "build", "target.run": "run", "trace.record": "run",
              "tests.run": "test"}
CANCELLABLE = (*OPERATIONS, "project.analyse", "view.get", "trace.load", "toolchain.inspect", "queue.continue", "spec.save")
WORKFLOW_KINDS = ("architecture", "implementation_approach", "implementation_queue")
WORKFLOW_METHODS = ("workflow.start", "workflow.status", "workflow.cancel", "purpose.propose", "purpose.status",
                    "purpose.apply", "purpose.reject", "conversation.send", "conversation.history",
                    "prompt.rephrase", "cli.command")
QUEUE_METHODS = ("queue.settings.get", "queue.settings.set", "queue.continue")
RECOVERY_METHODS = ("recovery.list", "recovery.resolve")
REVIEW_METHODS = ("proposal.get", "proposal.approve", "proposal.reject", "proposal.adapt", "proposal.rebuild",
                  "history.list", "step.undo", "step.commitManual")
METHODS = ("initialize", "project.create", "project.open", "project.close", "project.analyse", "source.resolve",
           "targets.list", "target.select", "view.get", "view.revealFile", "graph.interactions",
           "cluster.pin", "cluster.unpin", "cluster.rename", "cluster.assignFile", "view.state.get", "view.state.set",
           "mindmap.setExpanded", "mindmap.step", "issues.list", "coverage.get",
           "spec.get", "spec.validate", "spec.save", "phase.get", "phase.transition", "providers.list", "providers.select",
           "trace.load", "trace.step", "trace.reset", "operation.cancel", "toolchain.inspect", *OPERATIONS,
           *WORKFLOW_METHODS, *REVIEW_METHODS, *QUEUE_METHODS, *RECOVERY_METHODS)
LOG = logging.getLogger(__name__)


class ServiceError(Exception):
    """An operation failure with a stable wire code and structured context."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error = {"code": code, "message": message, "details": details or {}}


class ProjectLock:
    """An OS-owned advisory lock; retained files never require racy stale-PID deletion."""

    def __init__(self, root: Path) -> None:
        digest = hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()
        directory = Path(tempfile.gettempdir()) / "icoda-service-locks"
        try:
            # Windows maps 0700 to an owner-only ACL. Inherit the temp parent's
            # ACL so a helper account cannot exclude the desktop user.
            directory.mkdir(mode=0o777 if sys.platform == "win32" else 0o700, exist_ok=True)
            self.handle = (directory / (digest + ".lock")).open("a+b")
        except OSError as exc:
            raise ServiceError("project_lock_unavailable",
                               "Cannot access the project lock directory. Check its permissions: " + str(directory),
                               {"path": str(root), "lockDirectory": str(directory)}) from exc
        try:
            self.acquire()
        except OSError as exc:
            self.handle.close()
            raise ServiceError("project_locked", "Another ICODA service owns this project. Close it first.",
                               {"path": str(root)}) from exc
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(str(os.getpid()).encode("ascii"))
        self.handle.flush()

    def acquire(self) -> None:
        if sys.platform == "win32":
            import msvcrt

            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def close(self) -> None:
        self.handle.close()


def check_cancelled(context: dict[str, Any]) -> None:
    from icoda_core import process

    event = process.current_cancellation()
    if event is not None and event.is_set():
        raise ServiceError("cancelled", "Operation cancelled or superseded by a project selection.", context)


def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ServiceError("invalid_params", f"{key} must be a nonempty string without NULs.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ServiceError("invalid_params", f"{key} must be valid UTF-8.") from exc
    return value


def _integer(data: dict[str, Any], key: str, minimum: int = 1) -> int:
    value = data.get(key)
    if type(value) is not int or value < minimum:
        raise ServiceError("invalid_params", f"{key} must be an integer >= {minimum}.")
    return value


def _params(data: dict[str, Any], required: tuple[str, ...] = (), optional: tuple[str, ...] = ()) -> None:
    missing, unknown = set(required) - data.keys(), data.keys() - set(required + optional)
    if missing or unknown:
        raise ServiceError("invalid_params", "Invalid method parameters.",
                           {"missing": sorted(missing), "unknown": sorted(unknown)})


def _boolean(data: dict[str, Any], key: str) -> bool:
    value = data.get(key)
    if type(value) is not bool:
        raise ServiceError("invalid_params", f"{key} must be a boolean.")
    return value


@dataclass
class ProjectSession:
    """Authoritative state for the explicit workspace and its whole-project model."""

    store: ProjectStore
    model: DerivedModel
    session_id: str = field(default_factory=lambda: uuid4().hex)
    revision: int = 1
    playback: CallPlayback | None = None
    trace_id: str | None = None
    choices: tuple[Entry, ...] = ()
    selected: Entry | None = None
    target_diagnostics: list[dict[str, str]] = field(default_factory=list)
    model_available: bool = False
    pending_proposal: bool = False
    conversation: list[tuple[str, str]] = field(default_factory=list)
    conversation_issue: Diagnosis | None = None
    provider_models: dict[str, str] = field(default_factory=dict)

    def context(self) -> dict[str, Any]:
        return {"sessionId": self.session_id, "sourceRootId": self.session_id + ":workspace",
                "modelRevision": self.revision, "targetId": target_id(self.selected)}

    def snapshot(self) -> dict[str, Any]:
        return {**self.context(), "root": str(self.store.root), "model": json.loads(self.model.to_json())}

    def scoped_model(self) -> DerivedModel:
        """Keep the authoritative whole model intact, including in overview mode."""
        from icoda_core import executables

        return self.model if self.selected is None else executables.scope_model(
            self.model, self.selected, root=self.store.root)


def target_id(entry: Entry | None) -> str | None:
    """Encode the desktop selection key without process, root or revision dependence."""
    return None if entry is None else "entry:" + json.dumps(entry.key, separators=(",", ":"))


def discover_targets(project: ProjectSession, key: Any) -> None:
    """Read a revision's target catalog and restore the desktop's selection policy."""
    from icoda_core import executables

    project.target_diagnostics = []
    try:
        targets = executables.read_targets(project.store.root)
        if not targets and (project.store.root / "CMakeLists.txt").is_file():
            project.target_diagnostics.append({"code": "target_metadata_unavailable",
                                               "message": "No CMake target metadata; showing analysed entry points."})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        targets = ()
        project.target_diagnostics.append({"code": "target_metadata_invalid", "message": str(exc)})
    project.choices = executables.entries(project.model, targets)
    project.selected = None if key == [] else executables.choose(project.choices, key)


def target_item(entry: Entry | None) -> dict[str, Any]:
    """Describe a selectable desktop entry, with a distinct Whole Project item."""
    if entry is None:
        return {"id": None, "kind": "whole-project", "name": "Whole Project", "label": "Whole Project",
                "configuration": None, "entryUsr": None}
    return {"id": target_id(entry), "kind": "library" if entry.is_library else "executable",
            "name": entry.target.name if entry.target else entry.file, "label": entry.label,
            "configuration": entry.target.configuration if entry.target else None,
            "entryUsr": entry.usr or None}


@dataclass
class WorkflowJob:
    """One owned background round; conversation/rephrase replies are redacted plain text."""

    context: dict[str, Any]
    kind: str
    notify: Callable[[dict[str, Any]], None]
    identifier: str = field(default_factory=lambda: uuid4().hex)
    cancel: threading.Event = field(default_factory=threading.Event)
    lock: Any = field(default_factory=threading.Lock)
    thread: threading.Thread | None = None
    state: str = "running"
    message: str = "Starting AI workflow"
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    runner: StepRunner | None = None
    candidate: Proposal | Approach | None = None
    purpose: Completion | None = None
    checked_fingerprint: str = ""
    base_commit: str = ""
    recovered: bool = False
    source_changed: bool = False

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {**self.context, "workflow": {"id": self.identifier, "kind": self.kind,
                "state": self.state, "message": self.message, "result": self.result, "error": self.error,
                "sourceChanged": self.source_changed}}

    def progress(self, message: str) -> None:
        from icoda_core import recovery

        with self.lock:
            self.message = recovery.redact(message)
        self.notify({"method": "workflow.progress", "params": self.snapshot()})

    def run(self, work: Callable[[], Any], project: ProjectSession) -> None:
        from icoda_core import documentation, git, process, steps

        try:
            with process.cancellation_scope(self.cancel):
                value = work()
                if self.cancel.is_set() or self.context != project.context():
                    if isinstance(value, documentation.Completion):
                        documentation.reject(value)
                    raise steps.StepCancelled()
                if isinstance(value, (steps.Proposal, steps.Approach)):
                    self.candidate = value
                    self.base_commit = git.head_commit(value.worktree if isinstance(value, steps.Proposal) else project.store.root)
                    self.checked_fingerprint = candidate_fingerprint(value)
                    project.pending_proposal = True
                result = value if isinstance(value, dict) else workflow_result(value)
                if isinstance(value, documentation.Completion):
                    self.purpose = value
                if not isinstance(value, dict):
                    project.pending_proposal = True
                with self.lock:
                    self.result, self.state = result, "completed"
                    self.message = ("Reply ready." if isinstance(value, dict) else
                                    "Proposal ready for review; nothing approved or applied.")
        except Exception as exc:  # noqa: BLE001 - worker failures must produce a terminal status
            with self.lock:
                self.error = workflow_error(exc, self.cancel.is_set())
                self.result = self.error["details"].get("proposal")
                self.state = "cancelled" if self.error["code"] == "provider_cancelled" else "failed"
                self.message = self.error["message"]
        finally:
            self.notify({"method": "workflow.state", "params": self.snapshot()})


def workflow_error(error: Exception, cancelled: bool) -> dict[str, Any]:
    from icoda_core import recovery, steps

    if cancelled or isinstance(error, steps.StepCancelled):
        return {"code": "provider_cancelled", "message": "AI workflow cancelled.", "details": {}}
    if isinstance(error, ServiceError):
        return error.error
    if isinstance(error, steps.ProviderError):
        return {"code": "provider_failed", "message": recovery.redact(str(error)),
                "details": {"diagnosis": asdict(error.diagnosis)}}
    return {"code": "workflow_failed", "message": recovery.redact(str(error)), "details": {}}


def workflow_result(value: Any) -> dict[str, Any]:
    from icoda_core import documentation, recovery, steps

    if isinstance(value, documentation.Completion):
        outcome = value.response
        if not outcome.result.ok:
            raise steps.ProviderError(outcome.diagnosis or recovery.diagnose(outcome.result.stderr))
        return {"round": "purpose", "summary": recovery.redact(outcome.result.stdout)[:18000],
                "candidateLocation": str(value.candidate) if value.candidate else None,
                "files": [original.relative for original, _text in value.edits], "skipped": value.skipped}
    result = {"round": "approach" if isinstance(value, steps.Approach) else "code",
              "number": value.number, "attempts": value.attempts, "batch": list(value.request.batch),
              "focus": list(value.request.focus), "candidateLocation": None}
    if isinstance(value, steps.Approach):
        result.update(summary=recovery.redact(value.plan), files=list(value.files), entities=list(value.entities))
    else:
        result.update(summary=recovery.redact(value.response.rationale) if value.response else "",
            candidateLocation=str(value.worktree), delta=value.delta.summary() if value.delta else "",
            files=[item.path for item in value.response.files] if value.response else [],
            build={"ok": value.build.ok, "output": recovery.redact(value.build.output)},
            tests={"ok": value.test.ok, "output": recovery.redact(value.test.output)})
    if not value.ok:
        code = "provider_failed" if isinstance(value, steps.Approach) or value.response is None else "proposal_failed"
        raise ServiceError(code, recovery.redact(value.error), {"proposal": result})
    return result


def workflow_strings(params: dict[str, Any], key: str) -> tuple[str, ...]:
    value = params.get(key, [])
    if not isinstance(value, list) or len(value) > 1000:
        raise ServiceError("invalid_params", f"{key} must be a list of at most 1000 strings.")
    return tuple(_string({key: item}, key) for item in value)


def workflow_params(project: ProjectSession, method: str, params: dict[str, Any]) -> tuple[str, StepRequest | None]:
    from icoda_core import prompt

    required = ("idle", "unsavedDocuments") if method == "purpose.propose" else ("kind", "unsavedDocuments")
    optional = ("trusted", "provider", "model")
    _params(params, required, optional if method == "purpose.propose" else (*optional, "request", "focus", "maxEntities"))
    kind = "purpose" if method == "purpose.propose" else _string(params, "kind")
    if kind not in (*WORKFLOW_KINDS, "purpose") or (kind == "purpose" and method != "purpose.propose"):
        raise ServiceError("invalid_params", "Unknown workflow kind.")
    if kind == "purpose" and type(params["idle"]) is not bool:
        raise ServiceError("invalid_params", "idle must be a boolean.")
    workflow_strings(params, "unsavedDocuments")
    if kind == "purpose":
        return kind, None
    focus = workflow_strings(params, "focus")
    if any(item not in project.model.entities and item not in project.model.files for item in focus):
        raise ServiceError("invalid_params", "Context must contain analysed project file paths or entity IDs.")
    text = _string(params, "request") if "request" in params else ""
    limit = _integer(params, "maxEntities") if "maxEntities" in params else 5
    return kind, prompt.StepRequest(project.store.load_state().phase.value, 0, text, limit, focus=focus)


def review_params(method: str, params: dict[str, Any]) -> None:
    required = ("unsavedDocuments",) if method == "proposal.get" else ("unsavedDocuments", "evidenceFingerprint")
    extra = {"proposal.approve": ("confirmSignatures",), "proposal.reject": ("reason",),
             "proposal.adapt": ("constraints", "entitySummary")}.get(method, ())
    _params(params, required, ("trusted", *extra))
    workflow_strings(params, "unsavedDocuments")
    if method == "proposal.get":
        return
    require_trust(params)
    _string(params, "evidenceFingerprint")
    if "confirmSignatures" in params and type(params["confirmSignatures"]) is not bool:
        raise ServiceError("invalid_params", "confirmSignatures must be a boolean.")
    if method == "proposal.reject":
        _string(params, "reason")
    if method == "proposal.adapt":
        workflow_strings(params, "constraints")
        if "entitySummary" in params:
            _string(params, "entitySummary")


def review_error(error: StepError, method: str) -> ServiceError:
    """Translate core refusals without repeating any review or undo rules."""
    from icoda_core import recovery, steps

    if isinstance(error, steps.DirtyTree):
        code = "dirty_tree"
    elif isinstance(error, steps.SignatureConfirmationRequired):
        code = "signature_unconfirmed"
    else:
        code = "undo_disallowed" if method == "step.undo" else "proposal_gate_failed"
    return ServiceError(code, recovery.redact(str(error)))


def candidate_fingerprint(candidate: Proposal | Approach | None) -> str:
    from icoda_core import git, steps

    if isinstance(candidate, steps.Proposal):
        return git.review_fingerprint(candidate.worktree)
    return hashlib.sha256(repr(candidate).encode()).hexdigest()


def review_unsaved(project: ProjectSession, params: dict[str, Any]) -> tuple[str, ...]:
    from urllib.parse import unquote, urlparse

    relevant = []
    for document in workflow_strings(params, "unsavedDocuments"):
        uri = urlparse(document)
        if uri.scheme and uri.scheme != "file":
            relevant.append(document)  # Untitled/virtual buffers cannot be proven unrelated.
            continue
        path_text = unquote(uri.path) if uri.scheme == "file" else document
        if uri.scheme == "file" and uri.netloc and uri.netloc != "localhost":
            path_text = "//" + uri.netloc + path_text
        elif os.name == "nt" and uri.scheme == "file":
            path_text = path_text.lstrip("/")
        path = Path(path_text)
        if not path.is_absolute() or path.resolve().is_relative_to(project.store.root):
            relevant.append(document)
    return tuple(sorted(set(relevant)))


def review_fingerprint(project: ProjectSession, job: WorkflowJob | None, candidate_digest: str,
                       unsaved: tuple[str, ...]) -> str:
    from icoda_core import git

    workspace = git.review_fingerprint(project.store.root) if git.is_own_repository(project.store.root) else ""
    data = (project.context(), workspace, job.identifier if job else None,
            candidate_digest, unsaved)
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def require_review_evidence(project: ProjectSession, job: WorkflowJob | None, params: dict[str, Any],
                            reviewed: str | None) -> str:
    fingerprint = params["evidenceFingerprint"]
    candidate_digest = candidate_fingerprint(job.candidate) if job else ""
    unsaved = review_unsaved(project, params)
    if fingerprint != reviewed or fingerprint != review_fingerprint(project, job, candidate_digest, unsaved):
        raise ServiceError("stale_evidence", "Review evidence changed. Refresh the proposal review before deciding.")
    if unsaved:
        raise ServiceError("unsaved_documents", "Save or close unsaved project and candidate documents, then review again.")
    return candidate_digest


def review_record(record: StepRecord) -> dict[str, Any]:
    from icoda_core import recovery

    values = asdict(record)
    # Neither raw prompts/replies nor provider binary/authentication configuration belongs in review output.
    values.pop("binary", None)
    return {key: recovery.redact(value) if isinstance(value, str) else value for key, value in values.items()}


def review_history(project: ProjectSession) -> list[dict[str, Any]]:
    from icoda_core import steplog

    return [review_record(record) for record in steplog.StepLog(project.store.steps_path).records()]


def proposal_review(project: ProjectSession, job: WorkflowJob | None, params: dict[str, Any]) -> dict[str, Any]:
    from icoda_core import git

    candidate = job.candidate if job else None
    candidate_digest = candidate_fingerprint(candidate) if candidate else ""
    unsaved = review_unsaved(project, params)
    fresh = bool(job and job.checked_fingerprint == candidate_digest
                 and job.base_commit == git.head_commit(project.store.root))
    proposal = review_candidate(candidate) if candidate else None
    if proposal is not None and candidate is not None:
        proposal.update(evidenceFresh=fresh, canApprove=candidate.ok and fresh and not unsaved)
    return {**project.context(), "projectRoot": str(project.store.root), "proposal": proposal,
            "candidateGraph": candidate_graph(project, job) if fresh else None,
            "evidenceFingerprint": review_fingerprint(project, job, candidate_digest, unsaved), "records": review_history(project),
            "autoApprove": project.store.load_state().auto_approve,
            "message": "Review the candidate before deciding." if candidate else (
                "A retained candidate is available. Use Recover Interrupted Proposal to review it."
                if workflow_pending(project) else "No proposal awaiting review.")}


def candidate_graph(project: ProjectSession, job: WorkflowJob | None) -> dict[str, str] | None:
    """Bind candidate navigation to the same core inputs used for review, without approving it."""
    from icoda_core import steps

    candidate = job.candidate if job else None
    if not job or not isinstance(candidate, steps.Proposal) or candidate.model is None:
        return None
    fingerprint = review_fingerprint(project, job, job.checked_fingerprint, ())
    return {"sourceRootId": project.session_id + ":proposal:" + fingerprint,
            "root": str(candidate.worktree.resolve())}


def review_candidate(candidate: Proposal | Approach) -> dict[str, Any]:
    from icoda_core import adaptation, git, recovery, steps

    if isinstance(candidate, steps.Approach):
        return {"round": "approach", "number": candidate.number, "summary": recovery.redact(candidate.plan),
                "worktreeRoot": None, "files": [], "delta": "", "signatureChanges": [],
                "build": None, "tests": None, "entitySummary": "", "error": recovery.redact(candidate.error)}
    return {"round": "code", "number": candidate.number,
            "summary": recovery.redact(candidate.response.rationale) if candidate.response else "",
            "worktreeRoot": str(candidate.worktree),
            "files": [asdict(change) for change in git.status_changes(candidate.worktree)],
            "delta": candidate.delta.summary() if candidate.delta else "",
            "signatureChanges": [asdict(change) for change in candidate.delta.signature_changes] if candidate.delta else [],
            "build": {"ok": candidate.build.ok, "output": recovery.redact(candidate.build.output)},
            "tests": {"ok": candidate.test.ok, "output": recovery.redact(candidate.test.output)},
            "entitySummary": adaptation.render_summary(candidate.entities) if candidate.entities else "",
            "error": recovery.redact(candidate.error)}


def workflow_pending(project: ProjectSession) -> bool:
    return project.pending_proposal or (project.store.dir / "worktree").exists() \
        or (project.store.cache_dir / "interrupted-proposal.json").exists() \
        or any(project.store.cache_dir.glob("purpose-*"))


def workflow_readiness(project: ProjectSession, kind: str, params: dict[str, Any]) -> None:
    from icoda_core import documentation

    pending = workflow_pending(project)
    if kind == "purpose":
        reason = documentation.completion_refusal(idle=params["idle"], unsaved=bool(params["unsavedDocuments"]),
                                                  proposal=pending, model=project.model)
        if reason:
            raise ServiceError("purpose_not_ready", reason)
        if not documentation.missing_entities(project.model):
            raise ServiceError("purpose_not_ready", "No entities need purpose comments.")
    elif params["unsavedDocuments"]:
        raise ServiceError("unsaved_documents", "Save or close unsaved documents before starting an AI workflow.")
    if pending:
        raise ServiceError("proposal_pending", "An existing candidate must be reviewed before starting another workflow.")


def workflow_provider(project: ProjectSession, params: dict[str, Any]) -> tuple[Any, str, str, Any]:
    from icoda_core import agent, persistence

    config = persistence.UserConfig.load(persistence.config_path())
    saved = project.store.load_ui().get("provider") or {}
    provider_id = _string(params, "provider") if "provider" in params else saved.get("provider", config.provider)
    try:
        provider = agent.find_provider(agent.load_providers(), provider_id)
    except KeyError as exc:
        raise ServiceError("provider_unavailable", "Choose an installed ICODA provider/model.",
                           {"capability": list_providers(project, {})}) from exc
    binary = saved.get("binary", "") if saved.get("provider") == provider_id else ""
    if not provider.enabled or not agent.binary_available(provider, binary or None):
        raise ServiceError("provider_unavailable", f"{provider.label}: executable {binary or provider.command!r} "
                           f"is missing or the provider is disabled. Use Select Provider/Model. {provider.login_hint}",
                           {"provider": provider.id, "binary": binary or provider.command,
                            "loginHint": provider.login_hint, "capability": list_providers(project, {})})
    model_id = _string(params, "model") if "model" in params else (
        saved.get("model", "") if saved.get("provider") == provider_id else config.model if config.provider == provider_id else "")
    return provider, model_id or provider.default_model, agent.provider_binary(provider, binary or None) or binary or provider.command, config


class Service:
    """Dispatch validated requests without a GUI; track only explicitly owned operations."""

    def __init__(self, notify: Callable[[dict[str, Any]], None] = lambda _message: None) -> None:
        self.notify = notify
        self.operations: dict[Any, threading.Event] = {}
        self.operation_lock = threading.Lock()
        self.closing = False
        self.initialized = False
        self.interaction: WorkflowJob | None = None
        self.project: ProjectSession | None = None
        self.project_lock: ProjectLock | None = None
        self.workflow: WorkflowJob | None = None
        self.reviewed: str | None = None
        self.continuation: dict[str, Any] = {"state": "stopped", "reason": "Not started.", "ready": False}
        self.queue_options: dict[str, Any] = {}
        self.automatic_remaining: int | None = None

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        method, params = request.get("method"), request.get("params")
        if not isinstance(method, str) or not method:
            raise ServiceError("invalid_request", "method must be a nonempty string.")
        if not isinstance(params, dict):
            raise ServiceError("invalid_params", "params must be an object.")
        if method == "initialize":
            return self.initialize(params)
        if not self.initialized:
            raise ServiceError("not_initialized", "Call initialize before other methods.")
        if method not in METHODS:
            raise ServiceError("unknown_method", f"Unknown method: {method}")
        if method == "project.open":
            return self.open_project(params)
        if method == "project.create":
            if self.project is not None or "sessionId" in request:
                self.require_project(request)
            return self.create_project(params)
        if method == "toolchain.inspect":
            from icoda_core import process

            return inspect_toolchain(params, process.current_cancellation())
        if method == "operation.cancel":
            return self.cancel(params)
        project = self.require_project(request)
        if method == "project.close":
            _params(params)
            context = project.context()
            self.close_project()
            return {**context, "closed": True}
        if method in WORKFLOW_METHODS:
            return self.workflow_request(project, method, params)
        if method in QUEUE_METHODS:
            return self.queue_request(project, method, params)
        self.guard_workflow(method)
        if method in RECOVERY_METHODS:
            return self.recovery_request(project, method, params)
        if method in REVIEW_METHODS:
            return self.review_request(project, method, params)
        if method in OPERATIONS:
            return self.operate(project, request)
        return self.project_request(project, method, params)

    def cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        """Signal only the named queued/running operation; the shared runner kills its tree."""
        _params(params, ("requestId",))
        identifier = params["requestId"]
        if not _usable_id(identifier):
            raise ServiceError("invalid_params", "requestId must be a string or integer request ID.")
        with self.operation_lock:
            event = self.operations.get(identifier)
            if event is not None:
                event.set()
        return {"requestId": identifier, "cancellable": event is not None,
                "reason": "cancel_requested" if event is not None else "not_cancellable"}

    def cancel_all(self) -> None:
        with self.operation_lock:
            self.closing = True
            for event in self.operations.values():
                event.set()
            if self.workflow is not None:
                self.workflow.cancel.set()
            if self.interaction is not None:
                self.interaction.cancel.set()

    def supersede(self, request: dict[str, Any]) -> None:
        """The reader cancels old work; the worker still serializes all state changes."""
        if request.get("method") not in ("project.open", "project.close", "target.select"):
            return
        if request["method"] != "project.open":
            try:
                self.require_project(request)
            except ServiceError:
                return
        with self.operation_lock:
            for event in self.operations.values():
                event.set()

    def stop_workflow(self) -> None:
        self.stop_continuation("Cancelled or project selection changed.")
        self.queue_options = {}
        for job in (self.workflow, self.interaction):
            if job is not None:
                job.cancel.set()
                if job.thread is not None:
                    job.thread.join()
        self.interaction = None

    def close_project(self) -> None:
        self.stop_workflow()
        self.workflow, self.project, self.reviewed = None, None, None
        if self.project_lock is not None:
            self.project_lock.close()
            self.project_lock = None

    def guard_workflow(self, method: str) -> None:
        if not any(job and job.thread and job.thread.is_alive() for job in (self.workflow, self.interaction)):
            return
        if method in (*OPERATIONS, *REVIEW_METHODS, "recovery.resolve", "project.analyse", "spec.save", "phase.transition", "providers.select"):
            raise ServiceError("workflow_busy", "Cancel the active AI workflow before changing project state.")

    def stop_continuation(self, reason: str) -> None:
        self.continuation = {"state": "stopped", "reason": reason, "ready": False}
        self.automatic_remaining = None

    def queue_payload(self, project: ProjectSession) -> dict[str, Any]:
        from icoda_core import auto_approve, grouping, implementation_queue, steps

        state = project.store.load_state()
        job = self.workflow if self.workflow and self.workflow.context == project.context() else None
        if self.continuation["state"] == "running":
            if not state.auto_approve:
                self.stop_continuation("Automatic approval is disabled.")
            elif job and job.cancel.is_set():
                self.stop_continuation("Cancelled.")
            elif job and job.state == "running":
                self.continuation["ready"] = False
            elif job and job.candidate is not None:
                if job.recovered:
                    self.stop_continuation("Recovered proposals require explicit review and approval.")
                    return self.queue_payload(project)
                decision = auto_approve.derive(state.phase, job.candidate,
                    approach_round=isinstance(job.candidate, steps.Approach))
                if not decision.permitted:
                    self.stop_continuation(decision.reason)
                elif job.error:
                    self.stop_continuation(job.error["message"])
                else:
                    self.continuation["ready"] = True
            elif job and job.error:
                self.stop_continuation(job.error["message"])
            elif implementation_queue.remaining(state) == 0 or self.automatic_remaining == 0:
                self.stop_continuation("The implementation queue is empty; automatic approval stopped.")
            else:
                self.continuation["ready"] = True
        return {**project.context(), "workflow": job.snapshot()["workflow"] if job else None,
                "queueSettings": {"batchSize": state.implementation_batch_size,
                    "scope": state.implementation_scope, "grouping": state.implementation_grouping,
                    "autoApprove": state.auto_approve,
                    "scopes": [{"value": value.value, "label": label} for value, label in implementation_queue.SCOPE_LABELS],
                    "groupings": [{"value": value.value, "label": label} for value, label in grouping.GROUPING_LABELS]},
                "continuation": dict(self.continuation)}

    def queue_request(self, project: ProjectSession, method: str, params: dict[str, Any]) -> dict[str, Any]:
        from icoda_core import implementation_queue, steps

        require_trust(params)
        if method == "queue.settings.get":
            _params(params, (), ("trusted",))
            return self.queue_payload(project)
        if method == "queue.settings.set":
            _params(params, ("settings",), ("trusted",))
            settings = params["settings"]
            if not isinstance(settings, dict) or not settings:
                raise ServiceError("invalid_params", "settings must be a nonempty object.")
            _params(settings, (), ("batchSize", "scope", "grouping", "autoApprove"))
            for key in ("scope", "grouping"):
                if key in settings:
                    _string(settings, key)
            if "batchSize" in settings:
                _integer(settings, "batchSize")
            if "autoApprove" in settings and type(settings["autoApprove"]) is not bool:
                raise ServiceError("invalid_params", "autoApprove must be a boolean.")
            self.guard_workflow("proposal.approve")
            try:
                state = implementation_queue.update_settings(project.store.load_state(), model=project.model,
                    batch_size=settings.get("batchSize"), scope=settings.get("scope"),
                    grouping_mode=settings.get("grouping"), auto_approve=settings.get("autoApprove"))
            except ValueError as exc:
                raise ServiceError("invalid_params", str(exc)) from exc
            project.store.save_state(state)
            self.stop_continuation("Queue settings changed. Run Implementation Queue to continue.")
            if settings == {"autoApprove": True} and self.review_job(project) is not None:
                self.continuation = {"state": "running", "reason": "", "ready": True}
            return self.queue_payload(project)
        _params(params, ("unsavedDocuments",), ("trusted", "provider", "model", "request", "focus", "evidenceFingerprint"))
        workflow_params(project, "workflow.start", {key: value for key, value in
            {**params, "kind": "implementation_queue"}.items() if key != "evidenceFingerprint"})
        self.guard_workflow("proposal.approve")
        state = implementation_queue.ensure_state(project.store, project.model)
        if state.phase.value != "implementation":
            self.stop_continuation("Automatic continuation requires the implementation phase.")
            return self.queue_payload(project)
        if not state.auto_approve:
            self.stop_continuation("Automatic approval is disabled.")
            return self.queue_payload(project)
        check_cancelled(project.context())
        job = self.review_job(project)
        if self.workflow and self.workflow.cancel.is_set():
            self.stop_continuation("Cancelled. Decide any retained candidate before starting again.")
            return self.queue_payload(project)
        if params["unsavedDocuments"]:
            self.stop_continuation("Save or close unsaved documents before continuing.")
            raise ServiceError("unsaved_documents", self.continuation["reason"])
        if self.automatic_remaining is None:
            self.automatic_remaining = implementation_queue.remaining(state)
        self.continuation = {"state": "running", "reason": "", "ready": True}
        payload = self.queue_payload(project)
        if payload["continuation"]["state"] == "stopped":
            return payload
        if implementation_queue.remaining(state) == 0 or self.automatic_remaining == 0:
            self.stop_continuation("The implementation queue is empty; automatic approval stopped.")
            return self.queue_payload(project)
        if job and job.candidate is not None:
            _string(params, "evidenceFingerprint")
            try:
                result = self.review_request(project, "proposal.approve", {
                    "trusted": True, "unsavedDocuments": params["unsavedDocuments"],
                    "evidenceFingerprint": params["evidenceFingerprint"]})
            except (ServiceError, steps.StepError) as exc:
                from icoda_core import process

                event = process.current_cancellation()
                self.stop_continuation("Cancelled." if event and event.is_set() else str(exc))
                raise
            assert self.automatic_remaining is not None
            self.automatic_remaining -= 1
            return {**self.queue_payload(project), "decision": result}
        self.queue_options = {key: value for key, value in params.items()
                              if key not in ("unsavedDocuments", "trusted", "evidenceFingerprint")} or self.queue_options
        try:
            self.start_workflow(project, "workflow.start", {**self.queue_options,
                "kind": "implementation_queue", "unsavedDocuments": [], "trusted": True})
        except Exception as exc:
            self.stop_continuation(str(exc))
            raise
        return self.queue_payload(project)

    def workflow_request(self, project: ProjectSession, method: str, params: dict[str, Any]) -> dict[str, Any]:
        require_trust(params)
        if method == "purpose.status":
            workflow_params(project, "purpose.propose", params)
            try:
                self.guard_workflow("proposal.approve")
                if self.operations or self.continuation["state"] == "running":
                    raise ServiceError("purpose_not_ready", "Wait until ICODA is idle.")
                workflow_readiness(project, "purpose", params)
                workflow_provider(project, params)
            except ServiceError as exc:
                return {**project.context(), "ready": False, "reason": exc.error["message"]}
            return {**project.context(), "ready": True, "reason": ""}
        if method in ("conversation.send", "conversation.history", "prompt.rephrase", "cli.command"):
            return self.interaction_request(project, method, params)
        if method in ("workflow.start", "purpose.propose"):
            return self.start_workflow(project, method, params)
        if method in ("purpose.apply", "purpose.reject"):
            return self.decide_purpose(project, method, params)
        _params(params, (), ("trusted", "workflowId"))
        job = self.workflow
        identifier = _string(params, "workflowId") if "workflowId" in params else None
        interaction = self.interaction
        if interaction and interaction.context == project.context() and (
                identifier == interaction.identifier or identifier is None and interaction.state == "running"):
            if method == "workflow.cancel":
                interaction.cancel.set()
            return interaction.snapshot()
        if method == "workflow.cancel" and identifier is None:
            self.stop_continuation("Cancelled.")
        if job is None or job.context != project.context():
            if identifier:
                raise ServiceError("workflow_missing", "No workflow in this project revision.")
            return self.queue_payload(project)
        if identifier is not None and identifier != job.identifier:
            raise ServiceError("workflow_missing", "Unknown workflow ID.")
        if method == "workflow.cancel":
            job.cancel.set()
            self.stop_continuation("Cancelled.")
        return self.queue_payload(project)

    def interaction_request(self, project: ProjectSession, method: str, params: dict[str, Any]) -> dict[str, Any]:
        from icoda_core import agent, recovery, steps, terminal

        if method == "conversation.history":
            _params(params, (), ("trusted",))
            return {**project.context(), "messages": [
                {"role": role, "text": recovery.redact(text)} for role, text in project.conversation]}
        required = ("message", "unsavedDocuments") if method == "conversation.send" else ("unsavedDocuments",)
        _params(params, required, ("trusted", "provider", "model", "draft") if method == "cli.command"
                else ("trusted", "provider", "model"))
        unsaved = workflow_strings(params, "unsavedDocuments")
        message = _string(params, "message") if method == "conversation.send" else ""
        draft = _string(params, "draft") if "draft" in params else ""
        if len(message) > 20000 or len(draft) > 20000:
            raise ServiceError("invalid_params", "Conversation input is limited to 20000 characters.")
        self.guard_workflow("proposal.approve")
        review = self.review_job(project)
        candidate = review.candidate if review else None
        cwd = candidate.worktree if isinstance(candidate, steps.Proposal) else project.store.root
        if method != "prompt.rephrase":
            if unsaved:
                raise ServiceError("unsaved_documents", "Save or close unsaved documents before requesting project edits.")
            if workflow_pending(project) and candidate is None:
                raise ServiceError("proposal_pending", "Review the retained candidate before requesting project edits.")
        else:
            if candidate is None:
                raise ServiceError("proposal_missing", "No current proposal or pending approach to rephrase.")
            description, context = steps.rephrase_context(candidate)
            if not description.strip():
                raise ServiceError("proposal_missing", "No current step description to rephrase.")
        provider, model_id, binary, config = workflow_provider(project, params)
        if method == "cli.command":
            history = [*project.conversation, *([("Developer", draft)] if draft else [])]
            context = recovery.conversation_prompt(project.conversation_issue, history, cwd, interactive=True)
            try:
                argv = terminal.interactive_command(provider, binary, model_id, cwd, context)
            except ValueError as exc:
                raise ServiceError("provider_unavailable", str(exc), {"provider": provider.id}) from exc
            self.stop_continuation("Interactive CLI requires explicit review before continuing.")
            # Empty overrides inherit the extension host environment; no shell or terminal is spawned here.
            return {**project.context(), "argv": argv, "cwd": str(cwd), "env": {}}
        if method == "conversation.send":
            try:
                agent.editing_provider(provider)
            except ValueError as exc:
                raise ServiceError("provider_unavailable", str(exc), {"provider": provider.id}) from exc
        self.stop_continuation("Conversation/rephrase requires explicit review before continuing.")
        job = WorkflowJob(project.context(), method, self.notify)
        runner = steps.StepRunner(project.store.root, config, provider.id, binary, model_id,
                                  progress=job.progress, cancelled=job.cancel.is_set)
        job.runner = runner
        if method == "conversation.send":
            project.conversation.append(("Developer", message))
            request = recovery.conversation_prompt(project.conversation_issue, project.conversation, cwd, writable=True)

        def changed(value: bool) -> None:
            job.source_changed = value
            if value:
                project.model.stale = True
                project.model.stale_reason = "Conversation edited source. Analyse Project to refresh source facts."
                project.store.save_model(project.model)

        def work() -> dict[str, Any]:
            if method == "conversation.send":
                outcome = recovery.send_conversation(provider, model_id, request, cwd, binary=binary,
                    cancelled=job.cancel.is_set, changed=changed, progress=job.progress)
                if job.cancel.is_set() or outcome.result.cancelled:
                    raise steps.StepCancelled()
                if not outcome.result.ok:
                    issue = outcome.diagnosis or recovery.diagnose(outcome.result.stderr or outcome.result.stdout)
                    project.conversation_issue = issue
                    project.conversation.append(("Assistant", issue.text()))
                    raise steps.ProviderError(issue)
                answer = outcome.result.stdout
                project.conversation.append(("Assistant", answer))
            else:
                try:
                    answer = runner.rephrase_description(description, context=context)
                except steps.StepError as exc:
                    if isinstance(exc, (steps.ProviderError, steps.StepCancelled)):
                        raise
                    raise ServiceError("provider_failed", str(exc), {"provider": provider.id}) from exc
                assert candidate is not None
                if job.cancel.is_set() or job.context != project.context():
                    raise steps.StepCancelled()
                fresh = review is not None and review.checked_fingerprint == candidate_fingerprint(candidate)
                steps.replace_description(candidate, answer)
                if fresh and review is not None and isinstance(candidate, steps.Approach):
                    review.checked_fingerprint = candidate_fingerprint(candidate)
                if review is not None and review.result is not None:
                    review.result["summary"] = recovery.redact(answer)
                # Prose changes invalidate a previously displayed review token, never its build/test evidence.
                self.reviewed = None
            return {"round": method, "summary": recovery.redact(answer), "files": [], "candidateLocation": None}

        with self.operation_lock:
            if self.closing:
                raise ServiceError("provider_cancelled", "The backend is shutting down.")
            self.interaction = job
            job.thread = threading.Thread(target=job.run, args=(work, project), name="icoda-interaction")
            job.thread.start()
        return job.snapshot()

    def decide_purpose(self, project: ProjectSession, method: str, params: dict[str, Any]) -> dict[str, Any]:
        from icoda_core import documentation

        _params(params, ("workflowId", "idle", "unsavedDocuments"), ("trusted",))
        identifier = _string(params, "workflowId")
        workflow_strings(params, "unsavedDocuments")
        if type(params["idle"]) is not bool:
            raise ServiceError("invalid_params", "idle must be a boolean.")
        self.guard_workflow("proposal.approve")
        job = self.workflow
        if job is None or job.identifier != identifier or job.context != project.context() or job.purpose is None:
            raise ServiceError("purpose_missing", "No checked purpose-comment candidate in this project revision.")
        completion = job.purpose
        skipped = completion.skipped
        if method == "purpose.apply":
            refusal = documentation.completion_refusal(
                idle=params["idle"] and not self.operations, unsaved=bool(review_unsaved(project, params)),
                proposal=job.candidate is not None or (project.store.dir / "worktree").exists(), model=project.model)
            if refusal:
                raise ServiceError("purpose_not_ready", refusal)
            try:
                documentation.validate_candidate(completion)
            except (OSError, ValueError) as exc:
                raise ServiceError("stale_evidence", "Purpose-comment source or candidate changed. Reject it and propose again.") from exc
            changed, skipped = documentation.apply(completion)
            if changed:
                project.model.stale = True
                project.model.stale_reason = "Purpose comments applied. Analyse Project to refresh source facts."
                project.store.save_model(project.model)
        documentation.reject(completion)
        assert job.runner is not None
        result = self.finish_review(project, None, job.runner, refresh=False)
        return {**result, "workflow": None, "decision": "applied" if method == "purpose.apply" else "rejected",
                "skipped": skipped}

    def start_workflow(self, project: ProjectSession, method: str, params: dict[str, Any]) -> dict[str, Any]:
        from icoda_core import steps

        kind, request = workflow_params(project, method, params)
        self.guard_workflow("proposal.approve")
        workflow_readiness(project, kind, params)
        provider, model_id, binary, config = workflow_provider(project, params)
        if kind in ("implementation_queue", "implementation_approach"):
            self.queue_options = {key: value for key, value in params.items()
                                  if key in ("provider", "model", "request", "focus")}
        job = WorkflowJob(project.context(), kind, self.notify)
        runner = steps.StepRunner(project.store.root, config, provider.id, binary, model_id,
                                  progress=job.progress, cancelled=job.cancel.is_set,
                                  checkpoint=lambda candidate: self.checkpoint(project, candidate))
        job.runner = runner
        def work() -> Any:
            from icoda_core import documentation
            if kind == "purpose":
                return documentation.propose(project.store.root, project.model, provider, model_id, binary,
                    idle=params["idle"], unsaved=bool(params["unsavedDocuments"]), proposal=project.pending_proposal,
                    cancelled=job.cancel.is_set, progress=job.progress)
            assert request is not None
            return steps.run_workflow(runner, request, kind)
        with self.operation_lock:
            if self.closing:
                raise ServiceError("provider_cancelled", "The backend is shutting down.")
            self.workflow = job
            job.thread = threading.Thread(target=job.run, args=(work, project), name="icoda-workflow")
            job.thread.start()
        return job.snapshot()

    @staticmethod
    def checkpoint(project: ProjectSession, candidate: Proposal | Approach) -> None:
        from icoda_core import recovery

        recovery.checkpoint_proposal(project.store.root, candidate)

    def recovery_request(self, project: ProjectSession, method: str, params: dict[str, Any]) -> dict[str, Any]:
        from icoda_core import git, persistence, recovery, steps

        require_trust(params)
        required = () if method == "recovery.list" else ("recoveryId", "choice", "unsavedDocuments")
        _params(params, required, ("trusted",) if method == "recovery.list" else ("trusted", "confirmDiscard"))
        try:
            if method == "recovery.list":
                active = self.workflow and self.workflow.context == project.context() and (
                    self.workflow.state == "running" or self.workflow.candidate is not None)
                return {**project.context(), "items": [] if active else recovery.interrupted_proposals(project.store.root)}
            if self.review_job(project):
                raise ServiceError("proposal_pending", "The current proposal is already available for review.")
            identifier, choice = _string(params, "recoveryId"), _string(params, "choice")
            if "confirmDiscard" in params and type(params["confirmDiscard"]) is not bool:
                raise ServiceError("invalid_params", "confirmDiscard must be a boolean.")
            if review_unsaved(project, params) and choice != "keep":
                raise ServiceError("unsaved_documents", "Save or close unsaved project and candidate documents first.")
            runner = steps.StepRunner(project.store.root, persistence.UserConfig())
            candidate = recovery.resolve_proposal(runner, identifier, choice, confirmed=params.get("confirmDiscard", False))
            self.stop_continuation("Interrupted proposal recovery requires explicit review.")
            if candidate is not None:
                return self.resume_proposal(project, runner, candidate)
            if choice == "discard":
                project.pending_proposal = False
                self.workflow, self.reviewed = None, None
            return {**project.context(), "items": recovery.interrupted_proposals(project.store.root)}
        except recovery.ProposalRecoveryError as exc:
            raise ServiceError(exc.code, str(exc)) from exc
        except steps.StepError as exc:
            raise review_error(exc, method) from exc
        except git.GitError as exc:
            raise ServiceError("git_failed", recovery.redact(str(exc))) from exc

    def resume_proposal(self, project: ProjectSession, runner: StepRunner, candidate: Proposal | Approach) -> dict[str, Any]:
        from icoda_core import git, steps

        job = WorkflowJob(project.context(), "recovery", self.notify, runner=runner, candidate=candidate,
                          base_commit=git.head_commit(project.store.root), recovered=True)
        runner.progress, runner.cancelled = job.progress, job.cancel.is_set
        runner.checkpoint = lambda value: self.checkpoint(project, value)
        project.pending_proposal, self.reviewed = True, None
        with self.operation_lock:
            if self.closing:
                raise ServiceError("provider_cancelled", "The backend is shutting down.")
            self.workflow = job
            work = (lambda: runner.rebuild(candidate)) if isinstance(candidate, steps.Proposal) and candidate.response else (lambda: candidate)
            job.thread = threading.Thread(target=job.run, args=(work, project), name="icoda-recovery")
            job.thread.start()
        return job.snapshot()

    def review_job(self, project: ProjectSession) -> WorkflowJob | None:
        job = self.workflow
        return job if job and job.context == project.context() and job.candidate is not None else None

    def review_request(self, project: ProjectSession, method: str, params: dict[str, Any]) -> dict[str, Any]:
        from icoda_core import git, persistence, steps

        if method == "history.list":
            _params(params)
            return {**project.context(), "records": review_history(project)}
        review_params(method, params)
        job = self.review_job(project)
        if method == "proposal.get":
            result = proposal_review(project, job, params)
            self.reviewed = result["evidenceFingerprint"]
            return result
        runner = job.runner if job else steps.StepRunner(project.store.root, persistence.UserConfig())
        assert runner is not None
        try:
            if method != "step.commitManual" and git.is_own_repository(project.store.root):
                runner._require_clean()
            candidate_digest = require_review_evidence(project, job, params, self.reviewed)
            if method in ("step.undo", "step.commitManual"):
                if workflow_pending(project):
                    raise ServiceError("proposal_pending", "Decide the current proposal before changing project history.")
                record = runner.undo() if method == "step.undo" else runner.commit_manual_edits()
                return self.finish_review(project, record, runner, refresh=True)
            if job is None or job.candidate is None:
                raise ServiceError("proposal_missing", "No proposal is available in this project revision.")
            return self.decide_proposal(project, job, method, params, candidate_digest)
        except steps.StepError as exc:
            raise review_error(exc, method) from exc

    def decide_proposal(self, project: ProjectSession, job: WorkflowJob, method: str,
                        params: dict[str, Any], candidate_digest: str) -> dict[str, Any]:
        from icoda_core import git, recovery, steps

        runner, candidate = job.runner, job.candidate
        assert runner is not None and candidate is not None
        if method in ("proposal.approve", "proposal.adapt") and job.checked_fingerprint != candidate_digest:
            raise ServiceError("stale_evidence", "Candidate inputs changed. Rebuild the proposal before deciding.")
        if method in ("proposal.adapt", "proposal.rebuild"):
            return self.revise_proposal(project, job, method, params)
        if method == "proposal.approve":
            if job.base_commit != git.head_commit(project.store.root):
                raise ServiceError("stale_evidence", "Candidate inputs changed. Rebuild the proposal before approval.")
            record = runner.approve_reviewed(candidate, params.get("confirmSignatures", False))
        else:
            reason = _string(params, "reason")
            if isinstance(candidate, steps.Approach):
                record = runner.reject_approach(candidate, reason)
            else:
                record = runner.reject(candidate, reason)
        if isinstance(candidate, steps.Proposal):
            git.remove_worktree(project.store.root, candidate.worktree)
        recovery.proposal_journal(project.store.root).unlink(missing_ok=True)
        result = self.finish_review(project, record, runner, refresh=method == "proposal.approve")
        if method == "proposal.approve" and project.store.load_state().auto_approve and (
                isinstance(candidate, steps.Approach) or params.get("confirmSignatures", False)):
            self.continuation = {"state": "running", "reason": "", "ready": True}
        elif method == "proposal.reject":
            self.stop_continuation("Proposal rejected.")
        return result

    def revise_proposal(self, project: ProjectSession, previous: WorkflowJob, method: str,
                        params: dict[str, Any]) -> dict[str, Any]:
        from icoda_core import git, steps

        runner, candidate = previous.runner, previous.candidate
        assert runner is not None and candidate is not None
        if method == "proposal.rebuild" and not isinstance(candidate, steps.Proposal):
            raise ServiceError("invalid_params", "Only code proposals can be rebuilt.")
        if previous.base_commit != git.head_commit(project.store.root):
            raise ServiceError("stale_evidence", "Project HEAD changed. Reject this candidate and propose again.")
        if previous.recovered and method == "proposal.adapt":
            provider, model_id, binary, config = workflow_provider(project, {})
            runner.provider_id, runner.binary, runner.model_id, runner.config = provider.id, binary, model_id, config
        job = WorkflowJob(project.context(), previous.kind, self.notify, runner=runner,
                          candidate=candidate, checked_fingerprint=previous.checked_fingerprint,
                          base_commit=previous.base_commit, recovered=previous.recovered)
        runner.progress, runner.cancelled = job.progress, job.cancel.is_set
        def work() -> Any:
            try:
                if method == "proposal.rebuild":
                    assert isinstance(candidate, steps.Proposal)
                    return runner.rebuild(candidate)
                return runner.adapt(candidate, workflow_strings(params, "constraints"), params.get("entitySummary"))
            except (steps.ProviderError, steps.StepCancelled):
                raise
            except steps.StepError as exc:
                raise review_error(exc, method) from exc
        self.reviewed = None
        with self.operation_lock:
            if self.closing:
                raise ServiceError("provider_cancelled", "The backend is shutting down.")
            self.workflow = job
            job.thread = threading.Thread(target=job.run, args=(work, project), name="icoda-review")
            job.thread.start()
        return job.snapshot()

    def finish_review(self, project: ProjectSession, record: StepRecord | None, runner: StepRunner,
                      *, refresh: bool) -> dict[str, Any]:
        project.pending_proposal = False
        self.workflow, self.reviewed = None, None
        if refresh:
            project.model = runner.current_model()
            if record is not None and record.decision in ("undone", "manual"):
                project.model.stale = True
                project.model.stale_reason = "Project source changed. Analyse Project to refresh source facts."
            project.model_available = True
        project.revision += 1
        project.playback, project.trace_id = None, None
        return {**project.snapshot(), "record": review_record(record) if record else None,
                "records": review_history(project)}

    def operate(self, project: ProjectSession, request: dict[str, Any]) -> dict[str, Any]:
        """Adapt shared target operations to protocol context and structured notifications."""
        from icoda_core import executables, steps

        method, identifier = request["method"], request.get("id")
        options, overrides = operation_params(method, request["params"])
        whole_build = method == "build.run" and project.selected is None
        if method in ("target.run", "trace.record") and project.selected is None:
            raise ServiceError("invalid_target", "Select an executable to run or record.")
        if method in ("target.run", "trace.record") and project.selected and project.selected.is_library:
            raise ServiceError("invalid_target", "Select an executable to run or record.")
        with self.operation_lock:
            event = self.operations.setdefault(identifier, threading.Event())
        context = project.context()
        def notify(kind: str, text: str) -> None:
            self.notify({"method": "operation." + kind,
                         "params": {**context, "requestId": identifier, "message": text}})
        try:
            if event.is_set():
                raise steps.StepCancelled()
            notify("progress", "Inspecting toolchain")
            report = operation_tools(method, project, overrides, event)
            environment = {**os.environ, **report["environment"]}
            paths = {tool["name"]: tool["path"] for tool in report["tools"] if tool["path"]}
            if whole_build or method == "tests.run":
                result = project_check(project, method, environment, paths, event, notify)
                self.require_project(request)
                return result
            outcome = executables.operate(project.store.root, project.model, project.selected,
                OPERATIONS[method], event.is_set, options, environment=environment, tools=paths,
                cancel_event=event, progress=lambda text: notify("progress", text),
                log=lambda text: notify("log", text))
            if event.is_set():
                raise steps.StepCancelled()
            self.require_project(request)
            result = operation_result(project, method, outcome)
            notify("progress", outcome.message)
            return result
        except steps.StepCancelled as exc:
            raise ServiceError("cancelled", "Target operation cancelled.", context) from exc
        except (steps.StepError, OSError, ValueError) as exc:
            code = "cancelled" if event.is_set() else (
                "test_failed" if method == "tests.run" else
                "run_failed" if getattr(exc, "stage", "").startswith("Running ") else "build_failed")
            raise ServiceError(code, str(exc), context) from exc
        finally:
            with self.operation_lock:
                self.operations.pop(identifier, None)

    def project_request(self, project: ProjectSession, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Route project operations only after their identity has been checked."""
        if method == "providers.select":
            result = select_provider(project, params)
            self.stop_continuation("Provider selection changed. Run Implementation Queue to continue.")
            self.queue_options = {}
            return result
        if method in ("view.state.get", "view.state.set"):
            if params.get("view") == "file":
                return file_view_state(project, method, params)
            return diagram_view_state(project, method, params)
        if method in ("cluster.pin", "cluster.unpin", "cluster.rename", "cluster.assignFile"):
            return edit_cluster(project, method, params)
        handlers = {"project.analyse": self.analyse_project, "source.resolve": self.resolve_source,
                    "targets.list": self.list_targets, "target.select": self.select_target,
                    "view.get": self.get_view, "view.revealFile": reveal_file, "trace.load": self.load_trace,
                    "graph.interactions": self.graph_interactions,
                    "mindmap.setExpanded": set_mindmap_expanded, "mindmap.step": mindmap_step,
                    "issues.list": list_issues, "coverage.get": get_coverage,
                    "spec.get": get_specification, "spec.validate": validate_specification,
                    "spec.save": self.save_specification, "phase.get": get_phase,
                    "phase.transition": transition_phase, "providers.list": list_providers}
        if method in handlers:
            return handlers[method](project, params)
        return self.navigate_trace(project, method, params)

    def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        _params(params, ("protocolVersion",))
        version = _integer(params, "protocolVersion")
        if version != PROTOCOL_VERSION:
            raise ServiceError("protocol_version_mismatch", "Unsupported protocol version.",
                               {"supportedVersions": [PROTOCOL_VERSION], "requestedVersion": version})
        if self.initialized:
            raise ServiceError("already_initialized", "This connection is already initialized.")
        self.initialized = True
        return {"protocolVersion": PROTOCOL_VERSION, "backendVersion": __version__,
                "capabilities": {"methods": list(METHODS), "cancellation": True,
                                 "cancellableMethods": list(CANCELLABLE), "projectLock": True,
                                 "workflowKinds": list(WORKFLOW_KINDS), "purposeComments": True,
                                 "proposalReview": True, "candidateCallView": True, "automaticAnalysis": True,
                                 "specificationPostSave": True,
                                 "targetSelection": True, "views": ["call", "file", "class", "mindmap"],
                                 "maxMessageBytes": MAX_MESSAGE_BYTES},
                "runtime": {"python": sys.executable}, "analysisTimeoutSeconds": ANALYSIS_TIMEOUT}

    def create_project(self, params: dict[str, Any]) -> dict[str, Any]:
        from icoda_core import persistence, session

        _params(params, ("parentPath", "name", "language"), ("summary", "trusted"))
        if params.get("trusted") is not True:
            raise ServiceError("not_trusted", "Trust this workspace before creating an ICODA project.")
        parent = Path(_string(params, "parentPath"))
        name, language = _string(params, "name"), _string(params, "language")
        summary = params.get("summary", "")
        if not isinstance(summary, str) or "\0" in summary:
            raise ServiceError("invalid_params", "summary must be a string without NULs.")
        try:
            summary.encode("utf-8")
            root, written = session.create_project(parent, name, language, summary)
        except FileExistsError as exc:
            raise ServiceError("target_exists", "The target already exists. Choose a new project name.") from exc
        except ValueError as exc:
            raise ServiceError("invalid_params", str(exc)) from exc
        except OSError as exc:
            raise ServiceError("project_create_failed", str(exc)) from exc
        store = persistence.ProjectStore(root)
        return {"root": str(root), "writtenFiles": written, "specificationPath": str(store.specification_path),
                "state": store.load_state().to_dict()}

    def open_project(self, params: dict[str, Any]) -> dict[str, Any]:
        _params(params, ("path",))
        root = Path(_string(params, "path"))
        if not root.is_absolute():
            raise ServiceError("invalid_params", "project.open path must be an absolute folder path.")
        root = root.resolve()
        if not root.is_dir():
            raise ServiceError("project_missing", "Project folder does not exist.", {"path": str(root)})
        lock = self.project_lock
        if lock is None or self.project is None or self.project.store.root != root:
            lock = ProjectLock(root)
        try:
            return self.install_project(root, lock)
        except BaseException:
            if lock is not self.project_lock:
                lock.close()
            raise

    def install_project(self, root: Path, lock: ProjectLock) -> dict[str, Any]:
        from icoda_core import persistence
        from icoda_core.model import DerivedModel

        self.stop_workflow()
        try:
            store = persistence.ProjectStore(root)
            state, ui, layout = store.load_state(), store.load_ui(), store.load_layout()
            cached = store.load_model()
        except Exception as exc:
            raise ServiceError("project_open_failed", str(exc), {"path": str(root)}) from exc
        model = cached if cached is not None else DerivedModel(
            str(root), stale=True, stale_reason="Project has not been analysed.")
        model.root = str(root)
        if cached is not None and not model.stale:
            changed = cached_source_changes(root, model)
            if changed:
                model.stale = True
                model.stale_reason = ("Cached source changed or is missing: " + ", ".join(changed[:5])
                                      + ". Run ICODA: Analyse Project to refresh the model.")
        project = ProjectSession(store, model, model_available=cached is not None)
        discover_targets(project, ui.get("executable"))
        if self.project_lock is not None and self.project_lock is not lock:
            self.project_lock.close()
        self.project_lock = lock
        self.workflow, self.reviewed = None, None
        self.stop_continuation("Not started.")
        self.project = project
        return {**project.snapshot(), "cached": cached is not None, "state": state.to_dict(),
                "ui": ui, "layout": layout.to_dict()}

    def require_project(self, request: dict[str, Any]) -> ProjectSession:
        project = self.project
        if project is None:
            raise ServiceError("project_not_open", "Open an explicit project folder first.")
        session_id = _string(request, "sessionId")
        revision = _integer(request, "modelRevision")
        if "targetId" not in request:
            raise ServiceError("invalid_params", "targetId is required (null for Whole Project).")
        if request["targetId"] is not None:
            _string(request, "targetId")
        if session_id != project.session_id:
            raise ServiceError("invalid_session", "This request belongs to another project session.")
        if revision != project.revision:
            raise ServiceError("stale_revision", "The model revision has changed.", project.context())
        if request["targetId"] != target_id(project.selected):
            raise ServiceError("stale_target", "The selected target has changed.", project.context())
        return project

    def analyse_project(self, project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
        from icoda_core import source_watch

        _params(params, optional=("automatic", "unsavedDocuments"))
        automatic = _boolean(params, "automatic") if "automatic" in params else False
        if automatic:
            if review_unsaved(project, params):
                raise ServiceError("unsaved_documents", "Automatic analysis waits for saved project documents.")
            if workflow_pending(project):
                raise ServiceError("proposal_pending", "Automatic analysis waits until the candidate is decided.")
        before = source_watch.snapshot_project(project.store.root) if automatic else None
        candidate, toolchain, diagnostics, failed = analyse_candidate(project)
        try:
            check_cancelled(project.context())
        except ServiceError:
            # The analysis child may have written a candidate cache before cancellation.
            project.store.save_model(project.model)
            raise
        if failed:
            # The child can overwrite its cache before reporting failure; retain our last published model.
            project.model.stale = True
            project.model.stale_reason = "; ".join(d["message"] for d in diagnostics) or (
                candidate.stale_reason if candidate is not None else "") or "Analysis did not produce a model."
        else:
            assert candidate is not None
            project.model = candidate
            project.model.stale_reason = ""
            project.model_available = True
        if before is not None and before != source_watch.snapshot_project(project.store.root):
            project.model.stale = True
            project.model.stale_reason = "Source changed during automatic analysis; another refresh is required."
        project.revision += 1
        project.playback, project.trace_id = None, None
        discover_targets(project, project.store.load_ui().get("executable"))
        snapshot = {**project.snapshot(), "diagnostics": diagnostics, "toolchain": toolchain}
        try:
            project.store.save_model(project.model)
        except OSError as exc:
            project.model.stale = True
            project.model.stale_reason = str(exc)
            raise ServiceError("analysis_failed", str(exc), {**snapshot, **project.snapshot()}) from exc
        if failed:
            raise ServiceError("analysis_failed", project.model.stale_reason, snapshot)
        return snapshot

    def save_specification(self, project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
        from icoda_core import persistence, session, steps

        _params(params, ("document",), ("trusted", "postSave", "unsavedDocuments"))
        post_save = _boolean(params, "postSave") if "postSave" in params else False
        if not post_save:
            return save_specification(project, {key: params[key] for key in ("document", "trusted") if key in params})
        require_trust(params)
        if review_unsaved(project, params):
            raise ServiceError("unsaved_documents", "Save or close other project documents before saving the specification.")
        if workflow_pending(project):
            raise ServiceError("proposal_pending", "Review the pending proposal before saving the specification.")
        validation = specification_findings(params["document"])
        if not validation["valid"]:
            raise ServiceError("invalid_specification", "Specification validation failed; no files were changed.", validation)
        existing_edit = project.store.load_state().phase != persistence.ProjectPhase.SPECIFICATION
        written = session.save_project_specification(project.store.root, params["document"], existing_edit=existing_edit)
        error: dict[str, Any] | None = None
        revision = project.revision
        try:
            if written is not None:
                session.log_event(f"skeleton written: {written}", project.store.root)
                built = steps.build_project(project.store.root)
                check_cancelled(project.context())
                if not built.ok:
                    raise ServiceError("build_failed", built.output)
            self.analyse_project(project, {})
        except (ServiceError, steps.StepError, OSError) as exc:
            error = exc.error if isinstance(exc, ServiceError) else {
                "code": "build_failed", "message": str(exc), "details": {}}
            project.model.stale = True
            project.model.stale_reason = f"Specification saved; refresh failed: {error['message']}"
            project.store.save_model(project.model)
        if project.revision == revision:
            project.revision += 1
            project.playback, project.trace_id = None, None
        result = {**get_specification(project, {}), **project.snapshot(), "saved": True,
                "state": project.store.load_state().to_dict(), "writtenFiles": written,
                "diagnostics": [], "postSaveError": error}
        if error and error["code"] == "cancelled":
            raise ServiceError("cancelled", "Specification saved; project refresh cancelled.", result)
        return result

    def list_targets(self, project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
        """Return the read-only catalog captured when this model revision was opened/analysed."""
        _params(params)
        return {**project.context(), "targets": [target_item(None), *(target_item(e) for e in project.choices)],
                "diagnostics": project.target_diagnostics}

    def select_target(self, project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
        """Persist only the desktop UI key, then publish a dependency projection."""
        _params(params, ("targetId",))
        identifier = _string(params, "targetId") if params["targetId"] is not None else None
        selected = next((entry for entry in project.choices if target_id(entry) == identifier), None)
        if identifier is not None and selected is None:
            raise ServiceError("unknown_target", "Choose a target from targets.list.", {"targetId": identifier})
        if identifier != target_id(project.selected):
            self.stop_workflow()
        ui = project.store.load_ui()
        ui["executable"] = selected.key if selected is not None else []
        try:
            project.store.save_ui(ui)
        except OSError as exc:
            raise ServiceError("selection_failed", str(exc), project.context()) from exc
        if identifier != target_id(project.selected):
            project.revision += 1
            project.playback, project.trace_id = None, None
        project.selected = selected
        return {**project.context(), "model": json.loads(project.scoped_model().to_json())}

    def get_view(self, project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
        """Serialize the same layered static layout used by the desktop Call View."""
        from icoda_core import views

        if params.get("view") == "file":
            return file_view(project, params)
        if params.get("view") == "class":
            return class_view(project, params)
        if params.get("view") == "mindmap":
            _params(params, ("view",))
            return mindmap_view(project)
        _params(params, ("view",), ("root", "depth", "callers", "traceId", "sourceRootId"))
        if _string(params, "view") != "call":
            raise ServiceError("unknown_view", "Available views: call, file, class, mindmap.")
        source_root = _string(params, "sourceRootId") if "sourceRootId" in params else project.context()["sourceRootId"]
        candidate = None
        if source_root != project.context()["sourceRootId"]:
            if "traceId" in params:
                raise ServiceError("invalid_params", "Recorded playback belongs to the project, not a candidate.")
            project, candidate = self.candidate_project(project, source_root)
        if not project.model_available:
            raise ServiceError("model_unavailable", "Analyse the project before requesting a view.")
        model = project.scoped_model()
        root, roots = call_roots(project, model, params)
        depth = _integer(params, "depth", 0) if "depth" in params else 3
        callers = params.get("callers", False)
        if type(callers) is not bool:
            raise ServiceError("invalid_params", "callers must be a boolean.")
        paths, free = trace_view_paths(project, roots, params)
        if "traceId" in params:
            model = project.model
        added = {entity.usr for entity in candidate.delta.added} if candidate and candidate.delta else set()
        changed = {entity.usr for entity in candidate.delta.changed} if candidate and candidate.delta else set()
        if candidate and params.get("root") is None:
            from icoda_core.model import CALLABLE_KINDS

            paths = tuple(next((path for root in roots if (path := views.call_path(model, root, usr))), (usr,))
                          for usr in sorted(added | changed)
                          if usr in model.entities and model.entities[usr].kind in CALLABLE_KINDS)
        layout = views.layout_call_view(model, roots, depth, callers=callers,
                                        required_paths=paths, free_functions=free)
        return {**project.context(), "view": "call", "root": root, "roots": list(roots), "depth": depth,
                "callers": callers,
                "libraryMode": bool(project.selected and project.selected.is_library),
                "stale": model.stale, "staleReason": model.stale_reason,
                "sourceRootId": source_root,
                "nodes": [{**call_node(project, model, node), "sourceRootId": source_root,
                           **({"added": node.usr in added, "changed": node.usr in changed} if candidate else {})}
                          for node in layout.nodes.values()],
                "edges": [{**asdict(edge), "kind": "calls"} for edge in layout.edges],
                "width": layout.width, "height": layout.height}

    def graph_interactions(self, project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
        """Read-only desktop filter decisions; never change layout, root, camera or playback."""
        from icoda_core import clusters, coverage_index, graph_filter, node_status, steplog

        _params(params, ("sourceRootId", "text", "depth", "focus"), ("traceId",))
        text = params["text"]
        if not isinstance(text, str) or len(text) > 256 or "\0" in text:
            raise ServiceError("invalid_params", "Filter text must contain at most 256 characters without NULs.")
        depth = _integer(params, "depth", 0)
        if depth > 12:
            raise ServiceError("invalid_params", "Neighborhood depth must be between 0 and 12.")
        focus = _string(params, "focus") if params["focus"] is not None else None
        source_root = _string(params, "sourceRootId")
        if source_root != project.context()["sourceRootId"]:
            if "traceId" in params:
                raise ServiceError("invalid_params", "Recorded playback belongs to the project.")
            project, _ = self.candidate_project(project, source_root)
        if not project.model_available:
            raise ServiceError("model_unavailable", "Analyse the project before filtering its graph.")
        model = project.scoped_model()
        if "traceId" in params:
            if _string(params, "traceId") != project.trace_id:
                raise ServiceError("invalid_params", "Choose the current recording.")
            model = project.model
        grouping = clusters.cluster_files(model, project.store.load_layout())
        graph = graph_filter.project_graph(model,
            {file: cluster.id for cluster in grouping.clusters for file in cluster.files},
            {cluster.id: cluster.name for cluster in grouping.clusters})
        if focus is not None and focus not in graph.nodes:
            raise ServiceError("invalid_params", "Choose a source node in the current graph.")
        records = steplog.StepLog(project.store.steps_path).records()
        coverage = coverage_index.scoped_index(project.model, records, model)
        appearances = node_status.derive(model, project.store.load_state(), records, coverage)
        decisions = graph_filter.derive(model, graph, appearances, graph_filter.parse(text),
                                        focus_node=focus, neighborhood_depth=depth)
        return {**project.context(), "sourceRootId": source_root,
                "decisions": {key: {"hidden": item.hidden, "dimmed": item.dimmed}
                              for key, item in decisions.items()}}

    def candidate_project(self, project: ProjectSession, source_root: str) -> tuple[ProjectSession, Proposal]:
        from icoda_core import git, persistence, steps

        job = self.review_job(project)
        candidate = job.candidate if job else None
        graph = candidate_graph(project, job)
        if not job or not isinstance(candidate, steps.Proposal) or not graph:
            raise ServiceError("stale_evidence", "No analysed candidate is available. Refresh the proposal review.")
        if (source_root != graph["sourceRootId"] or job.checked_fingerprint != candidate_fingerprint(candidate)
                or job.base_commit != git.head_commit(project.store.root)
                or job.thread and job.thread.is_alive()):
            raise ServiceError("stale_evidence", "Candidate source changed. Rebuild and reopen the proposal Call View.")
        assert candidate.model is not None
        return replace(project, store=persistence.ProjectStore(candidate.worktree), model=candidate.model,
                       model_available=True, playback=None, trace_id=None), candidate

    def resolve_source(self, project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
        from icoda_core import source_edit

        _params(params, ("sourceRootId",), ("file", "usr", "line"))
        source_root = _string(params, "sourceRootId")
        if source_root != project.context()["sourceRootId"]:
            if not source_root.startswith(project.session_id + ":proposal:"):
                raise ServiceError("invalid_params", "Unknown sourceRootId for this session.")
            project, _candidate = self.candidate_project(project, source_root)
        if ("file" in params) == ("usr" in params):
            raise ServiceError("invalid_params", "Supply exactly one of file or usr.")
        file, line = requested_source(project, params)
        details = {**project.context(), "sourceRootId": source_root, "file": file, "line": line}
        try:
            candidates = source_edit.find_source(project.store.root, file)
        except (OSError, ValueError) as exc:
            raise ServiceError("source_missing", str(exc), details) from exc
        if not candidates:
            raise ServiceError("source_missing", "Source file was not found inside the project.", details)
        if len(candidates) > 1:
            raise ServiceError("source_ambiguous", "Choose among equally ranked source files.",
                               {**details, "candidates": list(candidates)})
        path = source_edit.source_path(project.store.root, candidates[0])
        return {**details, "file": candidates[0], "path": str(path)}

    def load_trace(self, project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
        from icoda_core import call_trace

        _params(params, ("path",))
        path = project.store.root / _string(params, "path")
        try:
            trace = call_trace.load_trace(path, project.model)
        except (OSError, ValueError) as exc:
            raise ServiceError("invalid_trace", str(exc), {"path": str(path)}) from exc
        check_cancelled(project.context())
        project.playback = call_trace.CallPlayback(trace)
        project.trace_id = uuid4().hex
        calls = [event for event in trace.events if event.kind == call_trace.EventKind.ENTRY]
        return {**playback_state(project), "path": str(path), "events": len(trace.events),
                "resolvedCalls": sum(event.entity is not None for event in calls), "recordedCalls": len(calls)}

    def navigate_trace(self, project: ProjectSession, method: str, params: dict[str, Any]) -> dict[str, Any]:
        _params(params, ("traceId",) if method == "trace.reset" else ("traceId", "action"),
                () if method == "trace.reset" else ("usr",))
        trace_id = _string(params, "traceId")
        playback = project.playback
        if playback is None:
            raise ServiceError("trace_not_loaded", "Load a trace first.")
        if trace_id != project.trace_id:
            raise ServiceError("invalid_trace", "This traceId is no longer loaded.")
        if method == "trace.reset":
            playback.reset()
        else:
            action = _string(params, "action")
            actions = {"into": playback.step_into, "over": playback.step_over,
                       "out": playback.step_out, "previous": playback.previous_call}
            if action == "seek":
                usr = _string(params, "usr")
                if playback.seek_first_call(usr) is None:
                    raise ServiceError("trace_call_missing", "No recorded call resolves to this USR.", {"usr": usr})
            elif action in actions and "usr" not in params:
                actions[action]()
            else:
                raise ServiceError("invalid_params", "action must be into, over, out, previous, or seek (with usr).")
        return playback_state(project)


def class_view(project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
    """Serialize the shared class projection and geometry, exposing only the visible level."""
    from icoda_core import clusters, views

    _params(params, ("view",), ("clusterId",))
    if not project.model_available:
        raise ServiceError("model_unavailable", "Analyse the project before requesting a view.")
    group = _string(params, "clusterId") if params.get("clusterId") is not None else None
    model = project.scoped_model()
    clustering = clusters.cluster_files(model, project.store.load_layout())
    try:
        layout, summary, groups = views.class_view_level(model, clustering, group)
    except ValueError as exc:
        raise ServiceError("unknown_cluster", str(exc), {"clusterId": group}) from exc
    overview = summary is not None and group is None
    nodes = [class_node(project, key, panel, summary.nodes[key] if overview and summary else None, groups)
             for key, panel in layout.nodes.items()]
    return {**project.context(), "view": "class", "clusterId": group, "overview": overview,
            "clusterPath": [{"id": group, "label": summary.nodes[group].label}] if group and summary else [],
            "nodes": nodes, "edges": [asdict(edge) for edge in layout.edges],
            "bounds": {"x": 0, "y": 0}, "width": layout.width, "height": layout.height,
            "headerHeight": views.CLASS_HEADER_HEIGHT, "memberHeight": views.CLASS_MEMBER_HEIGHT,
            "stale": model.stale, "staleReason": model.stale_reason}


def evidence_source(project: ProjectSession, file: str, line: int) -> dict[str, Any]:
    """Serialize a bounded source location, retaining stale paths for source.resolve."""
    from icoda_core import source_edit

    try:
        relative = source_edit.relative_path(project.store.root, file) if file else None
    except ValueError:
        relative = None
    return {"file": relative, "line": max(1, line), "sourceRootId": project.context()["sourceRootId"]}


def evidence_state(project: ProjectSession) -> dict[str, Any]:
    return {**project.context(), "stale": project.model.stale, "staleReason": project.model.stale_reason}


def specification_findings(document: Any) -> dict[str, Any]:
    """Add stable wire identities to the core's ordered validation messages."""
    from icoda_core import specification

    problems = specification.validate(document)
    occurrences: dict[str, int] = {}
    findings = []
    for message in problems:
        count = occurrences.get(message, 0)
        occurrences[message] = count + 1
        identifier = hashlib.sha256(f"{message}\0{count}".encode()).hexdigest()
        findings.append({"id": "spec:" + identifier, "severity": "error", "message": message})
    return {"valid": not problems, "findings": findings}


def get_specification(project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
    from icoda_core import analysis, specification

    _params(params)
    exists = project.store.specification_path.is_file()
    try:
        document = specification.load(project.store.specification_path) if exists else \
            specification.default_specification(project.store.root.name, analysis.detect_language(project.store.root))
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise ServiceError("invalid_specification", "Cannot read the saved specification. Repair its JSON first.") from exc
    return {**project.context(), "document": document, "schemaVersion": specification.SCHEMA_VERSION,
            "codeProfile": document.get("code_profile", {}), "exists": exists,
            **specification_findings(document)}


def validate_specification(project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
    _params(params, ("document",))
    return {**project.context(), **specification_findings(params["document"])}


def require_trust(params: dict[str, Any]) -> None:
    if params.get("trusted") is not True:
        raise ServiceError("workspace_untrusted", "Trust this workspace before changing ICODA project state.")


def save_specification(project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
    from icoda_core import specification

    _params(params, ("document",), ("trusted",))
    require_trust(params)
    validation = specification_findings(params["document"])
    if not validation["valid"]:
        raise ServiceError("invalid_specification", "Specification validation failed; no files were changed.", validation)
    project.store.ensure()
    specification.save(project.store.specification_path, params["document"])
    project.revision += 1
    return {**project.context(), "document": params["document"], "schemaVersion": specification.SCHEMA_VERSION,
            "codeProfile": params["document"]["code_profile"], "exists": True, **validation,
            "state": project.store.load_state().to_dict()}


def get_phase(project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
    from icoda_core import phases

    _params(params)
    state = project.store.load_state()
    transitions = [{"phase": target.value, "reason": reason}
                   for target, reason in phases.transition_options(project.store).items()]
    if workflow_pending(project):
        for transition in transitions:
            transition["reason"] = "Review the pending proposal before changing phase."
    return {**project.context(), "phase": state.phase.value, "state": state.to_dict(),
            "allowedTransitions": [item["phase"] for item in transitions if not item["reason"]],
            "transitions": transitions}


def transition_phase(project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
    from icoda_core import persistence, phases

    _params(params, ("phase",), ("trusted",))
    require_trust(params)
    if workflow_pending(project):
        raise ServiceError("proposal_pending", "Review the pending proposal before changing phase.")
    try:
        target = persistence.ProjectPhase(_string(params, "phase"))
    except ValueError as exc:
        raise ServiceError("invalid_params", "Unknown project phase.") from exc
    try:
        record = phases.advance(project.store, target, project.model)
    except persistence.PhaseTransitionError as exc:
        raise ServiceError("disallowed_transition", str(exc)) from exc
    project.revision += 1
    return {**get_phase(project, {}), "record": asdict(record)}


def list_providers(project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
    """Read the registry and local markers only; never run CLI help, login, or a model."""
    from icoda_core import agent, persistence

    _params(params)
    saved = project.store.load_ui().get("provider") or {}
    config = persistence.UserConfig.load(persistence.config_path())
    selection = {"provider": saved.get("provider", config.provider), "model": saved.get("model", config.model)}
    providers = []
    for provider in agent.load_providers():
        if provider.id == selection["provider"] and not selection["model"] and provider.models:
            selection["model"] = provider.default_model
        binary = saved.get("binary") if saved.get("provider") == provider.id else None
        installed = agent.binary_available(provider, binary)
        available = installed and provider.enabled
        providers.append({"id": provider.id, "label": provider.label, "installed": installed,
            "enabled": provider.enabled, "verified": provider.verified, "available": available,
            "binary": binary or provider.command, "binaryPath": agent.provider_binary(provider, binary),
            "loginHint": provider.login_hint,
            "selectedModel": selection["model"] if selection["provider"] == provider.id else
                project.provider_models.get(provider.id, provider.default_model),
            "authenticationConfigured": agent.authentication_configured(provider),
            "models": [{"id": model.id, "label": model.label, "available": available} for model in provider.models]})
    available = any(item["available"] for item in providers)
    return {**project.context(), "providers": providers, "selection": selection,
            "emptyReason": None if available else "no_available_providers",
            "message": "" if available else
                "No enabled provider is installed. Source and graph browsing remain available."}


def select_provider(project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
    """Persist the desktop's project binary/model and ICODA user default; never invoke/login."""
    from icoda_core import agent, persistence

    _params(params, ("provider", "model", "binary"), ("trusted",))
    if params.get("trusted") is not True:
        raise ServiceError("workspace_untrusted", "Trust this workspace before changing its provider executable.")
    for key, maximum in (("provider", 256), ("model", 256), ("binary", 4096)):
        value = _string(params, key)
        if value != value.strip() or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ServiceError("invalid_params", f"{key} must be trimmed and at most {maximum} characters without controls.")
    binary = Path(params["binary"]).expanduser()
    if not binary.is_absolute() and ("/" in params["binary"] or "\\" in params["binary"]):
        raise ServiceError("invalid_params", "binary must be an absolute executable path or a command without arguments.")
    try:
        provider = agent.find_provider(agent.load_providers(), params["provider"])
    except KeyError as exc:
        raise ServiceError("provider_failed", "Unknown ICODA provider. Refresh Select Provider/Model.",
                           {"provider": params["provider"]}) from exc
    if not provider.enabled or not agent.binary_available(provider, str(binary)):
        raise ServiceError("provider_failed", f"{provider.label}: executable {str(binary)!r} is missing "
                           f"or the provider is disabled. Choose an installed executable. {provider.login_hint}",
                           {"provider": provider.id, "binary": str(binary), "loginHint": provider.login_hint})
    ui = project.store.load_ui()
    previous = list_providers(project, {})["selection"]
    project.provider_models[previous["provider"]] = previous["model"]
    config_path = persistence.config_path()
    config = persistence.UserConfig.load(config_path)
    config.provider, config.model = provider.id, params["model"]
    config.save(config_path)
    project.store.save_ui({**ui, "provider": {"provider": provider.id, "binary": str(binary), "model": params["model"]}})
    project.provider_models[provider.id] = params["model"]
    return list_providers(project, {})


def list_issues(project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
    """Expose advisory core findings against the selected model, without modifying it."""
    from icoda_core import rules, steplog

    _params(params)
    findings = []
    if project.model_available:
        records = steplog.StepLog(project.store.steps_path).records()
        for issue in rules.check(project.scoped_model(), records):
            identity = json.dumps(asdict(issue), sort_keys=True, ensure_ascii=False).encode("utf-8")
            findings.append({"id": "issue:" + hashlib.sha256(identity).hexdigest(),
                "ruleId": issue.rule_id, "severity": issue.severity, "message": issue.message,
                "usr": issue.usr or None, **evidence_source(project, issue.file, issue.line)})
    reason = "no_model" if not project.model_available else "no_findings" if not findings else None
    message = "Run ICODA: Analyse Project to see advisory findings." if reason == "no_model" else (
        "No advisory findings in the selected target." if reason else "")
    return {**evidence_state(project), "findings": findings, "emptyReason": reason, "message": message}


def get_coverage(project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
    """Keep explicit requirement tags separate from recorded structural test evidence."""
    from icoda_core import steplog

    _params(params)
    model = project.scoped_model()
    records = steplog.StepLog(project.store.steps_path).records() if project.model_available else []
    return {**evidence_state(project), "requirementTraceability": requirement_evidence(project, model),
            "structuralTestReachability": structural_evidence(project, model, records)}


def requirement_evidence(project: ProjectSession, model: DerivedModel) -> dict[str, Any]:
    from icoda_core import requirement_coverage, specification

    path = project.store.specification_path
    has_specification = path.is_file()
    spec = specification.load(path) if project.model_available and has_specification else {}
    requirements = requirement_coverage.project(spec, model)
    entries = [{"id": item.identifier, "kind": item.kind, "title": item.title, "uncovered": item.uncovered,
        "entities": [{"usr": entity.usr, "qualifiedName": entity.qualified_name,
                      **evidence_source(project, model.entities[entity.usr].file, model.entities[entity.usr].line)}
                     for entity in item.implementing_entities]} for item in requirements]
    reason = "no_model" if not project.model_available else "no_specification" if not has_specification else (
        "no_requirements" if not entries else None)
    messages = {"no_model": "Run ICODA: Analyse Project to see requirement traceability.",
                "no_specification": "No specification. Add project goals and requirements to link source tags.",
                "no_requirements": "The specification has no goals or requirements."}
    return {"label": "Requirement Traceability", "entries": entries, "emptyReason": reason,
            "message": messages.get(reason, "") if reason else ""}


def structural_evidence(project: ProjectSession, model: DerivedModel, records: list[StepRecord]) -> dict[str, Any]:
    from icoda_core import coverage_index

    index = coverage_index.scoped_index(project.model, records, model) if project.model_available else (
        coverage_index.CoverageIndex())
    entries = [{"usr": item.usr, "qualifiedName": item.qualified_name, "signature": item.signature,
                **evidence_source(project, item.file, item.line), "covered": item.covered,
                "tests": list(item.tests), "evidence": [asdict(evidence) for evidence in item.evidence]}
               for item in index.entries]
    reason = "no_model" if not project.model_available else "no_callables" if not entries else (
        "no_recorded_tests" if not index.covered else None)
    messages = {"no_model": "Run ICODA: Analyse Project to build the structural reachability index.",
                "no_callables": "No callable entities in the selected target; no reachability index is available.",
                "no_recorded_tests": "No reaching recorded test identifiers. Record successful focused tests in step history."}
    return {"label": "Structural Test Reachability", "entries": entries, "uncovered": list(index.uncovered),
            "emptyReason": reason, "message": messages.get(reason, "") if reason else ""}


def mindmap_step(project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
    """Resolve a node's current introduction through the shared hierarchy and desktop history rule."""
    from icoda_core import clusters, mind_map, steplog

    _params(params, ("nodeId",))
    node_id = _string(params, "nodeId")
    if not project.model_available:
        raise ServiceError("model_unavailable", "Analyse the project before requesting a view.")
    model = project.scoped_model()
    records = steplog.StepLog(project.store.steps_path).records()
    tree = mind_map.build_mind_map(model, records, clusters.cluster_files(model, project.store.load_layout()))
    node = tree.node_map().get(node_id)
    if node is None:
        raise ServiceError("invalid_params", "Choose a Mind Map node in the selected target.")
    record = steplog.introducing_record(records, node.introduced_iteration)
    if record is None:
        raise ServiceError("step_unavailable", "No introducing step is recorded for this Mind Map node.")
    return {**project.context(), "nodeId": node_id, "record": review_record(record)}


def set_mindmap_expanded(project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
    """Set one expansion choice after the dispatcher has checked the project identity."""
    _params(params, ("nodeId", "expanded"))
    node_id = _string(params, "nodeId")
    if type(params["expanded"]) is not bool:
        raise ServiceError("invalid_params", "expanded must be a boolean.")
    return mindmap_view(project, (node_id, params["expanded"]))


def mindmap_view(project: ProjectSession, expansion: tuple[str, bool] | None = None) -> dict[str, Any]:
    """Project the same scoped forest and layout as the desktop, with optional persisted expansion."""
    from icoda_core import clusters, mind_map, steplog, views

    if not project.model_available:
        raise ServiceError("model_unavailable", "Analyse the project before requesting a view.")
    model, state = project.scoped_model(), project.store.load_state()
    records = steplog.StepLog(project.store.steps_path).records()
    clustering = clusters.cluster_files(model, project.store.load_layout())
    tree = mind_map.build_mind_map(model, records, clustering)
    nodes = tree.node_map()
    choices = state.mind_map if expansion is None else mindmap_expansion(project, state, nodes, expansion)
    layout = views.layout_mind_map(tree, choices)
    parents = {edge.target: edge.source for edge in layout.edges}
    metadata = mindmap_metadata(project, model, records)
    expanded = set(choices.expanded)
    return {**project.context(), "view": "mindmap", "totalNodes": len(nodes),
            "nodes": [mindmap_node(project, item, parents.get(item.node.id), expanded, metadata)
                      for item in layout.nodes], "edges": [asdict(edge) for edge in layout.edges],
            "bounds": {"x": 0, "y": 0}, "width": layout.width, "height": layout.height,
            "stale": model.stale, "staleReason": model.stale_reason,
            "empty": not nodes, "emptyReason": "No project nodes in the selected target." if not nodes else "",
            "requirements": list(metadata["requirements"].values()), "hasSteps": bool(records),
            "messages": metadata["messages"]}


def mindmap_expansion(project: ProjectSession, state: ProjectState, nodes: dict[str, MindMapNode],
                      expansion: tuple[str, bool]) -> MindMapViewState:
    """Preserve all other project state and hidden expansion choices, just as MindMapCanvas does."""
    from icoda_core.mind_map import MindMapViewState

    node_id, expand = expansion
    node = nodes.get(node_id)
    if node is None or not node.children:
        raise ServiceError("invalid_params", "Choose an expandable Mind Map node in the selected target.",
                           {"nodeId": node_id})
    expanded = set(state.mind_map.expanded)
    expanded.add(node_id) if expand else expanded.discard(node_id)
    choices = MindMapViewState(tuple(expanded))
    project.store.save_state(replace(state, mind_map=choices))
    return choices


def mindmap_metadata(project: ProjectSession, model: DerivedModel,
                     records: list[StepRecord]) -> dict[str, Any]:
    """Attach specification traceability and step titles without deriving hierarchy or statuses."""
    from icoda_core import requirement_coverage, specification, steplog

    path = project.store.specification_path
    spec = specification.load(path) if path.is_file() else {}
    use_cases = {item["id"]: item.get("use_cases", []) for item in spec.get("requirements", [])}
    requirements = {item.identifier: {"id": item.identifier, "title": item.title,
        "uncovered": item.uncovered, "useCaseIds": use_cases.get(item.identifier, [])}
        for item in requirement_coverage.project(spec, model)}
    titles = {record.number: record.title for record in records
              if record.round != steplog.APPROACH_ROUND and record.decision in ("approved", "manual")}
    messages = []
    if not requirements:
        messages.append("No specification goals or requirements yet; source tags have no definitions.")
    if not records:
        messages.append("No steps yet; introducing step history is unavailable.")
    return {"requirements": requirements, "titles": titles, "messages": messages}


def mindmap_node(project: ProjectSession, item: MindMapNodeLayout, parent: str | None,
                 expanded: set[str], metadata: dict[str, Any]) -> dict[str, Any]:
    """Serialize shared node facts and geometry; source paths obey the existing root boundary."""
    from icoda_core import source_edit

    node = item.node
    entity = project.model.entities.get(node.usr)
    requirements = [metadata["requirements"].get(tag, {"id": tag, "title": "", "uncovered": None,
                    "useCaseIds": []}) for tag in node.satisfied_requirement_ids]
    try:
        file = source_edit.relative_path(project.store.root, node.file) if node.file else None
    except ValueError:
        file = None
    return {"id": node.id, "label": node.name, "qualifiedName": node.qualified_name, "kind": node.kind.value,
            "parent": parent, "children": [child.id for child in node.children], "depth": item.depth,
            "x": item.x, "y": item.y, "width": item.width, "height": item.height,
            "expandable": bool(node.children), "expanded": bool(node.children) and node.id in expanded,
            "status": node.status, "requirementIds": list(node.satisfied_requirement_ids),
            "requirements": requirements, "useCaseIds": sorted({uc for req in requirements for uc in req["useCaseIds"]}),
            "step": {"number": node.introduced_iteration, "title": metadata["titles"].get(node.introduced_iteration, "")}
            if node.introduced_iteration is not None else None,
            "usr": node.usr or None, "file": file, "line": max(1, entity.line) if entity else 1,
            "sourceRootId": project.context()["sourceRootId"]}


def class_node(project: ProjectSession, key: str, panel: ClassNodeLayout,
               summary: Node | None, groups: dict[str, set[str]]) -> dict[str, Any]:
    """Attach members and bounded source locations; never leak a group's representative class."""
    node = panel.node
    result = {"id": key, "x": panel.x, "y": panel.y, "width": panel.width, "height": panel.height}
    if summary is not None and summary.kind == "cluster":
        return {**result, "kind": "cluster", "label": summary.label, "count": len(groups[key]), "expandable": True,
                "filterMembers": sorted(groups[key])}
    return {**result, **class_source(project, node), "kind": node.kind.value, "label": node.qualified_name,
            "expandable": False, "members": [{**class_source(project, member), "name": member.name,
                "kind": member.kind.value, "declaration": member.declaration, "status": member.status,
                "visibility": None} for member in node.members]}


def class_source(project: ProjectSession, node: ClassNode | ClassMember) -> dict[str, Any]:
    """Use the existing project boundary rules; resolution/relocation happens on selection."""
    from icoda_core import source_edit

    try:
        file = source_edit.relative_path(project.store.root, node.file)
    except ValueError:
        file = None
    return {"usr": node.usr, "entityId": node.usr, "file": file, "line": node.line,
            "sourceRootId": project.context()["sourceRootId"]}


def cached_source_changes(root: Path, model: DerivedModel) -> list[str]:
    """Compare the shared analysis hashes without replacing the retained cache or source."""
    changed = []
    for name, info in model.files.items():
        if not info.content_hash:
            continue  # Legacy/constructed models have no freshness evidence to compare.
        path = (root / name).resolve()
        try:
            if not path.is_relative_to(root) or hashlib.sha1(path.read_bytes()).hexdigest() != info.content_hash:
                changed.append(name)
        except OSError:
            changed.append(name)
    return changed


def checked_diagram_state(view: str, state: Any) -> dict[str, Any]:
    if view == "class":
        return checked_file_view_state(state)
    if not isinstance(state, dict):
        raise ServiceError("invalid_params", "state must be a diagram state object.")
    _params(state, ("viewport", "root", "depth", "callers", "filter") if view == "call" else ("viewport",))
    if state["viewport"] is not None:
        checked_file_view_state({"clusterId": None, "cameras": [{"clusterId": None, "viewport": state["viewport"]}]})
    if view == "call":
        if state["root"] is not None and len(_string(state, "root")) > 4096:
            raise ServiceError("invalid_params", "root must be a bounded entity ID or null.")
        if _integer(state, "depth", 0) > 12:
            raise ServiceError("invalid_params", "depth must be between 0 and 12.")
        _boolean(state, "callers")
        if not isinstance(state["filter"], str) or len(state["filter"]) > 256 or "\0" in state["filter"]:
            raise ServiceError("invalid_params", "filter must be bounded text without NULs.")
    return dict(state)


def diagram_view_state(project: ProjectSession, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Extend the existing target-scoped UI storage; never persist playback or review evidence."""
    _params(params, ("view", "state") if method == "view.state.set" else ("view",))
    view = _string(params, "view")
    defaults = {"call": {"viewport": None, "root": None, "depth": 3, "callers": False, "filter": ""},
                "class": {"clusterId": None, "cameras": []}, "mindmap": {"viewport": None}}
    if view not in defaults:
        raise ServiceError("unknown_view", "Available persistent views: file, call, class, mindmap.")
    ui = project.store.load_ui()
    field = {"call": "vscodeCallViews", "class": "vscodeClassViews", "mindmap": "vscodeMindMapViews"}[view]
    saved = ui.get(field, {})
    if not isinstance(saved, dict):
        raise ServiceError("view_state_invalid", "Repair .icoda/ui.json; invalid saved diagram state has been preserved.")
    saved = dict(saved)
    key = target_id(project.selected) or "whole-project"
    if method == "view.state.set":
        state = checked_diagram_state(view, params["state"])
        saved[key] = state
        project.store.save_ui({**ui, field: saved})
    else:
        try:
            state = checked_diagram_state(view, saved.get(key, defaults[view]))
        except ServiceError as exc:
            raise ServiceError("view_state_invalid", "Saved diagram state is invalid; repair .icoda/ui.json. "
                               "The saved bytes have been preserved.") from exc
        # Obsolete roots/groups use the shared model/grouping, without rewriting saved choices on read.
        if view == "call" and state["root"] is not None:
            from icoda_core.model import CALLABLE_KINDS

            entity = project.scoped_model().entities.get(state["root"])
            if entity is None or entity.kind not in CALLABLE_KINDS:
                state.update(root=None, viewport=None)
        if view == "class" and project.model_available:
            from icoda_core import clusters, views

            model = project.scoped_model()
            _, _, groups = views.class_view_level(model, clusters.cluster_files(model, project.store.load_layout()))
            valid = {None, *groups}
            state = {"clusterId": state["clusterId"] if state["clusterId"] in valid else None,
                     "cameras": [camera for camera in state["cameras"] if camera["clusterId"] in valid]}
    return {**project.context(), "view": view, "state": state}


def checked_file_view_state(state: Any) -> dict[str, Any]:
    """Bound the persisted camera data just like the webview boundary; no filesystem paths."""
    if not isinstance(state, dict):
        raise ServiceError("invalid_params", "state must be a File View state object.")
    _params(state, ("clusterId", "cameras"))
    def cluster_id(data: dict[str, Any]) -> str | None:
        if data.get("clusterId") is None:
            return None
        value = _string(data, "clusterId")
        if len(value) > 4096 or not (value == "external:overview" or value.startswith("cluster:") and value[8:].strip()):
            raise ServiceError("invalid_params", "clusterId must be a bounded File View cluster ID or null.")
        return value
    selected = cluster_id(state)
    cameras = state["cameras"]
    if not isinstance(cameras, list) or len(cameras) > 512:
        raise ServiceError("invalid_params", "cameras must contain at most 512 entries.")
    seen = set()
    for camera in cameras:
        if not isinstance(camera, dict) or not isinstance(camera.get("viewport"), dict):
            raise ServiceError("invalid_params", "Each camera needs a clusterId and viewport.")
        _params(camera, ("clusterId", "viewport"))
        key = cluster_id(camera)
        if key in seen:
            raise ServiceError("invalid_params", "Camera cluster IDs must be unique.")
        seen.add(key)
        _params(camera["viewport"], ("x", "y", "scale"))
        for component, low, high in (("x", -1e7, 1e7), ("y", -1e7, 1e7), ("scale", 0.1, 4)):
            value = camera["viewport"][component]
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ServiceError("invalid_params", f"viewport.{component} must be finite and between {low} and {high}.")
    return {"clusterId": selected, "cameras": cameras}


def file_view_state(project: ProjectSession, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Merge target-scoped File View state into ProjectStore UI data, preserving desktop keys."""
    from icoda_core import clusters

    _params(params, ("view", "state") if method == "view.state.set" else ("view",))
    if params["view"] != "file":
        raise ServiceError("unknown_view", "Persistent view state is available for File View.")
    ui = project.store.load_ui()
    saved = ui.get("vscodeFileViews", {})
    saved = dict(saved) if isinstance(saved, dict) else {}
    key = target_id(project.selected) or "whole-project"
    if method == "view.state.set":
        state = checked_file_view_state(params["state"])
        saved[key] = state
        project.store.save_ui({**ui, "vscodeFileViews": saved})
    else:
        try:
            state = checked_file_view_state(saved.get(key, {"clusterId": None, "cameras": []}))
        except ServiceError:
            state = {"clusterId": None, "cameras": []}
        choices = project.store.load_layout()
        grouping = clusters.with_parents(clusters.cluster_files(project.scoped_model(), choices), choices)
        valid = {None, *("cluster:" + item.id for item in grouping.clusters if len(item.files) > 1)}
        if len(project.scoped_model().externals) > 1:
            valid.add("external:overview")
        state = {"clusterId": state["clusterId"] if state["clusterId"] in valid else None,
                 "cameras": [camera for camera in state["cameras"] if camera["clusterId"] in valid]}
    return {**project.context(), "view": "file", "state": state}


def edit_cluster(project: ProjectSession, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Apply the desktop's layout decisions without changing the source model or playback."""
    from icoda_core import clusters

    required = ("clusterId", "file") if method == "cluster.assignFile" else (
        ("clusterId", "name") if method == "cluster.rename" else ("clusterId",))
    _params(params, required, ("viewClusterId", "hierarchy"))
    hierarchy = _boolean(params, "hierarchy") if "hierarchy" in params else False
    identifier = None if method == "cluster.assignFile" and params["clusterId"] is None else _string(params, "clusterId")
    name = _string(params, "name") if method == "cluster.rename" else ""
    group = _string(params, "viewClusterId") if params.get("viewClusterId") is not None else None
    if not project.model_available:
        raise ServiceError("model_unavailable", "Analyse the project before editing clusters.")
    model, choices = project.scoped_model(), project.store.load_layout()
    clustering = clusters.cluster_files(model, choices)
    if hierarchy:
        clustering = clusters.with_parents(clustering, choices)
    cluster = next((item for item in clustering.clusters if "cluster:" + item.id == identifier), None)
    if cluster is None and identifier is not None:
        raise ServiceError("unknown_cluster", "Choose a cluster in the selected target.", {"clusterId": identifier})
    groups = {"cluster:" + item.id for item in clustering.clusters if len(item.files) > 1}
    if len(model.externals) > 1:
        groups.add("external:overview")
    if group is not None and group not in groups:
        raise ServiceError("unknown_cluster", "The displayed cluster is no longer available.", {"clusterId": group})
    if method == "cluster.assignFile":
        file = _string(params, "file")
        if file not in model.files:
            raise ServiceError("source_missing", "Choose an analysed file in the selected target.", {"file": file})
        decision = clusters.pin_file(choices, clustering, file, cluster.id) if cluster else clusters.unpin_file(choices, file)
    elif method == "cluster.pin":
        assert cluster is not None
        decision = clusters.pin_cluster(choices, clustering, cluster.id)
    elif method == "cluster.unpin":
        assert cluster is not None
        decision = clusters.unpin_cluster(choices, cluster.id, clustering)
    else:
        assert cluster is not None
        decision = clusters.rename_cluster(choices, cluster.id, name)
    updated = decision.to_layout()
    try:
        result = file_view(project, {"view": "file", "clusterId": group, "hierarchy": hierarchy}, updated)
    except ServiceError as exc:
        if exc.error["code"] != "unknown_cluster":
            raise
        # Unpinning a manually assigned group can dissolve it under the shared clustering rules.
        result = file_view(project, {"view": "file", "hierarchy": hierarchy}, updated)
    if decision.changed:
        project.store.save_layout(updated)
    return result


def file_view(project: ProjectSession, params: dict[str, Any], choices: Layout | None = None) -> dict[str, Any]:
    """Serialize only the desktop's requested File View level, retaining core geometry/counts."""
    from icoda_core import clusters, views

    _params(params, ("view",), ("clusterId", "width", "height", "hierarchy"))
    hierarchy = _boolean(params, "hierarchy") if "hierarchy" in params else False
    if not project.model_available:
        raise ServiceError("model_unavailable", "Analyse the project before requesting a view.")
    group = _string(params, "clusterId") if params.get("clusterId") is not None else None
    width = _integer(params, "width") if "width" in params else 1000
    height = _integer(params, "height") if "height" in params else 700
    if max(width, height) > 100_000:
        raise ServiceError("invalid_params", "View dimensions must be at most 100000.")
    model = project.scoped_model()
    choices = choices if choices is not None else project.store.load_layout()
    clustering = clusters.cluster_files(model, choices)
    if hierarchy:
        clustering = clusters.with_parents(clustering, choices)
    groups = {"cluster:" + item.id: item.name for item in clustering.clusters if len(item.files) > 1}
    if len(model.externals) > 1:
        groups["external:overview"] = "External libraries"
    if group is not None and group not in groups:
        raise ServiceError("unknown_cluster", "Choose a cluster in the selected target.", {"clusterId": group})
    layout, overview = views.file_view_level(model, clustering, group, width, height)
    left, top, right, bottom = views.file_view_bounds(layout)
    nodes = [file_node(project, node, clustering, choices) for node in layout.nodes.values()]
    path = [{"id": group, "label": groups[group],
             "pinned": clusters.cluster_is_pinned(choices, clustering, group.removeprefix("cluster:"))}] \
        if group is not None else []
    by_id = {"cluster:" + item.id: item for item in clustering.clusters}
    while path and path[0]["id"] in by_id:
        parent = by_id[path[0]["id"]].parent_id
        key = "cluster:" + parent if parent else None
        if parent is None or key not in groups or any(item["id"] == key for item in path):
            break
        path.insert(0, {"id": key, "label": groups[key],
                        "pinned": clusters.cluster_is_pinned(choices, clustering, parent)})
    return {**project.context(), "view": "file", "clusterId": group, "overview": overview,
            "clusterPath": path,
            **({"clusters": [{"id": "cluster:" + item.id, "label": item.name, "fileCount": len(item.files)}
                             for item in clustering.clusters]} if hierarchy else {}),
            "nodes": nodes, "edges": [{"source": a.source, "target": a.target, "count": a.weight,
                "counts": {kind.value: count for kind, count in a.counts.items()}, "label": a.badge}
                for a in layout.file_arrows], "bounds": {"x": left, "y": top},
            "width": right - left, "height": bottom - top, "stale": model.stale, "staleReason": model.stale_reason}


def file_node(project: ProjectSession, node: Node, clustering: Clustering, choices: Layout) -> dict[str, Any]:
    """Attach existing persistent cluster choices or a bounded native-source reference."""
    from icoda_core import clusters, source_edit, views

    result = {**asdict(node), "width": views.file_node_size(node)[0], "height": views.file_node_size(node)[1],
              "expandable": node.kind == "cluster" or node.id == "external:overview"}
    if node.kind == "cluster":
        cluster = next(item for item in clustering.clusters if item.id == node.cluster)
        result.update(name=cluster.name, fileCount=len(cluster.files), filterMembers=list(cluster.files),
                      pinned=clusters.cluster_is_pinned(choices, clustering, cluster.id),
                      renamed=cluster.id in choices.names or cluster.parent_id in choices.names,
                      parentId=cluster.parent_id)
    elif node.id == "external:overview":
        result["filterMembers"] = ["external:" + library for library in project.scoped_model().externals]
    elif node.kind == "file":
        try:
            file = source_edit.relative_path(project.store.root, node.id)
        except ValueError:
            file = None
        result.update(entityId=node.id, file=file, sourceRootId=project.context()["sourceRootId"], line=1)
    return result


def reveal_file(project: ProjectSession, params: dict[str, Any]) -> dict[str, Any]:
    """Locate a file in the selected model and return its shared expansion ancestry."""
    from icoda_core import clusters, source_edit, views

    _params(params, ("sourceRootId",), ("file", "usr", "hierarchy"))
    hierarchy = _boolean(params, "hierarchy") if "hierarchy" in params else False
    if _string(params, "sourceRootId") != project.context()["sourceRootId"]:
        raise ServiceError("invalid_source_root", "This source root is no longer open.")
    if ("file" in params) == ("usr" in params):
        raise ServiceError("invalid_params", "Supply exactly one of file or usr.")
    if not project.model_available:
        raise ServiceError("model_unavailable", "Analyse the project before revealing a file.")
    file, _line = requested_source(project, params)
    try:
        file = source_edit.relative_path(project.store.root, file)
        source_edit.source_path(project.store.root, file)
    except ValueError as exc:
        raise ServiceError("source_missing", str(exc)) from exc
    model = project.scoped_model()
    if file not in model.files:
        matches = relocated_model_files(project, model, file)
        if len(matches) != 1:
            raise ServiceError("source_missing", "No unique analysed file in the selected target. Analyse or select Whole Project.")
        file = matches[0]
    choices = project.store.load_layout()
    clustering = clusters.cluster_files(model, choices)
    if hierarchy:
        clustering = clusters.with_parents(clustering, choices)
    path = views.file_cluster_path(model, clustering, file)
    return {**project.context(), "file": file, "entityId": file, "clusterPath": list(path),
            "clusterId": path[-1] if path else None}


def relocated_model_files(project: ProjectSession, model: DerivedModel, file: str) -> list[str]:
    """Match a native editor's moved path through the existing unambiguous source resolver."""
    from icoda_core import source_edit

    matches = []
    for cached in model.files:
        if os.path.normcase(Path(cached).name) != os.path.normcase(Path(file).name):
            continue
        try:
            if source_edit.find_source(project.store.root, cached) == (file,):
                matches.append(cached)
        except (OSError, ValueError):
            continue
    return matches


def operation_params(method: str, params: dict[str, Any]) -> tuple[InstrumentationOptions | None, dict[str, str]]:
    """Validate additive tool overrides and bounded recording options before any writes."""
    from icoda_core import instrumentation, toolchain

    _params(params, optional=("trusted", *toolchain.TOOL_SETTINGS.values(),
                             *(("durationSeconds",) if method == "trace.record" else ())))
    require_trust(params)
    overrides = {key: _string(params, key) for key in toolchain.TOOL_SETTINGS.values() if key in params}
    options = None
    if method == "trace.record":
        duration = params.get("durationSeconds", instrumentation.DEFAULT_DURATION_SECONDS)
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            raise ServiceError("invalid_params", "durationSeconds must be positive and finite.")
        options = instrumentation.InstrumentationOptions(True, duration,
                    Path(".icoda/cache") / ("call-trace-" + uuid4().hex + ".tsv"))
    return options, overrides


def operation_tools(method: str, project: ProjectSession, overrides: dict[str, str],
                    cancel_event: threading.Event | None = None) -> dict[str, Any]:
    from icoda_core import cmake, steps

    # Python checks use the existing Code Profile runtime and need no C++ toolchain.
    if (method == "tests.run" or (method == "build.run" and project.selected is None)) and (
            steps._project_code_profile(project.store.root).get("language") == "Python"):
        return {"environment": {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")},
                "tools": []}

    directory = cmake.build_directory(project.store.root)
    cached = cmake.cache_values(directory) if directory is not None else {}
    effective = configured_tool_overrides(cached, overrides)
    report = inspect_toolchain(effective, cancel_event)
    if cancel_event is not None and cancel_event.is_set():
        raise ServiceError("cancelled", "Tool discovery cancelled.", project.context())
    paths = {tool["name"]: tool["path"] for tool in report["tools"]}
    required = set() if method == "tests.run" else {"cmake", "clang"}
    if method == "trace.record" and not paths["clang"] and "clangPath" not in overrides:
        try:
            environment = cmake._instrumented_build_environment(
                cached.get("CMAKE_CXX_COMPILER", ("", ""))[1], environ={**os.environ, **report["environment"]},
                cancel_event=cancel_event)
            report["environment"] = {key: value for key, value in environment.items() if os.environ.get(key) != value}
            required.remove("clang")  # Shared GCC fallback supports function instrumentation too.
        except RuntimeError:
            pass
    compiler = report["environment"].get("CXX", "")
    configured = cached.get("CMAKE_CXX_COMPILER", ("", ""))[1]
    if method != "tests.run" and (method == "trace.record" or directory is None
            or "Ninja" in cached.get("CMAKE_GENERATOR", ("", ""))[1] or (
            compiler and Path(compiler).resolve() != Path(configured).resolve())):
        required.add("ninja")
    for error in report["errors"]:
        if error["details"]["tool"] in required:
            raise ServiceError("missing_tool", error["message"], {**error["details"], "inspection": report})
    return report


def project_check(project: ProjectSession, method: str, environment: dict[str, str], tools: dict[str, str],
                  event: threading.Event, notify: Callable[[str, str], None]) -> dict[str, Any]:
    """Run the desktop's full build/test gates without creating a proposal or touching its evidence."""
    from icoda_core import executables, steps

    root = project.store.root
    output: list[str] = []
    runner = executables._operation_runner(root, event.is_set, environment, event, output,
        lambda text: notify("progress", text), lambda text: notify("log", text))

    def run(command: list[str], stage: str, timeout: float) -> str:
        if event.is_set():
            raise steps.StepCancelled()
        executable = str(root / command[0]) if any(sep in command[0] for sep in ("/", "\\")) else command[0]
        if shutil.which(executable, path=environment.get("PATH")) is None:
            raise ServiceError("missing_tool", f"{command[0]} is unavailable. Install it or update the project's "
                               "test command / Code Profile test runner.",
                               {**project.context(), "tool": command[0], "stage": stage})
        return runner(command, stage, timeout)

    kind = "tests" if method == "tests.run" else "build"
    checked: steps.TestResult | steps.BuildResult
    if kind == "tests":
        command = steps.gate_commands(root, project.store.load_state().test_command).test
        checked = steps.test_project(root, command, run=run)
    else:
        checked = steps.build_project(root, environment=environment, tools=tools, run=run)
    if event.is_set():
        raise steps.StepCancelled()
    if checked.ok is not True:
        raise ServiceError("test_failed" if kind == "tests" else "build_failed", checked.output, project.context())
    message = f"Whole Project: {kind} passed (saved files)."
    notify("progress", message)
    return {**project.context(), "message": message,
            "targets": [target_item(None), *(target_item(entry) for entry in project.choices)],
            "diagnostics": project.target_diagnostics, "target": target_item(None), "executable": None, "path": None,
            "check": {"kind": kind, "ok": True, "output": checked.output}}


def configured_tool_overrides(cached: dict[str, tuple[str, str]], overrides: dict[str, str]) -> dict[str, str]:
    """Honor usable recorded tools outside PATH, with explicit settings taking precedence."""
    effective = dict(overrides)
    for setting, key in (("cmakePath", "CMAKE_COMMAND"), ("ninjaPath", "CMAKE_MAKE_PROGRAM"),
                         ("clangPath", "CMAKE_CXX_COMPILER")):
        value = cached.get(key, ("", ""))[1]
        if setting == "ninjaPath" and "Ninja" not in cached.get("CMAKE_GENERATOR", ("", ""))[1]:
            continue
        if setting == "clangPath" and "clang++" not in Path(value).name.lower():
            continue
        if setting not in effective and value and Path(value).is_file():
            effective[setting] = value
    return effective


def operation_result(project: ProjectSession, method: str, outcome: Outcome) -> dict[str, Any]:
    """Publish refresh metadata only; recorded Debug targets never replace ordinary selections."""
    if method == "targets.refresh":
        selected = outcome.selected if project.selected is not None else None
        ui = project.store.load_ui()
        ui["executable"] = selected.key if selected is not None else []
        project.store.save_ui(ui)
        project.choices, project.selected = outcome.entries, selected
        project.revision += 1
        project.playback, project.trace_id = None, None
        project.target_diagnostics = []
    elif outcome.selected is None:
        raise ServiceError("invalid_target", outcome.message, project.context())
    if method == "trace.record" and (outcome.trace_file is None or not outcome.trace_file.is_file()
                                     or not outcome.trace_file.stat().st_size):
        raise ServiceError("run_failed", "The executable did not produce a nonempty trace.", project.context())
    selected = outcome.selected
    return {**project.context(), "message": outcome.message,
            "targets": [target_item(None), *(target_item(entry) for entry in project.choices)],
            "diagnostics": project.target_diagnostics, "target": target_item(selected),
            "executable": str(selected.target.artifact) if selected and selected.target and selected.target.artifact else None,
            "path": str(outcome.trace_file) if outcome.trace_file is not None else None}


def inspect_toolchain(params: dict[str, Any], cancel_event: threading.Event | None = None) -> dict[str, Any]:
    """Report each capability independently; strict checks are opt-in for tool consumers."""
    from icoda_core import toolchain

    _params(params, optional=(*toolchain.TOOL_SETTINGS.values(), "requiredTools"))
    overrides = {key: _string(params, key) for key in toolchain.TOOL_SETTINGS.values() if key in params}
    required = params.get("requiredTools", [])
    if not isinstance(required, list) or any(not isinstance(name, str) or name not in toolchain.TOOL_SETTINGS
                                             for name in required):
        raise ServiceError("invalid_params", "requiredTools must be a list of supported tool names.")
    report = toolchain.inspect_tools(overrides, **({"cancel_event": cancel_event} if cancel_event else {}))
    report["runtime"] = {"python": sys.executable}
    errors: list[dict[str, Any]] = []
    for tool in report["tools"]:
        if tool["source"] == "missing":
            name = tool["name"]
            setting = "icoda.toolchain." + toolchain.TOOL_SETTINGS[name]
            errors.append({"code": "missing_tool", "message": f"{name} is unavailable. Configure {setting}.",
                           "details": {"tool": name, "setting": setting}})
    report["errors"] = errors
    for error in errors:
        if error["details"]["tool"] in required:
            raise ServiceError("missing_tool", error["message"], {**error["details"], "inspection": report})
    return report


def analyse_candidate(project: ProjectSession) -> tuple[
        DerivedModel | None, dict[str, Any] | None, list[dict[str, str]], bool]:
    """Gather analysis evidence before publishing or retaining the last whole model."""
    from icoda_core import analysis, session

    LOG.info("Analysing %s", project.store.root)
    candidate, toolchain = None, None
    diagnostics: list[dict[str, str]] = []
    try:
        result = session.analyse_in_child(project.store.root, timeout=ANALYSIS_TIMEOUT)
        toolchain = {"frontend": result.libclang, "libclangPath": result.libclang_path}
        diagnostics = [{"message": message} for message in result.messages]
        candidate = project.store.load_model()
        if candidate is not None:
            diagnostics.extend({"file": info.path, "message": message}
                               for info in candidate.files.values() for message in info.errors)
        failed = (result.libclang is None or candidate is None or candidate.stale
                  or any(info.errors for info in candidate.files.values())
                  or (result.libclang != "Python ast" and not analysis.load_compile_commands(project.store.root)))
    except Exception as exc:
        LOG.exception("Analysis failed")
        diagnostics.append({"message": str(exc)})
        failed = True
    return candidate, toolchain, diagnostics, failed


def requested_source(project: ProjectSession, params: dict[str, Any]) -> tuple[str, int]:
    """Read a source location without conflating lookup failures with provider errors."""
    line = _integer(params, "line") if "line" in params else 1
    if "usr" not in params:
        return _string(params, "file"), line
    usr = _string(params, "usr")
    entity = project.model.entities.get(usr)
    if entity is None:
        raise ServiceError("source_missing", "No source for this entity.", {"usr": usr})
    return entity.file, line if "line" in params else max(1, entity.line)


def call_roots(project: ProjectSession, model: DerivedModel,
               params: dict[str, Any]) -> tuple[str | None, tuple[str, ...]]:
    """Use an explicit callable, the selected main, or the shared library API roots."""
    from icoda_core import views
    from icoda_core.model import CALLABLE_KINDS

    selected = project.selected
    root: str | None
    if params.get("root") is not None:
        root = _string(params, "root")
        entity = model.entities.get(root)
        if entity is None or entity.kind not in CALLABLE_KINDS:
            raise ServiceError("unknown_root", "The root must be a callable in the selected target.", {"usr": root})
    elif selected is not None and selected.is_library:
        return None, views.library_roots(model)
    else:
        root = selected.usr if selected is not None and selected.usr in model.entities else views.default_root(model)
    return root, (root,) if root is not None else ()


def call_node(project: ProjectSession, model: DerivedModel, node: CallNode) -> dict[str, Any]:
    """Keep core geometry/status and attach a bounded, one-based editor location."""
    from icoda_core import source_edit

    entity = model.entities.get(node.usr)
    file = None
    if entity is not None:
        try:
            file = source_edit.relative_path(project.store.root, entity.file)
        except ValueError:
            pass
    return {**asdict(node), "sourceRootId": project.context()["sourceRootId"], "file": file,
            "line": max(1, entity.line) if entity is not None else None}


def trace_view_paths(project: ProjectSession, roots: tuple[str, ...],
                     params: dict[str, Any]) -> tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]:
    """Include recorded functions once at trace load, without rerooting for each step."""
    from icoda_core import views

    if "traceId" not in params:
        return (), ()
    if project.playback is None or _string(params, "traceId") != project.trace_id:
        raise ServiceError("invalid_trace", "This traceId is no longer loaded.")
    paths, free = [], []
    for entity in project.playback.entities:
        path = next((path for root in roots if (path := views.call_path(project.model, root, entity.usr))), ())
        if path:
            paths.append(path)
        else:
            free.append(entity.usr)
    return tuple(paths), tuple(free)


def playback_state(project: ProjectSession) -> dict[str, Any]:
    """Serialize the shared cursor and availability; no stepping decisions live here."""
    from icoda_core import source_edit

    playback = project.playback
    assert playback is not None
    entity, source = playback.current_entity, None
    event = playback.current_event
    if entity is not None:
        try:
            file = source_edit.relative_path(project.store.root, entity.file)
        except ValueError:
            file = None
        source = {"sourceRootId": project.context()["sourceRootId"], "file": file, "line": max(1, entity.line)}
    return {**project.context(), "traceId": project.trace_id,
            "position": playback.position, "total": playback.total,
            "currentEntityUsr": entity.usr if entity is not None else None, "source": source,
            "currentCall": {"usr": entity.usr, "source": source, "threadId": event.thread_id,
                            "depth": event.depth, "sequence": event.sequence}
            if entity is not None and event is not None else None,
            "repeatCount": playback.current_repeat_count, "callerCounts": dict(playback.current_caller_counts),
            "status": playback.status,
            "availability": {**{mode: playback.can_step(mode) for mode in ("into", "over", "out")},
                             "previous": playback.position > 0, "reset": playback.position > 0}}


def _usable_id(value: Any) -> bool:
    return type(value) is int or (isinstance(value, str) and bool(value))


def _failure(request_id: Any, error: dict[str, Any]) -> dict[str, Any]:
    if _usable_id(request_id):
        return {"id": request_id, "status": "error", "error": error}
    return {"method": "protocol.error", "params": {"error": error}}


def handle_line(service: Service, line: bytes) -> dict[str, Any]:
    """Handle one frame, recovering malformed requests without losing subsequent lines."""
    request_id = None
    try:
        if len(line) > MAX_MESSAGE_BYTES:
            raise ServiceError("message_too_large", "Request exceeds the 1 MiB frame limit.")
        try:
            request = json.loads(line.decode("utf-8"), parse_constant=_invalid_constant)
        except (ValueError, RecursionError) as exc:
            raise ServiceError("invalid_json", "Request must be valid UTF-8 JSON.") from exc
        if not isinstance(request, dict):
            raise ServiceError("invalid_request", "Request must be an object with id, method, and params.")
        request_id = request.get("id")
        if not _usable_id(request_id):
            raise ServiceError("invalid_request", "id must be a nonempty string or an integer.")
        context = {key: request[key] for key in ("sessionId", "modelRevision", "targetId") if key in request}
        check_cancelled(context)
        result = service.dispatch(request)
        check_cancelled(context)
        return {"id": request_id, "status": "ok", "result": result}
    except ServiceError as exc:
        return _failure(request_id, exc.error)
    except Exception as exc:
        LOG.exception("Unhandled service error")
        return _failure(request_id, {"code": "internal_error", "message": str(exc), "details": {}})


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Not a JSON constant: {value}")


def serve(input_stream: BinaryIO, output_stream: TextIO) -> None:
    """Serialize state changes on one worker, keeping the reader free for cancellation."""
    write_lock = threading.Lock()
    def write(message: dict[str, Any]) -> None:
        with write_lock:
            output_stream.write(json.dumps(message, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n")
            output_stream.flush()
    service = Service(write)
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="icoda-operation")
    def shutdown(_signum, _frame):
        service.cancel_all()
        raise SystemExit(0)
    previous = None
    if threading.current_thread() is threading.main_thread():
        previous = signal.signal(signal.SIGTERM, shutdown)
    try:
        with redirect_stdout(sys.stderr):
            while line := input_stream.readline(MAX_MESSAGE_BYTES + 1):
                if len(line) > MAX_MESSAGE_BYTES:
                    tail = line
                    while not tail.endswith(b"\n"):
                        tail = input_stream.readline(MAX_MESSAGE_BYTES + 1)
                        if not tail:
                            break
                route_frame(service, line, worker, write)
    finally:
        service.cancel_all()
        worker.shutdown(wait=True)
        service.close_project()
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


def route_frame(service: Service, line: bytes, worker: ThreadPoolExecutor,
                write: Callable[[dict[str, Any]], None]) -> None:
    """Reserve IDs before queuing, so cancellation also works before a child starts."""
    try:
        request = json.loads(line) if len(line) <= MAX_MESSAGE_BYTES else {}
    except (ValueError, RecursionError):
        request = {}
    request = request if isinstance(request, dict) else {}
    method, identifier = request.get("method"), request.get("id")
    service.supersede(request)
    event = None
    cancellable = isinstance(method, str) and method in CANCELLABLE
    if method == "spec.save":
        cancellable = isinstance(request.get("params"), dict) and request["params"].get("postSave") is True
    if cancellable and _usable_id(identifier):
        with service.operation_lock:
            if identifier in service.operations:
                write(_failure(identifier, {"code": "invalid_request", "message": "Request ID is already active.", "details": {}}))
                return
            event = service.operations[identifier] = threading.Event()
            if service.closing:
                event.set()
    def respond() -> None:
        from icoda_core import process

        try:
            if event is None:
                write(handle_line(service, line))
            else:
                with process.cancellation_scope(event):
                    write(handle_line(service, line))
        finally:
            if event is not None:
                with service.operation_lock:
                    service.operations.pop(identifier, None)
    if method == "operation.cancel":
        respond()
    else:
        worker.submit(respond)


def main() -> int:
    """Reserve a private protocol stream; route native writes and child output to stderr too."""
    sys.stdout.flush()
    with os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", newline="\n") as protocol:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        logging.basicConfig(level=logging.INFO, stream=sys.stderr)
        serve(sys.stdin.buffer, protocol)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
