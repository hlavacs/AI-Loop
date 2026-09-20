"""Shared expansion wiring through the existing Tk-stub/headless pattern."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from icoda_core import clusters, persistence, session, views
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, External, FileInfo, Kind


def _opened(root: Path) -> session.OpenedProject:
    model = DerivedModel(str(root))
    model.files["src/app.cpp"] = FileInfo("src/app.cpp")
    model.files["tests/app_test.cpp"] = FileInfo("tests/app_test.cpp")
    model.add_entity(Entity("u:type", Kind.CLASS, "App", "App", "src/app.cpp", 1))
    model.add_entity(Entity("u:run", Kind.METHOD, "run", "App::run", "src/app.cpp", 3,
                            parent="u:type", status="stub"))
    model.add_entity(Entity("u:far", Kind.FUNCTION, "far", "far", "src/app.cpp", 9,
                            status="tested"))
    model.add_entity(Entity("u:test", Kind.FUNCTION, "app_test", "app_test", "tests/app_test.cpp", 1))
    model.add_edge(Edge(EdgeKind.CALLS, "u:test", "u:run"))
    model.add_edge(Edge(EdgeKind.CALLS, "u:run", "u:far"))
    model.add_edge(Edge(EdgeKind.USES_TYPE, "u:run", "external:std"))
    model.externals["std"] = External("std", ("std::string", "std::vector"))
    grouping = clusters.cluster_files(model)
    return session.OpenedProject(root, model, grouping, views.layout_file_view(model, grouping), None)


def _app(app_module, root: Path):
    opened = _opened(root)
    persistence.ProjectStore(root).save_state(persistence.ProjectState())
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(),
                         config_path=root / "config.json")
    app.show(opened)
    return app


def _sets(app) -> tuple[frozenset[str], ...]:
    return tuple(canvas.rendered_expansion_nodes() for canvas in app._expansion_canvases())


def _first(app, kind: str) -> str:
    result = app.view.expansion_result
    assert result is not None
    return next(node.key for node in result.decisions.values()
                if result.decisions[node.key].is_container
                and next(item.kind for item in result.graph.nodes if item.key == node.key) == kind)


def test_three_canvases_share_one_result_and_identical_expanded_node_sets(
        app_module, tmp_path: Path) -> None:
    app = _app(app_module, tmp_path)
    canvases = app._expansion_canvases()
    assert all(canvas.expansion_result is app.view.expansion_result for canvas in canvases)

    app.collapse_all()
    collapsed = _sets(app)
    assert collapsed[0] == collapsed[1] == collapsed[2]
    cluster = next(key for key in collapsed[0] if key.startswith("cluster:"))
    app.toggle_graph_expansion(cluster)
    expanded = _sets(app)
    assert expanded[0] == expanded[1] == expanded[2]
    assert all(len(after) > len(before) for before, after in zip(collapsed, expanded, strict=True))

    app.collapse_all()
    assert _sets(app) == collapsed
    app.collapse_all()
    assert _sets(app) == collapsed


def test_hierarchy_rows_render_each_file_and_its_contents_together(app_module, tmp_path, monkeypatch):
    app = _app(app_module, tmp_path)
    for canvas in app._expansion_canvases():
        rows = []
        monkeypatch.setattr(canvas, "_draw_expansion_row", lambda node, *_args, rows=rows: rows.append(node))
        canvas.draw_expansion_layer()
        keys = [node.key for node in rows]
        first_file = keys.index("file:src/app.cpp")
        assert keys[first_file:first_file + 4] == [
            "file:src/app.cpp", "entity:u:type", "entity:u:run", "entity:u:far"]
        assert keys[keys.index("file:tests/app_test.cpp") + 1] == "entity:u:test"
        assert canvas.node_fill("u:test") == "#aec7e8"


def test_long_hierarchy_scrolls_without_zooming_or_panning_and_clamps_after_collapse(
        app_module, tmp_path, monkeypatch):
    app = _app(app_module, tmp_path)
    for index in range(60):
        app.opened.model.add_entity(Entity(f"u:api{index}", Kind.FUNCTION, f"api{index}", f"api{index}",
                                           "src/app.cpp", 10 + index))
    app.show(app.opened)
    for canvas in app._expansion_canvases():
        rows = []
        monkeypatch.setattr(canvas, "_draw_expansion_row", lambda node, *_args, rows=rows: rows.append(node.key))
        before = (canvas.scale, canvas.offset)
        left, top, _right, _bottom = canvas.hierarchy_bounds
        canvas.on_wheel(SimpleNamespace(x=left + 40, y=top + 40, delta=-120, num=0))
        assert canvas.hierarchy_offset == 3
        assert (canvas.scale, canvas.offset) == before
        rows.clear()
        canvas.scroll_hierarchy("moveto", "1")
        assert len(rows) == canvas.hierarchy_page_size
        assert rows[-1] == canvas.expansion_result.graph.nodes[-1].key
        assert rows[0] != canvas.expansion_result.graph.nodes[0].key
        maximum = canvas.hierarchy_offset
        canvas.scroll_hierarchy("scroll", "1", "pages")
        assert canvas.hierarchy_offset == maximum
        canvas.scroll_hierarchy("scroll", "-1", "pages")
        assert canvas.hierarchy_offset == maximum - canvas.hierarchy_page_size + 1
        canvas.scroll_hierarchy("moveto", "-1")
        assert canvas.hierarchy_offset == 0
        canvas.on_press(SimpleNamespace(x=left + 40, y=top + 40))
        canvas.on_drag(SimpleNamespace(x=left + 80, y=top + 80))
        assert (canvas.scale, canvas.offset) == before
        canvas.scroll_hierarchy("moveto", "1")
    app.collapse_all()
    assert all(canvas.hierarchy_offset == 0 for canvas in app._expansion_canvases())
    for canvas in app._expansion_canvases():
        canvas.expansion_layer_enabled = False
        canvas.redraw()
        assert canvas.hierarchy_bounds is None


def test_slow_diagram_drags_accumulate_and_survive_resize(app_module, tmp_path):
    app = _app(app_module, tmp_path)
    for canvas in app._diagram_canvases():
        before = canvas.offset
        canvas.on_press(SimpleNamespace(x=100, y=100))
        for distance in range(1, 31):
            canvas.on_drag(SimpleNamespace(x=100 + distance, y=100))
        assert canvas.offset == (before[0] + 30, before[1])
        assert canvas.dragged and canvas.user_zoomed
        canvas.on_release(SimpleNamespace(x=130, y=100, num=1))
        canvas.on_resize(None)
        assert canvas.offset == (before[0] + 30, before[1])
        assert canvas.drag_start is None


def test_hierarchy_clicks_do_not_select_diagram_nodes_underneath(app_module, tmp_path, monkeypatch):
    app = _app(app_module, tmp_path)
    for canvas in app._expansion_canvases():
        canvas.hierarchy_background = 20
        canvas.item_nodes = {10: "underlying", 30: "hierarchy-row"}
        monkeypatch.setattr(canvas.canvas, "find_overlapping", lambda *args: (10, 20, 30))
        assert canvas.node_at(600, 100) == "hierarchy-row"
        monkeypatch.setattr(canvas.canvas, "find_overlapping", lambda *args: (10, 20))
        assert canvas.node_at(600, 100) is None


def test_shared_affordance_click_dispatches_without_changing_plain_click_contract(
        app_module, tmp_path: Path) -> None:
    app = _app(app_module, tmp_path)
    app.collapse_all()
    canvas = app.view
    item, cluster = next(iter(canvas.expansion_items.items()))
    before = canvas.rendered_expansion_nodes()
    canvas.canvas.find_overlapping = lambda *_args: (item,)
    canvas.on_release(SimpleNamespace(x=10, y=10, num=1))
    assert cluster in app.expansion_state
    assert len(canvas.rendered_expansion_nodes()) > len(before)


def test_external_expansion_reveals_referenced_symbols_in_every_diagram(
        app_module, tmp_path: Path) -> None:
    app = _app(app_module, tmp_path)
    app.collapse_all()
    before = _sets(app)
    app.toggle_graph_expansion("external:std")
    after = _sets(app)
    result = app.view.expansion_result
    assert result is not None
    children = result.decisions["external:std"].children
    assert len(children) == 2 and set(children) <= after[0]
    assert after[0] == after[1] == after[2]
    assert all(len(current) > len(old) for old, current in zip(before, after, strict=True))


def test_expansion_composes_with_filter_and_neighborhood_dimming(
        app_module, tmp_path: Path) -> None:
    app = _app(app_module, tmp_path)
    app.graph_filter_var.set("kind:class")
    result = app.view.expansion_result
    assert result is not None
    assert all(not canvas.node_visible("u:run") for canvas in app._expansion_canvases())
    assert "entity:u:type" in result.graph.node_keys
    assert "entity:u:run" not in result.graph.node_keys

    app.clear_graph_filter()
    app.focus_graph_node("u:test")
    app.neighborhood_depth_var.set(1)
    assert all(not canvas.node_dimmed("u:run") for canvas in app._expansion_canvases())
    assert all(canvas.node_dimmed("u:far") for canvas in app._expansion_canvases())
    assert all("entity:u:far" in canvas.rendered_expansion_nodes()
               for canvas in app._expansion_canvases())


def test_completed_step_rederives_without_reload_and_preserves_expansion_state(
        app_module, tmp_path: Path, monkeypatch) -> None:
    app = _app(app_module, tmp_path)
    app.collapse_all()
    result = app.view.expansion_result
    assert result is not None
    file_key = result.decisions["entity:u:type"].parent
    assert file_key is not None
    cluster = result.decisions[file_key].parent
    assert cluster is not None
    app.toggle_graph_expansion(cluster)
    app.toggle_graph_expansion(file_key)
    class_key = "entity:u:type"
    app.toggle_graph_expansion(class_key)
    expected_state = app.expansion_state
    previous = app.view.expansion_result
    updated = DerivedModel.from_json(app.opened.model.to_json())
    updated.add_entity(Entity("u:new", Kind.METHOD, "new_method", "App::new_method", "src/app.cpp", 12,
                              parent="u:type", status="stub"))
    monkeypatch.setattr(app, "reload", lambda: (_ for _ in ()).throw(AssertionError("reloaded")))

    app.show_after_step(updated)

    assert app.expansion_state == expected_state
    assert app.view.expansion_result is not previous
    assert "entity:u:new" in app.view.rendered_expansion_nodes()


def test_controls_are_inert_without_project_and_empty_model_is_safe(
        app_module, tmp_path: Path) -> None:
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(),
                         config_path=tmp_path / "config.json")
    app.collapse_all()
    app.toggle_graph_expansion("unknown")
    assert app.opened is None and app.expansion_state == frozenset()

    root = tmp_path / "empty"
    model = DerivedModel(str(root))
    grouping = clusters.cluster_files(model)
    persistence.ProjectStore(root).save_state(persistence.ProjectState())
    app.show(session.OpenedProject(root, model, grouping, views.layout_file_view(model, grouping), None))
    assert _sets(app) == (frozenset(),) * 3
    app.collapse_all()
    assert _sets(app) == (frozenset(),) * 3
