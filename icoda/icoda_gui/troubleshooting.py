"""Recovery-first failure handling and a conversational interface to the selected CLI provider."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from functools import partial
from pathlib import Path
from threading import Event
from tkinter import ttk
from typing import Any

from icoda_core import agent, documentation, process, recovery, session, source_watch, steps, terminal
from icoda_gui import provider_field, tasks


class Troubleshooting:
    def __init__(self, window: Any) -> None:
        self.window = window
        self.frame = ttk.Frame(window.views)
        window.views.add(self.frame, text="Prompt")
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
        self.purpose_attempts: dict[str, int] = {}
        self.purpose_active = False
        self.purpose_busy = False
        self.purpose_cancel = Event()
        self.summary = tk.StringVar(value="Open a project to ask questions or edit files in Prompt.")
        ttk.Label(self.frame, textvariable=self.summary, wraplength=850, justify="left").pack(
            fill=tk.X, padx=8, pady=6)
        selection = window.provider_field.selection()
        self.provider = provider_field.ProviderField(self.frame, agent.load_providers(),
                                                    binary=selection.binary, model=selection.model)
        self.provider.frame.pack(fill=tk.X, padx=8)
        ttk.Label(self.frame, text="Send can inspect and edit project files. Open CLI opens an interactive terminal.",
                  anchor="w").pack(fill=tk.X, padx=8, pady=2)
        self.transcript = self._text(self.frame, 12, editable=False)
        self.input = self._text(self.frame, 3, editable=True)
        self.input.bind("<Control-Return>", self._send_shortcut)
        self.input.bind("<Command-Return>", self._send_shortcut)
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
        self.input.bind("<<Modified>>", self._input_changed)
        self.provider.on_change = self._controls
        window.panel.activity_var.trace_add("write", lambda *_args: self._controls())
        window.panel.activity_var.trace_add(
            "write", lambda *_args: window.root.after(0, self.ensure_purpose_comments))
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
        idle = not self.busy and not self.window.panel.busy
        selection = self.provider.selection()
        provider = provider_field.resolve_provider(self.provider.providers, selection.binary)
        ready = idle and self.cwd is not None and provider is not None and provider.enabled
        enabled = {"Send": ready and bool(self.input.get("1.0", "end").strip()),
                   "Open CLI": ready, "Cancel": self.busy or self.purpose_busy,
                   "Retry step": idle and self.retry is not None and self.project == self.window.project,
                   "Details": idle and self.issue is not None}
        for label, button in self.buttons.items():
            button.state(["!disabled"] if enabled[label] else ["disabled"])

    def _input_changed(self, _event: Any = None) -> None:
        if self.input.edit_modified():
            self.input.edit_modified(False)
            self._controls()

    def _send_shortcut(self, _event: Any = None) -> str:
        self.send()
        return "break"  # Do not also run the application's Propose shortcut.

    def set_project(self, project: Path) -> None:
        """Enable ordinary conversations on project open, preserving them across reloads."""
        if self.project == project:
            return
        self.reset()
        self.project = self.cwd = project
        self.follow_provider()
        self.summary.set(f"Ask about {project.name}, review code, or request changes with the selected CLI.")
        self._controls()

    def follow_provider(self) -> None:
        """Use the project's provider until a conversation or recovery has started."""
        if not self.history and self.issue is None and not self.busy:
            selection = self.window.provider_field.selection()
            self.provider.set(selection.binary, selection.model)

    def reset(self) -> None:
        """Invalidate callbacks and conversations when the project changes."""
        self.generation += 1
        self.cancel_purpose_comments()
        self.pending.clear()
        if self.busy:
            self.cancel()
            self._set_busy(False)
        self.issue, self.retry, self.project, self.cwd = None, None, None, None
        self.history.clear()
        self.purpose_attempts.clear()
        self.purpose_active = False
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")
        self.input.delete("1.0", "end")
        self.summary.set("Open a project to ask questions or edit files in Prompt.")
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
        project = Path(self.window.project) if self.window.project else None
        if self.project != project:
            self.reset()
        self.project = project
        self.cwd = cwd or self.project
        self.retry = retry
        self.issue = error.diagnosis if isinstance(error, steps.ProviderError) else recovery.diagnose(str(error))
        selection = self.window.provider_field.selection()
        self.provider.set(selection.binary, selection.model)
        self.generation += 1
        if isinstance(error, steps.ProviderError) or attempted or self.finishing:
            self._present("Automatic recovery attempts have finished without resolving the failure.")
            return
        self.summary.set("Trying automatic recovery…")
        self.window.status.set("Trying automatic recovery…")
        token = self.generation
        issue, project = self.issue, self.project
        llm_requested = False

        def request_started() -> None:
            nonlocal llm_requested
            llm_requested = True

        def work() -> Any:
            if repair is not None:
                request_started()
                return repair()
            return self._investigate(issue, selection, project, request_started)

        def done(result: Any) -> None:
            if token != self.generation:
                return
            self._set_busy(False)
            if llm_requested and not self.cancelled and not isinstance(result, steps.StepCancelled):
                tasks.completion_ping(self.window.root)
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
                     project: Path | None, request_started: Callable[[], None]) -> str:
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
        request_started()
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
        self.window.status.set("Recovery needs your input — see Prompt")
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
        else:
            self.cancel_purpose_comments()

    def cancel_purpose_comments(self) -> None:
        """Cancel this window's comment job without stopping a build or a Prompt request."""
        self.purpose_cancel.set()
        self.purpose_busy = False
        self.purpose_attempts = {usr: 2 for usr in self.purpose_attempts}
        self._controls()

    def ensure_purpose_comments(self) -> None:
        """Complete missing source comments automatically, with at most two attempts per entity."""
        opened = self.window.opened
        if (opened is None or opened.root != self.project or self.purpose_busy or self.busy or self.window.panel.busy
                or self.window._pending_analyses or self.window._editor_refresh_pending is not None
                or self.window.source_editor.dirty):
            return
        model = opened.model  # The whole project, even when the diagrams show only one target.
        if model.stale or any(info.errors for info in model.files.values()):
            return  # Fix analysis before asking an agent to document incomplete source facts.
        missing = documentation.missing_entities(model)
        usrs = {entity.usr for entity in missing}
        self.purpose_attempts = {usr: count for usr, count in self.purpose_attempts.items() if usr in usrs}
        if not missing:
            if self.purpose_active:
                self.summary.set(f"Purpose comments verified for all {len(model.entities)} project entities.")
                self._append("ICODA", self.summary.get())
                self.purpose_active = False
            return
        pending = tuple(entity for entity in missing if self.purpose_attempts.get(entity.usr, 0) < 2)
        if not pending:
            if self.purpose_active:
                self.summary.set(f"{len(missing)} entities still need purpose comments. Continue in Prompt.")
                self._append("ICODA", self.summary.get())
                self.purpose_active = False
            return
        selection = self.window.provider_field.selection()
        provider = provider_field.resolve_provider(self.provider.providers, selection.binary)
        if provider is None or not provider.enabled or not agent.binary_available(provider, selection.binary):
            self.window.status.set(f"{len(missing)} entities need purpose comments — choose an available CLI in LLM.")
            return
        for entity in pending:
            self.purpose_attempts[entity.usr] = self.purpose_attempts.get(entity.usr, 0) + 1
        self.purpose_active = True
        self.summary.set(f"Adding purpose comments for {len(pending)} entities in the background. You can keep working.")
        self._document_in_background(documentation.completion_prompt(pending), tuple(model.files),
                                     provider, selection)

    def _document_in_background(self, message: str, files: tuple[str, ...], provider: agent.Provider,
                                selection: provider_field.ProviderSelection) -> None:
        """Use an independent worker and cancellation event, without the workflow's busy flag."""
        project = self.project
        assert project is not None
        cancel = self.purpose_cancel = Event()
        self.purpose_busy = True
        self._append("ICODA purpose comments", message)
        self._controls()

        def invoke(scratch: Path) -> recovery.RecoveryResult:
            return recovery.invoke(
                provider, selection.model or provider.default_model, message, scratch,
                binary=selection.binary, timeout=1800, cancelled=cancel.is_set, writable=True,
                runner=partial(process.run_bounded, cancel_event=cancel))

        def done(result: Any) -> None:
            if cancel is not self.purpose_cancel or project != self.project:
                return
            if cancel.is_set():
                self.purpose_busy = False
                self._controls()
                return
            # Applying files and reloading must not interrupt a foreground step or unsaved editor buffer.
            if (self.busy or self.window.panel.busy or self.window._pending_analyses
                    or self.window._editor_refresh_pending is not None or self.window.source_editor.dirty
                    or self.window.steps.proposal is not None):
                self.window.root.after(250, lambda: done(result))
                return
            self.purpose_busy = False
            if isinstance(result, Exception):
                self._append("ICODA purpose comments", recovery.diagnose(str(result)).text())
            elif result.response.result.cancelled:
                self.purpose_attempts = {usr: 2 for usr in self.purpose_attempts}
                self._append("ICODA purpose comments", "Background comment request cancelled.")
            else:
                changed = False
                skipped = list(result.skipped)
                for original, text in result.edits:
                    try:
                        original.save(text)  # Refuses a file changed by the user since the snapshot.
                        changed = True
                    except (OSError, ValueError):
                        skipped.append(original.relative)
                response = result.response
                answer = (response.result.stdout if response.result.ok else
                          (response.diagnosis or recovery.diagnose(response.result.stderr)).text())
                self._append("ICODA purpose comments", answer)
                if skipped:
                    self._append("ICODA", "Left these files unchanged because they changed while the LLM was "
                                 "working or the returned edits were not documentation only:\n" +
                                 "\n".join(sorted(set(skipped))))
                if changed:
                    self._refresh_after_edits(project)
            self._controls()
            self.window.root.after(0, self.ensure_purpose_comments)

        self.window.run_async(lambda: documentation.complete(project, files, invoke), done)

    def send(self, message: str | None = None) -> None:
        if self.busy or self.window.panel.busy or self.cwd is None:
            return
        from_input = message is None
        message = self.input.get("1.0", "end").strip() if message is None else message
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
        if from_input:
            self.input.delete("1.0", "end")
        self.history.append(("Developer", message))
        self._append("You", message)
        cwd = self.cwd
        assert cwd is not None
        request = recovery.conversation_prompt(self.issue, self.history, cwd, writable=True)
        token = self.generation
        changed = False
        self._set_busy(True)

        def work() -> recovery.RecoveryResult:
            nonlocal changed
            before = source_watch.snapshot_project(cwd)
            try:
                return recovery.invoke(
                    provider, selection.model or provider.default_model, request, cwd, binary=selection.binary,
                    timeout=1800, cancelled=lambda: self.cancelled, writable=True)
            finally:
                after = source_watch.snapshot_project(cwd)
                changed = before is None or after is None or bool(source_watch.changed_files(before, after))

        def done(result: Any) -> None:
            if token != self.generation:
                return
            self._set_busy(False)
            # A failed or cancelled request can still have made changes before it stopped.
            if changed:
                self._refresh_after_edits(cwd)
            if self.cancelled or isinstance(result, steps.StepCancelled):
                self._append("ICODA", "Conversation request cancelled.")
                return
            if isinstance(result, Exception):
                tasks.completion_ping(self.window.root)
                self.issue = recovery.diagnose(str(result))
                self._append("ICODA", self.issue.text())
                self._controls()
                return
            if result.result.cancelled:
                self._append("ICODA", "Conversation request cancelled.")
                return
            tasks.completion_ping(self.window.root)
            if result.result.ok:
                answer = result.result.stdout
            else:
                self.issue = result.diagnosis or recovery.diagnose(result.result.stderr or result.result.stdout)
                answer = self.issue.text()
            self.history.append(("Assistant", answer))
            self._append(provider.label, answer)
            self._controls()

        self.window.run_async(work, done)

    def _refresh_after_edits(self, cwd: Path) -> None:
        editor = self.window.source_editor
        document = editor.document
        if document is not None and document.root == cwd.resolve() and not editor.dirty:
            if document.path.is_file():
                editor.refresh()
            else:
                editor.clear()
        self.window._source_changed(cwd.resolve())

    def retry_step(self) -> None:
        if self.busy or self.window.panel.busy or self.retry is None or self.project != self.window.project:
            return
        selection = self.provider.selection()
        self.window.provider_field.set(selection.binary, selection.model)
        self.window.steps._ensure_runner()  # retries may close over the existing runner
        self.retry()

    def open_cli(self) -> None:
        if self.busy or self.window.panel.busy or self.cwd is None:
            return
        selection = self.provider.selection()
        if not selection.provider_id:
            self._append("ICODA", "Select an enabled Binary first.")
            return
        provider = agent.find_provider(agent.load_providers(), selection.provider_id)
        if not provider.enabled:
            self._append("ICODA", "This provider is disabled. Choose an enabled provider.")
            return
        history = list(self.history)
        draft = self.input.get("1.0", "end").strip()
        if draft:
            history.append(("Developer", draft))
        context = recovery.conversation_prompt(self.issue, history, self.cwd, interactive=True)
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
            self._append("ICODA", "Opened the interactive CLI. " + (
                "After the fix, return here and Retry step to run the checks again." if self.retry is not None
                else "Return here when you are ready to continue in ICODA."))
        self.window.run_async(work, done)

    def details(self) -> None:
        if self.issue is not None:
            self._append("Error evidence", self.issue.detail)
