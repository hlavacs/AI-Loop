"""One shared filter and neighbourhood control across all four Tk-stub diagrams."""

from __future__ import annotations

from pathlib import Path

from icoda_core import clusters, persistence, session, views
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind
from icoda_gui import graph_canvas


def _opened(root: Path) -> session.OpenedProject:
    model = DerivedModel(str(root))
    model.files["src/app.cpp"] = FileInfo("src/app.cpp")
    model.files["tests/app_test.cpp"] = FileInfo("tests/app_test.cpp")
    model.add_entity(Entity("u:type", Kind.CLASS, "App", "App", "src/app.cpp", 1))
    model.add_entity(Entity("u:covered", Kind.METHOD, "covered", "App::covered", "src/app.cpp", 3,
                            parent="u:type", status="tested", satisfies=("R-1",)))
    model.add_entity(Entity("u:uncovered", Kind.METHOD, "missing", "App::missing", "src/app.cpp", 7,
                            parent="u:type", status="stub"))
    model.add_entity(Entity("u:test", Kind.FUNCTION, "app_test", "app_test", "tests/app_test.cpp", 1))
    model.add_edge(Edge(EdgeKind.CALLS, "u:test", "u:covered"))
    model.add_edge(Edge(EdgeKind.CALLS, "u:covered", "u:uncovered"))
    grouping = clusters.cluster_files(model)
    return session.OpenedProject(root, model, grouping, views.layout_file_view(model, grouping), None)


def _app(app_module, root: Path):
    opened = _opened(root)
    persistence.ProjectStore(root).save_state(persistence.ProjectState())
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(),
                         config_path=root / "config.json")
    app.show(opened)
    return app


def _visible(app) -> tuple[frozenset[str], ...]:
    usrs = frozenset(app.opened.model.entities)
    return tuple(frozenset(usr for usr in usrs if canvas.node_visible(usr))
                 for canvas in app._diagram_canvases())


def test_filter_apply_change_and_clear_have_identical_cross_view_sets(
        app_module, tmp_path: Path) -> None:
    app = _app(app_module, tmp_path)
    all_usrs = frozenset(app.opened.model.entities)
    assert _visible(app) == (all_usrs,) * 4
    assert all(canvas.node_decisions is app.view.node_decisions for canvas in app._diagram_canvases())

    app.graph_filter_var.set("status:stub")
    filtered = _visible(app)
    assert filtered == (frozenset({"u:type", "u:uncovered"}),) * 4

    drawn_text: list[list[str]] = [[] for _canvas in app._diagram_canvases()]
    for canvas, texts in zip(app._diagram_canvases(), drawn_text, strict=True):
        canvas.canvas.create_text = lambda *_args, texts=texts, **kwargs: (
            texts.append(str(kwargs.get("text", ""))) or len(texts))
    app.graph_filter_var.set("name:no-match")
    assert _visible(app) == (frozenset(),) * 4
    assert all(canvas.filter_active for canvas in app._diagram_canvases())
    assert all("No nodes match the current filter." in texts for texts in drawn_text)

    app.clear_graph_filter()
    assert _visible(app) == (all_usrs,) * 4
    app.clear_graph_filter()
    assert _visible(app) == (all_usrs,) * 4


def test_one_focus_and_depth_dim_identically_with_shared_appearance(
        app_module, tmp_path: Path) -> None:
    app = _app(app_module, tmp_path)
    app.focus_graph_node("u:test")
    app.neighborhood_depth_var.set(1)
    canvases = app._diagram_canvases()

    assert all(not canvas.node_dimmed("u:test") for canvas in canvases)
    assert all(not canvas.node_dimmed("u:covered") for canvas in canvases)
    assert all(canvas.node_dimmed("u:uncovered") for canvas in canvases)
    assert {canvas.node_fill("u:uncovered", "#123456") for canvas in canvases} == {
        graph_canvas.DIMMED_APPEARANCE["fill"]}
    assert {canvas.node_outline("u:uncovered", "#123456") for canvas in canvases} == {
        graph_canvas.DIMMED_APPEARANCE["outline"]}

    app.neighborhood_depth_var.set(2)
    assert all(not canvas.node_dimmed("u:uncovered") for canvas in canvases)


def test_controls_are_inert_without_project_and_empty_model_is_safe(
        app_module, tmp_path: Path) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(),
                         config_path=tmp_path / "empty-config.json")
    app.graph_filter_var.set("kind:function")
    app.neighborhood_depth_var.set(2)
    app.clear_graph_filter()
    app.clear_graph_filter()
    assert app.opened is None

    root = tmp_path / "project"
    model = DerivedModel(str(root))
    grouping = clusters.cluster_files(model)
    opened = session.OpenedProject(root, model, grouping, views.layout_file_view(model, grouping), None)
    persistence.ProjectStore(root).save_state(persistence.ProjectState())
    app.show(opened)
    assert all(dict(canvas.node_decisions) == {} for canvas in app._diagram_canvases())


def test_completed_step_rederives_active_filter_and_dimming_without_reload(
        app_module, tmp_path: Path, monkeypatch) -> None:
    app = _app(app_module, tmp_path)
    app.graph_filter_var.set("name:new_name")
    app.focus_graph_node("u:test")
    app.neighborhood_depth_var.set(1)
    previous = app.call_view.node_decisions
    updated = DerivedModel.from_json(app.opened.model.to_json())
    updated.entities["u:covered"].name = "new_name"
    updated.entities["u:covered"].qualified_name = "App::new_name"
    monkeypatch.setattr(app, "reload", lambda: (_ for _ in ()).throw(AssertionError("reloaded")))

    app.show_after_step(updated)

    assert app.call_view.node_decisions is not previous
    assert all(canvas.node_visible("u:covered") for canvas in app._diagram_canvases())
    assert all(not canvas.node_dimmed("u:covered") for canvas in app._diagram_canvases())
    assert app.graph_filter_var.get() == "name:new_name"
    assert app.neighborhood_depth_var.get() == 1
