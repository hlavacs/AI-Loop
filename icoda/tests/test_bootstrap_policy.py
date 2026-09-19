from __future__ import annotations

import re
from pathlib import Path

import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ICODA_DIR = Path(__file__).resolve().parents[1]


def test_runtime_dependencies_are_bounded_and_constrained() -> None:
    project = tomllib.loads((ICODA_DIR / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    constraint_lines = (ICODA_DIR / "constraints.txt").read_text(encoding="utf-8").splitlines()
    pin_lines = [line for line in constraint_lines if line and not line.startswith("#")]
    assert all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*==[^=\s]+", line) for line in pin_lines)
    pins = {
        canonicalize_name(match.group("name"))
        for line in pin_lines
        if (match := re.fullmatch(r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==[^=\s]+", line))
    }

    for dependency in project["dependencies"]:
        requirement = Requirement(dependency)
        operators = {specifier.operator for specifier in requirement.specifier}
        assert operators & {">", ">="}, f"{dependency} has no lower bound"
        assert operators & {"<", "<="}, f"{dependency} has no upper bound"
        assert canonicalize_name(requirement.name) in pins


def test_launchers_never_elevate_or_upgrade_pip() -> None:
    for name in ("icoda.bash", "icoda.cmd", "icoda_python.bash"):
        text = (ICODA_DIR / name).read_text(encoding="utf-8")
        assert "--upgrade pip" not in text
        assert not any(re.match(r"\s*sudo(?:\s|$)", line) for line in text.splitlines())
        pip_commands = (line.lstrip() for line in text.splitlines() if " -m pip " in line)
        assert all(line.startswith("echo ") for line in pip_commands)
