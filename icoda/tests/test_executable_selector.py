"""Selector persistence, graph navigation, unsaved source protection, and operation recovery."""

from pathlib import Path
from types import SimpleNamespace

from icoda_core import clusters, executables, persistence, prompt, session, steps, views
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
    assert not app.view.layout.nodes and not app.class_view.model.files and not app.call_view.model.files
    assert "Select" in selector.choice_var.get() and "Select" in app.status.get()
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


def test_operations_guard_busy_and_send_failures_to_recovery(app_module, tmp_path, monkeypatch):
    app = app_module.App(app_module.tk.Tk(), config=persistence.UserConfig(), config_path=tmp_path / "c.json")
    app.show(opened(tmp_path))
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
    failures[0][1]["repair"]()
    assert repaired == ["Build failed: example compilation"]
    assert not app.panel.busy and not app.executables.running


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
    assert selector.selected is None and "Choose target" in selector.choice_var.get()
    selector.operate("run")
    assert len(results) == 1
    selector.choice_var.set(choice.label)
    selector.select()
    selector.operate("run")
    assert not results and selector.output.get("1.0", "end").strip() == "first output"
    assert persistence.ProjectStore(tmp_path).load_ui()["executable"] == [source.file, "first", "Debug"]


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
