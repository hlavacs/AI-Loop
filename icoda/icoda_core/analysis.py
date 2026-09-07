"""Parsing a project with libclang into the derived model; incremental cache; stale marking.

Module interface units are parsed twice: once as written (only to tokenize), then as an ordinary
translation unit from memory with the ``export`` and ``module`` keywords blanked, because libclang does
not visit the declarations inside an ``export``. Offsets are preserved, so locations and USRs match
what call sites in other units reference.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from clang import cindex

from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, External, FileInfo, Kind

MODULE_SUFFIXES = frozenset({".cppm", ".ixx", ".mpp", ".cxxm", ".c++m", ".ccm"})
HEADER_SUFFIXES = frozenset({".h", ".hh", ".hpp", ".hxx", ".h++", ".inl"})
_MODULE_DECL = re.compile(r"^\s*(export\s+)?module\s+([A-Za-z_][\w.:]*)\s*;", re.MULTILINE)
_NEEDS_SHADOW = re.compile(r"^\s*(export\s+)?module\b|^\s*export\b", re.MULTILINE)

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


# --------------------------------------------------------------------------- compile commands

@dataclass(frozen=True)
class CompileCommand:
    """One translation unit: the file, where it is compiled, and the cleaned compiler arguments."""

    file: str
    directory: str
    arguments: tuple[str, ...]
    compiler: str
    module_unit: bool


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
        raw = entry["arguments"] if "arguments" in entry else shlex.split(entry["command"])
        directory = entry["directory"]
        file = str((Path(directory) / entry["file"]).resolve())
        expanded = expand_response_files(raw[1:], directory)
        arguments = clean_arguments(expanded, file, directory)
        module_unit = Path(file).suffix in MODULE_SUFFIXES or "c++-module" in arguments
        commands.append(CompileCommand(file, directory, tuple(arguments), raw[0], module_unit))
    return commands


def expand_response_files(arguments: Sequence[str], directory: str) -> list[str]:
    """Replace ``@file`` arguments by the file's contents (CMake's ``.modmap`` files)."""
    expanded: list[str] = []
    for argument in arguments:
        if argument.startswith("@") and (Path(directory) / argument[1:]).is_file():
            for line in (Path(directory) / argument[1:]).read_text(encoding="utf-8").splitlines():
                expanded.extend(shlex.split(line))
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
    """The blanked source text and the byte ranges that were ``export`` keywords or blocks."""

    text: str
    export_ranges: list[tuple[int, int]] = field(default_factory=list)
    block_ranges: list[tuple[int, int]] = field(default_factory=list)


def shadow_source(source: bytes, tokens: Sequence[Any]) -> Shadow:
    """Blank ``export``, ``export { }`` braces and every ``module …;`` statement, keeping offsets."""
    blanks: list[tuple[int, int]] = []
    shadow = Shadow("")
    index = 0
    while index < len(tokens):
        token = tokens[index]
        spelling, start, end = token.spelling, token.extent.start.offset, token.extent.end.offset
        if spelling == "export" and token.kind == cindex.TokenKind.KEYWORD:
            index = _blank_export(tokens, index, blanks, shadow)
        elif spelling == "module" and index + 1 < len(tokens) and tokens[index + 1].spelling in (";", ":") \
                or spelling == "module" and _starts_statement(tokens, index):
            index = _blank_until_semicolon(tokens, index, blanks)
        index += 1
    buffer = bytearray(source)
    for start, end in blanks:
        for offset in range(start, min(end, len(buffer))):
            if buffer[offset] not in b"\n":
                buffer[offset] = ord(" ")
    shadow.text = bytes(buffer).decode("utf-8", errors="replace")
    return shadow


def _starts_statement(tokens: Sequence[Any], index: int) -> bool:
    """``module name;`` at the start of a line (a module declaration, not the word in some expression)."""
    previous = tokens[index - 1].spelling if index > 0 else ";"
    following = tokens[index + 1] if index + 1 < len(tokens) else None
    return previous in (";", "}", "{", "export") and following is not None and following.kind == cindex.TokenKind.IDENTIFIER


def _blank_export(tokens: Sequence[Any], index: int, blanks: list[tuple[int, int]], shadow: Shadow) -> int:
    token = tokens[index]
    start, end = token.extent.start.offset, token.extent.end.offset
    blanks.append((start, end))
    following = tokens[index + 1] if index + 1 < len(tokens) else None
    if following is not None and following.spelling in ("module", "import"):
        return index
    if following is not None and following.spelling == "{":
        close = _matching_brace(tokens, index + 1)
        blanks.append((following.extent.start.offset, following.extent.end.offset))
        blanks.append((tokens[close].extent.start.offset, tokens[close].extent.end.offset))
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


def _blank_until_semicolon(tokens: Sequence[Any], index: int, blanks: list[tuple[int, int]]) -> int:
    end = index
    while end < len(tokens) and tokens[end].spelling != ";":
        end += 1
    end = min(end, len(tokens) - 1)
    blanks.append((tokens[index].extent.start.offset, tokens[end].extent.end.offset))
    return end


# --------------------------------------------------------------------------- parsing

class Parser:
    """Parses compile commands into translation units, through the shadow for module units."""

    def __init__(self, resource_dirs: dict[str, str] | None = None) -> None:
        self.index = cindex.Index.create()
        self.resource_dirs = resource_dirs or {}

    def arguments(self, command: CompileCommand) -> list[str]:
        arguments = list(command.arguments)
        resource = self.resource_dirs.get(command.compiler)
        if resource and "-resource-dir" not in arguments:
            arguments += ["-resource-dir", resource]
        return arguments

    def parse(self, command: CompileCommand) -> tuple[Any, Shadow | None]:
        source = Path(command.file).read_bytes()
        arguments = self.arguments(command)
        options = cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
        if not _NEEDS_SHADOW.search(source.decode("utf-8", errors="replace")):
            return self.index.parse(command.file, args=arguments, options=options), None
        quick = self.index.parse(command.file, args=arguments,
                                 options=cindex.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES)
        shadow = shadow_source(source, list(quick.get_tokens(extent=quick.cursor.extent)))
        plain = _plain_arguments(arguments)
        unit = self.index.parse(command.file, args=plain, unsaved_files=[(command.file, shadow.text)],
                                options=options)
        return unit, shadow


def _plain_arguments(arguments: Sequence[str]) -> list[str]:
    plain = [a for a in arguments if not a.startswith("-fmodule-output")]
    return ["c++" if index > 0 and plain[index - 1] == "-x" and a == "c++-module" else a
            for index, a in enumerate(plain)]


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
                   [Edge(EdgeKind(e["kind"]), e["source"], e["target"], e["file"], e["line"], e["label"])
                    for e in data["edges"]],
                   {k: list(v) for k, v in data["externals"].items()},
                   [_file_info(f) for f in data["extra_files"]])


def _entity_json(entity: Entity) -> dict[str, Any]:
    data = asdict(entity)
    data.update(kind=entity.kind.value, satisfies=list(entity.satisfies), template_params=list(entity.template_params))
    return data


def _entity_from_json(data: dict[str, Any]) -> Entity:
    data = dict(data)
    data.update(kind=Kind(data["kind"]), satisfies=tuple(data["satisfies"]),
                template_params=tuple(data["template_params"]))
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
        return path.resolve().relative_to(self.root).as_posix()

    def inside(self, path: str | None) -> bool:
        if not path:
            return False
        try:
            Path(path).resolve().relative_to(self.root)
            return True
        except ValueError:
            return False

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
        path = Path(file_name).resolve()
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
        brief, satisfies = parse_doc_comment(cursor.raw_comment or "")
        return Entity(cursor.get_usr(), kind, cursor.spelling, qualified_name(cursor), self.relative(Path(file_name)),
                      cursor.location.line, cursor.extent.end.line, parent, _signature(cursor, kind), brief, satisfies,
                      _template_params(cursor), bool(cursor.is_definition()), self._exported(cursor),
                      _value(cursor, kind))

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
        declaration = ctype.get_declaration()
        if declaration.kind in _TYPE_DECLS:
            self._reference(kind, entity.usr, declaration, entity.file, line, _template_label(declaration))
        canonical = ctype.get_canonical()
        for index in range(max(canonical.get_num_template_arguments(), 0)):
            self._type_edge(kind, entity, canonical.get_template_argument_type(index), line, depth + 1)

    def _calls(self, cursor: Any, source: str) -> None:
        for node in cursor.walk_preorder():
            if node.kind != CK.CALL_EXPR or node.referenced is None:
                continue
            target = node.referenced
            if target.kind not in _CALLABLE and target.kind != CK.CONVERSION_FUNCTION:
                continue
            self._reference(EdgeKind.CALLS, source, target, self.relative(self._main), node.location.line,
                            _call_label(node, target))

    def _reference(self, kind: EdgeKind, source: str, declaration: Any, file: str, line: int, label: str) -> None:
        if _is_implicit_member(declaration):
            declaration, kind = declaration.semantic_parent, EdgeKind.USES_TYPE
        pattern = template_pattern(declaration)
        target_file = pattern.location.file.name if pattern.location.file else None
        if self.inside(target_file):
            if pattern.get_usr() != source:
                self._current.edges.append(Edge(kind, source, pattern.get_usr(), file, line, label))
        elif target_file:
            library = library_name(target_file, self.resource_dirs)
            names = self._current.externals.setdefault(library, [])
            display = external_display_name(pattern)
            if display and display not in names:
                names.append(display)
            self._current.edges.append(Edge(kind, source, f"external:{library}", file, line, display))

    def _inclusion(self, cursor: Any) -> None:
        included = cursor.get_included_file()
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

def qualified_name(cursor: Any) -> str:
    parts = []
    node = cursor
    while node is not None and node.kind != CK.TRANSLATION_UNIT:
        if node.spelling and node.kind not in (CK.LINKAGE_SPEC, CK.UNEXPOSED_DECL):
            parts.append(node.spelling)
        node = node.semantic_parent
    return "::".join(reversed(parts))


def template_pattern(cursor: Any) -> Any:
    """The template a specialization or a member of a specialization comes from; else the cursor itself."""
    specialized = cindex.conf.lib.clang_getSpecializedCursorTemplate(cursor)
    if specialized is not None and specialized.kind != CK.NO_DECL_FOUND and specialized.kind.is_declaration():
        return specialized
    parent = cursor.semantic_parent
    if parent is not None and parent.kind in (CK.CLASS_DECL, CK.STRUCT_DECL):
        parent_template = cindex.conf.lib.clang_getSpecializedCursorTemplate(parent)
        if parent_template is not None and parent_template.kind == CK.CLASS_TEMPLATE:
            for member in parent_template.get_children():
                if member.spelling == cursor.spelling and member.kind == cursor.kind:
                    return member
    return cursor


def _is_implicit_member(declaration: Any) -> bool:
    """Compiler-generated constructors and destructors sit exactly at their class's location."""
    parent = declaration.semantic_parent
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
    parent = target.semantic_parent
    if parent is not None and parent.kind in (CK.CLASS_DECL, CK.STRUCT_DECL) and "<" in parent.type.spelling:
        return _template_label(parent)
    count = target.get_num_template_arguments()
    if count > 0:
        return ", ".join(target.get_template_argument_type(i).spelling for i in range(count))
    return ""


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


def parse_doc_comment(comment: str) -> tuple[str, tuple[str, ...]]:
    """(brief, satisfies) from a Doxygen comment: ``@brief``/first sentence and ``@satisfies A, B``."""
    lines = [re.sub(r"^\s*(/\*\*|/\*!|\*/|///?<?|//!<?|\*)\s?", "", line).rstrip() for line in comment.splitlines()]
    text = "\n".join(line for line in lines if line != "/")
    satisfies = tuple(t for m in re.finditer(r"[@\\]satisfies\s+([^\n@\\]+)", text)
                      for t in re.split(r"[,\s]+", m.group(1).strip()) if t)
    brief_match = re.search(r"[@\\]brief\s+(.+?)(?=\n\s*\n|\n\s*[@\\]|$)", text, re.DOTALL)
    brief = brief_match.group(1) if brief_match else re.split(r"\n\s*[@\\]|\n\s*\n", text, 1)[0]
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
    digest = hashlib.sha1(f"{libclang_version}\n{' '.join(command.arguments)}\n".encode())
    for relative in sorted(contributing):
        path = root / relative
        digest.update(relative.encode())
        digest.update(path.read_bytes() if path.is_file() else b"missing")
    return digest.hexdigest()


def parse_project(root: Path, commands: Sequence[CompileCommand], *, resource_dirs: dict[str, str] | None = None,
                  cache_dir: Path | None = None, previous: DerivedModel | None = None,
                  libclang_version: str = "") -> DerivedModel:
    """Parse every compile command (from cache where nothing changed) and assemble the derived model."""
    root = root.resolve()
    parser = Parser(resource_dirs)
    extractor = Extractor(root, build_module_map(root, commands), (resource_dirs or {}).values())
    extractor.compiled_files = {str(Path(c.file).resolve()) for c in commands}
    results = [_unit_result(command, parser, extractor, root, cache_dir, libclang_version) for command in commands]
    model = assemble(root, results, libclang_version)
    broken = [f"{r.file.path}: {r.file.errors[0]}" for r in results if r.file.errors]
    if broken and previous is not None:
        previous.stale, previous.stale_reason = True, "; ".join(broken[:5])
        return previous
    return model


def _unit_result(command: CompileCommand, parser: Parser, extractor: Extractor, root: Path,
                 cache_dir: Path | None, libclang_version: str) -> UnitResult:
    cache_file = cache_dir / "units" / f"{_sha1(command.file.encode())}.json" if cache_dir else None
    if cache_file and cache_file.is_file():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if cached.get("key") == unit_cache_key(command, cached["result"]["contributing"], root, libclang_version):
            return UnitResult.from_json(cached["result"])
    unit, shadow = parser.parse(command)
    result = extractor.extract(unit, shadow, command)
    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        key = unit_cache_key(command, result.contributing, root, libclang_version)
        cache_file.write_text(json.dumps({"key": key, "result": result.to_json()}), encoding="utf-8")
    return result


def assemble(root: Path, results: Sequence[UnitResult], libclang_version: str) -> DerivedModel:
    model = DerivedModel(str(root), libclang_version)
    for result in results:
        model.files[result.file.path] = result.file
        for extra in result.extra_files:
            model.files.setdefault(extra.path, extra)
        for entity in result.entities:
            model.add_entity(entity)
        for library, names in result.externals.items():
            merged = sorted(set(names) | set(model.externals[library].names if library in model.externals else ()))
            model.externals[library] = External(library, tuple(merged))
    for result in results:
        for edge in result.edges:
            if _known(model, edge.source) and _known(model, edge.target):
                model.add_edge(edge)
    return model


def _known(model: DerivedModel, endpoint: str) -> bool:
    return endpoint in model.entities or endpoint in model.files or endpoint.startswith("external:")
