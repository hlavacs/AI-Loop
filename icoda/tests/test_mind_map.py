"""Pure M4 mind-map hierarchy, deterministic geometry and persistence."""

from __future__ import annotations

import json
from pathlib import Path

from icoda_core import mind_map, persistence, views
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind
from icoda_core.steplog import StepRecord


def project(reverse: bool = False) -> DerivedModel:
    model = DerivedModel("/project")
    files = [FileInfo("core/alpha.cpp"), FileInfo("empty/nothing.cpp"), FileInfo("ui/view.cpp")]
    entities = [
        Entity("u:widget", Kind.CLASS, "Widget", "app::Widget", "core/alpha.cpp", 10,
               satisfies=("R-CLASS",), status="implemented"),
        Entity("u:run", Kind.METHOD, "run", "app::Widget::run", "core/alpha.cpp", 14,
               parent="u:widget", satisfies=("R-RUN", "R-COMMON"), status="tested"),
        Entity("u:stop", Kind.METHOD, "stop", "app::Widget::stop", "core/alpha.cpp", 18,
               parent="u:widget", satisfies=("R-STOP",), status="stub"),
        Entity("u:helper", Kind.FUNCTION, "helper", "app::helper", "core/alpha.cpp", 25,
               satisfies=("R-COMMON",), status="implemented"),
        Entity("u:view", Kind.STRUCT, "View", "ui::View", "ui/view.cpp", 3,
               satisfies=("R-VIEW",), status="implemented"),
        Entity("u:draw", Kind.METHOD, "draw", "ui::View::draw", "ui/view.cpp", 7,
               parent="u:view", satisfies=("R-DRAW",), status="tested"),
    ]
    edges = [
        Edge(EdgeKind.CALLS, "u:run", "u:helper"),
        Edge(EdgeKind.CALLS, "u:stop", "u:helper"),
    ]
    for file in reversed(files) if reverse else files:
        model.files[file.path] = file
    for entity in reversed(entities) if reverse else entities:
        model.add_entity(entity)
    for edge in reversed(edges) if reverse else edges:
        model.add_edge(edge)
    return model


def history() -> list[StepRecord]:
    return [
        StepRecord(4, "architecture", "approved", entities_added=["u:view", "u:draw"],
                   files=["ui/view.cpp"]),
        StepRecord(2, "architecture", "approved", entities_added=["u:widget", "u:run", "u:stop"],
                   files=["core/alpha.cpp"]),
        StepRecord(1, "architecture", "manual", entities_added=["u:helper"], files=["core/alpha.cpp"]),
        StepRecord(9, "architecture", "rejected", entities_added=["u:draw"]),
    ]


def test_full_hierarchy_metadata_and_documented_order() -> None:
    tree = mind_map.build_mind_map(project(), history())
    assert [(node.id, node.kind) for node in tree.clusters] == [
        ("cluster:core", mind_map.MindMapNodeKind.CLUSTER),
        ("cluster:empty", mind_map.MindMapNodeKind.CLUSTER),
        ("cluster:ui", mind_map.MindMapNodeKind.CLUSTER),
    ]
    nodes = tree.node_map()
    core_file = nodes["file:core/alpha.cpp"]
    assert [child.id for child in core_file.children] == ["entity:u:widget", "entity:u:helper"]
    assert [child.id for child in nodes["entity:u:widget"].children] == ["entity:u:run", "entity:u:stop"]
    assert nodes["entity:u:run"].status == "tested"
    assert nodes["entity:u:run"].satisfied_requirement_ids == ("R-COMMON", "R-RUN")
    assert nodes["entity:u:run"].introduced_iteration == 2
    assert nodes["entity:u:widget"].status == "implemented"
    assert nodes["entity:u:widget"].satisfied_requirement_ids == ("R-CLASS",)
    assert nodes["entity:u:helper"].introduced_iteration == 1
    assert nodes["file:core/alpha.cpp"].introduced_iteration == 1
    assert nodes["cluster:core"].introduced_iteration == 1
    assert nodes["cluster:core"].status == "stub"
    assert nodes["cluster:core"].satisfied_requirement_ids == (
        "R-CLASS", "R-COMMON", "R-RUN", "R-STOP")
    entity_nodes = [node.usr for node in tree.nodes() if node.usr]
    assert sorted(entity_nodes) == sorted(project().entities)
    assert len(entity_nodes) == len(set(entity_nodes))


def test_builder_and_layout_ignore_model_insertion_order() -> None:
    first = mind_map.build_mind_map(project(), history())
    second_model = DerivedModel.from_json(project(reverse=True).to_json())
    second = mind_map.build_mind_map(second_model, reversed(history()))
    state = mind_map.MindMapViewState(tuple(node.id for node in first.nodes()))
    assert first == second
    assert views.layout_mind_map(first, state) == views.layout_mind_map(second, state)


def test_layout_does_not_overlap_and_collapse_removes_only_descendants() -> None:
    tree = mind_map.build_mind_map(project(), history())
    expanded = mind_map.MindMapViewState(tuple(node.id for node in tree.nodes()))
    full = views.layout_mind_map(tree, expanded)
    for index, left in enumerate(full.nodes):
        for right in full.nodes[index + 1:]:
            separated = (abs(left.x - right.x) >= (left.width + right.width) / 2
                         or abs(left.y - right.y) >= (left.height + right.height) / 2)
            assert separated

    collapsed = views.layout_mind_map(
        tree, mind_map.MindMapViewState(tuple(node_id for node_id in expanded.expanded
                                             if node_id != "file:core/alpha.cpp")))
    removed = set(full.node_map()) - set(collapsed.node_map())
    assert removed == {"entity:u:widget", "entity:u:run", "entity:u:stop", "entity:u:helper"}
    assert "file:core/alpha.cpp" in collapsed.node_map()


def test_view_state_and_legacy_project_state_round_trip(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    view_state = mind_map.MindMapViewState(("file:core/alpha.cpp", "cluster:core", "cluster:core"))
    state = persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION, mind_map=view_state)
    store.save_state(state)
    assert store.load_state() == state
    assert json.loads(store.state_path.read_text(encoding="utf-8"))["mind_map"] == {
        "expanded": ["cluster:core", "file:core/alpha.cpp"]}

    store.state_path.write_text('{"phase": "implementation"}', encoding="utf-8")
    legacy_state = store.load_state()
    assert legacy_state.mind_map == mind_map.MindMapViewState()
    loaded_model = DerivedModel.from_json(project().to_json())
    loaded_tree = mind_map.build_mind_map(loaded_model, history())
    assert loaded_tree == mind_map.build_mind_map(project(), history())
    assert {item.node.id for item in views.layout_mind_map(loaded_tree, legacy_state.mind_map).nodes} == {
        node.id for node in loaded_tree.clusters}


def test_empty_and_incomplete_inputs_are_valid() -> None:
    empty_tree = mind_map.build_mind_map(DerivedModel("/empty"), [])
    assert empty_tree == mind_map.MindMap()
    assert views.layout_mind_map(empty_tree) == views.MindMapLayout(empty_tree, (), (), 1.0, 1.0)

    model = DerivedModel("/partial")
    model.files["only/empty.cpp"] = FileInfo("only/empty.cpp")
    model.files["only/code.cpp"] = FileInfo("only/code.cpp")
    model.add_entity(Entity("u:unknown", Kind.FUNCTION, "unknown", "unknown", "only/code.cpp", 1,
                            satisfies=("R-X",), status="implemented"))
    tree = mind_map.build_mind_map(model, [])
    nodes = tree.node_map()
    assert nodes["file:only/empty.cpp"].children == ()
    assert nodes["file:only/empty.cpp"].status == "unknown"
    assert nodes["entity:u:unknown"].introduced_iteration is None
    expanded = mind_map.MindMapViewState(tuple(node.id for node in tree.nodes()))
    assert set(views.layout_mind_map(tree, expanded).node_map()) == set(nodes)


def test_rename_keeps_introducing_iteration_and_undone_steps_do_not_count() -> None:
    model = DerivedModel("/rename")
    model.files["renamed.cpp"] = FileInfo("renamed.cpp")
    model.add_entity(Entity("u:new", Kind.FUNCTION, "renamed", "renamed", "renamed.cpp", 1))
    records = [
        StepRecord(1, "architecture", "approved", entities_added=["u:old"]),
        StepRecord(2, "implementation", "approved", entities_renamed=[("u:old", "u:new")]),
        StepRecord(3, "implementation", "approved", entities_added=["u:new"]),
        StepRecord(4, "implementation", "undone", undoes=3),
    ]
    node = mind_map.build_mind_map(model, records).node_map()["entity:u:new"]
    assert node.introduced_iteration == 1
