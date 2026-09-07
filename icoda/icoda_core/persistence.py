"""The .icoda/ folder of a project and the user configuration."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from icoda_core.clusters import Layout
from icoda_core.model import DerivedModel

ICODA_DIR = ".icoda"
PROJECT_GITIGNORE = "cache/\nui.json\n"
MAX_KNOWN_PROJECTS = 10


@dataclass
class ProjectStore:
    """Paths and load/save helpers for one project's ``.icoda/`` folder."""

    root: Path

    @property
    def dir(self) -> Path:
        return self.root / ICODA_DIR

    @property
    def cache_dir(self) -> Path:
        return self.dir / "cache"

    @property
    def layout_path(self) -> Path:
        return self.dir / "layout.json"

    @property
    def ui_path(self) -> Path:
        return self.dir / "ui.json"

    @property
    def model_path(self) -> Path:
        return self.cache_dir / "model.json"

    @property
    def specification_path(self) -> Path:
        return self.dir / "specification.json"

    @property
    def steps_path(self) -> Path:
        return self.dir / "steps.jsonl"

    def ensure(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        gitignore = self.dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(PROJECT_GITIGNORE, encoding="utf-8")

    def load_layout(self) -> Layout:
        return Layout.from_dict(_read_json(self.layout_path) or {})

    def save_layout(self, layout: Layout) -> None:
        _write_json(self.layout_path, layout.to_dict())

    def load_ui(self) -> dict[str, Any]:
        return _read_json(self.ui_path) or {}

    def save_ui(self, state: Mapping[str, Any]) -> None:
        _write_json(self.ui_path, dict(state))

    def load_model(self) -> DerivedModel | None:
        return DerivedModel.load(self.model_path) if self.model_path.is_file() else None

    def save_model(self, model: DerivedModel) -> None:
        model.save(self.model_path)


@dataclass
class UserConfig:
    """ICODA's own settings: known projects, the libclang choice, the default binary and model, the editor."""

    known_projects: list[str] = field(default_factory=list)
    last_project: str | None = None
    libclang: str | None = None
    provider: str = "claude"
    model: str = ""
    editor: str = ""

    def remember_project(self, root: Path) -> None:
        path = str(root.resolve())
        self.known_projects = [path, *(p for p in self.known_projects if p != path)][:MAX_KNOWN_PROJECTS]
        self.last_project = path

    @classmethod
    def load(cls, path: Path) -> UserConfig:
        data = _read_json(path) or {}
        known = [str(p) for p in data.get("known_projects", [])]
        return cls(known, data.get("last_project"), data.get("libclang"), data.get("provider", "claude"),
                   data.get("model", ""), data.get("editor", ""))

    def save(self, path: Path) -> None:
        _write_json(path, asdict(self))


def config_path(platform: str = sys.platform, environ: Mapping[str, str] | None = None,
                home: Path | None = None) -> Path:
    """Where the user configuration lives on this platform."""
    environ = os.environ if environ is None else environ
    home = home or Path.home()
    if platform == "darwin":
        return home / "Library" / "Application Support" / "ICODA" / "config.json"
    if platform == "win32":
        return Path(environ.get("APPDATA", str(home / "AppData" / "Roaming"))) / "ICODA" / "config.json"
    return Path(environ.get("XDG_CONFIG_HOME", str(home / ".config"))) / "icoda" / "config.json"


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
