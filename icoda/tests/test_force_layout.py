"""Relationship-based layouts are deterministic, bounded, and label-safe."""

import math
from itertools import combinations

import pytest

from icoda_core import force_layout


@pytest.mark.parametrize("shape", ["star", "clique", "disconnected"])
def test_variable_rectangles_never_overlap_and_all_fit(shape):
    sizes = {f"n{i}": (120 + (i % 3) * 80, 1800 if i == 0 else 40 + (i % 7) * 25) for i in range(35)}
    edges = [(a, b, 1) for a, b in combinations(sizes, 2)
             if shape == "clique" or (shape == "star" and a == "n0")]
    saved = dict(sizes)
    positions, width, height = force_layout.arrange(sizes, edges, gap=35)
    assert sizes == saved and set(positions) == set(sizes)
    for key, (x, y) in positions.items():
        w, h = sizes[key]
        assert math.isfinite(x) and math.isfinite(y)
        assert 0 <= x - w / 2 < x + w / 2 <= width
        assert 0 <= y - h / 2 < y + h / 2 <= height
    for a, b in combinations(sizes, 2):
        assert abs(positions[a][0] - positions[b][0]) >= (sizes[a][0] + sizes[b][0]) / 2 + 35 - 1e-6 \
            or abs(positions[a][1] - positions[b][1]) >= (sizes[a][1] + sizes[b][1]) / 2 + 35 - 1e-6
    assert (positions, width, height) == force_layout.arrange(dict(reversed(list(sizes.items()))), reversed(edges), 35)
    # No fixed rows/columns: at least one axis retains mostly distinct organic positions.
    assert max(len({round(point[axis], 3) for point in positions.values()}) for axis in (0, 1)) > 25


def test_connected_entities_are_closer_than_unconnected_entities():
    sizes = {str(i): (100, 40) for i in range(24)}
    edges = [(str(i), str(j), 4) for i in range(24) for j in range(i + 1, 24) if i // 6 == j // 6]
    positions, _, _ = force_layout.arrange(sizes, edges)
    linked, separate = [], []
    for a, b in combinations(sizes, 2):
        target = linked if int(a) // 6 == int(b) // 6 else separate
        target.append(math.dist(positions[a], positions[b]))
    assert sum(linked) / len(linked) < .7 * sum(separate) / len(separate)


def test_empty_single_self_loops_and_unknown_endpoints():
    assert force_layout.arrange({}, []) == ({}, 1, 1)
    plain = force_layout.arrange({"a": (200, 100)}, [])
    assert plain == force_layout.arrange({"a": (200, 100)}, [("a", "a", 100), ("a", "missing", 4)])
    assert plain == ({"a": (140, 90)}, 280, 180)
