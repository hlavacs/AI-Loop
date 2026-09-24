"""Entry points and CMake executable/library targets, resolved using the CMake file API."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from icoda_core import analysis, cmake, instrumentation, process, steps
from icoda_core.cmake import build_directory
from icoda_core.model import DerivedModel, Kind


@dataclass(frozen=True)
class Target:
    name: str
    configuration: str
    build_dir: Path
    artifact: Path | None
    sources: frozenset[str]
    dependency_sources: frozenset[str] = frozenset()
    kind: str = "EXECUTABLE"

    @property
    def is_library(self) -> bool:
        return self.kind.endswith("_LIBRARY")


@dataclass(frozen=True)
class Entry:
    usr: str
    file: str
    line: int
    target: Target | None = None

    @property
    def is_library(self) -> bool:
        return self.target is not None and self.target.is_library

    @property
    def key(self) -> list[str]:
        return [self.file, self.target.name if self.target else "",
                self.target.configuration if self.target else ""]

    @property
    def label(self) -> str:
        if self.target:
            config = f" [{self.target.configuration}]" if self.target.configuration else ""
            if self.is_library:
                kind = self.target.kind.removesuffix("_LIBRARY").lower()
                return f"{self.target.name}{config} — {kind} library"
            return f"{self.target.name}{config} — {self.file}:{self.line}"
        return f"{self.file}:{self.line} — main"


@dataclass(frozen=True)
class Outcome:
    entries: tuple[Entry, ...]
    selected: Entry | None
    output: str
    message: str
    trace_file: Path | None = None


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def read_targets(root: Path, directory: Path | None = None) -> tuple[Target, ...]:
    directory = directory or build_directory(root)
    if directory is None:
        return ()
    reply = directory / ".cmake/api/v1/reply"
    indexes = sorted(reply.glob("index-*.json"))
    if not indexes:
        return ()
    index = _json(indexes[-1])
    reference = next((obj for obj in index.get("objects", [])
                      if obj.get("kind") == "codemodel" and obj.get("version", {}).get("major") == 2), None)
    if reference is None:
        return ()
    model = _json(reply / reference["jsonFile"])
    source_root = Path(model["paths"]["source"]).resolve()
    if source_root != root.resolve():
        raise ValueError("The CMake target metadata belongs to another project. Refresh targets to rebuild it.")
    targets = []
    for config in model["configurations"]:
        by_id = {reference["id"]: _json(reply / reference["jsonFile"])
                 for reference in config.get("targets", [])}
        for target in by_id.values():
            if target["type"] != "EXECUTABLE" and not target["type"].endswith("_LIBRARY"):
                continue
            sources = frozenset(str((source_root / source["path"]).resolve())
                                for source in target.get("sources", []))
            artifacts = target.get("artifacts", [])
            artifact = next((item["path"] for item in artifacts
                             if Path(item["path"]).name == target.get("nameOnDisk")),
                            artifacts[0]["path"] if artifacts else None)
            targets.append(Target(target["name"], config["name"], directory,
                                  (directory / artifact).resolve() if artifact else None, sources,
                                  _library_sources(target, by_id, source_root), target["type"]))
    return tuple(targets)


def _library_sources(target: dict[str, Any], by_id: dict[str, dict[str, Any]], root: Path) -> frozenset[str]:
    """Collect library dependencies, excluding executables used only for build ordering."""
    sources: set[str] = set()
    seen: set[str] = set()
    pending = [item["id"] for item in target.get("dependencies", [])]
    while pending:
        identifier = pending.pop()
        if identifier in seen:
            continue
        seen.add(identifier)
        dependency = by_id.get(identifier, {})
        if not dependency.get("type", "").endswith("_LIBRARY"):
            continue
        sources.update(str((root / source["path"]).resolve()) for source in dependency.get("sources", []))
        pending.extend(item["id"] for item in dependency.get("dependencies", []))
    return frozenset(sources)


def entries(model: DerivedModel, targets: tuple[Target, ...] = ()) -> tuple[Entry, ...]:
    result = []
    for entity in model.entities.values():
        if entity.kind != Kind.FUNCTION or entity.name != "main" or not entity.is_definition:
            continue
        # C++ namespace::main is an ordinary function, not an entry point.
        if Path(entity.file).suffix != ".py" and entity.qualified_name != "main":
            continue
        matches: list[Target | None] = [
            target for target in targets if not target.is_library
            and str((Path(model.root) / entity.file).resolve()) in target.sources]
        for target in matches or [None]:
            result.append(Entry(entity.usr, entity.file, entity.line, target))
    # A library is selected by target identity, independent of any particular API function or source file.
    result.extend(Entry("", "", 0, target) for target in targets if target.is_library)
    return tuple(sorted(result, key=lambda item: (not item.file.startswith("examples/"), item.file,
                                                 item.target.name if item.target else "",
                                                 item.target.configuration if item.target else "")))


def choose(choices: tuple[Entry, ...], key: Any) -> Entry | None:
    exact = next((entry for entry in choices if entry.key == key), None)
    same_file = [entry for entry in choices if isinstance(key, list) and key and key[0]
                 and entry.file == key[0]]
    return exact or (same_file[0] if len(same_file) == 1 else choices[0] if len(choices) == 1 else None)


def scope_model(model: DerivedModel, selected: Entry | None, *, root: Path | None = None) -> DerivedModel:
    """Project one executable or library and its dependencies without changing the analysis model."""
    files: set[str] = set()
    if selected is not None and (selected.is_library or selected.usr in model.entities):
        base = root or Path(model.root)
        sources = selected.target.sources | selected.target.dependency_sources if selected.target else frozenset()
        files = {file for file in model.files if str((base / file).resolve()) in sources}
        if selected.file:
            files.add(selected.file)
        allowed = set(model.files)
        if selected.target:
            allowed = files | {file for file in model.files if Path(file).suffix in analysis.HEADER_SUFFIXES}
        allowed -= {entry.file for entry in entries(model) if entry.file != selected.file}
        dependencies: dict[str, set[str]] = defaultdict(set)
        for source, target, _kind in model.file_edges():
            dependencies[source].add(target)
        for entity in model.entities.values():
            if entity.declaration_file:
                dependencies[entity.declaration_file].add(entity.file)
                dependencies[entity.file].add(entity.declaration_file)
        pending = list(files)
        files &= allowed
        while pending:
            for target in dependencies[pending.pop()] & allowed - files:
                files.add(target)
                pending.append(target)
    entities = {usr: entity for usr, entity in model.entities.items() if entity.file in files}
    endpoints = files | entities.keys()
    edges = [edge for edge in model.edges if edge.source in endpoints
             and (edge.target in endpoints or edge.target.startswith("external:"))
             and (not edge.file or edge.file in files)]
    externals = {edge.target.removeprefix("external:") for edge in edges if edge.target.startswith("external:")}
    return replace(model, files={file: info for file, info in model.files.items() if file in files},
                   entities=entities, edges=edges,
                   externals={name: item for name, item in model.externals.items() if name in externals})


def operate(root: Path, model: DerivedModel, selected: Entry | None, action: str,
            cancelled: Callable[[], bool],
            instrumentation_options: instrumentation.InstrumentationOptions | None = None) -> Outcome:
    """Refresh, build, or run one target, optionally in an isolated instrumented Debug tree."""
    if action == "run" and selected is not None and selected.is_library:
        raise steps.StepError("A library has no executable to run. Use Build or select an executable.")
    output: list[str] = []
    environment = None
    instrumentation_files: instrumentation.InstrumentationFiles | None = None

    def run(command: list[str], stage: str, timeout: float = 600) -> None:
        if cancelled():
            raise steps.StepCancelled()
        result = process.run_bounded(command, cwd=root, timeout=timeout, env=environment)
        output.append("$ " + shlex.join(command) + "\n" + result.stdout + result.stderr)
        if result.cancelled or cancelled():
            raise steps.StepCancelled()
        if not result.ok:
            reason = "timed out" if result.timed_out else f"exit {result.returncode}"
            raise steps.StepError(f"{stage} failed ({reason}).\n" + "\n".join(output))

    if action == "refresh" and build_directory(root) is None:
        raise steps.StepError("Configure/build this CMake project first with Project → Build, then refresh targets.")
    try:
        if action != "refresh" and instrumentation_options is not None and instrumentation_options.enabled:
            directory, configure, environment, instrumentation_files = (
                cmake.instrumented_clang_configuration(root, instrumentation_options))
            environment = dict(environment)
            environment["PATH"] = str(directory) + os.pathsep + environment.get("PATH", "")
            loader_path = "PATH" if sys.platform == "win32" else (
                "DYLD_LIBRARY_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH")
            if loader_path != "PATH":
                environment[loader_path] = str(directory) + os.pathsep + environment.get(loader_path, "")
        else:
            directory, configure, environment = cmake.clang_configuration(root)
    except (RuntimeError, OSError, ValueError) as exc:
        raise steps.StepError(str(exc)) from exc
    run(configure, "CMake configuration")
    if action != "refresh":
        try:
            if instrumentation_files is not None:
                assert environment is not None
                cmake.verify_compiler(directory, environment["CXX"])
            else:
                cmake.verify_clang(directory)
        except RuntimeError as exc:
            raise steps.StepError(str(exc)) from exc
    choices = entries(model, read_targets(root, directory))
    if action == "refresh":
        return Outcome(choices, choose(choices, selected.key if selected else None), "\n".join(output),
                       "Executable / library target list refreshed")
    assert selected is not None
    matches = [entry for entry in choices if entry.file == selected.file and entry.target is not None]
    exact = next((entry for entry in matches if entry.key == selected.key), None)
    if exact is None and selected.target:
        exact = next((entry for entry in matches if entry.target and entry.target.name == selected.target.name), None)
    chosen = exact or (matches[0] if len(matches) == 1 and selected.target is None else None)
    if chosen is None:
        if matches:
            return Outcome(choices, None, "\n".join(output),
                           "Choose a CMake target/configuration, then press Build or Run again")
        if selected.target is not None and selected.is_library:
            raise steps.StepError(f"CMake library target {selected.target.name} is no longer available. "
                                  "Refresh targets and select a library again.")
        raise steps.StepError(f"No CMake executable target contains {selected.file}. "
                              "Add it to an add_executable target and refresh targets.")
    assert chosen.target is not None
    target = chosen.target
    if action == "run" and (target.is_library or target.artifact is None):
        raise steps.StepError("The selected target has no executable to run. Refresh targets and choose again.")
    command = [configure[0], "--build", str(target.build_dir), "--target", target.name]
    if target.configuration:
        command.extend(("--config", target.configuration))
    run(command, "Build")
    if action == "run":
        if instrumentation_files is not None and target.artifact is not None:
            runtime = instrumentation_files.build_directory / "icoda_call_trace_runtime.dll"
            deployed = target.artifact.parent / runtime.name
            if runtime.is_file() and runtime.resolve() != deployed.resolve():
                # Windows prefers a DLL beside the executable over the updated one on PATH.
                shutil.copy2(runtime, deployed)
        run([str(target.artifact)], f"Running {target.name}", timeout=3600)
    message = f"{target.name}: {'finished (exit 0)' if action == 'run' else 'build passed'}"
    if action == "run" and instrumentation_files is not None:
        message += f"; call trace: {instrumentation_files.trace_file}"
    trace_file = instrumentation_files.trace_file if action == "run" and instrumentation_files is not None else None
    return Outcome(choices, chosen, "\n".join(output), message, trace_file)
