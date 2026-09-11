"""Pure targeted-test selection over the derived call graph and step history."""

from __future__ import annotations

from pathlib import Path

from icoda_core import steplog, test_selection
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, Kind


def selection_model() -> DerivedModel:
    model = DerivedModel("/project")
    entities = (
        Entity("u:target", Kind.FUNCTION, "target", "app::target", "src/app.cpp", 10),
        Entity("u:bridge", Kind.FUNCTION, "bridge", "test::bridge", "tests/z_test.cpp", 4),
        Entity("u:z", Kind.FUNCTION, "test_z", "test::test_z", "tests/z_test.cpp", 1),
        Entity("u:a", Kind.FUNCTION, "test_a", "test::test_a", "tests/a_test.cpp", 1),
        Entity("u:other", Kind.FUNCTION, "test_other", "test::test_other", "tests/other_test.cpp", 1),
        Entity("u:none", Kind.FUNCTION, "none", "app::none", "src/app.cpp", 20),
    )
    for entity in entities:
        model.add_entity(entity)
    model.add_edge(Edge(EdgeKind.CALLS, "u:z", "u:bridge"))
    model.add_edge(Edge(EdgeKind.CALLS, "u:bridge", "u:target"))
    model.add_edge(Edge(EdgeKind.CALLS, "u:a", "u:target"))
    return model


def test_target_reached_by_a_known_test_selects_that_test(tmp_path: Path) -> None:
    model = selection_model()
    del model.entities["u:z"], model.entities["u:bridge"]
    model.edges = [edge for edge in model.edges if edge.source not in ("u:z", "u:bridge")]
    log = steplog.StepLog(tmp_path / "steps.jsonl")
    log.append(steplog.StepRecord(1, "implementation", "approved",
                                  expected_files=["src/app.cpp", "tests/a_test.cpp"]))
    assert test_selection.select_tests(model, log, "u:target") == ("tests/a_test.cpp",)


def test_several_tests_are_stable_and_de_duplicated() -> None:
    model = selection_model()
    records = [
        steplog.StepRecord(1, "implementation", "approved",
                           selected_tests=["tests/z_test.cpp", "tests/a_test.cpp", "tests/z_test.cpp"]),
        steplog.StepRecord(2, "implementation", "approved", files=["tests/a_test.cpp"]),
    ]
    assert test_selection.select_tests(model, records, "u:target") == (
        "tests/z_test.cpp", "tests/a_test.cpp")


def test_unknown_or_unreached_target_has_no_selection() -> None:
    model = selection_model()
    records = [steplog.StepRecord(1, "implementation", "approved", files=["tests/other_test.cpp"])]
    assert test_selection.select_tests(model, records, "u:none") == ()
    assert test_selection.select_tests(model, records, "u:missing") == ()
