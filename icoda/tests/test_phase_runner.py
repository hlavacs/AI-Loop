"""The step runner gates requests and budgets with the persisted project phase."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from icoda_core import persistence, prompt, steps
from icoda_core.model import DerivedModel, Entity, Kind


def test_runner_uses_persisted_phase_for_rules_and_architecture_budget(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE))
    reply = json.dumps({"title": "One type", "rationale": "Needed.",
                        "files": [{"path": "x.cpp", "content": "class X {};\n"}]})
    runner = steps.StepRunner(tmp_path, persistence.UserConfig(), invoke=lambda text, root: reply, attempts=1)
    seen_prompts: list[str] = []
    monkeypatch.setattr(runner, "_fresh_worktree", lambda: tmp_path)

    def build_prompt(request: prompt.StepRequest) -> str:
        state = runner.store.load_state()
        text = prompt.build_prompt({}, runner.current_model(), request, state=state)
        seen_prompts.append(text)
        return text

    def apply(proposal: steps.Proposal) -> None:
        added = Entity("u:X", Kind.CLASS, "X", "X", "x.cpp", 1)
        proposal.build = steps.BuildResult(True, "")
        proposal.test = steps.TestResult(True, "")
        proposal.model = DerivedModel(str(tmp_path))
        proposal.delta = steps.Delta((added,), (), (), ("x.cpp",))
        proposal.error = steps._delta_error(proposal.request, proposal.delta)

    monkeypatch.setattr(runner, "_prompt", build_prompt)
    monkeypatch.setattr(runner, "_apply_and_check", apply)

    architecture = runner.propose(prompt.StepRequest(prompt.IMPLEMENTATION, 0, max_entities=0))
    assert architecture.request.phase == prompt.ARCHITECTURE and not architecture.ok
    assert architecture.request.target == ""
    assert "software architect" in seen_prompts[-1]
    assert "exceeding the maximum of 0" in architecture.error

    store.save_state(persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION))
    implementation_model = DerivedModel(str(tmp_path))
    implementation_model.add_entity(Entity("u:work", Kind.FUNCTION, "work", "app::work", "x.cpp", 1,
                                           signature="void work()", status="stub"))
    store.save_model(implementation_model)
    with pytest.raises(steps.StepError, match="implementation approach for 'app::work'.*has not been approved"):
        runner.propose(prompt.StepRequest(prompt.ARCHITECTURE, 0, max_entities=0))
    state = store.load_state()
    store.save_state(persistence.ProjectState(state.phase, state.implementation_queue, state.implementation_cursor,
                                              state.test_command, "Use the existing data structures."))
    implementation = runner.propose(prompt.StepRequest(prompt.ARCHITECTURE, 0, max_entities=0))
    assert implementation.request.phase == prompt.IMPLEMENTATION and implementation.ok
    assert implementation.request.target == "u:work" and implementation.request.focus[0] == "u:work"
    assert store.load_state().implementation_queue == ("u:work",)
    assert "the implementer" in seen_prompts[-1] and "new architecture entities" not in seen_prompts[-1]
    assert "app::work" in seen_prompts[-1]


def test_runner_rejects_step_requests_during_specification(tmp_path: Path) -> None:
    persistence.ProjectStore(tmp_path).save_state(
        persistence.ProjectState(persistence.ProjectPhase.SPECIFICATION))
    runner = steps.StepRunner(tmp_path, persistence.UserConfig())
    with pytest.raises(steps.StepError) as refused:
        runner.prepare()
        runner.propose(prompt.StepRequest(prompt.ARCHITECTURE, 0))
    assert str(refused.value) == (
        "the project is in the specification phase; save the specification before proposing")


def test_specification_refusal_precedes_prepare_mutations(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.ensure()
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.SPECIFICATION))
    (tmp_path / "project.py").write_text("def main() -> None:\n    pass\n", encoding="utf-8")
    runner = steps.StepRunner(
        tmp_path, persistence.UserConfig(), invoke=lambda text, root: "{}",
        build=lambda root: steps.BuildResult(True, ""), analyse=lambda root: DerivedModel(str(root)), attempts=1,
    )

    def project_files() -> dict[str, bytes]:
        return {str(path.relative_to(tmp_path)): path.read_bytes()
                for path in tmp_path.rglob("*") if path.is_file()}

    before_state = store.load_state()
    before_state_bytes = store.state_path.read_bytes()
    before_records = runner.log.records()
    before_files = project_files()
    before_git_root = steps.git.repository_root(tmp_path)

    with pytest.raises(steps.StepError) as refused:
        runner.prepare()
        runner.propose(prompt.StepRequest(prompt.ARCHITECTURE, 0))

    assert str(refused.value) == (
        "the project is in the specification phase; save the specification before proposing")
    assert store.load_state() == before_state
    assert store.state_path.read_bytes() == before_state_bytes
    assert runner.log.records() == before_records
    assert project_files() == before_files
    assert steps.git.repository_root(tmp_path) == before_git_root


def test_approval_advances_and_persists_the_implementation_cursor(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = persistence.ProjectStore(tmp_path)
    model = DerivedModel(str(tmp_path))
    first = Entity("u:first", Kind.FUNCTION, "first", "app::first", "x.cpp", 1, status="stub")
    second = Entity("u:second", Kind.FUNCTION, "second", "app::second", "x.cpp", 2, status="stub")
    model.add_entity(first)
    model.add_entity(second)
    store.save_model(model)
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION,
                                              (first.usr, second.usr), 0,
                                              approved_approach="Implement directly."))
    runner = steps.StepRunner(tmp_path, persistence.UserConfig(), build=lambda root: steps.BuildResult(True, ""),
                              test=lambda root, command: steps.TestResult(True, ""))
    proposal_model = DerivedModel(str(tmp_path))
    proposal_model.add_entity(Entity(**{**first.__dict__, "status": "implemented"}))
    proposal_model.add_entity(second)
    proposal = steps.Proposal(
        1, prompt.StepRequest(prompt.IMPLEMENTATION, 1, target=first.usr), tmp_path / "worktree", attempts=1,
        response=steps.response.StepResponse("Implement first", "Done.", ()),
        build=steps.BuildResult(True, ""), test=steps.TestResult(True, ""), model=proposal_model,
        delta=steps.Delta((), (), (proposal_model.entities[first.usr],), ("x.cpp",)),
    )
    monkeypatch.setattr(steps.git, "promote_worktree", lambda root, worktree: ["x.cpp"])
    monkeypatch.setattr(steps.git, "commit_all", lambda *args: "commit")

    runner.approve(proposal)

    assert store.load_state().implementation_cursor == 1
    assert store.load_state().approved_approach == ""
    reloaded = steps.StepRunner(tmp_path, persistence.UserConfig(), invoke=lambda text, root: "{}", attempts=1)
    monkeypatch.setattr(reloaded, "_fresh_worktree", lambda: tmp_path)
    seen: list[prompt.StepRequest] = []

    def capture(request: prompt.StepRequest) -> str:
        seen.append(request)
        return "prompt"

    def accept(candidate: steps.Proposal) -> None:
        candidate.response = steps.response.StepResponse("Implement second", "Done.", ())
        candidate.build = steps.BuildResult(True, "")
        candidate.test = steps.TestResult(True, "")
        candidate.model = model
        candidate.delta = steps.Delta((), (), (second,), ("x.cpp",))

    monkeypatch.setattr(reloaded, "_prompt", capture)
    monkeypatch.setattr(reloaded, "_apply_and_check", accept)
    with pytest.raises(steps.StepError, match="approach for 'app::second'.*has not been approved"):
        reloaded.propose(prompt.StepRequest(prompt.ARCHITECTURE, 0))
    following_state = store.load_state()
    store.save_state(persistence.ProjectState(following_state.phase, following_state.implementation_queue,
                                              following_state.implementation_cursor, following_state.test_command,
                                              "Use the same direct implementation."))
    following = reloaded.propose(prompt.StepRequest(prompt.ARCHITECTURE, 0))
    assert following.request.target == second.usr and seen[0].target == second.usr
    assert runner.current_model().entities[first.usr].status == "tested"
    assert steps.implementation_queue.build(runner.current_model()) == (second.usr,)


def test_approach_round_targets_queue_head_and_gates_code_prompt(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = persistence.ProjectStore(tmp_path)
    model = DerivedModel(str(tmp_path))
    target = Entity("u:leaf", Kind.FUNCTION, "leaf", "app::leaf", "src/app.cpp", 4,
                    signature="int leaf()", status="stub")
    model.add_entity(target)
    store.save_model(model)
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION, (target.usr,), 0))
    reply = json.dumps({"plan": "Use std::ranges::fold_left; about 8 lines; simple and allocation-free.",
                        "entities": ["app::leaf"], "files": ["src/app.cpp", "tests/app_test.cpp"]})
    runner = steps.StepRunner(tmp_path, persistence.UserConfig(), invoke=lambda text, root: reply, attempts=1)
    monkeypatch.setattr(runner, "_prompt_context",
                        lambda: ({}, [], {}))

    with pytest.raises(steps.StepError, match="approach for 'app::leaf'.*has not been approved"):
        runner.propose(prompt.StepRequest(prompt.IMPLEMENTATION, 0))
    approach = runner.propose_approach(prompt.StepRequest(prompt.IMPLEMENTATION, 0, "implement leaf"))
    assert approach.ok and approach.target == target.usr
    assert approach.plan.startswith("Use std::ranges::fold_left")
    assert "app::leaf int leaf()" in approach.prompt_text
    assert "Do not emit source code" in approach.prompt_text and "file changes in this round" in approach.prompt_text

    rejected = runner.reject_approach(approach, "avoid fold_left for compiler compatibility")
    assert (rejected.round, rejected.decision) == ("approach", "rejected")
    assert store.load_state().approved_approach == ""
    replacement = runner.propose_approach(prompt.StepRequest(prompt.IMPLEMENTATION, 0, "implement leaf"))
    assert "avoid fold_left for compiler compatibility" in replacement.prompt_text
    record = runner.approve_approach(replacement)
    state = store.load_state()
    assert state.approved_approach == replacement.plan
    assert (record.round, record.decision, record.rationale) == ("approach", "approved", replacement.plan)
    assert record.expected_entities == ["app::leaf"] and record.expected_files == ["src/app.cpp", "tests/app_test.cpp"]

    code_reply = json.dumps({"title": "Implement leaf", "rationale": "Follow the approved approach.",
                             "files": [{"path": "src/app.cpp", "content": "int leaf() { return 1; }\n"}]})
    runner.invoke = lambda text, root: code_reply
    monkeypatch.setattr(runner, "_fresh_worktree", lambda: tmp_path)

    def accept(candidate: steps.Proposal) -> None:
        candidate.build = steps.BuildResult(True, "")
        candidate.test = steps.TestResult(True, "")
        candidate.model = model
        candidate.delta = steps.Delta((), (), (target,), ("src/app.cpp",))

    monkeypatch.setattr(runner, "_apply_and_check", accept)
    proposal = runner.propose(prompt.StepRequest(prompt.IMPLEMENTATION, 0))
    assert proposal.ok
    assert "# Approved approach" in proposal.prompt_text and replacement.plan in proposal.prompt_text


def test_legacy_batch_default_keeps_single_target_flow_end_to_end(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = persistence.ProjectStore(tmp_path)
    model = DerivedModel(str(tmp_path))
    first = Entity("u:first", Kind.FUNCTION, "first", "app::first", "x.cpp", 1,
                   signature="void first()", status="stub")
    second = Entity("u:second", Kind.FUNCTION, "second", "app::second", "x.cpp", 2,
                    signature="void second()", status="stub")
    model.add_entity(first)
    model.add_entity(second)
    store.save_model(model)
    store.state_path.write_text(
        json.dumps({"phase": "implementation", "implementation_queue": [first.usr, second.usr],
                    "implementation_cursor": 0, "approved_approach": "Implement directly."}),
        encoding="utf-8",
    )
    reply = json.dumps({"title": "Implement first", "rationale": "Done.",
                        "files": [{"path": "x.cpp", "content": "void first() {}\n"}]})
    runner = steps.StepRunner(
        tmp_path, persistence.UserConfig(), invoke=lambda text, root: reply,
        build=lambda root: steps.BuildResult(True, ""),
        test=lambda root, command: steps.TestResult(True, ""), attempts=1,
    )
    monkeypatch.setattr(runner, "_fresh_worktree", lambda: tmp_path / "worktree")
    monkeypatch.setattr(runner, "_prompt_context", lambda: ({}, [], {}))

    def accept(candidate: steps.Proposal) -> None:
        candidate.build = steps.BuildResult(True, "")
        candidate.test = steps.TestResult(True, "")
        candidate.model = model
        candidate.delta = steps.Delta((), (), (first,), ("x.cpp",))

    monkeypatch.setattr(runner, "_apply_and_check", accept)
    proposal = runner.propose(prompt.StepRequest(prompt.IMPLEMENTATION, 0))
    step_text = proposal.prompt_text.split("# This step", 1)[1].split("# Response format", 1)[0]
    assert store.load_state().implementation_batch_size == 1
    assert proposal.request.batch == (first.usr,) and proposal.request.target == first.usr
    assert "Implement exactly this function: `app::first void first()`" in step_text
    assert "app::second" not in step_text and "Do not implement other stub functions" in step_text

    monkeypatch.setattr(steps.git, "promote_worktree", lambda root, worktree: ["x.cpp"])
    monkeypatch.setattr(steps.git, "commit_all", lambda *args: "commit")
    record = runner.approve(proposal)
    assert store.load_state().implementation_cursor == 1
    assert record.batch == [first.usr] and runner.log.records()[-1].batch == [first.usr]


def test_batch_approach_gate_and_approval_recheck(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = persistence.ProjectStore(tmp_path)
    model = DerivedModel(str(tmp_path))
    for usr, name in (("u:first", "first"), ("u:second", "second")):
        model.add_entity(Entity(usr, Kind.FUNCTION, name, f"app::{name}", "x.cpp", 1,
                                signature=f"void {name}()", status="stub"))
    store.save_model(model)
    store.save_state(persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("u:first", "u:second"), 0,
        implementation_batch_size=2))
    reply = json.dumps({"plan": "Implement both accessors directly in six lines.",
                        "entities": ["app::first", "app::second"], "files": ["x.cpp"]})
    runner = steps.StepRunner(tmp_path, persistence.UserConfig(), invoke=lambda text, root: reply, attempts=1)
    monkeypatch.setattr(runner, "_prompt_context", lambda: ({}, [], {}))

    with pytest.raises(steps.StepError, match="approach for 'app::first, app::second'.*has not been approved"):
        runner.propose(prompt.StepRequest(prompt.IMPLEMENTATION, 0))
    approach = runner.propose_approach(prompt.StepRequest(prompt.IMPLEMENTATION, 0))
    assert approach.request.batch == ("u:first", "u:second")
    assert "app::first" in approach.prompt_text and "app::second" in approach.prompt_text

    store.save_state(persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("u:first", "u:second"), 0,
        implementation_batch_size=1))
    with pytest.raises(steps.StepError, match="queue batch changed after this approach"):
        runner.approve_approach(approach)
    store.save_state(persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("u:first", "u:second"), 0,
        implementation_batch_size=2))
    runner.approve_approach(approach)

    runner.invoke = lambda text, root: json.dumps({
        "title": "Implement pair", "rationale": "Done.",
        "files": [{"path": "x.cpp", "content": "void first() {}\nvoid second() {}\n"}],
    })
    monkeypatch.setattr(runner, "_fresh_worktree", lambda: tmp_path)

    def accept(candidate: steps.Proposal) -> None:
        candidate.build = steps.BuildResult(True, "")
        candidate.test = steps.TestResult(True, "")
        candidate.model = model
        candidate.delta = steps.Delta((), (), tuple(model.entities.values()), ("x.cpp",))

    monkeypatch.setattr(runner, "_apply_and_check", accept)
    assert runner.propose(prompt.StepRequest(prompt.IMPLEMENTATION, 0)).ok


def test_batch_approval_advances_every_member_and_refuses_a_changed_head(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = persistence.ProjectStore(tmp_path)
    model = DerivedModel(str(tmp_path))
    for usr in ("first", "second", "third"):
        model.add_entity(Entity(usr, Kind.FUNCTION, usr, f"app::{usr}", "x.cpp", 1, status="stub"))
    store.save_model(model)
    initial = persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("first", "second", "third"), 0,
        approved_approach="Implement the pair.", implementation_batch_size=2)
    store.save_state(initial)
    runner = steps.StepRunner(
        tmp_path, persistence.UserConfig(), build=lambda root: steps.BuildResult(True, ""),
        test=lambda root, command: steps.TestResult(True, ""))
    request = prompt.StepRequest(prompt.IMPLEMENTATION, 1, target="first", batch=("first", "second"))
    proposal = steps.Proposal(
        1, request, tmp_path / "worktree", response=steps.response.StepResponse("Implement pair", "Done.", ()),
        build=steps.BuildResult(True, ""), test=steps.TestResult(True, ""), model=model,
        delta=steps.Delta((), (), (model.entities["first"], model.entities["second"]), ("x.cpp",)))
    monkeypatch.setattr(steps.git, "promote_worktree", lambda root, worktree: ["x.cpp"])
    monkeypatch.setattr(steps.git, "commit_all", lambda *args: "commit")

    store.save_state(replace(initial, implementation_cursor=1))
    with pytest.raises(steps.StepError, match="queue batch changed after this proposal"):
        runner.approve(proposal)
    store.save_state(initial)
    record = runner.approve(proposal)
    assert store.load_state().implementation_cursor == 2
    assert record.batch == ["first", "second"]
