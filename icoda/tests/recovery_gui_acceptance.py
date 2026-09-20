"""Exercise Prompt before any failure, project switching, and recovery in a real Tk window."""
from __future__ import annotations

import argparse
import json
import sys
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gui_acceptance import load_application, require_visible

from icoda_core import persistence, recovery
from icoda_core.process import ProcessResult
from tools.capture_cpp_tutorial import capture_window


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    project = args.output / "recovery-project"
    project.mkdir(exist_ok=True)
    app_module = load_application()
    root = tk.Tk()
    original = recovery.invoke
    calls = []

    def provider(provider, model, prompt, cwd, **kwargs):
        calls.append(prompt)
        if "Diagnosis:" not in prompt:
            return recovery.RecoveryResult(ProcessResult([], 0, "Start by inspecting main.cpp.", ""))
        return recovery.RecoveryResult(ProcessResult([], 0,
            "The installed CLI could not be updated automatically. Open CLI to check its installation, "
            "or select another installed provider here. Your project files are unchanged.", ""))

    try:
        app = app_module.App(root, config=persistence.UserConfig(), config_path=args.output / "config.json")
        assert app.views.tab(app.recovery.frame, "text") == "Prompt"
        assert all(button.instate(["disabled"]) for button in app.recovery.buttons.values())
        app.new_project(project)
        assert app.spec_editor is not None
        app.spec_editor.close()
        app.provider_field.set("codex", "gpt-6-astra")
        recovery.invoke = provider

        def finish() -> None:
            deadline = time.monotonic() + 10
            while app.recovery.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(.02)
            assert not app.recovery.busy and not app.panel.busy
            for _ in range(5):
                root.update()
                time.sleep(.05)
            assert not app.panel.progress.winfo_ismapped()

        app.views.select(app.recovery.frame)
        root.update()
        actions = []
        app.steps.action = lambda *args: actions.append(args)
        assert app.recovery.buttons["Open CLI"].instate(["!disabled"])
        assert app.recovery.buttons["Send"].instate(["disabled"])
        for text in ("Explain this project", "Where should I start reading?"):
            app.recovery.input.insert("end", text)
            root.update()
            assert app.recovery.buttons["Send"].instate(["!disabled"])
            assert app.recovery.buttons["Retry step"].instate(["disabled"])
            assert app.recovery.buttons["Details"].instate(["disabled"])
            app.panel.set_busy(True, "building")
            assert app.recovery.buttons["Send"].instate(["disabled"])
            app.panel.set_busy(False)
            assert app.recovery.buttons["Send"].instate(["!disabled"])
            if text == "Where should I start reading?":
                app.recovery.input.focus_force()
                root.update()
                modifier = "Command" if sys.platform == "darwin" else "Control"
                app.recovery.input.event_generate(f"<{modifier}-Return>")
            else:
                app.recovery.buttons["Send"].invoke()
            assert app.recovery.buttons["Send"].instate(["disabled"])
            assert app.recovery.buttons["Cancel"].instate(["!disabled"])
            finish()
        assert len(calls) == 2 and "Explain this project" in calls[1]
        assert not actions, "Prompt's Send shortcut must not also propose a workflow step"
        assert "Start by inspecting main.cpp." in calls[1] and app.recovery.issue is None
        app.recovery.input.insert("end", "How can I add a C++ test?")
        root.update()
        require_visible(root, app.recovery.buttons)
        capture_window(root, args.output / "prompt.png")
        other = args.output / "other-project"
        app.new_project(other)
        assert app.spec_editor is not None
        app.spec_editor.close()
        assert app.recovery.cwd == other.resolve() and not app.recovery.history
        assert not app.recovery.input.get("1.0", "end").strip()
        root.update()
        assert app.recovery.buttons["Send"].instate(["disabled"])
        app.recovery.handle_failure(
            "The 'gpt-6-astra' model requires a newer version of Codex.",
            repair=lambda: ValueError("Automatic update could not complete: installation is locked."),
            retry=lambda: None)
        assert app.recovery.busy and "Trying automatic recovery" in app.status.get()
        finish()
        assert app.views.select() == str(app.recovery.frame)
        for text in ("What is the cause?", "Can I use another provider while I fix the installation?"):
            app.recovery.input.insert("end", text)
            root.update()
            assert app.recovery.buttons["Send"].instate(["!disabled"])
            app.recovery.buttons["Send"].invoke()
            finish()
        assert len(calls) == 4 and "What is the cause?" in calls[3]
        assert "Your project files are unchanged." in calls[3]
        app.recovery.input.insert("end", "I have updated the CLI. What should I check before retrying?")
        require_visible(root, app.recovery.buttons)
        root.update()
        bounds = capture_window(root, args.output / "prompt-recovery.png")
        (args.output / "recovery-gui.json").write_text(json.dumps({
            "passed": True, "scripted_provider_turns": len(calls), "bounds": bounds,
            "status": app.status.get()}, indent=2) + "\n")
        print("PASS: real Tk Prompt before failure, four conversational turns, project reset, recovery, controls")
    finally:
        recovery.invoke = original
        root.destroy()


if __name__ == "__main__":
    main()
