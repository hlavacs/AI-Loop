"""Opening a project end to end, without any GUI: folder, configuration, libclang, parse, clusters, layout.

The libclang part runs in a child process (``python -m icoda_core.session <root>``) so that a crash inside
libclang cannot take the window down; the child writes the derived model to the project's cache and a
small JSON result to stdout, and the parent clusters and lays out the model.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from icoda_core import analysis, clusters, persistence, steplog, toolchain, views
from icoda_core.model import DerivedModel

LOG_NAME = "icoda.log"


@dataclass
class OpenedProject:
    """Everything the window needs after a project was opened or reloaded."""

    root: Path
    model: DerivedModel
    clustering: clusters.Clustering
    layout: views.FileViewLayout
    libclang: str | None
    messages: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"{len(self.model.files)} files", f"{len(self.model.entities)} entities",
                 f"{len(self.model.edges)} relations", f"{len(self.clustering.clusters)} clusters",
                 f"clustering: {self.clustering.algorithm}"]
        if self.model.stale:
            parts.append(f"STALE: {self.model.stale_reason}")
        return ", ".join(parts)


@dataclass
class AnalysisResult:
    """What the analysis (in-process or child process) reports back besides the cached model."""

    libclang: str | None
    libclang_path: str | None
    messages: list[str]


def log_event(message: str, root: Path | None = None) -> None:
    """Append a line to the project's ``.icoda/icoda.log`` (or the user config folder before a project is open)."""
    target = (persistence.ProjectStore(root).dir if root else persistence.config_path().parent) / LOG_NAME
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')} {message}\n")
    except OSError:
        pass


# --------------------------------------------------------------------------- analysis (child side)

def choose_libclang(config: persistence.UserConfig, compilers: list[str] | None = None) -> toolchain.Loaded | None:
    """The library beside the project's compiler, else the configured one, else the first candidate."""
    detected = [toolchain.Candidate(p, "compiler") for c in compilers or []
                if (p := toolchain.library_beside(c))]
    if config.libclang and Path(config.libclang).exists():
        detected.append(toolchain.Candidate(config.libclang, "configured"))
    detected.extend(toolchain.candidates())
    selection = toolchain.select_candidate(detected, config.preferred_libclang)
    paths = [candidate.path for candidate in selection.candidates]
    if selection.active is not None:
        paths.remove(selection.active.path)
        paths.insert(0, selection.active.path)
    for path in paths:
        try:
            return toolchain.load(path)
        except Exception as exc:  # noqa: BLE001  (a candidate that does not load is skipped, and logged)
            log_event(f"libclang candidate {path} rejected: {exc!r}")
            continue
    return None


def analyse(root: Path, config: persistence.UserConfig) -> AnalysisResult:
    """Parse the project with libclang and save the derived model to the project cache."""
    root = root.resolve()
    store = persistence.ProjectStore(root)
    store.ensure()
    commands = analysis.load_compile_commands(root)
    compilers = sorted({c.compiler for c in commands})
    python = analysis.detect_language(root) == analysis.PYTHON_LANGUAGE
    loaded = None if python else choose_libclang(config, compilers)
    frontend = "Python ast" if python else loaded.describe() if loaded else "no libclang"
    log_event(f"analysing with {frontend}; compilers {compilers}", root)
    messages: list[str] = []
    model = _derive_model(root, store, loaded, commands, messages)
    store.save_model(model)
    return AnalysisResult(frontend if python or loaded else None, loaded.path if loaded else None, messages)


def _derive_model(root: Path, store: persistence.ProjectStore, loaded: toolchain.Loaded | None,
                  commands: list[analysis.CompileCommand], messages: list[str]) -> DerivedModel:
    previous = store.load_model()
    if previous is not None:
        previous.stale = False
    if analysis.detect_language(root) == analysis.PYTHON_LANGUAGE:
        model = analysis.parse_project_for_root(root, commands)
        broken = [info for info in model.files.values() if info.errors]
        if broken:
            messages.append(f"{len(broken)} files with parse errors, first: "
                            f"{broken[0].path}: {broken[0].errors[0]}")
        return model
    if loaded is None:
        messages.append("no libclang found: showing the last derived model" if previous else "no libclang found")
        return previous or DerivedModel(str(root))
    if not commands:
        messages.append("No compile_commands.json found. Press Build to prepare the project and analyse its sources.")
        return previous or DerivedModel(str(root), loaded.version)
    from icoda_core import windows_analysis

    commands = windows_analysis.prepare(commands, loaded, store.cache_dir,
                                        lambda message: log_event(message, root))
    resource = {c.compiler: r for c in commands if (r := toolchain.resource_dir(c.compiler))}
    version = f"{loaded.version}|{toolchain.default_sysroot() or ''}"
    model = analysis.parse_project_for_root(
        root, commands, resource_dirs=resource, cache_dir=store.cache_dir,
        previous=previous, libclang_version=version, sysroot=toolchain.default_sysroot(),
        apple=loaded.apple, notes=messages,
        progress=lambda unit: log_event(f"parsing {unit}", root))
    _report_errors(model, messages, root, loaded, resource)
    return model


def _report_errors(model: DerivedModel, messages: list[str], root: Path, loaded: toolchain.Loaded,
                   resource: dict[str, str]) -> None:
    broken = [info for info in model.files.values() if info.errors]
    if not broken:
        return
    messages.append(f"{len(broken)} files with parse errors, first: {broken[0].path}: {broken[0].errors[0]}")
    lines = [f"parse errors with {loaded.describe()}; resource dirs {resource}; sysroot {toolchain.default_sysroot()}"]
    lines += [f"  {info.path}: {error}" for info in broken for error in info.errors[:3]]
    log_event("\n".join(lines), root)


def main(argv: list[str]) -> int:
    """Child-process entry: analyse the project given as argument, print the result as JSON."""
    root = Path(argv[0])
    config = persistence.UserConfig.load(persistence.config_path())
    result = analyse(root, config)
    print(json.dumps({"libclang": result.libclang, "libclang_path": result.libclang_path,
                      "messages": result.messages}))
    return 0


# --------------------------------------------------------------------------- opening (parent side)

def analyse_in_child(root: Path, timeout: float = 1800.0) -> AnalysisResult:
    """Run :func:`analyse` in a child process; a crash becomes a message naming the signal and the last unit."""
    command = [sys.executable, "-m", "icoda_core.session", str(root)]
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent))
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False, env=env)
    except subprocess.TimeoutExpired:
        return AnalysisResult(None, None, [f"analysis did not finish within {int(timeout)} s"])
    if completed.returncode == 0 and completed.stdout.strip():
        data = json.loads(completed.stdout.strip().splitlines()[-1])
        return AnalysisResult(data.get("libclang"), data.get("libclang_path"), list(data.get("messages", [])))
    return AnalysisResult(None, None, [_crash_message(completed, root)])


def _crash_message(completed: subprocess.CompletedProcess[str], root: Path) -> str:
    last = _last_log_line(root)
    if completed.returncode < 0:
        return f"analysis crashed with signal {-completed.returncode} (last step: {last})"
    tail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "no error output"
    return f"analysis failed (exit {completed.returncode}): {tail} (last step: {last})"


def _last_log_line(root: Path) -> str:
    log = persistence.ProjectStore(root).dir / LOG_NAME
    try:
        lines = log.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "?"
    return lines[-1][:160] if lines else "?"


def open_project(root: Path, config: persistence.UserConfig, width: float = 1600.0, height: float = 1000.0,
                 in_process: bool = False) -> OpenedProject:
    """Analyse (in a child process unless ``in_process``), then cluster and lay out the project."""
    root = root.resolve()
    store = persistence.ProjectStore(root)
    store.ensure()
    worktree = store.dir / "worktree"
    try:
        store.load_state()
    except persistence.ProjectStateError as exc:
        if worktree.is_dir():
            raise persistence.ProjectStateError(
                f"{exc}; leftover proposal worktree preserved at {worktree}") from exc
        raise
    config.remember_project(root)
    result = analyse(root, config) if in_process else analyse_in_child(root)
    if result.libclang_path:
        config.libclang = result.libclang_path
    model = store.load_model() or DerivedModel(str(root))
    steplog.apply_statuses(model, steplog.StepLog(store.steps_path))
    clustering = clusters.cluster_files(model, store.load_layout())
    layout = views.layout_file_view(model, clustering, width, height)
    messages = list(result.messages)
    if worktree.is_dir():
        messages.append(f"leftover proposal worktree preserved at {worktree}")
    return OpenedProject(root, model, clustering, layout, result.libclang, messages)


# --------------------------------------------------------------------------- editor

def editor_command(path: Path, line: int, editor: str = "") -> list[str]:
    """How to open ``path`` at ``line``: the configured editor template, VS Code when on PATH, else the OS opener."""
    if editor:
        template = editor if "{file}" in editor else editor + " {file}"
        return [part.format(file=str(path), line=line) for part in template.split()]
    if shutil.which("code"):
        return ["code", "--goto", f"{path}:{line}"]
    return system_open_command(path)


def system_open_command(path: Path) -> list[str]:
    """Open ``path`` with the application the operating system associates with it."""
    if sys.platform == "darwin":
        return ["open", str(path)]
    if sys.platform == "win32":
        return ["cmd", "/c", "start", "", str(path)]
    return ["xdg-open", str(path)]


def open_in_editor(path: Path, line: int = 1, editor: str = "") -> bool:
    return _spawn(editor_command(path, line, editor))


def open_with_system(path: Path) -> bool:
    """Open a document or log file with the system's default application (not the code editor)."""
    return _spawn(system_open_command(path))


def _spawn(command: list[str]) -> bool:
    try:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dict(os.environ))
        return True
    except OSError:
        return False


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
