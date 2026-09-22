"""Pure Python-to-:class:`~icoda_core.model.DerivedModel` analysis.

The front end parses source with :mod:`ast`; it never imports or executes the
analysed project.  It maps Python onto the existing language-neutral model as
follows (``module`` is the root-relative dotted module path):

========================  ======================  ================================
Python construct          Existing model value    Stable synthetic USR
========================  ======================  ================================
``path/to/mod.py``        ``FileInfo``            no USR; ``path/to/mod.py``
``class Widget``          ``Kind.CLASS``          ``python:module:Widget``
module ``def build``      ``Kind.FUNCTION``       ``python:module:build``
class ``def render``      ``Kind.METHOD``         ``python:module:Widget.render``
========================  ======================  ================================

Nested classes extend the qualified-name portion in the same way.  Nested
functions and closures are deliberately not entities: the current model has no
local-function kind or callable-parent semantics.  The scheme contains neither
absolute paths nor source positions, so unrelated edits cannot change an
entity's identity.  Methods use their owning class's USR as ``Entity.parent``.
Calls are emitted only when same-module definitions, explicit imports,
``self``/``cls``, or annotated locals resolve them.  Dynamic or otherwise
uncertain calls are omitted instead of being guessed because the existing
``Edge`` schema has no uncertainty field.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from icoda_core.bodyhash import body_hash
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, External, FileInfo, Kind

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
PYTHON_SOURCE_EXCLUDED_DIRECTORIES = frozenset({
    "build", "dist", "node_modules", "site-packages",
})
PYTHON_SOURCE_EXCLUDE_PATTERN = (
    rf"(?:^|[\\/])\.[^\\/]+[\\/]"
    rf"|(?:^|[\\/])(?:{'|'.join(re.escape(name) for name in sorted(PYTHON_SOURCE_EXCLUDED_DIRECTORIES))})"
    r"(?:[\\/]|$)"
)


@dataclass(frozen=True)
class _Import:
    local: str
    module: str
    symbol: str | None = None
    prefix: tuple[str, ...] = ()
    project: bool = False


@dataclass
class _Module:
    name: str
    file: str
    path: Path
    source: str
    tree: ast.Module
    is_package: bool
    imports: dict[str, _Import] = field(default_factory=dict)


@dataclass
class _Context:
    model: DerivedModel
    modules: dict[str, _Module]
    symbols: dict[tuple[str, str], str]
    members: dict[tuple[str, str], str]
    edges: set[Edge]


def parse_project(root: Path) -> DerivedModel:
    """Parse every ``.py`` below ``root`` and return a non-stale derived model.

    A syntax-invalid file remains present as a :class:`FileInfo` with an error,
    but contributes no entities or edges.  Missing, empty, and Python-free
    directories therefore return valid (possibly empty) models.
    """
    model = DerivedModel(str(root.resolve()))
    modules = _read_modules(root, model)
    context = _Context(model, modules, {}, {}, set())
    for module in modules.values():
        module.imports = _collect_imports(module, modules)
        _add_import_facts(context, module)
    for module in modules.values():
        _collect_entities(context, module, module.tree.body, None, ())
    for entity in model.entities.values():
        if entity.parent is not None:
            context.members.setdefault((entity.parent, entity.name), entity.usr)
    for module in modules.values():
        _collect_relations(context, module, module.tree.body, None, ())
        _ExternalUses(context, module).visit(module.tree)
    return model


def _add_edge(context: _Context, edge: Edge) -> None:
    if edge not in context.edges:
        context.edges.add(edge)
        context.model.edges.append(edge)


def find_python_sources(root: Path, *, virtual_environments: list[Path] | None = None) -> tuple[Path, ...]:
    """Discover project Python files, optionally reporting root-relative virtual environments."""
    sources: list[Path] = []
    for directory, subdirectories, files in os.walk(root):
        directory_path = Path(directory)
        if "pyvenv.cfg" in files:
            subdirectories.clear()
            if virtual_environments is not None:
                virtual_environments.append(directory_path.relative_to(root))
            continue
        subdirectories[:] = sorted(
            name for name in subdirectories
            if not name.startswith(".") and name not in PYTHON_SOURCE_EXCLUDED_DIRECTORIES
        )
        sources.extend(directory_path / name for name in sorted(files) if name.endswith(".py"))
    return tuple(sources)


def _read_modules(root: Path, model: DerivedModel) -> dict[str, _Module]:
    modules: dict[str, _Module] = {}
    for path in find_python_sources(root):
        relative = path.relative_to(root).as_posix()
        try:
            raw = path.read_bytes()
        except OSError as exc:
            model.files[relative] = FileInfo(relative, errors=(str(exc),))
            continue
        name, package = _module_name(Path(relative))
        digest = hashlib.sha1(raw).hexdigest()
        try:
            source = raw.decode("utf-8-sig")
            tree = ast.parse(source, filename=relative)
        except (SyntaxError, UnicodeDecodeError) as exc:
            model.files[relative] = FileInfo(relative, name, "source", digest, (_parse_error(exc),))
            continue
        model.files[relative] = FileInfo(relative, name, "source", digest)
        modules[name] = _Module(name, relative, path, source, tree, package)
    return modules


def _module_name(relative: Path) -> tuple[str, bool]:
    parts = list(relative.with_suffix("").parts)
    package = bool(parts and parts[-1] == "__init__")
    if package:
        parts = parts[:-1]
    return (".".join(parts) or "__init__", package)


def _parse_error(exc: SyntaxError | UnicodeDecodeError) -> str:
    if isinstance(exc, SyntaxError):
        location = f" line {exc.lineno}" if exc.lineno is not None else ""
        return f"{exc.msg}{location}"
    return str(exc)


def _collect_imports(module: _Module, modules: dict[str, _Module]) -> dict[str, _Import]:
    imports: dict[str, _Import] = {}
    for node in _module_nodes(module.tree.body):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                prefix = () if alias.asname else tuple(alias.name.split(".")[1:])
                imports[local] = _Import(local, alias.name, prefix=prefix, project=alias.name in modules)
        elif isinstance(node, ast.ImportFrom):
            source = _absolute_import(module, node)
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                candidate = f"{source}.{alias.name}" if source else alias.name
                if candidate in modules:
                    imports[local] = _Import(local, candidate, project=True)
                else:
                    imports[local] = _Import(local, source, alias.name, project=source in modules)
    return imports


def _module_nodes(statements: list[ast.stmt]) -> list[ast.stmt]:
    result: list[ast.stmt] = []
    pending = deque(statements)
    while pending:
        node = pending.popleft()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        result.append(node)
        for value in ast.iter_child_nodes(node):
            if isinstance(value, ast.stmt):
                pending.append(value)
    return result


def _absolute_import(module: _Module, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = module.name if module.is_package else module.name.rpartition(".")[0]
    parts = package.split(".") if package else []
    keep = max(0, len(parts) - node.level + 1)
    base = parts[:keep]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _add_import_facts(context: _Context, module: _Module) -> None:
    seen: set[tuple[str, str]] = set()
    for imported in module.imports.values():
        target_module = context.modules.get(imported.module)
        if imported.project and target_module is not None:
            target, library = target_module.file, ""
        else:
            library = imported.module
            target = f"external:{library}"
            context.model.externals.setdefault(library, External(library))
        if library or target_module is not None:
            key = (target, imported.module)
            if key not in seen:
                _add_edge(
                    context,
                    Edge(EdgeKind.IMPORTS, module.file, target, module.file, label=imported.module)
                )
                seen.add(key)


def _collect_entities(
    context: _Context,
    module: _Module,
    statements: list[ast.stmt],
    owner_usr: str | None,
    scope: tuple[str, ...],
) -> None:
    for node in statements:
        if isinstance(node, ast.ClassDef):
            qualified = (*scope, node.name)
            entity = _entity(module, node, Kind.CLASS, owner_usr, qualified)
            context.model.add_entity(entity)
            context.symbols[(module.name, ".".join(qualified))] = entity.usr
            _collect_entities(context, module, node.body, entity.usr, qualified)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if owner_usr is None or _owner_is_class(context.model, owner_usr):
                kind = Kind.METHOD if owner_usr else Kind.FUNCTION
                qualified = (*scope, node.name)
                entity = _entity(module, node, kind, owner_usr, qualified)
                context.model.add_entity(entity)
                context.symbols[(module.name, ".".join(qualified))] = entity.usr
        else:
            for body in _statement_bodies(node):
                _collect_entities(context, module, body, owner_usr, scope)


def _owner_is_class(model: DerivedModel, usr: str) -> bool:
    owner = model.entities.get(usr)
    return owner is not None and owner.kind == Kind.CLASS


def _entity(
    module: _Module, node: ast.ClassDef | FunctionNode, kind: Kind, parent: str | None, parts: tuple[str, ...]
) -> Entity:
    qualified = f"{module.name}.{'.'.join(parts)}"
    digest = (
        _function_body_hash(module.source, node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        else ""
    )
    return Entity(
        _usr(module.name, parts),
        kind,
        node.name,
        qualified,
        module.file,
        node.lineno,
        getattr(node, "end_lineno", node.lineno) or node.lineno,
        parent,
        _signature(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "",
        _brief(node),
        body_hash=digest,
        declaration_file="",
    )


def _usr(module: str, parts: tuple[str, ...]) -> str:
    return f"python:{module}:{'.'.join(parts)}"


def _signature(node: FunctionNode) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    return f"{prefix} {node.name}({_arguments(node.args)}){returns}"


def _arguments(arguments: ast.arguments) -> str:
    rendered: list[str] = []
    positional = [*arguments.posonlyargs, *arguments.args]
    default_at = len(positional) - len(arguments.defaults)
    for index, argument in enumerate(positional):
        value = _argument(argument)
        if index >= default_at:
            value += f"={ast.unparse(arguments.defaults[index - default_at])}"
        rendered.append(value)
        if arguments.posonlyargs and index + 1 == len(arguments.posonlyargs):
            rendered.append("/")
    if arguments.vararg:
        rendered.append(f"*{_argument(arguments.vararg)}")
    elif arguments.kwonlyargs:
        rendered.append("*")
    for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        rendered.append(_argument(argument) + (f"={ast.unparse(default)}" if default else ""))
    if arguments.kwarg:
        rendered.append(f"**{_argument(arguments.kwarg)}")
    return ", ".join(rendered)


def _argument(argument: ast.arg) -> str:
    annotation = f": {ast.unparse(argument.annotation)}" if argument.annotation is not None else ""
    return argument.arg + annotation


def _brief(node: ast.ClassDef | FunctionNode) -> str:
    doc = ast.get_docstring(node, clean=True) or ""
    return " ".join(doc.split("\n\n", 1)[0].split())


def _function_body_hash(source: str, node: FunctionNode) -> str:
    statements = node.body[1:] if ast.get_docstring(node) is not None else node.body
    chunks = [ast.get_source_segment(source, statement) or "" for statement in statements]
    return body_hash("\n".join(chunks))


def _statement_bodies(node: ast.stmt) -> list[list[ast.stmt]]:
    bodies: list[list[ast.stmt]] = []
    for name in ("body", "orelse", "finalbody"):
        value = getattr(node, name, None)
        if isinstance(value, list) and all(isinstance(item, ast.stmt) for item in value):
            bodies.append(value)
    for handler in getattr(node, "handlers", []):
        bodies.append(handler.body)
    return bodies


def _collect_relations(
    context: _Context,
    module: _Module,
    statements: list[ast.stmt],
    owner_usr: str | None,
    scope: tuple[str, ...],
) -> None:
    for node in statements:
        if isinstance(node, ast.ClassDef):
            parts = (*scope, node.name)
            usr = context.symbols[(module.name, ".".join(parts))]
            _class_relations(context, module, node, usr)
            _collect_relations(context, module, node.body, usr, parts)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parts = (*scope, node.name)
            function_usr = context.symbols.get((module.name, ".".join(parts)))
            if function_usr is not None:
                _function_relations(context, module, node, function_usr, scope)
        else:
            for body in _statement_bodies(node):
                _collect_relations(context, module, body, owner_usr, scope)


def _class_relations(context: _Context, module: _Module, node: ast.ClassDef, usr: str) -> None:
    for base in node.bases:
        target = _resolve_type(context, module, base)
        if target is not None:
            _add_edge(
                context,
                Edge(EdgeKind.INHERITS, usr, target[0], module.file, node.lineno, target[1])
            )
    for statement in node.body:
        if isinstance(statement, ast.AnnAssign):
            _annotation_edges(context, module, usr, statement.annotation, statement.lineno)


def _function_relations(
    context: _Context, module: _Module, node: FunctionNode, usr: str, class_scope: tuple[str, ...]
) -> None:
    annotations = [
        argument.annotation
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        if argument.annotation is not None
    ]
    if node.args.vararg and node.args.vararg.annotation:
        annotations.append(node.args.vararg.annotation)
    if node.args.kwarg and node.args.kwarg.annotation:
        annotations.append(node.args.kwarg.annotation)
    if node.returns is not None:
        annotations.append(node.returns)
    for annotation in annotations:
        _annotation_edges(context, module, usr, annotation, annotation.lineno)
    visitor = _CallVisitor(
        context, module, usr, class_scope if class_scope else (), _parameter_types(context, module, node)
    )
    for statement in node.body:
        visitor.visit(statement)


def _parameter_types(context: _Context, module: _Module, node: FunctionNode) -> dict[str, str]:
    result: dict[str, str] = {}
    arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
    for argument in arguments:
        if argument.annotation is None:
            continue
        resolved = _resolve_type(context, module, argument.annotation)
        if resolved is not None and _is_class(context.model, resolved[0]):
            result[argument.arg] = resolved[0]
    return result


def _annotation_edges(
    context: _Context, module: _Module, source: str, annotation: ast.expr, line: int
) -> None:
    for expression in _annotation_parts(annotation):
        target = _resolve_type(context, module, expression)
        if target is not None and target[0] != source:
            _add_edge(context, Edge(EdgeKind.USES_TYPE, source, target[0], module.file, line, target[1]))


def _annotation_parts(annotation: ast.expr) -> list[ast.expr]:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            return _annotation_parts(ast.parse(annotation.value, mode="eval").body)
        except SyntaxError:
            return []
    if isinstance(annotation, (ast.Name, ast.Attribute)):
        return [annotation]
    parts: list[ast.expr] = []
    for child in ast.iter_child_nodes(annotation):
        if isinstance(child, ast.expr):
            parts.extend(_annotation_parts(child))
    return parts


def _resolve_type(context: _Context, module: _Module, expression: ast.expr) -> tuple[str, str] | None:
    chain = _name_chain(expression)
    if not chain:
        return None
    project = _resolve_project_chain(context, module, chain)
    if project is not None:
        return (project, "")
    external = _external_reference(module, chain)
    if external is None:
        return None
    library, name = external
    _record_external(context.model, library, name)
    return (f"external:{library}", name)


def _resolve_project_chain(context: _Context, module: _Module, chain: tuple[str, ...]) -> str | None:
    if not chain:
        return None
    direct = context.symbols.get((module.name, ".".join(chain)))
    if direct is not None:
        return direct
    imported = module.imports.get(chain[0])
    if imported is None or not imported.project:
        return None
    tail = chain[1:]
    if imported.symbol is not None:
        qualified = (imported.symbol, *tail)
    else:
        qualified = tail[len(imported.prefix) :] if tail[: len(imported.prefix)] == imported.prefix else tail
    target = context.symbols.get((imported.module, ".".join(qualified)))
    return target


def _constructor(context: _Context, usr: str) -> str | None:
    entity = context.model.entities.get(usr)
    if entity is None or entity.kind != Kind.CLASS:
        return usr
    return context.members.get((usr, "__init__"))


def _is_class(model: DerivedModel, usr: str) -> bool:
    entity = model.entities.get(usr)
    return entity is not None and entity.kind == Kind.CLASS


def _class_member(context: _Context, class_usr: str, name: str) -> str | None:
    return context.members.get((class_usr, name))


def _name_chain(node: ast.AST) -> tuple[str, ...]:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return ()
    return (current.id, *reversed(parts))


def _external_reference(module: _Module, chain: tuple[str, ...]) -> tuple[str, str] | None:
    if not chain:
        return None
    imported = module.imports.get(chain[0])
    if imported is None or imported.project:
        return None
    if imported.symbol is not None:
        return (imported.module, imported.symbol)
    tail = chain[1:]
    if imported.prefix and tail[: len(imported.prefix)] == imported.prefix:
        tail = tail[len(imported.prefix) :]
    return (imported.module, ".".join(tail)) if tail else None


def _record_external(model: DerivedModel, library: str, name: str) -> None:
    external = model.externals.setdefault(library, External(library))
    if name:
        model.externals[library] = External(library, tuple(sorted({*external.names, name})))


class _CallVisitor(ast.NodeVisitor):
    def __init__(self, context: _Context, module: _Module, source: str,
                 class_scope: tuple[str, ...], local_types: dict[str, str]) -> None:
        self.context = context
        self.module = module
        self.source = source
        self.class_scope = class_scope
        self.local_types = local_types

    def visit_Call(self, node: ast.Call) -> None:
        target = self._target(node.func)
        if target is not None and target[0] != self.source:
            _add_edge(
                self.context,
                Edge(EdgeKind.CALLS, self.source, target[0], self.module.file, node.lineno, target[1], uncertain=False)
            )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Assign(self, node: ast.Assign) -> None:
        class_usr = self._constructed_class(node.value)
        if class_usr is not None:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.local_types[target.id] = class_usr
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        resolved = _resolve_type(self.context, self.module, node.annotation)
        if isinstance(node.target, ast.Name) and resolved is not None and _is_class(
            self.context.model, resolved[0]
        ):
            self.local_types[node.target.id] = resolved[0]
        self.generic_visit(node)

    def _target(self, expression: ast.expr) -> tuple[str, str] | None:
        chain = _name_chain(expression)
        if not chain:
            return self._constructed_member(expression)
        if chain[0] in {"self", "cls"} and self.class_scope:
            usr = self.context.symbols.get((self.module.name, ".".join((*self.class_scope, *chain[1:]))))
        elif chain[0] in self.local_types and len(chain) == 2:
            usr = _class_member(self.context, self.local_types[chain[0]], chain[1])
        else:
            usr = _resolve_project_chain(self.context, self.module, chain)
        if usr is not None:
            callable_usr = _constructor(self.context, usr)
            return (callable_usr, "") if callable_usr is not None else None
        external = _external_reference(self.module, chain)
        if external is None:
            return None
        library, name = external
        _record_external(self.context.model, library, name)
        return (f"external:{library}", name)

    def _constructed_class(self, expression: ast.expr) -> str | None:
        if not isinstance(expression, ast.Call):
            return None
        usr = _resolve_project_chain(self.context, self.module, _name_chain(expression.func))
        return usr if usr is not None and _is_class(self.context.model, usr) else None

    def _constructed_member(self, expression: ast.expr) -> tuple[str, str] | None:
        if not isinstance(expression, ast.Attribute):
            return None
        class_usr = self._constructed_class(expression.value)
        if class_usr is None:
            return None
        member = _class_member(self.context, class_usr, expression.attr)
        return (member, "") if member is not None else None


class _ExternalUses(ast.NodeVisitor):
    def __init__(self, context: _Context, module: _Module) -> None:
        self.context = context
        self.module = module

    def visit_Attribute(self, node: ast.Attribute) -> None:
        chain = _name_chain(node)
        reference = _external_reference(self.module, chain)
        if reference is None:
            self.generic_visit(node)
        else:
            _record_external(self.context.model, *reference)

    def visit_Name(self, node: ast.Name) -> None:
        if not isinstance(node.ctx, ast.Load):
            return
        imported = self.module.imports.get(node.id)
        if imported is not None and not imported.project and imported.symbol is not None:
            _record_external(self.context.model, imported.module, imported.symbol)
