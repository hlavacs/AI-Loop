"""Recovery-first failure handling and a conversational interface to the selected CLI provider."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from typing import Any

from icoda_core import agent, process, recovery, session, steps, terminal
from icoda_gui import provider_field


class Troubleshooting:
    def __init__(self, window: Any) -> None:
        self.window = window
        self.frame = ttk.Frame(window.views)
        window.views.add(self.frame, text="Troubleshooting")
        self.issue: recovery.Diagnosis | None = None
        self.history: list[tuple[str, str]] = []
        self.retry: Callable[[], None] | None = None
        self.project: Path | None = None
        self.cwd: Path | None = None
        self.generation = 0
        self.busy = False
        self.cancelled = False
        self.finishing = False
        self.pending: list[tuple[Exception | str, dict[str, Any], Path | None]] = []
        self.summary = tk.StringVar(value="Recovery and direct CLI help appear here when an operation fails.")
        ttk.Label(self.frame, textvariable=self.summary, wraplength=850, justify="left").pack(
            fill=tk.X, padx=8, pady=6)
        selection = window.provider_field.selection()
        self.provider = provider_field.ProviderField(self.frame, agent.load_providers(),
                                                    binary=selection.binary, model=selection.model)
        self.provider.frame.pack(fill=tk.X, padx=8)
        ttk.Label(self.frame, text="Use another Binary/Model here if the failing provider cannot respond.",
                  anchor="w").pack(fill=tk.X, padx=8, pady=2)
        self.transcript = self._text(self.frame, 12, editable=False)
        self.input = self._text(self.frame, 3, editable=True)
        self.input.bind("<Control-Return>", lambda _event: self.send())
        self.input.bind("<Command-Return>", lambda _event: self.send())
        row = ttk.Frame(self.frame)
        row.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=4)
        self.input.master.pack(side=tk.BOTTOM, fill=tk.X, padx=8)
        self.transcript.master.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.buttons = {}
        for label, command in (("Send", self.send), ("Cancel", self.cancel),
                               ("Retry step", self.retry_step), ("Open CLI", self.open_cli),
                               ("Details", self.details)):
            self.buttons[label] = ttk.Button(row, text=label, command=command)
            self.buttons[label].pack(side=tk.LEFT, padx=(0, 6))
        self._controls()

    @staticmethod
    def _text(parent: Any, height: int, *, editable: bool) -> Any:
        frame = ttk.Frame(parent)
        text = tk.Text(frame, wrap="word", height=height, state="normal" if editable else "disabled")
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(fill=tk.BOTH, expand=True)
        text.master = frame
        return text

    def _append(self, role: str, text: str) -> None:
        self.transcript.configure(state="normal")
        self.transcript.insert("end", f"{role}\n{recovery.redact(text)}\n\n")
        self.transcript.configure(state="disabled")
        self.transcript.see("end")

    def _controls(self) -> None:
        for label, button in self.buttons.items():
            enabled = self.busy if label == "Cancel" else not self.busy and self.issue is not None
            if label in {"Send", "Open CLI"}:
                enabled = enabled and self.cwd is not None
            if label == "Retry step":
                enabled = enabled and self.retry is not None
            button.state(["!disabled"] if enabled else ["disabled"])

    def reset(self) -> None:
        """Invalidate callbacks and conversations when the project changes."""
        self.generation += 1
        self.pending.clear()
        if self.busy:
            self.cancel()
            self._set_busy(False)
        self.issue, self.retry, self.project, self.cwd = None, None, None, None
        self.history.clear()
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")
        self.input.delete("1.0", "end")
        self.summary.set("Recovery and direct CLI help appear here when an operation fails.")
        self._controls()

    def handle_failure(self, error: Exception | str, *, retry: Callable[[], None] | None = None,
                       repair: Callable[[], Any] | None = None,
                       repaired: Callable[[Any], None] | None = None,
                       attempted: bool = False, cwd: Path | None = None) -> None:
        """Try recovery before exposing a failure; provider failures already carry their repair result."""
        if self.busy:
            session.log_event("additional error during recovery: " + recovery.redact(str(error)),
                              self.window.project)
            if not any(str(item[0]) == str(error) for item in self.pending):
                self.pending.append((error, {"retry": retry, "repair": repair, "repaired": repaired,
                                                "attempted": attempted, "cwd": cwd}, self.window.project))
            return
        self.project = Path(self.window.project) if self.window.project else None
        self.cwd = cwd or self.project
        self.retry = retry
        self.issue = error.diagnosis if isinstance(error, steps.ProviderError) else recovery.diagnose(str(error))
        selection = self.window.provider_field.selection()
        self.provider.set(selection.binary, selection.model)
        self.history.clear()
        self.generation += 1
        if isinstance(error, steps.ProviderError) or attempted or self.finishing:
            self._present("Automatic recovery attempts have finished without resolving the failure.")
            return
        self.summary.set("Trying automatic recovery…")
        self.window.status.set("Trying automatic recovery…")
        token = self.generation
        issue, project = self.issue, self.project

        def work() -> Any:
            if repair is not None:
                return repair()
            return self._investigate(issue, selection, project)

        def done(result: Any) -> None:
            if token != self.generation:
                return
            self._set_busy(False)
            if self.cancelled or isinstance(result, steps.StepCancelled):
                self._present("Recovery was cancelled. You can continue the investigation here.")
            elif not isinstance(result, Exception) and repaired is not None and getattr(result, "ok", True):
                self.summary.set("Automatic recovery completed. Review the result before continuing.")
                self._append("ICODA", self.summary.get())
                self.finishing = True
                try:
                    repaired(result)
                except Exception as exc:  # noqa: BLE001  (the recovery callback must not start a retry loop)
                    self._present("Recovery could not restore the interface: " + recovery.redact(str(exc)))
                finally:
                    self.finishing = False
            else:
                if isinstance(result, steps.Proposal):
                    self.cwd = result.worktree
                    self.window.steps.proposal = result
                    self.window.panel.show(result)
                    outcome = result.error + "\n" + result.build.output + "\n" + result.test.output
                else:
                    outcome = str(result) if result is not None else "No automatic fix found."
                self._present(recovery.redact(outcome))

        runner = self.window.steps.runner
        if runner is not None:
            runner.begin()
        self._set_busy(True)
        self.window.run_async(work, done)

    def _investigate(self, issue: recovery.Diagnosis, selection: provider_field.ProviderSelection,
                     project: Path | None) -> str:
        """Ask for evidence-based recovery when there is no deterministic repair handler."""
        if issue.code == "workflow":
            return "Checked the workflow prerequisites. " + issue.next_step
        if project is None or not selection.provider_id:
            return "No project or provider is available for automatic investigation."
        provider = agent.find_provider(agent.load_providers(), selection.provider_id)
        if not provider.enabled:
            return "The selected CLI is disabled. Choose an enabled provider here."
        question = ("Diagnose this failure and identify the smallest fix. Run read-only checks when useful. "
                    "Explain what can be repaired.")
        request = recovery.conversation_prompt(issue, [("Developer", question)], project)
        result = recovery.invoke(provider, selection.model or provider.default_model, request, project,
                                 binary=selection.binary, timeout=120, cancelled=lambda: self.cancelled).result
        if result.cancelled:
            raise steps.StepCancelled()
        if not result.ok:
            return "Automatic investigation could not complete:\n" + recovery.diagnose(
                result.stderr or result.stdout).text()
        return result.stdout

    def _present(self, outcome: str) -> None:
        assert self.issue is not None
        self.summary.set(self.issue.summary)
        proposal = self.window.steps.proposal
        if proposal is not None and not proposal.ok:
            self.window.panel.show(proposal)
            self.window.steps._consider_auto_approve()
        self.window.status.set("Recovery needs your input — see Troubleshooting")
        self.window.panel.show_failure(self.issue.text())
        self._append("ICODA diagnosis", self.issue.text())
        self._append("Recovery result", outcome)
        self.history.append(("Assistant", recovery.redact(outcome)))
        session.log_event("recovery unresolved: " + self.issue.text() + "\n" + recovery.redact(outcome),
                          self.project)
        self.window.views.select(self.frame)
        self._controls()

    def _set_busy(self, value: bool) -> None:
        self.busy = value
        if value:
            self.cancelled = False
        self.window.panel.set_busy(value, "recovering / talking to the CLI" if value else "", cancellable=value)
        self._controls()
        if not value and self.pending:
            self.window.root.after(0, self._drain_pending)

    def _drain_pending(self) -> None:
        if not self.busy and self.pending:
            error, options, project = self.pending.pop(0)
            if project == self.window.project:
                self.handle_failure(error, **options)
            if not self.busy and self.pending:
                self.window.root.after(0, self._drain_pending)

    def cancel(self) -> None:
        if self.busy:
            self.cancelled = True
            if self.window.steps.runner is not None:
                self.window.steps.runner.cancel()
            else:
                process.cancel_running()

    def send(self) -> None:
        if self.busy or self.window.panel.busy or self.issue is None or self.cwd is None:
            return
        message = self.input.get("1.0", "end").strip()
        if not message:
            return
        selection = self.provider.selection()
        if not selection.provider_id:
            self._append("ICODA", "Select an enabled provider in Binary first.")
            return
        provider = agent.find_provider(agent.load_providers(), selection.provider_id)
        if not provider.enabled:
            self._append("ICODA", "This provider is disabled. Choose an enabled provider.")
            return
        self.input.delete("1.0", "end")
        self.history.append(("Developer", message))
        self._append("You", message)
        request = recovery.conversation_prompt(self.issue, self.history, self.cwd)
        cwd, token = self.cwd, self.generation
        self._set_busy(True)

        def done(result: Any) -> None:
            if token != self.generation:
                return
            self._set_busy(False)
            if self.cancelled or isinstance(result, steps.StepCancelled):
                self._append("ICODA", "Conversation request cancelled.")
                return
            if isinstance(result, Exception):
                self._append("ICODA", recovery.diagnose(str(result)).text())
                return
            if result.result.cancelled:
                self._append("ICODA", "Conversation request cancelled.")
                return
            answer = result.result.stdout if result.result.ok else result.diagnosis.text()
            self.history.append(("Assistant", answer))
            self._append(provider.label, answer)

        self.window.run_async(lambda: recovery.invoke(
            provider, selection.model or provider.default_model, request, cwd, binary=selection.binary,
            timeout=180, cancelled=lambda: self.cancelled), done)

    def retry_step(self) -> None:
        if self.busy or self.window.panel.busy or self.retry is None or self.project != self.window.project:
            return
        selection = self.provider.selection()
        self.window.provider_field.set(selection.binary, selection.model)
        self.window.steps._ensure_runner()  # retries may close over the existing runner
        self.retry()

    def open_cli(self) -> None:
        if self.busy or self.window.panel.busy or self.issue is None or self.cwd is None:
            return
        selection = self.provider.selection()
        if not selection.provider_id:
            self._append("ICODA", "Select an enabled Binary first.")
            return
        provider = agent.find_provider(agent.load_providers(), selection.provider_id)
        context = ("Help me resolve this ICODA failure in the current project/worktree. "
                   "Inspect the cause and make the smallest fix with my normal CLI approvals. "
                   "Preserve tests and do not commit or change ICODA metadata.\n" + self.issue.text()
                   + "\nError evidence:\n" + self.issue.detail[-8000:])
        cwd = self.cwd

        def work() -> None:
            command = terminal.interactive_command(provider, selection.binary,
                                                  selection.model or provider.default_model, cwd, context)
            terminal.open_cli(command, cwd)

        token = self.generation
        self._set_busy(True)

        def done(result: Any) -> None:
            if token != self.generation:
                return
            self._set_busy(False)
            if isinstance(result, Exception):
                self._append("ICODA", "Could not open the terminal: " + str(result)
                             + "\nYou can continue using Send in this tab.")
                return
            self._append("ICODA", "Opened the interactive CLI. After the fix, return here and Retry step "
                         "to run the checks again.")
        self.window.run_async(work, done)

    def details(self) -> None:
        if self.issue is not None:
            self._append("Error evidence", self.issue.detail)
