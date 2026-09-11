"""Clang-independent normalization and hashing of C++ function bodies."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator


def body_hash(body: str | None) -> str:
    """Return a stable digest of C++ tokens, or ``""`` when no body is available."""
    tokens = list(_tokens(body or ""))
    if len(tokens) >= 2 and tokens[0] == "{" and tokens[-1] == "}":
        tokens = tokens[1:-1]
    if not tokens:
        return ""
    return hashlib.sha256("\0".join(tokens).encode("utf-8")).hexdigest()


def changed(previous: str, current: str) -> bool:
    """Whether two available hashes from :func:`body_hash` describe different bodies."""
    return bool(previous and current and previous != current)


def _tokens(source: str) -> Iterator[str]:
    index = 0
    while index < len(source):
        if source[index].isspace():
            index += 1
        elif source.startswith("//", index):
            index = _line_comment_end(source, index + 2)
        elif source.startswith("/*", index):
            index = _block_comment_end(source, index + 2)
        else:
            end = _token_end(source, index)
            yield source[index:end]
            index = end


def _line_comment_end(source: str, index: int) -> int:
    end = source.find("\n", index)
    return len(source) if end < 0 else end + 1


def _block_comment_end(source: str, index: int) -> int:
    end = source.find("*/", index)
    return len(source) if end < 0 else end + 2


def _token_end(source: str, index: int) -> int:
    raw_end = _raw_string_end(source, index)
    if raw_end is not None:
        return raw_end
    if source[index] in "\"'":
        return _quoted_end(source, index)
    if source[index].isalnum() or source[index] == "_":
        end = index + 1
        while end < len(source) and (source[end].isalnum() or source[end] == "_"):
            end += 1
        return end
    return index + 1


def _quoted_end(source: str, index: int) -> int:
    quote = source[index]
    index += 1
    while index < len(source):
        if source[index] == "\\":
            index += 2
        elif source[index] == quote:
            return index + 1
        else:
            index += 1
    return len(source)


def _raw_string_end(source: str, index: int) -> int | None:
    prefixes = ("u8R\"", "uR\"", "UR\"", "LR\"", "R\"")
    prefix = next((value for value in prefixes if source.startswith(value, index)), None)
    if prefix is None:
        return None
    delimiter_start = index + len(prefix)
    opening = source.find("(", delimiter_start, delimiter_start + 17)
    if opening < 0:
        return None
    delimiter = source[delimiter_start:opening]
    closing = source.find(")" + delimiter + "\"", opening + 1)
    return len(source) if closing < 0 else closing + len(delimiter) + 2
