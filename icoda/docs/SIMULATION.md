# ICODA end-to-end development simulation

Date: 2026-09-11 (updated through iteration 56).

The simulation follows the plan's Phase 0 wording: “What the system does with the specification is not to implement
it. It lays out a plan, an architectural overview, and it does not start with the whole architecture, which would be
overwhelming, but with a first simple step.” It then exercises the named first artifact: “Step 0 is always the same:
the project skeleton.” It also retains M3's acceptance wording: “fake-provider tests on the sample project covering
order, approval, batching stop, and status transitions”, plus the design's stronger promise that ICODA “keeps the
developer in the loop at every step”.

The fixture starts as a source-light Python project persisted at `ProjectPhase.SPECIFICATION`. One real `App` session
uses the specification editor's Save control, `StepController`, `StepRunner`, the real Step 0 generator, git worktree
promotion, persisted `ProjectState`, `StepLog`, Python AST analysis for the scripted architecture/implementation
changes, and the established `ScriptedProvider` contract. Build and test outcomes are deterministic fakes; no
provider, API key, network, compiler, or external test process is used. The observed `ProjectPhase` sequence is
`SPECIFICATION → ARCHITECTURE → IMPLEMENTATION`, ending in terminal `IMPLEMENTATION` with queue cursor 2 of 2 and
no target. There are ten stops.

Phase-transition validation belongs to `icoda_core/phases.py:transition`. The sole refusal of a developer code-step
request during `ProjectPhase.SPECIFICATION` belongs to `icoda_core/steps.py:StepRunner.prepare`, because
`icoda_gui/step_controller.py:StepController.propose` calls preparation before proposal generation. That check runs
before `ProjectStore.ensure`, Git initialization, model preparation, and Step 0 logging; `StepRunner.propose` has no
duplicate specification refusal.

| Stop | Phase | Exactly what the developer sees | Exactly what the developer can control | Developer decision | Evidence |
|---:|---|---|---|---|---|
| 01 | `SPECIFICATION` | The `File View` and its source-light `project.py` projection; `Phase: specification`; `Implementation queue: inactive`; all six overview tabs; `Step failed — the project is in the specification phase; save the specification before proposing`; the same refusal in the status bar; `Build: not run`; `Tests: not run`; Binary and Model fields. | All approve/reject gates and the panel's `Propose` control are disabled. Project → Propose Next Step still routes the attempted request through the controller, but the sole `StepRunner.prepare` phase check refuses it before any preparation mutation; Project → Specification… remains available, as do the overview tabs, graph controls, provider fields, undo, and manual-commit controls. | Accept that code cannot be requested during specification and open the specification editor. Persisted phase `SPECIFICATION`, its exact state file, project files, Git state, empty queue, cursor 0, batch size 1, and empty step log remain unchanged. | `sim-01-specification-code-refused.png` |
| 02 | `SPECIFICATION` before Save; `ARCHITECTURE` after Save | The six-page `SpecificationEditor`: Overview, Scope, Use cases, Requirements, Decisions, and Code profile; the valid fixture title; `Validate`, `Save`, and `Close`. | Every specification field and record list, page selection, validation, Save, and Close. `SpecificationEditor.save` is the exact developer-facing exit control; its callback is `App._save_specification`. | Save the specification. The persisted phase is asserted as `SPECIFICATION` immediately before Save and `ARCHITECTURE` immediately after; the queue remains empty and batch size remains 1. The transition is step-log record 0 (`specification → architecture`, `phase_transition`, `specification completed`), and the real Step 0 skeleton is generated. | `sim-02-specification-save.png` |
| 03 | `ARCHITECTURE` | The `Call View` tab; `Phase: architecture`; `Implementation queue: inactive`; proposal title `Step 1: Draft formatter architecture (attempt 1)`; `Build: passed`; `Tests: passed`; the `Source diff` tab with `+class Formatter:`; an editable canonical `Entity summary`; all six overview tabs; Binary and Model fields. | `Request`, `Max entities`, Binary, Model, `Propose`, `Approve`, `Reject…`, `Adapt…`, `Rebuild`, `Open worktree`, undo/manual-commit controls; Project menu equivalents; graph Filter, Neighborhood, Collapse all, navigation, and zoom. | Reject the draft with reason `Keep the public API smaller`. Persisted architecture state and empty queue remain unchanged. | `sim-03-architecture-reject.png` |
| 04 | `ARCHITECTURE` | Revised title `Step 1: Add formatter architecture (attempt 1)`; passed build/test fields; `Delta` with `service.Formatter`, `service.Formatter.normalize`, and `service.main`; `Signature changes: none`; rationale and highlighted proposed call graph. | The same proposal review controls; `Approve` and `Reject…` are live, while `Approve architecture` is disabled until this proposal is decided. The developer may inspect Approach, Delta, Signature changes, editable Entity summary, Source diff, Build, and Tests. | Approve and promote the atomic architecture proposal. | `sim-04-architecture-approve.png` |
| 05 | `ARCHITECTURE` | Refreshed `File View`; `No proposal`; `Build: not run`; `Tests: not run`; `Implementation queue: inactive`; all six overview tabs render the promoted `service.py` model and `Formatter.normalize` has gray `stub` appearance. | `Approve architecture` is the live phase gate; `Propose` can request another architecture step. File/Project/View menus, overview tabs, Filter, Neighborhood, Collapse all, and diagram controls remain available. | Approve the architecture and begin implementation. | `sim-05-architecture-gate.png` |
| 06 | `IMPLEMENTATION` | `Phase: implementation`; `Current target: service.Formatter.normalize — 2 remaining`; batch size 1; persisted queue-scope selector; Approach text `Replace the normalize stub directly and add one focused test.`; no code proposal, Delta, or source diff yet. | `Approve approach`, `Reject…`, and `Adapt…` are live. The developer can edit Request, batch size, queue scope, Binary, and Model and inspect every overview tab. `Propose` code remains gated off. | Approve the prose approach for `Formatter.normalize`. | `sim-06-normalize-approach.png` |
| 07 | `IMPLEMENTATION` | `Class View` with `Formatter.normalize [stub]`; title `Step 2: Implement Formatter.normalize (attempt 1)`; `Build: passed`; `Tests: passed`; `Signature changes: none`; Delta showing the changed method and added `tests.test_service.test_normalize`; Source diff adding `return value.strip()` and the test. | `Approve`, `Reject…`, `Adapt…`, `Rebuild`, and `Open worktree` are live; seven detail tabs expose approach, derived Delta, signature decisions, editable structured summary, actual source diff, build output, and test output. | Approve the build-and-test-gated implementation. The queue advances to cursor 1; refreshed appearance is green `tested`, and Coverage picks up `tests/test_service.py`. | `sim-07-normalize-build-test.png` |
| 08 | `IMPLEMENTATION` | Refreshed `Mind Map`; `Current target: service.main — 1 remaining`; status, requirement, and introducing-step metadata; Approach text `Complete main using Formatter and add its observable result test.` | `Approve approach`, `Reject…`, and `Adapt…` are live; `Propose` code is gated off until approval. Mind-map expansion/history selection, global graph controls, overview tabs, Request, batch size, queue scope, Binary, and Model remain available. | Approve the prose approach for `main`. | `sim-08-main-approach.png` |
| 09 | `IMPLEMENTATION` | `Issues` tab with current rule rows; title `Step 3: Implement main (attempt 1)`; `Build: passed`; `Tests: passed`; `Signature changes: none`; Source diff adding the `ready:` result and `test_main`; persisted queue remains at cursor 1 until approval. | `Approve`, `Reject…`, `Adapt…`, `Rebuild`, and `Open worktree` are live; Delta, signature decisions, editable Entity summary, source diff, separate Build and Tests, every overview, and unchanged global/project controls remain inspectable. | Approve the second build-and-test-gated implementation. | `sim-09-main-build-test.png` |
| 10 | terminal `IMPLEMENTATION` | Refreshed `Coverage`; `Test coverage: 4/4 callables covered · 0 uncovered`; callable/test/evidence rows; `Implementation queue: empty — no unimplemented functions`; `No proposal`; both targets have green `tested` appearance; step-log record numbers are `0, 0, 1, 1, 2, 2, 2, 3, 3`. | No approve/reject gate is live. The developer can inspect all views/history, change graph/view controls, edit the specification, reload, undo the last step, or commit manual edits. | End the session: terminal `ProjectPhase.IMPLEMENTATION`, cursor 2 equals queue length 2. | `sim-10-terminal-overview.png` |

## Explicit gap list against the finishing criteria

The simulated path meets the finishing criteria for this bounded two-function project: the developer can accompany
and control specification completion, every architecture, approach, build/test, approval, rejection, phase, and step-
granularity decision, and an overview surface is available and refreshed throughout. M3.5 now supplies the last
capability on which that control criterion directly depended. Wider plan gaps that do not block this recorded
criterion remain explicit:

- Specification-to-code overview is closed for the M4.2 uncovered-requirement slice:
  `icoda_core/requirement_coverage.py:project` reports every requirement and positional goal against exact existing
  `Entity.satisfies` tags, and `CoverageOverview.show` names implementing entities or marks the item `UNCOVERED`.
  Saving an existing specification now refreshes this section through `App.open_project` → `App.show`; a project
  with no requirements/goals displays an explanatory note. The separate all-view colour mode still means recorded
  test provenance rather than specification-tag coverage, so that wider EVOLUTION highlighting promise remains open.
- Deliberate few-line grouping is **DONE**: `icoda_core/grouping.py:derive` owns the accessor/overload family and Code
  Profile size decision, `StepPanel.grouping_combobox` owns the developer choice, and
  `rules.group_test_coverage` requires reaching recorded evidence for every grouped entity before approval.
- External-edit reconciliation is fully closed: **3a DONE** —
  `icoda/icoda_core/steplog.py:apply_statuses` uses `bodyhash.changed` and
  `StepRecord.entity_body_hashes`, while `icoda/icoda_core/persistence.py:ProjectStore.load_model` reapplies that
  persisted history so an edited tested callable reads back as `implemented` and matching/unrelated entities retain
  their statuses. `icoda_core/node_status.py:derive` consumes that reconciled status and uses
  `steplog.last_entity_body_hashes` only for the stale marker. **3b DONE** —
  `icoda/icoda_core/source_watch.py:snapshot_files` and `changed_files` compare an in-memory frozen snapshot of the
  analysed sources, and `icoda/icoda.py:App._refresh_external_edits` binds root `<FocusIn>` to the existing reload
  and re-analysis path only when that snapshot changes. The App regression shows `python:service:answer` as `tested`
  before an external body edit and `implemented` after the focus event without reopening; unchanged focus performs
  one total analysis call and leaves state, model, and step-log bytes identical. Real Tk acceptance fires the binding
  and observes the edited Python body hash. No persisted field or watcher dependency was added.
- Structured adaptation is **DONE (4a DONE; 4b DONE)**. **4a DONE:**
  `icoda_core/response.py:parse_response` recognizes the exact `diff --git ` discriminator and purely parses
  validated `DiffHunk` data into `FileChange.hunks`; `icoda_core/steps.py:_apply_candidate_files`,
  `_plan_candidate_change`, and `_patched_bytes` apply all hunks against current worktree bytes only after every file
  validates. Patch matching and replacement reuse each target line's own ending, context is reinserted verbatim, and
  a pure insertion uses its adjacent file line, so LF, CRLF, and untouched mixed-ending regions do not depend on
  `os.linesep`. **4b DONE:** each live usable proposal with a response `entities` summary now exposes an editable
  canonical JSON `Entity summary` tab and live `Adapt…` action. The pure `icoda_core/adaptation.py` parser reports
  deterministic ordinary problems and describes the exact edits; `StepController.adapt` sends that description
  through the existing `StepRequest.constraints` → `StepRunner._prompt` → `prompt.build_prompt` → `_feedback`
  channel and replaces the displayed proposal with the re-requested result. If the developer leaves the structured
  summary unchanged, the same Adapt action asks for a free-text instruction and sends it through that one channel;
  Reject instead records a reason, discards the live proposal, and waits for another explicit proposal request.
  Historical records, unusable proposals, and proposals without a structured summary keep Adapt disabled.
- Exact test provenance is **DONE (gap 5)**: the coverage index considers only test identifiers recorded by each
  successful step. `icoda_core/node_status.py:derive` assigns `NodeAppearance.covered` from the matching index
  entry, and `NodeAppearanceCanvas.node_fill` consumes that same value. Model reachability and `@satisfies` alone
  do not make a node green: a step naming no reaching test contributes no evidence, and its entity is shown as
  `No recorded tests` and uncovered in both the Coverage tab and coverage colours. At stop 10 the actual
  implementation records still credit `tests/test_service.py`, while architecture step 1 no longer does.
- Python Code Profile, skeleton, and gate integration is **DONE (gaps 6a, 6b, and 6c CLOSED)**: language detection selects concrete Python 3.12, pytest,
  test-file/source-extension, and module/class/function naming defaults for a new Python specification; the editor
  presents and persists them, and architecture/implementation prompts use Python module, stub, docstring, and test
  rules without C++ header/source wording. The approved profile also drives the generated source/test paths and
  module/class/function names; the resulting Python skeleton round-trips through `python_analysis.parse_project`.
  `icoda_core/steps.py:gate_commands` gives that skeleton a real whole-tree Python byte-compilation gate and derives
  its targeted test command from the same profile's test runner. A profile-less legacy specification still loads
  the unchanged C++ default. Gap 6 is closed in full; the existing simulation intentionally retains its injected
  deterministic fake gates. Gap 7's release evidence is reconciled separately in `GAP_ANALYSIS.md` and
  `RELEASE_MATRIX.md`.
- Gap 7A Linux verification is **DONE at its 90.00% closure measurement**: both `icoda/verify.bash` and
  `icoda/tests/verify.py` are green on this host,
  the sample is built with an automatically discovered module-capable Clang before coverage tests consume its
  compile database; the latest measured tested-branch coverage is 90.22% against the unchanged 85% threshold. Gap
  7B's matrix obligation is done while Windows and macOS remain explicitly unqualified and unmeasured. Gap 7C1
  migration/recovery qualification is done including developer-visible phase display. Gap 7C2's measurement and
  `coverage_index.build_index` defect are closed; its three named material-growth defects remain open but do not
  block the 4.389153-second summed overview against the 10.0-second interactive interpretation.

Iteration 24 audited the refusal ownership exposed by the extended run. `StepController.propose` calls
`StepRunner.prepare` before `StepRunner.propose`, and preparation is the first mutation-capable core operation.
Therefore `StepRunner.prepare` retains the sole specification refusal, now before even `ProjectStore.ensure`, while
the later duplicate in `StepRunner.propose` is removed. `test_specification_refusal_precedes_prepare_mutations`
directly proves the exact error and unchanged persisted state bytes, step-log records, complete project-file
snapshot, and Git repository identity. With that guard temporarily absent, the test fails because preparation
appends the Step 0 skeleton record before the later refusal.

Iteration 25 closes direct queue selection and manual batch scope without adding auto-approval.
`implementation_queue.scope_targets`, `implementation_queue.select_scope`, and
`implementation_queue.override_target` own deterministic expansion/reordering over the derived model and frozen
`ProjectState`; `ProjectState.implementation_scope` and `ProjectState.implementation_override` persist the choices
with legacy defaults. `StepPanel.scope_combobox` dispatches through the existing controller, and
`StepController.implement_here` persists the selected callable before invoking the existing two-round path.
`App.graph_actions` now enables “Implement this function” for any pending remaining callable. The real-App
regression proves that selecting a non-head callable changes the persisted head/override, provider request target,
and approach `StepRecord.batch`; `implementation-queue-override.png` shows the scope control and overridden target.

Iteration 27 closes the signature-decision gap. `icoda_core/steps.py:SignatureChange`,
`Delta.signature_changes`, and `compute_delta` compare the current project model with the proposal model and retain
unambiguous rename continuity through the existing body-hash path. `StepPanel.signature`,
`StepPanel.confirm_signature`, `StepController.confirm_signature`, and `StepController.approve` show both
declarations and refuse approval until the developer confirms the current proposal. The refusal precedes runner
creation and every persisted-state, step-log, worktree, promotion, build, test, and cursor mutation. Confirmation is
deliberately proposal-local: no `ProjectState` or `StepRecord` field was added. The simulation's stub implementations
do not alter signatures, so its two specification stops and terminal iteration list
`[0, 0, 1, 1, 2, 2, 2, 3, 3]` remain unchanged. Stub tests prove the classification, exact action sets, refusal, and
cursor advancement; the completed real-Tk `signature-confirmation.png` proves the new tab and reachable control.

Iteration 29 closes bounded auto-approval without changing the ten manual stops above. The frozen
`icoda_core/auto_approve.py:Decision` and pure `derive` own every classification. The persisted
`ProjectState.auto_approve` switch defaults off, and `StepPanel.auto_approve_check` routes its changes through
`StepController.auto_approve_changed`. A green implementation code proposal may commit automatically; the controller
then requests the next approach and stops visibly because architecture and approach decisions remain developer-owned.
After that approval, automation resumes for the code proposal. The Tk-stub controller regression automatically
approves two green code proposals and advances the cursor by exactly two, then exposes the exact failing-test reason
without advancing or writing another code record. The real-Tk `auto-approve.png` proves the reachable checkbutton.
Because the switch defaults off, the simulation's two specification stops and terminal iteration list
`[0, 0, 1, 1, 2, 2, 2, 3, 3]` are unchanged.

Iteration 32 closes external-edit trigger gap 3b without changing the ten manual stops. The snapshot is held only
in memory by `App`; `<FocusIn>` checks only files in the currently analysed model and calls the existing `reload`
path only when `source_watch.changed_files` reports a difference. The Tk-stub App regression proves both the
`tested → implemented` overview refresh after an external edit and the byte-identical no-op case. The real-Tk
acceptance fires `<FocusIn>` on Xephyr and proves the binding publishes the edited body. The simulation's two
specification stops and terminal iteration list `[0, 0, 1, 1, 2, 2, 2, 3, 3]` remain unchanged.

Iteration 33 closes parsing/application gap 4a without changing any widget or developer-visible stop. A response
file whose `content` begins exactly with `diff --git ` now carries validated unified-diff hunks; StepRunner applies
them to the current candidate bytes through the same worktree path used by full-file replies. A real-StepRunner
regression proves equivalent diff/full replies produce identical `service.py` bytes and equal `Delta` values, and a
second regression proves stale context leaves both candidate files byte-identical. Gap 4b remains the editable
structured-summary surface in `StepController.adapt` / `StepPanel`. The simulation's two specification stops and
terminal iteration list `[0, 0, 1, 1, 2, 2, 2, 3, 3]` did not change.

Iteration 34 repairs gap 4a's platform-dependent newline handling without changing any widget or developer-visible
flow. The real StepRunner now matches each context/removed line using the target file line's ending, preserves
context verbatim, and gives added replacements the ending of the line they replace; adjacent target lines supply the
ending for pure insertions. Tests cover simulated Windows `os.linesep` against an LF file, a genuine CRLF file, and
untouched lines in a mixed-ending file. A non-applying diff is fed to the next attempt as the exact
`validation_error` with empty `build_errors`, because file application failed before build could run. The simulation's
two specification stops and terminal iteration list `[0, 0, 1, 1, 2, 2, 2, 3, 3]` did not change.

Iteration 36 closes gap 4b. At each scripted live code proposal, the optional response `entities` now appears in an
editable `Entity summary` tab in canonical JSON; `Adapt…` parses the developer's correction and requests the same
step again through the existing hard-constraint feedback channel. The real-App regression edits a function's
signature and requirement list, proves the exact instruction in the second `ScriptedProvider` prompt, and proves
that `Add configurable answer` replaces `Add fixed answer` in the panel. Historical records and absent, failed, or
entities-free proposals keep structured adapt disabled. The ten scripted stops and their `sim-01` through `sim-10`
screenshots did not change because this capability adds an available control without inserting another lifecycle
decision; their terminal iteration list remains `[0, 0, 1, 1, 2, 2, 2, 3, 3]`. The separate real-Tk evidence is
`icoda/.icoda-test-artifacts/iteration-36-structured-adaptation/structured-adaptation.png`.

Iteration 37 repairs the missing free-text half of the live Adapt decision and re-proves gap 4b. An unchanged
structured summary now opens the existing hard-constraints dialog; semicolon-separated text joins structured edits
at the same `StepRequest.constraints` boundary and reaches the same single provider call site. The ten scripted stops
and their screenshots did not change, and the terminal iteration list remains
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`. Fresh real-Tk evidence is
`icoda/.icoda-test-artifacts/iteration-37-structured-adaptation/structured-adaptation.png`.

Iteration 39 re-proves gap 5 at the diagram boundary. The focused GUI regression gives one callable model-level
test reachability with no successful record naming that test and gives another callable a reaching test named by a
successful record; coverage mode renders the first red/uncovered and the second green/covered. The obsolete
`NodeAppearance.specification_covered` input was removed because iteration 38 left it with no consumer. This does
not change the ten stops: terminal iterations remain `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and the
queue display contains `empty`.

Iteration 40 closes gap 6a without changing the ten scripted stops. `default_code_profile` now returns a concrete
Python profile when `detect_language` selects Python, the specification editor presents and persists every Python
test/file/naming field, and the phase prompts emit Python-specific architecture and implementation rules. Existing
profile-less specifications retain the C++ default. The separate real-Tk `python-code-profile.png` proves the
visible values. Terminal iterations remain `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and the queue
display contains `empty`; no simulation assertion changed. Gap 6b (generator) and 6c (real commands) remain open.

Iteration 42 re-verifies gap 6a without production or simulation-assertion edits. Mutation tests prove that legacy
profile loading depends on `specification.upgrade` supplying the unchanged C++ profile and that Python architecture
prompts depend on the language branch. The focused lifecycle/Python/editor run remains green, and real Tk again
shows all seven Python test/file/naming values. The ten-stop terminal list remains
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and the queue display contains `empty`. Gap 6 is narrowed
exactly to Python generator skeletons (6b) and real Python build/test commands (6c).

Iteration 43 closes gap 6b without changing the ten scripted stops. `generator.skeleton_files` has one language
decision and consumes the approved Code Profile's source extension, module/class/function naming, test framework,
test runner, and test-file convention. `App._save_specification` supplies that existing mapping through the new
optional generator parameter; omitted and explicit C++ profiles retain the existing C++ files and bytes. The
generated `src/demo_service.py` and `tests/test_demo_service.py` parse back into the expected four Python USRs.
Terminal iterations remain `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and the queue display contains
`empty`; no simulation assertion changed. Gap 6 is narrowed exactly to real Python build/test commands (6c).

Iteration 45 closes gap 7A without changing the ten scripted stops. `StepRunner` still uses the injected deterministic
fake build and test callables, so the simulation terminal iterations remain `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor
2, gate `none`, and `queue_var` containing `empty`; no simulation assertion was edited. Separately, the real Linux
verification entry points select the installed module-capable Clang, build and test the sample before coverage,
analyse it without stale messages, validate all 32 real-Tk screenshots, and report 90.00% tested-branch coverage.

Iteration 46 closes gap 7C1 without changing the ten scripted stops or their deterministic fake gates. A materialised
legacy specification, workflow state, and derived model prove that every older value remains exact while absent
additive fields receive their documented defaults. A separately materialised interrupted run proves that truncated
workflow state is refused with a usable error rather than replaced by an empty project, and that the leftover
proposal worktree is reported and preserved for inspection. Terminal iterations remain
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and `queue_var` containing `empty`; no simulation assertion was
edited. Gap 7C2 large-project performance qualification and gap 7B platform qualification remain open.

Iteration 47 strengthens that closed gap 7C1 qualification without changing the simulated project or any simulation
assertion. The App now reports truncated-state refusal through its existing status/dialog path rather than allowing a
Tk callback traceback; a valid state plus `.icoda/worktree` reopens with a preservation notice, and `ensure()` is
pinned not to alter unreadable state bytes. The terminal iterations remain `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2,
gate `none`, and `queue_var` containing `empty`; gap 7C2 and gap 7B remain open.

Iteration 48 qualifies the developer-visible phase after a successful open without changing production code, the
simulated project, its deterministic fake gates, or any simulation assertion. A materialised non-default
`implementation` state passes through `App.open_project` and `_poll`; the existing `App.show` successful-result path
uses `implementation_queue.ensure_state` and `StepPanel.set_phase` to show `Phase implementation`. The regression
test was green-first. Terminal iterations remain `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and
`queue_var` containing `empty`; gap 7A remains done at its 90.00% closure measurement (latest exercised result
90.08%), gap 7C1 remains closed, and gap 7C2 and gap 7B remain open.

Iteration 52 re-runs the ten-stop real-Tk acceptance in the shared final evidence directory. Its first two fresh
attempts exposed that stop 02 persisted `ARCHITECTURE` but could still display `specification` until the asynchronous
reload completed. `App._save_specification` now publishes the just-persisted architecture phase through
`StepPanel.set_phase` before starting that reload. The final real-Tk run passes all unchanged assertions and retains
the deterministic fake gates, terminal iterations `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and
`queue_var` containing `empty`.

Iteration 53 adds the focused `test_save_specification_publishes_architecture_phase_before_reload` guard. It drives
`App._save_specification` with asynchronous reload stubbed, passes with the iteration-52 publication line restored,
and fails with `specification` versus `architecture` when that line is temporarily removed. The fresh real-Tk replay
again passes all unchanged assertions with deterministic fake gates, terminal iterations
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and `queue_var` containing `empty`.

Iteration 54 adds the specification requirements section to the existing Coverage tab without changing tab order or
the scripted lifecycle. The pure projection treats only an exact requirement identifier in an entity's existing
`@satisfies` tags as implementation evidence; schema-v2 goals use their positional `G-1`, `G-2`, … identifiers.
The GUI repaint test saves a new `R-2`, routes through the existing open/show path, and observes it as `UNCOVERED`
beside covered `R-1`. Real Tk adds `requirements-coverage.png`, bringing the general capture count from 32 to 33.
The ten simulation captures, deterministic fake gates, terminal iterations
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and `queue_var` containing `empty` are unchanged; no simulation
assertion was edited.

Iteration 55 adds deliberate few-line grouping without changing the scripted lifecycle. The persisted selector
defaults to `One entity`, so every simulated implementation request and commit remains one queue entity. Selecting
`Few-line group` previews only an adjacent getter/setter family or overload set accepted by the Code Profile's
per-function and total line budgets. Group review names every member, and the code proposal and approval paths require
recorded reaching test evidence for each member through the existing coverage index. Real Tk adds
`few-line-grouping.png`, bringing the general capture count from 33 to 34. The ten simulation captures, deterministic
fake gates, terminal iterations `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and `queue_var` containing
`empty` are unchanged; no simulation assertion was edited.

Iteration 56 adds cluster-only Pin cluster, Unpin cluster, and Rename cluster actions to the existing shared
right-click menu without adding a lifecycle decision. Pin and rename edits use the existing `.icoda/layout.json`;
pinning is off when `Layout.pins` is empty, which remains the default. The shared repaint publishes renamed cluster
labels to File View, the Call/Class hierarchy, and Mind Map. M1.7's Louvain fallback remains open. The ten simulation
captures, deterministic fake gates, terminal iterations `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and
`queue_var` containing `empty` are unchanged; implementation grouping still defaults to one entity per step and no
simulation assertion was edited. Real Tk adds `cluster-pin-rename.png`, bringing the general capture count from 34
to 35.
