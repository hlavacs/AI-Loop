"""Shared diagram appearance wiring through the Tk stub."""

from __future__ import annotations

from pathlib import Path

from icoda_core import clusters, persistence, session, specification, steplog, views
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind
from icoda_gui import graph_canvas


def _opened(root: Path) -> session.OpenedProject:
    model = DerivedModel(str(root))
    model.files["src/app.cpp"] = FileInfo("src/app.cpp")
    model.files["tests/app_test.cpp"] = FileInfo("tests/app_test.cpp")
    model.files["tests/unrecorded_test.cpp"] = FileInfo("tests/unrecorded_test.cpp")
    model.add_entity(Entity("u:type", Kind.CLASS, "App", "App", "src/app.cpp", 1))
    model.add_entity(Entity("u:covered", Kind.METHOD, "covered", "App::covered", "src/app.cpp", 3,
                            parent="u:type", status="tested", body_hash="new"))
    model.add_entity(Entity("u:uncovered", Kind.METHOD, "uncovered", "App::uncovered", "src/app.cpp", 7,
                            parent="u:type", status="stub", satisfies=("R-1",)))
    model.add_entity(Entity("u:test", Kind.FUNCTION, "app_test", "app_test", "tests/app_test.cpp", 1))
    model.add_entity(Entity("u:unrecorded_test", Kind.FUNCTION, "unrecorded_test", "unrecorded_test",
                            "tests/unrecorded_test.cpp", 1))
    model.add_edge(Edge(EdgeKind.CALLS, "u:test", "u:covered", "tests/app_test.cpp", 2))
    model.add_edge(Edge(EdgeKind.CALLS, "u:unrecorded_test", "u:uncovered",
                        "tests/unrecorded_test.cpp", 2))
    grouping = clusters.cluster_files(model)
    return session.OpenedProject(root, model, grouping, views.layout_file_view(model, grouping), None)


def _app(app_module, tmp_path: Path):
    opened = _opened(tmp_path)
    store = persistence.ProjectStore(tmp_path)
    store.save_state(persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, ("u:uncovered",), 0))
    log = steplog.StepLog(store.steps_path)
    log.append(steplog.StepRecord(
        2, "implementation", "approved", entities_changed=["u:covered"], test_ok=True,
        selected_tests=["tests/app_test.cpp"], entity_body_hashes={"u:covered": "old"}))
    steplog.apply_statuses(opened.model, log)
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(),
                         config_path=tmp_path / "config.json")
    app.show(opened)
    return app


def test_all_four_canvases_share_mapping_colours_and_stale_marker(app_module, tmp_path: Path) -> None:
    app = _app(app_module, tmp_path)
    canvases = (app.view, app.call_view, app.class_view, app.mind_map_view)
    assert all(canvas.node_appearances is canvases[0].node_appearances for canvas in canvases)
    assert {canvas.node_fill("u:covered") for canvas in canvases} == {
        graph_canvas.NODE_COLOURS["implemented"]}
    assert {canvas.stale_marker("entity:u:covered") for canvas in canvases} == {
        graph_canvas.STALE_MARKER}
    assert {canvas.node_fill("u:missing") for canvas in canvases} == {
        graph_canvas.NODE_COLOURS["neutral"]}
    assert all(canvas.stale_marker("u:missing") == "" for canvas in canvases)
    assert app.opened is not None
    app.opened.model.stale, app.opened.model.stale_reason = True, "parse failed"
    app.refresh_graph_appearances()
    assert all(canvas.stale_marker("u:missing") == graph_canvas.STALE_MARKER for canvas in canvases)


def test_coverage_mode_uses_recorded_test_provenance_not_model_reachability(
        app_module, tmp_path: Path) -> None:
    empty = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(),
                           config_path=tmp_path / "empty.json")
    empty.coverage_mode_var.set(True)
    empty.toggle_coverage_mode()
    assert all(canvas.coverage_mode for canvas in empty._diagram_canvases())

    app = _app(app_module, tmp_path / "project")
    canvases = app._diagram_canvases()
    assert {canvas.node_fill("u:covered") for canvas in canvases} == {
        graph_canvas.NODE_COLOURS["implemented"]}
    app.coverage_mode_var.set(True)
    app.toggle_coverage_mode()
    assert {canvas.node_fill("u:covered") for canvas in canvases} == {
        graph_canvas.NODE_COLOURS["covered"]}
    assert {canvas.node_fill("u:uncovered") for canvas in canvases} == {
        graph_canvas.NODE_COLOURS["uncovered"]}


def test_completed_step_rederives_mapping_without_project_reload(
        app_module, tmp_path: Path, monkeypatch) -> None:
    app = _app(app_module, tmp_path)
    previous = app.call_view.node_appearances
    updated = DerivedModel.from_json(app.opened.model.to_json())
    updated.entities["u:covered"].body_hash = "old"
    monkeypatch.setattr(app, "reload", lambda: (_ for _ in ()).throw(AssertionError("reloaded")))

    app.show_after_step(updated)

    current = app.call_view.node_appearances
    assert current is not previous
    assert current["u:covered"].stale is False
    assert current["u:covered"].covered is True


def test_coverage_requirements_repaint_after_specification_save(
        app_module, tmp_path: Path, monkeypatch) -> None:
    spec = specification.default_specification("Requirement repaint")
    spec["requirements"] = [{"id": "R-1", "title": "Show the pending work", "priority": "must"}]
    store = persistence.ProjectStore(tmp_path)
    specification.save(store.specification_path, spec)
    app = _app(app_module, tmp_path)
    assert [(entry.identifier, entry.uncovered) for entry in app.coverage_view.requirements] == [
        ("R-1", False)
    ]

    rendered: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        app.coverage_view.requirement_tree,
        "insert",
        lambda _parent, _where, **kwargs: rendered.append(tuple(kwargs["values"])),
    )
    monkeypatch.setattr(app, "open_project", lambda _root: app.show(app.opened))
    spec["requirements"].append(
        {"id": "R-2", "title": "Explain a newly requested export", "priority": "should"}
    )

    app._save_specification(spec)

    assert app.coverage_view.requirements_summary_var.get() == (
        "Specification coverage: 1/2 goals and requirements covered · 1 UNCOVERED"
    )
    assert rendered == [
        ("Covered", "R-1", "Requirement", "Show the pending work", "App::uncovered"),
        ("UNCOVERED", "R-2", "Requirement", "Explain a newly requested export", "No implementing entity"),
    ]
