"""Windows compilation databases and separate Clang analysis modules."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from icoda_core import analysis, toolchain, windows_analysis


@pytest.mark.skipif(sys.platform != "win32", reason="Windows command-line quoting")
def test_windows_command_round_trip():
    arguments = [r"C:\Program Files\LLVM\clang-cl.exe", r"-IC:\project path\include",
                 '-DNAME="quoted value"', r"@src\target.obj.modmap", "", "ends\\"]
    assert analysis.split_command(subprocess.list2cmdline(arguments)) == arguments


@pytest.mark.skipif(sys.platform != "win32", reason="Windows compilation database")
def test_windows_database_expands_response_files_without_losing_paths(tmp_path):
    source = tmp_path / "main.cpp"
    source.write_text("struct Example {};\n")
    (tmp_path / "modules.modmap").write_text('-reference "math=src\\math.ifc"\n')
    arguments = [r"C:\Program Files\MSVC\cl.exe", "/TP", r"-IC:\SDK\include", "-MD",
                 "@modules.modmap", "/Fomain.obj", "-c", str(source)]
    database = tmp_path / "compile_commands.json"
    database.write_text(json.dumps([{"directory": str(tmp_path), "file": str(source),
                                      "command": subprocess.list2cmdline(arguments)}]))
    command, = analysis.load_compile_commands(database)
    assert command.compiler == arguments[0]
    assert r"-IC:\SDK\include" in command.arguments
    assert "-MD" in command.arguments
    assert windows_analysis.references(command) == ("math",)
    assert r"math=src\math.ifc" in command.arguments
    assert str(source) not in command.arguments


def test_msvc_flags_keep_preprocessing_and_exclude_output_flags():
    command = analysis.CompileCommand("a.cpp", ".", (
        "/TP", "/DDEBUG", '-DTITLE="hello"', r"/IC:\SDK", r"-external:IC:\system",
        "-std:c++latest", "-MDd", "/Foa.obj", "/Fddebug.pdb", "/MP", "/FS",
        "-reference", r"std=build\std.ifc", "-ifcOutput", "a.ifc", "/FI", "config.hpp",
    ), "cl.exe", False)
    args = windows_analysis.clang_arguments(command)
    assert "-DDEBUG" in args and '-DTITLE="hello"' in args
    assert r"-IC:\SDK" in args and r"C:\system" in args
    assert "-std=c++23" in args and "-fms-runtime-lib=dll_dbg" in args
    assert args[-2:] == ["-include", "config.hpp"]
    assert not any(".ifc" in arg or ".obj" in arg or ".pdb" in arg for arg in args)


def test_empty_previous_cache_does_not_hide_partial_analysis(tmp_path, monkeypatch):
    source = tmp_path / "a.cpp"
    source.write_text("struct Visible {};\n")
    command = analysis.CompileCommand(str(source), str(tmp_path), (), "clang++", False)
    info = analysis.FileInfo("a.cpp", errors=("missing dependency",))
    result = analysis.UnitResult(info, ["a.cpp"])
    monkeypatch.setattr(analysis, "Parser", lambda *args: type("Parser", (), {
        "missing_modules": set(), "arguments": lambda self, cmd: []})())
    monkeypatch.setattr(analysis, "_unit_result", lambda *args: result)
    previous = analysis.DerivedModel(str(tmp_path))
    model = analysis.parse_project(tmp_path, [command], previous=previous)
    assert model is not previous
    assert "a.cpp" in model.files and model.stale
    assert "missing dependency" in model.stale_reason


def test_prepare_builds_dependencies_and_invalidates_header_changes(tmp_path, monkeypatch):
    compiler = tmp_path / "clang++.exe"
    compiler.touch()
    library = tmp_path / "libclang.dll"
    library.touch()
    header = tmp_path / "header with spaces.hpp"
    header.write_text("struct Value {};\n")
    dependency = tmp_path / "base.ixx"
    dependency.write_text("export module base;\n")
    source = tmp_path / "main.cpp"
    source.write_text("import base;\n")
    commands = [analysis.CompileCommand(str(dependency), str(tmp_path), ("-std:c++latest",), "cl.exe", True),
                analysis.CompileCommand(str(source), str(tmp_path),
                                        ("-std:c++latest", "-reference", "base=base.ifc"), "cl.exe", False)]
    invocations = []

    def compile_module(argv, **kwargs):
        invocations.append(argv)
        output = Path(argv[argv.index("-o") + 1])
        output.write_bytes(b"PCM")
        depfile = Path(argv[argv.index("-MF") + 1])
        escaped = str(header).replace(" ", "\\ ")
        depfile.write_text(f"{output}: {escaped}\n")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(windows_analysis.subprocess, "run", compile_module)
    loaded = toolchain.Loaded(str(library), "20.1.8", 20, False)
    first = windows_analysis.prepare(commands, loaded, tmp_path / "cache", lambda message: None)
    assert len(invocations) == 1
    assert any(arg.startswith("-fmodule-file=base=") for arg in first[1].arguments)
    windows_analysis.prepare(commands, loaded, tmp_path / "cache", lambda message: None)
    assert len(invocations) == 1
    header.write_text("struct DifferentValue {};\n")
    windows_analysis.prepare(commands, loaded, tmp_path / "cache", lambda message: None)
    assert len(invocations) == 2


def test_rebuilt_module_invalidates_translation_unit_cache(tmp_path):
    module = tmp_path / "base.pcm"
    module.write_bytes(b"old module")
    command = analysis.CompileCommand(str(tmp_path / "a.cpp"), str(tmp_path),
                                      (f"-fmodule-file=base={module}",), "clang++", False)
    before = analysis.unit_cache_key(command, (), tmp_path, "20")
    module.write_bytes(b"new module with changed header")
    assert analysis.unit_cache_key(command, (), tmp_path, "20") != before


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows Clang integration")
def test_real_msvc_module_project_produces_class_and_call_diagrams(tmp_path):
    from test_analysis import _libclang

    from icoda_core import clusters, views

    loaded = _libclang()
    if not Path(loaded.path).with_name("clang++.exe").is_file():
        pytest.skip("no matching Clang compiler")
    base = tmp_path / "base.ixx"
    base.write_text("export module base;\nexport struct Box { int value() { return 42; } };\n")
    main = tmp_path / "main.cpp"
    main.write_text("import base;\nint main() { Box box; return box.value(); }\n")
    commands = [analysis.CompileCommand(str(base), str(tmp_path), ("-std:c++20",), "cl.exe", True),
                analysis.CompileCommand(str(main), str(tmp_path),
                                        ("-std:c++20", "-reference", "base=base.ifc"), "cl.exe", False)]
    prepared = windows_analysis.prepare(commands, loaded, tmp_path / "cache", lambda message: None)
    model = analysis.parse_project(tmp_path, prepared)
    assert not any(info.errors for info in model.files.values())
    assert any(entity.name == "Box" for entity in model.entities.values())
    assert any(edge.kind == analysis.EdgeKind.CALLS for edge in model.edges)
    assert views.layout_file_view(model, clusters.cluster_files(model)).nodes


def test_self_contained_module_needs_no_prebuilt_imports(tmp_path):
    from test_analysis import _libclang

    _libclang()
    source = tmp_path / "leaf.cppm"
    source.write_text("export module leaf;\nexport struct Leaf {};\n")
    command = analysis.CompileCommand(str(source), str(tmp_path), ("-std=c++20",), "clang++", True)
    notes = []
    model = analysis.parse_project(tmp_path, [command], notes=notes)
    assert not notes
    assert not any(info.errors for info in model.files.values())
