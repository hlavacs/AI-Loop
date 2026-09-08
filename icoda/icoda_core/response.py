"""The agent's answer: extracting the JSON object from whatever the binary printed and validating it.

A valid response (``response.schema.json``) names the files to write or delete with their full contents; the
error text of an invalid one goes back into the next prompt so that the agent can remake it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema

SCHEMA_PATH = Path(__file__).with_name("response.schema.json")
FORBIDDEN_PREFIXES = (".git/", ".icoda/cache/", "build/", "bin/")


@dataclass(frozen=True)
class FileChange:
    path: str
    content: str = ""
    delete: bool = False


@dataclass(frozen=True)
class StepResponse:
    """A validated response, ready to be applied to a worktree."""

    title: str
    rationale: str
    files: tuple[FileChange, ...]
    entities: tuple[dict[str, Any], ...] = ()
    questions: tuple[str, ...] = ()


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def extract_json(text: str) -> str | None:
    """The outermost ``{...}`` in ``text``; agents often wrap the object in prose or code fences."""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    return text[start:end + 1]


def parse_response(text: str) -> tuple[StepResponse | None, str]:
    """Return the response and an empty string, or None and what is wrong with the text."""
    candidate = extract_json(text)
    if candidate is None:
        return None, "the reply contains no JSON object"
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, f"the JSON object does not parse: {exc.msg} at line {exc.lineno}, column {exc.colno}"
    problems = validate(data)
    if problems:
        return None, "the JSON object does not match the response schema: " + "; ".join(problems[:5])
    return _to_response(data), ""


def validate(data: Any) -> list[str]:
    """Schema problems plus the path rules that a schema cannot express."""
    validator = jsonschema.Draft202012Validator(load_schema())
    problems = []
    for error in sorted(validator.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path]):
        where = "/".join(str(p) for p in error.absolute_path) or "(root)"
        problems.append(f"{where}: {error.message}")
    if isinstance(data, dict):
        problems.extend(_path_problems(data.get("files", [])))
    return problems


def _path_problems(files: Any) -> list[str]:
    problems = []
    seen: set[str] = set()
    for index, item in enumerate(files if isinstance(files, list) else []):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", ""))
        problem = path_problem(path)
        if problem:
            problems.append(f"files/{index}/path: {problem}")
        if path in seen:
            problems.append(f"files/{index}/path: {path!r} appears twice")
        seen.add(path)
        if item.get("action", "write") == "write" and "content" not in item:
            problems.append(f"files/{index}: a written file needs its full content")
    return problems


def path_problem(path: str) -> str:
    """Why ``path`` may not be written by the agent, or an empty string."""
    posix = PurePosixPath(path.replace("\\", "/"))
    if posix.is_absolute() or (len(path) > 1 and path[1] == ":"):
        return "must be relative to the project root"
    if ".." in posix.parts:
        return "must not leave the project root"
    if not path.strip() or path.strip() != path:
        return "must be a plain relative path"
    if any(str(posix).startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        return "may not touch git, build output or the ICODA cache"
    return ""


def _to_response(data: dict[str, Any]) -> StepResponse:
    files = tuple(FileChange(str(item["path"]).replace("\\", "/"), str(item.get("content", "")),
                             item.get("action") == "delete") for item in data["files"])
    return StepResponse(str(data["title"]).strip(), str(data["rationale"]).strip(), files,
                        tuple(data.get("entities", [])), tuple(str(q) for q in data.get("questions", [])))


def apply_changes(root: Path, files: tuple[FileChange, ...] | list[FileChange]) -> list[str]:
    """Write and delete the files under ``root``; return the paths touched."""
    touched = []
    for change in files:
        if path_problem(change.path):
            raise ValueError(f"{change.path}: {path_problem(change.path)}")
        target = root / change.path
        if change.delete:
            if target.exists():
                target.unlink()
                touched.append(change.path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change.content, encoding="utf-8")
        touched.append(change.path)
    return touched
