"""The .icoda/ folder round trips and the user configuration."""

from __future__ import annotations

from pathlib import Path

from icoda_core import persistence
from icoda_core.clusters import Layout
from icoda_core.model import DerivedModel, FileInfo


def test_project_store_creates_folder_and_round_trips(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.ensure()
    assert (tmp_path / ".icoda" / ".gitignore").read_text() == "cache/\nui.json\n"
    assert store.load_layout() == Layout() and store.load_ui() == {} and store.load_model() is None
    store.save_layout(Layout(names={"src/core": "Core"}, pins={"a.cpp": "src/core"}))
    store.save_ui({"zoom": 1.5, "view": "files"})
    model = DerivedModel(str(tmp_path))
    model.files["a.cpp"] = FileInfo("a.cpp")
    store.save_model(model)
    assert store.load_layout().names == {"src/core": "Core"}
    assert store.load_ui()["zoom"] == 1.5
    loaded = store.load_model()
    assert loaded is not None and "a.cpp" in loaded.files
    assert store.model_path.parent == store.cache_dir


def test_user_config_round_trip_and_recent_projects(tmp_path: Path) -> None:
    config = persistence.UserConfig()
    for name in "abcdefghijkl":
        config.remember_project(tmp_path / name)
    config.remember_project(tmp_path / "c")
    assert len(config.known_projects) == persistence.MAX_KNOWN_PROJECTS
    assert config.known_projects[0].endswith("/c") and config.last_project == config.known_projects[0]
    config.libclang, config.model, config.editor = "/x/libclang.dylib", "claude-opus-5", "code"
    config.save(tmp_path / "cfg" / "config.json")
    loaded = persistence.UserConfig.load(tmp_path / "cfg" / "config.json")
    assert loaded == config
    assert persistence.UserConfig.load(tmp_path / "missing.json") == persistence.UserConfig()


def test_config_path_per_platform(tmp_path: Path) -> None:
    assert persistence.config_path("darwin", {}, tmp_path) == tmp_path / "Library/Application Support/ICODA/config.json"
    assert persistence.config_path("win32", {"APPDATA": "C:/Users/h/AppData/Roaming"}, tmp_path) == \
        Path("C:/Users/h/AppData/Roaming/ICODA/config.json")
    assert persistence.config_path("linux", {}, tmp_path) == tmp_path / ".config/icoda/config.json"
    assert persistence.config_path("linux", {"XDG_CONFIG_HOME": "/xdg"}, tmp_path) == Path("/xdg/icoda/config.json")
