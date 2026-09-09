"""The step protocol: propose in a worktree, build, parse, show the delta; approve, reject, adapt, undo.

One persistent worktree, ``.icoda/worktree`` (ignored by git, so its ``build/`` survives between steps), holds each
proposal. Approving promotes the worktree's changes onto the working tree, rebuilds, and creates one commit that
includes the step log entry in ``.icoda/steps.jsonl``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from icoda_core import agent, analysis, git, persistence, prompt, response, session, specification
from icoda_core.model import CALLABLE_KINDS, TYPE_KINDS, DerivedModel, Entity, Kind
from icoda_core.process import run_bounded
from icoda_core.steplog import StepLog, StepRecord, apply_statuses

WORKTREE_DIR = "worktree"
LOG_PATH = ".icoda/steps.jsonl"
IGNORE_PATH = ".icoda/.gitignore"
MAX_ATTEMPTS = 3
BUILD_TIMEOUT = 900.0
PROVIDER_TIMEOUT = 1800.0
OUTPUT_TAIL = 6000
ARCHITECTURE_ENTITY_KINDS = TYPE_KINDS | CALLABLE_KINDS | frozenset({Kind.VARIABLE})


class StepError(RuntimeError):
    """The protocol cannot continue; the message says why."""


class DirtyTree(StepError):
    """Uncommitted changes in the working tree; commit them first (``commit_manual_edits``)."""


# --------------------------------------------------------------------------- build, delta, proposal


@dataclass(frozen=True)
class BuildResult:
    ok: bool
    output: str


def build_project(root: Path, timeout: float = BUILD_TIMEOUT) -> BuildResult:
    """Run the project's build script (configure, build, test); without one, configure and build with CMake."""
    if sys.platform == "win32" and (root / "build.cmd").is_file():
        commands = [["cmd", "/c", "build.cmd", "debug"]]
    elif (root / "build.sh").is_file():
        commands = [["bash", "build.sh", "debug"]]
    else:
        commands = [["cmake", "--preset", "debug"], ["cmake", "--build", "--preset", "debug"]]
    output = ""
    for command in commands:
        result = run_bounded(command, cwd=root, timeout=timeout)
        output += result.stdout + result.stderr
        if not result.ok:
            return BuildResult(False, _tail(output))
    return BuildResult(True, _tail(output))


def _tail(text: str) -> str:
    return text if len(text) <= OUTPUT_TAIL else "…" + text[-OUTPUT_TAIL:]


@dataclass(frozen=True)
class Delta:
    """What a proposal changes in the derived model."""

    added: tuple[Entity, ...]
    removed: tuple[Entity, ...]
    changed: tuple[Entity, ...]
    files: tuple[str, ...]
    modules: tuple[str, ...] = ()

    def summary(self) -> str:
        head = (f"{len(self.added)} entities added, {len(self.changed)} changed, {len(self.removed)} removed; "
                f"files: {', '.join(self.files) or 'none'}")
        lines = [head]
        lines.extend(f"+ {e.kind.value} {e.qualified_name} {e.signature}".rstrip() for e in self.added)
        lines.extend(f"+ module {name}" for name in self.modules)
        lines.extend(f"~ {e.kind.value} {e.qualified_name} {e.signature}".rstrip() for e in self.changed)
        lines.extend(f"- {e.kind.value} {e.qualified_name}" for e in self.removed)
        return "\n".join(lines)

    def architecture_entity_count(self) -> int:
        """New concepts charged to an architecture step's configurable entity budget."""
        return len(self.modules) + sum(entity.kind in ARCHITECTURE_ENTITY_KINDS for entity in self.added)


def compute_delta(before: DerivedModel, after: DerivedModel, files: Sequence[str]) -> Delta:
    def shape(entity: Entity) -> tuple[str, str, str, str | None]:
        return (entity.kind.value, entity.signature, entity.file, entity.parent)

    added = tuple(e for usr, e in after.entities.items() if usr not in before.entities)
    removed = tuple(e for usr, e in before.entities.items() if usr not in after.entities)
    changed = tuple(e for usr, e in after.entities.items()
                    if usr in before.entities and shape(e) != shape(before.entities[usr]))
    before_modules = {file.module for file in before.files.values() if file.module}
    added_modules = tuple(sorted({file.module for file in after.files.values() if file.module} - before_modules))
    return Delta(added, removed, changed, tuple(files), added_modules)


def _delta_error(request: prompt.StepRequest, delta: Delta) -> str:
    if request.phase != prompt.ARCHITECTURE:
        return ""
    count = delta.architecture_entity_count()
    if count <= request.max_entities:
        return ""
    names = [f"module {name}" for name in delta.modules]
    names.extend(entity.qualified_name for entity in delta.added if entity.kind in ARCHITECTURE_ENTITY_KINDS)
    return (f"the parsed architecture delta adds {count} budgeted entities, exceeding the maximum of "
            f"{request.max_entities}: {', '.join(names)}. Split this into a smaller atomic step")


@dataclass
class Proposal:
    """The outcome of :meth:`StepRunner.propose`: usable when ``ok``, otherwise ``error`` says what failed."""

    number: int
    request: prompt.StepRequest
    worktree: Path
    attempts: int = 0
    response: response.StepResponse | None = None
    build: BuildResult = BuildResult(False, "")
    model: DerivedModel | None = None
    delta: Delta | None = None
    source_diff: str = ""
    prompt_text: str = ""
    reply: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.response is not None and self.build.ok and self.delta is not None and not self.error


# --------------------------------------------------------------------------- the runner


class StepRunner:
    """Drives one project through the step protocol; every method is safe to call from a worker thread."""

    def __init__(self, root: Path, config: persistence.UserConfig, provider_id: str = "", binary: str = "",
                 model: str = "", *, invoke: Callable[[str, Path], str] | None = None,
                 build: Callable[[Path], BuildResult] = build_project,
                 analyse: Callable[[Path], DerivedModel] | None = None, attempts: int = MAX_ATTEMPTS,
                 progress: Callable[[str], None] = lambda message: None) -> None:
        self.root = root.resolve()
        self.config = config
        self.provider_id, self.binary, self.model_id = provider_id, binary, model
        self.store = persistence.ProjectStore(self.root)
        self.log = StepLog(self.store.steps_path)
        self.invoke = invoke or self._invoke_provider
        self.build = build
        self.analyse = analyse or analyse_tree
        self.attempts = attempts
        self.progress = progress

    # -- preparation ----------------------------------------------------------------------

    def prepare(self) -> StepRecord | None:
        """Make the project a built, analysed git repository with a committed step 0; refuse manual edits."""
        self.store.ensure()
        _ensure_ignored(self.root / IGNORE_PATH, WORKTREE_DIR + "/")
        if not git.is_own_repository(self.root):  # a project inside another repository gets its own
            git.run_git(["init", "-q"], self.root)
        if self.store.load_model() is None or analysis.find_compile_commands(self.root) is None:
            self.progress("step 0: building and parsing the project")
            build = self.build(self.root)
            if not build.ok:
                raise StepError("the project does not build:\n" + build.output)
            self.store.save_model(self.analyse(self.root))
        if self.log.records():
            self._require_clean()
            return None
        model = self.store.load_model() or DerivedModel(str(self.root))
        record = StepRecord(0, prompt.ARCHITECTURE, "approved", title="skeleton",
                            files=[c.path for c in git.status_changes(self.root)],
                            entities_added=[e.usr for e in model.entities.values() if e.kind in CALLABLE_KINDS])
        self.log.append(record)
        record.commit = git.commit_all(self.root, "icoda step 0: skeleton", *self._author())
        return record

    def _require_clean(self) -> None:
        """Only the step log may differ from HEAD (rejections are committed with the next step)."""
        if not git.is_clean(self.root, ignore_prefixes=(LOG_PATH, IGNORE_PATH)):
            raise DirtyTree("uncommitted changes in the project: commit them first (Project → Commit manual edits)")

    def commit_manual_edits(self) -> StepRecord | None:
        """Commit the developer's own changes as a manual step so that the next proposal starts from a clean tree."""
        changes = [c for c in git.status_changes(self.root) if c.path not in (LOG_PATH, IGNORE_PATH)]
        if not changes:
            return None
        record = self.log.append(StepRecord(self.log.next_number(), "manual", "manual", title="manual edit",
                                            files=[c.path for c in changes]))
        record.commit = git.commit_all(self.root, f"icoda step {record.number}: manual edit", *self._author())
        return record

    def current_model(self) -> DerivedModel:
        model = self.store.load_model() or DerivedModel(str(self.root))
        apply_statuses(model, self.log)
        return model

    # -- proposing ------------------------------------------------------------------------

    def propose(self, request: prompt.StepRequest) -> Proposal:
        """Ask the provider, apply, build and parse in the worktree; up to ``attempts`` tries with feedback."""
        number = self.log.next_number()
        request = replace(request, number=number, rejections=request.rejections or self.log.rejections(number))
        proposal = Proposal(number, request, self._fresh_worktree())
        for attempt in range(1, self.attempts + 1):
            proposal.attempts = attempt
            self.progress(f"step {number}: asking the provider (attempt {attempt} of {self.attempts})")
            proposal.prompt_text = self._prompt(request)
            proposal.reply = self.invoke(proposal.prompt_text, self.root)
            parsed, error = response.parse_response(proposal.reply)
            if parsed is None:
                request = replace(request, validation_error=error)
                proposal.error = error
                continue
            proposal.response, proposal.error = parsed, ""
            self._apply_and_check(proposal)
            if proposal.ok:
                return proposal
            request = self._retry_request(request, proposal)
        proposal.error = proposal.error or f"no usable proposal after {self.attempts} attempts"
        return proposal

    def rebuild(self, proposal: Proposal) -> Proposal:
        """Build and parse the worktree again after the developer edited it by hand."""
        proposal.error = ""
        self._build_and_parse(proposal)
        return proposal

    def _apply_and_check(self, proposal: Proposal) -> None:
        assert proposal.response is not None
        self._reset_worktree(proposal.worktree)
        proposal.build, proposal.model, proposal.delta = BuildResult(False, ""), None, None
        proposal.source_diff = ""
        try:
            response.apply_changes(proposal.worktree, proposal.response.files)
        except (OSError, ValueError) as exc:
            proposal.error = f"could not apply the files: {exc}"
            return
        self._build_and_parse(proposal)

    def _build_and_parse(self, proposal: Proposal) -> None:
        proposal.source_diff = git.working_tree_diff(proposal.worktree)
        self.progress(f"step {proposal.number}: building the proposal")
        proposal.build = self.build(proposal.worktree)
        if not proposal.build.ok:
            proposal.error = "the proposal does not build"
            return
        self.progress(f"step {proposal.number}: parsing the proposal")
        proposal.model = self.analyse(proposal.worktree)
        files = [c.path for c in git.status_changes(proposal.worktree)]
        proposal.delta = compute_delta(self.current_model(), proposal.model, files)
        proposal.error = _delta_error(proposal.request, proposal.delta)

    @staticmethod
    def _retry_request(request: prompt.StepRequest, proposal: Proposal) -> prompt.StepRequest:
        if proposal.build.ok and proposal.error:
            return replace(request, validation_error=proposal.error, build_errors="")
        return replace(request, validation_error="", build_errors=proposal.build.output)

    def _prompt(self, request: prompt.StepRequest) -> str:
        spec = specification.load(self.store.specification_path) if self.store.specification_path.is_file() \
            else specification.default_specification(self.root.name)
        tracked = git.run_git(["ls-files"], self.root).stdout.split()
        build_files = {name: (self.root / name).read_text(encoding="utf-8", errors="replace")
                       for name in tracked if Path(name).name in ("CMakeLists.txt", "vcpkg.json")}
        return prompt.build_prompt(spec, self.current_model(), request, tracked, build_files)

    # -- deciding -------------------------------------------------------------------------

    def approve(self, proposal: Proposal) -> StepRecord:
        """Promote the worktree, rebuild the project, log the step and commit it."""
        if not proposal.ok or proposal.response is None or proposal.delta is None:
            raise StepError("only a proposal that builds can be approved")
        self.progress(f"step {proposal.number}: promoting and rebuilding")
        files = git.promote_worktree(self.root, proposal.worktree)
        build = self.build(self.root)
        if not build.ok:
            raise StepError("the promoted project does not build:\n" + build.output)
        record = self._record(proposal, "approved")
        record.files, record.tests_passed = files, True
        record.entities_added = [e.usr for e in proposal.delta.added]
        record.entities_changed = [e.usr for e in proposal.delta.changed]
        self.log.append(record)
        record.commit = git.commit_all(self.root, f"icoda({proposal.request.phase}) step {record.number}: "
                                                  f"{record.title}", *self._author())
        if proposal.model is not None:
            proposal.model.root = str(self.root)
            self.store.save_model(proposal.model)
        return record

    def reject(self, proposal: Proposal, reason: str) -> StepRecord:
        record = self._record(proposal, "rejected")
        record.reason = reason.strip()
        return self.log.append(record)

    def undo(self) -> StepRecord:
        """Revert the last approved step with a commit of its own; uncommitted log records are kept."""
        last = self.log.approved()[-1:]
        if not last or last[0].number == 0:
            raise StepError("nothing to undo")
        self._require_clean()
        head = git.run_git(["log", "-1", "--format=%s"], self.root).stdout.strip()
        if f" step {last[0].number}:" not in head:
            raise StepError(f"HEAD is not the commit of step {last[0].number} ({head!r}); undo in git by hand")
        pending = self._pending_log_text()
        git.run_git(["checkout", "-q", "--", LOG_PATH], self.root)
        git.run_git(["revert", "--no-commit", "HEAD"], self.root)
        with self.log.path.open("a", encoding="utf-8") as handle:
            handle.write(pending)
        record = self.log.append(StepRecord(last[0].number, last[0].phase, "undone", title=last[0].title,
                                            undoes=last[0].number))
        record.commit = git.commit_all(self.root, f"icoda undo step {record.number}: {record.title}", *self._author())
        return record

    def _pending_log_text(self) -> str:
        """Log lines written since the last commit (rejections and failures)."""
        committed = git.run_git(["show", f"HEAD:{LOG_PATH}"], self.root, check=False).stdout
        current = self.log.path.read_text(encoding="utf-8") if self.log.path.is_file() else ""
        return current[len(committed):] if current.startswith(committed) else ""

    def _record(self, proposal: Proposal, decision: str) -> StepRecord:
        title = proposal.response.title if proposal.response else ""
        rationale = proposal.response.rationale if proposal.response else ""
        return StepRecord(proposal.number, proposal.request.phase, decision, title=title,
                          request=proposal.request.request, rationale=rationale, provider=self.provider_id,
                          binary=self.binary, model=self.model_id, attempts=proposal.attempts)

    # -- worktree and provider ------------------------------------------------------------

    def _fresh_worktree(self) -> Path:
        path = self.store.dir / WORKTREE_DIR
        if not (path / ".git").exists():
            if path.exists():
                git.remove_worktree(self.root, path)
            git.run_git(["worktree", "add", "--detach", str(path), "HEAD"], self.root)
        self._reset_worktree(path)
        return path

    def _reset_worktree(self, path: Path) -> None:
        """Back to the project's HEAD with no changes; ignored files such as ``build/`` are kept."""
        git.run_git(["reset", "-q", "--hard", git.head_commit(self.root)], path)
        git.run_git(["clean", "-qfd"], path)

    def _invoke_provider(self, prompt_text: str, cwd: Path) -> str:
        providers = agent.load_providers()
        try:
            provider = agent.find_provider(providers, self.provider_id)
        except KeyError as exc:
            raise StepError(f"unknown provider {self.provider_id!r}: choose a listed binary") from exc
        if not agent.binary_available(provider, self.binary or None):
            raise StepError(f"{self.binary or provider.command} is not on the PATH; {provider.login_hint}")
        result = agent.run_provider(provider, self.model_id or provider.default_model, prompt_text, cwd,
                                    binary=self.binary or None, timeout=PROVIDER_TIMEOUT)
        if not result.ok:
            raise StepError(f"{provider.label} failed ({result.returncode}): {_tail(result.stderr or result.stdout)}"
                            f"\nIf it asks for a login: {provider.login_hint}")
        return result.stdout

    def _author(self) -> tuple[str, str]:
        name = git.run_git(["config", "user.name"], self.root, check=False).stdout.strip() or "ICODA"
        email = git.run_git(["config", "user.email"], self.root, check=False).stdout.strip() or "icoda@localhost"
        return name, email


def analyse_tree(root: Path) -> DerivedModel:
    """Parse a checkout (the worktree) in a child process and return its derived model."""
    result = session.analyse_in_child(root)
    model = persistence.ProjectStore(root).load_model()
    if model is None:
        raise StepError("analysis produced no model: " + "; ".join(result.messages))
    return model


def _ensure_ignored(gitignore: Path, entry: str) -> None:
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.is_file() else []
    if entry not in lines:
        gitignore.write_text("\n".join([*lines, entry]) + "\n", encoding="utf-8")
