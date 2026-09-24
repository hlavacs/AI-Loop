"""Versioned call-trace parsing, model resolution, and playback cursor behavior."""

import json
import re
import shutil
from pathlib import Path

import pytest

from icoda_core import call_trace, instrumentation, process
from icoda_core.model import DerivedModel, Entity, Kind

_CLANGXX = shutil.which("clang++") or shutil.which("g++")
_NM = shutil.which("nm") or shutil.which("llvm-nm")


def _model(root: Path) -> DerivedModel:
    model = DerivedModel(str(root))
    model.add_entity(Entity("u:main", Kind.FUNCTION, "main", "main", "main.cpp", 3))
    model.add_entity(Entity("u:work", Kind.FUNCTION, "work", "demo::work", "work.cpp", 7))
    return model


def test_load_trace_preserves_order_resolves_symbols_and_steps_entries(tmp_path: Path) -> None:
    path = tmp_path / "calls.tsv"
    path.write_text(
        "# icoda-call-trace-v1\n"
        "# columns=event...\n"
        "E\t10\t0x1\t0\t0x100\t0x0\tmain\t/app/demo\n"
        "E\t15\t0x1\t1\t0x120\t0x100\t\t/app/demo\n"
        "X\t20\t0x1\t1\t0x120\t0x100\tdemo::work()\t/app/demo\n",
        encoding="utf-8",
    )

    trace = call_trace.load_trace(path, _model(tmp_path), {"/app/demo!0x120": "demo::work()"})

    assert [event.timestamp_ns for event in trace.events] == [10, 15, 20]
    assert [event.kind for event in trace.events] == [
        call_trace.EventKind.ENTRY, call_trace.EventKind.ENTRY, call_trace.EventKind.EXIT]
    assert trace.events[0].entity is not None and trace.events[0].entity.usr == "u:main"
    assert trace.events[1].entity is not None and trace.events[1].entity.usr == "u:work"
    assert trace.events[1].identifier == "/app/demo!0x120"
    assert trace.current is None
    assert trace.step_entry() == trace.events[0]
    assert trace.current == trace.events[0] and trace.cursor == 1
    assert trace.step_entry() == trace.events[1]
    assert trace.step_entry() is None and trace.cursor == 3
    trace.seek(2)
    assert trace.step() == trace.events[2]
    trace.reset()
    assert trace.cursor == 0 and trace.event_at(1) == trace.events[1]


def test_loader_only_resolves_an_unambiguous_callable(tmp_path: Path) -> None:
    model = DerivedModel(str(tmp_path))
    model.add_entity(Entity("a", Kind.METHOD, "run", "a::run", "a.cpp", 1))
    model.add_entity(Entity("b", Kind.METHOD, "run", "b::run", "b.cpp", 1))
    path = tmp_path / "calls.tsv"
    path.write_text(
        "# icoda-call-trace-v1\n"
        "E\t1\tt\t0\t0x1\t0x0\trun\tapp\n"
        "E\t2\tt\t0\t0x2\t0x0\tb::run()\tapp\n",
        encoding="utf-8",
    )

    events = call_trace.load_trace(path, model).events
    assert events[0].entity is None
    assert events[1].entity is model.entities["b"]


def test_loader_demangles_a_recorded_cpp_symbol(tmp_path: Path, monkeypatch) -> None:
    model = DerivedModel(str(tmp_path))
    model.add_entity(Entity(
        "method", Kind.METHOD, "method", "ns::Class::method", "class.cpp", 4,
        signature="void method(int)"))
    path = tmp_path / "calls.tsv"
    path.write_text(
        "# icoda-call-trace-v1\n"
        "E\t1\tt\t0\t0x10\t0x0\t_ZN2ns5Class6methodEi\t/app/demo\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(call_trace.shutil, "which", lambda name: "/tools/c++filt"
                        if name == "c++filt" else None)

    def run(command, **kwargs):
        assert command == ["/tools/c++filt"]
        assert kwargs["input_text"] == "_ZN2ns5Class6methodEi\n"
        return process.ProcessResult(command, 0, "ns::Class::method(int)\n", "")

    monkeypatch.setattr(call_trace.process, "run_bounded", run)

    event = call_trace.load_trace(path, model).events[0]
    assert event.function_name == "ns::Class::method(int)"
    assert event.entity is model.entities["method"]


def test_loader_resolves_a_clang_module_owned_symbol(tmp_path: Path, monkeypatch) -> None:
    model = DerivedModel(str(tmp_path))
    model.add_entity(Entity(
        "method", Kind.METHOD, "applyDefaults", "vve::simple::Engine::applyDefaults",
        "engine.cpp", 4, signature="void applyDefaults()"))
    path = tmp_path / "calls.tsv"
    path.write_text(
        "# icoda-call-trace-v1\n"
        "E\t1\tt\t0\t0x10\t0x0\t"
        "_ZN3vve6simpleW8VEEngineW6Simple6Engine13applyDefaultsEv\t/app/demo\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(call_trace.shutil, "which", lambda name: "/tools/c++filt"
                        if name == "c++filt" else None)
    monkeypatch.setattr(
        call_trace.process,
        "run_bounded",
        lambda command, **kwargs: process.ProcessResult(
            command, 0, "vve::simple::Engine@VEEngine.Simple::applyDefaults()\n", ""),
    )

    event = call_trace.load_trace(path, model).events[0]
    assert event.function_name == "vve::simple::Engine@VEEngine.Simple::applyDefaults()"
    assert event.entity is model.entities["method"]


def test_loader_resolves_an_empty_symbol_from_the_containing_nm_symbol(
        tmp_path: Path, monkeypatch) -> None:
    model = DerivedModel(str(tmp_path))
    model.add_entity(Entity(
        "work", Kind.FUNCTION, "work", "demo::work", "work.cpp", 4,
        signature="void work()"))
    path = tmp_path / "calls.tsv"
    path.write_text(
        "# icoda-call-trace-v1\n"
        "E\t1\tt\t0\t0x118\t0x0\t\t/app/demo\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(call_trace.shutil, "which", lambda name: "/tools/nm" if name == "nm" else None)

    def run(command, **kwargs):
        assert command == ["/tools/nm", "-C", "--defined-only", "/app/demo"]
        return process.ProcessResult(command, 0,
                                     "00000100 T before()\n"
                                     "00000110 T demo::work()\n"
                                     "00000120 T after()\n", "")

    monkeypatch.setattr(call_trace.process, "run_bounded", run)

    event = call_trace.load_trace(path, model).events[0]
    assert event.function_name == "demo::work()"
    assert event.entity is model.entities["work"]


def test_call_playback_steps_only_resolved_entries(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "calls.tsv"
    path.write_text(
        "# icoda-call-trace-v1\n"
        "E\t1\tt\t0\t0x1\t0x0\tmain\tapp\n"
        "E\t2\tt\t1\t0x2\t0x1\t\tapp\n"
        "X\t3\tt\t1\t0x2\t0x1\t\tapp\n"
        "E\t4\tt\t1\t0x3\t0x1\tdemo::work()\tapp\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(call_trace.shutil, "which", lambda _name: None)
    model = _model(tmp_path)
    playback = call_trace.CallPlayback(call_trace.load_trace(path, model))

    assert (playback.position, playback.total, playback.status) == (0, 2, "call 0 of 2")
    assert playback.next_call() is model.entities["u:main"]
    assert playback.status == "call 1 of 2: main"
    assert playback.next_call() is model.entities["u:work"]
    assert playback.next_call() is None
    assert playback.previous_call() is model.entities["u:main"]
    assert playback.previous_call() is None
    assert playback.position == 0
    assert playback.next_call() is model.entities["u:main"]
    playback.reset()
    assert playback.position == 0


def test_call_playback_collapses_consecutive_calls_to_the_same_function(tmp_path: Path) -> None:
    path = tmp_path / "calls.tsv"
    path.write_text(
        "# icoda-call-trace-v1\n"
        "E\t1\tt\t0\t0x1\t0x0\tmain\tapp\n"
        "E\t2\tt\t1\t0x2\t0x1\tdemo::work()\tapp\n"
        "X\t3\tt\t1\t0x2\t0x1\tdemo::work()\tapp\n"
        "E\t4\tt\t1\t0x2\t0x1\tdemo::work()\tapp\n"
        "E\t5\tt\t0\t0x1\t0x0\tmain\tapp\n",
        encoding="utf-8",
    )
    playback = call_trace.CallPlayback(call_trace.load_trace(path, _model(tmp_path)))

    assert playback.total == 3
    assert playback.next_call().usr == "u:main"
    assert playback.next_call().usr == "u:work"
    assert playback.current_repeat_count == 2
    assert playback.current_caller_counts == {"u:main": 2}
    assert playback.status == "call 2 of 3: demo::work — 2 consecutive calls"
    assert playback.next_call().usr == "u:main"
    assert playback.next_call() is None


def test_call_playback_seeks_to_the_first_call_of_a_function(tmp_path: Path) -> None:
    path = tmp_path / "calls.tsv"
    path.write_text(
        "# icoda-call-trace-v1\n"
        "E\t1\tt\t0\t0x1\t0x0\tmain\tapp\n"
        "E\t2\tt\t0\t0x2\t0x0\tdemo::work()\tapp\n"
        "E\t3\tt\t0\t0x1\t0x0\tmain\tapp\n"
        "E\t4\tt\t0\t0x2\t0x0\tdemo::work()\tapp\n",
        encoding="utf-8",
    )
    playback = call_trace.CallPlayback(call_trace.load_trace(path, _model(tmp_path)))

    assert playback.seek_first_call("missing") is None and playback.position == 0
    assert playback.seek_first_call("u:work") is playback.entities[1]
    assert playback.position == 2 and playback.status == "call 2 of 4: demo::work"
    assert playback.next_call() is playback.entities[0]
    assert playback.seek_first_call("u:work") is playback.entities[1] and playback.position == 2


@pytest.mark.skipif(_CLANGXX is None or _NM is None, reason="clang++/g++ and nm/llvm-nm are required")
def test_real_instrumented_cpp_trace_plays_main_work_helper(tmp_path: Path) -> None:
    trace_path = tmp_path / "calls.tsv"
    files = instrumentation.prepare_instrumentation(
        tmp_path, instrumentation.InstrumentationOptions(True, 5, trace_path))
    source = tmp_path / "program.cpp"
    source.write_text(
        "volatile int result = 0;\n"
        "__attribute__((noinline)) void helper() { ++result; }\n"
        "__attribute__((noinline)) void work() { helper(); }\n"
        "int main() { work(); return result == 1 ? 0 : 1; }\n",
        encoding="utf-8",
    )
    executable = tmp_path / "demo"
    compile_result = process.run_bounded([
        str(_CLANGXX), "-std=c++17", "-g", "-O0", "-finstrument-functions",
        str(source), str(files.runtime_source), "-ldl", "-o", str(executable),
    ], cwd=tmp_path, timeout=30)
    assert compile_result.ok, compile_result.stderr
    run_result = process.run_bounded([str(executable)], cwd=tmp_path, timeout=10)
    assert run_result.ok, run_result.stderr

    model = DerivedModel(str(tmp_path))
    model.add_entity(Entity("main", Kind.FUNCTION, "main", "main", "program.cpp", 4,
                            signature="int main()"))
    model.add_entity(Entity("work", Kind.FUNCTION, "work", "work", "program.cpp", 3,
                            signature="void work()"))
    model.add_entity(Entity("helper", Kind.FUNCTION, "helper", "helper", "program.cpp", 2,
                            signature="void helper()"))
    playback = call_trace.CallPlayback(call_trace.load_trace(trace_path, model))

    assert [playback.next_call().qualified_name for _ in range(3)] == ["main", "work", "helper"]
    assert playback.next_call() is None


@pytest.mark.parametrize("contents", [
    "E\t1\tt\t0\t0x1\t0x0\tmain\tapp\n",
    "# icoda-call-trace-v1\nE\tbad\tt\t0\t0x1\t0x0\tmain\tapp\n",
    "# icoda-call-trace-v1\nE\t1\tt\t0\t0x1\n",
])
def test_invalid_trace_reports_a_format_error(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "broken.tsv"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(call_trace.TraceFormatError, match=re.escape(str(path))):
        call_trace.load_trace(path)


def test_cursor_rejects_a_position_outside_the_trace() -> None:
    trace = call_trace.CallTrace(())
    with pytest.raises(IndexError):
        trace.seek(1)


def test_windows_pdb_trace_resolution_uses_image_relative_addresses(tmp_path, monkeypatch):
    path = tmp_path / "calls.tsv"
    module = str(tmp_path / "game.exe")
    path.write_text(F"{call_trace.FORMAT_HEADER}\nE\t1\tt\t0\t0x1000\t0x0\t\t{module}\n", encoding="utf-8")
    monkeypatch.setattr(call_trace.shutil, "which", lambda name: "symbolizer" if name == "llvm-symbolizer" else None)
    def run(command, **kwargs):
        assert command == ["symbolizer", f"--obj={module}", "--relative-address", "--no-inlines", "--output-style=JSON"]
        assert kwargs["input_text"] == "0x1000\n"
        return process.ProcessResult(command, 0, json.dumps({"Address": "0x1000", "Symbol": [{"FunctionName": "main"}]}), "")
    monkeypatch.setattr(call_trace.process, "run_bounded", run)
    model = _model(tmp_path)
    playback = call_trace.CallPlayback(call_trace.load_trace(path, model))
    assert playback.total == 1 and playback.next_call() is model.entities["u:main"]


def test_symbolizer_is_discovered_beside_visual_studio_libclang(tmp_path, monkeypatch):
    from types import SimpleNamespace
    tool = tmp_path / "llvm-symbolizer.exe"
    tool.touch()
    monkeypatch.setattr(call_trace.shutil, "which", lambda _name: None)
    monkeypatch.setattr(call_trace.toolchain, "candidates", lambda: [SimpleNamespace(path=str(tmp_path / "libclang.dll"))])
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return process.ProcessResult(command, 0, '{"Address":"0x1","Symbol":[{"FunctionName":"??"}]}', "")
    monkeypatch.setattr(call_trace.process, "run_bounded", run)
    assert call_trace._module_symbols("game.exe", {"0x1"}) == {}
    assert calls[0][0] == str(tool)
    assert "No project calls resolved" in call_trace.CallPlayback(call_trace.CallTrace(())).status
