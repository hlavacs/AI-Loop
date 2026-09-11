"""Pure structured-summary rendering, parsing, and deterministic change descriptions."""

from __future__ import annotations

import inspect
import json

from icoda_core import adaptation


def test_structured_summary_round_trip_is_canonical_and_has_no_tk_dependency() -> None:
    entities = (
        adaptation.EntitySummary(
            "service.Formatter", "class", "service.py", "class Formatter", ("R-1",)),
    )
    shown = adaptation.render_summary(entities)
    assert shown == '''[
  {
    "name": "service.Formatter",
    "kind": "class",
    "file": "service.py",
    "signature": "class Formatter",
    "satisfies": [
      "R-1"
    ]
  }
]
'''
    assert adaptation.parse_summary(shown) == adaptation.ParseResult(entities)
    assert "tkinter" not in inspect.getsource(adaptation)


def test_structured_summary_parser_returns_exact_ordinary_problems() -> None:
    malformed = json.dumps([
        {"name": "", "kind": "widget", "file": 3, "signature": [],
         "satisfies": "R-1", "extra": True},
        "not an entity",
    ])
    assert adaptation.parse_summary(malformed) == adaptation.ParseResult(problems=(
        "entity 1: unknown field 'extra'",
        "entity 1/name: must be a non-empty string",
        "entity 1/kind: must be one of module, namespace, struct, class, enum, function, method, alias, variable",
        "entity 1/file: must be a string",
        "entity 1/signature: must be a string",
        "entity 1/satisfies: must be an array of strings",
        "entity 2: must be an object",
    ))


def test_structured_summary_change_description_is_deterministic() -> None:
    before = (adaptation.EntitySummary(
        "service.Formatter", "class", "service.py", "class Formatter", ("R-1",)),)
    after = (adaptation.EntitySummary(
        "service.TextFormatter", "class", "service.py", "class TextFormatter", ("R-1", "R-2")),)
    assert adaptation.describe_changes(before, after) == (
        "Correct the proposal's structured entity summary: entity 1 name changed from "
        '"service.Formatter" to "service.TextFormatter"; entity 1 signature changed from '
        '"class Formatter" to "class TextFormatter"; entity 1 satisfies changed from '
        '["R-1"] to ["R-1", "R-2"].'
    )
