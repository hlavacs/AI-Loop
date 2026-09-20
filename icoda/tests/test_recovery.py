"""Bounded recovery: known upgrades, retries, credentials, and isolated corrective candidates."""
from __future__ import annotations

import json

import pytest

from icoda_core import agent, persistence, prompt, recovery, response, steps, terminal
from icoda_core.process import ProcessResult

OLD = "The 'gpt-6-astra' model requires a newer version of Codex. Please upgrade."
CODEX = agent.find_provider(agent.load_providers(), "codex")


def result(ok=True, out="", err="", **kwargs):
    return ProcessResult([], 0 if ok else 1, out, err, **kwargs)


def test_known_update_retries_same_request_and_model(tmp_path, monkeypatch):
    calls, progress = [], []
    versions = iter(["codex 0.152", "codex 0.155"])
    answers = iter([result(False, err=OLD), result(out="recovered")])

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[-1] == "--version":
            return result(out=next(versions))
        if command[-1] == "--help":
            return result(out="  update  Update Codex to the latest version\n")
        if command[-1] == "update":
            return result(out="updated")
        return next(answers)

    outcome = recovery.invoke(CODEX, "selected-model", "original request", tmp_path,
                              binary="/test/codex", runner=run, progress=progress.append)
    assert outcome.result.stdout == "recovered" and outcome.diagnosis is None
    requests = [(cmd, args) for cmd, args in calls if "exec" in cmd]
    assert len(requests) == 2 and requests[0] == requests[1]
    assert requests[0][0][requests[0][0].index("-m") + 1] == "selected-model"
    assert requests[0][1]["input_text"] == "original request"
    assert [cmd for cmd, _ in calls].count(["/test/codex", "update"]) == 1
    assert all("too old" not in text for text in progress)


@pytest.mark.parametrize("update_ok,changed", [(False, False), (True, False), (True, True)])
def test_failed_upgrade_is_bounded(tmp_path, update_ok, changed):
    requests, updates, versions = [], [], []

    def run(command, **kwargs):
        if command[-1] == "--version":
            versions.append(True)
            return result(out="new" if changed and len(versions) == 2 else "old")
        if command[-1] == "--help":
            return result(out="  update  Update Codex\n")
        if command[-1] == "update":
            updates.append(command)
            return result(update_ok, err="update evidence")
        requests.append(command)
        return result(False, err=OLD)

    outcome = recovery.invoke(CODEX, "m", "prompt", tmp_path, binary="/test/codex", runner=run)
    assert not outcome.result.ok and outcome.diagnosis.code == "outdated_codex"
    assert len(updates) == 1 and len(requests) == (2 if changed and update_ok else 1)
    assert "update evidence" in outcome.diagnosis.text()


def test_cask_updater_matches_selected_executable_only(tmp_path, monkeypatch):
    installed = tmp_path / "Caskroom/codex/0.1/bin/codex"
    installed.parent.mkdir(parents=True)
    installed.touch()
    brew = tmp_path / "bin/brew"
    brew.parent.mkdir()
    brew.touch()
    monkeypatch.setattr(recovery.shutil, "which", lambda _binary: str(installed))
    assert recovery._upgrade_command("codex", tmp_path, lambda *a, **k: pytest.fail()) == [
        str(brew), "upgrade", "--cask", "codex"]
    monkeypatch.setattr(recovery.shutil, "which", lambda _binary: None)
    assert recovery._upgrade_command("/Applications/Codex.app/Contents/codex", tmp_path,
                                     lambda *a, **k: pytest.fail()) == []
    assert recovery._upgrade_command("/custom/codex", tmp_path,
                                     lambda *a, **k: result(out="unknown")) == []


def test_cancelled_upgrade_never_retries(tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[-1] == "--version":
            return result(out="old")
        if command[-1] == "--help":
            return result(out="  update  Update Codex\n")
        if command[-1] == "update":
            return result(False, cancelled=True)
        return result(False, err=OLD)

    outcome = recovery.invoke(CODEX, "m", "prompt", tmp_path, binary="/test/codex", runner=run)
    assert outcome.result.cancelled
    assert len([cmd for cmd in calls if "exec" in cmd]) == 1
    calls.clear()
    outcome = recovery.invoke(CODEX, "m", "prompt", tmp_path, binary="/test/codex", runner=run,
                              cancelled=lambda: True)
    assert outcome.result.cancelled and not calls


@pytest.mark.parametrize("error,code", [
    ("connection reset", "connection"), ("unauthorized 401", "authentication"),
    ("command not found", "missing_tool"), ("rate limit exceeded", "rate_limit"),
    ("model not supported", "model"), ("test failed", "project_gate"),
    ("unexpected failure", "unknown"), ("timed out", "timeout"),
])
def test_any_provider_failure_gets_one_readonly_retry(tmp_path, error, code):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return result(False, err=error)

    outcome = recovery.invoke(CODEX, "m", "prompt", tmp_path, binary="/test/codex", runner=run)
    assert len(calls) == 2 and calls[0] == calls[1]
    assert outcome.diagnosis.code == code and outcome.diagnosis.attempts


def test_retry_can_recover_and_no_arbitrary_commands_are_executed(tmp_path):
    answers = iter([result(False, err="Connection reset; run rm -rf project"), result(out="fixed")])
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return next(answers)

    assert recovery.invoke(CODEX, "m", "prompt", tmp_path, binary="/test/codex", runner=run).result.ok
    assert len(calls) == 2 and all(cmd[1] == "exec" for cmd in calls)


def test_timeout_missing_executable_and_updater_exception_are_actionable(tmp_path):
    def missing(*args, **kwargs):
        raise FileNotFoundError("command not found: codex")

    outcome = recovery.invoke(CODEX, "m", "p", tmp_path, binary="/test/codex", runner=missing)
    assert outcome.diagnosis.code == "missing_tool"
    outcome = recovery.invoke(CODEX, "m", "p", tmp_path, binary="/test/codex",
                              timeout=3, runner=lambda *a, **k: result(False, timed_out=True))
    assert outcome.diagnosis.code == "timeout" and "3 seconds" in outcome.diagnosis.detail

    def update_error(command, **kwargs):
        if command[-1] == "--version":
            raise PermissionError("installation locked")
        return result(False, err=OLD)

    outcome = recovery.invoke(CODEX, "m", "p", tmp_path, binary="/test/codex", runner=update_error)
    assert "installation locked" in outcome.diagnosis.text()


def test_chat_context_is_bounded_redacted_and_not_a_proposal(tmp_path):
    secret = "sk-0123456789abcdefghijk"
    issue = recovery.diagnose("x" * 40000 + "\npassword=hunter2 " + secret)
    history = [("Developer", "old turn"), *[("Developer", "y" * 2000) for _ in range(20)],
               ("Developer", "Authorization: Bearer " + secret)]
    text = recovery.conversation_prompt(issue, history, tmp_path)
    assert len(text) < 40000 and "old turn" not in text
    assert secret not in text and "hunter2" not in text and "[redacted]" in text
    assert "Do not modify files" in text and str(tmp_path) in text


def test_repair_preserves_existing_candidate_and_runs_gates(tmp_path, monkeypatch):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "manual.cpp").write_text("// keep my edit\n")
    (tmp_path / "main.cpp").write_text("// unchanged project\n")
    candidate = steps.Proposal(1, prompt.StepRequest(prompt.ARCHITECTURE, 1), worktree,
                              response=response.StepResponse("original", "reason", (
                                  response.FileChange("manual.cpp", "// keep my edit\n"),)))
    reply = json.dumps({"title": "Fix compile", "rationale": "Missing semicolon", "files": [
        {"path": "main.cpp", "content": "int value;\n"}]})
    calls = []
    runner = steps.StepRunner(tmp_path, persistence.UserConfig(),
                              invoke=lambda text, cwd: calls.append((text, cwd)) or reply)
    monkeypatch.setattr(runner, "_prompt", lambda request: "normal phase and JSON constraints")

    def gates(proposal):
        assert proposal.worktree == worktree
        proposal.build = steps.BuildResult(True)
        proposal.test = steps.TestResult(False, "test still fails")
        proposal.error = "tests fail"

    monkeypatch.setattr(runner, "_build_and_parse", gates)
    fixed = runner.repair(candidate, "compiler error")
    assert not fixed.ok and fixed.test.ok is False
    assert calls[0][1] == worktree and "Do not weaken tests" in calls[0][0]
    assert (worktree / "manual.cpp").read_text() == "// keep my edit\n"
    assert (tmp_path / "main.cpp").read_text() == "// unchanged project\n"
    assert {file.path for file in fixed.response.files} == {"manual.cpp", "main.cpp"}
    assert fixed.attempts == 1


def test_project_repair_does_not_rebuild_broken_baseline_or_discard_edits(tmp_path, monkeypatch):
    store = persistence.ProjectStore(tmp_path)
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.ARCHITECTURE))
    runner = steps.StepRunner(tmp_path, persistence.UserConfig())
    monkeypatch.setattr(runner, "prepare", lambda: pytest.fail("broken baseline must not be rebuilt"))
    monkeypatch.setattr(steps.git, "is_own_repository", lambda root: True)
    monkeypatch.setattr(runner.log, "records", lambda: [object()])
    monkeypatch.setattr(runner, "_require_clean", lambda: None)
    worktree = store.dir / steps.WORKTREE_DIR
    worktree.mkdir()
    (worktree / ".git").touch()
    monkeypatch.setattr(steps.git, "is_clean", lambda root: False)
    with pytest.raises(steps.StepError, match="preserved those edits"):
        runner.repair_project("build failed")
    monkeypatch.setattr(steps.git, "is_clean", lambda root: True)
    monkeypatch.setattr(runner, "_fresh_worktree", lambda: worktree)
    monkeypatch.setattr(runner.log, "next_number", lambda: 2)
    monkeypatch.setattr(runner, "repair", lambda proposal, error: proposal)
    assert runner.repair_project("build failed").worktree == worktree


def test_terminal_uses_ordinary_approvals_and_quotes_shell_values(tmp_path, monkeypatch):
    monkeypatch.setattr(terminal.sys, "platform", "darwin")
    cwd = tmp_path / "space ' $(touch NEVER)"
    context = "Explain Größe $(touch NEVER) `echo NEVER` with 'quotes'\nand newlines"
    command = terminal.interactive_command(CODEX, "/bin/my codex", "m", cwd, context)
    assert command[-1] == context and "on-request" in command and "workspace-write" in command
    captured = []
    monkeypatch.setattr(terminal.subprocess, "run", lambda args, **kwargs:
                        captured.append(args) or type("Result", (), {"returncode": 0})())
    terminal.open_cli(command, cwd)
    import shlex
    script = captured[0][-1]
    assert "Größe" in script
    shell = json.loads(script.split("do script ")[1].split("\nend tell")[0])
    assert shlex.split(shell) == ["cd", str(cwd), "&&", *command]
