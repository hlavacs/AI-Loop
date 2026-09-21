"""Prompt assembly: sections, phase rules, feedback, and the model subset around a focus."""

from __future__ import annotations

import pytest

from icoda_core import persistence, prompt, rules, specification, steplog
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind


def small_model() -> DerivedModel:
    model = DerivedModel("/p")
    for f in ("src/main.cpp", "src/app/app.cppm", "src/util/log.cppm", "src/far/far.cppm"):
        model.files[f] = FileInfo(f, unit="source", module=f.split("/")[1] if f.endswith(".cppm") else "")
    model.add_entity(Entity("u:main", Kind.FUNCTION, "main", "main", "src/main.cpp", 3, signature="int main()",
                            status="implemented"))
    model.add_entity(Entity("u:run", Kind.FUNCTION, "run", "app::run", "src/app/app.cppm", 5,
                            signature="int run()", status="stub", satisfies=("UC-1",), brief="Entry point.",
                            test_files=("tests/app_test.cpp",)))
    model.add_entity(Entity("u:log", Kind.FUNCTION, "log", "util::log", "src/util/log.cppm", 2,
                            signature="void log(std::string_view)"))
    model.add_entity(Entity("u:far", Kind.CLASS, "Far", "far::Far", "src/far/far.cppm", 1))
    model.add_edge(Edge(EdgeKind.CALLS, "u:main", "u:run", "src/main.cpp", 4))
    model.add_edge(Edge(EdgeKind.IMPORTS, "src/main.cpp", "src/app/app.cppm", "src/main.cpp", 1))
    model.add_edge(Edge(EdgeKind.CALLS, "u:run", "u:log", "src/app/app.cppm", 6))
    return model


def test_architecture_prompt_has_all_sections() -> None:
    spec = specification.default_specification("Demo")
    spec["use_cases"] = [{"id": "UC-1", "title": "Start the app"}]
    request = prompt.StepRequest(prompt.ARCHITECTURE, 1, "introduce the renderer", max_entities=4,
                                 rejections=("too many classes",), constraints=("keep app::run",),
                                 build_errors="error: x", validation_error="no JSON")
    text = prompt.build_prompt(spec, small_model(), request,
                               state=persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE))
    for expected in ("software architect", "# Specification and code profile", "UC-1: Start the app",
                     "# Current code", "app::run int run() [stub] tests=tests/app_test.cpp @satisfies UC-1 — Entry point.",
                     "relations: calls src/app/app.cppm (1), imports src/app/app.cppm (1)", "# This step",
                     "At most 4 new architecture entities", "Fields and individual enum values", "introduce the renderer",
                     "too many classes", "keep app::run",
                     "error: x", "no JSON", "# Response format", '"rationale"'):
        assert expected in text, expected


@pytest.mark.parametrize("kind", ["architecture", "implementation", "approach"])
def test_every_step_round_requests_a_self_contained_explanation(kind) -> None:
    phase = prompt.ARCHITECTURE if kind == "architecture" else prompt.IMPLEMENTATION
    state = persistence.ProjectState(persistence.ProjectPhase(phase))
    request = prompt.StepRequest(phase, 3, target="u:run")
    build = prompt.build_approach_prompt if kind == "approach" else prompt.build_prompt
    text = build(specification.default_specification("Demo"), small_model(), request, state=state)
    explanation_rules = text.split("# Response format", 1)[1]
    assert prompt.STEP_DESCRIPTION_STYLE in explanation_rules
    assert "senior programmer explaining to a junior programmer exactly what to do next" in explanation_rules
    assert "has not read any previous steps" in explanation_rules
    assert "which project-relative file" in explanation_rules
    assert "Distinguish storing pointers from copying or owning" in explanation_rules
    assert "actual return value or empty behavior" in explanation_rules
    assert "Do not invent missing paths or declarations" in explanation_rules
    assert "up to three" not in explanation_rules and "short overview" not in explanation_rules
    if kind == "approach":
        assert "Do not emit source code" in text and "Code details" in explanation_rules
    elif kind == "architecture":
        assert "No algorithmic code" in text
    else:
        assert "Do not implement other stub functions" in text


def test_python_profile_and_prompt_rules_are_language_appropriate() -> None:
    spec = specification.default_specification("Python demo", "Python")
    assert spec["code_profile"] == {
        "language": "Python",
        "standard": "3.12",
        "modules": False,
        "build": "Python source; no compilation step",
        "platforms": ["macOS", "Linux", "Windows"],
        "test_framework": "pytest",
        "test_runner": "python -m pytest",
        "test_file_convention": "tests/test_<module>.py",
        "source_file_extension": ".py",
        "module_naming": "snake_case",
        "class_naming": "PascalCase",
        "function_naming": "snake_case",
        "library_policy": "PyPI dependencies declared in pyproject.toml",
        "max_function_lines": 30,
        "hard_max_function_lines": 50,
        "max_data_members": 10,
        "max_methods": 15,
        "style_notes": [
            "Use type annotations for public functions and methods.",
            "Every entity carries a docstring and, where a requirement applies, an @satisfies tag.",
            "Platform independence: no platform API without a portable wrapper.",
            ("Place all example and demo source files in the project-root examples/ directory; "
             "use examples/<name>/ for multi-file examples. Keep reusable library code in src/ "
             "and have examples use it."),
        ],
    }
    state = persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE)
    architecture = prompt.build_prompt(
        spec, DerivedModel("/p"), prompt.StepRequest(prompt.ARCHITECTURE, 1), state=state)
    expected_architecture_rule = (
        "- One Python module per concept, in a `.py` source file. Name modules in snake_case, classes in "
        "PascalCase, and functions in snake_case. Follow the `tests/test_<module>.py` test-file convention.")
    assert expected_architecture_rule in architecture
    assert "C++20 module" not in architecture and "headers only" not in architecture
    assert "CMake target lists" not in architecture and "compile and run" not in architecture

    state = persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION)
    implementation = prompt.build_prompt(
        spec, DerivedModel("/p"), prompt.StepRequest(prompt.IMPLEMENTATION, 2), state=state)
    expected_implementation_rule = (
        "- Add or extend its pytest test following `tests/test_<module>.py`; run it with `python -m pytest`, and "
        "make sure it passes.")
    assert expected_implementation_rule in implementation


def test_implementation_prompt_and_skeleton_only_model() -> None:
    spec = specification.default_specification("Demo")
    text = prompt.build_prompt(spec, DerivedModel("/p"), prompt.StepRequest(prompt.IMPLEMENTATION, 7),
                               skeleton_files=["CMakeLists.txt", "src/main.cpp"],
                               state=persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION))
    assert "the implementer" in text and "exactly one function" in text
    assert "only its skeleton so far:\n- CMakeLists.txt\n- src/main.cpp" in text
    assert "Propose the next step yourself" in text and "# Feedback" not in text


def test_current_rule_issues_are_actionable_in_the_next_prompt() -> None:
    issue = rules.Issue("missing-doxygen", "warning", "app::run needs documentation.",
                        "u:run", "src/app/app.cppm", 5)
    text = prompt.build_prompt(
        specification.default_specification("Demo"), small_model(),
        prompt.StepRequest(prompt.ARCHITECTURE, 2),
        state=persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE), issues=(issue,))
    assert "# Current rule-check issues" in text
    assert "[WARNING] missing-doxygen at src/app/app.cppm:5: app::run needs documentation." in text


def test_step_rule_issues_are_scoped_inert_and_report_truncation() -> None:
    model = DerivedModel("/p")
    for index in range(4):
        model.add_entity(Entity(f"u:target:{index}", Kind.FUNCTION, f"target{index}",
                                f"app::target{index}", "src/target.cpp", 10 + index, 70 + index,
                                signature=f"void target{index}(int a, int b, int c, int d, int e, int f)",
                                status="implemented"))
    model.add_entity(Entity("u:clean", Kind.FUNCTION, "clean", "app::clean", "src/clean.cpp", 1, 5,
                            signature="void clean()", status="stub",
                            brief="Clean operation.", satisfies=("R-1",)))
    history = [steplog.StepRecord(1, "implementation", "approved")]
    state = persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION)
    spec = specification.default_specification("Demo")

    clean_request = prompt.StepRequest(prompt.IMPLEMENTATION, 2, target="u:clean", focus=("u:clean",))
    clean = prompt.build_prompt(spec, model, clean_request, state=state,
                                issues=rules.for_step(model, history, clean_request))
    untargeted = prompt.StepRequest(prompt.IMPLEMENTATION, 2, focus=("src/target.cpp",))
    no_target = prompt.build_prompt(spec, model, untargeted, state=state,
                                    issues=rules.for_step(model, history, untargeted))
    empty_history = prompt.build_prompt(spec, model, clean_request, state=state,
                                        issues=rules.for_step(model, [], clean_request))
    batch = tuple(f"u:target:{index}" for index in range(4))
    request = prompt.StepRequest(prompt.IMPLEMENTATION, 2, target=batch[0], batch=batch, focus=batch)
    truncated = prompt.build_prompt(spec, model, request, state=state,
                                    issues=rules.for_step(model, history, request))
    issue_section = truncated.split("# Current rule-check issues\n\n", 1)[1].split("\n\n# This step", 1)[0]

    assert "# Current rule-check issues" not in clean
    assert "# Current rule-check issues" not in no_target
    assert "# Current rule-check issues" not in empty_history
    assert issue_section.endswith("... and 10 more")


def test_implementation_prompt_names_the_exact_queue_target() -> None:
    model = small_model()
    request = prompt.StepRequest(prompt.IMPLEMENTATION, 7, target="u:run", focus=("u:run",))
    text = prompt.build_prompt(specification.default_specification("Demo"), model, request,
                               state=persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION))
    assert "Implement exactly this function: `app::run int run()` (USR `u:run`)" in text
    assert "Do not implement other stub functions" in text


def test_implementation_and_approach_prompts_name_every_batch_member_only() -> None:
    model = small_model()
    model.add_entity(Entity("u:other", Kind.FUNCTION, "other", "app::other", "src/app/app.cppm", 9,
                            signature="void other()", status="stub"))
    request = prompt.StepRequest(prompt.IMPLEMENTATION, 8, target="u:run",
                                 batch=("u:run", "u:log"), focus=("u:run", "u:log"))
    state = persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION,
                                     implementation_batch_size=2)

    code = prompt.build_prompt(specification.default_specification("Demo"), model, request, state=state)
    approach = prompt.build_approach_prompt(
        specification.default_specification("Demo"), model, request, state=state)

    for text in (code, approach):
        assert "app::run int run()" in text and "util::log void log(std::string_view)" in text
        assert "u:run" in text and "u:log" in text
    assert "Do not implement any function outside this batch" in code
    assert "app::other" not in code.split("# This step", 1)[1]
    assert "Do not plan implementation of any function outside this batch" in approach


def test_approach_prompt_names_target_and_forbids_file_changes() -> None:
    model = small_model()
    request = prompt.StepRequest(prompt.IMPLEMENTATION, 7, "keep it short", target="u:run", focus=("u:run",))
    state = persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION)
    text = prompt.build_approach_prompt(specification.default_specification("Demo"), model, request, state=state)
    assert "approach for exactly this function: `app::run int run()` (USR `u:run`)" in text
    assert "STL algorithms/containers" in text and "estimated line count" in text and "trade-offs" in text
    assert "Do not emit source code, patches, diffs, file contents, or file changes" in text
    assert '"plan"' in text and '"entities"' in text and '"files"' in text


def test_implementation_prompt_contains_the_persisted_approved_approach() -> None:
    state = persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION,
                                     approved_approach="Use std::ranges::find and keep the signature.")
    request = prompt.StepRequest(prompt.IMPLEMENTATION, 7, target="u:run", focus=("u:run",))
    text = prompt.build_prompt(specification.default_specification("Demo"), small_model(), request, state=state)
    assert "# Approved approach" in text
    assert "Use std::ranges::find and keep the signature." in text


def test_persisted_phase_overrides_the_request_phase_rules() -> None:
    spec = specification.default_specification("Demo")
    request = prompt.StepRequest(prompt.IMPLEMENTATION, 3, max_entities=2)
    architecture = prompt.build_prompt(
        spec, DerivedModel("/p"), request,
        state=persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE),
    )
    assert "software architect" in architecture and "At most 2 new architecture entities" in architecture
    assert "exactly one function" not in architecture

    implementation = prompt.build_prompt(
        spec, DerivedModel("/p"), request,
        state=persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION),
    )
    assert "the implementer" in implementation and "exactly one function" in implementation
    assert "new architecture entities" not in implementation


def test_subset_follows_the_focus_and_lists_calls() -> None:
    model = small_model()
    assert prompt.subset_files(model, ["src/app/app.cppm"]) == ["src/app/app.cppm", "src/main.cpp",
                                                                "src/util/log.cppm"]
    assert prompt.subset_files(model, ["u:log"]) == ["src/util/log.cppm", "src/app/app.cppm"]
    text = prompt.describe_model(model, ["u:log"])
    assert "app::run calls util::log" in text and "Other files (not shown): src/far/far.cppm, src/main.cpp" in text
    assert "far::Far" not in text
