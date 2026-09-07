"""Opening the sample project without a GUI, and the editor command."""

from __future__ import annotations

from pathlib import Path

import pytest

from icoda_core import persistence, session, toolchain

SAMPLE = Path(__file__).resolve().parent / "sample_project"


def test_open_sample_project_produces_layout_and_remembers_it(tmp_path: Path) -> None:
    if not toolchain.candidates():
        pytest.skip("no libclang available")
    from test_analysis import _ensure_built  # type: ignore[import-not-found]

    _ensure_built(SAMPLE)
    config = persistence.UserConfig()
    opened = session.open_project(SAMPLE, config)
    assert opened.libclang is not None and not opened.model.stale
    assert len(opened.clustering.clusters) >= 5 and opened.layout.nodes
    assert "src/core/shapes.cppm" in opened.layout.nodes and "external:std" in opened.layout.nodes
    assert config.last_project == str(SAMPLE) and (SAMPLE / ".icoda" / "cache" / "model.json").is_file()
    assert "entities" in opened.summary


def test_open_project_without_build_reports_it(tmp_path: Path) -> None:
    (tmp_path / "a.cpp").write_text("int main() {}\n")
    opened = session.open_project(tmp_path, persistence.UserConfig())
    assert any("compile_commands" in m or "libclang" in m for m in opened.messages)
    assert opened.layout.circles == []


def test_editor_command() -> None:
    assert session.editor_command(Path("/p/a.cpp"), 7, "subl {file}:{line}") == ["subl", "/p/a.cpp:7"]
    assert session.editor_command(Path("/p/a.cpp"), 7, "myedit") == ["myedit", "/p/a.cpp"]
    command = session.editor_command(Path("/p/a.cpp"), 7)
    assert command[0] in ("code", "open", "cmd", "xdg-open")
