"""The window against the Tk stub: showing an opened project, describing and selecting nodes."""

from __future__ import annotations

from pathlib import Path

from icoda_core import clusters, persistence, session, views
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind, merge_external_names


def opened_project(tmp_path: Path) -> session.OpenedProject:
    model = DerivedModel(str(tmp_path))
    for f in ("src/a.cpp", "src/b.cpp"):
        model.files[f] = FileInfo(f, unit="source")
    model.files["src/b.cpp"].errors = ("expected ';'",)
    model.add_entity(Entity("u:A", Kind.CLASS, "A", "A", "src/a.cpp", 3))
    model.add_entity(Entity("u:A:f", Kind.METHOD, "f", "A::f", "src/a.cpp", 5, parent="u:A", signature="void f()"))
    model.add_entity(Entity("u:g", Kind.FUNCTION, "g", "g", "src/b.cpp", 1))
    model.add_edge(Edge(EdgeKind.CALLS, "u:g", "u:A:f", "src/b.cpp", 2))
    model.add_edge(Edge(EdgeKind.CALLS, "u:g", "external:std", "src/b.cpp", 3, "printf"))
    merge_external_names(model, "std", ["printf"])
    clustering = clusters.cluster_files(model)
    return session.OpenedProject(tmp_path, model, clustering, views.layout_file_view(model, clustering), None,
                                 ["no libclang found"])


def test_show_updates_status_config_and_canvas(app_module, tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=config_path)
    app.show(opened_project(tmp_path))
    assert "2 files" in app.status.get() and "libclang: none found" in app.status.get()
    assert "no libclang found" in app.status.get()
    assert app.view.layout is not None and "src/a.cpp" in app.view.layout.nodes
    assert config_path.is_file()


def test_describe_and_select_nodes(app_module, tmp_path: Path) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened_project(tmp_path))
    assert "2 entities" in app.describe_node("src/a.cpp")
    assert "errors: expected" in app.describe_node("src/b.cpp")
    assert app.describe_node("external:std").startswith("std\nprintf")
    app.select_node("src/a.cpp")
    assert app.side_title.get() == "src/a.cpp"
    app.select_node("external:std")
    assert app.side_title.get() == "src/a.cpp"


def test_zoom_keeps_the_point_under_the_cursor(app_module, tmp_path: Path) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened_project(tmp_path))
    view = app.view

    class Wheel:
        x, y, delta, num = 300, 200, 120, 0

    before = ((300 - view.offset[0]) / view.scale, (200 - view.offset[1]) / view.scale)
    view.on_wheel(Wheel())
    after = ((300 - view.offset[0]) / view.scale, (200 - view.offset[1]) / view.scale)
    assert abs(before[0] - after[0]) < 1e-6 and abs(before[1] - after[1]) < 1e-6 and view.scale > view.fit_scale


def test_new_project_writes_specification_and_skeleton_on_save(app_module, tmp_path: Path) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    opened: list[Path] = []
    app.open_project = opened.append
    project = tmp_path / "fresh"
    app.new_project(project)
    assert app.spec_editor is not None and (project / ".icoda").is_dir()
    assert app.spec_editor.to_specification()["title"] == "fresh"
    app.spec_editor.lines["objectives"].load(["ship it"])
    assert app.spec_editor.save()
    assert (project / ".icoda" / "specification.json").is_file() and (project / "CMakeLists.txt").is_file()
    assert (project / "src" / "app" / "app.cppm").is_file() and opened == [project]
    app.spec_editor.lines["objectives"].load(["ship it", "twice"])
    assert app.spec_editor.save() and opened == [project]  # the skeleton is written once
    app.edit_specification()
    assert app.spec_editor.to_specification()["objectives"] == ["ship it", "twice"]
