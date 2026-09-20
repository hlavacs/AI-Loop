"""Entry points and CMake executable targets, resolved using the CMake file API."""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from icoda_core import analysis, process, steps
from icoda_core.model import DerivedModel, Kind


@dataclass(frozen=True)
class Target:
    name: str
    configuration: str
    build_dir: Path
    artifact: Path
    sources: frozenset[str]


@dataclass(frozen=True)
class Entry:
    usr: str
    file: str
    line: int
    target: Target | None = None

    @property
    def key(self) -> list[str]:
        return [self.file, self.target.name if self.target else "",
                self.target.configuration if self.target else ""]

    @property
    def label(self) -> str:
        if self.target:
            config = f" [{self.target.configuration}]" if self.target.configuration else ""
            return f"{self.target.name}{config} — {self.file}:{self.line}"
        return f"{self.file}:{self.line} — main"


@dataclass(frozen=True)
class Outcome:
    entries: tuple[Entry, ...]
    selected: Entry | None
    output: str
    message: str


def build_directory(root: Path) -> Path | None:
    """Use the analysed build tree; verify its source root before reconfiguring it."""
    database = analysis.find_compile_commands(root)
    candidates = [database.parent] if database else []
    if database:
        for command in analysis.load_compile_commands(database):
            directory = Path(command.directory)
            candidates.extend((directory, *directory.parents))
    candidates.extend((root / "build/debug", root / "build", *sorted(root.glob("build/*")), root))
    for directory in dict.fromkeys(candidates):
        cache = directory / "CMakeCache.txt"
        if cache.is_file():
            for line in cache.read_text(encoding="utf-8").splitlines():
                if line.startswith("CMAKE_HOME_DIRECTORY:INTERNAL="):
                    if Path(line.split("=", 1)[1]).resolve() == root.resolve():
                        return directory.resolve()
                    break
    return None


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
        raise ValueError("The CMake target metadata belongs to another project. Refresh examples to rebuild it.")
    targets = []
    for config in model["configurations"]:
        for reference in config.get("targets", []):
            target = _json(reply / reference["jsonFile"])
            if target["type"] != "EXECUTABLE" or not target.get("artifacts"):
                continue
            sources = frozenset(str((source_root / source["path"]).resolve())
                                for source in target.get("sources", []))
            artifact = next((item["path"] for item in target["artifacts"]
                             if Path(item["path"]).name == target.get("nameOnDisk")),
                            target["artifacts"][0]["path"])
            targets.append(Target(target["name"], config["name"], directory,
                                  (directory / artifact).resolve(), sources))
    return tuple(targets)


def entries(model: DerivedModel, targets: tuple[Target, ...] = ()) -> tuple[Entry, ...]:
    result = []
    for entity in model.entities.values():
        if entity.kind != Kind.FUNCTION or entity.name != "main" or not entity.is_definition:
            continue
        # C++ namespace::main is an ordinary function, not an entry point.
        if Path(entity.file).suffix != ".py" and entity.qualified_name != "main":
            continue
        matches: list[Target | None] = [
            target for target in targets if str((Path(model.root) / entity.file).resolve()) in target.sources]
        for target in matches or [None]:
            result.append(Entry(entity.usr, entity.file, entity.line, target))
    return tuple(sorted(result, key=lambda item: (not item.file.startswith("examples/"), item.file,
                                                 item.target.name if item.target else "",
                                                 item.target.configuration if item.target else "")))


def choose(choices: tuple[Entry, ...], key: Any) -> Entry | None:
    exact = next((entry for entry in choices if entry.key == key), None)
    same_file = next((entry for entry in choices if isinstance(key, list) and key and entry.file == key[0]), None)
    return exact or same_file or (choices[0] if choices else None)


def operate(root: Path, model: DerivedModel, selected: Entry | None, action: str,
            cancelled: Callable[[], bool]) -> Outcome:
    """Refresh targets, or build/run exactly one target. Never guess when several targets share a main."""
    output: list[str] = []

    def run(command: list[str], stage: str, timeout: float = 600) -> None:
        if cancelled():
            raise steps.StepCancelled()
        result = process.run_bounded(command, cwd=root, timeout=timeout, env=steps.build_environment(root))
        output.append("$ " + shlex.join(command) + "\n" + result.stdout + result.stderr)
        if result.cancelled or cancelled():
            raise steps.StepCancelled()
        if not result.ok:
            reason = "timed out" if result.timed_out else f"exit {result.returncode}"
            raise steps.StepError(f"{stage} failed ({reason}).\n" + "\n".join(output))

    directory = build_directory(root)
    if directory is None:
        raise steps.StepError("Configure/build this CMake project first with Project → Build, then refresh examples.")
    query = directory / ".cmake/api/v1/query/client-icoda/codemodel-v2"
    query.parent.mkdir(parents=True, exist_ok=True)
    query.touch()
    run(["cmake", "-S", str(root), "-B", str(directory)], "CMake configuration")
    choices = entries(model, read_targets(root, directory))
    if action == "refresh":
        return Outcome(choices, choose(choices, selected.key if selected else None), "\n".join(output),
                       "Example / executable list refreshed")
    assert selected is not None
    matches = [entry for entry in choices if entry.file == selected.file and entry.target is not None]
    exact = next((entry for entry in matches if entry.key == selected.key), None)
    chosen = exact or (matches[0] if len(matches) == 1 and selected.target is None else None)
    if chosen is None:
        if matches:
            return Outcome(choices, None, "\n".join(output),
                           "Choose a CMake target/configuration for this main, then press Build or Run again")
        raise steps.StepError(f"No CMake executable target contains {selected.file}. "
                              "Add it to an add_executable target and refresh examples.")
    assert chosen.target is not None
    target = chosen.target
    command = ["cmake", "--build", str(target.build_dir), "--target", target.name]
    if target.configuration:
        command.extend(("--config", target.configuration))
    run(command, "Build")
    if action == "run":
        run([str(target.artifact)], f"Running {target.name}", timeout=3600)
    return Outcome(choices, chosen, "\n".join(output),
                   f"{target.name}: {'finished (exit 0)' if action == 'run' else 'build passed'}")
