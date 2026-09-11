"""The .icoda/ folder round trips and the user configuration."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from icoda_core import bodyhash, persistence, phases, session, specification, steplog
from icoda_core.clusters import Layout
from icoda_core.model import DerivedModel, Edge, EdgeKind, Entity, FileInfo, Kind


def test_legacy_project_migrates_additive_defaults_without_changing_saved_values(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.cache_dir.mkdir(parents=True)
    legacy_specification = {
        "schema_version": 2,
        "title": "Legacy München",
        "summary": "Keep this byte-for-byte:\nline two",
        "goals": ["Preserve α exactly"],
        "out_of_scope": ["No rewrite"],
        "not_allowed": ["No substitution"],
        "done_when": ["Values survive"],
        "use_cases": [{"id": "UC-7", "title": "Reopen", "description": "Load the old project"}],
        "requirements": [{"id": "R-9", "title": "Durable", "priority": "must",
                          "use_cases": ["UC-7"], "description": "Keep persisted values"}],
        "decisions": [{"id": "D-3", "title": "JSON", "rationale": "Existing format"}],
    }
    store.specification_path.write_text(json.dumps(legacy_specification, ensure_ascii=False), encoding="utf-8")
    legacy_state = {
        "phase": "implementation",
        "implementation_queue": ["c:@F@alpha#", "c:@F@β#"],
        "implementation_cursor": 1,
        "test_command": ["legacy-test", "--literal=ß"],
    }
    store.state_path.write_text(json.dumps(legacy_state, ensure_ascii=False), encoding="utf-8")
    legacy_model = {
        "root": "/legacy/project-ß",
        "libclang_version": "clang 15.0 exact",
        "files": [{"path": "src/über.cpp", "module": "legacy.core", "unit": "source",
                   "content_hash": "0011aabb", "errors": ["old warning"]}],
        "entities": [{"usr": "c:@F@β#", "kind": "function", "name": "β", "qualified_name": "legacy::β",
                      "file": "src/über.cpp", "line": 17, "end_line": 23, "parent": None,
                      "signature": "int β()", "brief": "Exact legacy brief", "satisfies": ["R-9"],
                      "template_params": ["T"], "is_definition": True, "exported": True,
                      "value": "0x00ff", "status": "tested"}],
        "edges": [{"kind": "calls", "source": "c:@F@β#", "target": "external:puts",
                   "file": "src/über.cpp", "line": 19, "label": "literal-edge"}],
        "externals": [{"library": "libc", "names": ["puts", "strlen"]}],
    }
    store.model_path.write_text(json.dumps(legacy_model, ensure_ascii=False), encoding="utf-8")

    loaded_specification = specification.load(store.specification_path)
    assert loaded_specification["code_profile"] == specification.default_code_profile()
    for key, value in legacy_specification.items():
        assert loaded_specification[key] == value

    state = store.load_state()
    assert state.phase is persistence.ProjectPhase.IMPLEMENTATION
    assert state.implementation_queue == ("c:@F@alpha#", "c:@F@β#")
    assert state.implementation_cursor == 1
    assert state.test_command == ("legacy-test", "--literal=ß")
    assert state.approved_approach == ""
    assert state.implementation_batch_size == 1
    assert state.mind_map.expanded == ()
    assert state.implementation_scope == "queue_order"
    assert state.implementation_override == ""
    assert state.auto_approve is False

    model = store.load_model()
    assert model is not None
    assert model.root == "/legacy/project-ß"
    assert model.libclang_version == "clang 15.0 exact"
    assert model.stale is False and model.stale_reason == ""
    assert model.files["src/über.cpp"] == FileInfo(
        "src/über.cpp", "legacy.core", "source", "0011aabb", ("old warning",))
    entity = model.entities["c:@F@β#"]
    assert (entity.name, entity.qualified_name, entity.file, entity.line, entity.end_line) == \
        ("β", "legacy::β", "src/über.cpp", 17, 23)
    assert (entity.signature, entity.brief, entity.satisfies, entity.template_params) == \
        ("int β()", "Exact legacy brief", ("R-9",), ("T",))
    assert (entity.is_definition, entity.exported, entity.value, entity.status, entity.body_hash) == \
        (True, True, "0x00ff", "tested", "")
    assert [(edge.kind.value, edge.source, edge.target, edge.file, edge.line, edge.label) for edge in model.edges] == [
        ("calls", "c:@F@β#", "external:puts", "src/über.cpp", 19, "literal-edge")]
    assert model.externals["libc"].names == ("puts", "strlen")


def test_open_project_refuses_truncated_state_and_reports_leftover_worktree(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.ensure()
    valid_state = store.state_path.read_bytes()
    store.state_path.write_bytes(valid_state[:-7])
    worktree = store.dir / "worktree"
    worktree.mkdir()
    (worktree / "unfinished.py").write_text("proposal = 'not promoted'\n", encoding="utf-8")

    message = (f"cannot open project: {store.state_path} contains invalid JSON; refusing to replace the persisted "
               f"state with defaults; leftover proposal worktree preserved at {worktree}")
    with pytest.raises(persistence.ProjectStateError, match="^" + re.escape(message) + "$"):
        session.open_project(tmp_path, persistence.UserConfig(), in_process=True)
    with pytest.raises(persistence.ProjectStateError, match="contains invalid JSON"):
        store.load_state()
    assert worktree.is_dir()
    assert (worktree / "unfinished.py").read_text(encoding="utf-8") == "proposal = 'not promoted'\n"


def test_open_project_reports_leftover_worktree_when_state_is_valid(tmp_path: Path, monkeypatch) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.ensure()
    worktree = store.dir / "worktree"
    worktree.mkdir()
    (worktree / "unfinished.py").write_text("proposal = 'not promoted'\n", encoding="utf-8")
    monkeypatch.setattr(
        session, "analyse", lambda root, config: session.AnalysisResult(None, None, ["analysis complete"]))

    opened = session.open_project(tmp_path, persistence.UserConfig(), in_process=True)

    assert opened.messages == ["analysis complete", f"leftover proposal worktree preserved at {worktree}"]
    assert worktree.is_dir()
    assert (worktree / "unfinished.py").read_text(encoding="utf-8") == "proposal = 'not promoted'\n"


def test_ensure_preserves_existing_unreadable_state(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.ensure()
    truncated_state = store.state_path.read_bytes()[:-7]
    store.state_path.write_bytes(truncated_state)

    store.ensure()

    assert store.state_path.read_bytes() == truncated_state


def test_project_store_creates_folder_and_round_trips(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.ensure()
    assert (tmp_path / ".icoda" / ".gitignore").read_text() == "cache/\nui.json\n"
    assert store.load_state() == persistence.ProjectState(persistence.ProjectPhase.SPECIFICATION)
    assert store.load_layout() == Layout() and store.load_ui() == {} and store.load_model() is None
    store.save_layout(Layout(names={"src/core": "Core"}, pins={"a.cpp": "src/core"}))
    store.save_ui({"zoom": 1.5, "view": "files"})
    model = DerivedModel(str(tmp_path))
    model.files["a.cpp"] = FileInfo("a.cpp")
    store.save_model(model)
    assert store.load_layout().names == {"src/core": "Core"}
    assert store.load_ui()["zoom"] == 1.5
    loaded = store.load_model()
    assert loaded is not None and "a.cpp" in loaded.files
    assert store.model_path.parent == store.cache_dir


def test_model_body_hash_round_trip_and_legacy_unknown(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    model = DerivedModel(str(tmp_path))
    model.add_entity(Entity("u:f", Kind.FUNCTION, "f", "f", "f.cpp", 1,
                            signature="int f()", body_hash="abc123"))
    store.save_model(model)
    loaded = store.load_model()
    assert loaded is not None and loaded.entities["u:f"].body_hash == "abc123"

    data = json.loads(store.model_path.read_text(encoding="utf-8"))
    data["entities"][0].pop("body_hash")
    store.model_path.write_text(json.dumps(data), encoding="utf-8")
    legacy = store.load_model()
    assert legacy is not None and legacy.entities["u:f"].body_hash == ""


def test_call_uncertainty_round_trip_and_legacy_default(tmp_path: Path) -> None:
    model = DerivedModel(str(tmp_path))
    model.add_edge(Edge(EdgeKind.CALLS, "u:caller", "u:virtual", uncertain=True))
    model.add_edge(Edge(EdgeKind.CALLS, "u:caller", "u:fixed"))

    loaded = DerivedModel.from_json(model.to_json())
    assert [edge.uncertain for edge in loaded.edges] == [True, False]

    data = json.loads(model.to_json())
    for edge in data["edges"]:
        edge.pop("uncertain")
    legacy = DerivedModel.from_json(json.dumps(data))
    assert [edge.uncertain for edge in legacy.edges] == [False, False]


def test_entity_declaration_file_round_trip_and_legacy_default(tmp_path: Path) -> None:
    model = DerivedModel(str(tmp_path))
    model.add_entity(Entity("u:paired", Kind.FUNCTION, "paired", "paired", "src/paired.cpp", 5,
                            declaration_file="include/paired.hpp"))

    loaded = DerivedModel.from_json(model.to_json())
    assert loaded.entities["u:paired"].declaration_file == "include/paired.hpp"

    data = json.loads(model.to_json())
    data["entities"][0].pop("declaration_file")
    legacy = DerivedModel.from_json(json.dumps(data))
    assert legacy.entities["u:paired"].declaration_file == ""


def test_project_store_reconciles_tested_status_after_external_body_edit(tmp_path: Path) -> None:
    edited_usr = "c:@F@edited#"
    matching_usr = "c:@F@matching#"
    unrelated_usr = "c:@F@unrelated#"
    original = bodyhash.body_hash("{ return 1; }")
    matching = bodyhash.body_hash("{ return 2; }")
    store = persistence.ProjectStore(tmp_path)
    model = DerivedModel(str(tmp_path))
    model.add_entity(Entity(edited_usr, Kind.FUNCTION, "edited", "edited", "app.cpp", 1,
                            body_hash=original))
    model.add_entity(Entity(matching_usr, Kind.FUNCTION, "matching", "matching", "app.cpp", 5,
                            body_hash=matching))
    model.add_entity(Entity(unrelated_usr, Kind.FUNCTION, "unrelated", "unrelated", "app.cpp", 9,
                            body_hash=bodyhash.body_hash("{ return 3; }")))
    store.save_model(model)
    log = steplog.StepLog(store.steps_path)
    log.append(steplog.StepRecord(
        0, "architecture", "approved", entities_added=[edited_usr, matching_usr, unrelated_usr]))
    log.append(steplog.StepRecord(
        1, "implementation", "approved", entities_changed=[edited_usr, matching_usr], test_ok=True,
        entity_body_hashes={edited_usr: original, matching_usr: matching}))

    before_edit = persistence.ProjectStore(tmp_path).load_model()
    assert before_edit is not None
    assert {usr: entity.status for usr, entity in before_edit.entities.items()} == {
        edited_usr: "tested", matching_usr: "tested", unrelated_usr: "stub"}
    changed = bodyhash.body_hash("{ return 4; }")
    assert changed != log.records()[1].entity_body_hashes[edited_usr]
    before_edit.entities[edited_usr].body_hash = changed
    store.save_model(before_edit)

    after_edit = persistence.ProjectStore(tmp_path).load_model()
    assert after_edit is not None
    assert {usr: entity.status for usr, entity in after_edit.entities.items()} == {
        edited_usr: "implemented", matching_usr: "tested", unrelated_usr: "stub"}


def test_project_phase_round_trip_and_legacy_defaults(tmp_path: Path) -> None:
    fresh = persistence.ProjectStore(tmp_path / "fresh")
    expected = persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION, ("u:leaf", "u:caller"), 1,
                                        approved_approach="Use std::ranges.", implementation_batch_size=3)
    fresh.save_state(expected)
    assert fresh.load_state() == expected

    imported = persistence.ProjectStore(tmp_path / "imported")
    imported.root.mkdir()
    (imported.root / "CMakeLists.txt").write_text("project(imported)\n", encoding="utf-8")
    imported.state_path.parent.mkdir()
    imported.state_path.write_text('{"older_field": true}', encoding="utf-8")
    assert imported.load_state() == persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION)

    before_queue = persistence.ProjectStore(tmp_path / "before-queue")
    before_queue.state_path.parent.mkdir(parents=True)
    before_queue.state_path.write_text('{"phase": "implementation"}', encoding="utf-8")
    legacy = before_queue.load_state()
    assert legacy == persistence.ProjectState(persistence.ProjectPhase.IMPLEMENTATION)
    assert legacy.approved_approach == ""
    assert legacy.implementation_batch_size == 1

    generated = persistence.ProjectStore(tmp_path / "generated")
    generated.root.mkdir()
    (generated.root / "CMakeLists.txt").write_text("project(generated)\n", encoding="utf-8")
    generated.specification_path.parent.mkdir()
    generated.specification_path.write_text("{}", encoding="utf-8")
    assert generated.load_state().phase == persistence.ProjectPhase.ARCHITECTURE


def test_auto_approve_round_trip_and_payload_without_field_defaults_off(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.save_state(persistence.ProjectState(
        persistence.ProjectPhase.IMPLEMENTATION, auto_approve=True))
    assert store.load_state().auto_approve is True

    payload = json.loads(store.state_path.read_text(encoding="utf-8"))
    payload.pop("auto_approve")
    store.state_path.write_text(json.dumps(payload), encoding="utf-8")

    assert store.load_state().auto_approve is False


def test_project_phase_transitions_are_validated_persisted_and_logged(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.ensure()
    started = phases.transition(store, persistence.ProjectPhase.ARCHITECTURE)
    approved = phases.transition(store, persistence.ProjectPhase.IMPLEMENTATION)
    assert store.load_state().phase == persistence.ProjectPhase.IMPLEMENTATION
    assert (started.previous_phase, started.title) == ("specification", "specification completed")
    assert (approved.previous_phase, approved.title) == ("architecture", "architecture approved")
    assert [record.decision for record in steplog.StepLog(store.steps_path).records()] == [
        "phase_transition", "phase_transition"]

    with pytest.raises(persistence.PhaseTransitionError, match="illegal project phase transition: implementation"):
        phases.transition(store, persistence.ProjectPhase.SPECIFICATION)
    assert store.load_state().phase == persistence.ProjectPhase.IMPLEMENTATION
    assert len(steplog.StepLog(store.steps_path).records()) == 2


def test_user_config_round_trip_and_recent_projects(tmp_path: Path) -> None:
    config = persistence.UserConfig()
    for name in "abcdefghijkl":
        config.remember_project(tmp_path / name)
    config.remember_project(tmp_path / "c")
    assert len(config.known_projects) == persistence.MAX_KNOWN_PROJECTS
    assert config.known_projects[0].endswith("/c") and config.last_project == config.known_projects[0]
    config.libclang, config.model, config.editor = "/x/libclang.dylib", "claude-opus-5", "code"
    config.save(tmp_path / "cfg" / "config.json")
    loaded = persistence.UserConfig.load(tmp_path / "cfg" / "config.json")
    assert loaded == config
    assert persistence.UserConfig.load(tmp_path / "missing.json") == persistence.UserConfig()


def test_config_path_per_platform(tmp_path: Path) -> None:
    assert persistence.config_path("darwin", {}, tmp_path) == tmp_path / "Library/Application Support/ICODA/config.json"
    assert persistence.config_path("win32", {"APPDATA": "C:/Users/h/AppData/Roaming"}, tmp_path) == \
        Path("C:/Users/h/AppData/Roaming/ICODA/config.json")
    assert persistence.config_path("linux", {}, tmp_path) == tmp_path / ".config/icoda/config.json"
    assert persistence.config_path("linux", {"XDG_CONFIG_HOME": "/xdg"}, tmp_path) == Path("/xdg/icoda/config.json")


def test_user_config_libclang_preference_round_trip_and_legacy_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    persistence.UserConfig(preferred_libclang="/opt/llvm/lib/libclang.so").save(config_path)

    assert persistence.UserConfig.load(config_path).preferred_libclang == "/opt/llvm/lib/libclang.so"

    config_path.write_text('{"provider": "codex", "model": "gpt"}', encoding="utf-8")
    legacy = persistence.UserConfig.load(config_path)
    assert legacy.preferred_libclang is persistence.LEGACY_LIBCLANG_PREFERENCE
    assert (legacy.provider, legacy.model) == ("codex", "gpt")
