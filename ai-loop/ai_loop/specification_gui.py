"""Tk presenter for the formal-specification draft workflow.

The module deliberately keeps conversion and parsing helpers independent of
Tk so they can be imported and tested on machines without a display.  The
authoritative persistence, validation, integrity, and lifecycle rules remain
in :mod:`ai_loop.specifications` and :mod:`ai_loop.specification_workflow`.
"""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

try:  # Importing this module must remain safe in headless/minimal environments.
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except (ImportError, RuntimeError):  # pragma: no cover - platform dependent
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    filedialog = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]

from ai_loop.elicitation import (
    CompletedElicitation,
    ElicitationEngine,
    StructuredOutputProvider,
    apply_elicitation_analysis,
)
from ai_loop.specification_workflow import (
    EDITOR_STAGES,
    StageAssessment,
    WorkflowIssue,
    approve,
    assess_specification,
    create_draft,
    return_to_draft,
    save_draft,
    submit_for_review,
)
from ai_loop.specifications import (
    SpecificationDocument,
    SpecificationService,
    StoredSpecificationVersion,
)
from ai_loop.specification_gui_support import (
    FieldSemanticFeedback,
    MetricAssertionParseError,
    PROCESS_OVERVIEW_TEXT,
    SPECIFICATION_FIELD_EXAMPLES,
    SPECIFICATION_FIELD_GUIDANCE,
    SPECIFICATION_SAVEFILE_SCHEMA,
    SPECIFICATION_SAVEFILE_VERSION,
    SpecificationSavefileError,
    SpecificationSuggestion,
    StructuredRecordParseError,
    USE_CASE_FIELDS,
    REQUIREMENT_FIELDS,
    RISK_FIELDS,
    DECISION_FIELDS,
    VERIFICATION_FIELDS,
    _Field,
    _field_guidance,
    analyze_specification,
    analyze_specification_suggestions,
    compute_field_feedback,
    document_to_record,
    format_list_text,
    format_metric_assertions,
    format_structured_records,
    issues_by_tab,
    model_to_record,
    parse_list_text,
    parse_metric_assertions,
    parse_structured_records,
    record_to_document,
    record_to_model,
    render_choice_summary,
    render_specification_json_diff,
    route_issues_to_tabs,
    savefile_to_record,
    specification_to_savefile_bytes,
    worked_example_document,
)


def _verification_for_dialog(record: Mapping[str, Any] | None) -> dict[str, Any]:
    result = copy.deepcopy(dict(record or {}))
    loop = result.pop("validation_loop", {})
    result.update(loop)
    result["metric_assertions"] = format_metric_assertions(result.get("metric_assertions", ()))
    result["coverage_targets"] = format_structured_records(
        result.get("coverage_targets", ())
    )
    result["required_evidence"] = format_structured_records(
        result.get("required_evidence", ())
    )
    return result


def _verification_from_dialog(record: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(record))
    if isinstance(result.get("metric_assertions"), str):
        result["metric_assertions"] = [
            item.__dict__ for item in parse_metric_assertions(result["metric_assertions"])
        ]
    for key in ("coverage_targets", "required_evidence"):
        if isinstance(result.get(key), str):
            result[key] = list(parse_structured_records(result[key]))
    loop_keys = (
        "maximum_correction_attempts",
        "repetitions_per_attempt",
        "stagnation_limit",
        "escalation_condition",
        "retain_evidence",
    )
    result["validation_loop"] = {key: result.pop(key) for key in loop_keys}
    result["command_override"] = result.get("command_override") or None
    return result


class _RecordDialog:
    """Scrollable record dialog with lossless nested verification records."""

    def __init__(
        self,
        parent: Any,
        title: str,
        fields: Sequence[_Field],
        initial: Mapping[str, Any] | None = None,
        *,
        field_path_prefix: str | None = None,
        feedback_provider: (
            Callable[[Mapping[str, Any]], Mapping[str, FieldSemanticFeedback]] | None
        ) = None,
    ) -> None:
        assert tk is not None and ttk is not None
        self.result: dict[str, Any] | None = None
        self._feedback_provider = feedback_provider
        self._feedback_after_id: str | None = None
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.geometry("720x700")
        self.window.minsize(520, 420)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)

        outer = ttk.Frame(self.window, padding=(10, 10, 10, 0))
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)
        canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        body = ttk.Frame(canvas, padding=(0, 0, 8, 8))
        body.columnconfigure(1, weight=1)
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_id, width=event.width))

        initial_values = dict(initial or {})
        self._controls: dict[str, tuple[_Field, Any]] = {}
        self.guidance_labels: dict[str, Any] = {}
        self._guidance_text: dict[str, str] = {}
        row = 0
        current_group = ""
        for field in fields:
            if field.group != current_group:
                ttk.Separator(body).grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 5))
                row += 1
                ttk.Label(body, text=field.group).grid(row=row, column=0, columnspan=2, sticky="w")
                row += 1
                current_group = field.group
            label_frame = ttk.Frame(body)
            label_frame.grid(row=row, column=0, sticky="new", padx=(0, 12), pady=4)
            ttk.Label(label_frame, text=field.label).pack(anchor="w")
            guidance_key = (
                f"{field_path_prefix}.{field.key}" if field_path_prefix else ""
            )
            guidance = _field_guidance(guidance_key) if guidance_key else ""
            if guidance:
                guidance_label = ttk.Label(
                    label_frame,
                    text=guidance,
                    wraplength=245,
                    justify="left",
                )
                guidance_label.pack(anchor="w", pady=(2, 0))
                self.guidance_labels[field.key] = guidance_label
                self._guidance_text[field.key] = guidance
            value = initial_values.get(field.key, field.default)
            control: Any
            if field.kind in {"text", "list", "metrics", "records"}:
                control = tk.Text(body, height=4 if field.kind == "text" else 5, wrap="word")
                if isinstance(value, str):
                    rendered = value
                elif field.kind == "metrics":
                    rendered = format_metric_assertions(value or ())
                elif field.kind == "records":
                    rendered = format_structured_records(value or ())
                else:
                    rendered = format_list_text(value or ())
                control.insert("1.0", rendered)
            elif field.kind == "enum":
                variable = tk.StringVar(value=str(value or field.default))
                control = ttk.Combobox(
                    body, textvariable=variable, values=field.values, state="readonly"
                )
            elif field.kind == "bool":
                variable = tk.BooleanVar(value=bool(value))
                control = ttk.Checkbutton(body, variable=variable)
            elif field.kind == "positive_int":
                variable = tk.IntVar(value=int(value or field.default))
                control = ttk.Spinbox(body, from_=1, to=1_000_000, textvariable=variable)
            else:
                variable = tk.StringVar(value="" if value is None else str(value))
                control = ttk.Entry(body, textvariable=variable)
            control.grid(row=row, column=1, sticky="ew", pady=4)
            self._controls[field.key] = (field, control)
            row += 1

        if self._feedback_provider is not None:
            self.window.bind("<KeyRelease>", self._schedule_feedback, add="+")
            self.window.bind("<<ComboboxSelected>>", self._schedule_feedback, add="+")
            self.window.bind("<ButtonRelease-1>", self._schedule_feedback, add="+")
            for field, control in self._controls.values():
                if field.kind in {"text", "list", "metrics", "records"}:
                    control.edit_modified(False)
                    control.bind("<<Modified>>", self._on_text_modified, add="+")

        actions = ttk.Frame(self.window, padding=10)
        actions.grid(row=1, column=0, sticky="ew")
        ttk.Button(actions, text="Cancel", command=self.window.destroy).pack(side="right")
        ttk.Button(actions, text="Apply", command=self._accept).pack(side="right", padx=(0, 8))
        self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)
        self._refresh_feedback()

    def _collect_values(self) -> tuple[dict[str, Any], dict[str, str]]:
        result: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for key, (field, control) in self._controls.items():
            try:
                if field.kind in {"text", "list", "metrics", "records"}:
                    value: Any = control.get("1.0", "end-1c")
                    if field.kind == "list":
                        value = list(parse_list_text(value))
                    elif field.kind == "metrics":
                        value = [item.__dict__ for item in parse_metric_assertions(value)]
                    elif field.kind == "records":
                        value = list(parse_structured_records(value))
                elif field.kind == "positive_int":
                    value = int(control.get())
                    if value <= 0:
                        raise ValueError(f"{field.label} must be positive")
                elif field.kind == "bool":
                    raw = control.getvar(control.cget("variable"))
                    value = str(raw).lower() in {"1", "true", "yes", "on"}
                else:
                    value = control.get()
                result[key] = value
            except (ValueError, tk.TclError) as exc:
                errors[key] = str(exc)
        return result, errors

    def _schedule_feedback(self, _event: Any = None) -> None:
        if self._feedback_provider is None:
            return
        if self._feedback_after_id is not None:
            try:
                self.window.after_cancel(self._feedback_after_id)
            except tk.TclError:
                pass
        self._feedback_after_id = self.window.after(100, self._finish_scheduled_feedback)

    def _on_text_modified(self, event: Any) -> None:
        if event.widget.edit_modified():
            event.widget.edit_modified(False)
            self._schedule_feedback(event)

    def _finish_scheduled_feedback(self) -> None:
        self._feedback_after_id = None
        self._refresh_feedback()

    def _refresh_feedback(self) -> None:
        if self._feedback_provider is None:
            return
        values, errors = self._collect_values()
        feedback = self._feedback_provider(values) if not errors else {}
        for key, label in self.guidance_labels.items():
            if key in errors:
                message = f"Needs attention — {errors[key]}"
            elif key in feedback:
                message = feedback[key].message
            else:
                message = "Waiting for the other record fields to become valid."
            label.configure(text=f"{self._guidance_text[key]}\n\nLive feedback: {message}")

    def _accept(self) -> None:
        result, errors = self._collect_values()
        if errors:
            assert messagebox is not None
            messagebox.showerror(
                "Invalid record",
                next(iter(errors.values())),
                parent=self.window,
            )
            return
        self.result = result
        self.window.destroy()

    def show(self) -> dict[str, Any] | None:
        self.window.wait_window()
        return self.result


class _SpecificationSuggestionsDialog:
    """Modal, scrollable presentation of a read-only holistic draft test."""

    def __init__(
        self,
        parent: Any,
        suggestions: Sequence[SpecificationSuggestion],
    ) -> None:
        assert tk is not None and ttk is not None
        self.window = tk.Toplevel(parent)
        self.window.title("Specification test results")
        self.window.geometry("860x620")
        self.window.minsize(600, 400)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        blocking_count = sum(item.severity == "blocking" for item in suggestions)
        ttk.Label(
            self.window,
            text=(
                f"Holistic review of the current draft: {blocking_count} blocking issue(s). "
                "Suggestions are ordered by completion risk, then verification traceability "
                "and runtime proof, then advisory polish. Nothing was changed."
            ),
            wraplength=820,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        frame = ttk.Frame(self.window)
        frame.grid(row=1, column=0, sticky="nsew", padx=10)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        results = tk.Text(frame, wrap="word", undo=False)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=results.yview)
        results.configure(yscrollcommand=scrollbar.set)
        results.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        rendered = []
        for index, suggestion in enumerate(suggestions, 1):
            rendered.append(
                f"{index}. [{suggestion.severity.upper()}] "
                f"{suggestion.tab} · {suggestion.field}\n{suggestion.message}"
            )
        results.insert("1.0", "\n\n".join(rendered))
        results.configure(state="disabled")
        self.results_text = results

        actions = ttk.Frame(self.window, padding=10)
        actions.grid(row=2, column=0, sticky="ew")
        ttk.Button(actions, text="Close", command=self.window.destroy).pack(side="right")
        self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)

    def show(self) -> None:
        self.window.wait_window()


class _ElicitationReviewDialog:
    """Modal review that keeps JSON additions and unresolved choices distinct."""

    def __init__(
        self,
        parent: Any,
        *,
        completed: CompletedElicitation,
        source: StoredSpecificationVersion,
    ) -> None:
        assert tk is not None and ttk is not None
        self.result: str | None = None
        self.window = tk.Toplevel(parent)
        self.window.title("Review AI Specification Analysis")
        self.window.geometry("1040x780")
        self.window.minsize(700, 500)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        summary_frame = ttk.LabelFrame(self.window, text="Analysis summary", padding=8)
        summary_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        summary_frame.columnconfigure(0, weight=1)
        ttk.Label(
            summary_frame,
            text=completed.result.summary,
            wraplength=950,
            justify="left",
        ).grid(row=0, column=0, sticky="ew")
        if completed.result.warnings:
            ttk.Label(
                summary_frame,
                text="Warnings:\n" + "\n".join(f"• {item}" for item in completed.result.warnings),
                wraplength=950,
                justify="left",
            ).grid(row=1, column=0, sticky="ew", pady=(6, 0))

        notebook = ttk.Notebook(self.window)
        notebook.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        diff_frame = ttk.Frame(notebook, padding=7)
        choices_frame = ttk.Frame(notebook, padding=7)
        notebook.add(diff_frame, text="Exact JSON Diff")
        notebook.add(choices_frame, text=f"Proposed Choices ({len(completed.result.choices)})")
        for frame in (diff_frame, choices_frame):
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(1, weight=1)

        diff = render_specification_json_diff(
            source.document,
            completed.result.suggested_specification,
            source_label=f"{source.specification_id}-v{source.version}-stored.json",
            suggestion_label=f"{completed.stored.analysis_id}-suggested.json",
        )
        ttk.Label(
            diff_frame,
            text=(
                "Unified diff of the exact stored draft JSON and the complete additive suggestion."
                if diff
                else "The analysis proposed no specification-field additions."
            ),
        ).grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.diff_text = self._readonly_text(diff_frame, diff, wrap="none")

        ttk.Label(
            choices_frame,
            text=(
                "These are unresolved proposals. Recommendations are not materialized decisions."
            ),
        ).grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.choice_text = self._readonly_text(
            choices_frame,
            render_choice_summary(completed.result.choices),
            wrap="word",
        )

        actions = ttk.Frame(self.window, padding=10)
        actions.grid(row=2, column=0, sticky="ew")
        ttk.Button(actions, text="Cancel", command=self._cancel).pack(side="right")
        ttk.Button(
            actions,
            text="Apply All",
            command=lambda: self._choose("apply_all"),
        ).pack(side="right", padx=(0, 7))
        ttk.Button(
            actions,
            text="Choices Only",
            command=lambda: self._choose("choices_only"),
        ).pack(side="right", padx=(0, 7))
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)

    @staticmethod
    def _readonly_text(parent: Any, value: str, *, wrap: str) -> Any:
        assert tk is not None and ttk is not None
        frame = ttk.Frame(parent)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        text_widget = tk.Text(frame, wrap=wrap, undo=False)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=vertical.set)
        text_widget.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        if wrap == "none":
            horizontal = ttk.Scrollbar(frame, orient="horizontal", command=text_widget.xview)
            text_widget.configure(xscrollcommand=horizontal.set)
            horizontal.grid(row=1, column=0, sticky="ew")
        text_widget.insert("1.0", value)
        text_widget.configure(state="disabled")
        return text_widget

    def _choose(self, action: str) -> None:
        self.result = action
        self.window.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.window.destroy()

    def show(self) -> str | None:
        self.window.wait_window()
        return self.result


class VerificationDashboardView:
    """Tk-only renderer for GUI-neutral formal verification dashboard rows."""

    def __init__(
        self,
        parent: Any,
        *,
        refresh_command: Callable[[], None],
        acknowledge_command: Callable[[str, str, str], None],
        default_actor: str,
    ) -> None:
        if tk is None or ttk is None or messagebox is None:
            raise RuntimeError("Tkinter is not available; the verification dashboard cannot open")
        self.frame = ttk.Frame(parent, padding=7)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        self._refresh_command = refresh_command
        self._acknowledge_command = acknowledge_command
        self._rows: dict[str, Mapping[str, Any]] = {}
        self._selected_repetitions: dict[str, Mapping[str, Any]] = {}
        self._selected_evidence: dict[str, Mapping[str, Any]] = {}

        bar = ttk.Frame(self.frame)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        bar.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Select a formal job to inspect verification.")
        ttk.Label(bar, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.refresh_button = ttk.Button(bar, text="Refresh", command=refresh_command)
        self.refresh_button.grid(row=0, column=1, sticky="e")

        split = ttk.PanedWindow(self.frame, orient="vertical")
        split.grid(row=1, column=0, sticky="nsew")
        cases_frame = ttk.LabelFrame(split, text="Formal verification cases", padding=5)
        details_frame = ttk.Frame(split)
        split.add(cases_frame, weight=3)
        split.add(details_frame, weight=4)

        cases_frame.columnconfigure(0, weight=1)
        cases_frame.rowconfigure(0, weight=1)
        case_columns = (
            "title",
            "requirements",
            "blocking",
            "automation",
            "realization",
            "runtime",
            "attempts",
            "repetitions",
            "metrics",
            "failed",
            "stagnation",
            "escalation",
        )
        self.case_tree = ttk.Treeview(
            cases_frame,
            columns=case_columns,
            show="tree headings",
            selectmode="browse",
        )
        self.case_tree.heading("#0", text="Verification ID")
        self.case_tree.column("#0", width=105, stretch=False)
        widths = {
            "title": 190,
            "requirements": 120,
            "blocking": 70,
            "automation": 90,
            "realization": 155,
            "runtime": 155,
            "attempts": 65,
            "repetitions": 85,
            "metrics": 150,
            "failed": 150,
            "stagnation": 95,
            "escalation": 85,
        }
        for column in case_columns:
            self.case_tree.heading(column, text=column.replace("_", " ").title())
            self.case_tree.column(column, width=widths[column], stretch=column == "title")
        case_y = ttk.Scrollbar(cases_frame, orient="vertical", command=self.case_tree.yview)
        case_x = ttk.Scrollbar(cases_frame, orient="horizontal", command=self.case_tree.xview)
        self.case_tree.configure(yscrollcommand=case_y.set, xscrollcommand=case_x.set)
        self.case_tree.grid(row=0, column=0, sticky="nsew")
        case_y.grid(row=0, column=1, sticky="ns")
        case_x.grid(row=1, column=0, sticky="ew")
        self.case_tree.bind("<<TreeviewSelect>>", self._on_case_selected)

        details_frame.columnconfigure(0, weight=1)
        details_frame.rowconfigure(0, weight=1)
        self.detail_notebook = ttk.Notebook(details_frame)
        self.detail_notebook.grid(row=0, column=0, sticky="nsew")
        contract_tab = ttk.Frame(self.detail_notebook, padding=5)
        attempts_tab = ttk.Frame(self.detail_notebook, padding=5)
        notes_tab = ttk.Frame(self.detail_notebook, padding=5)
        self.detail_notebook.add(contract_tab, text="Contract enforcement")
        self.detail_notebook.add(attempts_tab, text="Attempts and retained evidence")
        self.detail_notebook.add(notes_tab, text="Manual acknowledgements")
        self._build_contract_tab(contract_tab)
        self._build_attempts_tab(attempts_tab)
        self._build_notes_tab(notes_tab, default_actor)

    @staticmethod
    def _compact(value: Any, *, limit: int = 120) -> str:
        if value in (None, "", [], {}):
            return "—"
        if isinstance(value, Mapping):
            text = ", ".join(f"{key}={item}" for key, item in value.items())
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            text = ", ".join(str(item.get("metric") if isinstance(item, Mapping) else item) for item in value)
        else:
            text = str(value)
        return text if len(text) <= limit else text[: limit - 1] + "…"

    @staticmethod
    def _readonly_text(parent: Any, *, height: int = 8) -> Any:
        widget = tk.Text(parent, height=height, wrap="word", undo=False)
        widget.configure(state="disabled")
        return widget

    @staticmethod
    def _set_text(widget: Any, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _build_contract_tab(self, tab: Any) -> None:
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        ttk.Label(
            tab,
            text=(
                "DESCRIPTIVE means prose only; REALIZED means infrastructure exists; "
                "MACHINE-ENFORCED means the runtime evaluator consumed emitted evidence."
            ),
            wraplength=1000,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.contract_tree = ttk.Treeview(
            tab,
            columns=("name", "enforcement", "description", "runtime"),
            show="tree headings",
        )
        self.contract_tree.heading("#0", text="Contract type")
        self.contract_tree.column("#0", width=145, stretch=False)
        for column, width in (
            ("name", 190),
            ("enforcement", 145),
            ("description", 440),
            ("runtime", 240),
        ):
            self.contract_tree.heading(column, text=column.title())
            self.contract_tree.column(column, width=width, stretch=column == "description")
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.contract_tree.yview)
        self.contract_tree.configure(yscrollcommand=scrollbar.set)
        self.contract_tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

    def _build_attempts_tab(self, tab: Any) -> None:
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        split = ttk.PanedWindow(tab, orient="horizontal")
        split.grid(row=0, column=0, sticky="nsew")
        history = ttk.LabelFrame(split, text="Repetitions", padding=5)
        inspection = ttk.LabelFrame(split, text="Selected repetition", padding=5)
        split.add(history, weight=2)
        split.add(inspection, weight=3)
        history.columnconfigure(0, weight=1)
        history.rowconfigure(0, weight=1)
        self.repetition_tree = ttk.Treeview(
            history,
            columns=("attempt", "repetition", "status", "return", "elapsed", "task", "run"),
            show="headings",
            selectmode="browse",
        )
        for column, width in (
            ("attempt", 55),
            ("repetition", 70),
            ("status", 95),
            ("return", 55),
            ("elapsed", 65),
            ("task", 105),
            ("run", 105),
        ):
            self.repetition_tree.heading(column, text=column.title())
            self.repetition_tree.column(column, width=width, stretch=False)
        repetition_scroll = ttk.Scrollbar(history, orient="vertical", command=self.repetition_tree.yview)
        self.repetition_tree.configure(yscrollcommand=repetition_scroll.set)
        self.repetition_tree.grid(row=0, column=0, sticky="nsew")
        repetition_scroll.grid(row=0, column=1, sticky="ns")
        self.repetition_tree.bind("<<TreeviewSelect>>", self._on_repetition_selected)

        inspection.columnconfigure(0, weight=1)
        inspection.rowconfigure(1, weight=1)
        inspection.rowconfigure(3, weight=1)
        ttk.Label(inspection, text="Bounded output and assertion details").grid(row=0, column=0, sticky="w")
        self.repetition_text = self._readonly_text(inspection, height=7)
        self.repetition_text.grid(row=1, column=0, sticky="nsew", pady=(3, 6))
        evidence_bar = ttk.Frame(inspection)
        evidence_bar.grid(row=2, column=0, sticky="ew")
        ttk.Label(evidence_bar, text="Retained evidence (binary/large content is metadata-only)").pack(side="left")
        self.preview_button = ttk.Button(
            evidence_bar,
            text="Open bounded text preview",
            command=self.open_selected_evidence_preview,
            state="disabled",
        )
        self.preview_button.pack(side="right")
        self.evidence_tree = ttk.Treeview(
            inspection,
            columns=("kind", "media", "size", "path", "sha256"),
            show="tree headings",
            selectmode="browse",
        )
        self.evidence_tree.heading("#0", text="Name")
        self.evidence_tree.column("#0", width=130, stretch=False)
        for column, width in (
            ("kind", 110),
            ("media", 135),
            ("size", 80),
            ("path", 260),
            ("sha256", 260),
        ):
            self.evidence_tree.heading(column, text=column.title())
            self.evidence_tree.column(column, width=width, stretch=column == "path")
        evidence_y = ttk.Scrollbar(inspection, orient="vertical", command=self.evidence_tree.yview)
        evidence_x = ttk.Scrollbar(inspection, orient="horizontal", command=self.evidence_tree.xview)
        self.evidence_tree.configure(yscrollcommand=evidence_y.set, xscrollcommand=evidence_x.set)
        self.evidence_tree.grid(row=3, column=0, sticky="nsew", pady=(3, 0))
        evidence_y.grid(row=3, column=1, sticky="ns")
        evidence_x.grid(row=4, column=0, sticky="ew")
        self.evidence_tree.bind("<<TreeviewSelect>>", self._on_evidence_selected)

    def _build_notes_tab(self, tab: Any, default_actor: str) -> None:
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        self.manual_note_status_var = tk.StringVar(
            value="Manual notes are available only for a selected non-blocking manual case."
        )
        ttk.Label(tab, textvariable=self.manual_note_status_var, wraplength=1000).grid(
            row=0, column=0, sticky="ew", pady=(0, 5)
        )
        self.ack_tree = ttk.Treeview(
            tab,
            columns=("who", "when", "note"),
            show="headings",
        )
        for column, width in (("who", 150), ("when", 180), ("note", 650)):
            self.ack_tree.heading(column, text=column.title())
            self.ack_tree.column(column, width=width, stretch=column == "note")
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.ack_tree.yview)
        self.ack_tree.configure(yscrollcommand=scrollbar.set)
        self.ack_tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        controls = ttk.Frame(tab)
        controls.grid(row=2, column=0, sticky="ew", pady=(7, 0))
        controls.columnconfigure(3, weight=1)
        ttk.Label(controls, text="Who").grid(row=0, column=0, sticky="w")
        self.ack_actor_var = tk.StringVar(value=default_actor)
        self.ack_actor_entry = ttk.Entry(controls, textvariable=self.ack_actor_var, width=18)
        self.ack_actor_entry.grid(row=0, column=1, sticky="ew", padx=(4, 10))
        ttk.Label(controls, text="Note").grid(row=0, column=2, sticky="w")
        self.ack_note_var = tk.StringVar()
        self.ack_note_entry = ttk.Entry(controls, textvariable=self.ack_note_var)
        self.ack_note_entry.grid(row=0, column=3, sticky="ew", padx=4)
        self.ack_button = ttk.Button(
            controls,
            text="Record manual acknowledgement",
            command=self._record_manual_acknowledgement,
            state="disabled",
        )
        self.ack_button.grid(row=0, column=4, sticky="e", padx=(6, 0))

    def set_loading(self, loading: bool, message: str | None = None) -> None:
        self.refresh_button.configure(state="disabled" if loading else "normal")
        if message:
            self.status_var.set(message)
        if loading:
            self.ack_button.configure(state="disabled")
        else:
            self._update_manual_controls()

    def clear(self, message: str = "Select a formal job to inspect verification.") -> None:
        self._rows.clear()
        self._selected_repetitions.clear()
        self._selected_evidence.clear()
        for tree in (self.case_tree, self.contract_tree, self.repetition_tree, self.evidence_tree, self.ack_tree):
            tree.delete(*tree.get_children())
        self._set_text(self.repetition_text, "")
        self.preview_button.configure(state="disabled")
        self.status_var.set(message)
        self.manual_note_status_var.set(
            "Manual notes are available only for a selected non-blocking manual case."
        )
        self._update_manual_controls()

    def show_rows(self, job_id: str, rows: Sequence[Mapping[str, Any]]) -> None:
        selected = self.case_tree.focus()
        self.clear(f"Formal job {job_id}: {len(rows)} verification case(s)")
        self._rows = {str(row["verification_id"]): row for row in rows}
        for verification_id, row in self._rows.items():
            escalation = "YES" if row.get("escalation") else "no"
            self.case_tree.insert(
                "",
                "end",
                iid=verification_id,
                text=verification_id,
                values=(
                    row.get("title"),
                    ", ".join(row.get("requirement_ids") or []),
                    "yes" if row.get("blocking") else "no",
                    row.get("automation"),
                    row.get("realization_state"),
                    row.get("runtime_status"),
                    row.get("attempt_count"),
                    f"{row.get('repetitions')}/{row.get('repetitions_per_attempt')}",
                    self._compact(row.get("latest_metrics")),
                    self._compact(row.get("failed_assertions")),
                    f"{row.get('stagnation_count')}/{row.get('stagnation_series')}",
                    escalation,
                ),
            )
        target = selected if selected in self._rows else next(iter(self._rows), "")
        if target:
            self.case_tree.selection_set(target)
            self.case_tree.focus(target)
            self._render_case(self._rows[target])

    def _on_case_selected(self, _event: Any) -> None:
        verification_id = self.case_tree.focus()
        row = self._rows.get(verification_id)
        if row is not None:
            self._render_case(row)

    def _render_case(self, row: Mapping[str, Any]) -> None:
        self.contract_tree.delete(*self.contract_tree.get_children())
        contracts = row.get("contracts") or {}
        for group, label in (
            ("oracle", "Oracle"),
            ("coverage_targets", "Coverage target"),
            ("evidence_requirements", "Evidence requirement"),
        ):
            for index, item in enumerate(contracts.get(group, []), 1):
                runtime = item.get("runtime") if isinstance(item, Mapping) else None
                self.contract_tree.insert(
                    "",
                    "end",
                    text=label,
                    values=(
                        item.get("name"),
                        item.get("enforcement"),
                        item.get("description"),
                        self._compact(runtime, limit=220),
                    ),
                )

        self.repetition_tree.delete(*self.repetition_tree.get_children())
        self._selected_repetitions.clear()
        for attempt in row.get("attempts", []):
            for repetition in attempt.get("repetitions", []):
                iid = f"{repetition.get('record_id')}-{attempt.get('attempt')}-{repetition.get('repetition')}"
                self._selected_repetitions[iid] = repetition
                self.repetition_tree.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        attempt.get("attempt"),
                        repetition.get("repetition"),
                        repetition.get("status"),
                        repetition.get("return_code"),
                        repetition.get("elapsed_seconds"),
                        repetition.get("task_id"),
                        repetition.get("worker_run_id"),
                    ),
                )
        self._set_text(self.repetition_text, "No retained repetition is selected.")
        self.evidence_tree.delete(*self.evidence_tree.get_children())
        self._selected_evidence.clear()
        self.preview_button.configure(state="disabled")

        self.ack_tree.delete(*self.ack_tree.get_children())
        for item in row.get("manual_acknowledgements", []):
            self.ack_tree.insert(
                "",
                "end",
                values=(item.get("acknowledged_by"), item.get("created_at"), item.get("note")),
            )
        self._update_manual_controls()

    def _on_repetition_selected(self, _event: Any) -> None:
        repetition = self._selected_repetitions.get(self.repetition_tree.focus())
        if repetition is None:
            return
        details = [
            f"Status: {repetition.get('status')}",
            f"Return code: {repetition.get('return_code')}",
            f"Command: {repetition.get('command')}",
            f"Working directory: {repetition.get('working_directory')}",
            f"Timeout: {repetition.get('timeout_seconds')} seconds",
            f"Metrics: {repetition.get('metrics')}",
            f"Assertions: {repetition.get('assertion_results')}",
            f"Error: {repetition.get('error') or '—'}",
            f"Termination: {repetition.get('termination_details') or '—'}",
            "",
            "Bounded output preview" + (" (truncated)" if repetition.get("output_preview_truncated") else ""),
            str(repetition.get("output_preview") or ""),
        ]
        self._set_text(self.repetition_text, "\n".join(details))
        self.evidence_tree.delete(*self.evidence_tree.get_children())
        self._selected_evidence.clear()
        for index, evidence in enumerate(repetition.get("evidence", []), 1):
            iid = f"evidence-{index}"
            self._selected_evidence[iid] = evidence
            self.evidence_tree.insert(
                "",
                "end",
                iid=iid,
                text=evidence.get("name"),
                values=(
                    evidence.get("kind"),
                    evidence.get("media_type"),
                    evidence.get("size"),
                    evidence.get("artifact_path") or "inline structured value",
                    evidence.get("sha256"),
                ),
            )
        self.preview_button.configure(state="disabled")

    def _on_evidence_selected(self, _event: Any) -> None:
        evidence = self._selected_evidence.get(self.evidence_tree.focus())
        self.preview_button.configure(
            state="normal" if evidence and evidence.get("preview_available") else "disabled"
        )

    def open_selected_evidence_preview(self) -> None:
        evidence = self._selected_evidence.get(self.evidence_tree.focus())
        if evidence is None or not evidence.get("preview_available"):
            messagebox.showinfo(
                "Evidence preview",
                "This artifact is binary or has no bounded text preview. Use the displayed path and SHA-256 metadata.",
                parent=self.frame.winfo_toplevel(),
            )
            return
        window = tk.Toplevel(self.frame)
        window.title(f"Bounded evidence preview — {evidence.get('name')}")
        window.geometry("820x560")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        ttk.Label(
            window,
            text=(
                f"Path: {evidence.get('artifact_path') or 'inline'}\n"
                f"SHA-256: {evidence.get('sha256')}\n"
                f"Size: {evidence.get('size')} bytes"
            ),
        ).grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        preview = self._readonly_text(window, height=20)
        preview.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        suffix = "\n\n[Preview truncated by AI-Loop.]" if evidence.get("preview_truncated") else ""
        self._set_text(preview, str(evidence.get("text_preview") or "") + suffix)

    def _update_manual_controls(self) -> None:
        row = self._rows.get(self.case_tree.focus())
        allowed = bool(row and row.get("can_acknowledge_manual"))
        state = "normal" if allowed else "disabled"
        for widget in (self.ack_actor_entry, self.ack_note_entry, self.ack_button):
            widget.configure(state=state)
        if allowed:
            self.manual_note_status_var.set(
                "This append-only acknowledgement records who/when/note. It does not mark the case passed and does not change manual_pending."
            )
        elif row is not None:
            self.manual_note_status_var.set(
                "Acknowledgement is disabled: automated and blocking cases can only advance through trusted runtime evidence."
            )

    def _record_manual_acknowledgement(self) -> None:
        row = self._rows.get(self.case_tree.focus())
        if row is None or not row.get("can_acknowledge_manual"):
            messagebox.showerror(
                "Manual acknowledgement",
                "Only a non-blocking manual case can receive an acknowledgement note.",
                parent=self.frame.winfo_toplevel(),
            )
            return
        actor = self.ack_actor_var.get().strip()
        note = self.ack_note_var.get().strip()
        if not actor or not note:
            messagebox.showerror(
                "Manual acknowledgement",
                "Enter both who acknowledged the case and an audit note.",
                parent=self.frame.winfo_toplevel(),
            )
            return
        self._acknowledge_command(str(row["verification_id"]), actor, note)


class SpecificationEditor:
    """Resizable staged editor delegating all durable actions to the service."""

    def __init__(
        self,
        parent: Any,
        *,
        service: SpecificationService,
        repository_path: str | Path,
        initial_goal: str = "",
        creator: str = "gui-user",
        run_background: Callable[..., None] | None = None,
        elicitation_provider_factory: Callable[[], StructuredOutputProvider] | None = None,
        implementation_work_factory: (
            Callable[[StoredSpecificationVersion], Callable[[], str]] | None
        ) = None,
        on_implementation_started: Callable[[str], None] | None = None,
        on_close: Callable[[SpecificationEditor], None] | None = None,
        embedded: bool = False,
    ) -> None:
        if tk is None or ttk is None or filedialog is None or messagebox is None:
            raise RuntimeError("Tkinter is not available; the formal editor cannot be opened")
        self.parent = parent
        self.service = service
        self.repository_path = Path(repository_path).expanduser().resolve()
        self.creator = creator
        self._run_background = run_background
        self._elicitation_provider_factory = elicitation_provider_factory
        self._implementation_work_factory = implementation_work_factory
        self._on_implementation_started = on_implementation_started
        self._on_close_callback = on_close
        self._embedded = embedded
        self.snapshot: StoredSpecificationVersion | None = None
        self.suggested_choices: list[dict[str, Any]] = []
        self.record = document_to_record(
            SpecificationDocument.empty(summary=initial_goal if initial_goal else "")
        )
        self._busy = False
        self._implementation_job_id: str | None = None
        self._implementation_start_in_flight = False
        self._selector_rows: dict[str, dict[str, Any]] = {}
        self.guidance_labels: dict[str, Any] = {}
        self._guidance_text: dict[str, str] = {}

        self.window = parent if embedded else tk.Toplevel(parent)
        if not embedded:
            self.window.title("Formal Specification")
            self.window.geometry("1120x820")
            self.window.minsize(780, 560)
            self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        self._build_header()
        self._build_tabs()
        self._build_actions()
        self._load_record_into_widgets()
        self._assessment_after_id: str | None = None
        self.window.bind("<KeyRelease>", self._schedule_assessment, add="+")
        self.title_var.trace_add("write", self._schedule_assessment)
        for widget in (
            self.summary_text,
            self.objectives_text,
            self.stakeholders_text,
            *self.scope_widgets.values(),
            self.open_questions_text,
        ):
            widget.edit_modified(False)
            widget.bind("<<Modified>>", self._on_text_modified, add="+")
        self._refresh_assessment()
        self.refresh_specifications()

    def _build_header(self) -> None:
        header = ttk.Frame(self.window, padding=10)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Repository").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.repository_var = tk.StringVar(value=str(self.repository_path))
        ttk.Entry(header, textvariable=self.repository_var, state="readonly").grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Label(header, text="Open specification").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=(7, 0)
        )
        self.selector_var = tk.StringVar(value="New specification")
        self.selector = ttk.Combobox(
            header, textvariable=self.selector_var, state="readonly", values=("New specification",)
        )
        self.selector.grid(row=1, column=1, sticky="ew", pady=(7, 0))
        self.selector.bind("<<ComboboxSelected>>", self._on_selector_changed)
        file_actions = ttk.Frame(header)
        file_actions.grid(row=1, column=2, sticky="e", padx=(8, 0), pady=(7, 0))
        self.load_example_button = ttk.Button(
            file_actions,
            text="Load example",
            command=self.load_example,
        )
        self.load_example_button.pack(side="left")
        self.test_specification_button = ttk.Button(
            file_actions,
            text="Test specification",
            command=self.test_specification,
        )
        self.test_specification_button.pack(side="left", padx=(6, 0))
        self.save_specification_button = ttk.Button(
            file_actions,
            text="Save JSON",
            command=self.save_specification,
        )
        self.save_specification_button.pack(side="left", padx=(6, 0))
        self.load_specification_button = ttk.Button(
            file_actions,
            text="Load JSON",
            command=self.load_specification,
        )
        self.load_specification_button.pack(side="left", padx=(6, 0))
        self.status_var = tk.StringVar(value="New unsaved draft")
        self.status_label = ttk.Label(
            header,
            textvariable=self.status_var,
            justify="left",
        )
        self.status_label.grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(7, 0)
        )
        self._bind_responsive_wrap(self.status_label, header, margin=20)
        process_frame = ttk.LabelFrame(header, text="From specification to DONE", padding=7)
        process_frame.grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )
        process_frame.columnconfigure(0, weight=1)
        self.process_overview_label = ttk.Label(
            process_frame,
            text=PROCESS_OVERVIEW_TEXT,
            wraplength=1040,
            justify="left",
        )
        self.process_overview_label.grid(row=0, column=0, sticky="ew")
        self._bind_responsive_wrap(
            self.process_overview_label, process_frame, margin=20
        )

    def _build_tabs(self) -> None:
        self.notebook = ttk.Notebook(self.window)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=10)
        self.tabs: dict[str, Any] = {}
        self._stage_scroll_canvases: dict[str, Any] = {}
        for stage in EDITOR_STAGES:
            frame = ttk.Frame(self.notebook, padding=10)
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            self.notebook.add(frame, text=f"  {stage}")
            self.tabs[stage] = frame
        self._build_overview_tab()
        self._build_scope_tab()
        self._build_collection_tab("Use Cases", "use_cases", USE_CASE_FIELDS, ("id", "title"))
        self._build_collection_tab(
            "Requirements", "requirements", REQUIREMENT_FIELDS, ("id", "priority", "title")
        )
        self._build_collection_tab("Risks", "risks", RISK_FIELDS, ("id", "severity", "title"))
        self._build_collection_tab(
            "Verification", "verification", VERIFICATION_FIELDS, ("id", "automation", "title")
        )
        self._build_choices_tab()
        self._build_review_tab()

    @staticmethod
    def _responsive_wraplength(
        width: int, *, margin: int = 0, maximum: int = 1040
    ) -> int:
        """Return a readable label width that never exceeds its container."""

        return max(120, min(maximum, max(1, width - margin)))

    def _bind_responsive_wrap(
        self,
        label: Any,
        container: Any,
        *,
        margin: int = 0,
        maximum: int = 1040,
    ) -> None:
        """Keep a wrapping label fully visible when its tab is resized."""

        container.bind(
            "<Configure>",
            lambda event: label.configure(
                wraplength=self._responsive_wraplength(
                    int(event.width), margin=margin, maximum=maximum
                )
            ),
            add="+",
        )

    def _scrollable_stage_body(self, stage: str) -> Any:
        """Return a full-width vertically scrollable body for a form stage."""

        tab = self.tabs[stage]
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        canvas = tk.Canvas(tab, highlightthickness=0)
        vertical = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vertical.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        body = ttk.Frame(canvas, padding=(0, 0, 8, 0))
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
            add="+",
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(body_id, width=max(1, event.width)),
            add="+",
        )
        self._stage_scroll_canvases[stage] = canvas
        return body

    def _field_label(self, parent: Any, row: int, key: str, label: str) -> None:
        label_frame = ttk.Frame(parent)
        label_frame.grid(row=row, column=0, sticky="new", padx=(0, 12), pady=4)
        ttk.Label(label_frame, text=label).pack(anchor="w")
        guidance = ttk.Label(
            label_frame,
            text=_field_guidance(key),
            wraplength=260,
            justify="left",
        )
        guidance.pack(anchor="w", pady=(2, 0))
        self._bind_responsive_wrap(
            guidance, label_frame, margin=4, maximum=260
        )
        self.guidance_labels[key] = guidance
        self._guidance_text[key] = _field_guidance(key)

    def _labeled_text(
        self,
        parent: Any,
        row: int,
        key: str,
        label: str,
        *,
        height: int = 4,
    ) -> Any:
        self._field_label(parent, row, key, label)
        holder = ttk.Frame(parent)
        holder.grid(row=row, column=1, sticky="nsew", pady=4)
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        widget = tk.Text(holder, height=height, wrap="word")
        vertical = ttk.Scrollbar(holder, orient="vertical", command=widget.yview)
        widget.configure(yscrollcommand=vertical.set)
        widget.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        parent.rowconfigure(row, weight=1)
        return widget

    def _build_overview_tab(self) -> None:
        tab = self._scrollable_stage_body("Overview")
        tab.columnconfigure(1, weight=1)
        self._field_label(tab, 0, "title", "Title")
        self.title_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.title_var).grid(row=0, column=1, sticky="ew", pady=4)
        self.summary_text = self._labeled_text(tab, 1, "summary", "Summary", height=7)
        self.objectives_text = self._labeled_text(
            tab, 2, "objectives", "Objectives (one per line)"
        )
        self.stakeholders_text = self._labeled_text(
            tab, 3, "stakeholders", "Stakeholders (one per line)"
        )

    def _build_scope_tab(self) -> None:
        tab = self._scrollable_stage_body("Scope")
        tab.columnconfigure(1, weight=1)
        self.scope_widgets: dict[str, Any] = {}
        for row, (key, label) in enumerate(
            (
                ("in_scope", "Included scope"),
                ("out_of_scope", "Excluded scope"),
                ("assumptions", "Assumptions"),
                ("constraints", "Constraints"),
                ("dependencies", "Dependencies"),
            )
        ):
            self.scope_widgets[key] = self._labeled_text(
                tab, row, key, f"{label} (one per line)"
            )

    def _build_collection_tab(
        self,
        stage: str,
        key: str,
        fields: Sequence[_Field],
        columns: Sequence[str],
    ) -> None:
        tab = self.tabs[stage]
        tab.rowconfigure(0, weight=0)
        tab.rowconfigure(1, weight=1)
        guidance = ttk.Label(
            tab,
            text=_field_guidance(key),
            wraplength=1000,
            justify="left",
        )
        guidance.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._bind_responsive_wrap(guidance, tab, margin=20)
        self.guidance_labels[key] = guidance
        self._guidance_text[key] = _field_guidance(key)
        table_frame = ttk.Frame(tab)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(table_frame, columns=tuple(columns), show="headings", selectmode="browse")
        for column in columns:
            tree.heading(column, text=column.replace("_", " ").title())
            tree.column(column, width=130 if column != "title" else 300, stretch=True)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        actions = ttk.Frame(table_frame)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(
            actions, text="Add", command=lambda: self._edit_collection(key, fields, None)
        ).pack(side="left")
        ttk.Button(
            actions, text="Edit", command=lambda: self._edit_selected_collection(key, fields)
        ).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Remove", command=lambda: self._remove_selected(key)).pack(
            side="left", padx=(6, 0)
        )
        tree.bind("<Double-1>", lambda _event: self._edit_selected_collection(key, fields))
        self.collection_trees[key] = (tree, tuple(columns))

    def _build_choices_tab(self) -> None:
        tab = self.tabs["Choices"]
        tab.rowconfigure(0, weight=0)
        tab.rowconfigure(1, weight=2)
        tab.rowconfigure(2, weight=1)
        choices_guidance = ttk.Label(
            tab,
            text=(
                _field_guidance("decisions")
                + "  "
                + _field_guidance("open_questions")
            ),
            wraplength=1000,
            justify="left",
        )
        choices_guidance.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._bind_responsive_wrap(choices_guidance, tab, margin=20)
        self.guidance_labels["decisions"] = choices_guidance
        self.guidance_labels["open_questions"] = choices_guidance
        self._guidance_text["decisions"] = _field_guidance("decisions")
        self._guidance_text["open_questions"] = _field_guidance("open_questions")
        materialized = ttk.LabelFrame(tab, text="User-resolved specification decisions", padding=6)
        materialized.grid(row=1, column=0, sticky="nsew")
        materialized.columnconfigure(0, weight=1)
        materialized.rowconfigure(0, weight=1)
        tree = ttk.Treeview(
            materialized, columns=("topic", "decision"), show="headings", selectmode="browse"
        )
        tree.heading("topic", text="Topic")
        tree.heading("decision", text="Selected decision")
        tree.column("topic", width=180)
        tree.column("decision", width=500)
        tree.grid(row=0, column=0, sticky="nsew")
        actions = ttk.Frame(materialized)
        actions.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(actions, text="Add", command=lambda: self._edit_collection("decisions", DECISION_FIELDS, None)).pack(side="left")
        ttk.Button(actions, text="Edit", command=lambda: self._edit_selected_collection("decisions", DECISION_FIELDS)).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Remove", command=lambda: self._remove_selected("decisions")).pack(side="left", padx=(6, 0))
        self.collection_trees["decisions"] = (tree, ("topic", "selected_decision"))

        lower = ttk.PanedWindow(tab, orient="horizontal")
        lower.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        questions = ttk.LabelFrame(lower, text="Open questions (one per line)", padding=6)
        suggested = ttk.LabelFrame(lower, text="Suggested choices", padding=6)
        lower.add(questions, weight=1)
        lower.add(suggested, weight=2)
        questions.columnconfigure(0, weight=1)
        questions.rowconfigure(0, weight=1)
        self.open_questions_text = tk.Text(questions, height=7, wrap="word")
        questions_scrollbar = ttk.Scrollbar(
            questions, orient="vertical", command=self.open_questions_text.yview
        )
        self.open_questions_text.configure(
            yscrollcommand=questions_scrollbar.set
        )
        self.open_questions_text.grid(row=0, column=0, sticky="nsew")
        questions_scrollbar.grid(row=0, column=1, sticky="ns")
        suggested.columnconfigure(0, weight=1)
        suggested.rowconfigure(0, weight=1)
        self.suggested_tree = ttk.Treeview(
            suggested,
            columns=("status", "blocking", "topic", "question"),
            show="headings",
            selectmode="browse",
        )
        for column in ("status", "blocking", "topic", "question"):
            self.suggested_tree.heading(column, text=column.title())
        self.suggested_tree.column("status", width=80)
        self.suggested_tree.column("blocking", width=70)
        self.suggested_tree.column("topic", width=130)
        self.suggested_tree.column("question", width=320)
        self.suggested_tree.grid(row=0, column=0, sticky="nsew")
        self.resolve_button = ttk.Button(
            suggested, text="Resolve selected choice", command=self._resolve_selected_choice
        )
        self.resolve_button.grid(row=1, column=0, sticky="w", pady=(6, 0))
        suggested_help = ttk.Label(
            suggested,
            text="Analyze a clean stored draft to discover additional unresolved choices.",
            justify="left",
        )
        suggested_help.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        self._bind_responsive_wrap(suggested_help, suggested, margin=12)

    def _build_review_tab(self) -> None:
        tab = self.tabs["Review"]
        tab.rowconfigure(0, weight=0)
        tab.rowconfigure(1, weight=1)
        review_guidance = ttk.Label(
            tab,
            text=(
                "Review lists structural and approval issues by owning stage. Resolve each issue, "
                "save the draft, submit it for review, and approve only when the completion contract "
                "is accurate. Approval itself does not start implementation."
            ),
            wraplength=1000,
            justify="left",
        )
        review_guidance.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._bind_responsive_wrap(review_guidance, tab, margin=20)
        self.review_tree = ttk.Treeview(
            tab,
            columns=("owning_stage", "path", "severity", "message"),
            show="headings",
        )
        for column, width in (
            ("owning_stage", 110),
            ("path", 240),
            ("severity", 80),
            ("message", 560),
        ):
            self.review_tree.heading(column, text=column.replace("_", " ").title())
            self.review_tree.column(column, width=width, stretch=column == "message")
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.review_tree.yview)
        self.review_tree.configure(yscrollcommand=scrollbar.set)
        self.review_tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

    def _build_actions(self) -> None:
        footer = ttk.Frame(self.window, padding=10)
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.deferred_var = tk.StringVar(
            value=(
                "Approve the specification to enable implementation. Starting compiles and "
                "pins this exact version before the controller plans any work."
            )
        )
        deferred_label = ttk.Label(
            footer,
            textvariable=self.deferred_var,
            justify="left",
        )
        deferred_label.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._bind_responsive_wrap(deferred_label, footer, margin=20)
        actions = ttk.Frame(footer)
        actions.grid(row=1, column=0, sticky="e")
        self.close_button = ttk.Button(actions, text="Close", command=self.close)
        if not self._embedded:
            self.close_button.pack(side="right")
        self.start_button = ttk.Button(
            actions,
            text="Start Implementation",
            command=self.start_implementation,
            state="disabled",
        )
        self.start_button.pack(side="right", padx=(0, 6))
        self.approve_button = ttk.Button(actions, text="Approve", command=self.approve)
        self.approve_button.pack(side="right", padx=(0, 6))
        self.return_button = ttk.Button(
            actions, text="Return to Draft", command=self.return_to_draft
        )
        self.return_button.pack(side="right", padx=(0, 6))
        self.submit_button = ttk.Button(
            actions, text="Submit for Review", command=self.submit_for_review
        )
        self.submit_button.pack(side="right", padx=(0, 6))
        self.analyze_button = ttk.Button(actions, text="Analyze", command=self.analyze)
        self.analyze_button.pack(side="right", padx=(0, 6))
        self.save_button = ttk.Button(actions, text="Save Draft", command=self.save_draft)
        self.save_button.pack(side="right", padx=(0, 6))
        self.action_buttons = (
            self.save_button,
            self.submit_button,
            self.return_button,
            self.approve_button,
            self.analyze_button,
            self.start_button,
        )

    @property
    def collection_trees(self) -> dict[str, tuple[Any, tuple[str, ...]]]:
        if not hasattr(self, "_collection_trees"):
            self._collection_trees: dict[str, tuple[Any, tuple[str, ...]]] = {}
        return self._collection_trees

    def _set_text(self, widget: Any, value: str) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", value)

    def _load_record_into_widgets(self) -> None:
        self.title_var.set(self.record["title"])
        self._set_text(self.summary_text, self.record["summary"])
        self._set_text(self.objectives_text, format_list_text(self.record["objectives"]))
        self._set_text(self.stakeholders_text, format_list_text(self.record["stakeholders"]))
        for key, widget in self.scope_widgets.items():
            self._set_text(widget, format_list_text(self.record[key]))
        self._set_text(self.open_questions_text, format_list_text(self.record["open_questions"]))
        self._refresh_collection_trees()

    def _collect_record(self) -> dict[str, Any]:
        result = copy.deepcopy(self.record)
        result["title"] = self.title_var.get()
        result["summary"] = self.summary_text.get("1.0", "end-1c")
        result["objectives"] = list(parse_list_text(self.objectives_text.get("1.0", "end-1c")))
        result["stakeholders"] = list(parse_list_text(self.stakeholders_text.get("1.0", "end-1c")))
        for key, widget in self.scope_widgets.items():
            result[key] = list(parse_list_text(widget.get("1.0", "end-1c")))
        result["open_questions"] = list(
            parse_list_text(self.open_questions_text.get("1.0", "end-1c"))
        )
        return result

    def _current_document(self) -> SpecificationDocument:
        return record_to_document(self._collect_record(), worktree=self.repository_path)

    def _edit_collection(
        self, key: str, fields: Sequence[_Field], index: int | None
    ) -> None:
        initial = None if index is None else self.record[key][index]
        if key == "verification":
            initial = _verification_for_dialog(initial)
        dialog = _RecordDialog(
            self.window,
            f"Edit {key.replace('_', ' ').title()}",
            fields,
            initial,
            field_path_prefix=key,
            feedback_provider=lambda draft: self._collection_record_feedback(
                key, index, draft
            ),
        )
        result = dialog.show()
        if result is None:
            return
        if key == "verification":
            result = _verification_from_dialog(result)
        if index is None:
            self.record[key].append(result)
        else:
            self.record[key][index] = result
        self._refresh_collection_trees()
        self._refresh_assessment()

    def _selected_index(self, key: str) -> int | None:
        tree, _columns = self.collection_trees[key]
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("Select a record", "Select a record first.", parent=self.window)
            return None
        return int(selected[0])

    def _edit_selected_collection(self, key: str, fields: Sequence[_Field]) -> None:
        index = self._selected_index(key)
        if index is not None:
            self._edit_collection(key, fields, index)

    def _remove_selected(self, key: str) -> None:
        index = self._selected_index(key)
        if index is None:
            return
        del self.record[key][index]
        self._refresh_collection_trees()
        self._refresh_assessment()

    def _refresh_collection_trees(self) -> None:
        for key, (tree, columns) in self.collection_trees.items():
            tree.delete(*tree.get_children())
            for index, record in enumerate(self.record[key]):
                values = tuple(record.get(column, "") for column in columns)
                tree.insert("", "end", iid=str(index), values=values)

    def _refresh_suggested_choices(self) -> None:
        self.suggested_tree.delete(*self.suggested_tree.get_children())
        for decision in self.suggested_choices:
            self.suggested_tree.insert(
                "",
                "end",
                iid=decision["id"],
                values=(
                    decision["status"],
                    "yes" if decision["blocking"] else "no",
                    decision["topic"],
                    decision["question"],
                ),
            )

    def _unresolved_blocking_count(self) -> int:
        return sum(
            1
            for choice in self.suggested_choices
            if choice.get("blocking") and choice.get("status") == "unresolved"
        )

    def _refresh_assessment(self) -> None:
        record = self._collect_record()
        try:
            document = record_to_document(record, worktree=self.repository_path)
            assessment = assess_specification(
                document,
                worktree=self.repository_path,
                unresolved_blocking_decisions=self._unresolved_blocking_count(),
            )
        except Exception as exc:
            assessment = StageAssessment(
                issues=(WorkflowIssue("Review", "editor", "error", str(exc)),),
                structurally_valid=False,
                approval_ready=False,
            )
        self.assessment = assessment
        routed = route_issues_to_tabs(assessment)
        self.field_feedback = compute_field_feedback(
            record,
            worktree=self.repository_path,
            assessment=assessment,
        )
        self._render_field_feedback()
        feedback_keys_by_stage = {
            "Overview": ("title", "summary", "objectives", "stakeholders"),
            "Scope": ("in_scope", "out_of_scope", "assumptions", "constraints", "dependencies"),
            "Use Cases": ("use_cases",),
            "Requirements": ("requirements",),
            "Risks": ("risks",),
            "Verification": ("verification",),
            "Choices": ("decisions", "open_questions"),
            "Review": (),
        }
        for stage, frame in self.tabs.items():
            advisory_attention = any(
                self.field_feedback[key].health in {"weak", "needs_attention"}
                for key in feedback_keys_by_stage[stage]
            )
            marker = "!" if routed[stage] or advisory_attention else " "
            self.notebook.tab(frame, text=f"{marker} {stage}")
        self.review_tree.delete(*self.review_tree.get_children())
        for index, issue in enumerate(assessment.issues):
            self.review_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(issue.owning_stage, issue.path, issue.severity, issue.message),
            )
        self._update_actions()

    def _render_field_feedback(self) -> None:
        rendered_widgets: set[str] = set()
        for key, label in self.guidance_labels.items():
            widget_name = str(label)
            if widget_name in rendered_widgets:
                continue
            rendered_widgets.add(widget_name)
            related_keys = tuple(
                candidate
                for candidate, candidate_label in self.guidance_labels.items()
                if candidate_label is label
            )
            guidance = "  ".join(self._guidance_text[candidate] for candidate in related_keys)
            messages = [
                self.field_feedback[candidate].message
                for candidate in related_keys
                if candidate in self.field_feedback
            ]
            feedback_text = "  ".join(messages)
            label.configure(
                text=f"{guidance}\n\nLive feedback: {feedback_text}" if feedback_text else guidance
            )

    def _collection_record_feedback(
        self,
        key: str,
        index: int | None,
        dialog_record: Mapping[str, Any],
    ) -> dict[str, FieldSemanticFeedback]:
        candidate = self._collect_record()
        item = dict(dialog_record)
        if key == "verification":
            item = _verification_from_dialog(item)
        values = list(candidate[key])
        target_index = len(values) if index is None else index
        if index is None:
            values.append(item)
        else:
            values[index] = item
        candidate[key] = values
        computed = compute_field_feedback(candidate, worktree=self.repository_path)
        prefix = f"{key}[{target_index}]."
        return {
            path.removeprefix(prefix).removeprefix("validation_loop."): feedback
            for path, feedback in computed.items()
            if path.startswith(prefix)
        }

    def _schedule_assessment(self, *_event: Any) -> None:
        if self._assessment_after_id is not None:
            try:
                self.window.after_cancel(self._assessment_after_id)
            except tk.TclError:
                pass
        self._assessment_after_id = self.window.after(100, self._finish_scheduled_assessment)

    def _on_text_modified(self, event: Any) -> None:
        if event.widget.edit_modified():
            event.widget.edit_modified(False)
            self._schedule_assessment(event)

    def _finish_scheduled_assessment(self) -> None:
        self._assessment_after_id = None
        self._refresh_assessment()

    def _has_unsaved_edits(self) -> bool:
        if self.snapshot is None:
            return True
        try:
            return self._current_document().canonical_json() != self.snapshot.document.canonical_json()
        except Exception:
            return True

    def _update_actions(self) -> None:
        status = self.snapshot.status if self.snapshot else "new"
        dirty = self._has_unsaved_edits()
        states = {
            self.save_button: status in {"new", "draft", "approved"},
            self.submit_button: status == "draft" and not dirty,
            self.return_button: status == "review",
            self.approve_button: (
                status == "review" and not dirty and self.assessment.approval_ready
            ),
            self.analyze_button: (
                status == "draft"
                and not dirty
                and self._elicitation_provider_factory is not None
            ),
            self.start_button: (
                status == "approved"
                and not dirty
                and self._implementation_work_factory is not None
                and self._implementation_job_id is None
                and not self._implementation_start_in_flight
            ),
        }
        for button, enabled in states.items():
            button.configure(state="normal" if enabled and not self._busy else "disabled")
        self.selector.configure(state="disabled" if self._busy else "readonly")
        for button in (
            self.load_example_button,
            self.test_specification_button,
            self.save_specification_button,
            self.load_specification_button,
        ):
            button.configure(state="disabled" if self._busy else "normal")
        self.resolve_button.configure(
            state="normal"
            if not self._busy and any(c.get("status") == "unresolved" for c in self.suggested_choices)
            else "disabled"
        )

    def _set_busy(self, busy: bool, status: str | None = None) -> None:
        self._busy = busy
        if status:
            self.status_var.set(status)
        self._update_actions()

    def _background(
        self,
        work: Callable[[], Any],
        done: Callable[[Any, str | None], None],
        *,
        label: str,
    ) -> None:
        self._set_busy(True, f"{label}…")

        def finish(result: Any, error: str | None) -> None:
            self._set_busy(False)
            done(result, error)

        if self._run_background is not None:
            self._run_background(
                work,
                finish,
                name=f"ai-loop-spec-{label.lower().replace(' ', '-')}",
                label=label,
            )
            return

        def runner() -> None:
            try:
                result, error = work(), None
            except Exception as exc:  # pragma: no cover - exercised through injected runners
                result, error = None, str(exc) or repr(exc)
            try:
                self.window.after(0, lambda: finish(result, error))
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(target=runner, name="ai-loop-specification", daemon=True).start()

    def refresh_specifications(self, *, select_id: str | None = None) -> None:
        repository = self.repository_path

        def done(result: Any, error: str | None) -> None:
            if error:
                messagebox.showerror("Specification list failed", error, parent=self.window)
                self._show_snapshot_status()
                return
            rows = list(result)
            self._selector_rows = {
                self._selector_label(row): row for row in rows
            }
            values = ("New specification", *self._selector_rows)
            self.selector.configure(values=values)
            if select_id is not None:
                for label, row in self._selector_rows.items():
                    if row["id"] == select_id:
                        self.selector_var.set(label)
                        break
            self._show_snapshot_status()

        self._background(
            lambda: self.service.list(repository),
            done,
            label="Loading formal specifications",
        )

    @staticmethod
    def _selector_label(row: Mapping[str, Any]) -> str:
        return f"{row['title'] or '(untitled)'} — {row['id']} v{row['current_version']} [{row['status']}]"

    def load_example(self) -> None:
        """Replace the editor contents with a new, unsaved worked example."""

        self.snapshot = None
        self._implementation_job_id = None
        self.suggested_choices = []
        self.selector_var.set("New specification")
        self.record = document_to_record(
            worked_example_document(worktree=self.repository_path)
        )
        self._load_record_into_widgets()
        self._refresh_suggested_choices()
        self.status_var.set(
            "Worked example loaded — editable, unsaved, and not submitted or approved"
        )
        self.deferred_var.set(
            "Save this example as a draft, resolve Review issues, submit it, and approve it "
            "before Start Implementation can be enabled."
        )
        self._refresh_assessment()

    def test_specification(self) -> None:
        """Analyze the complete current draft without changing workflow state."""

        record = self._collect_record()
        suggestions = analyze_specification(
            record,
            worktree=self.repository_path,
            unresolved_blocking_decisions=self._unresolved_blocking_count(),
        )
        _SpecificationSuggestionsDialog(self.window, suggestions).show()

    def save_specification(self) -> None:
        """Save the current editor draft to a user-selected JSON file."""

        selected = filedialog.asksaveasfilename(
            parent=self.window,
            title="Save specification JSON",
            defaultextension=".json",
            filetypes=(("JSON files", "*.json"), ("All files", "*")),
            initialfile="specification.json",
        )
        if not selected:
            return
        try:
            # A disk save is a user checkpoint, not a workflow transition.  It
            # must preserve an unfinished draft even while live validation is
            # still reporting required fields or semantic issues.
            record = self._collect_record()
            Path(selected).write_bytes(specification_to_savefile_bytes(record))
        except Exception as exc:
            messagebox.showerror(
                "Save specification failed", str(exc), parent=self.window
            )
            return
        self.status_var.set(f"Specification saved to {selected}")

    def load_specification(self) -> None:
        """Load a saved draft into the editor without changing workflow state."""

        selected = filedialog.askopenfilename(
            parent=self.window,
            title="Load specification JSON",
            filetypes=(("JSON files", "*.json"), ("All files", "*")),
        )
        if not selected:
            return
        try:
            record = savefile_to_record(Path(selected).read_bytes())
        except Exception as exc:
            messagebox.showerror(
                "Load specification failed", str(exc), parent=self.window
            )
            return

        self.snapshot = None
        self._implementation_job_id = None
        self.suggested_choices = []
        self.selector_var.set("New specification")
        self.record = record
        self._load_record_into_widgets()
        self._refresh_suggested_choices()
        self.status_var.set(
            "Specification loaded from file — editable, unsaved, and not submitted or approved"
        )
        self.deferred_var.set(
            "Save this imported specification as a draft, resolve Review issues, submit it, "
            "and approve it before Start Implementation can be enabled."
        )
        self._refresh_assessment()

    def _on_selector_changed(self, _event: Any = None) -> None:
        label = self.selector_var.get()
        if label == "New specification":
            self.snapshot = None
            self._implementation_job_id = None
            self.suggested_choices = []
            self.record = document_to_record(SpecificationDocument.empty())
            self._load_record_into_widgets()
            self._refresh_suggested_choices()
            self.status_var.set("New unsaved draft")
            self._refresh_assessment()
            return
        row = self._selector_rows.get(label)
        if row is None:
            return

        def work() -> tuple[StoredSpecificationVersion, list[dict[str, Any]]]:
            return self.service.load(row["id"]), self.service.list_decisions(row["id"])

        def done(result: Any, error: str | None) -> None:
            if error:
                messagebox.showerror("Open specification failed", error, parent=self.window)
                self._show_snapshot_status()
                return
            self.snapshot, self.suggested_choices = result
            self._implementation_job_id = None
            self.record = document_to_record(self.snapshot.document)
            self._load_record_into_widgets()
            self._refresh_suggested_choices()
            self._show_snapshot_status()
            self._refresh_assessment()

        self._background(work, done, label="Opening formal specification")

    def _show_snapshot_status(self) -> None:
        if self.snapshot is None:
            self.status_var.set("New unsaved draft")
        else:
            self.status_var.set(
                f"{self.snapshot.specification_id} · version {self.snapshot.version} · "
                f"status {self.snapshot.status} · SHA-256 {self.snapshot.canonical_content_hash[:12]}…"
            )
        self._update_actions()

    def save_draft(self) -> None:
        try:
            document = self._current_document()
        except Exception as exc:
            messagebox.showerror("Save Draft", str(exc), parent=self.window)
            self._refresh_assessment()
            return
        current_id = self.snapshot.specification_id if self.snapshot else None

        def work() -> StoredSpecificationVersion:
            if current_id is None:
                return create_draft(
                    self.service,
                    self.repository_path,
                    document,
                    creator=self.creator,
                    change_summary="Initial GUI draft",
                )
            return save_draft(
                self.service,
                current_id,
                document,
                creator=self.creator,
                change_summary="GUI draft revision",
            )

        self._run_lifecycle(work, "Save Draft")

    def analyze(self) -> None:
        """Run read-only elicitation away from Tk, then open the modal review."""

        if self.snapshot is None:
            messagebox.showerror(
                "Analyze",
                "Save this specification as a draft before running AI analysis.",
                parent=self.window,
            )
            return
        if self.snapshot.status != "draft":
            messagebox.showerror(
                "Analyze",
                "AI analysis requires a stored draft. Return to Draft before analyzing.",
                parent=self.window,
            )
            return
        if self._has_unsaved_edits():
            messagebox.showerror(
                "Analyze",
                "Save the current editor content as a draft revision before analyzing it.",
                parent=self.window,
            )
            return
        if self._elicitation_provider_factory is None:
            messagebox.showerror(
                "Analyze",
                "No structured-output controller provider is configured for this editor.",
                parent=self.window,
            )
            return
        try:
            # Provider settings are a Tk-owned snapshot and must be read before
            # the background thread starts.
            provider = self._elicitation_provider_factory()
        except Exception as exc:
            messagebox.showerror("Analyze", str(exc), parent=self.window)
            return
        source = self.snapshot

        def work() -> CompletedElicitation:
            return ElicitationEngine(self.service, provider).analyze(
                source.specification_id,
                source.version,
            )

        def done(result: Any, error: str | None) -> None:
            if error:
                messagebox.showerror(
                    "AI analysis failed",
                    f"{error}\n\nThe stored draft was not changed. Correct the issue and run Analyze again.",
                    parent=self.window,
                )
                self._show_snapshot_status()
                return
            completed = result
            action = _ElicitationReviewDialog(
                self.window,
                completed=completed,
                source=source,
            ).show()
            if action is None:
                self.status_var.set(
                    f"Analysis {completed.stored.analysis_id} retained without application"
                )
                self._update_actions()
                return
            self._apply_elicitation(completed, action)

        self._background(work, done, label="Analyzing formal specification")

    def _apply_elicitation(
        self,
        completed: CompletedElicitation,
        application_mode: str,
    ) -> None:
        def work() -> tuple[Any, list[dict[str, Any]]]:
            applied = apply_elicitation_analysis(
                self.service,
                completed.stored.analysis_id,
                application_mode=application_mode,
                creator=self.creator,
            )
            choices = self.service.list_decisions(applied.snapshot.specification_id)
            return applied, choices

        def done(result: Any, error: str | None) -> None:
            if error:
                messagebox.showerror(
                    "Apply AI analysis",
                    f"{error}\n\nNo analysis changes were applied. Reopen the current draft "
                    "and run Analyze again if it changed.",
                    parent=self.window,
                )
                self._show_snapshot_status()
                self._refresh_assessment()
                return
            applied, choices = result
            self.snapshot = applied.snapshot
            self.suggested_choices = choices
            self.record = document_to_record(applied.snapshot.document)
            self._load_record_into_widgets()
            self._refresh_suggested_choices()
            self._show_snapshot_status()
            self._refresh_assessment()
            mode_label = "Choices Only" if application_mode == "choices_only" else "Apply All"
            messagebox.showinfo(
                "AI analysis applied",
                f"{mode_label} created draft version {applied.snapshot.version}.\n"
                f"Analysis: {applied.analysis.analysis_id}\n"
                f"Specification additions: {len(applied.additions)}\n"
                f"Proposed choices created: {applied.decisions_created}",
                parent=self.window,
            )
            self.refresh_specifications(select_id=applied.snapshot.specification_id)

        self._background(work, done, label="Applying AI analysis")

    def submit_for_review(self) -> None:
        if self.snapshot is None:
            return
        if self._has_unsaved_edits():
            messagebox.showerror(
                "Submit for Review",
                "Save the current draft revision before submitting it for review.",
                parent=self.window,
            )
            return
        self._run_lifecycle(
            lambda: submit_for_review(self.service, self.snapshot.specification_id),
            "Submit for Review",
        )

    def return_to_draft(self) -> None:
        if self.snapshot is None:
            return
        self._run_lifecycle(
            lambda: return_to_draft(self.service, self.snapshot.specification_id),
            "Return to Draft",
        )

    def approve(self) -> None:
        self._refresh_assessment()
        if self.snapshot is None or not self.assessment.approval_ready:
            messagebox.showerror(
                "Approve",
                "Resolve every Review issue and blocking suggested choice before approval.",
                parent=self.window,
            )
            return
        if self._has_unsaved_edits():
            messagebox.showerror(
                "Approve",
                "The review version differs from the editor. Return to Draft and save a revision first.",
                parent=self.window,
            )
            return
        self._run_lifecycle(
            lambda: approve(
                self.service, self.snapshot.specification_id, approved_by=self.creator
            ),
            "Approve",
        )

    def start_implementation(self) -> None:
        """Compile, pin, and enqueue the approved snapshot through the GUI job path."""

        if self._implementation_start_in_flight:
            messagebox.showinfo(
                "Start Implementation",
                "Implementation is already being created; wait for it to finish.",
                parent=self.window,
            )
            return
        if self._implementation_job_id is not None:
            messagebox.showinfo(
                "Start Implementation",
                f"Implementation already started as {self._implementation_job_id}.",
                parent=self.window,
            )
            return
        if (
            self.snapshot is None
            or self.snapshot.status != "approved"
            or self._implementation_work_factory is None
        ):
            messagebox.showerror(
                "Start Implementation",
                "Approve this specification before starting implementation.",
                parent=self.window,
            )
            return
        if self._has_unsaved_edits():
            messagebox.showerror(
                "Start Implementation",
                "The approved version differs from the editor. Reload it before starting.",
                parent=self.window,
            )
            return
        snapshot = self.snapshot
        self._implementation_start_in_flight = True
        self._update_actions()
        try:
            work = self._implementation_work_factory(snapshot)
        except Exception as exc:
            self._implementation_start_in_flight = False
            self._update_actions()
            messagebox.showerror(
                "Start Implementation", str(exc), parent=self.window
            )
            return

        def done(job_id: Any, error: str | None) -> None:
            self._implementation_start_in_flight = False
            if error:
                messagebox.showerror(
                    "Start Implementation", error, parent=self.window
                )
                self._show_snapshot_status()
                return
            self._implementation_job_id = str(job_id)
            self.status_var.set(
                f"Implementation started as {self._implementation_job_id}; "
                f"{snapshot.specification_id} v{snapshot.version} is pinned."
            )
            self.deferred_var.set(
                f"Implementation job {self._implementation_job_id} is queued for controller planning."
            )
            self._update_actions()
            if self._on_implementation_started is not None:
                self._on_implementation_started(self._implementation_job_id)
            messagebox.showinfo(
                "Implementation started",
                f"Created {self._implementation_job_id} and queued its initial PLAN task.",
                parent=self.window,
            )

        self._background(work, done, label="Start Implementation")

    def _run_lifecycle(
        self, work: Callable[[], StoredSpecificationVersion], label: str
    ) -> None:
        def done(result: Any, error: str | None) -> None:
            if error:
                messagebox.showerror(label, error, parent=self.window)
                self._show_snapshot_status()
                self._refresh_assessment()
                return
            self.snapshot = result
            self.record = document_to_record(result.document)
            self._load_record_into_widgets()
            self._show_snapshot_status()
            self._refresh_assessment()
            self.refresh_specifications(select_id=result.specification_id)

        self._background(work, done, label=label)

    def _resolve_selected_choice(self) -> None:
        selected = self.suggested_tree.selection()
        if not selected or self.snapshot is None:
            messagebox.showinfo("Resolve choice", "Select an unresolved choice first.", parent=self.window)
            return
        decision = next(
            (item for item in self.suggested_choices if item["id"] == selected[0]), None
        )
        if decision is None or decision["status"] != "unresolved":
            return
        options = decision.get("options", [])
        option_names = tuple(
            str(item.get("name", item.get("label", "")))
            for item in options
            if isinstance(item, Mapping)
        )
        fields = (
            _Field("selected_option", "Selected option", "enum", option_names, option_names[0] if option_names else ""),
            _Field("rationale", "Rationale", "text"),
            _Field("deferred", "Defer as non-blocking", "bool", default=False),
        )
        result = _RecordDialog(self.window, f"Resolve: {decision['topic']}", fields).show()
        if result is None:
            return

        def work() -> tuple[StoredSpecificationVersion, list[dict[str, Any]]]:
            self.service.resolve_decision(
                self.snapshot.specification_id,
                decision["id"],
                selected_option=result["selected_option"],
                rationale=result["rationale"],
                deferred=result["deferred"],
            )
            return (
                self.service.load(self.snapshot.specification_id),
                self.service.list_decisions(self.snapshot.specification_id),
            )

        def done(value: Any, error: str | None) -> None:
            if error:
                messagebox.showerror("Resolve choice", error, parent=self.window)
                self._show_snapshot_status()
                return
            self.snapshot, self.suggested_choices = value
            self._refresh_suggested_choices()
            self._show_snapshot_status()
            self._refresh_assessment()

        self._background(work, done, label="Resolve formal choice")

    def close(self) -> None:
        if self._busy:
            messagebox.showinfo(
                "Formal Specification",
                "Wait for the current specification operation to finish.",
                parent=self.window,
            )
            return
        if not self._embedded:
            self.window.destroy()
        if self._on_close_callback is not None:
            self._on_close_callback(self)


def open_specification_editor(
    parent: Any,
    *,
    service: SpecificationService,
    repository_path: str | Path,
    initial_goal: str = "",
    creator: str = "gui-user",
    run_background: Callable[..., None] | None = None,
    elicitation_provider_factory: Callable[[], StructuredOutputProvider] | None = None,
    implementation_work_factory: (
        Callable[[StoredSpecificationVersion], Callable[[], str]] | None
    ) = None,
    on_implementation_started: Callable[[str], None] | None = None,
    on_close: Callable[[SpecificationEditor], None] | None = None,
    embedded: bool = False,
) -> SpecificationEditor:
    """Open or embed a formal editor initialized from the Quick Goal fields."""

    return SpecificationEditor(
        parent,
        service=service,
        repository_path=repository_path,
        initial_goal=initial_goal,
        creator=creator,
        run_background=run_background,
        elicitation_provider_factory=elicitation_provider_factory,
        implementation_work_factory=implementation_work_factory,
        on_implementation_started=on_implementation_started,
        on_close=on_close,
        embedded=embedded,
    )


__all__ = [
    "FieldSemanticFeedback",
    "MetricAssertionParseError",
    "PROCESS_OVERVIEW_TEXT",
    "SPECIFICATION_FIELD_EXAMPLES",
    "SPECIFICATION_FIELD_GUIDANCE",
    "SPECIFICATION_SAVEFILE_SCHEMA",
    "SPECIFICATION_SAVEFILE_VERSION",
    "SpecificationSavefileError",
    "SpecificationEditor",
    "SpecificationSuggestion",
    "StructuredRecordParseError",
    "VerificationDashboardView",
    "analyze_specification",
    "analyze_specification_suggestions",
    "compute_field_feedback",
    "document_to_record",
    "format_list_text",
    "format_metric_assertions",
    "format_structured_records",
    "issues_by_tab",
    "model_to_record",
    "open_specification_editor",
    "parse_list_text",
    "parse_metric_assertions",
    "parse_structured_records",
    "record_to_document",
    "record_to_model",
    "render_choice_summary",
    "render_specification_json_diff",
    "savefile_to_record",
    "specification_to_savefile_bytes",
    "route_issues_to_tabs",
    "worked_example_document",
]
