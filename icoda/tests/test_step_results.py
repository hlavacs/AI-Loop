"""Build and test outcomes are executed, persisted and approved independently."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from icoda_core import git, persistence, prompt, response, steplog, steps
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, Kind
from icoda_core.process import ProcessResult


def proposal(root: Path, build: steps.BuildResult, test: steps.TestResult) -> steps.Proposal:
    return steps.Proposal(
        1, prompt.StepRequest(prompt.ARCHITECTURE, 1), root / "worktree", attempts=1,
        response=response.StepResponse("A change", "Because.", ()), build=build, test=test,
        model=DerivedModel(str(root)), delta=steps.Delta((), (), (), ("x.cpp",)),
    )


def quality_proposal(root: Path, *, end_line: int = 10) -> steps.Proposal:
    model = DerivedModel(str(root))
    target = Entity(
        "u:work", Kind.FUNCTION, "work", "app::work", "src/app.cpp", 1, end_line,
        signature="void work()", status="implemented", brief="Do production work.", satisfies=("R-1",),
    )
    model.add_entity(target)
    added = [target]
    files = ["src/app.cpp"]
    test_entity = Entity(
        "u:test-work", Kind.FUNCTION, "test_work", "test_work", "tests/app_test.cpp", 1, 5,
        signature="void test_work()", status="implemented", brief="Verify work.", satisfies=("R-1",),
    )
    model.add_entity(test_entity)
    model.add_edge(Edge(EdgeKind.CALLS, test_entity.usr, target.usr))
    added.append(test_entity)
    files.append("tests/app_test.cpp")
    candidate = proposal(root, steps.BuildResult(True, "built"), steps.TestResult(True, "tested"))
    candidate.model = model
    candidate.delta = steps.Delta(tuple(added), (), (), tuple(files))
    return candidate


def approval_runner(root: Path) -> steps.StepRunner:
    persistence.ProjectStore(root).save_state(
        persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE))
    return steps.StepRunner(
        root, persistence.UserConfig(), build=lambda _root: steps.BuildResult(True, "rebuilt"),
        test=lambda _root, _command: steps.TestResult(True, "retested"),
    )


def allow_promotion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(steps.git, "promote_worktree", lambda _root, _worktree: ["src/app.cpp"])
    monkeypatch.setattr(steps.git, "commit_all", lambda *_args: "commit")


def provider(*, enabled: bool = True) -> steps.agent.Provider:
    return steps.agent.Provider(
        "test-provider", "Test Provider", "test-provider", ("{binary}",), "stdin",
        (steps.agent.Model("test-model", "Test Model"),), enabled, enabled, "sign in",
    )


def implementation_runner(
        root: Path, reply: str, monkeypatch: pytest.MonkeyPatch) -> steps.StepRunner:
    store = persistence.ProjectStore(root)
    model = DerivedModel(str(root))
    model.add_entity(Entity("u:work", Kind.FUNCTION, "work", "app::work", "src/app.cpp", 1,
                            signature="void work()", status="stub"))
    store.save_model(model)
    store.save_state(persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("u:work",), 0))
    runner = steps.StepRunner(
        root, persistence.UserConfig(), invoke=lambda _prompt, _root: reply, attempts=1)
    monkeypatch.setattr(runner, "_prompt_context", lambda: ({}, [], {}))
    return runner


def test_provider_lookup_refuses_unknown_and_disabled_entries(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = steps.StepRunner(tmp_path, persistence.UserConfig(), provider_id="missing")
    monkeypatch.setattr(steps.agent, "load_providers", list)
    with pytest.raises(steps.StepError) as unknown:
        runner._invoke_provider("prompt", tmp_path)
    assert str(unknown.value) == "unknown provider 'missing': choose a listed binary"

    runner.provider_id = "test-provider"
    monkeypatch.setattr(steps.agent, "load_providers", lambda: [provider(enabled=False)])
    monkeypatch.setattr(
        steps.agent, "binary_available",
        lambda *_args: pytest.fail("a disabled provider must be refused before probing its binary"),
    )
    with pytest.raises(steps.StepError) as disabled:
        runner._invoke_provider("prompt", tmp_path)
    assert str(disabled.value) == "Test Provider is disabled; choose an enabled provider"


def test_provider_refuses_missing_binary_nonzero_exit_and_timeout(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = steps.StepRunner(
        tmp_path, persistence.UserConfig(), provider_id="test-provider", binary="chosen-tool")
    monkeypatch.setattr(steps.agent, "load_providers", lambda: [provider()])
    monkeypatch.setattr(steps.agent, "binary_available", lambda *_args: False)
    with pytest.raises(steps.StepError) as missing:
        runner._invoke_provider("prompt", tmp_path)
    assert isinstance(missing.value, steps.ProviderError)
    assert missing.value.diagnosis.code == "missing_tool"
    assert "chosen-tool" in missing.value.diagnosis.detail
    assert missing.value.diagnosis.attempts

    monkeypatch.setattr(steps.agent, "binary_available", lambda *_args: True)
    monkeypatch.setattr(
        steps.agent, "run_provider",
        lambda *_args, **_kwargs: ProcessResult(["chosen-tool"], 7, "", "permission denied"),
    )
    with pytest.raises(steps.StepError) as failed:
        runner._invoke_provider("prompt", tmp_path)
    assert isinstance(failed.value, steps.ProviderError)
    assert failed.value.diagnosis.detail == "permission denied"
    assert "Retried" in failed.value.diagnosis.text()

    monkeypatch.setattr(
        steps.agent, "run_provider",
        lambda *_args, **_kwargs: ProcessResult(["chosen-tool"], -9, "", "", timed_out=True),
    )
    with pytest.raises(steps.StepError) as timed_out:
        runner._invoke_provider("prompt", tmp_path)
    assert isinstance(timed_out.value, steps.ProviderError)
    assert timed_out.value.diagnosis.code == "timeout"
    assert "1800 seconds" in timed_out.value.diagnosis.detail


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("", "the reply contains no JSON object"),
        ('{"title": ]}', "the JSON object does not parse: Expecting value at line 1, column 11"),
    ],
)
def test_code_proposal_preserves_exact_parser_refusal(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: str, expected: str) -> None:
    persistence.ProjectStore(tmp_path).save_state(
        persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE))
    runner = steps.StepRunner(
        tmp_path, persistence.UserConfig(), invoke=lambda _prompt, _root: reply, attempts=1)
    monkeypatch.setattr(runner, "_fresh_worktree", lambda: tmp_path / "worktree")
    monkeypatch.setattr(runner, "_prompt", lambda _request: "prompt")

    candidate = runner.propose(prompt.StepRequest(prompt.ARCHITECTURE, 0))

    assert candidate.response is None and candidate.error == expected
    assert not (tmp_path / "worktree").exists()


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("", "the reply contains no JSON object"),
        ('{"plan": ]}', "the JSON object does not parse: Expecting value at line 1, column 10"),
    ],
)
def test_approach_preserves_exact_parser_refusal(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: str, expected: str) -> None:
    runner = implementation_runner(tmp_path, reply, monkeypatch)

    approach = runner.propose_approach(prompt.StepRequest(prompt.IMPLEMENTATION, 0))

    assert not approach.ok and approach.error == expected
    assert runner.log.records() == []


def test_approach_scope_may_name_planned_entities_and_files(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reply = ('{"plan": "Add a helper and its focused test.", '
             '"entities": ["app::planned_helper"], "files": ["tests/planned_test.cpp"]}')
    runner = implementation_runner(tmp_path, reply, monkeypatch)

    approach = runner.propose_approach(prompt.StepRequest(prompt.IMPLEMENTATION, 0))
    record = runner.approve_approach(approach)

    assert approach.ok and approach.entities == ("app::planned_helper",)
    assert not (tmp_path / "tests/planned_test.cpp").exists()
    assert record.expected_entities == ["app::planned_helper"]
    assert record.expected_files == ["tests/planned_test.cpp"]


def test_compile_failure_skips_tests_and_test_failure_stays_separate(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(steps.git, "working_tree_diff", lambda root: "")
    monkeypatch.setattr(steps.git, "status_changes", lambda root: [])

    failing_build = steps.StepRunner(
        tmp_path, persistence.UserConfig(), build=lambda root: _build(events, False),
        test=lambda root, command: _test(events, False), analyse=lambda root: _analyse(events, root),
    )
    compile_failure = proposal(tmp_path, steps.BuildResult(), steps.TestResult())
    failing_build._build_and_parse(compile_failure)
    assert events == ["build"]
    assert compile_failure.build.ok is False and compile_failure.test.ok is None
    assert compile_failure.error == "the proposal does not build"

    events.clear()
    failing_tests = steps.StepRunner(
        tmp_path, persistence.UserConfig(), build=lambda root: _build(events, True),
        test=lambda root, command: _test(events, False), analyse=lambda root: _analyse(events, root),
    )
    test_failure = proposal(tmp_path, steps.BuildResult(), steps.TestResult())
    failing_tests._build_and_parse(test_failure)
    assert events == ["build", "test", "analyse"]
    assert test_failure.build.ok is True and test_failure.test.ok is False
    assert test_failure.delta is not None and test_failure.error == "the proposal tests fail"

    events.clear()
    tests_not_run = steps.StepRunner(
        tmp_path, persistence.UserConfig(), build=lambda root: _build(events, True),
        test=lambda _root, _command: steps.TestResult(
            None, "No project test command is configured."),
        analyse=lambda root: _analyse(events, root),
    )
    missing_test_gate = proposal(tmp_path, steps.BuildResult(), steps.TestResult())
    tests_not_run._build_and_parse(missing_test_gate)
    assert events == ["build", "analyse"]
    assert missing_test_gate.test.ok is None
    assert missing_test_gate.error == "the proposal tests did not run"


def test_prepare_surfaces_initial_build_failure(tmp_path: Path) -> None:
    persistence.ProjectStore(tmp_path).save_state(
        persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE))
    runner = steps.StepRunner(
        tmp_path, persistence.UserConfig(),
        build=lambda _root: steps.BuildResult(False, "configure failed"),
    )

    with pytest.raises(steps.StepError) as refused:
        runner.prepare()

    assert str(refused.value) == "the project does not build:\nconfigure failed"
    assert runner.log.records() == []


def test_approach_refuses_wrong_phase_and_existing_approval(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE))
    runner = steps.StepRunner(tmp_path, persistence.UserConfig())
    with pytest.raises(steps.StepError) as wrong_phase:
        runner.propose_approach(prompt.StepRequest(prompt.IMPLEMENTATION, 0))
    assert str(wrong_phase.value) == (
        "an implementation approach can be proposed only in the implementation phase")

    runner = implementation_runner(tmp_path, "", monkeypatch)
    state = runner.store.load_state()
    runner.store.save_state(persistence.ProjectState(
        state.phase, state.implementation_queue, state.implementation_cursor,
        approved_approach="Already accepted."))
    with pytest.raises(steps.StepError) as already_approved:
        runner.propose_approach(prompt.StepRequest(prompt.IMPLEMENTATION, 0))
    assert str(already_approved.value) == (
        "an implementation approach for 'app::work' is already approved")


def test_approval_refuses_changed_phase_before_promotion(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "app.cpp"
    source.write_bytes(b"original\n")
    persistence.ProjectStore(tmp_path).save_state(
        persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION))
    runner = steps.StepRunner(tmp_path, persistence.UserConfig())
    monkeypatch.setattr(
        steps.git, "promote_worktree",
        lambda *_args: pytest.fail("phase refusal must precede promotion"),
    )

    with pytest.raises(steps.StepError) as refused:
        runner.approve(proposal(
            tmp_path, steps.BuildResult(True, "built"), steps.TestResult(True, "tested")))

    assert str(refused.value) == (
        "the project phase changed after this architecture proposal; propose again")
    assert source.read_bytes() == b"original\n"


def test_undo_refuses_when_no_approved_code_step_exists(tmp_path: Path) -> None:
    runner = steps.StepRunner(tmp_path, persistence.UserConfig())

    with pytest.raises(steps.StepError) as refused:
        runner.undo()

    assert str(refused.value) == "nothing to undo"
    assert runner.log.records() == []


def test_queue_refusals_name_empty_and_stale_targets(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.save_model(DerivedModel(str(tmp_path)))
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION))
    runner = steps.StepRunner(tmp_path, persistence.UserConfig())
    with pytest.raises(steps.StepError) as empty:
        runner.propose_approach(prompt.StepRequest(prompt.IMPLEMENTATION, 0))
    assert str(empty.value) == (
        "the implementation queue is empty; there are no unimplemented functions")

    store.save_state(persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("u:missing",), 0))
    monkeypatch.setattr(
        steps.implementation_queue, "ensure_state", lambda _store, _model: store.load_state())
    with pytest.raises(steps.StepError) as stale:
        runner.propose_approach(prompt.StepRequest(prompt.IMPLEMENTATION, 0))
    assert str(stale.value) == (
        "the implementation queue target 'u:missing' is absent from the derived model")


def test_approach_approval_refuses_unusable_changed_phase_and_duplicate(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = implementation_runner(tmp_path, "", monkeypatch)
    request = prompt.StepRequest(
        prompt.IMPLEMENTATION, 0, target="u:work", batch=("u:work",))
    unusable = steps.Approach(0, request, "u:work", error="invalid reply")
    with pytest.raises(steps.StepError) as bad:
        runner.approve_approach(unusable)
    assert str(bad.value) == "only a usable implementation approach can be approved"

    usable = steps.Approach(0, request, "u:work", plan="Implement directly.")
    state = runner.store.load_state()
    runner.store.save_state(persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE))
    with pytest.raises(steps.StepError) as phase:
        runner.approve_approach(usable)
    assert str(phase.value) == (
        "the project is no longer in the implementation phase; propose an approach again")

    runner.store.save_state(persistence.ProjectState(
        state.phase, state.implementation_queue, state.implementation_cursor,
        approved_approach="Already accepted."))
    with pytest.raises(steps.StepError) as duplicate:
        runner.approve_approach(usable)
    assert str(duplicate.value) == (
        "an implementation approach for 'app::work' is already approved")


def test_approach_log_failure_restores_unapproved_state(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = implementation_runner(tmp_path, "", monkeypatch)
    original = runner.store.load_state()
    approach = steps.Approach(
        0, prompt.StepRequest(
            prompt.IMPLEMENTATION, 0, target="u:work", batch=("u:work",)),
        "u:work", plan="Implement directly.",
    )
    failure = OSError("step log is unavailable")

    def fail_append(_record: steplog.StepRecord) -> steplog.StepRecord:
        raise failure

    monkeypatch.setattr(runner.log, "append", fail_append)
    with pytest.raises(OSError, match="step log is unavailable") as caught:
        runner.approve_approach(approach)

    assert caught.value is failure
    assert runner.store.load_state() == original


def test_candidate_diff_planning_failures_leave_every_file_byte_identical(
        tmp_path: Path) -> None:
    safe = tmp_path / "safe.txt"
    target = tmp_path / "target.txt"
    safe.write_bytes(b"safe original\n")
    target.write_bytes(b"one\ntwo\n")
    before = {path.name: path.read_bytes() for path in (safe, target)}
    overlap = response.FileChange(
        "target.txt", hunks=(
            response.DiffHunk(1, 1, 1, 1, ("-one\n", "+first\n")),
            response.DiffHunk(1, 1, 1, 1, ("-one\n", "+again\n")),
        ),
    )

    with pytest.raises(ValueError) as refused:
        steps._apply_candidate_files(
            tmp_path, (response.FileChange("safe.txt", "changed\n"), overlap))

    assert str(refused.value) == (
        "unified diff for 'target.txt' does not apply: hunk 2 overlaps an earlier hunk")
    assert {path.name: path.read_bytes() for path in (safe, target)} == before


def test_candidate_diff_refuses_a_symlink_escape_before_writing(
        tmp_path: Path) -> None:
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    safe = root / "safe.txt"
    escaped = outside / "escaped.txt"
    safe.write_bytes(b"safe original\n")
    escaped.write_bytes(b"outside original\n")
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("creating directory symlinks is not available")
    patch = response.FileChange(
        "linked/escaped.txt", hunks=(
            response.DiffHunk(1, 1, 1, 1, ("-outside original\n", "+changed\n")),
        ),
    )

    with pytest.raises(ValueError) as refused:
        steps._apply_candidate_files(
            root, (response.FileChange("safe.txt", "changed\n"), patch))

    assert str(refused.value) == (
        "candidate path 'linked/escaped.txt' leaves the project root")
    assert safe.read_bytes() == b"safe original\n"
    assert escaped.read_bytes() == b"outside original\n"


def test_dirty_tree_and_wrong_head_refuse_undo_before_git_changes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = steps.StepRunner(tmp_path, persistence.UserConfig())
    runner.log.append(steplog.StepRecord(1, prompt.ARCHITECTURE, "approved", title="change"))
    monkeypatch.setattr(steps.git, "is_clean", lambda *_args, **_kwargs: False)
    with pytest.raises(steps.DirtyTree) as dirty:
        runner.undo()
    assert str(dirty.value) == (
        "uncommitted changes in the project: commit them first (Project → Commit manual edits)")

    monkeypatch.setattr(steps.git, "is_clean", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        steps.git, "run_git",
        lambda *_args, **_kwargs: ProcessResult(["git"], 0, "manual commit\n", ""),
    )
    with pytest.raises(steps.StepError) as wrong_head:
        runner.undo()
    assert str(wrong_head.value) == (
        "HEAD is not the commit of step 1 ('manual commit'); undo in git by hand")


def test_cancelled_provider_and_missing_analysis_model_are_explicit(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = steps.StepRunner(tmp_path, persistence.UserConfig(), provider_id="test-provider")
    monkeypatch.setattr(steps.agent, "load_providers", lambda: [provider()])
    monkeypatch.setattr(steps.agent, "binary_available", lambda *_args: True)
    monkeypatch.setattr(
        steps.agent, "run_provider",
        lambda *_args, **_kwargs: ProcessResult(["test-provider"], -9, "", "", cancelled=True),
    )
    with pytest.raises(steps.StepCancelled) as cancelled:
        runner._invoke_provider("prompt", tmp_path)
    assert str(cancelled.value) == "the step was cancelled"

    monkeypatch.setattr(
        steps.session, "analyse_in_child",
        lambda _root: steps.session.AnalysisResult(None, None, ["worker exited without cache"]),
    )
    with pytest.raises(steps.StepError) as missing:
        steps.analyse_tree(tmp_path)
    assert str(missing.value) == "analysis produced no model: worker exited without cache"

    runner.cancel_requested = True
    with pytest.raises(steps.StepCancelled) as pre_cancelled:
        runner._check_cancelled()
    assert str(pre_cancelled.value) == "the step was cancelled"


@pytest.mark.parametrize("refusal", ["grouping refusal", "coverage refusal"])
def test_approval_rechecks_grouping_and_coverage_before_promotion(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refusal: str) -> None:
    runner = approval_runner(tmp_path)
    if refusal == "grouping refusal":
        monkeypatch.setattr(runner, "_grouping_refusal", lambda _proposal: refusal)
    else:
        monkeypatch.setattr(
            steps.rules, "group_test_coverage",
            lambda *_args, **_kwargs: steps.rules.GroupTestCoverage(refusal_reason=refusal),
        )
    monkeypatch.setattr(
        steps.git, "promote_worktree",
        lambda *_args: pytest.fail("refusal must precede promotion"),
    )

    with pytest.raises(steps.StepError) as refused:
        runner.approve(proposal(
            tmp_path, steps.BuildResult(True, "built"), steps.TestResult(True, "tested")))

    assert str(refused.value) == refusal


def test_grouped_proposal_revalidates_the_exact_selected_members(tmp_path: Path) -> None:
    model = DerivedModel(str(tmp_path))
    first = Entity("u:first", Kind.FUNCTION, "get_value", "A::get_value", "a.cpp", 1, 2,
                   status="implemented")
    second = Entity("u:second", Kind.FUNCTION, "set_value", "B::set_value", "b.cpp", 1, 2,
                    status="implemented")
    model.add_entity(first)
    model.add_entity(second)
    candidate = proposal(
        tmp_path, steps.BuildResult(True, "built"), steps.TestResult(True, "tested"))
    candidate.model = model
    candidate.request = prompt.StepRequest(
        prompt.IMPLEMENTATION, 1, target=first.usr,
        batch=(first.usr, second.usr), grouped=True,
    )
    runner = steps.StepRunner(tmp_path, persistence.UserConfig())

    assert runner._grouping_refusal(candidate) == (
        "cannot group B::set_value with A::get_value: entities are in different files")


def test_undo_reverts_the_step_but_preserves_pending_history(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    git.run_git(["init", "-q", "-b", "main"], root)
    source = root / "app.txt"
    source.write_bytes(b"version zero\n")
    runner = steps.StepRunner(root, persistence.UserConfig())
    runner.store.ensure()
    runner.log.append(steplog.StepRecord(0, prompt.ARCHITECTURE, "approved", title="skeleton"))
    git.commit_all(root, "icoda step 0: skeleton", "Test", "test@example.org")
    source.write_bytes(b"version one\n")
    runner.log.append(steplog.StepRecord(1, prompt.ARCHITECTURE, "approved", title="change"))
    git.commit_all(root, "icoda(architecture) step 1: change", "Test", "test@example.org")
    runner.log.append(steplog.StepRecord(2, prompt.ARCHITECTURE, "rejected", reason="keep this"))

    undone = runner.undo()

    assert source.read_bytes() == b"version zero\n"
    assert undone.decision == "undone" and undone.undoes == 1
    assert [(record.number, record.decision) for record in runner.log.records()] == [
        (0, "approved"), (2, "rejected"), (1, "undone"),
    ]
    assert git.is_clean(root)


def test_hard_function_limit_refuses_promotion(tmp_path: Path) -> None:
    runner = approval_runner(tmp_path)

    with pytest.raises(steps.StepError) as refused:
        runner.approve(quality_proposal(tmp_path, end_line=51))

    assert str(refused.value) == "app::work is 51 lines; split it below the hard maximum of 50."


def test_purpose_comment_is_required_even_when_only_documentation_changed(tmp_path: Path) -> None:
    runner = approval_runner(tmp_path)
    candidate = quality_proposal(tmp_path)
    candidate.model.entities["u:work"].brief = ""
    candidate.delta = steps.Delta((), (), (), ("src/app.cpp",))
    with pytest.raises(steps.StepError, match="app::work has no purpose comment"):
        runner.approve(candidate)


def test_hard_function_limit_allows_compliant_promotion(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = approval_runner(tmp_path)
    allow_promotion(monkeypatch)

    record = runner.approve(quality_proposal(tmp_path, end_line=50))

    assert record.decision == "approved"


def test_required_quality_rule_refuses_the_proposal_step(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = quality_proposal(tmp_path, end_line=51)
    assert expected.model is not None and expected.delta is not None
    runner = steps.StepRunner(
        tmp_path, persistence.UserConfig(), build=lambda _root: steps.BuildResult(True, "built"),
        test=lambda _root, _command: steps.TestResult(True, "tested"),
        analyse=lambda _root: expected.model,
    )
    monkeypatch.setattr(steps.git, "working_tree_diff", lambda _root: "")
    monkeypatch.setattr(
        steps.git, "status_changes",
        lambda _root: [git.Change("A", path) for path in expected.delta.files],
    )
    candidate = proposal(tmp_path, steps.BuildResult(), steps.TestResult())

    runner._build_and_parse(candidate)

    assert candidate.error == "app::work is 51 lines; split it below the hard maximum of 50."
    assert not candidate.ok


def _build(events: list[str], ok: bool) -> steps.BuildResult:
    events.append("build")
    return steps.BuildResult(ok, "compiler output")


def _test(events: list[str], ok: bool) -> steps.TestResult:
    events.append("test")
    return steps.TestResult(ok, "test output")


def _analyse(events: list[str], root: Path) -> DerivedModel:
    events.append("analyse")
    return DerivedModel(str(root))


def test_approval_names_failed_gate_and_records_both_successes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE))
    runner = steps.StepRunner(
        tmp_path, persistence.UserConfig(), build=lambda root: steps.BuildResult(True, "rebuilt"),
        test=lambda root, command: steps.TestResult(True, "retested"),
    )

    with pytest.raises(steps.StepError, match="build succeeds"):
        runner.approve(proposal(tmp_path, steps.BuildResult(False, "compile failed"), steps.TestResult()))
    with pytest.raises(steps.StepError, match="tests succeed.*tests failed"):
        runner.approve(proposal(tmp_path, steps.BuildResult(True, "built"),
                                steps.TestResult(False, "test failed")))

    monkeypatch.setattr(steps.git, "promote_worktree", lambda root, worktree: ["x.cpp"])
    monkeypatch.setattr(steps.git, "commit_all", lambda *args: "commit")
    candidate = proposal(tmp_path, steps.BuildResult(True, "built"), steps.TestResult(True, "tested"))
    candidate.selected_tests = ("tests/focused_test.cpp",)
    touched = Entity("u:touched", Kind.FUNCTION, "touched", "touched", "x.cpp", 1,
                     body_hash="approved-hash", brief="Exercises the approved source change.")
    assert candidate.model is not None
    candidate.model.add_entity(touched)
    candidate.delta = steps.Delta((), (), (touched,), ("x.cpp",))
    approved = runner.approve(candidate)
    loaded = runner.log.records()[0]
    assert approved.commit == "commit"
    assert (loaded.build_ok, loaded.build_output) == (True, "rebuilt")
    assert (loaded.test_ok, loaded.test_output) == (True, "retested")
    assert loaded.selected_tests == ["tests/focused_test.cpp"]
    assert loaded.entity_body_hashes == {"u:touched": "approved-hash"}


@pytest.mark.parametrize("failed_gate", ["build", "test"])
def test_approval_gate_failure_rolls_back_promotion(tmp_path: Path, failed_gate: str) -> None:
    root = tmp_path / "project"
    root.mkdir()
    git.run_git(["init", "-q", "-b", "main"], root)
    (root / "existing.cpp").write_text("original\n", encoding="utf-8")
    store = persistence.ProjectStore(root)
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE))
    git.commit_all(root, "initial", "Test", "test@example.org")
    worktree = git.create_worktree(root, tmp_path / "worktree", "icoda/step-1")
    (worktree / "existing.cpp").write_text("promoted\n", encoding="utf-8")
    (worktree / "added.cpp").write_text("added\n", encoding="utf-8")

    def build(_root: Path) -> steps.BuildResult:
        return steps.BuildResult(failed_gate != "build", "build failed")

    def test(_root: Path, _command: Sequence[str]) -> steps.TestResult:
        return steps.TestResult(failed_gate != "test", "test failed")

    runner = steps.StepRunner(root, persistence.UserConfig(), build=build, test=test)
    candidate = proposal(root, steps.BuildResult(True, "built"), steps.TestResult(True, "tested"))
    candidate.worktree = worktree

    failure = "does not build" if failed_gate == "build" else "tests failed"
    with pytest.raises(steps.StepError, match=failure):
        runner.approve(candidate)

    assert (root / "existing.cpp").read_text(encoding="utf-8") == "original\n"
    assert not (root / "added.cpp").exists()
    assert git.is_clean(root)


def test_approval_rolls_back_when_post_promotion_build_raises(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    failure = RuntimeError("injected rebuild crash")
    rolled_back: list[tuple[Path, list[str]]] = []

    def raise_failure(_root: Path) -> steps.BuildResult:
        raise failure

    runner = approval_runner(tmp_path)
    runner.build = raise_failure
    monkeypatch.setattr(steps.git, "promote_worktree", lambda _root, _worktree: ["src/app.cpp"])
    monkeypatch.setattr(
        steps.git, "rollback_promotion", lambda root, files: rolled_back.append((root, files)))

    with pytest.raises(RuntimeError, match="injected rebuild crash") as caught:
        runner.approve(proposal(tmp_path, steps.BuildResult(True, "built"), steps.TestResult(True, "tested")))

    assert caught.value is failure
    assert rolled_back == [(tmp_path, ["src/app.cpp"])]


def test_approval_surfaces_rollback_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = approval_runner(tmp_path)
    runner.build = lambda _root: steps.BuildResult(False, "injected rebuild failure")
    monkeypatch.setattr(steps.git, "promote_worktree", lambda _root, _worktree: ["src/app.cpp"])

    def fail_rollback(_root: Path, _files: Sequence[str]) -> None:
        raise OSError("injected rollback failure")

    monkeypatch.setattr(steps.git, "rollback_promotion", fail_rollback)

    with pytest.raises(OSError, match="injected rollback failure") as caught:
        runner.approve(proposal(tmp_path, steps.BuildResult(True, "built"), steps.TestResult(True, "tested")))

    assert isinstance(caught.value.__context__, steps.StepError)
    assert "promoted project does not build" in str(caught.value.__context__)


def test_approval_rolls_back_and_reraises_keyboard_interrupt(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    interruption = KeyboardInterrupt("injected interrupt")
    rolled_back: list[tuple[Path, list[str]]] = []

    def interrupt_retest(_root: Path, _command: Sequence[str]) -> steps.TestResult:
        raise interruption

    runner = approval_runner(tmp_path)
    runner.test = interrupt_retest
    monkeypatch.setattr(steps.git, "promote_worktree", lambda _root, _worktree: ["src/app.cpp"])
    monkeypatch.setattr(
        steps.git, "rollback_promotion", lambda root, files: rolled_back.append((root, files)))

    with pytest.raises(KeyboardInterrupt, match="injected interrupt") as caught:
        runner.approve(proposal(tmp_path, steps.BuildResult(True, "built"), steps.TestResult(True, "tested")))

    assert caught.value is interruption
    assert rolled_back == [(tmp_path, ["src/app.cpp"])]


@pytest.mark.parametrize("failure_stage", ["log", "commit"])
def test_approval_metadata_or_commit_failure_restores_the_entire_project(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_stage: str) -> None:
    root = tmp_path / "project"
    root.mkdir()
    git.run_git(["init", "-q", "-b", "main"], root)
    source = root / "existing.cpp"
    source.write_bytes(b"original\n")
    store = persistence.ProjectStore(root)
    store.ensure()
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE))
    git.commit_all(root, "initial", "Test", "test@example.org")
    worktree = git.create_worktree(root, tmp_path / "worktree", "icoda/step-1")
    (worktree / "existing.cpp").write_bytes(b"promoted\n")
    (worktree / "added.cpp").write_bytes(b"added\n")
    runner = steps.StepRunner(
        root, persistence.UserConfig(), build=lambda _root: steps.BuildResult(True, "rebuilt"),
        test=lambda _root, _command: steps.TestResult(True, "retested"),
    )
    candidate = proposal(root, steps.BuildResult(True, "built"), steps.TestResult(True, "tested"))
    candidate.worktree = worktree
    before = {path: path.read_bytes() for path in (source, store.state_path)}
    failure = OSError(f"injected {failure_stage} failure")

    if failure_stage == "log":
        monkeypatch.setattr(runner.log, "append", lambda _record: (_ for _ in ()).throw(failure))
    else:
        monkeypatch.setattr(steps.git, "commit_all", lambda *_args: (_ for _ in ()).throw(failure))

    with pytest.raises(OSError, match=f"injected {failure_stage} failure") as caught:
        runner.approve(candidate)

    assert caught.value is failure
    assert {path: path.read_bytes() for path in before} == before
    assert not (root / "added.cpp").exists()
    assert not store.steps_path.exists() and not store.model_path.exists()
    assert git.is_clean(root)


def test_step_log_round_trip_and_legacy_test_result_is_unknown(tmp_path: Path) -> None:
    log = steplog.StepLog(tmp_path / "steps.jsonl")
    log.append(steplog.StepRecord(1, "implementation", "approved", build_ok=True,
                                  build_output="built", test_ok=False, test_output="failed",
                                  selected_tests=["tests/unit_test.cpp", "app::test_work"],
                                  batch=["u:leaf", "u:caller"]))
    current = log.records()[0]
    assert (current.build_ok, current.build_output, current.test_ok, current.test_output) == (
        True, "built", False, "failed")
    assert current.selected_tests == ["tests/unit_test.cpp", "app::test_work"]
    assert current.batch == ["u:leaf", "u:caller"]

    log.path.write_text(
        '{"number": 2, "phase": "implementation", "decision": "approved", "tests_passed": true}\n',
        encoding="utf-8",
    )
    legacy = log.records()[0]
    assert legacy.tests_passed is True
    assert legacy.build_ok is None and legacy.test_ok is None
    assert legacy.round == steplog.CODE_ROUND
    assert legacy.selected_tests == []
    assert legacy.batch == []


def test_delta_pairs_renames_carries_status_and_rejects_unknown_or_changed_bodies() -> None:
    before, after = DerivedModel("/p"), DerivedModel("/p")
    before.add_entity(Entity("u:old", Kind.FUNCTION, "old", "scope::old", "old.cpp", 1,
                             signature="int old() const", status="tested", body_hash="same"))
    before.add_entity(Entity("u:unknown-old", Kind.FUNCTION, "unknown_old", "unknown_old", "x.cpp", 1,
                             signature="void unknown_old()"))
    before.add_entity(Entity("u:changed-old", Kind.FUNCTION, "changed_old", "changed_old", "x.cpp", 2,
                             signature="void changed_old()", body_hash="before"))
    before.add_entity(Entity("u:signature-old", Kind.FUNCTION, "signature_old", "signature_old", "x.cpp", 3,
                             signature="void signature_old(int)", body_hash="signature"))
    after.add_entity(Entity("u:new", Kind.FUNCTION, "new", "scope::new", "new.cpp", 4,
                            signature="int new() const", body_hash="same"))
    after.add_entity(Entity("u:unknown-new", Kind.FUNCTION, "unknown_new", "unknown_new", "x.cpp", 4,
                            signature="void unknown_new()"))
    after.add_entity(Entity("u:changed-new", Kind.FUNCTION, "changed_new", "changed_new", "x.cpp", 5,
                            signature="void changed_new()", body_hash="after"))
    after.add_entity(Entity("u:signature-new", Kind.FUNCTION, "signature_new", "signature_new", "x.cpp", 6,
                            signature="void signature_new(double)", body_hash="signature"))

    delta = steps.compute_delta(before, after, ["old.cpp", "new.cpp", "x.cpp"])

    assert [(pair.before.usr, pair.after.usr) for pair in delta.renamed] == [
        ("u:old", "u:new"), ("u:signature-old", "u:signature-new")]
    assert after.entities["u:new"].status == "tested"
    assert {entity.usr for entity in delta.removed} == {"u:unknown-old", "u:changed-old"}
    assert {entity.usr for entity in delta.added} == {"u:unknown-new", "u:changed-new"}
    assert delta.signature_changes == (
        steps.SignatureChange("u:signature-new", "signature_new",
                              "void signature_old(int)", "void signature_new(double)"),)


def test_delta_classifies_only_signature_changes_to_existing_entities() -> None:
    before, after = DerivedModel("/p"), DerivedModel("/p")
    before.add_entity(Entity("u:unchanged", Kind.FUNCTION, "unchanged", "app::unchanged", "x.cpp", 1,
                             signature="int unchanged(int)", body_hash="same"))
    before.add_entity(Entity("u:parameter", Kind.FUNCTION, "parameter", "app::parameter", "x.cpp", 2,
                             signature="void parameter(int)", body_hash="same"))
    before.add_entity(Entity("u:return", Kind.FUNCTION, "return_value", "app::return_value", "x.cpp", 3,
                             signature="int return_value()", body_hash="same"))
    before.add_entity(Entity("u:body", Kind.FUNCTION, "body", "app::body", "x.cpp", 4,
                             signature="void body()", body_hash="old"))
    before.add_entity(Entity("u:removed", Kind.FUNCTION, "removed", "app::removed", "x.cpp", 5,
                             signature="void removed()", body_hash="removed"))
    after.add_entity(Entity("u:unchanged", Kind.FUNCTION, "unchanged", "app::unchanged", "x.cpp", 1,
                            signature="int unchanged(int)", body_hash="same"))
    after.add_entity(Entity("u:parameter", Kind.FUNCTION, "parameter", "app::parameter", "x.cpp", 2,
                            signature="void parameter(int, double)", body_hash="same"))
    after.add_entity(Entity("u:return", Kind.FUNCTION, "return_value", "app::return_value", "x.cpp", 3,
                            signature="long return_value()", body_hash="same"))
    after.add_entity(Entity("u:body", Kind.FUNCTION, "body", "app::body", "x.cpp", 4,
                            signature="void body()", body_hash="new"))
    after.add_entity(Entity("u:added", Kind.FUNCTION, "added", "app::added", "x.cpp", 6,
                            signature="void added(int)", body_hash="added"))

    delta = steps.compute_delta(before, after, ["x.cpp"])

    assert delta.signature_changes == (
        steps.SignatureChange("u:parameter", "app::parameter",
                              "void parameter(int)", "void parameter(int, double)"),
        steps.SignatureChange("u:return", "app::return_value",
                              "int return_value()", "long return_value()"),
    )


def test_delta_classifies_a_removed_parameter_as_one_exact_signature_change() -> None:
    before, after = DerivedModel("/p"), DerivedModel("/p")
    before.add_entity(Entity("u:f", Kind.FUNCTION, "f", "app::f", "x.cpp", 1,
                             signature="void f(int value, double scale)", body_hash="same"))
    after.add_entity(Entity("u:f", Kind.FUNCTION, "f", "app::f", "x.cpp", 1,
                            signature="void f(int value)", body_hash="same"))
    assert steps.compute_delta(before, after, ["x.cpp"]).signature_changes == (
        steps.SignatureChange("u:f", "app::f", "void f(int value, double scale)", "void f(int value)"),)


@pytest.mark.parametrize(
    ("previous_signature", "proposed_signature"),
    [
        ("void f(int value)", "void f(int value, double scale)"),
        ("int f()", "long f()"),
    ],
)
def test_delta_classifies_an_added_parameter_or_return_change_as_one_exact_entry(
        previous_signature: str, proposed_signature: str) -> None:
    before, after = DerivedModel("/p"), DerivedModel("/p")
    before.add_entity(Entity("u:f", Kind.FUNCTION, "f", "app::f", "x.cpp", 1,
                             signature=previous_signature, body_hash="same"))
    after.add_entity(Entity("u:f", Kind.FUNCTION, "f", "app::f", "x.cpp", 1,
                            signature=proposed_signature, body_hash="same"))
    assert steps.compute_delta(before, after, ["x.cpp"]).signature_changes == (
        steps.SignatureChange("u:f", "app::f", previous_signature, proposed_signature),)


@pytest.mark.parametrize(
    ("before_entity", "after_entity", "expected"),
    [
        (Entity("u:f", Kind.FUNCTION, "f", "app::f", "x.cpp", 1,
                signature="int f()", body_hash="same"),
         Entity("u:f", Kind.FUNCTION, "f", "app::f", "x.cpp", 1,
                signature="int f()", body_hash="same"), ()),
        (Entity("u:f", Kind.FUNCTION, "f", "app::f", "x.cpp", 1,
                signature="int f()", body_hash="old"),
         Entity("u:f", Kind.FUNCTION, "f", "app::f", "x.cpp", 1,
                signature="int f()", body_hash="new"), ()),
        (None, Entity("u:new", Kind.FUNCTION, "new", "app::new", "x.cpp", 1,
                      signature="int new(int)", body_hash="new"), ()),
        (Entity("u:old", Kind.FUNCTION, "old", "app::old", "x.cpp", 1,
                signature="int old(int)", body_hash="old"), None, ()),
    ],
)
def test_delta_signature_change_exclusions(
        before_entity: Entity | None, after_entity: Entity | None,
        expected: tuple[steps.SignatureChange, ...]) -> None:
    before, after = DerivedModel("/p"), DerivedModel("/p")
    if before_entity is not None:
        before.add_entity(before_entity)
    if after_entity is not None:
        after.add_entity(after_entity)
    assert steps.compute_delta(before, after, ["x.cpp"]).signature_changes == expected


def test_body_hash_changes_a_same_usr_entity_delta() -> None:
    before, after = DerivedModel("/p"), DerivedModel("/p")
    before.add_entity(Entity("u:f", Kind.FUNCTION, "f", "f", "f.cpp", 1,
                             signature="int f()", body_hash="old"))
    after.add_entity(Entity("u:f", Kind.FUNCTION, "f", "f", "f.cpp", 1,
                            signature="int f()", body_hash="new"))
    assert [entity.usr for entity in steps.compute_delta(before, after, ["f.cpp"]).changed] == ["u:f"]


def test_step_log_round_trips_rename_pairs_and_applies_status_continuity(tmp_path: Path) -> None:
    log = steplog.StepLog(tmp_path / "steps.jsonl")
    log.append(steplog.StepRecord(0, "architecture", "approved", entities_added=["u:old"]))
    log.append(steplog.StepRecord(1, "implementation", "approved", entities_changed=["u:old"], test_ok=True))
    log.append(steplog.StepRecord(2, "implementation", "approved",
                                  entities_renamed=[("u:old", "u:new")], test_ok=True))
    loaded = log.records()
    assert loaded[2].entities_renamed == [("u:old", "u:new")]

    model = DerivedModel("/p")
    model.add_entity(Entity("u:new", Kind.FUNCTION, "new", "new", "f.cpp", 1))
    steplog.apply_statuses(model, log)
    assert model.entities["u:new"].status == "tested"

    log.path.write_text('{"number": 3, "phase": "implementation", "decision": "approved"}\n', encoding="utf-8")
    assert log.records()[0].entities_renamed == []


def test_approach_decision_round_trips_without_advancing_code_steps(tmp_path: Path) -> None:
    log = steplog.StepLog(tmp_path / "steps.jsonl")
    logged = steplog.StepRecord(2, "implementation", "approved", round=steplog.APPROACH_ROUND,
                                rationale="Use std::ranges.", expected_entities=["app::work"],
                                expected_files=["src/app.cpp"])
    log.append(logged)
    loaded = log.records()[0]
    assert (loaded.round, loaded.decision, loaded.rationale) == ("approach", "approved", "Use std::ranges.")
    assert loaded.expected_entities == ["app::work"] and loaded.expected_files == ["src/app.cpp"]
    assert log.next_number() == 0 and log.approved() == []


def test_runner_builds_targeted_and_full_commands_from_persisted_state(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    command = ("project-test", "--all")
    store = persistence.ProjectStore(tmp_path)
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION, test_command=command))
    model = DerivedModel(str(tmp_path))
    model.add_entity(Entity("u:target", Kind.FUNCTION, "target", "app::target", "src/app.cpp", 1))
    model.add_entity(Entity("u:test", Kind.FUNCTION, "test_target", "test::target", "tests/app_test.cpp", 1))
    model.add_entity(Entity("u:unreached", Kind.FUNCTION, "unreached", "app::unreached", "src/app.cpp", 5))
    model.add_entity(Entity("u:other", Kind.FUNCTION, "other", "app::other", "src/app.cpp", 7))
    model.add_entity(Entity("u:test-other", Kind.FUNCTION, "test_other", "test::other",
                            "tests/other_test.cpp", 1))
    model.add_edge(Edge(EdgeKind.CALLS, "u:test", "u:target"))
    model.add_edge(Edge(EdgeKind.CALLS, "u:test-other", "u:other"))
    store.save_model(model)
    seen: list[tuple[Path, tuple[str, ...]]] = []

    def run(root: Path, configured: Sequence[str]) -> steps.TestResult:
        seen.append((root, tuple(configured)))
        return steps.TestResult(True, "ok")

    runner = steps.StepRunner(tmp_path, persistence.UserConfig(),
                              build=lambda root: steps.BuildResult(True, "built"), test=run,
                              analyse=lambda root: model)
    monkeypatch.setattr(steps.git, "working_tree_diff", lambda root: "")
    monkeypatch.setattr(steps.git, "status_changes", lambda root: [])
    targeted = proposal(tmp_path, steps.BuildResult(), steps.TestResult())
    targeted.request = prompt.StepRequest(prompt.IMPLEMENTATION, 1, target="u:target")
    runner._build_and_parse(targeted)
    full = proposal(tmp_path, steps.BuildResult(), steps.TestResult())
    full.request = prompt.StepRequest(prompt.IMPLEMENTATION, 1, target="u:unreached")
    runner._build_and_parse(full)
    batched = proposal(tmp_path, steps.BuildResult(), steps.TestResult())
    batched.request = prompt.StepRequest(
        prompt.IMPLEMENTATION, 1, target="u:target", batch=("u:target", "u:other"))
    runner._build_and_parse(batched)
    assert targeted.selected_tests == ("tests/app_test.cpp",) and full.selected_tests == ()
    assert batched.selected_tests == ("tests/app_test.cpp", "tests/other_test.cpp")
    assert seen == [
        (tmp_path / "worktree", ("project-test", "--all", "tests/app_test.cpp")),
        (tmp_path / "worktree", command),
        (tmp_path / "worktree", ("project-test", "--all", "tests/app_test.cpp", "tests/other_test.cpp")),
    ]
