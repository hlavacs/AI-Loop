"""Controlled provider executable and service injection shared by Python and Node tests.

No real registry entry, network request, credential read, or CLI agent is used.
"""

from __future__ import annotations

import json
import shlex
import sys
import time
from dataclasses import replace
from pathlib import Path


def install() -> None:
    from icoda_core import agent

    provider = agent.Provider("fixture", "Controlled fixture", sys.executable,
        ("{binary}", str(Path(__file__).resolve()), "{model}"), "stdin",
        tuple(agent.Model(name, name) for name in ("ok", "fail", "slow", "purpose", "gate", "signature", "build")), True, True, "")
    agent.load_providers = lambda: [provider]
    agent.editing_provider = lambda item: item if item.id == "fixture" else _refuse()


def _refuse():
    raise AssertionError("Only the controlled fixture provider may run")


def prepare(root: Path, phase: str = "architecture") -> None:
    from icoda_core import analysis, persistence, specification, steps

    root.mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text('def run():\n    """An entry stub."""\n    pass\n', encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_main.py").write_text('def test_fixture():\n    assert 1 + 1 == 2\n', encoding="utf-8")
    (root / ".gitignore").write_text('__pycache__/\n.pytest_cache/\n', encoding="utf-8")
    store = persistence.ProjectStore(root)
    store.ensure()
    spec = specification.default_specification("Workflow fixture", analysis.PYTHON_LANGUAGE)
    spec["code_profile"]["test_runner"] = shlex.join([sys.executable, "-m", "pytest", "-q"])
    specification.save(store.specification_path, spec)
    store.save_state(replace(store.load_state(), phase=persistence.ProjectPhase.ARCHITECTURE if phase == "implementation" else persistence.ProjectPhase(phase)))
    steps.StepRunner(root, persistence.UserConfig()).prepare()  # Baseline fixture only; never invokes an agent.
    if phase == "implementation":
        model = store.load_model()
        target = next(entity.usr for entity in model.entities.values() if entity.name == "run")
        store.save_state(replace(store.load_state(), phase=persistence.ProjectPhase.IMPLEMENTATION,
                                 implementation_queue=(target,)))
    store.save_ui({"provider": {"provider": "fixture", "model": "ok"}})


def reply(mode: str, prompt: str) -> None:
    if mode.startswith("edit"):
        Path("src/main.py").write_text('def run():\n    """An edited entry."""\n    return 42\n', encoding="utf-8")
    if mode in ("slow", "edit-slow"):
        marker = Path(".icoda/cache/provider-started")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(__import__("os").getpid()), encoding="ascii")
        time.sleep(60)
    if mode in ("fail", "edit-fail"):
        print("Controlled provider failure", file=sys.stderr)
        raise SystemExit(3)
    if "Description to rewrite:" in prompt:
        if mode != "empty":
            print("A simpler description of the same step.")
    elif "Conversation:" in prompt:
        print("Controlled conversation reply.\n" + prompt.split("Conversation:\n", 1)[1])
    elif mode == "purpose":
        for path in Path(".").rglob("test_main.py"):
            path.write_text('def test_fixture():\n    """Check the fixture arithmetic."""\n    assert 1 + 1 == 2\n', encoding="utf-8")
        print("Documented the fixture test.")
    elif "# Approach round" in prompt:
        print(json.dumps({"plan": "Implement the selected stub and test its result.",
                          "entities": ["run"], "files": ["src/main.py"]}))
    elif "# Approved approach" in prompt and mode not in ("gate", "signature", "build"):
        print(json.dumps({"title": "Implement entry", "rationale": "Return the agreed value.",
            "files": [{"path": "src/main.py", "content": 'def run():\n    """Return the fixture value."""\n    return 1\n'}]}))
    elif mode == "build":
        print(json.dumps({"title": "Fail the build gate", "rationale": "Controlled invalid Python.",
            "files": [{"path": "src/main.py", "content": "def run(:\n"}]}))
    elif mode == "gate":
        print(json.dumps({"title": "Fail the test gate", "rationale": "Controlled failing check.",
            "files": [{"path": "tests/test_main.py", "content": 'def test_fixture():\n    """Fail the controlled gate."""\n    assert False\n'}]}))
    elif mode == "signature":
        print(json.dumps({"title": "Change entry API", "rationale": "Review the new argument.",
            "files": [{"path": "src/main.py", "content": 'def run(value=1):\n    """An entry stub."""\n    pass\n'}]}))
    else:
        print(json.dumps({"title": "Add helper stub", "rationale": "Add a documented helper for the next round.",
            "entities": [{"name": "helper", "kind": "function", "file": "src/helper.py", "signature": "def helper()"}],
            "files": [{"path": "src/helper.py", "content": 'def helper():\n    """A helper stub."""\n    pass\n'}]}))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    reply(sys.argv[1], sys.stdin.buffer.read().decode("utf-8"))
