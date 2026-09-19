"""One App session simulating ICODA's complete developer-controlled lifecycle."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from icoda_core import (
    persistence,
    prompt,
    python_analysis,
    specification,
    steplog,
    steps,
)
from icoda_gui import graph_canvas, step_controller

FORMATTER = "python:service:Formatter"
NORMALIZE = "python:service:Formatter.normalize"
MAIN = "python:service:main"

ARCHITECTURE_SOURCE = '''class Formatter:
    """Normalize display values."""

    def normalize(self, value: str) -> str:
        """Return the normalized value."""
        pass


def main() -> str:
    """Run the service."""
    formatter = Formatter()
    return formatter.normalize(" item ")
'''

NORMALIZE_SOURCE = ARCHITECTURE_SOURCE.replace("        pass\n", "        return value.strip()\n")
FINAL_SOURCE = NORMALIZE_SOURCE.replace(
    '    formatter = Formatter()\n    return formatter.normalize(" item ")\n',
    '    value = Formatter().normalize(" item ")\n    return f"ready:{value}"\n',
)
NORMALIZE_TEST = '''from service import Formatter


def test_normalize(formatter: Formatter) -> None:
    assert formatter.normalize(" item ") == "item"
'''
FINAL_TESTS = NORMALIZE_TEST + '''

from service import main


def test_main() -> None:
    assert main() == "ready:item"
'''

DIFF_INITIAL_SOURCE = '''def first() -> str:
    return "old-one"


def second() -> str:
    return "old-two"
'''
DIFF_UPDATED_SOURCE = DIFF_INITIAL_SOURCE.replace("old-one", "new-one").replace("old-two", "new-two")


class ScriptedProvider:
    """The same prompt-in/reply-out fake-provider contract used by test_steps.py."""

    def __init__(self, replies: Sequence[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt_text: str, cwd: Path) -> str:
        del cwd
        self.prompts.append(prompt_text)
        if not self.replies:
            raise AssertionError("the simulation made an unexpected provider request")
        return self.replies.pop(0)


def _reply(title: str, files: dict[str, str], entities: Sequence[dict[str, Any]] = ()) -> str:
    reply = {
        "title": title,
        "rationale": "Keep this atomic and derive the review delta from the changed source.",
        "files": [{"path": path, "content": content} for path, content in files.items()],
    }
    if entities:
        reply["entities"] = list(entities)
    return json.dumps(reply)


def _approach(plan: str, entity: str, files: Sequence[str]) -> str:
    return json.dumps({"plan": plan, "entities": [entity], "files": list(files)})


def simulation_replies() -> list[str]:
    """Responses for reject/replace architecture and two approach/code rounds."""
    architecture_entities = (
        {"name": "service.Formatter", "kind": "class", "file": "service.py"},
        {"name": "service.Formatter.normalize", "kind": "method", "file": "service.py"},
        {"name": "service.main", "kind": "function", "file": "service.py"},
    )
    return [
        _reply("Draft formatter architecture", {"service.py": ARCHITECTURE_SOURCE}, architecture_entities),
        _reply("Add formatter architecture", {"service.py": ARCHITECTURE_SOURCE}, architecture_entities),
        _approach("Replace the normalize stub directly and add one focused test.",
                  "service.Formatter.normalize", ("service.py", "tests/test_service.py")),
        _reply("Implement Formatter.normalize", {
            "service.py": NORMALIZE_SOURCE,
            "tests/test_service.py": NORMALIZE_TEST,
        }, ({"name": "service.Formatter.normalize", "kind": "method", "file": "service.py"},)),
        _approach("Complete main using Formatter and add its observable result test.",
                  "service.main", ("service.py", "tests/test_service.py")),
        _reply("Implement main", {"service.py": FINAL_SOURCE, "tests/test_service.py": FINAL_TESTS},
               ({"name": "service.main", "kind": "function", "file": "service.py"},)),
    ]


def write_simulation_project(root: Path) -> None:
    """Create the small Python fixture at the specification phase."""
    root.mkdir(parents=True)
    (root / "project.py").write_text('PROJECT = "icoda simulation"\n', encoding="utf-8")
    store = persistence.ProjectStore(root)
    store.ensure()
    specification.save(store.specification_path, specification.default_specification("simulation"))
    store.save_state(persistence.ProjectState(
        persistence.ProjectPhase.SPECIFICATION,
        test_command=("python", "-m", "pytest", "-q"),
        implementation_batch_size=1,
    ))


def passing_build(root: Path) -> steps.BuildResult:
    """Deterministic build gate for a Python source fixture."""
    return steps.BuildResult(root.is_dir(), "Python syntax/build gate passed.")


def passing_tests(root: Path, command: Sequence[str]) -> steps.TestResult:
    """Deterministic test gate; the selected command remains visible in the proposal."""
    return steps.TestResult(root.is_dir(), "Test gate passed: " + " ".join(command))


def runner_factory(provider: ScriptedProvider, *, attempts: int = 1) -> Callable[..., steps.StepRunner]:
    """Build the real runner around deterministic provider/build/test seams."""
    runner: steps.StepRunner | None = None

    def factory(root: Path, config: persistence.UserConfig, provider_id: str, binary: str,
                model: str, *, progress: Callable[[str], None]) -> steps.StepRunner:
        nonlocal runner
        if runner is None:
            runner = steps.StepRunner(
                root,
                config,
                provider_id,
                binary,
                model,
                invoke=provider,
                build=passing_build,
                test=passing_tests,
                analyse=python_analysis.parse_project,
                attempts=attempts,
                progress=progress,
            )
        return runner

    return factory


class _ImmediateThread:
    def __init__(self, *, target: Callable[..., Any], args: tuple[Any, ...], daemon: bool) -> None:
        del daemon
        self.target, self.args = target, args

    def start(self) -> None:
        self.target(*self.args)


def _open(app: Any, project: Path) -> None:
    app.open_project(project)
    app._poll()
    assert app.opened is not None and app.opened.root == project.resolve()


def _text(widget: Any) -> str:
    return str(widget.get("1.0", "end-1c"))


def _pending_gate(app: Any) -> str:
    """Name the gate exposed by the panel's public controls and result fields."""
    enabled = app.panel.enabled_actions
    if "approve_architecture" in enabled:
        return "architecture approval"
    if "approve_approach" in enabled:
        return "approach approval"
    if "approve" in enabled:
        build = app.panel.build_status_var.get().removeprefix("Build: ")
        test = app.panel.test_status_var.get().removeprefix("Tests: ")
        return f"code approval after build {build} and tests {test}"
    return "none"


def _assert_stop(
    app: Any,
    store: persistence.ProjectStore,
    *,
    phase: persistence.ProjectPhase,
    title: str,
    delta: str,
    source_diff: str,
    live: set[str],
    gate: str,
    queue: tuple[str, ...],
    cursor: int,
    iterations: list[int],
) -> None:
    """Assert only developer-visible widgets and persisted project/history records."""
    assert app.panel.phase_var.get() == phase.value
    assert title in app.panel.title_var.get()
    assert delta in _text(app.panel.details)
    assert source_diff in _text(app.panel.source_diff)
    assert ({"approve", "approve_architecture", "approve_approach", "reject"}
            & app.panel.enabled_actions) == live
    assert _pending_gate(app) == gate
    state = store.load_state()
    assert state.phase == phase
    assert state.implementation_queue == queue
    assert state.implementation_cursor == cursor
    assert state.implementation_batch_size == 1
    assert [record.number for record in steplog.StepLog(store.steps_path).records()] == iterations


def _assert_overviews(app: Any, *, specification_phase: bool = False) -> None:
    """All six named overview surfaces render their current public projection."""
    assert app.view.layout is not None and app.view.layout.nodes and app.view.item_nodes
    if specification_phase:
        assert app.call_view.layout is None and not app.call_view.item_nodes
        assert not app.class_view.graph.nodes and "project.py" in app.class_view.item_nodes.values()
        assert app.mind_map_view.tree is not None and app.mind_map_view.tree.nodes()
        assert app.mind_map_view.item_nodes
        assert not app.coverage_view.index.entries
        assert app.coverage_view.summary_var.get() == "Recorded test reachability: no callable entities"
        assert app.issue_view.summary_var.get() == "Rule checks: 0 issues · 0 errors · 0 warnings"
        assert not app.issue_view.issues
        return
    assert app.call_view.layout is not None and app.call_view.layout.nodes and app.call_view.item_nodes
    assert app.class_view.graph.nodes and app.class_view.item_nodes
    assert app.mind_map_view.tree is not None and app.mind_map_view.tree.nodes()
    assert app.mind_map_view.item_nodes
    assert app.coverage_view.index.entries \
        and app.coverage_view.summary_var.get().startswith("Recorded test reachability:")
    assert app.issue_view.summary_var.get().startswith("Rule checks:") and app.issue_view.issues


def _approve(app: Any, action: str) -> None:
    app.steps.action(action)
    # the panel stays busy only while a reload's analysis is still in flight (consumed by ``_poll``)
    assert not app.panel.busy or app._pending_analyses


def _run_immediately(work: Callable[[], Any], done: Callable[[Any], None]) -> None:
    try:
        result = work()
    except Exception as exc:  # noqa: BLE001  (mirror UiTasks' public error delivery synchronously)
        result = exc
    done(result)


class _LifecycleAssertions:
    def __init__(self, app: Any, store: persistence.ProjectStore, provider: ScriptedProvider) -> None:
        self.app, self.store, self.provider = app, store, provider
        self.queue = (NORMALIZE, MAIN)

    def complete_specification(self) -> None:
        self._refuse_specification_code_step()
        self._save_specification()

    def _refuse_specification_code_step(self) -> None:
        before_request = self.store.load_state()
        _assert_stop(
            self.app, self.store, phase=persistence.ProjectPhase.SPECIFICATION,
            title="No proposal", delta="", source_diff="", live=set(), gate="none",
            queue=(), cursor=0, iterations=[],
        )
        _assert_overviews(self.app, specification_phase=True)
        assert "propose" not in self.app.panel.enabled_actions
        self.app.steps.action("propose")
        _assert_stop(
            self.app, self.store, phase=persistence.ProjectPhase.SPECIFICATION,
            title="Step failed — the project is in the specification phase",
            delta="save the specification before proposing", source_diff="", live=set(), gate="none",
            queue=(), cursor=0, iterations=[],
        )
        assert self.app.status.get() == (
            "step failed: 'the project is in the specification phase; save the specification before proposing'"
        )
        assert self.store.load_state() == before_request
        _assert_overviews(self.app, specification_phase=True)

    def _save_specification(self) -> None:
        self.app.edit_specification()
        assert self.app.spec_editor is not None
        before_save = self.store.load_state()
        assert before_save.phase is persistence.ProjectPhase.SPECIFICATION
        assert self.app.spec_editor.save()
        self.app._poll()
        after_save = self.store.load_state()
        assert after_save.phase is persistence.ProjectPhase.ARCHITECTURE
        assert after_save.implementation_queue == () and after_save.implementation_batch_size == 1
        records = steplog.StepLog(self.store.steps_path).records()
        assert [record.number for record in records] == [0]
        assert [(record.previous_phase, record.phase, record.decision, record.title) for record in records] == [
            ("specification", "architecture", "phase_transition", "specification completed")
        ]
        assert self.app.panel.phase_var.get() == persistence.ProjectPhase.ARCHITECTURE.value

    def reject_architecture(self) -> None:
        self.app.steps.action("propose")
        _assert_stop(
            self.app, self.store, phase=persistence.ProjectPhase.ARCHITECTURE,
            title="Draft formatter architecture", delta="service.Formatter.normalize",
            source_diff="+class Formatter:", live={"approve", "reject"},
            gate="code approval after build passed and tests passed", queue=(), cursor=0,
            iterations=[0, 0],
        )
        before_reject = self.store.load_state()
        self.app.steps.action("reject")
        assert self.store.load_state() == before_reject
        records = steplog.StepLog(self.store.steps_path).records()
        assert [record.number for record in records] == [0, 0, 1]

    def approve_architecture(self) -> None:
        self.app.steps.action("propose")
        _assert_stop(
            self.app, self.store, phase=persistence.ProjectPhase.ARCHITECTURE,
            title="Add formatter architecture", delta="service.Formatter.normalize",
            source_diff="+class Formatter:", live={"approve", "reject"},
            gate="code approval after build passed and tests passed", queue=(), cursor=0,
            iterations=[0, 0, 1],
        )
        _approve(self.app, "approve")
        _assert_overviews(self.app)
        records = steplog.StepLog(self.store.steps_path).records()
        appearance = self.app.call_view.node_appearance(NORMALIZE)
        facts = [(r.number, r.decision, r.entities_renamed) for r in records]
        assert appearance is not None and appearance.status == "stub", facts

    def enter_implementation(self) -> None:
        _assert_stop(
            self.app, self.store, phase=persistence.ProjectPhase.ARCHITECTURE,
            title="No proposal", delta="", source_diff="", live={"approve_architecture"},
            gate="architecture approval", queue=(), cursor=0, iterations=[0, 0, 1, 1],
        )
        _approve(self.app, "approve_architecture")
        self.app._poll()
        _assert_overviews(self.app)
        assert self.store.load_state().implementation_queue == self.queue

    def implement_normalize(self) -> None:
        self.app.steps.action("propose_approach")
        _assert_stop(
            self.app, self.store, phase=persistence.ProjectPhase.IMPLEMENTATION,
            title="No proposal", delta="", source_diff="", live={"approve_approach", "reject"},
            gate="approach approval", queue=self.queue, cursor=0, iterations=[0, 0, 1, 1, 2],
        )
        assert "Replace the normalize stub" in _text(self.app.panel.approach_text)
        _approve(self.app, "approve_approach")
        _assert_overviews(self.app)
        self.app.steps.action("propose")
        _assert_stop(
            self.app, self.store, phase=persistence.ProjectPhase.IMPLEMENTATION,
            title="Implement Formatter.normalize", delta="~ method service.Formatter.normalize",
            source_diff="+        return value.strip()", live={"approve", "reject"},
            gate="code approval after build passed and tests passed", queue=self.queue, cursor=0,
            iterations=[0, 0, 1, 1, 2, 2],
        )
        _approve(self.app, "approve")
        _assert_overviews(self.app)
        appearance = self.app.call_view.node_appearance(NORMALIZE)
        assert appearance is not None and appearance.status == "tested"
        assert self.app.call_view.node_fill(NORMALIZE) == graph_canvas.NODE_COLOURS["tested"]
        coverage = self.app.coverage_view.index.entry_map()[NORMALIZE]
        assert coverage.covered and coverage.tests == ("tests/test_service.py",)

    def implement_main(self) -> None:
        self.app.steps.action("propose_approach")
        _assert_stop(
            self.app, self.store, phase=persistence.ProjectPhase.IMPLEMENTATION,
            title="No proposal", delta="", source_diff="", live={"approve_approach", "reject"},
            gate="approach approval", queue=self.queue, cursor=1,
            iterations=[0, 0, 1, 1, 2, 2, 2],
        )
        assert "Complete main" in _text(self.app.panel.approach_text)
        _approve(self.app, "approve_approach")
        _assert_overviews(self.app)
        self.app.steps.action("propose")
        _assert_stop(
            self.app, self.store, phase=persistence.ProjectPhase.IMPLEMENTATION,
            title="Implement main", delta="~ function service.main",
            source_diff='+    return f"ready:{value}"', live={"approve", "reject"},
            gate="code approval after build passed and tests passed", queue=self.queue, cursor=1,
            iterations=[0, 0, 1, 1, 2, 2, 2, 3],
        )
        _approve(self.app, "approve")
        _assert_overviews(self.app)

    def assert_terminal(self) -> None:
        _assert_stop(
            self.app, self.store, phase=persistence.ProjectPhase.IMPLEMENTATION,
            title="No proposal", delta="", source_diff="", live=set(), gate="none",
            queue=self.queue, cursor=2, iterations=[0, 0, 1, 1, 2, 2, 2, 3, 3],
        )
        assert "empty" in self.app.panel.queue_var.get() and self.provider.replies == []
        phase = persistence.ProjectPhase(self.app.panel.phase_var.get())
        assert phase is persistence.ProjectPhase.IMPLEMENTATION
        appearances = [self.app.call_view.node_appearance(usr) for usr in self.queue]
        assert all(item is not None and item.status == "tested" for item in appearances)
        assert self.app.coverage_view.index.entry_map()[MAIN].tests == ("tests/test_service.py",)


def test_complete_developer_controlled_simulation(
    app_module: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    project = tmp_path / "simulation"
    write_simulation_project(project)
    store = persistence.ProjectStore(project)
    provider = ScriptedProvider(simulation_replies())
    monkeypatch.setattr(app_module.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(step_controller.messagebox, "askyesno", lambda *args, **kwargs: True)
    monkeypatch.setattr(step_controller.simpledialog, "askstring",
                        lambda *args, **kwargs: "Keep the public API smaller")
    app = app_module.App(
        app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "config.json"
    )
    app.run_async = _run_immediately
    app.steps = step_controller.StepController(app, runner_factory(provider))
    _open(app, project)
    lifecycle = _LifecycleAssertions(app, store, provider)
    lifecycle.complete_specification()
    lifecycle.reject_architecture()
    lifecycle.approve_architecture()
    lifecycle.enter_implementation()
    lifecycle.implement_normalize()
    lifecycle.implement_main()
    lifecycle.assert_terminal()


def _diff_reply(title: str, patches: dict[str, str]) -> str:
    return json.dumps({
        "title": title,
        "rationale": "Exercise the same candidate path with a unified diff.",
        "files": [{"path": path, "content": content} for path, content in patches.items()],
    })


def _prepared_diff_runner(
    root: Path,
    provider: ScriptedProvider,
    *,
    source: bytes = DIFF_INITIAL_SOURCE.encode("utf-8"),
    attempts: int = 1,
) -> steps.StepRunner:
    root.mkdir()
    (root / "service.py").write_bytes(source)
    (root / "notes.txt").write_bytes(b"present\n")
    store = persistence.ProjectStore(root)
    store.ensure()
    specification.save(store.specification_path, specification.default_specification(root.name))
    store.save_state(persistence.ProjectState(
        persistence.ProjectPhase.ARCHITECTURE,
        test_command=("python", "-m", "pytest", "-q"),
    ))
    messages: list[str] = []
    runner = runner_factory(provider, attempts=attempts)(
        root, persistence.UserConfig(), "fake", "fake-bin", "fake-model", progress=messages.append
    )
    runner.prepare()
    return runner


def _propose_on_immediate_thread(runner: steps.StepRunner) -> steps.Proposal:
    outcomes: list[Any] = []
    thread = _ImmediateThread(
        target=_run_immediately,
        args=(lambda: runner.propose(prompt.StepRequest(prompt.ARCHITECTURE, 0)), outcomes.append),
        daemon=True,
    )
    thread.start()
    assert len(outcomes) == 1 and isinstance(outcomes[0], steps.Proposal)
    return outcomes[0]


def test_step_runner_unified_diff_and_full_file_produce_identical_candidate_and_delta(
        tmp_path: Path) -> None:
    full_provider = ScriptedProvider([_reply("Update both functions", {"service.py": DIFF_UPDATED_SOURCE})])
    diff = """diff --git a/service.py b/service.py
--- a/service.py
+++ b/service.py
@@ -2 +2 @@
-    return "old-one"
+    return "new-one"
@@ -6 +6 @@
-    return "old-two"
+    return "new-two"
"""
    diff_provider = ScriptedProvider([_diff_reply("Update both functions", {"service.py": diff})])
    full = _propose_on_immediate_thread(_prepared_diff_runner(tmp_path / "full", full_provider))
    patched = _propose_on_immediate_thread(_prepared_diff_runner(tmp_path / "diff", diff_provider))
    full_bytes = (full.worktree / "service.py").read_bytes()
    diff_bytes = (patched.worktree / "service.py").read_bytes()
    assert full.ok and patched.ok
    assert full_bytes == diff_bytes == DIFF_UPDATED_SOURCE.encode("utf-8")
    assert full.delta == patched.delta


def test_step_runner_lf_unified_diff_ignores_platform_linesep_and_matches_full_file_bytes(
        tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(steps.os, "linesep", "\r\n")
    full_provider = ScriptedProvider([_reply("Update LF file", {"service.py": DIFF_UPDATED_SOURCE})])
    diff = """diff --git a/service.py b/service.py
--- a/service.py
+++ b/service.py
@@ -2 +2 @@
-    return "old-one"
+    return "new-one"
@@ -6 +6 @@
-    return "old-two"
+    return "new-two"
"""
    diff_provider = ScriptedProvider([_diff_reply("Update LF file", {"service.py": diff})])
    full = _propose_on_immediate_thread(_prepared_diff_runner(tmp_path / "full-lf", full_provider))
    patched = _propose_on_immediate_thread(_prepared_diff_runner(tmp_path / "diff-lf", diff_provider))
    full_bytes = (full.worktree / "service.py").read_bytes()
    patched_bytes = (patched.worktree / "service.py").read_bytes()
    assert full.ok and patched.ok
    assert patched_bytes == full_bytes == DIFF_UPDATED_SOURCE.encode("utf-8")


def test_step_runner_unified_diff_preserves_crlf_file_endings(tmp_path: Path) -> None:
    source = DIFF_INITIAL_SOURCE.replace("\n", "\r\n").encode("utf-8")
    expected = DIFF_UPDATED_SOURCE.replace("\n", "\r\n").encode("utf-8")
    diff = """diff --git a/service.py b/service.py
--- a/service.py
+++ b/service.py
@@ -2 +2 @@
-    return "old-one"
+    return "new-one"
@@ -6 +6 @@
-    return "old-two"
+    return "new-two"
"""
    provider = ScriptedProvider([_diff_reply("Update CRLF file", {"service.py": diff})])
    proposal = _propose_on_immediate_thread(
        _prepared_diff_runner(tmp_path / "crlf", provider, source=source)
    )
    assert proposal.ok
    assert (proposal.worktree / "service.py").read_bytes() == expected


def test_step_runner_unified_diff_preserves_untouched_mixed_endings_byte_for_byte(
        tmp_path: Path) -> None:
    source = b"keep-crlf\r\nreplace-lf\nkeep-final-no-newline"
    diff = """diff --git a/service.py b/service.py
--- a/service.py
+++ b/service.py
@@ -2 +2 @@
-replace-lf
+changed-lf
"""
    provider = ScriptedProvider([_diff_reply("Update mixed file", {"service.py": diff})])
    proposal = _propose_on_immediate_thread(
        _prepared_diff_runner(tmp_path / "mixed", provider, source=source)
    )
    assert proposal.ok
    assert (proposal.worktree / "service.py").read_bytes() == (
        b"keep-crlf\r\nchanged-lf\nkeep-final-no-newline"
    )


def test_step_runner_stale_unified_diff_leaves_candidate_files_byte_identical(
        tmp_path: Path, monkeypatch: Any) -> None:
    valid_first = """diff --git a/service.py b/service.py
--- a/service.py
+++ b/service.py
@@ -2 +2 @@
-    return "old-one"
+    return "new-one"
"""
    stale_second = """diff --git a/notes.txt b/notes.txt
--- a/notes.txt
+++ b/notes.txt
@@ -1 +1 @@
-stale
+changed
"""
    provider = ScriptedProvider([_diff_reply("Stale second file", {
        "service.py": valid_first,
        "notes.txt": stale_second,
    })])
    runner = _prepared_diff_runner(tmp_path / "stale", provider)
    worktree = runner._fresh_worktree()
    before = {path: (worktree / path).read_bytes() for path in ("service.py", "notes.txt")}
    monkeypatch.setattr(runner, "_fresh_worktree", lambda: worktree)
    proposal = _propose_on_immediate_thread(runner)
    assert proposal.error == (
        "could not apply the files: unified diff for 'notes.txt' does not apply: "
        "hunk 1 does not match at old line 1"
    )
    assert {path: (worktree / path).read_bytes() for path in before} == before


def test_step_runner_non_applying_unified_diff_retry_uses_validation_error_without_build_errors(
        tmp_path: Path, monkeypatch: Any) -> None:
    stale = """diff --git a/notes.txt b/notes.txt
--- a/notes.txt
+++ b/notes.txt
@@ -1 +1 @@
-stale
+changed
"""
    provider = ScriptedProvider([
        _diff_reply("Stale patch", {"notes.txt": stale}),
        _reply("Valid retry", {"notes.txt": "changed\n"}),
    ])
    runner = _prepared_diff_runner(tmp_path / "retry", provider, attempts=2)
    requests: list[prompt.StepRequest] = []
    real_prompt = runner._prompt

    def capture_request(request: prompt.StepRequest) -> str:
        requests.append(request)
        return real_prompt(request)

    monkeypatch.setattr(runner, "_prompt", capture_request)
    proposal = _propose_on_immediate_thread(runner)
    exact_error = (
        "could not apply the files: unified diff for 'notes.txt' does not apply: "
        "hunk 1 does not match at old line 1"
    )
    assert proposal.ok and proposal.attempts == 2
    assert requests[1].validation_error == exact_error
    assert requests[1].build_errors == ""
    assert "The previous reply was not usable: " + exact_error in provider.prompts[1]
    assert "The previous attempt did not build" not in provider.prompts[1]


def test_step_runner_past_eof_removal_is_reported_as_non_applying(tmp_path: Path) -> None:
    source = b"first\nsecond\n"
    past_eof = """diff --git a/service.py b/service.py
--- a/service.py
+++ b/service.py
@@ -3 +3 @@
-missing
+changed
"""
    provider = ScriptedProvider([_diff_reply("Past EOF patch", {"service.py": past_eof})])
    proposal = _propose_on_immediate_thread(
        _prepared_diff_runner(tmp_path / "past-eof", provider, source=source)
    )
    assert proposal.error == (
        "could not apply the files: unified diff for 'service.py' does not apply: "
        "hunk 1 does not match at old line 3"
    )


def test_step_runner_context_matches_final_line_without_trailing_newline(tmp_path: Path) -> None:
    source = b"old\nfinal"
    diff = """diff --git a/service.py b/service.py
--- a/service.py
+++ b/service.py
@@ -1,2 +1,2 @@
-old
+new
 final
\\ No newline at end of file
"""
    provider = ScriptedProvider([_diff_reply("Keep final context", {"service.py": diff})])
    proposal = _propose_on_immediate_thread(
        _prepared_diff_runner(tmp_path / "final-context", provider, source=source)
    )
    assert proposal.ok
    assert (proposal.worktree / "service.py").read_bytes() == b"new\nfinal"


def _record_tested_answer(project: Path) -> tuple[persistence.ProjectStore, Path, str]:
    project.mkdir()
    source = project / "service.py"
    source.write_text("def answer() -> int:\n    return 1\n", encoding="utf-8")
    store = persistence.ProjectStore(project)
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION))
    model = python_analysis.parse_project(project)
    usr = "python:service:answer"
    store.save_model(model)
    steplog.StepLog(store.steps_path).append(steplog.StepRecord(
        1, "implementation", "approved", entities_changed=[usr], test_ok=True,
        entity_body_hashes={usr: model.entities[usr].body_hash},
    ))
    return store, source, usr


def test_app_focus_refresh_reconciles_external_body_edit_without_reopen(
    app_module: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    project = tmp_path / "external-edit"
    store, source, usr = _record_tested_answer(project)
    provider = ScriptedProvider(())
    monkeypatch.setattr(app_module.threading, "Thread", _ImmediateThread)
    real_open_project = app_module.session.open_project
    analysis_calls = 0

    def counted_open_project(root: Path, config: persistence.UserConfig) -> Any:
        nonlocal analysis_calls
        analysis_calls += 1
        return real_open_project(root, config, in_process=True)

    monkeypatch.setattr(app_module.session, "open_project", counted_open_project)
    app = app_module.App(
        app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "config.json"
    )
    app.run_async = _run_immediately
    app.steps = step_controller.StepController(app, runner_factory(provider))
    _open(app, project)
    before = app.call_view.node_appearance(usr)
    assert before is not None and before.status == "tested"
    watched_files = (store.state_path, store.model_path, store.steps_path)
    unchanged_bytes = {path: path.read_bytes() for path in watched_files}

    app._refresh_external_edits(None)

    assert analysis_calls == 1
    assert {path: path.read_bytes() for path in watched_files} == unchanged_bytes
    source.write_text("def answer() -> int:\n    return 200\n", encoding="utf-8")

    app._refresh_external_edits(None)
    app._poll()

    after = app.call_view.node_appearance(usr)
    assert analysis_calls == 2
    assert app.opened is not None and app.opened.root == project.resolve()
    assert after is not None and after.status == "implemented"
    assert provider.prompts == [] and provider.replies == []
