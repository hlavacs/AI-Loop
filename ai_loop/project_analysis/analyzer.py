"""Lightweight, dependency-free project source analysis."""

from __future__ import annotations

import ast
import os
import re
import tokenize
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ProjectModel = dict[str, Any]

_LANGUAGES = {
    ".py": "python",
    ".h": "cpp",
    ".h++": "cpp",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".c++": "cpp",
    ".ixx": "cpp",
    ".ccm": "cpp",
    ".cppm": "cpp",
    ".cxxm": "cpp",
    ".c++m": "cpp",
    ".mpp": "cpp",
    ".mxx": "cpp",
}
_IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}

_PYTHON_PLATFORM_VALUES = {
    "cygwin": "windows",
    "darwin": "macos",
    "linux": "linux",
    "linux2": "linux",
    "mac": "macos",
    "macos": "macos",
    "msys": "windows",
    "nt": "windows",
    "posix": "posix",
    "win32": "windows",
    "windows": "windows",
}
_CPP_PLATFORM_MACROS = {
    "_MSC_VER": "windows",
    "_WIN32": "windows",
    "_WIN64": "windows",
    "__APPLE__": "macos",
    "__MACH__": "macos",
    "__linux": "linux",
    "__linux__": "linux",
}
_CPP_PLATFORM_INCLUDES = {
    "TargetConditionals.h": "macos",
    "mach/mach.h": "macos",
    "sys/epoll.h": "linux",
    "unistd.h": "posix",
    "windows.h": "windows",
}


def analyze_project(
    path: str | os.PathLike[str],
    exclude_folders: Iterable[str] | None = None,
) -> ProjectModel:
    """Analyze *path* and return a JSON-serializable project hierarchy.

    Python is parsed with :mod:`ast`; C++ is inspected with deliberately
    lightweight lexical heuristics. Files in common generated, cache, and
    version-control directories are skipped. Invalid Python files remain in
    the result and report their syntax error in the file's ``issues`` list.

    Args:
        path: Directory whose source tree should be analyzed.
        exclude_folders: Optional folder paths, relative to *path*, whose
            contents should be skipped.

    Raises:
        FileNotFoundError: If *path* does not exist.
        NotADirectoryError: If *path* is not a directory.
        ValueError: If an excluded folder is outside *path*.
    """

    root = Path(path).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"project directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"project path is not a directory: {root}")
    root = root.resolve()
    excluded_folders = _normalize_excluded_folders(root, exclude_folders)

    files: list[dict[str, Any]] = []
    language_counts = {"python": 0, "cpp": 0}
    total_lines = 0
    for source_path in _source_files(root, excluded_folders):
        language = _LANGUAGES[source_path.suffix.lower()]
        source = _read_source(source_path, language)
        if language == "python":
            file_model = _analyze_python(source)
        else:
            file_model = _analyze_cpp(source)
        file_model.update(
            {
                "path": source_path.relative_to(root).as_posix(),
                "language": language,
                "line_count": len(source.splitlines()),
            }
        )
        files.append(file_model)
        language_counts[language] += 1
        total_lines += file_model["line_count"]

    insights = _project_insights(files, language_counts, total_lines)
    call_relationships = _project_call_relationships(files)

    return {
        "name": root.name,
        "path": str(root),
        "file_count": len(files),
        "line_count": total_lines,
        "languages": language_counts,
        "files": files,
        "insights": insights,
        "call_relationships": call_relationships,
    }


def _normalize_excluded_folders(
    root: Path, exclude_folders: Iterable[str] | None
) -> set[str]:
    normalized: set[str] = set()
    for folder in exclude_folders or ():
        folder = folder.strip()
        if not folder:
            continue
        candidate = Path(folder.replace("\\", "/"))
        resolved = (root / candidate).resolve()
        try:
            normalized.add(resolved.relative_to(root).as_posix())
        except ValueError as exc:
            raise ValueError(
                f"excluded folder is outside project directory: {folder}"
            ) from exc
    return normalized


def _source_files(root: Path, exclude_folders: Iterable[str] = ()) -> Iterable[Path]:
    excluded = set(exclude_folders)
    for current, directories, filenames in os.walk(root):
        current_path = Path(current)
        current_relative = current_path.relative_to(root).as_posix()
        if current_relative in excluded:
            directories[:] = []
            continue
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in _IGNORED_DIRECTORIES
            and (current_path / directory).relative_to(root).as_posix()
            not in excluded
        )
        for filename in sorted(filenames):
            candidate = current_path / filename
            if candidate.suffix.lower() in _LANGUAGES:
                yield candidate


def _read_source(path: Path, language: str) -> str:
    if language == "python":
        try:
            with tokenize.open(path) as source_file:
                return source_file.read()
        except (LookupError, SyntaxError, UnicodeError):
            pass
    return path.read_text(encoding="utf-8", errors="replace")


def _project_insights(
    files: list[dict[str, Any]],
    language_counts: dict[str, int],
    total_lines: int,
) -> dict[str, Any]:
    lines_by_language = {language: 0 for language in language_counts}
    class_count = 0
    function_count = 0
    data_type_count = 0
    issue_count = 0
    files_with_issues = 0
    platform_files: dict[str, set[str]] = {}
    platform_languages: dict[str, set[str]] = {}
    platform_marker_counts: dict[str, int] = {}
    portable_marker_count = 0

    for file_model in files:
        language = str(file_model.get("language", "unknown"))
        lines_by_language[language] = lines_by_language.get(language, 0) + int(
            file_model.get("line_count", 0)
        )
        class_count += len(file_model.get("classes", ()))
        function_count += len(file_model.get("functions", ()))
        data_type_count += len(file_model.get("data_types", ()))
        issues = file_model.get("issues", ())
        issue_count += len(issues)
        files_with_issues += bool(issues)
        for marker in file_model.get("platform_markers", ()):
            platform_name = str(marker.get("platform", "portable"))
            if platform_name == "portable":
                portable_marker_count += 1
                continue
            platform_files.setdefault(platform_name, set()).add(
                str(file_model.get("path", ""))
            )
            platform_languages.setdefault(platform_name, set()).add(language)
            platform_marker_counts[platform_name] = (
                platform_marker_counts.get(platform_name, 0) + 1
            )

    platforms = {
        platform_name: {
            "marker_count": platform_marker_counts[platform_name],
            "file_count": len(platform_files[platform_name]),
            "files": sorted(platform_files[platform_name]),
            "languages": sorted(platform_languages[platform_name]),
        }
        for platform_name in sorted(platform_files)
    }
    detected_platforms = sorted(platforms)
    per_language = {
        language: {
            "file_count": count,
            "line_count": lines_by_language.get(language, 0),
        }
        for language, count in sorted(language_counts.items())
    }
    return {
        "file_count": len(files),
        "line_count": total_lines,
        "files_by_language": dict(sorted(language_counts.items())),
        "lines_by_language": dict(sorted(lines_by_language.items())),
        "per_language": per_language,
        "class_count": class_count,
        "function_count": function_count,
        "data_type_count": data_type_count,
        "issue_count": issue_count,
        "files_with_issues": files_with_issues,
        "platforms": platforms,
        "detected_platforms": detected_platforms,
        "portable_marker_count": portable_marker_count,
        "multiplatform_capable": len(
            {"windows", "linux", "macos"}.intersection(detected_platforms)
        )
        > 1,
    }


def _expression_name(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError):
        return None


class _PythonSymbols(ast.NodeVisitor):
    def __init__(self) -> None:
        self.classes: list[dict[str, Any]] = []
        self.functions: list[dict[str, Any]] = []
        self.data_types: list[dict[str, Any]] = []
        self.relationships: list[dict[str, str]] = []
        self.imports: list[dict[str, Any]] = []
        self._scopes: list[tuple[str, str]] = []
        self._class_records: list[dict[str, Any]] = []
        self._function_types: list[dict[str, str]] = []

    def _qualified(self, name: str) -> str:
        return ".".join([*(scope[1] for scope in self._scopes), name])

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualified_name = self._qualified(node.name)
        bases = [name for base in node.bases if (name := _expression_name(base))]
        record: dict[str, Any] = {
            "name": node.name,
            "qualified_name": qualified_name,
            "line": node.lineno,
            "end_line": getattr(node, "end_lineno", node.lineno),
            "bases": bases,
            "methods": [],
            "data_members": [],
        }
        if docstring := ast.get_docstring(node, clean=True):
            record["docstring"] = docstring
        self.classes.append(record)
        for base in bases:
            self.relationships.append(
                {"kind": "inherits", "source": qualified_name, "target": base}
            )

        self._scopes.append(("class", node.name))
        self._class_records.append(record)
        self.generic_visit(node)
        self._class_records.pop()
        self._scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, is_async=True)

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_async: bool
    ) -> None:
        qualified_name = self._qualified(node.name)
        is_method = bool(self._scopes and self._scopes[-1][0] == "class")
        owner = (
            str(self._class_records[-1]["qualified_name"])
            if is_method and self._class_records
            else None
        )
        arguments = [
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ]
        parameters = [argument.arg for argument in arguments]
        parameter_types = {
            argument.arg: annotation
            for argument in arguments
            if (annotation := _expression_name(argument.annotation))
        }
        if node.args.vararg:
            parameters.append(f"*{node.args.vararg.arg}")
        if node.args.kwarg:
            parameters.append(f"**{node.args.kwarg.arg}")
        record = {
            "name": node.name,
            "qualified_name": qualified_name,
            "line": node.lineno,
            "end_line": getattr(node, "end_lineno", node.lineno),
            "kind": "method" if is_method else "function",
            "async": is_async,
            "parameters": parameters,
            "return_type": _expression_name(node.returns),
            "calls": _python_direct_calls(node),
            "call_sites": _python_direct_call_sites(node),
        }
        if docstring := ast.get_docstring(node, clean=True):
            record["docstring"] = docstring
        if owner is not None:
            record["owner"] = owner
        self.functions.append(record)
        if is_method and self._class_records:
            class_record = self._class_records[-1]
            class_record["methods"].append(qualified_name)
            self.relationships.append(
                {
                    "kind": "member_of",
                    "source": qualified_name,
                    "target": class_record["qualified_name"],
                }
            )

        self._scopes.append(("function", node.name))
        self._function_types.append(parameter_types)
        self.generic_visit(node)
        self._function_types.pop()
        self._scopes.pop()

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        scope_kind = self._scopes[-1][0] if self._scopes else "module"
        annotation = _expression_name(node.annotation)
        if (
            scope_kind == "function"
            and self._function_types
            and isinstance(node.target, ast.Name)
            and annotation
        ):
            self._function_types[-1][node.target.id] = annotation
        if self._class_records:
            self._record_data_member(node.target, annotation, node.lineno)
        if scope_kind in {"module", "class"}:
            name = _expression_name(node.target)
            if name:
                self.data_types.append(
                    {
                        "name": name,
                        "qualified_name": self._qualified(name),
                        "line": node.lineno,
                        "kind": "type_alias"
                        if annotation in {"TypeAlias", "typing.TypeAlias"}
                        else "annotated_variable",
                        "type": annotation,
                    }
                )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._class_records:
            if self._record_slots(node):
                self.generic_visit(node)
                return
            inferred_type = (
                _expression_name(node.value.func)
                if isinstance(node.value, ast.Call)
                else type(node.value.value).__name__
                if isinstance(node.value, ast.Constant)
                else type(node.value).__name__.lower()
                if isinstance(node.value, (ast.Dict, ast.List, ast.Set, ast.Tuple))
                else self._function_types[-1].get(node.value.id)
                if isinstance(node.value, ast.Name) and self._function_types
                else None
            )
            for target in node.targets:
                self._record_data_member(target, inferred_type, node.lineno)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if self._class_records:
            self._record_data_member(node.target, None, node.lineno)
        self.generic_visit(node)

    def _record_slots(self, node: ast.Assign) -> bool:
        """Record names declared through a class-level ``__slots__`` value."""

        scope_kind = self._scopes[-1][0] if self._scopes else "module"
        if scope_kind != "class" or not any(
            isinstance(target, ast.Name) and target.id == "__slots__"
            for target in node.targets
        ):
            return False
        values = (
            node.value.elts
            if isinstance(node.value, (ast.List, ast.Tuple, ast.Set))
            else (node.value,)
        )
        for value in values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                self._record_named_data_member(value.value, None, node.lineno)
        return True

    def _record_data_member(
        self, target: ast.AST, annotation: str | None, line: int
    ) -> None:
        if isinstance(target, (ast.List, ast.Tuple)):
            for element in target.elts:
                self._record_data_member(element, annotation, line)
            return
        scope_kind = self._scopes[-1][0] if self._scopes else "module"
        if scope_kind == "class" and isinstance(target, ast.Name):
            name = target.id
        elif (
            scope_kind == "function"
            and isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id in {"self", "cls"}
        ):
            name = target.attr
        else:
            return
        self._record_named_data_member(name, annotation, line)

    def _record_named_data_member(
        self, name: str, annotation: str | None, line: int
    ) -> None:
        class_record = self._class_records[-1]
        qualified_name = f"{class_record['qualified_name']}.{name}"
        if any(
            member.get("qualified_name") == qualified_name
            for member in class_record["data_members"]
        ):
            return
        class_record["data_members"].append(
            {
                "name": name,
                "qualified_name": qualified_name,
                "line": line,
                "end_line": line,
                "kind": "data_member",
                "type": annotation,
            }
        )

    def visit_Import(self, node: ast.Import) -> None:
        for imported in node.names:
            self.imports.append(
                {
                    "kind": "import",
                    "module": imported.name,
                    "name": imported.name,
                    "alias": imported.asname,
                    "level": 0,
                    "line": node.lineno,
                }
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for imported in node.names:
            self.imports.append(
                {
                    "kind": "from_import",
                    "module": node.module or "",
                    "name": imported.name,
                    "alias": imported.asname,
                    "level": node.level,
                    "line": node.lineno,
                }
            )


class _DirectCallVisitor(ast.NodeVisitor):
    def __init__(self, root: ast.AST) -> None:
        self.root = root
        self.calls: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        name = _expression_name(node.func)
        if name:
            self.calls.add(name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


class _DetailedCallVisitor(ast.NodeVisitor):
    """Collect direct calls and simple receiver types within one function."""

    def __init__(self, root: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.root = root
        self.call_sites: list[dict[str, Any]] = []
        self._types: dict[str, str] = {}
        for argument in [
            *root.args.posonlyargs,
            *root.args.args,
            *root.args.kwonlyargs,
        ]:
            annotation = _expression_name(argument.annotation)
            if annotation:
                self._types[argument.arg] = annotation

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            receiver = _expression_name(node.func.value)
            if receiver:
                receiver_type = self._receiver_type(node.func.value, receiver)
                self.call_sites.append(
                    {
                        "name": _expression_name(node.func) or node.func.attr,
                        "method": node.func.attr,
                        "receiver": receiver,
                        "receiver_type": receiver_type,
                        "line": node.lineno,
                    }
                )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        assigned_type = self._constructed_type(node.value)
        if assigned_type:
            for target in node.targets:
                if name := _expression_name(target):
                    self._types[name] = assigned_type
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        name = _expression_name(node.target)
        annotation = _expression_name(node.annotation)
        if name and annotation:
            self._types[name] = annotation
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def _receiver_type(self, node: ast.AST, receiver: str) -> str | None:
        if receiver in {"self", "cls"}:
            return receiver
        if constructed_type := self._constructed_type(node):
            return constructed_type
        return self._types.get(receiver)

    @staticmethod
    def _constructed_type(node: ast.AST | None) -> str | None:
        if isinstance(node, ast.Call):
            return _expression_name(node.func)
        return None


def _python_direct_calls(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    visitor = _DirectCallVisitor(node)
    visitor.visit(node)
    return sorted(visitor.calls)


def _python_direct_call_sites(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[dict[str, Any]]:
    visitor = _DetailedCallVisitor(node)
    visitor.visit(node)
    return sorted(
        visitor.call_sites,
        key=lambda item: (int(item["line"]), str(item["name"])),
    )


def _platform_marker(
    platform_name: str, kind: str, line: int, marker: str
) -> dict[str, Any]:
    return {
        "platform": platform_name,
        "kind": kind,
        "line": line,
        "marker": marker,
    }


def _deduplicate_platform_markers(
    markers: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    for marker in markers:
        key = (
            str(marker["platform"]),
            str(marker["kind"]),
            int(marker["line"]),
            str(marker["marker"]),
        )
        unique[key] = marker
    return sorted(
        unique.values(),
        key=lambda item: (
            int(item["line"]),
            str(item["platform"]),
            str(item["kind"]),
            str(item["marker"]),
        ),
    )


def _python_platform_markers(tree: ast.AST) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    platform_import_names: set[str] = set()
    platform_function_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                if imported.name == "platform":
                    name = imported.asname or imported.name
                    platform_import_names.add(name)
                    markers.append(
                        _platform_marker("portable", "module", node.lineno, name)
                    )
        elif isinstance(node, ast.ImportFrom) and node.module == "platform":
            for imported in node.names:
                name = imported.asname or imported.name
                platform_function_names.add(name)
                markers.append(
                    _platform_marker(
                        "portable", "module", node.lineno, f"platform.{imported.name}"
                    )
                )

    def expression_is_platform_api(node: ast.AST) -> bool:
        name = _expression_name(node) or ""
        if name in {"sys.platform", "os.name"}:
            return True
        if isinstance(node, ast.Call):
            function_name = _expression_name(node.func) or ""
            return function_name in platform_function_names or any(
                function_name == imported or function_name.startswith(f"{imported}.")
                for imported in platform_import_names
            )
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            name = _expression_name(node)
            if name in {"sys.platform", "os.name"}:
                markers.append(_platform_marker("portable", "api", node.lineno, name))
        elif isinstance(node, ast.Call) and expression_is_platform_api(node):
            name = _expression_name(node.func) or "platform"
            markers.append(
                _platform_marker("portable", "api", node.lineno, f"{name}()")
            )
        elif isinstance(node, (ast.If, ast.IfExp)):
            condition = node.test
            if not any(
                expression_is_platform_api(item) for item in ast.walk(condition)
            ):
                continue
            expression = _expression_name(condition) or "platform condition"
            for item in ast.walk(condition):
                if not isinstance(item, ast.Constant) or not isinstance(
                    item.value, str
                ):
                    continue
                platform_name = _PYTHON_PLATFORM_VALUES.get(item.value.casefold())
                if platform_name:
                    markers.append(
                        _platform_marker(
                            platform_name, "branch", node.lineno, expression
                        )
                    )

    return _deduplicate_platform_markers(markers)


def _analyze_python(source: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "classes": [],
        "functions": [],
        "data_types": [],
        "relationships": [],
        "imports": [],
        "includes": [],
        "issues": [],
        "platform_markers": [],
    }
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        result["issues"].append(
            {
                "kind": "syntax_error",
                "message": exc.msg,
                "line": exc.lineno,
                "column": exc.offset,
            }
        )
        return result

    symbols = _PythonSymbols()
    symbols.visit(tree)
    result.update(
        {
            "classes": symbols.classes,
            "functions": symbols.functions,
            "data_types": symbols.data_types,
            "relationships": symbols.relationships,
            "imports": symbols.imports,
            "platform_markers": _python_platform_markers(tree),
        }
    )
    return result


_CPP_TYPE_RE = re.compile(
    r"\b(?P<kind>class|struct|enum(?:\s+class)?)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*(?:final\s*)?"
    r"(?::\s*(?P<bases>[^;{]+))?\s*(?P<terminator>[{;])"
)
_CPP_USING_RE = re.compile(r"\busing\s+(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<type>[^;]+);")
_CPP_TYPEDEF_RE = re.compile(
    r"\btypedef\s+(?P<type>[^;{}]+?)\s+(?P<name>[A-Za-z_]\w*)\s*;"
)
_CPP_FUNCTION_RE = re.compile(
    r"(?m)^[ \t]*(?P<head>[^#;{}\n]*?)"
    r"(?P<name>(?:[A-Za-z_]\w*::)*~?[A-Za-z_]\w*)\s*"
    r"\((?P<parameters>[^;{}()]*(?:\([^()]*\)[^;{}()]*)*)\)\s*"
    r"(?P<suffix>(?:(?:const|override|final)\b\s*|"
    r"noexcept(?:\s*\([^)]*\))?\s*|->\s*[^;{]+\s*)*)"
    r"(?P<terminator>[;{])"
)
_CPP_DATA_MEMBER_RE = re.compile(r"(?m)^[ \t]*(?P<declaration>[^#;()\n]+);")
_CPP_QUALIFIED_CALL_RE = re.compile(
    r"(?<![\w:])(?P<class>(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)::"
    r"(?P<method>[A-Za-z_]\w*)\s*\("
)
_CPP_CONTROL_WORDS = {"catch", "for", "if", "return", "sizeof", "switch", "while"}


def _cpp_platform_markers(source: str) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    guard_pattern = re.compile(r"^\s*#\s*(?:if|ifdef|ifndef|elif)\b(?P<body>.*)$")
    include_pattern = re.compile(r"^\s*#\s*include\s*[<\"](?P<header>[^>\"]+)[>\"]")
    for line_number, line in enumerate(source.splitlines(), start=1):
        if guard := guard_pattern.match(line):
            body = guard.group("body")
            for macro, platform_name in _CPP_PLATFORM_MACROS.items():
                if re.search(rf"(?<!\w){re.escape(macro)}(?!\w)", body):
                    markers.append(
                        _platform_marker(
                            platform_name, "preprocessor_guard", line_number, macro
                        )
                    )
        if include := include_pattern.match(line):
            header = include.group("header")
            for known_header, platform_name in _CPP_PLATFORM_INCLUDES.items():
                if header.casefold() == known_header.casefold():
                    markers.append(
                        _platform_marker(
                            platform_name,
                            "platform_include",
                            line_number,
                            header,
                        )
                    )
                    break
    return _deduplicate_platform_markers(markers)


def _cpp_includes(source: str) -> list[dict[str, Any]]:
    include_pattern = re.compile(
        r'^\s*#\s*include\s*(?P<opening>[<"])(?P<path>[^>"]+)[>"]'
    )
    includes = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        if match := include_pattern.match(line):
            includes.append(
                {
                    "path": match.group("path"),
                    "system": match.group("opening") == "<",
                    "line": line_number,
                }
            )
    return includes


def _cpp_leading_comment(source: str, offset: int) -> str | None:
    """Return a documentation comment immediately preceding a declaration."""

    prefix = source[:offset].rstrip()
    if prefix.endswith("*/"):
        start = prefix.rfind("/*")
        if start >= 0:
            return prefix[start:]

    lines = prefix.splitlines()
    comments: list[str] = []
    for line in reversed(lines):
        if line.lstrip().startswith("//"):
            comments.append(line)
            continue
        break
    if comments:
        return "\n".join(reversed(comments))
    return None


def _strip_cpp_comments_and_literals(source: str) -> str:
    """Replace comments and literals with spaces while preserving line offsets."""

    pattern = re.compile(
        r"//[^\n]*|/\*.*?\*/|R\"(?P<delimiter>[^ ()\\\t\r\n]{0,16})\(.*?\)(?P=delimiter)\"|"
        r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
        re.DOTALL,
    )

    def replace(match: re.Match[str]) -> str:
        return "".join(
            "\n" if character == "\n" else " " for character in match.group()
        )

    return pattern.sub(replace, source)


def _line_number(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _matching_brace(source: str, opening: int) -> int | None:
    depth = 0
    for position in range(opening, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return position
    return None


def _cpp_base_name(base: str) -> str:
    base = re.sub(r"\b(?:public|protected|private|virtual)\b", "", base)
    return " ".join(base.split())


def _cpp_parameters(parameters: str) -> list[str]:
    if not parameters.strip() or parameters.strip() == "void":
        return []
    return [part.strip() for part in parameters.split(",") if part.strip()]


def _cpp_qualified_call_sites(
    source: str, body_start: int, body_end: int
) -> list[dict[str, Any]]:
    sites = []
    for match in _CPP_QUALIFIED_CALL_RE.finditer(source, body_start, body_end):
        class_name = match.group("class")
        method_name = match.group("method")
        sites.append(
            {
                "name": f"{class_name}::{method_name}",
                "method": method_name,
                "receiver": class_name,
                "receiver_type": class_name,
                "line": _line_number(source, match.start()),
            }
        )
    return sites


def _analyze_cpp(source: str) -> dict[str, Any]:
    cleaned = _strip_cpp_comments_and_literals(source)
    classes: list[dict[str, Any]] = []
    data_types: list[dict[str, Any]] = []
    functions: list[dict[str, Any]] = []
    relationships: list[dict[str, str]] = []
    class_ranges: list[tuple[int, int, dict[str, Any]]] = []

    for match in _CPP_TYPE_RE.finditer(cleaned):
        raw_kind = match.group("kind")
        kind = "enum" if raw_kind.startswith("enum") else raw_kind
        name = match.group("name")
        line = _line_number(cleaned, match.start())
        bases = [
            parsed
            for item in (match.group("bases") or "").split(",")
            if (parsed := _cpp_base_name(item))
        ]
        record: dict[str, Any] = {
            "name": name,
            "qualified_name": name,
            "line": line,
            "end_line": line,
            "kind": kind,
            "bases": bases,
            "methods": [],
            "data_members": [],
        }
        if leading_comment := _cpp_leading_comment(source, match.start()):
            record["leading_comment"] = leading_comment
        if kind in {"class", "struct"}:
            classes.append(record)
        if kind in {"struct", "enum"}:
            data_types.append(
                {"name": name, "line": line, "kind": kind, "type": raw_kind}
            )
        for base in bases:
            relationships.append({"kind": "inherits", "source": name, "target": base})
        if match.group("terminator") == "{":
            opening = match.end() - 1
            closing = _matching_brace(cleaned, opening)
            if closing is not None:
                record["end_line"] = _line_number(cleaned, closing)
                if kind in {"class", "struct"}:
                    class_ranges.append((opening, closing, record))

    for opening, closing, class_record in class_ranges:
        class_body = cleaned[opening + 1 : closing]
        for match in _CPP_DATA_MEMBER_RE.finditer(class_body):
            member_offset = opening + 1 + match.start()
            prefix = cleaned[opening + 1 : member_offset]
            if prefix.count("{") != prefix.count("}"):
                continue
            declaration = " ".join(match.group("declaration").split())
            parsed = re.fullmatch(
                r"(?P<type>.+?\S)\s+[*&]?(?P<name>[A-Za-z_]\w*)"
                r"(?:\s*\[[^\]]*\])?(?:\s*(?:=.*|\{.*\}))?",
                declaration,
            )
            if parsed is None or declaration.startswith(
                ("friend ", "static_assert ", "typedef ", "using ")
            ):
                continue
            line = _line_number(cleaned, member_offset)
            name = parsed.group("name")
            class_record["data_members"].append(
                {
                    "name": name,
                    "qualified_name": f"{class_record['qualified_name']}::{name}",
                    "line": line,
                    "end_line": line,
                    "kind": "data_member",
                    "type": parsed.group("type"),
                }
            )

    for pattern, kind in ((_CPP_USING_RE, "using"), (_CPP_TYPEDEF_RE, "typedef")):
        for match in pattern.finditer(cleaned):
            data_types.append(
                {
                    "name": match.group("name"),
                    "line": _line_number(cleaned, match.start()),
                    "kind": kind,
                    "type": " ".join(match.group("type").split()),
                }
            )

    for match in _CPP_FUNCTION_RE.finditer(cleaned):
        name = match.group("name")
        simple_name = name.rsplit("::", 1)[-1]
        if simple_name in _CPP_CONTROL_WORDS:
            continue
        head = " ".join(match.group("head").split())
        containing_class = next(
            (
                record
                for opening, closing, record in reversed(class_ranges)
                if opening < match.start() < closing
            ),
            None,
        )
        explicit_owner = name.rsplit("::", 1)[0] if "::" in name else None
        owner = containing_class["name"] if containing_class else explicit_owner
        is_constructor = bool(
            owner and simple_name.lstrip("~") == owner.rsplit("::", 1)[-1]
        )
        if not head and not is_constructor:
            continue
        qualified_name = (
            name
            if explicit_owner
            else f"{owner}::{simple_name}"
            if owner
            else simple_name
        )
        line = _line_number(cleaned, match.start())
        record = {
            "name": simple_name,
            "qualified_name": qualified_name,
            "line": line,
            "end_line": line,
            "kind": "method" if owner else "function",
            "parameters": _cpp_parameters(match.group("parameters")),
            "return_type": None if is_constructor else (head or None),
            "declaration": match.group("terminator") == ";",
            "calls": [],
            "call_sites": [],
        }
        if leading_comment := _cpp_leading_comment(source, match.start()):
            record["leading_comment"] = leading_comment
        if owner:
            record["owner"] = owner
        if match.group("terminator") == "{":
            body_start = match.end()
            closing = _matching_brace(cleaned, body_start - 1)
            if closing is not None:
                record["end_line"] = _line_number(cleaned, closing)
                record["call_sites"] = _cpp_qualified_call_sites(
                    cleaned, body_start, closing
                )
                record["calls"] = sorted(
                    {str(site["name"]) for site in record["call_sites"]}
                )
        functions.append(record)
        if owner:
            if containing_class:
                containing_class["methods"].append(qualified_name)
            relationships.append(
                {"kind": "member_of", "source": qualified_name, "target": owner}
            )

    return {
        "classes": classes,
        "functions": functions,
        "data_types": data_types,
        "relationships": relationships,
        "imports": [],
        "includes": _cpp_includes(source),
        "issues": [],
        "platform_markers": _cpp_platform_markers(source),
    }


def _project_call_relationships(
    files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve method call sites whose caller and callee are project classes."""

    names_by_file: dict[int, dict[str, list[dict[str, Any]]]] = {}
    names_global: dict[str, list[dict[str, Any]]] = {}
    imports_by_file: dict[int, dict[str, str]] = {}

    def add_alias(
        aliases: dict[str, list[dict[str, Any]]],
        alias: str,
        class_record: dict[str, Any],
    ) -> None:
        if alias:
            aliases.setdefault(alias, []).append(class_record)

    for file_index, file_model in enumerate(files):
        relative_path = str(file_model.get("path", ""))
        module_name = _python_module_name(relative_path)
        local_names: dict[str, list[dict[str, Any]]] = {}
        for class_model in file_model.get("classes", ()):
            if not isinstance(class_model, dict):
                continue
            qualified_name = str(
                class_model.get("qualified_name") or class_model.get("name") or ""
            )
            simple_name = str(class_model.get("name") or qualified_name)
            class_record = {
                "file_index": file_index,
                "path": relative_path,
                "name": qualified_name,
                "simple_name": simple_name,
                "model": class_model,
                "methods": {},
            }
            aliases = {qualified_name, simple_name}
            if file_model.get("language") == "python" and module_name:
                aliases.update(
                    {
                        f"{module_name}.{qualified_name}",
                        f"{module_name}.{simple_name}",
                    }
                )
            for alias in aliases:
                add_alias(local_names, alias, class_record)
                add_alias(names_global, alias, class_record)
        names_by_file[file_index] = local_names
        imports_by_file[file_index] = _python_import_aliases(
            file_model.get("imports"), relative_path
        )

    def resolve_class(reference: str, file_index: int) -> dict[str, Any] | None:
        for candidate in _class_reference_candidates(reference):
            imported = _expand_import_alias(
                candidate, imports_by_file.get(file_index, {})
            )
            for resolved_name in (candidate, imported):
                matches = names_by_file.get(file_index, {}).get(resolved_name, ())
                if len(matches) == 1:
                    return matches[0]
                matches = names_global.get(resolved_name, ())
                if len(matches) == 1:
                    return matches[0]
        return None

    for file_index, file_model in enumerate(files):
        for function in file_model.get("functions", ()):
            if not isinstance(function, dict) or not function.get("owner"):
                continue
            owner = resolve_class(str(function["owner"]), file_index)
            if owner is None:
                continue
            method_name = str(function.get("name") or "")
            existing = owner["methods"].get(method_name)
            if existing is None or (
                existing.get("declaration") and not function.get("declaration")
            ):
                owner["methods"][method_name] = {
                    **function,
                    "path": str(file_model.get("path", "")),
                }

    relationships = []
    seen: set[tuple[str, str, str, str, int]] = set()
    for file_index, file_model in enumerate(files):
        for function in file_model.get("functions", ()):
            if not isinstance(function, dict) or not function.get("owner"):
                continue
            caller = resolve_class(str(function["owner"]), file_index)
            if caller is None:
                continue
            call_sites = function.get("call_sites", ())
            if not isinstance(call_sites, (list, tuple)):
                continue
            for call_site in call_sites:
                if not isinstance(call_site, dict):
                    continue
                reference = str(
                    call_site.get("receiver_type")
                    or call_site.get("receiver")
                    or ""
                )
                if reference.startswith(("self.", "cls.")):
                    member_name = reference.split(".", 1)[1]
                    member = next(
                        (
                            item
                            for item in caller["model"].get("data_members", ())
                            if isinstance(item, dict)
                            and item.get("name") == member_name
                            and item.get("type")
                        ),
                        None,
                    )
                    if member is not None:
                        reference = str(member["type"])
                callee = (
                    caller
                    if reference in {"self", "cls"}
                    else resolve_class(reference, file_index)
                )
                method_name = str(call_site.get("method") or "")
                if callee is None or not method_name:
                    continue
                callee_method = callee["methods"].get(method_name)
                if callee_method is None:
                    continue
                try:
                    call_line = max(1, int(call_site.get("line", 1)))
                    callee_line = max(1, int(callee_method.get("line", 1)))
                except (TypeError, ValueError):
                    continue
                relationship = {
                    "caller_class": caller["name"],
                    "callee_class": callee["name"],
                    "caller_method": str(function.get("qualified_name") or ""),
                    "callee_method": str(
                        callee_method.get("qualified_name") or method_name
                    ),
                    "caller_path": caller["path"],
                    "callee_path": callee["path"],
                    "call_path": str(file_model.get("path", "")),
                    "callee_method_path": str(callee_method.get("path", "")),
                    "line": call_line,
                    "callee_line": callee_line,
                }
                key = (
                    relationship["caller_path"],
                    relationship["caller_class"],
                    relationship["callee_path"],
                    relationship["callee_method"],
                    call_line,
                )
                if key not in seen:
                    seen.add(key)
                    relationships.append(relationship)
    return sorted(
        relationships,
        key=lambda item: (
            str(item["caller_path"]),
            int(item["line"]),
            str(item["caller_class"]),
            str(item["callee_class"]),
            str(item["callee_method"]),
        ),
    )


def _python_module_name(relative_path: str) -> str:
    path = Path(relative_path)
    if path.suffix != ".py":
        return ""
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _python_import_aliases(imports: Any, source_path: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    source_module = _python_module_name(source_path)
    source_file = Path(source_path)
    source_package = (
        source_module.split(".")
        if source_file.stem == "__init__"
        else source_module.split(".")[:-1]
    )
    for imported in imports if isinstance(imports, (list, tuple)) else ():
        if not isinstance(imported, dict):
            continue
        module = str(imported.get("module", ""))
        name = str(imported.get("name", ""))
        alias = str(imported.get("alias") or name)
        if imported.get("kind") == "from_import":
            try:
                level = max(0, int(imported.get("level", 0)))
            except (TypeError, ValueError):
                level = 0
            if level:
                keep = max(0, len(source_package) - level + 1)
                module = ".".join(
                    part for part in (*source_package[:keep], module) if part
                )
            target = ".".join(part for part in (module, name) if part)
        else:
            target = name
            alias = str(imported.get("alias") or name.split(".", 1)[0])
        if alias and target:
            aliases[alias] = target
    return aliases


def _expand_import_alias(reference: str, aliases: dict[str, str]) -> str:
    first, separator, remainder = reference.partition(".")
    target = aliases.get(first)
    if target is None:
        return reference
    return target + (f".{remainder}" if separator else "")


def _class_reference_candidates(reference: str) -> list[str]:
    reference = reference.strip().strip("'\"")
    if not reference:
        return []
    candidates = [reference]
    optional = re.fullmatch(r"(?:typing\.)?Optional\[(.+)]", reference)
    if optional:
        candidates.insert(0, optional.group(1).strip())
    if "|" in reference:
        candidates = [
            part.strip() for part in reference.split("|") if part.strip() != "None"
        ] + candidates
    return list(dict.fromkeys(candidates))
