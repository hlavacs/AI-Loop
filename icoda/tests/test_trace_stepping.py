"""Debugger-style controls navigate the same recorded calls as Next Call."""

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
        ("E", 2, "peer", "a"), ("X", 2, "peer", "a"),
        ("X", 1, "work", "a"), ("E", 1, "second", "a"),
        ("X", 1, "second", "a"), ("X", 0, "main", "a"))


def test_into_matches_next_call_and_never_stops_on_returns(nested):
    def visit(action):
        visited = []
        while (entity := action()) is not None:
            visited.append((entity.usr, nested.position, nested.status))
        return visited

    expected = visit(nested.next_call)
    nested.reset()
    assert visit(nested.step_into) == expected
    assert [usr for usr, _, _ in expected] == ["main", "work", "helper", "peer", "second"]
    assert nested.current_entity.usr == "second"
    assert not any(nested.can_step(mode) for mode in ("into", "over", "out"))


def test_over_skips_children_and_out_skips_siblings(nested):
    assert nested.step_over().usr == "main"
    assert nested.step_into().usr == "work"
    assert nested.step_over().usr == "second"
    assert nested.status == "call 5 of 5: second"
    nested.seek_first_call("helper")
    assert nested.step_over().usr == "peer"
    assert nested.step_over().usr == "second"
    nested.seek_first_call("helper")
    assert nested.step_out().usr == "second"
    assert nested.step_out() is None
    assert nested.current_entity.usr == "second"


def test_into_preserves_repeat_counts_caller_counts_and_status():
    trace = playback(("E", 0, "main", "a"), ("E", 1, "f", "a"),
                     ("E", 2, "f", "a"), ("X", 2, "f", "a"),
                     ("X", 1, "f", "a"), ("E", 1, "f", "a"),
                     ("X", 1, "f", "a"), ("E", 1, "next", "a"))
    trace.next_call()
    trace.next_call()
    expected = (trace.position, trace.current_repeat_count, trace.current_caller_counts, trace.status)
    trace.reset()
    trace.step_into()
    assert trace.step_into().usr == "f"
    assert (trace.position, trace.current_repeat_count, trace.current_caller_counts, trace.status) == expected
    assert trace.current_repeat_count == 3
    assert trace.step_into().usr == "next"


def test_over_and_out_keep_repeat_highlights():
    trace = playback(("E", 0, "main", "a"), ("E", 1, "work", "a"),
                     ("E", 2, "helper", "a"), ("X", 2, "helper", "a"),
                     ("X", 1, "work", "a"), ("E", 1, "next", "a"),
                     ("X", 1, "next", "a"), ("E", 1, "next", "a"))
    for method, start in ((trace.step_over, "work"), (trace.step_out, "helper")):
        trace.seek_first_call(start)
        assert method().usr == "next"
        assert trace.current_repeat_count == 2
        assert trace.current_caller_counts == {"main": 2}
        assert trace.status.endswith("next — 2 consecutive calls")


def test_into_follows_global_next_call_order_but_depth_steps_stay_on_thread():
    trace = playback(("E", 0, "main", "a"), ("E", 1, "work", "a"),
                     ("E", 2, "helper", "a"), ("E", 0, "other", "b"),
                     ("X", 0, "other", "b"), ("X", 2, "helper", "a"),
                     ("X", 1, "work", "a"), ("E", 1, "next", "a"))
    trace.seek_first_call("helper")
    assert trace.step_into().usr == "other"
    trace.seek_first_call("work")
    assert trace.step_over().usr == "next"
    trace.seek_first_call("helper")
    assert trace.step_out().usr == "next"


def test_recursion_uses_current_invocations_return():
    trace = playback(("E", 0, "main", "a"), ("E", 1, "f", "a"),
                     ("E", 2, "bridge", "a"), ("E", 3, "f", "a"),
                     ("E", 4, "child", "a"), ("X", 4, "child", "a"),
                     ("X", 3, "f", "a"), ("X", 2, "bridge", "a"),
                     ("E", 2, "after", "a"), ("X", 2, "after", "a"),
                     ("X", 1, "f", "a"), ("E", 1, "next", "a"))
    trace.seek_first_call("bridge")
    assert trace.step_into().usr == "f"
    assert trace.step_out().usr == "after"
    trace.seek_first_call("f")
    assert trace.step_over().usr == "next"


def test_unresolved_calls_are_skipped():
    trace = playback(("E", 0, "main", "a"), ("E", 1, "unknown", "a"),
                     ("E", 2, "helper", "a"), ("X", 2, "helper", "a"),
                     ("X", 1, "unknown", "a"), ("E", 1, "next", "a"))
    trace.step_into()
    assert trace.step_into().usr == "helper"
    assert trace.step_out().usr == "next"


@pytest.mark.parametrize("exit_row", [None, ("X", 1, "wrong", "a")])
def test_missing_or_mismatched_return_does_not_invent_a_depth_step(exit_row):
    rows = [("E", 0, "main", "a"), ("E", 1, "work", "a")]
    if exit_row:
        rows.append(exit_row)
    rows.append(("E", 0, "later", "a"))
    trace = playback(*rows)
    trace.seek_first_call("work")
    status = trace.status
    assert not trace.can_step("out") and not trace.can_step("over")
    assert trace.step_out() is None and trace.step_over() is None
    assert trace.status == status and trace.current_entity.usr == "work"
    assert trace.step_into().usr == "later"


def test_group_navigation_and_reset_after_depth_steps(nested):
    nested.seek_first_call("work")
    nested.step_over()
    assert nested.next_call() is None
    assert nested.previous_call().usr == "peer"
    assert nested.step_into().usr == "second"
    nested.reset()
    assert nested.position == 0 and nested.current_entity is None
    assert nested.status == "call 0 of 5"
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
    view.step_into()
    view.playback_buttons["Step Over"].kwargs["command"]()
    assert view.selected == selected[-1] == "second"
    assert view.playback_status_var.get() == "call 5 of 5: second"
    assert all(value == ["disabled"] for value in states.values())
    view.step_into()  # Like Next Call, exhaustion keeps the last selected call.
    assert view.selected == "second"
    view.seek_first_call("helper")
    view.playback_buttons["Step Out"].kwargs["command"]()
    assert view.selected == selected[-1] == "second"
    view.reset_playback()
    assert states["Step Into"] == ["!disabled"] and view.selected is None
    view.set_playback(CallPlayback(CallTrace(())))
    for action in (view.step_into, view.step_over, view.step_out):
        action()
    assert all(value == ["disabled"] for value in states.values())
    assert view.selected is None
