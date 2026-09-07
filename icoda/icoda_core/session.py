"""Opening a project end to end, without any GUI: folder, configuration, libclang, parse, clusters, layout."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from icoda_core import analysis, clusters, persistence, toolchain, views
from icoda_core.model import DerivedModel


@dataclass
class OpenedProject:
    """Everything the window needs after a project was opened or reloaded."""

    root: Path
    model: DerivedModel
    clustering: clusters.Clustering
    layout: views.FileViewLayout
    libclang: toolchain.Loaded | None
    messages: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"{len(self.model.files)} files", f"{len(self.model.entities)} entities",
                 f"{len(self.model.edges)} relations", f"{len(self.clustering.clusters)} clusters"]
        if self.model.stale:
            parts.append(f"STALE: {self.model.stale_reason}")
        return ", ".join(parts)


def choose_libclang(config: persistence.UserConfig) -> toolchain.Loaded | None:
    """The configured library if it still exists, else the first candidate; None when nothing loads."""
    paths = [config.libclang] if config.libclang and Path(config.libclang).exists() else []
    paths += [c.path for c in toolchain.candidates() if c.path not in paths]
    for path in paths:
        try:
            return toolchain.load(path)
        except Exception as exc:  # noqa: BLE001  (a candidate that does not load is skipped, and logged)
            log_event(f"libclang candidate {path} rejected: {exc!r}")
            continue
    return None


LOG_NAME = "icoda.log"


def log_event(message: str, root: Path | None = None) -> None:
    """Append a line to the project's ``.icoda/icoda.log`` (or the user config folder before a project is open)."""
    target = (persistence.ProjectStore(root).dir if root else persistence.config_path().parent) / LOG_NAME
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')} {message}\n")
    except OSError:
        pass


def open_project(root: Path, config: persistence.UserConfig, width: float = 1600.0,
                 height: float = 1000.0) -> OpenedProject:
    """Parse (from cache where possible), cluster and lay out the project under ``root``."""
    root = root.resolve()
    store = persistence.ProjectStore(root)
    store.ensure()
    config.remember_project(root)
    loaded = choose_libclang(config)
    messages: list[str] = []
    model = _derive_model(root, store, loaded, messages)
    clustering = clusters.cluster_files(model, store.load_layout())
    layout = views.layout_file_view(model, clustering, width, height)
    return OpenedProject(root, model, clustering, layout, loaded, messages)


def _derive_model(root: Path, store: persistence.ProjectStore, loaded: toolchain.Loaded | None,
                  messages: list[str]) -> DerivedModel:
    previous = store.load_model()
    commands = analysis.load_compile_commands(root)
    if loaded is None:
        messages.append("no libclang found: showing the last derived model" if previous else "no libclang found")
        return previous or DerivedModel(str(root))
    if not commands:
        messages.append("no compile_commands.json found: build the project once (build.sh) to analyse it")
        return previous or DerivedModel(str(root), loaded.version)
    resource = {c.compiler: r for c in commands if (r := toolchain.resource_dir(c.compiler))}
    model = analysis.parse_project(root, commands, resource_dirs=resource, cache_dir=store.cache_dir,
                                   previous=previous, libclang_version=loaded.version)
    if not model.stale:
        store.save_model(model)
    return model


def editor_command(path: Path, line: int, editor: str = "") -> list[str]:
    """How to open ``path`` at ``line``: the configured editor template, VS Code when on PATH, else the OS opener."""
    if editor:
        template = editor if "{file}" in editor else editor + " {file}"
        return [part.format(file=str(path), line=line) for part in template.split()]
    if shutil.which("code"):
        return ["code", "--goto", f"{path}:{line}"]
    if sys.platform == "darwin":
        return ["open", str(path)]
    if sys.platform == "win32":
        return ["cmd", "/c", "start", "", str(path)]
    return ["xdg-open", str(path)]


def open_in_editor(path: Path, line: int = 1, editor: str = "") -> bool:
    try:
        subprocess.Popen(editor_command(path, line, editor), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env=dict(os.environ))
        return True
    except OSError:
        return False
