"""Parsing a project with libclang into the derived model; incremental cache; stale marking.

Module interface units are parsed twice: once as written (only to tokenize), then from memory as a
*shadow*: still the same module interface unit, with declaration ``export`` keywords blanked, because libclang does
not visit the declarations inside an ``export``. Offsets are preserved, so locations and USRs match
what call sites in other units reference. Implementation units and ordinary sources need no shadow.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from clang import cindex

from icoda_core import persistence
from icoda_core.bodyhash import body_hash
from icoda_core.model import (
    DerivedModel,
    Edge,
    EdgeKind,
    Entity,
    External,
    FileInfo,
    Kind,
    associate_test_files,
)

MODULE_SUFFIXES = frozenset({".cppm", ".ixx", ".mpp", ".cxxm", ".c++m", ".ccm"})
HEADER_SUFFIXES = frozenset({".h", ".hh", ".hpp", ".hxx", ".h++", ".inl"})
UNIT_CACHE_VERSION = 6
CPP_SUFFIXES = MODULE_SUFFIXES | HEADER_SUFFIXES | frozenset({".c", ".cc", ".cpp", ".cxx", ".c++"})
CPP_LANGUAGE = "C++"
PYTHON_LANGUAGE = "Python"
_MODULE_DECL = re.compile(r"^\s*(export\s+)?module\s+([A-Za-z_][\w.:]*)\s*;", re.MULTILINE)
_NEEDS_SHADOW = re.compile(r"^\s*export\s+module\b", re.MULTILINE)

CK = cindex.CursorKind
_KINDS = {
    CK.NAMESPACE: Kind.NAMESPACE, CK.STRUCT_DECL: Kind.STRUCT, CK.CLASS_DECL: Kind.CLASS,
    CK.CLASS_TEMPLATE: Kind.CLASS, CK.ENUM_DECL: Kind.ENUM, CK.ENUM_CONSTANT_DECL: Kind.ENUMERATOR,
    CK.FUNCTION_DECL: Kind.FUNCTION, CK.FUNCTION_TEMPLATE: Kind.FUNCTION, CK.CXX_METHOD: Kind.METHOD,
    CK.CONSTRUCTOR: Kind.CONSTRUCTOR, CK.DESTRUCTOR: Kind.DESTRUCTOR, CK.FIELD_DECL: Kind.FIELD,
    CK.VAR_DECL: Kind.VARIABLE, CK.TYPE_ALIAS_DECL: Kind.ALIAS, CK.TYPEDEF_DECL: Kind.ALIAS,
}
_CALLABLE = {CK.FUNCTION_DECL, CK.FUNCTION_TEMPLATE, CK.CXX_METHOD, CK.CONSTRUCTOR, CK.DESTRUCTOR}
_TYPE_DECLS = {CK.STRUCT_DECL, CK.CLASS_DECL, CK.CLASS_TEMPLATE, CK.ENUM_DECL, CK.TYPE_ALIAS_DECL, CK.TYPEDEF_DECL,
               CK.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION}
_TEMPLATE_PARAMS = {CK.TEMPLATE_TYPE_PARAMETER, CK.TEMPLATE_NON_TYPE_PARAMETER, CK.TEMPLATE_TEMPLATE_PARAMETER}
_REFERENCE_TYPES = {cindex.TypeKind.POINTER, cindex.TypeKind.LVALUEREFERENCE, cindex.TypeKind.RVALUEREFERENCE}
CACHE_VERSION = "dynamic-calls-v1"


# --------------------------------------------------------------------------- compile commands

@dataclass(frozen=True)
class CompileCommand:
    """One translation unit: the file, where it is compiled, and the cleaned compiler arguments."""

    file: str
    directory: str
    arguments: tuple[str, ...]
    compiler: str
    module_unit: bool


@dataclass(frozen=True)
class CallDispatch:
    """Plain facts extracted from one call site; independent of libclang cursor objects."""

    member: bool
    virtual: bool
    receiver_indirect: bool
    final: bool = False
    fully_qualified: bool = False


def is_uncertain_call(dispatch: CallDispatch) -> bool:
    """Whether a call can dynamically select an override rather than its static target."""
    return (dispatch.member and dispatch.virtual and dispatch.receiver_indirect
            and not dispatch.final and not dispatch.fully_qualified)


@dataclass(frozen=True)
class LogicalPairing:
    """Deterministically merged plain-Python entities and their relations."""

    entities: tuple[Entity, ...]
    edges: tuple[Edge, ...]


def pair_declarations(entities: Sequence[Entity], edges: Sequence[Edge]) -> LogicalPairing:
    """Pair extracted declarations by USR, with a definition owning body and location facts.

    ``Entity`` carries the already-extracted cursor facts needed here: USR, kind, file,
    definition flag and enclosing class (``parent``).  Therefore this decision is independent
    of libclang and the filesystem.  Identical non-empty USRs are one logical entity regardless
    of file; kind and parent participate only in deterministic ordering because libclang USRs
    already encode that identity.
    """
    groups: dict[str, list[Entity]] = {}
    for entity in sorted(entities, key=_entity_pairing_order):
        groups.setdefault(entity.usr, []).append(entity)

    merged: list[Entity] = []
    paired_sources: set[str] = set()
    for usr in sorted(groups):
        candidates = groups[usr]
        owner = min(candidates, key=_entity_pairing_order)
        declaration_files = sorted({
            path
            for entity in candidates
            for path in (entity.declaration_file, entity.file if not entity.is_definition else "")
            if path
        })
        brief = owner.brief or next((entity.brief for entity in candidates if entity.brief), "")
        merged.append(replace(owner, brief=brief,
                              declaration_file=declaration_files[0] if declaration_files else ""))
        if len(candidates) > 1:
            paired_sources.add(usr)

    owners = {entity.usr: entity for entity in merged}
    unique_edges: dict[tuple[str, str, str, str, bool, str, int], Edge] = {}
    for edge in sorted(edges, key=_edge_pairing_order):
        if edge.source in paired_sources and edge.kind != EdgeKind.CALLS:
            key = (edge.kind.value, edge.source, edge.target, edge.label, edge.uncertain, "", 0)
        else:
            key = (edge.kind.value, edge.source, edge.target, edge.label, edge.uncertain,
                   edge.file, edge.line)
        current = unique_edges.get(key)
        owner_file = owners[edge.source].file if edge.source in owners else ""
        if current is None or _edge_owner_order(edge, owner_file) < _edge_owner_order(current, owner_file):
            unique_edges[key] = edge
    return LogicalPairing(tuple(merged), tuple(sorted(unique_edges.values(), key=_edge_pairing_order)))


def _entity_pairing_order(entity: Entity) -> tuple[str, bool, str, str, str, int, int]:
    return (entity.usr, not entity.is_definition, entity.file, entity.kind.value,
            entity.parent or "", entity.line, entity.end_line)


def _edge_pairing_order(edge: Edge) -> tuple[str, str, str, str, int, str, bool]:
    return (edge.kind.value, edge.source, edge.target, edge.file, edge.line, edge.label, edge.uncertain)


def _edge_owner_order(edge: Edge, owner_file: str) -> tuple[bool, str, int]:
    return (edge.file != owner_file, edge.file, edge.line)


def find_compile_commands(root: Path) -> Path | None:
    """Newest ``compile_commands.json`` under the project: the root, ``build/``, or ``build/<preset>/``."""
    found = [p for p in (root / "compile_commands.json", *root.glob("build/compile_commands.json"),
                         *root.glob("build/*/compile_commands.json")) if p.is_file()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def load_compile_commands(location: Path) -> list[CompileCommand]:
    path = location if location.is_file() else find_compile_commands(location)
    if path is None:
        return []
    commands = []
    for entry in json.loads(path.read_text(encoding="utf-8")):
        raw = entry["arguments"] if "arguments" in entry else split_command_line(entry["command"])
        directory = entry["directory"]
        file = str((Path(directory) / entry["file"]).resolve())
        expanded = expand_response_files(raw[1:], directory)
        arguments = clean_arguments(expanded, file, directory)
        module_unit = Path(file).suffix in MODULE_SUFFIXES or "c++-module" in arguments
        commands.append(CompileCommand(file, directory, tuple(arguments), raw[0], module_unit))
    return commands


def split_command_line(command: str, platform: str = sys.platform) -> list[str]:
    """Decode compiler arguments without treating Windows path separators as shell escapes."""
    if platform != "win32":
        return shlex.split(command)
    arguments: list[str] = []
    token: list[str] = []
    quoted = started = False
    index = 0
    while index < len(command):
        char = command[index]
        if char.isspace() and not quoted:
            if started:
                arguments.append("".join(token))
                token = []
                started = False
        else:
            started = True
            if char == "\\":
                end = index
                while end < len(command) and command[end] == "\\":
                    end += 1
                count = end - index
                if end < len(command) and command[end] == '"':
                    token.extend("\\" * (count // 2))
                    if count % 2:
                        token.append('"')
                    else:
                        quoted = not quoted
                    index = end
                else:
                    token.extend("\\" * count)
                    index = end - 1
            elif char == '"':
                if quoted and command[index:index + 2] == '""':
                    token.append('"')
                    index += 1
                else:
                    quoted = not quoted
            else:
                token.append(char)
        index += 1
    if started:
        arguments.append("".join(token))
    return arguments


def expand_response_files(arguments: Sequence[str], directory: str) -> list[str]:
    """Replace ``@file`` arguments by the file's contents (CMake's ``.modmap`` files)."""
    expanded: list[str] = []
    for argument in arguments:
        if argument.startswith("@") and (Path(directory) / argument[1:]).is_file():
            for line in (Path(directory) / argument[1:]).read_text(encoding="utf-8").splitlines():
                expanded.extend(split_command_line(line))
        else:
            expanded.append(argument)
    return expanded


def clean_arguments(arguments: Sequence[str], file: str, directory: str) -> list[str]:
    """Drop the compile/output flags and the input file; make module file paths absolute."""
    cleaned: list[str] = []
    skip_next = False
    for argument in arguments:
        if skip_next:
            skip_next = False
            continue
        if argument in ("-o", "-MF", "-MT", "-MQ"):
            skip_next = True
        elif argument in ("-c", "-MD", "-MMD") or Path(argument).name == Path(file).name:
            continue
        else:
            cleaned.append(_absolute_module_flag(argument, directory))
    return cleaned


def _absolute_module_flag(argument: str, directory: str) -> str:
    for prefix in ("-fmodule-file=", "-fmodule-output=", "-fprebuilt-module-path="):
        if argument.startswith(prefix):
            head, _, path = argument.rpartition("=")
            if not Path(path).is_absolute():
                return f"{head}={Path(directory) / path}"
    return argument


def module_declaration(text: str) -> tuple[str, str]:
    """(module name, unit kind) from a source text: ``interface``, ``implementation`` or ``source``."""
    match = _MODULE_DECL.search(text)
    if not match:
        return "", "source"
    return match.group(2), "interface" if match.group(1) else "implementation"


# --------------------------------------------------------------------------- shadow parse

@dataclass
class Shadow:
    """The shadow text and the byte ranges that were ``export`` keywords or ``export { }`` blocks."""

    text: str
    export_ranges: list[tuple[int, int]] = field(default_factory=list)
    block_ranges: list[tuple[int, int]] = field(default_factory=list)


def shadow_source(source: bytes, tokens: Sequence[Any]) -> Shadow:
    """Keep the module identity (including partition imports); blank declaration exports and their block braces."""
    edits: list[tuple[int, int]] = []
    shadow = Shadow("")
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.spelling == "export" and token.kind == cindex.TokenKind.KEYWORD:
            following = tokens[index + 1] if index + 1 < len(tokens) else None
            if following is None or following.spelling != "module":
                index = _blank_export(tokens, index, edits, shadow)
        index += 1
    buffer = bytearray(source)
    for start, end in edits:
        for offset in range(start, min(end, len(buffer))):
            if buffer[offset] not in b"\n":
                buffer[offset] = ord(" ")
    shadow.text = bytes(buffer).decode("utf-8", errors="replace")
    return shadow


def _blank_export(tokens: Sequence[Any], index: int, edits: list[tuple[int, int]],
                  shadow: Shadow) -> int:
    token = tokens[index]
    start, end = token.extent.start.offset, token.extent.end.offset
    edits.append((start, end))
    following = tokens[index + 1] if index + 1 < len(tokens) else None
    if following is not None and following.spelling == "import":
        return index
    if following is not None and following.spelling == "{":
        close = _matching_brace(tokens, index + 1)
        edits.append((following.extent.start.offset, following.extent.end.offset))
        edits.append((tokens[close].extent.start.offset, tokens[close].extent.end.offset))
        shadow.block_ranges.append((following.extent.end.offset, tokens[close].extent.start.offset))
        return index + 1
    shadow.export_ranges.append((start, end))
    return index


def _matching_brace(tokens: Sequence[Any], open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(tokens)):
        if tokens[index].spelling == "{":
            depth += 1
        elif tokens[index].spelling == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(tokens) - 1


# --------------------------------------------------------------------------- parsing

class Parser:
    """Parses compile commands into translation units, through the shadow for module units.

    Compile commands do not always say everything libclang needs: CMake 4 omits ``-isysroot`` on macOS,
    and older CMake writes no module flags at all. Both are supplied here.
    """

    def __init__(self, resource_dirs: dict[str, str] | None = None, sysroot: str | None = None,
                 apple: bool = False) -> None:
        self.index = cindex.Index.create()
        self.resource_dirs = resource_dirs or {}
        self.sysroot = sysroot
        self.apple = apple
        self._prebuilt: dict[str, list[str]] = {}
        self.missing_modules: set[str] = set()
        self.last_shadow: Shadow | None = None

    def arguments(self, command: CompileCommand) -> list[str]:
        arguments = list(command.arguments)
        resource = self.resource_dirs.get(command.compiler)
        if resource and "-resource-dir" not in arguments:
            arguments += ["-resource-dir", resource]
        if self.sysroot and "-isysroot" not in arguments and not any(a.startswith("--sysroot") for a in arguments):
            arguments += ["-isysroot", self.sysroot]
        arguments += libcxx_arguments(command.compiler, arguments)
        if self.apple and "-fcxx-modules" not in arguments:
            arguments.append("-fcxx-modules")  # Apple's libclang treats `import` as a keyword only with this
        if not any(a.startswith(("-fmodule-file=", "-fprebuilt-module-path=")) for a in arguments):
            flags = self.prebuilt_module_flags(command.directory)
            if not flags:
                self.missing_modules.add(command.directory)
            arguments += flags
        return arguments

    def prebuilt_module_flags(self, directory: str) -> list[str]:
        """``-fprebuilt-module-path`` for every folder under the build directory that holds ``.pcm`` files."""
        if directory not in self._prebuilt:
            folders = sorted({str(p.parent) for p in Path(directory).rglob("*.pcm")})
            self._prebuilt[directory] = [f"-fprebuilt-module-path={folder}" for folder in folders]
        return self._prebuilt[directory]

    def parse(self, command: CompileCommand) -> tuple[Any, Shadow | None]:
        source = Path(command.file).read_bytes()
        arguments = self.arguments(command)
        options = cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
        if not _NEEDS_SHADOW.search(source.decode("utf-8", errors="replace")):
            return self.index.parse(command.file, args=arguments, options=options), None
        quick = self.index.parse(command.file, args=arguments,
                                 options=cindex.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES)
        shadow = shadow_source(source, list(quick.get_tokens(extent=quick.cursor.extent)))
        self.last_shadow = shadow
        plain = [a for a in arguments if not a.startswith("-fmodule-output")]
        if "c++-module" not in plain and Path(command.file).suffix not in MODULE_SUFFIXES:
            plain = ["-x", "c++-module", *plain]
        unit = self.index.parse(command.file, args=plain, unsaved_files=[(command.file, shadow.text)],
                                options=options)
        return unit, shadow


def libcxx_arguments(compiler: str, arguments: Sequence[str], platform: str = sys.platform) -> list[str]:
    """Point libclang at the libc++ installed beside a non-system clang.

    The compiler finds ``<prefix>/include/c++/v1`` from its own executable path; libclang has no such
    path and would fall back to the SDK's libc++, which does not match module files built against the
    compiler's copy. Applies where libc++ is the compiler's default (macOS) or requested explicitly.
    """
    uses_libcxx = platform == "darwin" or "-stdlib=libc++" in arguments
    if not uses_libcxx or "-nostdinc++" in arguments or "-stdlib=libstdc++" in arguments:
        return []
    resolved_compiler = Path(compiler).resolve()
    if "clang" not in resolved_compiler.name.lower():
        return []
    libcxx = resolved_compiler.parent.parent / "include" / "c++" / "v1"
    if not (libcxx / "__config").is_file():
        return []
    return ["-nostdinc++", "-isystem", str(libcxx)]


# --------------------------------------------------------------------------- extraction

@dataclass
class UnitResult:
    """What one translation unit contributes to the model."""

    file: FileInfo
    contributing: list[str]
    entities: list[Entity] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    externals: dict[str, list[str]] = field(default_factory=dict)
    extra_files: list[FileInfo] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"file": asdict(self.file), "contributing": self.contributing,
                "entities": [_entity_json(e) for e in self.entities],
                "edges": [{**asdict(e), "kind": e.kind.value} for e in self.edges],
                "externals": self.externals, "extra_files": [asdict(f) for f in self.extra_files]}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> UnitResult:
        return cls(_file_info(data["file"]), list(data["contributing"]),
                   [_entity_from_json(e) for e in data["entities"]],
                   [Edge(EdgeKind(e["kind"]), e["source"], e["target"], e["file"], e["line"], e["label"],
                         e.get("uncertain", False))
                    for e in data["edges"]],
                   {k: list(v) for k, v in data["externals"].items()},
                   [_file_info(f) for f in data["extra_files"]])


def _entity_json(entity: Entity) -> dict[str, Any]:
    data = asdict(entity)
    data.update(kind=entity.kind.value, satisfies=list(entity.satisfies), template_params=list(entity.template_params),
                test_files=list(entity.test_files))
    return data


def _entity_from_json(data: dict[str, Any]) -> Entity:
    data = dict(data)
    data.update(kind=Kind(data["kind"]), satisfies=tuple(data["satisfies"]),
                template_params=tuple(data["template_params"]))
    data.setdefault("body_hash", "")
    data.setdefault("declaration_file", "")
    data["test_files"] = tuple(data.get("test_files", ()))
    return Entity(**data)


def _file_info(data: dict[str, Any]) -> FileInfo:
    return FileInfo(data["path"], data["module"], data["unit"], data["content_hash"], tuple(data["errors"]))


class Extractor:
    """Walks one translation unit and collects entities, edges and external usage."""

    def __init__(self, root: Path, module_map: dict[str, str], resource_dirs: Iterable[str] = ()) -> None:
        self.root = root.resolve()
        self.module_map = module_map
        self.resource_dirs = tuple(resource_dirs)
        self.compiled_files: set[str] = set()
        self._paths: dict[str, Path] = {}
        self._sources: dict[str, bytes] = {}

    # -- entry point ------------------------------------------------------------------------

    def extract(self, unit: Any, shadow: Shadow | None, command: CompileCommand) -> UnitResult:
        main_path = Path(command.file).resolve()
        text = main_path.read_text(encoding="utf-8", errors="replace")
        module, unit_kind = module_declaration(text)
        errors = tuple(d.spelling for d in unit.diagnostics if d.severity >= cindex.Diagnostic.Error)
        info = FileInfo(self.relative(main_path), module, unit_kind, _sha1(main_path.read_bytes()), errors[:10])
        result = UnitResult(info, [info.path])
        self._current = result
        self._shadow = shadow
        self._main = main_path
        for cursor in unit.cursor.get_children():
            self._visit(cursor, None)
        result.contributing = sorted({info.path, *(f.path for f in result.extra_files)})
        return result

    def relative(self, path: Path) -> str:
        return self._resolved(str(path)).relative_to(self.root).as_posix()

    def _resolved(self, path: str) -> Path:
        # An AST can contain hundreds of thousands of cursors from the same headers.
        # Resolve each distinct path once instead of hitting the filesystem per cursor.
        if path not in self._paths:
            self._paths[path] = Path(path).resolve()
        return self._paths[path]

    def inside(self, path: str | None) -> bool:
        if not path:
            return False
        return _project_file(self._resolved(path), self.root)

    # -- declarations -----------------------------------------------------------------------

    def _visit(self, cursor: Any, parent: str | None) -> None:
        file_name = cursor.location.file.name if cursor.location.file else None
        if cursor.kind == CK.INCLUSION_DIRECTIVE:
            self._inclusion(cursor)
            return
        if cursor.kind == CK.MODULE_IMPORT_DECL:
            self._import(cursor)
            return
        if file_name is None or not self._own_file(file_name):
            return
        if cursor.kind in _KINDS and cursor.spelling:
            entity = self._entity(cursor, parent, file_name)
            self._current.entities.append(entity)
            self._relations(cursor, entity)
            if cursor.kind in _CALLABLE:
                self._calls(cursor, entity.usr)
            else:
                for child in cursor.get_children():
                    self._visit(child, entity.usr)
        elif cursor.kind in (CK.LINKAGE_SPEC, CK.UNEXPOSED_DECL, CK.NAMESPACE):
            for child in cursor.get_children():
                self._visit(child, parent)

    def _own_file(self, file_name: str | None) -> bool:
        """Entities come from the main file and from project headers no compile command covers."""
        if not file_name or not self.inside(file_name):
            return False
        path = self._resolved(file_name)
        if path == self._main:
            return True
        if str(path) in self.compiled_files or path.suffix not in HEADER_SUFFIXES:
            return False
        relative = self.relative(path)
        if all(f.path != relative for f in self._current.extra_files):
            self._current.extra_files.append(FileInfo(relative, "", "header", _sha1(path.read_bytes())))
        return True

    def _entity(self, cursor: Any, parent: str | None, file_name: str) -> Entity:
        kind = _KINDS[cursor.kind]
        brief, satisfies = parse_doc_comment(self._doc_comment(cursor, file_name))
        digest = body_hash(_body_source(cursor, file_name)) if cursor.kind in _CALLABLE else ""
        is_definition = bool(cursor.is_definition())
        relative_file = self.relative(Path(file_name))
        name = qualified_name(cursor)
        return Entity(self._usr(cursor), kind, cursor.spelling, name, relative_file,
                      cursor.location.line, cursor.extent.end.line, parent, _signature(cursor, kind), brief, satisfies,
                      _template_params(cursor), is_definition, self._exported(cursor),
                      _value(cursor, kind), body_hash=digest,
                      declaration_file="" if is_definition else relative_file)

    def _doc_comment(self, cursor: Any, file_name: str) -> str:
        """Clang omits trailing documentation on some class/struct definitions."""
        if cursor.raw_comment:
            return str(cursor.raw_comment)
        if file_name not in self._sources:
            self._sources[file_name] = Path(file_name).read_bytes()
        tail = self._sources[file_name][cursor.extent.end.offset:]
        match = re.match(rb"[ \t]*;?[ \t]*(///<[^\r\n]*|//!<[^\r\n]*|/\*[*!]<.*?\*/)", tail, re.DOTALL)
        return match.group(1).decode("utf-8", errors="replace") if match else ""

    def _usr(self, cursor: Any) -> str:
        usr = cursor.get_usr()
        if cursor.kind == CK.FUNCTION_DECL and qualified_name(cursor) == "main" and cursor.location.file:
            return f"{usr}@entry:{self.relative(Path(cursor.location.file.name))}"
        return str(usr)

    def _exported(self, cursor: Any) -> bool:
        if self._shadow is None:
            return False
        start = cursor.extent.start.offset
        if any(a <= start <= b for a, b in self._shadow.block_ranges):
            return True
        text = self._shadow.text
        return any(text[end:start].strip() == "" and end <= start for _, end in self._shadow.export_ranges)

    # -- relations --------------------------------------------------------------------------

    def _relations(self, cursor: Any, entity: Entity) -> None:
        if entity.kind in (Kind.STRUCT, Kind.CLASS):
            for child in cursor.get_children():
                if child.kind == CK.CXX_BASE_SPECIFIER:
                    self._type_edge(EdgeKind.INHERITS, entity, child.type, child.location.line)
        if entity.kind in (Kind.FIELD, Kind.VARIABLE, Kind.ALIAS):
            self._type_edge(EdgeKind.USES_TYPE, entity, cursor.type, cursor.location.line)
        if cursor.kind in _CALLABLE:
            self._type_edge(EdgeKind.USES_TYPE, entity, cursor.result_type, cursor.location.line)
            for argument in cursor.get_arguments():
                self._type_edge(EdgeKind.USES_TYPE, entity, argument.type, cursor.location.line)

    def _type_edge(self, kind: EdgeKind, entity: Entity, ctype: Any, line: int, depth: int = 0) -> None:
        if ctype is None or depth > 2:
            return
        while ctype.kind in _REFERENCE_TYPES:
            ctype = ctype.get_pointee()
        declaration = _valid(ctype.get_declaration())
        if declaration is not None and declaration.kind in _TYPE_DECLS:
            self._reference(kind, entity.usr, declaration, entity.file, line, _template_label(declaration))
        canonical = ctype.get_canonical()
        for index in range(max(canonical.get_num_template_arguments(), 0)):
            self._type_edge(kind, entity, canonical.get_template_argument_type(index), line, depth + 1)

    def _calls(self, cursor: Any, source: str) -> None:
        for node in cursor.walk_preorder():
            if node.kind != CK.CALL_EXPR:
                continue
            target = _valid(node.referenced)
            if target is None or (target.kind not in _CALLABLE and target.kind != CK.CONVERSION_FUNCTION):
                continue
            uncertain = is_uncertain_call(_call_dispatch(node, target))
            self._reference(EdgeKind.CALLS, source, target, self.relative(self._main), node.location.line,
                            _call_label(node, target), uncertain)

    def _reference(self, kind: EdgeKind, source: str, declaration: Any, file: str, line: int, label: str,
                   uncertain: bool = False) -> None:
        if _is_implicit_member(declaration):
            declaration, kind = declaration.semantic_parent, EdgeKind.USES_TYPE
        pattern = template_pattern(declaration)
        target_file = pattern.location.file.name if pattern.location.file else None
        if self.inside(target_file):
            target_usr = self._usr(pattern)
            if target_usr != source:
                self._current.edges.append(Edge(kind, source, target_usr, file, line, label, uncertain))
        elif target_file:
            library = library_name(target_file, self.resource_dirs)
            names = self._current.externals.setdefault(library, [])
            display = external_display_name(pattern)
            if display and display not in names:
                names.append(display)
            self._current.edges.append(Edge(kind, source, f"external:{library}", file, line, display, uncertain))

    def _inclusion(self, cursor: Any) -> None:
        included = _included_file(cursor)
        if included is None or not cursor.location.file or Path(cursor.location.file.name).resolve() != self._main:
            return
        source = self.relative(self._main)
        if self.inside(included.name):
            self._current.edges.append(Edge(EdgeKind.INCLUDES, source, self.relative(Path(included.name)), source,
                                            cursor.location.line))
        else:
            library = library_name(included.name, self.resource_dirs)
            self._current.externals.setdefault(library, [])
            self._current.edges.append(Edge(EdgeKind.INCLUDES, source, f"external:{library}", source,
                                            cursor.location.line, cursor.spelling))

    def _import(self, cursor: Any) -> None:
        if not cursor.location.file or Path(cursor.location.file.name).resolve() != self._main:
            return
        source = self.relative(self._main)
        target = self.module_map.get(cursor.spelling, f"external:{cursor.spelling.split(':')[0]}")
        self._current.edges.append(Edge(EdgeKind.IMPORTS, source, target, source, cursor.location.line,
                                        cursor.spelling))


# --------------------------------------------------------------------------- cursor helpers

def _valid(cursor: Any) -> Any:
    """``cursor`` unless it is None or a null cursor (newer bindings raise on any use of a null cursor)."""
    if cursor is None:
        return None
    is_null = getattr(cursor, "is_null", None)
    if callable(is_null) and is_null():
        return None
    return cursor


def _included_file(cursor: Any) -> Any:
    """The file an inclusion directive resolved to, or None when it did not resolve (the bindings assert then)."""
    try:
        return cursor.get_included_file()
    except AssertionError:
        return None


def qualified_name(cursor: Any) -> str:
    parts = []
    node = _valid(cursor)
    while node is not None and node.kind != CK.TRANSLATION_UNIT:
        if node.spelling and node.kind not in (CK.LINKAGE_SPEC, CK.UNEXPOSED_DECL):
            parts.append(node.spelling)
        node = _valid(node.semantic_parent)
    return "::".join(reversed(parts))


def template_pattern(cursor: Any) -> Any:
    """The template a specialization or a member of a specialization comes from; else the cursor itself."""
    specialized = _specialized_template(cursor)
    if specialized is not None and specialized.kind != CK.NO_DECL_FOUND and specialized.kind.is_declaration():
        return specialized
    parent = _valid(cursor.semantic_parent)
    if parent is not None and parent.kind in (CK.CLASS_DECL, CK.STRUCT_DECL):
        parent_template = _specialized_template(parent)
        if parent_template is not None and parent_template.kind == CK.CLASS_TEMPLATE:
            for member in parent_template.get_children():
                if member.spelling == cursor.spelling and member.kind == cursor.kind:
                    return member
    return cursor


def _specialized_template(cursor: Any) -> Any:
    result = _valid(cindex.conf.lib.clang_getSpecializedCursorTemplate(cursor))
    if result is not None:
        # Recent bindings return a raw cursor here. Retain its translation unit before
        # reading children, as the bindings' high-level cursor accessors do.
        result._tu = cursor._tu
    return result


def _is_implicit_member(declaration: Any) -> bool:
    """Compiler-generated constructors and destructors sit exactly at their class's location."""
    parent = _valid(declaration.semantic_parent)
    if declaration.kind not in (CK.CONSTRUCTOR, CK.DESTRUCTOR) or parent is None:
        return False
    return (declaration.location.line, declaration.location.column) == (parent.location.line, parent.location.column)


def external_display_name(declaration: Any) -> str:
    """A short name for an external entity: no operators, no template argument lists."""
    name = declaration.spelling
    if not name or name.startswith("operator"):
        return ""
    return name.split("<", 1)[0]


def _template_label(declaration: Any) -> str:
    text = declaration.type.spelling if declaration.kind in (CK.CLASS_DECL, CK.STRUCT_DECL) else ""
    return text[text.find("<") + 1:text.rfind(">")] if "<" in text else ""


def _call_label(call: Any, target: Any) -> str:
    parent = _valid(target.semantic_parent)
    if parent is not None and parent.kind in (CK.CLASS_DECL, CK.STRUCT_DECL) and "<" in parent.type.spelling:
        return _template_label(parent)
    count = target.get_num_template_arguments()
    if count > 0:
        return ", ".join(target.get_template_argument_type(i).spelling for i in range(count))
    return ""


def _call_dispatch(call: Any, target: Any) -> CallDispatch:
    """Extract cursor facts and leave the dispatch decision to ``is_uncertain_call``."""
    member = target.kind == CK.CXX_METHOD
    member_ref = next((child for child in call.get_children() if child.kind == CK.MEMBER_REF_EXPR), None)
    parent = _valid(target.semantic_parent)
    return CallDispatch(
        member=member,
        virtual=bool(member and target.is_virtual_method()),
        receiver_indirect=bool(member_ref is not None and _receiver_is_indirect(member_ref)),
        final=_has_final_attribute(target) or (parent is not None and _has_final_attribute(parent)),
        fully_qualified=bool(member_ref is not None and "::" in (token.spelling for token in member_ref.get_tokens())),
    )


def _receiver_is_indirect(member_ref: Any) -> bool:
    receiver = next((child for child in member_ref.get_children() if child.kind != CK.TYPE_REF), None)
    if receiver is None:
        return False
    for cursor in receiver.walk_preorder():
        referenced = _valid(cursor.referenced)
        types = (cursor.type, referenced.type if referenced is not None else None)
        if any(ctype is not None and ctype.kind in _REFERENCE_TYPES for ctype in types):
            return True
    return False


def _has_final_attribute(cursor: Any) -> bool:
    final_attribute = getattr(CK, "CXX_FINAL_ATTR", None)
    return final_attribute is not None and any(child.kind == final_attribute for child in cursor.get_children())


def _signature(cursor: Any, kind: Kind) -> str:
    if kind in (Kind.FUNCTION, Kind.METHOD, Kind.CONSTRUCTOR, Kind.DESTRUCTOR):
        result = cursor.result_type.spelling if cursor.result_type and cursor.result_type.spelling else ""
        const = " const" if cursor.kind == CK.CXX_METHOD and cursor.is_const_method() else ""
        return f"{result} {cursor.displayname}{const}".strip()
    if kind in (Kind.FIELD, Kind.VARIABLE):
        return cursor.type.spelling
    if kind == Kind.ALIAS:
        return cursor.underlying_typedef_type.spelling if cursor.kind == CK.TYPEDEF_DECL else cursor.type.spelling
    return ""


def _template_params(cursor: Any) -> tuple[str, ...]:
    return tuple(c.spelling for c in cursor.get_children() if c.kind in _TEMPLATE_PARAMS)


def _value(cursor: Any, kind: Kind) -> str:
    return str(cursor.enum_value) if kind == Kind.ENUMERATOR else ""


def _body_source(cursor: Any, file_name: str) -> str:
    body = next((child for child in cursor.get_children() if child.kind == CK.COMPOUND_STMT), None)
    if body is None:
        return ""
    try:
        source = Path(file_name).read_bytes()
    except OSError:
        return ""
    start, end = body.extent.start.offset, body.extent.end.offset
    return source[start:end].decode("utf-8", errors="replace")


def parse_doc_comment(comment: str) -> tuple[str, tuple[str, ...]]:
    """(brief, satisfies) from a Doxygen comment: ``@brief``/first sentence and ``@satisfies A, B``."""
    comment = re.sub(r"\s*\*/\s*$", "", comment)
    lines = [re.sub(r"^\s*(/\*\*<?|/\*!<?|\*/|//!<?|///?<?|\*)\s?", "", line).rstrip()
             for line in comment.splitlines()]
    text = "\n".join(line for line in lines if line != "/")
    satisfies = tuple(t for m in re.finditer(r"[@\\]satisfies\s+([^\n@\\]+)", text)
                      for t in re.split(r"[,\s]+", m.group(1).strip()) if t)
    brief_match = re.search(r"[@\\]brief\s+(.+?)(?=\n\s*\n|\n\s*[@\\]|$)", text, re.DOTALL)
    brief = brief_match.group(1) if brief_match else re.split(r"\n\s*[@\\]|\n\s*\n", text, maxsplit=1)[0]
    if not brief_match and brief.lstrip().startswith(("@", "\\")):
        brief = ""
    return " ".join(brief.split()), satisfies


def library_name(path: str, resource_dirs: Iterable[str] = ()) -> str:
    """The library an external file belongs to: ``std`` for the toolchain, else the include subdirectory."""
    normalized = path.replace("\\", "/")
    system_markers = ("/c++/", "/usr/include/", "/usr/lib/gcc/", "CommandLineTools", "Xcode.app", ".sdk/",
                      "/lib/clang/", "Microsoft Visual Studio", "Windows Kits")
    if any(marker in normalized for marker in system_markers) or any(normalized.startswith(r) for r in resource_dirs):
        return "std"
    parts = normalized.split("/")
    if "include" in parts:
        after = parts[len(parts) - 1 - parts[::-1].index("include") + 1:]
        return after[0] if len(after) > 1 else Path(after[0]).stem
    return parts[-2] if len(parts) > 1 else Path(path).stem


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


# --------------------------------------------------------------------------- project

def detect_language(root: Path) -> str:
    """Detect Python-only projects; C/C++ wins for mixed and source-free projects."""
    has_python = False
    try:
        paths = root.rglob("*")
        for path in paths:
            if not path.is_file():
                continue
            if path.suffix.lower() in CPP_SUFFIXES:
                return CPP_LANGUAGE
            has_python = has_python or path.suffix.lower() == ".py"
    except OSError:
        return CPP_LANGUAGE
    return PYTHON_LANGUAGE if has_python else CPP_LANGUAGE


def parse_project_for_root(
    root: Path, commands: Sequence[CompileCommand], *, resource_dirs: dict[str, str] | None = None,
    cache_dir: Path | None = None, previous: DerivedModel | None = None,
    libclang_version: str = "", sysroot: str | None = None, apple: bool = False,
    notes: list[str] | None = None, progress: Callable[[str], None] | None = None,
) -> DerivedModel:
    """Select the Python front end or call the existing C++ parser unchanged."""
    if detect_language(root) == PYTHON_LANGUAGE:
        from icoda_core import python_analysis

        return python_analysis.parse_project(root)
    return parse_project(root, commands, resource_dirs=resource_dirs, cache_dir=cache_dir,
                         previous=previous, libclang_version=libclang_version, sysroot=sysroot,
                         apple=apple, notes=notes, progress=progress)

def build_module_map(root: Path, commands: Sequence[CompileCommand]) -> dict[str, str]:
    """Module name -> interface unit path (relative), read from the ``export module`` declarations."""
    module_map: dict[str, str] = {}
    for command in commands:
        if command.module_unit:
            name, unit = module_declaration(Path(command.file).read_text(encoding="utf-8", errors="replace"))
            if name and unit == "interface":
                module_map[name] = Path(command.file).resolve().relative_to(root.resolve()).as_posix()
    return module_map


def unit_cache_key(command: CompileCommand, contributing: Iterable[str], root: Path, libclang_version: str) -> str:
    digest = hashlib.sha1(
        f"schema={UNIT_CACHE_VERSION}\n{CACHE_VERSION}\n{libclang_version}\n{' '.join(command.arguments)}\n".encode()
    )
    for relative in sorted(contributing):
        path = root / relative
        digest.update(relative.encode())
        digest.update(path.read_bytes() if path.is_file() else b"missing")
    return digest.hexdigest()


def parse_project(root: Path, commands: Sequence[CompileCommand], *, resource_dirs: dict[str, str] | None = None,
                  cache_dir: Path | None = None, previous: DerivedModel | None = None,
                  libclang_version: str = "", sysroot: str | None = None, apple: bool = False,
                  notes: list[str] | None = None, progress: Callable[[str], None] | None = None) -> DerivedModel:
    """Parse the project's compile commands; dependencies outside its root remain external."""
    root = root.resolve()
    # CMake also exports commands for toolchain modules (e.g. std.compat.cppm) and
    # dependencies outside the project. They cannot become project-relative files.
    commands = [command for command in commands if _project_file(Path(command.file).resolve(), root)]
    parser = Parser(resource_dirs, sysroot, apple)
    extractor = Extractor(root, build_module_map(root, commands), (resource_dirs or {}).values())
    extractor.compiled_files = {str(Path(c.file).resolve()) for c in commands}
    results = []
    for command in commands:
        if progress is not None:
            progress(f"{command.file} with {' '.join(parser.arguments(command))}")
        results.append(_unit_result(command, parser, extractor, root, cache_dir, libclang_version))
    if parser.missing_modules and notes is not None:
        notes.append("no built module files (.pcm) under the build directory: imports cannot be resolved until the "
                     "project is built (build.sh)")
    model = assemble(root, results, libclang_version)
    broken = [f"{r.file.path}: {r.file.errors[0]}" for r in results if r.file.errors]
    if broken and previous is not None:
        previous.stale, previous.stale_reason = True, "; ".join(broken[:5])
        return previous
    return model


def _project_file(path: Path, root: Path) -> bool:
    if not path.is_relative_to(root):
        return False
    # vcpkg installs dependencies inside the source/build tree in manifest mode.
    # Treat their headers as external libraries, not hundreds of thousands of project entities.
    return "vcpkg_installed" not in path.relative_to(root).parts


def _unit_result(command: CompileCommand, parser: Parser, extractor: Extractor, root: Path,
                 cache_dir: Path | None, libclang_version: str) -> UnitResult:
    cache_file = cache_dir / "units" / f"{_sha1(command.file.encode())}.json" if cache_dir else None
    if cache_file and cache_file.is_file():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if cached.get("key") == unit_cache_key(command, cached["result"]["contributing"], root, libclang_version):
            return UnitResult.from_json(cached["result"])
    try:
        unit, shadow = parser.parse(command)
    except cindex.TranslationUnitLoadError as exc:
        explanation = explain_with_compiler(command, parser.arguments(command), parser.last_shadow)
        return _unparsable(command, root, f"libclang could not parse this unit: {exc}; compiler says: {explanation}")
    result = extractor.extract(unit, shadow, command)
    if result.file.errors:
        explanation = explain_with_compiler(command, parser.arguments(command), shadow)
        result.file.errors = (*result.file.errors, f"compiler says: {explanation}")
    if cache_file:
        key = unit_cache_key(command, result.contributing, root, libclang_version)
        persistence._atomic_write_text(cache_file, json.dumps({"key": key, "result": result.to_json()}))
    return result


def explain_with_compiler(command: CompileCommand, arguments: Sequence[str], shadow: Shadow | None = None) -> str:
    """Run the project's compiler in syntax-only mode with libclang's arguments (and the shadow text, if any)."""
    argv = [command.compiler, "-fsyntax-only", *[a for a in arguments if not a.startswith("-fmodule-output")]]
    if shadow is not None:
        argv += ["-x", "c++-module", "-"]
    else:
        argv.append(command.file)
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False,
                                   cwd=command.directory, input=shadow.text if shadow else None)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"could not run {command.compiler}: {exc}"
    if completed.returncode == 0:
        return "accepts the unit with the same arguments (a libclang-only problem)"
    lines = [line for line in completed.stderr.splitlines() if "error" in line or "note" in line][:4]
    return " | ".join(lines) if lines else completed.stderr.strip()[:300]


def _unparsable(command: CompileCommand, root: Path, reason: str) -> UnitResult:
    path = Path(command.file).resolve()
    relative = path.relative_to(root).as_posix()
    module, unit_kind = module_declaration(path.read_text(encoding="utf-8", errors="replace"))
    return UnitResult(FileInfo(relative, module, unit_kind, _sha1(path.read_bytes()), (reason,)), [relative])


def assemble(root: Path, results: Sequence[UnitResult], libclang_version: str) -> DerivedModel:
    model = DerivedModel(str(root), libclang_version)
    entities: list[Entity] = []
    edges: list[Edge] = []
    for result in results:
        model.files[result.file.path] = result.file
        for extra in result.extra_files:
            model.files.setdefault(extra.path, extra)
        entities.extend(result.entities)
        edges.extend(result.edges)
        for library, names in result.externals.items():
            merged = sorted(set(names) | set(model.externals[library].names if library in model.externals else ()))
            model.externals[library] = External(library, tuple(merged))
    pairing = pair_declarations(entities, edges)
    model.entities = {entity.usr: entity for entity in pairing.entities}
    for edge in pairing.edges:
        if _known(model, edge.source) and _known(model, edge.target):
            model.add_edge(edge)
    associate_test_files(model)
    return model


def _known(model: DerivedModel, endpoint: str) -> bool:
    return endpoint in model.entities or endpoint in model.files or endpoint.startswith("external:")
