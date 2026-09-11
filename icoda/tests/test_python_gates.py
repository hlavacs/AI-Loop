"""Real build and test gates for a generated Python project."""

from __future__ import annotations

import sys
from pathlib import Path

from icoda_core import generator, persistence, specification, steps


def test_python_skeleton_real_build_and_targeted_test_gates(tmp_path: Path) -> None:
    profile = {
        **specification.default_code_profile("Python"),
        "test_runner": f"{sys.executable} -m pytest -q",
    }
    root = tmp_path / "demo-service"
    generator.write_skeleton(root, "Demo Service", profile)
    spec = specification.default_specification("Demo Service", "Python")
    spec["code_profile"] = profile
    specification.save(persistence.ProjectStore(root).specification_path, spec)
    selected = ("tests/test_demo_service.py",)

    build = steps.build_project(root)
    assert build.ok is True, build.output
    commands = steps.gate_commands(root, persistence.DEFAULT_TEST_COMMAND, selected)
    assert commands.test == (sys.executable, "-m", "pytest", "-q", "tests/test_demo_service.py")
    passing = steps.test_project(root, commands.test)
    assert passing.ok is True, passing.output

    test_file = root / selected[0]
    broken_test = test_file.read_text(encoding="utf-8").replace("== 0", "== 1") + "\n# force pyc refresh\n"
    test_file.write_text(broken_test, encoding="utf-8")
    failing = steps.test_project(root, commands.test)
    assert failing.ok is False
    assert "FAILED tests/test_demo_service.py::test_demo_service_runs" in failing.output
    assert "assert 0 == 1" in failing.output
