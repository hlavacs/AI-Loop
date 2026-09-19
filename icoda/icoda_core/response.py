"""Pure parsing of the agent's structured answer into full-file changes or unified-diff hunks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema

from icoda_core import adaptation

SCHEMA_PATH = Path(__file__).with_name("response.schema.json")
FORBIDDEN_PREFIXES = (".git/", ".icoda/", "build/", "bin/")
DIFF_DISCRIMINATOR = "diff --git "
HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$")
MAX_RESPONSE_BYTES = 200_000


@dataclass(frozen=True)
class DiffHunk:
    """One validated unified-diff hunk; line prefixes retain their patch meaning."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class FileChange:
    path: str
    content: str = ""
    delete: bool = False
    hunks: tuple[DiffHunk, ...] = ()


@dataclass(frozen=True)
class StepResponse:
    """A validated response, ready to be applied to a worktree."""

    title: str
    rationale: str
    files: tuple[FileChange, ...]
    entities: tuple[adaptation.EntitySummary, ...] = ()
    questions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApproachResponse:
    """A validated prose-only implementation approach."""

    plan: str
    entities: tuple[str, ...]
    files: tuple[str, ...]


APPROACH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["plan", "entities", "files"],
    "properties": {
        "plan": {"type": "string", "minLength": 1},
        "entities": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "files": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
}


def load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
        return json.load(schema_file)


def extract_json(text: str) -> str | None:
    """The outermost ``{...}`` in ``text``; agents often wrap the object in prose or code fences."""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    return text[start:end + 1]


def parse_response(text: str) -> tuple[StepResponse | None, str]:
    """Return the response and an empty string, or None and what is wrong with the text."""
    if _payload_size(text) > MAX_RESPONSE_BYTES:
        return None, f"the reply exceeds the {MAX_RESPONSE_BYTES}-byte size limit"
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
    assert isinstance(data, dict)
    try:
        return _to_response(data), ""
    except ValueError as exc:
        return None, str(exc)


def parse_approach_response(text: str) -> tuple[ApproachResponse | None, str]:
    """Return a prose-only approach, rejecting file contents and unsafe expected paths."""
    if _payload_size(text) > MAX_RESPONSE_BYTES:
        return None, f"the reply exceeds the {MAX_RESPONSE_BYTES}-byte size limit"
    candidate = extract_json(text)
    if candidate is None:
        return None, "the reply contains no JSON object"
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, f"the JSON object does not parse: {exc.msg} at line {exc.lineno}, column {exc.colno}"
    problems = _approach_problems(data)
    if problems:
        return None, "the JSON object does not match the approach schema: " + "; ".join(problems[:5])
    assert isinstance(data, dict)
    return ApproachResponse(str(data["plan"]).strip(), tuple(str(item) for item in data["entities"]),
                            tuple(str(item).replace("\\", "/") for item in data["files"])), ""


def _approach_problems(data: Any) -> list[str]:
    validator = jsonschema.Draft202012Validator(APPROACH_SCHEMA)
    problems = []
    for error in sorted(validator.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path]):
        where = "/".join(str(p) for p in error.absolute_path) or "(root)"
        problems.append(f"{where}: {error.message}")
    if isinstance(data, dict) and isinstance(data.get("plan"), str) and not data["plan"].strip():
        problems.append("plan: must contain prose")
    if isinstance(data, dict) and isinstance(data.get("files"), list):
        for index, item in enumerate(data["files"]):
            if isinstance(item, str) and path_problem(item):
                problems.append(f"files/{index}: {path_problem(item)}")
    problems.extend(_unicode_problems(data))
    return problems


def validate(data: Any) -> list[str]:
    """Schema problems plus the path rules that a schema cannot express."""
    validator = jsonschema.Draft202012Validator(load_schema())
    problems = []
    for error in sorted(validator.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path]):
        where = "/".join(str(p) for p in error.absolute_path) or "(root)"
        problems.append(f"{where}: {error.message}")
    if isinstance(data, dict):
        problems.extend(_path_problems(data.get("files", [])))
    problems.extend(_unicode_problems(data))
    return problems


def _payload_size(text: str) -> int:
    return len(text.encode("utf-8", errors="surrogatepass"))


def _unicode_problems(value: Any, parts: tuple[str, ...] = ()) -> list[str]:
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            where = "/".join(parts) or "(root)"
            return [f"{where}: must contain valid UTF-8 text"]
        return []
    if isinstance(value, dict):
        return [problem for key, item in value.items()
                for problem in _unicode_problems(item, (*parts, str(key)))]
    if isinstance(value, list):
        return [problem for index, item in enumerate(value)
                for problem in _unicode_problems(item, (*parts, str(index)))]
    return []


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
    if "\0" in path:
        return "must not contain a NUL byte"
    posix = PurePosixPath(path.replace("\\", "/"))
    if posix.is_absolute() or (len(path) > 1 and path[1] == ":"):
        return "must be relative to the project root"
    if ".." in posix.parts:
        return "must not leave the project root"
    if not path.strip() or path.strip() != path:
        return "must be a plain relative path"
    if any(str(posix).startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        return "may not touch git, build output or the .icoda folder"
    return ""


def _to_response(data: dict[str, Any]) -> StepResponse:
    files = tuple(_file_change(item) for item in data["files"])
    return StepResponse(str(data["title"]).strip(), str(data["rationale"]).strip(), files,
                        tuple(adaptation.from_mapping(item) for item in data.get("entities", [])),
                        tuple(str(q) for q in data.get("questions", [])))


def _file_change(item: dict[str, Any]) -> FileChange:
    path = str(item["path"]).replace("\\", "/")
    content = str(item.get("content", ""))
    delete = item.get("action") == "delete"
    hunks = _parse_unified_diff(path, content) if not delete and content.startswith(DIFF_DISCRIMINATOR) else ()
    return FileChange(path, content, delete, hunks)


def _parse_unified_diff(path: str, content: str) -> tuple[DiffHunk, ...]:
    lines = content.splitlines(keepends=True)
    header = lines[0].rstrip("\r\n")
    expected = f"diff --git a/{path} b/{path}"
    if header != expected:
        raise ValueError(f"unified diff for {path!r} has header {header!r}; expected {expected!r}")
    if len(lines) < 4 or lines[1].rstrip("\r\n") != f"--- a/{path}" \
            or lines[2].rstrip("\r\n") != f"+++ b/{path}":
        raise ValueError(f"unified diff for {path!r} must contain exact --- a/{path} and +++ b/{path} headers")
    hunks: list[DiffHunk] = []
    index = 3
    while index < len(lines):
        shown = lines[index].rstrip("\r\n")
        match = HUNK_HEADER.fullmatch(shown)
        if match is None:
            raise ValueError(f"unified diff for {path!r} has malformed hunk header at line {index + 1}: {shown!r}")
        old_start, old_count, new_start, new_count = _hunk_numbers(match)
        index += 1
        body: list[str] = []
        while index < len(lines) and not lines[index].startswith("@@"):
            line = lines[index]
            if line.startswith(DIFF_DISCRIMINATOR):
                raise ValueError(f"unified diff for {path!r} contains more than one file")
            if line.startswith("\\ No newline at end of file"):
                if not body:
                    raise ValueError(f"unified diff for {path!r} has a misplaced no-newline marker")
                body[-1] = body[-1].rstrip("\r\n")
            elif not line or line[0] not in " +-":
                raise ValueError(f"unified diff for {path!r} has an invalid hunk line at line {index + 1}")
            else:
                body.append(line)
            index += 1
        _check_hunk_counts(path, len(hunks) + 1, old_count, new_count, body)
        hunks.append(DiffHunk(old_start, old_count, new_start, new_count, tuple(body)))
    if not hunks:
        raise ValueError(f"unified diff for {path!r} contains no hunks")
    return tuple(hunks)


def _hunk_numbers(match: re.Match[str]) -> tuple[int, int, int, int]:
    return (int(match.group(1)), int(match.group(2) or "1"),
            int(match.group(3)), int(match.group(4) or "1"))


def _check_hunk_counts(path: str, number: int, old_count: int, new_count: int, lines: list[str]) -> None:
    actual_old = sum(line[0] in " -" for line in lines)
    actual_new = sum(line[0] in " +" for line in lines)
    if (actual_old, actual_new) != (old_count, new_count):
        raise ValueError(f"unified diff for {path!r} hunk {number} line counts disagree with its header: "
                         f"expected old {old_count}/new {new_count}, got old {actual_old}/new {actual_new}")


def apply_changes(root: Path, files: tuple[FileChange, ...] | list[FileChange]) -> list[str]:
    """Write and delete the files under ``root``; return the paths touched."""
    touched = []
    resolved_root = root.resolve()
    for change in files:
        if path_problem(change.path):
            raise ValueError(f"{change.path}: {path_problem(change.path)}")
        target = root / change.path
        try:
            target.resolve().relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"candidate path {change.path!r} leaves the project root") from exc
        if change.delete:
            if target.exists():
                target.unlink()
                touched.append(change.path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change.content, encoding="utf-8")
        touched.append(change.path)
    return touched
