"""The step protocol end to end: a skeleton project, a scripted provider, real builds and parses in a worktree."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from icoda_core import generator, persistence, prompt, specification, steplog, steps, toolchain

pytestmark = pytest.mark.skipif(shutil.which("cmake") is None or shutil.which("ninja") is None
                                or not toolchain.candidates(), reason="needs cmake, ninja and libclang")

APP_WITH_ANSWER = """module;
#include <string>
export module app;

/// @brief The application.
export namespace app {

/// @brief The answer. @satisfies UC-1
int answer() {
    return 42;
}

/// @brief Runs the application.
int run() {
    return answer() - 42;
}

}  // namespace app
"""
APP_BROKEN = "export module app;\nexport namespace app {\nint run() { return broken; }\n}\n"


def reply(title: str, path: str, content: str) -> str:
    return json.dumps({"title": title, "rationale": "Because the specification asks for it.",
                       "files": [{"path": path, "content": content}]})


class ScriptedProvider:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def __call__(self, prompt_text: str, cwd: Path) -> str:
        self.prompts.append(prompt_text)
        return self.replies.pop(0)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    if sys.platform == "darwin":
        monkeypatch.delenv("CC", raising=False)
        monkeypatch.delenv("CXX", raising=False)
    else:
        monkeypatch.setenv("CC", os.environ.get("CC", "clang"))
        monkeypatch.setenv("CXX", os.environ.get("CXX", "clang++"))
    if sys.platform != "darwin" and shutil.which(os.environ["CXX"]) is None:
        pytest.skip("no clang++")
    root = tmp_path / "demo"
    generator.write_skeleton(root, "demo")
    spec = specification.default_specification("demo")
    spec["use_cases"] = [{"id": "UC-1", "title": "Know the answer"}]
    specification.save(persistence.ProjectStore(root).specification_path, spec)
    return root


def git_log(root: Path) -> list[str]:
    return subprocess.run(["git", "log", "--format=%s"], cwd=root, capture_output=True, text=True,
                          check=True).stdout.splitlines()


def test_step_zero_then_propose_approve_reject_undo(project: Path) -> None:
    provider = ScriptedProvider([
        "Here you are:\n```json\n" + reply("Add the answer", "src/app/app.cppm", APP_WITH_ANSWER) + "\n```",
        "I cannot do that.",
        reply("Break it", "src/app/app.cppm", APP_BROKEN),
        reply("Add the answer again", "src/app/app.cppm", APP_WITH_ANSWER.replace("42;", "41;\n")),
    ])
    messages: list[str] = []
    runner = steps.StepRunner(project, persistence.UserConfig(), "fake", "fake-bin", "fake-model",
                              invoke=provider, progress=messages.append)
    zero = runner.prepare()
    assert zero is not None and zero.number == 0 and zero.commit and git_log(project) == ["icoda step 0: skeleton"]
    names = {e.qualified_name: e for e in runner.current_model().entities.values()}
    assert names["app::run"].status == "stub" and "main" in names
    assert runner.prepare() is None

    proposal = runner.propose(prompt.StepRequest(prompt.ARCHITECTURE, 0, "add the answer"))
    assert proposal.ok and proposal.number == 1 and proposal.attempts == 1, proposal.error + proposal.build.output
    assert "# Build files" in proposal.prompt_text and "add_executable" in proposal.prompt_text
    assert proposal.delta is not None and [e.qualified_name for e in proposal.delta.added] == ["app::answer"]
    assert proposal.delta.files == ("src/app/app.cppm",)
    assert (project / "src/app/app.cppm").read_text() != APP_WITH_ANSWER  # only the worktree has it so far

    approved = runner.approve(proposal)
    assert approved.commit and (project / "src/app/app.cppm").read_text() == APP_WITH_ANSWER
    assert git_log(project)[0] == "icoda(architecture) step 1: Add the answer"
    assert (approved.provider, approved.binary, approved.model) == ("fake", "fake-bin", "fake-model")
    answer = next(e for e in runner.current_model().entities.values() if e.qualified_name == "app::answer")
    assert answer.status == "stub" and answer.usr in approved.entities_added

    second = runner.propose(prompt.StepRequest(prompt.ARCHITECTURE, 0))
    assert second.ok and second.number == 2 and second.attempts == 3, second.error
    assert "was not usable" in provider.prompts[2] and "did not build" in provider.prompts[3]
    rejected = runner.reject(second, "not now")
    assert rejected.decision == "rejected" and runner.log.rejections(2) == ("not now",)

    undone = runner.undo()
    assert undone.undoes == 1 and "answer" not in (project / "src/app/app.cppm").read_text()
    assert git_log(project)[0] == "icoda undo step 1: Add the answer"
    records = steplog.StepLog(persistence.ProjectStore(project).steps_path).records()
    assert [r.decision for r in records] == ["approved", "rejected", "undone"]
    assert runner.log.next_number() == 1 and runner.prepare() is None

    (project / "README.md").write_text("edited by hand\n")
    with pytest.raises(steps.DirtyTree):
        runner.prepare()
    manual = runner.commit_manual_edits()
    assert manual is not None and manual.decision == "manual" and manual.files == ["README.md"]
    assert runner.prepare() is None and any("building" in m for m in messages)


def test_delta_and_log_helpers(tmp_path: Path) -> None:
    from icoda_core.model import DerivedModel, Entity, Kind

    before, after = DerivedModel("/p"), DerivedModel("/p")
    before.add_entity(Entity("u:a", Kind.FUNCTION, "a", "a", "x.cpp", 1, signature="void a()"))
    before.add_entity(Entity("u:gone", Kind.FUNCTION, "gone", "gone", "x.cpp", 5))
    after.add_entity(Entity("u:a", Kind.FUNCTION, "a", "a", "x.cpp", 1, signature="int a()"))
    after.add_entity(Entity("u:b", Kind.CLASS, "B", "B", "y.cppm", 2))
    delta = steps.compute_delta(before, after, ["x.cpp", "y.cppm"])
    assert [e.usr for e in delta.added] == ["u:b"] and [e.usr for e in delta.changed] == ["u:a"]
    assert [e.usr for e in delta.removed] == ["u:gone"]
    assert delta.summary().splitlines()[0] == "1 entities added, 1 changed, 1 removed; files: x.cpp, y.cppm"

    log = steplog.StepLog(tmp_path / "steps.jsonl")
    log.append(steplog.StepRecord(0, "architecture", "approved", entities_added=["u:a"]))
    log.append(steplog.StepRecord(1, "implementation", "approved", entities_changed=["u:a"], tests_passed=True))
    log.append(steplog.StepRecord(2, "architecture", "rejected", reason="no"))
    assert log.next_number() == 2 and log.rejections(2) == ("no",)
    steplog.apply_statuses(after, log)
    assert after.entities["u:a"].status == "tested"
    log.append(steplog.StepRecord(1, "implementation", "undone", undoes=1))
    steplog.apply_statuses(after, log)
    assert after.entities["u:a"].status == "stub" and [r.number for r in log.approved()] == [0]
