"""Real multi-executable CMake projects: distinct mains, exact targets, artifacts, and cancellation."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from icoda_core import (
    analysis,
    executables,
    implementation_queue,
    persistence,
    process,
    steplog,
    steps,
    toolchain,
)
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind, merge_external_names


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, DerivedModel]:
    if not shutil.which("cmake"):
        pytest.skip("CMake unavailable")
    root = tmp_path / "project with spaces"
    model = DerivedModel(str(root))
    for name in ("first", "second"):
        file = f"examples/{name}/main.cpp"
        path = root / file
        path.parent.mkdir(parents=True)
        path.write_text(f'#include <cstdio>\nint {name}() {{ puts("{name}"); return 0; }}\n'
                        f'int main() {{ return {name}(); }}\n')
        model.files[file] = FileInfo(file)
        model.add_entity(Entity(name, Kind.FUNCTION, "main", "main", file, 3))
    (root / "broken.cpp").write_text("this target must not be built\n")
    (root / "CMakeLists.txt").write_text('''cmake_minimum_required(VERSION 3.20)
project(Examples LANGUAGES CXX)
add_executable(first examples/first/main.cpp)
set_target_properties(first PROPERTIES OUTPUT_NAME renamed_program
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/bin/custom")
add_executable(second examples/second/main.cpp)
add_executable(broken broken.cpp)
''')
    configured = process.run_bounded(["cmake", "-S", str(root), "-B", str(root / "build/debug"),
                                      "-DCMAKE_BUILD_TYPE=Debug", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"])
    assert configured.ok, configured.stdout + configured.stderr
    return root, model


def test_two_real_mains_keep_their_own_calls(project) -> None:
    root, _ = project
    candidates = toolchain.candidates()
    if not candidates:
        pytest.skip("libclang unavailable")
    loaded = toolchain.load(candidates[0].path)
    commands = [c for c in analysis.load_compile_commands(root) if "examples" in c.file]
    model = analysis.parse_project(root, commands, libclang_version=loaded.version,
                                   sysroot=toolchain.default_sysroot(), apple=loaded.apple)
    mains = [e for e in model.entities.values() if e.qualified_name == "main"]
    assert len(mains) == 2 and len({e.usr for e in mains}) == 2
    for entry in mains:
        name = Path(entry.file).parent.name
        called = {model.entities[edge.target].name for edge in model.callees(entry.usr)
                  if edge.target in model.entities}
        assert called == {name}


def test_build_and_run_selected_target_use_cmake_artifact(project) -> None:
    root, model = project
    initial = executables.entries(model)
    first = initial[0]
    built = executables.operate(root, model, first, "build", lambda: False)
    assert built.selected.target.name == "first"
    assert built.selected.target.artifact == root / "bin/custom/renamed_program"
    assert built.selected.target.artifact.is_file()
    assert not (root / "build/debug/second").exists()
    assert "--target first" in built.output and built.message == "first: build passed"
    ran = executables.operate(root, model, built.selected, "run", lambda: False)
    assert ran.output.endswith("first\n") and "exit 0" in ran.message
    second = next(e for e in ran.entries if e.target.name == "second")
    ran_second = executables.operate(root, model, second, "run", lambda: False)
    assert ran_second.output.endswith("second\n")
    assert not (root / "build/debug/broken").exists()


def test_shared_main_requires_explicit_target_selection(project) -> None:
    root, model = project
    with (root / "CMakeLists.txt").open("a") as output:
        output.write("add_executable(first_variant examples/first/main.cpp)\n")
    result = executables.operate(root, model, executables.entries(model)[0], "run", lambda: False)
    assert result.selected is None and "Choose" in result.message
    assert {entry.target.name for entry in result.entries if entry.file == "examples/first/main.cpp"} == {
        "first", "first_variant"}
    assert not (root / "bin/custom/renamed_program").exists()
    variant = next(entry for entry in result.entries if entry.target.name == "first_variant")
    assert executables.operate(root, model, variant, "run", lambda: False).output.endswith("first\n")


def test_cancel_after_build_does_not_launch_program(project, monkeypatch) -> None:
    root, model = project
    ready = executables.operate(root, model, executables.entries(model)[0], "refresh", lambda: False)
    original = process.run_bounded
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "--build" in command:
            return process.ProcessResult(command, -15, "", "", cancelled=True)
        return original(command, **kwargs)

    monkeypatch.setattr(process, "run_bounded", run)
    with pytest.raises(steps.StepCancelled):
        executables.operate(root, model, ready.selected, "run", lambda: False)
    assert len(calls) == 2 and all(command[0] == "cmake" for command in calls)


def test_selection_is_required_and_ambiguous_saved_sources_are_not_guessed(project):
    root, model = project
    choices = executables.entries(model)
    assert executables.choose(choices, None) is None
    assert executables.choose(choices, ["removed.cpp", "", ""]) is None
    assert executables.choose((choices[0],), None) == choices[0]
    targets = tuple(executables.Target(name, "Debug", root / "build", root / name,
                                       frozenset({str(root / choices[0].file)})) for name in ("one", "two"))
    variants = executables.entries(model, targets)
    assert executables.choose(variants, choices[0].key) is None
    assert executables.choose(variants, variants[1].key) == variants[1]


def test_scope_follows_dependencies_without_reverse_callers_or_other_mains(tmp_path):
    model = DerivedModel(str(tmp_path), stale=True, stale_reason="source changed")
    for file in ("examples/basic/main.cpp", "tests/smoke.cpp", "src/shared.cpp", "include/shared.hpp"):
        model.files[file] = FileInfo(file)
    for usr, file, name in (("basic", "examples/basic/main.cpp", "main"),
                            ("smoke", "tests/smoke.cpp", "main"), ("shared", "src/shared.cpp", "run")):
        model.add_entity(Entity(usr, Kind.FUNCTION, name, name, file, 1,
                                declaration_file="include/shared.hpp" if usr == "shared" else ""))
    model.add_edge(Edge(EdgeKind.INCLUDES, "examples/basic/main.cpp", "include/shared.hpp"))
    model.add_edge(Edge(EdgeKind.CALLS, "smoke", "shared", "tests/smoke.cpp"))
    model.add_edge(Edge(EdgeKind.CALLS, "smoke", "external:gtest", "tests/smoke.cpp"))
    merge_external_names(model, "gtest", ["assert"])
    before = model.to_json()
    basic, smoke = executables.entries(model)
    scoped = executables.scope_model(model, basic)
    assert set(scoped.files) == {"examples/basic/main.cpp", "include/shared.hpp", "src/shared.cpp"}
    assert set(scoped.entities) == {"basic", "shared"} and not scoped.externals
    assert scoped.stale and scoped.stale_reason == "source changed"
    tests = executables.scope_model(model, smoke)
    assert set(tests.files) == {"tests/smoke.cpp", "src/shared.cpp", "include/shared.hpp"}
    assert set(tests.externals) == {"gtest"}
    empty = executables.scope_model(model, None)
    assert not empty.files and not empty.entities and not empty.edges and not empty.externals
    assert model.to_json() == before


def test_cmake_scope_includes_library_and_uncalled_helpers_but_excludes_other_executable(project):
    root, model = project
    for file in ("shared.cpp", "first_helper.cpp", "second_helper.cpp"):
        (root / file).write_text("// target source\n")
        model.files[file] = FileInfo(file)
    with (root / "CMakeLists.txt").open("a") as output:
        output.write("add_library(shared STATIC shared.cpp)\n"
                     "target_link_libraries(first PRIVATE shared)\n"
                     "target_link_libraries(second PRIVATE shared)\n"
                     "target_sources(first PRIVATE first_helper.cpp)\n"
                     "target_sources(second PRIVATE second_helper.cpp)\n"
                     "add_dependencies(first second)\n")
    choices = executables.operate(root, model, None, "refresh", lambda: False).entries
    first = next(entry for entry in choices if entry.target.name == "first")
    second = next(entry for entry in choices if entry.target.name == "second")
    assert set(executables.scope_model(model, first).files) == {
        "examples/first/main.cpp", "shared.cpp", "first_helper.cpp"}
    assert set(executables.scope_model(model, second).files) == {
        "examples/second/main.cpp", "shared.cpp", "second_helper.cpp"}


def test_legacy_main_history_and_queue_follow_the_original_file(tmp_path) -> None:
    model = DerivedModel(str(tmp_path))
    legacy = "c:@F@main#"
    for name in ("first", "second"):
        file = f"examples/{name}/main.cpp"
        model.add_entity(Entity(f"{legacy}@entry:{file}", Kind.FUNCTION, "main", "main", file, 1))
    store = persistence.ProjectStore(tmp_path)
    log = steplog.StepLog(store.steps_path)
    log.append(steplog.StepRecord(1, "architecture", "approved", entities_added=[legacy],
                                  files=["examples/first/main.cpp"]))
    steplog.apply_statuses(model, log)
    current = f"{legacy}@entry:examples/first/main.cpp"
    assert model.entities[current].status == "stub"
    assert model.entities[f"{legacy}@entry:examples/second/main.cpp"].status == "implemented"
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION,
                     implementation_queue=(legacy,), implementation_override=legacy,
                     approved_approach="old scope"))
    state = implementation_queue.ensure_state(store, model)
    assert state.implementation_queue == (current,) and state.implementation_override == current
    assert state.approved_approach == "" and store.load_state() == state
