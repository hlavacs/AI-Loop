"""Protocol acceptance through real service processes, independent of the Tk test stubs."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from queue import Queue
from typing import Any

import pytest
import test_executables

from icoda_core import __version__, cmake, persistence, python_analysis, toolchain, views
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind
from icoda_core.service import MAX_MESSAGE_BYTES, OPERATIONS, ProjectLock, Service, ServiceError, handle_line

ROOT = Path(__file__).resolve().parent.parent
cmake_project = test_executables.project  # Reuse the configure-only multi-executable fixture.
SOURCE = '''raise RuntimeError("Analysis must never execute this project")

def main():
    A()
    E()

def A():
    B()
    D()

def B():
    C()

def C():
    """A leaf with a UTF-8 purpose: Grüße."""
    return 1

def D():
    return 2

def E():
    return 3
'''
ROWS = (("E", 0, "main"), ("E", 1, "A"), ("E", 2, "B"), ("E", 3, "C"),
        ("X", 3, "C"), ("X", 2, "B"), ("E", 2, "D"), ("X", 2, "D"),
        ("X", 1, "A"), ("E", 1, "E"), ("X", 1, "E"), ("X", 0, "main"))


class Client:
    """A tiny line client with a read deadline, stderr capture, and deterministic cleanup."""

    def __init__(self, config: Path, stderr, bootstrap: str | None = None):
        env = dict(os.environ, XDG_CONFIG_HOME=str(config), APPDATA=str(config), PYTHONIOENCODING="ascii")
        self.stderr = stderr
        # config_path ignores environment overrides on macOS. Pin it in every child too.
        isolated = ("from pathlib import Path\nfrom icoda_core import persistence\n"
                    f"persistence.config_path = lambda: Path({str(config / 'icoda/config.json')!r})\n")
        args = ["-c", isolated + (bootstrap or "from icoda_core.service import main; main()")]
        self.process = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr)
        self.lines: Queue[bytes] = Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.sequence = 0
        self.context: dict[str, Any] = {}
        self.trace_id = None
        self.notifications = []

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(b"")

    def exchange(self, frame):
        self.process.stdin.write(frame + b"\n")
        self.process.stdin.flush()
        while True:
            line = self.lines.get(timeout=60)
            assert line, "Service exited before answering"
            result = json.loads(line.decode("utf-8"))
            assert isinstance(result, dict)
            if "id" in result or result.get("method") == "protocol.error":
                return result
            self.notifications.append(result)

    def request(self, method, params=None, **context):
        self.sequence += 1
        if method in OPERATIONS:
            params = {"trusted": True, **(params or {})}
        request = {"id": self.sequence, "method": method, "params": params or {}, **self.context, **context}
        result = self.exchange(json.dumps(request, ensure_ascii=False).encode("utf-8"))
        assert result["id"] == request["id"]
        assert result["status"] in {"ok", "error", "cancelled"}
        if result["status"] == "ok":
            assert "error" not in result
            payload = result["result"]
        else:
            assert "result" not in result and set(result["error"]) == {"code", "message", "details"}
            payload = result["error"]["details"]
        if "sessionId" in payload:
            self.context = {key: payload[key] for key in ("sessionId", "modelRevision", "targetId")}
        if "traceId" in payload:
            self.trace_id = payload["traceId"]
        return result

    def ok(self, method, params=None, **context):
        response = self.request(method, params, **context)
        assert response["status"] == "ok", response
        return response["result"]

    def step(self, action, **params):
        return self.ok("trace.step", {"traceId": self.trace_id, "action": action, **params})

    def close(self):
        if self.process.stdout.closed:
            return
        if not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            self.reader.join(timeout=5)
            self.process.stdout.close()
            self.stderr.seek(0)
            self.logs = self.stderr.read().decode("utf-8", errors="replace")
        assert self.process.returncode == 0, self.logs
        assert self.lines.get(timeout=1) == b"", "Unexpected stdout after the last response"


@pytest.fixture(autouse=True)
def isolated_user_config(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "config_path", lambda: tmp_path / "config/icoda/config.json")


@pytest.fixture
def clients(tmp_path):
    with ExitStack() as stack:
        def start(bootstrap=None):
            client = Client(tmp_path / "config", stack.enter_context(tempfile.TemporaryFile()), bootstrap)
            stack.callback(client.close)
            return client
        yield start


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project ü"
    root.mkdir()
    (root / "program.py").write_text(SOURCE, encoding="utf-8")
    return root


def open_project(client, project, analyse=True):
    client.ok("initialize", {"protocolVersion": 1})
    opened = client.ok("project.open", {"path": str(project)})
    return client.ok("project.analyse") if analyse else opened


def write_trace(project, rows=ROWS):
    path = project / "calls.tsv"
    lines = ["# icoda-call-trace-v1"]
    for index, (kind, depth, name) in enumerate(rows):
        lines.append(f"{kind}\t{index}\tthread-1\t{depth}\t{name}\t\t{name}\t")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def assert_error(response, code):
    assert response["status"] == "error", response
    assert response["error"]["code"] == code, response
    assert response["error"]["message"]
    assert isinstance(response["error"]["details"], dict)
    return response["error"]["details"]


@pytest.mark.parametrize("language", ["C++", "Python"])
def test_project_create_shared_skeleton_state_and_session_preserved(clients, project, tmp_path, language):
    from icoda_core import generator, specification, steplog

    client = clients()
    opened = open_project(client, project, analyse=False)
    parent = tmp_path / "new projects"
    parent.mkdir()
    result = client.ok("project.create", {"parentPath": str(parent), "name": "Sample Project",
                                         "language": language, "summary": "A small example.", "trusted": True})
    root = parent / "Sample Project"
    store = persistence.ProjectStore(root)
    assert result["root"] == str(root) and result["specificationPath"] == str(store.specification_path)
    spec = specification.default_specification(root.name, language)
    spec["summary"] = "A small example."
    assert specification.load(store.specification_path) == spec
    assert specification.validate(spec) == []
    expected = generator.skeleton_files(root.name, spec["code_profile"])
    assert set(result["writtenFiles"]) == set(expected)
    for path, content in expected.items():
        assert (root / path).read_text(encoding="utf-8") == content
    assert {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} == set(expected) | {
        ".icoda/.gitignore", ".icoda/state.json", ".icoda/specification.json", ".icoda/steps.jsonl", ".icoda/icoda.log"}
    assert store.cache_dir.is_dir()
    assert result["state"]["phase"] == store.load_state().phase.value == "architecture"
    records = steplog.StepLog(store.steps_path).records()
    assert len(records) == 1 and records[0].decision == "phase_transition"
    assert records[0].previous_phase == "specification"
    assert not (root / ".git").exists() and not store.model_path.exists()
    assert client.context == {key: opened[key] for key in ("sessionId", "modelRevision", "targetId")}
    assert client.ok("targets.list")["sessionId"] == opened["sessionId"]
    assert not (project / ".icoda").exists()


def test_project_create_without_open_project_advertises_capability(clients, tmp_path):
    client = clients()
    hello = client.ok("initialize", {"protocolVersion": 1})
    assert "project.create" in hello["capabilities"]["methods"]
    result = client.ok("project.create", {"parentPath": str(tmp_path), "name": "fresh",
                                         "language": "Python", "trusted": True})
    assert result["state"]["phase"] == "architecture"
    assert client.context == {}
    assert_error(client.request("targets.list"), "project_not_open")


@pytest.mark.parametrize("kind", ["empty", "nonempty", "file", "symlink", "dangling"])
def test_project_create_refuses_existing_targets_without_changes(clients, tmp_path, kind):
    parent = tmp_path / "parent"
    parent.mkdir()
    target = parent / "existing"
    outside = tmp_path / "outside"
    outside.mkdir()
    if kind in {"symlink", "dangling"}:
        target.symlink_to(outside if kind == "symlink" else outside / "missing", target_is_directory=True)
    elif kind == "file":
        target.write_text("keep")
    else:
        target.mkdir()
        if kind == "nonempty":
            (target / "source.py").write_text("keep")
            persistence.ProjectStore(target).ensure()
    before = {p: p.read_bytes() for p in parent.rglob("*") if p.is_file()}
    client = clients()
    client.ok("initialize", {"protocolVersion": 1})
    assert_error(client.request("project.create", {"parentPath": str(parent), "name": "existing",
                                                  "language": "Python", "trusted": True}), "target_exists")
    assert {p: p.read_bytes() for p in parent.rglob("*") if p.is_file()} == before
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("trusted", [False, None, "true"])
def test_project_create_requires_trust_before_writing(clients, tmp_path, trusted):
    client = clients()
    client.ok("initialize", {"protocolVersion": 1})
    assert_error(client.request("project.create", {"parentPath": str(tmp_path), "name": "fresh",
                                                  "language": "Python", "trusted": trusted}), "not_trusted")
    assert not (tmp_path / "fresh").exists()


@pytest.mark.parametrize("name", ["", " ", ".", "..", "bad\0name", "bad:name", "NUL", "COM1.txt", "trailing."])
def test_project_create_rejects_invalid_name(clients, tmp_path, name):
    parent = tmp_path / "parent"
    parent.mkdir()
    client = clients()
    client.ok("initialize", {"protocolVersion": 1})
    assert_error(client.request("project.create", {"parentPath": str(parent), "name": name,
                                                  "language": "Python", "trusted": True}), "invalid_params")
    assert list(parent.iterdir()) == []


@pytest.mark.parametrize("name", ["../escape", "nested/escape", "..\\escape", "C:\\escape", "/escape"])
def test_project_create_rejects_path_escape(clients, tmp_path, name):
    parent = tmp_path / "parent"
    parent.mkdir()
    client = clients()
    client.ok("initialize", {"protocolVersion": 1})
    assert_error(client.request("project.create", {"parentPath": str(parent), "name": name,
                                                  "language": "Python", "trusted": True}), "invalid_params")
    assert list(parent.iterdir()) == [] and not (tmp_path / "escape").exists()


@pytest.mark.parametrize("override", [{"parentPath": "relative"}, {"language": "Ruby"}, {"summary": []},
                                     {"summary": "bad\0text"}, {"summary": "\ud800"}, {"name": 12}])
def test_project_create_rejects_invalid_inputs(tmp_path, override):
    service = Service()
    service.dispatch({"method": "initialize", "params": {"protocolVersion": 1}})
    params = {"parentPath": str(tmp_path), "name": "fresh", "language": "Python", "trusted": True, **override}
    # Escaped JSON allows the malformed Unicode transport case to reach parameter validation.
    assert_error(handle_line(service, json.dumps({"id": 1, "method": "project.create", "params": params}).encode()),
                 "invalid_params")
    assert not (tmp_path / "fresh").exists()


def test_project_create_rejects_stale_session_before_writing(clients, project, tmp_path):
    client = clients()
    opened = open_project(client, project, analyse=False)
    params = {"parentPath": str(tmp_path), "name": "fresh", "language": "Python", "trusted": True}
    assert_error(client.request("project.create", params, sessionId="old"), "invalid_session")
    assert_error(client.request("project.create", params, modelRevision=opened["modelRevision"] + 1), "stale_revision")
    assert_error(client.request("project.create", params, targetId="old"), "stale_target")
    assert not (tmp_path / "fresh").exists()


def test_initialize_and_cache_only_open(clients, project, tmp_path):
    config = persistence.config_path()
    persistence.UserConfig(last_project=str(tmp_path / "remembered")).save(config)
    before = config.read_bytes()
    client = clients()
    initialized = client.ok("initialize", {"protocolVersion": 1})
    assert initialized["backendVersion"] == __version__ and initialized["protocolVersion"] == 1
    assert Path(initialized["runtime"]["python"]).samefile(sys.executable)
    assert initialized["capabilities"]["cancellation"] is True
    assert {"targets.list", "target.select", "view.get"} <= set(initialized["capabilities"]["methods"])
    assert initialized["capabilities"]["targetSelection"]
    assert initialized["capabilities"]["views"] == ["call", "file", "class", "mindmap"]
    assert "mindmap.setExpanded" in initialized["capabilities"]["methods"]
    opened = client.ok("project.open", {"path": str(project)})
    assert opened["root"] == str(project) and opened["targetId"] is None
    assert opened["cached"] is False and opened["model"]["entities"] == []
    assert opened["model"]["stale"] and opened["modelRevision"] == 1
    assert not (project / ".icoda").exists()
    assert config.read_bytes() == before
    assert_error(client.request("initialize", {"protocolVersion": 1}), "already_initialized")


def test_analysis_returns_real_entities_and_cache(clients, project):
    client = clients()
    analysed = open_project(client, project)
    model = analysed["model"]
    assert not model["stale"] and analysed["modelRevision"] == 2 and not analysed["diagnostics"]
    assert analysed["toolchain"]["frontend"] == "Python ast"
    assert {entity["name"] for entity in model["entities"]} == {"main", "A", "B", "C", "D", "E"}
    assert {(edge["source"], edge["target"]) for edge in model["edges"] if edge["kind"] == "calls"} == {
        (f"python:program:{a}", f"python:program:{b}") for a, b in
        (("main", "A"), ("main", "E"), ("A", "B"), ("A", "D"), ("B", "C"))}
    cached = client.ok("project.open", {"path": str(project)})
    assert cached["cached"] and cached["model"] == model
    assert cached["sessionId"] != analysed["sessionId"]


def test_analysis_failure_retains_stale_model_and_diagnostics(clients, project):
    client = clients()
    good = open_project(client, project)
    (project / "program.py").write_text("def broken(\n", encoding="utf-8")
    failed = assert_error(client.request("project.analyse"), "analysis_failed")
    assert failed["modelRevision"] == 3 and failed["model"]["stale"]
    assert failed["model"]["entities"] == good["model"]["entities"]
    assert any(d.get("file") == "program.py" for d in failed["diagnostics"])
    assert persistence.ProjectStore(project).load_model().stale
    reopened = client.ok("project.open", {"path": str(project)})
    assert reopened["model"]["stale"]
    (project / "program.py").write_text(SOURCE, encoding="utf-8")
    recovered = client.ok("project.analyse")
    assert not recovered["model"]["stale"] and recovered["model"]["stale_reason"] == ""


def test_source_resolution_moved_ambiguous_missing_and_boundaries(clients, project, tmp_path):
    client = clients()
    opened = open_project(client, project)
    root = {"sourceRootId": opened["sourceRootId"]}
    (project / "relocated").mkdir()
    (project / "program.py").rename(project / "relocated" / "program.py")
    resolved = client.ok("source.resolve", {**root, "usr": "python:program:B"})
    assert resolved["file"] == "relocated/program.py" and resolved["line"] == 11
    assert resolved["path"] == str(project / "relocated" / "program.py")
    assert client.ok("source.resolve", {**root, "file": "old/program.py", "line": 4})["line"] == 4
    for parent in ("one", "two"):
        (project / parent).mkdir()
        (project / parent / "duplicate.py").write_text("# source\n", encoding="utf-8")
    ambiguous = assert_error(client.request("source.resolve", {**root, "file": "old/duplicate.py"}),
                             "source_ambiguous")
    assert ambiguous["candidates"] == ["one/duplicate.py", "two/duplicate.py"]
    assert client.ok("source.resolve", {**root, "file": "old/one/duplicate.py"})["file"] == "one/duplicate.py"
    for file in ("missing.py", "../outside.py", str(tmp_path / "outside.py"), ".icoda/state.json"):
        assert_error(client.request("source.resolve", {**root, "file": file}), "source_missing")
    assert_error(client.request("source.resolve", {**root, "usr": "absent"}), "source_missing")
    assert_error(client.request("source.resolve", {"sourceRootId": "other", "file": "program.py"}),
                 "invalid_params")


@pytest.mark.parametrize("action,destination,position,forward", [
    ("into", "C", 4, {"into": True, "over": True, "out": True}),
    ("over", "D", 5, {"into": True, "over": True, "out": True}),
    ("out", "E", 6, {"into": False, "over": False, "out": False}),
])
def test_trace_b_to_c_d_e_and_synchronized_state(clients, project, action, destination, position, forward):
    client = clients()
    analysed = open_project(client, project)
    path = write_trace(project)
    loaded = client.ok("trace.load", {"path": str(path)})
    assert loaded["position"] == 0 and loaded["total"] == 6 and loaded["currentEntityUsr"] is None
    assert loaded["currentCall"] is None
    assert loaded["source"] is None and loaded["recordedCalls"] == loaded["resolvedCalls"] == 6
    assert loaded["availability"] == {"into": True, "over": True, "out": False, "previous": False, "reset": False}
    for name in ("main", "A", "B"):
        selected = client.step("into")
        assert selected["currentEntityUsr"] == f"python:program:{name}"
    assert selected["position"] == 3 and all(selected["availability"].values())
    selected = client.step(action)
    assert selected["currentEntityUsr"] == f"python:program:{destination}" and selected["position"] == position
    entity = next(e for e in analysed["model"]["entities"] if e["name"] == destination)
    assert selected["source"] == {"sourceRootId": analysed["sourceRootId"], "file": "program.py",
                                  "line": entity["line"]}
    assert selected["currentCall"] == {"usr": entity["usr"], "source": selected["source"],
                                       "threadId": "thread-1", "depth": {"C": 3, "D": 2, "E": 1}[destination],
                                       "sequence": {"C": 3, "D": 6, "E": 9}[destination]}
    assert selected["availability"] == {**forward, "previous": True, "reset": True}
    assert selected["repeatCount"] == 1
    caller = {"C": "B", "D": "A", "E": "main"}[destination]
    assert selected["callerCounts"] == {f"python:program:{caller}": 1}
    for _ in range(7):
        selected = client.step("into")
    assert selected["position"] == 6 and selected["currentEntityUsr"] == "python:program:E"
    assert not any(selected["availability"][mode] for mode in ("into", "over", "out"))
    assert client.step("previous")["currentEntityUsr"] == "python:program:D"
    assert client.step("seek", usr="python:program:B")["position"] == 3
    reset = client.ok("trace.reset", {"traceId": client.trace_id})
    assert reset["position"] == 0 and reset["source"] is None and reset["repeatCount"] == 0
    assert reset["currentCall"] is None
    assert reset["callerCounts"] == {} and reset["availability"] == loaded["availability"]
    client.step("into")
    assert client.step("previous")["position"] == 0


def test_empty_unresolved_truncated_and_invalid_trace(clients, project):
    client = clients()
    open_project(client, project)
    for rows in ((), (("E", 0, "unknown"),)):
        loaded = client.ok("trace.load", {"path": str(write_trace(project, rows))})
        assert loaded["total"] == 0 and not any(loaded["availability"].values())
        assert "No project calls resolved" in loaded["status"]
        assert client.step("into")["position"] == 0
    client.ok("trace.load", {"path": str(write_trace(project, ROWS[:4]))})
    selected = client.step("seek", usr="python:program:B")
    assert selected["availability"] == {"into": True, "over": False, "out": False, "previous": True, "reset": True}
    assert client.step("out")["position"] == 3
    for payload in (b"", b"bad trace", b"# icoda-call-trace-v1\nE\tbad\n", b"\xff"):
        (project / "invalid.tsv").write_bytes(payload)
        assert_error(client.request("trace.load", {"path": "invalid.tsv"}), "invalid_trace")
    assert_error(client.request("trace.load", {"path": "absent.tsv"}), "invalid_trace")
    assert client.step("into")["currentEntityUsr"] == "python:program:C"  # bad loads retained the trace


def test_trace_metadata_and_repeat_edges_share_the_group_cursor(clients, project):
    client = clients()
    open_project(client, project)
    rows = (("E", 0, "main"), ("E", 1, "A"), ("E", 2, "B"), ("X", 2, "B"),
            ("E", 2, "B"), ("X", 2, "B"), ("X", 1, "A"), ("E", 1, "E"))
    client.ok("trace.load", {"path": str(write_trace(project, rows))})
    selected = client.step("seek", usr="python:program:B")
    assert selected["repeatCount"] == 2 and selected["callerCounts"] == {"python:program:A": 2}
    assert selected["currentCall"]["sequence"] == 2
    assert selected["currentCall"]["threadId"] == "thread-1" and selected["currentCall"]["depth"] == 2
    assert client.step("out")["currentEntityUsr"] == "python:program:E"
    assert client.step("previous") == selected
    reset = client.ok("trace.reset", {"traceId": client.trace_id})
    assert reset["currentCall"] is None and reset["callerCounts"] == {} and reset["repeatCount"] == 0


def test_trace_view_includes_recorded_nodes_without_rerooting_or_changing_static_view(clients, project):
    client = clients()
    open_project(client, project)
    params = {"view": "call", "root": "python:program:A", "depth": 0}
    before = client.ok("view.get", params)
    assert [node["usr"] for node in before["nodes"]] == ["python:program:A"]
    loaded = client.ok("trace.load", {"path": str(write_trace(project))})
    graph = client.ok("view.get", {**params, "traceId": loaded["traceId"]})
    assert graph["roots"] == before["roots"] and graph["root"] == before["root"]
    assert {node["usr"] for node in graph["nodes"]} == {f"python:program:{name}" for name in ("main", "A", "B", "C", "D", "E")}
    client.step("seek", usr="python:program:E")
    assert client.ok("view.get", {**params, "traceId": loaded["traceId"]}) == graph
    assert client.ok("view.get", params) == before
    assert_error(client.request("view.get", {**params, "traceId": "obsolete"}), "invalid_trace")
    assert_error(client.request("view.get", {**params, "traceId": 3}), "invalid_params")


def test_service_disables_depth_steps_when_the_parent_return_is_missing(clients, project):
    client = clients()
    open_project(client, project)
    rows = (("E", 0, "main"), ("E", 1, "A"), ("E", 2, "B"), ("X", 2, "B"), ("E", 1, "E"))
    client.ok("trace.load", {"path": str(write_trace(project, rows))})
    before = client.step("seek", usr="python:program:B")
    assert before["availability"] == {"into": True, "over": False, "out": False, "previous": True, "reset": True}
    assert client.step("out") == before and client.step("over") == before
    assert client.step("into")["currentEntityUsr"] == "python:program:E"


def test_protocol_errors_recover_and_cancel_is_honest(clients, project):
    client = clients()
    assert_error(client.request("project.open", {"path": str(project)}), "not_initialized")
    assert_error(client.request("initialize", {"protocolVersion": 2}), "protocol_version_mismatch")
    client.ok("initialize", {"protocolVersion": 1})
    for frame, code in ((b"{", "invalid_json"), (b"\xff", "invalid_json"),
                        (b"NaN", "invalid_json"), (b"[]", "invalid_request"),
                        (b'{"id":true}', "invalid_request"), (b"{}", "invalid_request"),
                        (b"x" * (MAX_MESSAGE_BYTES + 1), "message_too_large")):
        response = client.exchange(frame)
        assert "id" not in response and response["method"] == "protocol.error"
        assert response["params"]["error"]["code"] == code
    assert_error(client.request("unknown"), "unknown_method")
    assert_error(client.request("project.analyse"), "project_not_open")
    assert client.ok("operation.cancel", {"requestId": "unknown"}) == {
        "requestId": "unknown", "cancellable": False, "reason": "not_cancellable"}
    assert_error(client.request("operation.cancel", {"requestId": False}), "invalid_params")
    for frame, code in ((b'{"id":0,"method":"initialize"}', "invalid_params"),
                        (b'{"id":"string-id","method":2,"params":{}}', "invalid_request"),
                        (b'{"id":7,"method":"project.open","params":[]}', "invalid_params")):
        assert_error(client.exchange(frame), code)


def test_invalid_parameters_and_stale_identities_do_not_mutate_state(clients, project, tmp_path):
    client = clients()
    client.ok("initialize", {"protocolVersion": 1})
    for params in ({}, {"path": 3}, {"path": "relative"}, {"path": str(project), "extra": True}):
        assert_error(client.request("project.open", params), "invalid_params")
    assert_error(client.request("project.open", {"path": str(tmp_path / "absent")}), "project_missing")
    opened = client.ok("project.open", {"path": str(project)})
    assert_error(client.request("project.analyse", sessionId="old"), "invalid_session")
    assert_error(client.request("project.analyse", modelRevision=99), "stale_revision")
    assert_error(client.request("project.analyse", modelRevision=True), "invalid_params")
    assert_error(client.request("project.analyse", targetId="executable"), "stale_target")
    assert_error(client.request("project.analyse", sessionId=None), "invalid_params")
    for params in ({}, {"sourceRootId": opened["sourceRootId"], "file": "program.py", "line": 0},
                   {"sourceRootId": opened["sourceRootId"], "usr": "a", "file": "b"}):
        assert_error(client.request("source.resolve", params), "invalid_params")
    client.ok("project.analyse")
    assert_error(client.request("trace.reset", {"traceId": "none"}), "trace_not_loaded")
    loaded = client.ok("trace.load", {"path": str(write_trace(project))})
    for params in ({"traceId": client.trace_id}, {"traceId": client.trace_id, "action": "next"},
                   {"traceId": client.trace_id, "action": "seek"}):
        assert_error(client.request("trace.step", params), "invalid_params")
    assert_error(client.request("trace.step", {"traceId": "old", "action": "into"}), "invalid_trace")
    assert_error(client.request("trace.step", {"traceId": client.trace_id, "action": "seek", "usr": "absent"}),
                 "trace_call_missing")
    assert client.step("into")["position"] == 1
    client.ok("project.open", {"path": str(tmp_path)})
    assert_error(client.request("trace.reset", {"traceId": loaded["traceId"]}), "trace_not_loaded")
    assert_error(client.request("project.analyse", **{key: loaded[key] for key in client.context}), "invalid_session")


def test_fresh_interpreter_import_and_running_service_are_headless(clients, project):
    client = clients('''
import sys
from icoda_core import service
def check():
    assert not any(name == "tkinter" or name.startswith("tkinter.") or
                   name == "icoda_gui" or name.startswith("icoda_gui.") for name in sys.modules)
check()
service.main()
check()
''')
    open_project(client, project)
    targets = client.ok("targets.list")["targets"]
    client.ok("target.select", {"targetId": targets[1]["id"]})
    assert len(client.ok("view.get", {"view": "call"})["nodes"]) == 6
    assert client.ok("issues.list")["findings"]
    assert client.ok("coverage.get")["structuralTestReachability"]["entries"]
    document = client.ok("spec.get")["document"]
    assert client.ok("spec.validate", {"document": document})["valid"]
    client.ok("spec.save", {"document": document, "trusted": True})
    assert client.ok("phase.get")["allowedTransitions"] == ["architecture"]
    client.ok("phase.transition", {"phase": "architecture", "trusted": True})
    client.ok("providers.list")
    client.ok("target.select", {"targetId": None})
    client.ok("view.get", {"view": "call"})
    client.ok("view.get", {"view": "class"})
    client.ok("source.resolve", {"sourceRootId": client.context["sessionId"] + ":workspace", "file": "program.py"})
    client.ok("trace.load", {"path": str(write_trace(project))})
    client.step("into")
    client.close()


def test_backend_logs_and_native_stdout_do_not_corrupt_protocol(clients, project):
    client = clients('''
import logging, os, subprocess, sys
from icoda_core import service, session
logger = logging.getLogger("noisy-core")
logger.addHandler(logging.StreamHandler(sys.stdout))
original = session.analyse_in_child
def noisy(*args, **kwargs):
    print("core print")
    logger.warning("core log")
    os.write(1, b"native stdout\\n")
    subprocess.run([sys.executable, "-c", "print('child stdout')"], check=True)
    return original(*args, **kwargs)
session.analyse_in_child = noisy
service.main()
''')
    assert open_project(client, project)["model"]["entities"]
    client.close()
    assert all(message in client.logs for message in ("core print", "core log", "native stdout", "child stdout"))


def test_analysis_child_failure_is_typed_and_keeps_cache_stale(clients, project):
    client = clients('''
from icoda_core import service, session
def failed(*args, **kwargs):
    return session.AnalysisResult(None, None, ["analysis crashed with signal 11"])
session.analyse_in_child = failed
service.main()
''')
    # Seed a genuine cached model through another real service process.
    seed = clients()
    good = open_project(seed, project)
    seed.close()
    open_project(client, project, analyse=False)
    failed = assert_error(client.request("project.analyse"), "analysis_failed")
    assert failed["model"]["entities"] == good["model"]["entities"] and failed["model"]["stale"]
    assert "signal 11" in failed["model"]["stale_reason"]


@pytest.fixture
def target_project(cmake_project):
    """Real configured targets with a controlled cached model; no target is built."""
    root, model = cmake_project
    (root / "shared.cpp").write_text('void helper() {}\nvoid api() { helper(); }\nvoid unused() {}\n')
    (root / "shared.hpp").write_text('void api();\nvoid unused();\n')
    for file in ("shared.cpp", "shared.hpp"):
        model.files[file] = FileInfo(file)
    for name, line in (("helper", 1), ("api", 2), ("unused", 3)):
        model.add_entity(Entity(name, Kind.FUNCTION, name, name, "shared.cpp", line,
                                declaration_file="" if name == "helper" else "shared.hpp"))
    model.add_edge(Edge(EdgeKind.CALLS, "api", "helper", "shared.cpp", 2))
    model.add_edge(Edge(EdgeKind.CALLS, "first", "api", model.entities["first"].file, 3))
    (root / model.entities["first"].file).write_text('#include "../../shared.hpp"\n\nint main() { api(); }\n')
    with (root / "CMakeLists.txt").open("a") as output:
        output.write('add_library(shared STATIC shared.cpp)\ntarget_link_libraries(first PRIVATE shared)\n')
    result = subprocess.run(cmake.configure_command(root, root / "build/debug"),
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    persistence.ProjectStore(root).save_model(model)
    return root


def file_contents(root: Path) -> dict[str, bytes]:
    """Detect discovery side effects, including attempted CMake configuration."""
    return {file.relative_to(root).as_posix(): file.read_bytes() for file in root.rglob("*") if file.is_file()}


def test_targets_use_real_discovery_without_building_and_have_stable_ids(clients, target_project):
    client = clients('''
import subprocess
from icoda_core import cmake, executables, service
def forbidden(*args, **kwargs):
    raise AssertionError("Listing/selection/viewing must not configure, build or launch tools")
subprocess.Popen = forbidden
cmake.configure_command = executables.operate = forbidden
service.main()
''')
    before = file_contents(target_project)
    opened = open_project(client, target_project, analyse=False)
    listed = client.ok("targets.list")
    items = listed["targets"]
    assert items[0] == {"id": None, "kind": "whole-project", "name": "Whole Project", "label": "Whole Project",
                        "configuration": None, "entryUsr": None}
    assert {(t["name"], t["kind"], t["configuration"]) for t in items[1:]} == {
        ("first", "executable", "Debug"), ("second", "executable", "Debug"), ("shared", "library", "Debug")}
    assert len({t["id"] for t in items}) == len(items) and not listed["diagnostics"]
    assert client.ok("targets.list") == listed
    client.ok("view.get", {"view": "call"})
    assert file_contents(target_project) == before
    chosen = client.ok("target.select", {"targetId": items[1]["id"]})
    reopened = client.ok("project.open", {"path": str(target_project)})
    assert reopened["sessionId"] != opened["sessionId"] and reopened["targetId"] == chosen["targetId"]
    assert client.ok("targets.list")["targets"] == items
    assert not file_contents(target_project / "bin") and not (target_project / "build/debug/second").exists()


def test_target_selection_projects_dependencies_and_preserves_whole_model(clients, target_project):
    store = persistence.ProjectStore(target_project)
    store.save_ui({"executable": [], "unrelated": {"keep": True}})
    before = store.model_path.read_bytes()
    client = clients()
    whole = open_project(client, target_project, analyse=False)["model"]
    overview = client.ok("view.get", {"view": "call"})
    items = {item["name"]: item for item in client.ok("targets.list")["targets"]}
    first = client.ok("target.select", {"targetId": items["first"]["id"]})
    assert first["modelRevision"] == 2 and first["targetId"] == items["first"]["id"]
    assert {e["usr"] for e in first["model"]["entities"]} == {"first", "api", "helper", "unused"}
    second = client.ok("target.select", {"targetId": items["second"]["id"]})
    view = client.ok("view.get", {"view": "call"})
    assert second["modelRevision"] == 3 and view["root"] == "second"
    assert {n["usr"] for n in view["nodes"]} == {"second"}
    restored = client.ok("target.select", {"targetId": None})
    assert restored["modelRevision"] == 4 and restored["model"] == whole
    graph = client.ok("view.get", {"view": "call"})
    assert graph["nodes"] == overview["nodes"] and graph["edges"] == overview["edges"]
    assert store.model_path.read_bytes() == before
    assert store.load_ui() == {"executable": [], "unrelated": {"keep": True}}
    assert client.ok("project.open", {"path": str(target_project)})["model"] == whole
    assert client.context["targetId"] is None


def test_library_roots_and_explicit_root_depth_match_core(clients, target_project):
    client = clients()
    open_project(client, target_project, analyse=False)
    item = next(t for t in client.ok("targets.list")["targets"] if t["kind"] == "library")
    selected = client.ok("target.select", {"targetId": item["id"]})
    model = DerivedModel.from_json(json.dumps(selected["model"]))
    graph = client.ok("view.get", {"view": "call"})
    assert graph["libraryMode"] and graph["root"] is None
    assert graph["roots"] == list(views.library_roots(model)) == ["api", "unused"]
    assert {n["usr"] for n in graph["nodes"]} == {"api", "helper", "unused"}
    assert graph["edges"] == [{**asdict(e), "kind": "calls"}
                              for e in views.layout_call_view(model, ("api", "unused")).edges]
    shallow = client.ok("view.get", {"view": "call", "root": "api", "depth": 0})
    assert shallow["root"] == "api" and shallow["roots"] == ["api"]
    assert [n["usr"] for n in shallow["nodes"]] == ["api"] and shallow["edges"] == []
    assert_error(client.request("view.get", {"view": "call", "root": "first"}), "unknown_root")


def test_call_view_has_real_python_locations_edges_and_core_geometry(clients, project):
    client = clients()
    analysed = open_project(client, project)
    graph = client.ok("view.get", {"view": "call"})
    model = DerivedModel.from_json(json.dumps(analysed["model"]))
    layout = views.layout_call_view(model, "python:program:main")
    assert graph["root"] == "python:program:main" and graph["roots"] == [graph["root"]]
    assert len(graph["nodes"]) == 6 and not graph["stale"] and not graph["libraryMode"]
    assert (graph["width"], graph["height"]) == (layout.width, layout.height)
    for node in graph["nodes"]:
        assert node == {**asdict(layout.nodes[node["usr"]]), "file": "program.py",
                        "line": model.entities[node["usr"]].line, "sourceRootId": analysed["sourceRootId"]}
    assert {(n["usr"].rsplit(":", 1)[1], n["line"]) for n in graph["nodes"]} == {
        ("main", 3), ("A", 7), ("B", 11), ("C", 14), ("D", 18), ("E", 21)}
    assert graph["edges"] == [{**asdict(e), "kind": "calls"} for e in layout.edges]
    assert {(e["source"].rsplit(":", 1)[1], e["target"].rsplit(":", 1)[1]) for e in graph["edges"]} == {
        ("main", "A"), ("main", "E"), ("A", "B"), ("A", "D"), ("B", "C")}
    assert not any(e["uncertain"] or e["loop"] for e in graph["edges"])


def test_service_and_desktop_call_the_same_layout_function(app_module, project, monkeypatch):
    """Spy on real layout invocation by both frontends, not a duplicated expected graph."""
    from icoda_gui.call_view import CallViewCanvas

    model = python_analysis.parse_project(project)
    persistence.ProjectStore(project).save_model(model)
    backend = Service()
    backend.initialize({"protocolVersion": 1})
    backend.open_project({"path": str(project)})
    session = backend.project
    assert session is not None
    before = session.model.to_json()
    layouts = []
    original = views.layout_call_view

    def record(*args, **kwargs):
        result = original(*args, **kwargs)
        layouts.append(result)
        return result

    monkeypatch.setattr(views, "layout_call_view", record)
    canvas = CallViewCanvas(app_module.tk.Tk(), lambda *_: None)
    canvas.entry_usr = session.selected.usr
    canvas.show(session.scoped_model())
    graph = backend.get_view(session, {"view": "call"})
    assert len(layouts) == 2 and layouts[0] == layouts[1] == canvas.layout
    assert [n["usr"] for n in graph["nodes"]] == list(canvas.layout.nodes)
    backend.select_target(session, {"targetId": None})
    assert session.model.to_json() == before


@pytest.mark.parametrize("method,params", [("targets.list", {}), ("target.select", {"targetId": None}),
                                          ("view.get", {"view": "call"})])
def test_new_methods_reject_stale_identity_before_mutating(clients, project, method, params):
    client = clients()
    open_project(client, project)
    before = file_contents(project)
    expected = dict(client.context)
    assert_error(client.request(method, params, sessionId="old"), "invalid_session")
    assert_error(client.request(method, params, modelRevision=1), "stale_revision")
    assert_error(client.request(method, params, targetId="old"), "stale_target")
    assert_error(client.request(method, params, targetId=12), "invalid_params")
    assert client.context == expected and file_contents(project) == before


def test_target_changes_invalidate_playback_but_reselecting_is_idempotent(clients, project):
    client = clients()
    open_project(client, project)
    loaded = client.ok("trace.load", {"path": str(write_trace(project))})
    client.step("into")
    previous = dict(client.context)
    selected = client.ok("target.select", {"targetId": previous["targetId"]})
    assert selected["modelRevision"] == previous["modelRevision"]
    assert client.step("into")["position"] == 2
    assert_error(client.request("target.select", {"targetId": "unknown"}), "unknown_target")
    assert client.step("into")["position"] == 3
    client.ok("target.select", {"targetId": None})
    assert_error(client.request("trace.reset", {"traceId": loaded["traceId"]}), "trace_not_loaded")
    assert_error(client.request("target.select", {"targetId": previous["targetId"]}, **previous), "stale_revision")
    client.ok("project.analyse")
    assert client.context["targetId"] is None  # explicit Whole Project survives a sole main


def test_view_and_selection_errors_are_structured_and_do_not_corrupt_stdout(clients, project):
    client = clients()
    open_project(client, project, analyse=False)
    assert_error(client.request("view.get", {"view": "call"}), "model_unavailable")
    assert_error(client.request("view.get", {"view": "unknown"}), "unknown_view")
    client.ok("project.analyse")
    for params in ({}, {"targetId": 3}, {"targetId": ""}, {"targetId": None, "extra": True}):
        assert_error(client.request("target.select", params), "invalid_params")
    for params in ({}, {"view": "call", "depth": -1}, {"view": "call", "depth": True},
                   {"view": "call", "root": []}, {"view": "call", "callers": 1},
                   {"view": "call", "callers": "true"}, {"view": "call", "callers": None}):
        assert_error(client.request("view.get", params), "invalid_params")
    assert_error(client.request("view.get", {"view": "call", "root": "absent"}), "unknown_root")
    assert_error(client.request("targets.list", {"refresh": True}), "invalid_params")
    assert len(client.ok("view.get", {"view": "call", "root": None})["nodes"]) == 6


def test_callers_switch_matches_shared_layout_without_changing_defaults(clients, project):
    client = clients()
    analysed = open_project(client, project)
    model = DerivedModel.from_json(json.dumps(analysed["model"]))
    params = {"view": "call", "root": "python:program:B", "depth": 2}
    default = client.ok("view.get", params)
    assert not default["callers"]
    assert default == client.ok("view.get", {**params, "callers": False})
    graph = client.ok("view.get", {**params, "callers": True})
    layout = views.layout_call_view(model, params["root"], 2, callers=True)
    assert graph["callers"] and graph["root"] == params["root"]
    assert graph["modelRevision"] == default["modelRevision"]
    assert graph["targetId"] == default["targetId"]
    assert {n["usr"].rsplit(":", 1)[1] for n in graph["nodes"]} == {"main", "A", "B"}
    assert [(n["usr"], n["x"], n["y"], n["level"]) for n in graph["nodes"]] == [
        (n.usr, n.x, n.y, n.level) for n in layout.nodes.values()]
    assert graph["edges"] == [{**asdict(e), "kind": "calls"} for e in layout.edges]


@pytest.mark.parametrize("metadata", [None, "not JSON"])
def test_missing_or_invalid_target_metadata_retains_source_entries(clients, target_project, metadata):
    reply = target_project / "build/debug/.cmake/api/v1/reply"
    for index in reply.glob("index-*.json"):
        if metadata is None:
            index.unlink()
        else:
            index.write_text(metadata)
    client = clients()
    open_project(client, target_project, analyse=False)
    catalog = client.ok("targets.list")
    code = "target_metadata_unavailable" if metadata is None else "target_metadata_invalid"
    assert catalog["diagnostics"][0]["code"] == code
    assert {t["entryUsr"] for t in catalog["targets"]} == {None, "first", "second"}
    assert all(t["configuration"] is None for t in catalog["targets"])
    target = next(t for t in catalog["targets"] if t["entryUsr"] == "first")
    client.ok("target.select", {"targetId": target["id"]})
    assert client.ok("view.get", {"view": "call"})["root"] == "first"


def test_call_view_preserves_uncertainty_recursion_and_external_locations(clients, target_project):
    store = persistence.ProjectStore(target_project)
    model = store.load_model()
    model.add_edge(Edge(EdgeKind.CALLS, "helper", "helper", "shared.cpp", 1, uncertain=True))
    model.add_edge(Edge(EdgeKind.CALLS, "api", "external:std", "shared.cpp", 2, label="puts"))
    model.entities["api"].status = "tested"
    model.entities["helper"].file = str(target_project.parent / "outside.cpp")
    store.save_model(model)
    client = clients()
    open_project(client, target_project, analyse=False)
    graph = client.ok("view.get", {"view": "call"})
    loop = next(e for e in graph["edges"] if e["source"] == e["target"] == "helper")
    assert loop["loop"] and loop["uncertain"] and loop["kind"] == "calls"
    nodes = {n["usr"]: n for n in graph["nodes"]}
    assert nodes["api"]["status"] == "tested"
    assert nodes["external:std"]["kind"] == "external"
    assert nodes["external:std"]["file"] is None and nodes["external:std"]["line"] is None
    assert nodes["helper"]["file"] is None and nodes["helper"]["line"] == 1


def test_empty_and_stale_cached_models_remain_viewable(clients, project):
    store = persistence.ProjectStore(project)
    store.save_model(DerivedModel(str(project)))
    client = clients()
    open_project(client, project, analyse=False)
    empty = client.ok("view.get", {"view": "call"})
    assert empty["nodes"] == empty["edges"] == empty["roots"] == [] and empty["root"] is None
    client.ok("project.analyse")
    (project / "program.py").write_text("def broken(\n", encoding="utf-8")
    assert_error(client.request("project.analyse"), "analysis_failed")
    stale = client.ok("view.get", {"view": "call"})
    assert stale["stale"] and stale["staleReason"] and len(stale["nodes"]) == 6


def test_selection_write_failure_keeps_revision_target_and_trace(clients, project):
    seed = clients()
    open_project(seed, project)
    seed.close()
    client = clients('''
from icoda_core import persistence, service
def failed(*args, **kwargs):
    raise OSError("UI state is read-only")
persistence.ProjectStore.save_ui = failed
service.main()
''')
    open_project(client, project, analyse=False)
    client.ok("trace.load", {"path": str(write_trace(project))})
    before = dict(client.context)
    details = assert_error(client.request("target.select", {"targetId": None}), "selection_failed")
    assert all(details[key] == value for key, value in before.items())
    assert client.step("into")["currentEntityUsr"] == "python:program:main"


@pytest.fixture
def tool_service(monkeypatch, tmp_path):
    """An empty search environment makes missing-tool checks independent of this host."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "environ", {"PATH": str(tmp_path / "empty"), "KEEP_ME": "unchanged"})
    monkeypatch.setattr(toolchain, "candidates", lambda **_kwargs: [])
    backend = Service()
    backend.initialize({"protocolVersion": 1})
    return backend


def tool_request(backend, params=None):
    return handle_line(backend, json.dumps({"id": 1, "method": "toolchain.inspect", "params": params or {}}).encode())


def tool_files(directory, names):
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        path = directory / name
        path.touch()
        path.chmod(0o755)
    return {name: str(directory / name) for name in names}


def test_toolchain_inspect_overrides_win_and_environment_is_child_only(tool_service, tmp_path, monkeypatch):
    names = ("cmake", "ninja", "clang++", "clang", "clang-scan-deps", "llvm-symbolizer")
    inherited = tool_files(tmp_path / "on path", names)
    explicit = tool_files(tmp_path / "explicit ü", names)
    monkeypatch.setenv("PATH", str(Path(inherited["cmake"]).parent))
    monkeypatch.setenv("CXX", inherited["clang++"])
    probes = []

    def probe(command, **kwargs):
        probes.append((command, kwargs["env"]))
        return subprocess.CompletedProcess(command, 0, "clang version 18.1.8", "")

    monkeypatch.setattr(toolchain.subprocess, "run", probe)
    before = dict(os.environ)
    overrides = {setting: explicit["clang++" if name == "clang" else name]
                 for name, setting in toolchain.TOOL_SETTINGS.items()}
    result = tool_request(tool_service, overrides)["result"]
    assert result["tools"] == [{"name": name, "path": overrides[setting], "source": "override"}
                               for name, setting in toolchain.TOOL_SETTINGS.items()]
    assert not result["errors"] and not result["diagnostics"]
    assert result["environment"]["CC"] == explicit["clang"]
    assert result["environment"]["CXX"] == explicit["clang++"]
    assert result["environment"]["PATH"].split(os.pathsep)[0] == str(tmp_path / "explicit ü")
    assert "KEEP_ME" not in result["environment"] and result["runtime"]["python"] == sys.executable
    assert probes[0][0] == [explicit["clang++"], "--version"]
    assert probes[0][1]["KEEP_ME"] == "unchanged"
    assert os.environ == before


def test_toolchain_inspect_missing_tools_have_actionable_errors(tool_service):
    before = dict(os.environ)
    result = tool_request(tool_service)["result"]
    assert result["tools"] == [{"name": name, "path": None, "source": "missing"}
                               for name in toolchain.TOOL_SETTINGS]
    for error in result["errors"]:
        assert error["code"] == "missing_tool"
        name = error["details"]["tool"]
        setting = "icoda.toolchain." + toolchain.TOOL_SETTINGS[name]
        assert error["details"]["setting"] == setting
        assert name in error["message"] and setting in error["message"]
    details = assert_error(tool_request(tool_service, {"requiredTools": ["ninja"]}), "missing_tool")
    assert details["tool"] == "ninja" and details["setting"] == "icoda.toolchain.ninjaPath"
    assert details["inspection"] == result
    assert result["environment"] == {} and os.environ == before


@pytest.mark.parametrize("name", toolchain.TOOL_SETTINGS)
def test_invalid_tool_override_does_not_silently_fall_back(tool_service, tmp_path, monkeypatch, name):
    tools = tool_files(tmp_path / "bin", ("cmake", "ninja", "clang++", "clang", "clang-scan-deps", "llvm-symbolizer"))
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setattr(toolchain.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, 0, "clang version 18.1.8", ""))
    result = tool_request(tool_service, {toolchain.TOOL_SETTINGS[name]: str(tmp_path / "absent")})["result"]
    missing = next(tool for tool in result["tools"] if tool["name"] == name)
    assert missing == {"name": name, "path": None, "source": "missing"}
    for tool in result["tools"]:
        if tool["name"] != name:
            assert tool["source"] == "path"
            assert tool["path"] == tools["clang++" if tool["name"] == "clang" else tool["name"]]


@pytest.mark.parametrize("params", [{"cmakePath": 1}, {"ninjaPath": ""}, {"clangPath": "bad\0path"},
                                    {"llvmSymbolizerPath": None}, {"unknown": "tool"},
                                    {"requiredTools": "cmake"}, {"requiredTools": ["python"]},
                                    {"requiredTools": [{}]}])
def test_toolchain_inspect_validates_before_discovery(tool_service, monkeypatch, params):
    monkeypatch.setattr(toolchain, "inspect_tools", lambda *_: pytest.fail("invalid params reached discovery"))
    assert_error(tool_request(tool_service, params), "invalid_params")


def test_missing_build_tools_do_not_block_view_source_or_trace(tool_service, project):
    persistence.ProjectStore(project).save_model(python_analysis.parse_project(project))
    trace_path = write_trace(project)
    before = dict(os.environ)
    assert len(tool_request(tool_service)["result"]["errors"]) == 4
    opened = tool_service.dispatch({"method": "project.open", "params": {"path": str(project)}})
    context = {key: opened[key] for key in ("sessionId", "modelRevision", "targetId")}
    graph = tool_service.dispatch({**context, "method": "view.get", "params": {"view": "call"}})
    assert len(graph["nodes"]) == 6
    source = tool_service.dispatch({**context, "method": "source.resolve", "params": {
        "sourceRootId": opened["sourceRootId"], "usr": "python:program:B"}})
    assert source["path"] == str(project / "program.py") and source["line"] == 11
    trace = tool_service.dispatch({**context, "method": "trace.load", "params": {"path": str(trace_path)}})
    stepped = tool_service.dispatch({**context, "method": "trace.step", "params": {
        "traceId": trace["traceId"], "action": "into"}})
    assert trace["resolvedCalls"] == 6 and stepped["currentEntityUsr"] == "python:program:main"
    assert os.environ == before


def test_toolchain_inspect_real_service_needs_no_project(clients, tmp_path):
    client = clients()
    initialized = client.ok("initialize", {"protocolVersion": 1})
    assert "toolchain.inspect" in initialized["capabilities"]["methods"]
    result = client.ok("toolchain.inspect", {"cmakePath": str(tmp_path / "missing-cmake")})
    assert result["tools"][0] == {"name": "cmake", "path": None, "source": "missing"}
    assert result["runtime"] == initialized["runtime"]
    error = assert_error(client.request("toolchain.inspect", {
        "cmakePath": str(tmp_path / "missing-cmake"), "requiredTools": ["cmake"]}), "missing_tool")
    assert error["tool"] == "cmake" and error["setting"] == "icoda.toolchain.cmakePath"


def test_inspection_reuses_versioned_clang_discovery(tool_service, tmp_path, monkeypatch):
    tools = tool_files(tmp_path / "bin", ("clang++-18", "clang-18", "clang-scan-deps-18"))
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setattr(toolchain.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, 0, "clang version 18.1.8", ""))
    result = tool_request(tool_service)["result"]
    assert result["tools"][2] == {"name": "clang", "path": tools["clang++-18"], "source": "discovered"}
    assert result["environment"]["CXX"] == tools["clang++-18"]
    assert result["environment"]["CC"] == tools["clang-18"]


def test_inspection_finds_symbolizer_beside_detected_libclang(tool_service, tmp_path, monkeypatch):
    binary = tool_files(tmp_path / "llvm/bin", ("llvm-symbolizer",))["llvm-symbolizer"]
    library = tmp_path / "llvm/lib/libclang.so"
    library.parent.mkdir()
    library.touch()
    monkeypatch.setattr(toolchain, "candidates", lambda **_kwargs: [toolchain.Candidate(str(library), "linux")])
    result = tool_request(tool_service)["result"]
    symbolizer = result["tools"][3]
    assert Path(symbolizer["path"]).resolve() == Path(binary)
    assert symbolizer["source"] == "discovered"


@pytest.fixture
def target_service(tmp_path, monkeypatch):
    """Exercise the real target orchestration with deterministic configure/process boundaries."""
    from icoda_core import executables, process

    root = tmp_path / "target"
    root.mkdir()
    model = DerivedModel(str(root), files={"main.cpp": FileInfo("main.cpp")})
    model.add_entity(Entity("main", Kind.FUNCTION, "main", "main", "main.cpp", 1))
    store = persistence.ProjectStore(root)
    store.save_model(model)
    target = executables.Target("demo", "Debug", root / "build", root / "build/demo",
                                frozenset({str(root / "main.cpp")}))
    monkeypatch.setattr(executables, "read_targets", lambda *_args: (target,))
    environment = {**os.environ, "CXX": "/tools/clang++", "CC": "/tools/clang", "ICODA_CHILD_ONLY": "yes"}
    report = {"tools": [{"name": name, "path": "/tools/" + name, "source": "discovered"}
                        for name in ("cmake", "ninja", "clang")], "environment": environment, "diagnostics": []}
    monkeypatch.setattr(toolchain, "inspect_tools", lambda _overrides, **_kwargs: report.copy())
    monkeypatch.setattr(cmake, "clang_configuration", lambda _root, **_kwargs:
                        (target.build_dir, ["/tools/cmake", "configure"], environment))
    monkeypatch.setattr(cmake, "verify_clang", lambda _directory: None)
    monkeypatch.setattr(process, "run_bounded", lambda command, **_kwargs:
                        process.ProcessResult(command, 0, "", ""))
    notifications = []
    backend = Service(notifications.append)
    backend.initialize({"protocolVersion": 1})
    backend.open_project({"path": str(root)})
    return backend, notifications, target


def operation_request(backend, method="build.run", params=None, **context):
    if method in OPERATIONS:
        params = {"trusted": True, **(params or {})}
    request = {"id": 100, "method": method, "params": params or {}, **backend.project.context(), **context}
    return handle_line(backend, json.dumps(request).encode())


def test_target_operations_advertise_capabilities_and_child_environment(target_service, monkeypatch):
    from icoda_core import process

    backend, notifications, target = target_service
    before, calls = dict(os.environ), []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        kwargs["output"]("child output\n")
        return process.ProcessResult(command, 0, "child output\n", "")
    monkeypatch.setattr(process, "run_bounded", run)
    result = operation_request(backend, "target.run")
    assert result["status"] == "ok", result
    assert result["result"]["executable"] == str(target.artifact)
    assert result["result"]["target"]["name"] == "demo"
    assert len(calls) == 3 and calls[-1][0] == [str(target.artifact)]
    assert all(kwargs["env"]["ICODA_CHILD_ONLY"] == "yes" for _, kwargs in calls)
    assert all(kwargs["cancel_event"] is not None for _, kwargs in calls)
    assert os.environ == before
    assert {item["method"] for item in notifications} == {"operation.progress", "operation.log"}
    assert all(item["params"]["targetId"] == backend.project.context()["targetId"] for item in notifications)
    caps = Service().initialize({"protocolVersion": 1})["capabilities"]
    assert set(caps["cancellableMethods"]) == {"targets.refresh", "build.run", "target.run", "trace.record", "tests.run",
                                               "project.analyse", "view.get", "trace.load", "toolchain.inspect", "queue.continue", "spec.save"}
    assert set(caps["cancellableMethods"]) <= set(caps["methods"]) and caps["cancellation"]


@pytest.mark.parametrize("stage,code", [("configure", "build_failed"), ("--build", "build_failed"),
                                        ("demo", "run_failed")])
def test_target_operation_failures_remain_usable(target_service, monkeypatch, stage, code):
    from icoda_core import process

    backend, _, target = target_service
    def run(command, **kwargs):
        fails = stage in command if stage != "demo" else command == [str(target.artifact)]
        return process.ProcessResult(command, 2 if fails else 0, "", "diagnostic")
    monkeypatch.setattr(process, "run_bounded", run)
    assert_error(operation_request(backend, "target.run"), code)
    assert operation_request(backend, "targets.list")["status"] == "ok"


@pytest.mark.parametrize("field,value,code", [("modelRevision", 0, "invalid_params"),
    ("modelRevision", 999, "stale_revision"), ("targetId", "old", "stale_target"),
    ("sessionId", "old", "invalid_session")])
def test_target_operations_reject_stale_identity_before_launch(target_service, monkeypatch, field, value, code):
    from icoda_core import executables

    backend, _, _ = target_service
    monkeypatch.setattr(executables, "operate", lambda *_a, **_k: pytest.fail("stale operation launched"))
    assert_error(operation_request(backend, **{field: value}), code)


def test_target_operation_rejects_result_if_identity_changes(target_service, monkeypatch):
    from icoda_core import executables

    backend, _, _ = target_service
    original = executables.operate
    def operate(*args, **kwargs):
        outcome = original(*args, **kwargs)
        backend.project.revision += 1
        return outcome
    monkeypatch.setattr(executables, "operate", operate)
    assert_error(operation_request(backend), "stale_revision")


@pytest.mark.parametrize("tool,setting", [("cmake", "cmakePath"), ("clang", "clangPath"), ("ninja", "ninjaPath")])
def test_operation_missing_tool_identifies_setting(target_service, monkeypatch, tool, setting):
    backend, _, _ = target_service
    report = toolchain.inspect_tools({})
    for item in report["tools"]:
        if item["name"] == tool:
            item.update(path=None, source="missing")
    monkeypatch.setattr(toolchain, "inspect_tools", lambda _overrides, **_kwargs: report)
    details = assert_error(operation_request(backend, "trace.record", {setting: "/missing/tool"}), "missing_tool")
    assert details["tool"] == tool and details["setting"] == "icoda.toolchain." + setting


def test_refresh_advances_revision_and_preserves_whole_project(target_service, monkeypatch):
    from icoda_core import executables

    backend, _, target = target_service
    backend.select_target(backend.project, {"targetId": None})
    before = backend.project.revision
    monkeypatch.setattr(cmake, "build_directory", lambda _root: target.build_dir)
    monkeypatch.setattr(executables, "build_directory", lambda _root: target.build_dir)
    response = operation_request(backend, "targets.refresh")
    assert response["status"] == "ok", response
    result = response["result"]
    assert result["modelRevision"] == before + 1 and result["targetId"] is None
    assert result["targets"][1]["name"] == "demo"
    assert backend.project.store.load_ui()["executable"] == []


CANCEL_BOOTSTRAP = r'''import sys
from icoda_core import executables, process, service
service.operation_tools = lambda *_args: {"environment": {}, "tools": []}
def operate(root, model, selected, action, cancelled, options, **kwargs):
    code = """import os,time,subprocess,sys,signal
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
def stop(*_args):
    child.wait(timeout=3)
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
print(str(os.getpid())+' '+str(child.pid), flush=True)
time.sleep(60)
"""
    run = executables._operation_runner(root, cancelled, kwargs["environment"],
        kwargs["cancel_event"], [], kwargs["progress"], kwargs["log"])
    run([sys.executable, "-c", code], "Build" if action == "build" else "Running fixture")
executables.operate = operate
raise SystemExit(service.main())
'''


def active_operation(client, method):
    identifier = client.sequence + 1
    request = {**client.context, "id": identifier, "method": method, "params": {"trusted": True}}
    client.process.stdin.write(json.dumps(request).encode() + b"\n")
    client.process.stdin.flush()
    notifications = []
    while True:
        message = json.loads(client.lines.get(timeout=10))
        notifications.append(message)
        if message.get("method") == "operation.log":
            text = message["params"]["message"].strip()
            if text and all(part.isdigit() for part in text.split()):
                return identifier, list(map(int, text.split())), notifications


def assert_process_gone(pid):
    with pytest.raises(OSError):
        os.kill(pid, 0)


@pytest.mark.parametrize("method", ["build.run", "target.run"])
def test_cancel_kills_owned_child_tree_and_keeps_protocol_framed(clients, project, method):
    client = clients(CANCEL_BOOTSTRAP)
    open_project(client, project)
    identifier, pids, notifications = active_operation(client, method)
    frame = {"id": identifier + 1, "method": "operation.cancel", "params": {"requestId": identifier}}
    client.process.stdin.write(json.dumps(frame).encode() + b"\n")
    client.process.stdin.flush()
    responses = {}
    while len(responses) < 2:
        message = json.loads(client.lines.get(timeout=10))
        if "id" in message:
            responses[message["id"]] = message
        else:
            notifications.append(message)
    assert responses[identifier + 1]["result"]["cancellable"] is True
    assert_error(responses[identifier], "cancelled")
    for pid in pids:
        assert_process_gone(pid)
    assert all(item["method"].startswith("operation.") for item in notifications)
    client.sequence = identifier + 1
    assert client.ok("targets.list")["targets"]


def test_service_shutdown_cancels_owned_children(clients, project):
    client = clients(CANCEL_BOOTSTRAP)
    open_project(client, project)
    identifier, pids, _ = active_operation(client, "target.run")
    client.process.stdin.close()
    response = json.loads(client.lines.get(timeout=10))
    while "id" not in response:
        response = json.loads(client.lines.get(timeout=10))
    assert response["id"] == identifier
    assert_error(response, "cancelled")
    client.process.wait(timeout=10)
    for pid in pids:
        assert_process_gone(pid)


def tree_bytes(directory):
    return {str(path.relative_to(directory)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in directory.rglob("*") if path.is_file()}


def cpp_recording_project(tmp_path):
    """Configure a real ordinary tree with a retained project option and real source analysis."""
    from icoda_core import process

    report = toolchain.inspect_tools({})
    paths = {item["name"]: item["path"] for item in report["tools"]}
    for name in ("cmake", "ninja"):
        if not paths[name]:
            pytest.skip(f"AT11 requires installed {name}; shared toolchain discovery found none")
    environment = {**os.environ, **report["environment"]}
    if not paths["clang"]:
        try:
            environment = cmake._instrumented_build_environment(None, environ=environment)
        except RuntimeError as exc:
            pytest.skip(f"AT11 requires Clang or GCC; discovery found no compiler: {exc}")
    root = tmp_path / "recorded C++"
    root.mkdir()
    (root / "main.cpp").write_text("volatile int count = 0;\nvoid helper() { ++count; }\n"
                                    "int main() { helper(); return count == 1 ? 0 : 1; }\n")
    (root / "CMakeLists.txt").write_text('cmake_minimum_required(VERSION 3.20)\nproject(Trace LANGUAGES CXX)\n'
        'if(NOT KEEP_SETTING STREQUAL "retained")\nmessage(FATAL_ERROR "Lost setting")\nendif()\n'
        'add_executable(demo main.cpp)\n')
    directory, command, environment = cmake.clang_configuration(root,
        environment=environment, tools=paths)
    configured = process.run_bounded([*command, "-DKEEP_SETTING=retained"], cwd=root, env=environment)
    assert configured.ok, configured.stdout + configured.stderr
    built = process.run_bounded([command[0], "--build", str(directory), "--target", "demo"], cwd=root, env=environment)
    assert built.ok, built.stdout + built.stderr
    return root, directory, bool(paths["clang"])


def test_at11_real_service_records_loads_and_steps_without_touching_ordinary_tree(clients, tmp_path):
    from icoda_core import executables

    root, ordinary, has_clang = cpp_recording_project(tmp_path)
    client = clients()
    opened = open_project(client, root)
    assert opened["model"]["entities"] and opened["targetId"]
    artifact = next(target.artifact for target in executables.read_targets(root)
                    if target.name == "demo")
    built = client.ok("build.run") if has_clang else {"executable": str(artifact), "targetId": opened["targetId"]}
    assert Path(built["executable"]).is_file()
    if has_clang:
        assert client.ok("target.run")["path"] is None
    before = tree_bytes(ordinary)
    recorded = client.ok("trace.record", {"durationSeconds": 2})
    assert tree_bytes(ordinary) == before
    path = Path(recorded["path"])
    assert path.is_file() and path.stat().st_size > 100
    assert ".icoda/cache/instrumented-debug-build" in recorded["executable"].replace("\\", "/")
    assert recorded["targetId"] == built["targetId"] and recorded["target"]["name"] == "demo"
    assert recorded["executable"] != built["executable"]
    loaded = client.ok("trace.load", {"path": str(path)})
    assert loaded["resolvedCalls"] >= 2 and loaded["availability"]["into"]
    step = client.step("into")
    assert step["currentEntityUsr"] and step["source"]["file"] == "main.cpp"
    assert any(n["method"] == "operation.log" and "Building" in n["params"]["message"] for n in client.notifications)


def test_cancelled_configuration_and_refresh_save_failure_leave_identity_usable(target_service, monkeypatch):
    from icoda_core import executables, steps

    backend, _, target = target_service
    before = backend.project.context()
    def cancelled(_root, **_kwargs):
        raise steps.StepCancelled()
    original = cmake.clang_configuration
    monkeypatch.setattr(cmake, "clang_configuration", cancelled)
    assert_error(operation_request(backend), "cancelled")
    monkeypatch.setattr(cmake, "clang_configuration", original)
    monkeypatch.setattr(executables, "build_directory", lambda _root: target.build_dir)
    def fail(_ui):
        raise OSError("cannot save selection")
    monkeypatch.setattr(backend.project.store, "save_ui", fail)
    assert_error(operation_request(backend, "targets.refresh"), "build_failed")
    assert backend.project.context() == before


def test_cancelled_tool_probe_reports_cancellation_before_build(target_service, monkeypatch):
    from icoda_core import executables, process

    backend, _, _ = target_service
    report = toolchain.inspect_tools({})
    def inspect(_overrides, *, cancel_event):
        cancel_event.set()
        with pytest.raises(InterruptedError, match="cancelled"):
            toolchain._probe(["compiler", "--version"], {}, 30, cancel_event)
        return report
    monkeypatch.setattr(toolchain, "inspect_tools", inspect)
    monkeypatch.setattr(process, "run_bounded", lambda args, **kw:
                        process.ProcessResult(args, -1, "", "", cancelled=kw["cancel_event"].is_set()))
    monkeypatch.setattr(executables, "operate", lambda *_a, **_k: pytest.fail("cancelled discovery launched build"))
    assert_error(operation_request(backend), "cancelled")


def test_operations_honor_cached_tools_and_explicit_overrides(target_service, monkeypatch, tmp_path):
    from icoda_core.service import operation_tools

    backend, _, target = target_service
    recorded = {}
    for name in ("cmake", "ninja", "clang++"):
        path = tmp_path / name
        path.touch()
        recorded[name] = str(path)
    cached = {key: ("FILEPATH", recorded[name]) for key, name in
              (("CMAKE_COMMAND", "cmake"), ("CMAKE_MAKE_PROGRAM", "ninja"), ("CMAKE_CXX_COMPILER", "clang++"))}
    cached["CMAKE_GENERATOR"] = ("INTERNAL", "Ninja")
    monkeypatch.setattr(cmake, "build_directory", lambda _root: target.build_dir)
    monkeypatch.setattr(cmake, "cache_values", lambda _directory: cached)
    report, seen = toolchain.inspect_tools({}), []
    def inspect(overrides, **_kwargs):
        seen.append(overrides)
        return report.copy()
    monkeypatch.setattr(toolchain, "inspect_tools", inspect)
    operation_tools("build.run", backend.project, {})
    operation_tools("build.run", backend.project, {"cmakePath": "/explicit/cmake"})
    assert seen[0] == {"cmakePath": recorded["cmake"], "ninjaPath": recorded["ninja"], "clangPath": recorded["clang++"]}
    assert seen[1]["cmakePath"] == "/explicit/cmake"


def test_recording_gcc_fallback_keeps_inherited_environment_out_of_report(target_service, monkeypatch):
    from icoda_core.service import operation_tools

    backend, _, _ = target_service
    monkeypatch.setenv("ICODA_TEST_PARENT_VALUE", "parent-only")
    report = toolchain.inspect_tools({})
    report["tools"][2].update(path=None, source="missing")
    monkeypatch.setattr(toolchain, "inspect_tools", lambda *_a, **_kw: report)
    monkeypatch.setattr(cmake, "_instrumented_build_environment", lambda *_a, **_kw:
                        {**os.environ, "CC": "/gcc", "CXX": "/g++"})
    inspected = operation_tools("trace.record", backend.project, {})
    assert inspected["environment"]["CXX"] == "/g++"
    assert "ICODA_TEST_PARENT_VALUE" not in inspected["environment"]


@pytest.fixture
def file_project(tmp_path):
    """Eighty files, internal calls, mixed cross-group edges, singleton and external nodes."""
    from icoda_core import clusters
    from icoda_core.model import External

    root = tmp_path / "file project"
    root.mkdir()
    model = DerivedModel(str(root))
    for group in range(5):
        for index in range(16):
            file = f"group{group}/file{index}.py"
            path = root / file
            path.parent.mkdir(exist_ok=True)
            path.write_text('def work():\n    return 1\n', encoding="utf-8")
            model.files[file] = FileInfo(file)
            model.add_entity(Entity("entity:" + file, Kind.FUNCTION, "work", f"g{group}.f{index}.work", file, 1))
            if index:
                model.add_edge(Edge(EdgeKind.CALLS, f"group{group}/file{index - 1}.py", file))
    for index in range(3):
        model.add_edge(Edge(EdgeKind.CALLS, f"group0/file{index}.py", f"group1/file{index}.py"))
    model.add_edge(Edge(EdgeKind.IMPORTS, "group0/file0.py", "group1/file0.py"))
    model.files["single.py"] = FileInfo("single.py")
    model.externals = {name: External(name) for name in ("std", "thirdparty")}
    model.add_edge(Edge(EdgeKind.CALLS, "group0/file0.py", "external:std"))
    model.add_edge(Edge(EdgeKind.INCLUDES, "group0/file0.py", "external:thirdparty"))
    store = persistence.ProjectStore(root)
    store.save_model(model)
    store.save_ui({"executable": []})
    store.save_layout(clusters.Layout({"group0": "Core"}, {f: "group0" for f in model.files if f.startswith("group0/")}))
    return root


def test_file_overview_expansion_reveal_and_relationship_counts(clients, file_project):
    from icoda_core import clusters

    client = clients()
    opened = open_project(client, file_project, analyse=False)
    model = DerivedModel.from_json(json.dumps(opened["model"]))
    store = persistence.ProjectStore(file_project)
    before = store.model_path.read_bytes(), store.layout_path.read_bytes(), store.ui_path.read_bytes()
    grouping = clusters.cluster_files(model, store.load_layout())
    overview = client.ok("view.get", {"view": "file"})
    assert overview["overview"] and overview["clusterPath"] == []
    assert len(overview["nodes"]) == 7 < len(model.files)
    assert sum(n["kind"] == "cluster" for n in overview["nodes"]) == 5
    core = next(n for n in overview["nodes"] if n["id"] == "cluster:group0")
    assert core["pinned"] and core["renamed"] and core["fileCount"] == 16 and core["label"] == "Core\n16 files"
    edge = next(e for e in overview["edges"] if e["target"] == "cluster:group1")
    assert edge["source"] == "cluster:group0" and edge["count"] == 4 and edge["counts"] == {"calls": 3, "imports": 1}
    assert sum(e["count"] for e in overview["edges"]) == 6
    for cluster in grouping.clusters:
        if len(cluster.files) < 2:
            continue
        detail = client.ok("view.get", {"view": "file", "clusterId": "cluster:" + cluster.id})
        assert not detail["overview"] and {n["entityId"] for n in detail["nodes"]} == set(cluster.files)
        assert all(n["file"] == n["id"] and n["sourceRootId"] == opened["sourceRootId"] for n in detail["nodes"])
        assert sum(e["count"] for e in detail["edges"]) == 15
        revealed = client.ok("view.revealFile", {"file": cluster.files[0], "sourceRootId": opened["sourceRootId"]})
        assert revealed["clusterPath"] == ["cluster:" + cluster.id] and revealed["entityId"] == cluster.files[0]
    assert client.ok("view.get", {"view": "file"}) == overview
    assert before == (store.model_path.read_bytes(), store.layout_path.read_bytes(), store.ui_path.read_bytes())


def test_cluster_pin_rename_unpin_persist_across_service_restart(clients, file_project):
    from icoda_core import clusters

    store = persistence.ProjectStore(file_project)
    before = store.load_layout()
    model_bytes, ui_bytes = store.model_path.read_bytes(), store.ui_path.read_bytes()
    client = clients()
    opened = open_project(client, file_project, analyse=False)
    grouping = clusters.cluster_files(store.load_model(), before)
    cluster_id = "cluster:group1"
    pinned = client.ok("cluster.pin", {"clusterId": cluster_id})
    node = next(n for n in pinned["nodes"] if n["id"] == cluster_id)
    assert node["pinned"] and not node["renamed"]
    expected = clusters.pin_cluster(before, grouping, "group1").to_layout()
    assert store.load_layout() == expected
    renamed = client.ok("cluster.rename", {"clusterId": cluster_id, "name": "  Grüße <Core>  ",
                                           "viewClusterId": cluster_id})
    assert renamed["clusterId"] == cluster_id and not renamed["overview"]
    assert renamed["clusterPath"] == [{"id": cluster_id, "label": "Grüße <Core>", "pinned": True}]
    assert renamed["modelRevision"] == opened["modelRevision"]
    expected = clusters.rename_cluster(expected, "group1", "Grüße <Core>").to_layout()
    assert store.load_layout() == expected
    assert client.ok("view.get", {"view": "file", "clusterId": cluster_id}) == renamed
    client.close()

    restarted = clients()
    reopened = open_project(restarted, file_project, analyse=False)
    assert reopened["sessionId"] != opened["sessionId"]
    assert reopened["layout"] == expected.to_dict()
    overview = restarted.ok("view.get", {"view": "file"})
    node = next(n for n in overview["nodes"] if n["id"] == cluster_id)
    assert node["name"] == "Grüße <Core>" and node["label"] == "Grüße <Core>\n16 files"
    assert node["pinned"] and node["renamed"]
    unpinned = restarted.ok("cluster.unpin", {"clusterId": cluster_id})
    node = next(n for n in unpinned["nodes"] if n["id"] == cluster_id)
    assert not node["pinned"] and node["renamed"]
    expected = clusters.unpin_cluster(expected, "group1", grouping).to_layout()
    assert store.load_layout() == expected
    restarted.ok("project.close")
    assert restarted.ok("project.open", {"path": str(file_project)})["layout"] == expected.to_dict()
    reopened_nodes = restarted.ok("view.get", {"view": "file"})["nodes"]
    assert [{k: v for k, v in n.items() if k != "sourceRootId"} for n in reopened_nodes] == [
        {k: v for k, v in n.items() if k != "sourceRootId"} for n in unpinned["nodes"]]
    assert (store.model_path.read_bytes(), store.ui_path.read_bytes()) == (model_bytes, ui_bytes)


def test_p01_file_assignment_reuses_core_and_survives_restart(clients, file_project):
    from icoda_core import clusters

    store = persistence.ProjectStore(file_project)
    before = store.load_layout()
    source = "group0/file0.py"
    unchanged = store.model_path.read_bytes(), (file_project / source).read_bytes()
    client = clients()
    initialized = client.ok("initialize", {"protocolVersion": 1})
    assert {"cluster.assignFile", "view.state.get", "view.state.set"} <= set(initialized["capabilities"]["methods"])
    client.ok("project.open", {"path": str(file_project)})
    grouping = clusters.cluster_files(store.load_model(), before)
    params = {"file": source, "clusterId": "cluster:group1", "viewClusterId": "cluster:group0", "hierarchy": True}
    result = client.ok("cluster.assignFile", params)
    expected = clusters.pin_file(before, grouping, source, "group1").to_layout()
    assert store.load_layout() == expected
    assert result["clusterId"] == "cluster:group0" and source not in {n["id"] for n in result["nodes"]}
    client.close()
    restarted = clients()
    opened = open_project(restarted, file_project, analyse=False)
    assert opened["layout"] == expected.to_dict()
    reveal = restarted.ok("view.revealFile", {"sourceRootId": opened["sourceRootId"], "file": source, "hierarchy": True})
    assert reveal["clusterId"] == "cluster:group1"
    restarted.ok("cluster.assignFile", {**params, "clusterId": None})
    assert store.load_layout() == clusters.unpin_file(expected, source).to_layout()
    assert unchanged == (store.model_path.read_bytes(), (file_project / source).read_bytes())


def test_p01_saved_parent_drill_in_and_reveal_keep_bounded_children(clients, file_project):
    from icoda_core import clusters

    store = persistence.ProjectStore(file_project)
    model = store.load_model()
    store.save_layout(clusters.Layout({"all": "Saved parent"}, {file: "all" for file in model.files}))
    client = clients()
    opened = open_project(client, file_project, analyse=False)
    params = {"view": "file", "hierarchy": True}
    overview = client.ok("view.get", params)
    parent = next(node for node in overview["nodes"] if node["kind"] == "cluster")
    assert parent["id"] == "cluster:all" and parent["fileCount"] == 81 and parent["pinned"]
    assert set(parent["filterMembers"]) == set(model.files)
    inside = client.ok("view.get", {**params, "clusterId": parent["id"]})
    assert inside["overview"] and inside["clusterPath"] == [{"id": "cluster:all", "label": "Saved parent", "pinned": True}]
    found = set()
    for child in inside["nodes"]:
        if child["kind"] == "file":
            found.add(child["file"])
            revealed = client.ok("view.revealFile", {"sourceRootId": opened["sourceRootId"], "file": child["file"], "hierarchy": True})
            assert revealed["clusterPath"] == [parent["id"]]
            continue
        assert child["kind"] == "cluster" and child["fileCount"] <= clusters.MAX_CLUSTER_SIZE
        detail = client.ok("view.get", {**params, "clusterId": child["id"]})
        assert [item["id"] for item in detail["clusterPath"]] == [parent["id"], child["id"]]
        assert not detail["overview"] and len(detail["nodes"]) == child["fileCount"]
        files = {node["file"] for node in detail["nodes"]}
        assert set(child["filterMembers"]) == files
        assert not files & found
        found |= files
        revealed = client.ok("view.revealFile", {"sourceRootId": opened["sourceRootId"], "file": min(files), "hierarchy": True})
        assert revealed["clusterPath"] == [parent["id"], child["id"]]
    assert found == set(model.files)
    # Existing v1 callers retain their flat overview and one-level ancestry.
    flat = client.ok("view.get", {"view": "file"})
    assert parent["id"] not in {node["id"] for node in flat["nodes"]}
    renamed = client.ok("cluster.rename", {"clusterId": parent["id"], "name": "Renamed parent", "hierarchy": True})
    assert next(node for node in renamed["nodes"] if node["id"] == parent["id"])["name"] == "Renamed parent"


def test_p01_file_camera_state_persists_per_target_and_preserves_ui(clients, target_project):
    store = persistence.ProjectStore(target_project)
    ui = {**store.load_ui(), "unrelated": {"value": 7}}
    store.save_ui(ui)
    client = clients()
    open_project(client, target_project, analyse=False)
    client.ok("target.select", {"targetId": None})
    state = {"clusterId": None, "cameras": [{"clusterId": None, "viewport": {"x": -42, "y": 18, "scale": 1.7}}]}
    client.ok("view.state.set", {"view": "file", "state": state})
    target = next(item for item in client.ok("targets.list")["targets"] if item["id"] is not None)
    client.ok("target.select", {"targetId": target["id"]})
    assert client.ok("view.state.get", {"view": "file"})["state"] == {"clusterId": None, "cameras": []}
    other = {"clusterId": None, "cameras": [{"clusterId": None, "viewport": {"x": 12, "y": 24, "scale": 0.6}}]}
    client.ok("view.state.set", {"view": "file", "state": other})
    client.close()
    restarted = clients()
    open_project(restarted, target_project, analyse=False)
    assert restarted.ok("view.state.get", {"view": "file"})["state"] == other
    restarted.ok("target.select", {"targetId": None})
    assert restarted.ok("view.state.get", {"view": "file"})["state"] == state
    assert store.load_ui()["unrelated"] == ui["unrelated"]
    # A removed group is discarded on read without rewriting unrelated persisted choices.
    removed = {"clusterId": "cluster:removed", "cameras": [{"clusterId": "cluster:removed", "viewport": state["cameras"][0]["viewport"]}]}
    restarted.ok("view.state.set", {"view": "file", "state": removed})
    assert restarted.ok("view.state.get", {"view": "file"})["state"] == {"clusterId": None, "cameras": []}


def test_p01_assignment_and_camera_validation_never_write_on_invalid_requests(clients, file_project):
    client = clients()
    open_project(client, file_project, analyse=False)
    store = persistence.ProjectStore(file_project)
    before = store.layout_path.read_bytes(), store.ui_path.read_bytes()
    assignment = {"file": "group0/file0.py", "clusterId": "cluster:group1", "hierarchy": True}
    state = {"clusterId": None, "cameras": []}
    for method, params in [("cluster.assignFile", assignment), ("view.state.set", {"view": "file", "state": state})]:
        for context, code in [({"sessionId": "old"}, "invalid_session"), ({"modelRevision": 999}, "stale_revision"),
                              ({"targetId": "old"}, "stale_target")]:
            assert_error(client.request(method, params, **context), code)
    assert_error(client.request("cluster.assignFile", {**assignment, "file": "../outside.py"}), "source_missing")
    assert_error(client.request("cluster.assignFile", {**assignment, "clusterId": "external:overview"}), "unknown_cluster")
    assert_error(client.request("cluster.assignFile", {**assignment, "hierarchy": "true"}), "invalid_params")
    for camera in [{"x": 0, "y": 0, "scale": 0}, {"x": 1e8, "y": 0, "scale": 1},
                   {"x": False, "y": 0, "scale": 1}, {"x": 0, "y": 0, "scale": 1, "extra": 1}]:
        invalid = {**state, "cameras": [{"clusterId": None, "viewport": camera}]}
        assert_error(client.request("view.state.set", {"view": "file", "state": invalid}), "invalid_params")
    assert_error(client.request("view.state.set", {"view": "call", "state": state}), "invalid_params")
    assert before == (store.layout_path.read_bytes(), store.ui_path.read_bytes())


@pytest.mark.parametrize("method", ["cluster.pin", "cluster.unpin", "cluster.rename"])
def test_cluster_edits_reject_unknown_and_stale_requests(clients, file_project, method):
    client = clients()
    initialized = client.ok("initialize", {"protocolVersion": 1})
    assert method in initialized["capabilities"]["methods"]
    client.ok("project.open", {"path": str(file_project)})
    store = persistence.ProjectStore(file_project)
    before = store.layout_path.read_bytes()
    params = {"clusterId": "cluster:group0", **({"name": "New"} if method == "cluster.rename" else {})}
    for changes, code in [({"sessionId": "old"}, "invalid_session"),
                          ({"modelRevision": 999}, "stale_revision"), ({"targetId": "old"}, "stale_target")]:
        assert_error(client.request(method, params, **changes), code)
    for identifier in ["cluster:missing", "group0", "external:overview", "group0/file0.py"]:
        response = client.request(method, {**params, "clusterId": identifier})
        assert_error(response, "unknown_cluster")
        assert response["error"]["details"]["clusterId"] == identifier
    assert_error(client.request(method, {**params, "viewClusterId": "cluster:missing"}), "unknown_cluster")
    assert store.layout_path.read_bytes() == before


@pytest.mark.parametrize("name", ["", " \n\t ", None, 3, "bad\0name"])
def test_cluster_rename_rejects_invalid_name_without_writing(clients, file_project, name):
    client = clients()
    open_project(client, file_project, analyse=False)
    store = persistence.ProjectStore(file_project)
    before = store.layout_path.read_bytes()
    assert_error(client.request("cluster.rename", {"clusterId": "cluster:group0", "name": name}), "invalid_params")
    assert store.layout_path.read_bytes() == before


def test_cluster_unpin_oversized_parent_uses_shared_membership(clients, file_project):
    from icoda_core import clusters

    store = persistence.ProjectStore(file_project)
    model = store.load_model()
    before = clusters.Layout({"all": "Pinned parent"}, {file: "all" for file in model.files})
    store.save_layout(before)
    grouping = clusters.cluster_files(model, before)
    child = grouping.clusters[0]
    client = clients()
    open_project(client, file_project, analyse=False)
    result = client.ok("cluster.unpin", {"clusterId": "cluster:" + child.id, "viewClusterId": "cluster:" + child.id})
    expected = clusters.unpin_cluster(before, child.id, grouping).to_layout()
    assert store.load_layout() == expected
    assert all(file not in expected.pins for file in child.files)
    assert result == client.ok("view.get", {"view": "file", "clusterId": result["clusterId"]})


def test_service_file_view_matches_desktop_grouping_geometry_and_expansion(app_module, file_project, monkeypatch):
    from icoda_core import clusters

    backend = Service()
    backend.initialize({"protocolVersion": 1})
    backend.open_project({"path": str(file_project)})
    project = backend.project
    grouping = clusters.cluster_files(project.model, project.store.load_layout())
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=file_project / "config.json")
    view = app.view
    def graph_bounds(tag):
        boxes = list(view.node_boxes.values())
        if tag == "file-graph" and boxes:
            return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
        return None
    monkeypatch.setattr(view.canvas, "bbox", graph_bounds)
    view.show(views.layout_file_view(project.model, grouping))
    overview = backend.get_view(project, {"view": "file"})
    assert view.overview
    assert {n["id"]: (n["label"], n["x"], n["y"]) for n in overview["nodes"]} == {
        key: (node.label, node.x, node.y) for key, node in view._draw_layout.nodes.items()}
    for group in ["cluster:group0", "external:overview"]:
        view.open_group(group)
        result = backend.get_view(project, {"view": "file", "clusterId": group})
        assert {n["id"] for n in result["nodes"]} == set(view.layout.nodes)
        assert [(e["source"], e["target"], e["count"]) for e in result["edges"]] == [
            (e.source, e.target, e.weight) for e in view.layout.file_arrows]
        view.back_to_overview()


def test_file_view_partition_bounds_and_reveal_use_saved_oversized_parent(clients, file_project):
    from icoda_core import clusters

    store = persistence.ProjectStore(file_project)
    model = store.load_model()
    store.save_layout(clusters.Layout({"all": "Pinned parent"}, {file: "all" for file in model.files}))
    grouping = clusters.cluster_files(model, store.load_layout())
    assert all(len(c.files) <= 40 for c in grouping.clusters)
    client = clients()
    opened = open_project(client, file_project, analyse=False)
    overview = client.ok("view.get", {"view": "file"})
    for node in overview["nodes"]:
        if node["kind"] != "cluster":
            continue
        assert node["parentId"] == "all" and node["pinned"] and node["renamed"]
        detail = client.ok("view.get", {"view": "file", "clusterId": node["id"]})
        assert len(detail["nodes"]) == node["fileCount"] <= 40
        file = detail["nodes"][0]["file"]
        revealed = client.ok("view.revealFile", {"sourceRootId": opened["sourceRootId"], "file": file})
        assert revealed["clusterPath"] == [node["id"]]


def test_file_view_scope_and_stale_identities(clients, target_project):
    client = clients()
    opened = open_project(client, target_project, analyse=False)
    whole = client.ok("view.get", {"view": "file"})
    before = persistence.ProjectStore(target_project).model_path.read_bytes()
    for target in client.ok("targets.list")["targets"]:
        selected = client.ok("target.select", {"targetId": target["id"]})
        graph = client.ok("view.get", {"view": "file"})
        files = set()
        for node in graph["nodes"]:
            if node["kind"] == "file":
                files.add(node["file"])
            elif node["kind"] == "cluster":
                files.update(n["file"] for n in client.ok("view.get", {"view": "file", "clusterId": node["id"]})["nodes"])
        assert files == {f["path"] for f in selected["model"]["files"]}
        for method, params in [("view.get", {"view": "file"}),
                               ("view.revealFile", {"file": next(iter(files)), "sourceRootId": opened["sourceRootId"]})]:
            assert_error(client.request(method, params, sessionId="old"), "invalid_session")
            assert_error(client.request(method, params, modelRevision=999), "stale_revision")
            assert_error(client.request(method, params, targetId="old"), "stale_target")
    client.ok("target.select", {"targetId": None})
    assert client.ok("view.get", {"view": "file"})["nodes"] == whole["nodes"]
    assert persistence.ProjectStore(target_project).model_path.read_bytes() == before


def test_file_reveal_moved_sources_and_invalid_requests(clients, file_project):
    client = clients()
    opened = open_project(client, file_project, analyse=False)
    source = {"sourceRootId": opened["sourceRootId"], "file": "group0/file0.py"}
    original = client.ok("view.revealFile", source)
    moved = file_project / "moved" / "group0" / "file0.py"
    moved.parent.mkdir(parents=True)
    (file_project / source["file"]).rename(moved)
    assert client.ok("source.resolve", source)["file"] == "moved/group0/file0.py"
    assert client.ok("view.revealFile", {**source, "file": "moved/group0/file0.py"}) == original
    assert client.ok("view.revealFile", {"sourceRootId": source["sourceRootId"], "usr": "entity:" + source["file"]}) == original
    assert client.ok("view.revealFile", {**source, "file": "single.py"})["clusterPath"] == []
    for params, code in [({"clusterId": "unknown"}, "unknown_cluster"), ({"clusterId": []}, "invalid_params"),
                         ({"width": False}, "invalid_params"), ({"height": 100001}, "invalid_params"),
                         ({"expanded": ["unknown"]}, "invalid_params")]:
        assert_error(client.request("view.get", {"view": "file", **params}), code)
    assert_error(client.request("view.revealFile", {**source, "sourceRootId": "old"}), "invalid_source_root")
    assert_error(client.request("view.revealFile", {**source, "file": "../outside.py"}), "source_missing")
    assert_error(client.request("view.revealFile", {**source, "usr": "unknown"}), "invalid_params")


def test_file_view_empty_unavailable_and_stale_models(clients, project):
    client = clients()
    opened = open_project(client, project, analyse=False)
    assert_error(client.request("view.get", {"view": "file"}), "model_unavailable")
    assert_error(client.request("view.revealFile", {"sourceRootId": opened["sourceRootId"], "file": "program.py"}),
                 "model_unavailable")
    store = persistence.ProjectStore(project)
    store.save_model(DerivedModel(str(project), stale=True, stale_reason="Retained analysis"))
    client.ok("project.open", {"path": str(project)})
    graph = client.ok("view.get", {"view": "file"})
    assert graph["nodes"] == [] and graph["edges"] == []
    assert graph["stale"] and graph["staleReason"] == "Retained analysis"
    model = python_analysis.parse_project(project)
    store.save_model(model)
    client.ok("project.open", {"path": str(project)})
    graph = client.ok("view.get", {"view": "file"})
    assert [n["id"] for n in graph["nodes"]] == ["program.py"] and not graph["overview"]


CPP_CLASSES = '''struct Base { int value; };
struct Part {};
class Widget : public Base {
    Part first;
    Part second;
public:
    void use(Part part) {}
    Part make() { return {}; }
};
'''
PYTHON_CLASSES = '''raise RuntimeError("Class analysis must never execute the project")
class Base:
    value: int
class Part:
    pass
class Widget(Base):
    first: Part
    second: Part
    def use(self, part: Part) -> Part:
        return part
'''


@pytest.fixture(params=["cpp", "python"])
def class_project(tmp_path, request):
    from icoda_core import analysis

    root = tmp_path / "classes"
    root.mkdir()
    if request.param == "cpp":
        candidates = toolchain.candidates()
        if not candidates:
            pytest.skip("C++ Class View requires libclang")
        loaded = toolchain.load(candidates[0].path)
        source = root / "types.cpp"
        source.write_text(CPP_CLASSES)
        command = analysis.CompileCommand(str(source), str(root), ("-std=c++20",), "clang++", False)
        model = analysis.parse_project(root, [command], libclang_version=loaded.version)
    else:
        (root / "types.py").write_text(PYTHON_CLASSES)
        model = python_analysis.parse_project(root)
    assert model.entities and not model.stale
    store = persistence.ProjectStore(root)
    store.save_model(model)
    store.save_ui({"executable": []})
    return root


def assert_class_layout(result, layout):
    assert {n["id"]: (n["x"], n["y"], n["width"], n["height"]) for n in result["nodes"]} == {
        key: (n.x, n.y, n.width, n.height) for key, n in layout.nodes.items()}
    assert result["edges"] == [asdict(edge) for edge in layout.edges]
    assert (result["width"], result["height"]) == (layout.width, layout.height)


def assert_class_members(result, graph):
    assert {n["usr"] for n in result["nodes"]} == {n.usr for n in graph.nodes}
    for node in result["nodes"]:
        core = graph.node_map()[node["usr"]]
        assert (node["label"], node["file"], node["line"]) == (core.qualified_name, core.file, core.line)
        assert node["id"] == node["entityId"] == node["usr"]
        assert [(m["usr"], m["name"], m["kind"], m["declaration"], m["status"], m["file"], m["line"])
                for m in node["members"]] == [
            (m.usr, m.name, m.kind.value, m.declaration, m.status, m.file, m.line) for m in core.members]
        assert all(m["visibility"] is None and m["sourceRootId"] == result["sourceRootId"] for m in node["members"])


def test_class_view_real_cpp_python_agrees_with_core_and_desktop(clients, class_project):
    import tkinter as tk

    from icoda_core import class_view
    from icoda_gui.class_view import ClassViewCanvas

    client = clients()
    opened = open_project(client, class_project, analyse=False)
    model = DerivedModel.from_json(json.dumps(opened["model"]))
    before = model.to_json()
    graph = class_view.build_class_graph(model)
    result = client.ok("view.get", {"view": "class"})
    assert not result["overview"] and result["clusterPath"] == []
    expected_kinds = {"inheritance", "usage"}
    if "types.cpp" in model.files:
        expected_kinds.add("composition")
        assert any(e["kind"] == "composition" and e["count"] == 2 for e in result["edges"])
    assert {e["kind"] for e in result["edges"]} == expected_kinds
    assert_class_members(result, graph)
    canvas = ClassViewCanvas(tk.Tk(), lambda *_: None)
    canvas.show(model)
    assert_class_layout(result, canvas.layout)
    member = next(n["members"][0] for n in result["nodes"] if n["members"])
    resolved = client.ok("source.resolve", {"usr": member["usr"], "sourceRootId": result["sourceRootId"]})
    assert resolved["line"] == member["line"] and Path(resolved["path"]).is_file()
    assert model.to_json() == before


@pytest.fixture
def grouped_class_project(tmp_path):
    from icoda_core import clusters

    root = tmp_path / "grouped classes"
    root.mkdir()
    (root / "left.py").write_text("class Base: pass\n" + "\n".join(f"class Type{i}(Base): pass" for i in range(44)))
    (root / "right.py").write_text("from left import Base\n" + "\n".join(
        f"class Other{i}(Base):\n    value: Base\n    def use(self, value: Base): pass" for i in range(8)))
    (root / "single.py").write_text("class Single: pass\n")
    store = persistence.ProjectStore(root)
    store.save_model(python_analysis.parse_project(root))
    store.save_ui({"executable": []})
    store.save_layout(clusters.Layout({"left": "Left", "right": "Right"},
                                     {"left.py": "left", "right.py": "right", "single.py": "single"}))
    return root


def test_class_grouping_drill_in_matches_desktop_visible_nodes_edges_and_geometry(clients, grouped_class_project):
    import tkinter as tk

    from icoda_core import clusters
    from icoda_gui.class_view import ClassViewCanvas

    client = clients()
    opened = open_project(client, grouped_class_project, analyse=False)
    store = persistence.ProjectStore(grouped_class_project)
    before = tree_bytes(store.dir)
    model = DerivedModel.from_json(json.dumps(opened["model"]))
    canvas = ClassViewCanvas(tk.Tk(), lambda *_: None)
    canvas.group_clustering = clusters.cluster_files(model, store.load_layout())
    drawn = []
    canvas._draw_edge = lambda edge, nodes=None: drawn.append(asdict(edge))
    canvas.show(model)
    result = client.ok("view.get", {"view": "class"})
    assert result["overview"] and len(result["nodes"]) < 54 and drawn
    assert result["edges"] == [asdict(e) for e in views.class_overview_edges(canvas.graph, canvas.groups)]
    assert all(e in drawn for e in result["edges"])
    assert {n["id"]: (n["x"], n["y"]) for n in result["nodes"]} == {
        key: (panel.x, panel.y) for key, panel in canvas._overview_panels.items()}
    seen = check_class_groups(client, canvas, result)
    assert seen == {n.usr for n in canvas.graph.nodes}
    assert client.ok("view.get", {"view": "class"}) == result
    assert tree_bytes(store.dir) == before


def check_class_groups(client, canvas, overview):
    seen = set()
    for node in overview["nodes"]:
        if not node["expandable"]:
            seen.add(node["usr"])
            assert node["members"] == []
            continue
        assert node["count"] <= 40 and "usr" not in node and "members" not in node
        canvas.open_group(node["id"])
        result = client.ok("view.get", {"view": "class", "clusterId": node["id"]})
        assert result["clusterPath"] == [{"id": node["id"], "label": node["label"]}]
        assert len(result["nodes"]) == node["count"] and not result["overview"]
        assert_class_layout(result, canvas.layout)
        assert_class_members(result, canvas.layout.graph)
        members = {n["usr"] for n in result["nodes"]}
        assert set(node["filterMembers"]) == members
        assert not seen & members
        seen.update(members)
        canvas.back_to_overview()
    return seen


def test_class_view_target_scope_and_stale_identity(clients, target_project):
    store = persistence.ProjectStore(target_project)
    model = store.load_model()
    for index, file in enumerate(model.files):
        model.add_entity(Entity(f"class:{index}", Kind.CLASS, f"C{index}", f"C{index}", file, 1))
    store.save_model(model)
    before = store.model_path.read_bytes()
    client = clients()
    open_project(client, target_project, analyse=False)
    whole = client.ok("view.get", {"view": "class"})
    counts = []
    for target in client.ok("targets.list")["targets"]:
        selected = client.ok("target.select", {"targetId": target["id"]})
        graph = client.ok("view.get", {"view": "class"})
        assert {n["usr"] for n in graph["nodes"]} == {
            e["usr"] for e in selected["model"]["entities"] if e["kind"] == "class"}
        counts.append(len(graph["nodes"]))
        for field, value, code in [("sessionId", "old", "invalid_session"),
                                   ("modelRevision", 999, "stale_revision"), ("targetId", "old", "stale_target")]:
            assert_error(client.request("view.get", {"view": "class"}, **{field: value}), code)
    assert min(counts) < max(counts) == len(whole["nodes"])
    client.ok("target.select", {"targetId": None})
    assert client.ok("view.get", {"view": "class"})["nodes"] == whole["nodes"]
    assert store.model_path.read_bytes() == before


@pytest.mark.parametrize("params,code", [({"clusterId": "unknown"}, "unknown_cluster"),
    ({"clusterId": 1}, "invalid_params"), ({"clusterId": ""}, "invalid_params"),
    ({"root": "usr"}, "invalid_params"), ({"depth": 2}, "invalid_params"), ({"extra": True}, "invalid_params")])
def test_class_view_rejects_invalid_params(clients, class_project, params, code):
    client = clients()
    open_project(client, class_project, analyse=False)
    assert_error(client.request("view.get", {"view": "class", **params}), code)


def test_class_view_empty_unavailable_and_stale(clients, project):
    client = clients()
    open_project(client, project, analyse=False)
    assert_error(client.request("view.get", {"view": "class"}), "model_unavailable")
    persistence.ProjectStore(project).save_model(DerivedModel(str(project), stale=True, stale_reason="Retained analysis"))
    client.ok("project.open", {"path": str(project)})
    graph = client.ok("view.get", {"view": "class"})
    assert graph["nodes"] == graph["edges"] == []
    assert graph["stale"] and graph["staleReason"] == "Retained analysis"


@pytest.fixture
def mindmap_project(tmp_path):
    from icoda_core import analysis, clusters, mind_map, specification, steplog

    root = tmp_path / "mindmap"
    root.mkdir()
    source = root / "library.cpp"
    source.write_text("/// @satisfies R-1\nclass Widget {\npublic:\n    /// @satisfies R-1\n"
                      "    int run() { return 1; }\n};\n")
    candidates = toolchain.candidates()
    if not candidates:
        pytest.skip("C++ Mind Map requires libclang")
    loaded = toolchain.load(candidates[0].path)
    command = analysis.CompileCommand(str(source), str(root), ("-std=c++20",), "clang++", False)
    model = analysis.parse_project(root, [command], libclang_version=loaded.version)
    store = persistence.ProjectStore(root)
    store.save_model(model)
    store.save_state(persistence.ProjectState(implementation_batch_size=3,
        mind_map=mind_map.MindMapViewState(("cluster:other-target",))))
    store.save_layout(clusters.Layout({"src": "Source"}, {"library.cpp": "src"}))
    spec = specification.default_specification("Mind Map fixture")
    spec["use_cases"] = [{"id": "UC-1", "title": "Run", "description": "Run the widget"}]
    spec["requirements"] = [
        {"id": "R-1", "title": "Return a value", "description": "Return one", "priority": "must", "use_cases": ["UC-1"]},
        {"id": "R-2", "title": "Not implemented", "description": "Later", "priority": "could", "use_cases": []}]
    assert specification.validate(spec) == []
    specification.save(store.specification_path, spec)
    steplog.StepLog(store.steps_path).append(steplog.StepRecord(2, "architecture", "approved",
        title="Introduce Widget", entities_added=list(model.entities), files=["library.cpp"]))
    return root


def assert_mindmap_layout(result, layout):
    assert [(n["id"], n["x"], n["y"], n["width"], n["height"], n["depth"]) for n in result["nodes"]] == [
        (n.node.id, n.x, n.y, n.width, n.height, n.depth) for n in layout.nodes]
    assert result["edges"] == [asdict(edge) for edge in layout.edges]
    assert (result["width"], result["height"]) == (layout.width, layout.height)
    parents = {edge.target: edge.source for edge in layout.edges}
    for node, item in zip(result["nodes"], layout.nodes):
        assert (node["label"], node["kind"], node["status"]) == (item.node.name, item.node.kind.value, item.node.status)
        assert node["requirementIds"] == list(item.node.satisfied_requirement_ids)
        assert node["children"] == [child.id for child in item.node.children]
        assert node["parent"] == parents.get(node["id"])
        assert node["step"] == {"number": item.node.introduced_iteration, "title": "Introduce Widget"}


def test_mindmap_shared_core_desktop_and_persisted_expansion(clients, mindmap_project):
    import tkinter as tk

    from icoda_core import clusters, steplog
    from icoda_gui.mind_map_view import MindMapCanvas

    client = clients()
    open_project(client, mindmap_project, analyse=False)
    store = persistence.ProjectStore(mindmap_project)
    model = store.load_model()
    canvas = MindMapCanvas(tk.Tk(), lambda *_: None)
    canvas.show(model, steplog.StepLog(store.steps_path), store, clusters.cluster_files(model, store.load_layout()))
    result = client.ok("view.get", {"view": "mindmap"})
    assert_mindmap_layout(result, canvas.layout)
    assert result["totalNodes"] == len(canvas.tree.nodes()) == 4
    # Compare the desktop choices with service writes, including unrelated/hidden choices.
    canvas.store = None
    for node_id in ("cluster:src", "file:library.cpp", "entity:c:@S@Widget"):
        canvas.activate_node(node_id)
        desktop_state = {**store.load_state().to_dict(), "mind_map": canvas.state.to_dict()}
        result = client.ok("mindmap.setExpanded", {"nodeId": node_id, "expanded": True})
        assert store.load_state().to_dict() == desktop_state
        assert_mindmap_layout(result, canvas.layout)
    assert result["hasSteps"] and not result["empty"] and result["messages"] == []
    check_mindmap_metadata(client, result)
    check_mindmap_reload(clients, client, store, result)


def check_mindmap_metadata(client, result):
    assert result["requirements"] == [
        {"id": "R-1", "title": "Return a value", "uncovered": False, "useCaseIds": ["UC-1"]},
        {"id": "R-2", "title": "Not implemented", "uncovered": True, "useCaseIds": []}]
    for node in result["nodes"]:
        assert node["requirementIds"] == ["R-1"] and node["useCaseIds"] == ["UC-1"]
        assert node["requirements"] == [result["requirements"][0]]
        assert node["sourceRootId"] == result["sourceRootId"]
        assert node["expanded"] == node["expandable"]
        if node["usr"]:
            source = client.ok("source.resolve", {"usr": node["usr"], "sourceRootId": node["sourceRootId"]})
            assert source["line"] == node["line"] and source["file"] == "library.cpp"


def test_p03_mindmap_step_opens_shared_history_and_rejects_stale_identity(clients, mindmap_project):
    from icoda_core import steplog

    client = clients()
    open_project(client, mindmap_project, analyse=False)
    store = persistence.ProjectStore(mindmap_project)
    log = steplog.StepLog(store.steps_path)
    # The latest code record wins; rejected and approach records with the same number do not.
    record = log.append(steplog.StepRecord(2, "architecture", "manual", title="Widget history",
        rationale="Keep the public API", files=["library.cpp"], build_ok=True,
        build_output="Build passed", test_ok=True, test_output="Tests passed", binary="private-provider"))
    log.append(steplog.StepRecord(2, "architecture", "rejected", title="Rejected retry"))
    log.append(steplog.StepRecord(2, "architecture", "approved", round=steplog.APPROACH_ROUND, title="Approach"))
    before = tree_bytes(store.dir)
    params = {"nodeId": "cluster:src"}
    result = client.ok("mindmap.step", params)
    from icoda_core.service import review_record

    assert result["record"] == review_record(record)
    assert "binary" not in result["record"]
    assert result["nodeId"] == params["nodeId"]
    assert all(result[key] == value for key, value in client.context.items())
    for field, value, code in [("sessionId", "old", "invalid_session"),
                              ("modelRevision", 999, "stale_revision"), ("targetId", "old", "stale_target")]:
        assert_error(client.request("mindmap.step", params, **{field: value}), code)
    for invalid in [{}, {"nodeId": ""}, {"nodeId": 2}, {"nodeId": "missing"}, {**params, "step": 2}]:
        assert_error(client.request("mindmap.step", invalid), "invalid_params")
    assert tree_bytes(store.dir) == before
    log.append(steplog.StepRecord(3, "architecture", "undone", undoes=2))
    assert_error(client.request("mindmap.step", params), "step_unavailable")
    store.steps_path.unlink()
    assert_error(client.request("mindmap.step", params), "step_unavailable")


def check_mindmap_reload(clients, client, store, expanded):
    before = store.load_state().to_dict()
    client.ok("mindmap.setExpanded", {"nodeId": "cluster:src", "expanded": False})
    persisted = json.loads(store.state_path.read_text())
    assert persisted["mind_map"]["expanded"] == ["cluster:other-target", "entity:c:@S@Widget", "file:library.cpp"]
    assert {k: v for k, v in persisted.items() if k != "mind_map"} == {
        k: v for k, v in before.items() if k != "mind_map"}
    client.ok("project.close")
    reloaded = clients()
    open_project(reloaded, store.root, analyse=False)
    collapsed = reloaded.ok("view.get", {"view": "mindmap"})
    assert len(collapsed["nodes"]) == 1 and not collapsed["nodes"][0]["expanded"]
    restored = reloaded.ok("mindmap.setExpanded", {"nodeId": "cluster:src", "expanded": True})
    assert restored["sessionId"] != expanded["sessionId"]
    assert restored["nodes"] == [{**node, "sourceRootId": restored["sourceRootId"]} for node in expanded["nodes"]]


@pytest.mark.parametrize("field,value,code", [("sessionId", "old", "invalid_session"),
    ("modelRevision", 999, "stale_revision"), ("targetId", "other", "stale_target")])
def test_mindmap_rejects_stale_read_and_expansion_without_writes(clients, mindmap_project, field, value, code):
    client = clients()
    open_project(client, mindmap_project, analyse=False)
    store = persistence.ProjectStore(mindmap_project)
    before = tree_bytes(store.dir)
    for method, params in [("view.get", {"view": "mindmap"}),
                           ("mindmap.setExpanded", {"nodeId": "cluster:src", "expanded": True})]:
        assert_error(client.request(method, params, **{field: value}), code)
    assert tree_bytes(store.dir) == before


@pytest.mark.parametrize("params", [{"nodeId": "", "expanded": True}, {"nodeId": 5, "expanded": True},
    {"nodeId": "cluster:src", "expanded": 1}, {"nodeId": "cluster:src", "expanded": "false"},
    {"nodeId": "cluster:src"}, {"nodeId": "missing", "expanded": True},
    {"nodeId": "entity:c:@S@Widget@F@run#", "expanded": True},
    {"nodeId": "cluster:src", "expanded": True, "extra": 0}])
def test_mindmap_rejects_invalid_expansion_without_writes(clients, mindmap_project, params):
    client = clients()
    open_project(client, mindmap_project, analyse=False)
    store = persistence.ProjectStore(mindmap_project)
    before = tree_bytes(store.dir)
    assert_error(client.request("mindmap.setExpanded", params), "invalid_params")
    assert_error(client.request("view.get", {"view": "mindmap", "depth": 2}), "invalid_params")
    assert tree_bytes(store.dir) == before


def test_mindmap_empty_metadata_does_not_hide_a_model(clients, mindmap_project):
    store = persistence.ProjectStore(mindmap_project)
    store.specification_path.unlink()
    store.steps_path.unlink()
    client = clients()
    open_project(client, mindmap_project, analyse=False)
    graph = client.ok("view.get", {"view": "mindmap"})
    assert graph["nodes"] and not graph["empty"] and graph["requirements"] == [] and not graph["hasSteps"]
    assert all(node["step"] is None for node in graph["nodes"])
    assert len(graph["messages"]) == 2
    assert graph["nodes"][0]["requirements"][0]["uncovered"] is None


def test_mindmap_empty_model_and_unavailable_model(clients, project):
    client = clients()
    open_project(client, project, analyse=False)
    assert_error(client.request("view.get", {"view": "mindmap"}), "model_unavailable")
    store = persistence.ProjectStore(project)
    store.save_model(DerivedModel(str(project), stale=True, stale_reason="Retained analysis"))
    client.ok("project.open", {"path": str(project)})
    graph = client.ok("view.get", {"view": "mindmap"})
    assert graph["empty"] and graph["emptyReason"] == "No project nodes in the selected target."
    assert graph["nodes"] == graph["edges"] == graph["requirements"] == []
    assert not graph["hasSteps"] and len(graph["messages"]) == 2
    assert graph["stale"] and graph["staleReason"] == "Retained analysis"


def test_mindmap_target_scope_preserves_whole_model_and_expansion(clients, target_project):
    from icoda_core import clusters, mind_map

    client = clients()
    open_project(client, target_project, analyse=False)
    store = persistence.ProjectStore(target_project)
    before = store.model_path.read_bytes()
    counts = []
    for target in client.ok("targets.list")["targets"]:
        selected = client.ok("target.select", {"targetId": target["id"]})
        model = DerivedModel.from_json(json.dumps(selected["model"]))
        tree = mind_map.build_mind_map(model, (), clusters.cluster_files(model, store.load_layout()))
        graph = client.ok("view.get", {"view": "mindmap"})
        assert graph["totalNodes"] == len(tree.nodes())
        assert [n["id"] for n in graph["nodes"]] == [n.id for n in tree.clusters]
        counts.append(graph["totalNodes"])
    assert min(counts) < max(counts)
    assert store.model_path.read_bytes() == before


def assert_issue_agreement(result, model, records):
    from icoda_core import rules

    assert [(i["ruleId"], i["severity"], i["message"], i["usr"], i["file"], i["line"])
            for i in result["findings"]] == [
        (i.rule_id, i.severity, i.message, i.usr, i.file, i.line) for i in rules.check(model, records)]
    assert len({i["id"] for i in result["findings"]}) == len(result["findings"])
    assert all(i["sourceRootId"] == result["sourceRootId"] for i in result["findings"])


def assert_coverage_agreement(result, model, spec, index):
    from icoda_core import requirement_coverage

    entries = result["requirementTraceability"]["entries"]
    assert [(i["id"], i["kind"], i["title"], i["uncovered"],
             [(e["usr"], e["qualifiedName"]) for e in i["entities"]]) for i in entries] == [
        (i.identifier, i.kind, i.title, i.uncovered,
         [(e.usr, e.qualified_name) for e in i.implementing_entities])
        for i in requirement_coverage.project(spec, model)]
    structural = result["structuralTestReachability"]
    assert structural["uncovered"] == list(index.uncovered)
    assert structural["entries"] == [{"usr": i.usr, "qualifiedName": i.qualified_name, "signature": i.signature,
        "file": i.file, "line": i.line, "sourceRootId": result["sourceRootId"], "covered": i.covered,
        "tests": list(i.tests), "evidence": json.loads(json.dumps([asdict(e) for e in i.evidence]))}
        for i in index.entries]
    for item in entries:
        for entity in item["entities"]:
            expected = model.entities[entity["usr"]]
            assert (entity["file"], entity["line"], entity["sourceRootId"]) == (
                expected.file, expected.line, result["sourceRootId"])


def test_evidence_core_agreement_navigation_and_read_only(clients, mindmap_project):
    from icoda_core import coverage_index, specification, steplog

    store = persistence.ProjectStore(mindmap_project)
    log = steplog.StepLog(store.steps_path)
    log.append(steplog.StepRecord(3, "implementation", "approved", title="Test Widget", test_ok=True,
                                selected_tests=["Widget::run"]))
    client = clients()
    opened = open_project(client, mindmap_project, analyse=False)
    before = tree_bytes(store.dir)
    model = DerivedModel.from_json(json.dumps(opened["model"]))
    issues, coverage = client.ok("issues.list"), client.ok("coverage.get")
    assert_issue_agreement(issues, model, log.records())
    assert_coverage_agreement(coverage, model, specification.load(store.specification_path),
                              coverage_index.build_index(model, log))
    assert issues["emptyReason"] is None
    assert coverage["structuralTestReachability"]["emptyReason"] is None
    for item in [*issues["findings"], *coverage["structuralTestReachability"]["entries"]]:
        resolved = client.ok("source.resolve", {key: item[key] for key in ("sourceRootId", "file", "line")})
        assert resolved["file"] == item["file"] and resolved["line"] == item["line"]
    client.ok("project.open", {"path": str(mindmap_project)})
    assert [i["id"] for i in client.ok("issues.list")["findings"]] == [i["id"] for i in issues["findings"]]
    assert tree_bytes(store.dir) == before


@pytest.mark.parametrize("field,value,code", [("sessionId", "old", "invalid_session"),
    ("modelRevision", 999, "stale_revision"), ("targetId", "other", "stale_target")])
def test_evidence_rejects_stale_identity_and_invalid_parameters(clients, project, field, value, code):
    client = clients()
    open_project(client, project)
    before = tree_bytes(persistence.ProjectStore(project).dir)
    for method in ("issues.list", "coverage.get"):
        assert_error(client.request(method, **{field: value}), code)
        assert_error(client.request(method, {"extra": True}), "invalid_params")
    assert tree_bytes(persistence.ProjectStore(project).dir) == before


def test_evidence_explicit_empty_states_and_capabilities(clients, project):
    client = clients()
    methods = client.ok("initialize", {"protocolVersion": 1})["capabilities"]["methods"]
    assert {"issues.list", "coverage.get"} <= set(methods)
    client.ok("project.open", {"path": str(project)})
    assert client.ok("issues.list")["emptyReason"] == "no_model"
    result = client.ok("coverage.get")
    for section in ("requirementTraceability", "structuralTestReachability"):
        assert result[section]["emptyReason"] == "no_model" and result[section]["entries"] == []
        assert result[section]["message"]
    client.ok("project.analyse")
    result = client.ok("coverage.get")
    assert result["requirementTraceability"]["emptyReason"] == "no_specification"
    structural = result["structuralTestReachability"]
    assert structural["emptyReason"] == "no_recorded_tests" and structural["message"]
    assert structural["entries"] and all(not i["covered"] for i in structural["entries"])
    check_empty_evidence_model(client, project)


def check_empty_evidence_model(client, project):
    from icoda_core import specification

    store = persistence.ProjectStore(project)
    specification.save(store.specification_path, specification.default_specification("Empty"))
    store.save_model(DerivedModel(str(project), stale=True, stale_reason="Retained model"))
    client.ok("project.open", {"path": str(project)})
    issues, coverage = client.ok("issues.list"), client.ok("coverage.get")
    assert issues["findings"] == [] and issues["emptyReason"] == "no_findings" and issues["message"]
    requirements, structural = coverage["requirementTraceability"], coverage["structuralTestReachability"]
    assert requirements["emptyReason"] == "no_requirements" and requirements["message"]
    assert structural["emptyReason"] == "no_callables" and structural["message"]
    assert requirements["entries"] == structural["entries"] == structural["uncovered"] == []
    assert coverage["stale"] and coverage["staleReason"] == issues["staleReason"] == "Retained model"


def test_evidence_target_scope_retains_tests_outside_selected_target(clients, target_project):
    from icoda_core import coverage_index, specification, steplog

    store = persistence.ProjectStore(target_project)
    model = store.load_model()
    model.entities["api"].satisfies = ("R-1",)
    store.save_model(model)
    spec = specification.default_specification("Targets")
    spec["requirements"] = [{"id": "R-1", "title": "API"}]
    specification.save(store.specification_path, spec)
    log = steplog.StepLog(store.steps_path)
    log.append(steplog.StepRecord(1, "implementation", "approved", test_ok=True, selected_tests=["first"]))
    complete = coverage_index.build_index(model, log)
    client = clients()
    open_project(client, target_project, analyse=False)
    before, counts = store.model_path.read_bytes(), []
    for target in client.ok("targets.list")["targets"]:
        selected = client.ok("target.select", {"targetId": target["id"]})
        scoped = DerivedModel.from_json(json.dumps(selected["model"]))
        rows = tuple(e for e in complete.entries if e.usr in scoped.entities)
        expected = coverage_index.CoverageIndex(rows, tuple(e.usr for e in rows if not e.covered))
        result = client.ok("coverage.get")
        assert_coverage_agreement(result, scoped, spec, expected)
        assert_issue_agreement(client.ok("issues.list"), scoped, log.records())
        counts.append(len(rows))
        if target["kind"] == "library" and target["name"] == "shared":
            assert "first" not in scoped.entities and next(e for e in rows if e.usr == "api").covered
    assert min(counts) < max(counts) and store.model_path.read_bytes() == before


def test_evidence_preserves_undo_and_failed_test_semantics(clients, mindmap_project):
    from icoda_core import coverage_index, specification, steplog

    store = persistence.ProjectStore(mindmap_project)
    log = steplog.StepLog(store.steps_path)
    for record in (steplog.StepRecord(3, "implementation", "approved", test_ok=True, selected_tests=["Widget::run"]),
                   steplog.StepRecord(4, "implementation", "undone", undoes=3),
                   steplog.StepRecord(5, "implementation", "approved", test_ok=False, selected_tests=["Widget::run"])):
        log.append(record)
    client = clients()
    open_project(client, mindmap_project, analyse=False)
    result = client.ok("coverage.get")
    assert_coverage_agreement(result, store.load_model(), specification.load(store.specification_path),
                              coverage_index.build_index(store.load_model(), log))
    assert result["structuralTestReachability"]["emptyReason"] == "no_recorded_tests"


WORKFLOW_METHODS = ("spec.get", "spec.validate", "spec.save", "phase.get", "phase.transition", "providers.list")


def test_specification_core_agreement_and_validated_save(clients, project):
    from icoda_core import analysis, specification

    client = clients()
    initialized = client.ok("initialize", {"protocolVersion": 1})
    assert set(WORKFLOW_METHODS) <= set(initialized["capabilities"]["methods"])
    assert initialized["capabilities"]["specificationPostSave"] is True
    client.ok("project.open", {"path": str(project)})
    result = client.ok("spec.get")
    document = specification.default_specification(project.name, analysis.detect_language(project))
    assert result["document"] == document
    assert result["schemaVersion"] == specification.SCHEMA_VERSION
    assert result["codeProfile"] == document["code_profile"]
    assert result["exists"] is False and not (project / ".icoda").exists()
    validation = client.ok("spec.validate", {"document": document})
    assert validation["valid"] and validation["findings"] == specification.validate(document) == []
    saved = client.ok("spec.save", {"document": document, "trusted": True})
    store = persistence.ProjectStore(project)
    assert specification.load(store.specification_path) == document
    assert saved["document"] == document and saved["modelRevision"] == result["modelRevision"] + 1
    assert saved["state"] == store.load_state().to_dict()
    assert client.ok("spec.get")["exists"] is True


@pytest.mark.parametrize("existing_file", [False, True])
def test_p08_save_builds_shared_skeleton_without_overwriting(clients, tmp_path, existing_file):
    from icoda_core import generator, session, specification, steplog

    root = tmp_path / "bare"
    root.mkdir()
    if existing_file:
        (root / "README.md").write_text("Keep my notes", encoding="utf-8")
    client = clients()
    opened = open_project(client, root, analyse=False)
    document = specification.default_specification(root.name, "Python")
    saved = client.ok("spec.save", {"document": document, "trusted": True, "postSave": True, "unsavedDocuments": []})
    expected = generator.skeleton_files(root.name, document["code_profile"])
    assert set(saved["writtenFiles"]) == set(expected) - ({"README.md"} if existing_file else set())
    for file, content in expected.items():
        assert (root / file).read_text(encoding="utf-8") == ("Keep my notes" if existing_file and file == "README.md" else content)
    assert saved["saved"] and saved["postSaveError"] is None
    assert saved["modelRevision"] == opened["modelRevision"] + 1
    assert saved["model"]["entities"] and not saved["model"]["stale"]
    assert saved["state"]["phase"] == client.ok("phase.get")["phase"] == "architecture"
    # Compare phase history and written paths with the same shared operation used by the desktop.
    desktop = tmp_path / "desktop" / "bare"
    session.prepare_new_project(desktop)
    if existing_file:
        (desktop / "README.md").write_text("Keep my notes", encoding="utf-8")
    assert session.save_project_specification(desktop, document) == saved["writtenFiles"]
    records = steplog.StepLog(persistence.ProjectStore(root).steps_path).records()
    assert [(r.previous_phase, r.phase, r.decision) for r in records] == [("specification", "architecture", "phase_transition")]
    # A second ordinary save is an edit, with no second skeleton or phase transition.
    again = client.ok("spec.save", {"document": document, "trusted": True, "postSave": True, "unsavedDocuments": []})
    assert again["writtenFiles"] is None and again["postSaveError"] is None
    assert len(steplog.StepLog(persistence.ProjectStore(root).steps_path).records()) == 1


def test_p08_existing_project_save_reanalyses(clients, project):
    store = persistence.ProjectStore(project)
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION))
    client = clients()
    before = open_project(client, project)
    with (project / "program.py").open("a", encoding="utf-8") as source:
        source.write("\ndef after_save():\n    return 42\n")
    document = client.ok("spec.get")["document"]
    saved = client.ok("spec.save", {"document": document, "trusted": True, "postSave": True, "unsavedDocuments": []})
    assert saved["writtenFiles"] is None and saved["postSaveError"] is None
    assert saved["modelRevision"] == before["modelRevision"] + 1
    assert any(entity["name"] == "after_save" for entity in saved["model"]["entities"])
    assert saved["state"]["phase"] == "implementation"
    assert not (project / "src").exists()


@pytest.mark.parametrize("failure", ["build", "tool", "analysis", "cancelled"])
def test_p08_post_save_failure_keeps_spec_and_marks_stale(clients, tmp_path, failure):
    from icoda_core import specification

    bootstrap = "from icoda_core import process, service, steps\n"
    if failure == "analysis":
        bootstrap += "service.analyse_candidate = lambda project: (None, None, [{'message': 'Analysis fixture failed'}], True)\n"
    elif failure == "tool":
        bootstrap += "def build(root):\n    raise FileNotFoundError('Missing cmake fixture')\nsteps.build_project = build\n"
    elif failure == "cancelled":
        bootstrap += ("def build(root):\n    process.current_cancellation().set()\n"
                      "    return steps.BuildResult(False, 'Cancelled')\nsteps.build_project = build\n")
    else:
        bootstrap += "steps.build_project = lambda root: steps.BuildResult(False, 'Build fixture failed')\n"
    client = clients(bootstrap + "raise SystemExit(service.main())\n")
    root = tmp_path / "failed"
    root.mkdir()
    opened = open_project(client, root, analyse=False)
    document = specification.default_specification(root.name, "Python")
    response = client.request("spec.save", {"document": document, "trusted": True, "postSave": True, "unsavedDocuments": []})
    if failure == "cancelled":
        saved = assert_error(response, "cancelled")
    else:
        assert response["status"] == "ok"
        saved = response["result"]
    code = {"analysis": "analysis_failed", "cancelled": "cancelled"}.get(failure, "build_failed")
    assert saved["saved"] and saved["postSaveError"]["code"] == code
    assert saved["model"]["stale"] and "Specification saved" in saved["model"]["stale_reason"]
    assert saved["modelRevision"] == opened["modelRevision"] + 1
    assert specification.load(persistence.ProjectStore(root).specification_path) == document
    assert client.ok("spec.get")["document"] == document
    assert client.ok("phase.get")["phase"] == "architecture"


@pytest.mark.parametrize("guard", ["trust", "unsaved", "proposal", "revision", "validation"])
def test_p08_post_save_guards_preserve_files(clients, tmp_path, guard):
    from icoda_core import specification

    root = tmp_path / "guarded"
    root.mkdir()
    client = clients()
    open_project(client, root, analyse=False)
    document = specification.default_specification(root.name, "Python")
    params = {"document": document, "trusted": guard != "trust", "postSave": True,
              "unsavedDocuments": [(root / "unsaved.py").as_uri()] if guard == "unsaved" else []}
    if guard == "proposal":
        (root / ".icoda/worktree").mkdir(parents=True)
    if guard == "validation":
        document["title"] = ""
    code = {"trust": "workspace_untrusted", "unsaved": "unsaved_documents", "proposal": "proposal_pending",
            "revision": "stale_revision", "validation": "invalid_specification"}[guard]
    assert_error(client.request("spec.save", params, **({"modelRevision": 999} if guard == "revision" else {})), code)
    assert not persistence.ProjectStore(root).specification_path.exists()
    assert not (root / "src").exists()


def test_invalid_specification_findings_match_core_and_save_preserves_bytes(clients, project):
    from icoda_core import specification

    store = persistence.ProjectStore(project)
    document = specification.default_specification("Before")
    specification.save(store.specification_path, document)
    before = store.specification_path.read_bytes()
    client = clients()
    open_project(client, project, analyse=False)
    document["title"] = ""
    document["requirements"] = [{"id": "R-1", "title": "Test", "priority": "must", "use_cases": ["UC-9"]}]
    result = client.ok("spec.validate", {"document": document})
    assert not result["valid"]
    assert [item["message"] for item in result["findings"]] == specification.validate(document)
    assert {item["severity"] for item in result["findings"]} == {"error"}
    assert result == client.ok("spec.validate", {"document": document})
    details = assert_error(client.request("spec.save", {"document": document, "trusted": True}), "invalid_specification")
    assert details["findings"] == result["findings"]
    assert store.specification_path.read_bytes() == before
    assert not store.state_path.exists()


@pytest.mark.parametrize("document", [None, [], 42, {"use_cases": None}, {"requirements": [False]},
    {"use_cases": [{"id": []}]}, {"requirements": [{"id": "R-1", "use_cases": [None, {}]}]}])
def test_specification_malformed_json_shapes_are_validation_findings(clients, project, document):
    client = clients()
    open_project(client, project, analyse=False)
    validation = client.ok("spec.validate", {"document": document})
    assert not validation["valid"] and validation["findings"]
    assert_error(client.request("spec.save", {"document": document, "trusted": True}), "invalid_specification")
    assert not (project / ".icoda").exists()


def test_phase_core_gates_and_queue_agree(clients, project):
    from icoda_core import implementation_queue, phases, specification, steplog

    client = clients()
    open_project(client, project)
    store = persistence.ProjectStore(project)
    phase = client.ok("phase.get")
    assert phase["state"] == store.load_state().to_dict()
    assert phase["allowedTransitions"] == []
    assert phase["transitions"] == [{"phase": p.value, "reason": reason} for p, reason in phases.transition_options(store).items()]
    assert_error(client.request("phase.transition", {"phase": "architecture", "trusted": True}), "disallowed_transition")
    document = specification.default_specification("Ready", "Python")
    client.ok("spec.save", {"document": document, "trusted": True})
    assert client.ok("phase.get")["allowedTransitions"] == [p.value for p, reason in phases.transition_options(store).items() if not reason]
    architecture = client.ok("phase.transition", {"phase": "architecture", "trusted": True})
    assert architecture["phase"] == "architecture"
    implementation = client.ok("phase.transition", {"phase": "implementation", "trusted": True})
    assert implementation["state"] == implementation_queue.ensure_state(store, store.load_model()).to_dict()
    assert implementation["record"]["title"] == "architecture approved"
    before = store.state_path.read_bytes(), store.steps_path.read_bytes()
    assert_error(client.request("phase.transition", {"phase": "specification", "trusted": True}), "disallowed_transition")
    assert (store.state_path.read_bytes(), store.steps_path.read_bytes()) == before
    assert [record.decision for record in steplog.StepLog(store.steps_path).records()] == ["phase_transition"] * 2


@pytest.mark.parametrize("method,params", [("spec.save", {"document": {}}), ("phase.transition", {"phase": "architecture"})])
@pytest.mark.parametrize("trusted", [None, False, 1, "true"])
def test_workflow_mutations_require_explicit_trust(clients, project, method, params, trusted):
    client = clients()
    open_project(client, project, analyse=False)
    assert_error(client.request(method, {**params, "trusted": trusted}), "workspace_untrusted")
    assert not (project / ".icoda").exists()


@pytest.mark.parametrize("method", WORKFLOW_METHODS)
def test_workflow_methods_reject_stale_context(clients, project, method):
    client = clients()
    open_project(client, project, analyse=False)
    assert_error(client.request(method, modelRevision=999), "stale_revision")
    assert_error(client.request(method, sessionId="obsolete"), "invalid_session")
    assert_error(client.request(method, targetId="obsolete"), "stale_target")
    assert not (project / ".icoda").exists()


def test_provider_inventory_is_read_only_and_never_invokes_a_cli(monkeypatch, project):
    from icoda_core import agent

    service = Service()
    service.initialize({"protocolVersion": 1})
    context = service.open_project({"path": str(project)})
    def request():
        return service.dispatch({**context, "method": "providers.list", "params": {}})
    monkeypatch.setattr(agent, "run_bounded", lambda *a, **k: pytest.fail("Must not execute a CLI"))
    monkeypatch.setattr(agent, "run_provider", lambda *a, **k: pytest.fail("Must not invoke a model"))
    monkeypatch.setattr(agent, "load_providers", list)
    assert request()["providers"] == []
    assert request()["emptyReason"] == "no_available_providers"
    provider = agent.Provider("stub", "Fixture", "stub", (), "stdin", (agent.Model("small", "Small"),), True, True, "")
    monkeypatch.setattr(agent, "load_providers", lambda: [provider])
    monkeypatch.setattr(persistence.UserConfig, "load", lambda path: persistence.UserConfig(provider="stub"))
    monkeypatch.setattr(agent, "binary_available", lambda *args: True)
    monkeypatch.setattr(agent, "authentication_configured", lambda *args: True)
    item = request()["providers"][0]
    assert item == {"id": "stub", "label": "Fixture", "installed": True, "enabled": True, "verified": True,
        "available": True, "authenticationConfigured": True, "binary": "stub", "binaryPath": None,
        "loginHint": "", "selectedModel": "small", "models": [{"id": "small", "label": "Small", "available": True}]}
    assert request()["selection"] == {"provider": "stub", "model": provider.default_model}
    monkeypatch.setattr(agent, "binary_available", lambda *args: False)
    assert not request()["providers"][0]["available"]
    assert service.dispatch({**context, "method": "spec.get", "params": {}})["document"]
    assert service.dispatch({**context, "method": "phase.get", "params": {}})["phase"] == "specification"
    assert service.dispatch({**context, "method": "source.resolve", "params": {
        "sourceRootId": context["sourceRootId"], "file": "program.py"}})["path"] == str(project / "program.py")
    service.project.model = python_analysis.parse_project(project)
    service.project.model_available = True
    assert service.dispatch({**context, "method": "view.get", "params": {"view": "call"}})["nodes"]
    assert not (project / ".icoda").exists()


def test_provider_authentication_markers_never_read_credentials(monkeypatch, tmp_path):
    from icoda_core import agent

    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    providers = agent.load_providers()
    for identifier, filename in (("codex", "auth.json"), ("claude", ".credentials.json")):
        provider = agent.find_provider(providers, identifier)
        assert agent.authentication_configured(provider) is False
        (tmp_path / filename).touch()
        with monkeypatch.context() as patch:
            patch.setattr(Path, "read_text", lambda *a, **k: pytest.fail("Must not read credentials"))
            assert agent.authentication_configured(provider) is True


def test_saved_invalid_specification_blocks_phase_without_changing_state(clients, project):
    from icoda_core import specification

    store = persistence.ProjectStore(project)
    document = specification.default_specification("")
    specification.save(store.specification_path, document)
    before = store.specification_path.read_bytes()
    client = clients()
    open_project(client, project, analyse=False)
    assert client.ok("spec.get")["valid"] is False
    assert client.ok("phase.get")["allowedTransitions"] == []
    assert_error(client.request("phase.transition", {"phase": "architecture", "trusted": True}), "disallowed_transition")
    assert store.specification_path.read_bytes() == before
    assert not store.state_path.exists() and not store.steps_path.exists()


def test_workflow_parameter_validation_and_untrusted_omission(clients, project):
    client = clients()
    open_project(client, project, analyse=False)
    assert_error(client.request("spec.save", {"document": {}}), "workspace_untrusted")
    assert_error(client.request("phase.transition", {"phase": "architecture"}), "workspace_untrusted")
    for method, params in (("spec.get", {"path": "outside"}), ("spec.validate", {}),
                           ("phase.transition", {"phase": "arbitrary", "trusted": True}),
                           ("phase.get", {"phase": "implementation"}), ("providers.list", {"invoke": True})):
        assert_error(client.request(method, params), "invalid_params")
    assert not (project / ".icoda").exists()


FAKE_WORKFLOW = ROOT / "tests" / "fixtures" / "fake_workflow.py"
FAKE_BOOTSTRAP = (f"import runpy; runpy.run_path({str(FAKE_WORKFLOW)!r})['install'](); "
                  "from icoda_core.service import main; main()")
AI_PARAMS = {"kind": "architecture", "trusted": True, "unsavedDocuments": [], "provider": "fixture", "model": "ok"}


@pytest.fixture
def workflow_project(tmp_path):
    import runpy

    root = tmp_path / "workflow"
    runpy.run_path(str(FAKE_WORKFLOW))["prepare"](root)
    return root


def wait_workflow(client, identifier, terminal=True):
    import time

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = client.ok("workflow.status", {"trusted": True, "workflowId": identifier})
        state = result["workflow"]["state"]
        if not terminal or state != "running":
            return result["workflow"]
        time.sleep(0.02)
    pytest.fail("Controlled workflow did not complete")


def start_workflow(client, **params):
    return client.ok("workflow.start", {**AI_PARAMS, **params})["workflow"]["id"]


def test_workflow_architecture_fake_provider_end_to_end(clients, workflow_project):
    from icoda_core import git

    client = clients(FAKE_BOOTSTRAP)
    opened = open_project(client, workflow_project, analyse=False)
    before = git.head_commit(workflow_project)
    identifier = start_workflow(client, focus=["src/main.py"], request="Add a helper stub.")
    job = wait_workflow(client, identifier)
    assert job["state"] == "completed", job
    result = job["result"]
    assert result["build"]["ok"] and result["tests"]["ok"]
    assert result["focus"] == ["src/main.py"]
    assert result["candidateLocation"] == str(workflow_project / ".icoda" / "worktree")
    assert (Path(result["candidateLocation"]) / "src/helper.py").is_file()
    assert not (workflow_project / "src/helper.py").exists()
    assert git.head_commit(workflow_project) == before
    assert client.context["modelRevision"] == opened["modelRevision"]
    assert any(note["method"] == "workflow.progress" for note in client.notifications)
    assert client.ok("source.resolve", {"file": "src/main.py", "sourceRootId": client.context["sessionId"] + ":workspace"})["line"] == 1
    assert_error(client.request("phase.transition", {"phase": "implementation", "trusted": True}), "proposal_pending")
    assert_error(client.request("workflow.start", AI_PARAMS), "proposal_pending")


def test_workflow_queue_uses_core_approach_gate(clients, workflow_project):
    from dataclasses import replace

    from icoda_core import implementation_queue

    store = persistence.ProjectStore(workflow_project)
    store.save_state(replace(store.load_state(), phase=persistence.ProjectPhase.IMPLEMENTATION))
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    job = wait_workflow(client, start_workflow(client, kind="implementation_queue"))
    assert job["state"] == "completed", job
    assert job["result"]["round"] == "approach"
    assert job["result"]["candidateLocation"] is None
    assert job["result"]["batch"] == [implementation_queue.target_usr(store.load_state())]
    assert store.load_state().approved_approach == ""
    assert store.load_state().implementation_cursor == 0
    assert not (store.dir / "worktree").exists()
    assert_error(client.request("purpose.propose", {"trusted": True, "idle": True, "unsavedDocuments": []}), "purpose_not_ready")


def wait_provider(root):
    import time

    marker = root / ".icoda/cache/provider-started"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if marker.is_file():
            return int(marker.read_text())
        time.sleep(0.02)
    pytest.fail("Fake provider did not start")


def test_workflow_cancellation_keeps_request_loop_and_navigation_alive(clients, workflow_project):
    import time

    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    identifier = start_workflow(client, model="slow")
    pid = wait_provider(workflow_project)
    started = time.monotonic()
    assert client.ok("source.resolve", {"file": "src/main.py", "sourceRootId": client.context["sessionId"] + ":workspace"})["path"].endswith("main.py")
    assert wait_workflow(client, identifier, terminal=False)["state"] == "running"
    client.ok("target.select", {"targetId": client.context["targetId"]})
    assert_error(client.request("target.select", {"targetId": "invalid"}), "unknown_target")
    assert wait_workflow(client, identifier, terminal=False)["state"] == "running"
    assert_error(client.request("project.analyse"), "workflow_busy")
    client.ok("workflow.cancel", {"trusted": True, "workflowId": identifier})
    job = wait_workflow(client, identifier)
    assert job["state"] == "cancelled" and job["error"]["code"] == "provider_cancelled"
    assert time.monotonic() - started < 5
    if sys.platform != "win32":
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    client.ok("source.resolve", {"file": "src/main.py", "sourceRootId": client.context["sessionId"] + ":workspace"})


def test_workflow_provider_failure_is_separate_from_navigation(clients, workflow_project):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    job = wait_workflow(client, start_workflow(client, model="fail"))
    assert job["state"] == "failed" and job["error"]["code"] == "provider_failed"
    assert "Controlled provider failure" in job["error"]["details"]["diagnosis"]["detail"]
    assert_error(client.request("source.resolve", {"file": "missing.py", "sourceRootId": client.context["sessionId"] + ":workspace"}), "source_missing")
    client.ok("source.resolve", {"file": "src/main.py", "sourceRootId": client.context["sessionId"] + ":workspace"})
    assert wait_workflow(client, job["id"])["error"] == job["error"]


@pytest.mark.parametrize("method,params", [("workflow.start", AI_PARAMS),
    ("workflow.status", {}), ("workflow.cancel", {"workflowId": "old"}),
    ("purpose.propose", {"idle": True, "unsavedDocuments": []}),
    ("purpose.apply", {"workflowId": "old", "idle": True, "unsavedDocuments": []}),
    ("purpose.reject", {"workflowId": "old", "idle": True, "unsavedDocuments": []})])
def test_ai_workflow_trust_and_identity_gates(clients, project, method, params):
    client = clients(FAKE_BOOTSTRAP)
    initialized = client.ok("initialize", {"protocolVersion": 1})
    assert method in initialized["capabilities"]["methods"]
    client.ok("project.open", {"path": str(project)})
    for trusted in (None, False, 1, "true"):
        assert_error(client.request(method, {**params, "trusted": trusted}), "workspace_untrusted")
    for context, code in (({"modelRevision": 99}, "stale_revision"),
                          ({"sessionId": "old"}, "invalid_session"), ({"targetId": "old"}, "stale_target")):
        assert_error(client.request(method, {**params, "trusted": True}, **context), code)


@pytest.mark.parametrize("params", [{"idle": False}, {"unsavedDocuments": ["untitled:unsaved.py"]}])
def test_purpose_preserves_idle_and_unsaved_safeguards(clients, workflow_project, params):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    assert_error(client.request("purpose.propose", {"trusted": True, "idle": True, "unsavedDocuments": [], **params}),
                 "purpose_not_ready")
    assert not list((workflow_project / ".icoda/cache").glob("purpose-*"))


def test_purpose_comments_are_checked_candidates_only(clients, workflow_project):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    source = workflow_project / "tests/test_main.py"
    before = source.read_bytes()
    result = client.ok("purpose.propose", {"trusted": True, "idle": True, "unsavedDocuments": [],
                                           "provider": "fixture", "model": "purpose"})
    job = wait_workflow(client, result["workflow"]["id"])
    assert job["state"] == "completed", job
    assert job["result"]["round"] == "purpose"
    assert source.read_bytes() == before
    assert "Check the fixture arithmetic" in (Path(job["result"]["candidateLocation"]) / "tests/test_main.py").read_text()
    assert_error(client.request("purpose.propose", {"trusted": True, "idle": True, "unsavedDocuments": []}), "purpose_not_ready")


@pytest.mark.parametrize("blocked", ["idle", "unsaved", "provider", "proposal", "retained", "analysis", "complete"])
def test_p10_purpose_status_reuses_core_readiness_without_starting_provider(clients, workflow_project, blocked):
    from dataclasses import replace

    store = persistence.ProjectStore(workflow_project)
    if blocked == "analysis":
        model = store.load_model()
        model.stale = True
        store.save_model(model)
    elif blocked == "complete":
        model = store.load_model()
        model.entities = {usr: replace(entity, brief="Documented") for usr, entity in model.entities.items()}
        store.save_model(model)
    elif blocked == "provider":
        store.save_ui({"provider": {"provider": "missing", "model": "missing"}})
    elif blocked == "retained":
        (store.dir / "worktree").mkdir()
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    if blocked == "proposal":
        identifier = start_workflow(client)
        assert wait_workflow(client, identifier)["state"] == "completed"
    params = {"trusted": True, "idle": blocked != "idle", "unsavedDocuments": ["src/main.py"] if blocked == "unsaved" else []}
    before = client.ok("workflow.status", {"trusted": True})["workflow"]
    result = client.ok("purpose.status", params)
    assert result["ready"] is False and result["reason"]
    assert client.ok("workflow.status", {"trusted": True})["workflow"] == before
    assert not list(store.cache_dir.glob("purpose-*"))


def test_p10_purpose_status_ready_active_cancelled_and_pending_candidate(clients, workflow_project):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    params = {"trusted": True, "idle": True, "unsavedDocuments": []}
    assert client.ok("purpose.status", params)["ready"] is True
    assert client.ok("workflow.status", {"trusted": True})["workflow"] is None
    identifier = client.ok("conversation.send", {"trusted": True, "unsavedDocuments": [], "model": "slow", "message": "Wait"})["workflow"]["id"]
    assert client.ok("purpose.status", params)["ready"] is False
    client.ok("workflow.cancel", {"trusted": True, "workflowId": identifier})
    assert wait_workflow(client, identifier)["state"] == "cancelled"
    job = client.ok("purpose.propose", {**params, "model": "purpose"})["workflow"]["id"]
    assert wait_workflow(client, job)["state"] == "completed"
    assert client.ok("purpose.status", params)["ready"] is False
    client.ok("purpose.reject", {**params, "workflowId": job})
    assert client.ok("purpose.status", params)["ready"] is True
    assert_error(client.request("purpose.status", {**params, "trusted": False}), "workspace_untrusted")
    assert_error(client.request("purpose.status", {**params, "idle": "yes"}), "invalid_params")


def test_p10_cancelled_purpose_completion_discards_owned_candidate(tmp_path):
    from icoda_core import documentation
    from icoda_core.service import WorkflowJob

    candidate = tmp_path / "purpose-candidate"
    candidate.mkdir()
    completion = documentation.Completion(None, [], [], candidate=candidate)
    job = WorkflowJob({"sessionId": "test", "modelRevision": 1, "targetId": None}, "purpose", lambda _note: None)
    job.cancel.set()
    job.run(lambda: completion, None)
    assert job.state == "cancelled"
    assert not candidate.exists()


def purpose_candidate(client, root):
    open_project(client, root, analyse=False)
    result = client.ok("purpose.propose", {"trusted": True, "idle": True, "unsavedDocuments": [],
                                           "provider": "fixture", "model": "purpose"})
    job = wait_workflow(client, result["workflow"]["id"])
    assert job["state"] == "completed", job
    return job, {"workflowId": job["id"], "trusted": True, "idle": True, "unsavedDocuments": []}


@pytest.mark.parametrize("method", ["purpose.apply", "purpose.reject"])
def test_purpose_decisions_refuse_untrusted_workspace(clients, workflow_project, method):
    client = clients(FAKE_BOOTSTRAP)
    job, params = purpose_candidate(client, workflow_project)
    source = workflow_project / "tests/test_main.py"
    candidate = Path(job["result"]["candidateLocation"]) / "tests/test_main.py"
    before, checked = source.read_bytes(), candidate.read_bytes()
    context = dict(client.context)
    response = client.request(method, {**params, "trusted": False})
    assert_error(response, "workspace_untrusted")
    assert "Trust this workspace" in response["error"]["message"]
    assert source.read_bytes() == before
    assert candidate.read_bytes() == checked
    assert client.context == context
    assert client.ok("workflow.status", {"trusted": True})["workflow"]["id"] == job["id"]


def test_purpose_apply_uses_checked_edits_and_clears_candidate(clients, workflow_project):
    from icoda_core import git

    client = clients(FAKE_BOOTSTRAP)
    job, params = purpose_candidate(client, workflow_project)
    before = git.head_commit(workflow_project)
    result = client.ok("purpose.apply", params)
    assert result["decision"] == "applied" and result["workflow"] is None and result["skipped"] == []
    assert '"""Check the fixture arithmetic."""' in (workflow_project / "tests/test_main.py").read_text()
    assert not Path(job["result"]["candidateLocation"]).exists()
    assert client.ok("workflow.status", {"trusted": True})["workflow"] is None
    assert result["model"]["stale"] and "Purpose comments applied" in result["model"]["stale_reason"]
    assert persistence.ProjectStore(workflow_project).load_model().stale
    assert git.head_commit(workflow_project) == before  # Documentation is not a step approval/commit.
    assert_error(client.request("purpose.apply", params), "purpose_missing")
    refreshed = client.ok("project.analyse")
    assert not refreshed["model"]["stale"]
    assert any(item["brief"] == "Check the fixture arithmetic." for item in refreshed["model"]["entities"])


def test_purpose_reject_preserves_source_and_allows_another_candidate(clients, workflow_project):
    client = clients(FAKE_BOOTSTRAP)
    before = (workflow_project / "tests/test_main.py").read_bytes()
    job, params = purpose_candidate(client, workflow_project)
    result = client.ok("purpose.reject", params)
    assert result["decision"] == "rejected" and result["workflow"] is None
    assert (workflow_project / "tests/test_main.py").read_bytes() == before
    assert not Path(job["result"]["candidateLocation"]).exists()
    assert client.ok("workflow.status", {"trusted": True})["workflow"] is None
    started = client.ok("purpose.propose", {"trusted": True, "idle": True, "unsavedDocuments": [],
                                           "provider": "fixture", "model": "purpose"})
    next_job = wait_workflow(client, started["workflow"]["id"])
    assert next_job["state"] == "completed"
    client.ok("purpose.reject", {**params, "workflowId": next_job["id"]})


@pytest.mark.parametrize("changed", ["source", "candidate"])
def test_purpose_apply_refuses_stale_candidate(clients, workflow_project, changed):
    client = clients(FAKE_BOOTSTRAP)
    job, params = purpose_candidate(client, workflow_project)
    candidate = Path(job["result"]["candidateLocation"])
    path = (workflow_project if changed == "source" else candidate) / "tests/test_main.py"
    path.write_text(path.read_text() + "\n# A newer user edit.\n")
    before = (workflow_project / "tests/test_main.py").read_bytes()
    response = client.request("purpose.apply", params)
    assert_error(response, "stale_evidence")
    assert "Reject it and propose again" in response["error"]["message"]
    assert (workflow_project / "tests/test_main.py").read_bytes() == before
    assert candidate.exists()
    client.ok("purpose.reject", params)  # Stale evidence must not prevent disposal.
    assert (workflow_project / "tests/test_main.py").read_bytes() == before


def test_purpose_apply_refuses_active_foreground_proposal(clients, workflow_project):
    from icoda_core import git

    client = clients(FAKE_BOOTSTRAP)
    _job, params = purpose_candidate(client, workflow_project)
    worktree = git.create_worktree(workflow_project, workflow_project / ".icoda/worktree", "foreground")
    before = (workflow_project / "tests/test_main.py").read_bytes()
    response = client.request("purpose.apply", params)
    assert_error(response, "purpose_not_ready")
    assert "existing proposal must be reviewed" in response["error"]["message"]
    assert (workflow_project / "tests/test_main.py").read_bytes() == before
    assert worktree.exists()


@pytest.mark.parametrize("blocked", ["idle", "workspace", "candidate"])
def test_purpose_apply_preserves_idle_and_unsaved_safeguards(clients, workflow_project, blocked):
    client = clients(FAKE_BOOTSTRAP)
    job, params = purpose_candidate(client, workflow_project)
    if blocked == "idle":
        params["idle"] = False
    else:
        root = workflow_project if blocked == "workspace" else Path(job["result"]["candidateLocation"])
        params["unsavedDocuments"] = [(root / "tests/test_main.py").as_uri()]
    before = (workflow_project / "tests/test_main.py").read_bytes()
    assert_error(client.request("purpose.apply", params), "purpose_not_ready")
    assert (workflow_project / "tests/test_main.py").read_bytes() == before
    assert client.ok("workflow.status", {"trusted": True})["workflow"]["id"] == job["id"]


def test_workflow_no_provider_does_not_prevent_browsing(clients, workflow_project):
    client = clients("from icoda_core import agent; agent.load_providers = lambda: []; "
                     "from icoda_core.service import main; main()")
    open_project(client, workflow_project, analyse=False)
    details = assert_error(client.request("workflow.start", AI_PARAMS), "provider_unavailable")
    assert details["capability"]["emptyReason"] == "no_available_providers"
    assert client.ok("source.resolve", {"file": "src/main.py", "sourceRootId": client.context["sessionId"] + ":workspace"})["path"].endswith("main.py")
    assert client.ok("view.get", {"view": "file"})["nodes"]
    assert client.ok("workflow.status", {"trusted": True})["workflow"] is None


def test_explicit_implementation_approach_uses_core_and_blocks_phase_change(clients, workflow_project):
    from dataclasses import replace

    store = persistence.ProjectStore(workflow_project)
    store.save_state(replace(store.load_state(), phase=persistence.ProjectPhase.IMPLEMENTATION))
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    job = wait_workflow(client, start_workflow(client, kind="implementation_approach", focus=["src/main.py"]))
    assert job["state"] == "completed", job
    assert job["result"]["round"] == "approach" and job["result"]["batch"]
    assert client.ok("phase.get")["allowedTransitions"] == []
    assert_error(client.request("phase.transition", {"phase": "architecture", "trusted": True}), "proposal_pending")


def test_workflow_project_switch_cancels_owned_provider_and_discards_old_status(clients, workflow_project, project):
    import time

    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    identifier = start_workflow(client, model="slow")
    pid = wait_provider(workflow_project)
    client.ok("project.open", {"path": str(project)})
    assert client.ok("workflow.status", {"trusted": True})["workflow"] is None
    assert_error(client.request("workflow.status", {"trusted": True, "workflowId": identifier}), "workflow_missing")
    if sys.platform != "win32":
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            pytest.fail("Old provider survived project switch")
    client.ok("providers.list")  # Drain final scoped notifications as well.


@pytest.mark.parametrize("params", [{"kind": "apply"}, {"focus": ["../outside.py"]},
    {"unsavedDocuments": "file.py"}, {"provider": 3}, {"maxEntities": False}, {"request": ""}])
def test_workflow_parameter_boundary_rejects_before_start(clients, workflow_project, params):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    assert_error(client.request("workflow.start", {**AI_PARAMS, **params}), "invalid_params")
    assert client.ok("workflow.status", {"trusted": True})["workflow"] is None
    assert not (workflow_project / ".icoda/worktree").exists()


def test_purpose_rejects_retained_candidate_after_reopen(clients, workflow_project):
    candidate = workflow_project / ".icoda/worktree"
    candidate.mkdir()
    preserved = candidate / "valuable.txt"
    preserved.write_text("Retained candidate", encoding="utf-8")
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    assert_error(client.request("purpose.propose", {"trusted": True, "idle": True, "unsavedDocuments": []}), "purpose_not_ready")
    assert_error(client.request("workflow.start", AI_PARAMS), "proposal_pending")
    assert preserved.read_text() == "Retained candidate"


def test_workflow_queue_with_saved_approach_stops_at_candidate_even_with_auto_approve(clients, workflow_project):
    from dataclasses import replace

    from icoda_core import git, implementation_queue

    store = persistence.ProjectStore(workflow_project)
    store.save_state(replace(store.load_state(), phase=persistence.ProjectPhase.IMPLEMENTATION))
    state = implementation_queue.ensure_state(store, store.load_model())
    store.save_state(replace(state, approved_approach="Return 1 from the entry function.", auto_approve=True))
    before = git.head_commit(workflow_project)
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    job = wait_workflow(client, start_workflow(client, kind="implementation_queue"))
    assert job["state"] == "completed", job
    assert job["result"]["round"] == "code"
    assert job["result"]["batch"] == [implementation_queue.target_usr(store.load_state())]
    assert store.load_state().implementation_cursor == 0
    assert store.load_state().approved_approach == "Return 1 from the entry function."
    assert git.head_commit(workflow_project) == before
    assert "pass" in (workflow_project / "src/main.py").read_text()
    assert "return 1" in (Path(job["result"]["candidateLocation"]) / "src/main.py").read_text()


@pytest.mark.parametrize("started", [False, True])
def test_workflow_eof_cancels_queued_or_running_children(clients, workflow_project, started):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    pid = None
    if started:
        start_workflow(client, model="slow")
        pid = wait_provider(workflow_project)
    else:
        frame = {"id": 99, "method": "workflow.start", "params": {**AI_PARAMS, "model": "slow"}, **client.context}
        client.process.stdin.write(json.dumps(frame).encode() + b"\n")
    client.process.stdin.close()
    assert client.process.wait(timeout=5) == 0
    terminal = []
    while line := client.lines.get(timeout=5):
        terminal.append(json.loads(line))
    client.lines.put(b"")  # The shared fixture's cleanup still checks orderly exit and stderr.
    assert any(note.get("error", {}).get("code") == "provider_cancelled" or
               note.get("params", {}).get("workflow", {}).get("state") == "cancelled" for note in terminal)
    if pid is not None and sys.platform != "win32":
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


REVIEW_PARAMS = {"trusted": True, "unsavedDocuments": []}


def reviewed_proposal(clients, root, mode="ok"):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, root, analyse=False)
    wait_workflow(client, start_workflow(client, model=mode))
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    return client, review, {**REVIEW_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"]}


@pytest.mark.parametrize("mode,usr,mark,file", [
    ("ok", "python:src.helper:helper", "added", "src/helper.py"),
    ("signature", "python:src.main:run", "changed", "src/main.py"),
])
def test_p02_candidate_call_graph_and_source_use_checked_core_delta(clients, workflow_project, mode, usr, mark, file):
    client, review, _params = reviewed_proposal(clients, workflow_project, mode)
    graph_source = review["candidateGraph"]
    assert graph_source and graph_source["sourceRootId"] != review["sourceRootId"]
    before = client.ok("view.get", {"view": "call"})
    graph = client.ok("view.get", {"view": "call", "sourceRootId": graph_source["sourceRootId"]})
    node = next(node for node in graph["nodes"] if node["usr"] == usr)
    assert node[mark] and not node["changed" if mark == "added" else "added"]
    assert node["sourceRootId"] == graph_source["sourceRootId"]
    assert graph["sourceRootId"] == graph_source["sourceRootId"]
    source = client.ok("source.resolve", {"sourceRootId": graph_source["sourceRootId"], "usr": usr})
    assert source["path"] == str(Path(graph_source["root"]) / file)
    assert source["file"] == file and source["line"] == 1
    assert client.ok("view.get", {"view": "call"}) == before
    assert_error(client.request("view.get", {"view": "call", "sourceRootId": graph_source["sourceRootId"],
                                           "traceId": "not-candidate-playback"}), "invalid_params")
    assert_error(client.request("source.resolve", {"sourceRootId": graph_source["sourceRootId"],
                                                 "file": "../main.py"}), "source_missing")
    assert_error(client.request("source.resolve", {"sourceRootId": graph_source["sourceRootId"],
                                                 "file": ".git"}), "source_missing")
    (Path(graph_source["root"]) / file).write_text("def edited(): pass\n")
    for method, params in (("view.get", {"view": "call"}), ("source.resolve", {"usr": usr})):
        assert_error(client.request(method, {**params, "sourceRootId": graph_source["sourceRootId"]}), "stale_evidence")
    assert client.ok("proposal.get", {"unsavedDocuments": []})["candidateGraph"] is None


def test_p02_candidate_source_expires_after_rejection(clients, workflow_project):
    client, review, params = reviewed_proposal(clients, workflow_project)
    source_root = review["candidateGraph"]["sourceRootId"]
    client.ok("proposal.reject", {**params, "reason": "Close candidate"})
    assert_error(client.request("source.resolve", {"sourceRootId": source_root, "file": "src/helper.py"}), "stale_evidence")
    assert client.ok("proposal.get", {"unsavedDocuments": []})["candidateGraph"] is None


def test_p05_automatic_analysis_refreshes_disk_changes_and_guards_unsaved(clients, project):
    client = clients()
    opened = open_project(client, project)
    caps = Service().initialize({"protocolVersion": 1})["capabilities"]
    assert caps["candidateCallView"] and caps["automaticAnalysis"]
    original = client.context.copy()
    new_file = project / "new.py"
    new_file.write_text("def added(): return 7\n")
    assert_error(client.request("project.analyse", {"automatic": True, "unsavedDocuments": [new_file.as_uri()]}), "unsaved_documents")
    assert client.context == original
    analysed = client.ok("project.analyse", {"automatic": True, "unsavedDocuments": []})
    assert analysed["modelRevision"] == opened["modelRevision"] + 1
    assert any(entity["name"] == "added" for entity in analysed["model"]["entities"])
    new_file.unlink()
    analysed = client.ok("project.analyse", {"automatic": True})
    assert not any(entity["name"] == "added" for entity in analysed["model"]["entities"])
    assert_error(client.request("project.analyse", {"automatic": "true"}), "invalid_params")


def test_p05_automatic_analysis_preserves_pending_review(clients, workflow_project):
    client, review, _params = reviewed_proposal(clients, workflow_project)
    assert_error(client.request("project.analyse", {"automatic": True}), "proposal_pending")
    assert client.ok("proposal.get", {"unsavedDocuments": []}) == review


def test_p05_core_snapshot_marks_mid_analysis_changes_stale(monkeypatch, project):
    from icoda_core import service as service_module

    service = Service()
    service.initialize({"protocolVersion": 1})
    context = service.open_project({"path": str(project)})
    model = python_analysis.parse_project(project)

    def analyse(_project):
        (project / "new.py").write_text("def late(): pass\n")
        return model, {}, [], False

    monkeypatch.setattr(service_module, "analyse_candidate", analyse)
    try:
        result = service.dispatch({**context, "method": "project.analyse", "params": {"automatic": True}})
        assert result["model"]["stale"]
        assert "Source changed during automatic analysis" in result["model"]["stale_reason"]
    finally:
        service.close_project()


def test_review_approve_commit_history_and_undo(clients, workflow_project):
    from icoda_core import git

    client, review, params = reviewed_proposal(clients, workflow_project)
    assert review["proposal"]["canApprove"]
    assert review["proposal"]["worktreeRoot"] == str(workflow_project / ".icoda/worktree")
    assert review["proposal"]["files"] == [{"status": "A", "path": "src/helper.py"}]
    before = git.head_commit(workflow_project)
    result = client.ok("proposal.approve", params)
    assert result["record"]["decision"] == "approved"
    assert result["record"]["commit"] == git.head_commit(workflow_project) != before
    assert result["modelRevision"] == review["modelRevision"] + 1
    assert (workflow_project / "src/helper.py").exists()
    assert not (workflow_project / ".icoda/worktree").exists()
    assert client.ok("history.list")["records"][-1]["title"] == "Add helper stub"
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    undone = client.ok("step.undo", {**REVIEW_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"]})
    assert undone["record"]["decision"] == "undone" and undone["record"]["commit"] != before
    assert not (workflow_project / "src/helper.py").exists()
    assert undone["model"]["stale"]


def test_review_failed_gate_cannot_approve(clients, workflow_project):
    from icoda_core import git

    client, review, params = reviewed_proposal(clients, workflow_project, "gate")
    assert review["proposal"]["tests"]["ok"] is False
    assert not review["proposal"]["canApprove"]
    before = git.head_commit(workflow_project)
    assert_error(client.request("proposal.approve", params), "proposal_gate_failed")
    assert git.head_commit(workflow_project) == before
    assert "assert False" not in (workflow_project / "tests/test_main.py").read_text()


def test_review_signature_confirmation_is_required(clients, workflow_project):
    from icoda_core import git

    client, review, params = reviewed_proposal(clients, workflow_project, "signature")
    assert review["proposal"]["signatureChanges"][0]["proposed_signature"] == "def run(value=1)"
    before = git.head_commit(workflow_project)
    assert_error(client.request("proposal.approve", params), "signature_unconfirmed")
    assert git.head_commit(workflow_project) == before
    result = client.ok("proposal.approve", {**params, "confirmSignatures": True})
    assert result["record"]["decision"] == "approved"
    assert result["record"]["commit"] == git.head_commit(workflow_project) != before
    assert "value=1" in (workflow_project / "src/main.py").read_text()


@pytest.mark.parametrize("method", ["proposal.approve", "proposal.adapt", "proposal.rebuild",
                                    "proposal.reject", "step.undo"])
def test_review_dirty_tree_is_distinct_for_every_decision(clients, workflow_project, method):
    from icoda_core import git

    client, _review, params = reviewed_proposal(clients, workflow_project)
    before = git.head_commit(workflow_project)
    source = workflow_project / "src/main.py"
    source.write_text(source.read_text() + "# saved manual edit\n")
    if method == "proposal.reject":
        params["reason"] = "Skip this proposal."
    assert_error(client.request(method, params), "dirty_tree")
    assert git.head_commit(workflow_project) == before
    assert "saved manual edit" in source.read_text()
    assert client.ok("proposal.get", {"unsavedDocuments": []})["proposal"] is not None


@pytest.mark.parametrize("method", ["adapt", "rebuild"])
@pytest.mark.parametrize("exception,code", [
    ("steps.DirtyTree('Controlled refusal')", "dirty_tree"),
    ("steps.SignatureConfirmationRequired('Controlled refusal')", "signature_unconfirmed"),
    ("steps.StepError('Controlled refusal')", "proposal_gate_failed"),
    ("steps.StepCancelled()", "provider_cancelled"),
    ("steps.ProviderError(recovery.diagnose('Controlled provider failure'))", "provider_failed"),
])
def test_review_worker_preserves_step_error_codes(clients, workflow_project, method, exception, code):
    from icoda_core import git

    injection = ("from icoda_core import recovery, steps\n"
                 f"def refuse(*args, **kwargs):\n    raise {exception}\n"
                 f"steps.StepRunner.{method} = refuse\n")
    client = clients(FAKE_BOOTSTRAP.replace("main()", "\n" + injection + "main()"))
    open_project(client, workflow_project, analyse=False)
    wait_workflow(client, start_workflow(client))
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    before = git.head_commit(workflow_project)
    started = client.ok(f"proposal.{method}", {**REVIEW_PARAMS,
                                             "evidenceFingerprint": review["evidenceFingerprint"]})
    job = wait_workflow(client, started["workflow"]["id"])
    assert job["state"] == ("cancelled" if code == "provider_cancelled" else "failed")
    assert job["error"]["code"] == code
    assert git.head_commit(workflow_project) == before
    assert client.ok("proposal.get", {"unsavedDocuments": []})["proposal"] is not None


@pytest.mark.parametrize("changed", ["candidate", "unchanged_input", "unsaved", "dirty", "head"])
def test_review_rejects_changed_evidence(clients, workflow_project, changed):
    from icoda_core import git

    client, _review, params = reviewed_proposal(clients, workflow_project)
    if changed in ("candidate", "unchanged_input"):
        name = "helper.py" if changed == "candidate" else "main.py"
        path = workflow_project / ".icoda/worktree/src" / name
        path.write_text(path.read_text() + "# edited after review\n")
    elif changed == "unsaved":
        params["unsavedDocuments"] = [(workflow_project / ".icoda/worktree/src/helper.py").as_uri()]
    elif changed == "dirty":
        (workflow_project / "src/main.py").write_text("# manual edit\n")
    else:
        git.run_git(["-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "--allow-empty", "-m", "external commit"], workflow_project)
    assert_error(client.request("proposal.approve", params), "dirty_tree" if changed == "dirty" else "stale_evidence")
    if changed in ("candidate", "unchanged_input", "head"):
        refreshed = client.ok("proposal.get", {"unsavedDocuments": []})
        assert not refreshed["proposal"]["canApprove"]
        assert_error(client.request("proposal.approve", {**params, "evidenceFingerprint": refreshed["evidenceFingerprint"]}), "stale_evidence")


def test_review_reject_records_reason_and_releases_next_workflow(clients, workflow_project):
    client, _review, params = reviewed_proposal(clients, workflow_project)
    result = client.ok("proposal.reject", {**params, "reason": "Use a clearer helper name."})
    assert result["record"]["decision"] == "rejected"
    assert client.ok("history.list")["records"][-1]["reason"] == "Use a clearer helper name."
    assert wait_workflow(client, start_workflow(client))["state"] == "completed"


def test_review_adapt_uses_core_summary_and_provider(clients, workflow_project):
    client, review, params = reviewed_proposal(clients, workflow_project)
    summary = json.loads(review["proposal"]["entitySummary"])
    summary[0]["name"] = "clearer_helper"
    started = client.ok("proposal.adapt", {**params, "entitySummary": json.dumps(summary)})
    assert wait_workflow(client, started["workflow"]["id"])["state"] == "completed"
    updated = client.ok("proposal.get", {"unsavedDocuments": []})
    assert updated["evidenceFingerprint"] != review["evidenceFingerprint"]
    assert updated["proposal"]["canApprove"]
    assert_error(client.request("proposal.approve", params), "stale_evidence")
    assert not (workflow_project / "src/helper.py").exists()


def test_review_edited_candidate_must_be_rebuilt(clients, workflow_project):
    client, _review, _params = reviewed_proposal(clients, workflow_project)
    candidate = workflow_project / ".icoda/worktree/src/helper.py"
    candidate.write_text(candidate.read_text() + "# reviewed manual candidate edit\n")
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    started = client.ok("proposal.rebuild", {**REVIEW_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"]})
    assert wait_workflow(client, started["workflow"]["id"])["state"] == "completed"
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    assert review["proposal"]["canApprove"]
    client.ok("proposal.approve", {**REVIEW_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"]})
    assert "manual candidate edit" in (workflow_project / "src/helper.py").read_text()


@pytest.mark.parametrize("external_commit", [False, True])
def test_review_undo_disallowed_follows_core_rules(clients, workflow_project, external_commit):
    from icoda_core import git

    client, _review, params = reviewed_proposal(clients, workflow_project)
    client.ok("proposal.approve" if external_commit else "proposal.reject", {**params, **({} if external_commit else {"reason": "Skip"})})
    if external_commit:
        git.run_git(["-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "--allow-empty", "-m", "external commit"], workflow_project)
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    assert_error(client.request("step.undo", {**REVIEW_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"]}), "undo_disallowed")


@pytest.mark.parametrize("method", ["proposal.approve", "proposal.reject", "proposal.adapt", "proposal.rebuild", "step.undo", "step.commitManual"])
def test_review_mutations_are_trusted_scoped_and_validated(clients, workflow_project, method):
    client = clients(FAKE_BOOTSTRAP)
    initialized = client.ok("initialize", {"protocolVersion": 1})
    assert method in initialized["capabilities"]["methods"]
    client.ok("project.open", {"path": str(workflow_project)})
    params = {**REVIEW_PARAMS, "evidenceFingerprint": "old"}
    if method == "proposal.reject":
        params["reason"] = "Skip"
    assert_error(client.request(method, {**params, "trusted": False}), "workspace_untrusted")
    assert_error(client.request(method, params, modelRevision=99), "stale_revision")
    assert_error(client.request(method, params, sessionId="other"), "invalid_session")
    assert_error(client.request(method, params, targetId="other"), "stale_target")
    assert_error(client.request(method, {**params, "unsavedDocuments": "invalid"}), "invalid_params")
    assert_error(client.request(method, params), "stale_evidence")


def test_review_manual_edit_records_commit_and_blocks_unsaved(clients, workflow_project):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    path = workflow_project / "src/main.py"
    path.write_text(path.read_text() + "# developer edit\n")
    unsaved = [path.as_uri()]
    review = client.ok("proposal.get", {"unsavedDocuments": unsaved})
    assert_error(client.request("step.commitManual", {**REVIEW_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"],
        "unsavedDocuments": unsaved}), "unsaved_documents")
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    result = client.ok("step.commitManual", {**REVIEW_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"]})
    assert result["record"]["decision"] == "manual" and result["record"]["commit"]
    assert client.ok("history.list")["records"][-1]["decision"] == "manual"


def test_review_approach_approval_then_queue_code_approval(clients, workflow_project):
    from dataclasses import replace

    store = persistence.ProjectStore(workflow_project)
    store.save_state(replace(store.load_state(), phase=persistence.ProjectPhase.IMPLEMENTATION))
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    wait_workflow(client, start_workflow(client, kind="implementation_queue"))
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    assert review["proposal"]["round"] == "approach"
    client.ok("proposal.approve", {**REVIEW_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"]})
    assert store.load_state().approved_approach
    wait_workflow(client, start_workflow(client, kind="implementation_queue"))
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    assert review["proposal"]["round"] == "code"
    client.ok("proposal.approve", {**REVIEW_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"]})
    assert not store.load_state().approved_approach
    assert store.load_state().implementation_cursor == 1


def test_review_unsaved_scope_keeps_candidate_and_virtual_buffers(tmp_path):
    from icoda_core.service import ProjectSession, review_unsaved

    root = tmp_path / "project with spaces"
    root.mkdir()
    project = ProjectSession(persistence.ProjectStore(root), DerivedModel(str(root)))
    candidate = (root / ".icoda/worktree/src/helper.py").as_uri()
    workspace = (root / "src/main.py").as_uri()
    unrelated = (tmp_path / "other/main.py").as_uri()
    documents = [candidate, workspace, candidate, unrelated, "untitled:Unsaved-1"]
    assert review_unsaved(project, {"unsavedDocuments": documents}) == tuple(sorted({candidate, workspace, "untitled:Unsaved-1"}))
    localhost = workspace.replace("file:///", "file://localhost/")
    assert review_unsaved(project, {"unsavedDocuments": [localhost]}) == (localhost,)


SLOW_LIFECYCLE_BOOTSTRAP = r'''
import sys
from icoda_core import process, service
code = "import os,time; print(os.getpid(), flush=True); time.sleep(60)"
def delay(original):
    def run(self, project, params):
        context = project.context()
        def notify(text):
            self.notify({"method": "operation.progress", "params": {**context, "message": text}})
        process.run_bounded([sys.executable, "-c", code], timeout=10, output=notify)
        notify("Old worker finished")
        return original(self, project, params)
    return run
for name in ("analyse_project", "get_view", "load_trace"):
    setattr(service.Service, name, delay(getattr(service.Service, name)))
service.main()
'''


def send_request(client, identifier, method, params=None):
    frame = {**client.context, "id": identifier, "method": method, "params": params or {}}
    client.process.stdin.write(json.dumps(frame).encode() + b"\n")
    client.process.stdin.flush()


def receive_responses(client, count):
    responses = {}
    while len(responses) < count:
        message = json.loads(client.lines.get(timeout=10))
        if "id" in message:
            responses[message["id"]] = message
        else:
            client.notifications.append(message)
    return responses


def begin_slow_request(client, method):
    params = {"view": "call"} if method == "view.get" else {"path": "calls.tsv"} if method == "trace.load" else {}
    identifier = client.sequence + 1
    send_request(client, identifier, method, params)
    while True:
        message = json.loads(client.lines.get(timeout=10))
        client.notifications.append(message)
        assert "id" not in message, message
        text = message["params"].get("message", "").strip()
        if text.isdigit():
            return identifier, int(text)


@pytest.mark.parametrize("method", ["project.analyse", "view.get", "trace.load"])
@pytest.mark.parametrize("switch", ["project.open", "target.select", "project.close"])
def test_slow_request_is_cancelled_before_selection_changes(clients, project, tmp_path, method, switch):
    store = persistence.ProjectStore(project)
    store.save_model(python_analysis.parse_project(project))
    before = store.model_path.read_bytes()
    write_trace(project)
    client = clients(SLOW_LIFECYCLE_BOOTSTRAP)
    open_project(client, project, analyse=False)
    old = dict(client.context)
    identifier, pid = begin_slow_request(client, method)
    other = tmp_path / "other"
    other.mkdir()
    params = {"path": str(other)} if switch == "project.open" else {"targetId": None} if switch == "target.select" else {}
    send_request(client, identifier + 1, switch, params)
    responses = receive_responses(client, 2)
    details = assert_error(responses[identifier], "cancelled")
    assert all(details[key] == value for key, value in old.items())
    result = responses[identifier + 1]
    assert result["status"] == "ok", result
    assert all(all(note["params"][key] == value for key, value in old.items()) for note in client.notifications)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert store.model_path.read_bytes() == before
    if switch == "target.select":
        assert result["result"]["modelRevision"] == old["modelRevision"] + 1
    elif switch == "project.open":
        assert result["result"]["sessionId"] != old["sessionId"]
    else:
        assert result["result"]["closed"]


def test_analysis_explicit_cancel_preserves_revision_and_connection(clients, project):
    persistence.ProjectStore(project).save_model(python_analysis.parse_project(project))
    client = clients(SLOW_LIFECYCLE_BOOTSTRAP)
    open_project(client, project, analyse=False)
    identifier, pid = begin_slow_request(client, "project.analyse")
    send_request(client, identifier + 1, "operation.cancel", {"requestId": identifier})
    responses = receive_responses(client, 2)
    assert_error(responses[identifier], "cancelled")
    assert responses[identifier + 1]["result"]["cancellable"]
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    client.sequence = identifier + 1
    assert client.ok("targets.list")["modelRevision"] == client.context["modelRevision"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows directory ACL inheritance")
def test_windows_lock_directory_inherits_parent_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    lock = ProjectLock(tmp_path / "project")
    try:
        acl = subprocess.run(["icacls", str(tmp_path / "icoda-service-locks")],
                             capture_output=True, text=True, errors="replace", check=True)
        assert "(I)" in acl.stdout, "Lock storage must retain inherited Windows access rights"
    finally:
        lock.close()


@pytest.mark.parametrize("operation", ["mkdir", "open"])
def test_inaccessible_lock_storage_reports_actionable_error(tmp_path, monkeypatch, operation):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    def denied(*args, **kwargs):
        raise PermissionError("Access denied")

    monkeypatch.setattr(Path, operation, denied)
    with pytest.raises(ServiceError) as failure:
        ProjectLock(tmp_path / "project")
    assert failure.value.error["code"] == "project_lock_unavailable"
    assert failure.value.error["details"]["lockDirectory"] == str(tmp_path / "icoda-service-locks")
    assert "permissions" in str(failure.value).lower()


def test_project_lock_excludes_second_service_and_releases_on_close(clients, project):
    first, second = clients(), clients()
    opened = open_project(first, project, analyse=False)
    second.ok("initialize", {"protocolVersion": 1})
    assert_error(second.request("project.open", {"path": str(project)}), "project_locked")
    reopened = first.ok("project.open", {"path": str(project)})
    assert reopened["sessionId"] != opened["sessionId"]  # Same owner may reopen without duplicating its lock.
    first.ok("project.close")
    assert_error(first.request("targets.list"), "project_not_open")
    assert second.ok("project.open", {"path": str(project)})["root"] == str(project)
    second.ok("project.close")
    assert first.ok("project.open", {"path": str(project)})["root"] == str(project)


def test_dead_lock_owner_is_recovered_without_deleting_lock_file(clients, project):
    from icoda_core.service import ProjectLock

    bootstrap = ("import sys; from pathlib import Path; from icoda_core.service import ProjectLock; "
                 "lock=ProjectLock(Path(sys.argv[1])); print(lock.handle.name, flush=True)")
    owner = subprocess.run([sys.executable, "-c", bootstrap, str(project)], cwd=ROOT,
                           capture_output=True, text=True, timeout=10, check=True)
    lock_path = Path(owner.stdout.strip())
    old_pid = int(lock_path.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(old_pid, 0)
    client = clients()
    open_project(client, project, analyse=False)
    assert int(lock_path.read_text()) == client.process.pid
    with pytest.raises(Exception, match="Another ICODA service"):
        ProjectLock(project)
    client.ok("project.close")
    lock = ProjectLock(project)
    lock.close()


def test_project_lock_is_released_on_service_exit(clients, project):
    first, second = clients(), clients()
    open_project(first, project, analyse=False)
    second.ok("initialize", {"protocolVersion": 1})
    assert_error(second.request("project.open", {"path": str(project)}), "project_locked")
    first.close()  # EOF must release ownership without a project.close request.
    assert first.process.returncode == 0
    assert second.ok("project.open", {"path": str(project)})["root"] == str(project)


def test_performance_script_measures_real_protocol_without_writing_fixture():
    fixture = ROOT / "vscode/src/test/fixtures/python"
    before = {path.relative_to(fixture): path.read_bytes() for path in fixture.rglob("*") if path.is_file()}
    result = subprocess.run([sys.executable, "tools/measure_service.py", "--project", str(fixture),
                             "--runs", "2", "--steps", "12"], cwd=ROOT, capture_output=True,
                            text=True, timeout=60, check=True)
    report = json.loads(result.stdout)
    measured, = report["projects"]
    assert report["protocolVersion"] == 1
    assert (measured["files"], measured["entities"], measured["edges"]) == (2, 7, 5)
    assert measured["trace"]["resolvedCalls"] == measured["trace"]["recordedCalls"] == 6
    assert set(measured["timings"]) == {"startup.initialize", "project.open", "project.analyse",
                                        "view.get.call", "view.get.file", "view.get.class", "trace.load", "trace.step"}
    for method, metrics in measured["timings"].items():
        assert metrics["count"] == len(metrics["samplesMs"]) == (24 if method == "trace.step" else 2)
        assert 0 <= metrics["medianMs"] <= metrics["p95Ms"] <= metrics["maxMs"]
    assert before == {path.relative_to(fixture): path.read_bytes() for path in fixture.rglob("*") if path.is_file()}


@pytest.mark.parametrize("switch", ["project.close", "target.select"])
def test_workflow_switch_joins_provider_and_keeps_terminal_notification_scoped(clients, workflow_project, switch):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    # Whole Project -> an injected real catalog entry makes target.select a change.
    if switch == "target.select":
        client.ok("project.close")
        store = persistence.ProjectStore(workflow_project)
        model = store.load_model()
        model.entities["fixture-main"] = Entity("fixture-main", Kind.FUNCTION, "main", "main", "src/main.py", 1)
        store.save_model(model)
        client.ok("project.open", {"path": str(workflow_project)})
    old = dict(client.context)
    start_workflow(client, model="slow")
    pid = wait_provider(workflow_project)
    client.ok(switch, {"targetId": None} if switch == "target.select" else {})
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    terminal = [note["params"] for note in client.notifications if note["method"] == "workflow.state"]
    assert terminal and terminal[-1]["workflow"]["state"] == "cancelled"
    assert all(all(note[key] == value for key, value in old.items()) for note in terminal)


@pytest.mark.parametrize("method", ["build.run", "target.run", "trace.record"])
def test_project_close_reaps_operation_descendants_before_unlock(clients, project, method):
    client = clients(CANCEL_BOOTSTRAP)
    open_project(client, project)
    identifier, pids, _ = active_operation(client, method)
    send_request(client, identifier + 1, "project.close")
    responses = receive_responses(client, 2)
    assert_error(responses[identifier], "cancelled")
    assert responses[identifier + 1]["result"]["closed"]
    for pid in pids:
        assert_process_gone(pid)
    replacement = clients()
    assert open_project(replacement, project, analyse=False)["root"] == str(project)


def test_lock_is_released_when_project_loading_fails(clients, project):
    store = persistence.ProjectStore(project)
    store.dir.mkdir()
    store.state_path.write_text("not-json")
    first, second = clients(), clients()
    for client in (first, second):
        client.ok("initialize", {"protocolVersion": 1})
        assert_error(client.request("project.open", {"path": str(project)}), "project_open_failed")
    store.state_path.unlink()
    assert second.ok("project.open", {"path": str(project)})["root"] == str(project)


def test_standalone_tool_discovery_uses_request_cancellation(monkeypatch):
    from icoda_core import process

    owner = threading.Event()
    backend = Service()
    backend.initialize({"protocolVersion": 1})
    def inspect(_overrides, *, cancel_event):
        assert cancel_event is owner
        cancel_event.set()
        return {"tools": [], "environment": {}, "diagnostics": []}
    monkeypatch.setattr(toolchain, "inspect_tools", inspect)
    with process.cancellation_scope(owner):
        response = handle_line(backend, b'{"id":1,"method":"toolchain.inspect","params":{}}')
    assert_error(response, "cancelled")


QUEUE_PARAMS = {"trusted": True, "unsavedDocuments": [], "provider": "fixture", "model": "ok"}


def prepare_queue(root, *, approved=True, single=True):
    from dataclasses import replace

    from icoda_core import implementation_queue

    store = persistence.ProjectStore(root)
    store.save_state(replace(store.load_state(), phase=persistence.ProjectPhase.IMPLEMENTATION))
    state = implementation_queue.ensure_state(store, store.load_model())
    store.save_state(replace(state, auto_approve=True,
        implementation_queue=state.implementation_queue[:1] if single else state.implementation_queue,
        approved_approach="Return 1 from run." if approved else ""))
    return store


def queue_status(client):
    return client.ok("queue.settings.get", {"trusted": True})


def continue_to_candidate(client, **params):
    status = client.ok("queue.continue", {**QUEUE_PARAMS, **params})
    if status["workflow"]:
        wait_workflow(client, status["workflow"]["id"])
    return queue_status(client)


def test_queue_settings_persist_across_restart_and_invalidate_approach(clients, workflow_project):
    from icoda_core import implementation_queue

    store = prepare_queue(workflow_project)
    before = store.load_state()
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    assert queue_status(client)["queueSettings"]["autoApprove"] is True
    patch = {"batchSize": 3, "scope": "all_remaining_leaves", "grouping": "few_line_group", "autoApprove": False}
    result = client.ok("queue.settings.set", {"trusted": True, "settings": patch})
    assert {key: result["queueSettings"][key] for key in patch} == patch
    expected = implementation_queue.update_settings(before, model=store.load_model(), batch_size=3,
        scope="all_remaining_leaves", grouping_mode="few_line_group", auto_approve=False)
    assert store.load_state() == expected and not expected.approved_approach
    client.close()
    reopened = clients(FAKE_BOOTSTRAP)
    open_project(reopened, workflow_project, analyse=False)
    assert queue_status(reopened)["queueSettings"] == result["queueSettings"]
    assert queue_status(reopened)["continuation"]["state"] == "stopped"


@pytest.mark.parametrize("settings", [{}, None, {"unknown": 1}, {"batchSize": 0}, {"batchSize": -1},
    {"batchSize": True}, {"batchSize": 1.5}, {"batchSize": None}, {"scope": "invalid"},
    {"scope": None}, {"grouping": "invalid"}, {"autoApprove": "yes"}, {"autoApprove": None}])
def test_queue_settings_reject_invalid_values_without_writes(clients, workflow_project, settings):
    store = prepare_queue(workflow_project)
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    before = store.state_path.read_bytes()
    assert_error(client.request("queue.settings.set", {"trusted": True, "settings": settings}), "invalid_params")
    assert store.state_path.read_bytes() == before


@pytest.mark.parametrize("method,params", [("queue.settings.get", {}),
    ("queue.settings.set", {"settings": {"autoApprove": True}}), ("queue.continue", QUEUE_PARAMS)])
def test_queue_methods_enforce_trust_and_stale_identity(clients, workflow_project, method, params):
    store = prepare_queue(workflow_project)
    client = clients(FAKE_BOOTSTRAP)
    opened = open_project(client, workflow_project, analyse=False)
    before = tree_bytes(store.dir)
    assert_error(client.request(method, {**params, "trusted": False}), "workspace_untrusted")
    for key, value, code in (("modelRevision", opened["modelRevision"] + 1, "stale_revision"),
                             ("sessionId", "old", "invalid_session"), ("targetId", "old", "stale_target")):
        assert_error(client.request(method, {**params, "trusted": True}, **{key: value}), code)
    assert tree_bytes(store.dir) == before


@pytest.mark.parametrize("remaining", [False, True])
def test_queue_continuation_passing_fake_step_advances(clients, workflow_project, remaining):
    from icoda_core import git, steplog

    store = prepare_queue(workflow_project, single=not remaining)
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    before = git.head_commit(workflow_project)
    status = continue_to_candidate(client)
    assert status["continuation"] == {"state": "running", "reason": "", "ready": True}
    assert git.head_commit(workflow_project) == before  # No approval without fresh editor evidence.
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    result = client.ok("queue.continue", {**QUEUE_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"]})
    assert result["decision"]["record"]["decision"] == "approved"
    if remaining:
        assert result["continuation"]["state"] == "running"
        result = continue_to_candidate(client)
        assert "approach rounds require developer approval" in result["continuation"]["reason"]
    else:
        assert result["continuation"]["state"] == "stopped" and "empty" in result["continuation"]["reason"]
    assert store.load_state().implementation_cursor == 1
    assert "return 1" in (workflow_project / "src/main.py").read_text()
    assert git.head_commit(workflow_project) != before
    assert steplog.StepLog(store.steps_path).records()[-1].decision == "approved"
    assert queue_status(client)["continuation"] == result["continuation"]


@pytest.mark.parametrize("mode,reason", [("build", "build gate"), ("gate", "test gate"),
    ("signature", "signature"), ("fail", "provider failure")])
def test_queue_continuation_stops_at_gates_signature_and_provider_failure(clients, workflow_project, mode, reason):
    from icoda_core import git

    store = prepare_queue(workflow_project)
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    before = git.head_commit(workflow_project)
    status = continue_to_candidate(client, model=mode)
    assert status["continuation"]["state"] == "stopped", status
    assert reason in status["continuation"]["reason"].lower(), status
    again = client.ok("queue.continue", {**QUEUE_PARAMS, "model": mode})
    assert again["continuation"]["state"] == "stopped"
    assert store.load_state().implementation_cursor == 0
    assert git.head_commit(workflow_project) == before
    if mode == "signature":
        review = client.ok("proposal.get", {"unsavedDocuments": []})
        client.ok("proposal.approve", {**REVIEW_PARAMS, "confirmSignatures": True,
                                      "evidenceFingerprint": review["evidenceFingerprint"]})
        assert store.load_state().implementation_cursor == 1
        assert "empty" in queue_status(client)["continuation"]["reason"]


def test_queue_continuation_requires_explicit_approach_approval(clients, workflow_project):
    store = prepare_queue(workflow_project, approved=False)
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    status = continue_to_candidate(client)
    assert status["continuation"]["state"] == "stopped"
    assert "approach rounds require developer approval" in status["continuation"]["reason"]
    assert not store.load_state().approved_approach
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    client.ok("proposal.approve", {**REVIEW_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"]})
    assert store.load_state().approved_approach
    assert queue_status(client)["continuation"] == {"state": "running", "reason": "", "ready": True}
    status = continue_to_candidate(client)
    assert status["workflow"]["result"]["round"] == "code"


def test_queue_continuation_cancellation_stops_provider_and_between_rounds(clients, workflow_project):
    from icoda_core import git

    store = prepare_queue(workflow_project)
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    before = git.head_commit(workflow_project)
    result = client.ok("queue.continue", {**QUEUE_PARAMS, "model": "slow"})
    wait_provider(workflow_project)
    client.ok("workflow.cancel", {"trusted": True, "workflowId": result["workflow"]["id"]})
    wait_workflow(client, result["workflow"]["id"])
    assert "Cancelled" in queue_status(client)["continuation"]["reason"]
    assert client.ok("queue.continue", QUEUE_PARAMS)["continuation"]["state"] == "stopped"
    assert store.load_state().implementation_cursor == 0 and git.head_commit(workflow_project) == before
    client.ok("project.open", {"path": str(workflow_project)})
    # Cancellation without a job also clears a ready continuation.
    client.ok("workflow.cancel", {"trusted": True})
    assert queue_status(client)["continuation"]["state"] == "stopped"


def test_queue_continuation_empty_never_starts_provider(clients, workflow_project):
    from dataclasses import replace

    store = prepare_queue(workflow_project)
    state = store.load_state()
    store.save_state(replace(state, implementation_cursor=len(state.implementation_queue)))
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    result = client.ok("queue.continue", {**QUEUE_PARAMS, "provider": "must-not-resolve"})
    assert result["workflow"] is None
    assert result["continuation"]["state"] == "stopped" and "empty" in result["continuation"]["reason"]


@pytest.mark.parametrize("changed", ["unsaved", "candidate", "project"])
def test_queue_continuation_revalidates_approval_evidence(clients, workflow_project, changed):
    from icoda_core import git

    store = prepare_queue(workflow_project)
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    continue_to_candidate(client)
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    params = {**QUEUE_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"]}
    if changed == "unsaved":
        params["unsavedDocuments"] = [str(workflow_project / "src/main.py")]
    elif changed == "candidate":
        (store.dir / "worktree/src/main.py").write_text("def run():\n    return 9\n")
    else:
        (workflow_project / "src/main.py").write_text("def run():\n    return 8\n")
    before = git.head_commit(workflow_project)
    code = {"unsaved": "unsaved_documents", "candidate": "stale_evidence", "project": "dirty_tree"}[changed]
    assert_error(client.request("queue.continue", params), code)
    assert queue_status(client)["continuation"]["state"] == "stopped"
    assert store.load_state().implementation_cursor == 0 and git.head_commit(workflow_project) == before


def test_queue_continuation_cancelled_promotion_rolls_back(clients, workflow_project):
    import time

    from icoda_core import git

    store = prepare_queue(workflow_project)
    marker = workflow_project.parent / "promotion-started"
    bootstrap = FAKE_BOOTSTRAP.split("from icoda_core.service import main;")[0] + f'''
from icoda_core import steps, process
from pathlib import Path
import sys
original = steps.StepRunner._build_project
def slow_promotion(self, root):
    if root == self.root and 'return 1' in (root / 'src/main.py').read_text():
        Path({str(marker)!r}).write_text('started')
        result = process.run_bounded([sys.executable, '-c', 'import time; time.sleep(60)'], cwd=root)
        return steps.BuildResult(result.ok, 'controlled promotion cancelled')
    return original(self, root)
steps.StepRunner._build_project = slow_promotion
from icoda_core.service import main
main()
'''
    client = clients(bootstrap)
    open_project(client, workflow_project, analyse=False)
    continue_to_candidate(client)
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    before = git.head_commit(workflow_project)
    request_id = "queue-promotion"
    client.process.stdin.write(json.dumps({"id": request_id, "method": "queue.continue", **client.context,
        "params": {**QUEUE_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"]}}).encode() + b"\n")
    client.process.stdin.flush()
    deadline = time.monotonic() + 10
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert marker.exists()
    client.ok("operation.cancel", {"requestId": request_id})
    while True:
        reply = json.loads(client.lines.get(timeout=10))
        if reply.get("id") == request_id:
            break
        client.notifications.append(reply)
    assert reply["status"] in ("error", "cancelled")
    assert queue_status(client)["continuation"] == {"state": "stopped", "reason": "Cancelled.", "ready": False}
    assert store.load_state().implementation_cursor == 0 and git.head_commit(workflow_project) == before
    assert "pass" in (workflow_project / "src/main.py").read_text()


def test_queue_settings_busy_guard_and_disabled_continuation(clients, workflow_project):
    from dataclasses import replace

    store = prepare_queue(workflow_project)
    store.save_state(replace(store.load_state(), auto_approve=False))
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    result = client.ok("queue.continue", {**QUEUE_PARAMS, "provider": "must-not-resolve"})
    assert result["workflow"] is None and result["continuation"]["state"] == "stopped"
    identifier = start_workflow(client, kind="implementation_queue", model="slow")
    wait_provider(workflow_project)
    before = store.state_path.read_bytes()
    assert_error(client.request("queue.settings.set", {"trusted": True, "settings": {"batchSize": 2}}), "workflow_busy")
    assert store.state_path.read_bytes() == before
    client.ok("workflow.cancel", {"trusted": True, "workflowId": identifier})
    wait_workflow(client, identifier)


def test_queue_auto_toggle_evaluates_current_candidate(clients, workflow_project):
    from dataclasses import replace

    store = prepare_queue(workflow_project)
    store.save_state(replace(store.load_state(), auto_approve=False))
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    wait_workflow(client, start_workflow(client, kind="implementation_queue"))
    result = client.ok("queue.settings.set", {"trusted": True, "settings": {"autoApprove": True}})
    assert result["continuation"] == {"state": "running", "reason": "", "ready": True}
    assert store.load_state().implementation_cursor == 0


@pytest.fixture
def interrupted_proposal(workflow_project):
    """A partially applied code response; no provider is invoked to create this checkout."""
    from icoda_core import git, prompt, recovery, response, steps

    runner = steps.StepRunner(workflow_project, persistence.UserConfig())
    worktree = git.create_worktree(workflow_project, runner.store.dir / "worktree", "retained-proposal")
    reply = json.dumps({"title": "Retained helper", "rationale": "Review the interrupted helper addition.",
                       "files": [{"path": "src/helper.py", "content": 'def helper():\n    """A helper stub."""\n    pass\n'}]})
    parsed, error = response.parse_response(reply)
    assert parsed is not None, error
    candidate = steps.Proposal(1, prompt.StepRequest("architecture", 1, "Add the helper", max_entities=2),
                               worktree, response=parsed, reply=reply)
    recovery.checkpoint_proposal(workflow_project, candidate)
    (worktree / "src/helper.py").write_text(parsed.files[0].content)
    return workflow_project, worktree


def recovery_params(client, choice, **extra):
    listed = client.ok("recovery.list", {"trusted": True})
    assert len(listed["items"]) == 1
    assert [item["value"] for item in listed["items"][0]["choices"]] == ["resume", "keep", "discard"]
    return {"trusted": True, "recoveryId": listed["items"][0]["id"], "choice": choice,
            "unsavedDocuments": [], **extra}


@pytest.mark.parametrize("choice", ["resume", "keep", "discard"])
def test_recovery_choices_preserve_source_and_resume_review(clients, interrupted_proposal, choice):
    from icoda_core import git, recovery

    root, worktree = interrupted_proposal
    before = git.head_commit(root)
    client = clients()
    open_project(client, root, analyse=False)
    params = recovery_params(client, choice, confirmDiscard=choice == "discard")
    result = client.ok("recovery.resolve", params)
    assert git.head_commit(root) == before and not (root / "src/helper.py").exists()
    if choice == "resume":
        assert wait_workflow(client, result["workflow"]["id"])["state"] == "completed"
        review = client.ok("proposal.get", {"unsavedDocuments": []})
        assert review["proposal"]["worktreeRoot"] == str(worktree)
        assert review["proposal"]["canApprove"] and review["proposal"]["evidenceFresh"]
        assert client.ok("recovery.list", {"trusted": True})["items"] == []
        client.ok("proposal.reject", {**REVIEW_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"], "reason": "Not needed"})
        assert not recovery.proposal_journal(root).exists()
    elif choice == "keep":
        assert (worktree / "src/helper.py").exists() and len(result["items"]) == 1
        assert_error(client.request("workflow.start", AI_PARAMS), "proposal_pending")
        client.close()
        reopened = clients()
        open_project(reopened, root, analyse=False)
        assert recovery_params(reopened, "keep")["recoveryId"] == params["recoveryId"]
    else:
        assert result["items"] == [] and not worktree.exists() and not recovery.proposal_journal(root).exists()
        assert git.run_git(["rev-parse", "retained-proposal"], root).stdout.strip() == before  # Named refs are preserved.


@pytest.mark.parametrize("choice", ["resume", "discard"])
@pytest.mark.parametrize("obstacle", ["dirty", "unsaved", "unconfirmed"])
def test_recovery_refuses_dirty_unsaved_and_unconfirmed_discard(clients, interrupted_proposal, choice, obstacle):
    root, worktree = interrupted_proposal
    client = clients()
    open_project(client, root, analyse=False)
    params = recovery_params(client, choice, confirmDiscard=True)
    if obstacle == "dirty":
        (root / "src/main.py").write_text("# Manual edits must survive\n")
        code = "dirty_tree"
    elif obstacle == "unsaved":
        params["unsavedDocuments"] = [(worktree / "src/helper.py").as_uri()]
        code = "unsaved_documents"
    else:
        params["choice"], params["confirmDiscard"] = "discard", False
        code = "confirmation_required"
    assert_error(client.request("recovery.resolve", params), code)
    assert (worktree / "src/helper.py").exists()


def test_recovery_identity_choice_and_trust_errors(clients, interrupted_proposal):
    root, _worktree = interrupted_proposal
    client = clients()
    capabilities = client.ok("initialize", {"protocolVersion": 1})["capabilities"]["methods"]
    assert {"recovery.list", "recovery.resolve"} <= set(capabilities)
    client.ok("project.open", {"path": str(root)})
    params = recovery_params(client, "keep")
    for method, values in (("recovery.list", {"trusted": True}), ("recovery.resolve", params)):
        for context, code in (({"modelRevision": 999}, "stale_revision"), ({"sessionId": "old"}, "invalid_session"),
                              ({"targetId": "old"}, "stale_target")):
            assert_error(client.request(method, values, **context), code)
        for trusted in (False, "true", 1, None):
            assert_error(client.request(method, {**values, "trusted": trusted}), "workspace_untrusted")
    assert_error(client.request("recovery.resolve", {**params, "choice": "approve"}), "invalid_choice")
    assert_error(client.request("recovery.resolve", {**params, "recoveryId": "unknown"}), "recovery_missing")
    assert_error(client.request("recovery.resolve", {**params, "confirmDiscard": "true"}), "invalid_params")


def test_recovery_revalidates_candidate_and_git_failures(clients, interrupted_proposal):
    root, worktree = interrupted_proposal
    client = clients()
    open_project(client, root, analyse=False)
    params = recovery_params(client, "resume")
    (worktree / "src/helper.py").write_text("# changed after listing\n")
    assert_error(client.request("recovery.resolve", params), "recovery_missing")
    # A registered worktree lock must be reported, never bypassed with a filesystem delete.
    from icoda_core import git
    git.run_git(["worktree", "lock", str(worktree)], root)
    params = recovery_params(client, "discard", confirmDiscard=True)
    assert_error(client.request("recovery.resolve", params), "git_failed")
    assert worktree.exists()


def test_recovery_failed_gate_and_unsaved_evidence_still_block_approval(clients, interrupted_proposal):
    from icoda_core import git

    root, worktree = interrupted_proposal
    (worktree / "tests/test_main.py").write_text('def test_fixture():\n    """Fail deliberately."""\n    assert False\n')
    before = git.head_commit(root)
    client = clients()
    open_project(client, root, analyse=False)
    result = client.ok("recovery.resolve", recovery_params(client, "resume"))
    assert wait_workflow(client, result["workflow"]["id"])["state"] == "failed"
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    assert review["proposal"]["tests"]["ok"] is False and not review["proposal"]["canApprove"]
    params = {**REVIEW_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"]}
    assert_error(client.request("proposal.approve", params), "proposal_gate_failed")
    assert_error(client.request("proposal.approve", {**params, "unsavedDocuments": [(worktree / "src/helper.py").as_uri()]}), "stale_evidence")
    assert git.head_commit(root) == before


def test_recovery_legacy_worktree_and_changed_base(clients, interrupted_proposal):
    from icoda_core import git, recovery

    root, _worktree = interrupted_proposal
    recovery.proposal_journal(root).unlink()
    client = clients()
    open_project(client, root, analyse=False)
    job = client.ok("recovery.resolve", recovery_params(client, "resume"))
    assert wait_workflow(client, job["workflow"]["id"])["state"] == "completed"
    client.close()
    git.run_git(["-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "--allow-empty", "-m", "Moved baseline"], root)
    reopened = clients()
    open_project(reopened, root, analyse=False)
    assert_error(reopened.request("recovery.resolve", recovery_params(reopened, "resume")), "stale_evidence")


def test_recovery_interrupted_provider_checkpoint_survives_restart(clients, workflow_project):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    identifier = start_workflow(client, model="slow")
    wait_provider(workflow_project)
    client.ok("workflow.cancel", {"trusted": True, "workflowId": identifier})
    wait_workflow(client, identifier)
    client.close()  # Reopen after an interrupted provider; the journal and checkout survive.
    reopened = clients()
    open_project(reopened, workflow_project, analyse=False)
    result = reopened.ok("recovery.resolve", recovery_params(reopened, "resume"))
    wait_workflow(reopened, result["workflow"]["id"])
    assert reopened.ok("proposal.get", {"unsavedDocuments": []})["proposal"] is not None
    assert reopened.ok("workflow.status", {"trusted": True})["continuation"]["state"] == "stopped"


def test_recovery_never_auto_approves_or_skips_signature_confirmation(clients, workflow_project):
    from dataclasses import replace

    from icoda_core import git

    client, _review, _params = reviewed_proposal(clients, workflow_project, "signature")
    client.close()
    store = persistence.ProjectStore(workflow_project)
    store.save_state(replace(store.load_state(), auto_approve=True))
    before = git.head_commit(workflow_project)
    resumed = clients()
    open_project(resumed, workflow_project, analyse=False)
    result = resumed.ok("recovery.resolve", recovery_params(resumed, "resume"))
    wait_workflow(resumed, result["workflow"]["id"])
    status = resumed.ok("queue.settings.set", {"trusted": True, "settings": {"autoApprove": True}})
    assert status["continuation"]["state"] == "stopped"
    assert "explicit review" in status["continuation"]["reason"]
    review = resumed.ok("proposal.get", {"unsavedDocuments": []})
    params = {**REVIEW_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"]}
    assert_error(resumed.request("proposal.approve", params), "signature_unconfirmed")
    assert git.head_commit(workflow_project) == before
    resumed.ok("proposal.approve", {**params, "confirmSignatures": True})
    assert git.head_commit(workflow_project) != before


def test_recovery_queue_stops_automatic_approval_and_keeps_approach_gate(clients, workflow_project):
    from dataclasses import replace

    from icoda_core import git

    store = prepare_queue(workflow_project)
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    assert wait_workflow(client, start_workflow(client, kind="implementation_queue"))["state"] == "completed"
    client.close()
    before = git.head_commit(workflow_project)
    resumed = clients()
    open_project(resumed, workflow_project, analyse=False)
    job = resumed.ok("recovery.resolve", recovery_params(resumed, "resume"))
    assert wait_workflow(resumed, job["workflow"]["id"])["state"] == "completed"
    review = resumed.ok("proposal.get", {"unsavedDocuments": []})
    result = resumed.ok("queue.continue", {**REVIEW_PARAMS, "evidenceFingerprint": review["evidenceFingerprint"]})
    assert result["continuation"]["state"] == "stopped" and "explicit review" in result["continuation"]["reason"]
    assert git.head_commit(workflow_project) == before and store.load_state().implementation_cursor == 0
    resumed.close()
    store.save_state(replace(store.load_state(), approved_approach=""))
    reopened = clients()
    open_project(reopened, workflow_project, analyse=False)
    assert_error(reopened.request("recovery.resolve", recovery_params(reopened, "resume")), "proposal_gate_failed")


@pytest.mark.parametrize("reply", ["", '{"plan":"Return one", "entities":["run"], "files":["src/main.py"]}'])
def test_recovery_approach_checkpoint_preserves_explicit_review(clients, workflow_project, reply):
    from icoda_core import prompt, recovery, steps

    prepare_queue(workflow_project, approved=False)
    runner = steps.StepRunner(workflow_project, persistence.UserConfig())
    request, _state = runner._targeted_request(prompt.StepRequest("implementation", 1), 1, "approach")
    recovery.checkpoint_proposal(workflow_project, steps.Approach(1, request, request.target, reply=reply))
    client = clients()
    open_project(client, workflow_project, analyse=False)
    result = client.ok("recovery.resolve", recovery_params(client, "resume"))
    wait_workflow(client, result["workflow"]["id"])
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    assert review["proposal"]["round"] == "approach" and review["proposal"]["canApprove"] == bool(reply)
    assert not runner.store.load_state().approved_approach


def test_recovery_rediscovered_after_analysis_supersedes_review(clients, interrupted_proposal):
    root, _worktree = interrupted_proposal
    client = clients()
    open_project(client, root, analyse=False)
    job = client.ok("recovery.resolve", recovery_params(client, "resume"))
    wait_workflow(client, job["workflow"]["id"])
    assert client.ok("recovery.list", {"trusted": True})["items"] == []
    client.ok("project.analyse")
    assert len(client.ok("recovery.list", {"trusted": True})["items"]) == 1
    job = client.ok("recovery.resolve", recovery_params(client, "resume"))
    assert wait_workflow(client, job["workflow"]["id"])["state"] == "completed"


INTERACTION_PARAMS = {"trusted": True, "unsavedDocuments": [], "provider": "fixture", "model": "ok"}


def start_interaction(client, method="conversation.send", **params):
    return client.ok(method, {**INTERACTION_PARAMS, **({"message": "Explain the entry."}
        if method == "conversation.send" else {}), **params})["workflow"]["id"]


def test_conversation_shared_provider_history_and_no_step_records(clients, workflow_project):
    from icoda_core import git

    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    store = persistence.ProjectStore(workflow_project)
    before = store.steps_path.read_bytes(), store.state_path.read_bytes(), git.head_commit(workflow_project)
    for message in ("Explain the entry.", "And its caller? Grüße"):
        job = wait_workflow(client, start_interaction(client, message=message))
        assert job["state"] == "completed", job
        assert message in job["result"]["summary"]
    messages = client.ok("conversation.history", {"trusted": True})["messages"]
    assert [item["role"] for item in messages] == ["Developer", "Assistant"] * 2
    assert "Explain the entry." in messages[-1]["text"]
    assert before == (store.steps_path.read_bytes(), store.state_path.read_bytes(), git.head_commit(workflow_project))
    assert client.ok("workflow.status", {"trusted": True})["workflow"] is None
    client.ok("project.analyse")
    assert client.ok("conversation.history", {"trusted": True})["messages"] == messages
    client.ok("project.open", {"path": str(workflow_project)})
    assert client.ok("conversation.history", {"trusted": True})["messages"] == []


@pytest.mark.parametrize("mode,state", [("edit", "completed"), ("edit-fail", "failed"), ("edit-slow", "cancelled")])
def test_conversation_edits_and_partial_failure_cancel_mark_stale(clients, workflow_project, mode, state):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    log = persistence.ProjectStore(workflow_project).steps_path.read_bytes()
    identifier = start_interaction(client, model=mode)
    if state == "cancelled":
        wait_provider(workflow_project)
        assert_error(client.request("workflow.start", AI_PARAMS), "workflow_busy")
        client.ok("workflow.cancel", {"trusted": True, "workflowId": identifier})
    job = wait_workflow(client, identifier)
    assert job["state"] == state, job
    assert job["sourceChanged"]
    assert "return 42" in (workflow_project / "src/main.py").read_text()
    assert persistence.ProjectStore(workflow_project).load_model().stale
    assert persistence.ProjectStore(workflow_project).steps_path.read_bytes() == log
    if state != "completed":
        assert job["error"]["code"] == ("provider_cancelled" if state == "cancelled" else "provider_failed")
    assert client.ok("view.get", {"view": "file"})["nodes"]


@pytest.mark.parametrize("kind", ["architecture", "implementation_approach"])
def test_rephrase_preserves_candidate_gates_history_and_approval(clients, workflow_project, kind):
    from dataclasses import replace

    store = persistence.ProjectStore(workflow_project)
    if kind == "implementation_approach":
        store.save_state(replace(store.load_state(), phase=persistence.ProjectPhase.IMPLEMENTATION))
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    wait_workflow(client, start_workflow(client, kind=kind))
    review = client.ok("proposal.get", {"unsavedDocuments": []})
    before = store.steps_path.read_bytes(), store.state_path.read_bytes()
    job = wait_workflow(client, start_interaction(client, "prompt.rephrase"))
    assert job["state"] == "completed", job
    after = client.ok("proposal.get", {"unsavedDocuments": []})
    assert after["proposal"]["summary"] == "A simpler description of the same step."
    assert {k: v for k, v in after["proposal"].items() if k != "summary"} == {
        k: v for k, v in review["proposal"].items() if k != "summary"}
    assert before == (store.steps_path.read_bytes(), store.state_path.read_bytes())
    assert after["proposal"]["canApprove"]


@pytest.mark.parametrize("mode,state", [("fail", "failed"), ("empty", "failed"), ("slow", "cancelled")])
def test_rephrase_failure_cancel_keep_original_review(clients, workflow_project, mode, state):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    wait_workflow(client, start_workflow(client, model="gate"))
    before = client.ok("proposal.get", {"unsavedDocuments": []})
    job_id = start_interaction(client, "prompt.rephrase", model=mode)
    if state == "cancelled":
        wait_provider(workflow_project)
        client.ok("workflow.cancel", {"trusted": True, "workflowId": job_id})
    job = wait_workflow(client, job_id)
    assert job["state"] == state, job
    assert job["error"]["code"] == ("provider_cancelled" if state == "cancelled" else "provider_failed")
    after = client.ok("proposal.get", {"unsavedDocuments": []})
    assert before == after
    assert not after["proposal"]["canApprove"]


def test_conversation_candidate_edits_require_rebuild_and_never_approve(clients, workflow_project):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    wait_workflow(client, start_workflow(client))
    before = client.ok("proposal.get", {"unsavedDocuments": []})
    wait_workflow(client, start_interaction(client, model="edit"))
    assert "return 42" not in (workflow_project / "src/main.py").read_text()
    assert "return 42" in (workflow_project / ".icoda/worktree/src/main.py").read_text()
    after = client.ok("proposal.get", {"unsavedDocuments": []})
    assert not after["proposal"]["evidenceFresh"] and not after["proposal"]["canApprove"]
    assert_error(client.request("proposal.approve", {"trusted": True, "unsavedDocuments": [],
        "evidenceFingerprint": before["evidenceFingerprint"]}), "stale_evidence")
    wait_workflow(client, start_interaction(client, "prompt.rephrase"))
    assert not client.ok("proposal.get", {"unsavedDocuments": []})["proposal"]["canApprove"]


@pytest.mark.parametrize("method,params", [("conversation.send", {"message": "Hello"}),
    ("conversation.history", {}), ("prompt.rephrase", {}), ("cli.command", {"draft": "Help"})])
def test_interaction_trust_identity_and_no_provider_navigation(clients, workflow_project, method, params):
    client = clients("from icoda_core import agent; agent.load_providers = lambda: []; "
        "from icoda_core.service import main; main()")
    open_project(client, workflow_project, analyse=False)
    args = {**INTERACTION_PARAMS, **params} if method != "conversation.history" else {"trusted": True}
    for trusted in (False, None, "true"):
        assert_error(client.request(method, {**args, "trusted": trusted}), "workspace_untrusted")
    assert_error(client.request(method, args, modelRevision=999), "stale_revision")
    assert_error(client.request(method, args, sessionId="old"), "invalid_session")
    assert_error(client.request(method, args, targetId="old"), "stale_target")
    if method in ("conversation.send", "cli.command"):
        assert_error(client.request(method, args), "provider_unavailable")
    elif method == "prompt.rephrase":
        assert_error(client.request(method, args), "proposal_missing")
    else:
        assert client.ok(method, args)["messages"] == []
    assert client.ok("source.resolve", {"file": "src/main.py", "sourceRootId": client.context["sessionId"] + ":workspace"})["path"].endswith("main.py")
    assert client.ok("view.get", {"view": "file"})["nodes"]


@pytest.mark.parametrize("params", [{"message": " "}, {"message": "x" * 20001}, {"message": "x\0"},
    {"message": 7}, {"message": "Hi", "argv": ["unsafe"]}])
def test_conversation_rejects_invalid_inputs_before_provider(clients, workflow_project, params):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    assert_error(client.request("conversation.send", {**INTERACTION_PARAMS, **params}), "invalid_params")
    assert client.ok("conversation.history", {"trusted": True})["messages"] == []


@pytest.mark.parametrize("method", ["conversation.send", "cli.command"])
def test_conversation_cli_preserve_unsaved_buffers(clients, workflow_project, method):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    params = {**INTERACTION_PARAMS, **({"message": "Edit"} if method == "conversation.send" else {}),
        "unsavedDocuments": [(workflow_project / "src/main.py").as_uri()]}
    assert_error(client.request(method, params), "unsaved_documents")


def test_cli_command_argument_array_context_and_no_spawn(clients, workflow_project):
    # A controlled registry entry named codex exercises its shared interactive template; it is never run.
    bootstrap = FAKE_BOOTSTRAP.replace("from icoda_core.service import main; main()", """
from dataclasses import replace
from icoda_core import agent, terminal
fixture = agent.load_providers()[0]
agent.load_providers = lambda: [fixture, replace(fixture, id='codex')]
original = agent.run_provider
def run_fixture(provider, *args, **kwargs):
    assert provider.id == 'fixture'
    return original(provider, *args, **kwargs)
agent.run_provider = run_fixture
def refuse(*args, **kwargs):
    raise AssertionError('CLI command must never spawn a process')
terminal.open_cli = refuse
from icoda_core.service import main
main()
""")
    client = clients(bootstrap)
    opened = open_project(client, workflow_project, analyse=False)
    wait_workflow(client, start_interaction(client))
    messages = client.ok("conversation.history", {"trusted": True})["messages"]
    draft = 'Explain "hello"; $(touch forbidden)\nGrüße'
    result = client.ok("cli.command", {**INTERACTION_PARAMS, "provider": "codex", "draft": draft})
    assert result["argv"][:9] == [os.path.abspath(sys.executable), "--cd", str(workflow_project), "-m", "ok",
        "--sandbox", "workspace-write", "--ask-for-approval", "on-request"]
    assert draft in result["argv"][-1] and "Explain the entry." in result["argv"][-1]
    assert result["cwd"] == str(workflow_project) and result["env"] == {}
    assert result["sessionId"] == opened["sessionId"]
    assert client.ok("conversation.history", {"trusted": True})["messages"] == messages
    assert not (workflow_project / "forbidden").exists()


@pytest.mark.parametrize("method", ["conversation.send", "prompt.rephrase"])
def test_interaction_project_switch_cancels_provider_and_drops_old_job(clients, workflow_project, project, method):
    client = clients(FAKE_BOOTSTRAP)
    old = open_project(client, workflow_project, analyse=False)
    if method == "prompt.rephrase":
        wait_workflow(client, start_workflow(client))
    identifier = start_interaction(client, method, model="slow")
    pid = wait_provider(workflow_project)
    opened = client.ok("project.open", {"path": str(project)})
    assert old["sessionId"] != opened["sessionId"]
    assert_error(client.request("workflow.status", {"trusted": True, "workflowId": identifier}), "workflow_missing")
    assert client.ok("conversation.history", {"trusted": True})["messages"] == []
    if sys.platform != "win32":
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_rephrase_no_provider_and_cli_unsupported_are_provider_errors(clients, workflow_project):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, workflow_project, analyse=False)
    wait_workflow(client, start_workflow(client))
    before = client.ok("proposal.get", {"unsavedDocuments": []})
    assert_error(client.request("prompt.rephrase", {**INTERACTION_PARAMS, "provider": "not-installed"}), "provider_unavailable")
    assert_error(client.request("cli.command", INTERACTION_PARAMS), "provider_unavailable")
    assert before == client.ok("proposal.get", {"unsavedDocuments": []})
    assert client.ok("source.resolve", {"file": "src/main.py", "sourceRootId": client.context["sessionId"] + ":workspace"})["path"].endswith("main.py")


def test_p04_graph_interactions_match_desktop_filters_and_preserve_views(clients, tmp_path):
    from icoda_core import clusters, coverage_index, graph_filter, node_status

    root = tmp_path / "graph"
    root.mkdir()
    model = DerivedModel(str(root))
    for scope in ("app", "app::detail", "apple"):
        file = scope.replace("::", "/") + ".cpp"
        model.files[file] = FileInfo(file)
        for name, kind in ((scope, Kind.NAMESPACE), (scope + "::Widget", Kind.CLASS),
                           (scope + "::Widget::run", Kind.METHOD)):
            model.add_entity(Entity(name, kind, name.rpartition("::")[2], name, file, 1,
                                    parent=scope + "::Widget" if kind == Kind.METHOD else None))
    model.add_edge(Edge(EdgeKind.CALLS, "app::Widget::run", "app::detail::Widget::run"))
    model.add_edge(Edge(EdgeKind.USES_TYPE, "app::Widget", "apple::Widget"))
    store = persistence.ProjectStore(root)
    store.ensure()
    store.save_model(model)
    before = {p: p.read_bytes() for p in store.dir.rglob("*") if p.is_file()}
    client = clients()
    opened = open_project(client, root, analyse=False)
    context = dict(client.context)
    graphs = {view: client.ok("view.get", {"view": view}) for view in ("call", "file", "class", "mindmap")}
    grouping = clusters.cluster_files(model, store.load_layout())
    graph = graph_filter.project_graph(model,
        {file: cluster.id for cluster in grouping.clusters for file in cluster.files},
        {cluster.id: cluster.name for cluster in grouping.clusters})
    appearances = node_status.derive(model, store.load_state(), [], coverage_index.CoverageIndex())
    for text in ("namespace:app", "namespace:app::*", "edge:calls", "kind:method", "status:stub", "name:missing"):
        result = client.ok("graph.interactions", {"sourceRootId": opened["sourceRootId"],
                           "text": text, "depth": 1, "focus": "entity:app::Widget::run"})
        expected = graph_filter.derive(model, graph, appearances, graph_filter.parse(text),
                                      focus_usr="app::Widget::run", neighborhood_depth=1)
        assert result["decisions"] == {key: {"hidden": value.hidden, "dimmed": value.dimmed}
                                        for key, value in expected.items()}
        if text == "namespace:app":
            assert not result["decisions"]["app::Widget::run"]["hidden"]
            assert result["decisions"]["app::detail::Widget::run"]["hidden"]
        if text == "namespace:app::*":
            assert not result["decisions"]["app::detail::Widget::run"]["hidden"]
            assert result["decisions"]["apple::Widget::run"]["hidden"]
    for view, original in graphs.items():
        assert client.ok("view.get", {"view": view}) == original
    assert client.context == context
    assert {p: p.read_bytes() for p in store.dir.rglob("*") if p.is_file()} == before


def test_p04_graph_interactions_validate_identity_and_keep_playback(clients, project):
    client = clients()
    opened = open_project(client, project)
    args = {"sourceRootId": opened["sourceRootId"], "text": "", "depth": 1, "focus": "python:program:B"}
    trace = client.ok("trace.load", {"path": str(write_trace(project))})
    selected = client.step("seek", usr="python:program:B")
    result = client.ok("graph.interactions", {**args, "traceId": trace["traceId"]})
    assert not result["decisions"]["python:program:C"]["dimmed"]
    assert result["decisions"]["python:program:E"]["dimmed"]
    assert client.step("seek", usr="python:program:B") == selected
    for invalid in ({"text": "x" * 257}, {"text": "a\0b"}, {"text": []}, {"depth": True},
                    {"depth": -1}, {"depth": 13}, {"depth": 1.5}, {"focus": "absent"},
                    {"focus": ""}, {"unexpected": True}, {"traceId": "old"}):
        assert_error(client.request("graph.interactions", {**args, **invalid}), "invalid_params")
    assert_error(client.request("graph.interactions", args, modelRevision=opened["modelRevision"] - 1), "stale_revision")
    assert_error(client.request("graph.interactions", {**args, "sourceRootId": "other"}), "stale_evidence")
    assert client.step("over")["currentEntityUsr"] == "python:program:D"


@pytest.mark.parametrize("method", ["build.run", "tests.run", "target.run", "trace.record", "targets.refresh"])
@pytest.mark.parametrize("params,code", [({}, "workspace_untrusted"), ({"trusted": False}, "workspace_untrusted"),
    ({"trusted": "true"}, "workspace_untrusted"), ({"trusted": True, "selection": ["anything"]}, "invalid_params")])
def test_p06_operations_validate_trust_and_params_before_tools(target_service, monkeypatch, method, params, code):
    from icoda_core import service

    backend, _, _ = target_service
    monkeypatch.setattr(service, "operation_tools", lambda *_a: pytest.fail("unvalidated operation launched"))
    frame = {"id": 53, "method": method, "params": params, **backend.project.context()}
    assert_error(handle_line(backend, json.dumps(frame).encode()), code)
    assert operation_request(backend, "targets.list")["status"] == "ok"


def test_p06_whole_build_uses_shared_gate_and_child_environment(target_service, monkeypatch):
    from icoda_core import process, service, steps

    backend, notifications, target = target_service
    backend.select_target(backend.project, {"targetId": None})
    context, before, calls = backend.project.context(), dict(os.environ), []
    (backend.project.store.root / "CMakeLists.txt").touch()
    monkeypatch.setattr(service.shutil, "which", lambda command, **_k: command)
    def run(command, **kwargs):
        calls.append((command, kwargs))
        kwargs["output"]("whole build output\n")
        return process.ProcessResult(command, 0, "whole build output\n", "")
    monkeypatch.setattr(steps, "run_bounded", lambda *_a, **_k: pytest.fail("must use owned runner"))
    monkeypatch.setattr(process, "run_bounded", run)
    result = operation_request(backend)["result"]
    assert result["check"] == {"kind": "build", "ok": True, "output": "whole build output\n" * 2}
    assert calls[-1][0] == ["/tools/cmake", "--build", str(target.build_dir)]
    assert all(kwargs["env"]["ICODA_CHILD_ONLY"] == "yes" and kwargs["cancel_event"] for _, kwargs in calls)
    assert result["target"]["kind"] == "whole-project" and result["executable"] is None
    assert backend.project.context() == context and os.environ == before
    assert any(note["method"] == "operation.log" for note in notifications)


def test_p06_python_build_and_full_pytest_failure_recover_without_cpp_tools(clients, tmp_path):
    root = tmp_path / "Python checks"
    root.mkdir()
    test_file = root / "test_example.py"
    test_file.write_text("def test_example():\n    assert True\n")
    client = clients()
    open_project(client, root)
    client.ok("target.select", {"targetId": None})
    context = dict(client.context)
    # A bad C++ override cannot prevent Python's compileall or Code Profile pytest runner.
    params = {"clangPath": "/absent/clang"}
    assert client.ok("build.run", params)["check"]["kind"] == "build"
    result = client.ok("tests.run", params)
    assert result["check"]["ok"] and "1 passed" in result["check"]["output"]
    test_file.write_text("def test_example():\n    assert False, 'P06 failing assertion'\n")
    failed = client.request("tests.run", params)
    assert_error(failed, "test_failed")
    assert "P06 failing assertion" in failed["error"]["message"]
    test_file.write_text("def test_example():\n    assert True\n")
    assert client.ok("tests.run", params)["check"]["ok"]
    assert client.context == context
    assert not (root / "build").exists() and not (root / ".icoda/steps.jsonl").exists()


def test_p06_full_tests_use_configured_arguments_report_missing_tool_and_preserve_target(target_service, monkeypatch):
    from dataclasses import replace

    from icoda_core import process, service

    backend, _, _ = target_service
    root = backend.project.store.root
    (root / "CMakeLists.txt").touch()
    command = ("/custom/test runner", "argument with spaces", "--output-on-failure")
    backend.project.store.save_state(replace(backend.project.store.load_state(), test_command=command))
    context, calls = backend.project.context(), []
    monkeypatch.setattr(service.shutil, "which", lambda command, **_k: command)
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return process.ProcessResult(args, 0, "all tests passed", "")
    monkeypatch.setattr(process, "run_bounded", run)
    result = operation_request(backend, "tests.run")["result"]
    assert calls[0][0] == list(command) and len(calls) == 1
    assert result["check"]["kind"] == "tests"
    assert result["targetId"] == context["targetId"] and result["target"]["kind"] == "whole-project"
    monkeypatch.setattr(service.shutil, "which", lambda *_a, **_k: None)
    details = assert_error(operation_request(backend, "tests.run"), "missing_tool")
    assert details["tool"] == command[0] and len(calls) == 1
    assert backend.project.context() == context


def test_p06_full_tests_cancellation_keeps_service_usable(target_service, monkeypatch):
    from dataclasses import replace

    from icoda_core import process, service

    backend, _, _ = target_service
    (backend.project.store.root / "CMakeLists.txt").touch()
    backend.project.store.save_state(replace(backend.project.store.load_state(), test_command=(sys.executable, "-V")))
    monkeypatch.setattr(service.shutil, "which", lambda command, **_k: command)
    def run(command, **kwargs):
        kwargs["cancel_event"].set()
        return process.ProcessResult(command, -1, "", "", cancelled=True)
    monkeypatch.setattr(process, "run_bounded", run)
    assert_error(operation_request(backend, "tests.run"), "cancelled")
    assert not backend.operations
    assert operation_request(backend, "targets.list")["status"] == "ok"


def test_p09_provider_custom_selection_persists_and_invokes_shared_core(clients, workflow_project, tmp_path):
    # A spaced symlink also proves invocation retains the venv, instead of resolving its interpreter.
    binary = tmp_path / "provider with spaces"
    binary.symlink_to(sys.executable)
    store = persistence.ProjectStore(workflow_project)
    store.save_ui({**store.load_ui(), "unrelated": "keep"})
    config_path = tmp_path / "config/icoda/config.json"
    persistence.UserConfig(editor="keep-editor", known_projects=["keep-project"]).save(config_path)
    client = clients(FAKE_BOOTSTRAP)
    opened = open_project(client, workflow_project, analyse=False)
    args = {"provider": "fixture", "model": "custom-fixture-id", "binary": str(binary), "trusted": True}
    result = client.ok("providers.select", args)
    assert result["modelRevision"] == opened["modelRevision"]
    provider = result["providers"][0]
    assert provider["binaryPath"] == str(binary) and provider["selectedModel"] == "custom-fixture-id"
    assert provider["available"] and not provider["authenticationConfigured"]  # Auth detection is advisory.
    assert store.load_ui() == {"unrelated": "keep", "provider": {k: args[k] for k in ("provider", "model", "binary")}}
    config = persistence.UserConfig.load(config_path)
    assert (config.provider, config.model, config.editor, config.known_projects) == (
        "fixture", "custom-fixture-id", "keep-editor", ["keep-project"])
    assert not (workflow_project / ".icoda/cache/provider-started").exists()
    client.close()
    reopened = clients(FAKE_BOOTSTRAP)
    open_project(reopened, workflow_project, analyse=False)
    assert reopened.ok("providers.list")["selection"] == result["selection"]
    job = reopened.ok("conversation.send", {"trusted": True, "unsavedDocuments": [], "message": "Explain run"})["workflow"]
    completed = wait_workflow(reopened, job["id"])
    assert completed["state"] == "completed", completed
    assert "Controlled conversation reply" in completed["result"]["summary"]
    other = tmp_path / "other"
    other.mkdir()
    reopened.ok("project.open", {"path": str(other)})
    inventory = reopened.ok("providers.list")
    assert inventory["selection"] == result["selection"]
    assert inventory["providers"][0]["binary"] == sys.executable  # Custom paths are project-local.


@pytest.mark.parametrize("patch,code", [
    ({"trusted": False}, "workspace_untrusted"), ({"trusted": "true"}, "workspace_untrusted"),
    ({"model": ""}, "invalid_params"), ({"model": "x\n"}, "invalid_params"),
    ({"model": "x" * 257}, "invalid_params"), ({"binary": "relative/provider"}, "invalid_params"),
    ({"binary": "x\0"}, "invalid_params"), ({"binary": " x"}, "invalid_params"),
    ({"binary": "x" * 4097}, "invalid_params"), ({"token": "forbidden"}, "invalid_params"),
    ({"provider": "unknown"}, "provider_failed"),
])
def test_p09_provider_selection_rejects_invalid_messages_without_writes(clients, project, tmp_path, patch, code):
    client = clients(FAKE_BOOTSTRAP)
    open_project(client, project, analyse=False)
    args = {"provider": "fixture", "model": "ok", "binary": sys.executable, "trusted": True, **patch}
    assert_error(client.request("providers.select", args), code)
    assert not (project / ".icoda/ui.json").exists()
    assert not (tmp_path / "config/icoda/config.json").exists()


def test_p09_provider_missing_and_failed_leave_source_and_graph_usable(clients, workflow_project, tmp_path):
    client = clients(FAKE_BOOTSTRAP)
    opened = open_project(client, workflow_project, analyse=False)
    store = persistence.ProjectStore(workflow_project)
    before = store.ui_path.read_bytes()
    missing = str(tmp_path / "missing-provider")
    response = client.request("providers.select", {"provider": "fixture", "model": "ok", "binary": missing, "trusted": True})
    details = assert_error(response, "provider_failed")
    assert details["provider"] == "fixture" and details["binary"] == missing
    assert "Controlled fixture" in response["error"]["message"]
    assert store.ui_path.read_bytes() == before
    client.ok("providers.select", {"provider": "fixture", "model": "fail", "binary": sys.executable, "trusted": True})
    job = client.ok("conversation.send", {"trusted": True, "unsavedDocuments": [], "message": "Fail safely"})["workflow"]
    failed = wait_workflow(client, job["id"])
    assert failed["state"] == "failed" and failed["error"]["code"] == "provider_failed"
    store.save_ui({"provider": {"provider": "fixture", "model": "ok", "binary": missing}})
    assert not client.ok("providers.list")["providers"][0]["available"]
    response = client.request("conversation.send", {"trusted": True, "unsavedDocuments": [], "message": "Missing"})
    assert_error(response, "provider_unavailable")
    assert "Controlled fixture" in response["error"]["message"]
    assert client.ok("view.get", {"view": "call"})["nodes"]
    assert client.ok("source.resolve", {"sourceRootId": opened["sourceRootId"], "file": "src/main.py"})["path"] == str(workflow_project / "src/main.py")


def test_p09_provider_selection_guards_identity_busy_and_remembers_models(clients, workflow_project):
    bootstrap = FAKE_BOOTSTRAP.replace("from icoda_core.service import main; main()", """
from dataclasses import replace
from icoda_core import agent
fixture = agent.load_providers()[0]
agent.load_providers = lambda: [fixture, replace(fixture, id='second'), replace(fixture, id='disabled', enabled=False)]
from icoda_core.service import main
main()
""")
    client = clients(bootstrap)
    open_project(client, workflow_project, analyse=False)
    args = {"provider": "fixture", "model": "custom", "binary": sys.executable, "trusted": True}
    for context, code in [({"sessionId": "old"}, "invalid_session"), ({"modelRevision": 999}, "stale_revision"),
                          ({"targetId": "old"}, "stale_target")]:
        assert_error(client.request("providers.select", args, **context), code)
    assert_error(client.request("providers.select", {**args, "provider": "disabled"}), "provider_failed")
    client.ok("providers.select", args)
    client.ok("providers.select", {**args, "provider": "second", "model": "other"})
    inventory = client.ok("providers.list")
    assert inventory["providers"][0]["selectedModel"] == "custom"
    identifier = start_workflow(client, model="slow")
    wait_provider(workflow_project)
    assert_error(client.request("providers.select", args), "workflow_busy")
    client.ok("workflow.cancel", {"trusted": True, "workflowId": identifier})
    assert wait_workflow(client, identifier)["state"] == "cancelled"


def test_p09_unauthenticated_provider_keeps_existing_cli_diagnosis(clients, workflow_project):
    bootstrap = FAKE_BOOTSTRAP.replace("from icoda_core.service import main; main()", """
from dataclasses import replace
from icoda_core import agent
fixture = agent.load_providers()[0]
fixture = replace(fixture, invocation=('{binary}', '-c', "import sys; print('not logged in', file=sys.stderr); sys.exit(1)"),
                  login_hint='Use the controlled fixture login')
agent.load_providers = lambda: [fixture]
from icoda_core.service import main
main()
""")
    client = clients(bootstrap)
    open_project(client, workflow_project, analyse=False)
    inventory = client.ok("providers.select", {"provider": "fixture", "binary": sys.executable,
                                                "model": "ok", "trusted": True})
    assert inventory["providers"][0]["loginHint"] == "Use the controlled fixture login"
    job = client.ok("conversation.send", {"trusted": True, "unsavedDocuments": [], "message": "Authentication fixture"})["workflow"]
    error = wait_workflow(client, job["id"])["error"]
    assert error["code"] == "provider_failed"
    assert error["details"]["diagnosis"]["code"] == "authentication"
    assert "not logged in" in error["details"]["diagnosis"]["detail"]
    assert "not retried" in error["details"]["diagnosis"]["next_step"]
    assert "Open CLI" in error["details"]["diagnosis"]["next_step"]
    assert client.ok("view.get", {"view": "call"})["nodes"]


@pytest.mark.parametrize("view,state", [
    ("call", {"root": "python:program:B", "depth": 5, "callers": True, "filter": "leaf",
              "viewport": {"x": -24, "y": 31, "scale": 1.4}}),
    ("class", {"clusterId": None, "cameras": [{"clusterId": None, "viewport": {"x": 3, "y": 7, "scale": 0.8}}]}),
    ("mindmap", {"viewport": {"x": -88, "y": 20, "scale": 1.8}}),
])
def test_p11_diagram_state_survives_restart_without_changing_history(clients, project, view, state):
    client = clients()
    open_project(client, project)
    store = persistence.ProjectStore(project)
    ui = {"provider": {"provider": "codex", "binary": "missing-provider", "model": "saved-model"},
          "unrelated": {"keep": True}}
    store.save_ui(ui)
    before = store.state_path.read_bytes(), store.model_path.read_bytes()
    assert client.ok("view.state.set", {"view": view, "state": state})["state"] == state
    client.close()
    restarted = clients()
    opened = open_project(restarted, project, analyse=False)
    assert opened["ui"]["provider"] == ui["provider"]
    assert restarted.ok("view.state.get", {"view": view})["state"] == state
    assert store.load_ui()["unrelated"] == ui["unrelated"]
    assert before == (store.state_path.read_bytes(), store.model_path.read_bytes())
    assert not store.steps_path.exists()


@pytest.mark.parametrize("view,state", [
    ("call", {"root": None, "depth": 4, "callers": True, "filter": "main", "viewport": None}),
    ("class", {"clusterId": None, "cameras": [{"clusterId": None, "viewport": {"x": 7, "y": 9, "scale": 1}}]}),
    ("mindmap", {"viewport": {"x": 7, "y": 9, "scale": 1}}),
])
def test_p11_diagram_state_scopes_targets_and_rejects_stale_writes(clients, target_project, view, state):
    client = clients()
    open_project(client, target_project, analyse=False)
    client.ok("target.select", {"targetId": None})
    default = client.ok("view.state.get", {"view": view})["state"]
    client.ok("view.state.set", {"view": view, "state": state})
    target = next(item for item in client.ok("targets.list")["targets"] if item["id"] is not None)
    client.ok("target.select", {"targetId": target["id"]})
    assert client.ok("view.state.get", {"view": view})["state"] == default
    before = persistence.ProjectStore(target_project).ui_path.read_bytes()
    for context, code in [({"sessionId": "old"}, "invalid_session"), ({"modelRevision": 999}, "stale_revision"),
                          ({"targetId": None}, "stale_target")]:
        assert_error(client.request("view.state.set", {"view": view, "state": state}, **context), code)
    assert persistence.ProjectStore(target_project).ui_path.read_bytes() == before
    client.ok("target.select", {"targetId": None})
    assert client.ok("view.state.get", {"view": view})["state"] == state


def test_p11_invalid_and_obsolete_diagram_state_preserves_saved_bytes(clients, project):
    client = clients()
    open_project(client, project)
    store = persistence.ProjectStore(project)
    state = {"root": None, "depth": 3, "callers": False, "filter": "", "viewport": None}
    client.ok("view.state.set", {"view": "call", "state": state})
    before = store.ui_path.read_bytes()
    for field, value in [("depth", True), ("depth", 13), ("callers", 1), ("root", "x\0"),
                         ("filter", "x" * 257), ("viewport", {"x": 0, "y": 0, "scale": 0}), ("extra", 1)]:
        assert_error(client.request("view.state.set", {"view": "call", "state": {**state, field: value}}), "invalid_params")
    assert store.ui_path.read_bytes() == before
    client.ok("view.state.set", {"view": "call", "state": {**state, "root": "removed"}})
    before = store.ui_path.read_bytes()
    assert client.ok("view.state.get", {"view": "call"})["state"]["root"] is None
    assert store.ui_path.read_bytes() == before
    ui = store.load_ui()
    next(iter(ui["vscodeCallViews"].values()))["depth"] = "broken"
    store.save_ui(ui)
    before = store.ui_path.read_bytes()
    assert_error(client.request("view.state.get", {"view": "call"}), "view_state_invalid")
    assert store.ui_path.read_bytes() == before
    assert client.ok("view.get", {"view": "call"})["nodes"]
    ui["vscodeCallViews"] = "invalid mapping"
    store.save_ui(ui)
    before = store.ui_path.read_bytes()
    assert_error(client.request("view.state.get", {"view": "call"}), "view_state_invalid")
    assert_error(client.request("view.state.set", {"view": "call", "state": state}), "view_state_invalid")
    assert store.ui_path.read_bytes() == before


@pytest.mark.parametrize("newline,bom", [("\n", b""), ("\r\n", b""), ("\r\n", b"\xef\xbb\xbf")])
def test_p11_reopen_unchanged_analysis_keeps_raw_byte_hash_fresh(clients, project, newline, bom):
    raw = bom + SOURCE.replace("\n", newline).encode("utf-8")
    path = project / "program.py"
    path.write_bytes(raw)
    client = clients()
    assert not open_project(client, project)["model"]["stale"]
    store = persistence.ProjectStore(project)
    assert store.load_model().files["program.py"].content_hash == hashlib.sha1(raw).hexdigest()
    before = store.model_path.read_bytes(), store.state_path.read_bytes()
    client.close()
    reopened = clients()
    snapshot = open_project(reopened, project, analyse=False)
    assert snapshot["model"]["entities"]
    assert not snapshot["model"]["stale"]
    assert not reopened.ok("view.get", {"view": "call"})["stale"]
    assert path.read_bytes() == raw
    assert before == (store.model_path.read_bytes(), store.state_path.read_bytes())


@pytest.mark.parametrize("change", ["edit", "remove"])
def test_p11_reopen_reports_stale_cache_and_explicit_analysis_recovers(clients, project, change):
    client = clients()
    open_project(client, project)
    store = persistence.ProjectStore(project)
    before = store.model_path.read_bytes(), store.state_path.read_bytes()
    client.close()
    path = project / "program.py"
    if change == "edit":
        path.write_text(SOURCE + '\n# changed while closed\n', encoding="utf-8")
    else:
        path.unlink()
    reopened = clients()
    snapshot = open_project(reopened, project, analyse=False)
    assert snapshot["model"]["stale"]
    assert "Analyse Project" in snapshot["model"]["stale_reason"]
    assert snapshot["model"]["entities"]
    assert before == (store.model_path.read_bytes(), store.state_path.read_bytes())
    assert reopened.ok("view.get", {"view": "call"})["stale"]
    if change == "remove":
        path.write_text(SOURCE, encoding="utf-8")  # User restores the missing source before refreshing.
    assert not reopened.ok("project.analyse")["model"]["stale"]


def test_p11_corrupt_state_keeps_interrupted_work_and_history(clients, project):
    store = persistence.ProjectStore(project)
    store.ensure()
    store.state_path.write_text('{broken', encoding="utf-8")
    store.steps_path.write_text('{"number": 1, "phase": "architecture", "decision": "rejected"}\n', encoding="utf-8")
    work = store.dir / "worktree" / "draft.py"
    work.parent.mkdir()
    work.write_text("# precious interrupted work\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in (store.state_path, store.steps_path, work)}
    client = clients()
    client.ok("initialize", {"protocolVersion": 1})
    error = client.request("project.open", {"path": str(project)})
    assert_error(error, "project_open_failed")
    assert "refusing to replace" in error["error"]["message"]
    assert before == {path: path.read_bytes() for path in before}
