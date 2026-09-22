"""Pure rule checks over a derived model and optional step history.

The checker is deliberately independent of clang, Tk, the filesystem, and builds.  It
projects the rules in ``EVOLUTION.md`` into stable, actionable issue records.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, overload

from icoda_core import coverage_index, test_selection
from icoda_core.model import CALLABLE_KINDS, DerivedModel, Edge, EdgeKind, Entity, Kind
from icoda_core.persistence import ProjectState
from icoda_core.steplog import StepLog, StepRecord

if TYPE_CHECKING:
    from icoda_core.prompt import StepRequest

FUNCTION_LINE_GUIDELINE = 30
FUNCTION_LINE_HARD_MAX = 50
DATA_MEMBER_GUIDELINE = 10
METHOD_GUIDELINE = 15
PARAMETER_GUIDELINE = 5
MAX_STEP_ISSUES = 10

PLATFORM_LIBRARIES = frozenset({
    "android", "appkit", "carbon", "cocoa", "darwin", "directx", "foundation",
    "ios", "linux", "posix", "uikit", "win32", "windows", "x11",
})
PLATFORM_SYMBOL_PREFIXES = (
    "CF", "CG", "CreateFile", "Dispatch", "GetLastError", "NS", "Reg", "SDL_Sys",
    "SetLastError", "WaitForSingleObject", "WSA",
)
PLATFORM_SYMBOLS = frozenset({
    "close", "dlopen", "fork", "ioctl", "kqueue", "mmap", "open", "poll", "pthread_create",
    "read", "select", "socket", "write",
})
WRAPPER_PARTS = frozenset({"adapter", "platform", "portable", "portability", "wrapper"})


@dataclass(frozen=True)
class Issue:
    """One developer-actionable rule violation at a source entity."""

    rule_id: str
    severity: str
    message: str
    usr: str
    file: str
    line: int


@dataclass(frozen=True)
class IssueSelection(Sequence[Issue]):
    """A bounded step issue sequence plus the number omitted from its prompt."""

    issues: tuple[Issue, ...] = ()
    omitted: int = 0

    def __len__(self) -> int:
        return len(self.issues)

    @overload
    def __getitem__(self, index: int) -> Issue: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[Issue, ...]: ...

    def __getitem__(self, index: int | slice) -> Issue | tuple[Issue, ...]:
        return self.issues[index]


@dataclass(frozen=True)
class GroupTestCoverage:
    """Per-entity recorded-test reachability required by one deliberate function group."""

    covered: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    refusal_reason: str = ""

    @property
    def complete(self) -> bool:
        return not self.missing and not self.refusal_reason


History = ProjectState | StepLog | Iterable[StepRecord]


def check(model: DerivedModel, state_or_log: History) -> tuple[Issue, ...]:
    """Return every documented code-rule violation in deterministic display order."""
    issues: list[Issue] = []
    for entity in model.entities.values():
        issues.extend(_entity_issues(entity))
    for entity in model.entities.values():
        if entity.kind in (Kind.CLASS, Kind.STRUCT):
            issues.extend(_class_issues(model, entity))
    issues.extend(_platform_issues(model))
    issues.extend(_test_issues(model, state_or_log))
    return tuple(sorted(issues, key=_issue_key))


def promotion_refusal(
    model: DerivedModel,
    state_or_log: History,
    changed_usrs: Iterable[str],
    *, documentation_usrs: Iterable[str] = (),
) -> str:
    """Return the first required-rule violation introduced or changed by a proposal.

    Purpose comments also cover the other entities in affected files; the hard function
    limit applies only to changed callables. Other issues remain advisory.
    """
    changed = set(changed_usrs)
    documented = changed | set(documentation_usrs)
    if not documented:
        return ""
    for issue in check(model, state_or_log):
        if issue.rule_id == "missing-doxygen" and issue.usr in documented:
            return issue.message
        if issue.usr in changed and issue.rule_id == "function-lines" and issue.severity == "error":
            return issue.message
    return ""


def for_step(model: DerivedModel, state_or_log: History, request: StepRequest) -> IssueSelection:
    """Select at most ``MAX_STEP_ISSUES`` relevant issues for one targeted step.

    Relevance is limited to the requested target/batch and the files named by those
    entities or by the request focus.  Untargeted requests and empty or unavailable
    histories deliberately receive no issues.
    """
    targets = request.batch or ((request.target,) if request.target else ())
    records = _records(state_or_log)
    if not targets or not records:
        return IssueSelection()
    files = {entity.file for usr in targets if (entity := model.entities.get(usr)) is not None}
    for item in request.focus:
        entity = model.entities.get(item)
        if entity is not None:
            files.add(entity.file)
        else:
            files.add(item)
    relevant = tuple(issue for issue in check(model, records)
                     if issue.usr in targets or issue.file in files)
    return IssueSelection(relevant[:MAX_STEP_ISSUES], max(0, len(relevant) - MAX_STEP_ISSUES))


def group_test_coverage(
    model: DerivedModel,
    state_or_log: History,
    request: StepRequest,
    selected_tests: Sequence[str] = (),
    files: Sequence[str] = (),
) -> GroupTestCoverage:
    """Require prospective recorded-test reachability for every deliberate group member.

    Candidate matching and call reachability stay owned by ``coverage_index`` and
    ``test_selection``. The synthetic record is not persisted; it models exactly the
    test identifiers the approval record would add after the already-passing test gate.
    """
    targets = tuple(sorted(set(request.batch))) if request.grouped else ()
    if len(targets) < 2:
        return GroupTestCoverage(covered=targets)
    records = _records(state_or_log) or []
    candidate = StepRecord(
        request.number, request.phase, "approved", title="pending grouped step",
        test_ok=True, selected_tests=list(selected_tests), files=list(files), batch=list(targets),
    )
    covered_index = set(coverage_index.build_index(model, [*records, candidate]).covered)
    covered = tuple(target for target in targets if target in covered_index)
    missing = tuple(target for target in targets if target not in covered_index)
    if not missing:
        return GroupTestCoverage(covered)
    names = tuple(sorted(
        model.entities[target].qualified_name if target in model.entities else target for target in missing))
    reason = ("group approval requires a recorded successful test identifier that structurally reaches every "
              "entity; missing: " + ", ".join(names))
    return GroupTestCoverage(covered, missing, reason)


def _entity_issues(entity: Entity) -> list[Issue]:
    issues: list[Issue] = []
    if entity.kind in CALLABLE_KINDS:
        issues.extend(_callable_issues(entity))
    if not entity.brief.strip():
        issues.append(_issue("missing-doxygen", "warning", entity,
                             f"{entity.qualified_name} has no purpose comment; add one sentence explaining "
                             "what it does and why it exists."))
    if not entity.satisfies:
        issues.append(_issue("missing-satisfies", "warning", entity,
                             f"{entity.qualified_name} has no @satisfies tag; link it to its requirement."))
    return issues


def _callable_issues(entity: Entity) -> list[Issue]:
    issues: list[Issue] = []
    lines = _line_count(entity)
    if lines > FUNCTION_LINE_HARD_MAX:
        issues.append(_issue("function-lines", "error", entity,
                             f"{entity.qualified_name} is {lines} lines; split it below the hard maximum of 50."))
    elif lines > FUNCTION_LINE_GUIDELINE:
        issues.append(_issue("function-lines", "warning", entity,
                             f"{entity.qualified_name} is {lines} lines; reduce it to at most 30."))
    parameters = _parameter_count(entity.signature, entity.name)
    if parameters > PARAMETER_GUIDELINE:
        issues.append(_issue("many-parameters", "warning", entity,
                             f"{entity.qualified_name} has {parameters} parameters; group or simplify them."))
    return issues


def _class_issues(model: DerivedModel, entity: Entity) -> list[Issue]:
    children = model.children(entity.usr)
    data_count = sum(child.kind == Kind.FIELD for child in children)
    method_count = sum(child.kind in CALLABLE_KINDS for child in children)
    issues: list[Issue] = []
    if data_count > DATA_MEMBER_GUIDELINE:
        issues.append(_issue("data-members", "warning", entity,
                             f"{entity.qualified_name} has {data_count} data members; keep it at or below 10."))
    if method_count > METHOD_GUIDELINE:
        issues.append(_issue("methods", "warning", entity,
                             f"{entity.qualified_name} has {method_count} methods; keep it at or below 15."))
    return issues


def _platform_issues(model: DerivedModel) -> list[Issue]:
    issues: list[Issue] = []
    for edge in model.edges_of(EdgeKind.CALLS):
        entity = model.entities.get(edge.source)
        if entity is not None and _is_platform_api(edge) and not _is_wrapper(entity):
            message = (f"{entity.qualified_name} calls platform API {edge.label or edge.target}; "
                       "move the call behind a portable wrapper.")
            issues.append(Issue("platform-api", "error", message, entity.usr,
                                edge.file or entity.file, edge.line or entity.line))
    return issues


def _test_issues(model: DerivedModel, history: History) -> list[Issue]:
    records = _records(history)
    if records is None:
        return []
    covered = set(coverage_index.build_index(model, records).covered)
    test_identifiers = set(test_selection.model_test_identifiers(model))
    return [_issue("missing-test", "warning", entity,
                   f"{entity.qualified_name} has no recorded successful test identifier that structurally "
                   "reaches it; add or run its focused test.")
            for entity in model.entities.values()
            if entity.kind in CALLABLE_KINDS and entity.status != "stub" and entity.usr not in covered
            and entity.file not in test_identifiers and entity.qualified_name not in test_identifiers]


def _records(history: History) -> list[StepRecord] | None:
    if isinstance(history, ProjectState):
        return None
    return history.records() if isinstance(history, StepLog) else list(history)


def _line_count(entity: Entity) -> int:
    return entity.end_line - entity.line + 1 if entity.end_line >= entity.line else 0


def _parameter_count(signature: str, name: str) -> int:
    marker = name + "("
    start = signature.find(marker)
    start = start + len(name) if start >= 0 else signature.find("(")
    if start < 0:
        return 0
    depth, angle_depth, count = 0, 0, 1
    content = ""
    for character in signature[start + 1:]:
        if character == ")" and depth == 0:
            break
        content += character
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth = max(0, depth - 1)
        elif character == "<":
            angle_depth += 1
        elif character == ">":
            angle_depth = max(0, angle_depth - 1)
        elif character == "," and depth == 0 and angle_depth == 0:
            count += 1
    return 0 if not content.strip() or content.strip() == "void" else count


def _is_platform_api(edge: Edge) -> bool:
    library = edge.target.removeprefix("external:").lower()
    symbol = edge.label.rsplit("::", 1)[-1]
    return library in PLATFORM_LIBRARIES or symbol in PLATFORM_SYMBOLS \
        or symbol.startswith(PLATFORM_SYMBOL_PREFIXES)


def _is_wrapper(entity: Entity) -> bool:
    words = entity.file.replace("\\", "/").lower().replace(".", "/").replace("_", "/").split("/")
    words.extend(entity.qualified_name.lower().replace("::", "/").replace("_", "/").split("/"))
    return bool(WRAPPER_PARTS.intersection(words))


def _issue(rule_id: str, severity: str, entity: Entity, message: str) -> Issue:
    return Issue(rule_id, severity, message, entity.usr, entity.file, entity.line)


def _issue_key(issue: Issue) -> tuple[int, str, int, str, str, str]:
    return (0 if issue.severity == "error" else 1, issue.file, issue.line,
            issue.rule_id, issue.usr, issue.message)
