"""Compact project-wide executable/library selector and selected-target build/run actions."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any

from icoda_core import executables, persistence, process, recovery, session, steps
from icoda_core.model import DerivedModel
from icoda_gui import tooltip


class ExecutableSelector:
    def __init__(self, window: Any, bar: Any, notebook: Any) -> None:
        self.window = window
        self.project: Path | None = None
        self.model: DerivedModel | None = None
        self.choices: tuple[executables.Entry, ...] = ()
        self.selected: executables.Entry | None = None
        self.running = False
        self.choice_var = tk.StringVar(value="No targets")
        ttk.Label(bar, text="Executable / library:").pack(side=tk.LEFT, padx=(4, 4))
        self.buttons = {}
        for label, command in (("Output", self.show_output), ("Stop", self.stop),
                               ("Run", lambda: self.operate("run")),
                               ("Build", lambda: self.operate("build")),
                               ("Refresh targets", lambda: self.operate("refresh"))):
            button = ttk.Button(bar, text=label, command=command)
            button.pack(side=tk.RIGHT, padx=(0, 4))
            self.buttons[label] = button
        self.combo = ttk.Combobox(bar, textvariable=self.choice_var, state="readonly", width=45)
        self.combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.combo.bind("<<ComboboxSelected>>", self.select)
        tooltip.attach(self.combo, "Choose one executable or library to display its sources and dependencies "
                       "in all code views. The choice is saved per project. Libraries expose functions and methods "
                       "without a main; "
                       "Build is available for both, Run only for executables.")
        tooltip.attach(self.buttons["Refresh targets"], "Refresh CMake target names and configurations "
                       "from the project's configured build tree.")
        tooltip.attach(self.buttons["Build"], "Build the selected target. When no targets have been discovered, "
                       "build the project using its existing CMake configuration and analyse its sources.")
        tooltip.attach(self.buttons["Run"], "Build the selected CMake target, then run its executable "
                       "from the project directory. Output is captured; Stop cancels it.")
        self.notebook = notebook
        self.output_frame = ttk.Frame(notebook)
        notebook.add(self.output_frame, text="Program output")
        self.output = tk.Text(self.output_frame, wrap=tk.WORD, state="disabled", width=30, height=8)
        scroll = ttk.Scrollbar(self.output_frame, command=self.output.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.output.configure(yscrollcommand=scroll.set)
        self.output.pack(fill=tk.BOTH, expand=True)
        self.update_controls()

    def show(self, project: Path, model: DerivedModel) -> None:
        if self.project != project:
            self._output("")
        self.project, self.model = project, model
        try:
            targets = executables.read_targets(project)
        except (OSError, ValueError, KeyError, TypeError):
            # Still offer source-based graph selection; Refresh regenerates stale CMake metadata.
            targets = ()
        key = persistence.ProjectStore(project).load_ui().get("executable")
        self._choices(executables.entries(model, targets), key)

    def clear(self) -> None:
        self.project, self.model, self.selected = None, None, None
        self._choices((), None)
        self.window.call_view.entry_usr = None
        self._output("")

    def _choices(self, choices: tuple[executables.Entry, ...], key: Any) -> None:
        self.choices = choices
        self.combo.configure(values=[entry.label for entry in choices])
        self.selected = executables.choose(choices, key)
        self.choice_var.set(self.selected.label if self.selected else
                            "Select executable / library" if choices else "No targets")
        self._call_entry()
        self.update_controls()

    def select(self, _event: Any = None) -> None:
        chosen = next((entry for entry in self.choices if entry.label == self.choice_var.get()), None)
        if self.window.panel.busy or chosen is None:
            return
        if not self.window.source_editor.confirm_saved():
            self.choice_var.set(self.selected.label if self.selected else "Select executable / library")
            return
        self.selected = chosen
        self._save_selection()
        self._call_entry()
        self.update_controls()
        self.window.show_executable()
        if chosen.usr:
            self.window.select_node(chosen.usr)
        self.window.status.set(f"Selected {chosen.label}")

    def _call_entry(self) -> None:
        self.window.call_view.entry_usr = self.selected.usr if self.selected else None
        self.window.call_view.library_mode = bool(self.selected and self.selected.is_library)

    def _save_selection(self) -> None:
        if self.project is not None:
            store = persistence.ProjectStore(self.project)
            ui = store.load_ui()
            if self.selected is not None:
                ui["executable"] = self.selected.key
            else:
                ui.pop("executable", None)
            store.save_ui(ui)

    def update_controls(self) -> None:
        ready = self.project is not None and self.window.project == self.project and not self.window.panel.busy
        self.combo.configure(state="readonly" if ready and self.choices else "disabled")
        cmake = ready and (self.project / "CMakeLists.txt").is_file() if self.project else False
        for label in ("Build", "Run", "Refresh targets"):
            enabled = cmake and (label == "Refresh targets" or self.selected is not None)
            if label == "Build" and (not self.choices or not (self.model and self.model.files)):
                enabled = cmake
            if label == "Run" and self.selected is not None and self.selected.is_library:
                enabled = False
            self.buttons[label].state(["!disabled"] if enabled else ["disabled"])
        self.buttons["Stop"].state(["!disabled"] if self.running else ["disabled"])

    def show_output(self) -> None:
        self.notebook.select(self.output_frame)

    def _output(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

    def stop(self) -> None:
        if self.running:
            self.window.steps.cancel_requested = True
            process.cancel_running()

    def operate(self, action: str) -> None:
        if self.project is None or self.model is None or self.window.panel.busy:
            return
        if action == "build" and (not self.choices or not self.model.files):
            self.window.build_project()
            return
        if action != "refresh" and self.selected is None:
            return
        if action == "run" and self.selected is not None and self.selected.is_library:
            return
        if not self.window.source_editor.confirm_saved():
            return
        if self.window.panel.busy:  # saving source may start analysis; wait for its current model
            return
        project, model, selected = self.project, self.model, self.selected
        self.running = True
        self.window.steps.cancel_requested = False
        self.window.panel.set_busy(True, f"{action}: {selected.label if selected else 'targets'}", cancellable=True)
        self._output(f"{action.capitalize()} in progress. Output will appear when the operation finishes.\n")
        self.show_output()
        self.update_controls()

        def done(result: Any) -> None:
            self.running = False
            self.window.panel.set_busy(False)
            if project != self.window.project:
                return
            if isinstance(result, steps.StepCancelled):
                self._output("Cancelled.\n")
                self.window.status.set("Target operation cancelled")
            elif isinstance(result, Exception):
                self._output("ICODA is attempting recovery. See Prompt if further input is needed.\n")
                options: dict[str, Any] = {"retry": lambda: self.operate(action)}
                state = persistence.ProjectStore(project).load_state()
                if (recovery.diagnose(str(result)).code == "project_gate"
                        and state.phase == persistence.ProjectPhase.ARCHITECTURE):
                    runner = self.window.steps._ensure_runner()
                    options.update(repair=lambda: runner.repair_project(str(result)),
                                   repaired=self.window.steps._show_proposal)
                self.window.recovery.handle_failure(result, **options)
            else:
                self._choices(result.entries, result.selected.key if result.selected else None)
                if result.selected is None:  # ambiguity requires an explicit new selection
                    self.selected = None
                    self._call_entry()
                    self.choice_var.set("Choose target / configuration")
                self._save_selection()
                self.window.show_executable()
                self._output(result.output)
                self.window.status.set(result.message)
                session.log_event(result.message + "\n" + result.output, project)
                if action == "refresh" and not model.files:
                    self.window.open_project(project)
            self.update_controls()

        self.window.run_async(lambda: executables.operate(
            project, model, selected, action, lambda: self.window.steps.cancel_requested), done)
