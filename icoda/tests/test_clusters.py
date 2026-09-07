"""Clustering: every file in exactly one cluster, directories as seeds, no collapse, splitting, pins."""

from __future__ import annotations

from icoda_core import clusters
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
