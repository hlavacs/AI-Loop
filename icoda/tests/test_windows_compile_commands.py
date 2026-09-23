"""Windows compiler paths, quoting and module response files survive database loading."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from icoda_core import analysis


@pytest.mark.parametrize("arguments", [
    [r"C:\Program Files\LLVM\bin\clang++.exe", r"-IC:\project\include", "-c", r"C:\project\main.cpp"],
    [r"C:\tools\cl.exe", r"-IC:\include with spaces", '-DNAME="hello world"', ""],
    ["clang++", "C:\\trailing space\\", "\\\\server\\share\\a.cpp", "a\\\"b", "a\\\\\"b"],
    ["clang++", "single'quote", "two words", "ordinary", "\\"],
])
def test_windows_command_round_trip(arguments: list[str]) -> None:
    assert analysis.split_command_line(subprocess.list2cmdline(arguments), "win32") == arguments


def test_windows_embedded_quotes_and_backslashes() -> None:
    assert analysis.split_command_line(r'cl -I"C:\Program Files\headers" "a""b"', "win32") == [
        "cl", r"-IC:\Program Files\headers", 'a"b']


def test_posix_shell_quoting_is_preserved() -> None:
    assert analysis.split_command_line("clang++ '-I/some path' -DNAME=\\\"hi\\\"", "linux") == [
        "clang++", "-I/some path", '-DNAME="hi"']


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows paths in a CMake database")
@pytest.mark.parametrize("use_arguments", [False, True])
def test_load_windows_database_and_module_response(tmp_path: Path, use_arguments: bool) -> None:
    source = tmp_path / "source space" / "main.cpp"
    compiler = r"C:\Program Files\LLVM\bin\clang++.exe"
    module = r"C:\project\build space\math.pcm"
    (tmp_path / "module flags.rsp").write_text(
        subprocess.list2cmdline([f"-fmodule-file=math={module}"]) + "\n", encoding="utf-8")
    raw = [compiler, r"-IC:\project\include", "@module flags.rsp", "-o", "main.obj", "-c", str(source)]
    entry: dict[str, object] = {"directory": str(tmp_path), "file": str(source)}
    entry["arguments" if use_arguments else "command"] = raw if use_arguments else subprocess.list2cmdline(raw)
    database = tmp_path / "compile_commands.json"
    database.write_text(json.dumps([entry]), encoding="utf-8")
    command, = analysis.load_compile_commands(database)
    assert command.compiler == compiler
    assert command.file == str(source)
    assert command.arguments == (r"-IC:\project\include", f"-fmodule-file=math={module}")


@pytest.mark.skipif(sys.platform != "win32", reason="MSVC response syntax")
def test_msvc_module_map_preserves_paths_and_separate_lines(tmp_path: Path) -> None:
    (tmp_path / "math.modmap").write_text(
        '-interface\n-ifcOutput "src\\math.ifc"\n-reference "std=src\\std.ifc"\n', encoding="utf-8")
    assert analysis.expand_response_files(["@math.modmap"], str(tmp_path)) == [
        "-interface", "-ifcOutput", r"src\math.ifc", "-reference", r"std=src\std.ifc"]
