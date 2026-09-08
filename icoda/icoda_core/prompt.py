"""Prompt assembly for one step.

A prompt carries the Code Profile and the compact specification, the part of the derived model the step touches,
the step request with the rules of its phase, the feedback gathered so far (rejections, constraints, compiler
output, a validation error), and the response format. Everything is plain text; the answer must be one JSON object.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from icoda_core import response, specification
from icoda_core.model import CALLABLE_KINDS, DerivedModel, EdgeKind, Entity, Kind

ARCHITECTURE = "architecture"
IMPLEMENTATION = "implementation"
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


def build_prompt(spec: specification.Specification, model: DerivedModel, request: StepRequest,
                 skeleton_files: Iterable[str] = ()) -> str:
    """The complete prompt text for ``request``."""
    parts = [
        _role(request),
        "# Specification and code profile\n\n" + specification.compact(spec),
        "# Current code\n\n" + describe_model(model, request.focus, skeleton_files),
        "# This step\n\n" + _step_text(request),
    ]
    feedback = _feedback(request)
    if feedback:
        parts.append("# Feedback on earlier attempts\n\n" + feedback)
    parts.append("# Response format\n\n" + _format_text())
    return "\n\n".join(part.rstrip() for part in parts) + "\n"


def _role(request: StepRequest) -> str:
    what = ("the software architect" if request.phase == ARCHITECTURE else "the implementer")
    return (f"You are {what} of a project developed step by step with ICODA. The developer approves, rejects or "
            "adapts every step; you propose exactly one step now, as small as the rules below allow, and reply "
            "with one JSON object and nothing else. Do not run tools, do not edit files yourself: return the "
            "full contents of every file the step writes.")


def _step_text(request: StepRequest) -> str:
    lines = [f"Step {request.number} of the {request.phase} phase."]
    if request.request.strip():
        lines.append(f"The developer asks: {request.request.strip()}")
    else:
        lines.append("Propose the next step yourself, following the use cases and the code that exists.")
    lines.append("")
    lines.extend(_architecture_rules(request) if request.phase == ARCHITECTURE else _implementation_rules())
    return "\n".join(lines)


def _architecture_rules(request: StepRequest) -> list[str]:
    return [
        (f"- At most {request.max_entities} new entities (modules, structs, classes, enums, functions) in this step; "
         "any number of relations among them and to existing code."),
        ("- One C++20 module per concept with an exported interface; headers only where a library or platform "
         "forces them. Keep the CMake target lists in sync when files are added."),
        ("- Declarations with full signatures and empty bodies. The one exception: calls to other functions and the "
         "construction of the objects they need, so that the call graph is real compiled code. Value-returning "
         "stubs return `{}`. Enums are complete. No algorithmic code."),
        "- Steps go top-down from `main()` along the use cases; the project must compile and run after the step.",
        ("- Every entity gets a Doxygen comment with @brief and, where a requirement or use case applies, "
         "`@satisfies UC-n, R-n`."),
    ]


def _implementation_rules() -> list[str]:
    return [
        ("- Implement exactly one function (or a trivial group such as a getter/setter pair) that is still a stub, "
         "preferring leaves of the call graph so that it can be tested at once."),
        "- Add or extend the test for it in the project's test framework; the test must pass.",
        "- Keep the signature unless the specification forces a change, and then say so in the rationale.",
        "- Respect the Code Profile limits on function length; split helpers out when needed.",
    ]


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
