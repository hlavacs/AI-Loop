"""Clang-free rule checks and their Tk-stub issue overview."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

from icoda_core import persistence, prompt, rules, steplog
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, Kind
from icoda_gui import issue_view


def violating_model(reverse: bool = False) -> DerivedModel:
    model = DerivedModel("/project")
    entities = [
        Entity("u:large", Kind.FUNCTION, "large", "app::large", "src/app.cpp", 10, 70,
               signature="void large(int a, int b, int c, int d, int e, int f)", status="implemented"),
        Entity("u:class", Kind.CLASS, "Crowded", "app::Crowded", "src/types.cpp", 2,
               brief="Crowded type.", satisfies=("R-1",)),
        *(Entity(f"u:field:{index}", Kind.FIELD, f"f{index}", f"app::Crowded::f{index}",
                 "src/types.cpp", 3 + index, parent="u:class", brief="Stored value.", satisfies=("R-1",))
          for index in range(11)),
        *(Entity(f"u:method:{index}", Kind.METHOD, f"m{index}", f"app::Crowded::m{index}",
                 "src/types.cpp", 20 + index, 20 + index, parent="u:class", signature=f"void m{index}()",
                 status="stub", brief="Operation.", satisfies=("R-1",))
          for index in range(16)),
        Entity("u:platform", Kind.FUNCTION, "save", "app::save", "src/app.cpp", 80, 84,
               signature="void save()", status="stub", brief="Save data.", satisfies=("R-2",)),
    ]
    for entity in reversed(entities) if reverse else entities:
        model.add_entity(entity)
    model.add_edge(Edge(EdgeKind.CALLS, "u:platform", "external:windows", "src/app.cpp", 82, "CreateFileW"))
    return model


def clean_model() -> DerivedModel:
    model = DerivedModel("/project")
    model.add_entity(Entity("u:small", Kind.FUNCTION, "small", "app::small", "src/app.cpp", 2, 8,
                            signature="int small(int value)", status="tested",
                            brief="Return a small value.", satisfies=("R-1",)))
    model.add_entity(Entity("u:test", Kind.FUNCTION, "test_small", "tests::test_small", "tests/app_test.cpp", 2, 8,
                            signature="void test_small()", status="implemented",
                            brief="Verify small.", satisfies=("R-1",)))
    model.add_edge(Edge(EdgeKind.CALLS, "u:test", "u:small", "tests/app_test.cpp", 5))
    return model


def passed_record() -> steplog.StepRecord:
    return steplog.StepRecord(1, "implementation", "approved", test_ok=True,
                              selected_tests=["tests/app_test.cpp"])


def test_each_documented_rule_has_an_actionable_issue() -> None:
    issues = rules.check(violating_model(), [])
    by_rule = {issue.rule_id: issue for issue in issues}
    assert {"function-lines", "many-parameters", "data-members", "methods", "missing-doxygen",
            "missing-satisfies", "platform-api", "missing-test"}.issubset(by_rule)
    assert by_rule["function-lines"].severity == "error"
    assert by_rule["platform-api"].severity == "error"
    assert all(issue.usr and issue.file and issue.line > 0 and issue.message for issue in issues)
    assert "hard maximum" in by_rule["function-lines"].message
    assert "portable wrapper" in by_rule["platform-api"].message


def test_function_guideline_warns_and_portable_wrapper_is_allowed() -> None:
    model = DerivedModel("/project")
    model.add_entity(Entity("u:f", Kind.FUNCTION, "f", "app::f", "src/platform/windows.cpp", 1, 31,
                            signature="void f()", status="stub", brief="Wrapper.", satisfies=("R-1",)))
    model.add_edge(Edge(EdgeKind.CALLS, "u:f", "external:windows", "src/platform/windows.cpp", 3, "CreateFileW"))
    issues = rules.check(model, [])
    assert [(issue.rule_id, issue.severity) for issue in issues] == [("function-lines", "warning")]


def test_clean_model_has_no_issues_and_uses_successful_test_evidence() -> None:
    assert rules.check(clean_model(), [passed_record()]) == ()


def test_order_is_deterministic_across_entity_insertion_order() -> None:
    assert rules.check(violating_model(), []) == rules.check(violating_model(reverse=True), [])


def test_step_selection_is_relevant_bounded_and_deterministic() -> None:
    def model_with_many_issues(reverse: bool) -> DerivedModel:
        model = DerivedModel("/project")
        entities = [
            *(Entity(f"u:target:{index}", Kind.FUNCTION, f"target{index}", f"app::target{index}",
                     f"src/target{index}.cpp", 10, 70,
                     signature=f"void target{index}(int a, int b, int c, int d, int e, int f)",
                     status="implemented")
              for index in range(3)),
            *(Entity(f"u:other:{index}", Kind.FUNCTION, f"other{index}", f"app::other{index}",
                     f"src/other{index}.cpp", 10, 70,
                     signature=f"void other{index}(int a, int b, int c, int d, int e, int f)",
                     status="implemented")
              for index in range(12)),
        ]
        for entity in reversed(entities) if reverse else entities:
            model.add_entity(entity)
        return model

    targets = tuple(f"u:target:{index}" for index in range(3))
    request = prompt.StepRequest(prompt.IMPLEMENTATION, 4, target=targets[0], batch=targets, focus=targets)
    history = [steplog.StepRecord(1, "implementation", "approved")]
    first = rules.for_step(model_with_many_issues(False), history, request)
    second = rules.for_step(model_with_many_issues(True), history, request)

    assert len(first) == rules.MAX_STEP_ISSUES == 10
    assert first.omitted == 5
    assert all(issue.usr in targets for issue in first)
    assert [issue.severity for issue in first] == sorted(
        (issue.severity for issue in first), key=lambda severity: severity != "error")
    assert first == second


def test_step_selection_includes_other_issues_in_a_target_file() -> None:
    model = DerivedModel("/project")
    model.add_entity(Entity("u:target", Kind.FUNCTION, "target", "app::target", "src/target.cpp", 2, 4,
                            signature="void target()", status="stub",
                            brief="Target operation.", satisfies=("R-1",)))
    model.add_entity(Entity("u:nearby", Kind.CLASS, "Nearby", "app::Nearby", "src/target.cpp", 8))
    model.add_entity(Entity("u:far", Kind.CLASS, "Far", "app::Far", "src/far.cpp", 8))
    request = prompt.StepRequest(prompt.IMPLEMENTATION, 2, target="u:target", focus=("u:target",))

    selected = rules.for_step(model, [steplog.StepRecord(1, "architecture", "approved")], request)

    assert {issue.usr for issue in selected} == {"u:nearby"}


def test_old_empty_history_and_project_state_are_usable(tmp_path: Path) -> None:
    old = DerivedModel.from_json(DerivedModel("/old").to_json())
    assert rules.check(old, steplog.StepLog(tmp_path / "missing.jsonl")) == ()
    assert rules.check(old, persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE)) == ()


def test_step_selection_accepts_old_empty_history_and_project_state(tmp_path: Path) -> None:
    old = DerivedModel.from_json(DerivedModel("/old").to_json())
    request = prompt.StepRequest(prompt.IMPLEMENTATION, 1, target="u:old")
    assert not rules.for_step(old, steplog.StepLog(tmp_path / "missing.jsonl"), request)
    assert not rules.for_step(old, persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE), request)


def test_issue_overview_renders_and_opens_source_and_handles_empty(monkeypatch: Any) -> None:
    opened: list[tuple[str, int]] = []
    overview = issue_view.IssueOverview(tk.Tk(), lambda file, line: opened.append((file, line)))
    rendered: list[tuple[Any, ...]] = []
    monkeypatch.setattr(overview.tree, "insert",
                        lambda _parent, _where, **kwargs: rendered.append(tuple(kwargs["values"])))

    overview.show(violating_model(), [])
    assert "issues" in overview.summary_var.get() and any(row[0] == "Error" for row in rendered)
    assert any(row[1] == "platform-api" and "portable wrapper" in row[3] for row in rendered)
    platform_index = next(index for index, issue in enumerate(overview.issues) if issue.rule_id == "platform-api")
    monkeypatch.setattr(overview.tree, "selection", lambda: (str(platform_index),))
    overview._open_selected(None)
    assert opened == [("src/app.cpp", 82)]

    rendered.clear()
    overview.show(DerivedModel("/empty"), steplog.StepLog(Path("/missing/steps.jsonl")))
    assert overview.summary_var.get() == "Rule checks: 0 issues · 0 errors · 0 warnings"
    assert overview.note_var.get().startswith("No rule-check issues") and rendered == []
