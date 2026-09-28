# ICODA VS Code migration: delivery and parity record

Inspected 2026-09-27 for M0/G01, against
`fde592e3636dd19c9e84c51ffb43337d395fc717`. Paths below are relative to `icoda/`,
except where explicitly described as repository-root paths. Goal IDs refer to
[VSCODE_EXTENSION_PLAN.md](../VSCODE_EXTENSION_PLAN.md), not the older desktop
milestones in `ICODA_PLAN.md`.

Reconciled against brief sections 6–8 on 2026-09-28 (iteration 59).
**M1 is delivered on the tested Linux fixtures; the full migration is Partial.**
The first usable analysis/Call View/source/playback journey is distinct from
completion of G01–G18. Later P01–P11 work is reflected in the current matrix and
ledgers below. Remaining implementation and qualification are explicit; none is
an agreed removal from the brief. Windows, macOS and the named hardware/provider
journeys remain Not qualified.

The desktop matrix, milestone/goal/AT ledgers and final **iteration-59 verification**
section are authoritative. Earlier implementation sections are dated history;
their pass counts and pending statements do not describe this run. Protocol
version remains 1. This review preserves all accumulated migration changes and
adds only the two requested P11 regression checks and documentation corrections.

## Baseline and reproduction

| Item | Observation before edits |
|---|---|
| Checkout | AI-Loop job worktree `J20260927-170326-588902`; `git rev-parse HEAD` returned `fde592e3636dd19c9e84c51ffb43337d395fc717`. |
| Working tree | `git status --short` returned no entries: no tracked modifications or untracked files to preserve. This repository is not committed or merged by this task. |
| Instructions | Read repository-root `AGENTS.md`. No nested `AGENTS.md` or `CLAUDE.md` exists under `icoda/`. |
| Python | CPython 3.12.3, GCC 13.3.0, base prefix `/usr`; Linux `7.0.0-31-generic`, x86_64, glibc 2.39. |
| Environment | Reused the prepared `icoda/.icoda-venv` in the main AI-Loop checkout, outside this job worktree (`../../AI-Loop/icoda/.icoda-venv/bin/python` relative to the job repository root). This identifies the observed environment, not a required installation path. No packages were installed or upgraded. The ordinary shell has `/usr/bin/python3` but no `python`; the virtual environment's `bin` was prepended to PATH for each test command. |
| Packages | pytest 9.1.1, pytest-cov 7.1.0, clang bindings 21.1.7, networkx 3.6.1, jsonschema 4.26.0, Ruff 0.16.8, mypy 2.3.1. These versions agree with the corresponding entries in `constraints.txt`. |
| Test scope | Commands run from this worktree's `icoda/`. `pyproject.toml` sets `testpaths = ["tests"]` and `pythonpath = ["."]`; `tests/conftest.py` also puts this checkout first on `sys.path`. The sibling AI-Loop suite is independent. |
| Tk environment | `ICODA_TK_STUB` was unset; `tests/conftest.py:16` defaults it to stub behavior. A real display was available as `DISPLAY=:10.0`; pytest results are still predominantly Tk-stub evidence. |

To reproduce with an already prepared environment, set `ICODA_TEST_PYTHON` to its
Python executable, then run from `icoda/`:

```bash
# Set this to your prepared environment, locally or outside the worktree.
ICODA_TEST_PYTHON=/path/to/prepared/venv/bin/python
PATH="$(dirname "$ICODA_TEST_PYTHON"):$PATH" python -m pytest -q
```

The unmodified-tree command exited **1** with:

```text
FAILED tests/test_verify.py::test_evidence_documents_match_current_module_inventory
1 failed, 902 passed, 20 skipped in 31.97s
```

### Reproducible pre-existing pytest failure

`tests/test_verify.py:156` counts modules and compares the counts against
`docs/GAP_ANALYSIS.md` and `docs/RELEASE_MATRIX.md`. The assertion at line 170 fails
first on `GAP_ANALYSIS.md` at base `fde592e`. Both documents then claimed 78 Python
test modules (71 ordinary plus seven acceptance scripts), while that base had
**80** (73 plus seven). Its count of 48 core Python modules was correct. Re-running only
the failing case on the unmodified tree gave **1 failed in 0.14s**:

```bash
"$ICODA_TEST_PYTHON" -m pytest -q \
  tests/test_verify.py::test_evidence_documents_match_current_module_inventory
```

Iteration 8 corrected both evidence inventories to **81 = 74 + 7**, including
`test_service.py`, and 49 core modules including `service.py`. The two-module
defect was pre-existing at base `fde592e`, as the detached-base test reproduced.
The corrected inventory test passed with the other verification tests (10 passed
in 0.23s). Adding cases to an existing module does not change these counts.

The 20 skipped cases are prerequisite/platform limitations, not passes. The
post-change `-rs` run identifies ten sample-project build-dependent cases, one
case with no matching compiler beside libclang, three requiring unversioned
`clang++`, and six native Windows cases. This Linux host has versioned Clang
discovery even though `clang++` is absent from ordinary PATH; missing that alias
must not be reported as proof that Clang is uninstalled.

### Desktop launch and verification instructions

Supported repository launch commands, from `icoda/`, are `./icoda.bash
[project-directory]` on Linux/macOS and `icoda.cmd [project-directory]` on Windows.
They validate Python, Tkinter, tools, and a prepared `.icoda-venv`, then run
`icoda.py`. They do **not** install dependencies. The local worktree had no
`.icoda-venv`; the equivalent direct entry command with the external environment
is `"$ICODA_TEST_PYTHON" icoda.py [project-directory]`. With no argument, `main`
reopens the remembered project when it exists (`icoda.py:1864`).

A real-Tk, empty-window smoke check passed with Tcl/Tk **8.6.14**, using isolated
configuration and no project/provider operation. Reproduce from `icoda/` on a
working display:

```bash
"$ICODA_TEST_PYTHON" - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import icoda
from icoda_core import persistence

with TemporaryDirectory(prefix="icoda-m0-launch-") as temporary:
    root = tk.Tk()
    app = icoda.App(root, config=persistence.UserConfig(),
                    config_path=Path(temporary) / "config.json")
    root.update()
    assert app.project is None and root.winfo_exists()
    print("Desktop empty-window smoke: PASS; Tcl/Tk", root.tk.call("info", "patchlevel"))
    app.close()
PY
```

This establishes window construction/close, not full desktop or VS Code UI
acceptance. No Windows launch or ViennaVulkanEngine run was performed for M0.

Read `README.md`, `HANDBOOK.md`, `ICODA_PLAN.md`, `EVOLUTION.md`,
`docs/RELEASE_MATRIX.md`, the recent `docs/VERIFY_LOG.md` entries, and the verifier
itself. Also read repository-root `README.md` and `ai-loop/docs/HANDBOOK.md`;
the latter describes a separate application's specification lifecycle and must
not become an ICODA dependency. The full ICODA gate is:

```bash
ICODA_VERIFY_PYTHON="$ICODA_TEST_PYTHON" ./verify.bash --artifacts-root /tmp/icoda-verification
```

`tests/verify.py` currently includes diff checking, Ruff, mypy, byte compilation,
provider qualification, real-provider acceptance, sample build/CTest, pytest with
85% branch-coverage threshold, fresh analysis, and three real-Tk GUI programs
(general, recovery, editor). This is more than the older handbook's ten-stage
list. Real-provider acceptance consumes provider usage; the explicit
`--allow-missing-real-provider` option only waives missing credentials, not a
failed provider run. Historical gate counts are not the baseline for this task.

## Baseline behavior versus historical descriptions (M0)

| Historical claim | Current code and migration consequence |
|---|---|
| Python is a later milestone (`EVOLUTION.md`, `ICODA_PLAN.md`). | `python_analysis.parse_project` uses `ast` without importing/executing project code; `session.analyse` dispatches by language. Python generation and gates already exist. Preserve them. |
| Launchers create environments/install tools; ICODA has no editor. | `icoda.bash`/`icoda.cmd` validate only; `icoda_gui/source_editor.py` supplies an editor with unsaved-buffer protection. VS Code will replace that presentation, not discard its safeguards. |
| Compiler database is simply the newest one. | `analysis.find_compile_commands` prefers a Clang database before comparing modification times. Retain compiler-aware selection. |
| File layout is always circular, Call groups use force placement. | `icoda.py:192` automatically enters cluster overview when fit would shrink/overlap labels. `diagram_partition.py` bounds thematic groups; force layouts apply inside File/Class groups. `call_view.py` now uses `views.layout_call_view` for the layered waterfall. |
| Library Call View starts from all functions. | `views.library_roots` prefers exported/header declarations, then roots of call components, including recursive components. Access control/symbol visibility is not fully modeled. |
| Seven provider templates imply seven supported providers. | `providers.json` enables Claude and Codex; the other templates are disabled. Preserve discovery, CLI authentication, and qualification boundaries. |
| Every failed analysis necessarily marks the retained model stale. | C++ parse errors do this in `analysis.parse_project`; `session._derive_model` clears previous stale state before its missing-libclang/missing-database fallbacks. Child failure can also leave cached data without a fresh stale marker. G05 needs explicit stale-result handling; do not infer freshness from cache presence. |
| Python's module docstring says the edge schema has no uncertainty field. | `model.Edge.uncertain` exists; C++ virtual-call analysis sets it. Python currently omits unresolved dynamic calls and emits resolved calls with `uncertain=False`. Preserve this distinction instead of inventing confident edges. |
| Historical release counts qualify today's tree/platforms. | The release matrix is dated 2026-09-11; later verification notes describe later desktop changes. Neither qualifies the future extension or replaces the current failing baseline. |

## Desktop feature/parity matrix

Final status: **Delivered** means the stated behavior has implementation and
cited evidence, with the test layer and qualification limits named. **Partial**
means implemented portions have evidence, with remaining work and its reason
listed explicitly. A deferred portion is not an agreement to remove that scope.
**Not qualified** means the named platform/project run requires an unavailable
host or qualification environment. Every row has one disposition; there are no
unexplained omissions. The AT ledger separately records native journey coverage. Core and GUI filenames are relative to `icoda_core/` and
`icoda_gui/`; `../icoda.py` identifies the desktop shell. Test paths below are
relative to `icoda/`; Node suites are under `vscode/src/test/`. Dated run artifacts
refer to this job's system-temp report directory, never repository attachments.

| Feature and behavior to preserve | Core owners | Desktop owners | Final status | Delivery evidence / reason and follow-up |
|---|---|---|---|---|
| Open/create/reload C++ and Python projects; compiler commands, cache, errors, entity identities, external dependencies | `session.py`, `analysis.py`, `python_analysis.py`, `windows_analysis.py`, `model.py`, `generator.py` | `../icoda.py` (`open_project`, `_analyse`, `show`, `new_project`) | **Delivered** | G03/G05/G14 deliver opening, analysis, retained stale models and explicit workspace/target identity (`tests/test_service.py`, `projectSession.test.ts`, G16 `suite.ts` analysis case). Gap 6 delivers protocol v1 `project.create` and native `icoda.newProject`: shared preparation/specification save/generation, new child-folder validation, trust/session guards and explicit Open in New Window / Add to Workspace. Verification (2026-09-28, gap 6): `tests/test_service.py::test_project_create_shared_skeleton_state_and_session_preserved`, `test_project_create_refuses_existing_targets_without_changes`, `test_project_create_requires_trust_before_writing`, `test_project_create_rejects_invalid_name`, `test_project_create_rejects_path_escape`, `test_project_create_rejects_stale_session_before_writing`; `tests/test_app.py::test_desktop_new_project_shared_creation_preserves_existing_files`; `lifecycle.test.ts` checks `newProject is discoverable and creates through the shared service without switching projects`, `newProject native inputs validate required values and cancellation never starts the backend`, and `newProject trust guard runs before native pickers or backend startup`, plus its existing target/path and late-reply cases. See the gap-6 contract below. Automatic post-save build/reanalysis remains unchanged. |
| File View: typed dependency summaries, external libraries, source selection, initial gray cluster overview | `views.py`, `clusters.py`, `diagram_partition.py`, `force_layout.py` | `../icoda.py:79` (`FileViewCanvas`), `graph_canvas.py` | **Delivered** | G10/G15: shared typed relations, external nodes, source selection and automatic gray overview. Evidence: `tests/test_service.py::test_file_overview_expansion_reveal_and_relationship_counts`, `fileView.test.ts`, and the 81-file automated fixture. The historical G10/It12 cached-model captures are narrower evidence; a ViennaVulkanEngine large-project run remains **Not qualified** in this review (AT02). |
| Clustering: deterministic bounded communities/themes, pins/names, expand group, return to overview, reveal file, saved layout | `clusters.py`, `diagram_partition.py`, `expansion.py`, `views.py`, `persistence.py` | `../icoda.py` (`fit`, `open_group`, `back_to_overview`, `_apply_cluster_layout`), `graph_canvas.py`, `class_view.py` | **Delivered** | P01/G10/G14 (2026-09-28, iteration 45): File View now assigns/unpins individual files through shared `clusters.pin_file`/`unpin_file`, navigates saved parents and bounded children, and restores target-scoped levels/cameras through `ProjectStore`. Existing deterministic grouping, names/pins and typed summaries remain shared. Python: `tests/test_service.py::test_p01_file_assignment_reuses_core_and_survives_restart`, `test_p01_saved_parent_drill_in_and_reveal_keep_bounded_children`, `test_p01_file_camera_state_persists_per_target_and_preserves_ui`, `test_p01_assignment_and_camera_validation_never_write_on_invalid_requests`, plus existing cluster and desktop agreement cases. Node: five `P01` checks in `fileView.test.ts` cover routing/validation, native picker cancellation and stale choices, nested camera restoration and stale state replies/same-target reselection. Native VS Code 1.96.4: `integration/suite.ts` check `P01 File View assignment command, saved parents, source and cameras survive reopen and restart` drives registered `icoda.assignFileCluster`, `icoda.openFileView`, `icoda.revealInFileView` and `icoda.restartBackend` against the real service. See the P01 v1 contract below; evidence is Linux, not VVE/Windows qualification. |
| Call View: layered graph, main/library roots, depth/callers, recursion/shared calls, uncertainty, statuses and proposal outlines | `views.py`, `model.py`, `graph_filter.py`, `node_status.py` | `call_view.py`, `graph_canvas.py`, `../icoda.py` (`show_proposal_calls`) | **Delivered** | P02/G07/G13 (2026-09-28, iteration 46): shared roots/layout, recursion, uncertainty, statuses and recorded nodes remain available; checked proposal models now supply core added/changed outlines in a separate native-command Call View, with worktree source navigation and independent camera/root state. Python: `tests/test_service.py::test_p02_candidate_call_graph_and_source_use_checked_core_delta` (added/changed cases), `test_p02_candidate_source_expires_after_rejection`. Node: `callViewModel.test.ts` P02 checked-root/playback-preservation and stale-candidate cases. Native: `integration/suite.ts` check `P02 proposal command shows core delta and candidate source while retaining project playback` drives `icoda.showProposalCallView`, recovery, review, rebuild and rejection, verifies dirty candidate buffers and approval refusal, and retains the project trace/root/camera. See the P02/P05 v1 contract below. Controlled candidates on Linux; real-provider qualification remains separate. |
| Recorded trace playback: resolved entries, grouped repeats/caller counts, Into/Over/Out, Previous, Reset, graph seek | `call_trace.py` (`load_trace`, `CallPlayback`), `toolchain.py`, `process.py` | `call_view.py`, `../icoda.py:753` (`load_call_trace`) | **Delivered** | G03/G08/G15/G16: one shared CallPlayback cursor, invocation-safe Into/Over/Out, Previous/Reset/seek, counts and six-control overflow toolbar. Evidence: `tests/test_call_trace.py`, `tests/test_trace_stepping.py`, `tests/test_service.py::test_trace_b_to_c_d_e_and_synchronized_state`, `ui.test.ts`, and G16 `suite.ts` AT05/AT09. Native overflow interaction remains Not qualified under AT15. |
| Class View: member signatures/status, inheritance, composition/aggregation/usage, bounded groups | `class_view.py`, `views.py`, `diagram_partition.py`, `force_layout.py` | `class_view.py`, `graph_canvas.py` | **Delivered** | G11a/G15: shared class/member panels, status/signatures and counted relationships with bounded groups. Evidence: `tests/test_service.py::test_class_view_real_cpp_python_agrees_with_core_and_desktop`, `classView.test.ts`, and It13 native class/member source navigation (`it13-ui-evidence.json`, light/dark captures). The core visibility/attribute limitations below remain explicit. |
| Mind Map: project/cluster/file/class/function hierarchy, expansion, requirements, status, introducing step | `mind_map.py`, `views.py`, `steplog.py`, `persistence.py` | `mind_map_view.py`, `graph_canvas.py`, `../icoda.py` (`select_step`) | **Delivered** | P03/G11b (2026-09-28, iteration 50): shared hierarchy, persisted expansion, requirements/status, introducing metadata and source navigation remain delivered (`tests/test_service.py::test_mindmap_shared_core_desktop_and_persisted_expansion`, `mindMap.test.ts`, historical `it14-ui-evidence.json`). Open Step now opens the selected node's actual introducing record through shared core history selection and the identity-checked service. Passing new tests: Python `tests/test_service.py::test_p03_mindmap_step_opens_shared_history_and_rejects_stale_identity`; Node `mindMap.test.ts` — `P03 Mind Map opens only current backend history and drops stale replies`; native VS Code 1.96.4 `integration/suite.ts` — `P03 Mind Map opens introducing history and source with session guards`. Missing/undone history, stale replies and native output disposal are covered; graph selection/camera and native source remain synchronized. See the P03 contract and iteration-50 Linux evidence below. |
| Shared graph interactions: filter, exact/descendant namespaces, neighborhood dimming, expansion, zoom/pan/fit, tooltips, context actions | `graph_filter.py`, `expansion.py`, `node_status.py`, `views.py`, `guidance.py` | `graph_canvas.py`, `zoom_controls.py`, `tooltip.py`, `../icoda.py` | **Partial** | P04 (iteration 52): all four webviews share the compact **Focus** popover, bounded `graphOptions` messages, `GraphInteractions` routing and one SVG decorator. Read-only protocol v1 `graph.interactions` reuses Python `graph_filter.parse/derive` and `node_status` for name/kind/status/coverage/staleness/cluster filters, exact `namespace:app`, descendant `namespace:app::*`, typed incident-edge filters and 0–12-hop neighborhood dimming. File/class focus includes their entities; source aliases resolve in Python. Candidate/recording roots and session/revision/target guards apply; stale replies are discarded. Selection, layout/root/camera, playback counters/semantics and the six-button trace toolbar remain unchanged. Focus filtering keeps expandable gateways, Call roots and selection visible; Focus settings are panel-local, and Call’s existing quick substring filter remains available. Existing zoom/pan/Fit, tooltips, group/tree expansion and keyboard access remain delivered. Passing tests: Python `test_p04_graph_interactions_match_desktop_filters_and_preserve_views`, `test_p04_graph_interactions_validate_identity_and_keep_playback` (`tests/test_service.py`), `test_p04_aggregate_focus_uses_all_file_entities_and_preserves_usr_policy` (`tests/test_graph_filter.py`); Node `graphInteractions.test.ts` — `P04 graph options use one strict schema in all four webviews`, four model-routing checks, `P04 shared interactions discard superseded project graph and disposed replies`, `P04 shared interactions route candidate and recording identities and expose local errors`, `P04 shipped shared controls decorate nodes edges and keyboard focus without moving the scene`; native VS Code 1.96.4 `integration/suite.ts` — `P04 shared graph filters and neighborhoods preserve native source playback and cameras`. Current regression results are in the iteration-59 verification section; original P04 native evidence is retained under `iteration52/`. **Deferred:** shared hierarchy/external-name expansion and aggregate pruning need a common expansion contract; reachability coloring needs a separate appearance/legend policy; node workflow/test context actions need their own proposal/test-gate routing. Those independent features exceed this interaction slice. Accessibility/platform qualification remains AT15; no Windows/VVE claim. |
| Source lookup/editor: relocated files, suffix-ranked ambiguity, project/worktree boundaries, generated sources, unsaved edits, save-triggered analysis | `source_edit.py` (`find_source`, `source_path`, `relative_path`, `Document`), `source_watch.py`, `session.py` | `source_editor.py`, `../icoda.py:1744` (`open_editor`), `../icoda.py:1779` (`_source_changed`) | **Delivered** | P05/G06/G13 (2026-09-28, iteration 46): shared relocated/ambiguous/missing-source handling and native dirty-buffer reuse now include checked candidate graph roots; saved and external created/changed/deleted sources trigger debounced analysis with session, busy, unsaved-document and pending-proposal guards. Python: `tests/test_service.py::test_p05_automatic_analysis_refreshes_disk_changes_and_guards_unsaved`, `test_p05_automatic_analysis_preserves_pending_review`, `test_p05_core_snapshot_marks_mid_analysis_changes_stale`, plus P02 candidate resolution and existing source-boundary cases. Node: five P05 cases in `sourceChanges.test.ts` and `sourceNavigation.test.ts` cover deferred retries, revision/selection/disposal races, deletion boundaries and checked candidate roots. Native: `integration/suite.ts` check `P05 saved and external source changes refresh analysis without overwriting dirty editors` drives registered `icoda.analyseProject` then real editor/save/filesystem events; the P02 command check covers candidate source and approval invalidation. `icoda.autoAnalyse` defaults on and can be disabled to retain recorded playback while editing. See the P02/P05 contract below. |
| Whole Project/executable/library selection, configuration/artifact identity, dependency-scoped models | `executables.py`, `cmake.py`, `persistence.py` | `executable_selector.py`, `../icoda.py:1383` (`executable_model`) | **Delivered** | G03/G05/G09/G14: shared target catalog, saved selection and dependency projection preserve the whole model/cache. Evidence: `tests/test_service.py::test_targets_use_real_discovery_without_building_and_have_stable_ids`, `test_target_selection_projects_dependencies_and_preserves_whole_model`, `projectSession.test.ts`, `lifecycle.test.ts` restart/restore case. |
| Target refresh, build, run, stop/output, instrumented recording, full/targeted tests | `executables.py` (`operate`), `cmake.py`, `instrumentation.py`, `steps.py`, `test_selection.py`, `process.py` | `executable_selector.py`, `step_controller.py`, `../icoda.py` (`build_project`) | **Partial** | P06 (2026-09-28, iteration 53): **Build Target** now accepts **Whole Project**, delegating to shared `steps.build_project` (CMake configure/build or Python compileall). **Run All Project Tests** (`icoda.testProject`, advertised cancellable `tests.run`) delegates to `steps.gate_commands` / `test_project`: C++ uses the persisted argument-array `test_command`; Python uses the Code Profile `test_runner`, with the backend runtime's bin directory in the child environment. Tests always run the configured full project suite, even with a target selected; they retain the selected target/model/playback and do not record proposal approval evidence. Both checks operate on saved files, stream commands/stdout/stderr to ICODA Output, and share native progress/Cancel, bounded execution and process-tree cleanup. `build.run` with null target and `tests.run` return an additional strictly checked `{kind, ok:true, output}` result; failed/missing checks return `build_failed` / `test_failed`, unavailable executables return `missing_tool` naming the actual command, and cancellation returns `cancelled`. All five target-operation service routes now require literal `trusted:true` in addition to frontend Workspace Trust, strict params and session/revision/target validation. Existing selected-target/configuration refresh/build/run/record and isolated traces remain delivered; no global PATH change or instrumentation-tree policy change. Passing Python tests in `tests/test_service.py`: `test_p06_operations_validate_trust_and_params_before_tools`, `test_p06_whole_build_uses_shared_gate_and_child_environment`, `test_p06_python_build_and_full_pytest_failure_recover_without_cpp_tools`, `test_p06_full_tests_use_configured_arguments_report_missing_tool_and_preserve_target`, `test_p06_full_tests_cancellation_keeps_service_usable`. Passing Node `targetOperations.test.ts`: `P06 all five trusted target commands register the manifest's operation and title`, `P06 full checks validate messages and preserve the selected model through failures and stale replies`; existing real build/record/cancellation tests remain passing. Native VS Code 1.96.4 `integration/suite.ts`: `P06 Whole Project build and full CTest failure cancellation and recovery preserve target and build artifacts` drives the real commands/service against a temporary copy of `vscode/src/test/fixtures/cpp`, runs the compiled demo through CTest, observes a failing check, cancels a live test child, retries successfully, and compares ordinary cache/database/executable bytes and mtimes. Existing `AT11 records the selected executable in isolation and steps real calls in the graph and editor` still verifies recording isolation and playback. `integration/untrusted.ts` now includes the new command and all five service trust refusals. Current regression results and the P06 native evidence rerun are in the iteration-59 verification section. **Deferred:** targeted/per-target tests need a shared mapping from selected entities/targets to runner-specific selectors (the existing append-only selection helper does not establish CTest test-name mappings); automatic analysis after refresh/Whole Project build needs coordinated model publication and cancellation, so use **Analyse Project** explicitly. No Windows qualification is claimed. |
| P07 — Python/runtime and CMake/Ninja/Clang/libclang/symbolizer discovery; Visual Studio SDK environment | `toolchain.py`, `cmake.py`, `session.py`, `windows_analysis.py`, `call_trace.py`, `agent.py` | `../icoda.py` (`configure_windows_toolchain`, libclang chooser), `provider_field.py`; launchers outside GUI package | **Not qualified** | G04/G09/G17 deliver runtime/tool overrides, inspection, discovered child environments and actionable missing-tool errors (`toolchain.test.ts`, `pythonRuntime.test.ts`, `tests/test_windows_startup.py`, G17 installed smoke). Windows SDK/bundled-tool discovery is simulated only, and no extension libclang chooser is supplied (P07). AT10 is **Not qualified** because it needs a Windows desktop host outside a developer prompt; macOS is also unqualified. The missing native libclang chooser is explicitly deferred because it needs configuration UI beyond the delivered discovery/overrides. |
| Specification schema, Code Profile, validation/save/reread, skeleton creation, phase changes | `session.py`, `specification.py`, `specification.schema.json`, `generator.py`, `phases.py`, `implementation_queue.py`, `persistence.py` | `spec_editor.py`, `../icoda.py`, `step_controller.py` | **Delivered** | P08/G12a (2026-09-28, iteration 48): native saves use shared desktop skeleton/phase operations, build new skeletons, reanalyse existing projects, and refresh the model, diagrams, targets and phase. Build/tool/analysis failures retain the saved specification and publish a stale model with a structured error. Python: `tests/test_service.py::test_p08_save_builds_shared_skeleton_without_overwriting`, `test_p08_existing_project_save_reanalyses`, `test_p08_post_save_failure_keeps_spec_and_marks_stale`, `test_p08_post_save_guards_preserve_files`, plus existing `test_specification_core_agreement_and_validated_save` and `test_phase_core_gates_and_queue_agree`. Node: `specification.test.ts` check `P08 saves refresh model, targets, phase and reread while retaining structured post-save failures`, existing schema/profile/validation/draft checks, and `backendClient.test.ts` real-service specification round trip. Native VS Code 1.96.4: `integration/suite.ts` check `P08 native specification save builds a bare project, refreshes edits and retains failed-build saves` uses temporary projects and real editor Save/reopen, Python build/analysis and Call View refresh. See the P08 contract below; Linux evidence does not qualify Windows toolchains. |
| Provider/model selection, CLI auth, architecture proposals, approach-before-code workflow, focus/context, persisted queue/batches | `agent.py`, `persistence.py`, `providers.json`, `provider_check.py`, `prompt.py`, `response.py`, `steps.py`, `implementation.py`, `implementation_queue.py`, `grouping.py` | `provider_field.py`, `step_controller.py`, `step_panel.py` | **Partial** | P09 (2026-09-28, iteration 55 verification of iteration 54): native Select Provider/Model now offers enabled providers (including missing executables for configuration), registry model suggestions and custom model IDs, a command/absolute executable path, effective resolved paths and provider CLI login hints. Protocol v1 `providers.select` validates exact parameters, requires literal trust and current project/target/revision, refuses active provider jobs, saves the desktop-compatible `.icoda/ui.json` provider/binary/model and ICODA `UserConfig` provider/model default, and stops automatic continuation when the selection changes. Per-provider models are remembered during the project session; project choices survive reopen/restart and custom binaries stay project-local. `providers.list` and selection never execute a provider or read/store credentials; local auth markers remain advisory, and actual authentication failures retain `provider_failed` with the shared CLI diagnosis. Missing selection paths return `provider_failed`; existing invocation-time `provider_unavailable` now identifies the provider, executable and login hint. Source/graph browsing remains usable. Discovery/invocation stays in Python; the identifier-only VS Code setting is a compatibility mirror. Shared project UI provider/binary/model state is authoritative for the picker, tree and every workflow; a stale or manually edited workspace setting cannot override it. Passing Python: `tests/test_service.py::test_p09_provider_custom_selection_persists_and_invokes_shared_core`, `test_p09_provider_selection_rejects_invalid_messages_without_writes`, `test_p09_provider_missing_and_failed_leave_source_and_graph_usable`, `test_p09_provider_selection_guards_identity_busy_and_remembers_models`, `test_p09_unauthenticated_provider_keeps_existing_cli_diagnosis`. Python service tests now pin `persistence.config_path()` to pytest temporary storage in both the parent and every service child, including macOS; Node picker tests mock requests without persistence, and the P09 EDH shim pins its config under the temporary report directory. Authentication text is intentional existing shared behavior: `recovery.diagnose` and `invoke` are unchanged from the starting commit and iteration 54. Editing conversations keep the authentication diagnosis/detail plus the existing no-retry/Open CLI guidance; read-only failures retain the provider CLI login text. Desktop `tests/test_recovery.py` and `tests/test_troubleshooting.py` pass. Passing Node `workflow.test.ts`: `P09 workflows inherit the project provider when the workspace setting disagrees`. Passing Node in `specification.test.ts`: `P09 provider choice parsing rejects credentials controls and malformed custom selections`; `P09 provider selection routes through the service and renders effective path custom model and CLI login`; `P09 provider selection drops stale replies and refuses untrusted disposed or invalid writes`; `P09 native provider picker cancels and rechecks project trust before persistence`. Passing VS Code 1.96.4 `integration/suite.ts`: `P09 provider picker persists custom executable and model while missing providers leave browsing usable`, using the controlled `fake_workflow.py` provider through the real service, native commands and editor; it verifies persisted project/user selection after restart, a conflicting workspace setting, `provider_failed` for a missing executable and continued Call View/source navigation. G12a/G12b/G13 architecture/approach/code, context, cancellation and It33 persisted queue scope/grouping/batches/automatic approval remain delivered (`workflow.test.ts`, queue service tests and `tests/test_step_gui.py::test_desktop_queue_settings_use_shared_updates_and_preserve_controls`). **Deferred:** queue target override needs separate native queue controls and validation; real-provider/native authentication qualification requires an explicitly authorized provider run and is outside these controlled Linux tests. Current regression results and the controlled P09 native evidence rerun are in the iteration-59 verification section. No real provider was invoked. |
| Prompt conversation, explicit project editing, investigation/recovery, Open CLI, rephrasing | `recovery.py`, `agent.py`, `terminal.py`, `steps.py`, `source_watch.py` | `troubleshooting.py`, `step_controller.py`, `step_panel.py` | **Delivered** | Gap 5 delivers native Send Conversation, Show Conversation History, Open CLI and Rephrase Current Description through protocol v1 `conversation.send`, `conversation.history`, `cli.command`, `prompt.rephrase`. Shared editing invocation, bounded context, source-change tracking and review prose preserve cancellation, provider diagnostics, candidate gates and session identity. CLI returns argv/cwd/env for a trusted VS Code terminal. Verification (2026-09-28, gap 5): `tests/test_service.py::test_conversation_shared_provider_history_and_no_step_records`, `test_conversation_edits_and_partial_failure_cancel_mark_stale`, `test_rephrase_preserves_candidate_gates_history_and_approval`, `test_cli_command_argument_array_context_and_no_spawn`; `tests/test_step_gui.py::test_desktop_rephrase_delegates_shared_scope_and_publication`, `tests/test_troubleshooting.py::test_desktop_conversation_delegates_shared_edit_tracking`; conversation/rephrase routing, native controls, terminal arguments and stale/trust guard cases in `workflow.test.ts`. Controlled-provider and native-API mock evidence; no real-provider or new interactive-terminal platform qualification claim. See the gap-5 contract below. |
| Background missing-purpose comments, documentation-only temporary copies, idle/no-proposal/no-unsaved-buffer guards | `documentation.py`, `source_edit.py`, `source_watch.py`, `recovery.py`, `service.py` | `troubleshooting.py:ensure_purpose_comments` / `_document_in_background`, `../icoda.py:show` / `_provider_changed` | **Partial** | P10 (iteration 56): desktop schedules automatically after project display/provider changes, waits for idle analysis/editor/workflow state and clean editor buffers, requires an enabled installed provider, limits each missing entity to two attempts, edits a private copy and delays checked application while a proposal is pending; it has no blanket Git-clean gate. Extension adds opt-in resource setting `icoda.backgroundPurposeComments` (false by default, deliberately requiring opt-in instead of the desktop’s automatic default), a 30-second idle timer and one automatic attempt per revision. Separate `WorkflowModel` state and owned cancellation preserve foreground conversations; editor/backend activity delays scheduling, foreground requests including trace playback cancel/wait for owned work, and disabling/switching/deactivation disposes or cancels it. Trust/dirty/busy guards precede the read-only `purpose.status`; Python reuses `workflow_readiness`, `documentation.completion_refusal` and `workflow_provider` for current provider, fresh analysis and pending/retained proposal gates. Existing `purpose.propose` and Apply/Reject review enforce documentation-only edits and source/candidate snapshots; background results never auto-apply. Node `purposeComments.test.ts`: `P10 background purpose fires after idle through WorkflowModel and leaves conversation state alone`, `P10 background purpose is suppressed when dirty` and its untrusted/no provider/workflow active/proposal pending/foreground busy/setting off cases, `P10 background timer cancels its owned job on deactivate`, `P10 background timer cancels its owned job on session change`, `P10 background timer cancels its owned job on setting off`, `P10 foreground and trace activity cancels only background work and waits for it`, `P10 workspace setting is opt-in and resource scoped`. Python `tests/test_service.py::test_p10_purpose_status_reuses_core_readiness_without_starting_provider`, `test_p10_purpose_status_ready_active_cancelled_and_pending_candidate`, `test_p10_cancelled_purpose_completion_discards_owned_candidate`, plus existing purpose decision/stale-evidence tests. Native VS Code 1.96.4 `integration/suite.ts`: `P10 idle purpose proposal is reviewable without changing Call View or source editor` uses only `tests/fixtures/fake_workflow.py` and temporary config/project roots, verifies candidate contents, unchanged source/selection/camera/editor, and native Reject. **Deferred:** desktop per-entity retry parity (one attempt per revision bounds unattended provider usage) and retained purpose-candidate recovery (needs persisted review snapshots; retained candidates continue to block further work). Current regression results and the P10 native evidence rerun are in the iteration-59 verification section. Linux controlled-provider evidence only; no real-provider or Windows qualification claimed. |
| Proposal review: candidate source/diff, entity/API delta, build/test logs, signature confirmations, reject/adapt/rebuild, bounded auto-approval | `steps.py`, `adaptation.py`, `auto_approve.py`, `rules.py`, `test_selection.py`, `response.py` | `step_controller.py`, `step_panel.py`, `source_editor.py`, `../icoda.py` | **Delivered** | G13 delivers native diffs, delta/gate/history output, signature confirmation, explicit approve/reject/adapt/rebuild and stale/dirty evidence refusal (`proposal.test.ts`, `tests/test_service.py` review cases). It33 adds configurable automatic code approval through the same review evidence, `auto_approve.derive` and `StepRunner.approve_reviewed` gates, stopping at approach/signature confirmation, failed checks, cancellation, empty queue and provider failure (`tests/test_service.py` queue cases and `workflow.test.ts`). It34 restores interrupted candidates through shared recovery and fresh review checks (`tests/test_service.py::test_recovery_failed_gate_and_unsaved_evidence_still_block_approval`, `test_recovery_never_auto_approves_or_skips_signature_confirmation`, `proposal.test.ts` recovery cases). Recovered candidates require explicit approval, including when automatic approval is saved. The real-provider AT13 journey remains Not qualified; P02 adds controlled native candidate/dirty-buffer evidence. |
| Git: isolated worktrees, clean-tree checks, promotion/rollback, approval commits, manual edits, history and conditional undo | `git.py`, `steps.py`, `steplog.py`, `persistence.py` | `step_controller.py`, `step_panel.py`, `mind_map_view.py`, `../icoda.py` | **Delivered** | G13: core isolated worktrees, clean-tree checks, promotion/rollback, approval/manual commits, history and conditional undo remain authoritative. Evidence: `tests/test_service.py::test_review_approve_commit_history_and_undo`, `test_review_dirty_tree_is_distinct_for_every_decision`, `test_review_manual_edit_records_commit_and_blocks_unsaved`, `tests/test_git.py`, and `proposal.test.ts`. Commits in these tests affect disposable fixture repositories only. |
| Issues and Coverage: advisory rules, requirement tags, structural recorded-test reachability, stale body/status evidence | `rules.py`, `requirement_coverage.py`, `coverage_index.py`, `test_selection.py`, `steplog.py`, `node_status.py` | `issue_view.py`, `coverage_view.py`, `graph_canvas.py` | **Delivered** | G11c: native Issues and separate requirement traceability/structural test reachability, preserving stale body/status evidence and source locations. Evidence: `tests/test_service.py::test_evidence_core_agreement_navigation_and_read_only`, `test_evidence_preserves_undo_and_failed_test_semantics`, `tests/test_coverage_index.py`, `evidence.test.ts`. Neither section claims measured runtime coverage; native tree visual qualification remains open. |
| Persistence/recovery: specification, workflow queue, logs, cached model, UI target/provider, pins/names, mind-map expansion, corrupt/interrupted state | `persistence.py`, `steplog.py`, `session.py`, `implementation_queue.py`, `recovery.py`, `steps.py`, `git.py` | `../icoda.py`, `executable_selector.py`, `provider_field.py`, `mind_map_view.py` | **Partial** | P11 (iteration 58, 2026-09-28). **Desktop audit → extension mapping:** `persistence.py:ProjectStore.load_state/save_state/load_model/load_ui/save_ui/load_layout/save_layout` and `_atomic_write_text` own the existing `.icoda` JSON/cache files and atomic replacement; `session.py:save_project_specification/open_project/log_event`, `../icoda.py:App.open_project/show` restore specification/phase/cache and append diagnostics. Extension `service.py:Service.install_project/save_specification`, specification/workflow views and Output already reuse these owners; no new state file or version was introduced. `persistence.py:UserConfig.remember_project` and `../icoda.py:main` remember/reopen the desktop project; VS Code uses its explicit workspace folder and native recent-folder UI instead of silently opening the desktop's last project. `executable_selector.py:ExecutableSelector.show/_save_selection`, `../icoda.py:App._restore_provider/_provider_changed` and `provider_field.py:ProviderField` restore target and project binary/model with user defaults; existing `target.select`, `providers.list/select`, `ProjectSession.open` and `workflowModel.ts` retain this state without launching a provider. `implementation_queue.py:ensure_state/update_settings/target_usr`, `step_controller.py:StepController.scope_changed/batch_size_changed/grouping_changed` and `steps.py:StepRunner.approve_approach/approve` persist queue/cursor/scope/grouping/batch/approved approach; existing queue operations restore these choices, and automatic continuation stays stopped after restart. `../icoda.py:App._apply_cluster_layout` and `mind_map_view.py:MindMapCanvas.show/_save_state` persist pins/names and Mind Map expansion; existing cluster and mindmap operations plus P01 File View persistence reuse them. Added target-scoped Call root/depth/callers/filter/camera, Class level/cameras and Mind Map camera through the existing `view.state.get/set` interface and `ProjectStore.ui.json` extension keys (`vscodeCallViews`, `vscodeClassViews`, `vscodeMindMapViews`), using the same bounded camera validation as File View. `viewState.ts` coalesces writes, rejects obsolete session/target replies, and flushes before switching, restart and disposal without waiting for unrelated pending panel actions. Candidate/trace playback state remains session-only; saved review approvals are never restored. Invalid saved diagram entries report `view_state_invalid` and block automatic replacement; obsolete roots/groups fall back using shared model/layout data without rewriting on read. **Recovery audit:** desktop `session.py:open_project` reports and preserves leftover worktrees; `persistence.py:ProjectStore.load_state` refuses malformed state, and `steplog.py:StepLog.records` refuses malformed history. Existing extension `recovery.list/resolve` and `proposalModel.ts:loadRecoveries/recover` call `recovery.py:interrupted_proposals/resolve_proposal/_restore_proposal/checkpoint_proposal` for Resume for Review / Keep for Later / confirmed Discard. Resumed candidates get fresh checks and explicit decisions; dirty-tree, unsaved-buffer, signature and approval evidence guards remain. `steplog.py:StepLog.approved` / `steplog.py:introducing_record`, `steps.py:StepRunner.undo/commit_manual_edits` and desktop `step_controller.py:StepController.undo/commit_manual` plus `../icoda.py:App.select_step` map to the existing native history/undo/manual-edit commands with clean-tree and HEAD safeguards. `../icoda.py:App._recover_analysis` rebuilds then reopens after analysis failures; the extension retains explicit Build Target and Analyse Project actions. Added `service.py:cached_source_changes` compares existing `FileInfo.content_hash` values on open, marks modified/missing cached sources stale in memory, and points to Analyse Project while preserving cache/source bytes. `recovery.py:diagnose/invoke` and `troubleshooting.py:Troubleshooting.handle_failure` own provider repair; extension provider failures already use shared diagnoses and separate conversation/CLI recovery, never for source lookup. **Evidence:** `tests/test_service.py::test_p11_diagram_state_survives_restart_without_changing_history`, `test_p11_diagram_state_scopes_targets_and_rejects_stale_writes`, `test_p11_invalid_and_obsolete_diagram_state_preserves_saved_bytes`, `test_p11_reopen_reports_stale_cache_and_explicit_analysis_recovers`, `test_p11_corrupt_state_keeps_interrupted_work_and_history`; retained `test_queue_settings_persist_across_restart_and_invalidate_approach`, `test_review_approve_commit_history_and_undo`, `test_recovery_choices_preserve_source_and_resume_review`, `test_recovery_refuses_dirty_unsaved_and_unconfirmed_discard`, `test_recovery_interrupted_provider_checkpoint_survives_restart` and `test_recovery_failed_gate_and_unsaved_evidence_still_block_approval`. Node `viewState.test.ts`: `P11 view state restores, coalesces writes and flushes before disposal`, `P11 pending camera writes and late restores cannot cross target or session generations`, `P11 corrupt saved state is reported and never overwritten by default cameras`, and `P11 call controls restore after model recreation and save camera changes`, `P11 class controls restore after model recreation and save camera changes`, `P11 mindmap controls restore after model recreation and save camera changes`. Native VS Code 1.96.4 `integration/suite.ts`: `P11 restart restores diagrams and reports retained work with safe recovery` reopens a temporary Python fixture through Restart Backend, checks controls/cameras and stored provider/target, reports stale analysis, invokes Keep for Later and Analyse Project, and compares retained draft, history, state and user-source bytes. **Deferred:** shared desktop/service `ProjectLock` ownership needs desktop lifecycle coordination (this task audits desktop read-only; current locks coordinate services only); avoid concurrent frontend writers. Retained purpose candidates and restoration of prior review snapshots need persisted review fingerprints; they remain blocked/preserved and cannot regain approval from old gates. Real-provider repair/authentication requires an authorized provider run; Windows/macOS persistence/locking qualification requires those hosts (Linux controlled fixtures only). Complete offline invalidation for newly added files, compiler/dependency changes and legacy models lacking hashes needs additional analysis evidence; explicit Analyse Project remains available. Corrupt specification/state/history requires manual repair or restoration from version control, matching the shared refusal to invent or overwrite user data. P04 graph interaction controls, P06 automatic post-build analysis and P09/P10 provider/background workflows are unchanged. Iteration 59 confirms raw-byte SHA-1 consistency and disposal ordering without production changes: `test_p11_reopen_unchanged_analysis_keeps_raw_byte_hash_fresh` covers LF, CRLF and UTF-8 BOM; `viewState.test.ts` adds `P11 disposal drops pending and queued writes after project or target switches` and asserts same-session persistence in the retained disposal test. Current gate results and native P11 evidence are in the iteration-59 verification section. |
| Desktop shell: commands, recent projects, help/logs, busy/status, startup/shutdown, task delivery | `session.py`, `persistence.py`, `process.py`, `guidance.py` | `../icoda.py`, `tasks.py`, `dialogs.py`, `screen.py` | **Delivered** | G02/G14/G15/G17 replace shell presentation with VS Code commands, workspace/recent-folder UI, output/progress and lifecycle; help/setup ships in `vscode/README.md`. Evidence: G16 `suite.ts` activation/empty-workspace cases, `lifecycle.test.ts`, G17 `vsixSuite.ts` production activation, and the G18 desktop regression run below. Desktop entry points remain available; historical GUI failures are not new migration regressions. |
| Tests, installation, documentation and release qualification | Existing core tests, `pyproject.toml`, resource JSON/schema files | Tk-stub tests and real-Tk acceptance programs under `tests/` | **Delivered** | G16/G17/G18 deliver separate Python/Node/host suites, a reproducible backend-bundling VSIX and installation/developer documentation (`pythonRuntime.test.ts`, `integration/suite.ts`, `integration/vsixSuite.ts`, G17 recorded run, G18 rerun below). Verification (2026-09-28, gap 7): `vscode/src/test/integration/untrusted.ts` checks `Restricted Mode activation retains trust guards and starts no backend`; `Restricted Mode refuses execution commands before tools providers terminals or backend requests`; `Restricted Mode output project placeholder and native source editor remain usable`; `Read-only service open views source and recorded playback need no trust authorization`; `Service rejects untrusted creation workflows conversation CLI purpose apply and proposal approval`. The existing Python-startup trust boundary is preserved; see the gap-7 inventory and exact test names below. Only Linux is tested; platform, accessibility, broader installed journeys and real-provider extension acceptance remain open. Qualification follow-up: execute the AT ledger on its named hosts; installed/native journeys need additional UI evidence, while a real-provider run is outside this offline review. Packaging and automated passes do not qualify those journeys. |

Matrix tally: **16 Delivered, 5 Partial, 1 Not qualified (22 rows); 0 unexplained omissions**. Partial rows retain their delivered portions and the reason for each deferred behavior.
## Tkinter and headless blockers

The import inventory was obtained with:

```bash
rg -n 'tkinter|icoda_gui|\.after\(|\.after_cancel\(|messagebox|filedialog|simpledialog' \
  icoda_core icoda.py icoda_gui/step_controller.py icoda_gui/tasks.py
```

There are **no Tkinter or `icoda_gui` imports in `icoda_core/`**, and no core
callback requires a Tk widget. `icoda_core/views.py:7` is a docstring saying it
does not import Tkinter. `progress: Callable[[str], None]` in analysis, session,
Windows module preparation and `StepRunner` is a replaceable notification sink,
not a Tk dependency. A fresh interpreter importing `session`, `executables`,
`call_trace` and `source_edit` passed an assertion that neither `tkinter` nor
`icoda_gui` appeared in `sys.modules`.

Line references below are at the baseline commit; later shared extractions are
recorded in their goal sections. Callback groups identify application boundaries rather than proposing
a wholesale GUI refactor.

| Location | Tk dependency / callback boundary | Later replacement |
|---|---|---|
| `icoda.py:17`, `icoda.py:21`, `icoda.py:51` | Imports Tk, dialogs/ttk, and all desktop widgets. | Service imports core only. |
| `icoda.py:82`, `icoda.py:107`, `icoda.py:145`, `icoda.py:183`, `icoda.py:192`, `icoda.py:256`, `icoda.py:446`, `icoda.py:497` | `FileViewCanvas`: mouse/configure bindings, `after` resize, Tk font measurement, fit/overview, draw and group navigation; async Organise completion at `:168` updates widgets. | Reuse core geometry; replace canvas/events; extract overview decisions with measured label sizes. |
| `icoda.py:530`, `icoda.py:592`, `icoda.py:641`, `icoda.py:841`, `icoda.py:963`, `icoda.py:985` | `App` constructs Tk variables/widgets, menus, shortcuts, panel/status; variable traces, focus binding and callback exception hook at `:574`–`:586`. | Explicit session state; VS Code commands, listeners and progress. Never instantiate an App with dummy widgets in the service. |
| `icoda.py:681`, `icoda.py:687`, `icoda.py:718` | About/libclang windows, radio selection, apply-and-reload callbacks. | Native information/settings/picker; core tool discovery. |
| `icoda.py:753`, `icoda.py:761`, `icoda.py:768` | Trace file dialog and async `done` closure publish into Call View/status; existing closure checks model identity. | Path input and revision-checked playback response. |
| `icoda.py:793`, `icoda.py:799`, `icoda.py:807`, `icoda.py:812`, `icoda.py:1587`, `icoda.py:1606` | Coverage/filter/focus/expansion and context-action callbacks read Tk state; cluster rename dialog. | Typed view-state inputs and explicit cluster actions. |
| `icoda.py:1024`, `icoda.py:1029`, `icoda.py:1061`, `icoda.py:1066` | Open/new directory dialogs, editor clear/save prompts, busy guards, widget resets and worker start; poll scheduled at `:1059`. | Workspace selection in frontend; project state/worker lifecycle in service. |
| `icoda.py:1089`, `icoda.py:1110`, `icoda.py:1128`, `icoda.py:1175`, `icoda.py:1189` | Specification editor save/reread closures, widget refresh and skeleton-build confirmation. | Core specification operations with explicit frontend decisions. |
| `icoda.py:1198`, `icoda.py:1229`, `icoda.py:1236`, `icoda.py:1247`, `icoda.py:1256` | Build completion, test-command dialog, reload/busy controls. | Operations plus structured state/outcomes. |
| `icoda.py:1266`, `icoda.py:1276`, `icoda.py:1283`, `icoda.py:1304`, `icoda.py:1312` | Focus-triggered source watching, queue/poll via `root.after`, automatic recovery, global Tk callback error handler. | Debounced save/watch events, request-scoped workers and typed errors; do not send source errors to provider recovery. |
| `icoda.py:1319`, `icoda.py:1389`, `icoda.py:1429`, `icoda.py:1447`, `icoda.py:1498` | `show`, target projection, proposal Call View and post-step rendering mix queue/state updates with all view refreshes; startup comment job at `:1381`. | Extract state publication; return models/layouts; frontend renders. |
| `icoda.py:1519`, `icoda.py:1525`, `icoda.py:1540` | Provider field persistence/readiness and `after` purpose-comment scheduling at `:1538`. | Separate provider settings/capabilities from foreground browsing. |
| `icoda.py:1682`, `icoda.py:1720`, `icoda.py:1724`, `icoda.py:1736`, `icoda.py:1744` | Graph/tree selection populates `ttk.Treeview`, opens built-in editor, handles local missing/ambiguous paths, controls focus. | Reuse `source_edit.find_source`; native document navigation with correct project/proposal root. |
| `icoda.py:1776`, `icoda.py:1779`, `icoda.py:1796`, `icoda.py:1805`, `icoda.py:1812` | Editor save invalidates proposal evidence, deferred reanalysis uses `after`, close prompts/cancels/destroys root, history selects panel content. | Native buffer events; service evidence revisions; deterministic disposal. |
| `icoda.py:1850`, `icoda.py:1864` | Tcl/Tk library setup and `main` create `tk.Tk`, `App`, and run `mainloop`. | New headless entry point in G03, keeping desktop entry intact. `configure_windows_toolchain` at `:1831` is not Tk-bound but currently changes process environment globally. |
| `icoda_gui/step_controller.py:13`, `:30`, `:43`, `:55`, `:64` | Dialog/GUI imports; controller owns a window and reads provider widgets to create `StepRunner`; `action` shows dialogs. | Explicit provider/session/runner state with validated operations. |
| `icoda_gui/step_controller.py:74`, `:81`, `:88`, `:97`, `:114`, `:130`, `:145` | UI-thread progress, busy state, unsaved-editor guard, async `finished`, completion bell, recovery/cancel, dirty-tree manual-commit dialog. | Worker notifications and explicit decisions; preserve mutation/cancellation boundaries. |
| `icoda_gui/step_controller.py:154`, `:200`, `:210`, `:220`, `:230`, `:255`, `:260`, `:291`, `:303` | Rephrase/approach/propose/focus/implement/test callbacks read controls and publish results in panel/graphs. | Extract request assembly/publishing; reuse runner operations. |
| `icoda_gui/step_controller.py:314`, `:334`, `:344`, `:358`, `:370`, `:394`, `:404`, `:409` | Approval and signature confirmation belong partly to controller state; auto-approve reads Tk phase/flags/history; architecture approval uses dialogs at `:412`/`:415`. | Service-enforced review state and frontend decisions. Calling `StepRunner.approve` alone does not preserve the controller's signature-confirmation gate. |
| `icoda_gui/step_controller.py:425`, `:438`, `:453`, `:477` | Batch/scope/grouping changes read panel variables and invalidate approaches. | Explicit core-state inputs and refreshed queue response. |
| `icoda_gui/step_controller.py:491`, `:496`, `:522`, `:533`, `:544`, `:552`, `:558`, `:562`, `:564`, `:573` | Reject/adapt/undo dialogs, edited Summary, rebuild result callback, external worktree opener and manual-commit completion. | Preserve core actions/gates; native diff/worktree UI. `undo_question` at `:585` only formats text but lives in this GUI-importing module. |
| `icoda_gui/tasks.py:9`, `:18`, `:29`, `:36`, `:50`, `:54`, `:63` | Tk import/bell; `UiTasks` delivers worker results only when `root.after` drains callback queue. | Service worker executor and notification queue independent of Tk. |
| `icoda_gui/tasks.py:78`, `:88`, `:91`, `:95` | Watchdog measures Tk heartbeat via `after`; daemon loop has no shutdown API. | Service process health/owned-worker cleanup, not a Tk heartbeat. |

Additional extraction owners from the matrix: `icoda_gui/executable_selector.py` holds
selection/recording UI and callbacks; `icoda_gui/call_view.py:109` and `:247` add
trace-observed functions/paths; `icoda_gui/troubleshooting.py:290` and `:328` coordinate
purpose-comment work and guarded apply. These must not be imported into G03 merely
to obtain their application behavior.

## Proposed G03 service boundary

Use one Python backend per explicitly selected workspace folder, with authoritative
project root, `ProjectStore`, whole-project model, selected `Entry`, projected
model, model revision, source-root registry, and optional `CallPlayback`. Keep
layout/view choices separate from the playback cursor. Queue mutations per project
and prevent two sessions writing the same `.icoda` state. Selecting a target must
not mutate the whole-project model.

The extension owns workspace selection, native documents/diffs, webview drawing,
viewport/focus, settings, output/progress and Workspace Trust. The backend owns
analysis, target projection, source resolution, trace parsing and all stepping.
Build/agent/worktree operations are later milestones, not G03 initialization side
effects. No Tk, Redis, AI-Loop runner, HTTP server or custom editor is required.

### Operation mapping

The table maps the wider planned boundary. The implemented subset and exact wire
fields are specified below; target selection and static Call layout are now available,
while other views and cancellable workers remain future work.

| Operation | Inputs/result and existing core functions to wrap | Boundary work still needed |
|---|---|---|
| `initialize` | Client protocol version/settings → negotiated protocol version, `icoda_core.__version__`, capabilities and effective runtime/tool paths. Reuse `persistence.UserConfig.load`, `persistence.config_path`; lazy discovery through `toolchain.candidates`, `toolchain.select_candidate`, `agent.load_providers`/`agent.binary_available`. | New handshake; do not parse a project, initialize Tk, execute an agent or install dependencies. Missing build/provider tools reduce capabilities, not navigation. |
| `project.open` | Explicit folder URI → session/source-root IDs, cached model/state and initial revision. Reuse `persistence.ProjectStore.ensure`, `load_state`, `load_ui`, `load_model`, `load_layout`; `session.OpenedProject` is an existing result shape. | `session.open_project` already combines opening, analysis and File layout; split the cache-only path for this operation. It writes state and remembers the project, so no implicit open of another workspace/last desktop project. |
| `project.analyse` | Session plus expected revision → fresh or explicitly stale model, diagnostics, toolchain identity. Reuse `session.open_project`/`analyse_in_child`/`analyse`; pipeline uses `analysis.load_compile_commands`, `parse_project_for_root`, `python_analysis.parse_project`, `windows_analysis.prepare`, `steplog.apply_statuses`, `clusters.cluster_files` and store cache. | Child crash isolation already exists, but add tracked cancellation, progress events, settings forwarding, serialization of cache writes and generation checks. Existing `analyse_in_child` reloads global config, not the caller's explicit config. Preserve per-file Python errors and C++ stale-model semantics. |
| `targets.list` | Session/revision → target/configuration/kind/artifact/source memberships and entry choices. Reuse `executables.read_targets`, `executables.entries`, `cmake.build_directory`. | Read available metadata without configuring/building. Report invalid/missing target metadata separately while retaining source-derived entries. Explicit configure/refresh through `executables.operate(..., "refresh", ...)` belongs to G09. |
| `target.select` | Session/revision and target key or Whole Project → selection identity and projected model revision. Reuse `executables.Entry.key`, `executables.choose`, `executables.scope_model`, `ProjectStore.load_ui`/`save_ui`. | Extract selector persistence (`ui["executable"]`; `[]` means Whole Project). Validate explicit selections; use original model for Whole Project, never `scope_model(model, None)`. Reset/invalidate playback association on selection change and discard older results. |
| `view.get` | Session/revision, view kind, root/depth/callers/filter/expansion/selection → entities, edges, geometry and statuses. Reuse `DerivedModel.to_json`, `views.default_root`, `library_roots`, `layout_call_view`, `call_path`, `reachable_calls`; shared `graph_filter.derive`, `node_status.derive`, `expansion.derive`. Later File/Class/Mind Map use `layout_file_view`, `file_view_overview`, `file_view_group`, `class_view.build_class_graph`, `layout_class_view`, `mind_map.build_mind_map`, `layout_mind_map`. | Serialize existing dataclasses; extract trace-required paths/extra functions from Call View. Return selected source with playback; do not reroot/refit the graph per step. Advertise only implemented view kinds. |
| `source.resolve` | Session, source-root ID, relative path or entity USR and one-based line → one path, ranked tied candidates, or typed missing-source error. Reuse model entity locations and `source_edit.relative_path`, `source_path`, `find_source`. | Native file chooser for equal matches; preserve suffix ranking, metadata exclusion and symlink/root boundaries. Register proposal root explicitly in G13. Do not fall back from a missing candidate to the project. Do not call `Document.save`, an external editor or provider recovery. |
| `trace.load` | Session/revision, selected executable identity and trace path → trace ID/association, resolved counts, initial playback state. Reuse `call_trace.load_trace(path, scoped_model)` and `CallPlayback(trace)` with existing symbol resolution. | Reject stale results after target changes; expose `TraceFormatError` as invalid trace, zero resolved calls as an explanatory empty state. Keep original UTF-8 TSV format; loading an external trace must not claim its executable was verified merely because symbols matched. |
| `trace.step` | Trace/session/revision and `into`, `over`, `out`, `previous`, or seek-to-USR → shared cursor/entity/source, counts, caller-edge annotations and availability. Wrap `CallPlayback.step_into`, `step_over`, `step_out`, `previous_call`, `seek_first_call`; query `can_step`, `position`, `total`, `status`, `current_entity`, `current_repeat_count`, `current_caller_counts`. | One Python implementation only. Into retains global grouped order; Over/Out use the selected thread and invocation returns. Previous/reset availability can be computed from position; do not add TypeScript depth logic. |
| `trace.reset` | Trace/session/revision → cleared selection, position zero and refreshed availability. Wrap `CallPlayback.reset`. | Publish graph/source selection coherently; keep graph root and viewport. Reset is not trace unload. |
| `operation.cancel` | Session and request/operation ID → cancellation acknowledgement plus one eventual cancelled/completed/failed result for the original request. Existing hooks: `process.run_bounded` cancellation, `process.kill_tree`, `process.cancel_running`; later `steps.StepRunner.cancel` and `begin`. | New request-to-worker registry. `cancel_running` at `process.py:70` is process-wide; `session.analyse_in_child` uses unregistered `subprocess.run`. Neither is a ready request-scoped cancellation API. Isolate/track owned analysis workers before advertising cancellable analysis; preserve non-cancellable promotion/commit boundaries in G13. |

### Proposed wire/lifecycle contract

- Use version **1**, UTF-8 JSON, one complete compact JSON object per newline on
  stdin/stdout. JSON string newlines are escaped; bound message size. Only protocol
  output belongs on stdout; diagnostics go to stderr or explicit log notifications.
  Do not reuse the current child's “last stdout line is JSON” convention as the
  service transport.
- A request has `id`, `method`, `params`, and (after initialization) `sessionId`.
  Project-dependent requests carry expected `modelRevision` and selected target
  identity. Responses echo IDs and return `status: ok|cancelled|error`, with either
  `result` or structured `error {code, message, details}`. Notifications have no
  request ID; `progress`, `log` and `state` include operation/session/revision IDs.
- Negotiate protocol/backend versions and supported capabilities before project
  work. Reject unsupported versions/unknown methods/malformed parameters without
  invoking tools. Recover at the next newline after invalid JSON; unparseable
  requests without a usable ID get a protocol-error notification. Startup failure
  or backend exit resolves every pending client request with a clear outcome.
- Increment a generation when project/target changes or source edits invalidate
  analysis. Publish results only for the current generation. Check the generation
  before cache publication as well as before rendering; dropping a UI response
  alone does not prevent an old worker from overwriting `.icoda/cache`.
- Entity IDs remain core USRs; files remain workspace-relative paths under an
  explicit source-root ID. Include one-based line numbers, trace ID, grouped call
  position/count and selected entity in each playback state. The client translates
  to native editor coordinates. Unsaved document versions must invalidate evidence
  without overwriting buffers.
- Keep `source_missing`, `source_ambiguous`, `tool_missing`, `invalid_trace`,
  `analysis_failed`, `provider_failed`, `build_failed`, `test_failed`,
  `stale_revision`, `timeout` and protocol errors distinguishable. Do not classify
  a missing source by parsing it through generic provider/Binary recovery text.
- Cancellation acknowledgement is not evidence that work has stopped. Reap owned
  processes, settle the original request exactly once, and preserve last good
  state. Define per-operation timeouts (existing analysis default is 1,800 seconds;
  provider/build/run limits already exist). On close/restart dispose processes,
  listeners and views; return errors for outstanding requests before restarting.
- Honor Workspace Trust before running project tools/agents, including C++ analysis
  paths that can invoke compilers. Cached viewing/source navigation needs no agent.
  Validate webview messages in the extension and use a restrictive CSP. Spawn with
  argument arrays and pass discovered tool environments to owned children, not
  global user PATH changes. Existing Visual Studio batch-environment setup is a
  platform adapter to audit, not a shell template for arbitrary webview input.

The first subprocess contract tests cover handshake/version mismatch, malformed
frames, unknown methods, no-project state, fixture open/model/source/trace,
non-cancellable acknowledgements, stdout isolation and stale identities. Worker
cancellation and concurrent generation/cache publication remain future G03/G14
work; G02 client startup/exit handling is described below.

### Implemented protocol v1 slice

Run `python -m icoda_core.service` from `icoda/` using the prepared ICODA Python
environment. This reuses the existing dependencies and needs neither Tk nor a
display. Initialization does not discover tools, execute providers or read a
remembered project. Core imports are lazy. Analysis uses
`session.analyse_in_child`, including its existing global user-config lookup,
compiler-aware parsing and 1,800-second timeout. G04 adds request-local tool
overrides to `toolchain.inspect`; analysis continues using the project's existing
compiler/dependency settings and the child configuration described above.

The initial slice used a sequential request loop with one active explicit project
per connection. G09 retains serialized state and adds request cancellation and
progress events. Cross-process project locking and cancellable analysis remain
unimplemented.
Clients must give the service exclusive ownership of that project's
cache while analysing. These limitations prevent claiming G03/G14 complete.

Requests require `id` (nonempty string or integer), `method` and object `params`.
`initialize`, `project.open`, `operation.cancel` and `toolchain.inspect` need no session identity.
Every other implemented method requires top-level `sessionId`, `modelRevision`
(positive integer) and `targetId` (the current target ID, or null for Whole Project).
Stale session, revision or target requests fail before running operations. Each successful open gets a
new opaque session/source-root identity and revision 1. Each analysis attempt
increments the revision and invalidates loaded playback, including on failure.
Changing the selected target also increments the revision and invalidates playback;
reselecting the current target preserves both. For `target.select`, the top-level
`targetId` identifies the **current** selection and `params.targetId` the **requested** one.

| Method | Exact params | Result |
|---|---|---|
| `initialize` | `{"protocolVersion":1}` | `protocolVersion`, `backendVersion` from `icoda_core.__version__`, `runtime.python`, `analysisTimeoutSeconds`, and capabilities: implemented `methods`, `cancellation:true`, additive `cancellableMethods` (the four G09 operations below), `targetSelection:true`, `views:["call","file","class","mindmap"]`, `maxMessageBytes`. A version mismatch does not initialize the connection; a successful handshake cannot be repeated. |
| `project.open` | `{"path":"/absolute/project/folder"}` | Session context (`sessionId`, `sourceRootId`, `modelRevision`, `targetId`), `root`, `cached`, whole-project `model`, persisted `state`, `ui`, `layout`. Native filesystem paths (VS Code `Uri.fsPath`), not URI strings. Reads `ProjectStore` and available target metadata without `ensure`, analysis, configuration, layout computation or writes. Restores selection using the desktop policy below. Missing cache returns an empty model marked stale. |
| `project.analyse` | `{}`; P05 also accepts optional `automatic` (boolean) and `unsavedDocuments` (URI array), see below | Session context, `root`, whole-project core JSON `model`, `diagnostics` (message, and file where available), `toolchain` (frontend and libclangPath). Refreshes the target catalog against the published model and restores selection. Failure returns `analysis_failed` with the same snapshot in `error.details`, retaining the previously published model marked stale. Per-file parse diagnostics survive even when retaining an older model; repaired sources can produce a fresh revision. Missing libclang/database and child failure cannot make cached data appear fresh. |
| `targets.list` | `{}` | Session context, `targets` (Whole Project first, then desktop entries) and `diagnostics`. Returns the catalog read at open/analysis for this model revision; reopen or analyse after external metadata changes. No configure/build/tool process is started. |
| `target.select` | `{"targetId":ID}` or `{"targetId":null}` | Updated session context and scoped core JSON `model`. Rejects unknown IDs without fallback. Saves only `ui["executable"]` in `.icoda/ui.json`, preserving other UI keys. Whole Project bypasses `scope_model`; projections never replace or mutate the whole-project model/cache. A failed UI write preserves selection, revision and playback. |
| `view.get` | `{"view":"call"}`, optional `root` (USR or null), `depth` (integer >= 0, default 3), `callers` (boolean, default false), and `traceId` (current loaded trace ID); P02 adds optional `sourceRootId` for a checked candidate, see below | Session context plus the Call View payload below. By default uses the selected target's projection and the same `views.layout_call_view` as the desktop; `traceId` additionally includes recorded whole-model paths/functions as specified in G08. Requires a cached or successfully analysed model; a retained stale model remains viewable and explicitly marked stale. |
| `issues.list` | `{}` | Scoped advisory findings, stable IDs, source locations and explicit empty states; see G11c. |
| `coverage.get` | `{}` | Separate requirement traceability and recorded structural test reachability, with source locations and explicit empty states; see G11c. |
| `view.get` Mind Map kind | `{"view":"mindmap"}` | Shared scoped hierarchy, visible layout, requirement/status/source metadata and introducing steps; exact additive fields are documented under G11b below. |
| `mindmap.setExpanded` | `nodeId` (nonempty stable node ID), `expanded` (boolean) | Persist one expansion choice through `ProjectState.mind_map`; return the same Mind Map view payload. Session/revision/target envelope is required; model revision is unchanged. |
| `mindmap.step` | `nodeId` (nonempty stable node ID) | Read the current introducing history record from the shared Mind Map/step log. Session/revision/target envelope is required; see P03 below. |
| `source.resolve` | `sourceRootId`, exactly one of `file` or `usr`, optional positive `line` | Session context, source-root-relative `file`, absolute `path`, one-based `line`. The root is the workspace or P02's checked candidate worktree. Defaults to the entity's line or 1. Reuses suffix ranking, metadata exclusion and root/symlink boundaries from `find_source`/`source_path`. `source_ambiguous` includes sorted tied relative `candidates` in `error.details`; `source_missing` is local to source lookup. Neither invokes provider recovery. |
| `trace.load` | `{"path":"calls.tsv"}` | Playback state, `path`, `events`, `recordedCalls`, `resolvedCalls`. Relative trace paths resolve against the explicit project; absolute external trace paths are allowed. Uses `load_trace` and `CallPlayback` against the whole-project model. No executable association is verified in this slice. Failed loads preserve the preceding playback. |
| `trace.step` | `traceId`, `action`: `into`, `over`, `out`, `previous`, or `seek`; `usr` required only for `seek` | Playback state. Wraps only the corresponding `CallPlayback` method; seek chooses the first grouped call of that USR. A missing seek destination returns `trace_call_missing` without moving. Unavailable steps keep the shared cursor unchanged. |
| `trace.reset` | `traceId` | Playback state at position zero; trace remains loaded. |
| `operation.cancel` | `requestId` (string or integer) | G09 adds immediate request-scoped cancellation for its four owned operations (`cancellable:true`, `reason:"cancel_requested"`). Other/finished IDs retain `cancellable:false`, `reason:"not_cancellable"`. See the G09 contract below. |
| `toolchain.inspect` | Optional `cmakePath`, `ninjaPath`, `clangPath`, `llvmSymbolizerPath` (nonempty executable paths or commands without arguments); optional `requiredTools` (array of tool names) | `runtime`, `tools`, `environment`, `diagnostics`, `errors`, as specified in G04 below. Requires initialization, but no project or session identity. Missing tools remain independent capabilities; explicitly required missing tools return `missing_tool` with the inspection in error details. |

### P01 — File View clustering and saved navigation (iteration 45)

This is the first automatable parity area: P01 File View clustering/navigation.
P02/P05 concern candidate graphs/source refresh, P03 provenance/history, P04
shared graph policies, P06 executable operations, P07 analysis runtime selection,
and P08 specification orchestration. Iteration 45 changed only P01; iteration 46 delivers the related P02/P05 area
below. Iteration 48 delivers P08 in the specification contract. The other independent areas remain for later iterations.

Protocol v1 advertises three additive methods in `initialize.capabilities.methods`.
They require the existing session/revision/target envelope and preserve the model
revision and playback. No GUI imports, tools or provider calls are involved.

| Method | Exact params | Result |
|---|---|---|
| `cluster.assignFile` | `file` (exact analysed file ID in the selected target), `clusterId` (returned `cluster:` ID or null for automatic grouping); optional `viewClusterId`, `hierarchy` (boolean, default false) | Updated File View payload, retaining the requested level if it still exists. Reuses `clusters.pin_file` or `unpin_file`, then atomic `ProjectStore.save_layout`. Source/model files are untouched. Unknown file returns `source_missing`; unknown destination/display group returns `unknown_cluster`; malformed fields return `invalid_params`. |
| `view.state.get` | `view:"file"` | Session context, `view`, `state:{clusterId,cameras}`. Each camera is `{clusterId,viewport:{x,y,scale}}`. Missing/corrupt state defaults to overview; groups no longer present in the target are removed from the returned state without rewriting the saved file. |
| `view.state.set` | `view:"file"`, `state:{clusterId,cameras}` | Same response shape. Atomically merges into `.icoda/ui.json` under `vscodeFileViews`, keyed by opaque target ID or `whole-project`, preserving other UI keys. Accepts at most 512 unique cameras; cluster IDs are null, `external:overview`, or bounded nonempty `cluster:` IDs (at most 4096 characters). Finite x/y must be in ±10,000,000 and scale in [0.1,4]; extra fields and booleans as numbers are refused. Other views return `unknown_view`. |

File `view.get`, `view.revealFile`, and all three existing cluster edit methods
also accept optional `hierarchy:true`. Omission preserves the original flat v1
projection. The extension requests hierarchy: `clusters.with_parents` summarizes
the existing bounded clusters using their authoritative `parent_id` and saved
names; shared `views.file_view_level` and `file_cluster_path` compute visible
levels, counted relationships and ancestry. A saved parent is expandable into
bounded child groups (and inline singleton files), then into their files. Back
visits the preceding ancestor and eventually overview. No grouping algorithm or
membership policy is implemented in TypeScript. Parent pin/rename actions reuse
the existing shared layout decisions. An edit dissolving the active group returns
overview, with the saved overview camera.

Hierarchical File View responses add `clusters:[{id,label,fileCount}]` for the
native assignment picker. `clusterPath` contains all available ancestors in order.
The six trace controls and Call View behavior are unchanged. File assignment is
available from right-click/Shift+F10 on a visible file, and through registered
`ICODA: Assign File to Cluster` after selecting a native source or Call View
function. Its picker includes Automatic grouping (unpin file); cancellation writes
nothing. The webview sends only validated `{type:"assign",id,version}`. Trust,
visible-file membership, panel disposal and session identity are checked again
after the picker closes; the model accepts only offered destination IDs.

File View saves camera changes after a 150 ms debounce and flushes on navigation,
analysis/target/project changes, panel close and backend restart/deactivation.
Restoration checks session tickets, including same-target reselection, and drops
obsolete responses. Only File View state is implemented here;
P11's other-view state and cross-frontend writer coordination remain deferred.
This supersedes the historical single-level limitation for File View only; Class
View's clusterPath remains unchanged. Native evidence uses temporary generated
Python files plus the copied sentinel fixture; production commands, backend,
project persistence and VS Code editors run normally, with only picker choices
supplied by the test. The retained `p01-file-clustering.json` records requests,
layout/UI data, graph and native editor locations under this job's system-temp
`iteration45/icoda-integration-*/` report directory.

Verification on Linux/X11, 2026-09-28: `npm run compile` passed; `npm test`
reported **237 passed / 0 failed**. `npm run test:integration` with VS Code
**1.96.4** reported workspace **29/0**, empty **1/0**, C++ **2/0**, and untrusted
**5/0** (passed/failed). `npm run test:vsix` packaged the current backend and
reported **4/0** in a fresh profile. Repository-root `python -m pytest -q`
reported **1851 passed, 8 skipped**, no failures, in 371.98 seconds. Node was
`$HOME/.local/share/nodejs/v24.21.0/bin/node`; `ICODA_TEST_PYTHON` retained the
prepared venv's executable path. The root pytest run used that venv on PATH,
installed LLVM 18 tools and the existing AI-Loop venv site-packages on PYTHONPATH
for its Redis dependency; no collection-skip plugin or new dependency was used.
Logs are `compile.log`, `npm-test.log`, `integration.log`, `vsix.log` and
`pytest.log` under `iteration45/` in the job's system-temp report directory.
Changed-module Ruff, headless imports/capabilities and `git diff --check` passed.
An additional mypy check retains five errors in the unchanged `force_layout.py`
and `source_edit.py`; none is in an edited module. Committed fixtures and all
other parity rows are unchanged. The full real-provider/Tk release verifier was
not run; this is P01 implementation evidence, not full platform qualification.

### P03 — Mind Map introducing-step navigation (iteration 50)

The parity audit found exactly one remaining P03 behavior: opening the introducing
history record from a Mind Map node. G11b already delivers shared hierarchy and
layout, persisted expansion, requirements/status and introducing-step metadata,
and native source opening. Those behaviors are retained; no other parity row is
part of this change.

Protocol v1 adds advertised `mindmap.step`, with exactly `params:{"nodeId":...}`
and the usual top-level session/revision/target envelope. The service rebuilds the
current scoped hierarchy with `mind_map.build_mind_map`, the saved clustering and
`StepLog.records()`, then resolves its introducing iteration through
`steplog.introducing_record`. That helper is the extracted desktop `App.select_step`
rule: the latest approved/manual, non-approach record with that number. The core
hierarchy still decides introductions, including renames and undone records.
The response is `{sessionId,modelRevision,targetId,sourceRootId,nodeId,record}`;
`record` uses the existing redacted proposal-history serialization. No source,
state, history, model revision or playback cursor is changed. Unknown nodes or
invalid params produce `invalid_params`, unavailable introductions produce
`step_unavailable`, and absent analysis produces `model_unavailable`. Existing
identity errors apply before lookup.

The existing compact, scrolling toolbar adds **Open Step**, enabled only when the
selected visible node has an introducing step. Its validated webview message is
exactly `{type:"openStep",version,nodeId}`; it accepts no step number or path from
the webview. The model requests the backend record and drops obsolete panel,
session, target, revision and connection-generation replies. The panel rechecks
trust/disposal and shows the selected record in the native read-only **ICODA Mind
Map History** output channel, including request/rationale, file/entity changes,
commit and build/test results. Closing the Mind Map disposes that channel. Source
selection, expansion and camera are retained. Missing history is a local Mind Map
error and never invokes a provider. CSP, theme colors and keyboard-operable native
buttons retain the existing presentation rules.

New focused acceptance checks:

- Python: `tests/test_service.py::test_p03_mindmap_step_opens_shared_history_and_rejects_stale_identity`.
- Node: `mindMap.test.ts` — `P03 Mind Map opens only current backend history and drops stale replies`.
- Native VS Code: `integration/suite.ts` — `P03 Mind Map opens introducing history and source with session guards`.

The native check uses a temporary copy of the Python fixture, appends controlled
step records, opens the registered Mind Map command, expands/selects B, verifies
`main.py:14` in the native editor and the exact history output, then changes target
while a real service reply is delayed. The stale reply opens nothing. Its history,
expansion state and editor layout are restored before the remaining host checks.
`p03-mindmap-history.json` retains the service records and observed native output.
Logs and host evidence are under
`/tmp/ai-loop-worker-reports/J20260927-170326-588902/iteration50/`.

Verification (Linux x86_64/X11, 2026-09-28):

| Command / check | Actual result | Log under `iteration50/` |
|---|---|---|
| `npm run compile` | Exit 0; also rerun by the final native suite | `compile.log`, `integration-pass.log` |
| `npm test` | **246 passed, 0 failed, 0 skipped** | `npm-test.log` |
| `npm run test:integration`, VS Code **1.96.4** | **42 passed, 0 failed, 0 skipped**: workspace 33, empty 1, C++ 2, untrusted 6 | `integration-pass.log`, `icoda-integration-HuPlgX/*-results.json` |
| `npm run test:vsix` | Rebuilt package; fresh-profile installation **4 passed, 0 failed** | `vsix.log`, `icoda-integration-0Un66A/vsix-results.json` |
| Repository-root `python -m pytest -q` | **1870 passed, 0 failed, 8 existing skips**, 392.01s | `pytest-pass.log` |
| Mind Map service selection / desktop regressions | **16 passed** / **9 passed**, no failures | `p03-python.log`, `desktop-mindmap.log` |
| Changed-file Ruff / service and step-log mypy / `git diff --check` | All pass | `ruff.log`, `mypy.log`, `diffcheck.log` |

Node came from `$HOME/.local/share/nodejs/v24.21.0/bin`; `ICODA_TEST_PYTHON`
retained the prepared venv executable path. The root suite used that venv on PATH,
installed LLVM 18 tools and the prepared AI-Loop test dependencies on PYTHONPATH;
`TMPDIR` and `PYTEST_ADDOPTS` were unset. No dependencies were added and no tests
were weakened or skipped by this change. Earlier attempts are retained: an
inherited `--basetemp` was rejected by nested pytest invocations; a redirected
`TMPDIR` broke three sibling AI-Loop path expectations (all three passed when
unset). The new native check's editor-layout cleanup and initial-fit wait were
corrected; an existing C++ tab-title assertion passed unchanged on the final full
run. These failed attempts are not counted as passing evidence.

HEAD remains `fde592e3636dd19c9e84c51ffb43337d395fc717`; accumulated earlier
changes were preserved. The 13 changed source/documentation files are confined
to P03, and no other parity row changed. The sample analysis log was retained in
temp and its original bytes restored; all fixture hashes match their starting
values. The VSIX's P03 backend and frontend assets match the working sources.
No commit or merge was made. This evidence qualifies Linux, not other platforms.

### P02/P05 — Candidate Call View and source refresh (iteration 46)

`classification.txt` lists P02 Call View and P05 Source lookup/editor separately.
Iteration 46 groups them because candidate graph selection and native source
navigation share one checked proposal-root contract; automatic source refresh
must preserve that review evidence and its unsaved-document/proposal guards.
The P02 native check therefore also verifies P05 candidate navigation and approval
invalidation; P05's separate native check verifies saved/external source refresh.

Protocol v1 adds `initialize.capabilities.candidateCallView:true` and
`automaticAnalysis:true`; existing method names and default request behavior are
unchanged. The session/revision/target envelope and Workspace Trust guards still
apply. Navigation reuses the core candidate model/delta, target projection, call
layout and source lookup; it never starts a provider or imports GUI modules.

| Existing method | Additive contract |
|---|---|
| `proposal.get` | `candidateGraph` is null unless a code candidate has a model and fresh checked evidence. Otherwise it is `{sourceRootId,root}`: an opaque checked navigation token and the absolute worktree root. It uses the existing review fingerprint inputs (session/target/revision, workspace Git state, candidate identity/checked bytes). This read capability does not grant approval or relax unsaved/build/test/signature gates. |
| `view.get` (`view:"call"`) | Optional `sourceRootId` defaults to the workspace. A candidate token selects its core model and adds per-node `added`/`changed` flags from `Proposal.delta`; response and node source IDs identify the candidate. Shared `views.call_path`/`layout_call_view` include changed/new callables, including disconnected ones, at the default root. Candidate requests cannot contain `traceId` (`invalid_params`). Workspace playback/model/cache are unchanged. |
| `source.resolve` | Accepts the checked candidate token and resolves `usr`/`file` inside that worktree using the same ambiguity, metadata and symlink boundaries. Candidate tokens are revalidated on every graph/source request. Changed/replaced/decided candidates or obsolete review evidence return `stale_evidence`; rebuild and reopen the proposal view. Existing unknown-source IDs still return `invalid_params`. |
| `project.analyse` | Optional `automatic:true` checks `unsavedDocuments` (URI array, default empty) through the review document guard and refuses pending proposals with `proposal_pending`; active workflows retain `workflow_busy`. These refusals leave revision, playback, candidate and cache untouched. Accepted analysis uses the existing operation and publication rules; `source_watch.snapshot_project` before/after analysis marks a result stale if source changes during the operation. |

`ICODA: Show Proposal Call View` opens a separate panel through the registered
`icoda.showProposalCallView` command. It uses the existing renderer, selection and
native editor boundary, hides recorded playback controls, and keeps the project's
trace, root and camera intact. Native documents, including dirty candidate buffers,
are reused. Candidate decisions/rebuilds and session changes dispose of that panel;
stale on-disk candidate edits require a rebuild before further source navigation.

`icoda.autoAnalyse` defaults to true per workspace folder. Source saves and native
filesystem create/change/delete events are coalesced (1 second for source events,
then 300 ms for analysis scheduling). The watcher covers analysed Python/C/C++
extensions and excludes metadata, hidden and common dependency/build directories.
It resolves symlinks before accepting events, including surviving parents for
deletions. Source callbacks survive analysis revision changes but never cross an
explicit project/target selection; overlapping events queue a subsequent refresh.
Busy operations, dirty project buffers and pending proposals defer automatic work.
Watchers/timers are disposed with their owning session. Progress uses VS Code's
window status; manual analysis keeps its cancellable notification. Analysis retains
the existing revision/trace invalidation behavior: disable `icoda.autoAnalyse` when
editing while retaining loaded playback. No build/provider is scheduled by a source
event, and unsaved editor text is never written or replaced by analysis.

It45 was verified before implementation with Node 24.21.0, the existing Python
venv executable (not its resolved symlink), VS Code 1.96.4 and Linux/X11:
`npm run compile`, `npm test` (**237/0**), `npm run test:integration`
(**37/0**, workspace 29, empty 1, C++ 2, untrusted 5), and `npm run test:vsix`
(**4/0**) passed, including P01 `fileClustering`. No P01 defect was found.
The saved It45 diff confirms that `view.state.get/set` were introduced there;
both methods and `cluster.assignFile` already appear in `METHODS`, initialize's
method capability list and the P01 contract above. P01 remains Delivered; P11
retains the remaining view-state and shared-lock work explicitly.

Iteration 46 verification: `npm run compile` passed; `npm test` **244/0**;
root `python -m pytest -q` **1857 passed, 8 skipped**, no failures (389.24 s).
The focused P02/P05 service run passed all six cases. Native command evidence
passed in VS Code 1.96.4: `npm run test:integration` **39/0/0**
(passed/failed/skipped: workspace 31, empty 1, C++ 2, untrusted 5);
`npm run test:vsix` **4/0** in a fresh installed profile. The final native
reports are `icoda-integration-GaXaxq/` and `icoda-integration-p17GaR/` respectively.
Changed-module Ruff and `git diff --check` pass; the optional service mypy check
retains five pre-existing errors in unchanged `force_layout.py`/`source_edit.py`.
Starting HEAD was `fde592e3636dd19c9e84c51ffb43337d395fc717`; the accumulated
migration edits were retained. Only P02/P05 change disposition, P11's remaining
work is corrected, and committed fixtures are unchanged. No commit or merge.
Reports are under `/tmp/ai-loop-worker-reports/J20260927-170326-588902/iteration46/`:
`it45-compile.log`, `it45-npm-test.log`, `it45-integration.log`, `it45-vsix.log`,
`compile.log`, `npm-test.log`, `focused-python.log`, `pytest.log`,
`integration.log`, `vsix.log`, and native `p02-candidate-call-view.json` /
`p05-source-refresh.json` in the generated `icoda-integration-*/` directories.
The root suite used the prepared ICODA venv plus the existing AI-Loop venv
site-packages on PYTHONPATH for its Redis dependency, with LLVM 18 on PATH;
no dependencies were installed. EDH screenshot capture uses system Python's
existing GI bindings. Controlled temporary Git/worktree fixtures establish the
candidate workflow; no real provider or additional platform is qualified here.

Each target item contains `id`, `kind`, `name`, `label`, `configuration` and
`entryUsr`. Whole Project has `id:null`, `kind:"whole-project"`, name/label
`"Whole Project"`, and null configuration/entry. Other kinds are `executable` or
`library`; configured entries use the CMake name/configuration. Source-only mains
use their relative file as the name and null configuration. IDs are opaque strings
deterministically encoded from `Entry.key` (file, target name, configuration), so
they survive reopen/reanalysis without depending on session IDs or absolute roots.
`executables.read_targets` uses `cmake.build_directory`; `executables.entries`
offers analysed mains (including source-only fallbacks) and CMake libraries. As
on desktop, a CMake executable without an analysed main is not yet selectable.
Missing/invalid CMake metadata yields `target_metadata_unavailable` or
`target_metadata_invalid` diagnostics while preserving source-derived choices.
No tool installation is needed for reading this metadata.

Opening/analysing restores the saved desktop key through `executables.choose`:
an exact or unique same-file match, otherwise a sole choice, otherwise Whole Project.
An explicit saved `[]` always keeps Whole Project, even with a sole target. Only
`target.select` writes this key; listing/opening/viewing do not persist defaults.

The Call View payload contains `view:"call"`, `root`, `roots`, `depth`, `callers`,
`libraryMode`, `stale`, `staleReason`, `nodes`, `edges`, `width` and `height`.
The default root is the selected executable's entry, otherwise `views.default_root`.
Libraries use `views.library_roots` (API/header entries or incoming-free call
components), with `root:null` and all entries in `roots`. An explicit root must
be a callable in the scoped model. Passing null restores the default. Empty models
return empty nodes/edges/roots. Root/depth/callers are request-local, not persisted.
G07 adds only the optional boolean `callers` parameter and its response field.
Omitting it preserves the existing callee layout exactly; true delegates to
`views.layout_call_view(..., callers=True)`. Edge direction remains caller to
callee. This addition neither changes session/revision/target identity nor
persists settings; invalid non-boolean values produce `invalid_params`.

Nodes retain the core `CallNode` fields: `usr` (stable entity ID), `label`, `x`,
`y`, `level` (layer), `status`, `kind`, `signature` and `brief`, plus
`sourceRootId`, workspace-relative `file` and one-based `line`. External nodes
have null file/line; legacy locations outside the workspace have null file.
Edges retain `source`, `target`, `label`, `loop` (the desktop's recursion/backward
edge flag), `uncertain` and `free`, plus `kind:"calls"`. Geometry is in core
layout units; frontend zoom/pan is not service state. G07 now renders selection
highlights. G08 adds opt-in trace-observed paths/nodes through `traceId`, described
below. The service does not yet publish proposal markings. Existing `trace.*`
symbol resolution still uses the whole model and does not verify an executable association. Target
changes invalidate playback rather than relabeling an existing recording.

Models use the existing `DerivedModel.to_json` schema, as an object rather than
a JSON string. Playback states contain session context, `traceId`, `position`
(zero before selection, otherwise one-based grouped index), `total`,
`currentEntityUsr`, `source`, `repeatCount`, `callerCounts`, `status`, the additive
G08 `currentCall` object described below, and
`availability: {into, over, out, previous, reset}`. With no selection, entity and
source are null and counters are empty/zero. A selected source contains
`sourceRootId`, workspace-relative `file` and one-based `line`; callers use
`source.resolve` for relocation/disambiguation. A legacy location outside the
root has `file:null` rather than leaking another root into editor navigation.
Forward availability comes directly from `CallPlayback.can_step`; Previous and
Reset are available at positive positions. Previous from the first call resets,
matching the shared core. Empty/unresolved traces return the core's explanatory
status and disabled actions. No TypeScript stepping logic or Next Call operation is added.

Responses are exactly `{"id":…, "status":"ok", "result":…}` or
`{"id":…, "status":"error", "error":{"code":…, "message":…, "details":{…}}}`.
`status:"cancelled"` remains reserved; G09 cancellation uses `status:"error"` with `error.code:"cancelled"`.
Invalid JSON or requests without a usable ID produce an ID-free
`{"method":"protocol.error", "params":{"error":{…}}}` notification. Request
frames are limited to 1 MiB including the newline; oversized frames are drained
through their newline before processing the next frame. Non-UTF-8 input and
non-JSON constants are rejected. Outgoing JSON is compact, ASCII-escaped UTF-8,
newline-terminated and flushed per response. A private stdout descriptor carries
only protocol; Python prints, native descriptor-1 writes, inherited child output
and diagnostic logging go to stderr.

Errors distinguish `not_initialized`, `already_initialized`,
`protocol_version_mismatch`, `invalid_json`, `invalid_request`, `invalid_params`,
`message_too_large`, `unknown_method`, `project_not_open`, `project_missing`,
`project_open_failed`, `invalid_session`, `stale_revision`, `stale_target`, `analysis_failed`,
`unknown_target`, `selection_failed`, `model_unavailable`, `unknown_view`, `unknown_root`,
`source_missing`, `source_ambiguous`, `trace_not_loaded`, `invalid_trace`,
`trace_call_missing`, G04's `missing_tool`, and unexpected `internal_error`. The existing analysis
child reports timeout/failure diagnostics through `AnalysisResult`; this slice
wraps those as `analysis_failed` rather than inferring typed errors from prose.
EOF now cancels owned G09 operations and waits for their cleanup; other queued operations remain serialized. The client rejects pending requests on backend termination. See G09 for process ownership and shutdown limits.

Reproduce this slice's subprocess acceptance with
`python -m pytest -q tests/test_service.py`. Its temporary Python fixture is parsed
without execution; synthetic TSV records prove independent B→C/D/E destinations,
source coordinates, counters and availability. Separate fresh interpreters check
headless imports and deliberately noisy Python/native/child output. Existing
`tests/test_call_trace.py` and `tests/test_trace_stepping.py` remain the shared
stepping regressions; this is service evidence, not VS Code UI acceptance.
The target tests reuse the configure-only multi-executable CMake fixture from
`tests/test_executables.py`, add a library and seed a controlled cached model.
They read real file-API metadata with tool launches forbidden in the service,
check scoped/Whole Project results and persistence, and retain the unchanged
whole-model cache. Python Call View tests analyse the six-function fixture and
compare locations, edges and geometry to the shared core. A desktop/service spy
test proves both invoke `views.layout_call_view`; fresh-interpreter checks cover
all three new methods without importing Tk or GUI modules.

### Playback acceptance carried forward

The new parameterized regression in `tests/test_trace_stepping.py` uses complete,
single-threaded entry/exit events for:

```text
main
  A
    B
      C
    D
  E
```

Each of the three independent test invocations steps through `main`, `A`, `B`
using Into, then asserts Into → C, Over → D, or Out → E. All six returns resolve
to entities too, so a return exposed as a stop would fail the six-call total,
destination position, exact remaining visible sequence or retained final E
assertions. At exhaustion all forward modes are unavailable. These cases pass
against the existing `CallPlayback`; **no production fix was needed**.

Existing trace tests cover repeat/caller counts, recursion, unresolved calls,
interleaved threads, missing/mismatched returns, Previous/Reset and Tk control
wiring. At M0, parent-scope and repeat-group behavior in truncated traces still needed
regressions. G08 below adds those failing cases and corrects shared `CallPlayback`
return/ancestor checks. The single-threaded example alone is not evidence for
every incomplete-invocation case.

G08 must preserve call-only stops, same-thread Over/Out and global Into order,
repeat aggregation, end selection, source synchronization and root/viewport.
The existing toolbar (`icoda_gui/call_view.py:90`) has Load trace, Previous call,
Step Over, Step Into, Step Out and Reset horizontally; keep those six controls
with overflow at narrow widths, and keep Next Call absent.

## G02 extension development scaffold

This iteration started at `fde592e3636dd19c9e84c51ffb43337d395fc717`, with existing
edits to `docs/GAP_ANALYSIS.md`, `docs/RELEASE_MATRIX.md` and
`tests/test_trace_stepping.py`, and untracked `docs/VSCODE_MIGRATION.md`,
`icoda_core/service.py` and `tests/test_service.py`. Those earlier changes were
preserved; only this document, `vscode/` and its ignore rules were changed. No
commit or merge was made.

The scaffold contributes **ICODA: Open Project**, **ICODA: Show Output** and
**ICODA: Restart Backend**, an ICODA activity-bar container and a placeholder
Project tree. Activating a command or opening the view registers the UI without
starting Python. Open Project selects the sole workspace folder or asks which
folder in a multi-root workspace; with no folder it explains how to proceed.
It sends only `project.open`, logs the returned cached state, and performs no
analysis. The view explains the no-folder, untrusted, backend-not-started and
opened-project states. Restart creates a fresh connection; reopening a project
is explicit. Show Output is always available.

The declared minimum is VS Code **1.74.0**, with `@types/vscode` pinned to
**1.74.0** (the 1.74.1 typings actually describe 1.75). This is the baseline for
[automatic command/view activation](https://code.visualstudio.com/api/references/activation-events);
explicit `onCommand`/`onView` events also document the intended activation scope.
The scaffold uses stable commands, OutputChannel, TreeView/message, workspace
folder picker, configuration, disposables and Workspace Trust APIs available at
that baseline. It uses no proposed APIs. Only output and the placeholder view
are available before workspace trust; starting Python requires trust because
the configured runtime or repository virtual environment is executable code.

### Prerequisites and commands

Install **Node.js LTS 22 or newer** and its bundled npm explicitly before
development. For a user-local Linux installation, match `uname -m` to the
official architecture (`x86_64` → `linux-x64`, `aarch64` → `linux-arm64`), download
the chosen LTS tarball and `SHASUMS256.txt` from the same release directory under
[nodejs.org/dist](https://nodejs.org/dist/), and verify the tarball with
`sha256sum --check` before extraction. Extract outside the checkout, for example
under `~/.local/share/nodejs/<version>`, and link `node`, `npm` and `npx` into
`~/.local/bin`. Prepend the installation's `bin` to PATH for these commands and
the VS Code launch; no shell startup-file or global PATH changes are required.
Check `node --version` and `npm --version`. Activation never installs software.

Prepare Python 3.10+ and ICODA dependencies using the existing
[handbook bootstrap](../HANDBOOK.md#2-installation-and-launch). Python resolution
is: nonempty `icoda.pythonPath`, then `icoda/.icoda-venv/bin/python` (Windows:
`.icoda-venv/Scripts/python.exe`), then `python3`/`python` from the process PATH.
A configured executable is checked as a file or resolved as a command on PATH,
without adding arguments or silently falling back. A missing/non-executable
override names `icoda.pythonPath` in the error. Set this option explicitly when using a prepared environment
outside the checkout. The output channel records both the selected executable
and `runtime.python` reported by the handshake. Restart after changing it.

Run these from the repository root with the chosen Node bin on PATH:

```bash
npm --prefix icoda/vscode ci
npm --prefix icoda/vscode run compile
# If Python is outside icoda/.icoda-venv, set ICODA_TEST_PYTHON to its executable.
ICODA_TEST_PYTHON=/path/to/prepared/venv/bin/python npm --prefix icoda/vscode test
# Incremental compilation while developing:
npm --prefix icoda/vscode run watch
```

`package-lock.json` is npm-generated. There are no runtime npm dependencies;
the G02 direct development dependencies were TypeScript, Node typings and VS
Code typings. G16 adds the pinned `@vscode/test-electron` development dependency.
Compilation is strict, with source maps and output in ignored
`vscode/out/`; `vscode/node_modules/` is ignored too. Tests use `node --test` on
the compiled files, so run compile after editing TypeScript.

Open **`icoda/vscode/` itself** as the VS Code development workspace (for example
`code icoda/vscode` from the repository root). Choose **Run ICODA Extension** in
Run and Debug and press F5. The checked-in launch configuration runs the compile
task first and loads `out/extension.js` in an Extension Development Host.
In that host, open a fixture folder, set `icoda.pythonPath` if necessary, and run
**ICODA: Open Project**. Inspect **ICODA: Show Output** for the effective Python,
protocol/backend versions and `project.open` result. Opening the ICODA view or
Show Output alone should not start a backend. Also check an empty window, a
multi-folder workspace, Restart Backend, and shutdown with no Python left over.
These were manual host checks in G02; G16 below adds a separate automated Electron suite.

This scaffold locates the Python package as the parent of the extension directory
and launches `[python, "-m", "icoda_core.service"]` with that package as cwd and
no shell. It therefore requires the repository layout during development. A
standalone installed VSIX with bundled backend/resources is still G17 work.

### Client lifecycle and current limits

One lazy client per window owns the active connection; command work is serialized
to avoid overlapping opens/restarts. The client waits for `initialize` before
sending queued requests, correlates numeric IDs, preserves structured errors,
and separates ID-free notifications (including `protocol.error`) from responses.
UTF-8 NDJSON is read across arbitrary pipe chunk boundaries; stderr is output
only. The client enforces the service's 1 MiB request limit, not a response limit
(model responses may be larger). Initialization has a 10-second timeout; ordinary
requests have no client deadline. Protocol v1's synchronous non-cancellable
behavior is unchanged. Restart/disposal rejects pending work locally, terminates
the service, escalates to a kill after one second if needed, and waits for close.
Process/stream failures reject pending requests and permit a fresh connection.
Deactivation disposes command/workspace/configuration listeners, the tree, Python
and the output channel. This is not cancellation of future analysis/build child
process trees, which the scaffold never starts.

### G02 verification (2026-09-27, Linux x86_64)

Node **v24.21.0 LTS** and bundled npm **11.19.0** were installed user-locally
outside the checkout. The official `node-v24.21.0-linux-x64.tar.xz` passed
`sha256sum --check` against its release's `SHASUMS256.txt`:

```text
node-v24.21.0-linux-x64.tar.xz: OK
fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6
```

| Check | Observed result |
|---|---|
| `npm --prefix icoda/vscode ci` | Exit 0: `added 4 packages, and audited 5 packages in 364ms`; `found 0 vulnerabilities`. |
| `npm --prefix icoda/vscode run compile` | Exit 0: `> icoda@0.1.0 compile`, `> tsc -p .`; no diagnostics, `out/extension.js` exists. |
| `ICODA_TEST_PYTHON=… npm --prefix icoda/vscode test` | Exit 0: `node --test out/test/*.test.js`; **10 passed, 0 failed, 0 skipped**. Uses the prepared CPython 3.12.3 environment. |
| `python -m pytest -q` from `icoda/` in the prepared environment | **943 passed, 10 skipped, 1 failed in 48.06s**; only `tests/test_verify.py::test_evidence_documents_match_current_module_inventory` fails, as at baseline. |
| TypeScript function-size inspection | Largest function is 20 lines, below the 30/50-line rule. |
| `git diff --check`; `git check-ignore` for node_modules and out | Passed. |
| Extension Development Host launch | The initial Snap-wrapper attempt was blocked. **Superseded by It8:** the packaged Linux executable launched successfully with isolated profile/extensions directories and `--no-sandbox`. Call View/native-source/theme/overflow smoke evidence is recorded below. This caveat does not qualify normal sandboxed startup or another platform. |

The temporary Node fixture has a Unicode/space-containing path and a Python
source file that raises if executed. Tests cover handshake and read-only open,
protocol-version mismatch with structured details, 24 simultaneous requests with
distinct responses/errors, `model_unavailable` followed by successful source
resolution, and all pending requests rejecting after a real process kill.
Additional checks cover a missing Python executable, idempotent disposal,
oversized requests, real service stderr diagnostics and manifest/compiled-entry
consistency. The POSIX kill test pauses the actual backend before queuing work
and then kills it, making the pending-request condition deterministic. These are
Node/service results, not VS Code UI acceptance or Windows/macOS qualification.

## G05 project analysis and target selection

Iteration 5 started at `fde592e3636dd19c9e84c51ffb43337d395fc717`, preserving
the existing changes to `docs/GAP_ANALYSIS.md`, `docs/RELEASE_MATRIX.md`,
`tests/test_trace_stepping.py` and the untracked migration document, service,
service tests and `vscode/` scaffold. This slice changes only `vscode/` and this
document; no commit or merge was made.

**ICODA: Analyse Project** (`icoda.analyseProject`) opens a workspace folder
through the existing Open Project picker when no project is open, then calls
`project.analyse` under a native progress notification. In a multi-root workspace,
the chosen folder remains the analysis root until another explicit Open Project.
Workspace Trust is required to start Python or perform analysis/target writes.
The Project tree now shows the root, model state (`none`, `fresh`, `stale`,
`analysing`), whole-project entity/edge counts and a Targets branch. Diagnostics,
including file-specific parse errors, go to ICODA output. Typed failures retain
their code and message; failed analysis updates the revision and displays the
retained model as stale with its reason in the model item's tooltip.

**ICODA: Select Target** (`icoda.selectTarget`) offers a QuickPick of Whole Project,
executables and libraries from `targets.list`. Clicking a target tree item selects
it directly. Both surfaces mark the current selection. Target selection sends
only `target.select`, using the current identity at the top level and the desired
target in `params.targetId`; it neither invokes analysis nor replaces whole-project
counts with the returned projection. The existing service persists the choice.
The command palette and Project view menu expose selection only while
`icoda.projectOpen` is true. Both new commands have explicit command activation.

`sessionState.ts` owns the client identity. Each request captures a generation
and session/revision/target context. Read replies must match that context exactly;
analysis must advance its revision by one; selection advances it only when the
target changes. Only a current open request may establish a new session at
revision 1. Reset invalidates even pending opens without a session ID. Obsolete
replies are dropped and logged. `invalid_session`, `stale_revision` and
`stale_target` errors offer **Refresh Project**, which runs the explicit folder
picker again. Tree selections also carry their original context to reject clicks
on an obsolete item.

`projectSession.ts` coordinates these four service operations without VS Code.
`projectTreeData.ts` constructs plain descriptions; `projectTree.ts` is the thin
TreeDataProvider adapter. **Protocol v1 and Python code are unchanged**: counts
come from the existing `model.entities`/`model.edges` arrays, and stale state from
`model.stale`/`model.stale_reason`, including `analysis_failed.error.details`.
The existing `BackendClient` and `pythonRuntime` remain in use.

Commands remain serialized, including Restart Backend. Analysis progress remains
non-cancellable; G09 adds cancellable progress for its four target operations. Generation tests cover delayed replies
across reset/replacement, but this slice does not implement cancellable analysis
children, concurrent cache writers, source watchers or automatic reanalysis.
Those G14/G06 limitations remain; the later It8 host smoke below supersedes
the initial host-startup limitation; this is the requested G05 command/tree slice, not full migration acceptance.

### G05 verification (2026-09-27, Linux x86_64)

Use the Node setup and prepared `ICODA_TEST_PYTHON` environment documented above.
The Python executable must retain its virtual-environment path rather than
resolving its symlink to the base interpreter.

| Check | Actual result |
|---|---|
| `npm --prefix icoda/vscode ci` | Exit 0: `added 4 packages, and audited 5 packages in 437ms`; `found 0 vulnerabilities`. |
| `npm --prefix icoda/vscode run compile` | Exit 0: `tsc -p .`, strict compilation with zero diagnostics. |
| `ICODA_TEST_PYTHON=… npm --prefix icoda/vscode test` | **31 passed, 0 failed, 0 skipped**. Real service and plain TypeScript tests; no VS Code module imported in Node tests. |
| `python -m pytest -q` from `icoda/` in the prepared environment | **943 passed, 10 skipped, 1 failed in 48.31s**. Only the pre-existing `tests/test_verify.py::test_evidence_documents_match_current_module_inventory` failure. |
| Function-size inspection of TypeScript using its AST | Largest function, including tests, is 24 lines; all below the 30/50-line rule. |
| Repository scope check and `git diff --check` | Only this slice's permitted files changed; existing unrelated modifications retained. Whitespace check passed. |

The checked-in Python fixture at `vscode/src/test/fixtures/python/` produces
**7 entities and 5 edges** and raises at module scope if executed. Real-service
Node tests open and analyse a disposable copy, list Whole Project and its source
executable, select both, check every identity transition, confirm idempotent
reselection and persisted selection after reopening, and compare the whole-model
cache before/after selection. A second run breaks the source syntax, verifies
retained counts/stale diagnostics, selects a target with the updated context,
repairs the source and obtains a fresh model again. No C++ toolchain is needed.

Plain unit tests cover stale session/revision/target responses, reset and project
replacement during delayed analysis, delayed open/list/select responses, typed
identity failures and a target-select spy proving no analysis request is sent.
Tree tests cover all four model states, existing empty states, Whole Project,
executable/library items, selection marking and context-bearing actions.

Manual host procedure (not executed in this slice): launch the development host
as above, open a disposable copy of the Python fixture, run Analyse Project and
inspect the tree/output; choose Whole Project and the executable from the palette
and tree and check the unchanged counts. Break `main.py`, analyse again and check
the stale reason/error; repair and analyse again. Repeat Open/Analyse in a
multi-root workspace, and check the no-folder and untrusted empty states. The later It8 host smoke established activation, graph and source interaction;
this broader G05 manual scenario was not executed in that slice. No Windows/macOS
acceptance is claimed here.

## G06 native source navigation and save notifications

Iteration 6 implements **ICODA: Go to Entity** (`icoda.revealEntity`) in the
Command Palette and Project view menu while `icoda.projectOpen` is set. Execution
also requires Workspace Trust. Its QuickPick lists files, classes/structs and
functions/methods/constructors/destructors from the held whole-project model,
including files without callable entities. Open and analysis refresh that model;
target changes retain the whole-project catalog and use the new target identity
on subsequent source requests. An empty catalog directs the user to Analyse Project.

`sourceNavigation.ts` is independent of VS Code. It translates the existing
`source.resolve` success/error contract into `open`, `choose`, `missing` or typed
`error` outcomes. **No Python or protocol addition was necessary**: the existing
success already supplies the relocated relative `file` and absolute `path`, and
`source_ambiguous.error.details` already supplies ranked tied `candidates` and
the requested entity line. Lookup remains in `source_edit.find_source`, with its
suffix ranking, metadata exclusions and project/symlink boundaries. Every request
carries the current session/revision/target context and source-root ID; SessionState
rejects obsolete replies. Candidates are resolved again after the user chooses one.
Missing sources and typed failures produce a local source-location warning and
ICODA output entry, without invoking provider or Binary recovery.

`sourceEditor.ts` supplies reusable `revealSource(context, ref, preserveFocus)`
glue. Explicit Go to Entity uses `preserveFocus:false`, `showTextDocument` and
`revealRange`, converting the service's one-based line to editor coordinates
(column 1, since v1 has no column field). It checks the physical path stays in the
project, reuses an open document by URI or physical-path alias, and opens a document
only when none is already open. It never writes, reloads or reverts a dirty buffer.
Session and trust checks guard the awaits before requesting or revealing source.

A project-scoped `onDidSaveTextDocument` listener filters Python and the C/C++
source/header/module suffixes from `analysis.CPP_SUFFIXES`, including generated
sources under the chosen root. `sourceChanges.ts` owns the plain path filter and
one-second trailing debounce. Rapid saves produce one tree stale mark naming the
latest saved file; unrelated extensions, other roots and project metadata are
ignored. Symlink destinations are checked before notification. The user reruns
**ICODA: Analyse Project** explicitly; saves do not invoke analysis or change the
wire revision/cache. A save mark during analysis remains stale after that earlier
analysis completes. The listener and pending timer are disposed on project switch,
backend exit/restart and deactivation. This is local save notification, not an
external filesystem watcher or persisted backend stale state.

### G06 verification (2026-09-27, Linux x86_64)

The starting HEAD remains `fde592e3636dd19c9e84c51ffb43337d395fc717`.
Only `vscode/` and this document changed during this slice; all earlier working-tree
changes were retained. No commit or merge was made. Commands use user-local Node
v24.21.0/npm 11.19.0 and the prepared Python environment described above.

| Check | Actual result |
|---|---|
| Before edits, `npm ci` / `npm run compile` from `vscode/` | Exit 0; `added 4 packages, and audited 5 packages in 394ms`, `found 0 vulnerabilities`; `tsc -p .` with zero diagnostics. |
| Initial `npm test`, without `ICODA_TEST_PYTHON` | **26 passed, 5 failed**; default Python lacks `networkx` (`internal_error: No module named 'networkx'`). No code was changed to mask this environment issue. |
| Before edits, repeat ci/compile/test with prepared `ICODA_TEST_PYTHON` | Exit 0; `added 4 packages, and audited 5 packages in 365ms`, `found 0 vulnerabilities`; strict compile; **31 passed, 0 failed, 0 skipped**, 1112.819702 ms. Confirms It5. |
| After edits, `npm --prefix icoda/vscode ci` | Exit 0; `added 4 packages, and audited 5 packages in 471ms`, `found 0 vulnerabilities`. |
| `npm --prefix icoda/vscode run compile` | Exit 0; `tsc -p .`, strict, zero diagnostics. |
| `npm --prefix icoda/vscode test` with prepared `ICODA_TEST_PYTHON` | **49 passed, 0 failed, 0 skipped**, 1577.311422 ms; no Node test imports VS Code. |
| `python -m pytest -q` from `icoda/`, prepared environment | **943 passed, 10 skipped, 1 failed in 49.25s**; only the pre-existing `tests/test_verify.py::test_evidence_documents_match_current_module_inventory` failure. |
| TypeScript AST function-size inspection | Largest function, including tests: **25 lines**. |
| Starting-file hash comparison; `git diff --check` | Only the 12 permitted source/test/manifest/documentation files changed; no removed files, Python changes or dependency changes. Whitespace check passed. |

The real-service Node acceptance copies `vscode/src/test/fixtures/python/`, analyses
it without execution, and moves `main.py` to `relocated/main.py`. The original
`python:main:B` USR resolves there at line 14 (AT03). Adding `two/main.py` returns
both candidates with line 14; explicitly choosing the second resolves it. Deleting
both yields `missing` with `source_missing` and no provider/Binary diagnosis (AT04).
A separate real-service test rejects outside-root and traversal requests and, on
this Linux host, an escaping symlink. Plain tests cover all four outcomes, entity
choices, stale response identities, save filters/timing/coalescing/disposal,
stale marks during analysis, explicit reanalysis, and manifest activation/visibility.

Manual host procedure (not executed): open/analyse a disposable fixture copy, run
Go to Entity for a file and function, and confirm source focus/line. Modify the
open document without saving, navigate to it again, and confirm its dirty contents
remain. Move/duplicate/delete `main.py` and repeat B navigation as above. Save an
analysed file and inspect the tree tooltip after one second; analyse explicitly to
clear it. Save again and immediately switch projects or restart the backend to
check disposal. Repeat in a multi-root workspace and an untrusted window.
The later It8 smoke demonstrates native source navigation; dirty-buffer interaction
and Windows/macOS qualification remain pending; these Node/service results do not claim UI acceptance.

## G07 interactive Call View

**ICODA: Show Call View** (`icoda.showCallView`) opens or reveals one panel for
the active project session. The command palette and Project title action require
`icoda.projectOpen`; execution also requires Workspace Trust. Open and analyse a
project first, then invoke the command. The graph uses the selected target's
`view.get` nodes, columns and edges directly. Entry points, library API roots,
recursion, shared calls, uncertain dashed `?` edges and function statuses retain
the shared Python layout and model data; TypeScript computes no graph layout.

One horizontally scrollable control row provides an explicit Root selector,
Depth (0–12), Callers, text Filter, zoom and Fit. Filtering matches qualified
name, kind, source file or status, always retains the roots, and keeps the original
coordinates. Changing roots is explicit; selecting a function only highlights it
and calls `revealSource(context, {sourceRootId, usr}, true)`. The native editor
opens beside the diagram with focus preserved. Selection retains the chosen
root and viewport and sends no new layout request. Tooltips include qualified
name, kind, source line, status, signature and purpose. The renderer can show
optional node `added`/`changed` boolean markings, but this service slice supplies
no proposals and makes no proposal-workflow claim.

Drag or scroll to pan; Ctrl/Cmd+wheel zooms around the pointer. Tab reaches
controls and nodes; Enter/Space selects a node. With graph focus, arrow keys pan,
plus/minus zoom, and F fits. Shortcuts stay inside the webview. Theme variables
cover light/dark/high-contrast styling; narrow panels scroll the single control
row instead of adding rows. Trace loading, stepping and the trace toolbar are
not part of this slice.

`callViewMessages.ts` validates **every** incoming webview message before dispatch:

| Message | Fields beyond `type` |
|---|---|
| `ready` | None; requests the current render state after first load or revealing a hidden webview. |
| `select` / `root` | `version`, `usr`; only `root` accepts null to restore entry points. IDs must belong to the current graph; external nodes cannot become roots. |
| `depth` / `callers` / `filter` | `version` and respectively integer `depth` (0–12), boolean `callers`, or string `text` (up to 256 characters). |
| `viewport` | `version`, `viewport:{x,y,scale}`; finite bounded coordinates and scale 0.1–4. |
| `fit` | `version`, positive finite `width` and `height` of the drawing surface. |

Unknown types, extra fields, wrong types, NULs, oversized fields and payloads over
16 KiB are dropped and logged without printing payload contents. `version` is a
panel-local graph request counter, not a wire model revision. `CallViewModel`
owns graph, selection, controls and viewport outside VS Code. Every `view.get`
attaches the captured SessionState context; responses must match session,
revision and target. Superseded responses and obsolete webview actions cannot
replace a newer graph. Analysis and target revisions request fresh data; save
notifications update the stale status without relayout. An explicit root removed
by analysis falls back to the backend's entry points. Project switches, removal
of the owning workspace folder, backend exit/restart, panel close and deactivation
dispose the panel/listeners and invalidate pending view requests.

The HTML uses a random nonce, `default-src 'none'`, no inline handlers or remote
resources, and `localResourceRoots` restricted to the extension's `media/`
directory. Static JS draws SVG using DOM creation and `textContent`, never graph
text interpolated into HTML. This follows the
[VS Code webview guidance](https://code.visualstudio.com/api/extension-guides/webview).
The package still has no runtime npm dependencies.

### G07 verification and preliminary fixes (Linux, 2026-09-27)

Iteration 7 started at `fde592e3636dd19c9e84c51ffb43337d395fc717` with the earlier
migration changes already present, including the scaffold, service, service tests,
trace regressions and evidence documents. Those changes were preserved.

- **P1:** `git worktree add --detach <temporary-directory> HEAD`, followed there by
  `python -m pytest -q icoda/tests/test_verify.py::test_evidence_documents_match_current_module_inventory`,
  reproduced `1 failed in 0.16s` at the base commit. The worktree was removed with
  `git worktree remove --force <temporary-directory>`. The working-tree rerun was
  `1 failed in 0.14s`. Core/service additions are already inventoried; the prior
  discrepancy was pre-existing at base `fde592e`. **It8 corrected both evidence
  inventories to 81 = 74 + 7**, including the service test module, and 49 core
  modules. Its verification-test run passed (10 passed in 0.23s).
- **P2:** `watchSourceSaves` uses the plain `watchSourcePaths` adapter. It resolves
  the project root once and resolves each saved path before the boundary check.
  The real-filesystem Node regression saves through a symlinked **parent**, marks
  the model stale, rejects an escaping symlink, and checks disposal. Windows skips
  this symlink case. All seven source-change tests pass on this Linux host.
- **P3:** before edits, npm ci reported `added 4 packages, and audited 5 packages`
  and `found 0 vulnerabilities`; strict `tsc -p .` exited zero; Node reported
  `tests 49`, `pass 49`, `fail 0`. The first unconfigured run had 42 passes and
  seven failures because the default Python lacked networkx; setting
  `ICODA_TEST_PYTHON` to the prepared environment produced the clean baseline.
  After changes, the same install/compile commands pass with zero vulnerabilities
  and zero compiler errors; Node reports **64 tests, 64 pass, 0 fail, 0 skipped**.
- Node tests exercise message/CSP validation, geometry/edge/root mapping,
  root-preserving filtering, selection/source/viewport state, late results,
  revision refresh and disposal. The real Python fixture is analysed without
  execution: its exact edges are main→A, A→B, B→C, A→D and main→E; selecting B
  resolves to `main.py` at its analysed line. Manifest tests assert the command,
  activation event, trust enablement and `icoda.projectOpen` menu conditions.
- `python -m pytest -q tests/test_service.py`: **29 passed in 8.04s**. The callers
  regression compares actual coordinates and edges with the shared layout,
  validates non-boolean input, and confirms omitted/false callers equivalence.
- `python -m pytest -q` from `icoda/`, using the complete prepared development
  environment: **1 failed, 944 passed, 10 skipped in 50.72s**. The P1 inventory
  defect was the sole It7 failure and was corrected by It8. An earlier run in a
  minimal test environment had three wheel
  setup errors due to missing setuptools; the complete environment resolves them.
- Ruff passes for both changed Python modules; focused mypy with
  `--follow-imports=silent` passes for `icoda_core/service.py`. An initial mypy
  invocation from the repository root also traversed existing modules and found
  33 errors (including missing stubs); it is not a clean whole-core gate.

### It8 Linux host smoke and inventory correction (2026-09-27)

The successful isolated-profile Linux Extension Development Host smoke supersedes
It7's launcher limitation. It used the installed packaged VS Code executable
with `--no-sandbox`, separate user-data/extensions directories, the checked-in
extension, and a temporary copy of `vscode/src/test/fixtures/python/`. No system
sandbox configuration was changed. This establishes the exercised development
host path; it does not qualify default sandboxed startup, Windows/macOS or a VSIX.

Retained `it8-ui-evidence.json` and `it8-callview-*.png` show root A, selection B,
unchanged viewport, native `main.py:14` in column 2 and focus staying in Call View.
Light/dark themes, keyboard Enter, filtering, depth, Callers and a single scrolling
row were exercised. The narrow toolbar was 651 px wide, 661 px scroll width and
36 px high. Evidence lives in the supplied system-temp worker report directory.

It8 also corrected `GAP_ANALYSIS.md` and `RELEASE_MATRIX.md`: **81 = 74 + 7**
Python test modules, including `test_service.py`, and 49 core modules. The
pre-existing two-module discrepancy was reproduced at base `fde592e`;
`it8-base-pytest.log` reports 1 failed, 9 passed. After correction,
`it8-verify-pytest.log` reports 10 passed; `it8-full-pytest.log` records the separate
repository-root run, 1505 passed, 11 skipped. These are It8 observations, not new
G08 verification or updated historical platform release qualification.

## G08 recorded-trace playback (iteration 9, Linux, 2026-09-27)

This slice started at `fde592e3636dd19c9e84c51ffb43337d395fc717`, retaining the
It8 inventory corrections, trace tests, service and extension working-tree files.
No repository commit or merge was made. Changes are confined to shared playback,
the service, Call View/source-reveal integration, their tests/TSV fixture and this
document. `GAP_ANALYSIS.md` and `RELEASE_MATRIX.md` were already corrected by It8
and were not edited again.

The existing single horizontally scrolling Call View row now labels **Trace
playback** and contains exactly **Load Trace, Previous Call, Step Over, Step Into,
Step Out, Reset**. No Next Call control or command is introduced. Load Trace uses
`showOpenDialog`, initially at the selected project, and validates the chosen
physical path against that project's physical root before `trace.load`. Other
workspace roots and escaping symlinks are rejected locally; `.icoda` recording
paths inside the project are permitted. The webview cannot supply a file path.

All navigation calls the shared Python `CallPlayback`; TypeScript has no depth,
return or grouping rules. The five navigation buttons use only the returned
availability flags. Graph clicks/Enter seek the first grouped call of a function
when a trace is loaded. Selection and native source reveal (`preserveFocus=true`)
share the returned USR/line. The counter, thread/depth tooltip and caller-edge
`×count` annotations follow the same cursor. Exhaustion keeps the final call;
Reset clears graph selection and counts without unloading the trace or closing
the editor. Invalid loads retain the previous usable state and show their typed
error; a header-only or unresolved recording has disabled actions and the core's
explanation. Empty files and malformed TSV yield `invalid_trace`.

Loading a recording requests trace-aware layout once with the current root,
depth and callers controls. Shared `call_path`/`layout_call_view` includes recorded
paths beyond the depth limit and free nodes absent from a static path. Later
steps only highlight and annotate that graph. Root, node geometry and viewport
stay fixed during playback; filtering retains the selected recorded node. Trace
operations/source reveals are serialized at the panel boundary. Session/revision/
target, panel version, request number, trace ID and disposal guards reject late
results and obsolete actions. Closing the panel also invalidates a pending source
reveal. CSP/nonce, `localResourceRoots=media` and zero runtime npm dependencies
are unchanged.

### Additive protocol v1 and message changes

- Every successful `trace.load`, `trace.step` and `trace.reset` response adds
  `currentCall`, null before selection/after reset, otherwise
  `{usr, source, threadId, depth, sequence}`. `source` has the existing
  `{sourceRootId, file, line}` shape; `sequence` is the zero-based entry-event
  index. Thread/depth/sequence describe the first entry representing the grouped
  stop, directly from the new read-only `CallPlayback.current_event` property.
  All previous fields and methods, including Previous, remain unchanged.
- `view.get` adds optional `traceId`. Omitting it preserves the static scoped
  layout. Supplying the loaded ID includes that recording's resolved whole-model
  functions/paths through shared layout, keeping the scoped root(s); stale or
  unloaded IDs return `invalid_trace`. No project model/cache is mutated. Existing
  whole-model symbol resolution is retained, so importing a trace does not verify
  its executable binary identity. A target/revision change still unloads playback.
- Strict webview messages add `traceLoad` and `traceReset` (only `type, version`),
  `traceStep` (`type, version, action`, with previous/over/into/out only), and
  `traceSeek` (`type, version, usr`, bounded and required in the current graph).
  Trace IDs and session identity come from the extension, never the webview.
  Extra fields, unknown actions and malformed values are rejected as before.

Four new Python regression cases first failed, demonstrating missing caller
returns, incomplete grouped invocations and replacement-parent jumps. The shared
fix records parent invocation identities and every grouped entry, requiring
matching returns for exited scopes up to the destination's common ancestor.
It checks grouped invocations on the selected entry's thread. Into/global order,
repeat/caller counts, representative-first grouping and same-thread Over/Out
remain intact. Existing recursion, interleaved-thread, unresolved-call, Previous,
Reset and desktop-control tests also pass.

### G08 verification actually run

Use the prepared Python environment and user-local Node on PATH as documented
above; set `ICODA_TEST_PYTHON` for Node tests. The new checked-in fixture is
`vscode/src/test/fixtures/python/calls.tsv`, an explicit synthetic recording of
main/A/B/C/D/E. Python source analysis still never executes that fixture.

| Check | Actual result |
|---|---|
| New incomplete-trace regressions before the core fix | **4 failed, 14 deselected in 0.05s**, retained as `it9-regression-before.log`. |
| `python -m pytest -q tests/test_service.py tests/test_trace_stepping.py` from `icoda/` | **50 passed in 8.09s**. Includes current-call fields, repeats, graph expansion, invalid loads and backend flags. |
| `python -m pytest -q` from `icoda/` | **952 passed, 10 skipped in 60.84s**, zero failures. |
| Repository-root `python -m pytest -q`, with both applications' prepared test dependencies | **1512 passed, 11 skipped in 69.48s**, zero failures (`it9-root-pytest.log`). |
| `npm --prefix icoda/vscode run compile` | Exit 0, `tsc -p .`, zero compiler errors. |
| `ICODA_TEST_PYTHON=… npm --prefix icoda/vscode test` | **78 tests, 78 pass, 0 fail, 0 skipped**. Real Python process tests prove independent B→C/D/E at `main.py:18/23/27`, Previous, graph seek, Reset, exhausted flags and malformed/empty recovery (AT05/AT08/AT09). |
| Ruff on changed Python files; focused mypy `--follow-imports=silent` on service and playback | `All checks passed!`; `Success: no issues found in 2 source files`. |
| Function-size checks | Changed Python functions are at most 37 lines; TypeScript/JS including tests at most 34. All changed functions remain below the 50-line hard limit. |
| `git diff --check`; starting-file hash comparison | Whitespace clean; preceding inventory edits preserved; only task-related files changed. |
| Isolated-profile Linux Extension Development Host | Native Load Trace picker loaded the fixture. Actual webview controls gave **B→C:18, B→D:23, B→E:27**, with native editor column 2, graph focus, root A and unchanged viewport. Previous, graph seek, Reset, disabled forward buttons at E and keyboard Enter on Step Into passed. Light/dark screenshots show the six controls in a single 36 px row; a 651 px panel scrolls its 1371 px toolbar. |
| Complete `verify.bash --artifacts-root …` | **Exit 1**, retaining the previously documented mypy and three desktop GUI failures. Diff, Ruff, byte compilation, provider qualification, real-provider acceptance, sample build/CTest, pytest and analysis passed. Gate pytest: **952 passed, 10 skipped**, **87.34%** coverage. This is not a clean full-gate claim. |

The initial repository-root attempt exited 2 without a retained diagnostic in the
ICODA-only environment, which lacked the sibling application's yaml/redis/requests
packages. The passing root run used the same Python with the sibling prepared
site-packages on `PYTHONPATH`, only for that combined test command. To reproduce,
set `AILOOP_TEST_SITE_PACKAGES` to that prepared dependency directory and run
`PYTHONPATH="$AILOOP_TEST_SITE_PACKAGES" "$ICODA_TEST_PYTHON" -m pytest -q`
from the repository root. This does not add an ICODA runtime dependency.

The native host used the installed packaged executable with `--no-sandbox`,
isolated profile/extensions directories and a disposable fixture copy. The
initial smoke harness needed its synthetic Enter event corrected to include the
carriage return and first-run VS Code onboarding dismissed; the final retained
run passes. Logs, `it9-ui-evidence.json`, `it9-callview-{dark-end,light-selected,
keyboard}.png`, and full-gate artifacts are exclusively in the supplied
system-temp worker report directory. The extension host was closed after the
check. No Windows/macOS, high-contrast/display-scaling, large-project, real
recording UI or installed-VSIX acceptance is inferred from this Linux smoke.

## G04 runtime and toolchain inspection (iteration 10, Linux, 2026-09-27)

This slice began at `fde592e3636dd19c9e84c51ffb43337d395fc717`, retaining the
It8 evidence-inventory edits and It9 shared playback changes, service, tests,
extension and migration document. No commit or merge was made. It9 verification
was closed first: TypeScript compilation exited 0 with no errors and Node reported
**78 tests, 78 pass, 0 fail**. The existing HTML test positively asserts all six
controls in order (Load Trace, Previous Call, Step Over, Step Into, Step Out,
Reset), and rejects Next Call in HTML, script and manifest. G08's section and
matrix row were already present, as were the corrected inventory/host statements.
The shared playback diff is covered by the caller-return, incomplete-repeat-group
and replacement-parent regressions in `tests/test_trace_stepping.py`; this slice
does not alter playback code or UI.

**ICODA: Show Toolchain** (`icoda.showToolchain`) starts the existing lazy Python
client, calls `toolchain.inspect`, and writes effective Python, each tool's path
and source, missing-tool errors, discovery diagnostics and child environment
additions to the ICODA output channel. It works without an open project. It
requires Workspace Trust because discovery can execute installed tool probes.
The command uses native progress, with the service's existing non-cancellable
semantics. Activation only registers UI; it never installs or upgrades anything.

The four new settings and existing runtime setting are strings, empty by default,
with `machine-overridable` scope and Workspace Trust restrictions:

| Setting | Meaning |
|---|---|
| `icoda.pythonPath` | Python executable path or command, without arguments. The existing resolver checks this override, then (only when empty) ICODA's `.icoda-venv`, then `python3`/`python` on PATH. Restart Backend after changing it. |
| `icoda.toolchain.cmakePath` | CMake executable path or command. |
| `icoda.toolchain.ninjaPath` | Ninja executable path or command. |
| `icoda.toolchain.clangPath` | The Clang **C++ driver**, `clang++`/`clang++.exe` (versioned names also work). The shared build selector requires Clang 16+, sibling `clang` and `clang-scan-deps`. |
| `icoda.toolchain.llvmSymbolizerPath` | `llvm-symbolizer` executable path or command. |

Tool overrides are read on each Show Toolchain request, using the selected project
folder's configuration when one is open and workspace/user configuration otherwise.
No shell arguments or expansion are added; use absolute executable paths for tools
outside PATH. An empty frontend setting omits that override. Invalid explicit
overrides remain missing instead of falling back to another installation. Python
selection retains its virtual-environment path rather than dereferencing its
symlink to the base interpreter.

### Additive protocol v1 contract

`initialize.capabilities.methods` now includes `toolchain.inspect`. No existing
field, method, identity rule or playback behavior is renamed or removed.
Inspection does not select a project, change a model revision, write project state
or persist tool overrides. For example, after initialization:

```json
{"id":2,"method":"toolchain.inspect","params":{"cmakePath":"/tools/cmake"}}
```

The result is:

- `runtime: {python}`: the running Python executable, as in the handshake.
- `tools`: ordered entries for `cmake`, `ninja`, `clang`, `llvm-symbolizer`, each
  `{name, path, source}`. Paths are absolute or null. `source` is `override`,
  `discovered` (including Visual Studio or versioned Clang), `path` (inherited
  ordinary PATH) or `missing`. Optional version metadata is reserved; this slice
  does not claim version checks for CMake/Ninja/symbolizer.
- `environment`: **only changed/added key-value pairs** to overlay on a copy of
  the parent's environment for child processes. PATH includes resolved tool
  directories; successful compiler selection includes CC/CXX; Windows also
  includes SDK changes from the existing `vswhere`/`vcvars64` discovery. Unchanged
  parent variables are not returned. Merge case-insensitively on Windows.
- `diagnostics`: discovery failure messages, including SDK initialization or
  unavailable module-capable Clang. Failure of one capability preserves others.
- `errors`: structured `{code:"missing_tool", message, details:{tool, setting}}`
  for each missing tool. Both the message and details identify the actual tool
  and its `icoda.toolchain.*Path` setting. Inventory mode returns status `ok` so
  all available and missing tools remain inspectable together.

A caller needing a particular capability may supply `requiredTools`, for example
`["cmake", "ninja"]`. If one is missing, the normal status `error` envelope uses
`missing_tool`; its details contain `tool`, `setting`, and the complete
`inspection` result. This opt-in check does not establish a global requirement.
Unknown tool names, malformed lists and invalid override types return
`invalid_params` before discovery. Empty override strings must be omitted.

Discovery lives in `icoda_core/toolchain.py`, reusing `clang_build_environment`,
Visual Studio discovery and libclang candidates (including the symbolizer beside
LLVM). The selector now optionally accepts an environment copy and an explicit-only
compiler choice; existing desktop callers retain their preference/fallback policy.
Probe processes receive that copied environment; neither inspection nor Python
resolution modifies `os.environ` or the user's global PATH. A failed SDK probe
preserves ordinary-PATH discovery and reports its diagnostic. Missing CMake,
Ninja, Clang or symbolizer does not gate project.open, view.get, source.resolve
or trace playback. No provider is started by inspection or browsing.

This is the requested discovery/settings surface, not G09 build/run implementation.
The returned paths and environment are available for those future operation
consumers; these request-local overrides do not rewrite existing analysis compiler
settings or change trace symbolization. CMake cache options and normal build trees
remain untouched. Full G04 platform acceptance remains pending.

### Explicit dependency setup

Prepare Python 3.10+ and install dependencies manually from `icoda/` using the
pinned handbook commands, for example:

```bash
python3 -m venv .icoda-venv
.icoda-venv/bin/python -m pip install -e '.[dev]' -c constraints.txt
```

On Windows use `py -3.12 -m venv .icoda-venv` and
`.icoda-venv\Scripts\python.exe -m pip install -e ".[dev]" -c constraints.txt`.
These are installation instructions, **not commands executed by activation or
this iteration**. Python analysis and cached source/graph/trace browsing need no
C++ build tools. For C++ work install compatible LLVM/libclang, CMake and Ninja
explicitly; generated module projects require CMake 3.28+ and clang-scan-deps.
On Windows select the Visual Studio Desktop development with C++ workload, C++
Clang tools, C++ CMake tools and Windows SDK components, or configure standalone
executable overrides. On macOS the existing handbook uses Homebrew LLVM; on Linux
use matching LLVM/compiler/scanner packages for the project. A provider CLI is
only required for the later AI workflows. No packages or tools were installed or
upgraded during this slice.

### G04 verification and limits

Commands use the prepared Python environment and user-local Node described above;
set `ICODA_TEST_PYTHON` for Node tests. The new tests cover override precedence,
missing and invalid overrides, strict missing-tool errors, input validation,
versioned Clang and adjacent symbolizer discovery, capability separation and
unchanged process environment. `tests/test_windows_startup.py` additionally
simulates a Visual Studio installation and empty PATH: real shared discovery
calls mocked vswhere/vcvars, finds bundled CMake/Ninja/Clang/symbolizer, and passes
SDK variables into the compiler probe. It is host-independent test evidence.

| Check | Actual result |
|---|---|
| It9 compile and Node tests before changes | Compile exit 0 with zero errors; **78 tests, 78 pass, 0 fail, 0 skipped**. |
| `python -m pytest -q` from `icoda/` | **971 passed, 10 skipped in 50.68s**, zero failures. Includes the existing shared playback regressions and new service/Windows-discovery tests. |
| Repository-root `python -m pytest -q`, with both applications' prepared test dependencies | **1531 passed, 11 skipped in 63.81s (0:01:03)**, zero failures. Uses the G08 reproduction command with sibling site-packages only for this combined test invocation. |
| `npm --prefix icoda/vscode run compile` | **Exit 0**, `tsc -p .`, zero compiler errors. |
| `ICODA_TEST_PYTHON=… npm --prefix icoda/vscode test` | **83 tests, 83 pass, 0 fail, 0 skipped**, 2990.662996 ms. |
| Ruff on changed Python files; focused mypy with project configuration | `All checks passed!`; `Success: no issues found in 2 source files`. |
| Function-size inspection using Python/TypeScript ASTs | Changed production functions at most 35 Python lines and 20 TypeScript lines; all under the 50-line hard limit. |
| Starting-file hashes and `git diff --check` | Only 11 task-related files changed in this iteration. Existing It8 inventory and It9 playback edits preserved byte-for-byte; whitespace clean. |
| Complete `verify.bash --artifacts-root …` | **Exit 1**. Diff, Ruff, byte compilation, provider qualification, real-provider acceptance, sample build/CTest, pytest and fresh analysis passed. Gate pytest: **971 passed, 10 skipped in 81.61s (0:01:21)**; coverage **88.16%**, above the 85% gate. The same 32 mypy errors in five unchanged files and three documented desktop GUI failures remain; this is not a clean full-gate claim. |

Reproduce the focused checks from `icoda/`:

```bash
"$ICODA_TEST_PYTHON" -m pytest -q tests/test_service.py tests/test_windows_startup.py \
  tests/test_toolchain.py tests/test_clang_build.py tests/test_trace_stepping.py
```

Compile before the Node test command.
Logs are retained outside the repository in the task's supplied system-temp
worker-report directory as `it10-{compile,npm-test,icoda-pytest,root-pytest}.log`.
Full-gate logs are in `it10-verify.log` and
`it10-verification/20260927-220058-043809/`, including `summary.txt`, `mypy.log`,
`gui.log`, `gui-recovery.log` and `gui-editor.log`. The failures are the previously
documented File View missing source boxes, recovery expected-provider-call
assertion, and editor file-box assertion. Their source files were not changed.
The real-provider gate ran its existing fixture successfully; that is desktop
workflow evidence, not extension-provider or Windows qualification.

**AT10 (a real Windows desktop session) was NOT run on this Linux host.** This
iteration does not qualify Windows, macOS, installed VSIX, or the new command in
an actual Extension Development Host. Node tests cover settings mapping, manifest
contributions, output formatting and an actual Python service connection.

## G09 selected-target build, run and recording (iteration 11, Linux)

Started from `fde592e3636dd19c9e84c51ffb43337d395fc717`. The existing It8–It10
working-tree changes were retained: evidence inventories, shared playback/toolchain
fixes, Windows/playback tests, service, extension and this document. Root
`AGENTS.md` and the referenced handbooks, plans and analysis/persistence modules
were refreshed; no nested ICODA instructions were found. No commit or merge was
made. This section supersedes the earlier slices' non-cancellable build/lifecycle
limitations; analysis itself is still non-cancellable.

The quick It9/It10 checks returned **TypeScript exit 0, zero errors** and **83
Node tests, 83 pass, 0 fail, 0 skipped**. The existing Call View test positively
asserts Load Trace, Previous Call, Step Over, Step Into, Step Out and Reset in
one row and rejects Next Call. G04/G08 sections and matrix rows, the explicit
AT10-not-run statement and the mocked VS-bundled CMake/Ninja/Clang test were
present. The three requested obsolete claims were absent. Removing the blank
line between the fixture's standard-library and project imports produced Ruff
`I001`; it was restored because the repository's import check requires it.

### Protocol v1 additions

The four new methods require the existing top-level `sessionId`, `modelRevision`
and `targetId` (null means Whole Project). All accept optional `cmakePath`,
`ninjaPath`, `clangPath`, `llvmSymbolizerPath`, using the same validation and
inspection as `toolchain.inspect`. Only `trace.record` additionally accepts
`durationSeconds`, a positive finite number, default 5. Unknown params remain
errors. No arbitrary shell command or process environment can be submitted.

| Method / native command | Behavior and result |
|---|---|
| `targets.refresh` / **ICODA: Refresh Targets** (`icoda.refreshTargets`) | Reconfigure existing CMake target metadata through `executables.operate("refresh")`. Requires a previously configured project. Publish the refreshed catalog, preserve Whole Project, persist the restored selection, advance the revision once and invalidate playback. No source analysis is implied. |
| `build.run` / **ICODA: Build Target** (`icoda.buildTarget`) | Require an executable/library selection. Use the existing ordinary Clang configure/build workflow, preserving cached project/dependency options and its existing separate-tree behavior for a different compiler. |
| `target.run` / **ICODA: Run Target** (`icoda.runTarget`) | Require an executable; configure/build it using the shared workflow, then run the discovered artifact with the project root as working directory. Libraries/Whole Project return `invalid_target`. |
| `trace.record` / **ICODA: Record Trace** (`icoda.recordTrace`) | Require an executable. Use shared instrumentation generation/configuration and `operate("run")` in `.icoda/cache/instrumented-debug-build`, then return the nonempty trace. The ordinary build tree is never configured or built by recording. Each recording has a unique `.icoda/cache/call-trace-<id>.tsv` path. |

Every success includes the existing session context and `message`, `targets`,
`diagnostics`, `target` (the existing target-item shape for the actual operated
configuration), `executable` (absolute artifact path or null) and `path` (absolute
trace path for recording, otherwise null). `path` can be passed directly as
`trace.load.params.path`. Build/run/record retain the request's revision and
selected `targetId`; the instrumented Debug target/artifact is reported in
`target`/`executable` without replacing the ordinary target catalog/selection.
Refresh alone advances the revision. Persisting a refresh fails before changing
published state if the UI state file cannot be saved.

`initialize.capabilities` now advertises these methods, `cancellation:true`, and
adds `cancellableMethods` listing exactly the four methods. Other operations,
including analysis and standalone toolchain inspection, remain non-cancellable.
State-changing requests execute on one worker. The reader accepts cancellation
while that worker runs; all other requests queue and revalidate their context
when executed. No concurrent model/cache writer is introduced. Late frontend
successes/errors are dropped after a project/target/revision change.

ID-free notifications have `method: "operation.progress"` or `"operation.log"`
and `params: {requestId, sessionId, sourceRootId, modelRevision, targetId, message}`.
Progress describes the current stage; log messages contain the command and
streamed UTF-8 output chunks. A locked writer frames both notifications and
responses as newline-delimited JSON. Captured child stdout/stderr never becomes
unframed service stdout. Existing Python/native stdout isolation remains active.

`operation.cancel({requestId})` bypasses the worker queue and returns
`{requestId, cancellable:true, reason:"cancel_requested"}` for an owned queued or
running operation. Its cancellation event reaches tool-discovery probes, CMake
preset/configure/build and executable children through `process.run_bounded`;
`process.kill_tree` terminates descendants. The original request completes once
with the backward-compatible error envelope (`status:"error"`,
`error.code:"cancelled"`). A request that already finished may return its normal
outcome. Unknown/finished/non-cancellable IDs retain
`{requestId, cancellable:false, reason:"not_cancellable"}`. Cancellation affects
only that request, not unrelated globally registered desktop processes.

EOF cancels queued/running G09 operations and waits for owned processes to stop;
SIGTERM follows the same cleanup on this host. Extension disposal closes stdin
and waits for backend shutdown (with a seven-second forced-exit fallback).
Pending client requests reject on backend exit. Configure/build retain the
shared 600-second limit, presets 30 seconds, target execution 3,600 seconds;
discovery retains its bounded probe limits. `durationSeconds` limits trace
capture, not executable runtime. Cancellation/failure retains build diagnostics
and partial isolated artifacts, never offers a failed recording as successful,
and leaves the connection usable.

| Error code | Meaning |
|---|---|
| `missing_tool` | A required discovered/explicit tool is unavailable; `details.tool`, `details.setting` (for example `icoda.toolchain.cmakePath`) and `details.inspection` identify the remedy. Missing symbolization alone does not block building. Recording retains the core's GCC fallback when Clang is absent and no explicit Clang override was supplied. |
| `build_failed` | Configuration, compilation, metadata refresh or persistence failed/timed out; captured diagnostics identify the stage. |
| `run_failed` | The executable failed to launch, exited unsuccessfully, timed out, or produced no nonempty trace when recording. |
| `cancelled` | The owned request was cancelled, including during tool discovery or configuration. |
| `invalid_target` | Whole Project/library cannot perform the requested operation, or target matching requires an explicit selection. |
| `invalid_session`, `stale_revision`, `stale_target`, `invalid_params` | Existing identity/shape checks still reject work before launch; results are rechecked before publication. |

### Shared implementation and frontend

`executables.py` retains the target matching/build/runtime-deployment decisions,
with small extracted helpers for stage errors, process callbacks and configuration.
Usable tools recorded in the ordinary CMake cache are inspected even outside PATH;
explicit extension tool settings take precedence.
`cmake.py` accepts optional inspected tool paths/environment and an owned preset
runner; `instrumentation.py` still generates all instrumentation. `process.py`
adds incremental output callbacks to its bounded/cancellable runner. Toolchain
probes accept request cancellation, and the Windows batch environment uses an
argument-array `cmd` invocation with a child-only quoted path variable. The
service never changes `os.environ`, global PATH or installed packages. Existing
desktop call sites continue to work without the new optional arguments.

All four native commands have Workspace Trust enablement and an invocation-time
trust check, native progress with Cancel, and ICODA output streaming. A successful
recording offers **Load Trace**; the Call View title identifies its target and
recording, while Output identifies the full executable and trace paths. Loading
uses the same project boundary checks and shared playback model. No stepping,
root, viewport or six-button toolbar semantics changed. Failures/cancellations
release the command lock and cancellation listeners. Compilation and process
launch remain in Python; TypeScript only coordinates UI/protocol state.

Whole-project builds and native full/targeted test commands are still broader
migration inventory work, outside this iteration's four requested methods.
Source analysis, trace browsing and source navigation do not require build tools.

### Verification on this host

| Check | Actual result |
|---|---|
| Repository-root `python -m pytest -q -rs` with both prepared dependency sets | **1552 passed, 11 skipped in 75.21s (0:01:15)**; zero failures, including all G09 service cases and existing desktop regressions. |
| Explicit AT11 command below | **1 passed in 2.01s**, not skipped. Temporary `recorded C++` fixture, CMake target `demo`, real analysed `main.cpp` (`main` → `helper`), real ordinary build/run and isolated recording. The trace resolves at least two calls; Into reaches a project function. Every ordinary-tree file's bytes and modification time match before/after recording. |
| `npm --prefix icoda/vscode run compile` | Exit **0**, `tsc -p .`, **zero compiler errors**. |
| `npm --prefix icoda/vscode test` with the prepared Python | **90 tests, 90 pass, 0 fail, 0 skipped**. Includes command registration/manifest/trust, native-token cancellation mapped to a real build request, a real C++ service build/record/load/step, stale response routing and all six trace controls. |
| Focused Python service/Clang-build/Windows-startup checks | **88 passed in 11.55s**. Build/run failures, missing-tool settings, cache-tool precedence, cancellation/process-tree death, framed notifications, shutdown and retained identity are covered. |
| Ruff on affected Python files; mypy `--follow-imports=silent` on the five affected core modules | **All checks passed!**; **Success: no issues found in 5 source files**. |
| Function sizes; `git diff --check` | Affected Python core functions at most **50 lines**; TypeScript module functions at most **24 lines**. Whitespace check passed. |

The first full run exposed one regression: extra inherited environment keys were
merged into the desktop's explicitly configured child environment. The shared
runner now uses exactly that configured environment. The existing desktop test
and final full suite pass; no unrelated test expectation was weakened.

The eleven final skips comprise one sibling Redis-dependent case, one ICODA
compiler/libclang pairing case, three older checks requiring the unversioned
`clang++` command, and six native Windows cases. G09's real recording tests use
installed-tool discovery and were **not skipped**. The AT11 fixture only skips
when CMake, Ninja or a usable Clang/GCC compiler is unavailable, naming the tool.

Logs are outside the checkout in the supplied system-temp worker-report directory:
`it11-compile.log`, `it11-npm-test.log`, `it11-root-pytest.log` (including skip
reasons) and `it11-at11.log` (the explicit named acceptance case).

Reproduce with
`ICODA_TEST_PYTHON` pointing to a prepared environment and the required user-local
Node executable directory prepended to PATH; no machine-specific runtime path is
checked into the implementation. Repository-root pytest additionally uses the
sibling application's prepared dependencies through `AILOOP_TEST_SITE_PACKAGES`,
only for that combined test invocation, as documented for G08.

```bash
npm --prefix icoda/vscode run compile
ICODA_TEST_PYTHON="$ICODA_TEST_PYTHON" npm --prefix icoda/vscode test
PYTHONPATH="$AILOOP_TEST_SITE_PACKAGES" "$ICODA_TEST_PYTHON" -m pytest -q -rs
# Explicit automated AT11, from icoda/:
"$ICODA_TEST_PYTHON" -m pytest -v tests/test_service.py::test_at11_real_service_records_loads_and_steps_without_touching_ordinary_tree
```

**AT10 was not run on this Linux host.** The Windows test is mocked discovery
and argv/environment evidence only. No Windows/macOS qualification, new native
Extension Development Host recording journey, VSIX installation, or complete
G09/M2 UI acceptance is claimed. The full provider/desktop-GUI verification gate
was not rerun for this slice; its previously documented failures are historical,
not new passing evidence.

## G10 clustered File View (iteration 12, Linux)

Started at `fde592e3636dd19c9e84c51ffb43337d395fc717` with the preceding migration's
working-tree changes already present. Those edits were preserved; no commit or
merge was made. This slice changes the File View service/extension/tests, this
document, and a behavior-preserving extraction of the desktop readability predicate.
The Call View gains only a read-only selection accessor for the new reveal command;
its rendering, recorded stepping, toolbar and G09 operations are unchanged.

**ICODA: Open File View** (`icoda.openFileView`) opens one panel per project session.
**ICODA: Reveal in File View** (`icoda.revealInFileView`) uses the active Call View
selection, otherwise the active native editor (or the sole visible native editor
while a webview has focus). Both commands require an open project and Workspace
Trust. Open File View is also in the Project title menu; Reveal is in the native
editor context menu. With multiple visible editors and none active, select one
explicitly. The File View's **Reveal active file** button invokes the same action.

Clusters are gray boxes with labels and file counts. Click or Enter/Space enters
a group; **← Overview** returns to the parent with its earlier zoom/pan intact.
The breadcrumb names the current group. Each group retains its own camera until
analysis/target identity changes or the panel closes. Selecting a file highlights
it and uses the existing `revealSource` path to open native source beside the
graph with focus preserved. Moved paths, ambiguity choices, root boundaries and
unsaved-buffer handling therefore remain the G06 behavior. Reveal maps the source
to its cluster and highlights its file; it never changes the selected target.

Zoom buttons, Fit, drag/scroll pan, Ctrl/Cmd+wheel zoom, scoped arrow/+/−/F keys,
Overview and Reveal occupy one horizontally scrolling control row. Fit uses the
backend's visible bounds, including labels and negative coordinates. Resizing
preserves the camera; use Fit after splitting/resizing the editor if desired.
The SVG renders only returned nodes and edges; text uses DOM `textContent`.
Scripts use a random nonce CSP and local resources, with the same theme variables
and high-contrast outlines as Call View. Closing/restarting/switching sessions
invalidates requests and disposes panel listeners; model/target changes reload
the current scope. Late responses and old webview actions are rejected.

### Shared implementation

`clusters.cluster_files` supplies the desktop assignments and persisted names/pins,
including `diagram_partition`'s thematic refinement and 40-file bound. `grouping.py`
was inspected: it groups implementation steps, not diagram files, and is deliberately
not called to invent a second grouping scheme. `views.layout_file_view`,
`file_view_overview`, `file_view_group` and `organise_file_view` supply file ordering,
aggregation and geometry; the latter uses shared `force_layout.arrange`.
`views.file_cluster_path` reads ancestry from `expansion.derive` and the existing
`graph_filter.project_graph` hierarchy. No GUI module is imported by the service.

The small extracted `views.file_view_needs_overview` predicate is used by the
desktop and headless adapter: switch to overview if fitting shrinks below 1.0 or
label boxes overlap. The desktop still uses its measured Tk bounds and unchanged
fit loop. Headless `file_view_level` uses the shared layout's existing 8-unit
character/18-unit line estimate and the same 24/60-unit fit margins. This is the
same readability threshold, with font measurement adapted to a headless process;
pixel-identical Tk/web fonts are not claimed. Organise is never required first.

The core's current diagram hierarchy has one level of bounded clusters and their
files; oversized pinned parents are represented by bounded children directly in
the overview. `parentId` describes the saved parent assignment, not an extra
navigable node. Singleton files stay inline. Multiple external libraries share
`external:overview`, which opens their existing external nodes. No synthetic
folder tree, client clustering, or client force simulation is introduced.

### Additive protocol v1 contract

`initialize.capabilities.views` now includes `file`, and `methods` includes
`view.revealFile`. Existing methods/fields retain their meanings. Both operations
require the same top-level `sessionId`, `modelRevision`, and selected `targetId`
as Call View and reject `invalid_session`, `stale_revision`, or `stale_target`
before work. A cached or successfully analysed model is required; retained stale
models remain viewable with their stale reason. All operations below are read-only.

| Operation | Params | Result additions |
|---|---|---|
| `view.get` File kind | `{"view":"file"}`; optional `clusterId` (a returned group ID, null/omitted for initial level), `width`, `height` (integers 1–100000, default 1000×700 for initial readability selection) | Session/source-root context; `view:"file"`, `clusterId`, `overview`, `clusterPath` as `{id,label}[]`, `nodes`, `edges`, visible `bounds:{x,y}`, `width`, `height`, `stale`, `staleReason`. The webview uses the default initial level dimensions and fits it to its actual panel. |
| `view.revealFile` | `sourceRootId` and exactly one of `file` or entity `usr` | Session/source-root context; canonical analysed `file`, stable file `entityId`, `clusterPath` as group-ID array and final `clusterId` or null. Feed that `clusterId` to `view.get`, then highlight `entityId`. |

Every node includes `id`, `label`, `kind` (`cluster`, `file`, `external`), shared
`x`, `y`, `cluster`, estimated `width`, `height`, and `expandable`. Cluster nodes
add `fileCount`, `pinned`, `renamed`, and nullable raw `parentId`; inherited pinned
parent names count as renamed. File nodes add `entityId` (the core's stable file
path ID, not a callable USR), workspace-relative `file`, `sourceRootId`, and
`line:1`; legacy outside-root locations have null `file` and cannot open source.
Hidden membership lists and hidden entity-level edges are not serialized.

Edges contain visible `source`, `target`, total `count`, per-kind `counts` and the
shared short `label` badge. Counts aggregate the scoped model's relations exactly
as on desktop. Intra-cluster edges are omitted in overview; group views contain
only relationships with both endpoints inside that group. Self summaries are
omitted. Source/entity lookup for reveal respects the selected target and uses
`find_source` for an unambiguous relocated native-editor path. Duplicate/missing
source remains handled by `source.resolve` when opening a file.

Unknown/non-expandable groups return new `unknown_cluster`. Invalid dimensions,
wrong types, extra fields and incompatible Call View params return `invalid_params`.
Reveal returns existing `invalid_source_root`, `source_missing`, or
`model_unavailable` for the corresponding condition; a missing analysed file
suggests reanalysis/Whole Project locally, without provider recovery.

### File webview messages

All messages pass `parseFileViewMessage` before dispatch. It reuses the established
camera/size/UTF-8 validation and requires exact fields. Except for `ready`, every
message carries the panel-local nonnegative integer `version`.

| `type` | Additional fields / behavior |
|---|---|
| `ready` | None; request the current render state. |
| `enter` | Bounded nonempty `id`; must identify an expandable node in the current visible graph. |
| `select` | Bounded nonempty `id`; must identify a visible file. Source references come from the backend node. |
| `back` | None; return to overview. |
| `reveal` | None; request the trusted extension's active-source command. No webview-supplied paths. |
| `viewport` | `viewport:{x,y,scale}`; finite x/y within ±1e7, scale 0.1–4. |
| `fit` | Positive finite `width`, `height`, at most 100000. Fit changes only the camera. |

Outbound `render` contains `version`, `graph` (the File View response or absent
while loading), `selected` file ID or null, optional `viewport`, `loading`, and
user-facing `message`. Unknown types, extra fields, oversized/NUL IDs and obsolete
versions are dropped without logging untrusted payload contents.

### Verification and limits

Checks use the prepared Python environment and user-local Node v24.21.0 on PATH,
with `ICODA_TEST_PYTHON` set for Node tests. Reproduce from the repository root:

```bash
npm --prefix icoda/vscode run compile
ICODA_TEST_PYTHON="$ICODA_TEST_PYTHON" npm --prefix icoda/vscode test
PYTHONPATH="$AILOOP_TEST_SITE_PACKAGES" "$ICODA_TEST_PYTHON" -m pytest -q -rs
# Focused ICODA checks:
cd icoda
"$ICODA_TEST_PYTHON" -m pytest -q tests/test_service.py tests/test_app.py tests/test_clusters.py tests/test_views.py
```

Use a normalized absolute path to the virtual-environment executable (preserving
its final Python symlink). An initial combined-suite invocation containing `../..`
failed only the sibling shell test's executable-string comparison; the normalized
invocation passed. No unrelated production code/test was changed for that issue.
The Python fixture has 81 files, five multi-file groups, mixed counted cross-group
relations, saved pins/names and external libraries. Tests cover initial reduction,
all groups, reveal, source relocation, inherited pin splitting, empty/stale states,
model immutability, selected executable/library scopes and obsolete identities.
The Tk-stub comparison agrees with actual desktop grouping/overview coordinates
and internal group edges; it is separate from native VS Code evidence.

| Check | Actual final result |
|---|---|
| Repository-root `python -m pytest -q -rs`, both prepared dependency sets | **1558 passed, 11 skipped in 68.32s (0:01:08)**; zero failures. Includes desktop regressions and all File View cases. |
| `npm --prefix icoda/vscode run compile` | **Exit 0**, `tsc -p .`, **0 compiler errors**. |
| `npm --prefix icoda/vscode test`, prepared `ICODA_TEST_PYTHON` | **98 tests, 98 pass, 0 fail, 0 skipped**, 5896.631295 ms. Manifest/registration, CSP/messages, camera/lifecycle and real overview→expand→select→resolve→reveal round trip pass; relocated sources retain ambiguity handling. |
| Focused service/desktop app/cluster/view tests | **181 passed in 12.89s**. |
| Ruff on affected Python files; focused mypy on service | **All checks passed!**; **Success: no issues found in 1 source file**. |
| New production function sizes; whitespace/scope review | Python at most **28 lines**; new TypeScript/JS at most **23 lines**, under the 30/50 rule. `git diff --check` passes; pre-existing unrelated working-tree files are unchanged. |
| Complete `verify.bash --artifacts-root …` | **Exit 1**: the same documented **32 mypy errors in five files** and three desktop GUI acceptance failures remain. Diff/Ruff/byte compilation/provider qualification/real-provider/sample build/pytest/fresh analysis stages pass. Gate pytest: **998 passed, 10 skipped in 76.56s (0:01:16)**; **87.37%** coverage (85% required). This is not a clean full-gate claim. |

The eleven combined-suite skips are the existing sibling Redis case, one compiler/
libclang pairing case, three checks requiring unversioned `clang++`, and six native
Windows cases. The gate's GUI failures are the documented File View source-box,
recovery provider-call, and editor file-box assertions. Logs and screenshots are
in `it12-verification/20260927-225546-243072/`; unchanged failure categories are
reported separately from the passing task acceptance suite.

**ViennaVulkanEngine was available and was actually exercised (AT02).** A read-only
Whole Project service check loaded its existing Linux analysis cache: **101 files,
2301 entities, 9 file clusters, 13 visible nodes and 56 aggregated edges**. Opening
took **279 ms**, overview **24 ms**, group entry **17–42 ms**, reveal **35 ms** in
that single warm-host run. Every expandable group was entered; largest file group
had **17 files**. Reveal/source resolution reached the existing generated
`build/debug-linux/_deps/viennavulkanpostprocessinglibrary-src/src/VVPPL.cpp`.
Cache/layout/UI bytes were unchanged. These are cached-model timings, not fresh
C++ analysis measurements or a general performance budget.

An actual isolated-profile Linux Extension Development Host opened the same VVE
checkout with its persisted **game / Debug** selection: **5 file clusters and
8 visible nodes**. Keyboard Enter entered the 16-file generated-source group;
file selection opened native `VVPPL.cpp:1`; Back restored the exact panned overview
camera; Reveal navigated back and highlighted it. A separate actual Call View
selection of `main` revealed/highlighted `examples/game/game.cpp` in File View
(`it12-call-reveal.json`). Light/dark screenshots and the
34-pixel control row were checked, including a 651-pixel split panel and explicit
Fit after resizing. Artifacts are retained only in the supplied system-temp report
directory: `it12-vve.json`, `it12-ui-evidence.json`, `it12-vve-*.png`, and command
logs. The host used the previously qualified `--no-sandbox` launch; no system
sandbox settings or VVE source/state were changed. This does not qualify Windows,
macOS, a fresh analysis, or installed VSIX behavior.

**Deferred this iteration:** pinning, renaming and saved-layout editing **from the
webview**. Existing persisted pin/name choices are honored and exposed read-only.
Class/Mind Map/evidence views remain G11. Cross-session camera persistence,
additional hierarchy modes and broader accessibility/platform qualification are
not claimed by this slice.

## G11a — Class View (iteration 13)

**Delivered:** `ICODA: Open Class View` (`icoda.openClassView`) opens a dedicated
`icoda.classView` webview for the selected target. The command is contributed to
the Command Palette and Project view title, requires an open trusted project, and
registers without starting Python during activation. The panel follows project,
revision and target changes and disposes on session closure/backend restart.
Class View is done for this slice; G11 remains **partial** because Mind Map,
Issues and Coverage are pending.

### Shared projection and desktop compatibility

`class_view.build_class_graph` supplies class/struct identities, direct fields and
callable members, signatures/statuses, and counted inheritance/composition/usage
edges. `clusters.cluster_files` applies saved file pins/names before
`views.entity_view_overview` derives the same bounded class groups as desktop.
`grouping.py` was inspected: it groups implementation steps, not diagrams.

`views.class_view_level` uses the desktop's existing threshold (more than 12
classes), inline singleton panels, groups of at most 40 classes, and
`layout_class_view` / `organise_class_view` geometry. Two minimal calculations
were extracted from the desktop canvas: `arrange_class_overview` sizes/positions
singleton panels beside gray groups; `class_overview_edges` aggregates typed
relationships between visible groups. The desktop calls these same helpers and
retains its filtering, navigation, member rendering and interaction behavior.
No Tk/GUI imports enter the service, and neither TypeScript nor `service.py`
derives relationships or performs graph layout.

### Additive protocol v1 contract

`initialize.capabilities.views` adds `class`. No method was removed or renamed;
Call/File/trace/build contracts are unchanged. The existing parameter is named
`view` (the view kind), so use `view.get` with `{"view":"class"}`. Optional
`clusterId` is a returned expandable group ID; null/omitted requests the initial
level. No other Class View params are accepted. Requests require the existing
`sessionId`, `modelRevision` and selected `targetId`, checked before projection.

| Response field | Meaning |
|---|---|
| Context | Existing `sessionId`, `modelRevision`, `targetId`, `sourceRootId`; `view:"class"`. |
| Navigation | `clusterId`, `overview`, and `clusterPath:[{id,label}]`; empty path at the initial level. |
| Geometry | Core `width`, `height`, `bounds:{x:0,y:0}`, plus `headerHeight` and `memberHeight` for drawing the core-sized member panels. |
| State | `stale` and `staleReason`; retained stale models remain viewable. |
| Class nodes | `id`, `usr`, `entityId` (all the entity USR), `label` (qualified name), `kind:"class"\|"struct"`, `x`, `y`, `width`, `height`, `expandable:false`, workspace-relative `file`, `line`, `sourceRootId`, `members`. |
| Members | `usr`, `entityId`, `name`, core `kind`, `declaration`, `status`, `visibility`, workspace-relative `file`, `line`, `sourceRootId`. Data members precede member functions, in the shared core order. |
| Group nodes | `id`, `label`, `count` (classes/structs), `kind:"cluster"`, `x`, `y`, `width`, `height`, `expandable:true`. No representative class, hidden member list or hidden entity edges are serialized. |
| Edges | Visible `source`, `target`, `kind:"inheritance"\|"composition"\|"usage"` and `count`. Overview combines counts by group pair/type, omitting internal relationships; drill-in includes the group's internal edges, including self relations. |

The current shared model has no access-control field, so member `visibility` is
null (unknown); the frontend does not infer public/private. Python AST analysis
currently provides classes, methods, inheritance and callable type usage, but
annotated class attributes do not become field entities. The extension preserves
these core limitations instead of inventing members or composition. Legacy
outside-root source locations have null `file` and cannot be opened from the panel.

Unknown/non-expandable groups return existing `unknown_cluster`. Bad fields/types
return `invalid_params`; absent models return `model_unavailable`. Existing
`invalid_session`, `stale_revision` and `stale_target` apply unchanged.
Class/member selection uses the trusted backend USR/root with the existing
`revealSource` → `source.resolve` path. Relocated files, ambiguous matches and
missing source retain the established local source handling and unsaved-editor
behavior; no provider is needed.

### Class webview messages and presentation

`parseClassViewMessage` reuses the bounded exact-shape File/Call validators and
rejects File View's `reveal` action. Every new message is checked at the extension
boundary before dispatch. The allowed messages are:

| `type` | Fields and behavior |
|---|---|
| `ready` | No other fields; render current panel state. |
| `enter` | `version`, `id`; ID must be an expandable group in the visible graph. |
| `select` | `version`, `id`; ID must be a visible class or one of its members. Source references come from the backend, never webview paths. |
| `back` | `version`; return to overview, restoring its camera. |
| `viewport` | `version`, `viewport:{x,y,scale}` with the existing finite ±1e7 coordinates and 0.1–4 scale limits. |
| `fit` | `version`, positive finite `width`, `height`, at most 100000; fit the existing geometry. |

`version` is a nonnegative safe integer matching the current panel. IDs use the
existing nonempty/4096-character/UTF-8/NUL restrictions. Unknown/extra fields,
obsolete versions, hidden IDs and late responses are discarded. Outbound
`render` carries `version`, `graph` (absent while loading), `selected` USR or null,
optional `viewport`, `loading` and user-facing `message`.

The nonce CSP permits local styles and nonce scripts only; model strings are DOM
`textContent`. One scrolling row contains Overview/breadcrumb and zoom/Fit.
Gray cluster panels drill into member panels; full member lists appear in class
tooltips. Inheritance uses a hollow triangle, composition a filled diamond, and
usage a dashed arrow, with type/count labels and distinct theme colors. Self
relations remain visible. Tab/Enter/Space select groups/classes/members; arrows
pan, +/- zoom and F fits within the graph. Cameras survive drilling and Back.
No command steals normal editor shortcuts.

### Verification and scope

Started from `fde592e3636dd19c9e84c51ffb43337d395fc717` with the earlier migration's
tracked modifications and untracked service/tests/extension already present.
Root `AGENTS.md` and this migration document were refreshed; no ICODA-local
`AGENTS.md` exists. Only Class View implementation, tests and this document were
changed in this iteration. No commit or merge was made.

Before implementation, reran the exact carried-over command with user-local
Node v24.21.0 prepended to PATH and `ICODA_TEST_PYTHON` set to the prepared venv:

```bash
cd icoda/vscode && npm run compile && npm test
```

Result: `tsc -p .` exited **0**, **0 errors**; **98 tests, 98 pass, 0 fail,
0 skipped** (5888.759703 ms). The It12 AT02 entry was confirmed present and
explicit: **ViennaVulkanEngine was available and actually exercised** in the
cached-model service and Linux Extension Development Host checks described above.
That AT02 evidence was not replaced with a claim of a new VVE run in It13.

Reproduce final checks with `ICODA_TEST_PYTHON` pointing to the prepared ICODA
Python executable, user-local Node on PATH, and (for the combined repository
suite) `AILOOP_TEST_SITE_PACKAGES` pointing to the sibling's prepared dependencies:

```bash
cd icoda/vscode && npm run compile && npm test
# From the repository root:
PATH="$(dirname "$ICODA_TEST_PYTHON"):$PATH" \
  PYTHONPATH="$AILOOP_TEST_SITE_PACKAGES" python -m pytest -q
ICODA_VERIFY_PYTHON="$ICODA_TEST_PYTHON" ./icoda/verify.bash --artifacts-root /tmp/icoda-verification
```

| Check | Actual result |
|---|---|
| Combined repository `python -m pytest -q` | **1575 passed, 11 skipped in 76.65s (0:01:16)**; zero failures. Includes desktop Class/File/Call and trace/build regressions. |
| Focused new Class View Python cases | **17 passed, 77 deselected in 3.27s**: actual C++/Python parsing, member/edge agreement with core and desktop, counted composition, singleton/bounded grouping, all-group drill-in, target scopes, stale identities, invalid params, empty/stale states and unchanged project bytes. |
| Extension compile | `tsc -p .`, **exit 0, 0 errors**. |
| Node suite | **105 tests, 105 pass, 0 fail, 0 skipped** (6120.096234 ms). Includes manifest/registration, CSP/message validation, camera/lifecycle and real-service Class View→class/member selection→source resolution, relocation, ambiguity and deletion. |
| Ruff / whitespace / function size | Ruff and `git diff --check` pass. New production Python functions at most 24 lines; new TS/JS functions stay below 30 lines. |
| Final service/Class View/grouped desktop regression run | **125 passed in 15.41s** (`tests/test_service.py tests/test_class_view.py tests/test_grouped_views.py`), after the extraction typing correction. |
| Service mypy | **Success: no issues found in 1 source file** (`--follow-imports=silent`). |
| Complete verification gate | **Exit 1**; diff/Ruff/compileall/provider qualification/real-provider/sample build/pytest/fresh analysis pass. Gate pytest: **1015 passed, 10 skipped in 76.95s (0:01:16)**, **87.49%** branch coverage. The three previously documented desktop GUI assertions still fail. |
| Full mypy rerun after extraction typing correction | **25 errors in four pre-existing areas**: `force_layout.py`, `source_edit.py`, existing `views.py` File/entity overview code, and `icoda.py`. No errors in the new Class View helpers/service or desktop Class View. The full gate initially reported 26, including one extracted variable's int/float inference subsequently fixed. Extraction removed the former desktop Class View errors; unrelated diagnostics were left unchanged. |

The eleven combined-suite skips retain the It12 prerequisite/platform categories.
The broad gate is not claimed green. Evidence is in the supplied system-temp job
report directory, under `it13-verification/20260927-231610-578314/`, with the
post-correction `it13-mypy.log`, `it13-root-pytest.log` and extension logs beside it.

An actual isolated-profile Linux Extension Development Host rendered a freshly
libclang-analysed C++ fixture (two source files, 16 classes/structs, 22 entities).
Its two groups drilled to the three-class Types panel with six members and four
counted typed edges, including self composition. Class selection opened
`types.cpp:3`; keyboard Enter on `use` opened `types.cpp:8`. Back restored the
panned overview camera. Light/dark screenshots were visually checked; the single
control row stayed 34 pixels high in a 651-pixel split panel. Composition was
changed to an opaque theme color after inspecting the initial screenshots.
Retained artifacts: `it13-ui-fixture/`, `it13-ui-evidence.json`,
`it13-class-overview-dark.png`, `it13-class-members-dark.png`,
`it13-class-members-light.png`, and the host/check scripts and logs. The host used
the previously documented `--no-sandbox` mode; no system sandbox setting changed.
This qualifies that Linux fixture journey, not Windows scaling, high-contrast
visual acceptance, macOS, installed VSIX, or full G11 parity.

## G11b — Mind Map (iteration 14)

`ICODA: Open Mind Map` (`icoda.openMindMap`) is available in the Command Palette
and ICODA Project title menu after opening a trusted project. It uses the
selected Whole Project, executable or library scope. `MindMapPanel` has the same
session/trust/disposal boundary as File/Class View and participates in controller
refresh, project switching, backend restart/exit and extension shutdown.

### Shared projection and persistence

The service calls `clusters.cluster_files` with the saved layout,
`mind_map.build_mind_map` with `StepLog.records()`, and `views.layout_mind_map`
with the saved `MindMapViewState`. These are the desktop MindMapCanvas inputs;
no hierarchy, aggregation, introducing-step decisions or layout were copied into
TypeScript or the service. `MIND_MAP_NODE_WIDTH` and the other layout constants
remain authoritative. No Tk helper extraction or desktop changes were needed.
The latest approved/manual, non-approach title for an introducing step number
matches `App.select_step`'s existing record selection.

`mindmap.setExpanded` replaces only `mind_map` in `store.load_state()` and calls
`ProjectStore.save_state`, matching desktop `_save_state`. Other workflow fields,
hidden descendant choices and choices belonging to other target scopes survive.
Expansion is navigation state: it does not advance `modelRevision`, change the
whole model, affect a trace, or rewrite specification/history/layout files.
Both reads and writes first reject stale session/revision/target identities.
The service's existing worker serializes operations; cross-process locking is
still the G14 limitation documented above.

### Additive protocol v1 contract

The existing selector field is `view`, so the new kind is requested with
`view.get`, `params:{"view":"mindmap"}`. The new method is
`mindmap.setExpanded`, `params:{"nodeId":"cluster:src","expanded":true}`.
Both carry the usual **top-level** `sessionId`, `modelRevision`, and `targetId`;
identity fields are not duplicated inside params. Initialization now advertises
`mindmap` in `capabilities.views` and `mindmap.setExpanded` in `METHODS` and
`capabilities.methods`. No existing response fields or methods were removed.

Both operations return the same payload:

| Fields | Meaning |
|---|---|
| `sessionId`, `modelRevision`, `targetId`, `sourceRootId`, `view:"mindmap"` | Current authoritative context. |
| `nodes`, `edges`, `totalNodes` | Visible core pre-order layout, its `{source,target}` links, and total forest node count including hidden descendants. |
| `bounds:{x:0,y:0}`, `width`, `height` | Shared layout extent; an empty forest retains the core's 1×1 size. |
| `stale`, `staleReason` | Selected model freshness, including retained stale models. |
| `empty`, `emptyReason` | Explicit empty-forest flag and explanation; nonempty forests use an empty reason string. |
| `requirements`, `hasSteps`, `messages` | Specification goal/requirement records described below, whether step records exist, and explanatory messages for missing specification entries or history. |

Each visible node contains:

- Stable `id`, `label`, `qualifiedName`, `kind` (`cluster`, `file`, `class`,
  `function`), `parent` (null for roots), immediate `children` IDs, and `depth`.
- Core center coordinates `x`, `y`, `width`, `height`; `expandable` and
  `expanded` booleans. Leaf nodes have both flags false.
- Core implementation `status`, original `requirementIds`, matching
  `requirements`, and sorted `useCaseIds` from the specification's explicit
  requirement-to-use-case links. No text matching is performed.
- `step` as `{number,title}` when the core supplies an introducing iteration,
  otherwise null. Missing titles remain empty strings.
- `usr` (null for containers), bounded project-relative `file` (null without a
  safe source path), one-based `line` (1 for files/containers), `sourceRootId`.

A requirement record is `{id,title,uncovered,useCaseIds}`. `uncovered` comes
from `requirement_coverage.project` over the same scoped model. Unknown source
tags retain their ID with empty title/use-case links and `uncovered:null`.
This is specification tag traceability, **not measured runtime coverage**.
The tooltip says “tagged in code”, “no tagged entities”, or “not in specification”.
Implementation status and introducing-step provenance remain separate facts.

An analysed empty project without specification/history returns `empty:true`,
empty nodes/edges/requirements, `hasSteps:false` and explicit messages. Missing specification/history does not
hide an otherwise useful code hierarchy: available nodes remain visible with
empty metadata and explanations. An unanalysed project returns the existing
`model_unavailable`. Invalid fields/types and unknown or leaf expansion IDs
return `invalid_params` without writes. `invalid_session`, `stale_revision` and
`stale_target` remain unchanged. There are no new diagnostic channels on stdout.

The Python analyzer currently retains docstrings but does not populate
`Entity.satisfies`; this pre-existing limitation was preserved. The tagged
acceptance fixture uses real libclang C++ analysis. Python hierarchies, source
navigation and recorded step provenance use the same shared model path.

### Webview messages and presentation

`parseMindMapMessage` validates every inbound message before dispatch. IDs must
be nonempty, at most 4096 characters, valid UTF-8 and NUL-free. Camera messages
reuse the established bounded Call View schema. Unknown or extra fields,
nonboolean expansion values, obsolete versions, hidden IDs and late responses
are rejected. Sources always come from the trusted backend node.

| `type` | Exact additional fields and action |
|---|---|
| `ready` | None; render current state. |
| `select` | `version`, `nodeId`; select a visible node and, when source-mapped, use `revealSource` → `source.resolve` and the native editor. |
| `setExpanded` | `version`, `nodeId`, `expanded` (boolean); call `mindmap.setExpanded` for a visible expandable node. |
| `viewport` | `version`, `viewport:{x,y,scale}`; finite ±1e7 coordinates, scale 0.1–4. |
| `fit` | `version`, `width`, `height`; finite dimensions 1–100000. |

`version` is a nonnegative safe integer matching the panel's current state.
Outbound `render` contains `version`, `graph` (absent while loading), `selected`
(node ID or null), optional `viewport`, `loading`, and user-facing `message`.
Expansion preserves the camera and clears a selection hidden by collapse. A
failed expansion keeps the previous hierarchy available for retry. Project or
target changes invalidate pending results and reset the panel's camera.

The HTML uses a nonce CSP, local resources and DOM `textContent`. One scrolling
control row contains the node count and zoom/Fit controls. Gray clusters and
opaque theme-colored boxes keep edges out of labels. Node details include status,
requirements, use cases, introducing step number/title and source line. Tab and
Enter/Space operate nodes and separate expansion buttons; arrows pan, +/- zoom,
and F fits while the graph is focused. Wheel pans; Ctrl/Command-wheel zooms.
No global editor/debugger bindings were added.

### Baseline re-confirmed before G11b

HEAD remained `fde592e3636dd19c9e84c51ffb43337d395fc717`. Earlier tracked changes
and the untracked migration/service/tests/extension were preserved. Root
`AGENTS.md`, the migration record and the listed guidance/core files were
refreshed; no ICODA-local `AGENTS.md` exists. No repository commit, branch merge
or stash was used.

From `icoda/`, with the prepared Python on PATH and a working display, these
standalone commands all exited 1 **before Mind Map implementation**:

```bash
ICODA_TK_STUB=0 python tests/gui_acceptance.py --project tests/sample_project --output "$REPORT/it14-gui"
ICODA_TK_STUB=0 python tests/recovery_gui_acceptance.py --output "$REPORT/it14-gui-recovery"
ICODA_TK_STUB=0 python tests/editor_gui_acceptance.py --output "$REPORT/it14-gui-editor"
```

`REPORT` denotes this job's system-temp artifact directory. The failing checks are:

| Check | Reproduced failure |
|---|---|
| General desktop GUI | `tests/gui_acceptance.py:248`: `RuntimeError: File View is missing source boxes`. |
| Recovery desktop GUI | `tests/recovery_gui_acceptance.py:136`: `assert len(calls) == 5 and "What is the cause?" in calls[4]`. |
| Editor desktop GUI | `tests/editor_gui_acceptance.py:139`, `verify_file_boxes`: `assert set(files) <= boxes.keys()`. |

Ran `mypy icoda.py icoda_core icoda_gui` with the same prepared environment in
this checkout and a detached `git worktree add --detach "$temporary/checkout"
HEAD`, with `temporary` created by `mktemp -d` under the system temp directory.
Separate external mypy caches avoided sharing cached diagnostics. Removed the
base checkout with `git worktree remove` immediately after comparison.

- **HEAD: 32 errors in 5 files (68 source files checked).**
- **Before and after G11b: 25 errors in 4 files (69 source files checked).**
- Comparing diagnostic multisets after normalizing line numbers found **zero
  added diagnostics**, including in It13/It14 files. The seven removed errors
  were in desktop `icoda_gui/class_view.py`. There are no diagnostics in
  `service.py` or current desktop `class_view.py`. The 19 `views.py` diagnostics
  map to unchanged File/entity overview code already present at HEAD; the other
  six are four in `force_layout.py`, one in `source_edit.py`, one in `icoda.py`.

### Verification actually performed

Use the prepared `ICODA_TEST_PYTHON`; for Node, prepend the requested user-local
Node v24.21.0 bin directory to PATH. For the combined repository suite only,
`AILOOP_TEST_SITE_PACKAGES` identifies the sibling application's prepared test
dependencies. Do not run the combined suite while the verifier rebuilds the
shared C++ sample.

```bash
# From icoda/vscode, with ICODA_TEST_PYTHON exported:
npm run compile && npm test
# From the repository root, after the verifier finishes:
PATH="$(dirname "$ICODA_TEST_PYTHON"):$PATH" \
  PYTHONPATH="$AILOOP_TEST_SITE_PACKAGES" python -m pytest -q
ICODA_VERIFY_PYTHON="$ICODA_TEST_PYTHON" ./icoda/verify.bash --artifacts-root "$REPORT/it14-verification"
# From icoda/:
python -m pytest -q tests/test_service.py tests/test_mind_map.py tests/test_mind_map_gui.py
mypy icoda.py icoda_core icoda_gui
```

| Check | Actual result |
|---|---|
| Combined repository pytest, serialized rerun | **1590 passed, 11 skipped in 76.63s (0:01:16)**; zero failures. |
| Service/shared/desktop Mind Map regressions | **118 passed in 17.90s**; includes 15 new service cases for real tagged C++, geometry/hierarchy/status/step agreement, expansion reload, invalid inputs without writes, empty metadata/models, and target/session/revision scope. |
| Extension compile | `tsc -p .`, **exit 0, 0 errors**. |
| Node suite | **114 tests, 114 pass, 0 fail, 0 skipped** (6515.259953 ms). Manifest/command registration, strict messages/CSP, empty/error states, cameras/lifecycle, and a real C++ service → expansion → source-resolution/persistence journey. |
| Ruff, diff and function size | Ruff and `git diff --check` pass; new production Python functions at most 24 lines, new TS/JS functions at most 22 lines. |
| Full verifier | Exit **1** solely for the same mypy and three standalone desktop GUI checks. Diff/Ruff/compileall/provider qualification/real-provider/sample build/pytest/fresh analysis pass. Gate pytest: **1030 passed, 10 skipped in 77.73s (0:01:17)**; **87.21%** branch coverage. |
| Mypy compared with HEAD and It13 | **32 → 25 errors**, unchanged from the It13 starting tree; zero new diagnostics. |

An initial combined-suite run overlapped the verifier's sample rebuild and
reported **2 failed, 1588 passed, 11 skipped in 81.97s (0:01:21)**:
`test_cache_makes_the_second_parse_identical` observed 9 cached units versus 12
commands, and `test_missing_module_flags_are_recovered_from_pcm_files` could not
find the `config` module. The standalone verifier's subsequent suite passed,
and the serialized combined rerun above passed without source changes. Retain
`it14-root-pytest-overlap.log` as evidence of the test-ordering limitation.

An isolated-profile Linux Extension Development Host opened the real C++ fixture
`it14-ui-fixture/library.cpp`: four cluster/file/class/function nodes, R-1 → UC-1,
and approved step 2 “Introduce Widget”. Keyboard expansion preserved the panned
camera; keyboard selection opened `Widget::run` at **library.cpp:5**. Collapse
persisted while retaining hidden child expansion; panel reopening restored it.
The control row measured **34 pixels high** at **1046** and **503 pixels wide**.
Light/dark captures were inspected; the inspected translucent fills were replaced
with opaque theme fills, then rechecked. At narrow widths Fit necessarily shrinks
a deep hierarchy; zoom/pan were exercised to read the selected node and its source.
This is a Linux fixture check, not Windows scaling, screen-reader/high-contrast,
macOS or installed-VSIX qualification. The host used the previously documented
`--no-sandbox` mode; no system sandbox setting changed.

Evidence is retained in the supplied system-temp job report directory:
`it14-mypy-base.log`, `it14-mypy-before.log`, `it14-mypy.log`, the three
`it14-gui*.log` files, `it14-focused.log`, `it14-node.log`,
`it14-root-pytest.log`, `it14-verification/20260927-234031-529680/`,
`it14-ui-evidence.json`, `it14-mindmap-expanded-dark.png`,
`it14-mindmap-source-dark.png`, `it14-mindmap-source-light.png`, and host/check
scripts. G11 still needs Issues and Coverage; G12/G13 history-review actions
remain their own milestone. Mind Map currently presents step provenance in its
node details, without opening an unimplemented history-review UI.

## G11c — Issues and Coverage (iteration 15)

Implemented 2026-09-28. The ICODA container now includes **ICODA Issues**
(`icoda.issues`) and **ICODA Coverage** (`icoda.coverage`) native TreeViews.
Issues groups advisory findings by severity. Coverage keeps **Requirement
Traceability** and **Structural Test Reachability** in separate sections.
Expand a requirement to inspect its satisfying entities; expand a reached
callable to inspect the successful step numbers/titles/times and test identifiers.
Selecting a finding, satisfying entity, callable or its evidence row opens its
source through `revealSource` → `source.resolve`, including relocated-path lookup
and ambiguity handling. Finding navigation preserves the offending call-site
line rather than substituting the entity declaration. Native editor buffers are
reused; missing sources stay local source diagnostics.

Commands **ICODA: Refresh Issues** (`icoda.refreshIssues`) and **ICODA: Refresh
Coverage** (`icoda.refreshCoverage`) are in the command palette and their view
title bars. Reads refresh automatically on session, model revision or target
changes through `SessionState` tickets. Closing/restarting the backend clears
the trees; stale successes/errors and overlapping refreshes cannot publish into
a newer selection. Saved-source stale state is displayed. Activation only
registers views and commands; it does not start Python. Refresh and source actions
honor Workspace Trust. Native controls supply keyboard navigation and theme
colors, but no new screen-reader, display-scaling or platform qualification is
claimed by the Node tests.

### Additive protocol v1 contract

Both new methods are in `METHODS` and `initialize.capabilities.methods`. Requests
use empty `params: {}` plus the existing top-level `sessionId`, `modelRevision`
and `targetId` (null means Whole Project). The existing `invalid_session`,
`stale_revision`, `stale_target`, `project_not_open` and `invalid_params` checks
apply before any projection. Reads neither advance revisions nor write project
state, execute tests/tools, invoke providers or import Tk/GUI modules.
Responses include the existing context fields (`sessionId`, `modelRevision`,
`targetId`, `sourceRootId`) plus `stale` and `staleReason`.

`issues.list` adds `findings`, `emptyReason` and `message`. Each finding has:

- `id`: `issue:` plus SHA-256 of sorted-key UTF-8 JSON of the core Issue fields;
  the same finding keeps its identity across reads and reopened sessions.
- `ruleId`, `severity`, `message`, `usr` (null when absent).
- `file` (workspace-relative or null when not project-scoped), `line` (at least 1),
  and `sourceRootId` for the existing source-resolution API.

Findings and ordering come directly from `rules.check(scoped_model, records)`,
as in desktop Issues. `emptyReason` is `no_model`, `no_findings`, or null;
`message` explains the first two, and is otherwise empty.

`coverage.get` adds two objects, each with `label`, `entries`, `emptyReason` and
`message`:

| Object | Entry fields and computation | Empty reasons |
|---|---|---|
| `requirementTraceability` | `id`, `kind` (goal/requirement), `title`, `uncovered`, `entities`. Each entity has `usr`, `qualifiedName`, `file`, `line`, `sourceRootId`. Uses `specification.load` and `requirement_coverage.project(spec, scoped_model)`, including exact `@satisfies` tags and positional G-1/G-2 goal IDs. | `no_model`, `no_specification`, `no_requirements`, or null. |
| `structuralTestReachability` | `usr`, `qualifiedName`, `signature`, `file`, `line`, `sourceRootId`, `covered`, `tests`, `evidence`. Evidence retains the core `step`, `title`, `time`, `tests` fields. The section also has `uncovered`, the core list of unreached USRs. | `no_model`, `no_callables`, `no_recorded_tests`, or null. |

Structural evidence uses successful step history and analysed call edges. The
minimal shared `coverage_index.scoped_index` helper extracts the desktop's
existing whole-model computation followed by filtering to selected-model USRs;
`App.executable_coverage` delegates to it with unchanged behavior. Thus tests
outside a selected executable/library can still supply structural evidence.
Failed/undone records retain the core's exclusion rules. `no_recorded_tests`
means there are no reaching recorded identifiers in this selection; all analysed
callable rows remain visible as not reached. An empty callable model has no
index rows. Neither section measures runtime code coverage, assertions, branches
or test quality. No findings or coverage computation is ported to TypeScript.

The internal tree command `icoda.revealEvidence` accepts only an exact
`{view: "issues" | "coverage", id: string, version: positive integer}` shape.
IDs are nonempty, bounded valid UTF-8 without NULs. The extension resolves the ID
against the current rendered tree and validates its version/session before and
after awaiting the backend; arbitrary source paths and obsolete items cannot
navigate. This adds no webview message surface and changes no CSP.

### Carry-over baseline recovered and corrected

HEAD remains `fde592e3636dd19c9e84c51ffb43337d395fc717`. All earlier tracked and
untracked implementation changes were retained. Root `AGENTS.md`, this record
and the requested guidance/core files were reread; there is no ICODA-local
`AGENTS.md`. No stash, commit or merge was used. A detached HEAD checkout was
created under the system temp directory with `git worktree add --detach` and
removed with `git worktree remove` after the baseline runs.

With the same prepared environment, `mypy icoda.py icoda_core icoda_gui` reported:

- Starting current worktree: **25 errors in 4 files (69 source files checked)**.
- Detached HEAD: **32 errors in 5 files (68 source files checked)**.
- Final current worktree: **6 errors in 3 files (69 source files checked)**.

The 19 inherited `views.py` diagnostics came from reusing variable names for
incompatible types in existing File/entity overview code. Local variable renames
remove them without changing layout behavior. There are now **zero diagnostics
in service.py, views.py or icoda_gui/class_view.py, and zero in It13–It15 code**.
Diagnostic multisets normalized for line numbers show zero additions versus
both HEAD and the starting worktree. The remaining six are four original
`force_layout.py` errors, one `source_edit.py` annotation error and the original
optional-layout access in `icoda.py:331` (HEAD line 338), outside the extracted
coverage helper. No clean full-mypy claim is made.

All three previously reported standalone real-Tk GUI failures were reproduced
before implementation, and on HEAD:

| Check | Current and equivalent-fixture HEAD result |
|---|---|
| General GUI, `tests/gui_acceptance.py:248` | `RuntimeError: File View is missing source boxes` |
| Recovery GUI, `tests/recovery_gui_acceptance.py:136` | `assert len(calls) == 5 and "What is the cause?" in calls[4]` |
| Editor GUI, `tests/editor_gui_acceptance.py:139`, `verify_file_boxes` | `assert set(files) <= boxes.keys()` |

Reproduce from the relevant checkout's `icoda/`, with prepared Python on PATH,
a working display, `REPORT` set to a temp artifact directory, and `SAMPLE_PROJECT`
set to the absolute path of the same **built** `tests/sample_project` fixture:

```bash
ICODA_TK_STUB=0 python tests/gui_acceptance.py --project "$SAMPLE_PROJECT" --output "$REPORT/gui"
ICODA_TK_STUB=0 python tests/recovery_gui_acceptance.py --output "$REPORT/gui-recovery"
ICODA_TK_STUB=0 python tests/editor_gui_acceptance.py --output "$REPORT/gui-editor"
```

The fresh detached worktree's unbuilt sample initially failed the general GUI at
line 260 (`File View has no multi-file cluster for pin/rename acceptance`). Using
the same built sample as the current checkout reproduces the line-248 source-box
failure on HEAD too. This distinction is retained in `it15-base-gui.log` and
`it15-base-gui-built.log`; it is not a migration regression claim.

### Verification performed for G11c

Set `ICODA_TEST_PYTHON` to a prepared Python executable and put its bin directory
on PATH. Use the requested user-local Node.js v24.21.0 via
`PATH="$HOME/.local/share/nodejs/v24.21.0/bin:$PATH"` for npm. No machine-specific
runtime path is required by the extension.

| Check | Actual result |
|---|---|
| `python -m pytest -q` from `icoda/` | **1037 passed, 10 skipped in 60.49s (0:01:00)**; zero failures, including existing desktop, view, trace and build/record regressions. |
| Repository-root `python -m pytest -q`, serialized after the verifier | **1597 passed, 11 skipped in 77.65s (0:01:17)**; zero failures. Prepared ICODA Python on PATH and sibling test dependencies via `PYTHONPATH="$AILOOP_TEST_SITE_PACKAGES"`, as in It14. |
| Focused evidence and headless service cases (`python -m pytest -q tests/test_service.py -k "evidence or headless"`) | **8 passed, 108 deselected in 2.06s**. Core agreement, exact source locations, stable identities, read-only state, all empty reasons, stale session/revision/target rejection, target projection with external test evidence, failed/undone tests. |
| `npm run compile` from `icoda/vscode/` | `tsc -p .`, exit **0**, **0 errors**. |
| `ICODA_TEST_PYTHON=… npm test` | **124 tests, 124 pass, 0 fail, 0 skipped**. Registration, mapping/empty states, command validation, stale/overlapping responses, disposal and real-service round trip. |
| Mypy current versus HEAD | **6 versus 32 errors**, zero new diagnostics; starting current tree had 25. |
| Complete `./icoda/verify.bash --artifacts-root "$REPORT/it15-verification"` | Exit **1** only for the six inherited mypy errors and three reproduced standalone GUI checks. Diff/Ruff/byte compilation/provider qualification/real-provider/sample build/pytest/fresh analysis pass. Gate pytest: **1037 passed, 10 skipped in 81.55s (0:01:21)**; **87.02%** branch coverage (85% required). |
| Ruff, whitespace and sizes | Ruff and `git diff --check` pass. New production functions are below 30 lines; typing-only variable renames preserve existing overview function lengths. |

The real-service Node fixture uses the existing `writeMindMapFixture` C++ source
`library.cpp`, R-1 → Widget entities, and an approved step 3 naming `Widget::run`
as a successful test identifier. It opens and analyses the fixture, reads both
new methods and resolves selected tree items to the actual file/line. This
establishes recorded structural evidence, not an executed test or runtime
measurement. Service regressions also exercise actual Python analysis without
executing the project. New native-tree visual/Extension Host qualification was
not run in this iteration; earlier Class/Mind Map UI evidence is retained above.

Logs remain under the supplied system-temp job artifact directory: `it15-mypy-`
`{before,base}.log`, `it15-mypy.log`, `it15-{current,base}-*gui.log`,
`it15-base-gui-built.log`, `it15-focused.log`, `it15-pytest.log`, `it15-npm-compile.log`,
`it15-npm-test.log`, `it15-root-pytest.log`, and
`it15-verification/20260928-000406-796955/`. No worker-report file is stored in
the repository. G11 implementation is done; G12/G13 workflows and G14–G17
qualification remain separate milestones.

## G12a — Specification, phase and provider inventory (iteration 16)

The native **ICODA Specification** tree (`icoda.specification`) shows the current
phase and transition refusals, Code Profile fields, core validation findings,
and provider/model availability. It supplies explicit states for no open project,
no saved specification, an absent Code Profile, and no available providers.
Read failures stay local to their section; an unavailable provider does not block
specification, source or graph access.

### Commands and native editing

- **ICODA: Open Specification** (`icoda.openSpecification`) opens JSON in a native
  VS Code text editor. A writable `icoda-specification:` filesystem holds a draft
  tied to the session/revision; its write handler calls `spec.validate` followed
  by `spec.save`. It never writes the project file directly. Invalid JSON, core
  findings, revoked trust, and obsolete drafts fail Save and retain editor edits.
- **ICODA: Validate Specification** (`icoda.validateSpecification`) validates the
  active specification draft, or refreshes the tree and validates the saved/default
  document if another editor is active. Validation writes no project files.
- **ICODA: Advance Phase** (`icoda.advancePhase`) offers only backend-approved
  transitions. Selecting implementation explicitly approves the architecture;
  the backend rechecks the gate and initialises the shared implementation queue.
- **ICODA: Select Provider/Model** (`icoda.selectProviderModel`) offers installed,
  enabled registry models and saves identifiers to resource-scoped
  `icoda.providerSelection: {provider, model}` in workspace-folder settings.
  This follows the desktop's per-project selection scope. When empty, the tree
  inherits `.icoda/ui.json`'s provider selection, then the desktop UserConfig
  default (including the core default model when none was saved). Desktop
  preferences are read but not overwritten by the extension.

All four commands reject external arguments. Choices come from current backend
responses; the extension checks its session ticket again after native pickers.
The tree refreshes through `ProjectSession`/`SessionState`, drops old session,
revision, target and overlapping-refresh replies, and disposes with the other
views. No webview or CSP changes are involved. Open documents keep their unsaved
buffers across selection changes. Explicitly reopening creates a current draft
when the old revision is obsolete; edits can be copied across before saving.
A successful save keeps its own draft current for repeated saves.

### Additive protocol v1 contract

All six methods appear in `METHODS` and `initialize.capabilities.methods`.
Every request carries the existing top-level `sessionId`, `modelRevision` and
`targetId`; results carry those fields and `sourceRootId`. Read operations retain
identity. Successful save-only `spec.save` and `phase.transition` increment the
revision exactly once, retaining target/model/playback state. The frontend
`workflow` transition accepts that increment only for the same session and target.
The opt-in P08 save below instead publishes the ordinary analysis transition.

| Method | Params | Additional result fields |
|---|---|---|
| `spec.get` | `{}` | `document`: exact core-loaded/upgraded specification, or the desktop's language-aware default when absent; `schemaVersion`: `specification.SCHEMA_VERSION`; `codeProfile`: unmodified `document.code_profile`; `exists`: whether saved; `valid`, `findings`. No default is written. |
| `spec.validate` | `{document: JSON value}` | `valid` and `findings` from `specification.validate`, without persistence. |
| `spec.save` | `{document: JSON value, trusted: true, postSave?: boolean, unsavedDocuments?: string[]}` | The validated specification fields from `spec.get`, `exists: true`, and `state` in `ProjectState.to_dict()` form. Omitted/false `postSave` preserves the original save-only behavior. `postSave: true` adds the P08 result fields and orchestration below. |
| `phase.get` | `{}` | `phase`, `state`, `allowedTransitions: string[]`, and `transitions: [{phase, reason}]`; empty `reason` means currently permitted. |
| `phase.transition` | `{phase: string, trusted: true}` | The new `phase.get` fields plus the core step-log `record` (dataclass fields, including `previous_phase`, `decision`, `title`, number/time). |
| `providers.list` | `{}` | `providers`, desktop `selection: {provider, model}`, `emptyReason` (`no_available_providers` or null), and explanatory `message`. Always read-only. |

Findings have `{id, severity, message}`. IDs use a deterministic hash of the core
message and its duplicate occurrence; the same finding keeps its ID when unrelated
findings move. Current core validation findings are errors. No schema validation,
cross-reference logic, or phase rules are implemented in TypeScript.
`specification.validate` now also handles malformed JSON section types safely:
schema findings remain authoritative, and cross-reference checks skip malformed
records rather than crashing. Valid desktop documents retain their behavior.

#### P08 post-save orchestration (iteration 48)

`initialize.capabilities.specificationPostSave: true` advertises the additive
`spec.save` option; VS Code's ordinary Save always sends `postSave: true` and the
dirty-document URI list excluding the specification being saved. Session/revision/
target validation, Workspace Trust, active-workflow and pending-proposal guards
run before writes. Relevant unsaved documents also refuse the save. The extension
holds its existing operation-busy guard and shows native progress until refresh
finishes. `cancellableMethods` advertises `spec.save`; only the opt-in long save
reserves a cancellation scope. Project switches, backend shutdown and
`operation.cancel` stop its nested build/analysis processes using the existing
core timeouts and process cleanup. Native Save progress has no cancel button.

After validation, `session.save_project_specification` uses the desktop's
existing-edit flag (an opened project's phase is no longer specification).
The shared operation decides whether a skeleton is needed, preserves existing
files through `generator.write_skeleton`, and records the architecture transition
through `phases.transition`. A new skeleton automatically runs the desktop's
`steps.build_project` gate, then the existing service analysis operation. An
existing-project edit goes directly to that analysis operation. No build,
generation, validation or phase rules are implemented in TypeScript.

The response adds `saved: true`, `writtenFiles` (created relative paths, or null
for an existing-project edit), the project snapshot (`root`, `model`, source-root
identity), `diagnostics`, and `postSaveError` (null or `{code, message, details}`).
Post-save build/tool failures use `build_failed`; analysis failures use
`analysis_failed`. These errors accompany a successful save response so the
native document becomes clean, while its saved bytes and refreshed phase remain
available. The retained model is marked stale and cached. They never invoke
provider/Binary recovery. Cancellation after persistence uses the existing
`cancelled` error code with this complete saved-state result in `error.details`;
the frontend accepts the saved document and stale model only if its session is
still current. Preconditions and validation still fail the request
without saving. The revision advances exactly once, playback clears, and normal
analysis target discovery applies. VS Code accepts that analysis transition,
refreshes all model-dependent views, rereads targets/specification/phase, and
keeps the draft current for repeated Save. Closing and reopening the native
document rereads through `spec.get`.

P08 verification (Linux/X11, 2026-09-28): `npm run compile` passed; `npm test`
reported **245 passed, 0 failed**. VS Code **1.96.4** `test:integration` reported
workspace **32/0**, empty **1/0**, C++ **2/0**, untrusted **5/0** passed/failed;
`test:vsix` rebuilt the package and passed **4/0** installed checks. The exact
repository-root harness command `python -m pytest -q` reported **1869 passed,
8 skipped, 0 failed in 393.20s**; no skips were added or injected. `git diff
--check` and focused Ruff checks passed. Node **24.21.0**, the existing Python
venv (retaining its executable symlink path in `ICODA_TEST_PYTHON`), LLVM 18 and
the existing AI-Loop dependency location on `PYTHONPATH` were used. Logs are in
`/tmp/ai-loop-worker-reports/J20260927-170326-588902/iteration48/`:
`pytest.log`, `npm-test.log`, `integration.log`, `vsix.log`, and
`icoda-integration-JwJBcG/p08-specification-save.json`. Fixtures remain unchanged;
the sample analysis log's original bytes were restored. A supplemental mypy
check still reports five existing errors in unmodified `force_layout.py` and
`source_edit.py`; no P08 file has a reported mypy error.

`phase.get`/`phase.transition` use shared `phases.transition_options`,
`transition_refusal`, and `advance`, based on `ProjectState.transition_to`,
`phases.transition` and `implementation_queue.ensure_state`. Leaving specification
requires a saved valid specification, matching the desktop editor's gate.
Illegal lifecycle transitions fail before persistence/history changes. Architecture
approval uses the whole-project model for its queue, independent of target selection.
G12a has no pending provider proposals; the existing desktop pending-proposal gate
is unchanged and must be connected to authoritative proposal state in G12b/G13.

Errors add `invalid_specification` (validation failures include `valid: false`
and `findings` in `details`), `disallowed_transition`, and `workspace_untrusted`.
Unknown phases/malformed params use `invalid_params`; existing invalid-session,
stale-revision and stale-target errors apply before method dispatch. The extension
uses the same Workspace Trust check as G09; these two new mutation methods also
require the explicit boolean `trusted: true` at the backend boundary. Missing,
false, numeric and string trust values cannot authorise a write. This is a client
assertion, not a security boundary against another process with filesystem access.

### Provider capability semantics

Inventory entries expose `id`, `label`, `installed`, `enabled`, `verified`,
`available`, `authenticationConfigured` and `models: [{id, label, available}]`.
The registry and `agent.binary_available` provide the existing discovery policy,
including a saved desktop binary override. Available means installed and enabled
in the ICODA registry. Model rows are the shipped registry choices, **not a live
account entitlement query**. `verified` is historical registry metadata, not a
new CLI qualification result.

There was no authentication presence helper in the inspected core. The small
`agent.authentication_configured` helper checks only nonempty environment marker
presence and credential-file existence for the enabled Codex/Claude providers.
It never opens credential files, returns values/paths from them, runs help/login,
or invokes a model. `false` means not detected; keychain-only and unrecognised
setups may still authenticate. `true` is configuration presence, not verification
of working credentials. Other registry providers return false until a supported
local detection policy exists. Login continues to belong to the installed CLI.

No missing provider, model or auth marker is a failure of unrelated methods.
No activation, inventory, selection, editing or phase operation starts a provider.
The new `providers.list` operation does not run `provider_check`.

### Scope, evidence and remainder

G12 is **partially done (G12a)**. Saving edits only the specification and required
ICODA metadata. New-project skeleton generation/build prompts and automatic
post-save analysis remain G12b; Advance Phase is an explicit separate operation
in this slice. The standalone editor's existing skeleton/phase behavior is unchanged.
G12b also retains provider invocation, architecture/implementation-approach rounds,
context selection, queue/batch controls, progress/cancellation, conversations and
purpose-comment automation with idle/unsaved-file/proposal safeguards. Review,
worktree evidence, approval/Git/undo gates remain G13. This is no parity or release
completion claim.

Starting HEAD was `fde592e3636dd19c9e84c51ffb43337d395fc717`, with the preceding
migration's tracked/untracked changes already present. Their hashes were captured
before implementation and unrelated files were preserved. Root instructions and
this migration record were refreshed; no ICODA-local `AGENTS.md` exists. No commit,
merge, provider invocation, credential read, or dependency installation was performed.

Verification uses the prepared Python environment, user-local Node.js v24.21.0
via `PATH="$HOME/.local/share/nodejs/v24.21.0/bin:$PATH"`, and an explicit
`ICODA_TEST_PYTHON` retaining its virtual-environment path. Reproduce from `icoda/`:

```bash
python -m pytest -q
python -m ruff check icoda_core/agent.py icoda_core/phases.py icoda_core/service.py icoda_core/specification.py tests/test_service.py
python -m mypy icoda.py icoda_core icoda_gui
cd vscode
npm run compile
ICODA_TEST_PYTHON="$PREPARED_PYTHON" npm test
```

| Check | Actual result (Linux, 2026-09-28) |
|---|---|
| `python -m pytest -q` from `icoda/` | **1065 passed, 10 skipped in 64.17s (0:01:04)**; zero failures. |
| Repository-root `python -m pytest -q` | **1625 passed, 11 skipped in 87.70s (0:01:27)**; zero failures. Prepared ICODA Python on PATH, sibling test dependencies through `PYTHONPATH` as in G11c; final run includes all new service cases. |
| Focused service regressions (specification/phase/workflow/inventory/authentication/headless) | **29 passed, 115 deselected in 4.31s**. Core document/profile/validation agreement, malformed sections, invalid-save byte preservation, phase/history/queue gates, strict trust values, all six methods' stale session/revision/target checks, empty/stub discovery and no credential reads/CLI invocation. |
| `npm run compile` | `tsc -p .`, exit **0**, **0 errors**. |
| `ICODA_TEST_PYTHON=… npm test` | **135 tests, 135 pass, 0 fail, 0 skipped**. Native view/command registration, tree/profile/provider/empty mapping, argument boundaries, late/overlapping replies, disposal, invalid/untrusted/stale native drafts and repeated validated saves. |
| Ruff, Python byte compilation, whitespace | Passed for changed Python files; `git diff --check` passed. New production Python/TypeScript functions stay within 30 lines. |
| `python -m mypy icoda.py icoda_core icoda_gui` | **6 errors in 3 unchanged files (69 source files checked)**, the same inherited `force_layout.py`, `source_edit.py`, and `icoda.py` findings documented in G11c. No diagnostics in G12a changes. |

The Node real-service fixture contains `main.py` with a top-level exception to
prove project opening does not execute it. It opens the folder, fetches the core
Python specification/profile, validates a native draft, reads phase/providers,
refuses an invalid save, saves the valid draft and rereads phase availability.
The fresh-interpreter Python check now runs all six methods and confirms no Tk
or GUI imports before/after the service. Stub discovery also navigates actual
Python source and a parsed Call View with no installed provider. No real model
was invoked by either suite.

The complete `verify.bash` was intentionally not run: it includes real-provider
invocation, prohibited for G12a. Existing standalone GUI failures and six mypy
errors are documented in G11c; no new Extension Host screenshot/platform/VSIX
qualification is claimed for this native-tree slice. Evidence logs are in the
system-temp job artifact directory under `it16/`, outside the repository.

## G12b — Provider workflows and purpose-comment proposals (iteration 17)

The requested G12b command/service slice is delivered. It reuses the desktop
`StepRunner`, prompt builders, phase/queue rules and `documentation.complete`.
No approval, rejection, promotion, adaptation, commit or undo endpoint was added.
There are now **27 contributed commands**, including:

- **Propose Architecture** (`icoda.proposeArchitecture`).
- **Propose Implementation Approach** (`icoda.proposeImplementationApproach`).
- **Run Implementation Queue** (`icoda.runImplementationQueue`).
- **Cancel AI Workflow** (`icoda.cancelAIWorkflow`).
- **Propose Purpose Comments** (`icoda.proposePurposeComments`).

The native **ICODA AI Workflows** sibling tree shows current state, the latest
proposal summary, candidate location, proposed files and build/test outcomes.
Provider diagnostics go to **ICODA Providers** output. Each proposal command uses
cancellable native progress. The first three commands offer an optional request
and multiselect context of actual analysed files/entities. They pass those IDs to
`StepRequest.focus`; Python retains all prompt subset, neighbor, queue and batch
selection rules. Provider/model selection inherits G12a's workspace setting or
the saved desktop selection. Missing providers return the capability inventory;
source, graph, trace and specification browsing remain available.

Commands reject external arguments. `WorkflowModel` validates input shapes and
uses `SessionState` tickets to drop stale successes, errors and progress after
project/revision/target changes. It handles Cancel before the start response,
cancels owned work on disposal, and releases its native cancellation listener.
The tree and output dispose with the other extension views. No webview or CSP
changed. The frontend reports its current unsaved document URIs, including
untitled/specification buffers. Purpose requests also report foreground idle
state, including pending source-save refreshes. The backend applies the shared
safeguards; the frontend does not implement proposal or queue rules.

### Shared core and proposal boundary

`steps.run_workflow` extracts only the desktop's prepare-and-propose dispatch;
`StepController` uses the same helper for its existing two rounds. Architecture
runs `StepRunner.propose`; implementation approach runs `propose_approach`.
Queue execution uses the saved core queue, scope, grouping and batch settings and
stops at the **next reviewable round**: an approach when none is approved, or a
code/test proposal when an approach was already approved by the existing workflow.
It does not advance the cursor or enable automatic approval. Core preparation
still builds/parses the project and, for an unprepared project, creates its
existing step-zero Git baseline. There is no new commit operation, and producing
a candidate does not promote it or create an approval commit.

Core purpose completion edits a private source copy and rejects non-documentation
changes. The new `documentation.propose` retains checked files in a distinct
`.icoda/cache/purpose-*` candidate directory instead of saving them over project
source. `documentation.completion_refusal` is shared with the desktop's existing
start/completion checks. The desktop retains its background retry policy and its
idle/unsaved-buffer/proposal gate before applying comments; extension proposals
require idle, no unsaved documents, no pending candidate, and complete non-stale
analysis before starting. Each explicit command runs one completion pass; there
is no new automatic idle-time provider invocation. Candidate files require G13
review and source-freshness validation before any future apply operation.

The service preserves existing worktree/purpose candidates, including after a
backend restart, and refuses another proposal that could overwrite them. A live
proposal also blocks phase advancement. G12a's no-proposal phase behavior and
specification/provider contracts are retained. Proposal browsing/review actions,
discarding a candidate and continuing beyond a review gate remain G13.

A workflow owns a dedicated thread and a cancellation event. A thread-local
`process.cancellation_scope` supplies that event to nested provider/build/test
commands, Git commands and analysis child processes. Without an explicit scope,
desktop behavior is unchanged. No process-wide cancellation is used by the new
service methods. Successful project/target switches signal cancellation, and EOF/SIGTERM
cancel and join owned workflow work, including queued starts racing with EOF. Another workflow cannot start until the
previous worker has stopped. Project analysis, target operations, spec writes
and phase transitions reject concurrent execution with `workflow_busy`; source,
view, trace, inventory and status requests remain responsive. Core provider and
build/test timeouts remain in force. Cancellation acknowledgement does not imply
completion: poll until the terminal `cancelled` state.

### Additive protocol v1 contract

All four methods are in `METHODS` and `initialize.capabilities.methods`.
Capabilities additionally expose `workflowKinds` (`architecture`,
`implementation_approach`, `implementation_queue`) and `purposeComments: true`.
All requests require the existing top-level `sessionId`, `modelRevision`,
`targetId` and the exact boolean `params.trusted: true`, including status/cancel.
Existing stale-session/revision/target rejection runs before dispatch. Start and
status retain model revision: candidates do not replace the workspace model.

| Method | Params beyond `trusted` | Result |
|---|---|---|
| `workflow.start` | Required `kind`, `unsavedDocuments: string[]`; optional `provider`, `model`, `request`, `focus: string[]`, `maxEntities` (positive integer; default 5) | Current context and `workflow`, immediately after launching the worker. |
| `purpose.propose` | Required `idle: boolean`, `unsavedDocuments: string[]`; optional `provider`, `model` (purpose context is the whole-project missing-comment inventory) | The same asynchronous workflow envelope, with kind `purpose`. |
| `workflow.status` | Optional `workflowId` | Current scoped workflow; null if none belongs to this session/revision/target. An explicit unknown/old ID fails with `workflow_missing`. |
| `workflow.cancel` | Optional `workflowId` (omitting selects the current scoped job) | Signals the owned event and returns the current envelope. The terminal status arrives later. |

String lists allow at most 1,000 nonempty UTF-8 strings without NULs. Context
entries must exist as entity IDs or file paths in the whole-project model.
Provider/model strings use the registry and saved binary override; there is no
request parameter for an arbitrary executable or command line. Model IDs retain
the desktop's ability to use a custom selected model. No credentials are part of
the protocol. Diagnostic text passes through core credential redaction; raw
prompts and raw provider replies are not exposed as workflow status.

The envelope contains `sessionId`, `modelRevision`, `targetId`, `sourceRootId`,
and `workflow: {id, kind, state, message, result, error}`. States are `running`,
`completed`, `failed`, `cancelled`. A completed proposal is ready for review,
not approved. `result` reports `round` (`code`, `approach`, `purpose`), `summary`,
`candidateLocation` (core worktree/purpose directory, or null for prose), and
`files`. Code/approach results also contain `number`, `attempts`, `batch`, `focus`;
code results add `delta`, `build: {ok, output}` and `tests: {ok, output}`;
approaches add `entities`; purpose proposals add `skipped` files. Failed checked
proposals retain their result/candidate and repeat it in `error.details.proposal`.
The latest in-memory result is scoped to its originating selection; full
persisted proposal review/recovery is G13.

Notifications **`workflow.progress`** and **`workflow.state`** carry that same
scoped envelope in `params`, without a request ID. `workflow.id` identifies the
job. The first reports the core's progress; the second reports a terminal state.
Polling is equivalent and is used by the extension (200 ms interval). Start can
already report a terminal state for an immediately completed worker. Stdout
remains NDJSON only; diagnostic logging stays on stderr or in structured fields.

Immediate failures use normal protocol errors; asynchronous failures use the
same `{code, message, details}` shape inside `workflow.error`:

- `provider_unavailable`: disabled, unknown or uninstalled selected provider;
  `details.capability` is the current G12a inventory. No model is invoked.
- `provider_failed`: provider invocation/response failure. Invocation failures
  include the core `diagnosis` (code, summary, next_step, redacted detail,
  recovery attempts). Core read-only retry behavior is retained.
- `provider_cancelled`: explicit cancellation or a scope switch; no LLM recovery.
- `proposal_failed`: a returned code candidate failed the shared validation or
  build/test gates; its candidate and gate output remain available.
- `workflow_failed`: other core workflow/preparation failures (including phase,
  dirty-tree or queue prerequisites), without provider recovery.
- `workflow_busy`, `workflow_missing`, `proposal_pending`, `unsaved_documents`,
  `purpose_not_ready`: explicit lifecycle/safeguard refusals.
- Existing `invalid_params`, `workspace_untrusted`, `invalid_session`,
  `stale_revision`, `stale_target` retain their meanings.

`source_missing`/`source_ambiguous` never enter provider recovery. No automatic
provider call is introduced by opening projects, navigating or inspecting state.

### Controlled-provider verification and remaining G12 scope

Starting HEAD: `fde592e3636dd19c9e84c51ffb43337d395fc717`. Earlier migration
changes were already present and preserved; the starting file hashes and logs
are retained outside the repository in the job's system-temp `it17/` directory.
No repository commit or merge was made. There is no ICODA-local AGENTS.md.

Before implementation, in `vscode/`, using the requested user-local Node.js
v24.21.0 and an explicit prepared `ICODA_TEST_PYTHON`, **`npm run compile` exited
0 with 0 errors; `npm test` reported 135 tests, 135 pass, 0 fail, 0 skipped**.
There was no G12a baseline failure to repair.

`tests/fixtures/fake_workflow.py` is a controlled `Provider` executable invoked
through the ordinary agent/recovery path. Test-only bootstrap code replaces the
provider registry and editing template with this fixture; production has no
fake-provider switch or alternate invocation path. It supplies valid proposals,
a prose approach, a deterministic failure, a cancellable slow child and checked
purpose-comment edits. The shared fixture prepares a disposable Python Git
project with a real compileall build, pytest gate and child-process analysis.
Only disposable fixture baselines are committed. Python and Node tests launch
the actual service; the Node fixture injects the provider through a temporary
package shim. No real CLI agent or network service was invoked, and no credential
contents were read, printed or persisted.

Reproduction (set the prepared interpreter locally; no fixed machine path):

```bash
# From icoda/, with the prepared Python bin directory on PATH:
python -m pytest -q
python -m ruff check icoda_core/service.py icoda_core/steps.py icoda_core/documentation.py icoda_core/process.py icoda_core/session.py icoda_core/git.py icoda_gui/step_controller.py icoda_gui/troubleshooting.py tests/test_service.py tests/fixtures/fake_workflow.py
python -m mypy icoda.py icoda_core icoda_gui
cd vscode
npm run compile
ICODA_TEST_PYTHON="$PREPARED_PYTHON" npm test
```

Final verification on Linux (2026-09-28):

| Check | Actual result |
|---|---|
| `python -m pytest -q` from `icoda/` | **1089 passed, 10 skipped in 81.01s (0:01:21)**; zero failures, including desktop regressions. |
| Repository-root `python -m pytest -q` | **1649 passed, 11 skipped in 103.93s (0:01:43)**; zero failures, with the prepared ICODA Python and sibling test dependencies on `PYTHONPATH` as in G12a. |
| `npm run compile` | **`tsc -p .`, exit 0, 0 errors**. |
| `ICODA_TEST_PYTHON=… npm test` | **143 tests, 143 pass, 0 fail, 0 skipped**. |
| Ruff, byte compilation, whitespace | Passed for changed Python files; `git diff --check` passed. New production functions stay within the 30/50-line guideline/limit. |
| Mypy | **6 errors in 3 unchanged files (69 source files checked)**, matching the inherited findings below. |

The 24 added service cases cover architecture and both implementation queue
rounds, explicit approach proposals, no automatic approval even with that saved
setting enabled, successful build/test candidates, progress, independent source
navigation, provider failure, trust and all identity gates, malformed arguments,
idle/unsaved/pending purpose safeguards, candidate-only comments, project-switch
cancellation and backend EOF with queued/running children. Selecting the same
or an invalid target leaves an active workflow alone. The eight new Node cases
cover manifest/registration boundaries, validated inputs, progress/cancel and
listener cleanup, stale successes/failures, disposal, diagnostics isolation and
a real-service proposal round trip. The fake provider's PID is checked after
cancellation on POSIX. Test-only Git baselines and proposal files stay in
disposable directories; the repository HEAD is unchanged.

The full verifier is excluded because it invokes real providers. Native
Extension Host screenshots, real-provider qualification and Windows execution
were not performed in this slice. Mypy retains the six pre-existing findings in
`force_layout.py`, `source_edit.py`, and `icoda.py`; none is in the new workflow
code.

**G12 remains partial, with this exact remainder:** new-project skeleton/build
and post-save analysis UI integration; editing queue scope/grouping/batch settings
in the extension (execution already honors saved settings); conversational and
architecture/approach adaptation UI; automatic idle purpose-comment scheduling,
two-attempt tracking and verified application. Proposal review, approach/code
approval, adaptation gates, apply/reject/commit/undo, automatic approval and
continuing a queue after its review gate are G13, deliberately absent here.
Configured real-provider and native UI qualification remain separate evidence.
These are explicit remaining milestones, not user-agreed feature omissions.

## G13 — Proposal review and decisions (iteration 18)

This slice supplies review and explicit decisions for the code and approach
objects produced by G12b. The **ICODA Proposal Review** native tree shows the
candidate files, entity/API delta, build/test outcomes, saved automatic-approval
setting and step history. Clicking a file calls `vscode.diff` with the project
file on the left and the actual `.icoda/worktree` file on the right. Added and
deleted files use a read-only empty document for the missing side; source files
remain native VS Code documents, including their unsaved buffers. No webview or
CSP changed. The existing AI workflow commands now visibly explain that an
untrusted workspace must be trusted before they can run.

### Desktop audit and shared implementation

`step_panel.py` renders the delta, signature table, source diff and separate
build/test outputs. `StepController.approve` refuses failed proposals and
requires confirmation of the current proposal's signature changes. Its signature
check is now the shared `steps.require_signature_confirmation`; desktop behavior
and exception compatibility are retained. `StepRunner.approve_reviewed` applies
these review prerequisites and delegates to `approve` or `approve_approach`.
The existing core still owns quality/documentation/grouping/coverage checks,
phase and queue validation, promotion, repeat project build/test checks,
rollback, commit author/message, log entries and implementation cursor updates.
The service contains no replacement approval or undo algorithm.

`StepRunner.adapt` uses the existing `adaptation.parse_summary` and
`describe_changes` to build constraints, then enters the same normal proposal
round. As on desktop, structured code adaptation requires a usable proposal with
an entity summary; approach adaptation accepts constraints. Manual candidate
editing uses the existing `rebuild` operation before another review. Reject calls
`reject`/`reject_approach`, recording the reason for later prompts. History reads
`StepLog.records`; manual edits call `commit_manual_edits`. Undo calls `undo`,
which enforces the existing non-skeleton, clean-tree and latest-commit rules.
No alternate apply, force-approve or arbitrary Git command is exposed.

Desktop automatic approval uses `auto_approve.derive`, requires implementation
code with passing gates and confirmed signatures, and still pauses at approach
review. This slice reports the saved `ProjectState.auto_approve` value without
changing it or G12b's explicit stop-at-review behavior. It does not automatically
invoke a provider after a decision. Explicitly running the implementation queue
after approach approval now reaches code generation; code approval advances the
existing queue through the core.

### Additive protocol v1 contract

All eight methods below are in `METHODS` and `initialize.capabilities.methods`;
`initialize.capabilities.proposalReview` is `true`. Every method uses the
existing top-level `sessionId`, `modelRevision`, `targetId` identity checks.
The two reads do not require trust. Every mutation requires exact boolean
`trusted: true`, a nonempty `evidenceFingerprint` from the latest `proposal.get`,
and the current `unsavedDocuments: string[]`. The string-list limits and UTF-8
validation are the same as G12b. Unknown parameters are rejected.

| Method | Additional parameters | Result |
|---|---|---|
| `proposal.get` | Required `unsavedDocuments`; optional `trusted` | Scoped review envelope described below, including a fingerprint even when no current proposal exists (for undo/manual edits). |
| `proposal.approve` | Optional `confirmSignatures: boolean`, default false | Core code/approach approval record and updated project snapshot/history. |
| `proposal.reject` | Required nonempty `reason` | Core rejection record and updated project snapshot/history. |
| `proposal.adapt` | Optional `constraints: string[]`, `entitySummary: string` (editable JSON) | Existing asynchronous workflow envelope. Poll `workflow.status`; cancel with `workflow.cancel`. |
| `proposal.rebuild` | No additional parameters; code proposals only | Existing asynchronous workflow envelope for rebuilding/testing/parsing manually edited candidate files. |
| `history.list` | No parameters | Current context and `records` from the core step log. |
| `step.undo` | No additional parameters | Core undo record and updated project snapshot/history. |
| `step.commitManual` | No additional parameters | Core manual record (or null if unchanged) and updated project snapshot/history. Requires no pending candidate. |

The review envelope is `{sessionId, sourceRootId, modelRevision, targetId,
projectRoot, evidenceFingerprint, proposal, records, autoApprove, message}`.
`proposal` is null when this scoped service session has no reviewable code or
approach object. Otherwise it contains `round`, `number`, `summary`,
`worktreeRoot` (absolute, null for prose), `files: [{path, status}]` (worktree
relative, Git A/M/D), `delta` (the shared entity/API summary), `signatureChanges`
(the core's `usr`, `display_name`, `previous_signature`, `proposed_signature`),
`build` and `tests` (`{ok, output}`, null for prose), `entitySummary` (canonical
editable JSON), `error`, `evidenceFresh`, and `canApprove`. The last flag excludes
failed checks, changed candidate inputs and unsaved documents; a true flag still
requires signature confirmation and all core checks at decision time.

History records retain the `StepRecord` fields, excluding the provider binary
configuration; strings/output use core credential redaction. Raw provider
prompts/replies are not sent. As in the existing log format, `commit` is available
on the immediate decision record but is not persisted inside its own commit.
Build/test output is sent to **ICODA Proposal Review**, including history output.

Approve/reject/undo/manual responses contain the project snapshot plus `record`
and `records`, increment model revision once, retain selected target identity,
and clear loaded playback. Approval reloads the core's accepted model; undo and
manual edits mark the model stale and ask for Analyse Project. Adapt/rebuild
retain the revision and reuse G12b's `workflow.progress`/`workflow.state`
notifications, statuses, cancellation and worker ownership; no new notification
format is introduced. Decisions run on the existing serialized service worker.
Approval/undo/manual commits are noncancellable transactions with the core's
existing tool timeouts; the extension presents progress while awaiting them.
A final approve/reject clears the pending candidate and removes its worktree via
`git.remove_worktree`, allowing the next explicit G12 workflow to start.

Review fingerprints bind the session/selection/revision, workflow identity,
project and candidate Git HEAD/index, all tracked and nonignored untracked file
contents and modes (including unchanged inputs), and normalized relevant dirty
editor URIs. Ignored build/cache outputs do not invalidate evidence. The
candidate's checked fingerprint is captured when its generation/rebuild finishes:
calling `proposal.get` again after a file edit cannot make old gates current.
Rebuild produces new evidence and signature confirmation must be given again.
Project/candidate editor changes are relevant; unrelated local file editors are
excluded, while untitled/virtual editors conservatively block decisions. The
extension sends the dirty list at review and again after decision dialogs, never
saving or replacing buffers itself.

Distinct review errors are:

- `proposal_gate_failed`: candidate validation/build/test/quality or promoted
  project gates failed, or the core refused a review adaptation/rebuild.
- `signature_unconfirmed`: changed API signatures lack explicit confirmation
  (`steps.SignatureConfirmationRequired`). This existing v1 code is retained;
  it is not renamed to `signature_confirmation_required`.
- `stale_evidence`: candidate/project evidence, Git HEAD/index, review identity or
  relevant dirty-editor list changed; refresh/rebuild as directed.
- `dirty_tree`: the existing core clean-tree guard refuses ordinary project edits;
  its existing metadata exceptions are retained. Commit Manual Edits is the
  explicit supported path for saved manual changes.
- `undo_disallowed`: the core refuses undo (no approved non-skeleton step or
  unrelated HEAD); no revert is attempted by an alternate service path.
- `proposal_missing`: no scoped proposal is available to decide.
- `proposal_pending`, `unsaved_documents`, `workflow_busy`, `workspace_untrusted`,
  `invalid_params`, `invalid_session`, `stale_revision`, `stale_target` retain their
  existing meanings.
- `provider_failed`, `provider_cancelled`, `proposal_failed`, `workflow_failed`
  retain the G12b asynchronous envelope: provider failure, cancellation, a
  returned candidate with failed checks, and other unexpected worker failures,
  respectively. Retained candidate metadata remains available after a failed retry.

`review_error` maps `StepError` subclasses for immediate decisions and background
adapt/rebuild refusals. `DirtyTree` always maps to `dirty_tree`, signature
confirmation to `signature_unconfirmed`, and other core refusals to
`undo_disallowed` for undo or `proposal_gate_failed` for proposal decisions.
Background review refusals carry these same codes in `workflow.error`;
provider failures/cancellation retain their separate codes. G12 workflow methods
and their error mapping are unchanged. No gate or undo rule is implemented here.

### Commands, verification and precise remainder

The manifest now contains **36 commands**. Added ICODA commands are **Review
Proposal**, **Approve Proposal**, **Reject Proposal**, **Adapt Proposal**,
**Rebuild Proposal**, **Undo Last Step**, **Commit Manual Edits**, **Show Step
History**, and the tree's **Open Proposal Diff**. Signature confirmation is a
modal dialog showing old/new declarations. Reject records an explicit reason;
adapt accepts constraints or edited entity JSON. Decision commands reject
injected arguments; the diff command accepts only a validated current tree
selection, never a caller-supplied root. SessionState drops stale reads and
mutations. Views, command registrations, content providers and cancellation
listeners are disposed with the extension.

Starting HEAD remains `fde592e3636dd19c9e84c51ffb43337d395fc717`. Existing It1–It17
working-tree changes were preserved. No checkout commit or merge was performed;
all commits/reverts in acceptance tests belong to disposable fixture projects.
Only `tests/fixtures/fake_workflow.py` was used as a provider; there was no real
provider, CLI-agent or network-service invocation. The full verifier was not run
because it includes real-provider execution.

Baseline, with user-local Node v24.21.0 on PATH and `ICODA_TEST_PYTHON` set:
`npm run compile` printed `> tsc -p .` and exited **0 (0 errors)**;
`npm test` reported **143 tests, 143 pass, 0 fail, 0 skipped**.

Reproduce from `icoda/`, using a prepared Python environment:

```bash
python -m pytest -q
python -m ruff check icoda_core/service.py icoda_core/steps.py icoda_core/git.py icoda_gui/step_controller.py tests/test_service.py tests/fixtures/fake_workflow.py
cd vscode
npm run compile
ICODA_TEST_PYTHON="$PREPARED_PYTHON" npm test
```

The 22 new Python service cases exercise real approval commits/history,
failed-gate refusal, signature confirmation, candidate and unchanged-input
edits, changed dirty-editor lists, changed HEAD, dirty project files, rejection
reasons, structured adaptation, manual-candidate rebuild, manual commits,
approach-to-code queue continuation, allowed/disallowed undo, trust, malformed
parameters, relevant dirty-editor scope and all identity checks. Ten new Node
cases cover real view-method trust messaging, registration/manifest boundaries, Windows/POSIX diff roots and
missing sides, native diff arguments, stale selections/responses/disposal,
availability and adaptation cancellation. The existing real-service Node fixture
now also approves and checks source, commit and history. These are Linux service
and Node tests, not a native Extension Host qualification claim.

Final verification on Linux, 2026-09-28:

| Check | Actual result |
|---|---|
| `python -m pytest -q` from the repository root, prepared ICODA Python plus sibling test dependencies on `PYTHONPATH` | **1671 passed, 11 skipped in 153.34s (0:02:33)**; zero failures, including the complete ICODA and desktop regression suites and the final dirty-editor scope case. |
| Earlier standalone `icoda/` suite, before the final dirty-editor scope case | **1110 passed, 10 skipped in 137.67s (0:02:17)**; zero failures. |
| `npm run compile` | **`> tsc -p .`, exit 0, 0 errors**. |
| `ICODA_TEST_PYTHON=… npm test` | **153 tests, 153 pass, 0 fail, 0 skipped**. |
| Ruff / byte compilation / whitespace | Passed for changed Python files; `git diff --check` passed. |
| New/changed function sizes | Python review/service functions at most 33 lines; new TypeScript production functions at most 27, all below the existing 50-line maximum. |
| Mypy | **6 errors in 3 unchanged-by-this-iteration files (69 source files checked)**: the inherited `force_layout.py`, `source_edit.py` and `icoda.py` findings. No new findings in the review implementation. |

Baseline and final command logs are retained outside the repository in the job's
system-temp `it18/` artifact directory. Final HEAD remains the starting commit.
Root `AGENTS.md`, the migration contract and parity matrix were reread before
finalization; no ICODA-local instruction file exists. The other referenced
guidance files' modification times were unchanged since initial inspection.

**G13 decision implementation is complete (closure confirmed in iteration 20):** the requested explicit code/approach review,
decision, diff, history, rebuild, manual-edit and undo paths are delivered. Exact
remaining parity work is an extension editor/controller for automatic-approval
settings and queue continuation; rehydration of interrupted proposal metadata
after backend restart or a session/revision/target replacement (leftover files
are preserved, never approved using invented evidence); and native Extension
Host/Windows review screenshots and interaction qualification. Purpose-comment
application remains the separate G12 remainder. No deferral is presented as
user-agreed, and no overall migration completion is claimed.

### G13 review follow-up (iteration 19)

Proposal commands, including native diff, visibly warn when the workspace is
untrusted. Trust is checked again after decision dialogs. An approval rejected
with `signature_unconfirmed` opens the existing signature modal and retries at
most once after explicit confirmation, retaining the original evidence token
and collecting the current dirty-editor list. Cancelled dialogs, changed reviews
or sessions, and lost trust cannot authorize that retry. The reject branch is
split into readable code/approach branches without changing its core calls.

The initial corrected-environment npm baseline passed: `> tsc -p .`, exit 0
(0 errors); 153 tests, 153 pass, 0 fail, 0 skipped. Python service regressions
exercise the real clean-tree guard across approve/adapt/rebuild/reject/undo,
failed gates, signature refusal followed by approval, changed candidate/unsaved
evidence and disallowed undo. Injected worker exceptions additionally verify
subclass routing for adapt/rebuild without calling a real provider. Node tests
execute the view methods for trust warnings, signature dialogs, safe retry and
unrelated failures. Only `tests/fixtures/fake_workflow.py` supplies proposals.
Iteration 20 closes the requested G13 decision task after rerunning compile and all 158 Node tests. The broader parity and platform qualifications listed above remain visible for G18 reconciliation.

Final Linux verification (2026-09-28), with user-local Node v24.21.0 on PATH
and `ICODA_TEST_PYTHON` set to the prepared ICODA environment:

| Check | Actual result |
|---|---|
| Repository-root `python -m pytest -q`, with the sibling test dependencies on `PYTHONPATH` | **1686 passed, 11 skipped in 191.33s (0:03:11)**; zero failures, including desktop regressions. |
| `npm run compile` from `icoda/vscode/` | **`> tsc -p .`, exit 0, 0 errors**. |
| `npm test` from `icoda/vscode/` | **158 tests, 158 pass, 0 fail, 0 skipped**. |
| Focused `tests/test_service.py -k review` | **37 passed, 168 deselected in 94.35s (0:01:34)**. |
| Ruff / function sizes / whitespace | Passed; changed Python functions at most 32 lines, TypeScript functions at most 23, below the 50-line maximum. |

Only the service, Proposal View, their existing test modules and this document
changed in this follow-up. HEAD is unchanged; fixture commits remain confined to
disposable projects. Root instructions and this contract were reread; no nested
ICODA instructions exist and other referenced guidance modification times are
unchanged. The full verifier was excluded because it invokes real providers.
These tests do not add native Extension Host or Windows qualification evidence.

## G14a — Lifecycle and concurrency (iteration 20)

G14a delivers the requested AT12/AT14 lifecycle and concurrency work. At the end
of iteration 20, G14 was **partially complete**, pending the performance
measurements and budgets now recorded in G14b below. No new Extension Development Host, Windows, remote-host or installed
VSIX qualification is claimed by these automated Linux tests.

### Protocol v1 additions and ownership

- `project.close` accepts `{}` and the current session/revision/target envelope.
  It cancels and joins the owned workflow, releases project ownership, clears
  session/review state and returns the old identity plus `closed:true`. Further
  project requests receive `project_not_open` until `project.open` succeeds.
- `initialize.capabilities.projectLock:true` advertises exclusive service
  ownership. `cancellableMethods` additionally lists `project.analyse`,
  `view.get`, `trace.load` and `toolchain.inspect`; the four G09 entries remain.
  `operation.cancel` keeps its existing acknowledgement and eventual terminal
  response contract. Cancellation is an error with code `cancelled`, preserving
  the original request's identity in `error.details`.
- The reader signals pending cancellable operations when a project open/close or
  a current target-selection request arrives. State changes remain serialized
  on the existing worker; no two analysis/build/state writers run concurrently.
  A cancellation scope connects analysis and nested commands to the shared
  `process.run_bounded` / `process.kill_tree` implementation. Layout computation
  reaches cancellation at its return boundary; trace loading checks before
  installing playback. Cancelled analysis restores the retained model cache and
  does not publish a new revision. A switch waits for its predecessor to finish.
- Workflow progress and terminal notifications retain their captured identity.
  Project/target replacement cancels and joins an active workflow before changing
  that identity or releasing its lock. EOF, SIGTERM and project close likewise
  wait for owned operations/provider processes. Protocol stdout framing and all
  shared stepping, target-operation and proposal-gate behavior are unchanged.

`persistence.py` has atomic replacement but no writer exclusion; `session.py`
also has no ownership guard. The service now acquires an advisory OS file lock
at project open, before reading project state. Its retained file is under the
system temporary directory's `icoda-service-locks/`, named by the SHA-256 of the
resolved, platform-normalized project path. This keeps cached project opening
free of project-file writes and supports read-only project browsing. POSIX uses
`flock`; Windows uses `msvcrt.locking`. The PID in the file is diagnostic only:
the kernel releases ownership on process exit, so a dead owner's leftover file
is safely reused without PID guesses or unlink races. Lock files are deliberately
retained. Same-service reopen reuses ownership; failed loading releases newly
acquired ownership. A second service gets `project_locked` with the canonical
`path` in details. Close, replacement, EOF and exit release ownership after work
stops. This local advisory guard coordinates cooperating services, not desktop
processes or unrelated applications; it does not qualify network filesystems or
multiple machines sharing project storage.

### Extension lifecycle

Backend process/stream/write failures reject every pending promise exactly once
with `BackendError` code `backend_exited`; normal disposal uses `backend_disposed`.
An exit error includes exit `code` and `signal` when available. Abort listeners,
line readers, stderr listeners and pending-request entries are cleaned up. The
client closes stdin so Python can terminate its owned trees on both platforms;
the existing seven-second forced-exit fallback remains for a stuck backend.

**Restart Backend** waits for the old backend to close, starts a new connection,
then reopens the previous project and restores the selected target if still
available. It works after a crash without reloading VS Code. The controller
shares startup and serializes selection/restart commands so one extension host
cannot create duplicate project backends. Open Project, Select Target and Restart
Backend can supersede an ordinary long operation. Analyse Project now exposes
native cancellation. ProjectSession invalidates outstanding identity tickets
when target selection starts, drops obsolete successes/errors and scopes progress
to the originating ticket. Existing view/workflow identity checks remain shared.

Removing the selected workspace folder disposes its controller, including save
watchers/debounce timers, panels, tree providers, command/workspace listeners and
backend, before registering a fresh empty controller. Deactivation uses the same
idempotent disposal path and cannot recreate a controller during shutdown.
Backend stderr remains diagnostic output; session-bearing operation logs are filtered by current
session/revision/target. Context-free operation logs remain visible (G14b regression below).
Project switches close old diagram panels and replace
their source watcher.

### G13 closure and verification scope

The initial configured-environment checks passed: `npm run compile` printed
`> tsc -p .` and exited 0; `npm test` reported 158 tests, 158 pass, 0 fail. An
initial shell attempt selected system Python and failed for missing dependencies;
rerunning with `ICODA_TEST_PYTHON` pointing to the prepared environment resolved
that prerequisite issue without a code change. The proposal error catalogue
above includes **all seven** required codes: `dirty_tree`,
`signature_unconfirmed`, `proposal_gate_failed`, `stale_evidence`,
`undo_disallowed`, `provider_failed`, `provider_cancelled`. The matrix closes the
requested G13 decision task; its explicitly listed wider parity/qualification
limitations remain recorded for reconciliation, not silently declared delivered.
New lifecycle codes are `backend_exited`, `backend_disposed` and `project_locked`.
Protocol version remains 1; existing methods/fields and error codes are retained.

Reproduce with prepared Python dependencies, user-local Node on PATH, and
`ICODA_TEST_PYTHON` set to that Python (no installation or provider invocation):

```bash
# Repository root; include the sibling suite's prepared dependencies on PYTHONPATH.
python -m pytest -q
cd icoda/vscode
npm run compile
npm test
```

The new Python tests use bounded slow child fakes for analysis, view and trace
requests during project/target changes and close. They check cancellation errors,
original notification identity, cache preservation and absent child PIDs; separate
cases exercise explicit cancellation, failed-open lock release, service-to-service
lock exclusion, reopen/close and dead-owner recovery. Controlled workflow cases
check target/close cancellation and terminal identity. Build/run/record close
checks include grandchildren; the fixture parent reaps them, and PID assertions
reject zombies as well as running processes. Existing EOF/provider checks remain.
No real provider, CLI agent or network service is used.

Node tests kill a backend with pending requests, assert structured rejections and
reopen the same locked project through a new backend. New controller tests execute
actual activation, commands, restart, folder removal and deactivation against the
real service with a controlled target runner and tracked VS Code resource doubles.
They assert child/backend PID disappearance and disposal of registered watchers,
panels, trees and listeners. They are controller/service evidence, not an actual
Extension Host UI run. Deferred-response cases prove that target-switch intent
invalidates analysis before acknowledgement and drops obsolete progress/errors.

Starting HEAD remains `fde592e3636dd19c9e84c51ffb43337d395fc717`; all pre-existing
working-tree changes were retained. Only the service/client/session/controller,
identity helper, their tests and this document changed in G14a. No commit or merge
was performed. The complete verifier is excluded because it invokes real providers.

Final G14a verification on Linux, 2026-09-28:

| Check | Actual result |
|---|---|
| Repository-root `python -m pytest -q` with prepared ICODA Python and sibling test dependencies on `PYTHONPATH` | **1705 passed, 11 skipped in 210.32s (0:03:30)**, including desktop regressions. |
| `npm run compile`, user-local Node v24.21.0 | **`> tsc -p .`, exit 0, 0 errors**. |
| `npm test`, `ICODA_TEST_PYTHON` set | **167 tests, 167 pass, 0 fail, 0 skipped**. |
| Focused lifecycle/process/lock cases before the final tool-discovery case | **21 passed, 202 deselected in 7.94s**; final standalone discovery ownership case separately passed (1 passed, 223 deselected) and is included in the full gate above. |
| Ruff for service/tests; `git diff --check` | Passed. |
| Mypy for `icoda_core/service.py` using the ICODA configuration | Five inherited findings in unchanged `force_layout.py` and `source_edit.py`; no service findings. |
| Function sizes | Service maximum 42 lines; changed TypeScript production files maximum 27, within the 30/50-line rule. |

Logs are retained outside the repository in the job's system-temp `it20/`
artifact directory. Root `AGENTS.md` and this lifecycle contract/parity matrix
were reread before finalization; no ICODA-local instruction file exists. All
other referenced guidance files retained their starting modification times.

## G14b — Performance baseline and budgets (reverified in iteration 22, 2026-09-28)

The requested G14 lifecycle/concurrency and measured-budget work is complete on
the tested local Linux service/client path. This closes G14a verification and
adds reproducible headless performance evidence; it does not qualify native
Extension Host rendering, Windows, remote filesystems, or an installed VSIX.

### G14a verification closure

Iteration 22 compiled (`tsc -p .`, exit 0) and passed all **169 Node tests**,
including both iteration 21 additions: `BackendClient keeps the Node event loop
responsive during slow analysis` and `output accepts context-free and current
logs but drops stale or partial session logs`. No code correction was needed.
The existing service tests cover all four requested scenarios; the exact
selection below passed **12 cases in 2.36s**, including nine slow-operation /
selection-change combinations. No duplicate tests were added.

| Requirement | Passing function in `tests/test_service.py` | Assertion evidence |
|---|---|---|
| (a) Second-service exclusion; (b) release on close | `test_project_lock_excludes_second_service_and_releases_on_close` | A separate process gets `project_locked`; after `project.close`, the other service opens the same root. |
| (b) Release on process exit | `test_project_lock_is_released_on_service_exit` | EOF exits without a close request; the owner PID disappears and another service acquires the root. |
| (c) Dead-PID recovery | `test_dead_lock_owner_is_recovered_without_deleting_lock_file` | Confirms the recorded PID is dead, reuses the retained lock file and checks the new live owner. |
| (d) Slow operation across selection changes | `test_slow_request_is_cancelled_before_selection_changes` | Analysis/view/trace requests are cancelled across project open, target select and close; errors/notifications retain the old identity, the child exits, the model cache is unchanged and the switch succeeds. |

Existing Node crash/restart coverage also verifies acquisition after SIGKILL.
Superseded operations terminate with error code `cancelled` and the original
session/revision/target in `error.details`; they do not return an old successful
result to the new selection. The frontend invalidates its request ticket when a
switch starts and discards obsolete responses, errors and progress. G14a above
documents `backend_exited`, `backend_disposed` and `project_locked`, including
pending-request completion and lock ownership/release.

`extension.ts` forwards `operation.log` notifications with none of the three
session fields, as well as logs matching the complete current
session/revision/target. Partially scoped or stale notifications are dropped.
The focused Node test invokes the activated controller's notification callback
and asserts the actual output-channel writes for both accepted cases and all
three identity mismatches. `backend_exited`, `backend_disposed`, `project_locked`
and the superseded/cancelled lifecycle remain as documented in G14a; there is no
new protocol method, field, code, or version change.

Starting HEAD is still `fde592e3636dd19c9e84c51ffb43337d395fc717`. The inherited
working tree already contained the preceding migration's tracked changes and
untracked service, fixtures, extension, measurement tool and migration document.
Iteration 22 changes only this document; production code, tests and the measurement
tool were retained unchanged. No repository commit or merge was made.

### Reproducible measurement procedure

`tools/measure_service.py` launches the real service over UTF-8 newline-framed
protocol v1. It copies Python inputs using the shared source-discovery exclusions
into a fresh system-temp directory for each run; existing `.icoda` state, build
files and non-Python sources are excluded. It analyses those copies as Python,
including tests/tools when measuring ICODA. Project code is never executed.
Only initialization, opening, analysis, target selection, view and playback
operations run; no provider, build or network operation is invoked. Source copies,
configuration and generated traces are removed on exit; the source checkout is
not used as a writable project. Raw JSON goes to stdout for redirection below.
Each protocol read has a 120-second deadline and backend cleanup waits for EOF.

Measured host: Ubuntu 24.04.4 LTS, Linux 7.0.0-31-generic, x86_64, glibc 2.39;
AMD Ryzen 7 9700X desktop CPU class (8 cores / 16 threads); Python 3.12.3 and user-local
Node v24.21.0. Existing prepared dependencies were reused. No machine-specific
checkout/runtime path is required. With `ICODA_TEST_PYTHON` set to the prepared
venv executable (keep its venv path, not its resolved system-Python symlink):

```bash
# From icoda/; default projects are the two fixture roots and this ICODA checkout.
export ICODA_TEST_PYTHON
export PATH="$(dirname "$ICODA_TEST_PYTHON"):$PATH"
ICODA_EVIDENCE="${TMPDIR:-/tmp}/ai-loop-worker-reports/J20260927-170326-588902/it22"
mkdir -p "$ICODA_EVIDENCE"
PYTHONHASHSEED=0 python tools/measure_service.py > "$ICODA_EVIDENCE/performance.json"
# --project PATH may be repeated to select Python source roots explicitly.
cd vscode
export PATH="$HOME/.local/share/nodejs/v24.21.0/bin:$PATH"
npm run compile
node --test --test-name-pattern='Node event loop' out/test/lifecycle.test.js \
  > "$ICODA_EVIDENCE/responsiveness.log" 2>&1
npm test
```

These measurements cover **Python-source analysis only**. No C++ analysis or
ViennaVulkanEngine performance numbers are claimed. The first invocation without
a fixed hash seed aborted its count-consistency check: three diagnostic runs of
the unchanged ICODA snapshot returned File overviews with 25 / 25 / 24 nodes
and 173 / 173 / 161 edges, while model, Call and Class counts agreed. Setting
`PYTHONHASHSEED=0` for the measurement process and its children produced identical
counts across all three runs. That stabilized the benchmark without establishing
cross-seed overview determinism. Raw diagnostic observations remain in system temp.

**Hash-seed nit fixed in iteration 24:** one saved ICODA Python snapshot model
(160 files, 2,767 entities, 11,630 edges) reproduced 25 nodes / 173 edges for seeds
0 and 42, 24 / 161 for seed 1, and 20 / 117 for seeds 2 and 12345. Recursive
`diagram_partition.split` subgraph views iterated NetworkX's internal node sets,
changing fixed-seed Louvain input order. Shared-core canonical node/edge insertion
order now applies at every recursive level; the algorithm, scores and 40-file
limit are unchanged. All five seeds now yield byte-identical clusters, memberships,
labels, box order, geometry and arrows: 25 nodes / 173 edges, matching the previous
seed-0 output. Application launches do not pin `PYTHONHASHSEED`.

`tests/test_clusters.py::test_file_overview_is_identical_across_hash_seeds` runs
the shared File overview computation used by `view.get` on one fixed 136-file
recursive-partition fixture in five subprocesses. It failed before the fix and
passes afterward, comparing complete serialized clustering/layout results while
checking membership and the 40-file bound. Reproduce from `icoda/` with
`python -m pytest -q tests/test_clusters.py::test_file_overview_is_identical_across_hash_seeds`.
The focused clustering/partition/view suite passed all 75 cases without changing
existing assertions. Raw before/after models, results and logs remain under the
system-temp worker report directory's `it24/` subdirectory.

Three fresh backends and uncached project copies were measured per project, with
no timed warm-up or OS-cache flush. Startup includes spawning Python through the
initialize response. All other timings include request serialization, pipe
transport, backend work and response decoding, excluding copying/setup. Call
View uses Whole Project with the callable having the most direct call edges
(USR breaks ties), depth 3. File/Class use their default overview parameters
(File: 1000 × 700). Target selection is outside the measured view durations.

| Analysed Python snapshot | Files / entities / edges | Call / File / Class visible nodes | Trace used |
|---|---|---|---|
| `tests/fixtures` | 1 / 4 / 20 | 4 / 2 / 0 | 240 synthetic complete leaf calls alternating four resolved functions; 480 events. `fake_workflow.py` is only parsed. |
| `vscode/src/test/fixtures/python` | 2 / 7 / 5 | 4 / 2 / 0 | Checked-in synthetic `calls.tsv`: six calls, 12 events, main/A/B/C/D/E. |
| ICODA (`.`), Python-source snapshot | 160 / 2,767 / 11,630 | 89 / 25 / 20 | 240 synthetic complete leaf calls cycling the first 32 sorted callable USRs; 480 events. |

The small fixtures have no classes, so their Class measurements cover the empty
response; the ICODA measurement covers a populated grouped Class overview. Its
Call root was `python:tests.gui_acceptance:main` (126 visible edges), and File
and Class returned overviews (173 / 34 edges). This is a real repository AST
analysis, not generated model data. ViennaVulkanEngine was not measured for G14b.
Synthetic traces measure resolved playback, not recording/build throughput or
runtime call behavior of ICODA itself.

### Measured latencies and chosen budgets

All values below are **milliseconds, median / p95**. For startup/open/analyse/
views/load there are three samples, so nearest-rank p95 equals the observed
maximum; these are baseline observations, not a statistically stable tail
estimate. `trace.step` has **720 samples per project**, always advancing Into
to a resolved call. Exhausted fixture traces are reset outside the timed step;
reset/no-op latency is not mixed into the sample. Every run verifies identical
model/view counts and complete trace resolution. No stepping behavior changed.

| Protocol operation | `tests/fixtures` | VS Code Python fixture | ICODA Python snapshot |
|---|---:|---:|---:|
| Startup + initialize | 67.298 / 87.469 | 25.235 / 45.738 | 25.658 / 26.738 |
| `project.open` (no model cache) | 178.164 / 186.033 | 89.795 / 102.813 | 82.983 / 84.246 |
| `project.analyse` | 316.371 / 413.119 | 104.124 / 205.267 | 5,103.457 / 5,315.624 |
| `view.get` Call | 1.522 / 1.834 | 0.863 / 1.201 | 21.504 / 21.852 |
| `view.get` File | 1.807 / 2.134 | 0.540 / 0.732 | 54.258 / 57.404 |
| `view.get` Class | 0.376 / 0.420 | 0.141 / 0.208 | 97.364 / 102.272 |
| `trace.load` | 5.338 / 9.617 | 1.397 / 2.003 | 11.071 / 13.087 |
| `trace.step` Into | 0.137 / 0.194 | 0.064 / 0.079 | 0.069 / 0.125 |

Each metric has one budget shared by these three workloads, rounded upward from
three times its largest observed p95. The table states the resulting headroom
(budget divided by that p95). These are investigation thresholds for comparable
local hardware, not UI frame-rate guarantees or CI timing assertions. For
three-sample operations compare the maximum; the step budget applies to both
median and p95. These fresh results replace the iteration 21 performance figures.

| Metric | Largest measured p95 | Budget | Headroom |
|---|---:|---:|---:|
| Startup + initialize | 87.469 ms | 300 ms | 3.43× |
| Uncached `project.open` | 186.033 ms | 600 ms | 3.23× |
| `project.analyse` | 5,315.624 ms | 20,000 ms | 3.76× |
| Call `view.get` | 21.852 ms | 100 ms | 4.58× |
| File `view.get` | 57.404 ms | 250 ms | 4.36× |
| Class `view.get` | 102.272 ms | 500 ms | 4.89× |
| `trace.load` for the stated synthetic traces | 13.087 ms | 50 ms | 3.82× |
| `trace.step` Into | 0.194 ms | 1 ms | 5.16× |

### Node event-loop responsiveness and automated guards

`lifecycle.test.ts` drives `project.analyse` through the production BackendClient
and real service, with a controlled 750 ms delay before real Python analysis.
After a protocol progress marker, a Node timer writes a release marker required
by the backend; completion therefore proves that host timers/I/O can run while
the request is pending. The test also checks that a fresh nonempty model returns.
It records `monitorEventLoopDelay` with 10 ms resolution and timer tick count;
there is no tight scheduling assertion. The standalone measured run took
**955.468 ms** for analysis, with **93 ticks**, **11.862 ms maximum** event-loop
delay and **10.920 ms p95**. Those delay values include the nominal 10 ms sampling
interval. The chosen maximum-delay investigation budget is **100 ms**, more than
eightfold headroom (8.43×). This is the extension's client path in Node, not an Electron
Extension Development Host or webview-rendering measurement.

`test_performance_script_measures_real_protocol_without_writing_fixture` runs
two fresh services and 24 actual fixture steps, verifies all metric/sample
counts, successful analysis/resolution and unchanged fixture files. Its overall
60-second subprocess deadline is a hang guard; no per-step wall-clock CI limit
is imposed. The responsiveness test has a 20-second overall deadline and checks
progress/completion rather than enforcing the observed timing budget. This
keeps the checks bounded without assuming fast or idle CI hardware.

### Iteration 22 repair verification

The focused selection was run from `icoda/` with the same prepared Python:

```bash
python -m pytest -q \
  tests/test_service.py::test_project_lock_excludes_second_service_and_releases_on_close \
  tests/test_service.py::test_project_lock_is_released_on_service_exit \
  tests/test_service.py::test_dead_lock_owner_is_recovered_without_deleting_lock_file \
  tests/test_service.py::test_slow_request_is_cancelled_before_selection_changes
```

For the full job gate, start at the repository root, set `ICODA_TEST_PYTHON`
to the prepared venv executable and `AILOOP_TEST_SITE_PACKAGES` to the sibling
suite's prepared dependency directory, then run:

```bash
export PATH="$(dirname "$ICODA_TEST_PYTHON"):$PATH"
PYTHONPATH="$AILOOP_TEST_SITE_PACKAGES" python -m pytest -q \
  > "$ICODA_EVIDENCE/pytest.log" 2>&1
git diff --check
```

| Check | Actual result |
|---|---|
| Repository-root `python -m pytest -q`, prepared ICODA Python on PATH and sibling test dependencies on `PYTHONPATH` | **1707 passed, 11 skipped in 216.56s (0:03:36)**; includes all 226 service cases, the measurement-script regression and desktop regressions. |
| `npm run compile`, user-local Node v24.21.0 | **`> tsc -p .`, exit 0, 0 errors**. |
| `npm test`, `ICODA_TEST_PYTHON` set | **169 tests, 169 pass, 0 fail, 0 skipped**. |
| Four named service tests above (including parametrization) | **12 passed in 2.36s**. |
| Standalone Node responsiveness test | **1 test, 1 pass, 0 fail**; diagnostic measurements above. |
| Default-project measurement | Passed with `PYTHONHASHSEED=0`: three runs per project, 720 advancing steps per project. The initial variable-count failure is recorded above. |
| Documentation cross-check; whitespace | All 24 median/p95 pairs and three project counts match the raw JSON; lifecycle codes are present; document whitespace and `git diff --check` pass. |
| Change scope | File hashes confirm only this document changed during iteration 22; all existing code/tests/tool files and other working-tree modifications were preserved. |

The eleven skipped tests remain skips, not passes. These commands did not install
or upgrade dependencies. Raw results remain under the system-temp
`ai-loop-worker-reports/J20260927-170326-588902/it22/` directory:
`performance.json`, `observations.json`, `responsiveness.log`, `pytest.log`,
`service-lifecycle.log` and `node-initial.log`. No raw output was added to the
repository. Root `AGENTS.md` and this migration contract/matrix were reread before
finalization; no ICODA-local instruction file exists and the other referenced
guidance files retain their starting modification times.
The complete `verify.bash` remains excluded because it invokes real providers.
No real provider, CLI agent or network service was invoked for this iteration.

## G15 — Compact themed UI and keyboard access (iteration 23, 2026-09-28)

The requested extension implementation and automated checks are complete. Native
G15/AT15 acceptance remains pending the G16 Extension Development Host run.
Starting HEAD remains `fde592e3636dd19c9e84c51ffb43337d395fc717`; the preceding
migration's working-tree changes were retained. This iteration changes only
`vscode/` and this document. No commit or merge was made.

Call View keeps Load Trace, Previous Call, Step Over, Step Into, Step Out and
Reset in one horizontal toolbar. At narrower widths a measured prefix remains
in the row and the remaining **same button elements** move into the **…** menu.
The width partition preserves order and identity; moving the elements retains
handlers and backend availability, including updates while in the menu. The
menu supports Tab/Shift+Tab, Enter/Space, Up/Down, Home/End and Escape, restores
focus when closing, and closes when focus or a pointer moves outside. Resizing
moves controls back without duplicating them. There is no Next Call control.
Graph controls retain horizontal scrolling within the same row. File, Class
and Mind Map retain their existing compact scrolling toolbar.

All four stylesheets use VS Code theme variables for colors, including neutral
cluster backgrounds. There are no hard-coded color literals or semantic literal
exceptions in these stylesheets. Both high-contrast theme classes receive
explicit borders and focus rings. Graph nodes, class members and Mind Map
expansion controls retain Tab stops and Enter/Space activation; their focus
rings use `:focus-visible`. Status messages can wrap within a bounded area
instead of hiding the explanation in a single clipped line.

The five new commands are registered and contributed in the ICODA category.
Their shortcuts are also listed in the corresponding Call View button tooltips:

| Shortcut | Command/action |
|---|---|
| Ctrl+Alt+Left | `icoda.tracePrevious` — Previous Call |
| Ctrl+Alt+Down | `icoda.traceOver` — Step Over |
| Ctrl+Alt+Right | `icoda.traceInto` — Step Into |
| Ctrl+Alt+Up | `icoda.traceOut` — Step Out |
| Ctrl+Alt+Home | `icoda.traceReset` — Reset Trace Playback |

Every binding and command enablement uses
`activeWebviewPanelId == icoda.callView && !editorTextFocus && !inputFocus && icoda.projectOpen && isWorkspaceTrusted`.
No F10/F11 binding is contributed. Commands route through the existing validated
Call View action queue and backend availability checks. Actual host dispatch and
OS shortcut conflicts remain part of G16 qualification. Open Project and Restart
Backend now also declare their existing Workspace Trust requirement in command
enablement; Show Output remains available without a project or trust.

All four view models explicitly distinguish no project from no model and give
an actionable command. Existing empty-model and backend trace explanations
remain visible, including no loaded trace and no resolved project calls. A
frontend formatter presents backend explanations and recovery actions without
raw error-code prefixes in graph errors, project-command notifications and
source navigation warnings. Typed errors and their codes remain intact for
routing; the real-service invalid-trace regression asserts that distinction.
No protocol, shared stepping, build/record, workflow, proposal-gate, lifecycle
or desktop behavior was changed.

### Verification and evidence boundary

Run the repository-root Python command with `ICODA_TEST_PYTHON` set to the
prepared venv executable (keep its venv path, without resolving its symlink),
its `bin` directory on PATH, and `AILOOP_TEST_SITE_PACKAGES` set to the sibling
suite's prepared dependencies, as in iteration 22 above:

```bash
PYTHONPATH="$AILOOP_TEST_SITE_PACKAGES" python -m pytest -q
# From vscode/, with the user-local Node 24.21.0 bin directory first on PATH:
npm run compile
ICODA_TEST_PYTHON="$ICODA_TEST_PYTHON" npm test
```

| Check | Actual result |
|---|---|
| Repository-root `python -m pytest -q` | **1707 passed, 11 skipped in 205.87s (0:03:25)**. Skips remain prerequisite/platform limits. |
| `npm run compile` | **`> tsc -p .`, exit 0, 0 errors**. |
| `npm test` | **177 tests, 177 pass, 0 fail, 0 skipped**. Includes existing real-service B→C/D/E and C++ recording regressions. |
| Focused `ui.test.ts` additions | **8 passing tests**: `overflow partition`, `overflow DOM state`, `overflow keyboard`, `scoped trace bindings`, `theme color guard`, `graph keyboard access`, `view empty/errors`, `trace empty states`. |
| Existing HTML/security and source tests | Six playback controls and accessible overflow asserted; CSP/message validation retained. Manifest counts updated to 41 commands; source and invalid-trace UI assertions now require explanations without raw codes. |
| Function sizes; whitespace; scope | Changed production files have maximum function length 34 lines (below the 50-line hard limit); `git diff --check` passes. Initial file hashes confirm no changes outside `vscode/` and this document. |

The script tests execute the shipped Call View JavaScript in a minimal DOM with
controlled widths and events. The CSS guard checks all four stylesheets with an
empty semantic-color allowlist. These tests do not measure browser geometry,
contrast ratios, screen-reader output or native keyboard dispatch. The first
Node pass exposed old command-count/raw-error assertions and a shared scrolling
style regression; those were corrected before the passing full run.

**Native screenshots at narrow/wide widths, light/dark themes, both high-contrast
themes, keyboard/screen-reader operation and Windows display scaling are still
pending the G16 Extension Development Host run.** No new screenshots were
captured, and prior scrolling-toolbar screenshots do not qualify this overflow
menu. Retained logs are in the system-temp worker report directory under
`it23/` (`pytest.log`, `tsc.log`, `node.log`); no raw logs entered the repository.
No real LLM provider, CLI agent or network service was invoked. The complete
`verify.bash` remains excluded because it invokes real providers.

## G16 — Real Extension Development Host tests (reverified in iteration 26, 2026-09-28)

The requested G16 host-test slice is delivered in `vscode/src/test/integration/`.
`npm run test:integration` compiles and launches **VS Code 1.96.4** using
**`@vscode/test-electron` 2.5.2**, both pinned. This VS Code version satisfies
`engines.vscode: ^1.74.0`; execution on the minimum 1.74 version is not claimed.
`npm test` remains the separate Node suite, and Python pytest never launches
the new host suite. The downloaded `.vscode-test/` cache is ignored.

Iteration 25 supplied no worker verification report, so its claimed results are
superseded by the iteration 26 execution below. The launcher now passes the
downloaded executable directly to test-electron, with no generated shell
launcher or crash-wrapper setting. `run.ts` defines the version once and passes
it as `ICODA_TEST_VSCODE_VERSION` through `extensionTestsEnv`; `suite.ts` compares
the actual host version against that value. Protocol v1, shared Python stepping
and G08–G15 extension behavior are unchanged.

The launcher copies `src/test/fixtures/python/` into system temp and gives each
host its own profile, extension directory and logs. The extension starts its
real Python service with `icoda.pythonPath` set to `ICODA_TEST_PYTHON`, retaining
the prepared venv interpreter path rather than resolving its symlink. Fixture
state and source stay in temp; no repository fixture is modified. Updates,
experiments and telemetry are disabled. No provider or CLI agent is invoked.

The suite uses registered Open Project, Analyse Project, Show Call View and
trace commands. Activation exports inspection/UI hooks **only in
`ExtensionMode.Test`**: snapshots of the actual project tree/model and Call View,
the existing validated webview-message dispatcher, and a trace-file choice in
place of the native picker. That choice still passes through the existing
project-path check and trace loader. There is no substitute backend or stepping
algorithm in TypeScript. The source assertions focus the already-revealed second
editor group before inspecting `activeTextEditor`; they do not open the expected
document themselves or change ICODA's deliberate graph-focus preservation.

| Host check | Actual result |
|---|---|
| Activation/commands | ICODA activates, all 41 contributed commands are registered, and Python has not started merely from activation. |
| Open/analyse/tree (Python AT01) | Fresh real model: 7 functions across `main.py` and `library.py`, 5 call edges; the registered Project tree displays the matching entity/edge counts. The top-level `RuntimeError` sentinel is not executed. |
| Call View/source/trace | Native webview tab opens with six reachable functions; selecting B reveals `main.py:14`; the existing `calls.tsv` loads six recorded calls. |
| AT05, three independent cases | Reset and Into through main/A/B, then **Into → C:18 (cursor 4), Over → D:23 (5), Out → E:27 (6)**. Python selection, graph selection and active editor file/line agree; root and viewport remain unchanged. |
| AT09 | Reset clears selection/caller counts at cursor 0; graph seek selects D at 5, Previous selects C at 4 with editor sync, and Reset then Into selects main at 1. |
| No workspace | A second fresh host activates with no folders; Open Project/Analyse Project/Show Output complete without starting Python, creating a project or crashing. The tree explains the missing folder. |
| Native screenshots | Four 2560×1440 PNGs: `call-view-{dark,light}-{wide,narrow}.png`. Full-screen host, editor splits 75%/28%, 100% graph zoom, native root-window capture. All four images were inspected: six toolbar controls are visible in the wide view, the narrow view has the overflow control, and selected main/source line 4 agree. The fixed 100% viewport shows only part of the graph at narrow width; this is not a fit-to-panel or overflow-menu interaction check. |

The launcher reports `DISPLAY`, `WAYLAND_DISPLAY` and `XDG_SESSION_TYPE` from its
own environment before deciding whether a display exists; when both display
variables are absent on Linux it uses installed `xvfb-run` or fails with an
explicit prerequisite message. This run used **Ubuntu 24.04.4 LTS x86_64,
Linux 7.0.0-31-generic, X11 (`DISPLAY=:10.0`, `XDG_SESSION_TYPE=x11`,
`WAYLAND_DISPLAY` unset)**, Node **24.21.0**, npm **11.19.0**, and the prepared
Python **3.12.3** venv. Xvfb fallback was not needed or qualified. The test-electron
launcher supplies `--no-sandbox` and `--disable-gpu-sandbox`; this run also used
`--disable-gpu`. VS Code was launched directly without the removed shell wrapper.

Reproduction, starting at the repository root with prepared dependencies:

```bash
export PATH="$HOME/.local/share/nodejs/v24.21.0/bin:$PATH"
# Set these to existing prepared locations; retain the venv interpreter symlink.
export ICODA_TEST_PYTHON AILOOP_TEST_SITE_PACKAGES
# Python is the absolute venv/bin/python path; the other variable supplies the
# sibling AI-Loop suite's prepared site-packages for the repository-root run.
export ICODA_TEST_REPORT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/icoda-g16-XXXXXX")"
printf 'DISPLAY=%s\nWAYLAND_DISPLAY=%s\nXDG_SESSION_TYPE=%s\n' \
  "${DISPLAY-}" "${WAYLAND_DISPLAY-}" "${XDG_SESSION_TYPE-}"
uname -srmo
PATH="$(dirname "$ICODA_TEST_PYTHON"):$PATH" PYTHONPATH="$AILOOP_TEST_SITE_PACKAGES" \
  python -m pytest -q > "$ICODA_TEST_REPORT_DIR/pytest.log" 2>&1
cd icoda/vscode
npm run compile > "$ICODA_TEST_REPORT_DIR/compile.log" 2>&1
npm test > "$ICODA_TEST_REPORT_DIR/npm-test.log" 2>&1
npm run test:integration > "$ICODA_TEST_REPORT_DIR/integration.log" 2>&1
```

| Required verification | Actual result, exit 0 |
|---|---|
| Repository-root `python -m pytest -q` | **1708 passed, 11 skipped in 208.37s (0:03:28)**. Existing prerequisite/platform skips remain skips. |
| `npm run compile` | **`tsc -p .`, exit 0, 0 errors**. |
| `npm test` | **177 tests, 177 pass, 0 fail, 0 skipped**. |
| `npm run test:integration` — workspace mode | **8 passed, 0 failed; VS Code 1.96.4; X11**, host exit 0. |
| `npm run test:integration` — empty mode | **1 passed, 0 failed; VS Code 1.96.4; X11**, host exit 0. |
| Integration aggregate | **9 passed, 0 failed; VS Code 1.96.4; X11**, command exit 0. |

Retained final host artifacts are under the system-temp report directory above,
in **`icoda-integration-*/`**: screenshots, `environment.json`,
`workspace-results.json`, `empty-results.json`, fixture state and isolated host
logs/profiles. The parent retains `pytest.log`, `compile.log`, `npm-test.log`
and `integration.log`. All four requested commands passed on the first repair
run; no extension defect or further test correction was required. The existing
cached VS Code binary was reused. Host logs retain VS Code API-proposal warnings,
a lock-registration message and a built-in authentication timeout; neither host
reported an ICODA test failure. No authentication workflow is qualified here.

**Untrusted workspace pending:** neither mode enables Workspace Trust and leaves
the fixture untrusted. The profiles set `security.workspace.trust.enabled` to
false and test-electron also adds `--disable-workspace-trust`. No claim is made
that these host tests verify untrusted activation or prevent builds/providers
in an untrusted workspace; the empty-window check is separate evidence.

**Other pending qualification:** Windows/macOS, Windows display
scaling, high contrast, native keyboard/overflow-menu interaction, screen readers,
minimum-version execution, and VSIX installation. The screenshots are native
visual evidence, not full G15 accessibility qualification. This fixture suite
does not replace the remaining C++/large-project/workflow host acceptance cases.
The full `verify.bash` was excluded because it invokes real providers. No real
provider or CLI agent was invoked. Prepared npm dependencies were reused;
the only permitted network operation was test-electron's VS Code binary download.

Starting HEAD was `fde592e3636dd19c9e84c51ffb43337d395fc717`, with preceding
migration changes present. File hashes confirm that only
`vscode/src/test/integration/run.ts`, `vscode/src/test/integration/suite.ts` and
this document changed in iteration 26. Root `AGENTS.md` and this document were
reread before finalization; no ICODA-local instruction file exists, and other
referenced guidance retained its starting modification times. The longest
functions in the two changed TypeScript files are 19 and 20 lines respectively,
within the 30-line guideline; whitespace checks pass. No commit or merge was made.

## G17 — Installable VSIX (iteration 28 repair, 2026-09-28)

The requested packaging task is delivered and tested on **Linux only**. The VSIX
contains its own headless Python backend and works outside the development
checkout. It does not bundle a Python interpreter, install tools during activation,
change protocol v1, or change shared stepping and G08–G16 behavior. The standalone
application and unrelated pre-existing working-tree modifications were preserved.
Starting HEAD remains `fde592e3636dd19c9e84c51ffb43337d395fc717`; no commit, merge or
Marketplace publication was performed.

### Package layout and runtime resolution

`vscode/package.json` pins `@vscode/vsce` **3.6.0** as a devDependency; its npm lock
records the transitive dependencies. `npm run package` compiles TypeScript, runs
`scripts/package.mjs` to recreate ignored `backend/`, and invokes the local
`vsce package --no-dependencies --allow-missing-repository --out dist` command.
The local publisher identifier is `icoda` (extension ID `icoda.icoda`); it is
package metadata, not a Marketplace claim. Staging is cleared before copying and
removed in `finally` after packaging, including on failure. The licence is staged
from the repository's MIT licence. A fixed ZIP epoch (1980-01-01), or explicitly supplied
`SOURCE_DATE_EPOCH`, fixes entry ordering/timestamps for reproducible archives.

The `.vscodeignore` allowlist includes only compiled `out/*.js`, `media/`,
`backend/icoda_core/*.py`, the three core JSON resources (`providers.json`,
`response.schema.json`, `specification.schema.json`), dependency constraints,
licence, README and package metadata. It excludes `src/`, `out/test/`, tests,
fixtures, source maps, `.vscode-test/`, every `node_modules/` dependency, staging
scripts, Python bytecode and caches. There are no runtime npm dependencies.
Generated Python copies and VSIX files are ignored, never versioned. Removing
staging also prevents subsequent root pytest discovery from collecting a duplicate
of the production module `icoda_core/test_selection.py`. The old `.backend/` was
the iteration 27 staging target, not an unrelated copy; it has been removed and
is no longer produced or resolved.

`resolveBackend(extensionUri.fsPath)` first checks the installed
`backend/icoda_core/service.py`, then the development parent directory's
`icoda_core/service.py`, and otherwise reports an installation error. The four
existing Node resolution tests cover precedence, development fallback, installation without
a sibling checkout, and absent/non-file entry points. Two new tests execute the
packaging script against a temporary checkout and controlled vsce executable:
they verify fresh staging without removed Python files, cleanup on success and
failure, and live-parent backend resolution after both outcomes. `icoda.pythonPath`
remains the only interpreter override; the existing empty-setting fallback (backend-local
`.icoda-venv`, then PATH Python) is unchanged. `BackendClient` still launches an
argument array with the resolved backend as cwd. Output records the chosen root
and interpreter. After `npm run package` finishes, F5 development resolves the
live parent `icoda/` sources; installed extensions retain their bundled backend.

### User and developer instructions

The bundled [extension README](../vscode/README.md) covers installation, runtime
setup, first-project flow, recording/stepping, troubleshooting and developer
start/test/debug commands. Install `vscode/dist/icoda-0.1.0.vsix` using
**Extensions: Install from VSIX...** or `code --install-extension` with that file.
Prepare a Python interpreter and set `icoda.pythonPath` to its venv executable,
keeping its symlink path. The core requires Python 3.10+; this run used **3.12.3**
with **clang 21.1.7, networkx 3.6.1, jsonschema 4.26.0**. These qualification pins
need Python 3.11+ due to networkx. `backend/constraints.txt` is included for
explicit dependency installation; activation never runs pip. Bindings are needed
even for Python projects because shared modules import them. C++ additionally
needs compatible native libclang and `compile_commands.json`; build/recording
needs CMake, Ninja, Clang, symbolization tools and project dependencies (CMake
3.28+ and `clang-scan-deps` for module projects). Provider CLIs/authentication are
needed only for provider workflows, not ordinary analysis/navigation.

Open/trust a local folder, run **ICODA: Analyse Project**, inspect the Project
tree, and open **Show Call View** to navigate source. Choose the intended root in
multi-folder workspaces. For an executable, Refresh Targets and Select Target,
then Build Target, Run Target or Record Trace. The recording uses the isolated
instrumented tree and offers Load Trace. Playback's six compact controls remain
Load Trace, Previous Call, Step Over, Step Into, Step Out and Reset; B still steps
to C/D/E respectively. Show Output and Show Toolchain explain backend/tool paths;
Restart Backend applies interpreter changes. Missing source and provider failures
retain separate diagnostics. The README provides the details and limitations.

Reproduce from the repository root with Node.js 22+ (tested **24.21.0**, npm
**11.19.0**) and already prepared Python/test dependencies:

```bash
# Set these to prepared environments; retain the Python venv symlink path.
export ICODA_TEST_PYTHON AILOOP_TEST_SITE_PACKAGES
export ICODA_TEST_REPORT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/icoda-g17-XXXXXX")"
PATH="$(dirname "$ICODA_TEST_PYTHON"):$PATH" PYTHONPATH="$AILOOP_TEST_SITE_PACKAGES" \
  python -m pytest -q
cd icoda/vscode
npm ci
npm run compile
npm test
npm run test:integration
npm run package
sha256sum dist/icoda-0.1.0.vsix
npm run package
sha256sum dist/icoda-0.1.0.vsix
unzip -l dist/icoda-0.1.0.vsix
node -e 'require("./out/pythonRuntime").resolveBackend(process.cwd()).then(console.log)'
npm run test:vsix
```

`npm ci` is the lockfile-based setup command for another developer. This repair run
reused all prepared dependencies; no npm or Python installation was needed.
No real provider or CLI agent was invoked. Host tests reused the cached VS Code
binary; test-electron's binary download is needed only when it is absent. Unit
tests stay separate from both host suites; pytest does not launch either suite.
Open `vscode/` as the development workspace, choose **Run ICODA Extension**, and
press F5; `npm run watch` supports incremental builds. The backend can also be
started with `python -m icoda_core.service` from `icoda/` or installed `backend/`
for newline-delimited JSON protocol debugging, with diagnostics on stderr.

### Installed production smoke and verification

`npm run test:vsix` packages first, copies the existing Python fixture to system
temp, installs the archive with `--install-extension` into new `--extensions-dir`
and `--user-data-dir` directories, and launches pinned VS Code **1.96.4** using
test-electron **2.5.2** helpers. The only `--extensionDevelopmentPath` names a
minimal temporary test harness. No development path points at the checkout or at
ICODA; the ICODA extension is loaded from the installed archive in **production
mode**, confirmed by its undefined activation exports. `PYTHONPATH` is cleared
for this host. The interpreter is still the explicitly configured prepared venv.

The smoke observes real installed ProjectTree updates and CallViewPanel state,
forwarding every intercepted method to the original implementation and restoring
the methods afterward. It does not supply fake models or patch the shipped VSIX.
Assertions cover all 41 commands, fresh analysis/tree with seven entities, a
visible Call View tab with the six expected functions/five edges, packaged JSON
resources, and the actual backend package root written to ICODA's output log.
The fixture's top-level RuntimeError sentinel is never executed. This validates
installation and the Python first-project flow, not installed C++ recording or
provider acceptance.

Environment: **Ubuntu 24.04.4 LTS x86_64, Linux 7.0.0-31-generic, native X11**;
VS Code **1.96.4**, Node **24.21.0**, npm **11.19.0**, Python **3.12.3**. The helper
uses `--no-sandbox` / `--disable-gpu-sandbox`, and the runner adds `--disable-gpu`.
Workspace Trust is disabled in test profiles; no untrusted-workspace claim is
made. The fresh installed profile is not the user's ordinary VS Code profile.

| Check | Actual result, exit 0 |
|---|---|
| Repository-root `python -m pytest -q` | **1708 passed, 11 skipped in 207.44s (0:03:27)**. Existing prerequisite/platform skips remain skips. |
| `npm run compile` | **`tsc -p .`, exit 0, 0 errors**. |
| `npm test` | **183 tests, 183 pass, 0 fail, 0 skipped**. |
| `npm run test:integration` | **workspace 8 passed / 0 failed; empty 1 passed / 0 failed; aggregate 9 passed / 0 failed**, VS Code 1.96.4, X11. |
| `npm run package` | **`icoda-0.1.0.vsix`, 112 files, 301505 bytes (294.44 KiB)**. |
| ZIP content check | **49 Python modules, 3 core JSON resources, 45 compiled JavaScript modules, 9 media files**, plus README/package metadata/constraints/licence/VSIX metadata. Every packaged core source/resource matches the checkout; all exclusion checks above pass. |
| Reproducibility | Two successive builds are byte-identical: SHA-256 **`c24d099d01d1d0d67b018dd3991bee23cd66f0baccf80ff26321388e7b5c1de2`**. |
| `npm run test:vsix` | **4 passed, 0 failed; VS Code 1.96.4; X11**. Installed backend: `<fresh extensions dir>/icoda.icoda-0.1.0/backend`. |
| Post-package development resolution | After both builds and the installed-smoke rebuild, `resolveBackend(<checkout>/icoda/vscode)` returns the live parent `<checkout>/icoda/`. Neither `backend/` nor `.backend/` remains in the checkout. |

Retained evidence is in the system-temp worker report directory's `g17-repair/`:
`compile.log`, `npm-test.log`, `pytest.log`, `integration.log`, `package-1.log`,
`package-2.log`, matching `package-1.sha256` / `package-2.sha256`, `vsix.log`,
`vsix-contents.log` (`unzip -l`), `contents.json`, `dev-layout.log`, and
`icoda-integration-*/`. The development-host subdirectory contains per-mode
results and four native light/dark wide/narrow
screenshots. The installed-run subdirectory contains `install.log`, `launch.json`,
`environment.json`, `vsix-results.json`, the fixture, fresh profiles/extensions
and native ICODA logs. The development-host run is `icoda-integration-GvqQr5`;
the final installed run is `icoda-integration-6frBpV`. The smoke rebuild has the same SHA-256 as both
preceding builds; installed backend resources match the archive. Raw logs,
screenshots, staged sources and VSIX archives stay outside version control.

The repair replaces iteration 27's hidden staging workaround with one authoritative
`backend/` layout and guaranteed cleanup on normal success/error completion. The
resolution regressions failed before the fix and pass afterward. No protocol,
trace stepping, G08–G16 behavior or unrelated open nits were changed.

**Pending/skipped:** Windows and macOS installation have not run; Linux is the
only tested platform. Installed C++ recording/provider workflows, high contrast,
display scaling, native keyboard/overflow interaction, screen readers,
untrusted-workspace qualification, minimum-version execution and remote/browser
modes remain unqualified. The complete `verify.bash` was skipped because it
invokes real providers, prohibited for this task. G18 full parity reconciliation
remains separate from this G17 package delivery.

## Milestone status

**M1 is the first usable extension milestone**: actual analysis, Call View,
native source navigation and recorded B→C/D/E playback run in Linux VS Code.
**M5 is full migration completion in the brief, and remains Partial.**
Reconciliation is complete; completing a ledger does not complete the migration.
Outstanding work remains in scope unless the user agrees to defer it.

| Milestone | Delivered work and evidence | Remaining acceptance / implementation |
|---|---|---|
| M0 / G01, G03 design | Baseline, 22 desktop features, versioned headless boundary; baseline report and `tests/test_service.py::test_protocol_errors_recover_and_cancel_is_honest`. | None for baseline/design. |
| M1 / G02–G08 | Real analysis/source/playback: `integration/suite.ts` AT01 and AT03–AT09. P02 candidate markings and P05 automatic refresh are delivered; P04 adds shared filters/neighborhoods. | Windows tool discovery and P07 chooser remain Not qualified; P04's remaining desktop expansion/color/context policies need separate shared contracts. These do not erase the delivered Linux M1 journey. |
| M2 / G09 | Real selected-target build/run/record (native AT11); Whole Project build and full tests (native `P06 Whole Project build and full CTest failure cancellation and recovery preserve target and build artifacts`). | P06 targeted tests need runner-specific selectors; automatic analysis after build/refresh needs coordinated model publication/cancellation. Explicit Analyse Project remains available. |
| M3 / G10–G11 | Four diagrams and Issues/Coverage; P01 file assignment/saved hierarchy/cameras, P03 Mind Map history, P04 filtering. Native P01/P03/P04 cases and `test_evidence_core_agreement_navigation_and_read_only` cover the shared results. | P04 remaining graph policies need a common expansion and appearance contract; native evidence-tree visual qualification and VVE require retained UI/project runs. |
| M4 / G12–G13 | Specification/profile/phase/skeleton orchestration (P08), provider/custom model selection (P09), opt-in background purpose proposals (P10), queue/review/recovery/diffs/Git; native P02/P08/P09/P10 and service review tests. | P09 queue target override needs native controls/validation. P10 per-entity retries and retained-purpose recovery need bounded retry and persisted review evidence. Real-provider/authentication AT13 remains Not qualified; only controlled providers ran. |
| M5 / G14–G18 | Lifecycle/cancellation, P11 diagram persistence and stale-cache detection; real host regression modes and fresh installed VSIX smoke; current results below. Historical measured performance budgets remain in G14b. | Desktop/service writer coordination and complete offline cache invalidation remain P11 work; platform/accessibility/provider and complete installed journeys remain Not qualified. No unconditional full-migration claim. |

### Goal reconciliation G01–G18 (iteration 59)

Every goal has a disposition and verifiable evidence. **Delivered** is bounded by
the stated tested scope; **Partial** lists the remaining implementation or
qualification; **Not qualified** identifies a required journey that was not run.
Node files below are under `vscode/src/test/`; native cases are in
`vscode/src/test/integration/suite.ts` unless another path is named.

| Goal | Status | Evidence and remaining disposition |
|---|---|---|
| G01 | **Delivered** | Baseline/desktop inventory above; starting HEAD and preserved modifications in `head.txt`, `status-before.txt` and `hashes-before.json` under the report root below. Current guidance hashes are `guidance.json`. |
| G02 | **Delivered** | Native `activation and all registered ICODA commands` and `no-workspace activation and commands are safe`; `backendClient.test.ts` — `manifest activation and compiled entry agree with project commands`. |
| G03 | **Delivered** | `tests/test_service.py::test_protocol_errors_recover_and_cancel_is_honest`, `test_trace_b_to_c_d_e_and_synchronized_state`; `backendClient.test.ts` — `stderr diagnostics do not corrupt protocol responses`, `killing the backend rejects every pending request`, `protocol-version mismatch rejects the handshake with structured details`. |
| G04 | **Partial** | `toolchain.test.ts` — `output includes effective Python, every path/source, errors and only returned environment additions`; `tests/test_service.py::test_operations_honor_cached_tools_and_explicit_overrides`; native AT11 uses Linux tools. AT10/Windows and macOS require their hosts; P07 remains **Not qualified**, with native libclang chooser deferred because its selection UI/configuration is not implemented. |
| G05 | **Delivered** | Native `real Python analysis and populated project tree (AT01)` and AT11 C++ analysis; `test_targets_use_real_discovery_without_building_and_have_stable_ids`, `test_target_selection_projects_dependencies_and_preserves_whole_model`, `test_analysis_failure_retains_stale_model_and_diagnostics`, and new `test_p11_reopen_unchanged_analysis_keeps_raw_byte_hash_fresh` in `tests/test_service.py`. Complete offline invalidation is separately limited under P11/G14. |
| G06 | **Delivered** | Native AT03/AT04 and `P05 saved and external source changes refresh analysis without overwriting dirty editors`; `test_p05_automatic_analysis_preserves_pending_review` and `test_p02_candidate_call_graph_and_source_use_checked_core_delta` in `tests/test_service.py`. P02/P05 close the former candidate-source/automatic-refresh deferrals. |
| G07 | **Delivered** | `tests/test_service.py::test_service_and_desktop_call_the_same_layout_function`, `test_trace_view_includes_recorded_nodes_without_rerooting_or_changing_static_view`; native `P02 proposal command shows core delta and candidate source while retaining project playback` and `P04 shared graph filters and neighborhoods preserve native source playback and cameras`. Remaining broader desktop graph policies are explicitly Partial in P04. |
| G08 | **Delivered** | `test_trace_b_to_c_d_e_and_synchronized_state`, `test_trace_metadata_and_repeat_edges_share_the_group_cursor`, `test_service_disables_depth_steps_when_the_parent_return_is_missing` in `tests/test_service.py`; native AT05–AT09 now cover leaf/repeat/recursion/unresolved/thread/invalid-trace journeys. Shared Python stepping and the compact six-control toolbar are unchanged. |
| G09 | **Partial** | `tests/test_service.py::test_at11_real_service_records_loads_and_steps_without_touching_ordinary_tree`; native AT11 and P06 Whole Project/full-test checks. Whole Project build/full tests and native recording are delivered. Targeted tests and post-build automatic analysis remain deferred for the selector/publication reasons in P06; Windows recording is unqualified. |
| G10 | **Partial** | `tests/test_service.py::test_file_overview_expansion_reveal_and_relationship_counts`, `test_p01_saved_parent_drill_in_and_reveal_keep_bounded_children`; native `P01 File View assignment command, saved parents, source and cameras survive reopen and restart`. Assignment and camera persistence are delivered. AT02 VVE remains **Not qualified** because no suitable checkout/toolchain run was retained. |
| G11 | **Partial** | `test_class_view_real_cpp_python_agrees_with_core_and_desktop`, `test_mindmap_shared_core_desktop_and_persisted_expansion`, `test_evidence_core_agreement_navigation_and_read_only` in `tests/test_service.py`; native `P03 Mind Map opens introducing history and source with session guards`. Direct provenance/history navigation is delivered. Native Issues/Coverage tree visual acceptance still needs a retained UI journey. |
| G12 | **Partial** | Native P08 specification-save, P09 provider-picker and P10 idle-purpose cases; `tests/test_service.py::test_p09_provider_custom_selection_persists_and_invokes_shared_core`, `test_p10_purpose_status_ready_active_cancelled_and_pending_candidate`. Custom provider/model and opt-in idle scheduling are delivered. Queue target override and per-entity retry/retained-purpose recovery remain deferred for the P09/P10 reasons; real-provider/authentication acceptance is **Not qualified** because no real provider is authorized. |
| G13 | **Partial** | `tests/test_service.py::test_review_failed_gate_cannot_approve`, `test_review_rejects_changed_evidence`, `test_review_approve_commit_history_and_undo`, `test_recovery_failed_gate_and_unsaved_evidence_still_block_approval`; native P02 candidate diff/dirty-buffer/refusal and P11 safe recovery. Full real-provider AT13 decision journey remains **Not qualified**; controlled cases do not establish it. |
| G14 | **Partial** | Native AT12/AT14 and `P11 restart restores diagrams and reports retained work with safe recovery`; `tests/test_service.py::test_project_lock_excludes_second_service_and_releases_on_close`; `viewState.test.ts` disposal/switch checks. P11 restores diagram cameras/controls. Cross-frontend exclusion needs desktop lifecycle ownership; retained review snapshots and offline new-file/compiler/dependency invalidation need additional evidence. G14b measurements/budgets are historical and were not rerun. |
| G15 | **Partial** | Native `native light/dark Call View screenshots at wide/narrow widths`; `ui.test.ts` — `overflow keyboard`, `scoped trace bindings`, `theme color guard`, `graph keyboard access`. AT15 remains **Not qualified** for native overflow/shortcut completion, screen readers, high contrast and Windows scaling: those display/accessibility runs are absent. |
| G16 | **Delivered** | This run's full Python/Node, workspace/empty/C++/untrusted EDH and installed VSIX gates are recorded below with retained logs/results; `tests/test_service.py::test_at11_real_service_records_loads_and_steps_without_touching_ordinary_tree` supplies real recording evidence. No test weakened or manually skipped. Real-provider and standalone real-Tk release qualification are separate, unexecuted gates. |
| G17 | **Partial** | Fresh profile `integration/vsixSuite.ts` — `installed production activation and commands`, `installed Analyse Project and real populated tree`, `installed Call View with real Python graph`, `backend and resources resolve inside installed extension`, all rerun from this run's package. AT16's full source/trace/C++/provider journey remains **Not qualified** because the installed smoke covers only the named subset; Windows installation requires that host. |
| G18 | **Partial** | This reconciled 22-feature/G01–G18/AT01–AT16 ledger, `ledger-audit.json`, and `pytest.log` account for every item (paths under the report root below). Reconciliation is finished; full migration remains incomplete while P04/P06/P07/P09/P10/P11 and named qualifications remain. They have explicit reasons and are not user-agreed scope reductions. |

Goal tally: **8 Delivered, 10 Partial, 0 Not qualified (18 goals)**; the hardware/provider
subjourneys remain explicitly Not qualified within their Partial goals.

### Acceptance ledger AT01–AT16

**Delivered** means the required Linux fixture journey has recorded evidence.
**Partial** means a narrower tested portion exists. **Not qualified** means the
named required host/provider/UI journey has not run, even when narrower automated
evidence passes. All existing native test cases cited below were rerun in iteration
59; the current result files and screenshots are indexed in the final verification
section. Older artifact paths retain provenance, not current pass totals.

| Case | Status | Fixture, procedure, actual evidence and remaining work |
|---|---|---|
| AT01 — C++ and Python analysis | **Delivered** | Python sentinel fixture `vscode/src/test/fixtures/python`: `integration/suite.ts` case `real Python analysis and populated project tree (AT01)`, seven entities/five call edges without execution. Native `AT11 records the selected executable in isolation and steps real calls in the graph and editor` analyses the real `vscode/src/test/fixtures/cpp` fixture; `tests/test_service.py::test_class_view_real_cpp_python_agrees_with_core_and_desktop` checks both languages against the core. |
| AT02 — large-project overview | **Not qualified** | `tests/test_service.py::test_file_overview_expansion_reveal_and_relationship_counts` and `fileView.test.ts` cover the 81-file overview/expansion/reveal fixture. Historical It12 cached-model captures record only that narrower journey; they do not qualify a ViennaVulkanEngine large-project run for this review. A suitable VVE checkout/toolchain and a retained fresh analysis/overview/navigation run are still required. |
| AT03 — moved source | **Delivered** | Iteration 42, Linux X11, Node 24.21.0 / VS Code 1.96.4: `npm run test:integration`, `vscode/src/test/integration/suite.ts` test `AT03 moved source opens the relocated file and line through Go to Entity and Call View` passes. After real analysis, moves `main.py` to `relocated/main.py` in the runner's temporary copy of `vscode/src/test/fixtures/python/`; registered `icoda.revealEntity` and Call View selection both use real Python `source.resolve`. Asserts relocated service path, native active editor URI/line (B:14, C:18), retained entity selection in the panel graph and no warnings, file-choice or workflow requests. Only QuickPick answers are stubbed; committed fixtures and shared lookup remain unchanged. Evidence: `/tmp/ai-loop-worker-reports/J20260927-170326-588902/iteration42/integration.log`, `icoda-integration-Z8ZfqH/workspace-results.json` and `at03-moved.json` in that integration directory. |
| AT04 — ambiguous/missing source | **Delivered** | Iteration 42 native Linux VS Code 1.96.4 `npm run test:integration`: `vscode/src/test/integration/suite.ts` tests `AT04 ambiguous basenames offer a file choice and revalidate the selected source`; `AT04 missing source reports source_missing locally and keeps the editor and graph usable`; `AT04 outside-root matches and escaping symlinks are excluded`; `AT04 source navigation preserves a different file's unsaved editor buffer` all pass. Mutations stay in the runner's temporary Python fixture copy/sibling. Go to Entity and Call View exercise real `source.resolve`; only QuickPick answers are stubbed, choosing each tied basename with service revalidation. Assertions cover actual `source_ambiguous`/`source_missing` codes, messages and source details, native local warnings, active editor URI/line, panel selection, exclusion of an outside sibling and escaping symlink, retained dirty `library.py` text/disk bytes and usable navigation after source restoration. Pass-through request observations and native tab/terminal events verify no provider/Binary recovery activity or Prompt/recovery view. Evidence: iteration-42 `integration.log` and `icoda-integration-Z8ZfqH/{workspace-results,at04-ambiguous,at04-missing,at04-boundary,at04-dirty-buffer}.json` under the job report directory named in AT03. |
| AT05 — B→C/D/E | **Delivered** | Independent `integration/suite.ts` cases `AT05 B → C via Step Into, graph and active editor agree`, `AT05 B → D via Step Over, graph and active editor agree` and `AT05 B → E via Step Out, graph and active editor agree` use `calls.tsv`, registered trace commands and the real backend; graph and native editor agree at C:18, D:23, E:27, with unchanged root/viewport. It9 also exercised actual buttons (`it9-ui-evidence.json`). |
| AT06 — leaf/repeat/recursive/unresolved | **Delivered** | Iteration 41, Linux X11, Node 24.21.0 / VS Code 1.96.4: `npm run test:integration`, real Python service through Call View `loadTrace(path)` and registered trace commands. `vscode/src/test/integration/suite.ts`: `AT06 leaf Into skips returns and selects the next eligible call`; `AT06 repeats preserve counts and caller edges through Over, Into, Out, Previous and Reset`; `AT06 recursion uses the selected invocation's return`; `AT06 unresolved calls are skipped while their stack scopes remain usable` all pass. Fixtures in `vscode/src/test/fixtures/python/`: `calls.tsv`, `repeats.tsv`, `recursion.tsv`, `unresolved.tsv`, `unresolved-only.tsv`. Assertions cover native active editor URI/line, graph selection, grouped positions, repeat/caller counts and edge annotations, invocation metadata and all backend availability flags. No TypeScript stepping or core changes. Evidence: `/tmp/ai-loop-worker-reports/J20260927-170326-588902/iteration41/integration.log` and `icoda-integration-Mh969b/workspace-results.json` under that directory. |
| AT07 — interleaved threads | **Delivered** | Iteration 41 native Linux VS Code 1.96.4 `npm run test:integration`: `vscode/src/test/integration/suite.ts` test `AT07 interleaved threads keep Into global and Over/Out on the selected thread` passes using `vscode/src/test/fixtures/python/interleaved.tsv` through Call View `loadTrace(path)` and the real service. Independent commands from thread-1 B select thread-2 C via Into, thread-1 D via Over, and thread-1 E via Out; further Into steps cross back to thread-1 in global order. Native active editor URI/line, graph selection, grouped position, thread identity, repeat/caller counts and every backend availability flag are asserted. Shared Python stepping remains authoritative. Evidence: iteration-41 `integration.log` and `icoda-integration-Mh969b/workspace-results.json` in the system-temp job report directory named in AT06. |
| AT08 — invalid/incomplete/exhausted trace | **Delivered** | Iteration 41 native Linux VS Code 1.96.4 `npm run test:integration`: `vscode/src/test/integration/suite.ts` tests `AT08 empty trace disables playback and valid reload recovers`; `AT08 malformed trace reports invalid_trace without losing selection and reload recovers`; `AT08 truncated trace cannot invent scope exits and valid reload recovers`; `AT08 exhaustion retains selection, disables forward actions and reload recovers` all pass. `empty.tsv`, `malformed.tsv`, `truncated.tsv` and `calls.tsv` in `vscode/src/test/fixtures/python/` load through the real Call View path. Checks assert the typed `invalid_trace` explanation rendered in the panel, retained source/graph after a failed load, empty-state counters/flags, disabled Over/Out when a parent return is missing, no invented exits, retained exhausted selection, Previous/Reset and valid reload recovery. Native active editor URI/line, graph selection, repeat/caller counts and all backend flags are checked. Evidence: iteration-41 `integration.log` and `icoda-integration-Mh969b/workspace-results.json` in the system-temp job report directory named in AT06. |
| AT09 — Previous/Reset/seek | **Delivered** | `integration/suite.ts` — `AT09 seek, Previous Call and Reset share the Python cursor` checks shared cursor, native editor, graph seek D→Previous C, cleared Reset selection/counts and Into main. Service repeat-edge/counter regression and It9 actual-control evidence cover annotations. |
| AT10 — Windows outside developer PATH | **Not qualified** | No Windows host run. `tests/test_windows_startup.py` supplies simulated Visual Studio discovery/environment evidence only. Follow-up: launch Windows VS Code from an ordinary desktop session and record bundled-tool build/analysis. |
| AT11 — real executable recording | **Delivered** | Iteration 43, Linux X11, Node 24.21.0 / VS Code 1.96.4: `npm run test:integration`, `vscode/src/test/integration/suite.ts` test `AT11 records the selected executable in isolation and steps real calls in the graph and editor` passes on a temporary copy of `vscode/src/test/fixtures/cpp/` (`demo`, main → A → B → C, A → D, main → E). Shared Python discovery/configuration prepares the ordinary CMake tree; registered Open, Analyse, Refresh Targets, Select Target, Build, Run and Record commands use the real service. The recording offer loads Call View; the produced trace is also reloaded through the shared helper. Six calls resolve; selected target ID, recording path, executable in trace events and panel title agree. Into B → C:3, Over B → D:5 and Out B → E:7 assert graph selection, active `main.cpp` editor URI/line, cursor, caller counts and availability. SHA-256 and nanosecond mtimes of ordinary `CMakeCache.txt`, `compile_commands.json` and `demo` stay identical; recording uses `.icoda/cache/instrumented-debug-build`. Actual discovered tools: CMake 3.31.8, Ubuntu Clang 18.1.3, Ninja 1.11.1, LLVM 18 symbolizer; Python 3.12.3 venv. Missing required tools produce named prerequisite skips, excluded from pass/failure totals; no installs. Current host totals are in the iteration-59 verification section. Evidence: `/tmp/ai-loop-worker-reports/J20260927-170326-588902/iteration43/integration-rerun.log` and `icoda-integration-QYD79o/{cpp-results,at11-recording}.json`, `at11-configure.log` under that report directory. No shared-core defect or production change was needed. |
| AT12 — switch during slow work | **Delivered** | Iteration 44, Linux X11, Node 24.21.0 / VS Code 1.96.4: `npm run test:integration`, `vscode/src/test/integration/suite.ts` tests `AT12 target switch supersedes slow analysis without publishing old model graph or trace` and `AT12 progress cancellation sends operation.cancel and leaves analysis usable` pass. Registered Analyse Project and Select Target commands use the real Python service on the runner's temporary Python fixture copy. G14's existing file-gated analysis wrapper and service-shim writer are shared through `vscode/src/test/slowBackend.ts`; no production delay or cancellation/publication policy is added. With analysis pending, switching from the executable to Whole Project yields `cancelled`, advances only the selection revision, preserves the whole model, clears the old trace and fetches the correctly identified graph. Snapshot observations reject the obsolete source marker and trace; native progress completes. The progress token sends real `operation.cancel`, receives `cancel_requested`, settles the request as `cancelled`, retains revision/model/playback and displays the cancellation notice. Follow-up analysis and `view.get` succeed in both cases. This native case qualifies target switching; project/root variants retain the G14 service/Node evidence. Evidence: `/tmp/ai-loop-worker-reports/J20260927-170326-588902/iteration44/integration-final.log` and `icoda-integration-OHhdYE/{workspace-results,at12-superseded,at12-cancelled}.json` under that directory. Current host totals are in the iteration-59 verification section. |
| AT13 — candidate edit and gated approval | **Not qualified** | Controlled real-worktree/build/test/Git cases `tests/test_service.py::test_review_failed_gate_cannot_approve`, `test_review_rejects_changed_evidence`, `test_review_approve_commit_history_and_undo`, plus native `P02 proposal command shows core delta and candidate source while retaining project playback` and `P11 restart restores diagrams and reports retained work with safe recovery`, cover candidate source, dirty edits, failed approval and recovery. The full real-provider extension review/approval journey has not run: this task prohibits real providers. Controlled native coverage is narrower evidence. |
| AT14 — crash/restart/close/deactivate | **Delivered** | Iteration 44 native Linux VS Code 1.96.4 `npm run test:integration`: `vscode/src/test/integration/suite.ts` tests `AT14 busy backend crash settles requests and Restart Backend restores the project`; `AT14 restart reaps a busy backend and recovers with a fresh process`; `AT14 Call View close and reopen restores playback without accumulating listeners`; `AT14 deactivation settles pending work disposes views and reaps the backend` all pass. Real service analysis is held at the shared G14 file gate in a temporary runtime. SIGKILL produces `backend_exited`, ends native progress, clears project/model/panel and shows the stopped-backend tree message. Registered Restart Backend restores the project/target with a new session/PID and successful analysis/graph retrieval; restarting while busy and invoking the actual exported deactivation settle pending requests as `backend_disposed`. Old backend PIDs return ESRCH, and deactivation removes commands and native Call View tabs. Three native tab close/reopen cycles retain trace ID/cursor/counters/availability, root, viewport and graph; disposed hooks send no request, and each registered step produces exactly one service request with matching native source selection. This exposed and fixed lost playback state on close: `ProjectSession` retains a `CallViewModel` snapshot only for the same session/revision/target; `callViewModel.test.ts` regression `closing and reopening Call View restores playback only in the same session revision and target` failed before the fix and passes afterward. Evidence: iteration-44 `integration-final.log` and `icoda-integration-OHhdYE/{workspace-results,at14-crash,at14-restart,at14-webview,at14-deactivate}.json` under the AT12 report directory. Current host/Node/VSIX totals are in the iteration-59 verification section. These PID/UI results qualify Linux only. |
| AT15 — compact themes and keyboard | **Not qualified** | Native `native light/dark Call View screenshots at wide/narrow widths` rerun with synchronized source; `ui.test.ts` tests `overflow keyboard`, `scoped trace bindings`, `theme color guard` and `graph keyboard access` cover DOM/command behavior. Current native overflow/shortcut interaction, high contrast, screen readers and Windows display scaling need their own retained display/accessibility runs; this Linux light/dark fixture cannot qualify them. |
| AT16 — fresh-profile VSIX | **Not qualified** | This run rebuilds/installs into a fresh temporary profile. `integration/vsixSuite.ts` checks `installed production activation and commands`, `installed Analyse Project and real populated tree`, `installed Call View with real Python graph`, and `backend and resources resolve inside installed extension`. Installed source/trace controls, C++ recording and provider portions of the documented full journey still need acceptance; this smoke is narrower and real providers are prohibited in this task. Current install/results/log paths are in iteration-59 verification. |

AT tally: **11 Delivered, 0 Partial, 5 Not qualified (16 cases)**. Not qualified cases are AT02, AT10, AT13, AT15 and AT16; their passing narrower tests do not close the named qualification gaps.

**Not qualified:** AT02/VVE, AT10/Windows developer-shell-free toolchain discovery,
AT13/real-provider decisions, AT16/full installed provider journey, P07/native
libclang selection and platform discovery,
Windows display scaling, macOS, high contrast (both themes), and a
ViennaVulkanEngine large-project run. These require the named host/display/theme
or project qualification environment; this Linux fixture run cannot establish
them. Screen readers, current native overflow/shortcut interaction, minimum
VS Code 1.74 execution, remote hosts and browser-only mode also remain unqualified.
Historical It12 cached-model evidence is retained, not promoted to full VVE
qualification. Trusted/empty hosts use disabled Workspace Trust and sandbox/GPU
flags. The gap-7 host separately enables trust and verifies Restricted Mode on
Linux VS Code 1.96.4; untrusted workspaces are no longer an untested Linux mode.

**Restricted Mode:** all ICODA views and commands except **Show Output** are
disabled until the workspace is trusted, because starting the Python backend
requires trust. The Project tree can display an inert placeholder, and VS Code's
native source editor remains usable. The service's read-only model/view/source
and recorded-playback methods need no trust flag; tests use a separate owned
client, never the extension backend, to verify them without relaxing startup.

Native DAP/live debugging and remote/browser work remain the plan's optional
later work. The explicit deferrals above are outstanding implementation work, not a user-agreed reduction of the original acceptance contract.

### Known implementation limitations (left unchanged)

The following open nits were checked against the current code. They are not
fixed or disguised as delivered behavior by this documentation task.

| Limitation | Current location / consequence | Follow-up |
|---|---|---|
| Class View visibility is always null | `icoda_core/service.py:class_node` emits `visibility: None`; the shared model has no access-control fact. | Carry real parser/model visibility before displaying public/private/protected; retain unknown until then. |
| Class clusterPath is single-level | Class `view.get` in `icoda_core/service.py` returns an empty path or one group. P01 File View now returns saved parent paths and supports deeper navigation. | Extend Class hierarchy only with a shared navigation contract; File hierarchy is already covered by P01. |
| Class threshold is an inline literal | `icoda_core/views.py:class_view_level` uses `len(graph.nodes) > 12`. | Name the existing threshold in a focused maintenance change without changing its value. |
| File View box list is computed twice | `icoda_core/views.py:file_view_level` calls `file_view_bounds`, then reconstructs the same label boxes for readability checks. | Reuse that geometry in a separate performance/cleanup change with layout regressions. |
| specification.validate is typed Any | `icoda_core/specification.py:validate(spec: Any)` accepts arbitrary JSON for runtime validation but weakens static checking. | Narrow its input type while preserving malformed-JSON validation behavior. |

Other documented core limits remain: Python AST analysis omits unresolved dynamic
calls, annotated attributes are not field entities, and Python docstrings do not
populate `Entity.satisfies`. External trace import resolves symbols against the
model but does not independently authenticate the recording's executable. Real
recordings retain G09's selected-target/artifact association. Service locks only
coordinate cooperating services; do not treat them as desktop writer exclusion.

## G18 documentation reconciliation and desktop regressions (iteration 29)

Starting and final HEAD: `fde592e3636dd19c9e84c51ffb43337d395fc717`. The starting
working tree already contained the accumulated migration: 24 modified tracked
files (including the two evidence inventories) and untracked migration document,
service/tests/fixtures, measurement tool and extension. Starting status and file
hashes are retained under the system-temp report directory's `g18-iteration29/`.
This iteration changes only `docs/VSCODE_MIGRATION.md`, `vscode/README.md` and
`README.md`; earlier source/test/evidence changes remain intact. No commit or
merge was made. Root `AGENTS.md` and this record were reread at start and before
finalization; no ICODA-local instruction file exists.

The full ICODA `python -m pytest -q` run below includes the existing desktop
App, executable selector, step controller/panel, source editor, troubleshooting,
File/Class/Call/Mind Map, grouping and trace regressions. These predominantly
use the default Tk stub; passing pytest is not real-Tk visual acceptance.

The three standalone desktop GUI failures are **pre-existing on base commit
fde592e**, not migration regressions. G11c/It15 already reproduced each on a
detached base checkout and the migration checkout; G18 reread those retained logs:

| Standalone check | Base/current failure and retained evidence |
|---|---|
| `tests/gui_acceptance.py:248` | `RuntimeError: File View is missing source boxes`; `it15-base-gui-built.log` and `it15-current-gui.log`. The base run uses the same built sample; the initial unbuilt-base fixture failed a different cluster precondition and is not substituted for this comparison. |
| `tests/recovery_gui_acceptance.py:136` | Expected five calls and “What is the cause?” in the fifth; `it15-base-recovery_gui.log` and `it15-current-recovery_gui.log`. |
| `tests/editor_gui_acceptance.py:139` | `assert set(files) <= boxes.keys()`; `it15-base-editor_gui.log` and `it15-current-editor_gui.log`. |

No new base worktree or standalone GUI rerun was needed for documentation-only
edits: the equivalent-fixture base/current evidence already exists. The dated
G13 report also records six inherited mypy findings; no current full-mypy pass
is claimed. The full `verify.bash` gate was not run because it invokes real
providers, prohibited for this task. Controlled fixtures are the only provider
executables used by the required test suites.

### Reproduce the G18 verification

Use a prepared Python development environment and Node.js 22+; retain the venv
interpreter path rather than resolving its symlink. Run the following from
`icoda/`, with `ICODA_TEST_PYTHON` set to that interpreter:

```bash
export ICODA_TEST_PYTHON
export PATH="$(dirname "$ICODA_TEST_PYTHON"):$PATH"
export ICODA_TEST_REPORT_DIR="${TMPDIR:-/tmp}/ai-loop-worker-reports/J20260927-170326-588902/g18-iteration29"
mkdir -p "$ICODA_TEST_REPORT_DIR"
python -m pytest -q > "$ICODA_TEST_REPORT_DIR/pytest.log" 2>&1
cd vscode
npm run compile > "$ICODA_TEST_REPORT_DIR/compile.log" 2>&1
npm test > "$ICODA_TEST_REPORT_DIR/npm-test.log" 2>&1
npm run test:integration > "$ICODA_TEST_REPORT_DIR/integration.log" 2>&1
```

This ICODA-only pytest run avoids the independent AI-Loop network-service tests.
An initial repository-root invocation exited 2 without diagnostic output in the
ICODA-only environment (`root-pytest-attempt.log`); it is not a passing combined
suite. No sibling dependencies were installed and no combined-suite requalification
is claimed. The earlier G17 combined-suite result remains historical evidence.

| Required check | Actual G18 result (Linux, 2026-09-28) |
|---|---|
| `python -m pytest -q` from `icoda/` | **1148 passed, 10 skipped in 209.74s (0:03:29)**; exit 0, includes desktop regressions. |
| `npm run compile` from `vscode/` | **`tsc -p .`, exit 0, 0 errors**. |
| `npm test` | **183 tests, 183 pass, 0 fail, 0 skipped**. |
| `npm run test:integration` — workspace | **8 passed, 0 failed**, VS Code 1.96.4 / X11; host exit 0. |
| `npm run test:integration` — empty | **1 passed, 0 failed**, VS Code 1.96.4 / X11; host exit 0. |
| Integration aggregate | **9 passed, 0 failed**; command exit 0. |

Prepared dependencies and cached VS Code were reused; no install, real provider
or CLI agent was invoked. Host profiles retain disabled telemetry/updates and
Workspace Trust. Logs, result JSON and four native screenshots are only in
`g18-iteration29/`, with host artifacts under `icoda-integration-ow3px5/` in the
system-temp report directory. All four screenshots were inspected: wide panels
show six controls, narrow panels show overflow, and main/source line 4 agree.
The fixed 100% camera crops the narrow graph; this does not qualify Fit or native
overflow interaction. Pytest's appended sample-project analysis log was moved
to `sample-analysis.log` in temp and the original log restored by matching its
starting SHA-256 prefix. G17's package/reproducibility/installed smoke was
not rerun; those dated results support the delivered packaging, not a claim of
new installed acceptance after README edits. The ten pytest skips remain
prerequisite/platform limits, not passes. A focused `-rs` rerun of those cases
(`skip-reasons.log`) confirms six native Windows cases, three requiring the
unversioned `clang++` command and one missing compiler/libclang pairing; installed
versioned-tool discovery and real recording tests passed in the full suite.

## 2026-09-28 — G12 purpose-comment decisions (iteration 30)

Protocol v1 adds `purpose.apply` and `purpose.reject`, taking `workflowId`, `idle`,
`unsavedDocuments` and `trusted` with the existing session context. Both dispose
of the candidate; application reuses the extracted desktop loop, validates source
and candidate snapshots, and marks the model stale for explicit reanalysis.
The parity row above cites the new controlled-provider and Node regressions.
Linux verification: repository-root `python -m pytest -q`: **1716 passed, 13 skipped
in 222.29s** (including desktop regressions); `npm run compile`: **exit 0**;
`npm test`: **186 passed, 0 failed**; `npm run test:integration`: **workspace 8/0,
empty 1/0**, VS Code 1.96.4. Two Redis cases were explicitly skipped by a temporary
pytest hook to honor the network prohibition. Prepared dependencies were reused;
no real provider ran. Logs/screenshots remain in the system-temp report directory
(`iteration30-*.log`, `icoda-integration-8otVJd/`). The first host run passed seven
functional checks but failed screenshot capture because the venv's `python3`
lacked `gi`; the passing rerun kept system PATH for capture and selected the backend
with `ICODA_TEST_PYTHON`. No broader platform or native purpose-workflow acceptance
is claimed. No commit or merge was made.

**2026-09-28, iteration 31:** Purpose decisions share the view's trust/disposal/session
guard and forward actual trust. The existing service `require_trust` refuses both
decisions; the new trust tests and all four It30 acceptance cases cited in the parity
row pass. Service decisions use `documentation.apply`/`reject`; the desktop's
`icoda.py` Troubleshooting controller shares `apply` and `completion_refusal` unchanged.
Linux verification: root `python -m pytest -q` **1718 passed, 13 skipped in 208.84s**
(two Redis skips via the temporary network-policy hook); `npm run compile` **exit 0**;
`npm test` **189 passed, 0 failed**; `npm run test:integration` **workspace 8/0, empty
1/0**, VS Code 1.96.4. Only controlled providers ran. Logs remain in the system-temp
report directory's `iteration31/`; full untrusted-workspace integration remains unqualified.

## G10 — File View cluster edits (2026-09-28, iteration 32)

File View cluster boxes now offer **Pin Cluster** / **Unpin Cluster** and
**Rename Cluster…** on right-click or Shift+F10/Menu key. In an expanded cluster,
the breadcrumb button opens the same menu. Rename uses VS Code's native input
box, initially containing the clean cluster name; cancellation leaves state intact.
Menu actions carry only a validated cluster ID and panel version. The native
input supplies the name after checking trust, disposal and session identity again.
Rendering uses DOM text for names, retains the CSP, and preserves the current
root, expanded level, file selection and per-level camera during edits.

The backend reuses the exact desktop `clusters.pin_cluster`, `unpin_cluster`,
`rename_cluster`, `cluster_is_pinned` and `LayoutDecision.to_layout` functions,
then `ProjectStore.save_layout` atomically writes `.icoda/layout.json`. Its `names`
map uses raw stable cluster IDs; `pins` maps project-relative files to those IDs.
Pins/name choices survive view reload, service restart and project reopen.
`grouping.py` groups implementation steps and `expansion.py` projects hierarchy;
neither owns these edits. No extraction or desktop behavior change was needed.
File assignment, camera persistence across panel/project reopen, and the known
single-level clusterPath limitation remain outside this change.

Protocol v1 adds these methods to `initialize.capabilities.methods`:

| Method | Exact params | Result |
|---|---|---|
| `cluster.pin` | `clusterId`; optional `viewClusterId` (null/omitted for overview) | Updated File `view.get` payload. |
| `cluster.unpin` | `clusterId`; optional `viewClusterId` | Updated File `view.get` payload. |
| `cluster.rename` | `clusterId`, `name`; optional `viewClusterId` | Updated File `view.get` payload. |

All three require top-level `sessionId`, `modelRevision`, `targetId`, checked before
work using the existing `invalid_session`, `stale_revision`, `stale_target` errors.
`clusterId` is the returned stable File View ID including `cluster:`; an unknown
ID, external-library group or invalid display root returns `unknown_cluster`.
Blank/whitespace names, NULs and invalid types return `invalid_params`; shared core
trims accepted names. Failed validation never writes layout. Cluster edits retain
model revision, selected target and trace playback. Optional cluster-node `name`
is the clean display name; optional `clusterPath[].pinned` supports the current
cluster menu. Existing payload fields keep their meanings. `viewClusterId`
requests the current expanded level; if unpinning dissolves that group under core
membership rules, the result returns overview (`clusterId:null`). Camera remains
unchanged; ordinary edits retain the existing cluster root.

Webview types `pin`, `unpin`, `rename` accept exactly `{type,id,version}` with bounded,
nonempty `cluster:` IDs. A forged name, path, identity or extra field is rejected.
The model accepts only a currently visible cluster or the active cluster path,
serializes edits through the panel, and discards stale replies. Service errors
retain the preceding graph for continued navigation.

2026-09-28 verification: new `tests/test_service.py` cluster cases prove shared
persistence/reopen, validation, stale identities and oversized-parent unpinning;
new `vscode/src/test/fileView.test.ts` cases prove message rejection, service routing,
labels/context actions, preserved root/camera and native-input cancellation/races.
Linux verification: repository-root `python -m pytest -q` **1728 passed, 13 skipped
in 214.52s (0:03:34)**, including existing desktop cluster/menu regressions;
`npm run compile` **exit 0**; `npm test` **194 passed, 0 failed**;
`npm run test:integration` **workspace 8/0, empty 1/0**, VS Code 1.96.4.
The root pytest environment reused the prepared ICODA interpreter and the existing
AI-Loop venv packages; a temporary `PYTEST_PLUGINS` hook skipped the two real Redis
cases to honor the network prohibition. Other skips retain prerequisite/platform
limits. Logs are only in the job's system-temp report directory, `iteration32/`
(`pytest.log`, `compile.log`, `npm-test.log`, `integration.log`); host artifacts are
under `icoda-integration-W7KJ4g/`. The test-appended sample analysis log was retained
there and its original repository contents restored. Prepared dependencies and
cached VS Code were reused. No real provider or CLI agent ran; `verify.bash` was
not invoked because it runs real-provider acceptance. No additional platform or
native cluster-menu visual qualification is claimed. No commit or merge was made.

## G12/G13 — Queue settings and automatic continuation (iteration 33)

The Workflow tree exposes **Batch size**, **Queue scope**, **Queue grouping** and
**Auto-approve while gates pass** through native input/selection controls and
Command Palette commands. Values use the desktop's `ProjectState` fields in
`.icoda/state.json`: `implementation_batch_size`, `implementation_scope`,
`implementation_grouping`, `auto_approve`. The minimum batch size is 1; the desktop
spinbox suggests 1–20 but accepts larger positive integers, so no new upper limit
is imposed. Scope/grouping choices and labels come from the backend.

`implementation_queue.update_settings` extracts the desktop's settings updates;
the desktop still calls the same scope/regrouping rules and preserves approach
invalidation behavior. Continuation uses existing `implementation_queue.remaining`,
`steps.run_workflow`, `auto_approve.derive`, `StepRunner.approve_reviewed` and the
normal review fingerprint, clean-tree, build/test, promotion and rollback gates.
No queue ordering or approval rule is implemented in TypeScript.

**Run Implementation Queue** uses continuation when automatic approval is enabled.
Enabling it with a current eligible code candidate evaluates that candidate, as
on the desktop. After explicit approach approval, generation resumes automatically.
A passing code step advances the shared cursor and requests the next approach;
that approach always stops for developer approval. This is bounded by the remaining
queue count captured for the run, not permission to approve approach rounds.
Failed build/test or other approval gates, unconfirmed signature changes, provider
failure, cancellation and an empty queue stop continuation with a visible reason.
The toggle remains saved, as on the desktop. Explicit approach or signature-confirmed
approval resumes through review completion; other stops require running the queue
again after resolution. Reopening a project never resumes continuation.

Protocol v1 adds these methods (top-level `sessionId`, `modelRevision`, `targetId`
are required and checked with the existing identity errors):

| Method | Params | Result |
|---|---|---|
| `queue.settings.get` | `trusted:true` | Workflow status plus `queueSettings` and `continuation`. No provider runs. |
| `queue.settings.set` | `trusted:true`, nonempty `settings` patch: `batchSize`, `scope`, `grouping`, `autoApprove` | Persisted shared settings and current continuation state. |
| `queue.continue` | `trusted:true`, `unsavedDocuments`; optional `provider`, `model`, `request`, `focus`, `evidenceFingerprint` | Advance one backend-selected stage, or return its stop reason. |

Optional `queueSettings` contains `batchSize`, `scope`, `grouping`, `autoApprove`
and labeled `scopes`/`groupings`. Optional `continuation` contains
`state:running|stopped`, `reason` and `ready`. The existing `workflow.status` and
`workflow.cancel` responses may include these fields. `ready:true` requests the
next client handoff; a running provider is polled through `workflow.status`.
Before automatically approving a candidate, the frontend obtains fresh
`proposal.get` evidence and sends its fingerprint plus the latest dirty-document
list to `queue.continue`. That method cannot accept signature confirmation or
approve an approach. Successful approval returns optional `decision` with the
existing project snapshot/record format; its model revision advances once and
the client accepts that revision before continuing. Other queue operations retain
revision. Original `workflow.start` behavior is unchanged for existing v1 clients.

Invalid settings return `invalid_params` without a write; obsolete revisions
return `stale_revision`. Workspace Trust is checked before starting Python,
showing/editing settings, continuing, and after native-input waits. Busy workflow
mutations are refused. Disposal/session/target changes discard late replies.
`workflow.cancel` stops providers and between-round continuation; `queue.continue`
also supports `operation.cancel` during approval build/test checks with shared
rollback. The new cancelled-promotion regression exposed cancellation reaching
rollback Git reads; `steps.py` now lets transactional cleanup finish under an
uncancelled scope, restoring source and metadata before returning. Cancellation
never authorizes the next round. No CSP changes or new
webview messages are needed.

2026-09-28 verification: iteration-32 cluster pin/rename matrix and README entries
were already correct. New service tests: `test_queue_settings_*`,
`test_queue_methods_enforce_trust_and_stale_identity`, `test_queue_continuation_*`,
`test_queue_auto_toggle_evaluates_current_candidate`;
new desktop regression: `test_desktop_queue_settings_use_shared_updates_and_preserve_controls`;
new `workflow.test.ts` queue cases cover native commands/inputs, trust/stale/disposal,
late results, cancellation, live dirty buffers, rendering and a real service using
only the controlled fixture executable. Step 0 re-confirmed compile exit 0,
Node **194 passed / 0 failed**, host **workspace 8/0, empty 1/0** using the prepared
interpreter (the initial system-Python attempt lacked clang bindings).

The first combined-suite run found an outdated cancellation-capabilities assertion
and three sibling tests affected by overriding `TMPDIR`; the assertion now includes
`queue.continue`, and the normal `/tmp` setting restored the three sibling checks
without modifying sibling code (31 focused checks passed). A temporary pytest hook
skips the two real Redis tests under the task's network restriction.

Final Linux verification (2026-09-28): repository-root `python -m pytest -q`
**1761 passed, 13 skipped in 270.70s (0:04:30)**; `npm run compile` **exit 0**;
`npm test` **203 passed, 0 failed**; `npm run test:integration` **workspace 8/0,
empty 1/0**, VS Code 1.96.4. Existing desktop tests pass. The remaining skips retain
prerequisite/platform limits. Logs are in this job's system-temp report directory,
`iteration33/` (`pytest.log`, `compile.log`, `npm-test.log`, `integration.log`);
host artifacts are under `iteration33/icoda-integration-hNmGdk/`. The sample
analysis log was retained there and its original repository contents restored.
No commit or merge was made. Ruff and diff checks pass. A scoped mypy check with
the ICODA configuration still reports five existing diagnostics in unchanged
`force_layout.py`/`source_edit.py`; no type-check pass is claimed. No real provider
or new platform qualification is claimed.

## G13 — Interrupted proposal recovery (2026-09-28, iteration 34)

Desktop audit: `session.open_project` reports and preserves `.icoda/worktree` on
reopen; `icoda.py` displays that result. There is no startup Resume/Discard/Keep
dialog or persisted in-memory Proposal to extract. `recovery.py` diagnoses provider
failures and retries bounded read-only requests. `step_controller.py` offers Retry,
repair, Rebuild, Reject, manual-edit commit and Open worktree for an active candidate;
`tasks.py` delivers background outcomes. Saved-editor checks precede desktop actions;
shared clean-tree, signature, build/test and promotion checks remain authoritative.
A fresh desktop proposal still resets its detached worktree as documented in
`HANDBOOK.md`. No desktop startup, dialog, provider or cancellation behavior changed.

The service now opts into an optional `StepRunner.checkpoint` callback. Before
provider work and before file application it atomically saves the exact request
(including budget, batch and constraints), response and base commit to ignored
`.icoda/cache/interrupted-proposal.json`. Gate success is never persisted. Shared
`recovery.interrupted_proposals` and `resolve_proposal` handle the retained checkout
and journal, using `steps` and `git`; queue reconstruction uses the runner's existing
`implementation_queue` selection. The approach prerequisite was extracted into
`StepRunner._require_approved_approach`, called by desktop proposal generation and
recovery. The default desktop checkpoint is a no-op.

Protocol v1 adds only these methods, with required top-level `sessionId`,
`modelRevision`, `targetId` and the existing identity errors:

| Method | Params | Result |
|---|---|---|
| `recovery.list` | `trusted:true` | Session context and `items` containing `id`, `label`, `worktreeRoot` and labeled `choices`. No tools/providers are started except read-only Git inspection. |
| `recovery.resolve` | `trusted:true`, `recoveryId`, `choice:resume|keep|discard`, `unsavedDocuments`; optional boolean `confirmDiscard` | Keep/discard return the updated list. Resume returns an existing `WorkflowStatus` (`kind:recovery`), polled/cancelled through `workflow.status`/`workflow.cancel`. |

IDs fingerprint the retained metadata and candidate files; changed or unknown IDs
return `recovery_missing`. Invalid choices return `invalid_choice`, stale identity
returns `stale_revision`/`invalid_session`/`stale_target`, untrusted requests return
`workspace_untrusted`, unsaved project/candidate buffers return `unsaved_documents`,
shared clean-tree refusal returns `dirty_tree`, and Git failures return `git_failed`.
Missing discard confirmation returns `confirmation_required`. Invalid/corrupt or
out-of-project recovery metadata returns `recovery_invalid`; changed base commit,
phase or step returns `stale_evidence`. An active workflow or review cannot be
replaced by a recovery decision. No Git lock is deleted. Existing OS-owned service
locks still recover a dead owner and refuse a live owner (`test_dead_lock_owner_is_recovered_without_deleting_lock_file`).

Resume reviews existing bytes, including partial application and manual candidate
edits; it never replays a saved response or invokes a provider. Code candidates
rebuild/retest/reparse through `StepRunner.rebuild` and return through the existing
proposal fingerprint/signature/approval gates. A run interrupted before producing
any candidate remains blocked in review; restarting provider generation is a
separate explicit workflow after discard. Legacy desktop worktrees without a
journal use the current shared phase/queue scope and default entity budget, with
fresh checks. A different worktree base is refused. Keep preserves the candidate
and continues to block competing workflows. Discard requires native modal
confirmation, refuses dirty/unsaved work, and uses strict Git worktree removal;
Git failure preserves work. Named branches are retained, because current ICODA
uses detached worktrees and cannot infer ownership of arbitrary branch names.
Dirty partial promotion in the main tree requires developer resolution first.

The native Proposal tree discovers recovery on project open/restart, and **Recover
Interrupted Proposal** also refreshes it on demand. A native Quick Pick selects the
choice; only discard prompts modally. Inputs carry scoped IDs, never caller-supplied
paths. The model rechecks trust, identity, evidence membership and disposal, drops
late replies, and cancels owned checks. Resume opens the first changed file using
the existing native diff from the recovered worktree. Recovered candidates cannot
enter automatic approval, even via the queue toggle or Run Implementation Queue;
explicit review is required. No webview message or CSP changed.

2026-09-28 verification: step 0 re-confirmed compile exit 0, **203 Node tests passed**,
VS Code 1.96.4 **workspace 8/0, empty 1/0**. The It32 cluster pin/rename and It33
queue/automatic-continuation matrix rows and README entries were already correct
and cite their tests. New service `test_recovery_*` cases use temporary Git repos
and controlled fixtures only: all choices, trust/identity, dirty/unsaved refusal,
Git locks, changed candidate/base, partial application, interrupted provider,
legacy worktrees, approach recovery and failed/signature/automatic-approval gates.
`proposal.test.ts` covers native rendering/pickers/confirmation, correct worktree
diffs, open/restart detection, late results, cancellation and trust/stale/disposed
guards. `test_desktop_default_runner_keeps_interrupted_worktree_without_recovery_journal`
covers unchanged desktop defaults and the extracted approach prerequisite.
Final Linux verification (2026-09-28): repository-root `python -m pytest -q`
**1781 passed, 13 skipped in 307.70s (0:05:07)**; `npm run compile` **exit 0**;
`npm test` **211 passed, 0 failed, 0 skipped**; `npm run test:integration`
**workspace 8/0, empty 1/0**, VS Code 1.96.4. This includes 19 new service recovery
cases, one desktop regression and eight new Node tests. The earlier full run passed
1780 tests; the final run also includes the reanalysis/recovery lifecycle regression.
Two Redis network tests were skipped with the same temporary policy hook as It33;
the other skips retain prerequisite/platform limits. Prepared dependencies and
cached VS Code were reused. No real provider, CLI agent or network service ran.
Logs and host artifacts are only in the system-temp report directory's `iteration34/`
(`pytest.log`, `compile.log`, `npm-test.log`, `integration.log`,
`icoda-integration-vfcErc/`). The test-appended sample analysis log was retained
there and its original repository bytes restored. Ruff and diff checks pass.
Scoped mypy still reports the same five existing diagnostics in unchanged
`force_layout.py`/`source_edit.py`; no type-check pass is claimed. Recovery-specific
native host interactions remain unqualified; the new UI evidence is from Node
routing tests. No broader platform or real-provider qualification is claimed.
No commit or merge was made.

## M0 historical verification

| Check (from `icoda/` unless stated) | Actual result |
|---|---|
| Unmodified `python -m pytest -q` | 902 passed, 20 skipped, 1 pre-existing failure, 31.97s (details above). |
| Isolated baseline failure rerun | Same documentation inventory failure, 0.14s. |
| `python -m pytest -q tests/test_call_trace.py tests/test_trace_stepping.py` | **29 passed**, 0.54s, including the three new independent example cases. |
| Post-change `python -m pytest -q -rs` | **905 passed, 20 skipped, same 1 failure**, 31.05s. No new pytest failures. |
| `python -m ruff check tests/test_trace_stepping.py`; repository `git diff --check` | Passed. |
| Headless import of session/targets/source/trace core without Tk imports | Passed in a fresh interpreter. |
| Real-Tk empty-window construction and close | Passed, Tcl/Tk 8.6.14; no project or provider involved. |
| Complete `verify.bash` gate | Exit **1**; additional existing-area failures detailed below. The complete gate is not claimed green. |

The baseline and post-change suites include `test_call_trace.py`,
`test_trace_stepping.py`, `test_executable_selector.py`, `test_instrumentation.py`
and the File/Class/Call/Mind Map/cluster/expansion view tests. Their current
fixtures and assertions were inspected, including isolated recording builds,
target-scoped views, moved/ambiguous source lookup and camera preservation.
The existing plain C++ instrumentation fixtures execute real builds/runs; these
are core integration evidence, not extension UI or native Windows qualification.

### Broader gate observations (separate from the initial pytest baseline)

The full gate was run after adding the regressions, with `ICODA_VERIFY_PYTHON`
pointing at the same prepared environment. Evidence is retained outside the
repository under
`/tmp/ai-loop-worker-reports/J20260927-170326-588902/verification/20260927-190855-840222/`
(`summary.txt`, per-stage logs, JUnit, coverage and acceptance artifacts).

| Stage | Actual outcome |
|---|---|
| Diff, Ruff, byte compilation, provider qualification, fresh sample analysis | Passed. |
| Real-provider acceptance | Passed with Codex and the acceptance script's `gpt-5.6-sol` default; 49.6s. Its disposable project under the artifact directory exercised proposal/approval/undo and contains fixture commits. This repository's HEAD remained unchanged. |
| Sample build/CTest | Passed with discovered `/usr/bin/clang++-18`; 1/1 CTest passed. This generated ignored sample build/cache artifacts, not tracked source edits. |
| Pytest with coverage, after sample build | **915 passed, 10 skipped, 1 failed** in 63.22s; still only `test_evidence_documents_match_current_module_inventory`. Coverage **88.88%** exceeds the 85% gate. Ten formerly skipped sample-dependent cases now ran. |
| mypy | **32 errors in five unchanged production files**: `icoda_core/force_layout.py`, `source_edit.py`, `views.py`, `icoda_gui/class_view.py`, `icoda.py`. Includes inferred tuple/dict/list type mismatches, missing annotations, and optional layout access. Exact diagnostics are in `mypy.log`; reproduce with the mypy command in `tests/verify.py`. |
| General real-Tk GUI | `tests/gui_acceptance.py:248`: `RuntimeError: File View is missing source boxes`. |
| Recovery real-Tk GUI | `tests/recovery_gui_acceptance.py:136`: expected five provider calls and `What is the cause?` in the fifth call; assertion failed. |
| Editor real-Tk GUI | `tests/editor_gui_acceptance.py:139`: `assert set(files) <= boxes.keys()` failed. |

These additional failures were observed in unchanged application/acceptance files;
they are not results of an unmodified-tree full-gate run. The new regression file
is not an input to mypy or those standalone GUI programs. Their failures are
recorded as existing-area qualification limitations without diagnosing or fixing
them outside this task. The reproducibly isolated pre-existing **pytest** failure
was the inventory error documented above; It8 subsequently corrected it.
G11c/It15 subsequently reproduced all three standalone GUI failures on the base
commit with equivalent fixtures; G18 cites that evidence as pre-existing failures.

M0 changed only this document and `tests/test_trace_stepping.py`; its verification
above predates the first service slice. The service adds `icoda_core/service.py`
and `tests/test_service.py` without changing existing desktop/core behavior.
It8 corrected the inventories, including these additions, to 81 = 74 + 7 tests
and 49 core modules. Historical release results are not new qualification.


## Gap 5 — conversation, Open CLI and rephrase (2026-09-28)

Desktop audit and shared behavior:

- `Troubleshooting.send` takes the selected Binary/Model, current project or
  recovery worktree, message and in-memory transcript. `recovery.conversation_prompt`
  includes at most 16 turns / 20000 characters, saved-specification instructions
  and any provider diagnosis. `recovery.invoke(..., writable=True)` uses
  `agent.editing_provider` once, with a 1800-second timeout and owned cancellation.
  Explicit requests may edit source. Partial edits on cancellation/failure still
  trigger source refresh/invalidation. Busy/disabled-provider gates remain; the
  extension additionally refuses unsaved documents before requesting edits.
  Transcript entries are session memory, preserved across analysis, cleared on
  project open/restart, and never appended to the approval steplog.
- `Troubleshooting.open_cli` carries that context plus an optional unsent draft
  into `terminal.interactive_command`. Codex keeps `--sandbox workspace-write`
  and `--ask-for-approval on-request`; Claude keeps its normal interactive
  permissions. The draft does not become a history entry. The extension receives
  argv, cwd and environment overrides (currently empty, inheriting the host),
  passes argv[0] / argv.slice(1) to `createTerminal` shellPath/shellArgs and owns
  the terminal disposable. The backend never starts a terminal or shell.
- `StepController.rephrase` requires a current proposal rationale or unapproved
  approach plan and an available provider; historical/approved descriptions are
  unavailable. Shared `steps.rephrase_context` supplies the proposed diff/files
  and declaration delta, or planned files/entities. `StepRunner.rephrase_description`
  uses the existing read-only provider path and requests only simpler prose.
  Shared `steps.replace_description` updates rationale/plan after cancellation
  and identity checks. Files, raw replies, signature confirmations, checks and
  approval state stay intact. No steplog is written by rephrase; a later ordinary
  review decision records the current description through the existing path.

The service has a separate owned interaction job so a conversation or rephrase
cannot replace or approve a pending proposal. Candidate conversations/CLI use
its worktree; retained candidates must first be recovered. Purpose candidates
must be decided first. Conversation edits mark the model stale, including edits
made before failure or cancellation; Analyse Project refreshes source facts.
Candidate file fingerprints still require rebuild/review after edits. Rephrase
invalidates the displayed review token and preserves existing check validity.
Automatic queue continuation stops for explicit review. These operations never
call approval, promotion, signature confirmation or build/test bypass paths.
Provider failures remain `provider_failed` / `provider_unavailable` (with shared
provider diagnosis); source errors never enter conversation recovery. Ordinary
source/graph navigation and history work without a configured provider.

### Protocol v1 additions

All four methods require `trusted:true` and the current top-level sessionId,
modelRevision and targetId. Invalid or late identities are rejected before work.
The startup capabilities list advertises the methods. Provider/model overrides
are optional and otherwise use the existing persisted selection.

| Method | Parameters in addition to trust/identity | Result |
|---|---|---|
| `conversation.send` | Required nonblank `message` (max 20000 characters), `unsavedDocuments: string[]`; optional `provider`, `model` | Existing workflow envelope, kind/round `conversation.send`; plain redacted reply in `result.summary`. |
| `conversation.history` | None | Current context and `messages: [{role, text}]`, including developer and assistant turns. No disk persistence. |
| `prompt.rephrase` | Required `unsavedDocuments: string[]`; optional `provider`, `model` | Existing workflow envelope, kind/round `prompt.rephrase`; simplified current description in `result.summary`. Unsaved buffers are not modified. |
| `cli.command` | Required `unsavedDocuments: string[]`; optional nonblank `draft` (max 20000 characters), `provider`, `model` | Current context and `argv: string[]`, `cwd: string`, `env: object`; no process launch. |

Long calls use `workflow.status` / `workflow.cancel` with their returned workflowId,
plus existing workflow progress/state notifications. `workflow.sourceChanged`
also reports partial edits on failure/cancellation. Missing text/current review,
malformed input, unsaved buffers, active jobs and retained candidates produce
local structured refusals. Cancellation and project/target changes join owned
provider processes. Frontend tickets discard late replies/errors, and trust is
checked again before rendering or terminal creation. Replies use ICODA Providers
plain output; conversation input and rephrase choice use native Input Box/Quick Pick.

Verification (2026-09-28, gap 5): controlled provider fixture
`tests/fixtures/fake_workflow.py`; Python cases in `tests/test_service.py`:
`test_conversation_shared_provider_history_and_no_step_records`,
`test_conversation_edits_and_partial_failure_cancel_mark_stale`,
`test_rephrase_preserves_candidate_gates_history_and_approval`,
`test_rephrase_failure_cancel_keep_original_review`,
`test_conversation_candidate_edits_require_rebuild_and_never_approve`,
`test_interaction_trust_identity_and_no_provider_navigation`,
`test_conversation_rejects_invalid_inputs_before_provider`,
`test_conversation_cli_preserve_unsaved_buffers`,
`test_cli_command_argument_array_context_and_no_spawn`,
`test_interaction_project_switch_cancels_provider_and_drops_old_job`,
`test_rephrase_no_provider_and_cli_unsupported_are_provider_errors`.
Desktop extraction cases are
`test_desktop_rephrase_delegates_shared_scope_and_publication` and
`test_desktop_conversation_delegates_shared_edit_tracking`, alongside the existing
rephrase/Prompt regressions. Node `workflow.test.ts` covers conversation/rephrase
routing/rendering, CLI argument validation, native input/output/terminal calls,
trust/cancellation and session/target/revision/disposal guards, plus an end-to-end
controlled service conversation/rephrase retaining the proposal gates. These are
not real-provider or native interactive-terminal qualification. Required gate
logs are in `iteration36/` under this job's system-temp report directory; the final
report is `verification.txt` in that directory. No real provider/network service
was invoked by these tests.

Required gate results (Linux, 2026-09-28): `npm run compile` passed;
`npm test` reported 219 passed / 0 failed; `npm run test:integration` on
VS Code 1.96.4 reported workspace 8 passed / 0 failed and empty workspace
1 passed / 0 failed. Repository-root `python -m pytest -q` reported
1811 passed, 10 skipped in 356.38s. Two Redis integration cases were skipped
by a temporary pytest plugin to obey this task's network restriction; the
remaining skips are existing prerequisite/platform cases. The root run used
an already installed Redis package for AI-Loop imports and the installed LLVM
18 tools on PATH; no dependency was installed. Node used the requested 24.21.0
runtime and ICODA_TEST_PYTHON retained the venv executable path. Ruff, mypy on
the five changed production Python modules, headless import/capability checks
and `git diff --check` also passed.


## Gap 6 — New-project creation (2026-09-28, iteration 37)

Gap 5 was rechecked before changes: compile passed, Node 219 passed / 0 failed,
and VS Code 1.96.4 integration workspace 8 passed / 0 failed, empty workspace
1 passed / 0 failed. Its parity row already contained dated test citations and
the README listed only gaps 6–7. No gap-5 repair was needed.

Desktop audit: `App.ask_new_project` asks for a directory (it may not yet exist).
Despite the empty-directory dialog label, `App.new_project` accepts existing and
nonempty directories, resolves the root, creates parents and ensures `.icoda/cache/`,
`.icoda/.gitignore` and `.icoda/state.json`. Existing state is retained; otherwise
an empty project starts in `specification` (an existing CMake project can have
`implementation` state even while the new-project panel says specification).
Busy/recovery and unsaved-source guards precede creation. No separate name or
template dialog exists: the directory basename supplies the default title and
skeleton name, language detection selects the default Code Profile (C++ for an
empty folder), and the specification editor accepts C++ or Python. Schema
validation requires a nonempty title, with no desktop folder-name rule; shared
generators normalize CMake/module identifiers. The title can differ from the
folder basename.

On Save the desktop writes `.icoda/specification.json` and logs the save. Existing
CMake files or an existing-project specification edit bypass skeleton generation.
Otherwise `generator.write_skeleton` adds only missing files and
`phases.transition` persists architecture phase plus the phase-transition record
in `.icoda/steps.jsonl`. C++ generates `CMakeLists.txt`, `CMakePresets.json`,
`build.sh`, `build.cmd`, `vcpkg.json`, `Doxyfile`, `.gitignore`, `README.md`,
`examples/basic/main.cpp`, `src/app/app.cppm` and `tests/smoke_test.cpp`. Python
uses the profile's naming/path conventions for `src/<module>.py` and
`tests/test_<module>.py`, plus `pyproject.toml`, `.gitignore` and `README.md`.
The desktop offers Build, followed by analysis, or opens/analyzes immediately.
Creation itself does not initialize Git or commit: existing `StepRunner.prepare`
uses shared `git.py` for the first own repository and step-zero commit later.

`session.prepare_new_project` and `session.save_project_specification` now hold
only the extracted preparation and first-save operations. Desktop callbacks still
own editor/busy guards, panel changes, dialogs and reload/build decisions; their
existing behavior is preserved. `session.create_project` composes these operations
with a stricter boundary for the extension: an existing absolute parent, a valid
portable single-component name, C++ or Python, and optional summary. All existing
targets (including empty directories, files and symlinks) are refused, so the new
command cannot adopt an existing project. Validation happens before exclusive
folder creation. Skeleton paths come from the shared default profiles, not client
paths; there is no TypeScript generator or copy of the core folder-name rules.

Protocol v1 adds advertised `project.create` with required `parentPath`, `name`,
`language`, `trusted:true`, and optional `summary` (default empty). It requires
current top-level session/revision/target identity when a project is open, and also
works without an open project. Errors are `invalid_params`, `target_exists`,
`not_trusted`, existing identity errors, or `project_create_failed` for filesystem
failures. The result contains `root`, `writtenFiles` (skeleton-relative paths),
`specificationPath` and persisted `state`. It never installs another service
session, analyses a root, invokes a provider/build/Git operation, or changes the
current model/target. Creation is a short serialized operation, not a cancellable
background job; cancelling any picker before submission writes nothing.

`ICODA: New Project` (`icoda.newProject`) uses native folder/name/language/description
controls and can start from an empty VS Code window. It saves a schema-valid
specification from the shared defaults and entered description, generates the
skeleton and advances to architecture. The full specification remains editable
through Open Specification. Completion offers Open in New Window or Add to
Workspace; dismissing leaves the new folder on disk without switching the active
project. Trust, session/target identity, backend reset and disposal checks drop
obsolete successes/errors and workspace-open choices. Build, analysis and Git
preparation stay explicit existing operations; ordinary specification-save
behavior and documented open nits are unchanged. Gap 7 is not started.

Verification (2026-09-28, gap 6): Python cases in `tests/test_service.py`:
`test_project_create_shared_skeleton_state_and_session_preserved`,
`test_project_create_without_open_project_advertises_capability`,
`test_project_create_refuses_existing_targets_without_changes`,
`test_project_create_requires_trust_before_writing`,
`test_project_create_rejects_invalid_name`, `test_project_create_rejects_path_escape`,
`test_project_create_rejects_invalid_inputs`,
`test_project_create_rejects_stale_session_before_writing`.
Desktop extraction regression:
`tests/test_app.py::test_desktop_new_project_shared_creation_preserves_existing_files`,
plus existing first-save and phase-before-reload cases. Node `lifecycle.test.ts`
adds `newProject` tests for discoverability/service routing, native-input validation
and cancellation, trust before startup, shared path/existing-target refusal,
explicit new-window/add-folder choices, late session/target/trust/disposal/error
replies, and a stale workspace-open choice. Tests create only temporary projects
and use the actual shared service with mocked native UI boundaries. Existing
Electron suites qualify activation/regressions, not an interactive new-project
picker walkthrough or Windows creation. Logs are under `iteration37/` in this
job's system-temp report directory; no real provider or network service is used.

Required gate results (Linux, 2026-09-28): `npm run compile` passed; `npm test`
reported 231 passed / 0 failed. VS Code 1.96.4 integration reported workspace
8 passed / 0 failed and empty workspace 1 passed / 0 failed. Repository-root
`python -m pytest -q` reported 1845 passed, 10 skipped in 369.44s. As in the gap-5
recheck, two Redis integration cases were skipped by a temporary pytest plugin
to comply with the no-network-service constraint; eight existing prerequisites/
platform cases account for the other skips. Node 24.21.0 and the prepared venv
interpreter path were retained; no dependencies were installed. Changed-file Ruff,
headless imports and `git diff --check` passed. An additional mypy check reproduced
six unchanged errors against the pre-task snapshot (`force_layout.py`,
`source_edit.py`, and the existing FileViewLayout access in `icoda.py`); these
unrelated issues were left untouched. No commit or merge was made.

## Gap 7 — Restricted Mode integration qualification (2026-09-28, iteration 38)

Gap 6 was rechecked without repairs: compile passed, Node 231 passed / 0 failed,
and the unchanged VS Code 1.96.4 suites reported workspace 8 passed / 0 failed
and empty workspace 1 passed / 0 failed. The focused `project_create` service
selection reported 32 passed. The gap-6 parity row already records protocol
`project.create`, its shared-core delegation and dated test names. Creation
requires literal `trusted:true`, rejects invalid/escaping names and existing
targets with structured errors, and imports neither Tkinter nor `icoda_gui`.

The trust inventory distinguishes the frontend boundary from service methods:

| Boundary | Existing protection and operations |
|---|---|
| Manifest | Every contributed command except `icoda.showOutput` has `isWorkspaceTrusted` enablement, including graph/source/playback commands. `capabilities.untrustedWorkspaces.supported` is already `limited`; its description now explicitly names Show Output and the inert project placeholder, and Python/toolchain overrides are restricted configurations. Iteration 39 clarifies description wording only; enablement and guards are unchanged. |
| Python startup | `ExtensionController.backend()` refuses untrusted programmatic calls before starting Python. This also protects Open/Analyse Project, Restart Backend, toolchain inspection, target refresh/build/run/record, graphs and evidence. These executable operations do not all have a service `trusted` parameter; startup is their frontend trust boundary. |
| Project creation | `newProject` checks trust before native inputs and backend startup, rechecks across awaits, and sends actual trust. Service `project.create` requires `trusted:true`, otherwise `not_trusted`. |
| Workflows and interactions | `WorkflowView` and its model check actual trust for architecture/approach/queue, cancellation, purpose propose/apply/reject, queue settings, conversation/history, rephrase and Open CLI. Service workflow/queue methods require trust and return `workspace_untrusted`. No terminal can be created by an untrusted command. |
| Proposals and project state | Proposal decisions/recovery, review/diff/history, undo/manual commits, specification and provider UI retain frontend trust checks. Service proposal mutations, recovery, specification save and phase transition require trust. Service proposal/history reads are separate from these write guards. |
| Read-only service access | `project.open` reads cached state/model, `view.get` supplies File/Call/Class/Mind Map data, `source.resolve` resolves project source, and `trace.load`/`trace.step`/`trace.reset` navigate recordings without a trust parameter. They are tested through a separate test-owned client, with unchanged fixture bytes. This does not bypass or alter the extension's startup guard. |

The existing frontend restriction is retained: all ICODA views and commands
except Show Output are disabled in Restricted Mode until the workspace is trusted,
because Python backend startup requires trust. Native source documents and the
inert project placeholder remain visible. “Read-only
service” does not mean that a workspace-configured Python executable is safe to
launch without trust. No graph-browsing-in-Restricted-Mode claim is made.

`integration/run.ts` keeps the trusted workspace/empty launches unchanged and
adds an isolated untrusted fixture/profile. The pinned test-electron 2.5.2 helper
always adds `--disable-workspace-trust`, so only the additional run launches its
downloaded VS Code **1.96.4** executable directly, using an argument array without
that switch. Its fresh user settings enable Workspace Trust and suppress the
startup prompt without granting trust. The suite asserts `isTrusted === false`
at activation, during command execution and at completion. Reports retain launch
arguments, actual trust-refusal notifications and per-test outcomes in system temp.

Verification (2026-09-28, gap 7): `vscode/src/test/integration/untrusted.ts`:

- `Restricted Mode activation retains trust guards and starts no backend`
- `Restricted Mode refuses execution commands before tools providers terminals or backend requests`
- `Restricted Mode output project placeholder and native source editor remain usable`
- `Read-only service open views source and recorded playback need no trust authorization`
- `Service rejects untrusted creation workflows conversation CLI purpose apply and proposal approval`

The command test invokes registered commands programmatically, observes and
forwards real VS Code trust notifications, and installs fail-closed observers
for process creation, backend requests, terminals and native inputs. No attempted
execution is accepted as a pass, and fixture files remain unchanged. Separate
real-service checks verify B → C/D/E, Previous/Reset, all four view responses,
cached opening/source resolution and structured trust refusals. A Python audit
hook is verified installed before these requests and forbids process/network
attempts, so they cannot invoke a real provider even if a guard regresses.
No production gating defect was found or guard changed; no open nit was fixed.

Required gate results (Linux, 2026-09-28): `npm run compile` passed; `npm test`
reported 231 passed / 0 failed. VS Code 1.96.4 integration reported workspace
8 passed / 0 failed, empty workspace 1 passed / 0 failed, and untrusted workspace
5 passed / 0 failed (14 total). Repository-root `python -m pytest -q` reported
1845 passed, 10 skipped in 369.43s. Two Redis service cases were skipped by the
temporary no-network pytest plugin; eight existing prerequisite/platform skips
remain. Node 24.21.0 and the prepared venv interpreter path were retained; no
dependencies were installed. Headless service import and `git diff --check`
passed. Logs, host profiles/results and launch/refusal evidence are under
`iteration38/` in this job's system-temp report directory. No commit or merge
was made; the existing trusted suite assertions and production code are unchanged.


## G18 final reconciliation and verification (iteration 59, 2026-09-28)

Starting HEAD remains `fde592e3636dd19c9e84c51ffb43337d395fc717`. The accumulated
migration modifications were preserved (`status-before.txt`, `hashes-before.json`).
This iteration changes only `docs/VSCODE_MIGRATION.md`, `tests/test_service.py`
and `vscode/src/test/viewState.test.ts`. No production defect was exposed, so no
production code, playback semantics, toolbar, strict message schema, CSP or
Workspace Trust boundary changed. No commit or merge was made.

**Reconciliation is complete; full migration is Partial.** All 22 desktop rows,
G01–G18 and AT01–AT16 have dispositions and named tests/evidence. P01/P02/P03/P05/
P08/P09/P10/P11 delivery supersedes the corresponding stale deferrals. P04/P06/
P09/P10/P11 retain their stated remaining work; P07 and AT02/AT10/AT13/AT15/AT16
remain Not qualified for the reasons in their rows. The Class-only cluster-path
limitation replaces the stale claim that File View still has a single level.
No historical implementation pass total is promoted to this run's evidence.

### Focused P11 correctness evidence

- **Hash match.** `icoda_core/analysis.py:Extractor.extract`,
  `Extractor._own_file` (headers), and `_unparsable` construct `FileInfo` with
  `_sha1(path.read_bytes())`; `analysis.py:_sha1` is
  `hashlib.sha1(data).hexdigest()`. `python_analysis.py:_read_modules` reads
  `raw = path.read_bytes()` and hashes `hashlib.sha1(raw).hexdigest()` before
  decoding UTF-8/BOM for parsing. `model.py:FileInfo` stores that value and model
  JSON restoration preserves it. `service.py:cached_source_changes` uses the
  same SHA-1 hex digest of `path.read_bytes()`: no newline or encoding
  normalization in either producer or comparison. No helper/code change was
  needed. New `tests/test_service.py::test_p11_reopen_unchanged_analysis_keeps_raw_byte_hash_fresh`
  runs real analysis, closes/reopens through `project.open`, verifies the exact
  raw-byte digest and a non-stale model/Call View, and preserves source/cache/state
  bytes for LF, CRLF and UTF-8 BOM+CRLF Unicode fixtures. Existing
  `test_p11_reopen_reports_stale_cache_and_explicit_analysis_recovers` still tests
  modified and removed files. Focused command `python -m pytest -q
  icoda/tests/test_service.py -k p11`: **13 passed, 429 deselected**; `pytest-p11.log`.
- **Dispose ordering OK.** `vscode/src/viewState.ts:ViewState.dispose` invokes
  `flush()` before setting `disposed`. The queued write intentionally rechecks
  `session.identity.isCurrent(ticket)` so the captured session can receive its
  last pending state after disposal; a changed generation/context cannot receive
  it. `viewState.test.ts` now tests `P11 disposal drops pending and queued writes
  after project or target switches` for project replacement, target change and
  same-target reselection, with switch-before-dispose, flush-before-switch and
  dispose-before-switch orderings. The retained `P11 view state restores,
  coalesces writes and flushes before disposal` explicitly asserts the original
  session identity and last scheduled state. No production change was needed.
  `node --test out/test/viewState.test.js`: **7 passed, 0 failed**; `node-p11.log`.

### Current verification results

All retained artifacts below are under
`/tmp/ai-loop-worker-reports/J20260927-170326-588902/iteration59/`.
Linux x86_64/X11 (`7.0.0-31-generic`), Python 3.12.3, Node **24.21.0** from
`$HOME/.local/share/nodejs/v24.21.0/bin`, and cached VS Code **1.96.4** were used.
`ICODA_TEST_PYTHON` remained
`/home/hlavacs/Dokumente/GitHub/AI-Loop/icoda/.icoda-venv/bin/python`, retaining
its venv symlink. `test-env.sh` records the environment: existing LLVM 18 on PATH,
the sibling AI-Loop's prepared site-packages on PYTHONPATH for root tests,
XDG_CONFIG_HOME/APPDATA redirected to temporary `config/`, Python bytecode and
pytest caches outside the repository. No dependency installation, real provider,
manual test skip, weakened assertion, or user-config write was performed.

| Required command | Actual result in iteration 59 | Retained evidence |
|---|---|---|
| `npm run compile` in `vscode/` | **PASS**, exit 0 | `compile.log` |
| `npm test` in `vscode/` | **280 passed, 0 failed, 0 skipped** | `npm-test.log` |
| `npm run test:integration` in `vscode/` | **workspace 37/0, empty 1/0, C++ 3/0, untrusted 6/0** passed/failed; **47 passed, 0 skipped** | `edh.log`; `icoda-integration-PcP8RU/{workspace,empty,cpp,untrusted}-results.json` |
| `npm run test:vsix` in `vscode/` (includes compile/package/fresh install) | **4 passed, 0 failed**, exit 0; bundled-backend production extension | `vsix.log`; `icoda-integration-vbgPOL/{install.log,vsix-results.json,launch.json}`; packaged archive in `artifacts/dist/` |
| `python -m pytest -q` at the worktree root | **1934 passed, 0 failed, 8 existing skips in 411.70s (0:06:51)**, exit 0 | `pytest.log` |
| `git diff --check` at the worktree root | **PASS**, no whitespace errors | `diffcheck.log` |

The EDH directory retains the temporary Python/C++ fixtures, profile settings,
actual source/trace/counter assertions and `at03-*`, `at04-*`, `at11-recording.json`,
`at12-*`, `at14-*`, `p01-*`, `p02-*`, `p03-*`, `p04-*`, `p05-*`, `p06-*`, `p08-*`,
`p09-*`, `p10-*`, `p11-*` evidence. Its four `call-view-{light,dark}-{wide,narrow}.png`
images record native source/editor synchronization and compact toolbar/overflow;
these are not high-contrast, screen-reader, Windows-scaling or full native
keyboard qualification. The installed smoke uses a fresh profile/extension root
and a copied fixture, finding backend/resources inside that installed extension.
Its narrower journey does not close AT16.

The first root run used the report directory as `TMPDIR` and reported
**1931 passed, 3 failed, 8 skipped** (`pytest-initial-tmpdir.log`). Its three
failures were AI-Loop's
`test_run_codex_controller_can_use_external_systemd_confinement` (expects
`ReadWritePaths=/tmp`), `test_stop_terminates_escalates_and_reports` (PID identity
check, not reproduced on recheck), and
`test_no_profile_preserves_exact_existing_prompt_bytes` (the prompt contains the
system temporary path). Restoring ordinary `TMPDIR=/tmp` passed all three without
code/test changes (`pytest-environment-recheck.log`: **3 passed**). The complete
root gate was rerun with that setting; the table records that final run, not the
failed attempt. Config, caches and retained command logs still use the report
root. Reproduce the final root invocation after sourcing `test-env.sh`:

```bash
TMPDIR=/tmp PATH="$(dirname "$ICODA_TEST_PYTHON"):$PATH" python -m pytest -q
```

The eight existing skips are six Windows-only cases, the unavailable matching
compiler beside libclang (`tests/test_analysis.py::test_module_partitions_keep_their_identity_and_resolve_relative_imports`),
and AI-Loop's explicitly skipped `CreateNextTaskTests::test_test_command_laundering`
(the unit case cannot publish to Redis under its own test policy). No skip plugin
or deselection was used in the full gate; Redis integration tests ran normally.
`ruff check icoda/tests/test_service.py` also passed (`ruff.log`).

Generated extension output/VSIX were moved into `artifacts/`; no new bytecode remains in the repository;
the sample analysis log/cache were preserved/restored. Final source-file hash
comparison and guidance modification-time checks are retained in `final-audit.json`.
Only the three stated files differ from the iteration's starting source snapshot.
The full desktop verifier (real-provider stage), separate real-Tk programs and
historical G14 performance measurements were not rerun; they are not claimed as
new qualification. The brief's optional DAP/live/remote/browser work is unchanged.
