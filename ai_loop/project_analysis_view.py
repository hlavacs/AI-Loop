"""GUI-independent presentation model for project analysis results."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProjectTreeNode:
    """One displayable node in the project-analysis hierarchy."""

    node_id: str
    label: str
    kind: str
    line: int | None = None
    end_line: int | None = None
    summary: str = ""
    children: tuple[ProjectTreeNode, ...] = ()


@dataclass(frozen=True)
class SourceLocation:
    """A source file and inclusive line range selected in the hierarchy."""

    path: Path
    line: int
    end_line: int

    @property
    def line_range(self) -> tuple[int, int]:
        return self.line, self.end_line


@dataclass(frozen=True)
class DiagramNode:
    """A laid-out diagram node linked to an existing project tree node."""

    node_id: str
    label: str
    kind: str
    tree_node_id: str
    source_path: str
    line: int
    end_line: int
    description: str
    x: int
    y: int
    width: int
    height: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.node_id,
            "label": self.label,
            "kind": self.kind,
            "tree_node_id": self.tree_node_id,
            "source_location": {
                "path": self.source_path,
                "line": self.line,
                "end_line": self.end_line,
            },
            "description": self.description,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class DiagramEdge:
    """A directed relationship between two diagram node IDs."""

    source: str
    target: str
    kind: str
    callee_method: str | None = None
    call_line: int | None = None
    callee_line: int | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
        }
        if self.callee_method is not None:
            result["callee_method"] = self.callee_method
        if self.call_line is not None:
            result["call_line"] = self.call_line
        if self.callee_line is not None:
            result["callee_line"] = self.callee_line
        return result


@dataclass(frozen=True)
class ProjectDiagram:
    """Serializable diagram data with a deterministic, toolkit-free layout."""

    nodes: tuple[DiagramNode, ...]
    edges: tuple[DiagramEdge, ...]
    width: int
    height: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.as_dict() for node in self.nodes],
            "edges": [edge.as_dict() for edge in self.edges],
            "width": self.width,
            "height": self.height,
        }


def add_project_analysis_exclusion(
    excluded_folders: tuple[str, ...],
    project_directory: str | Path,
    selected_folder: str | Path,
) -> tuple[str, ...]:
    """Add a project-relative folder unless it is already excluded."""

    project_root = Path(project_directory).expanduser().resolve()
    selected_path = Path(selected_folder).expanduser().resolve()
    try:
        relative_path = selected_path.relative_to(project_root).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"selected folder is outside project directory: {selected_folder}"
        ) from exc
    if relative_path in excluded_folders:
        return excluded_folders
    return (*excluded_folders, relative_path)


def remove_project_analysis_exclusion(
    excluded_folders: tuple[str, ...], selected_folder: str
) -> tuple[str, ...]:
    """Remove a project-relative folder from an exclusion selection."""

    return tuple(folder for folder in excluded_folders if folder != selected_folder)


def _layout_diagram(
    nodes: list[dict[str, Any]], edges: list[DiagramEdge]
) -> ProjectDiagram:
    """Place nodes in a stable grid without depending on a GUI toolkit."""

    node_width = 176
    node_height = 58
    horizontal_gap = 54
    vertical_gap = 52
    margin = 28
    columns = min(4, max(1, _grid_columns(len(nodes))))
    laid_out = []
    for index, node in enumerate(nodes):
        column = index % columns
        row = index // columns
        laid_out.append(
            DiagramNode(
                node_id=str(node["id"]),
                label=str(node["label"]),
                kind=str(node["kind"]),
                tree_node_id=str(node["tree_node_id"]),
                source_path=str(node["source_path"]),
                line=int(node["line"]),
                end_line=int(node["end_line"]),
                description=str(node.get("description", "")),
                x=margin + column * (node_width + horizontal_gap),
                y=margin + row * (node_height + vertical_gap),
                width=node_width,
                height=node_height,
            )
        )
    rows = max(1, (len(nodes) + columns - 1) // columns)
    used_columns = min(columns, max(1, len(nodes)))
    width = (
        2 * margin
        + used_columns * node_width
        + (used_columns - 1) * horizontal_gap
    )
    height = 2 * margin + rows * node_height + (rows - 1) * vertical_gap
    return ProjectDiagram(tuple(laid_out), tuple(edges), width, height)


def _grid_columns(node_count: int) -> int:
    columns = 1
    while columns * columns < node_count:
        columns += 1
    return columns


class ProjectAnalysisController:
    """Adapt an ``analyze_project`` model for a tree/source-code view.

    This class intentionally knows nothing about Tkinter. A GUI can render
    :attr:`root_node` recursively and pass selected node IDs to
    :meth:`resolve_selection` to obtain the source range to display.
    """

    _SYMBOL_GROUPS = (
        ("classes", "Classes", "class"),
        ("functions", "Functions", "function"),
        ("data_types", "Data Types", "data_type"),
    )

    def __init__(self, model: dict[str, Any]) -> None:
        self.model = model
        self.project_path = Path(str(model["path"])).expanduser().resolve()
        self._locations: dict[str, SourceLocation] = {}
        self._nodes: dict[str, ProjectTreeNode] = {}
        self._insights = self._normalized_insights()
        self.root_node = self.build_tree()

    @property
    def insights(self) -> dict[str, Any]:
        """Return project-level counts in a GUI-independent representation."""

        return dict(self._insights)

    @property
    def platform_summary(self) -> dict[str, dict[str, Any]]:
        """Return detected per-platform capabilities keyed by platform name."""

        platforms = self._insights.get("platforms", {})
        if not isinstance(platforms, dict):
            return {}
        return {
            str(name): dict(details)
            for name, details in platforms.items()
            if isinstance(details, dict)
        }

    @property
    def insights_summary(self) -> str:
        """Return a compact multiline summary suitable for any GUI toolkit."""

        insights = self._insights
        lines = [
            (
                f"Project: {insights['file_count']} files, "
                f"{insights['line_count']} lines"
            ),
            (
                f"Symbols: {insights['class_count']} classes, "
                f"{insights['function_count']} functions, "
                f"{insights['data_type_count']} data types"
            ),
            (
                f"Potential problems: {insights['issue_count']} issues in "
                f"{insights['files_with_issues']} files"
            ),
        ]
        per_language = insights.get("per_language", {})
        language_parts = []
        if isinstance(per_language, dict):
            for language, counts in sorted(per_language.items()):
                if not isinstance(counts, dict) or not counts.get("file_count"):
                    continue
                language_parts.append(
                    f"{self._display_name(str(language))}: "
                    f"{counts.get('file_count', 0)} files / "
                    f"{counts.get('line_count', 0)} lines"
                )
        if language_parts:
            lines.append("Languages: " + "; ".join(language_parts))

        platform_parts = []
        for platform_name, details in sorted(self.platform_summary.items()):
            platform_parts.append(
                f"{self._display_name(platform_name)} "
                f"({details.get('file_count', 0)} files, "
                f"{details.get('marker_count', 0)} markers)"
            )
        if platform_parts:
            capability = (
                "multiplatform signals detected"
                if insights.get("multiplatform_capable")
                else "platform-specific signals detected"
            )
            lines.append(f"Platforms: {'; '.join(platform_parts)} — {capability}")
        else:
            lines.append("Platforms: no platform-specific signals detected")
        return "\n".join(lines)

    def class_diagram(self) -> dict[str, Any]:
        """Return a serializable class/inheritance graph with layout data."""

        nodes: list[dict[str, Any]] = []
        names_by_file: dict[int, dict[str, str]] = {}
        names_global: dict[str, list[str]] = {}
        files = self._sorted_files()
        for file_index, file_model in enumerate(files):
            relative_path = Path(str(file_model["path"])).as_posix()
            file_names: dict[str, str] = {}
            for symbol_index, symbol in enumerate(file_model.get("classes", ())):
                node_id = f"file:{file_index}:classes:{symbol_index}"
                tree_node = self.node(node_id)
                location = self.resolve_selection(node_id)
                if tree_node is None or location is None:
                    continue
                qualified_name = str(
                    symbol.get("qualified_name") or symbol.get("name") or tree_node.label
                )
                simple_name = str(symbol.get("name") or qualified_name)
                nodes.append(
                    {
                        "id": node_id,
                        "label": qualified_name,
                        "kind": "class",
                        "tree_node_id": node_id,
                        "source_path": relative_path,
                        "line": location.line,
                        "end_line": location.end_line,
                        "description": tree_node.summary,
                    }
                )
                aliases = {qualified_name, simple_name}
                if file_model.get("language") == "python":
                    module_name = self._python_module(relative_path)
                    if module_name:
                        aliases.update(
                            {
                                f"{module_name}.{qualified_name}",
                                f"{module_name}.{simple_name}",
                            }
                        )
                for name in aliases:
                    file_names[name] = node_id
                    names_global.setdefault(name, []).append(node_id)
            names_by_file[file_index] = file_names

        edges: list[DiagramEdge] = []
        seen_edges: set[tuple[str, str, str]] = set()
        for file_index, file_model in enumerate(files):
            for relationship in file_model.get("relationships", ()):
                kind = str(relationship.get("kind", ""))
                if kind not in {"inherits", "extends", "base_class"}:
                    continue
                source = self._resolve_class_name(
                    str(relationship.get("source", "")),
                    names_by_file.get(file_index, {}),
                    names_global,
                )
                target = self._resolve_class_name(
                    str(relationship.get("target", "")),
                    names_by_file.get(file_index, {}),
                    names_global,
                )
                edge_key = (source or "", target or "", "inherits")
                if source and target and source != target and edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edges.append(DiagramEdge(source, target, "inherits"))
        return _layout_diagram(nodes, edges).as_dict()

    def dependency_diagram(self) -> dict[str, Any]:
        """Return project-local Python import and C++ include dependencies."""

        files = self._sorted_files()
        nodes = []
        paths: dict[str, str] = {}
        modules: dict[str, str] = {}
        for file_index, file_model in enumerate(files):
            relative_path = Path(str(file_model["path"])).as_posix()
            node_id = f"file:{file_index}"
            location = self.resolve_selection(node_id)
            if location is None:
                continue
            nodes.append(
                {
                    "id": node_id,
                    "label": relative_path,
                    "kind": "file",
                    "tree_node_id": node_id,
                    "source_path": relative_path,
                    "line": location.line,
                    "end_line": location.end_line,
                }
            )
            paths[relative_path] = node_id
            if relative_path.endswith(".py"):
                modules[self._python_module(relative_path)] = node_id

        edges: list[DiagramEdge] = []
        seen_edges: set[tuple[str, str, str]] = set()
        for file_index, file_model in enumerate(files):
            source_id = f"file:{file_index}"
            relative_path = Path(str(file_model["path"])).as_posix()
            if file_model.get("language") == "python":
                targets = self._python_import_targets(
                    relative_path, file_model.get("imports", ()), modules
                )
                kind = "imports"
            else:
                targets = self._cpp_include_targets(
                    relative_path, file_model.get("includes", ()), paths
                )
                kind = "includes"
            for target_id in targets:
                edge_key = (source_id, target_id, kind)
                if source_id != target_id and edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edges.append(DiagramEdge(*edge_key))
        return _layout_diagram(nodes, edges).as_dict()

    def call_graph_diagram(self) -> dict[str, Any]:
        """Return class nodes and resolved project-class method-call edges."""

        class_diagram = self.class_diagram()
        nodes = []
        node_ids: dict[tuple[str, str], str] = {}
        for node in class_diagram.get("nodes", ()):
            if not isinstance(node, dict):
                continue
            location = node.get("source_location", {})
            if not isinstance(location, dict):
                continue
            source_path = Path(str(location.get("path", ""))).as_posix()
            label = str(node.get("label", ""))
            node_id = str(node.get("id", ""))
            if not node_id:
                continue
            nodes.append(
                {
                    "id": node_id,
                    "label": label,
                    "kind": "class",
                    "tree_node_id": str(node.get("tree_node_id", node_id)),
                    "source_path": source_path,
                    "line": self._line_number(location.get("line"), 1),
                    "end_line": self._line_number(
                        location.get("end_line"),
                        self._line_number(location.get("line"), 1),
                    ),
                    "description": str(node.get("description", "")),
                }
            )
            node_ids[(source_path, label)] = node_id

        edges: list[DiagramEdge] = []
        seen_edges: set[tuple[str, str, str, int]] = set()
        relationships = self.model.get("call_relationships", ())
        for relationship in (
            relationships if isinstance(relationships, (list, tuple)) else ()
        ):
            if not isinstance(relationship, dict):
                continue
            caller_path = Path(str(relationship.get("caller_path", ""))).as_posix()
            callee_path = Path(str(relationship.get("callee_path", ""))).as_posix()
            source = node_ids.get(
                (caller_path, str(relationship.get("caller_class", "")))
            )
            target = node_ids.get(
                (callee_path, str(relationship.get("callee_class", "")))
            )
            if source is None or target is None:
                continue
            call_line = self._line_number(relationship.get("line"), 1)
            callee_line = self._line_number(
                relationship.get("callee_line"), call_line
            )
            callee_method = str(relationship.get("callee_method", ""))
            edge_key = (source, target, callee_method, call_line)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            edges.append(
                DiagramEdge(
                    source,
                    target,
                    "calls",
                    callee_method=callee_method,
                    call_line=call_line,
                    callee_line=callee_line,
                )
            )
        return _layout_diagram(nodes, edges).as_dict()

    def build_tree(self) -> ProjectTreeNode:
        """Build and return the complete project/file/symbol hierarchy."""

        self._locations.clear()
        self._nodes.clear()
        files = self._sorted_files()
        file_nodes = tuple(
            self._build_file_node(index, file_model)
            for index, file_model in enumerate(files)
        )
        languages = self.model.get("languages", {})
        language_summary = ", ".join(
            f"{name}: {count}" for name, count in sorted(languages.items()) if count
        )
        totals = (
            f"{self.model.get('file_count', len(file_nodes))} files, "
            f"{self.model.get('line_count', 0)} lines"
        )
        summary = f"{totals} ({language_summary})" if language_summary else totals
        root = ProjectTreeNode(
            node_id="project",
            label=str(self.model.get("name") or self.project_path.name),
            kind="project",
            summary=summary,
            children=file_nodes,
        )
        self._nodes[root.node_id] = root
        return root

    def _sorted_files(self) -> list[dict[str, Any]]:
        return sorted(
            self.model.get("files", ()), key=lambda item: str(item.get("path", ""))
        )

    @staticmethod
    def _resolve_class_name(
        name: str,
        names_in_file: dict[str, str],
        names_global: dict[str, list[str]],
    ) -> str | None:
        if name in names_in_file:
            return names_in_file[name]
        matches = names_global.get(name, ())
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _python_module(relative_path: str) -> str:
        path = Path(relative_path)
        parts = list(path.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    @classmethod
    def _python_import_targets(
        cls,
        source_path: str,
        imports: Any,
        modules: dict[str, str],
    ) -> list[str]:
        source_module = cls._python_module(source_path)
        source_file = Path(source_path)
        source_package = (
            source_module.split(".")
            if source_file.stem == "__init__"
            else source_module.split(".")[:-1]
        )
        targets = []
        for imported in imports if isinstance(imports, (list, tuple)) else ():
            if isinstance(imported, str):
                candidates = [imported]
            elif isinstance(imported, dict):
                module = str(imported.get("module", ""))
                name = str(imported.get("name", ""))
                try:
                    level = max(0, int(imported.get("level", 0)))
                except (TypeError, ValueError):
                    level = 0
                if level:
                    keep = max(0, len(source_package) - level + 1)
                    base_parts = [*source_package[:keep], *module.split(".")]
                    base = ".".join(part for part in base_parts if part)
                else:
                    base = module
                candidates = [base]
                if imported.get("kind") == "from_import" and name != "*":
                    imported_module = ".".join(
                        part for part in (base, name) if part
                    )
                    candidates.insert(0, imported_module)
            else:
                continue
            target = next((modules[item] for item in candidates if item in modules), None)
            if target is not None:
                targets.append(target)
        return targets

    @staticmethod
    def _cpp_include_targets(
        source_path: str,
        includes: Any,
        paths: dict[str, str],
    ) -> list[str]:
        source_parent = Path(source_path).parent
        targets = []
        for included in includes if isinstance(includes, (list, tuple)) else ():
            include_path = (
                str(included.get("path", ""))
                if isinstance(included, dict)
                else str(included)
            )
            if not include_path:
                continue
            relative_candidate = posixpath.normpath(
                (source_parent / include_path).as_posix()
            )
            normalized_include = posixpath.normpath(Path(include_path).as_posix())
            candidates = [relative_candidate, normalized_include]
            target = next((paths[item] for item in candidates if item in paths), None)
            if target is None:
                suffix_matches = [
                    node_id
                    for path, node_id in paths.items()
                    if path == include_path or path.endswith(f"/{include_path}")
                ]
                if len(suffix_matches) == 1:
                    target = suffix_matches[0]
            if target is not None:
                targets.append(target)
        return targets

    def node(self, node_id: str) -> ProjectTreeNode | None:
        """Return display metadata for *node_id*, if it exists."""

        return self._nodes.get(node_id)

    def resolve_selection(self, node_id: str) -> SourceLocation | None:
        """Resolve a file or symbol node to an absolute source location."""

        return self._locations.get(node_id)

    def _normalized_insights(self) -> dict[str, Any]:
        files = self.model.get("files", ())
        languages = self.model.get("languages", {})
        calculated = {
            "file_count": self.model.get("file_count", len(files)),
            "line_count": self.model.get("line_count", 0),
            "class_count": sum(len(item.get("classes", ())) for item in files),
            "function_count": sum(len(item.get("functions", ())) for item in files),
            "data_type_count": sum(len(item.get("data_types", ())) for item in files),
            "issue_count": sum(len(item.get("issues", ())) for item in files),
            "files_with_issues": sum(bool(item.get("issues")) for item in files),
            "per_language": {
                str(language): {
                    "file_count": count,
                    "line_count": sum(
                        int(item.get("line_count", 0))
                        for item in files
                        if item.get("language") == language
                    ),
                }
                for language, count in languages.items()
            },
            "platforms": {},
            "multiplatform_capable": False,
        }
        supplied = self.model.get("insights", {})
        if isinstance(supplied, dict):
            calculated.update(supplied)
        return calculated

    @staticmethod
    def _display_name(name: str) -> str:
        names = {"cpp": "C++", "macos": "macOS"}
        return names.get(name, name.replace("_", " ").title())

    def _build_file_node(
        self, file_index: int, file_model: dict[str, Any]
    ) -> ProjectTreeNode:
        node_id = f"file:{file_index}"
        relative_path = Path(str(file_model["path"]))
        source_path = (self.project_path / relative_path).resolve()
        try:
            source_path.relative_to(self.project_path)
        except ValueError as exc:
            raise ValueError(
                f"source path escapes project root: {relative_path}"
            ) from exc

        line_count = max(1, self._line_number(file_model.get("line_count"), 1))
        self._locations[node_id] = SourceLocation(source_path, 1, line_count)
        groups = tuple(
            self._build_symbol_group(
                file_index,
                source_path,
                file_model,
                model_key,
                label,
                kind,
            )
            for model_key, label, kind in self._SYMBOL_GROUPS
            if file_model.get(model_key)
        )
        issues = self._build_issue_group(file_index, source_path, file_model)
        children = (*groups, *((issues,) if issues is not None else ()))
        language = str(file_model.get("language", "source"))
        node = ProjectTreeNode(
            node_id=node_id,
            label=relative_path.as_posix(),
            kind="file",
            line=1,
            end_line=line_count,
            summary=f"{language}, {line_count} lines",
            children=children,
        )
        self._nodes[node_id] = node
        return node

    def _build_symbol_group(
        self,
        file_index: int,
        source_path: Path,
        file_model: dict[str, Any],
        model_key: str,
        label: str,
        kind: str,
    ) -> ProjectTreeNode:
        group_id = f"file:{file_index}:{model_key}"
        symbols = tuple(
            self._build_symbol_node(
                group_id,
                source_path,
                file_model,
                symbol_index,
                symbol,
                kind,
            )
            for symbol_index, symbol in enumerate(file_model.get(model_key, ()))
        )
        node = ProjectTreeNode(
            node_id=group_id,
            label=f"{label} ({len(symbols)})",
            kind="group",
            summary=f"{len(symbols)} {label.lower()}",
            children=symbols,
        )
        self._nodes[group_id] = node
        return node

    def _build_symbol_node(
        self,
        group_id: str,
        source_path: Path,
        file_model: dict[str, Any],
        symbol_index: int,
        symbol: dict[str, Any],
        kind: str,
    ) -> ProjectTreeNode:
        node_id = f"{group_id}:{symbol_index}"
        line = self._line_number(symbol.get("line"), 1)
        end_line = max(line, self._line_number(symbol.get("end_line"), line))
        self._locations[node_id] = SourceLocation(source_path, line, end_line)
        symbol_kind = str(symbol.get("kind") or kind)
        details = [symbol_kind]
        if bases := symbol.get("bases"):
            details.append(f"bases: {', '.join(map(str, bases))}")
        if return_type := symbol.get("return_type"):
            details.append(f"returns: {return_type}")
        if data_type := symbol.get("type"):
            details.append(f"type: {data_type}")
        children: tuple[ProjectTreeNode, ...] = ()
        if kind == "class":
            children = self._build_class_member_nodes(
                node_id, source_path, file_model, symbol
            )
            data_count = sum(child.kind == "data_member" for child in children)
            method_count = sum(child.kind == "method" for child in children)
            relative_path = source_path.relative_to(self.project_path).as_posix()
            label = str(symbol.get("qualified_name") or symbol.get("name") or kind)
            details = [
                (
                    f"{label} — {relative_path}, lines {line}–{end_line}; "
                    f"{data_count} {self._plural(data_count, 'data member')}, "
                    f"{method_count} {self._plural(method_count, 'method')}"
                )
            ]
        node = ProjectTreeNode(
            node_id=node_id,
            label=str(symbol.get("qualified_name") or symbol.get("name") or kind),
            kind=symbol_kind,
            line=line,
            end_line=end_line,
            summary="; ".join(details),
            children=children,
        )
        self._nodes[node_id] = node
        return node

    def _build_class_member_nodes(
        self,
        class_node_id: str,
        source_path: Path,
        file_model: dict[str, Any],
        class_symbol: dict[str, Any],
    ) -> tuple[ProjectTreeNode, ...]:
        """Return the analyzer's direct class data and methods in source order."""

        class_name = str(
            class_symbol.get("qualified_name") or class_symbol.get("name") or ""
        )
        method_names = {str(name) for name in class_symbol.get("methods", ())}
        members: list[tuple[int, int, dict[str, Any], str]] = []
        data_members = class_symbol.get("data_members")
        if not isinstance(data_members, (list, tuple)):
            data_members = (
                data_symbol
                for data_symbol in file_model.get("data_types", ())
                if str(data_symbol.get("qualified_name") or "").rpartition(".")[0]
                == class_name
            )
        for index, data_symbol in enumerate(data_members):
            if isinstance(data_symbol, dict):
                members.append(
                    (
                        self._line_number(data_symbol.get("line"), 1),
                        index,
                        data_symbol,
                        "data_member",
                    )
                )
        for index, function_symbol in enumerate(file_model.get("functions", ())):
            qualified_name = str(function_symbol.get("qualified_name") or "")
            if qualified_name in method_names:
                members.append(
                    (
                        self._line_number(function_symbol.get("line"), 1),
                        index,
                        function_symbol,
                        "method",
                    )
                )

        nodes = []
        for member_index, (_, _, member, member_kind) in enumerate(
            sorted(members, key=lambda item: (item[0], item[1], item[3]))
        ):
            node_id = f"{class_node_id}:member:{member_index}"
            line = self._line_number(member.get("line"), 1)
            end_line = max(line, self._line_number(member.get("end_line"), line))
            details = [member_kind.replace("_", " ")]
            if data_type := member.get("type"):
                details.append(f"type: {data_type}")
            if return_type := member.get("return_type"):
                details.append(f"returns: {return_type}")
            node = ProjectTreeNode(
                node_id=node_id,
                label=str(member.get("name") or member.get("qualified_name") or "member"),
                kind=member_kind,
                line=line,
                end_line=end_line,
                summary="; ".join(details),
            )
            self._locations[node_id] = SourceLocation(source_path, line, end_line)
            self._nodes[node_id] = node
            nodes.append(node)
        return tuple(nodes)

    @staticmethod
    def _plural(count: int, singular: str) -> str:
        return singular if count == 1 else f"{singular}s"

    def _build_issue_group(
        self,
        file_index: int,
        source_path: Path,
        file_model: dict[str, Any],
    ) -> ProjectTreeNode | None:
        issues = file_model.get("issues", ())
        if not issues:
            return None
        group_id = f"file:{file_index}:issues"
        issue_nodes: list[ProjectTreeNode] = []
        for issue_index, issue in enumerate(issues):
            node_id = f"{group_id}:{issue_index}"
            line = self._line_number(issue.get("line"), 1)
            end_line = max(line, self._line_number(issue.get("end_line"), line))
            self._locations[node_id] = SourceLocation(source_path, line, end_line)
            node = ProjectTreeNode(
                node_id=node_id,
                label=str(issue.get("message") or issue.get("kind") or "Issue"),
                kind=str(issue.get("kind") or "issue"),
                line=line,
                end_line=end_line,
                summary=str(issue.get("message") or ""),
            )
            self._nodes[node_id] = node
            issue_nodes.append(node)
        group = ProjectTreeNode(
            node_id=group_id,
            label=f"Issues ({len(issue_nodes)})",
            kind="group",
            summary=f"{len(issue_nodes)} potential problems",
            children=tuple(issue_nodes),
        )
        self._nodes[group_id] = group
        return group

    @staticmethod
    def _line_number(value: Any, default: int) -> int:
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return default
