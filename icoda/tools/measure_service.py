"""Measure protocol-v1 round trips on disposable Python-source snapshots; JSON goes to stdout.

Run with the prepared ICODA Python. Redirect output to a system-temp file.
Project code is parsed, never executed; no provider, build, or network operation runs.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from queue import Queue

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from icoda_core.python_analysis import find_python_sources


class Client:
    """A sequential protocol client with bounded reads and EOF cleanup."""

    def __init__(self, temporary: Path, stderr):
        self.context = {}
        self.sequence = 0
        self.lines = Queue()
        env = dict(os.environ, XDG_CONFIG_HOME=str(temporary), APPDATA=str(temporary),
                   PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        self.process = subprocess.Popen([sys.executable, "-m", "icoda_core.service"], cwd=ROOT,
                                        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(b"")

    def request(self, method, params=None):
        self.sequence += 1
        frame = {**self.context, "id": self.sequence, "method": method, "params": params or {}}
        self.process.stdin.write(json.dumps(frame).encode("utf-8") + b"\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + 120
        while True:
            line = self.lines.get(timeout=max(0, deadline - time.monotonic()))
            if not line:
                raise RuntimeError("Backend exited before responding")
            response = json.loads(line)
            if "id" not in response:
                if response.get("method") == "protocol.error":
                    raise RuntimeError(response)
                continue
            if response["id"] != self.sequence or response["status"] != "ok":
                raise RuntimeError(response)
            result = response["result"]
            if "sessionId" in result:
                self.context = {key: result[key] for key in ("sessionId", "modelRevision", "targetId")}
            return result

    def close(self):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=10)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
            self.reader.join(timeout=5)
            self.process.stdout.close()
        if self.process.returncode:
            raise RuntimeError(f"Backend exited with code {self.process.returncode}")


def snapshot(source: Path, destination: Path) -> int:
    """Copy only AST inputs and the optional checked-in trace, never project state."""
    sources = find_python_sources(source)
    if not sources:
        raise ValueError(f"No Python sources in {source}")
    for path in sources:
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    if (source / "calls.tsv").is_file():
        shutil.copyfile(source / "calls.tsv", destination / "calls.tsv")
    return len(sources)


def timed(samples, name, operation):
    begin = time.perf_counter()
    result = operation()
    samples[name].append((time.perf_counter() - begin) * 1000)
    return result


def trace_path(root: Path, model, steps: int) -> tuple[Path, str]:
    """Use the existing trace or generate resolved, alternating complete leaf calls."""
    path = root / "calls.tsv"
    if path.is_file():
        return path, "checked-in synthetic calls.tsv"
    functions = sorted((e for e in model["entities"] if e["kind"] in ("function", "method")),
                       key=lambda entity: entity["usr"])[:32]
    if len(functions) < 2:
        raise ValueError("Measurement requires at least two callable entities")
    lines = ["# icoda-call-trace-v1"]
    for index in range(steps):
        name = functions[index % len(functions)]["qualified_name"]
        for offset, kind in enumerate(("E", "X")):
            lines.append(f"{kind}\t{index * 2 + offset}\tbenchmark\t0\t{name}\t\t{name}\t")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, "synthetic alternating complete leaf calls (up to 32 functions)"


def measure_views(client, model, samples):
    """Use Whole Project, a stable high-fanout call root, and default overview sizes."""
    client.request("target.select", {"targetId": None})
    calls = Counter(edge["source"] for edge in model["edges"] if edge["kind"] == "calls")
    functions = [e["usr"] for e in model["entities"] if e["kind"] in ("function", "method")]
    root = min(functions, key=lambda usr: (-calls[usr], usr))
    shapes = {}
    for view in ("call", "file", "class"):
        params = {"view": view, **({"root": root, "depth": 3} if view == "call" else {})}
        result = timed(samples, f"view.get.{view}", lambda params=params: client.request("view.get", params))
        shapes[view] = {"nodes": len(result["nodes"]), "edges": len(result["edges"]),
                        "overview": result.get("overview", False)}
    return {"callRoot": root, "views": shapes}


def measure_trace(client, root, model, steps, samples):
    path, description = trace_path(root, model, steps)
    state = timed(samples, "trace.load", lambda: client.request("trace.load", {"path": str(path)}))
    if not state["total"] or state["resolvedCalls"] != state["recordedCalls"]:
        raise RuntimeError("Measurement trace must resolve every call")
    counts = {key: state[key] for key in ("events", "recordedCalls", "resolvedCalls", "total")}
    params = {"traceId": state["traceId"], "action": "into"}
    for _ in range(steps):
        if not state["availability"]["into"]:
            state = client.request("trace.reset", {"traceId": state["traceId"]})
        position = state["position"]
        state = timed(samples, "trace.step", lambda: client.request("trace.step", params))
        if state["position"] != position + 1 or not state["currentEntityUsr"]:
            raise RuntimeError("trace.step did not select the next call")
    return {"description": description, **counts}


def measure_run(source, steps, samples):
    with tempfile.TemporaryDirectory(prefix="icoda-perf-") as temporary, tempfile.TemporaryFile() as stderr:
        root = Path(temporary) / "project"
        files = snapshot(source, root)
        begin = time.perf_counter()
        client = Client(Path(temporary) / "config", stderr)
        try:
            initialized = client.request("initialize", {"protocolVersion": 1})
            if initialized["protocolVersion"] != 1:
                raise RuntimeError("Expected protocol v1")
            samples["startup.initialize"].append((time.perf_counter() - begin) * 1000)
            opened = timed(samples, "project.open", lambda: client.request("project.open", {"path": str(root)}))
            if opened["cached"]:
                raise RuntimeError("Expected a fresh project snapshot")
            analysed = timed(samples, "project.analyse", lambda: client.request("project.analyse"))
            model = analysed["model"]
            shapes = measure_views(client, model, samples)
            trace = measure_trace(client, root, model, steps, samples)
            return {"files": files, "entities": len(model["entities"]), "edges": len(model["edges"]),
                    "trace": trace, **shapes}
        finally:
            client.close()


def summarize(values):
    ordered = sorted(values)
    return {"count": len(values), "medianMs": statistics.median(values),
            "p95Ms": ordered[math.ceil(len(values) * 0.95) - 1], "maxMs": max(values), "samplesMs": values}


def measure_project(source, runs, steps):
    samples = defaultdict(list)
    observations = [measure_run(source, steps, samples) for _ in range(runs)]
    if any(item != observations[0] for item in observations):
        raise RuntimeError("Project/trace/view counts changed between runs")
    return {"project": source.relative_to(ROOT).as_posix() if source.is_relative_to(ROOT) else source.name,
            **observations[0], "timings": {name: summarize(values) for name, values in samples.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, action="append", help="Repeat for Python source roots; defaults to both fixtures and ICODA")
    parser.add_argument("--runs", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--steps", type=int, choices=range(10, 2001), default=240, metavar="10..2000")
    args = parser.parse_args()
    projects = args.project or [ROOT / "tests/fixtures", ROOT / "vscode/src/test/fixtures/python", ROOT]
    report = {"protocolVersion": 1, "python": platform.python_version(), "os": platform.platform(),
              "architecture": platform.machine(), "runs": args.runs, "stepsPerRun": args.steps,
              "projects": [measure_project(path.resolve(), args.runs, args.steps) for path in projects]}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
