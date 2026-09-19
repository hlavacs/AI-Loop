"""Compile commands, the shadow parse, extraction facts on the sample project, cache and stale handling."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from icoda_core import analysis, toolchain
from icoda_core.bodyhash import body_hash
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, Kind

SAMPLE = Path(__file__).resolve().parent / "sample_project"


# --------------------------------------------------------------------------- pure functions

def test_expand_response_files_and_clean_arguments(tmp_path: Path) -> None:
    (tmp_path / "a.modmap").write_text("-fmodule-file=math=CMakeFiles/x/math.pcm\n-fmodule-output=x.pcm\n")
    raw = ["-std=c++23", "@a.modmap", "-MD", "-MT", "t.o", "-MF", "t.d", "-o", "main.o", "-c", "/src/main.cpp"]
    expanded = analysis.expand_response_files(raw, str(tmp_path))
    cleaned = analysis.clean_arguments(expanded, "/src/main.cpp", str(tmp_path))
    assert cleaned == ["-std=c++23", f"-fmodule-file=math={tmp_path / 'CMakeFiles/x/math.pcm'}",
                       f"-fmodule-output={tmp_path / 'x.pcm'}"]


def test_module_declaration() -> None:
    assert analysis.module_declaration("module;\n#include <x>\nexport module geometry;\n") == ("geometry", "interface")
    assert analysis.module_declaration("module shapes;\nint f();") == ("shapes", "implementation")
    assert analysis.module_declaration("int main() {}") == ("", "source")


def test_parse_doc_comment() -> None:
    brief, satisfies = analysis.parse_doc_comment("/// @brief Sum of the values.\n/// @satisfies R-1, UC-3 R-7\n")
    assert brief == "Sum of the values." and satisfies == ("R-1", "UC-3", "R-7")
    brief, satisfies = analysis.parse_doc_comment("/** First sentence here.\n * More text.\n */")
    assert brief.startswith("First sentence here.") and satisfies == ()


def test_library_name() -> None:
    assert analysis.library_name("/usr/include/c++/11/vector") == "std"
    assert analysis.library_name("/opt/x/vcpkg_installed/arm64-osx/include/fmt/core.h") == "fmt"
    assert analysis.library_name("/opt/x/vcpkg_installed/arm64-osx/include/doctest.h") == "doctest"
    assert analysis.library_name("/home/u/llvm18/lib/clang/18/include/stddef.h", ["/home/u/llvm18/lib/clang/18"]) == "std"


def test_unit_cache_key_changes_with_the_extractor_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "a.cpp"
    source.write_text("int a() { return 1; }\n")
    command = analysis.CompileCommand(str(source), str(tmp_path), ("-std=c++23",), "clang++", False)
    before = analysis.unit_cache_key(command, ["a.cpp"], tmp_path, "clang 22")
    monkeypatch.setattr(analysis, "UNIT_CACHE_VERSION", analysis.UNIT_CACHE_VERSION + 1)
    assert analysis.unit_cache_key(command, ["a.cpp"], tmp_path, "clang 22") != before


def test_unit_result_cache_uses_atomic_write_and_cleans_up_after_mid_write_failure(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "a.cpp"
    source.write_text("int a;\n", encoding="utf-8")
    command = analysis.CompileCommand(str(source), str(tmp_path), (), "clang++", False)
    cache_dir = tmp_path / "cache"
    cache_file = cache_dir / "units" / f"{analysis._sha1(command.file.encode())}.json"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text('{"key": "stale", "result": {"contributing": []}}', encoding="utf-8")
    previous_bytes = cache_file.read_bytes()
    result = analysis.UnitResult(analysis.FileInfo("a.cpp"), ["a.cpp"])

    class ParserStub:
        def parse(self, _command: analysis.CompileCommand) -> tuple[object, None]:
            return object(), None

    class ExtractorStub:
        def extract(self, _unit: object, _shadow: None,
                    _command: analysis.CompileCommand) -> analysis.UnitResult:
            return result

    calls: list[Path] = []
    atomic_write = analysis.persistence._atomic_write_text

    def observed_atomic_write(target: Path, text: str) -> None:
        calls.append(target)
        atomic_write(target, text)

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("injected mid-write failure")

    monkeypatch.setattr(analysis.persistence, "_atomic_write_text", observed_atomic_write)
    monkeypatch.setattr(analysis.persistence.os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="injected mid-write failure"):
        analysis._unit_result(command, ParserStub(), ExtractorStub(), tmp_path, cache_dir, "clang test")

    assert calls == [cache_file]
    assert cache_file.read_bytes() == previous_bytes
    assert sorted(item.name for item in cache_file.parent.iterdir()) == [cache_file.name]


def test_body_hash_ignores_whitespace_and_comments_but_not_statements() -> None:
    compact = "{ const auto url = R\"(https://example.test/a//b)\"; return value + 1; }"
    reformatted = """{
        /* The raw string contains comment markers. */
        const auto url=R"(https://example.test/a//b)";
        return value+1; // formatting-only edit
    }"""
    changed = reformatted.replace("value+1", "value+2")
    assert body_hash(compact) == body_hash(reformatted)
    assert len(body_hash(compact)) == 64 and body_hash(changed) != body_hash(compact)
    assert body_hash(None) == body_hash("") == body_hash(" { /* no statements */ } ") == ""


def test_virtual_member_through_base_pointer_is_uncertain() -> None:
    dispatch = analysis.CallDispatch(member=True, virtual=True, receiver_indirect=True)

    assert analysis.is_uncertain_call(dispatch)


def test_virtual_override_on_concrete_object_is_certain() -> None:
    dispatch = analysis.CallDispatch(member=True, virtual=True, receiver_indirect=False)

    assert not analysis.is_uncertain_call(dispatch)
    assert not analysis.is_uncertain_call(analysis.CallDispatch(
        member=True, virtual=True, receiver_indirect=True, final=True))
    assert not analysis.is_uncertain_call(analysis.CallDispatch(
        member=True, virtual=True, receiver_indirect=True, fully_qualified=True))


def test_non_virtual_member_call_is_certain() -> None:
    dispatch = analysis.CallDispatch(member=True, virtual=False, receiver_indirect=True)

    assert not analysis.is_uncertain_call(dispatch)


def test_free_function_call_is_certain() -> None:
    dispatch = analysis.CallDispatch(member=False, virtual=False, receiver_indirect=False)

    assert not analysis.is_uncertain_call(dispatch)


def test_pair_declarations_merges_header_declaration_with_source_definition() -> None:
    declaration = Entity("c:@F@answer#", Kind.FUNCTION, "answer", "answer", "include/answer.hpp", 4,
                         signature="int answer()", is_definition=False)
    definition = Entity("c:@F@answer#", Kind.FUNCTION, "answer", "answer", "src/answer.cpp", 9, 11,
                        signature="int answer()", body_hash="definition-body")

    paired = analysis.pair_declarations([declaration, definition], [])

    assert len(paired.entities) == 1
    assert paired.entities[0] == Entity(
        "c:@F@answer#", Kind.FUNCTION, "answer", "answer", "src/answer.cpp", 9, 11,
        signature="int answer()", body_hash="definition-body", declaration_file="include/answer.hpp")


def test_pair_declarations_keeps_header_only_declaration_as_one_entity() -> None:
    declaration = Entity("c:@F@pending#", Kind.FUNCTION, "pending", "pending", "include/pending.hpp", 7,
                         signature="void pending()", is_definition=False)

    paired = analysis.pair_declarations([declaration, declaration], [])

    assert len(paired.entities) == 1
    assert not paired.entities[0].is_definition
    assert paired.entities[0].file == paired.entities[0].declaration_file == "include/pending.hpp"


def test_pair_declarations_keeps_different_usrs_in_one_header_separate() -> None:
    declarations = [
        Entity("c:@F@first#", Kind.FUNCTION, "first", "first", "include/api.hpp", 2,
               is_definition=False),
        Entity("c:@F@second#", Kind.FUNCTION, "second", "second", "include/api.hpp", 3,
               is_definition=False),
    ]

    paired = analysis.pair_declarations(declarations, [])

    assert [entity.usr for entity in paired.entities] == ["c:@F@first#", "c:@F@second#"]


def test_pair_declarations_deduplicates_edges_from_both_cursors() -> None:
    entities = [
        Entity("c:@F@convert#", Kind.FUNCTION, "convert", "convert", "include/convert.hpp", 4,
               is_definition=False),
        Entity("c:@F@convert#", Kind.FUNCTION, "convert", "convert", "src/convert.cpp", 8),
        Entity("c:@S@Value", Kind.STRUCT, "Value", "Value", "include/value.hpp", 1),
    ]
    edges = [
        Edge(EdgeKind.USES_TYPE, "c:@F@convert#", "c:@S@Value", "include/convert.hpp", 4),
        Edge(EdgeKind.USES_TYPE, "c:@F@convert#", "c:@S@Value", "src/convert.cpp", 8),
    ]

    paired = analysis.pair_declarations(entities, edges)

    assert paired.edges == (
        Edge(EdgeKind.USES_TYPE, "c:@F@convert#", "c:@S@Value", "src/convert.cpp", 8),)


def test_unit_result_declaration_file_legacy_default() -> None:
    unit = analysis.UnitResult(
        analysis.FileInfo("src/paired.cpp"),
        ["src/paired.cpp"],
        [Entity("u:paired", Kind.FUNCTION, "paired", "paired", "src/paired.cpp", 2,
                declaration_file="include/paired.hpp")],
    )
    payload = unit.to_json()
    payload["entities"][0].pop("declaration_file")

    loaded = analysis.UnitResult.from_json(payload)

    assert loaded.entities[0].declaration_file == ""


# --------------------------------------------------------------------------- with libclang

def _libclang() -> toolchain.Loaded:
    found = toolchain.candidates()
    if not found:
        pytest.skip("no libclang available")
    return toolchain.load(found[0].path)


def _ensure_built(root: Path) -> Path:
    if analysis.find_compile_commands(root) is None:
        if shutil.which("cmake") is None or shutil.which("ninja") is None:
            pytest.skip("cmake/ninja not available to build the sample project")
        env = dict(os.environ)
        if sys.platform == "darwin":
            env.pop("CC", None)
            env.pop("CXX", None)
        else:
            env.setdefault("CC", "clang")
            env.setdefault("CXX", "clang++")
        if subprocess.run(["bash", "build.sh", "debug"], cwd=root, env=env, capture_output=True,
                          check=False).returncode != 0:
            pytest.skip("sample project does not build here")
    commands = analysis.find_compile_commands(root)
    assert commands is not None
    return commands


@pytest.fixture(scope="module")
def sample() -> DerivedModel:
    loaded = _libclang()
    _ensure_built(SAMPLE)
    commands = analysis.load_compile_commands(SAMPLE)
    resource = {c.compiler: r for c in commands if (r := toolchain.resource_dir(c.compiler))}
    return analysis.parse_project(SAMPLE, commands, resource_dirs=resource, libclang_version=loaded.version,
                                  sysroot=toolchain.default_sysroot(), apple=loaded.apple)


def _by_name(model: DerivedModel, qualified: str):
    matches = [e for e in model.entities.values() if e.qualified_name == qualified]
    assert matches, qualified
    return matches[0]


def test_sample_parses_without_errors(sample: DerivedModel) -> None:
    assert not sample.stale
    assert {f.path for f in sample.files.values() if f.errors} == set()
    assert sample.files["src/core/shapes.cppm"].module == "shapes"
    assert sample.files["src/core/shapes.cppm"].unit == "interface"
    assert sample.files["src/third_party/json_lite.h"].unit == "header"


def test_analysis_populates_function_body_hash(tmp_path: Path) -> None:
    loaded = _libclang()
    source = tmp_path / "body.cpp"
    source.write_text("int answer() { return 42; }\n", encoding="utf-8")
    command = analysis.CompileCommand(str(source), str(tmp_path), ("-std=c++20",), "clang++", False)
    model = analysis.parse_project(tmp_path, [command], libclang_version=loaded.version)
    answer = _by_name(model, "answer")
    assert answer.body_hash == body_hash("{ return 42; }")


def test_real_parse_marks_only_base_pointer_virtual_call_uncertain(tmp_path: Path) -> None:
    loaded = _libclang()
    source = tmp_path / "dispatch.cpp"
    source.write_text(
        """struct Base { virtual void run() {} void fixed() {} };
struct Derived final : Base { void run() override {} };
void dispatch(Base* base, Derived concrete) {
  base->run();
  concrete.run();
  base->fixed();
}
""",
        encoding="utf-8",
    )
    command = analysis.CompileCommand(str(source), str(tmp_path), ("-std=c++20",), "clang++", False)

    model = analysis.parse_project(tmp_path, [command], libclang_version=loaded.version)

    dispatch = _by_name(model, "dispatch")
    calls = {
        (model.entities[edge.target].qualified_name, edge.line): edge.uncertain
        for edge in model.callees(dispatch.usr)
    }
    assert calls == {("Base::run", 4): True, ("Derived::run", 5): False, ("Base::fixed", 6): False}


def test_real_parse_pairs_header_declaration_and_source_definition(tmp_path: Path) -> None:
    loaded = _libclang()
    include = tmp_path / "include"
    source_dir = tmp_path / "src"
    include.mkdir()
    source_dir.mkdir()
    header = include / "answer.hpp"
    source = source_dir / "answer.cpp"
    header.write_text("int answer();\n", encoding="utf-8")
    source.write_text('#include "answer.hpp"\nint answer() { return 42; }\n', encoding="utf-8")
    command = analysis.CompileCommand(
        str(source), str(tmp_path), ("-std=c++20", f"-I{include}"), "clang++", False)

    model = analysis.parse_project(tmp_path, [command], libclang_version=loaded.version)

    answers = [entity for entity in model.entities.values() if entity.qualified_name == "answer"]
    assert len(answers) == 1
    assert answers[0].file == "src/answer.cpp"
    assert answers[0].declaration_file == "include/answer.hpp"
    assert answers[0].body_hash == body_hash("{ return 42; }")


def test_main_calls_into_the_simulation(sample: DerivedModel) -> None:
    main = _by_name(sample, "main")
    callees = {sample.entities[e.target].qualified_name for e in sample.callees(main.usr) if e.target in sample.entities}
    assert {"load_config", "Simulation::run", "log"} <= callees
    run = _by_name(sample, "Simulation::run")
    run_callees = {sample.entities[e.target].qualified_name for e in sample.callees(run.usr) if e.target in sample.entities}
    assert "Simulation::draw_all" in run_callees


def test_callable_bodies_are_hashed_and_tests_are_associated(sample: DerivedModel) -> None:
    run = _by_name(sample, "Simulation::run")
    assert len(run.body_hash) == 64
    assert run.test_files == ("tests/smoke_test.cpp",)
    assert _by_name(sample, "Shape::area").body_hash == ""


def test_stack_is_one_entity_with_labelled_edges(sample: DerivedModel) -> None:
    stack = _by_name(sample, "Stack")
    assert stack.template_params == ("T",) and stack.exported and stack.satisfies == ("R-3",)
    assert len([e for e in sample.entities.values() if e.name == "Stack"]) == 1
    push, pop = _by_name(sample, "Stack::push"), _by_name(sample, "Stack::pop")
    labels = {e.label for e in sample.callers(push.usr)} | {e.label for e in sample.callers(pop.usr)}
    assert "int" in labels and any("string" in label for label in labels)


def test_enum_hierarchy_types_and_documentation(sample: DerivedModel) -> None:
    kind = _by_name(sample, "ShapeKind")
    assert [e.value for e in sample.children(kind.usr)] == ["0", "1", "2"]
    assert _by_name(sample, "describe").satisfies == ("R-1",)
    circle, shape = _by_name(sample, "Circle"), _by_name(sample, "Shape")
    assert any(e.source == circle.usr and e.target == shape.usr for e in sample.edges_of(EdgeKind.INHERITS))
    canvas = _by_name(sample, "Canvas")
    canvas_members = {canvas.usr, *(m.usr for m in sample.children(canvas.usr))}
    assert any(e.source in canvas_members and e.target == shape.usr for e in sample.edges_of(EdgeKind.USES_TYPE))
    assert shape.exported and not _by_name(sample, "Shape::area").exported
    assert _by_name(sample, "Shape::area").kind == Kind.METHOD and _by_name(sample, "Shape::area").brief == "Enclosed area."


def test_external_std_node_and_file_relations(sample: DerivedModel) -> None:
    assert "std" in sample.externals and "accumulate" in sample.externals["std"].names
    assert ("src/app/simulation.cppm", "src/render/canvas.cppm", EdgeKind.IMPORTS) in sample.file_edges()
    assert ("src/third_party/json_lite.cppm", "src/third_party/json_lite.h", EdgeKind.INCLUDES) in sample.file_edges()
    assert ("src/render/renderer.cppm", "src/core/shapes.cppm", EdgeKind.CALLS) in sample.file_edges()


def test_cache_makes_the_second_parse_identical(sample: DerivedModel, tmp_path: Path) -> None:
    commands = analysis.load_compile_commands(SAMPLE)
    resource = {c.compiler: r for c in commands if (r := toolchain.resource_dir(c.compiler))}
    first = analysis.parse_project(SAMPLE, commands, resource_dirs=resource, cache_dir=tmp_path,
                                   libclang_version="v", sysroot=toolchain.default_sysroot())
    assert len(list((tmp_path / "units").glob("*.json"))) == len(commands)
    second = analysis.parse_project(SAMPLE, commands, resource_dirs=resource, cache_dir=tmp_path,
                                    libclang_version="v", sysroot=toolchain.default_sysroot())
    assert second.to_json() == first.to_json()


def test_broken_project_keeps_previous_model_marked_stale(tmp_path: Path) -> None:
    _libclang()
    bad = tmp_path / "bad.cpp"
    bad.write_text("int main( { return 0; }\n")
    command = analysis.CompileCommand(str(bad), str(tmp_path), ("-std=c++20",), "clang++", False)
    previous = DerivedModel(str(tmp_path))
    result = analysis.parse_project(tmp_path, [command], previous=previous)
    assert result is previous and result.stale and "bad.cpp" in result.stale_reason


def test_shadow_source_blanks_export_blocks_and_keeps_offsets(tmp_path: Path) -> None:
    _libclang()
    from clang import cindex

    source = b"module;\n#include <vector>\nexport module m;\nexport {\nint f();\n}\nexport int g();\nmodule :private;\n"
    unit = cindex.Index.create().parse("m.cppm", args=["-std=c++20", "-x", "c++-module"],
                                       unsaved_files=[("m.cppm", source.decode())],
                                       options=cindex.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES)
    shadow = analysis.shadow_source(source, list(unit.get_tokens(extent=unit.cursor.extent)))
    assert len(shadow.text) == len(source)
    lines = shadow.text.splitlines()
    assert lines[0] == "module;" and lines[1] == "#include <vector>"
    assert lines[2] == "export module M;"
    assert lines[3].strip() == "" and lines[4] == "int f();" and lines[5].strip() == ""
    assert lines[6] == "       int g();" and lines[7] == "module :private;"
    assert len(shadow.block_ranges) == 1 and len(shadow.export_ranges) == 1


def test_missing_module_flags_are_recovered_from_pcm_files(sample: DerivedModel) -> None:
    """Older CMake writes no module flags into compile_commands.json; the built .pcm files still resolve imports."""
    commands = analysis.load_compile_commands(SAMPLE)
    smoke = next(c for c in commands if c.file.endswith("smoke_test.cpp"))
    stripped = analysis.CompileCommand(smoke.file, smoke.directory,
                                       tuple(a for a in smoke.arguments if not a.startswith("-fmodule-file=")),
                                       smoke.compiler, False)
    resource_path = toolchain.resource_dir(smoke.compiler)
    resource = {smoke.compiler: resource_path} if resource_path else {}
    parser = analysis.Parser(resource, sysroot=toolchain.default_sysroot())
    assert any(a.startswith("-fprebuilt-module-path=") for a in parser.arguments(stripped))
    unit, _ = parser.parse(stripped)
    from clang import cindex

    assert [d.spelling for d in unit.diagnostics if d.severity >= cindex.Diagnostic.Error] == []


def test_libcxx_beside_the_compiler_is_used(tmp_path: Path) -> None:
    prefix = tmp_path / "llvm"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "include" / "c++" / "v1").mkdir(parents=True)
    (prefix / "include" / "c++" / "v1" / "__config").write_text("")
    compiler = prefix / "bin" / "clang++"
    compiler.write_text("")
    expected = ["-nostdinc++", "-isystem", str(prefix / "include/c++/v1")]
    assert analysis.libcxx_arguments(str(compiler), [], platform="darwin") == expected
    assert analysis.libcxx_arguments(str(compiler), ["-stdlib=libc++"], platform="linux") == expected
    assert analysis.libcxx_arguments(str(compiler), [], platform="linux") == []
    assert analysis.libcxx_arguments(str(compiler), ["-nostdinc++"], platform="darwin") == []
    assert analysis.libcxx_arguments("/usr/bin/c++", [], platform="darwin") == []
