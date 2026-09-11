"""The .icoda/ folder of a project and the user configuration."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from icoda_core import grouping
from icoda_core.clusters import Layout
from icoda_core.mind_map import MindMapViewState
from icoda_core.model import DerivedModel

ICODA_DIR = ".icoda"
PROJECT_GITIGNORE = "cache/\nui.json\n"
MAX_KNOWN_PROJECTS = 10
DEFAULT_TEST_COMMAND = ("ctest", "--preset", "debug")
LEGACY_LIBCLANG_PREFERENCE: str | None = None


class ProjectPhase(str, Enum):
    """The developer-controlled phase of an ICODA project."""

    SPECIFICATION = "specification"
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"


PHASE_TRANSITIONS = {
    ProjectPhase.SPECIFICATION: frozenset({ProjectPhase.ARCHITECTURE}),
    ProjectPhase.ARCHITECTURE: frozenset({ProjectPhase.IMPLEMENTATION}),
    ProjectPhase.IMPLEMENTATION: frozenset({ProjectPhase.ARCHITECTURE}),
}


class PhaseTransitionError(ValueError):
    """A requested project phase transition is not part of the ICODA lifecycle."""


class ProjectStateError(RuntimeError):
    """Persisted workflow state cannot be read safely and must not be replaced silently."""


@dataclass(frozen=True)
class ProjectState:
    """Persistent workflow state for one project."""

    phase: ProjectPhase = ProjectPhase.SPECIFICATION
    implementation_queue: tuple[str, ...] = ()
    implementation_cursor: int = 0
    test_command: tuple[str, ...] = DEFAULT_TEST_COMMAND
    approved_approach: str = ""
    implementation_batch_size: int = 1
    mind_map: MindMapViewState = field(default_factory=MindMapViewState)
    implementation_scope: str = "queue_order"
    implementation_override: str = ""
    auto_approve: bool = False
    implementation_grouping: str = grouping.Mode.SINGLE_ENTITY.value

    def to_dict(self) -> dict[str, Any]:
        return {"phase": self.phase.value, "implementation_queue": list(self.implementation_queue),
                "implementation_cursor": self.implementation_cursor, "test_command": list(self.test_command),
                "approved_approach": self.approved_approach,
                "implementation_batch_size": self.implementation_batch_size,
                "mind_map": self.mind_map.to_dict(),
                "implementation_scope": self.implementation_scope,
                "implementation_override": self.implementation_override,
                "auto_approve": self.auto_approve,
                "implementation_grouping": self.implementation_grouping}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], default: ProjectPhase) -> ProjectState:
        value = data.get("phase")
        queue = tuple(str(usr) for usr in data.get("implementation_queue", ()))
        cursor = max(0, int(data.get("implementation_cursor", 0)))
        command = tuple(str(part) for part in data.get("test_command", DEFAULT_TEST_COMMAND))
        approved_approach = str(data.get("approved_approach", ""))
        batch_size = max(1, int(data.get("implementation_batch_size", 1)))
        mind_map_data = data.get("mind_map", {})
        mind_map = MindMapViewState.from_dict(mind_map_data if isinstance(mind_map_data, Mapping) else {})
        implementation_scope = str(data.get("implementation_scope", "queue_order"))
        implementation_override = str(data.get("implementation_override", ""))
        auto_approve = bool(data.get("auto_approve", False))
        implementation_grouping = str(data.get(
            "implementation_grouping", grouping.Mode.SINGLE_ENTITY.value))
        if value is None:  # projects written before the phase and queue fields
            return cls(default, queue, cursor, command, approved_approach, batch_size, mind_map,
                       implementation_scope, implementation_override, auto_approve, implementation_grouping)
        try:
            return cls(ProjectPhase(str(value)), queue, cursor, command, approved_approach, batch_size, mind_map,
                       implementation_scope, implementation_override, auto_approve, implementation_grouping)
        except ValueError as exc:
            choices = ", ".join(phase.value for phase in ProjectPhase)
            raise ValueError(f"unknown project phase {value!r}; expected one of: {choices}") from exc

    def transition_to(self, phase: ProjectPhase) -> ProjectState:
        if phase not in PHASE_TRANSITIONS[self.phase]:
            raise PhaseTransitionError(f"illegal project phase transition: {self.phase.value} -> {phase.value}")
        return ProjectState(phase, test_command=self.test_command,
                            implementation_batch_size=self.implementation_batch_size, mind_map=self.mind_map,
                            auto_approve=self.auto_approve,
                            implementation_grouping=self.implementation_grouping)


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
    def state_path(self) -> Path:
        return self.dir / "state.json"

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
        if not self.state_path.exists():
            self.save_state(ProjectState(self._default_phase()))

    def load_layout(self) -> Layout:
        return Layout.from_dict(_read_json(self.layout_path) or {})

    def save_layout(self, layout: Layout) -> None:
        _write_json(self.layout_path, layout.to_dict())

    def load_ui(self) -> dict[str, Any]:
        return _read_json(self.ui_path) or {}

    def save_ui(self, state: Mapping[str, Any]) -> None:
        _write_json(self.ui_path, dict(state))

    def load_state(self) -> ProjectState:
        if not self.state_path.is_file():
            return ProjectState(self._default_phase())
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProjectStateError(
                f"cannot open project: {self.state_path} contains invalid JSON; "
                "refusing to replace the persisted state with defaults") from exc
        return ProjectState.from_dict(data, self._default_phase())

    def save_state(self, state: ProjectState) -> None:
        _write_json(self.state_path, state.to_dict())

    def _default_phase(self) -> ProjectPhase:
        if not (self.root / "CMakeLists.txt").is_file():
            return ProjectPhase.SPECIFICATION
        if self.specification_path.is_file():
            return ProjectPhase.ARCHITECTURE
        return ProjectPhase.IMPLEMENTATION

    def load_model(self) -> DerivedModel | None:
        if not self.model_path.is_file():
            return None
        model = DerivedModel.load(self.model_path)
        # Local import avoids making the step-log module part of persistence's import-time foundation.
        from icoda_core.steplog import StepLog, apply_statuses
        apply_statuses(model, StepLog(self.steps_path))
        return model

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
    preferred_libclang: str | None = LEGACY_LIBCLANG_PREFERENCE

    def remember_project(self, root: Path) -> None:
        path = str(root.resolve())
        self.known_projects = [path, *(p for p in self.known_projects if p != path)][:MAX_KNOWN_PROJECTS]
        self.last_project = path

    @classmethod
    def load(cls, path: Path) -> UserConfig:
        data = _read_json(path) or {}
        known = [str(p) for p in data.get("known_projects", [])]
        preferred_libclang = data.get("preferred_libclang", LEGACY_LIBCLANG_PREFERENCE)
        return cls(known, data.get("last_project"), data.get("libclang"), data.get("provider", "claude"),
                   data.get("model", ""), data.get("editor", ""), preferred_libclang)

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
