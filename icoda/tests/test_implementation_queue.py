"""The implementation queue is deterministic and respects call dependencies."""

from __future__ import annotations

import json
from pathlib import Path

from icoda_core import implementation_queue, persistence
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind


def function(usr: str, name: str, *, status: str = "stub", definition: bool = True) -> Entity:
    return Entity(usr, Kind.FUNCTION, name, name, "functions.cpp", 1, signature=f"void {name}()",
                  status=status, is_definition=definition)


def test_bottom_up_queue_puts_each_callee_before_its_caller() -> None:
    model = DerivedModel("/p")
    for entity in (function("caller", "a_caller"), function("middle", "m_middle"),
                   function("leaf", "z_leaf"), function("done", "done", status="implemented")):
        model.add_entity(entity)
    model.add_edge(Edge(EdgeKind.CALLS, "caller", "middle"))
    model.add_edge(Edge(EdgeKind.CALLS, "middle", "leaf"))
    model.add_edge(Edge(EdgeKind.CALLS, "caller", "done"))
    assert implementation_queue.build(model) == ("leaf", "middle", "caller")


def test_independent_functions_use_the_documented_stable_tie_break() -> None:
    model = DerivedModel("/p")
    model.add_entity(function("z-usr", "zeta"))
    model.add_entity(function("a-usr", "alpha"))
    model.add_entity(function("declared", "middle", status="implemented", definition=False))
    assert implementation_queue.build(model) == ("a-usr", "declared", "z-usr")


def test_recursive_cycle_is_one_component_with_stably_sorted_members() -> None:
    model = DerivedModel("/p")
    for entity in (function("cycle-z", "z_cycle"), function("cycle-a", "a_cycle"),
                   function("caller", "caller")):
        model.add_entity(entity)
    model.add_edge(Edge(EdgeKind.CALLS, "cycle-z", "cycle-a"))
    model.add_edge(Edge(EdgeKind.CALLS, "cycle-a", "cycle-z"))
    model.add_edge(Edge(EdgeKind.CALLS, "caller", "cycle-z"))
    assert implementation_queue.build(model) == ("cycle-a", "cycle-z", "caller")


def test_next_batch_starts_at_head_and_honours_limit_without_clang() -> None:
    model = DerivedModel("/p")
    for usr in ("head", "second", "third"):
        model.add_entity(function(usr, usr))
    state = persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("head", "second", "third"), 0)

    assert implementation_queue.next_batch(model, state, 1) == ["head"]
    assert implementation_queue.next_batch(model, state, 2) == ["head", "second"]
    assert implementation_queue.next_batch(model, state, 20) == ["head", "second", "third"]


def test_next_batch_stops_before_a_target_with_an_outside_dependency() -> None:
    model = DerivedModel("/p")
    for usr in ("head", "blocked", "dependency", "later"):
        model.add_entity(function(usr, usr))
    model.add_edge(Edge(EdgeKind.CALLS, "blocked", "dependency"))
    state = persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("head", "blocked", "dependency", "later"), 0)

    assert implementation_queue.next_batch(model, state, 4) == ["head"]


def test_next_batch_accepts_a_dependency_already_inside_and_handles_exhaustion() -> None:
    model = DerivedModel("/p")
    model.add_entity(function("leaf", "leaf"))
    model.add_entity(function("caller", "caller"))
    model.add_edge(Edge(EdgeKind.CALLS, "caller", "leaf"))
    model.add_edge(Edge(EdgeKind.CALLS, "caller", "caller"))
    active = persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("leaf", "caller"), 0)
    exhausted = persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("leaf", "caller"), 2)

    assert implementation_queue.next_batch(model, active, 2) == ["leaf", "caller"]
    assert implementation_queue.next_batch(model, exhausted, 2) == []
    assert implementation_queue.next_batch(
        model, persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION), 2) == []


def _scope_fixture() -> tuple[DerivedModel, persistence.ProjectState]:
    model = DerivedModel("/p")
    for file in ("src/widget.cpp", "src/other.cpp", "plugin/adapter.cpp"):
        model.files[file] = FileInfo(file)
    model.add_entity(Entity("class-a", Kind.CLASS, "A", "A", "src/widget.cpp", 1))
    model.add_entity(Entity("class-b", Kind.CLASS, "B", "B", "src/other.cpp", 1))
    entities = (
        Entity("a-leaf", Kind.METHOD, "leaf", "A::leaf", "src/widget.cpp", 2,
               parent="class-a", status="stub"),
        Entity("done", Kind.METHOD, "done", "A::done", "src/widget.cpp", 3,
               parent="class-a", status="implemented"),
        Entity("a-caller", Kind.METHOD, "caller", "A::caller", "src/widget.cpp", 4,
               parent="class-a", status="stub"),
        Entity("b-leaf", Kind.METHOD, "leaf", "B::leaf", "src/other.cpp", 2,
               parent="class-b", status="stub"),
        Entity("free", Kind.FUNCTION, "free", "free", "src/free.cpp", 1, status="stub"),
        Entity("plugin", Kind.FUNCTION, "plugin", "plugin", "plugin/adapter.cpp", 1, status="stub"),
    )
    for entity in entities:
        model.add_entity(entity)
    model.files["src/free.cpp"] = FileInfo("src/free.cpp")
    model.add_edge(Edge(EdgeKind.CALLS, "a-caller", "a-leaf"))
    model.add_edge(Edge(EdgeKind.CALLS, "free", "a-leaf"))
    queue = ("a-leaf", "done", "a-caller", "b-leaf", "free", "plugin")
    return model, persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION, queue, 0)


def test_scope_expansions_return_exact_pending_sets() -> None:
    model, state = _scope_fixture()

    assert set(implementation_queue.scope_targets(
        model, state, implementation_queue.Scope.SINGLE_ENTITY)) == {"a-leaf"}
    assert set(implementation_queue.scope_targets(
        model, state, implementation_queue.Scope.ENCLOSING_CLASS)) == {"a-leaf", "a-caller"}
    assert set(implementation_queue.scope_targets(
        model, state, implementation_queue.Scope.ENCLOSING_CLUSTER)) == {
            "a-leaf", "a-caller", "b-leaf", "free"
        }
    assert set(implementation_queue.scope_targets(
        model, state, implementation_queue.Scope.ALL_REMAINING_LEAVES)) == {
            "a-leaf", "b-leaf", "plugin"
        }


def test_scope_degenerate_cases_are_deterministic() -> None:
    model, state = _scope_fixture()
    free_state = implementation_queue.override_target(model, state, "free")
    done_state = persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("done",), 0)
    empty_state = persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, state.implementation_queue,
        len(state.implementation_queue))

    assert implementation_queue.scope_targets(
        model, free_state, implementation_queue.Scope.ENCLOSING_CLASS) == ("free",)
    assert implementation_queue.scope_targets(
        model, empty_state, implementation_queue.Scope.ALL_REMAINING_LEAVES) == ()
    assert implementation_queue.scope_targets(
        model, done_state, implementation_queue.Scope.ENCLOSING_CLASS) == ()


def test_scope_selection_groups_exact_targets_and_batch_size_remains_a_limit() -> None:
    model, state = _scope_fixture()
    selected = implementation_queue.select_scope(
        model, state, implementation_queue.Scope.ENCLOSING_CLASS)

    assert selected.implementation_scope == "enclosing_class"
    assert selected.implementation_queue[:3] == ("a-leaf", "a-caller", "done")
    assert implementation_queue.next_batch(model, selected, 1) == ["a-leaf"]
    assert implementation_queue.next_batch(model, selected, 20) == ["a-leaf", "a-caller"]


def test_override_moves_and_returns_the_exact_developer_selected_target() -> None:
    model, state = _scope_fixture()
    overridden = implementation_queue.override_target(model, state, "plugin")

    assert overridden.implementation_override == "plugin"
    assert overridden.implementation_queue == (
        "plugin", "a-leaf", "done", "a-caller", "b-leaf", "free")
    assert implementation_queue.target_usr(overridden) == "plugin"
    assert implementation_queue.next_batch(model, overridden, 1) == ["plugin"]


def test_state_without_scope_or_override_loads_with_compatible_defaults(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.state_path.parent.mkdir(parents=True)
    store.state_path.write_text(json.dumps({
        "phase": "implementation",
        "implementation_queue": ["head", "second", "third"],
        "implementation_cursor": 0,
        "implementation_batch_size": 3,
    }), encoding="utf-8")

    state = store.load_state()
    assert state.implementation_scope == implementation_queue.Scope.QUEUE_ORDER.value
    assert state.implementation_override == ""
    assert state.implementation_batch_size == 3
    model = DerivedModel("/p")
    for usr in state.implementation_queue:
        model.add_entity(function(usr, usr))
    assert implementation_queue.next_batch(model, state, state.implementation_batch_size) == [
        "head", "second", "third"]
    store.save_state(state)
    assert store.load_state() == state
