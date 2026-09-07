"""Derived model: definition precedence, edge deduplication, file-level aggregation, JSON round trip."""

from __future__ import annotations

from pathlib import Path

from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind, merge_external_names


def make_model() -> DerivedModel:
    model = DerivedModel("/proj", "clang 18")
    model.files["main.cpp"] = FileInfo("main.cpp", unit="source", content_hash="h1")
    model.files["render.cppm"] = FileInfo("render.cppm", module="render", unit="interface", content_hash="h2")
    model.add_entity(Entity("c:@F@main#", Kind.FUNCTION, "main", "main", "main.cpp", 3, signature="int main()"))
    model.add_entity(Entity("c:@S@Renderer", Kind.CLASS, "Renderer", "Renderer", "render.cppm", 5,
                            is_definition=False))
    model.add_entity(Entity("c:@S@Renderer", Kind.CLASS, "Renderer", "Renderer", "render.cppm", 8,
                            brief="Draws.", satisfies=("R-1",), exported=True))
    model.add_entity(Entity("c:@S@Renderer@F@draw#", Kind.METHOD, "draw", "Renderer::draw", "render.cppm", 10,
                            parent="c:@S@Renderer"))
    model.add_edge(Edge(EdgeKind.CALLS, "c:@F@main#", "c:@S@Renderer@F@draw#", "main.cpp", 4))
    model.add_edge(Edge(EdgeKind.CALLS, "c:@F@main#", "c:@S@Renderer@F@draw#", "main.cpp", 4))
    model.add_edge(Edge(EdgeKind.IMPORTS, "main.cpp", "render.cppm", "main.cpp", 1))
    merge_external_names(model, "std", ["vector", "printf"])
    merge_external_names(model, "std", ["vector", "accumulate"])
    return model


def test_definition_wins_and_edges_deduplicate() -> None:
    model = make_model()
    assert model.entities["c:@S@Renderer"].line == 8 and model.entities["c:@S@Renderer"].exported
    assert len(model.edges) == 2
    assert model.callees("c:@F@main#")[0].target == "c:@S@Renderer@F@draw#"
    assert model.callers("c:@S@Renderer@F@draw#")[0].source == "c:@F@main#"
    assert [e.name for e in model.children("c:@S@Renderer")] == ["draw"]
    assert model.externals["std"].names == ("accumulate", "printf", "vector")


def test_file_level_aggregation() -> None:
    counts = make_model().file_edges()
    assert counts == {("main.cpp", "render.cppm", EdgeKind.CALLS): 1,
                      ("main.cpp", "render.cppm", EdgeKind.IMPORTS): 1}


def test_json_round_trip(tmp_path: Path) -> None:
    model = make_model()
    model.stale, model.stale_reason = True, "main.cpp: error"
    model.save(tmp_path / ".icoda" / "cache" / "model.json")
    loaded = DerivedModel.load(tmp_path / ".icoda" / "cache" / "model.json")
    assert loaded.to_json() == model.to_json()
    assert loaded.entities["c:@S@Renderer"].satisfies == ("R-1",)
    assert loaded.files["render.cppm"].module == "render" and loaded.stale
