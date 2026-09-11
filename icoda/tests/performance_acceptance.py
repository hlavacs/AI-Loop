"""Measure large-Python-project analysis and pure overview-stage scaling."""

from __future__ import annotations

import argparse
import gc
import json
import sys
import tempfile
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from icoda_core import (
    class_view,
    clusters,
    coverage_index,
    expansion,
    graph_filter,
    mind_map,
    python_analysis,
    views,
)

PROJECT_SIZES = (("small", 50), ("large", 300))
METHODS_PER_MODULE = 8
ENTITIES_PER_MODULE = METHODS_PER_MODULE + 4
MATERIAL_GROWTH_RATIO = 1.5
INTERACTIVE_SECONDS = 10.0


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def _module_name(index: int) -> str:
    return f"package_{index // 30:02d}.module_{index:03d}"


def _module_source(index: int) -> str:
    imports = "from pathlib import Path\n"
    if index:
        imports += f"from {_module_name(index - 1)} import bridge_{index - 1:03d}\n"
    methods = []
    for method in range(METHODS_PER_MODULE):
        expression = f"self.step_{method + 1}(value + 1)" if method + 1 < METHODS_PER_MODULE else "value + 1"
        methods.append(
            f"    def step_{method}(self, value: int) -> int:\n"
            f"        return {expression}\n"
        )
    previous = f" + bridge_{index - 1:03d}(value)" if index else ""
    return (
        f"{imports}\n"
        f"class Service{index:03d}:\n"
        f"{''.join(methods)}\n"
        f"def helper_{index:03d}(value: int) -> int:\n"
        f"    return value + {index}\n\n"
        f"def bridge_{index:03d}(value: int) -> int:\n"
        f"    service = Service{index:03d}()\n"
        f"    return service.step_0(helper_{index:03d}(value)){previous}\n\n"
        f"def audit_{index:03d}(value: int) -> int:\n"
        f"    Path(str(value))\n"
        f"    return bridge_{index:03d}(value)\n"
    )


def _write_project(root: Path, module_count: int) -> None:
    """Write a deterministic, source-only project below a disposable root."""
    for index in range(module_count):
        path = root / f"package_{index // 30:02d}" / f"module_{index:03d}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_module_source(index), encoding="utf-8")


def _measure(operation: Callable[[], Any]) -> tuple[Any, dict[str, float]]:
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    try:
        result = operation()
        seconds = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return result, {"seconds": seconds, "peak_mb": peak / (1024 * 1024)}


def _measure_size(project: Path, label: str, expected_modules: int) -> dict[str, Any]:
    model, parse_metrics = _measure(lambda: python_analysis.parse_project(project))
    module_count = len(model.files)
    entity_count = len(model.entities)
    edge_count = len(model.edges)
    if module_count != expected_modules:
        raise RuntimeError(f"{label} generated {module_count} modules, expected {expected_modules}")
    expected_entities = expected_modules * ENTITIES_PER_MODULE
    if entity_count != expected_entities:
        raise RuntimeError(f"{label} produced {entity_count} entities, expected {expected_entities}")
    if expected_modules == PROJECT_SIZES[-1][1] and entity_count < 3_000:
        raise RuntimeError(f"large model has only {entity_count} entities")

    clustering = clusters.cluster_files(model)
    cluster_by_file = {
        file: cluster.id
        for cluster in clustering.clusters
        for file in cluster.files
    }
    call_root = f"python:{_module_name(expected_modules - 1)}:audit_{expected_modules - 1:03d}"
    class_graph = class_view.build_class_graph(model)
    tree = mind_map.build_mind_map(model, ())
    mind_state = mind_map.MindMapViewState(tuple(node.id for node in tree.nodes()))
    graph = graph_filter.project_graph(model, cluster_by_file)
    decisions = graph_filter.derive(model, graph, {})
    expanded = frozenset(graph.nodes)

    stages: dict[str, dict[str, float]] = {"parse_project": parse_metrics}
    operations: tuple[tuple[str, Callable[[], Any]], ...] = (
        ("layout_file_view", lambda: views.layout_file_view(model, clustering)),
        ("layout_call_view", lambda: views.layout_call_view(model, call_root)),
        ("layout_class_view", lambda: views.layout_class_view(class_graph)),
        ("layout_mind_map", lambda: views.layout_mind_map(tree, mind_state)),
        ("coverage_index.build_index", lambda: coverage_index.build_index(model, ())),
        ("expansion.derive", lambda: expansion.derive(model, graph, decisions, {}, expanded)),
    )
    retained: list[Any] = [model]
    for name, operation in operations:
        result, metrics = _measure(operation)
        retained.append(result)
        stages[name] = metrics
    for metrics in stages.values():
        metrics["microseconds_per_entity"] = metrics["seconds"] * 1_000_000 / entity_count
    return {
        "label": label,
        "module_count": module_count,
        "entity_count": entity_count,
        "edge_count": edge_count,
        "stages": stages,
    }


def _interpret(results: list[dict[str, Any]]) -> dict[str, Any]:
    small, large = results
    scaling = {}
    for stage, large_metrics in large["stages"].items():
        small_cost = small["stages"][stage]["microseconds_per_entity"]
        large_cost = large_metrics["microseconds_per_entity"]
        ratio = large_cost / small_cost if small_cost else 0.0
        scaling[stage] = {
            "small_microseconds_per_entity": small_cost,
            "large_microseconds_per_entity": large_cost,
            "ratio": ratio,
            "material_growth": ratio >= MATERIAL_GROWTH_RATIO,
        }
    large_seconds = sum(stage["seconds"] for stage in large["stages"].values())
    return {
        "material_growth_ratio": MATERIAL_GROWTH_RATIO,
        "interactive_seconds": INTERACTIVE_SECONDS,
        "large_total_seconds": large_seconds,
        "interactive_acceptable": large_seconds <= INTERACTIVE_SECONDS,
        "scaling": scaling,
    }


def _summary(results: list[dict[str, Any]], interpretation: dict[str, Any]) -> str:
    lines = [
        "ICODA large-project performance acceptance",
        "",
        f"Material-growth signal: >= {MATERIAL_GROWTH_RATIO:.2f}x large/small microseconds per entity",
        f"Interactive-overview interpretation: summed measured stages <= {INTERACTIVE_SECONDS:.1f} seconds",
        "",
    ]
    for result in results:
        lines.extend((
            f"Size: {result['label']}",
            f"Modules: {result['module_count']}",
            f"Entities: {result['entity_count']}",
            f"Edges: {result['edge_count']}",
            "Stage                            Seconds    Peak MB    Microseconds/entity",
            "-------------------------------  ---------  ---------  -------------------",
        ))
        for stage, metrics in result["stages"].items():
            lines.append(
                f"{stage:<31}  {metrics['seconds']:9.6f}  {metrics['peak_mb']:9.3f}  "
                f"{metrics['microseconds_per_entity']:19.3f}"
            )
        lines.append("")
    lines.append("Scaling assessment:")
    for stage, scaling in interpretation["scaling"].items():
        outcome = "MATERIAL GROWTH" if scaling["material_growth"] else "no material growth"
        lines.append(
            f"- {stage}: {scaling['small_microseconds_per_entity']:.3f} -> "
            f"{scaling['large_microseconds_per_entity']:.3f} us/entity "
            f"({scaling['ratio']:.3f}x); {outcome}."
        )
    acceptable = "acceptable" if interpretation["interactive_acceptable"] else "not acceptable"
    lines.extend((
        "",
        (
            f"Large summed stage latency: {interpretation['large_total_seconds']:.6f} seconds; "
            f"{acceptable} for an interactive overview by the stated <= {INTERACTIVE_SECONDS:.1f}s interpretation."
        ),
    ))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="icoda-performance-") as temporary:
        temporary_root = Path(temporary)
        for label, module_count in PROJECT_SIZES:
            project = temporary_root / label
            _write_project(project, module_count)
            results.append(_measure_size(project, label, module_count))
    interpretation = _interpret(results)
    payload = {
        "project": {
            "sizes": [{"label": label, "module_count": size} for label, size in PROJECT_SIZES],
            "methods_per_module": METHODS_PER_MODULE,
            "deterministic": True,
        },
        "results": results,
        "interpretation": interpretation,
    }
    performance_path = args.output / "performance.json"
    summary_path = args.output / "summary.txt"
    performance_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = _summary(results, interpretation)
    summary_path.write_text(summary, encoding="utf-8")
    print(summary, end="")
    print(f"Wrote {performance_path}")
    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
