"""Build and test outcomes are executed, persisted and approved independently."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from icoda_core import persistence, prompt, response, steplog, steps
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, Kind


def proposal(root: Path, build: steps.BuildResult, test: steps.TestResult) -> steps.Proposal:
    return steps.Proposal(
        1, prompt.StepRequest(prompt.ARCHITECTURE, 1), root / "worktree", attempts=1,
        response=response.StepResponse("A change", "Because.", ()), build=build, test=test,
        model=DerivedModel(str(root)), delta=steps.Delta((), (), (), ("x.cpp",)),
    )


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
                     body_hash="approved-hash")
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
