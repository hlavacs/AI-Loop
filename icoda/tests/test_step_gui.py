"""The step panel, the Call View canvas and the step controller against the Tk stub, with a fake runner."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from typing import Any, cast

import pytest

from icoda_core import (
    adaptation,
    grouping,
    implementation_queue,
    persistence,
    prompt,
    response,
    specification,
    steplog,
    steps,
    views,
)
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind
from icoda_gui import call_view, graph_canvas, step_controller, step_panel


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
    entities = (adaptation.EntitySummary("app::b", "function", "m.cpp", "int b()", ("R-1",)),)
    reply = response.StepResponse(
        "Add b", "Because.", (response.FileChange("m.cpp", "x"),), entities=entities, questions=("Why?",))
    delta = steps.compute_delta(DerivedModel("/p"), model, ["m.cpp"])
    proposal = steps.Proposal(1, prompt.StepRequest(prompt.ARCHITECTURE, 1, "add b"), tmp_path, attempts=2,
                              response=reply, build=steps.BuildResult(True, "built"),
                              test=steps.TestResult(True, "tested"), model=model, delta=delta,
                              source_diff="diff --git a/m.cpp b/m.cpp\n--- a/m.cpp\n+++ b/m.cpp\n@@ -1 +1 @@\n-old\n+new")
    if not ok:
        proposal.build, proposal.test = steps.BuildResult(False, "error: boom"), steps.TestResult()
        proposal.model, proposal.delta, proposal.error = None, None, "the proposal does not build"
    return proposal


def fake_approach() -> steps.Approach:
    return steps.Approach(
        1, prompt.StepRequest(prompt.IMPLEMENTATION, 1, target="u:b"), "u:b", attempts=1,
        plan="Use std::ranges::find; approximately 6 lines; no allocations.", entities=("b",),
        files=("m.cpp", "tests/m_test.cpp"), prompt_text="approach prompt",
    )


def test_review_details_collapse_without_losing_edits_and_reopen_for_results(tmp_path):
    panel = step_panel.StepPanel(tk.Tk(), lambda _action: None)
    assert not panel.details_visible
    panel.show(fake_proposal(tmp_path))
    assert panel.details_visible
    panel.entity_summary.insert("end", "Keep this manual summary edit")
    panel.toggle_details()
    assert not panel.details_visible
    panel.toggle_details()
    assert "Keep this manual summary edit" in panel.edited_entity_summary()
    panel.show(None)
    assert not panel.details_visible
    panel.show_approach(fake_approach())
    assert panel.details_visible
    panel.toggle_details()
    panel.show_failure("Build failed: missing include")
    assert panel.details_visible and "missing include" in panel.details.get("1.0", "end")


def test_panel_shows_proposals_and_requests(tmp_path: Path) -> None:
    pressed: list[str] = []
    panel = step_panel.StepPanel(tk.Tk(), pressed.append)
    assert panel.title_var.get() == "No proposal" and panel.request().phase == "specification"
    assert "values" not in cast(Any, panel.phase_label).kwargs  # a label, not the old free-choice phase combo
    panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
    panel.request_var.set("  implement a ")
    assert panel.request() == prompt.StepRequest(prompt.IMPLEMENTATION, 0, "implement a", max_entities=5)
    panel.show(fake_proposal(tmp_path))
    assert panel.title_var.get() == "Step 1: Add b  (attempt 2)"
    assert "Questions:\n- Why?" in panel.rationale.get("1.0", "end")
    assert "3 entities added" in panel.details.get("1.0", "end")
    assert "Architecture entity budget: 3 / 5" in panel.details.get("1.0", "end")
    assert "diff --git a/m.cpp b/m.cpp" in panel.source_diff.get("1.0", "end")
    assert "built" in panel.build_output.get("1.0", "end")
    assert panel.build_status_var.get() == "Build: passed" and panel.test_status_var.get() == "Tests: passed"
    panel.show(fake_proposal(tmp_path, ok=False))
    assert "no usable proposal" in panel.title_var.get() and "proposal does not build" in panel.details.get("1.0",
                                                                                                             "end")
    assert "boom" in panel.build_output.get("1.0", "end")
    assert "Tests did not run" in panel.test_output.get("1.0", "end")
    panel._pressed("undo")()
    assert pressed[-1] == "undo"


def test_panel_distinguishes_build_test_failure_and_not_run(tmp_path: Path) -> None:
    panel = step_panel.StepPanel(tk.Tk(), lambda action: None)
    failed = fake_proposal(tmp_path)
    failed.test, failed.error = steps.TestResult(False, "one test failed"), "the proposal tests fail"
    panel.show(failed)
    assert panel.build_status_var.get() == "Build: passed"
    assert panel.test_status_var.get() == "Tests: failed"
    assert "Full suite (no targeted tests selected)." in panel.test_output.get("1.0", "end")
    assert "one test failed" in panel.test_output.get("1.0", "end")

    not_run = steps.Proposal(2, prompt.StepRequest(prompt.ARCHITECTURE, 2), tmp_path)
    panel.show(not_run)
    assert panel.build_status_var.get() == "Build: not run"
    assert panel.test_status_var.get() == "Tests: not run"
    assert "Tests did not run" in panel.test_output.get("1.0", "end")


def test_panel_disables_structured_adapt_without_a_usable_live_summary(tmp_path: Path) -> None:
    panel = step_panel.StepPanel(tk.Tk(), lambda action: None)
    assert "adapt" not in panel.enabled_actions
    assert panel.edited_entity_summary() == adaptation.NO_USABLE_PROPOSAL

    failed = fake_proposal(tmp_path, ok=False)
    panel.show(failed)
    assert "adapt" not in panel.enabled_actions
    assert panel.edited_entity_summary() == adaptation.NO_USABLE_PROPOSAL

    panel.show_step(steplog.StepRecord(4, "architecture", "approved", title="old proposal"))
    assert "adapt" not in panel.enabled_actions
    assert panel.edited_entity_summary() == adaptation.HISTORICAL_UNAVAILABLE


def test_panel_tests_tab_shows_targeted_tests_and_full_suite_fallback(tmp_path: Path) -> None:
    panel = step_panel.StepPanel(tk.Tk(), lambda action: None)
    targeted = fake_proposal(tmp_path)
    targeted.selected_tests = ("tests/leaf_test.cpp", "app::test_leaf")
    panel.show(targeted)
    shown = panel.test_output.get("1.0", "end")
    assert "Selected tests:\n- tests/leaf_test.cpp\n- app::test_leaf" in shown
    assert "tested" in shown

    legacy_record = steplog.StepRecord.from_dict(
        {"number": 1, "phase": "implementation", "decision": "approved"})
    legacy = fake_proposal(tmp_path)
    legacy.selected_tests = tuple(legacy_record.selected_tests)
    panel.show(legacy)
    assert "Full suite (no targeted tests selected)." in panel.test_output.get("1.0", "end")


def test_panel_delta_shows_rename_pairs(tmp_path: Path) -> None:
    proposal = fake_proposal(tmp_path)
    before = Entity("u:old", Kind.FUNCTION, "old", "app::old", "m.cpp", 1,
                    signature="int old()", body_hash="same")
    after = Entity("u:new", Kind.FUNCTION, "new", "app::new", "m.cpp", 1,
                   signature="int new()", body_hash="same")
    proposal.delta = steps.Delta((), (), (), ("m.cpp",), renamed=(steps.RenamePair(before, after),))
    panel = step_panel.StepPanel(tk.Tk(), lambda action: None)
    panel.show(proposal)
    shown = panel.details.get("1.0", "end")
    assert "1 renamed" in shown and "> function app::old -> app::new int new()" in shown


def test_panel_requires_and_records_signature_confirmation_with_exact_actions(tmp_path: Path) -> None:
    proposal = fake_proposal(tmp_path)
    before, after = DerivedModel("/p"), DerivedModel("/p")
    before.add_entity(Entity("u:b", Kind.FUNCTION, "b", "app::b", "m.cpp", 1,
                             signature="int b()", body_hash="same"))
    after.add_entity(Entity("u:b", Kind.FUNCTION, "b", "app::b", "m.cpp", 1,
                            signature="long b(int value)", body_hash="same"))
    proposal.model = after
    proposal.delta = steps.compute_delta(before, after, ["m.cpp"])
    panel = step_panel.StepPanel(tk.Tk(), lambda action: None)
    panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
    panel.show(proposal)

    assert panel.enabled_actions == {
        "propose", "confirm_signature", "reject", "adapt", "rephrase", "rebuild", "open_worktree", "undo", "commit_manual"}
    assert "int b()" in panel.signature.get("1.0", "end")
    assert "long b(int value)" in panel.signature.get("1.0", "end")
    assert panel.signature_var.get() == "Signature changes: 1 — confirmation required"

    panel.confirm_signature(proposal)

    assert panel.enabled_actions == {
        "propose", "approve", "reject", "adapt", "rephrase", "rebuild", "open_worktree", "undo", "commit_manual"}
    assert panel.signature_var.get() == "Signature changes: 1 confirmed"


def test_panel_signature_confirmation_does_not_leak_to_different_proposal(tmp_path: Path) -> None:
    proposal_a = fake_proposal(tmp_path)
    before_a, after_a = DerivedModel("/p"), DerivedModel("/p")
    before_a.add_entity(Entity("u:a", Kind.FUNCTION, "a", "app::a", "m.cpp", 1,
                               signature="int a()", body_hash="same-a"))
    after_a.add_entity(Entity("u:a", Kind.FUNCTION, "a", "app::a", "m.cpp", 1,
                              signature="long a(int value)", body_hash="same-a"))
    proposal_a.model = after_a
    proposal_a.delta = steps.compute_delta(before_a, after_a, ["m.cpp"])
    proposal_b = fake_proposal(tmp_path)
    before_b, after_b = DerivedModel("/p"), DerivedModel("/p")
    before_b.add_entity(Entity("u:b", Kind.FUNCTION, "b", "app::b", "m.cpp", 2,
                               signature="int b()", body_hash="same-b"))
    after_b.add_entity(Entity("u:b", Kind.FUNCTION, "b", "app::b", "m.cpp", 2,
                              signature="bool b(int value)", body_hash="same-b"))
    proposal_b.model = after_b
    proposal_b.delta = steps.compute_delta(before_b, after_b, ["m.cpp"])
    panel = step_panel.StepPanel(tk.Tk(), lambda action: None)
    panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)

    panel.show(proposal_a)
    panel.confirm_signature(proposal_a)
    assert panel.enabled_actions == {
        "propose", "approve", "reject", "adapt", "rephrase", "rebuild", "open_worktree", "undo", "commit_manual"}

    panel.show(proposal_b)

    assert panel.enabled_actions == {
        "propose", "confirm_signature", "reject", "adapt", "rephrase", "rebuild", "open_worktree", "undo", "commit_manual"}


def test_panel_shows_multi_target_batch_but_keeps_single_target_proposal_text(tmp_path: Path) -> None:
    panel = step_panel.StepPanel(tk.Tk(), lambda action: None)
    single = fake_proposal(tmp_path)
    single.request = prompt.StepRequest(prompt.IMPLEMENTATION, 1, target="u:b", batch=("u:b",))
    panel.show(single)
    assert panel.title_var.get() == "Step 1: Add b  (attempt 2)"
    assert "Implementation batch" not in panel.details.get("1.0", "end")

    multiple = fake_proposal(tmp_path)
    multiple.request = prompt.StepRequest(
        prompt.IMPLEMENTATION, 1, target="u:b", batch=("u:b", "u:a"))
    panel.show(multiple)
    assert panel.title_var.get().endswith("— batch: b, a")
    assert "Implementation batch:\n- b\n- a" in panel.details.get("1.0", "end")


def test_panel_shows_the_persisted_queue_target_and_empty_state(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION,
                                              ("u:b", "u:a"), 1))
    state = store.load_state()
    model = model_with_calls()
    target = implementation_queue.target_usr(state)
    panel = step_panel.StepPanel(tk.Tk(), lambda action: None)
    panel.set_phase(state.phase)
    entity = model.entities.get(target) if target is not None else None
    panel.set_implementation_queue(entity.qualified_name if entity is not None else target,
                                   implementation_queue.remaining(state))
    assert panel.queue_var.get() == "Current target: a — 1 remaining"

    panel.set_implementation_queue(None, 0)
    assert panel.queue_var.get() == "Implementation queue: empty — no unimplemented functions"


def test_panel_shows_and_reports_the_developer_batch_size() -> None:
    actions: list[str] = []
    panel = step_panel.StepPanel(tk.Tk(), actions.append)
    panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
    panel.set_implementation_queue("b", 3, batch_size=2, batch=("b", "a"))
    assert panel.batch_size_var.get() == 2
    assert panel.queue_var.get() == "Current batch (2): b, a — 3 remaining"

    panel.batch_size_var.set(3)
    panel._batch_size_changed()
    assert panel.batch_size_var.get() == 3 and actions[-1] == "batch_size_changed"


def test_panel_exposes_and_dispatches_persisted_auto_approve_control() -> None:
    actions: list[str] = []
    panel = step_panel.StepPanel(tk.Tk(), actions.append)
    assert panel.auto_approve_var.get() is False
    assert panel.auto_approve_check.kwargs["variable"] is panel.auto_approve_var

    panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
    panel.set_implementation_queue("b", 1, auto_approve=True)
    panel._auto_approve_changed()

    assert panel.auto_approve_var.get() is True
    assert actions == ["auto_approve_changed"]


def test_grouping_selector_renders_and_changes_the_displayed_queue_target(tmp_path: Path) -> None:
    model = DerivedModel(str(tmp_path))
    model.add_entity(Entity("class:widget", Kind.CLASS, "Widget", "app::Widget", "widget.py", 1))
    for usr, name, line in (("method:get", "get_value", 10), ("method:set", "set_value", 14)):
        model.add_entity(Entity(
            usr, Kind.METHOD, name, f"app::Widget::{name}", "widget.py", line,
            end_line=line + 2, parent="class:widget", status="stub",
        ))
    store = persistence.ProjectStore(tmp_path)
    store.save_state(persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("method:get", "method:set")))
    specification.save(store.specification_path, specification.default_specification("Grouping", "Python"))
    window = Window(tmp_path)
    window.opened = type("Opened", (), {"model": model})()
    window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
    window.panel.set_implementation_queue("app::Widget::get_value", 2)
    controller = step_controller.StepController(window)
    window.panel.on_action = controller.action

    assert window.panel.grouping_combobox.kwargs["values"] == ("One entity", "Few-line group")
    assert window.panel.queue_var.get() == "Current target: app::Widget::get_value — 2 remaining"

    window.panel.grouping_var.set("Few-line group")
    window.panel._grouping_changed()

    assert store.load_state().implementation_grouping == grouping.Mode.FEW_LINE_GROUP.value
    assert window.panel.queue_var.get() == (
        "Current group (2): app::Widget::get_value, app::Widget::set_value — 2 remaining")


def test_panel_shows_approach_and_gates_code_actions() -> None:
    panel = step_panel.StepPanel(tk.Tk(), lambda action: None)
    panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
    panel.set_implementation_queue("b", 2)
    assert "No approach approved" in panel.approach_text.get("1.0", "end")
    assert "propose_approach" in panel.enabled_actions and "propose" not in panel.enabled_actions
    assert "approve_approach" not in panel.enabled_actions

    approach = fake_approach()
    panel.show_approach(approach)
    shown = panel.approach_text.get("1.0", "end")
    assert "Awaiting developer approval" in shown and approach.plan in shown
    assert "Expected entities:\n- b" in shown and "Expected files:\n- m.cpp" in shown
    assert "approve_approach" in panel.enabled_actions and "propose" not in panel.enabled_actions
    assert {"reject", "adapt"} <= panel.enabled_actions

    panel.show_approach(approach, approved=True)
    assert "Approved" in panel.approach_text.get("1.0", "end")
    assert "propose" in panel.enabled_actions and "approve_approach" not in panel.enabled_actions
    assert "propose_approach" not in panel.enabled_actions and "reject" not in panel.enabled_actions

    panel.set_implementation_queue("b", 2, approach.plan)
    assert "Approved approach" in panel.approach_text.get("1.0", "end")
    assert "propose" in panel.enabled_actions and "propose_approach" not in panel.enabled_actions


def test_call_view_canvas_follows_root_selection_and_proposals(tmp_path: Path, monkeypatch: Any) -> None:
    opened: list[tuple[str, int]] = []
    canvas = call_view.CallViewCanvas(tk.Tk(), lambda file, line: opened.append((file, line)))
    assert isinstance(canvas.action_menu, graph_canvas.NodeActionMenu)
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


def test_call_view_renders_uncertain_call_differently_from_certain_call(monkeypatch: Any) -> None:
    canvas = call_view.CallViewCanvas(tk.Tk(), lambda file, line: None)
    model = model_with_calls()
    model.edges[1] = Edge(EdgeKind.CALLS, "u:a", "u:b", "m.cpp", 3, uncertain=True)
    lines: list[dict[str, Any]] = []
    texts: list[str] = []
    monkeypatch.setattr(canvas.canvas, "create_line", lambda *args, **kwargs: lines.append(kwargs) or len(lines))
    monkeypatch.setattr(
        canvas.canvas,
        "create_text",
        lambda *args, **kwargs: texts.append(str(kwargs.get("text", ""))) or len(texts),
    )

    canvas.show(model)

    call_lines = [line for line in lines if line.get("arrow") == tk.LAST]
    assert len(call_lines) == 2
    assert sum("dash" in line for line in call_lines) == 1
    assert any("uncertain dynamic call" in text for text in texts)


class FakeRunner(steps.StepRunner):
    def __init__(self, root: Path, config: Any, provider: str, binary: str, model: str, *, progress: Any) -> None:
        super().__init__(root, config, provider, binary, model, progress=progress)
        self.calls: list[str] = []
        self.requests: list[tuple[str, prompt.StepRequest]] = []
        self.dirty = False
        self.proposal: steps.Proposal | None = None
        self.approach: steps.Approach | None = None

    def prepare(self) -> None:
        self.calls.append("prepare")
        if self.dirty:
            raise steps.DirtyTree("uncommitted changes in the project")

    def propose(self, request: prompt.StepRequest) -> steps.Proposal:
        self.requests.append(("propose", request))
        self.calls.append(f"propose:{request.request}:{';'.join(request.constraints)}")
        self.progress("working")
        assert self.proposal is not None
        return self.proposal

    def propose_approach(self, request: prompt.StepRequest) -> steps.Approach:
        self.requests.append(("propose_approach", request))
        self.calls.append(f"propose_approach:{request.request}:{';'.join(request.constraints)}")
        assert self.approach is not None
        return self.approach

    def approve_approach(self, approach: steps.Approach) -> Any:
        self.calls.append("approve_approach")
        return steps.StepRecord(approach.number, "implementation", "approved", round="approach",
                                title="Approach for b", rationale=approach.plan)

    def reject_approach(self, approach: steps.Approach, reason: str) -> Any:
        self.calls.append(f"reject_approach:{reason}")
        return steps.StepRecord(approach.number, "implementation", "rejected", round="approach", reason=reason)

    def approve(self, proposal: steps.Proposal) -> Any:
        self.calls.append("approve")
        title = proposal.response.title if proposal.response else ""
        return steps.StepRecord(1, "architecture", "approved", title=title)

    def reject(self, proposal: steps.Proposal, reason: str) -> Any:
        self.calls.append(f"reject:{reason}")
        return steps.StepRecord(1, "architecture", "rejected", reason=reason)

    def approve_architecture(self) -> Any:
        self.calls.append("approve_architecture")
        return steps.StepRecord(1, "implementation", "phase_transition", title="architecture approved",
                                previous_phase="architecture")


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
        self.step_models: list[DerivedModel | None] = []
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

    def show_after_step(self, model: DerivedModel | None) -> None:
        self.step_models.append(model)

    def show_call_view(self) -> None:
        self.shown_call_view += 1

    def show_proposal_calls(self, proposal: steps.Proposal) -> None:
        self.call_view.show_proposal(proposal.model, proposal.delta)


def signature_gate_controller(tmp_path: Path, monkeypatch: Any) \
        -> tuple[step_controller.StepController, steps.StepRunner, steps.Proposal]:
    store = persistence.ProjectStore(tmp_path)
    before = DerivedModel(str(tmp_path))
    before.add_entity(Entity("u:b", Kind.FUNCTION, "b", "app::b", "m.cpp", 1,
                             signature="int b()", status="stub", body_hash="same"))
    proposed = DerivedModel(str(tmp_path))
    proposed.add_entity(Entity("u:b", Kind.FUNCTION, "b", "app::b", "m.cpp", 1,
                               signature="int b(int value)", status="implemented", body_hash="same"))
    store.save_model(before)
    store.save_state(persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("u:b",), 0, approved_approach="Implement directly."))
    worktree = tmp_path / "proposal-worktree"
    worktree.mkdir()
    (worktree / "m.cpp").write_text("int b(int value) { return value; }\n", encoding="utf-8")
    proposal = steps.Proposal(
        1, prompt.StepRequest(prompt.IMPLEMENTATION, 1, target="u:b"), worktree, attempts=1,
        response=response.StepResponse("Change b", "Needed.", ()), build=steps.BuildResult(True, "built"),
        test=steps.TestResult(True, "tested"), model=proposed,
        delta=steps.compute_delta(before, proposed, ["m.cpp"]),
    )
    runner = steps.StepRunner(
        tmp_path, persistence.UserConfig(), build=lambda root: steps.BuildResult(True, "rebuilt"),
        test=lambda root, command: steps.TestResult(True, "retested"))
    monkeypatch.setattr(steps.git, "promote_worktree", lambda root, candidate: ["m.cpp"])
    monkeypatch.setattr(steps.git, "commit_all", lambda *args: "commit")
    window = Window(tmp_path)
    window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
    window.panel.set_implementation_queue("app::b", 1, approved_approach="Implement directly.")
    controller = step_controller.StepController(window)
    controller.runner = runner
    controller._show_proposal(proposal)
    return controller, runner, proposal


def test_controller_signature_refusal_precedes_all_approval_mutations(
        tmp_path: Path, monkeypatch: Any) -> None:
    controller, runner, proposal = signature_gate_controller(tmp_path, monkeypatch)
    store = persistence.ProjectStore(tmp_path)
    before_state = store.load_state()
    before_state_bytes = store.state_path.read_bytes()
    before_records = runner.log.records()
    before_worktree = {str(path.relative_to(proposal.worktree)): path.read_bytes()
                       for path in proposal.worktree.rglob("*") if path.is_file()}

    with pytest.raises(steps.StepError) as refused:
        controller.approve()

    assert str(refused.value) == step_controller.SIGNATURE_CONFIRMATION_REQUIRED
    assert store.load_state() == before_state
    assert store.state_path.read_bytes() == before_state_bytes
    assert runner.log.records() == before_records
    assert {str(path.relative_to(proposal.worktree)): path.read_bytes()
            for path in proposal.worktree.rglob("*") if path.is_file()} == before_worktree
    assert controller.proposal is proposal and controller.window.panel.proposal is proposal


def test_controller_signature_confirmation_allows_the_same_proposal_and_advances_cursor(
        tmp_path: Path, monkeypatch: Any) -> None:
    controller, runner, proposal = signature_gate_controller(tmp_path, monkeypatch)

    controller.confirm_signature()
    assert controller.confirmed_signature_proposal is proposal
    assert "approve" in controller.window.panel.enabled_actions
    controller.approve()

    state = persistence.ProjectStore(tmp_path).load_state()
    assert state.implementation_cursor == 1 and state.approved_approach == ""
    assert runner.log.records()[0].decision == "approved"
    assert controller.proposal is None and controller.window.panel.proposal is None


def test_controller_signature_confirmation_does_not_authorize_different_proposal(
        tmp_path: Path, monkeypatch: Any) -> None:
    controller, runner, proposal_a = signature_gate_controller(tmp_path, monkeypatch)
    controller.confirm_signature()
    assert controller.confirmed_signature_proposal is proposal_a

    proposal_b = fake_proposal(tmp_path)
    before_b, after_b = DerivedModel(str(tmp_path)), DerivedModel(str(tmp_path))
    before_b.add_entity(Entity("u:b", Kind.FUNCTION, "b", "app::b", "m.cpp", 1,
                               signature="int b()", status="stub", body_hash="same"))
    after_b.add_entity(Entity("u:b", Kind.FUNCTION, "b", "app::b", "m.cpp", 1,
                              signature="long b(int value)", status="implemented", body_hash="same"))
    proposal_b.number = 2
    proposal_b.request = prompt.StepRequest(prompt.IMPLEMENTATION, 2, target="u:b")
    proposal_b.model = after_b
    proposal_b.delta = steps.compute_delta(before_b, after_b, ["m.cpp"])
    controller._show_proposal(proposal_b)
    store = persistence.ProjectStore(tmp_path)
    before_state = store.load_state()
    before_state_bytes = store.state_path.read_bytes()
    before_records = runner.log.records()

    with pytest.raises(steps.StepError) as refused:
        controller.approve()

    assert str(refused.value) == step_controller.SIGNATURE_CONFIRMATION_REQUIRED
    assert store.load_state() == before_state
    assert store.state_path.read_bytes() == before_state_bytes
    assert runner.log.records() == before_records
    assert controller.proposal is proposal_b and controller.window.panel.proposal is proposal_b


def test_controller_runs_the_protocol_through_the_window(tmp_path: Path, monkeypatch: Any) -> None:
    window = Window(tmp_path)
    pings: list[bool] = []
    monkeypatch.setattr(window.root, "bell", lambda: pings.append(True))
    runners: list[FakeRunner] = []

    def factory(*args: Any, **kwargs: Any) -> FakeRunner:
        runner = FakeRunner(*args, **kwargs)
        runner.proposal = fake_proposal(tmp_path)
        runner.approach = fake_approach()
        runners.append(runner)
        return runner

    controller = step_controller.StepController(window, factory)
    window.panel.request_var.set("add b")
    controller.action("propose")
    assert len(pings) == 1
    runner = runners[0]
    assert runner.calls == ["prepare", "propose:add b:"] and (runner.binary, runner.model_id) == ("claude", "m")
    assert window.panel.proposal is runner.proposal and window.shown_call_view == 1
    assert "proposal ready" in window.status.get() and window.call_view.added == {"u:main", "u:a", "u:b"}

    edited = adaptation.render_summary((
        adaptation.EntitySummary("app::small_b", "function", "m.cpp", "int small_b()", ("R-1",)),))
    window.panel.entity_summary.delete("1.0", "end")
    window.panel.entity_summary.insert("1.0", edited)
    controller.action("adapt")
    assert runner.calls[-1] == (
        "propose:add b:Correct the proposal's structured entity summary: entity 1 name changed from "
        '\"app::b\" to \"app::small_b\"; entity 1 signature changed from \"int b()\" to \"int small_b()\".'
    )
    controller.action("approve")
    assert len(pings) == 2  # Adaptation completed; approval itself stays silent.
    assert runner.calls[-1] == "approve" and window.reloads == 0 and window.panel.proposal is None
    assert window.step_models == [cast(steps.Proposal, runner.proposal).model]
    assert "approved and committed: Add b" in window.status.get()

    controller.action("propose")
    monkeypatch.setattr(step_controller.simpledialog, "askstring", lambda *a, **k: "wrong module")
    controller.action("reject")
    assert runner.calls[-1] == "reject:wrong module" and "rejected" in window.status.get()

    runner.dirty = True
    controller.action("propose")
    assert "uncommitted changes" in window.status.get() and len(runners) == 1
    assert len(pings) == 3  # Rejection and the dirty-tree preflight do not ping.
    assert views.default_root(model_with_calls()) == "u:main"


def test_controller_unchanged_structured_summary_falls_back_to_free_text_adaptation(
        tmp_path: Path, monkeypatch: Any) -> None:
    window = Window(tmp_path)
    runner = FakeRunner(tmp_path, window.config, "claude", "claude", "m", progress=lambda message: None)
    runner.proposal = fake_proposal(tmp_path)
    controller = step_controller.StepController(window)
    controller.runner = runner
    controller._show_proposal(runner.proposal)
    asked: list[tuple[str, str]] = []

    def free_text(title: str, question: str, **kwargs: Any) -> str:
        asked.append((title, question))
        return "keep it small; one module"

    monkeypatch.setattr(step_controller.simpledialog, "askstring", free_text)
    controller.adapt()

    assert asked == [("Adapt", "Hard constraints for the next attempt, separated by ';'.")]
    assert runner.calls == ["prepare", "propose::keep it small;one module"]


def test_app_adapt_re_requests_through_feedback_and_replaces_proposal(
        app_module: Any, tmp_path: Path, monkeypatch: Any) -> None:
    from test_simulation import (
        ScriptedProvider,
        _ImmediateThread,
        _run_immediately,
        runner_factory,
        write_simulation_project,
    )

    project = tmp_path / "structured-adapt"
    write_simulation_project(project)
    first_source = "def answer() -> int:\n    return 1\n"
    second_source = "def answer(limit: int = 2) -> int:\n    return limit\n"
    original = {
        "name": "service.answer", "kind": "function", "file": "service.py",
        "signature": "answer() -> int", "satisfies": ["R-1"],
    }
    corrected = dict(original, signature="answer(limit: int = 2) -> int", satisfies=["R-1", "R-2"])
    provider = ScriptedProvider([
        json.dumps({"title": "Add fixed answer", "rationale": "First proposal.",
                    "files": [{"path": "service.py", "content": first_source}], "entities": [original]}),
        json.dumps({"title": "Add configurable answer", "rationale": "Replacement proposal.",
                    "files": [{"path": "service.py", "content": second_source}], "entities": [corrected]}),
    ])
    monkeypatch.setattr(app_module.threading, "Thread", _ImmediateThread)
    app = app_module.App(
        app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "config.json")
    app.run_async = _run_immediately
    app.steps = step_controller.StepController(app, runner_factory(provider))
    app.open_project(project)
    app._poll()
    app.edit_specification()
    assert app.spec_editor is not None and app.spec_editor.save()
    app._poll()
    app.steps.action("propose")

    edited = '''[
  {
    "name": "service.answer",
    "kind": "function",
    "file": "service.py",
    "signature": "answer(limit: int = 2) -> int",
    "satisfies": [
      "R-1",
      "R-2"
    ]
  }
]
'''
    app.panel.entity_summary.delete("1.0", "end")
    app.panel.entity_summary.insert("1.0", edited)
    app.steps.action("adapt")

    instruction = (
        "Correct the proposal's structured entity summary: entity 1 signature changed from "
        '\"answer() -> int\" to \"answer(limit: int = 2) -> int\"; entity 1 satisfies changed from '
        '[\"R-1\"] to [\"R-1\", \"R-2\"].'
    )
    assert len(provider.prompts) == 2 and ("Hard constraints for this attempt:\n- " + instruction) \
        in provider.prompts[1]
    assert app.panel.title_var.get() == "Step 1: Add configurable answer  (attempt 1)"
    assert app.steps.proposal is not None and app.steps.proposal.response is not None
    assert app.steps.proposal.response.title == "Add configurable answer"


def test_controller_runs_node_tests_through_runner_and_busy_path(tmp_path: Path) -> None:
    persistence.ProjectStore(tmp_path).save_state(
        persistence.ProjectState(test_command=("ctest", "--test-dir", "build")))
    window = Window(tmp_path)
    test_calls: list[tuple[Path, tuple[str, ...]]] = []

    def factory(*args: Any, **kwargs: Any) -> FakeRunner:
        runner = FakeRunner(*args, **kwargs)

        def run_tests(root: Path, command: Any) -> steps.TestResult:
            test_calls.append((root, tuple(command)))
            return steps.TestResult(True, "focused test passed")

        runner.test = run_tests
        return runner

    controller = step_controller.StepController(window, factory)
    controller.action("run_tests", ("tests/leaf_test.cpp", "app::test_leaf"))

    assert test_calls == [(tmp_path, ("ctest", "--test-dir", "build",
                                     "tests/leaf_test.cpp", "app::test_leaf"))]
    assert window.panel.busy is False
    assert window.status.get() == "targeted tests passed: tests/leaf_test.cpp, app::test_leaf"

    controller.action("run_tests", ())
    assert len(test_calls) == 1
    window.panel.set_busy(True)
    controller.action("run_tests", ("tests/leaf_test.cpp",))
    assert len(test_calls) == 1


def test_controller_propose_here_forwards_the_exact_node_usr_as_focus(tmp_path: Path) -> None:
    window = Window(tmp_path)
    window.panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
    runners: list[FakeRunner] = []

    def factory(*args: Any, **kwargs: Any) -> FakeRunner:
        runner = FakeRunner(*args, **kwargs)
        runner.proposal = fake_proposal(tmp_path)
        runners.append(runner)
        return runner

    controller = step_controller.StepController(window, factory)
    controller.action("propose_here", "u:exact-node")

    assert runners[0].requests[0][0] == "propose"
    assert runners[0].requests[0][1].focus == ("u:exact-node",)


def test_controller_implement_here_uses_approach_enabled_by_the_real_panel(tmp_path: Path) -> None:
    window = Window(tmp_path)
    window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
    window.panel.set_implementation_queue("b", 1)
    assert isinstance(window.panel, step_panel.StepPanel)
    assert "propose_approach" in window.panel.enabled_actions and "propose" not in window.panel.enabled_actions

    runner = FakeRunner(tmp_path, window.config, "claude", "claude", "m", progress=lambda _message: None)
    runner.approach = fake_approach()
    controller = step_controller.StepController(window, lambda *args, **kwargs: runner)
    controller.action("implement_here", "u:b")

    assert len(runner.requests) == 1
    action, request = runner.requests[0]
    assert action == "propose_approach" and request.focus == ("u:b",)


def test_controller_implement_here_uses_propose_enabled_by_the_real_panel(tmp_path: Path) -> None:
    window = Window(tmp_path)
    window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
    window.panel.set_implementation_queue("b", 1, approved_approach="Use ranges.")
    assert isinstance(window.panel, step_panel.StepPanel)
    assert "propose" in window.panel.enabled_actions and "propose_approach" not in window.panel.enabled_actions

    runner = FakeRunner(tmp_path, window.config, "claude", "claude", "m", progress=lambda _message: None)
    runner.proposal = fake_proposal(tmp_path)
    controller = step_controller.StepController(window, lambda *args, **kwargs: runner)
    controller.action("implement_here", "u:b")

    assert len(runner.requests) == 1
    action, request = runner.requests[0]
    assert action == "propose" and request.focus == ("u:b",)


def test_controller_node_actions_are_inert_without_payload_or_an_enabled_panel_action(tmp_path: Path) -> None:
    window = Window(tmp_path)
    controller = step_controller.StepController(window)
    assert isinstance(window.panel, step_panel.StepPanel)
    assert not {"propose_approach", "propose"} & window.panel.enabled_actions

    controller.action("implement_here", "u:b")
    controller.action("implement_here", "")
    controller.action("propose_here", "")

    assert controller.runner is None


def test_controller_existing_panel_buttons_preserve_the_empty_focus_request(tmp_path: Path) -> None:
    architecture = Window(tmp_path)
    architecture.panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
    architecture.panel.request_var.set("add one concept")
    architecture_runner = FakeRunner(
        tmp_path, architecture.config, "claude", "claude", "m", progress=lambda _message: None)
    architecture_runner.proposal = fake_proposal(tmp_path)
    expected_proposal_request = architecture.panel.request()
    step_controller.StepController(
        architecture, lambda *args, **kwargs: architecture_runner).action("propose")
    assert architecture_runner.requests == [("propose", expected_proposal_request)]
    assert expected_proposal_request.focus == ()

    implementation = Window(tmp_path)
    implementation.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
    implementation.panel.set_implementation_queue("b", 1)
    implementation.panel.request_var.set("keep the signature")
    approach_runner = FakeRunner(
        tmp_path, implementation.config, "claude", "claude", "m", progress=lambda _message: None)
    approach_runner.approach = fake_approach()
    expected_approach_request = implementation.panel.request()
    step_controller.StepController(
        implementation, lambda *args, **kwargs: approach_runner).action("propose_approach")
    assert approach_runner.requests == [("propose_approach", expected_approach_request)]
    assert expected_approach_request.focus == ()


def test_controller_runs_approach_approval_before_code(tmp_path: Path, monkeypatch: Any) -> None:
    window = Window(tmp_path)
    pings: list[bool] = []
    monkeypatch.setattr(window.root, "bell", lambda: pings.append(True))
    window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
    window.panel.set_implementation_queue("b", 1)
    runners: list[FakeRunner] = []

    def factory(*args: Any, **kwargs: Any) -> FakeRunner:
        runner = FakeRunner(*args, **kwargs)
        runner.approach = fake_approach()
        runner.proposal = fake_proposal(tmp_path)
        runners.append(runner)
        return runner

    controller = step_controller.StepController(window, factory)
    controller.action("propose_approach")
    runner = runners[0]
    assert runner.calls == ["prepare", "propose_approach::"]
    assert window.panel.approach is runner.approach and "approach ready" in window.status.get()
    controller.action("approve_approach")
    assert pings == [True]
    assert runner.calls[-1] == "approve_approach"
    assert window.panel.approach_approved and "code-and-test round" in window.status.get()
    controller.action("propose")
    assert runner.calls[-2:] == ["prepare", "propose::"]
    assert pings == [True, True]


def test_controller_persists_a_developer_batch_size_change(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.save_state(persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("u:b", "u:a"), 0,
        approved_approach="Old single-target approach."))
    window = Window(tmp_path)
    window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
    window.panel.batch_size_var.set(2)
    controller = step_controller.StepController(window)

    controller.action("batch_size_changed")

    state = store.load_state()
    assert state.implementation_batch_size == 2 and state.approved_approach == ""
    assert window.reloads == 1 and window.status.get() == "implementation batch size set to 2"


def test_controller_surfaces_a_test_failure_after_a_successful_build(tmp_path: Path) -> None:
    window = Window(tmp_path)
    controller = step_controller.StepController(window)
    failed = fake_proposal(tmp_path)
    failed.test, failed.error = steps.TestResult(False, "failed"), "the proposal tests fail"

    controller._show_proposal(failed)

    assert window.status.get() == "step 1: build passed; tests failed"
    assert window.shown_call_view == 1 and window.panel.proposal is failed


def test_controller_auto_approve_off_preserves_the_existing_manual_stop(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.save_state(persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("u:b",), 0,
        approved_approach="Implement directly."))
    before = store.state_path.read_bytes()
    window = Window(tmp_path)
    window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
    window.panel.set_implementation_queue("b", 1, approved_approach="Implement directly.")
    runner = FakeRunner(tmp_path, window.config, "claude", "claude", "m", progress=lambda _message: None)
    runner.proposal = fake_proposal(tmp_path)
    runner.proposal.request = prompt.StepRequest(prompt.IMPLEMENTATION, 1, target="u:b", batch=("u:b",))
    controller = step_controller.StepController(window, lambda *args, **kwargs: runner)

    controller._show_proposal(runner.proposal)

    assert window.panel.auto_approve_var.get() is False
    assert controller.proposal is runner.proposal and window.panel.proposal is runner.proposal
    assert runner.calls == [] and store.state_path.read_bytes() == before
    assert window.status.get() == "step 1: proposal ready — approve, reject or adapt"


def test_controller_auto_approves_two_green_steps_then_halts_on_failed_test_gate(
        app_module: Any, tmp_path: Path, monkeypatch: Any) -> None:
    from test_simulation import (
        ScriptedProvider,
        _approach,
        _ImmediateThread,
        _reply,
        _run_immediately,
        runner_factory,
        write_simulation_project,
    )

    stub_source = "def alpha():\n    pass\n\ndef beta():\n    pass\n\ndef gamma():\n    pass\n"
    alpha_source = stub_source.replace("def alpha():\n    pass", "def alpha():\n    return 'alpha'")
    beta_source = alpha_source.replace("def beta():\n    pass", "def beta():\n    return 'beta'")
    gamma_source = beta_source.replace("def gamma():\n    pass", "def gamma():\n    return 'gamma'")
    project = tmp_path / "auto-approve"
    write_simulation_project(project)
    provider = ScriptedProvider([
        _reply("Add three functions", {"automation.py": stub_source}),
        _approach("Implement alpha and test it.", "automation.alpha", ("automation.py",)),
        _reply("Implement alpha", {"automation.py": alpha_source}),
        _approach("Implement beta and test it.", "automation.beta", ("automation.py",)),
        _reply("Implement beta", {"automation.py": beta_source}),
        _approach("Implement gamma and test it.", "automation.gamma", ("automation.py",)),
        _reply("Implement gamma", {"automation.py": gamma_source}),
    ])
    monkeypatch.setattr(app_module.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(step_controller.messagebox, "askyesno", lambda *args, **kwargs: True)
    app = app_module.App(
        app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "config.json")
    app.run_async = _run_immediately
    app.steps = step_controller.StepController(app, runner_factory(provider))
    app.open_project(project)
    app._poll()
    app.edit_specification()
    assert app.spec_editor is not None and app.spec_editor.save()
    app._poll()
    app.steps.action("propose")
    app.steps.action("approve")
    app.steps.action("approve_architecture")
    app._poll()

    gate_calls = 0

    def tests_gate(root: Path, command: Any) -> steps.TestResult:
        nonlocal gate_calls
        del root, command
        gate_calls += 1
        return steps.TestResult(gate_calls < 5, "passed" if gate_calls < 5 else "deliberate failure")

    assert app.steps.runner is not None
    app.steps.runner.test = tests_gate
    store = persistence.ProjectStore(project)
    original_state = store.load_state()
    assert len(original_state.implementation_queue) == 3 and original_state.implementation_cursor == 0
    app.panel.auto_approve_var.set(True)
    app.steps.action("auto_approve_changed")
    assert persistence.ProjectStore(project).load_state().auto_approve is True
    app.panel.auto_approve_var.set(False)
    app.open_project(project)
    app._poll()
    assert app.panel.auto_approve_var.get() is True
    app.steps.action("propose_approach")
    app.steps.action("approve_approach")
    assert store.load_state().implementation_cursor == 1
    app.steps.action("approve_approach")
    assert store.load_state().implementation_cursor == 2
    approved = [record for record in steplog.StepLog(store.steps_path).records()
                if record.phase == prompt.IMPLEMENTATION and record.decision == "approved"
                and record.round == "code"]
    assert [record.title for record in approved] == ["Implement alpha", "Implement beta"]

    records_before_failure = len(steplog.StepLog(store.steps_path).records())
    code_records_before_failure = len(approved)
    app.steps.action("approve_approach")
    stopped = "the proposal test gate is not passing"
    assert "Prompt" in app.status.get()
    assert stopped in app.panel.auto_approve_note
    assert app.recovery.issue is not None
    assert app.panel.title_var.get().startswith("Step ")  # the proposal stays visible; the hint explains
    assert store.load_state().implementation_cursor == 2
    assert len(steplog.StepLog(store.steps_path).records()) == records_before_failure + 1
    assert len([record for record in steplog.StepLog(store.steps_path).records()
                if record.phase == prompt.IMPLEMENTATION and record.decision == "approved"
                and record.round == "code"]) == code_records_before_failure
    assert app.steps.proposal is not None and app.steps.proposal.test.ok is False

    manual_project = tmp_path / "manual-default"
    write_simulation_project(manual_project)
    manual_store = persistence.ProjectStore(manual_project)
    before = manual_store.state_path.read_bytes()
    manual_app = app_module.App(
        app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "manual-config.json")
    manual_app.run_async = _run_immediately
    manual_app.open_project(manual_project)
    manual_app._poll()
    assert manual_app.panel.auto_approve_var.get() is False
    assert manual_store.state_path.read_bytes() == before


def test_controller_approves_architecture_persists_and_logs_transition(tmp_path: Path, monkeypatch: Any) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE))
    window = Window(tmp_path)
    window.panel.set_phase(store.load_state().phase)
    monkeypatch.setattr(step_controller.messagebox, "askyesno", lambda *args, **kwargs: True)
    controller = step_controller.StepController(window)

    controller.action("approve_architecture")

    assert store.load_state().phase == persistence.ProjectPhase.IMPLEMENTATION
    records = controller.runner.log.records() if controller.runner is not None else []
    assert len(records) == 1
    assert (records[0].decision, records[0].previous_phase, records[0].phase, records[0].title) == (
        "phase_transition", "architecture", "implementation", "architecture approved")
    assert window.panel.phase_var.get() == "implementation" and window.reloads == 1


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


# --------------------------------------------------------------------------- the panel's guidance and busy state


def test_panel_shows_only_the_phase_buttons_and_explains_the_grey_ones(tmp_path: Path) -> None:
    panel = step_panel.StepPanel(tk.Tk(), lambda action: None)
    panel.set_project_facts(True)
    assert panel.visible_actions == ()  # specification phase: nothing to press yet
    assert "save it" in panel.hint_var.get()
    panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
    assert panel.visible_actions == ("propose", "approve", "reject", "adapt", "approve_architecture", "rephrase", "undo")
    assert "propose" in panel.enabled_actions and "approve" not in panel.enabled_actions
    assert panel.disabled_reasons["approve"] == "no proposal that builds and passes its tests"
    help_text = panel.tooltips["approve"]  # the tooltip text is built when the pointer rests on the button
    del help_text
    assert "Grey now: no proposal" in panel._help_for("approve")()
    assert "Grey now" not in panel._help_for("propose")()
    assert panel.hint_var.get().startswith("Architecture phase: press Propose")
    panel.show(fake_proposal(tmp_path))
    assert "approve" in panel.enabled_actions and panel.hint_var.get().startswith("Step 1 is ready.")
    assert "add b" in panel.prompt_view.get("1.0", "end") or "No prompt" in panel.prompt_view.get("1.0", "end")
    panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
    assert panel.visible_actions[0] == "propose_approach" and "approve_architecture" not in panel.visible_actions
    panel.set_implementation_queue(None, 0)
    assert panel.disabled_reasons["propose_approach"] == "the implementation queue is empty"


def test_panel_busy_state_hides_the_buttons_and_offers_cancel(tmp_path: Path) -> None:
    pressed: list[str] = []
    panel = step_panel.StepPanel(tk.Tk(), pressed.append)
    panel.set_project_facts(True)
    panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
    panel.set_busy(True, "asking the agent for the next step", cancellable=True)
    assert panel.visible_actions == () and panel.enabled_actions == set()
    assert panel.hint_var.get() == "Working: asking the agent for the next step. Press Cancel to stop."
    panel.set_activity("step 2: building the proposal")
    assert panel.activity_var.get() == "step 2: building the proposal"
    assert "building the proposal" in panel.hint_var.get()
    panel._pressed("cancel")()  # what the Cancel button runs
    assert pressed[-1] == "cancel"
    panel.set_busy(False)
    assert "propose" in panel.visible_actions and "propose" in panel.enabled_actions
    panel.show_auto_approve_refusal("the proposal test gate is not passing")
    assert panel.hint_var.get().endswith("Auto-approve paused: the proposal test gate is not passing. "
                                         "Decide yourself.")
    panel.show(None)
    assert panel.auto_approve_note == ""


def test_panel_prompt_and_reply_tabs_show_the_exchange(tmp_path: Path) -> None:
    panel = step_panel.StepPanel(tk.Tk(), lambda action: None)
    proposal = fake_proposal(tmp_path)
    proposal.prompt_text, proposal.reply = "PROMPT TEXT", '{"title": "Add b"}'
    panel.show(proposal)
    assert panel.prompt_view.get("1.0", "end").startswith("PROMPT TEXT")
    assert panel.reply_view.get("1.0", "end").startswith('{"title": "Add b"}')
    panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
    panel.show_approach(fake_approach())
    assert panel.prompt_view.get("1.0", "end").startswith("approach prompt")
    assert "No reply" in panel.reply_view.get("1.0", "end")


def test_rephrase_updates_only_description_and_keeps_review_decisions(tmp_path, monkeypatch):
    window = Window(tmp_path)
    pending, requests = [], []
    window.run_async = lambda work, done: pending.append((work, done))
    rewritten = "Add b so the app can calculate the next value.\n- Check it with the existing test."
    runner = steps.StepRunner(tmp_path, window.config,
                              invoke=lambda text, cwd: requests.append((text, cwd)) or rewritten)
    controller = step_controller.StepController(window, lambda *a, **k: runner)
    proposal = controller.proposal = fake_proposal(tmp_path)
    previous = DerivedModel.from_json(proposal.model.to_json())
    previous.entities["u:b"].signature = "long b()"
    proposal.delta = steps.compute_delta(previous, proposal.model, ["m.cpp"])
    window.panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
    window.panel.show(proposal)
    window.panel.confirm_signature(proposal)
    controller.confirmed_signature_proposal = proposal
    window.panel.auto_approve_var.set(True)
    window.panel.entity_summary.insert("end", "Keep this review edit")
    summary = window.panel.edited_entity_summary()
    original_response = proposal.response
    fields = {key: value for key, value in vars(proposal).items() if key != "response"}
    monkeypatch.setattr(controller, "_consider_auto_approve", lambda **k: pytest.fail("Rephrase cannot approve"))
    source = tmp_path / "m.cpp"
    source.write_text("int b();\n")

    controller.action("rephrase")
    assert window.panel.busy and "rephrase" not in window.panel.enabled_actions
    assert proposal.response is original_response and not requests
    work, done = pending.pop()
    result = work()
    assert proposal.response is original_response  # Publication waits for the UI callback.
    done(result)

    assert proposal.response.rationale == rewritten
    assert proposal.response.files is original_response.files and proposal.response.title == original_response.title
    assert proposal.response.entities == original_response.entities and proposal.response.questions == ("Why?",)
    assert {key: value for key, value in vars(proposal).items() if key != "response"} == fields
    assert window.panel.signature_confirmed and controller.confirmed_signature_proposal is proposal
    assert window.panel.edited_entity_summary() == summary
    assert rewritten in window.panel.rationale.get("1.0", "end") and "Why?" in window.panel.rationale.get("1.0", "end")
    assert source.read_text() == "int b();\n" and not runner.log.path.exists()
    assert requests[0][1] == tmp_path and original_response.rationale in requests[0][0]
    assert "Do not run tools or change files" in requests[0][0]
    window.panel.show_step(steplog.StepRecord(9, "architecture", "approved", rationale="Old step"))
    assert "rephrase" not in window.panel.enabled_actions


@pytest.mark.parametrize("outcome", ["error", "empty", "cancelled", "stale"])
def test_rephrase_keeps_original_on_failure_cancellation_or_project_change(tmp_path, monkeypatch, outcome):
    window = Window(tmp_path)
    pending, errors, pings = [], [], []
    window.run_async = lambda work, done: pending.append((work, done))
    monkeypatch.setattr(window.root, "bell", lambda: pings.append(True))
    monkeypatch.setattr(step_controller.dialogs, "show_error", lambda *args: errors.append(args))

    def invoke(text, cwd):
        if outcome == "error":
            raise OSError("connection reset")
        if outcome == "cancelled":
            runner.cancel_requested = True
        return "" if outcome == "empty" else "Simpler text"

    runner = steps.StepRunner(tmp_path, window.config, invoke=invoke)
    controller = step_controller.StepController(window, lambda *a, **k: runner)
    proposal = controller.proposal = fake_proposal(tmp_path)
    original = proposal.response
    window.panel.show(proposal)
    controller.rephrase()
    work, done = pending.pop()
    try:
        result = work()
    except (steps.StepError, OSError) as exc:
        result = exc
    if outcome == "stale":
        window.project = tmp_path / "other"
    done(result)
    assert proposal.response is original and not pending
    assert bool(errors) == (outcome in {"error", "empty"})
    assert bool(pings) == (outcome in {"error", "empty"})


def test_rephrase_pending_approach_preserves_scope_and_does_not_approve(tmp_path):
    window = Window(tmp_path)
    runner = steps.StepRunner(tmp_path, window.config, invoke=lambda *_: "Find the item with one search.")
    controller = step_controller.StepController(window, lambda *a, **k: runner)
    approach = controller.approach = fake_approach()
    window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
    assert "rephrase" not in window.panel.enabled_actions
    window.panel.show_approach(approach)
    controller.rephrase()
    assert approach.plan == "Find the item with one search."
    assert approach.entities == ("b",) and approach.files == ("m.cpp", "tests/m_test.cpp")
    assert not window.panel.approach_approved and not runner.log.path.exists()
    assert approach.plan in window.panel.approach_text.get("1.0", "end")
    window.panel.show_approach(approach, approved=True)
    assert "rephrase" not in window.panel.enabled_actions


def test_controller_cancel_stops_the_runner_and_records_nothing(tmp_path: Path, monkeypatch: Any) -> None:
    window = Window(tmp_path)
    monkeypatch.setattr(window.root, "bell", lambda: pytest.fail("Cancelled step must not ping"))
    cancelled: list[str] = []

    class CancellableRunner(FakeRunner):
        def begin(self) -> None:
            self.calls.append("begin")

        def cancel(self) -> int:
            cancelled.append("cancel")
            return 1

        def propose(self, request: prompt.StepRequest) -> steps.Proposal:
            self.calls.append("propose")
            raise steps.StepCancelled()

    runners: list[CancellableRunner] = []

    def factory(*args: Any, **kwargs: Any) -> CancellableRunner:
        runner = CancellableRunner(*args, **kwargs)
        runners.append(runner)
        return runner

    controller = step_controller.StepController(window, factory)
    window.panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
    controller.action("propose")
    assert runners[0].calls == ["begin", "prepare", "propose"]
    assert window.status.get() == "cancelled — nothing was recorded"
    assert window.panel.proposal is None and not window.panel.busy
    controller.cancel()  # not busy: nothing happens
    assert cancelled == []
    window.panel.set_busy(True, "x", cancellable=True)
    controller.cancel()
    assert cancelled == ["cancel"] and controller.cancel_requested and window.status.get() == "cancelling …"


def test_controller_run_reports_progress_to_panel_and_status(tmp_path: Path) -> None:
    window = Window(tmp_path)
    controller = step_controller.StepController(window)
    seen: list[str] = []

    def work() -> str:
        controller._progress("half way")
        seen.append(window.panel.activity_var.get())
        return "done"

    results: list[str] = []
    controller.run(work, results.append, "counting", cancellable=False)
    assert results == ["done"] and seen == ["half way"] and window.status.get() == "half way"
    assert not window.panel.busy


def test_undo_question_names_the_step_that_goes(tmp_path: Path) -> None:
    class Log:
        @staticmethod
        def approved() -> list[steplog.StepRecord]:
            return [steplog.StepRecord(0, "architecture", "approved", title="skeleton"),
                    steplog.StepRecord(4, "architecture", "approved", title="Add parser")]

    class Runner:
        log = Log()

    question = step_controller.undo_question(Runner())
    assert question.startswith("Undo step 4 “Add parser”?") and "Nothing is deleted" in question
    assert step_controller.undo_question(object()).startswith("There is no approved step to undo")


def test_watchdog_reports_a_stalled_tk_thread() -> None:
    import time

    from icoda_gui import tasks

    reports: list[str] = []
    watchdog = tasks.Watchdog(tk.Tk(), reports.append, stall_seconds=0.05, repeat_seconds=100.0)
    watchdog.last_beat = time.monotonic() - 10  # the stub never runs ``after`` callbacks
    time.sleep(1.5)
    assert reports and reports[0].startswith("the window has not answered for") and "Tk thread" in reports[0]
    assert len(reports) == 1  # repeated only after repeat_seconds
    watchdog._beat()
    assert time.monotonic() - watchdog.last_beat < 1
