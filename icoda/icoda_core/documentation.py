"""Inventory and source-editing instructions for project purpose comments."""

from __future__ import annotations

from collections.abc import Sequence

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
