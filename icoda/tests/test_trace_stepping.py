"""Debugger-style navigation preserves recorded invocations and thread stacks."""

import pytest

from icoda_core.call_trace import CallEvent, CallPlayback, CallTrace, EventKind
from icoda_core.model import DerivedModel, Entity, Kind


def playback(*rows):
    entities = {name: Entity(name, Kind.FUNCTION, name, name, "main.cpp", 1)
                for _, _, name, _ in rows if name != "unknown"}
    events = tuple(CallEvent(index, EventKind(kind), index, thread, depth, name,
                             None, name, "app", entities.get(name))
                   for index, (kind, depth, name, thread) in enumerate(rows))
    return CallPlayback(CallTrace(events))


@pytest.fixture
def nested():
    return playback(
        ("E", 0, "main", "a"), ("E", 1, "work", "a"),
        ("E", 2, "helper", "a"), ("X", 2, "helper", "a"),
        ("X", 1, "work", "a"), ("E", 1, "second", "a"),
        ("X", 1, "second", "a"), ("X", 0, "main", "a"))


def test_into_visits_calls_and_returns(nested):
    selected = []
    while nested.can_step("into"):
        entity = nested.step_into()
        selected.append(entity.usr if entity else None)
    assert selected == ["main", "work", "helper", "work", "main", "second", "main", None]
    assert "event 8 of 8" in nested.status and "returned from main" in nested.status
    assert nested.current_entity is None
    assert not any(nested.can_step(mode) for mode in ("into", "over", "out"))


def test_over_skips_nested_calls_and_out_returns_to_caller(nested):
    assert nested.step_over().usr == "main"
    assert nested.step_over().usr == "main"
    assert "event 5 of 8" in nested.status
    assert nested.step_into().usr == "second"
    assert nested.step_out().usr == "main"
    assert nested.step_out() is None
    assert nested.current_entity is None
    nested.reset()
    for _ in range(3):
        nested.step_into()
    assert nested.step_out().usr == "work"
    assert nested.step_out().usr == "main"


def test_recursion_and_repeated_calls_are_individual_steps():
    trace = playback(("E", 0, "f", "a"), ("E", 1, "f", "a"),
                     ("X", 1, "f", "a"), ("E", 1, "f", "a"),
                     ("X", 1, "f", "a"), ("X", 0, "f", "a"))
    assert trace.total == 1  # The existing grouped navigation remains available.
    assert trace.next_call().usr == "f"
    assert trace.current_repeat_count == 3
    assert trace.step_into().usr == "f"
    assert trace.current_repeat_count == 1
    assert "depth 1" in trace.status
    assert trace.step_out().usr == "f"
    assert "event 3 of 6" in trace.status and "depth 0" in trace.status
    assert trace.step_into().usr == "f"
    assert "event 4 of 6" in trace.status
    assert trace.step_out().usr == "f"
    assert trace.step_out() is None


def test_steps_stay_on_selected_thread():
    trace = playback(("E", 0, "main", "a"), ("E", 0, "main", "b"),
                     ("E", 1, "work", "a"), ("E", 1, "work", "b"),
                     ("X", 1, "work", "b"), ("X", 1, "work", "a"),
                     ("X", 0, "main", "b"), ("X", 0, "main", "a"))
    trace.step_into()
    assert trace.step_into().usr == "work"
    assert "event 3 of 8" in trace.status and "thread a" in trace.status
    assert trace.step_out().usr == "main"
    assert "event 6 of 8" in trace.status
    assert trace.step_out() is None
    assert "event 8 of 8" in trace.status


def test_unresolved_frames_allow_return_to_known_ancestor():
    trace = playback(("E", 0, "main", "a"), ("E", 1, "unknown", "a"),
                     ("E", 2, "helper", "a"), ("X", 2, "helper", "a"),
                     ("X", 1, "unknown", "a"), ("X", 0, "main", "a"))
    trace.step_into()
    assert trace.step_into().usr == "helper"
    assert trace.step_out().usr == "main"
    assert "event 4 of 6" in trace.status
    trace.reset()
    trace.step_into()
    assert trace.step_over().usr == "main"
    assert "event 5 of 6" in trace.status


@pytest.mark.parametrize("exit_row", [None, ("X", 1, "wrong", "a")])
def test_missing_or_mismatched_return_is_not_invented(exit_row):
    rows = [("E", 0, "main", "a"), ("E", 1, "work", "a")]
    if exit_row:
        rows.append(exit_row)
    trace = playback(*rows)
    trace.step_into()
    assert not trace.can_step("out") and not trace.can_step("over")
    trace.step_into()
    status = trace.status
    assert trace.step_out() is None and trace.current_entity.usr == "work"
    assert trace.status == status


def test_group_navigation_and_reset_after_debugger_steps(nested):
    nested.step_into()
    nested.step_over()
    assert nested.next_call().usr == "second"  # Do not replay calls already stepped over.
    assert nested.previous_call().usr == "helper"
    assert nested.step_out().usr == "work"
    assert nested.seek_first_call("work").usr == "work"
    assert nested.step_into().usr == "helper"
    nested.reset()
    assert nested.position == 0 and nested.current_entity is None
    assert nested.status == "call 0 of 4"
    assert nested.can_step("into") and not nested.can_step("out")


def test_buttons_update_graph_source_and_availability(app_module, tmp_path, nested, monkeypatch):
    from icoda_gui.call_view import CallViewCanvas

    selected, focused = [], []
    view = CallViewCanvas(app_module.tk.Tk(), lambda *_: None,
                          select_node=selected.append, focus_node=focused.append)
    model = DerivedModel(str(tmp_path))
    for entity in nested.entities:
        model.add_entity(entity)
    view.show(model, "main")
    view.entry_usr = "main"
    states = {}
    for label in ("Step Into", "Step Over", "Step Out"):
        assert view.playback_buttons[label].kwargs["state"] == app_module.tk.DISABLED
        monkeypatch.setattr(view.playback_buttons[label], "state",
                            lambda value, key=label: states.__setitem__(key, value))
    view.set_playback(nested)
    assert states == {"Step Into": ["!disabled"], "Step Over": ["!disabled"], "Step Out": ["disabled"]}
    view.playback_buttons["Step Into"].kwargs["command"]()
    assert view.selected == selected[-1] == focused[-1] == "main"
    assert view.root_usr == "main"
    view.playback_buttons["Step Over"].kwargs["command"]()
    assert "event 5 of 8" in view.playback_status_var.get()
    view.playback_buttons["Step Into"].kwargs["command"]()
    assert view.selected == selected[-1] == "second"
    view.playback_buttons["Step Out"].kwargs["command"]()
    assert view.selected == selected[-1] == "main"
    view.step_out()
    assert view.selected is None and focused[-1] is None
    assert all(value == ["disabled"] for value in states.values())
    view.reset_playback()
    assert states["Step Into"] == ["!disabled"]
    view.set_playback(CallPlayback(CallTrace(())))
    for action in (view.step_into, view.step_over, view.step_out):
        action()
    assert all(value == ["disabled"] for value in states.values())
    assert view.selected is None
