"""Recovery runs before any error UI; failures hand over a usable CLI conversation."""
from __future__ import annotations

from types import SimpleNamespace

from icoda_core import persistence, prompt, recovery, steps
from icoda_core.process import ProcessResult


def window(app_module, tmp_path):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(),
                         config_path=tmp_path / "config.json")
    app.project = tmp_path
    app.provider_field.set("codex", "gpt-6-astra")
    pending = []
    app.run_async = lambda work, done: pending.append((work, done))
    return app, pending


def complete(pending):
    work, done = pending.pop(0)
    try:
        result = work()
    except Exception as exc:  # noqa: BLE001  (simulate UiTasks result delivery)
        result = exc
    done(result)


def test_repair_precedes_error_ui_and_success_is_silent(app_module, tmp_path, monkeypatch):
    app, pending = window(app_module, tmp_path)
    shown, repairs, recovered = [], [], []
    monkeypatch.setattr(app.panel, "show_failure", shown.append)
    app.recovery.handle_failure("build failed", repair=lambda: repairs.append(True) or "fixed",
                                repaired=recovered.append)
    assert not shown and app.recovery.busy and not repairs
    assert "Trying automatic recovery" in app.status.get()
    complete(pending)
    assert not shown and repairs == [True] and recovered == ["fixed"]
    assert not app.panel.busy and not app.recovery.busy


def test_failed_repair_shows_tab_once_and_keeps_retry(app_module, tmp_path, monkeypatch):
    app, pending = window(app_module, tmp_path)
    shown, retried = [], []
    monkeypatch.setattr(app.panel, "show_failure", shown.append)
    app.recovery.handle_failure("compiler error", repair=lambda: ValueError("no fix found"),
                                retry=lambda: retried.append(True))
    assert not shown
    complete(pending)
    assert len(shown) == 1 and "Troubleshooting" in app.status.get()
    assert "no fix found" in app.recovery.transcript.get("1.0", "end")
    assert not pending
    app.recovery.provider.set("claude", "claude-opus-4-6")
    app.recovery.retry_step()
    assert retried == [True] and app.provider_field.selection().binary == "claude"


def test_provider_failure_already_attempted_does_not_repeat_update(app_module, tmp_path, monkeypatch):
    app, pending = window(app_module, tmp_path)
    issue = recovery.Diagnosis("outdated_codex", "CLI needs update", "Use CLI", "evidence", ("update failed",))
    app.recovery.handle_failure(steps.ProviderError(issue))
    assert not pending and "update failed" in app.recovery.transcript.get("1.0", "end")
    app.recovery.details()
    assert "evidence" in app.recovery.transcript.get("1.0", "end")


def test_conversation_keeps_history_and_candidate_directory(app_module, tmp_path, monkeypatch):
    app, pending = window(app_module, tmp_path)
    worktree = tmp_path / "candidate"
    worktree.mkdir()
    app.recovery.handle_failure("tests fail", attempted=True, cwd=worktree)
    calls = []

    def invoke(provider, model, request, cwd, **kwargs):
        calls.append((provider.id, request, cwd))
        return recovery.RecoveryResult(ProcessResult([], 0, "Inspect the missing include.", ""))

    monkeypatch.setattr(recovery, "invoke", invoke)
    for question in ("What failed?", "Which include?"):
        app.recovery.input.insert("end", question)
        app.recovery.send()
        assert app.recovery.busy
        complete(pending)
    assert len(calls) == 2 and all(call[2] == worktree for call in calls)
    assert "What failed?" in calls[1][1] and "Inspect the missing include." in calls[1][1]
    assert "Which include?" in calls[1][1]
    assert not app.panel.busy


def test_cancellation_and_project_reset_discard_stale_callbacks(app_module, tmp_path, monkeypatch):
    app, pending = window(app_module, tmp_path)
    stopped = []
    monkeypatch.setattr(steps, "cancel_running", lambda: 0)
    from icoda_gui import troubleshooting
    monkeypatch.setattr(troubleshooting.process, "cancel_running", lambda: stopped.append(True))
    app.recovery.handle_failure("failed", repair=lambda: "repair", repaired=lambda value: None)
    app.recovery.reset()
    assert stopped and not app.recovery.busy and not app.panel.busy
    complete(pending)
    assert app.recovery.issue is None and app.recovery.transcript.get("1.0", "end").strip() == ""
    app.recovery.handle_failure("failed", repair=lambda: "repair", repaired=lambda value: None)
    app.recovery.cancel()
    complete(pending)
    assert "cancelled" in app.recovery.transcript.get("1.0", "end")


def test_failed_proposal_is_not_rendered_before_repair(app_module, tmp_path, monkeypatch):
    app, pending = window(app_module, tmp_path)
    candidate = steps.Proposal(1, prompt.StepRequest(prompt.ARCHITECTURE, 1), tmp_path,
                              build=steps.BuildResult(False, "compiler evidence"), error="does not build")
    runner = SimpleNamespace(repair=lambda proposal, error: proposal)
    monkeypatch.setattr(app.steps, "_ensure_runner", lambda: runner)
    shown = []
    monkeypatch.setattr(app.panel, "show", shown.append)
    app.steps._show_proposal(candidate)
    assert not shown and app.steps.proposal is candidate
    complete(pending)
    assert shown and all(proposal is candidate for proposal in shown)
    assert "compiler evidence" in app.recovery.transcript.get("1.0", "end")
    assert "Proposal(" not in app.recovery.transcript.get("1.0", "end")
    assert not pending


def test_recovery_callback_failure_does_not_recurse(app_module, tmp_path):
    app, pending = window(app_module, tmp_path)

    def broken_view(result):
        app.recovery.handle_failure("drawing failed again", repair=lambda: "repaired", repaired=broken_view)

    app.recovery.handle_failure("drawing failed", repair=lambda: "repaired", repaired=broken_view)
    complete(pending)
    assert not pending and not app.recovery.busy
    assert "Troubleshooting" in app.status.get()


def test_terminal_launch_is_off_ui_thread_and_uses_candidate(app_module, tmp_path, monkeypatch):
    from icoda_gui import troubleshooting
    app, pending = window(app_module, tmp_path)
    candidate = tmp_path / "candidate"
    app.recovery.handle_failure("compiler error", attempted=True, cwd=candidate)
    calls = []
    monkeypatch.setattr(troubleshooting.terminal, "open_cli", lambda command, cwd: calls.append((command, cwd)))
    app.recovery.open_cli()
    assert not calls and app.recovery.busy
    complete(pending)
    assert calls[0][1] == candidate and "on-request" in calls[0][0]
    assert not app.recovery.busy and "Opened the interactive CLI" in app.recovery.transcript.get("1.0", "end")


def test_additional_errors_wait_for_recovery_and_are_not_dropped(app_module, tmp_path):
    app, pending = window(app_module, tmp_path)
    app.recovery.handle_failure("first error", repair=lambda: ValueError("cannot fix first"))
    app.recovery.handle_failure("second error", repair=lambda: ValueError("cannot fix second"))
    app.recovery.handle_failure("second error", repair=lambda: ValueError("duplicate"))
    assert len(app.recovery.pending) == 1
    complete(pending)
    app.recovery._drain_pending()
    assert app.recovery.busy
    complete(pending)
    assert "cannot fix first" in app.recovery.transcript.get("1.0", "end")
    assert "cannot fix second" in app.recovery.transcript.get("1.0", "end")
    assert not app.recovery.pending


def test_retry_updates_runner_captured_by_failed_action(app_module, tmp_path):
    app, _pending = window(app_module, tmp_path)
    runner = app.steps._ensure_runner()
    retried = []
    app.recovery.handle_failure("provider failed", attempted=True,
                                retry=lambda: retried.append((runner.binary, runner.model_id)))
    app.recovery.provider.set("claude", "chosen-model")
    app.recovery.retry_step()
    assert retried == [("claude", "chosen-model")]


def test_ui_callback_exception_keeps_completion_queue_alive(app_module, tmp_path):
    import pytest
    app, _pending = window(app_module, tmp_path)
    scheduled = []
    app.root.after = lambda *args: scheduled.append(args)

    def fail():
        raise ValueError("callback failed")

    app.tasks.run_on_ui(fail)
    with pytest.raises(ValueError, match="callback failed"):
        app.tasks._poll()
    assert scheduled[-1] == (app.tasks.interval, app.tasks._poll)
    app.recovery._investigate = lambda *args: "The save permission needs correction."
    app._recover_analysis = lambda: pytest.fail("reanalysis cannot prove that an unknown save succeeded")
    app._callback_error(ValueError, ValueError("save failed"), None)
    complete(_pending)
    assert "Troubleshooting" in app.status.get()
    assert "save permission" in app.recovery.transcript.get("1.0", "end")
