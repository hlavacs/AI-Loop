"""Selector persistence, graph navigation, unsaved source protection, and operation recovery."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from icoda_core import clusters, executables, instrumentation, persistence, prompt, session, steps, views
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind


def opened(root: Path) -> session.OpenedProject:
    model = DerivedModel(str(root))
    for name in ("first", "second"):
        file = f"examples/{name}/main.cpp"
        path = root / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("int main() { return 0; }\n")
        model.files[file] = FileInfo(file)
        model.add_entity(Entity(name, Kind.FUNCTION, "main", "main", file, 1))
    clustered = clusters.cluster_files(model)
    return session.OpenedProject(root, model, clustered, views.layout_file_view(model, clustered), None, [])


def test_selection_changes_graph_source_and_survives_reload(app_module, tmp_path):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    project = opened(tmp_path)
    app.show(project)
    selector = app.executables
    assert selector.selected is None
    assert set(app.view.layout.nodes) == set(project.model.files)
    assert app.class_view.model.files and app.call_view.model.files
    assert selector.choice_var.get() == "Whole project" and "Whole project" in app.status.get()
    selector.choice_var.set(selector.choices[1].label)
    selector.select()
    assert selector.selected.usr == app.call_view.root_usr == app.call_view.entry_usr == "second"
    assert app.source_editor.document.relative == "examples/second/main.cpp"
    saved = persistence.ProjectStore(tmp_path).load_ui()
    assert saved["executable"][0] == "examples/second/main.cpp"
    app.call_view.set_root("first")
    app.call_view.from_main()
    assert app.call_view.root_usr == "second"
    app.show(project)
    assert selector.selected.usr == app.call_view.root_usr == "second"
    other = tmp_path / "other"
    app.show(opened(other))
    assert selector.selected is None
    app.show(project)
    assert selector.selected.usr == "second"
    del project.model.entities["second"]
    app.show(project)
    assert selector.selected.usr == "first"  # deleted entry does not remain selected


def test_selection_cancel_keeps_unsaved_source_and_choice(app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened(tmp_path))
    selector = app.executables
    selector.choice_var.set(selector.choices[0].label)
    selector.select()
    app.source_editor.text.insert("end", "// keep me\n")
    draft = app.source_editor.content()
    monkeypatch.setattr(app_module.source_editor.messagebox, "askyesnocancel", lambda *a, **kw: None)
    selector.choice_var.set(selector.choices[1].label)
    selector.select()
    assert selector.selected.usr == app.call_view.root_usr == "first"
    assert selector.choice_var.get() == selector.choices[0].label
    assert app.source_editor.content() == draft and app.source_editor.dirty


@pytest.mark.parametrize("phase", [persistence.ProjectPhase.ARCHITECTURE, persistence.ProjectPhase.IMPLEMENTATION])
def test_operations_guard_busy_and_send_failures_to_recovery(app_module, tmp_path, monkeypatch, phase):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened(tmp_path))
    persistence.ProjectStore(tmp_path).save_state(persistence.ProjectState(phase=phase))
    app.executables.choice_var.set(app.executables.choices[0].label)
    app.executables.select()
    calls = []
    failures = []
    monkeypatch.setattr(app.recovery, "handle_failure", lambda error, **options: failures.append((error, options)))
    repaired = []
    monkeypatch.setattr(app.steps, "_ensure_runner", lambda: SimpleNamespace(repair_project=repaired.append))

    def work(root, model, selected, action, cancelled):
        calls.append((root, selected.usr, action))
        assert app.panel.busy
        return steps.StepError("Build failed: example compilation")

    monkeypatch.setattr(executables, "operate", work)
    app.run_async = lambda work, done: done(work())
    app.panel.set_busy(True, "existing operation")
    app.executables.operate("run")
    assert not calls
    app.panel.set_busy(False)
    app.executables.operate("run")
    assert calls == [(tmp_path, "first", "run")] and len(failures) == 1
    assert callable(failures[0][1]["retry"])
    if phase == persistence.ProjectPhase.ARCHITECTURE:
        failures[0][1]["repair"]()
        assert repaired == ["Build failed: example compilation"]
    else:
        assert "repair" not in failures[0][1]  # use ordinary CLI investigation for an existing project
    assert not app.panel.busy and not app.executables.running


def test_build_available_before_target_discovery_and_refresh_reanalyses(app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    (tmp_path / "CMakeLists.txt").touch()
    project = opened(tmp_path)
    project.model.files.clear()
    project.model.entities.clear()
    app.show(project)
    selector = app.executables
    states = {}
    for name in ("Build", "Run", "Refresh targets"):
        monkeypatch.setattr(selector.buttons[name], "state", lambda value, name=name: states.update({name: value}))
    selector.update_controls()
    assert states == {"Build": ["!disabled"], "Run": ["disabled"], "Refresh targets": ["!disabled"]}
    built, reloaded = [], []
    monkeypatch.setattr(app, "build_project", lambda: built.append(tmp_path))
    monkeypatch.setattr(app, "open_project", reloaded.append)
    selector.operate("build")
    assert built == [tmp_path]
    app.panel.set_busy(True, "busy")
    selector.operate("build")
    assert built == [tmp_path]
    app.panel.set_busy(False)
    library = executables.Target("library", "", tmp_path / "build", None, frozenset(), kind="STATIC_LIBRARY")
    selector._choices((executables.Entry("", "", 0, library),), None)
    selector.operate("build")
    assert built == [tmp_path, tmp_path]  # target metadata alone does not replace the missing source analysis
    app.run_async = lambda work, done: done(work())
    monkeypatch.setattr(executables, "operate", lambda *args: executables.Outcome((), None, "ok", "refreshed"))
    selector.operate("refresh")
    assert reloaded == [tmp_path]


def test_success_and_ambiguity_update_choices_without_running_an_arbitrary_target(app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened(tmp_path))
    selector = app.executables
    selector.choice_var.set(selector.choices[0].label)
    selector.select()
    source = selector.selected
    target = executables.Target("first", "Debug", tmp_path / "build", tmp_path / "program", frozenset())
    choice = executables.Entry(source.usr, source.file, source.line, target)
    results = [executables.Outcome((choice,), None, "Configured", "Choose a target"),
               executables.Outcome((choice,), choice, "first output\n", "first: finished (exit 0)")]
    monkeypatch.setattr(executables, "operate", lambda *args: results.pop(0))
    app.run_async = lambda work, done: done(work())
    selector.operate("run")
    assert selector.selected is None and selector.choice_var.get() == "Whole project"
    selector.operate("run")
    assert len(results) == 1
    selector.choice_var.set(choice.label)
    selector.select()
    selector.operate("run")
    assert not results and selector.output.get("1.0", "end").strip() == "first output"
    assert persistence.ProjectStore(tmp_path).load_ui()["executable"] == [source.file, "first", "Debug"]


def test_run_passes_call_trace_options_only_when_enabled(app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened(tmp_path))
    selector = app.executables
    selector.choice_var.set(selector.choices[0].label)
    selector.select()
    calls = []

    def operate(*args, **kwargs):
        calls.append(kwargs.get("instrumentation_options"))
        trace_file = tmp_path / "calls.tsv" if calls[-1] is not None else None
        return executables.Outcome(selector.choices, selector.selected, "", "finished", trace_file)

    monkeypatch.setattr(executables, "operate", operate)
    app.run_async = lambda work, done: done(work())
    selector.operate("run")
    selector.record_trace_var.set(True)
    selector.trace_seconds_var.set("7")
    selector.operate("run")

    assert calls == [None, instrumentation.InstrumentationOptions(True, 7.0)]
    assert app.last_trace_file == tmp_path / "calls.tsv"
    selector.trace_seconds_var.set("0")
    selector.operate("run")
    assert len(calls) == 2 and "positive number" in app.status.get()


def test_call_trace_playback_selects_recorded_functions_and_reports_bad_trace(
        app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    project = opened(tmp_path)
    main = project.model.entities["first"]
    main.usr = "main"
    project.model.entities = {"main": main}
    work_file = "examples/first/work.cpp"
    project.model.files[work_file] = FileInfo(work_file)
    project.model.add_entity(Entity("work", Kind.FUNCTION, "work", "demo::work", work_file, 1))
    project.model.add_edge(Edge(EdgeKind.CALLS, "main", "work", main.file, 1))
    app.show(project)

    def immediately(work, done):
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001  (mirror UiTasks exception delivery)
            result = exc
        done(result)

    app.run_async = immediately
    trace = tmp_path / "calls.tsv"
    trace.write_text(
        "# icoda-call-trace-v1\n"
        "E\t1\tt\t0\t0x1\t0x0\tmain\tapp\n"
        "E\t2\tt\t1\t0x2\t0x1\tdemo::work()\tapp\n",
        encoding="utf-8",
    )
    app.last_trace_file = trace
    buttons = app.call_view.playback_buttons
    assert all(button.kwargs["state"] == app_module.tk.DISABLED
               for label, button in buttons.items() if label != "Load trace")
    states = {label: [] for label in ("Previous call", "Next call", "Reset")}
    for label, values in states.items():
        monkeypatch.setattr(buttons[label], "state", lambda value, values=values: values.append(value))

    app.load_call_trace()
    assert all(values == [["!disabled"]] for values in states.values())
    app.call_view.next_call()
    assert app.call_view.selected == "main"
    assert app.call_view.playback_status_var.get() == "call 1 of 2: main"
    app.call_view.next_call()
    assert app.call_view.selected == "work"
    assert app.call_view.playback_status_var.get() == "call 2 of 2: demo::work"
    app.call_view.previous_call()
    assert app.call_view.selected == "main"
    assert app.call_view.playback_status_var.get() == "call 1 of 2: main"
    app.call_view.reset_playback()
    assert app.call_view.selected is None
    assert app.call_view.playback_status_var.get() == "call 0 of 2"

    malformed = tmp_path / "broken.tsv"
    malformed.write_text("not a trace\n", encoding="utf-8")
    app.last_trace_file = malformed
    app.load_call_trace()
    assert "Could not load call trace" in app.status.get()


def test_all_views_show_only_selected_executable_and_shared_dependencies(app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    project = opened(tmp_path)
    model = project.model
    model.files["src/shared.cpp"] = FileInfo("src/shared.cpp")
    model.add_entity(Entity("shared", Kind.CLASS, "Shared", "Shared", "src/shared.cpp", 1))
    for name in ("first", "second"):
        file = model.entities[name].file
        model.add_entity(Entity(name + "_class", Kind.CLASS, name, name, file, 2))
        model.add_edge(Edge(EdgeKind.USES_TYPE, name, "shared", file))
    before = model.to_json()
    app.show(project)
    selector = app.executables
    assert app.displayed.model is model
    assert set(app.view.layout.nodes) == set(model.files)
    assert set(app.class_view.layout.nodes) == {"first_class", "second_class", "shared"}
    app.views.select(app.class_view.frame)
    selected_tabs = []
    monkeypatch.setattr(app.views, "select", selected_tabs.append)
    for name, other in (("first", "second"), ("second", "first")):
        selector.choice_var.set(next(choice.label for choice in selector.choices if choice.usr == name))
        selector.select()
        files = {f"examples/{name}/main.cpp", "src/shared.cpp"}
        assert set(app.displayed.model.files) == set(app.view.layout.nodes) == files
        assert set(app.call_view.model.files) == set(app.class_view.model.files) == files
        assert set(app.class_view.layout.nodes) == {name + "_class", "shared"}
        nodes = app.mind_map_view.tree.node_map()
        assert "file:examples/" + other + "/main.cpp" not in nodes
        assert set(app.coverage_view.index.entry_map()) == {name}
        assert all(issue.file in files for issue in app.issue_view.issues)
        assert not selected_tabs
        app.select_node(other)  # Hidden entities cannot repopulate the sidebar or Call View.
        assert app.source_editor.document.relative == f"examples/{name}/main.cpp"
        app.call_view.callers_var.set(True)
        app.call_view.set_root("shared")
        assert other not in app.call_view.model.entities
        app.clear_graph_filter()
        app.collapse_all()
        assert set(app.view.layout.nodes) == files
    assert app.opened.model is model and model.to_json() == before
    app.show(project)
    assert selector.selected.usr == "second" and "examples/first/main.cpp" not in app.displayed.model.files
    selector.choice_var.set("Whole project")
    selector.select()
    assert selector.selected is None and app.displayed.model is model
    assert set(app.view.layout.nodes) == set(model.files)
    assert set(app.class_view.layout.nodes) == {"first_class", "second_class", "shared"}
    assert persistence.ProjectStore(tmp_path).load_ui()["executable"] == []
    assert not selected_tabs
    app.show(project)
    assert selector.selected is None and app.displayed.model is model


def test_whole_project_preserves_single_target_overview_and_requires_selection_to_run(
        app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    project = opened(tmp_path)
    (tmp_path / "CMakeLists.txt").touch()
    app.show(project)
    selector = app.executables
    called = []
    monkeypatch.setattr(app, "build_project", lambda: called.append("build"))
    monkeypatch.setattr(app, "run_async", lambda *args: called.append("target-operation"))
    selector.operate("run")
    assert not called
    selector.operate("build")
    assert called == ["build"]
    selector.choice_var.set(selector.choices[0].label)
    selector.select()
    chosen = selector.selected
    monkeypatch.setattr(app.source_editor, "confirm_saved", lambda: False)
    selector.choice_var.set("Whole project")
    selector.select()
    assert selector.selected == chosen and selector.choice_var.get() == chosen.label
    monkeypatch.setattr(app.source_editor, "confirm_saved", lambda: True)
    selector.choice_var.set("Whole project")
    selector.select()
    del project.model.entities["second"]
    app.show(project)
    assert len(selector.choices) == 1 and selector.selected is None
    assert app.displayed.model is project.model
    app.run_async = lambda work, done: done(work())
    choice = selector.choices[0]
    monkeypatch.setattr(executables, "operate", lambda *args: executables.Outcome((choice,), choice, "", "refreshed"))
    selector.operate("refresh")
    assert selector.selected is None and selector.choice_var.get() == "Whole project"
    assert app.displayed.model is project.model


def test_proposal_call_preview_obeys_selection_and_opens_candidate_source(app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    project = opened(tmp_path)
    app.show(project)
    selector = app.executables
    selector.choice_var.set(selector.choices[0].label)
    selector.select()
    candidate = tmp_path / "candidate"
    model = DerivedModel.from_json(project.model.to_json())
    model.root = str(candidate)
    delta = steps.compute_delta(project.model, model, [])
    proposal = steps.Proposal(1, prompt.StepRequest(prompt.ARCHITECTURE, 1), candidate, model=model, delta=delta)
    app.show_proposal_calls(proposal)
    assert set(app.call_view.model.files) == {"examples/first/main.cpp"}
    opened_files = []
    monkeypatch.setattr(app, "open_editor", lambda file, line, **kwargs: opened_files.append((file, kwargs)))
    app.open_call_source("examples/first/main.cpp", 1)
    assert opened_files == [("examples/first/main.cpp", {"root": candidate})]


def test_library_selection_scopes_all_views_shows_function_set_and_restores(app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    project = opened(tmp_path)
    (tmp_path / "CMakeLists.txt").write_text("# fixture\n")
    library_file = "library.cpp"
    (tmp_path / library_file).write_text("int api() { return 0; }\nint unused() { return 1; }\n")
    project.model.files[library_file] = FileInfo(library_file)
    for name in ("api", "unused"):
        project.model.add_entity(Entity(name, Kind.FUNCTION, name, name, library_file, 1))
    target = executables.Target("library", "Debug", tmp_path / "build", tmp_path / "build/liblibrary.a",
                                frozenset({str(tmp_path / library_file)}), kind="STATIC_LIBRARY")
    monkeypatch.setattr(executables, "read_targets", lambda _root: (target,))
    app.show(project)
    selector = app.executables
    assert selector.selected is None
    library = next(entry for entry in selector.choices if entry.is_library)
    states = {}
    for name in ("Run", "Build"):
        monkeypatch.setattr(selector.buttons[name], "state", lambda value, name=name: states.update({name: value}))
    selector.choice_var.set(library.label)
    selector.select()
    assert states == {"Run": ["disabled"], "Build": ["!disabled"]}
    assert set(app.displayed.model.files) == set(app.view.layout.nodes) == {library_file}
    assert set(app.class_view.model.files) == set(app.call_view.model.files) == {library_file}
    assert set(app.call_view.layout.nodes) == {"api", "unused"}
    assert app.call_view.library_mode and app.call_view.root_usr is None
    assert app.call_view.root_var.get() == "Library API (2)"
    assert set(app.coverage_view.index.entry_map()) == {"api", "unused"}
    assert all(issue.file == library_file for issue in app.issue_view.issues)
    assert "file:examples/first/main.cpp" not in app.mind_map_view.tree.node_map()
    app.call_view.set_root("api")
    assert set(app.call_view.layout.nodes) == {"api"}
    app.call_view.from_main()
    assert set(app.call_view.layout.nodes) == {"api", "unused"}
    calls = []
    monkeypatch.setattr(app, "run_async", lambda *args: calls.append(args))
    selector.operate("run")
    assert not calls
    app.show(project)
    assert selector.selected == library and set(app.call_view.layout.nodes) == {"api", "unused"}
    candidate = DerivedModel.from_json(project.model.to_json())
    candidate.root = str(tmp_path / "candidate")
    candidate.add_entity(Entity("new_api", Kind.FUNCTION, "new_api", "new_api", library_file, 3))
    proposal = steps.Proposal(1, prompt.StepRequest(prompt.ARCHITECTURE, 1), tmp_path / "candidate",
                             model=candidate, delta=steps.compute_delta(project.model, candidate, []))
    app.show_proposal_calls(proposal)
    assert set(app.call_view.layout.nodes) == {"api", "unused", "new_api"}
    selector.choice_var.set(next(entry.label for entry in selector.choices if entry.usr == "first"))
    selector.select()
    assert states["Run"] == ["!disabled"] and not app.call_view.library_mode
    assert app.call_view.root_usr == "first" and set(app.call_view.layout.nodes) == {"first"}
    selector.clear()
    assert not app.call_view.library_mode


def test_library_without_callables_has_empty_call_graph(app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    project = opened(tmp_path)
    project.model.files["types.hpp"] = FileInfo("types.hpp")
    project.model.add_entity(Entity("Type", Kind.CLASS, "Type", "Type", "types.hpp", 1))
    target = executables.Target("types", "", tmp_path / "build", None,
                                frozenset({str(tmp_path / "types.hpp")}), kind="INTERFACE_LIBRARY")
    monkeypatch.setattr(executables, "read_targets", lambda _root: (target,))
    app.show(project)
    selector = app.executables
    selector.choice_var.set(next(entry.label for entry in selector.choices if entry.is_library))
    selector.select()
    assert set(app.class_view.layout.nodes) == {"Type"}
    assert not app.call_view.layout.nodes and app.call_view.root_var.get() == "Library API (0)"


def test_empty_trace_disables_playback_and_explains_missing_symbols(app_module, tmp_path, monkeypatch):
    from icoda_core import call_trace
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    view = app.call_view
    states = {}
    for label in ("Previous call", "Next call", "Reset"):
        monkeypatch.setattr(view.playback_buttons[label], "state", lambda value, label=label: states.update({label: value}))
    view.set_playback(call_trace.CallPlayback(call_trace.CallTrace(())))
    assert all(value == ["disabled"] for value in states.values())
    assert "No project calls resolved" in view.playback_status_var.get()
