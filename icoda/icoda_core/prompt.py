"""Prompt assembly for one step.

A prompt carries the Code Profile and the compact specification, the part of the derived model the step touches,
the step request with the rules of its phase, the feedback gathered so far (rejections, constraints, compiler
output, a validation error), and the response format. Everything is plain text; the answer must be one JSON object.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from icoda_core import persistence, response, rules, specification
from icoda_core.model import CALLABLE_KINDS, DerivedModel, EdgeKind, Entity, Kind

ARCHITECTURE = persistence.ProjectPhase.ARCHITECTURE.value
IMPLEMENTATION = persistence.ProjectPhase.IMPLEMENTATION.value
MAX_SUBSET_FILES = 40


@dataclass(frozen=True)
class StepRequest:
    """What the developer wants from this step and what has been learnt about it so far."""

    phase: str
    number: int
    request: str = ""
    max_entities: int = 5
    rejections: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    build_errors: str = ""
    validation_error: str = ""
    focus: tuple[str, ...] = field(default_factory=tuple)  # files or USRs the step is about
    target: str = ""  # implementation queue head USR; empty outside the implementation phase
    batch: tuple[str, ...] = field(default_factory=tuple)  # consecutive queue USRs; target remains the head
    grouped: bool = False  # deliberate few-line group, subject to per-entity test evidence


def build_prompt(spec: specification.Specification, model: DerivedModel, request: StepRequest,
                 skeleton_files: Iterable[str] = (), build_files: Mapping[str, str] | None = None,
                 *, state: persistence.ProjectState, issues: Sequence[rules.Issue] = ()) -> str:
    """Build the prompt using the persisted ``state`` rather than a caller-selected phase."""
    if state.phase == persistence.ProjectPhase.SPECIFICATION:
        raise ValueError("step prompts are unavailable during the specification phase")
    request = replace(request, phase=state.phase.value)
    parts = [
        _role(request),
        "# Specification and code profile\n\n" + specification.compact(spec),
        "# Current code\n\n" + describe_model(model, request.focus, skeleton_files),
    ]
    if build_files:
        parts.append("# Build files\n\n" + "\n".join(f"## {name}\n```\n{content.rstrip()}\n```"
                                                     for name, content in sorted(build_files.items())))
    if request.phase == IMPLEMENTATION and state.approved_approach:
        parts.append("# Approved approach\n\n" + state.approved_approach.strip())
    if issues:
        parts.append("# Current rule-check issues\n\n" + _issues_text(issues))
    parts.append("# This step\n\n" + _step_text(request, model, spec.get("code_profile", {})))
    feedback = _feedback(request)
    if feedback:
        parts.append("# Feedback on earlier attempts\n\n" + feedback)
    parts.append("# Response format\n\n" + _format_text())
    return "\n\n".join(part.rstrip() for part in parts) + "\n"


def build_approach_prompt(spec: specification.Specification, model: DerivedModel, request: StepRequest,
                          build_files: Mapping[str, str] | None = None, *, state: persistence.ProjectState,
                          issues: Sequence[rules.Issue] = ()) -> str:
    """Build the prose-only first round for the current implementation target."""
    if state.phase != persistence.ProjectPhase.IMPLEMENTATION:
        raise ValueError("approach prompts are available only during the implementation phase")
    request = replace(request, phase=IMPLEMENTATION)
    parts = [
        _approach_role(),
        "# Specification and code profile\n\n" + specification.compact(spec),
        "# Current code\n\n" + describe_model(model, request.focus),
    ]
    if build_files:
        parts.append("# Build files\n\n" + "\n".join(f"## {name}\n```\n{content.rstrip()}\n```"
                                                     for name, content in sorted(build_files.items())))
    if issues:
        parts.append("# Current rule-check issues\n\n" + _issues_text(issues))
    parts.append("# Approach round\n\n" + _approach_step_text(request, model))
    feedback = _feedback(request)
    if feedback:
        parts.append("# Feedback on earlier approaches\n\n" + feedback)
    parts.append("# Response format\n\n" + _approach_format_text())
    return "\n\n".join(part.rstrip() for part in parts) + "\n"


def _approach_role() -> str:
    return ("You are the implementer planning one ICODA implementation step. The developer must decide on the "
            "approach before any code is written. Describe the intended implementation only. Do not emit source "
            "code, patches, diffs, file contents, or file changes in this round, and do not edit files or run tools.")


def _approach_step_text(request: StepRequest, model: DerivedModel) -> str:
    targets = _implementation_targets(request)
    lines = [f"Step {request.number} of the implementation phase."]
    if len(targets) == 1:
        lines.append(f"Propose an approach for exactly this function: {_target_text(model, targets[0])}.")
    else:
        lines.append("Propose one approach for exactly these functions in one small batch:")
        lines.extend(f"- {_target_text(model, target)}" for target in targets)
        lines.append("Do not plan implementation of any function outside this batch.")
        if request.grouped:
            lines.append("Plan distinct test evidence for every function in this deliberate few-line group.")
    if request.request.strip():
        lines.append(f"The developer asks: {request.request.strip()}")
    lines.extend([
        "Explain the algorithm, expected STL algorithms/containers or libraries, estimated line count, and trade-offs.",
        "Name the existing or planned entities and project-relative file paths you expect the later code round to touch.",
        "The developer will approve, adapt, or reject this approach before the separate code-and-test round.",
    ])
    return "\n".join(lines)


def _approach_format_text() -> str:
    return ("Reply with a single JSON object (no code fence or surrounding prose) with exactly these fields:\n"
            '{\n "plan": "prose implementation plan including trade-offs and estimated line count",\n'
            ' "entities": ["qualified entity name"],\n "files": ["project/relative/path"]\n}\n'
            "`entities` and `files` describe expected scope only. Do not include file contents, source code, "
            "patches, diffs, or commands.")


def _issues_text(issues: Sequence[rules.Issue]) -> str:
    lines = [f"- [{issue.severity.upper()}] {issue.rule_id} at {issue.file}:{issue.line}: {issue.message}"
             for issue in issues]
    omitted = issues.omitted if isinstance(issues, rules.IssueSelection) else 0
    if omitted:
        lines.append(f"... and {omitted} more")
    return "\n".join(lines)


def _role(request: StepRequest) -> str:
    what = ("the software architect" if request.phase == ARCHITECTURE else "the implementer")
    return (f"You are {what} of a project developed step by step with ICODA. The developer approves, rejects or "
            "adapts every step; you propose exactly one step now, as small as the rules below allow, and reply "
            "with one JSON object and nothing else. Do not run tools, do not edit files yourself: return the "
            "full contents of every file the step writes. Never use what the specification lists under "
            "'not allowed'; the project is finished when every 'done when' condition holds.")


def _step_text(request: StepRequest, model: DerivedModel, profile: Mapping[str, object]) -> str:
    lines = [f"Step {request.number} of the {request.phase} phase."]
    if request.request.strip():
        lines.append(f"The developer asks: {request.request.strip()}")
    else:
        lines.append("Propose the next step yourself, following the use cases and the code that exists.")
    lines.append("")
    lines.extend(_architecture_rules(request, profile) if request.phase == ARCHITECTURE
                 else _implementation_rules(request, model, profile))
    return "\n".join(lines)


def _architecture_rules(request: StepRequest, profile: Mapping[str, object]) -> list[str]:
    rules = [
        (f"- At most {request.max_entities} new architecture entities in this step. Each new module, type or alias, "
         "function or method, constructor or destructor, and global variable counts. Fields and individual enum "
         "values belong to their owning concept and do not consume separate slots. Any number of relations may "
         "connect the new and existing entities."),
    ]
    if profile.get("language") == "Python":
        extension = profile.get("source_file_extension", ".py")
        module_naming = profile.get("module_naming", "snake_case")
        class_naming = profile.get("class_naming", "PascalCase")
        function_naming = profile.get("function_naming", "snake_case")
        test_convention = profile.get("test_file_convention", "tests/test_<module>.py")
        rules.extend([
            (f"- One Python module per concept, in a `{extension}` source file. Name modules in {module_naming}, "
             f"classes in {class_naming}, and functions in {function_naming}. Follow the `{test_convention}` "
             "test-file convention."),
            ("- Define complete typed signatures with stub bodies. Keep required calls and object construction in "
             "the stubs so that the call graph is real code; otherwise raise `NotImplementedError`. Enums are "
             "complete. No algorithmic code."),
        ])
    else:
        rules.extend([
            ("- One C++20 module per concept with an exported interface; headers only where a library or platform "
             "forces them. Keep the CMake target lists in sync when files are added."),
            ("- Declarations with full signatures and empty bodies. The one exception: calls to other functions and "
             "the construction of the objects they need, so that the call graph is real compiled code. "
             "Value-returning stubs return `{}`. Enums are complete. No algorithmic code."),
        ])
    execution_rule = ("- Steps go top-down from `main()` along the use cases; the project must import and run after "
                      "the step." if profile.get("language") == "Python" else
                      "- Steps go top-down from `main()` along the use cases; the project must compile and run after "
                      "the step.")
    rules.extend([
        execution_rule,
        (("- Every entity gets a docstring and, where a requirement or use case applies, "
          "`@satisfies UC-n, R-n`.") if profile.get("language") == "Python" else
         ("- Every entity gets a Doxygen comment with @brief and, where a requirement or use case applies, "
          "`@satisfies UC-n, R-n`.")),
    ])
    return rules


def _implementation_rules(request: StepRequest, model: DerivedModel,
                          profile: Mapping[str, object]) -> list[str]:
    rules = []
    targets = _implementation_targets(request)
    if len(targets) == 1:
        rules.append(f"- Implement exactly this function: {_target_text(model, targets[0])}.")
    elif targets:
        rules.append("- Implement exactly these functions in one small batch:")
        rules.extend(f"  - {_target_text(model, target)}" for target in targets)
    else:
        rules.append("- Implement exactly one function that is still a stub, preferring leaves of the call graph.")
    python = profile.get("language") == "Python"
    framework = profile.get("test_framework", "pytest")
    runner = profile.get("test_runner", "python -m pytest")
    convention = profile.get("test_file_convention", "tests/test_<module>.py")
    test_rule = ((f"- Add or extend their {framework} tests following `{convention}`; run them with `{runner}`, "
                  "and make sure they pass.") if len(targets) > 1 else
                 (f"- Add or extend its {framework} test following `{convention}`; run it with `{runner}`, and make "
                  "sure it passes.")) if python else (
        "- Add or extend the tests for them in the project's test framework; the tests must pass."
        if len(targets) > 1 else "- Add or extend the test for it in the project's test framework; the test must pass.")
    rules.extend([
        ("- Do not implement any function outside this batch."
         if len(targets) > 1 else "- Do not implement other stub functions in this step."),
        test_rule,
        "- Keep the signature unless the specification forces a change, and then say so in the rationale.",
        "- Respect the Code Profile limits on function length; split helpers out when needed.",
    ])
    if request.grouped:
        rules.append("- Every function in this deliberate few-line group must have recorded reaching test evidence.")
    return rules


def _implementation_targets(request: StepRequest) -> tuple[str, ...]:
    return request.batch or ((request.target,) if request.target else ())


def _target_text(model: DerivedModel, target: str) -> str:
    entity = model.entities.get(target)
    name = entity.qualified_name if entity is not None else target
    signature = f" {entity.signature}" if entity is not None and entity.signature else ""
    return f"`{name}{signature}` (USR `{target}`)"


def _feedback(request: StepRequest) -> str:
    blocks = []
    if request.rejections:
        blocks.append("The developer rejected earlier proposals for this step:\n" +
                      "\n".join(f"- {r}" for r in request.rejections))
    if request.constraints:
        blocks.append("Hard constraints for this attempt:\n" + "\n".join(f"- {c}" for c in request.constraints))
    if request.build_errors.strip():
        blocks.append("The previous attempt did not build. Compiler output:\n```\n" +
                      request.build_errors.strip() + "\n```")
    if request.validation_error.strip():
        blocks.append("The previous reply was not usable: " + request.validation_error.strip() +
                      ". Reply again with one JSON object matching the response format.")
    return "\n\n".join(blocks)


def _format_text() -> str:
    schema = response.load_schema()
    return ("Reply with a single JSON object (no code fence, no prose around it) matching this schema:\n" +
            json.dumps(schema["properties"], indent=1) +
            "\n\nRules: `title` is one line for the commit message; `rationale` explains the step in prose; "
            "`files` lists every file the step creates, changes or deletes, with paths relative to the project "
            "root and the complete new content; `entities` summarises what the step introduces; `questions` "
            "is for what only the developer can answer.")


# --------------------------------------------------------------------------- model subset


def describe_model(model: DerivedModel, focus: Sequence[str] = (), skeleton_files: Iterable[str] = ()) -> str:
    """The files of the model near ``focus`` (all files when there is no focus and the model is small)."""
    files = subset_files(model, focus)
    if not model.files and not model.entities:
        listed = sorted(skeleton_files)
        return ("The project has only its skeleton so far" +
                (":\n" + "\n".join(f"- {f}" for f in listed) if listed else ".") + "\n")
    lines = [f"{len(model.files)} files, {len(model.entities)} entities; shown: {len(files)} files."]
    for file in files:
        lines.append(f"\n## {file}" + _file_note(model, file))
        lines.extend(_entity_lines(model, file))
        lines.extend(_relation_lines(model, file, files))
    if focus:
        calls = calls_within(model, files)
        if calls:
            lines.extend(["\n## Calls among the shown files", *calls])
    other = sorted(set(model.files) - set(files))
    if other:
        lines.append("\nOther files (not shown): " + ", ".join(other))
    return "\n".join(lines) + "\n"


def subset_files(model: DerivedModel, focus: Sequence[str] = ()) -> list[str]:
    """The focus files plus their direct neighbours over file-level relations, capped at MAX_SUBSET_FILES."""
    all_files = sorted(model.files)
    if not focus:
        return all_files[:MAX_SUBSET_FILES]
    chosen = {f for f in focus if f in model.files}
    chosen.update(model.file_of(item) or "" for item in focus)
    chosen.discard("")
    neighbours: set[str] = set()
    for (source, target, _kind) in model.file_edges():
        if source in chosen:
            neighbours.add(target)
        if target in chosen:
            neighbours.add(source)
    ordered = sorted(chosen) + sorted(neighbours - chosen)
    return ordered[:MAX_SUBSET_FILES]


def _file_note(model: DerivedModel, file: str) -> str:
    info = model.files.get(file)
    if info is None:
        return ""
    note = f"  ({info.unit}" + (f", module {info.module}" if info.module else "") + ")"
    return note + (f"  errors: {info.errors[0]}" if info.errors else "")


def _entity_lines(model: DerivedModel, file: str) -> list[str]:
    entities = sorted(model.entities_in(file), key=lambda e: e.line)
    lines = []
    for entity in entities:
        if entity.kind in (Kind.ENUMERATOR, Kind.NAMESPACE):
            continue
        lines.append(_entity_line(entity))
    return lines


def _entity_line(entity: Entity) -> str:
    text = f"- {entity.kind.value} {entity.qualified_name}"
    if entity.signature:
        text += f" {entity.signature}"
    if entity.kind in CALLABLE_KINDS:
        text += f" [{entity.status}]"
        if entity.test_files:
            text += " tests=" + ", ".join(entity.test_files)
    if entity.satisfies:
        text += " @satisfies " + ", ".join(entity.satisfies)
    if entity.brief:
        text += f" — {entity.brief}"
    return text


def _relation_lines(model: DerivedModel, file: str, shown: Sequence[str]) -> list[str]:
    counts: dict[tuple[str, str], int] = {}
    for (source, target, kind), count in model.file_edges().items():
        if source == file and (target in shown or target.startswith("external:")):
            key = (kind.value, target)
            counts[key] = counts.get(key, 0) + count
    if not counts:
        return []
    described = ", ".join(f"{kind} {target} ({count})" for (kind, target), count in sorted(counts.items()))
    return [f"  relations: {described}"]


def calls_within(model: DerivedModel, files: Sequence[str]) -> list[str]:
    """Function-level call lines among the shown files, for the implementation phase."""
    lines = []
    for edge in model.edges_of(EdgeKind.CALLS):
        source, target = model.entities.get(edge.source), model.entities.get(edge.target)
        if source and target and source.file in files and target.file in files:
            lines.append(f"- {source.qualified_name} calls {target.qualified_name}")
    return lines
