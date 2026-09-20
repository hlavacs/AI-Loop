"""Exercise recovery and a two-turn troubleshooting conversation in a real Tk window."""
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
        return recovery.RecoveryResult(ProcessResult([], 0,
            "The installed CLI could not be updated automatically. Open CLI to check its installation, "
            "or select another installed provider here. Your project files are unchanged.", ""))

    try:
        app = app_module.App(root, config=persistence.UserConfig(), config_path=args.output / "config.json")
        app.project = project
        app.provider_field.set("codex", "gpt-6-astra")
        recovery.invoke = provider
        app.recovery.handle_failure(
            "The 'gpt-6-astra' model requires a newer version of Codex.",
            repair=lambda: ValueError("Automatic update could not complete: installation is locked."),
            retry=lambda: None)
        assert app.recovery.busy and "Trying automatic recovery" in app.status.get()

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

        finish()
        assert app.views.select() == str(app.recovery.frame)
        for text in ("What is the cause?", "Can I use another provider while I fix the installation?"):
            app.recovery.input.insert("end", text)
            app.recovery.buttons["Send"].invoke()
            finish()
        assert len(calls) == 2 and "What is the cause?" in calls[1]
        assert "Your project files are unchanged." in calls[1]
        app.recovery.input.insert("end", "I have updated the CLI. What should I check before retrying?")
        require_visible(root, app.recovery.buttons)
        bounds = capture_window(root, args.output / "troubleshooting.png")
        (args.output / "recovery-gui.json").write_text(json.dumps({
            "passed": True, "scripted_provider_turns": len(calls), "bounds": bounds,
            "status": app.status.get()}, indent=2) + "\n")
        print("PASS: real Tk recovery, two conversational turns, visible controls, screenshot")
    finally:
        recovery.invoke = original
        root.destroy()


if __name__ == "__main__":
    main()
