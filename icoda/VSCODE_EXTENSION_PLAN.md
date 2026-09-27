# ICODA VS Code extension: implementation brief and goals

Prepared: 2026-09-27. Status: specification for future implementation; extension goals below are not yet marked complete.

This document is addressed to the LLM implementing the change. Paths are relative to the `icoda/` directory of the AI-Loop repository unless stated otherwise. The current development checkout is `C:\data\GitHub\AI-Loop\icoda`; do not hard-code this machine-specific path into the extension.

## 1. What the user wants

Turn ICODA into a usable Visual Studio Code extension so that developers can analyse their project, inspect its architecture, follow source locations, record and step through function calls, and use ICODA's development workflows inside VS Code.

The extension should become a proper frontend for ICODA. It must do real work against the opened project: show the actual analysis and trace, open the actual source, and invoke the existing build and development operations. A launcher that merely opens the separate Tkinter application does not meet this objective.

Reuse ICODA's existing Python engine wherever practical. Build the VS Code integration around it, replacing the desktop presentation layer for extension users. Preserve the standalone desktop application during the migration.

The user has specifically established these interaction requirements:

- Function tracing concerns the recorded calls of the executable selected in ICODA.
- Stepping must navigate function calls rather than displaying returns as separate stops.
- Step Into provides the forward navigation previously provided by Next Call. The redundant Next Call button has been removed and must stay removed.
- With B selected after A called B: Step Into enters B's next call; Step Over selects A's next call after B; Step Out selects the next function after A returns. Section 5 gives the exact acceptance example.
- Call View controls should share a compact horizontal row to save vertical space.
- A large project such as ViennaVulkanEngine must initially show a useful overview of larger gray clusters instead of an unreadable display of every file.
- If a referenced source file exists elsewhere in the project, ICODA should find it. A stale file path must not cause a misleading provider/executable diagnosis in Prompt.
- Installed tools must be discovered even when they are absent from the ordinary process PATH. This includes the CMake, Ninja, and Clang tools bundled with Visual Studio on Windows.

These requirements are the behavioral baseline for the extension. Preserve the fixes already implemented in the desktop application.

## 2. Scope and decision authority

Distinguish the following categories when implementing this brief:

| Category | Meaning |
|---|---|
| Confirmed product requirements | The objective and interaction requirements in section 1, including the tracing example in section 5. |
| Recommended implementation defaults | A TypeScript extension, a Python backend process, webviews for diagrams, native VS Code editors, and the staged goals below. These are the proposed migration design, not separately dictated technology choices from the user. |
| Existing behavior to preserve | Source analysis, project state, target selection, development workflows, and review gates found in the current implementation and documentation. Audit these instead of assuming every historical plan describes the current application accurately. |
| Optional later work | Native Debug Adapter Protocol integration, live debugging, browser-only VS Code, and remote-host qualification. These must not delay the initial desktop extension. |

The first useful milestone is Call View plus native source navigation and recorded-trace stepping. The overall migration should then cover ICODA's existing workflows. Finishing a prototype is not evidence of full feature parity.

This task does not require rewriting the Python engine in TypeScript, replacing libclang, inventing a new trace format, building another text editor, or adding dependencies on the sibling AI-Loop runner or Redis.

## 3. Inspect and reuse the current implementation

Read the applicable `AGENTS.md`, `README.md`, `HANDBOOK.md`, `ICODA_PLAN.md`, `EVOLUTION.md`, and release/verification documents before implementation. Resolve stale historical descriptions by inspecting current code and tests. Record the starting commit and working-tree changes.

The inspected checkout already separates much of the engine from Tkinter. In the following table, bare Python filenames refer to `icoda_core/`; GUI locations carry explicit paths.

| Existing area | Starting points | Migration treatment |
|---|---|---|
| Project/session orchestration | `icoda_core/session.py`, `persistence.py` | Reuse project opening, analysis results, and state; expose them without importing the GUI. |
| Source analysis | `analysis.py`, `python_analysis.py`, `windows_analysis.py` | Reuse C++ and Python analysis. Preserve compiler-aware parsing and analysis diagnostics. |
| Shared model | `icoda_core/model.py` | Reuse entity identities, source references, edges, and existing JSON serialization. |
| Diagram layout and grouping | `views.py`, `clusters.py`, `grouping.py`, `diagram_partition.py`, `force_layout.py`, `expansion.py` | Reuse layout and grouping calculations where feasible; port drawing and interaction to the webview. |
| Recorded calls | `call_trace.py` | Reuse trace loading, symbol resolution, repeat aggregation, and playback; keep one implementation of stepping semantics. |
| Builds and recording | `executables.py`, `cmake.py`, `instrumentation.py`, `toolchain.py`, `process.py` | Reuse target discovery, scoped models, build environments, instrumentation, and process management. |
| Source lookup | `source_edit.py`, `source_watch.py` | Reuse path resolution and change detection as appropriate; use VS Code to edit documents. |
| Specification and evidence | `specification.py`, `requirement_coverage.py`, `coverage_index.py`, `rules.py` | Expose the existing results and validation through extension views. |
| AI development workflow | `agent.py`, `prompt.py`, `steps.py`, `adaptation.py`, `implementation_queue.py`, `recovery.py`, `steplog.py` | Reuse provider invocation, proposals, gates, queue state, and history. |
| Desktop controllers | `icoda.py`, `icoda_gui/step_controller.py`, `icoda_gui/tasks.py` | Extract only the application operations needed by both frontends; replace Tk callbacks and dialogs at the boundary. |
| Desktop presentation | `icoda_gui/graph_canvas.py`, `call_view.py`, other view modules | Use as behavior references. Reimplement the presentation with web technologies and native VS Code controls. |

Names in the table are a navigation aid, not a claim that every module is already a service API. In particular, Tkinter-bound orchestration must be separated carefully instead of instantiating `App` inside the backend.

## 4. Recommended architecture

```text
VS Code native editor, commands, settings, progress, and output
                         |
                 TypeScript extension
                    /           \
       webview messages       structured process messages
                /                 \
       diagram webviews        Python backend process
                                     |
                              existing icoda_core
                                     |
                    source, .icoda state, toolchain, providers
```

### Extension responsibilities

Manage activation, workspace selection, backend lifecycle, commands, settings, progress, and VS Code document navigation. Own native editor and diff integration. Translate user actions into backend operations and render the resulting state.

Use native VS Code facilities where they fit: editor tabs for source, output channels for logs, progress notifications for long operations, and native lists/trees for simple structured information. Use webviews for the File, Call, Class, and Mind Map diagrams because their interactive graph presentation is central to ICODA. The official [Webview API](https://code.visualstudio.com/api/extension-guides/webview) supports custom HTML views and message passing.

### Backend responsibilities

Run analysis, layout calculations, trace playback, builds, and provider workflows outside the extension host's UI work. Own the authoritative project and playback state. Provide a headless entry point that works without Tkinter or a display server.

A TypeScript frontend with a Python service is a supported general extension architecture; Microsoft's [Python extension guidance](https://code.visualstudio.com/api/advanced-topics/python-extension-template) provides a related example. It does not mean ICODA must become a language server. Prefer a small, versioned JSON request/response interface over standard input/output unless inspection identifies a concrete reason for another transport.

### Service contract

Design the contract before connecting a complete UI. Document and test:

- Protocol and backend versions, startup handshake, and supported capabilities.
- Request IDs and responses that distinguish success, cancellation, and failure.
- Explicit project/session identity and selected executable/library identity.
- Model revision IDs so late analysis results cannot overwrite a newer project or selection.
- Progress and state notifications separate from responses.
- Stable entity IDs, workspace-relative source paths, source-root identity, line numbers, and trace position.
- Playback availability flags computed by the backend, including whether Into, Over, Out, Previous, and Reset are available.
- Structured errors that separate missing source, missing tool, invalid trace, failed analysis, provider failure, and failed build/test checks.
- Cancellation and timeout behavior, including completion of pending requests when the backend exits.

Reserve stdout for framed protocol messages; send diagnostic logs through stderr or explicit log notifications. Specify UTF-8 encoding and framing. Do not parse arbitrary console output as the protocol or add a local HTTP server merely to exchange messages.

Suggested initial operations are `initialize`, `project.open`, `project.analyse`, `targets.list`, `target.select`, `view.get`, `source.resolve`, `trace.load`, `trace.step`, `trace.reset`, and `operation.cancel`. These are proposed names, not existing methods. Expose build and AI operations when their milestones are implemented.

Use argument arrays when launching processes. Honor [VS Code Workspace Trust](https://code.visualstudio.com/api/extension-guides/workspace-trust) for operations that execute project tools or agents. Validate webview messages at the extension boundary and use a content security policy. These are integration requirements, not reasons to add repeated confirmation dialogs to ordinary navigation.

## 5. Exact tracing contract

### Recorded playback

This feature navigates recorded function calls from the selected executable. It does not, by itself, pause a live process, inspect variable values, or step source statements. Label it as trace playback.

The existing trace includes entry/exit events and per-thread depth. Keep that information in the backend to determine where to jump, but display function calls as the selectable stops. Never animate returns as extra forward-navigation steps.

### Authoritative example

Suppose the recording represents this program structure and execution order:

```text
main
  A
    B              <-- currently selected, reached by stepping into B from A
      C
    D
  E
```

Equivalently, `main` calls `A`, `A` calls `B` and then `D`, `B` calls `C`, and `main` calls `E` after `A` returns.

Each row below starts independently with B selected:

| Action | Destination | What is skipped |
|---|---|---|
| Step Into | C | Nothing before B's next eligible call. |
| Step Over | D | The remainder of B, including C and any deeper descendants. |
| Step Out | E | The remainder of A, including the rest of B and the later call to D. |

This is the user's requested function-call navigation. Do not reinterpret Step Out from B as selecting A's return event, and do not implement Step Over as displaying B again after one child returns.

### Boundary behavior and compatibility

- Step Into retains the previous Next Call behavior for ordinary forward navigation, including resolved-call filtering, consecutive-repeat aggregation, call counters, and highlighting.
- If a selected function has no further eligible nested call, Into proceeds to the next eligible recorded call. It must not get stuck on a leaf or insert a return stop.
- In a normal complete trace, Over chooses the next eligible call at the same or a shallower depth; Out chooses the next eligible call at a strictly shallower depth. Use matching invocations and returns to establish that the required scope has actually ended.
- Preserve the current thread policy during the migration: Into follows the recorded global call order, while Over and Out restrict their depth search to the selected call's thread. The example above is single-threaded. A new thread-filtered mode would be a separate, explicitly presented behavior change.
- Preserve repeat counts and caller-edge counts. Do not silently replace grouped playback with a different sequence of visible stops.
- Account for recursion and interleaved threads using invocation identity, not function name alone. Repeat grouping must not manufacture an incorrect jump.
- Ignore unresolved functions as visible destinations while retaining available stack information for navigation. Explain when no project functions could be resolved.
- An incomplete trace must not cause a guessed return or a jump into an unrelated invocation. Disable a depth-based action when its required return or destination cannot be established.
- At the end, leave the last selected call visible and disable unavailable forward actions. Reset clears the selection and returns to the beginning. Previous Call navigates backward through the existing grouped-call sequence.
- Selecting a trace call updates the graph and the corresponding source location together. Preserve the graph root and the user's zoom/pan instead of rebuilding the view around each selected function.

Use the existing `CallPlayback` and tests as the starting point. The example and boundary rules above are the acceptance contract. If an edge case requires a core correction, add a failing regression case and fix the shared Python implementation; do not introduce different stepping rules in TypeScript.

Keep Load Trace, Previous Call, Step Over, Step Into, Step Out, and Reset in one compact toolbar when space permits. Use an overflow mechanism on narrow panels instead of multiple permanent button rows. Do not restore Next Call.

## 6. Detailed goals

All goals start unchecked. Mark a goal complete only when its acceptance evidence exists. The scope and dependency choices below form the recommended implementation plan.

### G01 — Establish the baseline and feature inventory

- [ ] Record the checkout, existing modifications, working launch commands, Python environment, and relevant verification instructions.
- [ ] Inventory the desktop features and map each to reuse, extraction, extension implementation, or a documented later milestone.
- [ ] Identify Tkinter imports and callbacks that prevent headless reuse; avoid a broad cleanup of unrelated code.
- [ ] Record reproducible existing test failures separately from migration regressions. Historical pass counts and platform qualification are not current evidence.

**Acceptance:** a feature/parity matrix and a reproducible baseline report exist, and implementation can proceed without losing existing changes. Inspect `tests/test_call_trace.py`, `test_trace_stepping.py`, `test_executable_selector.py`, `test_instrumentation.py`, and the view tests.

### G02 — Create a working extension scaffold

- [ ] Add an extension package, preferably under `vscode/`, with TypeScript compilation, a manifest, activation rules, and development-host configuration.
- [ ] Add discoverable ICODA commands, an output channel, and an initial view/container.
- [ ] Start only the services needed by the invoked feature; handle opening VS Code with no workspace.
- [ ] Define a supported VS Code engine version based on APIs actually used.

**Acceptance:** the extension loads in an Extension Development Host, its commands are discoverable, and activation/deactivation is clean. This goal alone is not a usable ICODA migration.

### G03 — Expose a headless Python service

- [ ] Add the versioned service entry point and protocol described in section 4.
- [ ] Expose project opening, model retrieval, source resolution, and playback without creating a Tk root or importing GUI modules.
- [ ] Use explicit service state rather than emulating the desktop `App` object with placeholder widgets.
- [ ] Cover malformed messages, unknown methods, cancellation, startup failure, backend exit, and protocol-version mismatch.

**Acceptance:** a small client can open a fixture project, obtain its model, load a trace, and execute the B-to-C/D/E example without a GUI. Protocol output remains valid when backend operations produce logs.

### G04 — Make runtime and toolchain discovery reliable

- [ ] Provide settings for the ICODA Python runtime and relevant tool/provider overrides; make the effective paths inspectable.
- [ ] Reuse existing discovery before reporting a tool as missing. On Windows, initialize the Visual Studio environment and discover bundled CMake, Ninja, Clang, and symbolization tools as appropriate.
- [ ] Preserve project compiler/dependency settings and supply discovered environments to child processes without modifying the user's global PATH.
- [ ] Distinguish capabilities: a missing build tool must not prevent viewing an available model or trace. A missing provider must not prevent ordinary source navigation.
- [ ] Document dependency installation instead of silently installing or upgrading tools during activation.

**Acceptance:** launch VS Code from an ordinary Windows desktop session, outside a developer prompt, and use the installed Visual Studio tools successfully. Missing-tool messages identify the actual missing tool and actionable configuration.

### G05 — Open and analyse workspace projects

- [ ] Open the selected workspace folder using existing C++/Python analysis and `.icoda` state.
- [ ] Make project selection explicit in a workspace with several folders; do not accidentally analyse or write to a different root.
- [ ] Reuse compilation database discovery, target discovery, stale-model handling, and project persistence.
- [ ] Keep Whole Project, executable, and library selections consistent across views, builds, and trace operations.
- [ ] Preserve uncertainty in dynamic call analysis and existing external-dependency distinctions.

**Acceptance:** representative C++ and Python projects produce the expected entities and edges. Target changes affect the correct views without mutating the underlying whole-project model. Failed analysis leaves any retained model clearly marked stale.

### G06 — Use VS Code's editor and robust source lookup

- [ ] Selecting a file, class, or function opens/reveals the correct VS Code document and source line with intentional focus behavior.
- [ ] Resolve stale paths through the existing project-scoped source lookup before failing. Preserve its treatment of ambiguity and path boundaries.
- [ ] If there is one unambiguous relocated match, navigate to it. If there are several equally plausible matches, present a file choice instead of guessing. If there is no match, report a source-location problem locally.
- [ ] Resolve relative paths against the appropriate project or proposal-worktree root, including generated build sources where applicable.
- [ ] Respect unsaved VS Code documents. Debounce reanalysis after saves and mark results stale when their source version no longer matches.

**Acceptance:** clicking a moved source file finds the file, duplicate basenames are handled correctly, and an actually missing file never triggers the generic provider/Binary recovery workflow. Navigation does not overwrite unsaved buffers.

### G07 — Deliver an interactive Call View

- [ ] Render the current layered call graph using shared model/layout data, with entry-point and library-root behavior preserved.
- [ ] Support selection, source navigation, depth/caller controls, filtering, zoom, pan, fit, and useful tooltips.
- [ ] Preserve recursion/shared-call edges, uncertainty indicators, statuses, and proposal-added/changed markings.
- [ ] Include trace-observed functions that are absent from a statically reachable path using the existing behavior as reference.

**Acceptance:** a real analysed project is navigable entirely inside VS Code; selecting calls opens the corresponding source. Navigation and trace selection preserve the chosen root and viewport.

### G08 — Deliver recorded-trace stepping

- [ ] Load existing ICODA traces and resolve symbols using the shared backend.
- [ ] Connect the six-button toolbar listed in section 5, with availability and status supplied by the backend.
- [ ] Implement and verify every tracing rule in section 5, especially B → C/D/E.
- [ ] Keep counters, repeat-edge annotations, graph selection, and editor location synchronized after stepping, seeking, Previous Call, and Reset.

**Acceptance:** the extension passes the tracing acceptance cases in section 8, and the actual VS Code UI demonstrates the expected destinations. A Tk-stub test does not establish VS Code UI acceptance.

### G09 — Build, run, and record from VS Code

- [ ] Expose target refresh, build, run, test, and instrumented-recording operations backed by the existing implementation.
- [ ] Use output/progress integration with working cancellation and diagnostics tied to the actual project and target.
- [ ] Preserve isolated instrumented-build directories and ordinary build configuration.
- [ ] Make the resulting trace available for Call View playback, showing which executable and recording it belongs to.

**Acceptance:** compile and run a real small C++ fixture, produce a nonempty trace, and step it in the extension. Build/run errors and cancellation leave the extension usable and do not damage the normal build tree.

### G10 — Port the File View and clustered overview

- [ ] Reuse current grouping, expansion, partitioning, and layout behavior.
- [ ] Start large projects with readable higher-level gray cluster boxes where required; do not require Organise before the overview works.
- [ ] Support expanding a cluster, navigating into it, returning to the overview, and revealing a selected file.
- [ ] Preserve meaningful relationship summaries, cluster labels, pinning/renaming behavior, and applicable saved layout state.
- [ ] Keep navigation responsive by rendering the visible level of detail instead of forcing every file and edge onto the screen.

**Acceptance:** ViennaVulkanEngine, when available, opens with useful large groups, and users can reach individual source files through those groups. A smaller fixture covers the same behavior in automated tests.

### G11 — Port Class View, Mind Map, Issues, and Coverage

- [ ] Preserve class members, inheritance/composition/usage relationships, and class grouping.
- [ ] Preserve the Mind Map hierarchy, expansion state, requirements/status information, and step provenance.
- [ ] Expose advisory findings and navigable source locations through appropriate native or custom views.
- [ ] Preserve the distinction between requirement traceability and recorded structural test reachability; do not relabel either as measured runtime code coverage.

**Acceptance:** representative fixture results agree with the shared core and the desktop application. Each supported item opens the correct source or history record, and empty states explain what is missing.

### G12 — Bring specification and AI interactions into VS Code

- [ ] Expose the current specification schema, validation, Code Profile, and project phase transitions.
- [ ] Support installed provider/model selection and the existing provider authentication approach.
- [ ] Preserve the architecture and implementation-approach workflows, implementation queue, context selection, progress, and cancellation.
- [ ] Audit and migrate the existing purpose-comment workflow and its idle/unsaved-file/proposal safeguards; keep it separate from foreground navigation and conversations.
- [ ] Give provider failures their own diagnostics; do not route unrelated navigation failures into LLM recovery.

**Acceptance:** a configured provider can complete a representative proposal workflow in the extension, while source/graph browsing still works without a configured provider. Use controlled fixtures for automated tests and retain separate evidence for any real-provider run.

### G13 — Preserve proposal review, build/test gates, and Git behavior

- [ ] Keep generated proposals in their intended isolated worktrees and show candidate source from the correct root.
- [ ] Use VS Code's diff/editor facilities to review source changes alongside entity/API changes and build/test output.
- [ ] Preserve existing approval, rejection, adaptation, automatic-approval settings, signature confirmations, and failure gates rather than bypassing them during the port.
- [ ] Preserve history, approval commits, manual-edit recording, and supported undo conditions.
- [ ] Revalidate approval evidence when candidate files or relevant unsaved editor state change.

**Acceptance:** a failed proposal cannot be approved through an alternate UI path; a valid reviewed proposal can be applied through the existing workflow. Dirty trees, unsaved edits, and stale proposal evidence remain protected.

### G14 — Handle lifecycle, concurrency, and large projects

- [ ] Keep analysis and other long operations off the extension host's synchronous interaction path.
- [ ] Discard stale results after project/target switches and prevent duplicate sessions or concurrent writers from corrupting project state.
- [ ] Dispose of listeners, watchers, webviews, and owned processes on close, restart, cancellation, and deactivation.
- [ ] Restore selected target, appropriate view state, and persisted settings when reopening a project.
- [ ] Measure startup, analysis, graph update, and stepping behavior on fixtures and a larger project; set and document performance budgets from that baseline.

**Acceptance:** project switching and cancellation under load produce no cross-project results or orphaned owned processes. VS Code remains interactive during analysis. Record measurements rather than claiming untested scale or responsiveness.

### G15 — Make the extension feel integrated and compact

- [ ] Use VS Code theme colors and legible typography, including high-contrast support where supported.
- [ ] Keep the compact trace toolbar; do not reintroduce the removed Next Call button or waste diagram space with permanent stacked control rows.
- [ ] Make command names, enabled/disabled states, progress, empty states, and errors understandable without reading backend internals.
- [ ] Provide keyboard access and scoped shortcuts that do not steal normal editor input or another debugger's bindings.
- [ ] Verify behavior at narrow and wide panel sizes and common Windows display scaling.

**Acceptance:** screenshots from the actual extension show unclipped controls, readable diagrams, and synchronized editor selection. Test light/dark themes and keyboard operation; document any remaining accessibility limitation.

### G16 — Establish automated and manual verification

- [ ] Retain relevant Python tests and add meaningful regressions for extracted service operations and corrected behavior.
- [ ] Add protocol contract tests and TypeScript tests for backend lifecycle, commands, and state routing.
- [ ] Add Extension Development Host integration tests for navigation, trace commands, and workspace handling.
- [ ] Keep small C++/Python fixtures and trace fixtures for deterministic tests, plus a real instrumented-build check.
- [ ] Run the repository's applicable verification gates. Separate known failures, missing prerequisites, and skipped checks from passing evidence.

**Acceptance:** publish reproducible commands and results for each implemented milestone. No release claim may be based only on mocked backend data or Tkinter-stub tests. Platform claims identify the OS/toolchain actually tested.

### G17 — Package and document an installable extension

- [ ] Produce a VSIX from the checked-in package and a reproducible build.
- [ ] Ensure backend code/resources and Python dependencies can be found after installation outside the development checkout.
- [ ] Document the supported runtime/toolchain setup, explicit configuration overrides, first-project flow, recording/stepping, and troubleshooting.
- [ ] Declare supported workspace/platform modes accurately. Prioritize a qualified local Windows installation; retain portability and qualify Linux/macOS separately before claiming support.
- [ ] Add developer instructions for starting, testing, and debugging both the extension and backend.

**Acceptance:** install the VSIX in a fresh VS Code profile and complete the core user journey without relying on this machine's hard-coded development paths. Marketplace publication is separate from creating the installable package.

### G18 — Complete and document the migration

- [ ] Reconcile the feature inventory from G01 against the delivered extension.
- [ ] Finish the planned File/Call/Class/Mind Map views, source integration, trace workflow, specification/provider interactions, proposal review, evidence views, and project persistence, or clearly identify any user-agreed deferral.
- [ ] Keep the desktop application working against the shared core throughout migration.
- [ ] Update documentation and retain release evidence so another developer can install, reproduce, and continue the work.

**Acceptance:** the parity matrix contains no unexplained omission. A reviewer can distinguish the first usable milestone from the completed migration, and both frontends have appropriate regression evidence.

## 7. Recommended milestone order

Tests and lifecycle handling are part of each milestone, even when their broader goals appear later in this list.

| Milestone | Goals and work | Exit condition |
|---|---|---|
| M0: baseline and design | G01; define the G03 contract and installation strategy | Feature inventory, baseline evidence, and a small implementable service boundary. |
| M1: first usable extension | G02–G08, with the necessary parts of G14–G16 | Open a project, display Call View, navigate source, load a trace, and pass B → C/D/E inside VS Code. |
| M2: executable workflow | G09; improve G04 as needed | Build/run a selected executable, record a real trace, and navigate it without leaving VS Code. |
| M3: architecture/evidence views | G10–G11 and applicable G15 checks | File overview, Class View, Mind Map, Issues, and Coverage work against real project data. |
| M4: development workflow | G12–G13 | Specification, provider interactions, proposals, review gates, and Git workflow operate through the extension. |
| M5: qualification and completion | Complete G14–G18 | Installed-package acceptance, documented platform results, desktop regressions, and reconciled parity matrix. |

Keep changes reviewable. Do not pause after every small internal implementation choice; use the documented defaults and ordinary engineering judgment. Explain a changed architectural decision and its evidence instead of silently changing the scope or the agreed playback behavior.

## 8. Required acceptance cases

| ID | Scenario | Required result |
|---|---|---|
| AT01 | Open a small C++ project and a small Python project | Actual analysed entities/edges appear; Python analysis does not execute the project. |
| AT02 | Open a large project | File View starts with readable cluster-level information; expanding/revealing files works. |
| AT03 | Click a source location whose cached path moved | Find the unambiguous matching file inside the correct root and open its source line. |
| AT04 | Duplicate basenames or truly missing source | Request disambiguation only when needed or show a source error; no provider/Binary diagnosis. |
| AT05 | B selected in the main/A/B/C/D/E example | Into → C, Over → D, Out → E, with matching graph and editor selections. |
| AT06 | Leaf, repeated, recursive, and unresolved calls | Preserve eligible-call order/counts, correct invocation handling, and meaningful disabled states. |
| AT07 | Interleaved threads | Preserve the documented thread policy; Over/Out never use another thread's returns or depth. |
| AT08 | Empty, truncated, malformed, or exhausted trace | Explain the condition, do not invent scope exits, and keep the UI usable; end-of-trace retains selection. |
| AT09 | Previous Call, Reset, and graph seek | Correct shared cursor, counters, availability, source location, and repeat-edge annotations. |
| AT10 | Start Windows VS Code without developer-shell PATH | Find usable installed Visual Studio tools and pass the discovered environment to operations. |
| AT11 | Record a real selected executable | Ordinary build remains intact; the produced trace resolves and steps through real project calls. |
| AT12 | Switch workspace/target during a slow operation | Stale results do not appear in the new selection; cancellation and progress remain coherent. |
| AT13 | View/edit proposal source and attempt gated approval | Correct worktree source is shown; unsaved/stale evidence and failing checks enforce existing rules. |
| AT14 | Backend crash, restart, webview close, or extension deactivation | Pending work gets a clear outcome; state can recover and owned resources are cleaned up. |
| AT15 | Narrow panel, light/dark theme, keyboard navigation | Controls are usable, diagrams remain legible, and the toolbar has no duplicate Next Call button. |
| AT16 | Fresh-profile VSIX installation | The extension locates its backend/resources and completes the documented first-project flow. |

For each case, retain the fixture/project identity, command or UI procedure, actual result, and relevant log/screenshot. Use synthetic traces for precise edge cases and a compiled trace to establish integration. Use ViennaVulkanEngine for large-project acceptance when available; do not substitute a claim about it for an actual run.

## 9. Optional later work

**Native debug controls:** consider a custom [Debug Adapter](https://code.visualstudio.com/api/extension-guides/debugger-extension) to expose recorded playback through VS Code's debugging UI. This is a later integration option. It must preserve the agreed function-call semantics and identify the session as trace playback; do not imply that unrecorded variables or live execution state are available.

**Live debugging:** attaching to or controlling a running process is a separate feature and is not achieved merely by adding a debug adapter around recorded traces.

**Remote and browser environments:** avoid unnecessarily coupling the design to a local absolute path, but qualify Remote SSH, WSL, containers, and browser-only VS Code separately. The initial Python/process architecture should not be advertised as a browser-only extension without an appropriate execution backend.

**Alternate frontend technology or language-server features:** adopt only if a concrete requirement justifies the cost. The proposed service boundary does not require a full LSP implementation or a specific web UI framework.

## 10. Handoff instructions for the implementing LLM

When asked to implement this plan, begin with G01 and work through the milestone order. Inspect current files before editing; this brief may outlive the checkout it was written against. Preserve unrelated working-tree changes and the user's completed UI/toolchain/source-lookup fixes.

Maintain a progress record keyed by goal ID. For each completed milestone, report the observable functionality delivered, the files/components changed, the verification actually performed, and any unresolved limitation. Keep unsupported claims and old verification numbers out of the completion report.

The expected final deliverables are a working TypeScript extension, a reusable headless Python service, the required VS Code views and workflows, automated and manual acceptance evidence, an installable VSIX, and updated installation/development documentation. Optional work in section 9 is not a prerequisite for completing the planned migration.

The current authoring task creates this brief only. No extension implementation or migration goal is claimed complete by the existence of this document.
