"""Few-line implementation grouping and its per-entity test-evidence gate."""

from __future__ import annotations

from icoda_core import grouping, rules, specification
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, Kind
from icoda_core.prompt import IMPLEMENTATION, StepRequest


def _accessor_model(*, split_classes: bool = False, with_test: bool = False) -> DerivedModel:
    model = DerivedModel("/not-returned")
    model.add_entity(Entity("class:widget", Kind.CLASS, "Widget", "app::Widget", "src/widget.cpp", 1))
    model.add_entity(Entity("class:other", Kind.CLASS, "Other", "app::Other", "src/widget.cpp", 2))
    model.add_entity(Entity(
        "method:get", Kind.METHOD, "get_value", "app::Widget::get_value", "src/widget.cpp", 10,
        end_line=13, parent="class:widget", signature="int get_value()", status="stub",
    ))
    owner = "class:other" if split_classes else "class:widget"
    qualified = "app::Other::set_value" if split_classes else "app::Widget::set_value"
    model.add_entity(Entity(
        "method:set", Kind.METHOD, "set_value", qualified, "src/widget.cpp", 20,
        end_line=25, parent=owner, signature="void set_value(int value)", status="stub",
    ))
    if with_test:
        model.add_entity(Entity(
            "test:accessors", Kind.FUNCTION, "test_accessors", "test_accessors",
            "tests/widget_test.cpp", 1, end_line=5, signature="void test_accessors()",
        ))
        model.add_edge(Edge(EdgeKind.CALLS, "test:accessors", "method:get"))
        model.add_edge(Edge(EdgeKind.CALLS, "test:accessors", "method:set"))
    return model


def test_accepted_accessor_group_names_every_entity_and_requires_evidence_for_each() -> None:
    profile = specification.default_code_profile()
    model = _accessor_model()

    decision = grouping.derive(("method:get", "method:set"), model, profile)

    assert tuple(entity.qualified_name for entity in decision.entities) == (
        "app::Widget::get_value", "app::Widget::set_value")
    assert decision.refusal_reason == "" and decision.total_lines == 10

    request = StepRequest(
        IMPLEMENTATION, 3, target="method:get", batch=("method:get", "method:set"), grouped=True)
    refused = rules.group_test_coverage(model, (), request)
    assert refused.refusal_reason == (
        "group test coverage requires recorded evidence for every entity; missing: "
        "app::Widget::get_value, app::Widget::set_value")

    covered_model = _accessor_model(with_test=True)
    accepted = rules.group_test_coverage(
        covered_model, (), request, files=("tests/widget_test.cpp",))
    assert accepted.complete and accepted.covered == ("method:get", "method:set")


def test_cross_class_accessor_group_is_refused_with_exact_reason() -> None:
    decision = grouping.derive(
        ("method:get", "method:set"), _accessor_model(split_classes=True),
        specification.default_code_profile(),
    )

    assert tuple(entity.usr for entity in decision.entities) == ("method:get",)
    assert decision.refusal_reason == (
        "cannot group app::Other::set_value with app::Widget::get_value: "
        "entities have different enclosing classes")
