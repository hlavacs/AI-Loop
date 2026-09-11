"""Pure shared node appearance derivation."""

from __future__ import annotations

import pytest

from icoda_core import coverage_index, node_status, persistence, steplog
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, Kind


def _function(usr: str, *, body_hash: str = "", status: str = "implemented") -> Entity:
    return Entity(usr, Kind.FUNCTION, usr, usr, "src/app.cpp", 1,
                  status=status, body_hash=body_hash)


def _derive(model: DerivedModel, records: list[steplog.StepRecord] | None = None,
            state: persistence.ProjectState | None = None) -> node_status.NodeAppearanceMap:
    history = records or []
    index = coverage_index.build_index(model, history)
    return node_status.derive(model, state or persistence.ProjectState(), history, index)


def test_empty_model_returns_frozen_empty_mapping() -> None:
    appearances = _derive(DerivedModel("/p"))
    assert dict(appearances) == {}
    with pytest.raises(TypeError):
        appearances["u:any"] = node_status.NodeAppearance()  # type: ignore[index]


def test_node_never_touched_by_a_step_is_not_stale_and_can_be_queued() -> None:
    model = DerivedModel("/p")
    model.add_entity(_function("u:waiting", body_hash="current", status="stub"))
    state = persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("u:waiting",), 0)
    appearance = _derive(model, state=state)["u:waiting"]
    assert (appearance.status, appearance.queue_status, appearance.stale) == ("stub", "current", False)


def test_changed_body_since_last_touch_is_stale() -> None:
    model = DerivedModel("/p")
    model.add_entity(_function("u:f", body_hash="new"))
    records = [steplog.StepRecord(
        2, "implementation", "approved", entities_changed=["u:f"],
        entity_body_hashes={"u:f": "old"})]
    appearance = _derive(model, records)["u:f"]
    assert appearance.stale and appearance.status == "implemented"


def test_unchanged_body_since_last_touch_is_fresh_through_a_rename() -> None:
    model = DerivedModel("/p")
    model.add_entity(_function("u:new", body_hash="same", status="tested"))
    records = [
        steplog.StepRecord(1, "implementation", "approved", entities_changed=["u:old"],
                           entity_body_hashes={"u:old": "same"}),
        steplog.StepRecord(2, "implementation", "approved",
                           entities_renamed=[("u:old", "u:new")]),
    ]
    assert not _derive(model, records)["u:new"].stale


def test_uncovered_node_has_explicit_zero_test_coverage() -> None:
    model = DerivedModel("/p")
    model.add_entity(_function("u:uncovered"))
    appearance = _derive(model)["u:uncovered"]
    assert appearance.covered is False and appearance.covering_test_count == 0


def test_node_covered_by_several_tests_reports_unique_count() -> None:
    model = DerivedModel("/p")
    target = _function("u:target")
    model.add_entity(target)
    for number, name in enumerate(("alpha_test", "beta_test"), 1):
        usr = f"u:{name}"
        path = f"tests/{name}.cpp"
        model.add_entity(Entity(usr, Kind.FUNCTION, name, name, path, number))
        model.add_edge(Edge(EdgeKind.CALLS, usr, "u:target", path, number))
    records = [steplog.StepRecord(
        3, "implementation", "approved", test_ok=True,
        selected_tests=["tests/alpha_test.cpp", "tests/beta_test.cpp"])]
    appearance = _derive(model, records)["u:target"]
    assert appearance.covered is True and appearance.covering_test_count == 2


def test_global_stale_model_marks_every_node_and_legacy_hash_field_is_additive() -> None:
    model = DerivedModel("/p", stale=True, stale_reason="parse failed")
    model.add_entity(_function("u:f"))
    assert _derive(model)["u:f"].stale
    legacy = steplog.StepRecord.from_dict({
        "number": 1, "phase": "implementation", "decision": "approved",
    })
    assert legacy.entity_body_hashes == {}


def test_degenerate_unknown_hash_and_non_callable_coverage_are_safe() -> None:
    model = DerivedModel("/p")
    model.add_entity(Entity("u:type", Kind.CLASS, "Type", "Type", "src/type.cpp", 1))
    model.add_entity(_function("u:f", body_hash=""))
    records = [steplog.StepRecord(
        1, "implementation", "approved", entities_changed=["u:f"],
        entity_body_hashes={"u:f": "known"})]
    appearances = _derive(model, records)
    assert appearances["u:type"].covered is None
    assert not appearances["u:f"].stale
    assert appearances.get("u:missing") is None
