"""Deterministic, bounded diagram groups based on relationships and source themes."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

import networkx as nx

MAX_GROUP_SIZE = 40
Topics = Mapping[str, tuple[str, ...]]


def topics(file: str, qualified_name: str = "") -> tuple[str, ...]:
    """Structural and identifier hints; no guessed descriptions of the code."""
    path = PurePosixPath(file)
    hints = set()
    if path.parent.as_posix() not in {".", "src", "include", "lib"}:
        hints.add("path:" + path.parent.as_posix())
    scope = qualified_name.replace("::", ".").rsplit(".", 1)
    if len(scope) == 2:
        hints.add("scope:" + scope[0])
    for word in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", path.stem + " " + qualified_name):
        if len(word) >= 3:
            hints.add("name:" + word.lower())
    return tuple(sorted(hints))


def theme(members: Sequence[str], hints: Topics, population: Sequence[str]) -> str:
    """Name a group using hints that are common inside it and distinctive outside it."""
    total = Counter(topic for node in population for topic in hints.get(node, ()))
    local = Counter(topic for node in members for topic in hints.get(node, ()))
    ranked = sorted(local, key=lambda topic: (
        -local[topic] * math.log(len(population) / total[topic]),
        -topic.startswith("scope:"), topic))
    if not ranked:
        return PurePosixPath(min(members)).stem
    best = ranked[0]
    return best.split(":", 1)[1]


def split(graph: nx.Graph, hints: Topics, max_size: int = MAX_GROUP_SIZE) -> list[list[str]]:
    """Compare community resolutions and theme partitions; recursively bound every group."""
    if max_size < 1:
        raise ValueError("max_size must be positive")
    # Canonical insertion order makes fixed-seed algorithms insensitive to input order.
    ordered = nx.Graph()
    ordered.add_nodes_from(sorted(graph))
    ordered.add_weighted_edges_from(sorted(
        (min(a, b), max(a, b), data.get("weight", 1.0))
        for a, b, data in graph.edges(data=True) if a != b))

    def divide(nodes: list[str]) -> list[list[str]]:
        if len(nodes) <= max_size:
            return [nodes]
        subgraph = ordered.subgraph(nodes)
        candidates = []
        components = list(nx.connected_components(subgraph))
        if 1 < len(components) < len(nodes):
            candidates.append(components)
        if subgraph.number_of_edges():
            detect = getattr(nx.community, "louvain_communities", None)
            if detect is not None:
                for resolution in (1.0, 2.0, 4.0):
                    candidates.append(detect(subgraph, weight="weight", resolution=resolution, seed=0))
        counts = Counter(topic for node in nodes for topic in hints.get(node, ()))
        thematic: dict[str, set[str]] = defaultdict(set)
        for node in nodes:
            choices = [topic for topic in hints.get(node, ()) if 2 <= counts[topic] < len(nodes) * .8]
            label = min(choices, key=lambda topic: (-min(counts[topic], max_size), topic)) if choices else ""
            thematic[label].add(node)
        candidates.append(list(thematic.values()))
        valid = [sorted(sorted(group) for group in candidate)
                 for candidate in candidates if 1 < len(candidate) < len(nodes)]
        if valid:
            groups = min(valid, key=lambda groups: (-_quality(subgraph, groups, hints, counts), groups))
            # Reject fragmentation into singletons when it reveals no useful structure.
            if _quality(subgraph, groups, hints, counts) > 0:
                return [part for group in groups for part in divide(group)]
        return _balanced_neighbours(subgraph, hints, max_size)

    return sorted(divide(sorted(ordered))) if ordered else []


def _quality(graph: nx.Graph, groups: list[list[str]], hints: Topics, counts: Counter[str]) -> float:
    modularity = nx.community.modularity(graph, groups, weight="weight") if graph.number_of_edges() else 0.0
    coherence = 0.0
    for group in groups:
        shared = Counter(topic for node in group for topic in hints.get(node, ()))
        coherence += max((count * (1 - counts[topic] / len(graph)) for topic, count in shared.items()
                          if count > 1), default=0)
    tiny = sum(len(group) for group in groups if len(group) < 3) / len(graph)
    return modularity + .5 * coherence / len(graph) - .25 * tiny


def _balanced_neighbours(graph: nx.Graph, hints: Topics, max_size: int) -> list[list[str]]:
    """Last resort: balanced groups grown along strong relationships, with stable theme ties."""
    remaining = set(graph)
    size = math.ceil(len(graph) / math.ceil(len(graph) / max_size))
    groups = []
    while remaining:
        first = min(remaining, key=lambda node: (hints.get(node, ()), node))
        group = [first]
        remaining.remove(first)
        strength: dict[str, float] = defaultdict(float)
        shared = set(hints.get(first, ()))
        while remaining and len(group) < size:
            for neighbour, data in graph[group[-1]].items():
                strength[neighbour] += data.get("weight", 1.0)
            best = min(remaining, key=lambda node: (
                -strength[node], -len(shared.intersection(hints.get(node, ()))), node))
            group.append(best)
            remaining.remove(best)
            shared.update(hints.get(best, ()))
        groups.append(sorted(group))
    return groups
