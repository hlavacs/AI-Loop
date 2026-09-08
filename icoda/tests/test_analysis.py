"""Compile commands, the shadow parse, extraction facts on the sample project, cache and stale handling."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from icoda_core import analysis, toolchain
from icoda_core.model import DerivedModel, EdgeKind, Kind

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
        env = dict(os.environ, CC=os.environ.get("CC", "clang"), CXX=os.environ.get("CXX", "clang++"))
        for step in (["cmake", "--preset", "debug"], ["cmake", "--build", "--preset", "debug"]):
            if subprocess.run(step, cwd=root, env=env, capture_output=True, check=False).returncode != 0:
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
    return analysis.parse_project(SAMPLE, commands, resource_dirs=resource, libclang_version=loaded.version)


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


def test_main_calls_into_the_simulation(sample: DerivedModel) -> None:
    main = _by_name(sample, "main")
    callees = {sample.entities[e.target].qualified_name for e in sample.callees(main.usr) if e.target in sample.entities}
    assert {"load_config", "Simulation::run", "log"} <= callees
    run = _by_name(sample, "Simulation::run")
    run_callees = {sample.entities[e.target].qualified_name for e in sample.callees(run.usr) if e.target in sample.entities}
    assert "Simulation::draw_all" in run_callees


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
    first = analysis.parse_project(SAMPLE, commands, resource_dirs=resource, cache_dir=tmp_path, libclang_version="v")
    assert len(list((tmp_path / "units").glob("*.json"))) == len(commands)
    second = analysis.parse_project(SAMPLE, commands, resource_dirs=resource, cache_dir=tmp_path, libclang_version="v")
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
    assert shadow.text.splitlines()[1] == "#include <vector>"
    assert shadow.text.splitlines()[2].strip() == "" and shadow.text.splitlines()[3].strip() == ""
    assert shadow.text.splitlines()[4] == "int f();" and shadow.text.splitlines()[5].strip() == ""
    assert shadow.text.splitlines()[6] == "       int g();" and shadow.text.splitlines()[7].strip() == ""
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
    parser = analysis.Parser(resource)
    assert any(a.startswith("-fprebuilt-module-path=") for a in parser.arguments(stripped))
    unit, _ = parser.parse(stripped)
    from clang import cindex

    assert [d.spelling for d in unit.diagnostics if d.severity >= cindex.Diagnostic.Error] == []
