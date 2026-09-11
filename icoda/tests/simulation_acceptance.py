"""Replay ICODA's full lifecycle and capture every developer decision point."""

from __future__ import annotations

import argparse
import json
import sys
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gui_acceptance import capture, load_application, require_visible, wait_for_project
from test_simulation import ScriptedProvider, runner_factory, simulation_replies, write_simulation_project

from icoda_core import implementation_queue, persistence
from icoda_gui import dialogs, step_controller


def _wait(root: tk.Tk, app: Any, condition: Callable[[], bool], label: str,
          timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)
    root.update()
    if not condition():
        raise TimeoutError(f"{label} did not complete within {timeout:.0f} seconds: {app.status.get()}")
    if app.panel.title_var.get().startswith("Step failed"):
        raise RuntimeError(app.panel.title_var.get())


def _action(root: tk.Tk, app: Any, name: str) -> None:
    app.steps.action(name)
    _wait(root, app, lambda: not app.panel.busy, name)


def _capture_stop(root: tk.Tk, app: Any, output: Path, name: str,
                  metrics: dict[str, dict[str, float | int]]) -> None:
    require_visible(root, {
        **app.panel.buttons,
        "batch-size": app.panel.batch_size_spinbox,
        "filter": app.graph_filter_entry,
        "neighborhood": app.neighborhood_spinbox,
        "collapse-all": app.collapse_all_button,
    })
    path = output / name
    metrics[name] = capture(root, path)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"empty or absent lifecycle capture: {name}")


class _AcceptanceRun:
    def __init__(self, root: tk.Tk, app: Any, project: Path, output: Path,
                 provider: ScriptedProvider) -> None:
        self.root, self.app, self.project, self.output = root, app, project, output
        self.provider = provider
        self.metrics: dict[str, dict[str, float | int]] = {}

    def capture(self, name: str) -> None:
        _capture_stop(self.root, self.app, self.output, name, self.metrics)

    def capture_specification_editor(self, name: str) -> None:
        editor = self.app.spec_editor
        if editor is None:
            raise RuntimeError("the specification editor did not open")
        require_visible(editor.window, {"specification-pages": editor.notebook})
        path = self.output / name
        self.metrics[name] = capture(editor.window, path)
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"empty or absent lifecycle capture: {name}")

    def specification(self) -> None:
        self._refuse_specification_code_step()
        self._save_specification()

    def _refuse_specification_code_step(self) -> None:
        app, root = self.app, self.root
        store = persistence.ProjectStore(self.project)
        before_request = store.load_state()
        if before_request.phase is not persistence.ProjectPhase.SPECIFICATION:
            raise RuntimeError(f"simulation did not start in specification: {before_request}")
        app.steps.action("propose")
        deadline = time.monotonic() + 30.0
        while app.panel.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        root.update()
        if app.panel.busy:
            raise TimeoutError("specification refusal did not complete")
        refusal = "save the specification before proposing"
        if refusal not in app.panel.title_var.get() or refusal not in app.status.get():
            raise RuntimeError("the specification code-step refusal was not visible in the panel and status")
        if store.load_state() != before_request:
            raise RuntimeError("the refused specification request changed persisted project state")
        self.capture("sim-01-specification-code-refused.png")

    def _save_specification(self) -> None:
        app, root = self.app, self.root
        store = persistence.ProjectStore(self.project)
        app.edit_specification()
        root.update()
        if store.load_state().phase is not persistence.ProjectPhase.SPECIFICATION:
            raise RuntimeError("the project left specification before the developer saved it")
        self.capture_specification_editor("sim-02-specification-save.png")
        editor = app.spec_editor
        if editor is None or not editor.save():
            raise RuntimeError("the specification Save control did not accept the fixture")
        editor.close()
        root.update()
        if store.load_state().phase is not persistence.ProjectPhase.ARCHITECTURE \
                or app.panel.phase_var.get() != persistence.ProjectPhase.ARCHITECTURE.value:
            raise RuntimeError("the specification Save control did not persist architecture")

    def architecture(self) -> None:
        app, root = self.app, self.root
        _action(root, app, "propose")
        app.panel.detail_notebook.select(app.panel.source_diff.master)
        self.capture("sim-03-architecture-reject.png")
        _action(root, app, "reject")
        _action(root, app, "propose")
        app.panel.detail_notebook.select(app.panel.details.master)
        self.capture("sim-04-architecture-approve.png")
        _action(root, app, "approve")
        app.views.select(0)
        self.capture("sim-05-architecture-gate.png")
        previous_opened = app.opened
        _action(root, app, "approve_architecture")
        _wait(root, app, lambda: app.opened is not previous_opened, "architecture refresh")

    def normalize(self) -> None:
        app, root = self.app, self.root
        _action(root, app, "propose_approach")
        app.panel.detail_notebook.select(app.panel.approach_text.master)
        self.capture("sim-06-normalize-approach.png")
        _action(root, app, "approve_approach")
        _action(root, app, "propose")
        app.show_class_view()
        app.panel.detail_notebook.select(app.panel.details.master)
        self.capture("sim-07-normalize-build-test.png")
        _action(root, app, "approve")

    def main_target(self) -> None:
        app, root = self.app, self.root
        _action(root, app, "propose_approach")
        app.show_mind_map_view()
        app.panel.detail_notebook.select(app.panel.approach_text.master)
        self.capture("sim-08-main-approach.png")
        _action(root, app, "approve_approach")
        _action(root, app, "propose")
        app.show_issue_view()
        app.panel.detail_notebook.select(app.panel.source_diff.master)
        self.capture("sim-09-main-build-test.png")
        _action(root, app, "approve")

    def finish(self) -> dict[str, Any]:
        self.app.show_coverage_view()
        self.capture("sim-10-terminal-overview.png")
        state = persistence.ProjectStore(self.project).load_state()
        terminal = (
            state.phase is persistence.ProjectPhase.IMPLEMENTATION
            and implementation_queue.target_usr(state) is None
            and state.implementation_cursor == len(state.implementation_queue)
            and self.app.panel.phase_var.get() == persistence.ProjectPhase.IMPLEMENTATION.value
            and "empty" in self.app.panel.queue_var.get()
        )
        if not terminal:
            raise RuntimeError(f"simulation did not reach terminal implementation state: {state}")
        if self.provider.replies:
            raise RuntimeError(f"simulation left {len(self.provider.replies)} scripted provider replies unused")
        if len(self.metrics) != 10 or any(not (self.output / name).stat().st_size for name in self.metrics):
            raise RuntimeError("simulation did not retain all ten non-empty decision-point captures")
        return {"phase": state.phase.value, "queue": list(state.implementation_queue),
                "cursor": state.implementation_cursor, "terminal": terminal,
                "screenshots": self.metrics}


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def _disable_scripted_dialogs() -> None:
    dialogs.show_error = lambda *args, **kwargs: None
    step_controller.messagebox.askyesno = lambda *args, **kwargs: True
    step_controller.messagebox.showinfo = lambda *args, **kwargs: ""
    step_controller.simpledialog.askstring = lambda *args, **kwargs: "Keep the public API smaller"


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    if args.project.exists() and any(args.project.iterdir()):
        raise RuntimeError(f"simulation project directory is not empty: {args.project}")
    args.output.mkdir(parents=True, exist_ok=True)
    write_simulation_project(args.project)
    provider = ScriptedProvider(simulation_replies())
    root = tk.Tk()
    root.geometry("1200x760+20+20")
    try:
        module = load_application()
        _disable_scripted_dialogs()
        app = module.App(root, config=persistence.UserConfig(),
                         config_path=args.output / "user-config.json")
        app.steps = step_controller.StepController(app, runner_factory(provider))
        app.open_project(args.project)
        wait_for_project(root, app, args.project)
        root.geometry("1200x760+20+20")
        run = _AcceptanceRun(root, app, args.project, args.output, provider)
        run.specification()
        run.architecture()
        run.normalize()
        run.main_target()
        result = run.finish()
        (args.output / "simulation-state.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    finally:
        root.destroy()


if __name__ == "__main__":
    raise SystemExit(main())
