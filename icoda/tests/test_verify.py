"""Hermetic policy checks for the complete verification gate."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_verify() -> ModuleType:
    path = Path(__file__).with_name("verify.py")
    spec = importlib.util.spec_from_file_location("icoda_test_verify", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verify = _load_verify()


def _load_handbook_builder() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "tools" / "build_handbook_pdf.py"
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("icoda_build_handbook_pdf", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_real_provider_acceptance() -> ModuleType:
    path = Path(__file__).with_name("real_provider_acceptance.py")
    spec = importlib.util.spec_from_file_location("icoda_test_real_provider_acceptance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_commands_include_real_provider_acceptance_next_to_provider_qualification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify.steps, "build_environment", lambda _root: None)

    stages = verify.commands(tmp_path)
    names = [name for name, _command, _env in stages]
    provider_index = names.index("providers")
    name, command, env = stages[provider_index + 1]

    assert name == verify.REAL_PROVIDER_STAGE
    assert command[1].endswith("tests/real_provider_acceptance.py")
    assert command[-2:] == ["--output", str(tmp_path / "real-provider")]
    assert env is None


def test_missing_real_provider_credential_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(verify, "real_provider_credential", lambda: None)
    monkeypatch.setattr(verify, "run_check", _unexpected_stage_run)
    stage = [(verify.REAL_PROVIDER_STAGE, [sys.executable, "real_provider_acceptance.py"], None)]

    results = verify.run_commands(stage, tmp_path, allow_missing_real_provider=False)

    assert verify.exit_status(results) == 1
    assert results[0].outcome == "FAIL"
    output = capsys.readouterr().out
    assert "missing Codex credential: run 'codex login'" in output
    assert "printenv OPENAI_API_KEY | codex login --with-api-key" in output
    assert "printenv CODEX_ACCESS_TOKEN | codex login --with-access-token" in output
    assert "rerun with --allow-missing-real-provider" in output


def test_missing_real_provider_credential_waiver_is_recorded_as_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(verify, "real_provider_credential", lambda: None)
    monkeypatch.setattr(verify, "run_check", _unexpected_stage_run)
    monkeypatch.setattr(verify, "_output", lambda _command: "not probed")
    stage = [(verify.REAL_PROVIDER_STAGE, [sys.executable, "real_provider_acceptance.py"], None)]

    results = verify.run_commands(stage, tmp_path, allow_missing_real_provider=True)
    verify.write_metadata(tmp_path)
    verify.write_summary(tmp_path, results)

    assert verify.exit_status(results) == 0
    assert results[0].outcome == "SKIP"
    assert "SKIP real-provider" in capsys.readouterr().out
    assert (tmp_path / "summary.txt").read_text(encoding="utf-8").endswith("SKIP real-provider (0.0s)\n")
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["waived"] == ["real-provider"]
    assert summary["checks"][0]["outcome"] == "SKIP"


def test_metadata_and_summary_record_host_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify.platform, "platform", lambda: "TestOS-1.0")
    monkeypatch.setattr(verify.platform, "machine", lambda: "test-machine")
    monkeypatch.setattr(verify.platform, "python_version", lambda: "3.12.9")
    monkeypatch.setattr(verify, "_output", lambda _command: "not probed")

    verify.write_metadata(tmp_path)
    verify.write_summary(tmp_path, [])

    expected = {"platform": "TestOS-1.0", "machine": "test-machine", "python_version": "3.12.9"}
    metadata = json.loads((tmp_path / "environment.json").read_text(encoding="utf-8"))
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert {name: metadata[name] for name in expected} == expected
    assert {name: summary[name] for name in expected} == expected
    assert (tmp_path / "summary.txt").read_text(encoding="utf-8").startswith(
        "Platform: TestOS-1.0\nMachine: test-machine\nPython: 3.12.9\n\n"
    )


def test_release_matrix_names_every_branched_platform_with_explicit_status() -> None:
    root = Path(__file__).resolve().parent.parent
    python_sources = [root / "icoda.py", root / "tests" / "verify.py",
                      *sorted((root / "icoda_core").glob("*.py")),
                      *sorted((root / "icoda_gui").glob("*.py"))]
    branch_pattern = re.compile(
        r'(?:sys\.platform|os\.name|\bplatform)\s*(?:==|!=)\s*"([^"]+)"'
        r'|(?:sys\.platform|\bplatform)\.startswith\("([^"]+)"\)'
    )
    branch_values = {
        value
        for source in python_sources
        for match in branch_pattern.finditer(source.read_text(encoding="utf-8"))
        for value in match.groups()
        if value is not None
    }
    platform_names = {"linux": "Linux", "nt": "Windows", "win32": "Windows", "darwin": "macOS"}
    assert branch_values == set(platform_names)
    assert 'uname -s)" = "Darwin"' in (root / "icoda.bash").read_text(encoding="utf-8")
    assert 'uname -s)" = "Darwin"' in (root / "icoda_python.bash").read_text(encoding="utf-8")
    assert "launcher for Windows" in (root / "icoda.cmd").read_text(encoding="utf-8")

    matrix = (root / "docs" / "RELEASE_MATRIX.md").read_text(encoding="utf-8")
    statuses = dict(re.findall(
        r"^\| (Linux|Windows|macOS) \| \*\*(QUALIFIED|IMPLEMENTED BUT UNQUALIFIED)\*\* \|",
        matrix, re.MULTILINE,
    ))
    assert set(statuses) == set(platform_names.values())
    assert statuses == {"Linux": "QUALIFIED", "Windows": "IMPLEMENTED BUT UNQUALIFIED",
                        "macOS": "IMPLEMENTED BUT UNQUALIFIED"}


def test_evidence_documents_match_current_module_inventory() -> None:
    root = Path(__file__).resolve().parent.parent
    core_modules = sorted((root / "icoda_core").glob("*.py"))
    ordinary_test_modules = sorted((root / "tests").glob("test_*.py"))
    acceptance_modules = sorted((root / "tests").glob("*_acceptance.py"))
    test_modules = [*ordinary_test_modules, *acceptance_modules]

    claims = (
        f"{len(core_modules)} top-level Python modules",
        f"{len(test_modules)} Python test modules",
        f"{len(ordinary_test_modules)} top-level `test_*.py` modules plus the {len(acceptance_modules)}",
    )
    for relative in ("GAP_ANALYSIS.md", "RELEASE_MATRIX.md"):
        document = " ".join((root / "docs" / relative).read_text(encoding="utf-8").split())
        assert all(claim in document for claim in claims), relative


def test_real_provider_stage_flags_are_accepted_by_acceptance_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify.steps, "build_environment", lambda _root: None)
    _name, command, _env = next(stage for stage in verify.commands(tmp_path) if stage[0] == "real-provider")
    acceptance = _load_real_provider_acceptance()
    monkeypatch.setattr(acceptance, "execute", lambda _args, _evidence, _report: None)

    arguments = command[2:]
    assert [argument for argument in arguments if argument.startswith("--")] == ["--output"]
    assert acceptance.main(arguments) == 0


def test_handbook_preserves_production_safety_vocabulary_and_worked_examples() -> None:
    root = Path(__file__).resolve().parent.parent
    handbook = (root / "HANDBOOK.md").read_text(encoding="utf-8")

    assert all(term in handbook for term in (
        "recorded test reachability", "50-line", "MAX_RESPONSE_BYTES", "constraints.txt",
    ))
    assert all(heading in handbook for heading in (
        "### Worked example A: new Python project from first launch to approval",
        "### Worked example B: split a Python function refused by the 50-line gate",
        "### Worked example C: CMake/C++ with `CMAKE_PRESET`",
    ))


def test_tutorial_preserves_current_new_user_safety_vocabulary() -> None:
    root = Path(__file__).resolve().parent.parent
    tutorial = (root / "docs" / "TUTORIAL.md").read_text(encoding="utf-8")

    assert all(term in tutorial for term in (
        "recorded test reachability", "50-line", "MAX_RESPONSE_BYTES", "constraints.txt",
    ))


def test_readme_documents_the_offline_handbook_builder_invocation() -> None:
    root = Path(__file__).resolve().parent.parent
    builder = _load_handbook_builder()
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert builder.BUILD_INVOCATION == ".icoda-venv/bin/python tools/build_handbook_pdf.py"
    assert f"```bash\n{builder.BUILD_INVOCATION}\n```" in readme
    assert callable(builder.main)


def _unexpected_stage_run(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("the real-provider program must not run without credentials")
