"""Standard-library Python analysis and language-neutral consumer compatibility."""

from __future__ import annotations

from pathlib import Path

from icoda_core import (
    class_view,
    clusters,
    coverage_index,
    expansion,
    graph_filter,
    implementation_queue,
    mind_map,
    node_status,
    python_analysis,
    rules,
    test_selection,
    views,
)
from icoda_core.model import CALLABLE_KINDS, DerivedModel, EdgeKind, Kind
from icoda_core.persistence import ProjectState


def _write_project(root: Path) -> None:
    package = root / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("from .models import User\n", encoding="utf-8")
    (package / "models.py").write_text(
        "class User:\n"
        "    def __init__(self, name: str):\n"
        "        self.name = name\n"
        "\n"
        "    @classmethod\n"
        "    def from_name(cls, name: str) -> 'User':\n"
        "        return cls(name)\n",
        encoding="utf-8",
    )
    (package / "helpers.py").write_text(
        "def normalize(value: str) -> str:\n"
        "    return value.strip()\n",
        encoding="utf-8",
    )
    (package / "service.py").write_text(
        "from collections.abc import Iterable\n"
        "from pathlib import Path\n"
        "import json\n"
        "import never_used\n"
        "from .models import User\n"
        "from .helpers import normalize\n"
        "\n"
        "class Service:\n"
        "    def make(self, name: str) -> User:\n"
        "        clean = normalize(name)\n"
        "        return User.from_name(clean)\n"
        "\n"
        "    def all(self, values: Iterable[str]) -> list[User]:\n"
        "        return [self.make(value) for value in values]\n"
        "\n"
        "def run(service: Service, name: str) -> User:\n"
        "    Path(name)\n"
        "    json.loads(name)\n"
        "    return service.make(name)\n"
        "\n"
        "def unresolved():\n"
        "    return unknown_api()\n"
        "\n"
        "def outer():\n"
        "    def closure():\n"
        "        return normalize('nested')\n"
        "    return closure()\n",
        encoding="utf-8",
    )


def _model(tmp_path: Path) -> DerivedModel:
    _write_project(tmp_path)
    return python_analysis.parse_project(tmp_path)


def test_entities_have_existing_kinds_parents_and_source_lines(tmp_path: Path) -> None:
    model = _model(tmp_path)
    facts = {
        entity.usr: (entity.kind, entity.parent, entity.file, entity.line)
        for entity in model.entities.values()
    }
    assert facts == {
        "python:pkg.helpers:normalize": (Kind.FUNCTION, None, "pkg/helpers.py", 1),
        "python:pkg.models:User": (Kind.CLASS, None, "pkg/models.py", 1),
        "python:pkg.models:User.__init__": (
            Kind.METHOD,
            "python:pkg.models:User",
            "pkg/models.py",
            2,
        ),
        "python:pkg.models:User.from_name": (
            Kind.METHOD,
            "python:pkg.models:User",
            "pkg/models.py",
            6,
        ),
        "python:pkg.service:Service": (Kind.CLASS, None, "pkg/service.py", 8),
        "python:pkg.service:Service.make": (
            Kind.METHOD,
            "python:pkg.service:Service",
            "pkg/service.py",
            9,
        ),
        "python:pkg.service:Service.all": (
            Kind.METHOD,
            "python:pkg.service:Service",
            "pkg/service.py",
            13,
        ),
        "python:pkg.service:run": (Kind.FUNCTION, None, "pkg/service.py", 16),
        "python:pkg.service:unresolved": (Kind.FUNCTION, None, "pkg/service.py", 21),
        "python:pkg.service:outer": (Kind.FUNCTION, None, "pkg/service.py", 24),
    }
    assert set(model.files) == {
        "pkg/__init__.py",
        "pkg/helpers.py",
        "pkg/models.py",
        "pkg/service.py",
    }
    assert model.files["pkg/__init__.py"].module == "pkg"
    assert "closure" not in {entity.name for entity in model.entities.values()}


def test_project_calls_types_imports_and_external_names_are_resolved(tmp_path: Path) -> None:
    model = _model(tmp_path)
    project_calls = {
        (edge.source, edge.target)
        for edge in model.edges_of(EdgeKind.CALLS)
        if edge.target in model.entities
    }
    assert project_calls == {
        ("python:pkg.models:User.from_name", "python:pkg.models:User.__init__"),
        ("python:pkg.service:Service.make", "python:pkg.helpers:normalize"),
        ("python:pkg.service:Service.make", "python:pkg.models:User.from_name"),
        ("python:pkg.service:Service.all", "python:pkg.service:Service.make"),
        ("python:pkg.service:run", "python:pkg.service:Service.make"),
    }
    uses_types = {
        (edge.source, edge.target, edge.label)
        for edge in model.edges_of(EdgeKind.USES_TYPE)
    }
    assert {
        ("python:pkg.models:User.from_name", "python:pkg.models:User", ""),
        ("python:pkg.service:Service.make", "python:pkg.models:User", ""),
        ("python:pkg.service:Service.all", "python:pkg.models:User", ""),
        ("python:pkg.service:Service.all", "external:collections.abc", "Iterable"),
        ("python:pkg.service:run", "python:pkg.service:Service", ""),
        ("python:pkg.service:run", "python:pkg.models:User", ""),
    } <= uses_types
    assert {library: external.names for library, external in model.externals.items()} == {
        "collections.abc": ("Iterable",),
        "json": ("loads",),
        "never_used": (),
        "pathlib": ("Path",),
    }
    imports = {(edge.source, edge.target) for edge in model.edges_of(EdgeKind.IMPORTS)}
    assert ("pkg/__init__.py", "pkg/models.py") in imports
    assert ("pkg/service.py", "pkg/helpers.py") in imports
    assert ("pkg/service.py", "pkg/models.py") in imports
    unresolved = "python:pkg.service:unresolved"
    assert not model.callees(unresolved)


def test_usrs_are_deterministic_and_do_not_contain_location_data(tmp_path: Path) -> None:
    first_root, second_root = tmp_path / "first", tmp_path / "second"
    _write_project(first_root)
    _write_project(second_root)
    first = set(python_analysis.parse_project(first_root).entities)
    second = set(python_analysis.parse_project(second_root).entities)
    assert first == second
    assert all(str(first_root) not in usr and str(second_root) not in usr for usr in first)
    service = first_root / "pkg" / "service.py"
    service.write_text("\n\n" + service.read_text(encoding="utf-8"), encoding="utf-8")
    assert set(python_analysis.parse_project(first_root).entities) == first
    assert first == {
        "python:pkg.helpers:normalize",
        "python:pkg.models:User",
        "python:pkg.models:User.__init__",
        "python:pkg.models:User.from_name",
        "python:pkg.service:Service",
        "python:pkg.service:Service.all",
        "python:pkg.service:Service.make",
        "python:pkg.service:outer",
        "python:pkg.service:run",
        "python:pkg.service:unresolved",
    }


def test_body_hash_is_stable_for_unchanged_body_and_changes_for_edit(tmp_path: Path) -> None:
    first = _model(tmp_path)
    usr = "python:pkg.helpers:normalize"
    original = first.entities[usr].body_hash
    (tmp_path / "pkg" / "service.py").write_text(
        (tmp_path / "pkg" / "service.py").read_text(encoding="utf-8") + "\nUNRELATED = 1\n",
        encoding="utf-8",
    )
    unchanged = python_analysis.parse_project(tmp_path).entities[usr].body_hash
    helper = tmp_path / "pkg" / "helpers.py"
    helper.write_text(
        helper.read_text(encoding="utf-8").replace("value.strip()", "value.strip().lower()"),
        encoding="utf-8",
    )
    edited = python_analysis.parse_project(tmp_path).entities[usr].body_hash
    assert len(original) == 64 and unchanged == original and edited != original


def test_empty_invalid_and_degenerate_projects_never_raise(tmp_path: Path) -> None:
    no_python = tmp_path / "no-python"
    no_python.mkdir()
    assert python_analysis.parse_project(no_python).files == {}

    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "empty.py").write_text("", encoding="utf-8")
    (cases / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (cases / "plain.py").write_text(
        "def outer():\n"
        "    def inner():\n"
        "        return 1\n"
        "    return inner()\n",
        encoding="utf-8",
    )
    model = python_analysis.parse_project(cases)
    assert set(model.files) == {"broken.py", "empty.py", "plain.py"}
    assert model.files["broken.py"].errors
    assert not model.files["empty.py"].errors
    assert {(entity.name, entity.kind) for entity in model.entities.values()} == {
        ("outer", Kind.FUNCTION)
    }


def test_python_model_runs_through_existing_core_consumers(tmp_path: Path) -> None:
    model = _model(tmp_path)
    clustering = clusters.cluster_files(model)
    file_layout = views.layout_file_view(model, clustering)
    call_layout = views.layout_call_view(model, "python:pkg.service:Service.make")
    classes = class_view.build_class_graph(model)
    class_layout = views.layout_class_view(classes)
    coverage = coverage_index.build_index(model, [])
    appearances = node_status.derive(model, ProjectState(), [], coverage)
    cluster_by_file = {
        file: cluster.id for cluster in clustering.clusters for file in cluster.files
    }
    graph = graph_filter.project_graph(model, cluster_by_file)
    decisions = graph_filter.derive(model, graph, appearances)
    expanded = expansion.derive(
        model, graph, decisions, appearances, frozenset({"external:pathlib"})
    )
    tree = mind_map.build_mind_map(model, [])
    mind_layout = views.layout_mind_map(tree)

    assert file_layout.nodes and call_layout.nodes
    assert classes.nodes and class_layout.nodes
    assert coverage.uncovered == tuple(
        entity.usr
        for entity in sorted(
            (item for item in model.entities.values() if item.kind in CALLABLE_KINDS),
            key=lambda item: (item.qualified_name, item.signature, item.file, item.line, item.usr),
        )
    )
    assert appearances and decisions and mind_layout.nodes
    children = expanded.decisions["external:pathlib"].children
    assert [expanded.decisions[key].key for key in children]
    assert {node.label for node in expanded.graph.nodes if node.key in children} == {"Path"}
    assert implementation_queue.build(model) == ()
    assert test_selection.select_tests(model, [], "python:pkg.helpers:normalize") == ()
    assert isinstance(rules.check(model, []), tuple)
