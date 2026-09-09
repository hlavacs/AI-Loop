"""The step panel, the Call View canvas and the step controller against the Tk stub, with a fake runner."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

from icoda_core import persistence, prompt, response, steps, views
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind
from icoda_gui import call_view, step_controller, step_panel


def model_with_calls() -> DerivedModel:
    model = DerivedModel("/p")
    model.files["m.cpp"] = FileInfo("m.cpp")
    for usr, name in (("u:main", "main"), ("u:a", "a"), ("u:b", "b")):
        model.add_entity(Entity(usr, Kind.FUNCTION, name, name, "m.cpp", 1, signature=f"int {name}()", brief="hi"))
    model.add_edge(Edge(EdgeKind.CALLS, "u:main", "u:a", "m.cpp", 2))
    model.add_edge(Edge(EdgeKind.CALLS, "u:a", "u:b", "m.cpp", 3))
    return model


def fake_proposal(tmp_path: Path, ok: bool = True) -> steps.Proposal:
    model = model_with_calls()
    reply = response.StepResponse("Add b", "Because.", (response.FileChange("m.cpp", "x"),), questions=("Why?",))
    delta = steps.compute_delta(DerivedModel("/p"), model, ["m.cpp"])
    proposal = steps.Proposal(1, prompt.StepRequest(prompt.ARCHITECTURE, 1, "add b"), tmp_path, attempts=2,
                              response=reply, build=steps.BuildResult(True, "built"), model=model, delta=delta)
    if not ok:
        proposal.build, proposal.error = steps.BuildResult(False, "error: boom"), "the proposal does not build"
    return proposal


def test_panel_shows_proposals_and_requests(tmp_path: Path) -> None:
    pressed: list[str] = []
    panel = step_panel.StepPanel(tk.Tk(), pressed.append)
    assert panel.title_var.get() == "No proposal" and panel.request().phase == prompt.ARCHITECTURE
    panel.phase_var.set(prompt.IMPLEMENTATION)
    panel.request_var.set("  implement a ")
    assert panel.request() == prompt.StepRequest(prompt.IMPLEMENTATION, 0, "implement a", max_entities=5)
    panel.show(fake_proposal(tmp_path))
    assert panel.title_var.get() == "Step 1: Add b  (attempt 2)"
    assert "Questions:\n- Why?" in panel.rationale.get("1.0", "end")
    assert "3 entities added" in panel.details.get("1.0", "end")
    panel.show(fake_proposal(tmp_path, ok=False))
    assert "no usable proposal" in panel.title_var.get() and "boom" in panel.details.get("1.0", "end")
    panel._pressed("undo")()
    assert pressed[-1] == "undo"


def test_call_view_canvas_follows_root_selection_and_proposals(tmp_path: Path, monkeypatch: Any) -> None:
    opened: list[tuple[str, int]] = []
    canvas = call_view.CallViewCanvas(tk.Tk(), lambda file, line: opened.append((file, line)))
    model = model_with_calls()
    canvas.show(model)
    assert canvas.root_usr == "u:main" and canvas.layout is not None and len(canvas.layout.nodes) == 3
    assert canvas.root_var.get() == "main" and canvas.scale > 0
    fit_scale = canvas.fit_scale

    class Pointer:
        def __init__(self, x: int, y: int, num: int = 1, delta: int = 0) -> None:
            self.x, self.y, self.num, self.delta = x, y, num, delta

    before_point = ((300 - canvas.offset[0]) / canvas.scale, (200 - canvas.offset[1]) / canvas.scale)
    assert canvas.on_wheel(Pointer(300, 200, delta=120)) == "break"
    after_point = ((300 - canvas.offset[0]) / canvas.scale, (200 - canvas.offset[1]) / canvas.scale)
    assert abs(before_point[0] - after_point[0]) < 1e-6 and abs(before_point[1] - after_point[1]) < 1e-6
    assert canvas.scale > fit_scale
    assert {"zoom-out", "fit", "reset", "zoom-in"} <= set(canvas.toolbar_controls)
    canvas.reset_zoom()
    assert abs(canvas.scale - max(canvas.fit_scale, 1.0)) < 1e-6
    canvas.fit()
    canvas.zoom(0.8)
    assert abs(canvas.scale - canvas.fit_scale) < 1e-6
    canvas.set_root("u:a")
    assert set(canvas.layout.nodes) == {"u:a", "u:b"}
    canvas.depth_var.set(1)
    canvas.callers_var.set(True)
    canvas.controls_changed()
    assert set(canvas.layout.nodes) == {"u:a", "u:main"} and canvas.root_var.get() == "a (callers)"
    canvas.show_proposal(model, fake_proposal(tmp_path).delta)
    assert canvas.added == {"u:main", "u:a", "u:b"} and canvas.root_usr == "u:main"
    canvas.callers_var.set(False)
    canvas.depth_var.set(3)
    canvas.controls_changed()
    canvas.select("u:b")
    assert canvas.layout.path == {"u:main", "u:a", "u:b"}
    monkeypatch.setattr(canvas, "node_at", lambda _x, _y: "u:a")
    before_offset = canvas.offset
    canvas.on_press(Pointer(100, 100))
    canvas.on_drag(Pointer(122, 114))
    canvas.on_release(Pointer(122, 114))
    assert canvas.offset == (before_offset[0] + 22, before_offset[1] + 14)
    assert canvas.dragged and canvas.selected == "u:b"
    canvas.on_press(Pointer(122, 114, num=2))
    canvas.on_release(Pointer(122, 114, num=2))
    assert canvas.selected == "u:b"


class FakeRunner:
    def __init__(self, root: Path, config: Any, provider: str, binary: str, model: str, *, progress: Any) -> None:
        self.root, self.provider_id, self.binary, self.model_id = root, provider, binary, model
        self.progress = progress
        self.calls: list[str] = []
        self.dirty = False
        self.proposal: steps.Proposal | None = None

    def prepare(self) -> None:
        self.calls.append("prepare")
        if self.dirty:
            raise steps.DirtyTree("uncommitted changes in the project")

    def propose(self, request: prompt.StepRequest) -> steps.Proposal:
        self.calls.append(f"propose:{request.request}:{';'.join(request.constraints)}")
        self.progress("working")
        assert self.proposal is not None
        return self.proposal

    def approve(self, proposal: steps.Proposal) -> Any:
        self.calls.append("approve")
        title = proposal.response.title if proposal.response else ""
        return steps.StepRecord(1, "architecture", "approved", title=title)

    def reject(self, proposal: steps.Proposal, reason: str) -> Any:
        self.calls.append(f"reject:{reason}")
        return steps.StepRecord(1, "architecture", "rejected", reason=reason)


class Window:
    """The parts of the main window the controller talks to."""

    def __init__(self, tmp_path: Path) -> None:
        self.project = tmp_path
        self.config = persistence.UserConfig()
        self.root = tk.Tk()
        self.status = tk.StringVar(value="")
        self.panel = step_panel.StepPanel(self.root, lambda action: None)
        self.call_view = call_view.CallViewCanvas(self.root, lambda file, line: None)
        self.reloads = 0
        self.shown_call_view = 0

    class _Field:
        @staticmethod
        def selection() -> Any:
            from icoda_gui.provider_field import ProviderSelection
            return ProviderSelection("claude", "claude", "m")

    provider_field = _Field()

    def run_async(self, work: Any, done: Any) -> None:
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001
            result = exc
        done(result)

    def run_on_ui(self, func: Any, *args: Any) -> None:
        func(*args)

    def reload(self) -> None:
        self.reloads += 1

    def show_call_view(self) -> None:
        self.shown_call_view += 1


def test_controller_runs_the_protocol_through_the_window(tmp_path: Path, monkeypatch: Any) -> None:
    window = Window(tmp_path)
    runners: list[FakeRunner] = []

    def factory(*args: Any, **kwargs: Any) -> FakeRunner:
        runner = FakeRunner(*args, **kwargs)
        runner.proposal = fake_proposal(tmp_path)
        runners.append(runner)
        return runner

    controller = step_controller.StepController(window, factory)
    window.panel.request_var.set("add b")
    controller.action("propose")
    runner = runners[0]
    assert runner.calls == ["prepare", "propose:add b:"] and (runner.binary, runner.model_id) == ("claude", "m")
    assert window.panel.proposal is runner.proposal and window.shown_call_view == 1
    assert "proposal ready" in window.status.get() and window.call_view.added == {"u:main", "u:a", "u:b"}

    monkeypatch.setattr(step_controller.simpledialog, "askstring", lambda *a, **k: "keep it small; one module")
    controller.action("adapt")
    assert runner.calls[-1] == "propose:add b:keep it small;one module"
    controller.action("approve")
    assert runner.calls[-1] == "approve" and window.reloads == 1 and window.panel.proposal is None
    assert "approved and committed: Add b" in window.status.get()

    controller.action("propose")
    monkeypatch.setattr(step_controller.simpledialog, "askstring", lambda *a, **k: "wrong module")
    controller.action("reject")
    assert runner.calls[-1] == "reject:wrong module" and "rejected" in window.status.get()

    runner.dirty = True
    controller.action("propose")
    assert "uncommitted changes" in window.status.get() and len(runners) == 1
    assert views.default_root(model_with_calls()) == "u:main"


def test_failures_are_shortened_for_the_dialog_and_shown_in_full_in_the_panel(tmp_path: Path) -> None:
    from icoda_gui import dialogs

    long = "Claude Code failed (1): first line\n" + "\n".join(f"line {i}" for i in range(2, 60))
    short = dialogs.shorten(long)
    assert short.startswith("Claude Code failed (1): first line") and short.count("\n") <= 12
    assert "full text is in the step panel" in short and "line 59" not in short
    assert dialogs.shorten("all good") == "all good"
    panel = step_panel.StepPanel(tk.Tk(), lambda action: None)
    panel.show_failure(long)
    assert panel.title_var.get() == "Step failed — Claude Code failed (1): first line"
    assert "line 59" in panel.details.get("1.0", "end")
