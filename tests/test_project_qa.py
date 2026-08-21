from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_loop.project_qa import (
    AvailableLlm,
    ProjectQuestionError,
    ask_project_question,
    build_project_question_prompt,
    discover_available_llms,
)


def test_discover_available_llms_filters_missing_unsupported_and_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ai_loop.project_qa.shutil.which",
        lambda binary: f"/usr/bin/{binary}" if binary in {"codex", "claude"} else None,
    )

    llms = discover_available_llms(
        (
            ("codex", "codex", "gpt-5"),
            ("codex", "codex", "gpt-5"),
            ("claude", "claude", "opus"),
            ("gemini", "gemini", "pro"),
            ("unknown", "unknown", "model"),
        )
    )

    assert llms == (
        AvailableLlm("codex", "codex", "gpt-5"),
        AvailableLlm("claude", "claude", "opus"),
    )
    assert [llm.label for llm in llms] == [
        "Codex — gpt-5",
        "Claude — opus",
    ]


def test_project_question_prompt_is_grounded_read_only_and_bounded() -> None:
    history = tuple((f"question {index}", "x" * 4_000) for index in range(12))

    prompt = build_project_question_prompt(" How does the controller work? ", history)

    assert "Inspect the repository's source code" in prompt
    assert "Do not modify files" in prompt
    assert "question 0" not in prompt
    assert "Current question:\nHow does the controller work?" in prompt
    assert len(prompt) < 21_000
    with pytest.raises(ValueError, match="must not be empty"):
        build_project_question_prompt("   ")


def test_ask_project_question_uses_claude_read_only_tools_and_unwraps_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr("ai_loop.project_qa.shutil.which", lambda _binary: "/bin/claude")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout='{"result":"The controller plans tasks."}',
            stderr="",
            timed_out=False,
        )

    monkeypatch.setattr("ai_loop.project_qa.run_bounded_process", fake_run)

    answer = ask_project_question(
        tmp_path,
        AvailableLlm("claude", "claude", "opus"),
        "What does the controller do?",
    )

    command = captured["command"]
    assert answer == "The controller plans tasks."
    assert command[:6] == [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--permission-mode",
        "plan",
    ]
    assert command[command.index("--allowedTools") + 1] == "Read,Glob,Grep"
    assert command[command.index("--model") + 1] == "opus"
    assert captured["kwargs"]["cwd"] == tmp_path.resolve()


def test_ask_project_question_uses_codex_read_only_and_last_message_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr("ai_loop.project_qa.shutil.which", lambda _binary: "/bin/codex")
    monkeypatch.setattr("ai_loop.project_qa.systemd_sandbox_enabled", lambda: False)

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        result_path = Path(command[command.index("--output-last-message") + 1])
        result_path.write_text("The worker implements one task at a time.", encoding="utf-8")
        return SimpleNamespace(
            returncode=0,
            stdout="provider progress output",
            stderr="",
            timed_out=False,
        )

    monkeypatch.setattr("ai_loop.project_qa.run_bounded_process", fake_run)

    answer = ask_project_question(
        tmp_path,
        AvailableLlm("codex", "codex", "gpt-5"),
        "What does the worker do?",
    )

    command = captured["command"]
    assert answer == "The worker implements one task at a time."
    assert command[:5] == [
        "codex",
        "exec",
        "--cd",
        str(tmp_path.resolve()),
        "--sandbox",
    ]
    assert command[5] == "read-only"
    assert command[-1] == "-"
    assert "Current question:\nWhat does the worker do?" in captured["kwargs"][
        "input_text"
    ]


def test_ask_project_question_reports_provider_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ai_loop.project_qa.shutil.which", lambda _binary: "/bin/gemini")
    monkeypatch.setattr(
        "ai_loop.project_qa.run_bounded_process",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=7,
            stdout="",
            stderr="authentication required",
            timed_out=False,
        ),
    )

    with pytest.raises(ProjectQuestionError, match="rc=7.*authentication required"):
        ask_project_question(
            tmp_path,
            AvailableLlm("gemini", "gemini", "pro"),
            "How are jobs stored?",
        )


def test_gui_question_submission_runs_in_background_and_keeps_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ai_loop_gui

    class FakeVar:
        def __init__(self, value: str) -> None:
            self.value = value

        def get(self) -> str:
            return self.value

        def set(self, value: str) -> None:
            self.value = value

    class FakeWidget:
        def __init__(self, content: str = "") -> None:
            self.content = content
            self.state = "normal"

        def get(self, *_args) -> str:
            return self.content

        def delete(self, *_args) -> None:
            self.content = ""

        def configure(self, **options) -> None:
            self.state = str(options.get("state", self.state))

    llm = AvailableLlm("codex", "codex", "gpt-5")
    gui = ai_loop_gui.AiLoopGui.__new__(ai_loop_gui.AiLoopGui)
    gui._qa_running = False
    gui._qa_history = [("Earlier?", "Earlier answer.")]
    gui._qa_llms_by_label = {llm.label: llm}
    gui.qa_llm_var = FakeVar(llm.label)
    gui.qa_question_text = FakeWidget("How are tasks queued?")
    gui.qa_ask_button = FakeWidget()
    gui.qa_clear_button = FakeWidget()
    gui.qa_llm_combo = FakeWidget()
    gui.qa_status_var = FakeVar("")
    gui.backend = SimpleNamespace(root_dir=tmp_path)
    appended: list[tuple[str, str]] = []
    gui._append_qa_transcript = lambda heading, content: appended.append(
        (heading, content)
    )
    calls: list[tuple[Path, AvailableLlm, str, tuple[tuple[str, str], ...]]] = []

    def fake_question(repository, selected, question, *, history):
        calls.append((repository, selected, question, history))
        return "Tasks are published through the worker queue."

    monkeypatch.setattr(ai_loop_gui, "ask_project_question", fake_question)

    def immediate_background(work, done, **kwargs):
        assert kwargs["label"] == "AI-Loop Q&A"
        done(work(), None)

    gui._run_bg = immediate_background

    gui.ask_ai_loop_question()

    assert calls == [
        (
            tmp_path,
            llm,
            "How are tasks queued?",
            (("Earlier?", "Earlier answer."),),
        )
    ]
    assert appended == [
        (f"You · {llm.label}", "How are tasks queued?"),
        (f"AI-Loop answer · {llm.label}", "Tasks are published through the worker queue."),
    ]
    assert gui._qa_history[-1] == (
        "How are tasks queued?",
        "Tasks are published through the worker queue.",
    )
    assert gui.qa_question_text.content == ""
    assert gui.qa_ask_button.state == "normal"
    assert gui.qa_llm_combo.state == "readonly"


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a Tk display")
def test_ask_ai_loop_tab_builds_real_tk_controls() -> None:
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        pytest.skip("Tk is not installed")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk cannot connect to a display")
    root.withdraw()

    import ai_loop_gui

    class Harness:
        def help_widget(self, widget, _help_text):
            return widget

        def add_scrolled_text(self, parent, row, column, *, wrap="word"):
            return ai_loop_gui.AiLoopGui.add_scrolled_text(
                self, parent, row, column, wrap=wrap
            )

        def set_text(self, widget, text):
            return ai_loop_gui.AiLoopGui.set_text(widget, text)

        def refresh_qa_llms(self):
            self.qa_llm_combo.configure(values=("Codex — configured",))
            self.qa_llm_var.set("Codex — configured")
            self.qa_status_var.set("1 configured LLM option available.")

        def ask_ai_loop_question(self):
            return None

        def clear_qa_conversation(self):
            return None

        def _on_qa_question_shortcut(self, _event):
            return "break"

    try:
        parent = ttk.Frame(root)
        parent.grid(row=0, column=0, sticky="nsew")
        harness = Harness()

        ai_loop_gui.AiLoopGui._build_ai_loop_qa_tab(harness, parent)

        assert harness.qa_llm_combo.winfo_manager() == "grid"
        assert harness.qa_transcript_text.winfo_manager() == "grid"
        assert harness.qa_question_text.winfo_manager() == "grid"
        assert harness.qa_ask_button.winfo_manager() == "pack"
        assert harness.qa_llm_var.get() == "Codex — configured"
        assert str(harness.qa_transcript_text.cget("state")) == "disabled"
    finally:
        root.destroy()
