"""GUI-independent presentation model for project analysis results."""

from __future__ import annotations

import math
import posixpath
import re
from collections.abc import Iterable
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
    description: str = ""


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
    subtitle: str
    group: str
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
            "subtitle": self.subtitle,
            "group": self.group,
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
    call_count: int = 1

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
        if self.call_count > 1:
            result["call_count"] = self.call_count
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
    node_height = 72 if any(node.get("subtitle") for node in nodes) else 58
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
                subtitle=str(node.get("subtitle", "")),
                group=str(node.get("group", "")),
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


def _layout_grouped_diagram(
    nodes: list[dict[str, Any]],
    edges: list[DiagramEdge],
    groups: list[dict[str, Any]],
) -> dict[str, Any]:
    """Lay out members and classes according to their call dependencies.

    Connected members occupy a ring in their class panel. Every class involved
    in a cross-class call occupies one shared outer ring, while all remaining
    classes use a separate compact grid. A top-level main() group is instead
    fixed at the center of its call component, with its callees on the ring.
    """

    margin = 32
    section_gap = 100
    nodes_by_group: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        nodes_by_group.setdefault(str(node.get("group", "")), []).append(node)

    node_groups = {
        str(node["id"]): str(node.get("group", "")) for node in nodes
    }
    node_degree = {str(node["id"]): 0 for node in nodes}
    group_adjacency: dict[str, set[str]] = {
        str(group["id"]): set() for group in groups
    }
    for edge in edges:
        if edge.source in node_degree:
            node_degree[edge.source] += 1
        if edge.target in node_degree:
            node_degree[edge.target] += 1
        source_group = node_groups.get(edge.source)
        target_group = node_groups.get(edge.target)
        if source_group and target_group and source_group != target_group:
            group_adjacency.setdefault(source_group, set()).add(target_group)
            group_adjacency.setdefault(target_group, set()).add(source_group)

    panels = {
        str(group["id"]): _member_panel_geometry(
            nodes_by_group.get(str(group["id"]), ()), node_degree
        )
        for group in groups
    }
    group_order = {str(group["id"]): index for index, group in enumerate(groups)}
    components = _dependency_components(group_adjacency, group_order)
    external_components = [component for component in components if len(component) > 1]
    external_ids = [
        group_id for component in external_components for group_id in component
    ]
    external_set = set(external_ids)
    call_root_group_id = next(
        (
            str(group["id"])
            for group in groups
            if group.get("central_call_root")
        ),
        None,
    )
    central_group_id = call_root_group_id
    primary_ids = external_ids
    if central_group_id is not None:
        primary_ids = [
            central_group_id,
            *(group_id for group_id in external_ids if group_id != central_group_id),
        ]
        external_set = set(primary_ids)
    compact_ids = [
        str(group["id"])
        for group in groups
        if str(group["id"]) not in external_set
    ]
    external_geometry = (
        _centered_call_geometry(
            central_group_id,
            [group_id for group_id in primary_ids if group_id != central_group_id],
            panels,
        )
        if central_group_id is not None
        else _circular_class_geometry(primary_ids, panels)
    )
    compact_geometry = _compact_class_geometry(
        compact_ids,
        panels,
        preferred_width=max(1, int(external_geometry["width"])),
    )
    placements: dict[str, tuple[int, int]] = {}
    for group_id, position in external_geometry["positions"].items():
        placements[group_id] = (margin + position[0], margin + position[1])
    compact_y = margin
    if primary_ids:
        compact_y += int(external_geometry["height"]) + section_gap
    for group_id, position in compact_geometry["positions"].items():
        placements[group_id] = (margin + position[0], compact_y + position[1])
    component_indexes = {
        group_id: component_index
        for component_index, component in enumerate(components)
        for group_id in component
    }

    laid_out: list[DiagramNode] = []
    laid_out_groups: list[dict[str, Any]] = []
    groups_by_id = {str(group["id"]): group for group in groups}
    for group in groups:
        group_id = str(group["id"])
        panel = panels[group_id]
        panel_x, panel_y = placements[group_id]
        dependency_area = panel.get("dependency_area")
        class_layout = "compact"
        if group_id == call_root_group_id:
            class_layout = "call_root_center"
        elif group_id in external_set:
            class_layout = "external_call_ring"
        laid_out_group = {
            **groups_by_id[group_id],
            "x": panel_x,
            "y": panel_y,
            "width": int(panel["width"]),
            "height": int(panel["height"]),
            "dependency_cluster": component_indexes[group_id],
            "class_layout": class_layout,
        }
        if isinstance(dependency_area, dict):
            laid_out_group["dependency_area"] = {
                **dependency_area,
                "x": panel_x + int(dependency_area["x"]),
                "y": panel_y + int(dependency_area["y"]),
            }
        laid_out_groups.append(laid_out_group)
        for node in nodes_by_group.get(group_id, ()):
            node_x, node_y = panel["positions"][str(node["id"])]
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
                    subtitle=str(node.get("subtitle", "")),
                    group=group_id,
                    x=panel_x + int(node_x),
                    y=panel_y + int(node_y),
                    width=196,
                    height=72,
                )
            )

    content_width = max(
        int(external_geometry["width"]), int(compact_geometry["width"]), 1
    )
    content_height = int(external_geometry["height"])
    if primary_ids and compact_ids:
        content_height += section_gap
    content_height += int(compact_geometry["height"])
    height = content_height + 2 * margin if groups else 2 * margin
    width = content_width + 2 * margin if groups else 2 * margin
    diagram = ProjectDiagram(tuple(laid_out), tuple(edges), width, height).as_dict()
    diagram["groups"] = laid_out_groups
    diagram["layout"] = "dependency_radial"
    diagram["external_class_count"] = len(primary_ids)
    diagram["compact_class_count"] = len(compact_ids)
    diagram["central_call_root_id"] = call_root_group_id
    return diagram


def _member_panel_geometry(
    members: Iterable[dict[str, Any]], node_degree: dict[str, int]
) -> dict[str, Any]:
    """Return local geometry for a dynamically sized class-member panel."""

    node_width = 196
    node_height = 72
    node_gap = 52
    panel_padding = 24
    panel_header = 44
    members = list(members)
    connected = sorted(
        (member for member in members if node_degree.get(str(member["id"]), 0)),
        key=lambda member: (
            not bool(member.get("call_root_center")),
            -node_degree.get(str(member["id"]), 0),
            str(member.get("label", "")).casefold(),
            str(member["id"]),
        ),
    )
    unconnected = sorted(
        (member for member in members if not node_degree.get(str(member["id"]), 0)),
        key=lambda member: (
            str(member.get("kind", "")),
            str(member.get("label", "")).casefold(),
            str(member["id"]),
        ),
    )

    connected_count = len(connected)
    anchored_call_root = bool(connected and connected[0].get("call_root_center"))
    radius = 0.0
    if connected_count == 0:
        connected_width = connected_height = 0
    elif connected_count == 1:
        connected_width, connected_height = node_width, node_height
    elif anchored_call_root:
        clearance = math.hypot(node_width + node_gap, node_height + node_gap)
        satellite_count = connected_count - 1
        radius = clearance
        if satellite_count > 1:
            radius = max(
                radius,
                clearance / (2 * math.sin(math.pi / satellite_count)),
            )
        connected_width = math.ceil(2 * radius + node_width)
        connected_height = math.ceil(2 * radius + node_height)
    elif connected_count == 2:
        connected_width = 2 * node_width + node_gap
        connected_height = node_height
    else:
        clearance = math.hypot(node_width + node_gap, node_height + node_gap)
        satellite_count = connected_count - 1
        radius = max(
            clearance,
            clearance / (2 * math.sin(math.pi / satellite_count)),
        )
        connected_width = math.ceil(2 * radius + node_width)
        connected_height = math.ceil(2 * radius + node_height)

    unconnected_columns = min(6, max(1, _grid_columns(len(unconnected))))
    unconnected_rows = max(
        1 if unconnected else 0,
        (len(unconnected) + unconnected_columns - 1) // unconnected_columns,
    )
    unconnected_width = (
        unconnected_columns * node_width
        + max(0, unconnected_columns - 1) * node_gap
        if unconnected
        else 0
    )
    unconnected_height = (
        unconnected_rows * node_height
        + max(0, unconnected_rows - 1) * node_gap
        if unconnected
        else 0
    )
    content_width = max(node_width, connected_width, unconnected_width)
    panel_width = content_width + 2 * panel_padding
    connected_x = panel_padding + (content_width - connected_width) // 2
    connected_y = panel_header + panel_padding
    positions: dict[str, tuple[int, int]] = {}

    if connected_count == 1:
        positions[str(connected[0]["id"])] = (connected_x, connected_y)
    elif connected_count == 2 and not anchored_call_root:
        for index, member in enumerate(connected):
            positions[str(member["id"])] = (
                connected_x + index * (node_width + node_gap),
                connected_y,
            )
    elif connected_count > 1:
        center_x = connected_x + connected_width / 2
        center_y = connected_y + connected_height / 2
        positions[str(connected[0]["id"])] = (
            round(center_x - node_width / 2),
            round(center_y - node_height / 2),
        )
        satellites = connected[1:]
        for index, member in enumerate(satellites):
            angle = -math.pi / 2 + 2 * math.pi * index / len(satellites)
            positions[str(member["id"])] = (
                round(center_x + radius * math.cos(angle) - node_width / 2),
                round(center_y + radius * math.sin(angle) - node_height / 2),
            )

    separation = node_gap if connected and unconnected else 0
    unconnected_y = connected_y + connected_height + separation
    unconnected_x = panel_padding + (content_width - unconnected_width) // 2
    for index, member in enumerate(unconnected):
        column = index % unconnected_columns
        row = index // unconnected_columns
        positions[str(member["id"])] = (
            unconnected_x + column * (node_width + node_gap),
            unconnected_y + row * (node_height + node_gap),
        )

    content_height = connected_height + separation + unconnected_height
    panel_height = panel_header + 2 * panel_padding + max(node_height, content_height)
    result: dict[str, Any] = {
        "width": panel_width,
        "height": panel_height,
        "positions": positions,
    }
    call_root = next(
        (member for member in members if member.get("call_root_center")), None
    )
    if call_root is not None:
        root_position = positions.get(str(call_root["id"]))
        if root_position is not None:
            result["call_root_anchor"] = {
                "x": root_position[0] + node_width / 2,
                "y": root_position[1] + node_height / 2,
            }
    if connected:
        result["dependency_area"] = {
            "x": connected_x - 12,
            "y": connected_y - 12,
            "width": connected_width + 24,
            "height": connected_height + 24,
            "member_count": connected_count,
        }
    return result


def _dependency_components(
    adjacency: dict[str, set[str]], order: dict[str, int]
) -> list[list[str]]:
    """Return stable, dependency-first connected components of class IDs."""

    unvisited = set(adjacency)
    components: list[list[str]] = []
    while unvisited:
        seed = min(unvisited, key=lambda group_id: order.get(group_id, 0))
        pending = [seed]
        component: set[str] = set()
        while pending:
            group_id = pending.pop()
            if group_id in component:
                continue
            component.add(group_id)
            pending.extend(adjacency.get(group_id, set()) - component)
        unvisited -= component
        start = max(
            component,
            key=lambda group_id: (
                len(adjacency.get(group_id, ())),
                -order.get(group_id, 0),
            ),
        )
        arranged: list[str] = []
        queue = [start]
        queued = {start}
        while queue:
            group_id = queue.pop(0)
            arranged.append(group_id)
            neighbours = sorted(
                adjacency.get(group_id, set()) & component - queued,
                key=lambda item: (
                    -len(adjacency.get(item, ())),
                    order.get(item, 0),
                ),
            )
            queue.extend(neighbours)
            queued.update(neighbours)
        arranged.extend(
            sorted(component - set(arranged), key=lambda item: order.get(item, 0))
        )
        components.append(arranged)
    return sorted(
        components,
        key=lambda component: (-len(component), min(order[item] for item in component)),
    )


def _circular_class_geometry(
    group_ids: list[str],
    panels: dict[str, dict[str, Any]],
    *,
    class_gap: int = 120,
) -> dict[str, Any]:
    """Arrange every class with external calls on one non-overlapping ring."""

    if not group_ids:
        return {"positions": {}, "width": 0, "height": 0}
    positions: dict[str, tuple[int, int]] = {}
    if len(group_ids) == 1:
        group_id = group_ids[0]
        positions[group_id] = (0, 0)
    elif len(group_ids) == 2:
        first, second = group_ids
        positions[first] = (0, 0)
        positions[second] = (int(panels[first]["width"]) + class_gap, 0)
    else:
        count = len(group_ids)
        radius = 0.0
        for first_index, first in enumerate(group_ids):
            for second_index in range(first_index + 1, count):
                second = group_ids[second_index]
                steps = min(second_index - first_index, count - second_index + first_index)
                chord_factor = 2 * math.sin(math.pi * steps / count)
                required_distance = math.hypot(
                    (int(panels[first]["width"]) + int(panels[second]["width"]))
                    / 2
                    + class_gap,
                    (int(panels[first]["height"]) + int(panels[second]["height"]))
                    / 2
                    + class_gap,
                )
                radius = max(radius, required_distance / chord_factor)
        max_width = max(int(panels[group_id]["width"]) for group_id in group_ids)
        max_height = max(int(panels[group_id]["height"]) for group_id in group_ids)
        center = radius + max(max_width, max_height) / 2
        for index, group_id in enumerate(group_ids):
            angle = -math.pi / 2 + 2 * math.pi * index / count
            positions[group_id] = (
                round(
                    center
                    + radius * math.cos(angle)
                    - int(panels[group_id]["width"]) / 2
                ),
                round(
                    center
                    + radius * math.sin(angle)
                    - int(panels[group_id]["height"]) / 2
                ),
            )

    minimum_x = min(position[0] for position in positions.values())
    minimum_y = min(position[1] for position in positions.values())
    normalized = {
        group_id: (position[0] - minimum_x, position[1] - minimum_y)
        for group_id, position in positions.items()
    }
    width = max(
        x + int(panels[group_id]["width"])
        for group_id, (x, _) in normalized.items()
    )
    height = max(
        y + int(panels[group_id]["height"])
        for group_id, (_, y) in normalized.items()
    )
    return {"positions": normalized, "width": width, "height": height}


def _centered_call_geometry(
    center_id: str,
    satellite_ids: list[str],
    panels: dict[str, dict[str, Any]],
    *,
    class_gap: int = 120,
) -> dict[str, Any]:
    """Place one call root at the center of its non-overlapping callee ring."""

    if not satellite_ids:
        return _circular_class_geometry([center_id], panels, class_gap=class_gap)
    center_width = int(panels[center_id]["width"])
    center_height = int(panels[center_id]["height"])
    count = len(satellite_ids)
    radius = 0.0
    for satellite_id in satellite_ids:
        satellite_width = int(panels[satellite_id]["width"])
        satellite_height = int(panels[satellite_id]["height"])
        radius = max(
            radius,
            math.hypot(
                (center_width + satellite_width) / 2 + class_gap,
                (center_height + satellite_height) / 2 + class_gap,
            ),
        )
    if count > 1:
        for first_index, first in enumerate(satellite_ids):
            second = satellite_ids[(first_index + 1) % count]
            chord_factor = 2 * math.sin(math.pi / count)
            required_distance = math.hypot(
                (int(panels[first]["width"]) + int(panels[second]["width"]))
                / 2
                + class_gap,
                (int(panels[first]["height"]) + int(panels[second]["height"]))
                / 2
                + class_gap,
            )
            radius = max(radius, required_distance / chord_factor)

    ring_center = radius + max(
        center_width,
        center_height,
        *(int(panels[group_id]["width"]) for group_id in satellite_ids),
        *(int(panels[group_id]["height"]) for group_id in satellite_ids),
    )
    center_anchor = panels[center_id].get("call_root_anchor", {})
    center_anchor_x = float(center_anchor.get("x", center_width / 2))
    center_anchor_y = float(center_anchor.get("y", center_height / 2))
    positions: dict[str, tuple[int, int]] = {
        center_id: (
            round(ring_center - center_anchor_x),
            round(ring_center - center_anchor_y),
        )
    }
    for index, group_id in enumerate(satellite_ids):
        angle = -math.pi / 2 + 2 * math.pi * index / count
        positions[group_id] = (
            round(
                ring_center
                + radius * math.cos(angle)
                - int(panels[group_id]["width"]) / 2
            ),
            round(
                ring_center
                + radius * math.sin(angle)
                - int(panels[group_id]["height"]) / 2
            ),
        )

    minimum_x = min(position[0] for position in positions.values())
    minimum_y = min(position[1] for position in positions.values())
    normalized = {
        group_id: (x - minimum_x, y - minimum_y)
        for group_id, (x, y) in positions.items()
    }
    width = max(
        x + int(panels[group_id]["width"])
        for group_id, (x, _) in normalized.items()
    )
    height = max(
        y + int(panels[group_id]["height"])
        for group_id, (_, y) in normalized.items()
    )
    return {"positions": normalized, "width": width, "height": height}


def _compact_class_geometry(
    group_ids: list[str],
    panels: dict[str, dict[str, Any]],
    *,
    preferred_width: int,
) -> dict[str, Any]:
    """Pack classes without external calls into a dense variable-size grid."""

    if not group_ids:
        return {"positions": {}, "width": 0, "height": 0}
    gap = 36
    total_area = sum(
        (int(panels[group_id]["width"]) + gap)
        * (int(panels[group_id]["height"]) + gap)
        for group_id in group_ids
    )
    maximum_width = max(int(panels[group_id]["width"]) for group_id in group_ids)
    natural_width = int(math.sqrt(max(1, total_area)) * 1.45)
    row_limit = max(maximum_width, preferred_width, natural_width)
    positions: dict[str, tuple[int, int]] = {}
    cursor_x = 0
    cursor_y = 0
    row_height = 0
    used_width = 0
    for group_id in group_ids:
        panel_width = int(panels[group_id]["width"])
        panel_height = int(panels[group_id]["height"])
        if cursor_x and cursor_x + panel_width > row_limit:
            cursor_x = 0
            cursor_y += row_height + gap
            row_height = 0
        positions[group_id] = (cursor_x, cursor_y)
        cursor_x += panel_width + gap
        row_height = max(row_height, panel_height)
        used_width = max(used_width, cursor_x - gap)
    return {
        "positions": positions,
        "width": used_width,
        "height": cursor_y + row_height,
    }


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
        self._class_names = self._project_class_names()
        self._method_definitions = self._project_method_definitions()
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
                class_category = str(
                    symbol.get("class_category")
                    or ("struct" if symbol.get("kind") == "struct" else "class")
                )
                nodes.append(
                    {
                        "id": node_id,
                        "label": qualified_name,
                        "kind": class_category,
                        "tree_node_id": node_id,
                        "source_path": relative_path,
                        "line": location.line,
                        "end_line": location.end_line,
                        "description": tree_node.description or tree_node.summary,
                        "subtitle": class_category.replace("_", " "),
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

    def call_graph_diagram(
        self,
        *,
        include_unconnected: bool = True,
        selected_class_id: str | None = None,
        collapse_classes: bool = False,
    ) -> dict[str, Any]:
        """Compatibility alias for :meth:`member_graph_diagram`."""

        return self.member_graph_diagram(
            selected_class_id=selected_class_id,
            collapse_classes=collapse_classes,
        )

    def member_graph_diagram(
        self,
        *,
        selected_class_id: str | None = None,
        collapse_classes: bool = False,
    ) -> dict[str, Any]:
        """Return expanded members or collapsed classes with their call edges."""

        nodes, node_ids, global_node_ids, groups = self._member_diagram_nodes()
        aggregated_edges: dict[
            tuple[str, str, str], dict[str, int]
        ] = {}
        relationships = self.model.get("call_relationships", ())
        for relationship in (
            relationships if isinstance(relationships, (list, tuple)) else ()
        ):
            if not isinstance(relationship, dict):
                continue
            caller_method = str(relationship.get("caller_method", ""))
            callee_method = str(relationship.get("callee_method", ""))
            if relationship.get("caller_kind") == "function":
                caller_paths = {
                    Path(str(relationship.get(path_key, ""))).as_posix()
                    for path_key in ("call_path", "caller_path")
                }
                if not any(
                    node_ids.get((path, caller_method))
                    for path in caller_paths
                ):
                    continue
            source = self._resolve_method_node(
                node_ids,
                global_node_ids,
                caller_method,
                relationship.get("line"),
                relationship.get("call_path"),
                relationship.get("caller_path"),
            )
            target = self._resolve_method_node(
                node_ids,
                global_node_ids,
                callee_method,
                relationship.get("callee_line"),
                relationship.get("callee_method_path"),
                relationship.get("callee_path"),
            )
            if source is None or target is None:
                continue
            call_line = self._line_number(relationship.get("line"), 1)
            callee_line = self._line_number(
                relationship.get("callee_line"), call_line
            )
            edge_key = (source, target, callee_method)
            aggregate = aggregated_edges.setdefault(
                edge_key,
                {
                    "call_line": call_line,
                    "callee_line": callee_line,
                    "call_count": 0,
                },
            )
            aggregate["call_line"] = min(aggregate["call_line"], call_line)
            aggregate["call_count"] += 1

        edges = [
            DiagramEdge(
                source,
                target,
                "calls",
                callee_method=callee_method,
                call_line=aggregate["call_line"],
                callee_line=aggregate["callee_line"],
                call_count=aggregate["call_count"],
            )
            for (source, target, callee_method), aggregate in aggregated_edges.items()
        ]

        total_member_count = len(nodes)
        total_class_count = len(groups)
        focused_group = next(
            (group for group in groups if group["id"] == selected_class_id),
            None,
        )
        own_member_count = 0
        external_member_count = 0
        if focused_group is not None:
            own_ids = {
                str(node["id"])
                for node in nodes
                if node.get("group") == selected_class_id
            }
            own_member_count = len(own_ids)
            edges = [edge for edge in edges if edge.source in own_ids]
            external_ids = {edge.target for edge in edges if edge.target not in own_ids}
            external_member_count = len(external_ids)
            included_ids = own_ids | external_ids
            nodes = [node for node in nodes if str(node["id"]) in included_ids]
            included_groups = {
                str(node.get("group", "")) for node in nodes
            } | {selected_class_id}
            groups = [group for group in groups if group["id"] in included_groups]

        incoming = {str(node["id"]): 0 for node in nodes}
        outgoing = {str(node["id"]): 0 for node in nodes}
        for edge in edges:
            outgoing[edge.source] += 1
            incoming[edge.target] += 1
        for node in nodes:
            node_id = str(node["id"])
            if node.get("kind") in {"method", "function"}:
                node["subtitle"] = (
                    f"{incoming[node_id]} incoming · {outgoing[node_id]} outgoing"
                )

        diagram = _layout_grouped_diagram(nodes, edges, groups)
        diagram["total_member_count"] = total_member_count
        diagram["total_class_count"] = total_class_count
        diagram["shown_member_count"] = len(nodes)
        diagram["focused_class_id"] = (
            str(focused_group["id"]) if focused_group is not None else None
        )
        if focused_group is not None:
            external_group_count = sum(
                group["id"] != selected_class_id for group in groups
            )
            diagram["summary"] = (
                f"{focused_group['label']}: {own_member_count} direct "
                f"{self._plural(own_member_count, 'member')}; "
                f"{external_member_count} called "
                f"{self._plural(external_member_count, 'member')} in "
                f"{external_group_count} other "
                f"{self._plural(external_group_count, 'class')}."
            )
        else:
            edge_count = len(edges)
            diagram["summary"] = (
                f"Showing {total_member_count} "
                f"{self._plural(total_member_count, 'member')} across "
                f"{total_class_count} {self._plural(total_class_count, 'class')} "
                f"and {edge_count} resolved {self._plural(edge_count, 'call')}."
            )
        diagram["members_collapsed"] = False
        if collapse_classes:
            return self._collapse_member_classes(diagram)
        return diagram

    @staticmethod
    def _collapse_member_classes(diagram: dict[str, Any]) -> dict[str, Any]:
        """Replace member panels with class boxes in a smaller equivalent layout."""

        expanded_nodes = {
            str(node["id"]): node for node in diagram.get("nodes", ())
        }
        member_groups = {
            node_id: str(node.get("group", ""))
            for node_id, node in expanded_nodes.items()
        }
        collapsed_nodes: list[dict[str, Any]] = []
        node_width = 176
        node_height = 72
        for group in diagram.get("groups", ()):
            group_width = int(group.get("width", node_width))
            group_height = int(group.get("height", node_height))
            collapsed_nodes.append(
                {
                    "id": str(group["id"]),
                    "label": str(group["label"]),
                    "kind": str(group.get("kind", "class")),
                    "tree_node_id": str(
                        group.get("tree_node_id", group["id"])
                    ),
                    "source_location": {
                        "path": str(group.get("source_path", "")),
                        "line": int(group.get("line", 1)),
                        "end_line": int(group.get("end_line", 1)),
                    },
                    "description": str(group.get("description", "")),
                    "subtitle": str(group.get("kind", "class")).replace(
                        "_", " "
                    ),
                    "group": "",
                    "x": int(group.get("x", 0))
                    + (group_width - node_width) // 2,
                    "y": int(group.get("y", 0))
                    + (group_height - node_height) // 2,
                    "width": node_width,
                    "height": node_height,
                }
            )
        layout_kind, collapsed_width, collapsed_height = (
            ProjectAnalysisController._compact_collapsed_class_layout(
                collapsed_nodes, list(diagram.get("groups", ()))
            )
        )

        class_calls: dict[tuple[str, str], int] = {}
        for edge in diagram.get("edges", ()):
            source_group = member_groups.get(str(edge.get("source", "")))
            target_group = member_groups.get(str(edge.get("target", "")))
            if not source_group or not target_group or source_group == target_group:
                continue
            pair = (source_group, target_group)
            try:
                call_count = max(1, int(edge.get("call_count", 1)))
            except (TypeError, ValueError):
                call_count = 1
            class_calls[pair] = class_calls.get(pair, 0) + call_count

        collapsed_edges = []
        for (source, target), call_count in class_calls.items():
            collapsed_edge: dict[str, Any] = {
                "source": source,
                "target": target,
                "kind": "calls",
            }
            if call_count > 1:
                collapsed_edge["call_count"] = call_count
            collapsed_edges.append(collapsed_edge)

        collapsed = {
            **diagram,
            "nodes": collapsed_nodes,
            "edges": collapsed_edges,
            "groups": [],
            "width": collapsed_width,
            "height": collapsed_height,
            "collapsed_layout": layout_kind,
            "shown_member_count": 0,
            "shown_class_count": len(collapsed_nodes),
            "members_collapsed": True,
        }
        class_count = len(collapsed_nodes)
        relationship_count = len(collapsed_edges)
        collapsed["summary"] = (
            f"Showing {class_count} "
            f"{ProjectAnalysisController._plural(class_count, 'class')} and "
            f"{relationship_count} cross-class call "
            f"{ProjectAnalysisController._plural(relationship_count, 'relationship')}; "
            "members hidden."
        )
        return collapsed

    @staticmethod
    def _compact_collapsed_class_layout(
        nodes: list[dict[str, Any]], groups: list[dict[str, Any]]
    ) -> tuple[str, int, int]:
        """Relayout ring and compact classes using the small class boxes."""

        margin = 32
        if not nodes:
            return "small_box_radial", margin * 2, margin * 2

        nodes_by_id = {str(node["id"]): node for node in nodes}
        groups_by_id = {str(group["id"]): group for group in groups}
        external_ids = [
            group_id
            for group_id, group in groups_by_id.items()
            if group.get("class_layout") == "external_call_ring"
            and group_id in nodes_by_id
        ]
        central_id = next(
            (
                group_id
                for group_id, group in groups_by_id.items()
                if group.get("class_layout") == "call_root_center"
                and group_id in nodes_by_id
            ),
            None,
        )
        if external_ids:
            center_x = sum(
                int(groups_by_id[group_id]["x"])
                + int(groups_by_id[group_id]["width"]) / 2
                for group_id in external_ids
            ) / len(external_ids)
            center_y = sum(
                int(groups_by_id[group_id]["y"])
                + int(groups_by_id[group_id]["height"]) / 2
                for group_id in external_ids
            ) / len(external_ids)
            external_ids.sort(
                key=lambda group_id: (
                    math.atan2(
                        int(groups_by_id[group_id]["y"])
                        + int(groups_by_id[group_id]["height"]) / 2
                        - center_y,
                        int(groups_by_id[group_id]["x"])
                        + int(groups_by_id[group_id]["width"]) / 2
                        - center_x,
                    )
                    + math.pi / 2
                )
                % (2 * math.pi)
            )
        primary_ids = [*external_ids, *((central_id,) if central_id else ())]
        external_set = set(primary_ids)
        compact_ids = [
            str(node["id"])
            for node in nodes
            if str(node["id"]) not in external_set
        ]
        panels = {
            str(node["id"]): {
                "width": int(node["width"]),
                "height": int(node["height"]),
            }
            for node in nodes
        }
        external_geometry = (
            _centered_call_geometry(
                central_id, external_ids, panels, class_gap=28
            )
            if central_id is not None
            else _circular_class_geometry(external_ids, panels, class_gap=28)
        )
        compact_geometry = _compact_class_geometry(
            compact_ids,
            panels,
            preferred_width=max(1, int(external_geometry["width"])),
        )
        compact_y = margin
        if primary_ids and compact_ids:
            compact_y += int(external_geometry["height"]) + 60
        for group_id, (x, y) in external_geometry["positions"].items():
            nodes_by_id[group_id]["x"] = margin + x
            nodes_by_id[group_id]["y"] = margin + y
        for group_id, (x, y) in compact_geometry["positions"].items():
            nodes_by_id[group_id]["x"] = margin + x
            nodes_by_id[group_id]["y"] = compact_y + y

        content_width = max(
            int(external_geometry["width"]),
            int(compact_geometry["width"]),
            1,
        )
        content_height = int(external_geometry["height"])
        if primary_ids and compact_ids:
            content_height += 60
        content_height += int(compact_geometry["height"])
        return (
            "small_box_radial",
            content_width + margin * 2,
            content_height + margin * 2,
        )

    def _member_diagram_nodes(
        self,
    ) -> tuple[
        list[dict[str, Any]],
        dict[tuple[str, str], list[str]],
        dict[str, list[str]],
        list[dict[str, Any]],
    ]:
        """Build the main-function core, class panels, and callable aliases."""

        nodes: list[dict[str, Any]] = []
        node_ids: dict[tuple[str, str], list[str]] = {}
        global_node_ids: dict[str, list[str]] = {}
        groups: list[dict[str, Any]] = []
        relationships = [
            relationship
            for relationship in self.model.get("call_relationships", ())
            if isinstance(relationship, dict)
        ]
        free_function_definitions = {
            (
                Path(str(file_model.get("path", ""))).as_posix(),
                str(
                    function_symbol.get("qualified_name")
                    or function_symbol.get("name")
                    or ""
                ),
            )
            for file_model in self._sorted_files()
            for function_symbol in file_model.get("functions", ())
            if isinstance(function_symbol, dict)
            and function_symbol.get("kind") == "function"
            and function_symbol.get("declaration") is not True
        }
        main_groups_by_path: dict[str, str] = {}
        main_group_records: list[dict[str, Any]] = []
        for file_index, file_model in enumerate(self._sorted_files()):
            source_path = Path(str(file_model.get("path", ""))).as_posix()
            for function_index, function_symbol in enumerate(
                file_model.get("functions", ())
            ):
                if (
                    not isinstance(function_symbol, dict)
                    or function_symbol.get("kind") != "function"
                    or function_symbol.get("declaration") is True
                    or str(function_symbol.get("qualified_name") or "") != "main"
                    or main_group_records
                ):
                    continue
                tree_node_id = f"file:{file_index}:functions:{function_index}"
                tree_node = self.node(tree_node_id)
                location = self.resolve_selection(tree_node_id)
                if tree_node is None or location is None:
                    continue
                group_id = f"function-class:{tree_node_id}"
                main_groups_by_path[source_path] = group_id
                main_group_records.append(
                    {
                        "id": group_id,
                        "label": "main()",
                        "tree_node_id": tree_node_id,
                        "description": tree_node.description or tree_node.summary,
                        "kind": "class",
                        "source_path": source_path,
                        "line": location.line,
                        "end_line": location.end_line,
                        "function_as_class": True,
                        "central_call_root": True,
                    }
                )
        groups.extend(main_group_records)
        function_edges_by_caller: dict[
            tuple[str, str], list[tuple[str, str]]
        ] = {}
        for relationship in relationships:
            if (
                relationship.get("caller_kind") != "function"
                or relationship.get("callee_kind") != "function"
            ):
                continue
            caller_ref = (
                Path(str(relationship.get("caller_path", ""))).as_posix(),
                str(relationship.get("caller_method") or ""),
            )
            callee_ref = (
                Path(str(relationship.get("callee_path", ""))).as_posix(),
                str(relationship.get("callee_method") or ""),
            )
            function_edges_by_caller.setdefault(caller_ref, []).append(callee_ref)

        main_path_by_reachable_function: dict[tuple[str, str], str] = {}
        pending_functions: list[tuple[tuple[str, str], str]] = []
        for main_path in main_groups_by_path:
            main_ref = (main_path, "main")
            main_path_by_reachable_function[main_ref] = main_path
            pending_functions.append((main_ref, main_path))
        while pending_functions:
            caller_ref, main_path = pending_functions.pop(0)
            for callee_ref in function_edges_by_caller.get(caller_ref, ()):
                if callee_ref in main_path_by_reachable_function:
                    continue
                main_path_by_reachable_function[callee_ref] = main_path
                pending_functions.append((callee_ref, main_path))
        free_function_refs = set(main_path_by_reachable_function)
        for file_index, file_model in enumerate(self._sorted_files()):
            class_path = Path(str(file_model.get("path", ""))).as_posix()
            for class_index, class_symbol in enumerate(file_model.get("classes", ())):
                class_node = self.node(f"file:{file_index}:classes:{class_index}")
                if class_node is None:
                    continue
                class_name = str(
                    class_symbol.get("qualified_name")
                    or class_symbol.get("name")
                    or class_node.label
                )
                class_location = self.resolve_selection(class_node.node_id)
                class_category = str(
                    class_symbol.get("class_category")
                    or (
                        "struct"
                        if class_symbol.get("kind") == "struct"
                        else "class"
                    )
                )
                groups.append(
                    {
                        "id": class_node.node_id,
                        "label": class_name,
                        "tree_node_id": class_node.node_id,
                        "description": class_node.description,
                        "kind": class_category,
                        "source_path": class_path,
                        "line": class_location.line if class_location else 1,
                        "end_line": (
                            class_location.end_line if class_location else 1
                        ),
                    }
                )
                method_names = tuple(map(str, class_symbol.get("methods", ())))
                for member_node in class_node.children:
                    if member_node.kind not in {"data_member", "method"}:
                        continue
                    location = self.resolve_selection(member_node.node_id)
                    if location is None:
                        continue
                    if member_node.kind == "method":
                        qualified_name = next(
                            (
                                name
                                for name in method_names
                                if self._method_simple_name(name) == member_node.label
                            ),
                            self._qualified_method_name(
                                class_name, member_node.label
                            ),
                        )
                    else:
                        qualified_name = self._qualified_method_name(
                            class_name, member_node.label
                        )
                    source_path = location.path.relative_to(
                        self.project_path
                    ).as_posix()
                    nodes.append(
                        {
                            "id": member_node.node_id,
                            "label": member_node.label,
                            "kind": member_node.kind,
                            "tree_node_id": member_node.node_id,
                            "source_path": source_path,
                            "line": location.line,
                            "end_line": location.end_line,
                            "description": member_node.description,
                            "subtitle": (
                                member_node.summary.removeprefix(
                                    "data member; "
                                )
                                if member_node.kind == "data_member"
                                else ""
                            ),
                            "group": class_node.node_id,
                        }
                    )
                    if member_node.kind == "method":
                        for path in {class_path, source_path}:
                            node_ids.setdefault((path, qualified_name), []).append(
                                member_node.node_id
                            )
                        global_node_ids.setdefault(qualified_name, []).append(
                            member_node.node_id
                        )
            for function_index, function_symbol in enumerate(
                file_model.get("functions", ())
            ):
                if (
                    not isinstance(function_symbol, dict)
                    or (
                        function_symbol.get("kind") != "function"
                        and self._method_has_owning_class(function_symbol)
                    )
                ):
                    continue
                qualified_name = str(
                    function_symbol.get("qualified_name")
                    or function_symbol.get("name")
                    or ""
                )
                simple_name = str(function_symbol.get("name") or qualified_name)
                if (class_path, qualified_name) not in free_function_refs:
                    continue
                if (
                    function_symbol.get("declaration") is True
                    and (class_path, qualified_name) in free_function_definitions
                ):
                    continue
                tree_node_id = f"file:{file_index}:functions:{function_index}"
                tree_node = self.node(tree_node_id)
                location = self.resolve_selection(tree_node_id)
                if tree_node is None or location is None:
                    continue
                source_path = location.path.relative_to(
                    self.project_path
                ).as_posix()
                main_path = main_path_by_reachable_function.get(
                    (class_path, qualified_name)
                )
                group_id = main_groups_by_path.get(main_path or "")
                if group_id is None:
                    continue
                nodes.append(
                    {
                        "id": tree_node_id,
                        "label": f"{simple_name}()",
                        "kind": "function",
                        "tree_node_id": tree_node_id,
                        "source_path": source_path,
                        "line": location.line,
                        "end_line": location.end_line,
                        "description": tree_node.description or tree_node.summary,
                        "subtitle": "",
                        "group": group_id,
                        "call_root_center": qualified_name == "main",
                    }
                )
                for path in {class_path, source_path}:
                    node_ids.setdefault((path, qualified_name), []).append(
                        tree_node_id
                    )
                global_node_ids.setdefault(qualified_name, []).append(
                    tree_node_id
                )
        return nodes, node_ids, global_node_ids, groups

    def _resolve_method_node(
        self,
        node_ids: dict[tuple[str, str], list[str]],
        global_node_ids: dict[str, list[str]],
        qualified_name: str,
        line: Any,
        *paths: Any,
    ) -> str | None:
        def matching_node(matches: list[str] | tuple[str, ...]) -> str | None:
            unique_matches = tuple(dict.fromkeys(matches))
            if len(unique_matches) == 1:
                return unique_matches[0]
            selected_line = self._line_number(line, 1)
            line_matches = []
            for node_id in unique_matches:
                location = self.resolve_selection(node_id)
                if (
                    location is not None
                    and location.line <= selected_line <= location.end_line
                ):
                    line_matches.append(node_id)
            if len(line_matches) == 1:
                return line_matches[0]
            owning_nodes = {
                node_id.rpartition(":member:")[0]
                for node_id in unique_matches
                if ":member:" in node_id
            }
            if len(owning_nodes) == 1:
                return unique_matches[0]
            return None

        for value in paths:
            path = Path(str(value or "")).as_posix()
            matches = node_ids.get((path, qualified_name), ())
            if selected := matching_node(matches):
                return selected
        matches = global_node_ids.get(qualified_name, ())
        return matching_node(matches)

    @staticmethod
    def _method_simple_name(qualified_name: str) -> str:
        return re.split(r"::|\.", qualified_name)[-1]

    @staticmethod
    def _qualified_method_name(class_name: str, method_name: str) -> str:
        separator = "::" if "::" in class_name else "."
        return f"{class_name}{separator}{method_name}"

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

    def _project_class_names(self) -> set[str]:
        names: set[str] = set()
        for file_model in self.model.get("files", ()):
            for class_symbol in file_model.get("classes", ()):
                qualified_name = str(class_symbol.get("qualified_name") or "")
                simple_name = str(class_symbol.get("name") or "")
                names.update(name for name in (qualified_name, simple_name) if name)
        return names

    def _project_method_definitions(
        self,
    ) -> dict[str, list[tuple[Path, dict[str, Any]]]]:
        definitions: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
        for file_model in self.model.get("files", ()):
            relative_path = Path(str(file_model.get("path", "")))
            for function_symbol in file_model.get("functions", ()):
                if (
                    function_symbol.get("kind") != "method"
                    or function_symbol.get("declaration") is True
                ):
                    continue
                qualified_name = str(function_symbol.get("qualified_name") or "")
                if qualified_name:
                    definitions.setdefault(qualified_name, []).append(
                        (relative_path, function_symbol)
                    )
        return definitions

    def _method_has_owning_class(self, symbol: dict[str, Any]) -> bool:
        if symbol.get("kind") != "method":
            return False
        owner = str(symbol.get("owner") or "")
        if not owner:
            qualified_name = str(symbol.get("qualified_name") or "")
            separator = "::" if "::" in qualified_name else "."
            owner = qualified_name.rpartition(separator)[0]
        return (
            owner in self._class_names
            or owner.rsplit("::", 1)[-1] in self._class_names
        )

    def _display_symbols(
        self, file_model: dict[str, Any], model_key: str
    ) -> tuple[tuple[int, dict[str, Any]], ...]:
        symbols = tuple(enumerate(file_model.get(model_key, ())))
        if model_key != "functions":
            return symbols
        return tuple(
            (index, symbol)
            for index, symbol in symbols
            if not self._method_has_owning_class(symbol)
        )

    def _method_definition(
        self, source_path: Path, symbol: dict[str, Any]
    ) -> tuple[Path, dict[str, Any]]:
        if symbol.get("declaration") is not True:
            return source_path, symbol
        qualified_name = str(symbol.get("qualified_name") or "")
        candidates = self._method_definitions.get(qualified_name, ())
        parameters = tuple(symbol.get("parameters", ()))
        matching = [
            candidate
            for candidate in candidates
            if tuple(candidate[1].get("parameters", ())) == parameters
        ]
        if len(matching) == 1:
            relative_path, definition = matching[0]
            return self._source_path(relative_path), definition
        if len(candidates) == 1:
            relative_path, definition = candidates[0]
            return self._source_path(relative_path), definition
        return source_path, symbol

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
        source_path = self._source_path(relative_path)

        line_count = max(1, self._line_number(file_model.get("line_count"), 1))
        self._locations[node_id] = SourceLocation(source_path, 1, line_count)
        groups = []
        for model_key, label, kind in self._SYMBOL_GROUPS:
            symbols = self._display_symbols(file_model, model_key)
            if symbols:
                groups.append(
                    self._build_symbol_group(
                        file_index,
                        source_path,
                        file_model,
                        model_key,
                        label,
                        kind,
                        symbols,
                    )
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
        symbols: tuple[tuple[int, dict[str, Any]], ...],
    ) -> ProjectTreeNode:
        group_id = f"file:{file_index}:{model_key}"
        symbol_nodes = tuple(
            self._build_symbol_node(
                group_id,
                source_path,
                file_model,
                symbol_index,
                symbol,
                kind,
            )
            for symbol_index, symbol in symbols
        )
        node = ProjectTreeNode(
            node_id=group_id,
            label=f"{label} ({len(symbol_nodes)})",
            kind="group",
            summary=f"{len(symbol_nodes)} {label.lower()}",
            children=symbol_nodes,
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
        description = ""
        if kind == "class":
            description = self._class_description(symbol, children)
        node = ProjectTreeNode(
            node_id=node_id,
            label=str(symbol.get("qualified_name") or symbol.get("name") or kind),
            kind=symbol_kind,
            line=line,
            end_line=end_line,
            summary="; ".join(details),
            description=description,
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
            member_source_path = source_path
            displayed_member = member
            if member_kind == "method":
                member_source_path, displayed_member = self._method_definition(
                    source_path, member
                )
            line = self._line_number(displayed_member.get("line"), 1)
            end_line = max(
                line, self._line_number(displayed_member.get("end_line"), line)
            )
            details = [member_kind.replace("_", " ")]
            if data_type := displayed_member.get("type"):
                details.append(f"type: {data_type}")
            if return_type := displayed_member.get("return_type"):
                details.append(f"returns: {return_type}")
            node = ProjectTreeNode(
                node_id=node_id,
                label=str(
                    displayed_member.get("name")
                    or displayed_member.get("qualified_name")
                    or "member"
                ),
                kind=member_kind,
                line=line,
                end_line=end_line,
                summary="; ".join(details),
                description=(
                    self._method_description(displayed_member, member)
                    if member_kind == "method"
                    else self._data_member_description(
                        displayed_member, class_name
                    )
                ),
            )
            self._locations[node_id] = SourceLocation(
                member_source_path, line, end_line
            )
            self._nodes[node_id] = node
            nodes.append(node)
        return tuple(nodes)

    def _data_member_description(
        self, symbol: dict[str, Any], class_name: str
    ) -> str:
        """Return a concise explanation for a class data member."""

        name = str(symbol.get("name") or "member")
        purpose = self._identifier_purpose(name)
        sentences = [
            f"{class_name}.{name} stores {purpose} state for {class_name}."
        ]
        if data_type := symbol.get("type"):
            sentences.append(
                f"Its declared or inferred type is {self._metadata_text(data_type)}."
            )
        else:
            sentences.append("The analyzer could not determine its type statically.")
        return " ".join(sentences)

    def _class_description(
        self,
        symbol: dict[str, Any],
        children: tuple[ProjectTreeNode, ...],
    ) -> str:
        """Return a deterministic explanation for a class tree node."""

        name = self._metadata_text(
            symbol.get("qualified_name") or symbol.get("name") or "This class"
        )
        class_category = self._metadata_text(
            str(symbol.get("class_category") or "class").replace("_", " ")
        )
        documentation = self._documentation_sentences(symbol)
        data_count = sum(child.kind == "data_member" for child in children)
        method_count = sum(child.kind == "method" for child in children)
        sentences = documentation
        if not documentation:
            purpose = self._identifier_purpose(name)
            sentences.append(
                f"Its name indicates that it represents {purpose} responsibilities."
            )
        if bases := symbol.get("bases"):
            base_names = ", ".join(self._metadata_text(base) for base in bases)
            sentences.append(
                f"{name} is a {class_category} that groups related state and behavior "
                f"while deriving from {base_names}."
            )
        else:
            sentences.append(
                f"{name} is a {class_category} that defines a project-specific "
                "object type."
            )
        sentences.append(
            f"It contains {data_count} {self._plural(data_count, 'data member')} "
            f"and {method_count} {self._plural(method_count, 'method')}."
        )
        return " ".join(sentences[:5])

    def _method_description(
        self,
        symbol: dict[str, Any],
        declaration_symbol: dict[str, Any],
    ) -> str:
        """Return a deterministic explanation for a method tree node."""

        documentation = self._documentation_sentences(symbol, declaration_symbol)
        name = self._metadata_text(
            symbol.get("qualified_name")
            or declaration_symbol.get("qualified_name")
            or symbol.get("name")
            or "This method"
        )
        owner = self._metadata_text(
            symbol.get("owner") or declaration_symbol.get("owner") or "its class"
        )
        sentences = documentation
        sentences.append(
            f"{name} is a method that implements an operation for {owner}."
        )
        if not documentation:
            purpose = self._identifier_purpose(name)
            sentences.append(
                f"Its name indicates that it handles {purpose} behavior."
            )
        parameters = symbol.get(
            "parameters", declaration_symbol.get("parameters", ())
        )
        if not isinstance(parameters, (list, tuple)):
            parameters = ()
        parameter_names = [
            self._metadata_text(parameter)
            for parameter in parameters
            if str(parameter).strip()
        ]
        if parameter_names:
            parameter_text = ", ".join(parameter_names)
            behavior = f"It accepts {parameter_text}"
        else:
            behavior = "It accepts no declared parameters"
        return_type = symbol.get("return_type") or declaration_symbol.get(
            "return_type"
        )
        if return_type:
            behavior += f" and returns {self._metadata_text(return_type)}"
        else:
            behavior += " and has no declared return type"
        sentences.append(f"{behavior}.")
        return " ".join(sentences[:5])

    @classmethod
    def _documentation_sentences(
        cls, *symbols: dict[str, Any]
    ) -> list[str]:
        """Extract at most three normalized sentences from symbol documentation."""

        for symbol in symbols:
            for field in (
                "docstring",
                "doc",
                "documentation",
                "leading_comment",
                "comment",
                "comments",
            ):
                value = symbol.get(field)
                if isinstance(value, (list, tuple)):
                    text = " ".join(str(item) for item in value if item)
                elif isinstance(value, str):
                    text = value
                else:
                    continue
                text = cls._clean_documentation(text)
                if not text:
                    continue
                sentences = [
                    sentence.strip()
                    for sentence in re.split(r"(?<=[.!?])\s+", text)
                    if sentence.strip()
                ][:3]
                return [
                    sentence
                    if sentence.endswith((".", "!", "?"))
                    else f"{sentence}."
                    for sentence in sentences
                ]
        return []

    @staticmethod
    def _clean_documentation(text: str) -> str:
        lines = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            line = re.sub(r"^(?:/\*+|//+|\#+|\*+)\s?", "", line)
            line = re.sub(r"\s*\*/$", "", line)
            if line:
                lines.append(line)
        cleaned = " ".join(" ".join(lines).split())
        cleaned = re.sub(
            r":(?:attr|class|func|meth|mod):`~?([^`]+)`", r"\1", cleaned
        )
        cleaned = re.sub(r"``([^`]+)``", r"\1", cleaned)
        return re.sub(r"`([^`]+)`", r"\1", cleaned)

    @staticmethod
    def _identifier_purpose(value: Any) -> str:
        """Turn a qualified snake/camel-case symbol into readable words."""

        simple_name = re.split(r"::|\.", str(value))[-1].strip("_")
        spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", simple_name)
        words = " ".join(spaced.replace("_", " ").split()).lower()
        return words or "this operation"

    @staticmethod
    def _metadata_text(value: Any) -> str:
        """Keep metadata inside one sentence even when it contains punctuation."""

        text = " ".join(str(value).split()).strip(" .!?")
        return re.sub(r"[.!?]+(?=\s|$)", ",", text) or "unspecified"

    def _source_path(self, relative_path: Path) -> Path:
        source_path = (self.project_path / relative_path).resolve()
        try:
            source_path.relative_to(self.project_path)
        except ValueError as exc:
            raise ValueError(
                f"source path escapes project root: {relative_path}"
            ) from exc
        return source_path

    @staticmethod
    def _plural(count: int, singular: str) -> str:
        if count == 1:
            return singular
        if singular.endswith(("s", "x", "z", "ch", "sh")):
            return f"{singular}es"
        if singular.endswith("y") and singular[-2:-1].lower() not in "aeiou":
            return f"{singular[:-1]}ies"
        return f"{singular}s"

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
