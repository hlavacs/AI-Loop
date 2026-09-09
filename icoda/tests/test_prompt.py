"""Prompt assembly: sections, phase rules, feedback, and the model subset around a focus."""

from __future__ import annotations

from icoda_core import prompt, specification
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
    text = prompt.build_prompt(spec, small_model(), request)
    for expected in ("software architect", "# Specification and code profile", "UC-1: Start the app",
                     "# Current code", "app::run int run() [stub] tests=tests/app_test.cpp @satisfies UC-1 — Entry point.",
                     "relations: calls src/app/app.cppm (1), imports src/app/app.cppm (1)", "# This step",
                     "At most 4 new architecture entities", "Fields and individual enum values", "introduce the renderer",
                     "too many classes", "keep app::run",
                     "error: x", "no JSON", "# Response format", '"rationale"'):
        assert expected in text, expected


def test_implementation_prompt_and_skeleton_only_model() -> None:
    spec = specification.default_specification("Demo")
    text = prompt.build_prompt(spec, DerivedModel("/p"), prompt.StepRequest(prompt.IMPLEMENTATION, 7),
                               skeleton_files=["CMakeLists.txt", "src/main.cpp"])
    assert "the implementer" in text and "exactly one function" in text
    assert "only its skeleton so far:\n- CMakeLists.txt\n- src/main.cpp" in text
    assert "Propose the next step yourself" in text and "# Feedback" not in text


def test_subset_follows_the_focus_and_lists_calls() -> None:
    model = small_model()
    assert prompt.subset_files(model, ["src/app/app.cppm"]) == ["src/app/app.cppm", "src/main.cpp",
                                                                "src/util/log.cppm"]
    assert prompt.subset_files(model, ["u:log"]) == ["src/util/log.cppm", "src/app/app.cppm"]
    text = prompt.describe_model(model, ["u:log"])
    assert "app::run calls util::log" in text and "Other files (not shown): src/far/far.cppm, src/main.cpp" in text
    assert "far::Far" not in text
