"""Run ICODA's complete verification gate and retain machine-readable evidence."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "tests" / "sample_project"


@dataclass(frozen=True)
class CheckResult:
    name: str
    command: str
    returncode: int
    seconds: float
    log: str


def run_check(name: str, command: list[str], artifact: Path, env: dict[str, str] | None = None) -> CheckResult:
    """Run one check, tee combined output to its log, and never hide later checks after a failure."""
    log_path = artifact / f"{name}.log"
    shown = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
    started = time.monotonic()
    print(f"\n=== {name}: {shown} ===", flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"$ {shown}\n")
        try:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, errors="replace")
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
            returncode = process.wait()
        except OSError as exc:
            print(exc, flush=True)
            log.write(f"{exc}\n")
            returncode = 127
    seconds = time.monotonic() - started
    print(f"=== {name}: {'PASS' if returncode == 0 else 'FAIL'} ({seconds:.1f}s) ===", flush=True)
    return CheckResult(name, shown, returncode, round(seconds, 3), log_path.name)


def _output(command: list[str]) -> str:
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    return (result.stdout or result.stderr).strip()


def write_metadata(artifact: Path) -> None:
    metadata = {
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "python": sys.version,
        "executable": sys.executable,
        "git_head": _output(["git", "rev-parse", "HEAD"]),
        "git_status": _output(["git", "status", "--short"]),
        "cmake": _output(["cmake", "--version"]).splitlines()[:1],
        "clang": _output(["clang++", "--version"]).splitlines()[:2],
        "ninja": _output(["ninja", "--version"]),
    }
    (artifact / "environment.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def gui_command(artifact: Path) -> list[str]:
    command = [sys.executable, str(ROOT / "tests" / "gui_acceptance.py"),
               "--project", str(SAMPLE), "--output", str(artifact)]
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
        return ["xvfb-run", "-a", *command]
    return command


def commands(artifact: Path) -> list[tuple[str, list[str], dict[str, str] | None]]:
    python = sys.executable
    coverage = [python, "-m", "pytest", "-q", "--junitxml", str(artifact / "pytest.xml"), "--cov=.",
                "--cov-report=term-missing", f"--cov-report=xml:{artifact / 'coverage.xml'}",
                f"--cov-report=html:{artifact / 'coverage-html'}", "--cov-fail-under=85"]
    test_env = dict(os.environ, ICODA_TK_STUB="1", COVERAGE_FILE=str(artifact / ".coverage"))
    build_script = SAMPLE / ("build.cmd" if os.name == "nt" else "build.sh")
    build = ["cmd", "/c", str(build_script), "debug"] if os.name == "nt" \
        else ["bash", str(build_script), "debug"]
    return [
        ("diff-check", ["git", "diff", "--check"], None),
        ("ruff", [python, "-m", "ruff", "check", "."], None),
        ("mypy", [python, "-m", "mypy", "icoda.py", "icoda_core", "icoda_gui", "tests/verify.py",
                  "tests/gui_acceptance.py", "tests/real_provider_acceptance.py"], None),
        ("compileall", [python, "-m", "compileall", "-q", "icoda.py", "icoda_core", "icoda_gui", "tests"], None),
        ("providers", [python, "-m", "icoda_core.provider_check", "--output",
                       str(artifact / "provider-qualification.json"), "--cwd", str(ROOT)], None),
        ("pytest", coverage, test_env),
        ("sample-build", build, None),
        ("analysis", [python, "-m", "icoda_core.session", str(SAMPLE)], None),
        ("gui", gui_command(artifact), dict(os.environ, ICODA_TK_STUB="0")),
    ]


def artifact_directory(root: Path) -> Path:
    run_id = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    artifact = root / run_id
    artifact.mkdir(parents=True, exist_ok=False)
    root.mkdir(parents=True, exist_ok=True)
    (root / "LATEST").write_text(run_id + "\n", encoding="utf-8")
    return artifact


def write_summary(artifact: Path, results: list[CheckResult]) -> None:
    passed = all(result.returncode == 0 for result in results)
    summary: dict[str, Any] = {"passed": passed, "artifact": str(artifact),
                               "checks": [asdict(result) for result in results]}
    (artifact / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    lines = [f"{'PASS' if result.returncode == 0 else 'FAIL'} {result.name} ({result.seconds:.1f}s)"
             for result in results]
    (artifact / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-root", type=Path, default=ROOT / ".icoda-test-artifacts")
    args = parser.parse_args(argv)
    artifact = artifact_directory(args.artifacts_root.resolve())
    print(f"ICODA verification evidence: {artifact}")
    write_metadata(artifact)
    results = [run_check(name, command, artifact, env) for name, command, env in commands(artifact)]
    project_log = SAMPLE / ".icoda" / "icoda.log"
    if project_log.is_file():
        shutil.copy2(project_log, artifact / "icoda.log")
    write_summary(artifact, results)
    print(f"\n{'PASS' if all(r.returncode == 0 for r in results) else 'FAIL'}: {artifact / 'summary.txt'}")
    return 0 if all(result.returncode == 0 for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
