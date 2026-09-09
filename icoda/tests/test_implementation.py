"""Implementation-phase target ordering over the parsed call graph."""

from __future__ import annotations

from pathlib import Path

from icoda_core import implementation, persistence, prompt, steplog, steps
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, Kind


def _model(*names: str) -> DerivedModel:
    model = DerivedModel("/p")
    for name in names:
        model.add_entity(Entity(f"u:{name}", Kind.FUNCTION, name, name, "src/app.cpp", 1, status="stub"))
    return model


def _call(model: DerivedModel, caller: str, callee: str) -> None:
    model.add_edge(Edge(EdgeKind.CALLS, f"u:{caller}", f"u:{callee}", "src/app.cpp", 1))


def test_bottom_up_order_chooses_a_leaf_then_its_caller() -> None:
    model = _model("root", "middle", "leaf")
    _call(model, "root", "middle")
    _call(model, "middle", "leaf")
    assert implementation.next_target(model).usr == "u:leaf"  # type: ignore[union-attr]
    model.entities["u:leaf"].status = "tested"
    assert implementation.next_target(model).usr == "u:middle"  # type: ignore[union-attr]


def test_cycles_and_independent_leaves_are_resolved_deterministically() -> None:
    model = _model("zeta", "beta", "alpha")
    _call(model, "beta", "alpha")
    _call(model, "alpha", "beta")
    assert implementation.next_target(model).usr == "u:alpha"  # type: ignore[union-attr]
    model.entities["u:alpha"].status = "implemented"
    assert implementation.next_target(model).usr == "u:beta"  # type: ignore[union-attr]


def test_body_only_changes_are_part_of_the_model_delta() -> None:
    before, after = _model("work"), _model("work")
    before.entities["u:work"].body_hash = "before"
    after.entities["u:work"].body_hash = "after"
    assert [entity.usr for entity in steps.compute_delta(before, after, ["src/app.cpp"]).changed] == ["u:work"]


def test_test_callables_and_non_stubs_are_not_candidates() -> None:
    model = DerivedModel("/p")
    model.add_entity(Entity("u:test", Kind.FUNCTION, "test_a", "test_a", "tests/a_test.cpp", 1, status="stub"))
    model.add_entity(Entity("u:done", Kind.FUNCTION, "done", "done", "src/a.cpp", 1, status="tested"))
    assert implementation.candidates(model) == []
    assert implementation.next_target(model) is None


def test_runner_persists_phase_and_fills_an_empty_implementation_request(tmp_path: Path) -> None:
    model = _model("root", "leaf")
    _call(model, "root", "leaf")
    runner = steps.StepRunner(tmp_path, persistence.UserConfig())
    runner.store.ensure()
    runner.store.save_model(model)
    runner.log.append(steplog.StepRecord(0, prompt.ARCHITECTURE, "approved",
                                        entities_added=list(model.entities)))
    assert runner.log.current_phase() == prompt.ARCHITECTURE
    transition = runner.transition_phase(prompt.IMPLEMENTATION)
    assert transition is not None and transition.decision == "phase"
    assert runner.log.current_phase() == prompt.IMPLEMENTATION
    assert runner.transition_phase(prompt.IMPLEMENTATION) is None
    request = runner._implementation_request(prompt.StepRequest(prompt.IMPLEMENTATION, 0))
    assert request.focus == ("u:leaf",) and request.request == "Implement leaf."


def test_manual_status_record_downgrades_a_tested_function(tmp_path: Path) -> None:
    model = _model("work")
    entity = model.entities["u:work"]
    entity.body_hash = "same-body"
    entity.test_files = ("tests/work_test.cpp",)
    log = steplog.StepLog(tmp_path / "steps.jsonl")
    log.append(steplog.StepRecord(1, prompt.IMPLEMENTATION, "approved", entities_changed=[entity.usr],
                                  body_hashes={entity.usr: entity.body_hash},
                                  test_files={entity.usr: list(entity.test_files)},
                                  build_passed=True, tests_passed=True))
    steplog.apply_statuses(model, log)
    assert entity.status == "tested"
    log.append(steplog.StepRecord(2, "manual", "manual", entities_changed=[entity.usr]))
    steplog.apply_statuses(model, log)
    assert entity.status == "implemented"
