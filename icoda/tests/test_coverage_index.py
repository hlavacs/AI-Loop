"""Callable recorded-test reachability index and its Tk-stub overview."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

from icoda_core import coverage_index, steplog, test_selection
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, Kind
from icoda_gui import coverage_view


def coverage_model(reverse: bool = False) -> DerivedModel:
    model = DerivedModel("/project")
    entities = [
        Entity("u:test", Kind.FUNCTION, "test_direct", "suite::test_direct", "tests/app_test.cpp", 2),
        Entity("u:direct", Kind.FUNCTION, "direct", "app::direct", "src/app.cpp", 10),
        Entity("u:transitive", Kind.METHOD, "nested", "app::Worker::nested", "src/app.cpp", 20),
        Entity("u:none", Kind.FUNCTION, "unused", "app::unused", "src/app.cpp", 30),
        Entity("u:data", Kind.VARIABLE, "data", "app::data", "src/app.cpp", 40),
    ]
    for entity in reversed(entities) if reverse else entities:
        model.add_entity(entity)
    model.add_edge(Edge(EdgeKind.CALLS, "u:test", "u:direct"))
    model.add_edge(Edge(EdgeKind.CALLS, "u:direct", "u:transitive"))
    return model


def successful_record() -> steplog.StepRecord:
    return steplog.StepRecord(
        7, "implementation", "approved", title="Implement direct", test_ok=True,
        selected_tests=["suite::test_direct"], time="2026-09-10T08:00:00+00:00")


def test_index_maps_direct_transitive_and_uncovered_callables() -> None:
    index = coverage_index.build_index(coverage_model(), [successful_record()])
    entries = index.entry_map()
    assert [entry.qualified_name for entry in index.entries] == [
        "app::Worker::nested", "app::direct", "app::unused", "suite::test_direct"]
    assert entries["u:direct"].tests == ("suite::test_direct",)
    assert entries["u:transitive"].tests == ("suite::test_direct",)
    assert entries["u:transitive"].evidence == (
        coverage_index.CoverageEvidence(
            7, "Implement direct", "2026-09-10T08:00:00+00:00", ("suite::test_direct",)),)
    assert index.uncovered == ("u:none",)
    assert index.covered == ("u:transitive", "u:direct", "u:test")
    assert "u:data" not in entries


def test_index_is_deterministic_and_empty_history_is_valid(tmp_path: Path) -> None:
    first = coverage_index.build_index(coverage_model(), [successful_record()])
    second = coverage_index.build_index(coverage_model(reverse=True), [successful_record()])
    assert first == second

    old_model = DerivedModel.from_json(coverage_model().to_json())
    empty = coverage_index.build_index(old_model, steplog.StepLog(tmp_path / "missing.jsonl"))
    assert empty.covered == ()
    assert empty.uncovered == ("u:transitive", "u:direct", "u:none", "u:test")
    assert all(not entry.evidence and not entry.tests for entry in empty.entries)


def test_newest_successful_record_without_named_tests_has_no_coverage() -> None:
    record = steplog.StepRecord(
        8, "implementation", "approved", title="Implement direct", test_ok=True,
        entities_changed=["u:direct"], time="2026-09-10T09:00:00+00:00")

    entries = coverage_index.build_index(coverage_model(), [record]).entry_map()

    assert entries["u:direct"].tests == ()


def test_failed_undone_and_legacy_records_are_handled_without_changing_selection() -> None:
    model = coverage_model()
    failed = steplog.StepRecord(2, "implementation", "approved", test_ok=False,
                                selected_tests=["suite::test_direct"])
    passed = steplog.StepRecord.from_dict(
        {"number": 3, "phase": "implementation", "decision": "approved", "tests_passed": True,
         "selected_tests": ["suite::test_direct"]})
    undone = steplog.StepRecord(4, "implementation", "undone", undoes=3)
    assert coverage_index.build_index(model, [failed, passed, undone]).covered == ()
    assert test_selection.select_tests(model, [failed, passed, undone], "u:transitive") == (
        "suite::test_direct", "tests/app_test.cpp")


def test_index_credits_only_identifiers_named_by_each_successful_record() -> None:
    model = DerivedModel("/project")
    for entity in (
        Entity("u:alpha-test", Kind.FUNCTION, "test_alpha", "suite::test_alpha", "tests/test_alpha.py", 2),
        Entity("u:alpha-root", Kind.FUNCTION, "alpha_root", "app::alpha_root", "src/app.py", 10),
        Entity("u:alpha-leaf", Kind.METHOD, "alpha_leaf", "app::alpha_leaf", "src/app.py", 20),
        Entity("u:beta-test", Kind.FUNCTION, "test_beta", "suite::test_beta", "tests/test_beta.py", 3),
        Entity("u:beta-leaf", Kind.FUNCTION, "beta_leaf", "app::beta_leaf", "src/beta.py", 30),
        Entity("u:unrecorded-test", Kind.FUNCTION, "test_unrecorded", "suite::test_unrecorded",
               "tests/test_unrecorded.py", 4),
        Entity("u:uncredited", Kind.FUNCTION, "uncredited", "app::uncredited", "src/unused.py", 40),
    ):
        model.add_entity(entity)
    for edge in (
        Edge(EdgeKind.CALLS, "u:alpha-test", "u:alpha-root"),
        Edge(EdgeKind.CALLS, "u:alpha-root", "u:alpha-leaf"),
        Edge(EdgeKind.CALLS, "u:beta-test", "u:beta-leaf"),
        Edge(EdgeKind.CALLS, "u:unrecorded-test", "u:uncredited"),
    ):
        model.add_edge(edge)
    records = (
        steplog.StepRecord(
            9, "implementation", "approved", title="Alpha", test_ok=True,
            selected_tests=["suite::test_alpha"], time="2026-09-10T09:00:00+00:00"),
        steplog.StepRecord(
            10, "implementation", "manual", title="Beta", tests_passed=True,
            selected_tests=["suite::test_beta"], time="2026-09-10T10:00:00+00:00"),
        steplog.StepRecord(
            11, "implementation", "approved", title="Failed unrecorded", test_ok=False,
            selected_tests=["suite::test_unrecorded"], time="2026-09-10T11:00:00+00:00"),
        steplog.StepRecord(
            12, "implementation", "manual", title="Also failed", test_ok=False,
            selected_tests=["suite::test_alpha"], time="2026-09-10T12:00:00+00:00"),
    )
    alpha = coverage_index.CoverageEvidence(
        9, "Alpha", "2026-09-10T09:00:00+00:00", ("suite::test_alpha",))
    beta = coverage_index.CoverageEvidence(
        10, "Beta", "2026-09-10T10:00:00+00:00", ("suite::test_beta",))

    assert coverage_index.build_index(model, records) == coverage_index.CoverageIndex(
        entries=(
            coverage_index.CoverageEntry(
                "u:alpha-leaf", "app::alpha_leaf", "", "src/app.py", 20,
                (alpha,), ("suite::test_alpha",)),
            coverage_index.CoverageEntry(
                "u:alpha-root", "app::alpha_root", "", "src/app.py", 10,
                (alpha,), ("suite::test_alpha",)),
            coverage_index.CoverageEntry(
                "u:beta-leaf", "app::beta_leaf", "", "src/beta.py", 30,
                (beta,), ("suite::test_beta",)),
            coverage_index.CoverageEntry(
                "u:uncredited", "app::uncredited", "", "src/unused.py", 40),
            coverage_index.CoverageEntry(
                "u:alpha-test", "suite::test_alpha", "", "tests/test_alpha.py", 2,
                (alpha,), ("suite::test_alpha",)),
            coverage_index.CoverageEntry(
                "u:beta-test", "suite::test_beta", "", "tests/test_beta.py", 3,
                (beta,), ("suite::test_beta",)),
            coverage_index.CoverageEntry(
                "u:unrecorded-test", "suite::test_unrecorded", "",
                "tests/test_unrecorded.py", 4),
        ),
        uncovered=("u:uncredited", "u:unrecorded-test"),
    )


def test_coverage_overview_renders_covered_uncovered_and_empty_history(monkeypatch: Any) -> None:
    opened: list[tuple[str, int]] = []
    overview = coverage_view.CoverageOverview(tk.Tk(), lambda file, line: opened.append((file, line)))
    rendered: list[tuple[Any, ...]] = []
    monkeypatch.setattr(overview.tree, "insert",
                        lambda _parent, _where, **kwargs: rendered.append(tuple(kwargs["values"])))

    overview.show(coverage_model(), [successful_record()])
    assert overview.summary_var.get() == \
        "Recorded test reachability: 3/4 analysed callables reached · 1 not reached"
    assert any(row[0] == "Reached" and "app::direct" in row[1]
               and "suite::test_direct" in row[2] and "#7 Implement direct" in row[3]
               for row in rendered)
    assert any(row[0] == "Not reached" and "app::unused" in row[1] for row in rendered)
    monkeypatch.setattr(overview.tree, "selection", lambda: ("u:direct",))
    overview._open_selected(None)
    assert opened == [("src/app.cpp", 10)]

    rendered.clear()
    overview.show(coverage_model(), [])
    assert overview.summary_var.get() == \
        "Recorded test reachability: 0/4 analysed callables reached · 4 not reached"
    assert overview.note_var.get().startswith("No reaching recorded test identifiers")
    assert len(rendered) == 4 and all(
        row[0] == "Not reached" and row[2] == "No reaching recorded test" for row in rendered)
