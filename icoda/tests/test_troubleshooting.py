"""Recovery runs before any error UI; failures hand over a usable CLI conversation."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from icoda_core import agent, documentation, git, persistence, prompt, python_analysis, recovery, steps
from icoda_core.process import ProcessResult


def window(app_module, tmp_path):
    git.run_git(["init", "-q"], tmp_path)
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(),
                         config_path=tmp_path / "config.json")
    app.project = tmp_path
    app.provider_field.set("codex", "gpt-6-astra")
    app.recovery.set_project(tmp_path)
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


def undocumented_project(app_module, tmp_path, monkeypatch):
    app, pending = window(app_module, tmp_path)
    source = tmp_path / "settings.py"
    source.write_text("class Settings:\n    def load(self):\n        return 42\n\n"
                      "def main():\n    return Settings().load()\n")
    app.opened = SimpleNamespace(root=tmp_path, model=python_analysis.parse_project(tmp_path))
    # Simulate the normal reload after edits with the real parser, without background GUI threads.
    def refresh(root):
        app.opened.model = python_analysis.parse_project(root)
    monkeypatch.setattr(app, "_source_changed", refresh)
    monkeypatch.setattr(agent, "binary_available", lambda *_args: True)
    return app, pending, source


def test_automatic_purpose_comments_are_verified_and_preserve_prompt_draft(app_module, tmp_path, monkeypatch):
    app, pending, source = undocumented_project(app_module, tmp_path, monkeypatch)
    app.recovery.input.insert("end", "Keep this unsent question")
    app.recovery.history.append(("Developer", "Explain the configuration"))
    requests = []
    def invoke(provider, model, request, cwd, **kwargs):
        requests.append(request)
        assert cwd == tmp_path and kwargs["writable"]
        assert "settings.Settings.load" in request and "settings.main" in request
        source.write_text('class Settings:\n    """Stores the application settings."""\n'
                          '    def load(self):\n        """Loads the configured limit."""\n        return 42\n\n'
                          'def main():\n    """Loads settings when the program starts."""\n'
                          '    return Settings().load()\n')
        return recovery.RecoveryResult(ProcessResult([], 0, "Documented the three entities.", ""))
    monkeypatch.setattr(recovery, "invoke", invoke)
    app.recovery.ensure_purpose_comments()
    assert len(pending) == 1
    complete(pending)
    app.recovery.ensure_purpose_comments()
    assert not documentation.missing_entities(app.opened.model)
    assert "verified for all 3 project entities" in app.recovery.summary.get()
    assert len(requests) == 1 and not pending
    assert app.recovery.input.get("1.0", "end").strip() == "Keep this unsent question"
    assert app.recovery.history == [("Developer", "Explain the configuration")]


@pytest.mark.parametrize("cancelled", [False, True])
def test_automatic_documentation_is_bounded_and_respects_cancellation(
        app_module, tmp_path, monkeypatch, cancelled):
    app, pending, _source = undocumented_project(app_module, tmp_path, monkeypatch)
    monkeypatch.setattr(recovery, "invoke", lambda *_args, **_kwargs: recovery.RecoveryResult(
        ProcessResult([], 0, "Done", "", cancelled=cancelled)))
    app.recovery.ensure_purpose_comments()
    complete(pending)
    app.recovery.ensure_purpose_comments()
    if not cancelled:
        assert len(pending) == 1  # The CLI's claim of completion does not override the source inventory.
        complete(pending)
        app.recovery.ensure_purpose_comments()
    assert not pending
    assert "3 entities still need purpose comments" in app.recovery.summary.get()


def test_documentation_waits_for_saved_source_valid_analysis_and_an_available_provider(
        app_module, tmp_path, monkeypatch):
    app, pending, source = undocumented_project(app_module, tmp_path, monkeypatch)
    app.source_editor.open_file(tmp_path, source.name)
    app.source_editor.text.insert("end", "# Unfinished edit\n")
    app.recovery.ensure_purpose_comments()
    assert not pending
    app.source_editor._install(app.source_editor.document)
    app.source_editor.clear()
    app._editor_refresh_pending = tmp_path
    app.recovery.ensure_purpose_comments()
    assert not pending  # Wait for the delayed post-edit reload before considering another LLM request.
    app._editor_refresh_pending = None
    app.opened.model.stale = True
    app.recovery.ensure_purpose_comments()
    assert not pending
    app.opened.model.stale = False
    monkeypatch.setattr(agent, "binary_available", lambda *_args: False)
    app.recovery.ensure_purpose_comments()
    assert not pending and not app.recovery.purpose_attempts
    assert "choose an available CLI" in app.status.get()


def test_prompt_works_before_any_failure_and_keeps_history(app_module, tmp_path, monkeypatch):
    app, pending = window(app_module, tmp_path)
    calls = []
    pings = []
    monkeypatch.setattr(app.root, "bell", lambda: pings.append(True))

    def invoke(provider, model, request, cwd, **kwargs):
        calls.append((request, cwd))
        return recovery.RecoveryResult(ProcessResult([], 0, "Start with main.cpp.", ""))

    monkeypatch.setattr(recovery, "invoke", invoke)
    for question in ("Explain this project", "Which function should I inspect?"):
        app.recovery.input.insert("end", question)
        assert app.recovery._send_shortcut() == "break"
        assert app.recovery.busy and len(pending) == 1
        before = len(pings)
        work, done = pending.pop()
        result = work()
        assert len(pings) == before  # The worker never calls Tk or plays sound.
        done(result)
        assert len(pings) == before + 1
    assert app.recovery.issue is None and not app.panel.busy
    assert all(cwd == tmp_path for _, cwd in calls)
    assert "Explain this project" in calls[1][0] and "Start with main.cpp." in calls[1][0]
    assert "Diagnosis:" not in calls[0][0] and "failure" not in calls[0][0]


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled", "exception"])
def test_prompt_applies_edits_and_refreshes_even_after_partial_failure(app_module, tmp_path, monkeypatch, outcome):
    app, pending = window(app_module, tmp_path)
    pings = []
    monkeypatch.setattr(app.root, "bell", lambda: pings.append(True))
    original = tmp_path / "app.cppm"
    original.write_text("int run();\n")
    app.source_editor.open_file(tmp_path, original.name)
    changed = []
    monkeypatch.setattr(app, "_source_changed", changed.append)

    def invoke(provider, model, request, cwd, **kwargs):
        assert kwargs["writable"] and ".icoda/specification.json" in request
        original.rename(cwd / "app.cpp")
        if outcome == "exception":
            raise OSError("interrupted after edit")
        return recovery.RecoveryResult(
            ProcessResult([], 0 if outcome == "success" else 1, "Renamed app.cppm to app.cpp.", "",
                          cancelled=outcome == "cancelled"), recovery.diagnose("connection reset"))

    monkeypatch.setattr(recovery, "invoke", invoke)
    app.recovery.input.insert("end", "Rename app.cppm according to the specification")
    app.recovery.send()
    complete(pending)
    assert pings == ([] if outcome == "cancelled" else [True])
    assert (tmp_path / "app.cpp").exists() and not original.exists()
    assert changed == [tmp_path] and not app.panel.busy
    assert app.source_editor.document is None  # The clean editor no longer points at a deleted file.
    assert app.recovery.history[0][1].startswith("Rename app.cppm")
    if outcome in {"failure", "exception"}:
        assert app.recovery.issue is not None
        app.recovery.details()
        assert app.recovery.issue.detail in app.recovery.transcript.get("1.0", "end")


def test_prompt_without_edits_does_not_refresh(app_module, tmp_path, monkeypatch):
    app, pending = window(app_module, tmp_path)
    monkeypatch.setattr(app, "_source_changed", lambda _: pytest.fail("No files changed"))
    monkeypatch.setattr(recovery, "invoke", lambda *args, **kwargs:
                        recovery.RecoveryResult(ProcessResult([], 0, "Explanation", "")))
    app.recovery.input.insert("end", "Explain the project")
    app.recovery.send()
    complete(pending)


def test_prompt_candidate_edits_invalidate_passed_checks_and_keep_unsaved_buffer(app_module, tmp_path, monkeypatch):
    app, pending = window(app_module, tmp_path)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    git.run_git(["init", "-q"], candidate)
    source = candidate / "app.cpp"
    source.write_text("int run();\n")
    proposal = steps.Proposal(1, prompt.StepRequest(prompt.ARCHITECTURE, 1), candidate,
                              build=steps.BuildResult(True, "passed"), test=steps.TestResult(True, "passed"))
    app.steps.proposal = proposal
    app.steps.confirmed_signature_proposal = proposal
    app.recovery.handle_failure("test failed", attempted=True, cwd=candidate)
    app.source_editor.open_file(candidate, source.name)
    app.source_editor.text.insert("end", "// unsaved buffer\n")

    def invoke(*args, **kwargs):
        source.write_text("int run() { return 1; }\n")
        return recovery.RecoveryResult(ProcessResult([], 0, "Changed return value.", ""))

    monkeypatch.setattr(recovery, "invoke", invoke)
    app.recovery.input.insert("end", "Fix the return value")
    app.recovery.send()
    complete(pending)
    assert not proposal.build.ok and not proposal.test.ok
    assert app.steps.confirmed_signature_proposal is None
    assert app.source_editor.dirty and "unsaved buffer" in app.source_editor.text.get("1.0", "end")
    assert not (tmp_path / "app.cpp").exists()


def test_refresh_failure_keeps_prompt_conversation(app_module, tmp_path):
    app, _pending = window(app_module, tmp_path)
    app.recovery.history.append(("Developer", "Rename the example file"))
    app.recovery.handle_failure("compiler error after rename", attempted=True)
    assert app.recovery.history[0] == ("Developer", "Rename the example file")


def test_stale_prompt_completion_cannot_refresh_a_different_project(app_module, tmp_path, monkeypatch):
    app, pending = window(app_module, tmp_path)
    monkeypatch.setattr(app.root, "bell", lambda: pytest.fail("Stale request must not ping"))
    monkeypatch.setattr(app, "_source_changed", lambda _: pytest.fail("Stale edit callback"))

    def invoke(*args, **kwargs):
        (tmp_path / "app.cpp").write_text("int run();\n")
        return recovery.RecoveryResult(ProcessResult([], 0, "Created app.cpp", ""))

    monkeypatch.setattr(recovery, "invoke", invoke)
    app.recovery.input.insert("end", "Create app.cpp")
    app.recovery.send()
    work, done = pending.pop()
    result = work()
    app.project = tmp_path / "other"
    app.recovery.set_project(app.project)
    done(result)
    assert not app.recovery.history and not app.recovery.busy


def test_prompt_controls_follow_input_project_provider_and_busy_state(app_module, tmp_path, monkeypatch):
    app, pending = window(app_module, tmp_path)
    states = {}
    for label, button in app.recovery.buttons.items():
        monkeypatch.setattr(button, "state", lambda flags, label=label:
                            states.update({label: "disabled" not in flags}))
    app.recovery._controls()
    assert states == {"Send": False, "Open CLI": True, "Cancel": False,
                      "Retry step": False, "Details": False}
    app.recovery.input.insert("end", "Explain main.cpp")
    app.recovery._input_changed()
    assert states["Send"]
    app.panel.set_busy(True, "building")
    assert not any(states.values())
    app.recovery.send()
    app.recovery.open_cli()
    assert not pending
    app.panel.set_busy(False)
    assert states["Send"] and states["Open CLI"]
    app.recovery.provider.set("unrecognized-agent")
    assert not states["Send"] and not states["Open CLI"]
    app.recovery.provider.set("codex")
    assert states["Send"]
    app.recovery.input.delete("1.0", "end")
    app.recovery._input_changed()
    assert not states["Send"]
    app.recovery.reset()
    assert not any(states.values())


def test_prompt_project_switch_clears_context_and_restores_provider(app_module, tmp_path):
    app, _pending = window(app_module, tmp_path)
    app.recovery.history.append(("Developer", "old project question"))
    app.recovery.input.insert("end", "old draft")
    app.recovery.set_project(tmp_path)
    assert app.recovery.history and app.recovery.input.get("1.0", "end").strip()
    other = tmp_path / "other"
    app.project = other
    app.provider_field.set("claude", "project-model")
    app.recovery.set_project(other)
    assert not app.recovery.history and not app.recovery.input.get("1.0", "end").strip()
    assert app.recovery.cwd == other and app.recovery.issue is None
    assert app.recovery.provider.selection().model == "project-model"
    app.provider_field.set("codex", "new-project-model")
    assert app.recovery.provider.selection().model == "new-project-model"


def test_open_cli_before_failure_includes_draft_and_conversation(app_module, tmp_path, monkeypatch):
    from icoda_gui import troubleshooting
    app, pending = window(app_module, tmp_path)
    monkeypatch.setattr(app.root, "bell", lambda: pytest.fail("Opening a terminal must not ping"))
    calls = []
    monkeypatch.setattr(troubleshooting.terminal, "open_cli", lambda command, cwd: calls.append((command, cwd)))
    app.recovery.history.extend([("Developer", "Explain main.cpp"), ("Assistant", "It starts the app.")])
    app.recovery.input.insert("end", "Add a command-line option")
    app.recovery.open_cli()
    assert app.recovery.busy
    complete(pending)
    command, cwd = calls[0]
    assert cwd == tmp_path and "on-request" in command
    assert all(text in command[-1] for text in ("Explain main.cpp", "It starts the app.",
                                               "Add a command-line option"))
    assert "Diagnosis:" not in command[-1] and "Do not modify files" not in command[-1]
    assert "Retry step" not in app.recovery.transcript.get("1.0", "end")
    assert app.recovery.input.get("1.0", "end").strip() == "Add a command-line option"


def test_repair_precedes_error_ui_and_success_is_silent(app_module, tmp_path, monkeypatch):
    app, pending = window(app_module, tmp_path)
    shown, repairs, recovered = [], [], []
    pings = []
    monkeypatch.setattr(app.root, "bell", lambda: pings.append(True))
    monkeypatch.setattr(app.panel, "show_failure", shown.append)
    app.recovery.handle_failure("build failed", repair=lambda: repairs.append(True) or "fixed",
                                repaired=recovered.append)
    assert not shown and app.recovery.busy and not repairs and not pings
    assert "Trying automatic recovery" in app.status.get()
    complete(pending)
    assert not shown and repairs == [True] and recovered == ["fixed"]
    assert pings == [True]
    assert not app.panel.busy and not app.recovery.busy


def test_failed_repair_shows_tab_once_and_keeps_retry(app_module, tmp_path, monkeypatch):
    app, pending = window(app_module, tmp_path)
    shown, retried = [], []
    monkeypatch.setattr(app.panel, "show_failure", shown.append)
    app.recovery.handle_failure("compiler error", repair=lambda: ValueError("no fix found"),
                                retry=lambda: retried.append(True))
    assert not shown
    complete(pending)
    assert len(shown) == 1 and "Prompt" in app.status.get()
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
    monkeypatch.setattr(app.root, "bell", lambda: pytest.fail("Cancelled recovery must not ping"))
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


@pytest.mark.parametrize("outcome", ["success", "cancelled", "workflow"])
def test_investigation_pings_only_for_completed_llm_calls(app_module, tmp_path, monkeypatch, outcome):
    app, pending = window(app_module, tmp_path)
    pings = []
    monkeypatch.setattr(app.root, "bell", lambda: pings.append(True))
    monkeypatch.setattr(recovery, "invoke", lambda *args, **kwargs: recovery.RecoveryResult(
        ProcessResult([], 0, "Check the include path.", "", cancelled=outcome == "cancelled")))
    error = "specification phase: save the specification" if outcome == "workflow" else "compiler error"
    app.recovery.handle_failure(error)
    assert not pings
    complete(pending)
    assert pings == ([True] if outcome == "success" else [])


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
    assert "Prompt" in app.status.get()


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
    assert "Prompt" in app.status.get()
    assert "save permission" in app.recovery.transcript.get("1.0", "end")
