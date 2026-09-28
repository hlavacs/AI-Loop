"""Inventory and source-editing instructions for project purpose comments."""

from __future__ import annotations

import ast
import difflib
import shutil
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from icoda_core import agent, bodyhash, git, recovery, source_edit
from icoda_core.model import DerivedModel, Entity


def missing_entities(model: DerivedModel) -> tuple[Entity, ...]:
    """Include every analysed project entity, independently of diagram filters or targets."""
    return tuple(sorted((entity for entity in model.entities.values() if not entity.brief.strip()),
                        key=lambda entity: (entity.file, entity.line, entity.usr)))


def completion_prompt(entities: Sequence[Entity]) -> str:
    """Ask the CLI to read the code and add only the missing source documentation."""
    locations = "\n".join(f"- {entity.file}:{entity.line}: {entity.kind.value} {entity.qualified_name}"
                          for entity in entities)
    return ("Add a purpose comment to every entity listed below. Read its implementation, callers, and "
            "surrounding types first so the description explains its actual role. Start each comment with "
            "one simple sentence explaining what the entity does and why it exists, as a senior programmer "
            "would explain it to a junior. Do not just repeat its name or invent behaviour. For a stub, "
            "explain its intended role and clearly say it is not implemented yet.\n\n"
            "Edit only documentation comments or Python docstrings in the project's own source files. "
            "For C++, use /// @brief immediately before the declaration; document each field, enum value, "
            "alias, namespace, constructor, and destructor too. For Python classes and functions, use "
            "docstrings. Keep existing useful documentation, @satisfies tags, code, signatures, formatting, "
            "tests, build files, and user edits intact. Do not modify generated or third-party files, "
            "run builds, install packages, commit, or push. Line numbers are initial hints and will move "
            "as comments are inserted; identify each declaration by its name and context.\n\n"
            "Complete the entire list, then summarise what was documented and identify anything you could "
            "not document accurately. ICODA will reanalyse the files and check for remaining missing comments."
            "\n\nEntities missing purpose comments:\n" + locations)


@dataclass
class Completion:
    """A background CLI response and checked edits awaiting an idle UI."""

    response: recovery.RecoveryResult
    edits: list[tuple[source_edit.Document, str]]
    skipped: list[str]
    candidate: Path | None = None
    checked_files: list[source_edit.Document] = field(default_factory=list)


def validate_candidate(completion: Completion) -> None:
    """Refuse any changed source or candidate before applying the checked edits."""
    if completion.candidate is None or not completion.candidate.is_dir():
        raise ValueError("The purpose-comment candidate is missing.")
    for document in [*(original for original, _text in completion.edits), *completion.checked_files]:
        # Saving unchanged text only checks the shared Document snapshot; it writes nothing.
        document.save(document.text)


def apply(completion: Completion) -> tuple[bool, list[str]]:
    """Apply the desktop's checked edits, preserving files changed since the snapshot."""
    changed = False
    skipped = list(completion.skipped)
    for original, text in completion.edits:
        try:
            original.save(text)
            changed = True
        except (OSError, ValueError):
            skipped.append(original.relative)
    return changed, skipped


def reject(completion: Completion) -> None:
    """Discard the private candidate without changing project source."""
    if completion.candidate is not None:
        if completion.candidate.exists():
            shutil.rmtree(completion.candidate)
        completion.candidate = None
        completion.checked_files.clear()


def completion_refusal(*, idle: bool, unsaved: bool, proposal: bool = False,
                       model: DerivedModel | None = None) -> str:
    """Shared desktop idle/buffer/proposal gate; source facts must also be complete."""
    if not idle:
        return "Wait until ICODA is idle before proposing purpose comments."
    if unsaved:
        return "Save or close unsaved documents before proposing purpose comments."
    if proposal:
        return "An existing proposal must be reviewed before purpose comments can proceed."
    if model is not None and (model.stale or any(info.errors for info in model.files.values())):
        return "Analyse the project successfully before proposing purpose comments."
    return ""


def propose(root: Path, model: DerivedModel, provider: agent.Provider, model_id: str, binary: str,
            *, idle: bool, unsaved: bool, proposal: bool, cancelled: Callable[[], bool],
            progress: Callable[[str], None]) -> Completion:
    """Use the desktop's private-copy workflow, retaining a candidate for later review only."""
    refusal = completion_refusal(idle=idle, unsaved=unsaved, proposal=proposal, model=model)
    if refusal:
        raise ValueError(refusal)
    pending = missing_entities(model)
    progress(f"Proposing purpose comments for {len(pending)} entities")
    message = completion_prompt(pending)
    def invoke(scratch: Path) -> recovery.RecoveryResult:
        return recovery.invoke(provider, model_id, message, scratch, binary=binary, writable=True,
                               cancelled=cancelled, progress=progress)
    result = complete(root, tuple(model.files), invoke)
    if not result.response.result.ok or cancelled():
        return result
    directory = root / ".icoda" / "cache"
    directory.mkdir(parents=True, exist_ok=True)
    result.candidate = Path(tempfile.mkdtemp(prefix="purpose-", dir=directory))
    for original, text in result.edits:
        target = result.candidate / original.relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original.original)
        checked = source_edit.Document.load(result.candidate, original.relative)
        checked.save(text)
        result.checked_files.append(checked)
    return result


def complete(root: Path, files: Sequence[str], invoke: Callable[[Path], recovery.RecoveryResult]) -> Completion:
    """Let the CLI edit a private source copy so normal project work can continue."""
    originals = []
    skipped = []
    with tempfile.TemporaryDirectory(prefix="icoda-comments-") as directory:
        scratch = Path(directory)
        git.run_git(["init", "-q"], scratch)  # Codex expects a repository, including for documentation.
        for file in files:
            try:
                original = source_edit.Document.load(root, file)
            except (OSError, ValueError):
                skipped.append(file)
                continue
            target = scratch / original.relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original.original)
            originals.append(original)
        response = invoke(scratch)
        edits = []
        for original in originals:
            try:
                updated = source_edit.Document.load(scratch, original.relative)
                if updated.text == original.text:
                    continue
                if not comments_only(original.relative, original.text, updated.text):
                    raise ValueError("The CLI changed code rather than only adding documentation.")
                edits.append((original, updated.text))
            except (OSError, ValueError):
                skipped.append(original.relative)
        return Completion(response, edits, skipped)


def comments_only(file: str, before: str, after: str) -> bool:
    """Reject code edits; C++ adds full comment lines and Python may add docstrings."""
    if file.endswith(".py"):
        trees = []
        try:
            for source in (before, after):
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if (isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                            and ast.get_docstring(node) is not None):
                        node.body = node.body[1:]
                trees.append(ast.dump(tree))
        except SyntaxError:
            return False
        return trees[0] == trees[1]
    old, new = before.splitlines(keepends=True), after.splitlines(keepends=True)
    for tag, start, _end, new_start, new_end in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag != "insert" or (start and old[start - 1].rstrip().endswith("\\")):
            return False
        if any(not line.lstrip().startswith("///") or line.rstrip().endswith("\\")
               for line in new[new_start:new_end]):
            return False
    # A comment-looking line inside a raw string is data, not documentation.
    return bodyhash.body_hash(before) == bodyhash.body_hash(after)
