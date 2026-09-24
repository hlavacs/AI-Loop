"""Stable spring layouts for rectangular diagram nodes, without numerical dependencies."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping


def arrange(sizes: Mapping[str, tuple[float, float]], edges: Iterable[tuple[str, str, float]],
            gap: float = 40.0) -> tuple[dict[str, tuple[float, float]], float, float]:
    """Attract related nodes, repel all nodes, and resolve rectangle collisions exactly."""
    if not sizes:
        return {}, 1.0, 1.0
    weights: dict[tuple[str, str], float] = defaultdict(float)
    for source, target, weight in sorted(edges):
        if source in sizes and target in sizes and source != target:
            weights[tuple(sorted((source, target)))] += max(weight, 0.0)
    degree: dict[str, float] = defaultdict(float)
    for (source, target), weight in weights.items():
        degree[source] += weight
        degree[target] += weight
    keys = sorted(sizes, key=lambda key: (-degree[key], key))
    average_width = sum(size[0] for size in sizes.values()) / len(keys) + gap
    average_height = sum(size[1] for size in sizes.values()) / len(keys) + gap
    # A sunflower seed avoids row/column alignment and puts highly connected nodes near the centre.
    positions = {key: [math.cos(i * 2.399963229728653) * math.sqrt(i) * average_width,
                       math.sin(i * 2.399963229728653) * math.sqrt(i) * average_height]
                 for i, key in enumerate(keys)}
    scale = math.sqrt(average_width * average_height)
    for iteration in range(200):
        forces = {key: [-x * .1, -y * .1] for key, (x, y) in positions.items()}
        for index, a in enumerate(keys):
            for b in keys[index + 1:]:
                dx, dy = positions[b][0] - positions[a][0], positions[b][1] - positions[a][1]
                distance = max(math.hypot(dx, dy), .001)
                ux, uy = dx / distance, dy / distance
                if dx == dy == 0:
                    ux, uy = 1.0, 0.0
                half_width = (sizes[a][0] + sizes[b][0]) / 2 + gap
                half_height = (sizes[a][1] + sizes[b][1]) / 2 + gap
                clearance = min(half_width / max(abs(ux), 1e-9), half_height / max(abs(uy), 1e-9))
                repulsion = scale * scale * .015 / distance
                repulsion += max(clearance - distance, 0) * .7
                weight = weights.get(tuple(sorted((a, b))), 0)
                attraction = .18 * math.log1p(weight) * (distance - clearance - gap * .5)
                force = repulsion - attraction
                forces[a][0] -= ux * force
                forces[a][1] -= uy * force
                forces[b][0] += ux * force
                forces[b][1] += uy * force
        temperature = scale * .12 * (1 - iteration / 200) ** 2 + .05
        for key, (fx, fy) in forces.items():
            factor = min(1.0, temperature / max(math.hypot(fx, fy), .001))
            positions[key][0] += fx * factor
            positions[key][1] += fy * factor
    _separate(positions, sizes, keys, gap)
    left = min(positions[key][0] - sizes[key][0] / 2 for key in keys) - gap
    top = min(positions[key][1] - sizes[key][1] / 2 for key in keys) - gap
    result = {key: (positions[key][0] - left, positions[key][1] - top) for key in sorted(keys)}
    width = max(result[key][0] + sizes[key][0] / 2 for key in keys) + gap
    height = max(result[key][1] + sizes[key][1] / 2 for key in keys) + gap
    return result, width, height


def _separate(positions: dict[str, list[float]], sizes: Mapping[str, tuple[float, float]],
              keys: list[str], gap: float) -> None:
    """Project overlaps apart, then place any remaining collision at the nearest free boundary."""
    for _ in range(100):
        moved = False
        for index, a in enumerate(keys):
            for b in keys[index + 1:]:
                dx, dy = positions[b][0] - positions[a][0], positions[b][1] - positions[a][1]
                overlap_x = (sizes[a][0] + sizes[b][0]) / 2 + gap - abs(dx)
                overlap_y = (sizes[a][1] + sizes[b][1]) / 2 + gap - abs(dy)
                if overlap_x <= 0 or overlap_y <= 0:
                    continue
                axis = 0 if overlap_x < overlap_y else 1
                delta = (min(overlap_x, overlap_y) + .01) / 2
                delta *= 1 if (dx if axis == 0 else dy) >= 0 else -1
                positions[a][axis] -= delta
                positions[b][axis] += delta
                moved = True
        if not moved:
            return
    placed: list[str] = []
    for key in keys:
        x, y = positions[key]

        def free(point: tuple[float, float], key: str = key) -> bool:
            return all(abs(point[0] - positions[other][0]) >= (sizes[key][0] + sizes[other][0]) / 2 + gap
                       or abs(point[1] - positions[other][1]) >= (sizes[key][1] + sizes[other][1]) / 2 + gap
                       for other in placed)

        if not free((x, y)):
            candidates = []
            for other in placed:
                ox, oy = positions[other]
                w, h = (sizes[key][0] + sizes[other][0]) / 2 + gap + .01, \
                    (sizes[key][1] + sizes[other][1]) / 2 + gap + .01
                candidates.extend(((ox - w, y), (ox + w, y), (x, oy - h), (x, oy + h)))
            positions[key] = list(min((point for point in candidates if free(point)),
                                      key=lambda point: ((point[0] - x) ** 2 + (point[1] - y) ** 2, point)))
        placed.append(key)
