"""Derived model: entities, edges, USR identity, JSON round trip.

The model is derived from the code by ``icoda_core.analysis`` and cached; it is never edited by hand.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Kind(str, Enum):
    NAMESPACE = "namespace"
    STRUCT = "struct"
    CLASS = "class"
    ENUM = "enum"
    ENUMERATOR = "enumerator"
    FUNCTION = "function"
    METHOD = "method"
    CONSTRUCTOR = "constructor"
    DESTRUCTOR = "destructor"
    FIELD = "field"
    VARIABLE = "variable"
    ALIAS = "alias"


class EdgeKind(str, Enum):
    CALLS = "calls"
    INHERITS = "inherits"
    USES_TYPE = "uses-type"
    INCLUDES = "includes"
    IMPORTS = "imports"


CALLABLE_KINDS = frozenset({Kind.FUNCTION, Kind.METHOD, Kind.CONSTRUCTOR, Kind.DESTRUCTOR})
TYPE_KINDS = frozenset({Kind.STRUCT, Kind.CLASS, Kind.ENUM, Kind.ALIAS})


@dataclass
class Entity:
    """One declared thing, identified by its libclang USR."""

    usr: str
    kind: Kind
    name: str
    qualified_name: str
    file: str
    line: int
    end_line: int = 0
    parent: str | None = None
    signature: str = ""
    brief: str = ""
    satisfies: tuple[str, ...] = ()
    template_params: tuple[str, ...] = ()
    is_definition: bool = True
    exported: bool = False
    value: str = ""
    body_hash: str = ""
    test_files: tuple[str, ...] = ()
    status: str = "implemented"
    declaration_file: str = ""


@dataclass(frozen=True)
class Edge:
    """A relation; call ``label`` carries template arguments and ``uncertain`` marks dynamic dispatch."""

    kind: EdgeKind
    source: str
    target: str
    file: str = ""
    line: int = 0
    label: str = ""
    uncertain: bool = False


@dataclass
class FileInfo:
    """One parsed translation unit or a file reached through it."""

    path: str
    module: str = ""
    unit: str = "source"
    content_hash: str = ""
    errors: tuple[str, ...] = ()


@dataclass
class External:
    """A library outside the project, shown as one node: the names of its entities the project uses."""

    library: str
    names: tuple[str, ...] = ()


@dataclass
class DerivedModel:
    """Everything the views and the step protocol need, keyed by USR."""

    root: str
    libclang_version: str = ""
    files: dict[str, FileInfo] = field(default_factory=dict)
    entities: dict[str, Entity] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    externals: dict[str, External] = field(default_factory=dict)
    stale: bool = False
    stale_reason: str = ""

    def add_entity(self, entity: Entity) -> None:
        """Keep the definition over a declaration for the same USR."""
        existing = self.entities.get(entity.usr)
        if existing is None or (entity.is_definition and not existing.is_definition):
            self.entities[entity.usr] = entity

    def resolve_legacy_main(self, usr: str, files: Iterable[str] = ()) -> str:
        """Keep old main history/queue references attached to their source after entry-point disambiguation."""
        if usr in self.entities or "@entry:" in usr:
            return usr
        mains = [entity for entity in self.entities.values()
                 if entity.qualified_name == "main" and entity.usr.startswith(usr + "@entry:")]
        relevant = [entity for entity in mains if entity.file in files] or mains
        # Before disambiguation, declaration pairing kept the first definition by source path.
        return min(relevant, key=lambda entity: entity.file).usr if relevant else usr

    def add_edge(self, edge: Edge) -> None:
        if edge not in self._edge_set():
            self.edges.append(edge)

    def _edge_set(self) -> set[Edge]:
        cached = getattr(self, "_edges_seen", None)
        if cached is None or len(cached) != len(self.edges):
            cached = set(self.edges)
            object.__setattr__(self, "_edges_seen", cached)
        return cached

    def entities_in(self, file: str) -> list[Entity]:
        return [e for e in self.entities.values() if e.file == file]

    def children(self, usr: str) -> list[Entity]:
        return [e for e in self.entities.values() if e.parent == usr]

    def edges_of(self, kind: EdgeKind) -> Iterator[Edge]:
        return (edge for edge in self.edges if edge.kind == kind)

    def callees(self, usr: str) -> list[Edge]:
        return [e for e in self.edges if e.kind == EdgeKind.CALLS and e.source == usr]

    def callers(self, usr: str) -> list[Edge]:
        return [e for e in self.edges if e.kind == EdgeKind.CALLS and e.target == usr]

    def file_of(self, usr: str) -> str | None:
        entity = self.entities.get(usr)
        return entity.file if entity else None

    def file_edges(self) -> dict[tuple[str, str, EdgeKind], int]:
        """Relations aggregated to file level: (source file, target file, kind) -> count."""
        counts: dict[tuple[str, str, EdgeKind], int] = defaultdict(int)
        for edge in self.edges:
            source, target = self._endpoint_file(edge.source), self._endpoint_file(edge.target)
            if source and target and source != target:
                counts[(source, target, edge.kind)] += 1
        return dict(counts)

    def _endpoint_file(self, endpoint: str) -> str | None:
        if endpoint in self.files:
            return endpoint
        return self.file_of(endpoint)

    def to_json(self) -> str:
        data = {"root": self.root, "libclang_version": self.libclang_version, "stale": self.stale,
                "stale_reason": self.stale_reason,
                "files": [asdict(f) for f in self.files.values()],
                "entities": [_entity_dict(e) for e in self.entities.values()],
                "edges": [_edge_dict(e) for e in self.edges],
                "externals": [asdict(x) for x in self.externals.values()]}
        return json.dumps(data, indent=1)

    @classmethod
    def from_json(cls, text: str) -> DerivedModel:
        data = json.loads(text)
        model = cls(data["root"], data.get("libclang_version", ""), stale=data.get("stale", False),
                    stale_reason=data.get("stale_reason", ""))
        model.files = {f["path"]: FileInfo(f["path"], f["module"], f["unit"], f["content_hash"], tuple(f["errors"]))
                       for f in data["files"]}
        model.entities = {e["usr"]: _entity_from(e) for e in data["entities"]}
        model.edges = [Edge(EdgeKind(e["kind"]), e["source"], e["target"], e["file"], e["line"], e["label"],
                            e.get("uncertain", False))
                       for e in data["edges"]]
        model.externals = {x["library"]: External(x["library"], tuple(x["names"])) for x in data["externals"]}
        return model

    def save(self, path: Path) -> None:
        # Local import avoids the persistence -> model -> persistence cycle.
        from icoda_core.persistence import _atomic_write_text
        _atomic_write_text(path, self.to_json())

    @classmethod
    def load(cls, path: Path) -> DerivedModel:
        return cls.from_json(path.read_text(encoding="utf-8"))


def _entity_dict(entity: Entity) -> dict[str, Any]:
    data = asdict(entity)
    data["kind"] = entity.kind.value
    data["satisfies"] = list(entity.satisfies)
    data["template_params"] = list(entity.template_params)
    data["test_files"] = list(entity.test_files)
    return data


def _entity_from(data: dict[str, Any]) -> Entity:
    data = dict(data)
    data["kind"] = Kind(data["kind"])
    data["satisfies"] = tuple(data["satisfies"])
    data["template_params"] = tuple(data["template_params"])
    data["body_hash"] = str(data.get("body_hash", ""))
    data["test_files"] = tuple(data.get("test_files", ()))
    data.setdefault("declaration_file", "")
    return Entity(**data)


def _edge_dict(edge: Edge) -> dict[str, Any]:
    data = asdict(edge)
    data["kind"] = edge.kind.value
    return data


def merge_external_names(model: DerivedModel, library: str, names: Iterable[str]) -> None:
    """Record that the project uses ``names`` from ``library``."""
    existing = model.externals.get(library)
    merged = tuple(sorted(set(existing.names if existing else ()) | set(names)))
    model.externals[library] = External(library, merged)


def is_test_file(path: str) -> bool:
    """Recognise conventional test source paths without depending on one C++ test framework."""
    lowered = Path(path).as_posix().lower()
    stem = Path(lowered).stem
    return "tests" in Path(lowered).parts or stem.startswith("test_") or stem.endswith(("_test", "_tests"))


def associate_test_files(model: DerivedModel) -> None:
    """Attach each test source to the project callables reachable from calls made in that source."""
    pending = [(edge.target, edge.file) for edge in model.edges_of(EdgeKind.CALLS) if is_test_file(edge.file)]
    pending.extend((entity.usr, entity.file) for entity in model.entities.values()
                   if entity.kind in CALLABLE_KINDS and is_test_file(entity.file))
    associations: dict[str, set[str]] = defaultdict(set)
    while pending:
        usr, test_file = pending.pop()
        entity = model.entities.get(usr)
        if entity is None or test_file in associations[usr]:
            continue
        associations[usr].add(test_file)
        pending.extend((edge.target, test_file) for edge in model.callees(usr))
    for usr, files in associations.items():
        model.entities[usr].test_files = tuple(sorted(files))
