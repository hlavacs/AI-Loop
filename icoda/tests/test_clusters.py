"""Clustering: every file in exactly one cluster, directories as seeds, no collapse, splitting, pins."""

from __future__ import annotations

import json
from pathlib import Path

from icoda_core import clusters, persistence
from icoda_core.model import DerivedModel, Edge, EdgeKind, FileInfo


def synthetic_project(directories: int = 10, per_directory: int = 30) -> DerivedModel:
    """300 files in 10 directories; every file is reachable from main.cpp through its directory hub."""
    model = DerivedModel("/synthetic")
    model.files["main.cpp"] = FileInfo("main.cpp")
    for d in range(directories):
        hub = f"dir{d}/hub.cpp"
        model.files[hub] = FileInfo(hub)
        model.add_edge(Edge(EdgeKind.CALLS, "main.cpp", hub))
        for i in range(per_directory - 1):
            file = f"dir{d}/file{i}.cpp"
            model.files[file] = FileInfo(file)
            model.add_edge(Edge(EdgeKind.CALLS, hub, file))
            model.add_edge(Edge(EdgeKind.CALLS, file, f"dir{d}/file{(i + 1) % (per_directory - 1)}.cpp"))
    return model


def collapsed_modular_project() -> DerivedModel:
    """One directory and label, but two dense graph communities joined by one edge."""
    model = DerivedModel("/collapsed")
    communities = tuple(tuple(f"src/{prefix}{index:02}.cpp" for index in range(21))
                        for prefix in ("a", "b"))
    for files in communities:
        for file in files:
            model.files[file] = FileInfo(file)
        for index, source in enumerate(files):
            for target in files[index + 1:]:
                model.add_edge(Edge(EdgeKind.CALLS, source, target))
    model.add_edge(Edge(EdgeKind.CALLS, communities[0][0], communities[1][0]))
    return model


def test_every_file_in_exactly_one_cluster_and_no_collapse() -> None:
    model = synthetic_project()
    clustering = clusters.cluster_files(model)
    seen = [f for c in clustering.clusters for f in c.files]
    assert sorted(seen) == sorted(model.files) and len(seen) == len(set(seen)) == 301
    assert len(clustering.clusters) > 1
    assert all(len(c.files) <= clusters.MAX_CLUSTER_SIZE for c in clustering.clusters)


def test_directory_seeds_and_deterministic_result() -> None:
    model = synthetic_project(directories=3, per_directory=5)
    first, second = clusters.cluster_files(model), clusters.cluster_files(model)
    assert [c.files for c in first.clusters] == [c.files for c in second.clusters]
    assert first.cluster_of("dir1/file2.cpp") is first.cluster_of("dir1/hub.cpp")
    assert first.cluster_of("dir1/hub.cpp") is not first.cluster_of("dir2/hub.cpp")


def test_collapsed_large_model_falls_back_to_louvain_communities() -> None:
    model = collapsed_modular_project()
    graph = clusters.file_graph(model)
    seeds = {file: clusters.directory_seed(file) for file in graph.nodes}

    propagated = clusters.seeded_label_propagation(graph, seeds)
    clustering = clusters.cluster_files(model)

    assert len(set(propagated.values())) == 1
    assert clustering.algorithm == "louvain"
    assert len(clustering.clusters) > 1


def test_louvain_fallback_labels_are_byte_identical_across_runs() -> None:
    model = collapsed_modular_project()

    def encoded() -> bytes:
        clustering = clusters.cluster_files(model)
        assert clustering.algorithm == "louvain"
        labels = [(cluster.id, cluster.name, cluster.files) for cluster in clustering.clusters]
        return json.dumps(labels, separators=(",", ":")).encode()

    assert encoded() == encoded()


def test_sample_shaped_model_keeps_seeded_label_propagation() -> None:
    clustering = clusters.cluster_files(synthetic_project(directories=3, per_directory=5))

    assert clustering.algorithm == "seeded_label_propagation"


def test_pinned_file_keeps_chosen_cluster_during_louvain_fallback() -> None:
    layout = clusters.Layout(names={"chosen": "Chosen cluster"}, pins={"src/a00.cpp": "chosen"})

    clustering = clusters.cluster_files(collapsed_modular_project(), layout)

    pinned = clustering.cluster_of("src/a00.cpp")
    assert clustering.algorithm == "louvain"
    assert pinned is not None and pinned.id == "chosen" and pinned.name == "Chosen cluster"


def test_a_file_bound_elsewhere_moves() -> None:
    model = DerivedModel("/p")
    for f in ("a/x.cpp", "a/y.cpp", "b/stray.cpp", "b/z.cpp", "b/w.cpp"):
        model.files[f] = FileInfo(f)
    for _ in range(6):
        model.edges.append(Edge(EdgeKind.CALLS, "a/x.cpp", "a/y.cpp", line=len(model.edges)))
    for target in ("a/x.cpp", "a/y.cpp"):
        for _ in range(5):
            model.edges.append(Edge(EdgeKind.CALLS, "b/stray.cpp", target, line=len(model.edges)))
    model.edges.append(Edge(EdgeKind.CALLS, "b/stray.cpp", "b/z.cpp"))
    model.edges.append(Edge(EdgeKind.CALLS, "b/z.cpp", "b/w.cpp", line=1))
    model.edges.append(Edge(EdgeKind.CALLS, "b/w.cpp", "b/z.cpp", line=2))
    clustering = clusters.cluster_files(model)
    assert clustering.cluster_of("b/stray.cpp") is clustering.cluster_of("a/x.cpp")
    assert clustering.cluster_of("b/z.cpp") is not clustering.cluster_of("a/x.cpp")


def test_pins_and_names_from_layout() -> None:
    model = synthetic_project(directories=2, per_directory=3)
    layout = clusters.Layout(names={"dir0": "Core"}, pins={"dir1/hub.cpp": "dir0"})
    clustering = clusters.cluster_files(model, layout)
    core = clustering.cluster_of("dir1/hub.cpp")
    assert core is not None and core.name == "Core" and core.id == "dir0"
    assert clusters.Layout.from_dict(layout.to_dict()) == layout


def test_split_large() -> None:
    labels = {f"lib/f{i}.cpp": "lib" for i in range(95)}
    split = clusters.split_large(labels, max_size=40)
    assert {split[f] for f in labels} == {"lib#1", "lib#2", "lib#3"}


def _movable_project(bound_to_a: bool) -> DerivedModel:
    model = DerivedModel("/movable")
    for file in ("a/x.cpp", "a/y.cpp", "b/stray.cpp", "b/z.cpp", "b/w.cpp"):
        model.files[file] = FileInfo(file)
    model.add_edge(Edge(EdgeKind.CALLS, "a/x.cpp", "a/y.cpp"))
    model.add_edge(Edge(EdgeKind.CALLS, "b/z.cpp", "b/w.cpp"))
    if bound_to_a:
        for target in ("a/x.cpp", "a/y.cpp"):
            for line in range(5):
                model.add_edge(Edge(EdgeKind.CALLS, "b/stray.cpp", target, line=line))
    else:
        for target in ("b/z.cpp", "b/w.cpp"):
            for line in range(5):
                model.add_edge(Edge(EdgeKind.CALLS, "b/stray.cpp", target, line=line))
    return model


def test_pinned_cluster_keeps_membership_across_second_clustering_run() -> None:
    first = clusters.cluster_files(_movable_project(True))
    pinned = first.cluster_of("b/stray.cpp")
    assert pinned is not None and pinned.id == "a"
    decision = clusters.pin_cluster(clusters.Layout(), first, pinned.id)

    second = clusters.cluster_files(_movable_project(False), decision.to_layout())

    assert second.cluster_of("b/stray.cpp") is not None
    assert second.cluster_of("b/stray.cpp").id == pinned.id
    assert second.cluster_of("b/stray.cpp").files == pinned.files


def test_cluster_rename_is_persisted_and_reloaded(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    decision = clusters.rename_cluster(clusters.Layout(), "src", "Application Core")

    store.save_layout(decision.to_layout())

    assert store.load_layout() == clusters.Layout(names={"src": "Application Core"})


def test_unpin_restores_normal_reclustering() -> None:
    first = clusters.cluster_files(_movable_project(True))
    pinned = first.cluster_of("b/stray.cpp")
    assert pinned is not None
    pinned_layout = clusters.pin_cluster(clusters.Layout(), first, pinned.id).to_layout()
    unpinned_layout = clusters.unpin_cluster(pinned_layout, pinned.id).to_layout()

    reclustered = clusters.cluster_files(_movable_project(False), unpinned_layout)

    assert reclustered.cluster_of("b/stray.cpp") is not None
    assert reclustered.cluster_of("b/stray.cpp").id == "b"
    assert unpinned_layout.pins == {}


def test_pin_file_moves_only_selected_file_while_other_labels_stay_algorithmic() -> None:
    model = _movable_project(False)
    algorithmic = clusters.cluster_files(model)
    original = {file: cluster.id for cluster in algorithmic.clusters for file in cluster.files}
    decision = clusters.pin_file(
        clusters.Layout(names={"a": "Application"}, pins={"b/z.cpp": "b"}),
        algorithmic,
        "b/stray.cpp",
        "a",
    )

    pinned = clusters.cluster_files(model, decision.to_layout())
    actual = {file: cluster.id for cluster in pinned.clusters for file in cluster.files}

    assert decision.changed
    assert decision.names == (("a", "Application"),)
    assert decision.pins == (("b/stray.cpp", "a"), ("b/z.cpp", "b"))
    assert actual["b/stray.cpp"] == "a" != original["b/stray.cpp"]
    assert {file: label for file, label in actual.items() if file != "b/stray.cpp"} == {
        file: label for file, label in original.items() if file != "b/stray.cpp"
    }


def test_file_pin_is_persisted_reloaded_and_removable(tmp_path: Path) -> None:
    clustering = clusters.cluster_files(_movable_project(False))
    decision = clusters.pin_file(clusters.Layout(), clustering, "b/stray.cpp", "a")
    store = persistence.ProjectStore(tmp_path)

    store.save_layout(decision.to_layout())
    loaded = store.load_layout()
    removed = clusters.unpin_file(loaded, "b/stray.cpp")

    assert loaded == clusters.Layout(pins={"b/stray.cpp": "a"})
    assert removed.changed and removed.to_layout() == clusters.Layout()


def test_pin_file_survives_louvain_triggered_run() -> None:
    model = collapsed_modular_project()
    initial = clusters.cluster_files(model)
    source = "src/a00.cpp"
    original = initial.cluster_of(source)
    assert initial.algorithm == "louvain" and original is not None
    target = next(cluster.id for cluster in initial.clusters if cluster.id != original.id)
    decision = clusters.pin_file(clusters.Layout(), initial, source, target)

    rerun = clusters.cluster_files(model, decision.to_layout())

    assert rerun.algorithm == "louvain"
    assert rerun.cluster_of(source) is not None
    assert rerun.cluster_of(source).id == target


def test_reapplying_file_pin_is_idempotent_and_preserves_other_layout_entries() -> None:
    clustering = clusters.cluster_files(_movable_project(False))
    layout = clusters.Layout(names={"a": "Application"}, pins={"b/z.cpp": "b"})
    first = clusters.pin_file(layout, clustering, "b/stray.cpp", "a")
    second = clusters.pin_file(first.to_layout(), clustering, "b/stray.cpp", "a")

    assert first.changed
    assert not second.changed
    assert second.names == (("a", "Application"),)
    assert second.pins == (("b/stray.cpp", "a"), ("b/z.cpp", "b"))


def test_pin_file_refuses_unknown_file_or_unknown_target_cluster() -> None:
    clustering = clusters.cluster_files(_movable_project(False))
    layout = clusters.Layout(names={"a": "Application"}, pins={"b/z.cpp": "b"})

    unknown_file = clusters.pin_file(layout, clustering, "missing.cpp", "a")
    unknown_cluster = clusters.pin_file(layout, clustering, "b/stray.cpp", "missing")

    assert unknown_file == unknown_cluster == clusters.LayoutDecision(
        names=(("a", "Application"),), pins=(("b/z.cpp", "b"),), changed=False)
