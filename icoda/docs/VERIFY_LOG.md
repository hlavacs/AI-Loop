# ICODA verification log

## 2026-09-10 — iteration 6, M3 body hashes and rename pairs

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 36 source files`
- From the worktree root, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `640 passed, 13 skipped in 13.55s`
- A real-Tk StepPanel rendering of the rename Delta was captured at
  `icoda/.icoda-test-artifacts/iteration-6/rename-delta.png`. The validated image is 1200×520 pixels, has 361 sampled
  colours, and sampled variance 546.69.

## 2026-09-10 — iteration 7, M3 targeted test discovery

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 37 source files`
- From the worktree root, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `644 passed, 13 skipped in 13.55s`
- A real-Tk acceptance run used exact command
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python tests/gui_acceptance.py --project /tmp/icoda-gui-smoke-project --output .icoda-test-artifacts/iteration-7`
  from `icoda/`. It captured `icoda/.icoda-test-artifacts/iteration-7/proposal-targeted-tests.png`; the validated
  image is 1200×760 pixels, has 421 sampled colours, and sampled variance 556.87. The Tests tab lists both selected
  test identifiers and the failing test output while the separate Build status remains passed.

## 2026-09-10 — iteration 8, M3 implementation-queue batching

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 37 source files`
- From the worktree root, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `654 passed, 13 skipped in 13.43s`
- A real-Tk acceptance run used exact command
  `DISPLAY=:99 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python tests/gui_acceptance.py --project /tmp/icoda-gui-smoke-project --output .icoda-test-artifacts/iteration-8-xephyr`
  from `icoda/`, on an isolated Xephyr display. It captured
  `icoda/.icoda-test-artifacts/iteration-8-xephyr/proposal-batch.png`; the visually inspected and validated image is
  1200×760 pixels, has 340 sampled colours, and sampled variance 1184.85. It shows batch size 2, both current
  batch members, and both members in the proposal header and Delta tab.

## 2026-09-10 — iteration 9, M4 Class View graph

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 40 source files`
- From the worktree root, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `657 passed, 13 skipped in 14.02s`
- A real-Tk acceptance run used exact command
  `DISPLAY=:99 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python tests/gui_acceptance.py --project /tmp/icoda-gui-smoke-project --output .icoda-test-artifacts/iteration-9`
  from `icoda/`, on an isolated Xephyr display. It captured
  `icoda/.icoda-test-artifacts/iteration-9/class-view.png` and
  `icoda/.icoda-test-artifacts/iteration-9/class-view-zoomed.png`; both visually inspected and validated images are
  1200×760 pixels. The fitted image has 343 sampled colours and sampled variance 1149.82; the zoomed image has 354
  sampled colours and sampled variance 1150.85. The captures show the class member and its step-log-derived `stub`
  status; the acceptance checks also validated Fit, 100%, zoom-in, and a 32×22-pixel middle-button pan.

## 2026-09-10 — iteration 10, M4 callable coverage index

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 42 source files`
- From the worktree root, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `661 passed, 13 skipped in 14.02s`
- A real-Tk acceptance run used exact command
  `DISPLAY=:99 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/ai_run_crash_safe.bash -- /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python tests/gui_acceptance.py --project /tmp/icoda-gui-smoke-project --output .icoda-test-artifacts/iteration-10`
  from `icoda/`, on an isolated Xephyr display. It captured
  `icoda/.icoda-test-artifacts/iteration-10/coverage-overview.png`; the visually inspected and validated image is
  1200×760 pixels, has 567 sampled colours, and sampled variance 1178.2. It shows two covered callable rows with
  their named test and successful step evidence, plus fourteen explicitly uncovered callable rows.

## 2026-09-10 — iteration 11, M4 rule-check issues

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 44 source files`
- From the worktree root, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `668 passed, 13 skipped in 14.06s`
- A real-Tk acceptance run used exact command
  `DISPLAY=:99 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/ai_run_crash_safe.bash -- /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python tests/gui_acceptance.py --project /tmp/icoda-gui-smoke-project --output .icoda-test-artifacts/iteration-11`
  from `icoda/`, on an isolated Xephyr display. It captured
  `icoda/.icoda-test-artifacts/iteration-11/rule-issues.png`; the visually inspected and validated image is
  1200×760 pixels, has 544 sampled colours, and sampled variance 1173.64. The Issues tab shows six deterministic,
  actionable rows with severity, rule, entity, remediation, and source location; the acceptance program also records
  the metrics under `rule_issues` in `icoda/.icoda-test-artifacts/iteration-11/gui-state.json`.

## 2026-09-10 — iteration 12, bounded step rule issues

Rule issues now feed only targeted implementation step prompts: the deterministic selection contains at most 10
issues whose USR is in the current target/batch or whose file is one of the files the step touches. Prompt rendering
adds an explicit `... and N more` line when relevant issues are omitted; untargeted requests and empty histories stay
inert.

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 44 source files`
- From the worktree root, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `672 passed, 13 skipped in 13.44s`
- A real-Tk acceptance run used exact command
  `DISPLAY=:99 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/ai_run_crash_safe.bash -- /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python tests/gui_acceptance.py --project /tmp/icoda-gui-smoke-project --output .icoda-test-artifacts/iteration-12`
  from `icoda/`, on an isolated Xephyr display. It captured
  `icoda/.icoda-test-artifacts/iteration-12/implementation-approach.png`; the visually inspected and validated image
  is 1200×760 pixels, has 337 sampled colours, and sampled variance 1168.25. It shows the implementation target,
  developer-approved approach and disabled code proposal gate while the separate prompt tests verify issue scoping,
  inert cases and the explicit truncation count.

## 2026-09-10 — iteration 13, M4 persistent mind-map core

The pure core now builds a deterministic cluster → file → class/function hierarchy from the derived model and
effective step history. Every node carries status, satisfied requirement ids, and its introducing iteration; frozen
view state persists expanded node ids, defaulting legacy projects to fully collapsed. The matching geometry lays out
only visible nodes without importing Tk. The widget, App tab, and step navigation remain a later slice.

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 45 source files`
- From the worktree root, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `678 passed, 13 skipped in 13.46s`
- A one-off Pillow rendering of the pure geometry (not an application widget) was captured at
  `icoda/.icoda-test-artifacts/iteration-13/mind-map-geometry.png`. The visually inspected and validated image is
  1200×760 pixels, has 727 sampled colours and sampled variance 536.37, and shows nine visible nodes across two
  fully expanded cluster → file → class → function branches without overlap.

## 2026-09-10 — iteration 14, M4 mind-map GUI and step navigation

The application now has a persistent Mind Map tab beside Class View, Coverage, and Issues. Clicking an expandable
node saves the resulting expansion state in the existing project state and redraws the core-provided layout; clicking
a node with a known introducing iteration selects that historical record in the existing step panel. No-project,
empty-model, empty-history, and unknown-iteration cases remain non-crashing.

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 46 source files`
- From the worktree root, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `682 passed, 13 skipped in 13.54s`
- A real-Tk acceptance run used exact command
  `DISPLAY=:99 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/ai_run_crash_safe.bash -- /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python tests/gui_acceptance.py --project /tmp/icoda-gui-smoke-project --output .icoda-test-artifacts/iteration-14`
  from `icoda/`, on an isolated Xephyr display. It captured
  `icoda/.icoda-test-artifacts/iteration-14/mind-map.png`; the visually inspected and validated image is 1200×760
  pixels, has 460 sampled colours and sampled variance 1196.55. It shows nine visible nodes across an expanded
  cluster → file → class/function branch, including status, requirement, introducing-step metadata, and the selected
  introducing record in the step panel.

## 2026-09-10 — iteration 15, shared diagram node actions

File, Call, Class, and Mind Map views now reuse the one documented `NodeActionMenu` in `graph_canvas.py`. The menu
shows the introducing step and the plan's “Propose the next step here”, “Implement this function”, and “Run the
tests of changed functions” entries. Its history and exact target-test tuple come from the existing core projections;
test execution stays in `StepController.action`, the existing runner, and the existing busy lifecycle. Unknown
introducing iterations, missing test coverage, no project, empty models/history, and background clicks stay inert.

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 46 source files`
- From the worktree root, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `687 passed, 13 skipped in 13.58s`
- A real-Tk acceptance run used exact command
  `DISPLAY=:99 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/ai_run_crash_safe.bash -- /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python tests/gui_acceptance.py --project /tmp/icoda-gui-smoke-project --output .icoda-test-artifacts/iteration-15`
  from `icoda/`, on an isolated Xephyr display. It captured
  `icoda/.icoda-test-artifacts/iteration-15/node-action-menu.png`; the visually inspected and validated image is
  1200×760 pixels, has 307 sampled colours and sampled variance 1175.07. It shows the open shared right-click menu
  on the Call View's `main` node, including the enabled introducing-step entry and the phase/test-gated plan entries.

## 2026-09-10 — iteration 16, node-action controller proof and degenerate guards

The shared menu's propose and implement entries now have end-to-end Tk-stub coverage through
`App.dispatch_graph_action` and `StepController.action`. The tests prove exact node-USR focus forwarding, selection
between the real panel's approach and code actions, inert behavior with neither action or an empty payload, and
unchanged requests from the existing no-focus panel buttons. The two defects exposed by those assertions were that
direct empty controller payloads could start work and independently constructed enabled menu contexts did not also
require their payload; both are now guarded without changing labels or the menu contract.

The pre-job commit `170a5a7` already has `StepRequest.focus` with an empty tuple default at
`icoda/icoda_core/prompt.py:34`, passes it to `describe_model` at line 43, and tests focused model subsets in
`icoda/tests/test_prompt.py:51-58`. Iteration 15 therefore reused an additive, existing prompt input; it did not add
or change the accepted step-request/prompt slice.

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 46 source files`
- From the worktree root, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `694 passed, 13 skipped in 13.55s`
- The focused regression run from the worktree root used exact command
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_step_gui.py icoda/tests/test_graph_actions.py`
  and its exact result was `27 passed in 0.16s`.
- A real-Tk acceptance run used exact command
  `DISPLAY=:99 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/ai_run_crash_safe.bash -- /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python tests/gui_acceptance.py --project /tmp/icoda-gui-smoke-project --output .icoda-test-artifacts/iteration-16`
  from `icoda/`, on an isolated Xephyr display. It captured
  `icoda/.icoda-test-artifacts/iteration-16/node-action-menu.png`; the visually inspected and validated image is
  1200×760 pixels, has 293 sampled colours and sampled variance 4364.57. It shows the open shared right-click menu
  on the Call View's `main` node with all four unchanged labels and phase/target/test-gated states.

## 2026-09-10 — iteration 17, shared diagram node appearance

`icoda_core/node_status.py:derive` now returns the one frozen per-USR `NodeAppearance` mapping from the derived
model, persisted project queue/phase, effective step records, stored body hashes/rename pairs, and the existing
`coverage_index.build_index` result. `icoda_gui/graph_canvas.py:NodeAppearanceCanvas` and `NODE_COLOURS` are the
single shared renderer and colour table used by File, Call, Class, and Mind Map canvases. The one View → Coverage
colours toggle switches all four canvases together. Approved proposals are re-presented from their already-parsed
model through `App.show_after_step`/`App.show`, so the mapping refreshes without starting a project analysis reload.

The plan says the switched display is specification coverage, so the coverage fill follows `@satisfies`. The same
mapping separately retains successful-test `covered`/`uncovered` state and the distinct covering-test count from
the requested existing coverage index. The plan also says a manually changed tested body drops to implemented and
a stale model is marked in every view; the derivation therefore demotes that appearance and combines its per-node
body mismatch with the model-wide stale flag.

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 47 source files`
- From the worktree root, exact focused command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_node_status.py icoda/tests/test_node_status_gui.py icoda/tests/test_graph_actions.py icoda/tests/test_step_gui.py icoda/tests/test_step_results.py`
  Exact result: `46 passed in 0.19s`
- From the worktree root, exact full-suite command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `705 passed, 13 skipped in 13.60s`
- From `icoda/`, the plan's retained-evidence gate was also run with exact command:
  `ICODA_VERIFY_PYTHON=/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/ai_run_crash_safe.bash -- ./verify.bash`
  Exact result: `FAIL: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260910-053035-982747/summary.txt`.
  Its own ruff, mypy, compileall, provider, and 198-passed/12-skipped ICODA pytest assertions passed. The retained
  gate remains red on the already-documented release debt: `Total coverage: 84.44%` is below its 85% threshold,
  and the sample build selects GNU 13.3.0, which cannot scan its C++ module imports; the resulting stale model makes
  that gate's sample-project GUI capture fail. The isolated real-Tk acceptance project below is built and fresh.
- A real-Tk acceptance run used exact command
  `DISPLAY=:99 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/ai_run_crash_safe.bash -- /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python tests/gui_acceptance.py --project /tmp/icoda-gui-smoke-project --output .icoda-test-artifacts/iteration-17`
  from `icoda/`, on an isolated Xephyr display. Exact result: exit 0. It captured and validated:
  - `icoda/.icoda-test-artifacts/iteration-17/diagram-status-colours.png`: 1200×760 pixels, 497 sampled colours,
    sampled variance 1346.39. It visibly shows the shared status legend; blue implemented, gray stub, and green
    tested nodes; and the red `⚠` body-stale marker on `covered`.
  - `icoda/.icoda-test-artifacts/iteration-17/diagram-coverage-colours.png`: 1200×760 pixels, 515 sampled colours,
    sampled variance 1395.58. It visibly shows the shared coverage legend, the `@satisfies`-covered node in green,
    uncovered nodes in red, and the same red `⚠` marker.

## 2026-09-10 — iteration 18, shared diagram filtering and neighborhood dimming

`icoda_core/graph_filter.py:derive` is the single pure matching, hiding, existing-edge traversal, and neighborhood
derivation. It consumes the existing `node_status.derive` appearance facts and returns one frozen `NodeDecision`
mapping used unchanged by all four diagrams. `icoda_gui/graph_canvas.py:DIMMED_APPEARANCE` is the single dim table,
beside `NODE_COLOURS` and `STALE_MARKER`; `NodeAppearanceCanvas` is the only visibility/style resolver. The global
filter entry and neighborhood-depth control live in `icoda.py:App._build_graph_controls`, and
`App.refresh_graph_appearances` republishes both frozen mappings after edits and approved steps without reload.

The plan explicitly requires cluster, namespace, and edge-type filters, so those are supported in addition to the
task's name, kind, implementation-status, successful-test covered/uncovered, and stale criteria. The plan says
dimming follows the current selection and describes a class's complete neighborhood; the focus is therefore always
the selected entity and depth means the complete undirected neighborhood within that many existing model edges.
The plan does not fix a numeric depth or control shape, so the requested single `0=off` depth control supplies it.
No persisted field was added.

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 48 source files`
- From the worktree root, exact focused command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_graph_filter.py icoda/tests/test_graph_filter_gui.py icoda/tests/test_node_status.py icoda/tests/test_node_status_gui.py icoda/tests/test_class_view.py icoda/tests/test_mind_map_gui.py icoda/tests/test_graph_actions.py icoda/tests/test_step_gui.py icoda/tests/test_step_results.py`
  Exact result: `71 passed in 0.23s`
- From the worktree root, exact full-suite command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `724 passed, 13 skipped in 13.53s`
- A real-Tk acceptance run used exact command
  `DISPLAY=:99 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/ai_run_crash_safe.bash -- /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python tests/gui_acceptance.py --project /tmp/icoda-gui-smoke-project --output .icoda-test-artifacts/iteration-18`
  from `icoda/`, on an isolated Xephyr display. Exact result: exit 0. Its hard assertions proved that the filtered
  capture rendered fewer nodes than the unfiltered capture, retained the matching node's readable label, and the
  dimmed capture rendered at least one node with the shared dim fill. It captured and validated:
  - `icoda/.icoda-test-artifacts/iteration-18/diagram-unfiltered.png`: 1200×760 pixels, 505 sampled colours,
    sampled variance 1325.74. It visibly shows the empty global Filter entry, Neighborhood `0`, the shared status
    legend, and four Call View nodes: blue `appearance_root`, blue stale-marked `covered`, gray `uncovered`, and
    green `tested_fresh`.
  - `icoda/.icoda-test-artifacts/iteration-18/diagram-filtered.png`: 1200×760 pixels, 339 sampled colours,
    sampled variance 1168.32. It visibly shows `status:stub` in the global Filter entry and only the readable gray
    `uncovered` node; the other three nodes and their edges are hidden.
  - `icoda/.icoda-test-artifacts/iteration-18/diagram-neighborhood-dimmed.png`: 1200×760 pixels, 468 sampled
    colours, sampled variance 1236.26. It visibly shows Neighborhood `1`, normal blue `appearance_root` and
    stale-marked `covered`, plus `uncovered`, `tested_fresh`, and their incident edges in the one shared gray dim
    appearance.

## 2026-09-10 — iteration 19, shared hierarchical and external-library expansion

`icoda_core/expansion.py:derive` is the single pure container/child resolution, synthetic external-symbol,
collapsed-edge aggregation, and expanded-graph construction. It consumes the existing `graph_filter.derive`
`NodeDecision` mapping and `node_status.derive` `NodeAppearance` mapping without recomputing either. The one GUI
resolver and renderer is `icoda_gui/graph_canvas.py:NodeAppearanceCanvas`; its `EXPANSION_AFFORDANCE` table sits
beside `NODE_COLOURS`, `STALE_MARKER`, and `DIMMED_APPEARANCE`. `icoda.py:App.expansion_state` is the explicit frozen,
session-local state, `App.toggle_graph_expansion` is the shared dispatch path, `App.collapse_all` is the one global
reset, and `App.refresh_graph_appearances` republishes the same frozen expansion result to `FileViewCanvas`,
`CallViewCanvas`, and `ClassViewCanvas`, including through `App.show_after_step` without reload.

The final plan re-read confirmed Project → Cluster → File → Class → Function, one level per activation, and that an
expanded external library lists only used types/functions, has no internals, and belongs to no cluster. The shared
`+`/`−` affordance is the click target, reconciling the plan's click-to-expand wording with the accepted left-click
navigation contract. The plan asks for collapse/expand but does not prescribe a collapse-all shape or cross-session
memory; the task's single `Collapse all` control was added, and no `ProjectState` or persistence field was added.
The accepted independent `mind_map.MindMapViewState` and `MindMapCanvas.activate_node` behavior remains unchanged.

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 49 source files`
- From `icoda/`, exact new-test type-check command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy tests/test_expansion.py tests/test_expansion_gui.py`
  Exact result: `Success: no issues found in 2 source files`
- From the worktree root, exact focused command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_expansion.py icoda/tests/test_expansion_gui.py icoda/tests/test_graph_filter.py icoda/tests/test_graph_filter_gui.py icoda/tests/test_node_status.py icoda/tests/test_node_status_gui.py icoda/tests/test_class_view.py icoda/tests/test_mind_map.py icoda/tests/test_mind_map_gui.py icoda/tests/test_graph_actions.py`
  Exact result: `63 passed in 0.25s`
- From the worktree root, exact full-suite command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `739 passed, 13 skipped in 13.62s`
- A real-Tk acceptance run used exact command
  `DISPLAY=:99 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/ai_run_crash_safe.bash -- /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python tests/gui_acceptance.py --project /tmp/icoda-gui-smoke-project --output .icoda-test-artifacts/iteration-19`
  from `icoda/`, on an isolated Xephyr display. Exact result: exit 0. It hard-asserted that expanding the selected
  cluster rendered strictly more nodes than its collapsed form and that expanding `std` rendered both referenced
  symbol children. It captured and validated:
  - `icoda/.icoda-test-artifacts/iteration-19/diagram-container-collapsed.png`: 1200×760 pixels, 362 sampled
    colours, sampled variance 1131.06. It visibly shows the shared hierarchy with collapsed `cluster src` and
    collapsed `external std`, both with the common `+` affordance, plus the global `Collapse all` control.
  - `icoda/.icoda-test-artifacts/iteration-19/diagram-container-expanded.png`: 1200×760 pixels, 377 sampled
    colours, sampled variance 1129.49. It visibly shows that same `cluster src` with `−` and the newly revealed
    indented `file expansion.cpp` child with its own `+`; `external std` remains collapsed.
  - `icoda/.icoda-test-artifacts/iteration-19/diagram-external-expanded.png`: 1200×760 pixels, 392 sampled
    colours, sampled variance 1126.21. It visibly shows expanded `external std` with `−` and the two indented leaf
    rows `used std::string` and `used std::vector`, while the expanded cluster/file hierarchy remains visible.

## 2026-09-10 — iteration 20, pure Python analysis core

`icoda_core/python_analysis.py:parse_project` is the standalone, Tk-free M5 front end. It uses only the standard
library `ast` parser, never imports or executes analysed code, and produces the existing `DerivedModel`, `FileInfo`,
`Entity`, `Kind`, `Edge`, `EdgeKind`, and `External` vocabulary. It reuses `bodyhash.body_hash`. The fixture tests
prove stable path/line-independent USRs, classes/functions/methods and method parents, project-local call and
annotation resolution through each module's imports, precise used external symbols, relative/package imports,
syntax-error isolation, nested closures, decorators, dunder methods, unresolved calls, unused imports, and empty
inputs. They also execute every previously built language-neutral consumer without edits.

The final plan re-read confirmed that M5 requires an `ast`-based Python parser producing the same schema and says
Python identities and uncertain dynamic calls come first. The module docstring therefore specifies both the stable
identity mapping and the conservative uncertain-call policy (omit calls that cannot be resolved without guessing)
before describing the parser. The plan does not prescribe the construct mapping, import/external behavior, a new
module name, or a multi-language front-end abstraction; the task's concrete rules supply those details. No dispatch
seam was added to `icoda_core/analysis.py`: the existing project-open/session path is C++-specific, and language
selection plus GUI
wiring is the next slice. The pre-existing C++ analyzer and all downstream consumer modules remain unchanged.
Screenshots were deliberately not taken because this accepted slice is pure core and explicitly leaves GUI and
project-open language selection to the next task.

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 50 source files`
- From `icoda/`, exact new-test type-check command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy tests/test_python_analysis.py`
  Exact result: `Success: no issues found in 1 source file`
- From the worktree root, exact focused command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_python_analysis.py icoda/tests/test_analysis.py`
  Exact result: `15 passed, 7 skipped in 0.26s`
- From the worktree root, exact full-suite command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `745 passed, 13 skipped in 13.73s`

## 2026-09-10 — iteration 21, Python project-open and GUI vertical slice

`icoda_core.analysis.detect_language` auto-detects Python-only projects and deliberately keeps mixed and
source-free projects on the existing C++ path. `icoda_core.analysis.parse_project_for_root` is the one minimal
dispatch entry point: it calls iteration 20's unchanged `python_analysis.parse_project(root)` for Python and calls
the existing C++ `analysis.parse_project` with every argument unchanged otherwise. `session._derive_model` uses the
seam inside the existing child-safe project-open pipeline. `App.language_var` is shown in the status bar and is
re-detected on every open; no `ProjectState`, `ProjectStore`, dialog, registry, or configuration field was added.

The final plan re-read found no M5 language-selector, persistence, dialog, control, module, or function wording to
override. `ICODA_PLAN.md` says “Python identities and uncertain dynamic calls first, then the AST parser, generator,
project/test integration and a Python acceptance project”; its M5 section and `EVOLUTION.md` roadmap only require an
`ast`-based derived model, Python Code Profile, and Python generation. Therefore this slice follows the task's
auto-detection detail and leaves the Python Code Profile/generation/build/test end-to-end simulation to the final M5
task. It does not persist a choice that the plan never asks to persist.

`tests/test_python_gui.py` opens real temporary Python fixtures through `App.open_project` and the existing
`session.open_project` path. It asserts File, Call, Class, Mind Map, Coverage, Issues, coverage mode, filter,
neighborhood, shared affordance, Collapse all, all four `NodeActionMenu` actions, and the step panel. It also asserts
empty, source-free, syntax-invalid Python, mixed-language precedence, missing-root tolerance, and C++→Python
switching in one App. `gui_acceptance.py` now opens its generated Python fixture after the existing acceptance
captures and hard-fails if each Python diagram has no rendered node or readable node label.

The display probe used the same interpreter/environment as the GUI acceptance. Exact environment result:
`DISPLAY=':10.0' WAYLAND_DISPLAY=None XDG_SESSION_TYPE='x11' visible=1 size=200x200`. The desktop display was real and
visible, but its global grab was owned by another application during the menu capture, so the final isolated run used
the same Xephyr `DISPLAY=:99` approach recorded for iterations 16–19.

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py`
  Exact result: `Success: no issues found in 50 source files`
- From `icoda/`, exact new-test type-check command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy tests/test_python_gui.py`
  Exact result: `Success: no issues found in 1 source file`
- From the worktree root, exact focused command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_python_gui.py icoda/tests/test_python_analysis.py icoda/tests/test_analysis.py icoda/tests/test_session.py icoda/tests/test_app.py icoda/tests/test_expansion_gui.py icoda/tests/test_graph_filter_gui.py icoda/tests/test_graph_actions.py`
  Exact result: `46 passed, 9 skipped in 0.42s`
- From the worktree root, exact full-suite command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `750 passed, 13 skipped in 13.66s`
- From `icoda/`, the final real-Tk command was:
  `DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/ai_run_crash_safe.bash -- /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python tests/gui_acceptance.py --project tests/sample_project --output .icoda-test-artifacts/iteration-21-final`
  Exact result: exit 0. The Python hard-fail counters were `python_file_view ... labelled_nodes: 3`,
  `python_class_view ... labelled_nodes: 1`, and `python_call_view ... labelled_nodes: 1`.

Every screenshot captured by that run is 1200×760 pixels:
`call-view-zoomed.png`, `call-view.png`, `class-view-zoomed.png`, `class-view.png`,
`coverage-overview.png`, `diagram-container-collapsed.png`, `diagram-container-expanded.png`,
`diagram-coverage-colours.png`, `diagram-external-expanded.png`, `diagram-filtered.png`,
`diagram-neighborhood-dimmed.png`, `diagram-status-colours.png`, `diagram-unfiltered.png`,
`file-view-zoomed.png`, `file-view.png`, `implementation-approach.png`, `mind-map.png`,
`node-action-menu.png`, `proposal-batch.png`, `proposal-delta.png`, `proposal-source-diff.png`,
`proposal-targeted-tests.png`, `python-call-view.png`, `python-class-view.png`, `python-file-view.png`, and
`rule-issues.png`.

## 2026-09-10 — iteration 22, final end-to-end development simulation

One real `App` session traversed eight stops and the exact `ProjectPhase` sequence
`ARCHITECTURE → IMPLEMENTATION`: rejected architecture proposal, accepted architecture proposal, explicit
architecture approval, approach and code/build/test approval for `Formatter.normalize`, approach and code/build/test
approval for `main`, then terminal `IMPLEMENTATION` with queue cursor 2 of 2 and no target. The fake provider used the
same prompt-in/reply-out contract as `tests/test_steps.py`; build and test gates were deterministic and no network,
API key, compiler, real provider, or external test process was used.

The connected run first supplied failing regression evidence for three small integration defects, then passed after
their minimal fixes: `python_analysis._read_modules` parsed rejected source under `.icoda/worktree`;
`StepRunner.prepare` treated App-owned `.icoda/icoda.log` updates as manual source edits; and
`python_analysis._resolve_project_chain` indexed an empty chain for an assigned chained-call result.

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From the worktree root, exact focused command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py icoda/tests/test_python_analysis.py icoda/tests/test_step_gui.py icoda/tests/test_steps.py`
  Exact result: `29 passed, 2 skipped in 0.44s`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py tests/test_simulation.py tests/simulation_acceptance.py`
  Exact result: `Success: no issues found in 52 source files`
- From the worktree root, exact full-suite command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `751 passed, 13 skipped in 14.45s`

The display probe used the same interpreter and environment as the first real-Tk attempt. Exact result:
`DISPLAY=':10.0' WAYLAND_DISPLAY=None XDG_SESSION_TYPE='x11' viewable=1 size=200x200`. Although Tk reported a
viewable window, visual inspection showed that desktop capture returned the lock screen, so those images were not
accepted. The final run reused the established isolated Xephyr approach. From `icoda/`, its exact application command
inside the Xephyr `DISPLAY=:99` wrapper was:
`DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/ai_run_crash_safe.bash -- /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python tests/simulation_acceptance.py --project /tmp/icoda-simulation-final-fIazpU/project --output .icoda-test-artifacts/iteration-22`
Exact result: exit 0; `phase=implementation`, `cursor=2`, `terminal=true`.

Every final capture was visually inspected, non-empty, distinct by SHA-256, and validated by the unchanged
`gui_acceptance.capture` hard-fail checks:

- `sim-01-architecture-reject.png`: 1200×760 pixels.
- `sim-02-architecture-approve.png`: 1200×760 pixels.
- `sim-03-architecture-gate.png`: 1200×760 pixels.
- `sim-04-normalize-approach.png`: 1200×760 pixels.
- `sim-05-normalize-build-test.png`: 1200×760 pixels.
- `sim-06-main-approach.png`: 1200×760 pixels.
- `sim-07-main-build-test.png`: 1200×760 pixels.
- `sim-08-terminal-overview.png`: 1200×760 pixels.

## 2026-09-10 — iteration 23, specification-to-architecture simulation closure

The plan re-read governed this extension. `EVOLUTION.md` says: “What the system does with the specification is not
to implement it. It lays out a plan, an architectural overview, and it does not start with the whole architecture,
which would be overwhelming, but with a first simple step.” It names the artifact immediately afterwards: “Step 0
is always the same: the project skeleton.” The extended real `App` session therefore starts in persisted
`ProjectPhase.SPECIFICATION`, visibly refuses a code-step request without changing state or history, exercises the
specification editor's Save control (`SpecificationEditor.save` calling `App._save_specification`), and asserts the
persisted phase on both sides of `SPECIFICATION → ARCHITECTURE`. The existing architecture, approach, implementation,
build/test, rejection, approval, and terminal assertions then continue to `IMPLEMENTATION` cursor 2 of 2. The new
total is ten stops and the exact phase sequence is `SPECIFICATION → ARCHITECTURE → IMPLEMENTATION`.

The simulation first failed with one step-log record after the refused specification request. This exposed a genuine
integration defect: Project → Propose Next Step can dispatch through `StepController.propose` even while the panel's
Propose button is disabled, and the controller called `StepRunner.prepare` before `StepRunner.propose` applied its
existing specification guard. The smallest production fix is the early specification guard in
`icoda_core/steps.py:StepRunner.prepare`; it prevents git/model/log mutation and surfaces the same developer-facing
“save the specification before proposing” text. No other production behavior changed.

The display probe used the same interpreter and environment as the real-Tk acceptance. Exact result:
`DISPLAY=':10.0' WAYLAND_DISPLAY=None XDG_SESSION_TYPE='x11' viewable=1 size=200x200`. The isolated run reused the
established Xephyr `DISPLAY=:99` approach so the captured windows, rather than the host desktop/lock screen, were
observable.

All commands used the loop interpreter at
`/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python`.

- From the worktree root, exact focused command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py icoda/tests/test_phase_runner.py icoda/tests/test_step_gui.py icoda/tests/test_steps.py`
  Exact result: `30 passed, 2 skipped in 0.56s`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  Exact result: `All checks passed!`
- From `icoda/`, exact command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py tests/test_simulation.py tests/simulation_acceptance.py`
  Exact result: `Success: no issues found in 52 source files`
- From the worktree root, exact full-suite command:
  `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  Exact result: `751 passed, 13 skipped in 14.03s`

From `icoda/`, the exact real-Tk scratch acceptance command was:
`DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/ai_run_crash_safe.bash -- /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python tests/simulation_acceptance.py --project /tmp/icoda-simulation-iteration23-final-M1eUhv/project --output /tmp/icoda-simulation-iteration23-final-M1eUhv/output`

Exact result: exit 0. Its printed `simulation-state.json` was:

```json
{
  "cursor": 2,
  "phase": "implementation",
  "queue": [
    "python:service:Formatter.normalize",
    "python:service:main"
  ],
  "screenshots": {
    "sim-01-specification-code-refused.png": {
      "colours": 386,
      "height": 760,
      "variance": 467.68,
      "width": 1200
    },
    "sim-02-specification-save.png": {
      "colours": 123,
      "height": 680,
      "variance": 295.12,
      "width": 1000
    },
    "sim-03-architecture-reject.png": {
      "colours": 495,
      "height": 760,
      "variance": 556.3,
      "width": 1200
    },
    "sim-04-architecture-approve.png": {
      "colours": 514,
      "height": 760,
      "variance": 552.9,
      "width": 1200
    },
    "sim-05-architecture-gate.png": {
      "colours": 398,
      "height": 760,
      "variance": 444.01,
      "width": 1200
    },
    "sim-06-normalize-approach.png": {
      "colours": 430,
      "height": 760,
      "variance": 438.39,
      "width": 1200
    },
    "sim-07-normalize-build-test.png": {
      "colours": 541,
      "height": 760,
      "variance": 465.12,
      "width": 1200
    },
    "sim-08-main-approach.png": {
      "colours": 421,
      "height": 760,
      "variance": 433.9,
      "width": 1200
    },
    "sim-09-main-build-test.png": {
      "colours": 478,
      "height": 760,
      "variance": 481.18,
      "width": 1200
    },
    "sim-10-terminal-overview.png": {
      "colours": 413,
      "height": 760,
      "variance": 479.06,
      "width": 1200
    }
  },
  "terminal": true
}
```

Every final capture was visually inspected, non-empty, distinct by SHA-256, and passed the unchanged
`gui_acceptance.capture` content checks:

- `sim-01-specification-code-refused.png`: 1200×760 pixels.
- `sim-02-specification-save.png`: 1000×680 pixels.
- `sim-03-architecture-reject.png`: 1200×760 pixels.
- `sim-04-architecture-approve.png`: 1200×760 pixels.
- `sim-05-architecture-gate.png`: 1200×760 pixels.
- `sim-06-normalize-approach.png`: 1200×760 pixels.
- `sim-07-normalize-build-test.png`: 1200×760 pixels.
- `sim-08-main-approach.png`: 1200×760 pixels.
- `sim-09-main-build-test.png`: 1200×760 pixels.
- `sim-10-terminal-overview.png`: 1200×760 pixels.

## 2026-09-10 — iteration 24: sole specification refusal and no-mutation runner proof

Before changing code, the ownership inventory was:

- `icoda/tests/test_phase_runner.py:test_runner_rejects_step_requests_during_specification`:

  ```python
  def test_runner_rejects_step_requests_during_specification(tmp_path: Path) -> None:
      persistence.ProjectStore(tmp_path).save_state(
          persistence.ProjectState(persistence.ProjectPhase.SPECIFICATION))
      runner = steps.StepRunner(tmp_path, persistence.UserConfig())
      with pytest.raises(steps.StepError, match="save the specification"):
          runner.propose(prompt.StepRequest(prompt.ARCHITECTURE, 0))
  ```

- `icoda/icoda_core/phases.py:TRANSITION_TITLES` and `icoda/icoda_core/phases.py:transition` validated and recorded
  transitions; they did not refuse proposal requests:

  ```python
  TRANSITION_TITLES = {
      (ProjectPhase.SPECIFICATION, ProjectPhase.ARCHITECTURE): "specification completed",
      (ProjectPhase.ARCHITECTURE, ProjectPhase.IMPLEMENTATION): "architecture approved",
      (ProjectPhase.IMPLEMENTATION, ProjectPhase.ARCHITECTURE): "architecture session opened",
  }

  def transition(store: ProjectStore, target: ProjectPhase) -> StepRecord:
      """Validate, persist and log one developer-controlled phase transition."""
      current = store.load_state()
      updated = current.transition_to(target)
      title = TRANSITION_TITLES[(current.phase, target)]
      record = StepRecord(StepLog(store.steps_path).next_number(), target.value, "phase_transition", title=title,
                          previous_phase=current.phase.value)
      store.save_state(updated)
      try:
          return StepLog(store.steps_path).append(record)
      except OSError:
          store.save_state(current)
          raise
  ```

- `icoda/icoda_core/steps.py:StepRunner.prepare` contained the iteration-23 early guard, after `store.ensure()`:

  ```python
  self.store.ensure()
  if self.current_phase() == persistence.ProjectPhase.SPECIFICATION:
      raise StepError("the project is in the specification phase; save the specification before proposing")
  ```

- `icoda/icoda_core/steps.py:StepRunner.propose` contained the older duplicate:

  ```python
  phase = self.current_phase()
  if phase == persistence.ProjectPhase.SPECIFICATION:
      raise StepError("the project is in the specification phase; save the specification before proposing")
  ```

The controlling plan wording is `icoda/ICODA_PLAN.md:M2 step 4`: “Step protocol (`icoda_core/steps.py`) on
`icoda_core/git.py`: worktree per step, apply files, configure and build, parse, compute the delta…” and its progress
record says “`icoda_core/steps.py` + `steplog.py` — one persistent worktree `.icoda/worktree` … `prepare` (git init,
build + parse, step 0 commit), `propose`…”. `icoda/EVOLUTION.md:Program layout` likewise assigns
`icoda_core/steps.py` the “worktree-based step protocol: propose … approve, reject, adapt, undo, manual commits”,
while `icoda/ICODA_PLAN.md:dependency order` separately calls for the “M3 state foundation: persisted phase
transitions”. Following that boundary, `icoda_core/phases.py:transition` owns transition validation and
`icoda_core/steps.py:StepRunner.prepare` owns the request refusal at the first mutation-capable step-protocol
operation.

`icoda_gui/step_controller.py:StepController.propose` executes `runner.prepare()` before `runner.propose(request)`.
The `prepare` check is therefore the only check early enough to prevent `ProjectStore.ensure`, ignore-file edits, Git
initialization, model preparation, and Step 0 logging. It remains as the sole refusal, moved before
`ProjectStore.ensure`; the later `StepRunner.propose` duplicate was removed. Exactly one
`ProjectPhase.SPECIFICATION` check and one copy of the unchanged StepError message now remain in `steps.py`.

The new real-runner regression is
`icoda/tests/test_phase_runner.py:test_specification_refusal_precedes_prepare_mutations`:

```python
def test_specification_refusal_precedes_prepare_mutations(tmp_path: Path) -> None:
    store = persistence.ProjectStore(tmp_path)
    store.ensure()
    store.save_state(persistence.ProjectState(persistence.ProjectPhase.SPECIFICATION))
    (tmp_path / "project.py").write_text("def main() -> None:\n    pass\n", encoding="utf-8")
    runner = steps.StepRunner(
        tmp_path, persistence.UserConfig(), invoke=lambda text, root: "{}",
        build=lambda root: steps.BuildResult(True, ""), analyse=lambda root: DerivedModel(str(root)), attempts=1,
    )

    def project_files() -> dict[str, bytes]:
        return {str(path.relative_to(tmp_path)): path.read_bytes()
                for path in tmp_path.rglob("*") if path.is_file()}

    before_state = store.load_state()
    before_state_bytes = store.state_path.read_bytes()
    before_records = runner.log.records()
    before_files = project_files()
    before_git_root = steps.git.repository_root(tmp_path)

    with pytest.raises(steps.StepError) as refused:
        runner.prepare()
        runner.propose(prompt.StepRequest(prompt.ARCHITECTURE, 0))

    assert str(refused.value) == (
        "the project is in the specification phase; save the specification before proposing")
    assert store.load_state() == before_state
    assert store.state_path.read_bytes() == before_state_bytes
    assert runner.log.records() == before_records
    assert project_files() == before_files
    assert steps.git.repository_root(tmp_path) == before_git_root
```

With the sole `StepRunner.prepare` guard temporarily removed from the final shape, preparation appended Step 0 and
the request reached the later prompt-layer error instead of the required `StepError`. The new test failed directly:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
____________ test_specification_refusal_precedes_prepare_mutations _____________

tmp_path = PosixPath('/tmp/pytest-of-hlavacs/pytest-212/test_specification_refusal_pre0')

>   ???

icoda/tests/test_phase_runner.py:99:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
icoda/icoda_core/steps.py:400: in propose
    ???
icoda/icoda_core/steps.py:488: in _prompt
    ???
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

spec = {'schema_version': 2, 'title': 'test_specification_refusal_pre0', 'summary': '', 'goals': [], ...}
model = DerivedModel(root='/tmp/pytest-of-hlavacs/pytest-212/test_specification_refusal_pre0', libclang_version='', files={}, entities={}, edges=[], externals={}, stale=False, stale_reason='')
request = StepRequest(phase='specification', number=1, request='', max_entities=5, rejections=(), constraints=(), build_errors='', validation_error='', focus=(), target='', batch=())
skeleton_files = ['.icoda/.gitignore', '.icoda/state.json', '.icoda/steps.jsonl', 'project.py']
build_files = {}
state = ProjectState(phase=<ProjectPhase.SPECIFICATION: 'specification'>, implementation_queue=(), implementation_cursor=0, te...test', '--preset', 'debug'), approved_approach='', implementation_batch_size=1, mind_map=MindMapViewState(expanded=()))
issues = IssueSelection(issues=(), omitted=0)

>   ???
E   ValueError: step prompts are unavailable during the specification phase

icoda/icoda_core/prompt.py:44: ValueError
=========================== short test summary info ============================
FAILED icoda/tests/test_phase_runner.py::test_specification_refusal_precedes_prepare_mutations
1 failed in 0.17s
```

The verification results were:

- `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .`
  → `All checks passed!`
- `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py tests/test_phase_runner.py tests/test_simulation.py tests/simulation_acceptance.py`
  → `Success: no issues found in 53 source files`
- `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q`
  → `752 passed, 13 skipped in 14.14s`
- `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_phase_runner.py::test_specification_refusal_precedes_prepare_mutations`
  → `1 passed in 0.12s`
- `/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation`
  → `1 passed in 0.47s`; its two specification stops and terminal iteration list
  `[0, 0, 1, 1, 2, 2, 2, 3, 3]` remain unchanged.

The test environment reported `DISPLAY=:10.0`, unset `WAYLAND_DISPLAY`, and `XDG_SESSION_TYPE=x11`; Xorg was
running at `:10`, and `xwininfo` could inspect its root tree. Visual inspection showed the session was locked, so the
native-display images were discarded. The existing headless capture approach was reused by starting local Xephyr at
`:99`; `xdpyinfo` and `xwininfo` both confirmed that isolated display before the final run.

Final simulation command:

```text
DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/ai_run_crash_safe.bash -- /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python icoda/tests/simulation_acceptance.py --project /tmp/icoda-simulation-iteration24-final/project --output /tmp/icoda-simulation-iteration24-final/output
```

Exit status: `0`. Printed and persisted `simulation-state.json`:

```json
{
  "cursor": 2,
  "phase": "implementation",
  "queue": [
    "python:service:Formatter.normalize",
    "python:service:main"
  ],
  "screenshots": {
    "sim-01-specification-code-refused.png": {
      "colours": 382,
      "height": 760,
      "variance": 467.85,
      "width": 1200
    },
    "sim-02-specification-save.png": {
      "colours": 123,
      "height": 680,
      "variance": 295.12,
      "width": 1000
    },
    "sim-03-architecture-reject.png": {
      "colours": 495,
      "height": 760,
      "variance": 556.3,
      "width": 1200
    },
    "sim-04-architecture-approve.png": {
      "colours": 514,
      "height": 760,
      "variance": 552.9,
      "width": 1200
    },
    "sim-05-architecture-gate.png": {
      "colours": 398,
      "height": 760,
      "variance": 444.01,
      "width": 1200
    },
    "sim-06-normalize-approach.png": {
      "colours": 430,
      "height": 760,
      "variance": 438.39,
      "width": 1200
    },
    "sim-07-normalize-build-test.png": {
      "colours": 541,
      "height": 760,
      "variance": 465.12,
      "width": 1200
    },
    "sim-08-main-approach.png": {
      "colours": 421,
      "height": 760,
      "variance": 433.9,
      "width": 1200
    },
    "sim-09-main-build-test.png": {
      "colours": 478,
      "height": 760,
      "variance": 481.18,
      "width": 1200
    },
    "sim-10-terminal-overview.png": {
      "colours": 413,
      "height": 760,
      "variance": 479.06,
      "width": 1200
    }
  },
  "terminal": true
}
```

All ten files are non-empty, visually inspected ICODA captures, have distinct SHA-256 hashes, and passed the
unchanged hard-fail size/colour/variance checks:

- `sim-01-specification-code-refused.png`: 1200×760 pixels, 47,412 bytes.
- `sim-02-specification-save.png`: 1000×680 pixels, 11,427 bytes.
- `sim-03-architecture-reject.png`: 1200×760 pixels, 58,636 bytes.
- `sim-04-architecture-approve.png`: 1200×760 pixels, 62,124 bytes.
- `sim-05-architecture-gate.png`: 1200×760 pixels, 47,341 bytes.
- `sim-06-normalize-approach.png`: 1200×760 pixels, 55,613 bytes.
- `sim-07-normalize-build-test.png`: 1200×760 pixels, 67,236 bytes.
- `sim-08-main-approach.png`: 1200×760 pixels, 55,358 bytes.
- `sim-09-main-build-test.png`: 1200×760 pixels, 73,578 bytes.
- `sim-10-terminal-overview.png`: 1200×760 pixels, 58,169 bytes.

The bounded simulation meets the finishing criterion for its two-function project. ICODA as a whole still does not
meet the unrestricted criterion; the exact remaining gaps are the eight items retained in `icoda/docs/SIMULATION.md`:
signature confirmation, class/cluster/all-leaves and auto-approve batch controls, actual queue override from
`StepController.implement_here`, external-edit refresh and persisted demotion, structured proposal adaptation,
exact coverage provenance, complete Python generation/build/test integration, and cross-platform release
qualification.

## 2026-09-10 — iteration 25: deterministic batch scope and direct queue override

The controlling design is `icoda/EVOLUTION.md:Phase 2 — Implementation`: “Order. Bottom-up over the call graph by
default, leaves first… The developer can pick any function from the views instead.” It also says: “Batching. … the
developer can select a class, a cluster or ‘all leaves’ and enable auto-approve while build and tests pass. Every
function is still its own step and its own commit…”. `icoda/ICODA_PLAN.md:M3` assigns bottom-up ordering and “pick
this function” to item 1 and batching to item 4. Iteration 25 follows that ownership for ordering, scope, and target
selection, but deliberately excludes auto-approve under the task constraint because it removes a developer decision
point; it remains a documented gap.

Before this slice, `implementation_queue.target_usr` returned only
`state.implementation_queue[state.implementation_cursor]`, `next_batch` took consecutive queue entries up to the
numeric limit, and `StepController.implement_here` only called `propose_approach(focus=(target_usr,))` or
`propose(focus=(target_usr,))`. `ProjectState` persisted `implementation_queue`, `implementation_cursor`, and
`implementation_batch_size`, but no scope or override.

After this slice, `implementation_queue.Scope`, `scope_targets`, `select_scope`, `can_override`, and
`override_target` own the pure model/state decisions. `target_usr` consumes the persisted override, while
`ProjectState.implementation_scope` and `ProjectState.implementation_override` round-trip with additive defaults
`queue_order` and empty string. `StepPanel.scope_combobox` dispatches through `StepController.action`;
`StepController.implement_here` persists the core-produced state before reusing the existing two-round proposal
path; and `App.dispatch_graph_action` remains the sole graph-action route. The unchanged
`implementation_batch_size` remains the maximum number of safe targets in one proposal.

Focused core and real-App wiring command:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_implementation_queue.py::test_scope_expansions_return_exact_pending_sets icoda/tests/test_implementation_queue.py::test_scope_degenerate_cases_are_deterministic icoda/tests/test_implementation_queue.py::test_scope_selection_groups_exact_targets_and_batch_size_remains_a_limit icoda/tests/test_implementation_queue.py::test_override_moves_and_returns_the_exact_developer_selected_target icoda/tests/test_implementation_queue.py::test_state_without_scope_or_override_loads_with_compatible_defaults icoda/tests/test_graph_actions.py::test_real_app_scope_control_and_implement_here_override_persist_and_target_request
......                                                                   [100%]
6 passed in 0.22s
```

The real-App test uses `ScriptedProvider`, synchronous UI work, and `session.open_project(in_process=True)`. It
asserts the named `StepPanel.scope_combobox`, persisted `enclosing_class` scope, non-head `MAIN` override, reordered
queue, visible “Overridden target”, exact `Approach.request.target`/batch, provider prompt USR, and persisted approach
`StepRecord.batch`. No real provider, network, or API key was used.

The unchanged lifecycle test remains green with its two specification stops and terminal iteration list
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation
.                                                                        [100%]
1 passed in 0.47s
```

Final static checks from `icoda/`:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py tests/test_implementation_queue.py tests/test_graph_actions.py
Success: no issues found in 52 source files
```

Full repository suite from the worktree root:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
758 passed, 13 skipped in 14.61s
```

The same-process display probe reported `DISPLAY=':10.0'`, `WAYLAND_DISPLAY=None`,
`XDG_SESSION_TYPE='x11'`, and a mapped/viewable real Tk window of `320x180`. Xephyr was available but `:99` was
initially absent, so a fresh `Xephyr :99 -screen 1280x800 -ac -noreset` was started. The final crash-safe GUI
acceptance command used a fresh copied project and output directory:

```text
DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/ai_run_crash_safe.bash -- /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python icoda/tests/gui_acceptance.py --project /tmp/icoda-iteration25-final.b99cfL/project --output /tmp/icoda-iteration25-final.b99cfL/output
```

Exit status: `0`. The newly added, visually inspected hard-fail capture is
`implementation-queue-override.png`: 1200×760 pixels, 65,283 bytes. It visibly contains the `Single entity` scope
control and `Overridden target: centroid — 2 remaining`; its recorded capture metrics are 529 colours and variance
1170.03. Existing GUI captures and navigation assertions also passed unchanged.

Seven unrestricted-product gaps remain in `icoda/docs/SIMULATION.md`: explicit signature confirmation in
`step_panel.py`/Delta approval; auto-approve-while-passing in `step_panel.py` and `step_controller.py`; external-edit
refresh in `icoda.py` plus persisted demotion in `steplog.py`; structured response/adaptation in `response.py` and
`step_controller.py`; exact historical test provenance in `coverage_index.py`; Python profile/generator/real command
integration in specification/generator/step-runner surfaces; and cross-platform release qualification in
`verify.bash` plus the release acceptance documentation.

## 2026-09-10 — iterations 25/26: implementation-queue verification and documentation repair

Iteration 26 ran the three gates omitted from iteration 25. Ruff and mypy were clean, so no production edit was
required. The focused real-App pytest fixture uses the Tk stub installed by `icoda/tests/conftest.py` when
`ICODA_TK_STUB` is not `0`; its `scope_combobox.kwargs` assertion is deliberately stub-only. The real-Tk proof is
`icoda/tests/gui_acceptance.py:require_visible` plus its completed override block and capture.

From `icoda/`, exact static commands and results:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py tests/test_implementation_queue.py tests/test_graph_actions.py
Success: no issues found in 52 source files
```

From the worktree root, exact test commands and results:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
758 passed, 13 skipped in 14.05s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_implementation_queue.py
11 passed in 0.06s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_graph_actions.py::test_real_app_scope_control_and_implement_here_override_persist_and_target_request
1 passed in 0.17s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation
1 passed in 0.49s
```

The simulation test retains its two specification stops and terminal iteration list
`[0, 0, 1, 1, 2, 2, 2, 3, 3]` unchanged.

The same-process display probe was:

```text
DISPLAY=':10.0'
WAYLAND_DISPLAY=None
XDG_SESSION_TYPE='x11'
```

The first attempt exposed only a short-lived Xephyr launch, before application construction:

```text
_tkinter.TclError: couldn't connect to display ":99"
GUI_EXIT=1
```

Xephyr was restarted in a persistent foreground session at `:99`; `xdpyinfo` reported X.Org 1.21.1.11. The exact
successful command from the worktree root was:

```text
DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python icoda/tests/gui_acceptance.py --project /tmp/icoda-iteration26-final.HLaKdE/fresh-project --output /tmp/icoda-iteration26-final.HLaKdE/output
GUI_EXIT=0
```

`implementation-queue-override.png` is 1200×760 pixels and 63,932 bytes. It visibly shows `Single entity` and
`Overridden target: helper — 2 remaining`; the script recorded 511 sampled colours and variance 1149.25. Relative
to iteration 25's retained output, the other captures whose bytes changed were:

```text
call-view-zoomed.png 1200x760 55571 bytes
call-view.png 1200x760 55193 bytes
class-view-zoomed.png 1200x760 60686 bytes
class-view.png 1200x760 58656 bytes
coverage-overview.png 1200x760 76542 bytes
diagram-container-collapsed.png 1200x760 48128 bytes
diagram-container-expanded.png 1200x760 49234 bytes
diagram-coverage-colours.png 1200x760 57398 bytes
diagram-external-expanded.png 1200x760 50880 bytes
diagram-filtered.png 1200x760 50765 bytes
diagram-neighborhood-dimmed.png 1200x760 57271 bytes
diagram-status-colours.png 1200x760 57693 bytes
diagram-unfiltered.png 1200x760 57693 bytes
file-view-zoomed.png 1200x760 52870 bytes
file-view.png 1200x760 52854 bytes
implementation-approach.png 1200x760 61642 bytes
mind-map.png 1200x760 56748 bytes
node-action-menu.png 1200x760 60474 bytes
proposal-batch.png 1200x760 65667 bytes
proposal-delta.png 1200x760 65206 bytes
proposal-source-diff.png 1200x760 66273 bytes
proposal-targeted-tests.png 1200x760 64178 bytes
rule-issues.png 1200x760 100825 bytes
```

The script's Python File, Class, and Call captures were byte-identical to iteration 25. No production edit was
required; only `icoda/docs/GAP_ANALYSIS.md`, `icoda/docs/SIMULATION.md`, and this verification log changed in iteration 26.

## 2026-09-10 — iteration 27: existing-entity signature confirmation gate

`icoda_core.steps.SignatureChange` and `Delta.signature_changes` now carry a frozen, deterministically ordered
comparison of existing declarations. Same-USR changes are direct comparisons; a rename first uses the existing
body-hash/kind/structural-signature pairing and then an unambiguous body-hash/kind fallback when the structural
signature itself changed. Added, removed, body-only, and pure-rename entities are excluded. The dedicated
`StepPanel.signature` tab shows both declarations and `StepPanel.signature_var` shows confirmation state.
`StepController.approve` refuses the current proposal before creating a runner or starting approval work until
`StepController.confirm_signature` records proposal-local confirmation. No `ProjectState` or `StepRecord` field was
added.

The exact focused signature command from the worktree root and result were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_step_results.py::test_delta_pairs_renames_carries_status_and_rejects_unknown_or_changed_bodies icoda/tests/test_step_results.py::test_delta_classifies_only_signature_changes_to_existing_entities icoda/tests/test_step_results.py::test_delta_classifies_a_removed_parameter_as_one_exact_signature_change icoda/tests/test_step_results.py::test_delta_classifies_an_added_parameter_or_return_change_as_one_exact_entry icoda/tests/test_step_results.py::test_delta_signature_change_exclusions icoda/tests/test_step_gui.py::test_panel_requires_and_records_signature_confirmation_with_exact_actions icoda/tests/test_step_gui.py::test_controller_signature_refusal_precedes_all_approval_mutations icoda/tests/test_step_gui.py::test_controller_signature_confirmation_allows_the_same_proposal_and_advances_cursor
12 passed in 0.17s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_step_gui.py
24 passed in 0.11s
```

These pytest GUI assertions use the Tk stub installed by `icoda/tests/conftest.py`: exact enabled-action sets,
separate rendered declaration text, controller no-mutation refusal, and cursor advancement after confirmation. The
only real-Tk proof of the new widget is the completed `gui_acceptance.py` run below. Its initial same-process display
probe was:

```text
DISPLAY=':10.0'
WAYLAND_DISPLAY=None
XDG_SESSION_TYPE='x11'
```

Xephyr was absent at `:99`, then was kept alive in a persistent foreground session with
`Xephyr :99 -screen 1280x800 -ac -noreset`. The exact successful real-Tk command from the worktree root was:

```text
DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python icoda/tests/gui_acceptance.py --project /tmp/icoda-iteration27-final.nSfDx5/project --output /tmp/icoda-iteration27-final.nSfDx5/output
```

Exit status: `0`. `signature-confirmation.png` is 1200×760 pixels and 64,726 bytes. Visual inspection confirms the
existing entity name, previous and proposed declarations, disabled Approve action, enabled fully visible Confirm
signatures action, and unclipped existing controls. The script then invoked the real control and asserted that it
disabled itself and re-enabled Approve. It recorded 525 sampled colours and variance 1163.82. The new block did not
raise, so there was no traceback to fix.

The unchanged simulation kept its two specification stops and terminal iteration list
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation
1 passed in 0.49s
```

Final project-prescribed static commands from `icoda/` and full suite from the worktree root:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 50 source files
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
769 passed, 13 skipped in 14.54s
```

The exact stable synchronous refusal is: `the proposal changes existing entity signatures; confirm the signature
changes before approving`. The focused refusal test proves the persisted state object, byte-for-byte `state.json`,
step-log records, proposal worktree files, controller proposal, and panel proposal remain unchanged.

## 2026-09-10 — iteration 28: cross-proposal signature-confirmation hardening

Two Tk-stub regression tests now prove that signature confirmation belongs only to the exact proposal object. After
proposal A is confirmed, showing distinct signature-changing proposal B restores the exact unconfirmed panel action
set, with `confirm_signature` present and `approve` absent. At controller level, approval of B raises the exact
`SIGNATURE_CONFIRMATION_REQUIRED` message while the persisted `ProjectState`, byte-for-byte `state.json`, and
`StepLog` records remain unchanged. The production code already had both necessary guards:
`StepPanel.show` resets `signature_confirmed`, and `StepController._show_proposal` clears
`confirmed_signature_proposal` before `StepController.approve` checks proposal identity. No production file changed.

The exact project-prescribed static commands from `icoda/` and their results were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 50 source files
```

The full suite and focused evidence from the worktree root were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
771 passed, 13 skipped in 14.61s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_step_results.py
16 passed in 0.15s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_step_gui.py
26 passed in 0.14s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_step_gui.py::test_panel_signature_confirmation_does_not_leak_to_different_proposal icoda/tests/test_step_gui.py::test_controller_signature_confirmation_does_not_authorize_different_proposal
2 passed in 0.09s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation
1 passed in 0.47s
```

The simulation still has its two specification stops, and its terminal iteration list remains
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`.

The same-process display probe was:

```text
DISPLAY=':10.0'
WAYLAND_DISPLAY=None
XDG_SESSION_TYPE='x11'
```

`xdpyinfo -display :99` initially exited 1 because no server was present. Xephyr was then retained in a persistent
foreground session with `Xephyr :99 -screen 1280x800 -ac -noreset`. The exact successful real-Tk command from the
worktree root was:

```text
DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python icoda/tests/gui_acceptance.py --project /tmp/icoda-iteration28-final.2uA6je/project --output /tmp/icoda-iteration28-final.2uA6je/output
```

Exit status: `0`. `signature-confirmation.png` is 1200×760 pixels and 64,726 bytes; its hard-fail capture metrics
record 525 sampled colours and variance 1163.82. Visual inspection confirms the existing entity, both declarations,
disabled Approve action, and enabled fully visible Confirm signatures action. The script invoked that real widget,
verified approval became available only for that proposal, and ran all later acceptance blocks to completion. No
signature-block traceback occurred.

The exact stable synchronous refusal remains: `the proposal changes existing entity signatures; confirm the
signature changes before approving`. No persisted `ProjectState` or `StepRecord` field was added. The focused pytest
GUI tests, including both new cross-proposal assertions, use the Tk stub installed by `icoda/tests/conftest.py`; only
the completed `gui_acceptance.py` run above is real-Tk proof of the `confirm_signature` widget.

## 2026-09-10 — iteration 29: bounded auto-approve while every gate is green

`icoda_core.auto_approve.derive` is a standard-library-only classifier returning a frozen decision. Its exact-set
tests cover a clean implementation proposal plus phase, architecture/approach, build, test, signature, history, and
missing-proposal refusals. `ProjectState.auto_approve` round-trips and a payload written without the field loads it as
`False`. `StepPanel.auto_approve_check` is persisted by `StepController.auto_approve_changed`; the controller uses
the core decision, bounds a run by the remaining queue, automatically commits only passing implementation code
proposals, and leaves every approach, architecture, history, and signature gate with the developer.

The focused Tk-stub commands from the worktree root were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_auto_approve.py
3 passed in 0.11s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_step_gui.py
29 passed in 0.62s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_persistence.py
7 passed in 0.07s
```

The controller test uses `ScriptedProvider`, `_ImmediateThread`, `_run_immediately`, and `runner_factory`. It
automatically approves two green implementation code proposals, with the explicit approach gates still approved by
the developer, then deliberately fails the next proposal test gate. The cursor remains 2, no third code record is
written, and the panel shows `the proposal test gate is not passing`. The control/state assertions in these pytest
files run under the Tk stub from `icoda/tests/conftest.py`. Only the acceptance run below uses real Tk.

The unchanged manual simulation retained its two specification stops and terminal iteration list
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation
1 passed in 0.51s
```

The same-process display probe was:

```text
DISPLAY=':10.0'
WAYLAND_DISPLAY=None
XDG_SESSION_TYPE='x11'
```

No X server was initially present at `:99` (`XEPHYR_99_EXIT=1`). Xephyr was kept alive in a persistent foreground
session as `Xephyr :99 -screen 1280x800 -ac -noreset`; `xdpyinfo` identified X.Org 21.1.11. The exact successful
real-Tk command from the worktree root was:

```text
DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python icoda/tests/gui_acceptance.py --project /tmp/icoda-iteration29-final.NCOEHz/project --output /tmp/icoda-iteration29-final.NCOEHz/output
GUI_EXIT=0
```

`auto-approve.png` is 1200×760 pixels and 58,933 bytes, with 480 sampled colours and variance 1164.79. Visual
inspection confirms the fully visible checked control beside Scope and the developer-visible missing-proposal stop.
The script invoked the real checkbutton, asserted its bound variable changed, restored it, and completed every later
acceptance block. No traceback occurred.

The exact project-prescribed static commands from `icoda/` and the final full suite from the worktree root were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 51 source files
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
778 passed, 13 skipped in 15.04s
```

## 2026-09-10 — iteration 30: gap-2 auto-approve evidence repair

The existing scripted-provider controller regression now also asserts that toggling
`app.panel.auto_approve_var` and dispatching `action("auto_approve_changed")` writes
`ProjectState.auto_approve is True`. It then clears the in-memory variable, reopens the same project, and asserts
that `app.panel.auto_approve_var.get() is True`. These assertions and all focused pytest GUI assertions run with the
Tk stub installed by `icoda/tests/conftest.py`; the completed acceptance script below is the only real-Tk proof of
`StepPanel.auto_approve_check`.

The exact project-prescribed static commands were run from `icoda/`:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 51 source files
```

The focused and full-suite commands were run from the worktree root:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_auto_approve.py
3 passed in 0.12s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_step_gui.py
29 passed in 0.79s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_persistence.py
7 passed in 0.07s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation
1 passed in 0.55s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
778 passed, 13 skipped in 14.78s
```

The unchanged simulation retained its two specification stops and terminal iteration list
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`.

The same-process display probe was:

```text
DISPLAY=':10.0'
WAYLAND_DISPLAY=None
XDG_SESSION_TYPE='x11'
XEPHYR_99_EXIT=1
```

Xephyr was kept alive in a persistent foreground session as
`Xephyr :99 -screen 1280x800 -ac -noreset`; `xdpyinfo` reported X.Org 21.1.11. The exact completed real-Tk command
from the worktree root was:

```text
DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python icoda/tests/gui_acceptance.py --project /tmp/icoda-iteration30-final.LW2h5B/project --output /tmp/icoda-iteration30-final.LW2h5B/output
GUI_EXIT=0
```

`auto-approve.png` is 1200×760 pixels and 59,116 bytes, with 485 sampled colours and variance 1164.98. Visual
inspection confirms that the fully visible checkbutton is checked and that the missing-proposal refusal is visible;
the script continued through every later acceptance block without a traceback. No production file changed.

## 2026-09-10 — iteration 31: gap 3a persisted external-edit demotion

`icoda_core.steplog.apply_statuses` now owns status reconciliation. It uses the existing
`bodyhash.changed` helper and `StepRecord.entity_body_hashes` to demote a tested callable only when both hashes are
available and differ. `ProjectStore.load_model` reapplies that persisted history whenever it reads the cached model.
`node_status.derive` consumes the resulting entity status and reuses `steplog.last_entity_body_hashes` only to set
the stale marker, so it no longer implements a second status demotion. No persisted field was added.

The new end-to-end core regression is
`test_project_store_reconciles_tested_status_after_external_body_edit`. Its edited entity is
`c:@F@edited#`; a fresh `ProjectStore` reads it as `tested` before its cached current body hash changes and as
`implemented` afterward. The same exact-set assertions prove `c:@F@matching#` stays `tested` because its hash still
matches and unrelated `c:@F@unrelated#` stays `stub`.

All pytest assertions below ran with the Tk stub installed by `icoda/tests/conftest.py`. No assertion ran under real
Tk, and no GUI acceptance screenshot was required because this task adds no widget or focus-refresh behavior.

The exact project-prescribed static commands from `icoda/` were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 51 source files
```

The focused and full-suite commands from the worktree root were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_persistence.py
8 passed in 0.11s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_node_status_gui.py
3 passed in 0.10s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation
1 passed in 0.47s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
779 passed, 13 skipped in 14.66s
```

The simulation retained its two specification stops and terminal iteration list
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`; the list did not change. Gap 3b remains deliberately open:
`icoda.py:App` still has no focus-event refresh or file watcher.

## 2026-09-10 — iteration 32: gap 3b focus-driven external-edit refresh

`icoda_core.source_watch.snapshot_files` records frozen project-relative path, `mtime_ns`, and size entries for the
currently analysed files; `changed_files` makes the exact-set decision without Tk, threading, persistence, or a
third-party watcher. `App` keeps this snapshot in memory, binds root `<FocusIn>`, and calls the existing `reload`
path only when the snapshot changed. No `ProjectState` or `StepRecord` field was added.

The first static run exposed one new import-style issue:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
UP035 [*] Import from `collections.abc` instead: `Iterable`
Found 1 error.
```

The minimal fix moved `Iterable` from `typing` to `collections.abc`. The clean prescribed static runs from
`icoda/` were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 52 source files
```

The focused Tk-stub runs from the worktree root were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_source_watch.py
1 passed in 0.04s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py
2 passed in 0.54s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_persistence.py
8 passed in 0.07s
```

`test_changed_files_reports_only_the_edited_analysed_source` returns exactly `{"edited.py"}` and excludes
`untouched.py`. `test_app_focus_refresh_reconciles_external_body_edit_without_reopen` shows
`python:service:answer` as `tested`, edits the body on disk, directly fires the App focus-refresh path in the same
App session, and then shows `implemented`. Before the edit, an unchanged focus event leaves the analysis call count
at 1 and leaves `state.json`, the cached model, and `steps.jsonl` byte-identical. These assertions use the Tk stub;
they do not claim that a real binding fired.

The full worktree suite was:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
781 passed, 13 skipped in 15.24s
```

The simulation still has its two specification stops and terminal iteration list
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`; the list did not change.

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation
1 passed in 0.54s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_app_focus_refresh_reconciles_external_body_edit_without_reopen
1 passed in 0.15s
```

Xephyr was kept alive in a persistent foreground session with:

```text
Xephyr :99 -screen 1280x800 -ac -noreset
```

The exact completed real-Tk command from the worktree root was:

```text
DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python icoda/tests/gui_acceptance.py --project /tmp/icoda-iteration32-final.c3Iemy/project --output /tmp/icoda-iteration32-final.c3Iemy/output
GUI_EXIT=0
```

This real-Tk run generated `<FocusIn>` after editing `python:service:normalize`, waited for a new analysed
`OpenedProject`, and asserted its body hash changed. `external-edit-focus-refresh.png` is 1200×760 pixels and 53,338
bytes; visual inspection confirms a populated, unclipped refreshed File View. Every earlier acceptance block also
completed. The auto-approve controller audit returned:

```text
102:        self._consider_auto_approve(approach_round=True)
129:        self._consider_auto_approve()
211:        self._consider_auto_approve()
227:    def auto_approve_changed(self) -> None:
236:            self._consider_auto_approve(
239:    def _consider_auto_approve(self, *, approach_round: bool = False) -> None:
```

There is no `_maybe_auto_approve` implementation. The corrected capability row names only the existing
`StepController.auto_approve_changed` and `StepController._consider_auto_approve`; controller production code was
not renamed or restructured.

## 2026-09-10 — iteration 33: gap 4a unified-diff proposal parsing and application

The design wording implemented here is: “The response is structured JSON validated against a schema — rationale
and files, as full contents or unified diffs —”. A file entry selects the unified-diff form only when `content`
starts exactly with `diff --git `; all existing full-file entries retain their prior shape and parsing. Pure
`parse_response` produces frozen per-file `DiffHunk` data without filesystem access, Tk, threading, or a third-party
parser. StepRunner validates and stages all patched bytes before the first candidate write. No persisted field was
added.

The exact project-prescribed static commands from `icoda/` were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 52 source files
```

The focused and full-suite commands from the worktree root were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_response.py
7 passed in 0.02s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_steps.py
1 passed, 2 skipped in 0.14s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py
4 passed in 0.55s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation
1 passed in 0.48s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
785 passed, 13 skipped in 15.16s
```

`test_step_runner_unified_diff_and_full_file_produce_identical_candidate_and_delta` writes `service.py` and asserts
`full_bytes == diff_bytes == DIFF_UPDATED_SOURCE.encode("utf-8")` plus `full.delta == patched.delta`.
`test_step_runner_stale_unified_diff_leaves_candidate_files_byte_identical` reports
`could not apply the files: unified diff for 'notes.txt' does not apply: hunk 1 does not match at old line 1` and
asserts `{path: (worktree / path).read_bytes() for path in before} == before` after a valid first-file patch and a
stale second-file patch. The complete simulation retained its two specification stops and terminal iteration list
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`; it did not change.

All pytest commands used the Tk stub installed by `icoda/tests/conftest.py`. The new parser and StepRunner assertions
do not instantiate Tk; the App-level simulation assertions ran on the stub. No widget changed, no screenshot was
required, and no real-Tk claim is made.

## 2026-09-10 — iteration 34: platform-independent unified-diff newlines and provenance repair

Gap 4a now derives every patched line ending from the file being patched. Context is reinserted verbatim; each
removed line is matched with its target line's ending; added replacements inherit the ending of the corresponding
removed line; and pure insertions use the adjacent target line. No `os.linesep` value participates in patching, so
the diff and full-file candidate paths agree on LF independently of the host, CRLF survives, and untouched mixed
endings remain byte-identical. The existing staged `_apply_candidate_files` / `_plan_candidate_change` write path
remains the only candidate writer.

The Git provenance checks were `git log --oneline 170a5a7..HEAD -- icoda/icoda_core/response.py
icoda/icoda_core/steps.py conftest.py`, `git diff 170a5a7 -- icoda/icoda_core/response.py
icoda/icoda_core/steps.py`, and base-object checks with `git cat-file -e`. There are no post-base commits because the
job is intentionally uncommitted. The cumulative base diff plus the controller's retained per-iteration records show
that root `conftest.py` was introduced in iteration 0, while iteration 33 replaced both jsonschema validators and
changed `_retry_request`. `jsonschema` 4.26.0 imports in the gate interpreter, so the hand-written validator was
reverted to `jsonschema.Draft202012Validator`. The retry condition remains
`if proposal.error and proposal.build.ok is not False`: a file-application failure leaves `build.ok` as `None`, and
must therefore be sent as the exact `validation_error` with empty `build_errors` rather than being lost as an empty
compiler failure.

The exact project-prescribed static commands from `icoda/` were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 52 source files
```

The focused and full-suite commands from the worktree root were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_response.py
7 passed in 0.07s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_steps.py
1 passed, 2 skipped in 0.10s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py
8 passed in 0.61s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation
1 passed in 0.48s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
789 passed, 13 skipped in 14.91s
```

The new focused tests are
`test_step_runner_lf_unified_diff_ignores_platform_linesep_and_matches_full_file_bytes`,
`test_step_runner_unified_diff_preserves_crlf_file_endings`,
`test_step_runner_unified_diff_preserves_untouched_mixed_endings_byte_for_byte`, and
`test_step_runner_non_applying_unified_diff_retry_uses_validation_error_without_build_errors`. The LF test's exact
byte-identity assertion is `assert patched_bytes == full_bytes == DIFF_UPDATED_SOURCE.encode("utf-8")`. The complete
simulation retained terminal iteration list `[0, 0, 1, 1, 2, 2, 2, 3, 3]`; it did not change.

No persisted field was added. All pytest assertions used the Tk stub installed by `icoda/tests/conftest.py`; the
App-level complete simulation assertions ran on that stub, no widget changed, no new screenshot was needed, and no
real-Tk claim is made.

## 2026-09-10 — iteration 35: out-of-range unified-diff guard repair

The regression was first pinned through the real `StepRunner`, using `ScriptedProvider`, `_ImmediateThread`,
`_run_immediately`, `runner_factory`, and `_prepared_diff_runner`. With production code still unfixed,
`test_step_runner_past_eof_removal_is_reported_as_non_applying` failed on a two-line `service.py` and
`@@ -3 +3 @@`: `IndexError: list index out of range` escaped from
`icoda/icoda_core/steps.py:355`, `removed.append(replaced[old_index])`. After the repair, a length mismatch between
the target slice and the old patch is part of the existing non-applying guard, so no short or empty slice reaches
the rebuild loop. The end-to-end proposal now carries exactly `could not apply the files: unified diff for
'service.py' does not apply: hunk 1 does not match at old line 3`.

`test_step_runner_context_matches_final_line_without_trailing_newline` fixes the retained behavior: context for a
file's final line without a trailing newline matches, that context is reinserted byte-for-byte, and changing the
preceding line produces exactly `b"new\nfinal"`. No `_patch_line` newline rule, response diff parser, candidate
writer, widget, or persisted field changed. `icoda/docs/SIMULATION.md` was deliberately not edited because the
developer-visible flow, ten stops, and screenshots did not change. The existing screenshots therefore remain the
visual evidence for the unchanged flow; no real-Tk rerun was required.

The orphan searches were:

```text
rg -n "RESPONSE_SCHEMA|_object_problems|_value_problems" icoda/icoda_core/response.py || true
(no output)
rg -n "RESPONSE_SCHEMA|_object_problems|_value_problems" icoda || true
(no output)
rg -n "^[A-Z][A-Z0-9_]*\\s*=|^def _[a-zA-Z0-9_]+\\(" icoda/icoda_core/response.py
13:SCHEMA_PATH = Path(__file__).with_name("response.schema.json")
14:FORBIDDEN_PREFIXES = (".git/", ".icoda/", "build/", "bin/")
15:DIFF_DISCRIMINATOR = "diff --git "
16:HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$")
58:APPROACH_SCHEMA = {
120:def _approach_problems(data: Any) -> list[str]:
147:def _path_problems(files: Any) -> list[str]:
179:def _to_response(data: dict[str, Any]) -> StepResponse:
185:def _file_change(item: dict[str, Any]) -> FileChange:
193:def _parse_unified_diff(path: str, content: str) -> tuple[DiffHunk, ...]:
232:def _hunk_numbers(match: re.Match[str]) -> tuple[int, int, int, int]:
237:def _check_hunk_counts(path: str, number: int, old_count: int, new_count: int, lines: list[str]) -> None:
```

`RESPONSE_SCHEMA` was deleted. The two hand-written-validator helpers `_object_problems` and `_value_problems` had
already been deleted by iteration 34 and remain absent. `validate()` has exactly the body present at base commit
`170a5a7`: it constructs `jsonschema.Draft202012Validator(load_schema())`, formats sorted errors, and appends path
problems. `_approach_problems()` cannot match that base because no approach parser or approach helper existed at
`170a5a7`; it remains later two-round functionality and uses `Draft202012Validator(APPROACH_SCHEMA)` plus the
whitespace and safe-path checks. `load_schema()` reads the same checked-in `SCHEMA_PATH` as the base version, but
uses `SCHEMA_PATH.open()` with `json.load()` instead of `Path.read_text()` with `json.loads()` so the unmodified
iteration-33 test continues to forbid candidate-file reads while allowing the pre-existing schema-resource read.

The exact project-prescribed static commands from `icoda/` were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 52 source files
```

The focused and repository-root commands were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_response.py
7 passed in 0.05s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_steps.py
1 passed, 2 skipped in 0.12s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py
10 passed in 0.72s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation
1 passed in 0.52s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
791 passed, 13 skipped in 15.32s
```

The complete simulation retained terminal iteration list `[0, 0, 1, 1, 2, 2, 2, 3, 3]`; it did not change. The
complete lifecycle and focus-refresh App assertions in the simulation suite ran on the Tk stub installed by
`icoda/tests/conftest.py`; no claim about real Tk is made.

## 2026-09-10 — iteration 36: editable structured-summary adaptation

Discovery found that `response.schema.json` still declared optional `entities` with `name`, `kind`, `file`,
`signature`, and `satisfies`; `response.StepResponse.entities` and `_to_response` already retained it, while
`steps.Proposal` did not expose it. Rejections and constraints already converge in `prompt.StepRequest` and are
rendered by `StepRunner._prompt` → `prompt.build_prompt` → `prompt._feedback`; `StepRunner._retry_request` uses the
same request for validation/build feedback. `StepController.adapt` was extended to put the deterministic summary
change description in `StepRequest.constraints`, with no second request path or provider call site.

`Proposal.entities` is the only new additive field and defaults to `()`. `StepResponse.entities` already had the
additive `()` default; no `ProjectState` or `StepRecord` field was added, and historical logs store no adaptation.
The six new tests are
`test_structured_summary_round_trip_is_canonical_and_has_no_tk_dependency`,
`test_structured_summary_parser_returns_exact_ordinary_problems`,
`test_structured_summary_change_description_is_deterministic`,
`test_entities_free_reply_keeps_the_additive_empty_default`,
`test_panel_disables_structured_adapt_without_a_usable_live_summary`, and
`test_app_adapt_re_requests_through_feedback_and_replaces_proposal`.

The first ruff run reported `Found 1 error.` for the new `step_controller.py` import block. The minimal fix was only
to format that import as ruff's sorted parenthesized group; the exact prescribed clean reruns from `icoda/` were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
```

Focused and repository-root test results were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_adaptation.py
3 passed in 0.01s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_response.py
8 passed in 0.04s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_step_gui.py
31 passed in 0.93s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py
10 passed in 0.65s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation
1 passed in 0.48s
python -m pytest -q
797 passed, 13 skipped in 15.18s
```

The complete simulation's terminal iteration list remained
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`; it did not change. The adaptation, response, StepPanel/StepController, real-App
re-request, replacement-proposal, and complete simulation assertions ran with the Tk stub. No real provider, API
key, network, compiler, or external test command was used by the App-level adapt regression.

Real Tk ran in a persistent foreground server and completed after correcting the acceptance assertion to preserve
the canonical renderer's trailing newline:

```text
Xephyr :99 -screen 1280x800 -ac -noreset
ICODA_TK_STUB=0 DISPLAY=:99 PATH=/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin:$PATH python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-36-structured-adaptation
exit status 0
```

`structured-adaptation.png` is 1200 × 760 pixels and 67,275 bytes. The real-Tk acceptance selected the new Entity
summary tab, required both its text area and Adapt button to be visible, compared its canonical contents, edited the
signature, invoked the control, and observed the `adapt` dispatch. The provider prompt and proposal-replacement
assertions ran only on the Tk stub through the real `StepRunner` and `ScriptedProvider`.

## 2026-09-10 — iteration 37: gap-4b verification repair and free-text adaptation fallback

Review confirmed that structured edits used the existing `StepRequest.constraints` feedback channel, but an
unchanged live summary returned early and could no longer carry a free-text instruction. Reject was not equivalent:
it logged the reason, discarded the proposal, and waited for a separate developer proposal request. The minimal
repair restores the existing hard-constraints dialog only for an unchanged live summary; both structured and
free-text inputs now form one constraints tuple before the same single `StepController.propose` call.
`test_controller_unchanged_structured_summary_falls_back_to_free_text_adaptation` pins the dialog text, semicolon
normalization, and single re-request path.

`StepResponse.entities` is normalized by `response._to_response` to frozen `adaptation.EntitySummary` values,
copied by `Proposal.__post_init__` / `StepRunner.propose`, rendered and gated by `StepPanel`, and compared by
`StepController.adapt`. Architecture budget and step-log entity bookkeeping continue to consume parsed-model
`model.Entity` objects from `Proposal.delta`, not response summaries. Prompt construction consumes only the
resulting string constraints and its checked-in response schema. Compatibility remains pinned by
`test_entities_free_reply_keeps_the_additive_empty_default`,
`test_project_phase_round_trip_and_legacy_defaults`, and
`test_step_log_round_trip_and_legacy_test_result_is_unknown`.

The exact prescribed static commands from `icoda/` were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
```

Focused and repository-root test results were:

```text
python -m pytest -q icoda/tests/test_adaptation.py
3 passed in 0.01s
python -m pytest -q icoda/tests/test_response.py
8 passed in 0.08s
python -m pytest -q icoda/tests/test_step_gui.py
32 passed in 0.95s
python -m pytest -q icoda/tests/test_simulation.py
10 passed in 0.64s
python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation
1 passed in 0.48s
python -m pytest -q
798 passed, 13 skipped in 15.19s
```

The complete simulation retained terminal iteration list `[0, 0, 1, 1, 2, 2, 2, 3, 3]`; it did not change.
No `ProjectState`, `StepRecord`, `StepResponse`, or `Proposal` field was added in this repair.

Real Tk ran on the persistent foreground server `Xephyr :99 -screen 1280x800 -ac -noreset`:

```text
DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-37-structured-adaptation
exit status 0
```

`structured-adaptation.png` is 1200 × 760 pixels and 67,275 bytes. Real Tk selected and validated the canonical
Entity summary and required both it and the Adapt button to be visible. The exact provider-prompt constraint and
replacement-proposal assertions, the restored free-text fallback, and the complete simulation ran only on the Tk
stub; the visual widget reachability and dispatch assertions ran on real Tk.

## 2026-09-10 — iteration 38: exact recorded-test coverage provenance

`icoda_core/coverage_index.py:_entry` no longer substitutes all tests discoverable in the current model when one
successful historical record names no tests. Each record now contributes only identifiers present in its own
`selected_tests`, `expected_files`, or `files`; an empty record contributes no evidence. No persisted field or disk
format changed. The Coverage tab presents the chosen empty-provenance state as `No recorded tests` and uncovered,
and `NodeAppearanceCanvas.node_fill` consumes `NodeAppearance.covered` so coverage colours use the same recorded
test evidence rather than the independent specification `@satisfies` flag.

The focused regression was added before the production repair. From `icoda/`, the unfixed command and failure were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q tests/test_coverage_index.py::test_newest_successful_record_without_named_tests_has_no_coverage
F                                                                        [100%]
=================================== FAILURES ===================================
______ test_newest_successful_record_without_named_tests_has_no_coverage _______
E   AssertionError: assert ('tests/app_test.cpp',) == ()
E     Left contains one more item: 'tests/app_test.cpp'
FAILED tests/test_coverage_index.py::test_newest_successful_record_without_named_tests_has_no_coverage
1 failed in 0.03s
```

After the repair, the same exact command passed:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q tests/test_coverage_index.py::test_newest_successful_record_without_named_tests_has_no_coverage
.                                                                        [100%]
1 passed in 0.01s
```

The complete developer-controlled simulation needed no expectation edit. Its implementation records still credit
`tests/test_service.py`, while architecture step 1 no longer receives that test as evidence. The terminal iteration
list remains `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and `queue_var` containing `empty`:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q tests/test_simulation.py::test_complete_developer_controlled_simulation
.                                                                        [100%]
1 passed in 0.50s
```

The exact prescribed static commands from `icoda/` were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
```

The repository-root full suite, whose previous baseline was 798 passes, includes the new focused regression:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
799 passed, 13 skipped in 15.15s
```

Real Tk ran under the persistent foreground server and the requested acceptance command exited 0:

```text
Xephyr :99 -screen 1280x800 -ac -noreset
DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-38-coverage-provenance
exit status 0
```

`coverage-overview.png` is 1200 × 760 pixels and 94,097 bytes. It visibly presents uncovered rows as
`No recorded tests`. `diagram-coverage-colours.png` is 1200 × 760 pixels and 64,346 bytes; only the callable reached
by the successful record's named test is green, and callables without recorded test evidence are red.

## 2026-09-10 — iteration 39: coverage-colour provenance repair

`icoda_core/node_status.py:derive` already obtained `coverage_entries = coverage.entry_map()`, and its helper's
exact assignment was `covered = entry.covered if entry is not None else None`. Thus `NodeAppearance.covered` was
already recorded step-log evidence supplied by the coverage index, not independent model reachability or
`@satisfies`. `NodeAppearanceCanvas.node_fill` already consumed that value after iteration 38. No colouring-behavior
production fix was required: the new boundary regression passed before the only production edit. That edit removed
the orphaned `NodeAppearance.specification_covered` field and its derivation because it had no remaining consumer.

The focused regression makes `u:uncovered` reachable from a model test whose identifier no successful record names,
while the successful record names the different test that reaches `u:covered`. From the worktree root, its first
run against the existing production behaviour was already green:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_node_status_gui.py::test_coverage_mode_uses_recorded_test_provenance_not_model_reachability
.                                                                        [100%]
1 passed in 0.13s
```

The iteration-38 move of `satisfies=("R-1",)` from the recorded callable to the unrecorded callable remains useful
and is retained: it proves `@satisfies` cannot make the unrecorded node green. The `test_python_gui.py` expectation
also remains `NODE_COLOURS["covered"]`, but not for an empty history: its current fixture explicitly appends an
approved `StepRecord` with `test_ok=True` and `selected_tests=["tests/test_service.py"]`, and that recorded test
reaches `python:service:main`. Reverting that expectation would contradict the exact recorded evidence.

The focused lifecycle and Python GUI commands from the worktree root passed:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation
.                                                                        [100%]
1 passed in 0.48s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_python_gui.py
.....                                                                    [100%]
5 passed in 0.17s
```

The simulation's terminal iteration list is unchanged at `[0, 0, 1, 1, 2, 2, 2, 3, 3]`; cursor 2, gate `none`,
and `queue_var` containing `empty` are also unchanged. No persisted field or on-disk format changed.

The prescribed static commands from `icoda/` passed:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
```

The full suite from the worktree root passed:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
799 passed, 13 skipped in 15.12s
```

No Xephyr process was initially available, so the required persistent foreground server was started with the exact
command `Xephyr :99 -screen 1280x800 -ac -noreset`. With that server kept running, real Tk passed:

```text
DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-39-coverage-colour-provenance
exit status 0
```

`diagram-coverage-colours.png` is 1200 × 760 pixels and 64,346 bytes. `coverage-overview.png` is 1200 × 760 pixels
and 94,097 bytes. Visual inspection confirms the classifications match: diagram nodes are green under the same
successful-record/named-reaching-test condition that produces `Covered` rows, and unrecorded callables are red and
shown as `Uncovered` / `No recorded tests`.

## 2026-09-11 — iteration 40: language-selected Python Code Profile (gap 6a)

`icoda_core/specification.py:default_code_profile` and `default_specification` now select a concrete Python 3.12
profile without changing the default C++ profile. The Python values specify pytest, `python -m pytest`,
`tests/test_<module>.py`, `.py`, snake_case modules/functions, and PascalCase classes. `upgrade` supplies the
unchanged C++ profile to a pre-profile file, preserving compatibility. The additive schema properties are presented
and persisted by `icoda_gui/spec_editor.py:PROFILE_FIELDS`. `icoda_core/prompt.py:_architecture_rules` and
`_implementation_rules` now branch on the persisted profile language, while `App.edit_specification` and
`StepRunner._prompt_context` pass the already detected project language only when constructing a new default
specification. No generator skeleton or build/test command execution changed.

The central regression and legacy compatibility regression were written first. From the worktree root, the exact
unfixed command and failure were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_prompt.py::test_python_profile_and_prompt_rules_are_language_appropriate icoda/tests/test_specification.py::test_pre_profile_specification_loads_with_the_unchanged_cpp_default
FF                                                                       [100%]
=================================== FAILURES ===================================
________ test_python_profile_and_prompt_rules_are_language_appropriate _________
E   TypeError: default_specification() takes 1 positional argument but 2 were given
_____ test_pre_profile_specification_loads_with_the_unchanged_cpp_default ______
E   KeyError: 'code_profile'
2 failed in 0.12s
```

The same focused command after the implementation passed:

```text
.gui-venv/bin/python -m pytest -q icoda/tests/test_prompt.py::test_python_profile_and_prompt_rules_are_language_appropriate icoda/tests/test_specification.py::test_pre_profile_specification_loads_with_the_unchanged_cpp_default
..                                                                       [100%]
2 passed in 0.10s
```

The specification-editor round-trip assertion passed as part of the focused core/editor run:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q icoda/tests/test_prompt.py::test_python_profile_and_prompt_rules_are_language_appropriate icoda/tests/test_specification.py::test_pre_profile_specification_loads_with_the_unchanged_cpp_default icoda/tests/test_spec_editor.py::test_python_profile_fields_are_present_and_persisted
...                                                                      [100%]
3 passed in 0.17s
```

The prescribed static commands from `icoda/` passed:

```text
.gui-venv/bin/python -m ruff check .
All checks passed!
.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
```

The focused lifecycle and Python GUI commands from the worktree root passed:

```text
.gui-venv/bin/python -m pytest -q icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation
.                                                                        [100%]
1 passed in 0.53s
.gui-venv/bin/python -m pytest -q icoda/tests/test_python_gui.py
.....                                                                    [100%]
5 passed in 0.14s
```

No simulation expectation changed. The terminal iteration list remains `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2,
gate `none`, and `queue_var` containing `empty`.

The repository-root full suite passed:

```text
.gui-venv/bin/python -m pytest -q
802 passed, 13 skipped in 15.13s
```

No Xephyr process was initially available, so the persistent foreground server was started with the exact command
`Xephyr :99 -screen 1280x800 -ac -noreset`. With that server still running, the requested real-Tk command passed:

```text
DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-40-python-code-profile
exit status 0
```

`python-code-profile.png` is 1000 × 760 pixels and 41,236 bytes. Visual inspection confirms that it shows Python
3.12, pytest, `python -m pytest`, `tests/test_<module>.py`, `.py`, snake_case module/function naming, and PascalCase
class naming in the real specification editor.

## 2026-09-11 — iteration 42: gap-6a proof repair

No production code or simulation assertion was edited. `App.edit_specification` and
`StepRunner._prompt_context` are the two default-specification language seams. `generator.py` received no gap-6a
Python handling; gap 6b remains open. The only gap-6a line in `steps.py` is the `_prompt_context` call to
`default_specification(self.root.name, analysis.detect_language(self.root))`.

The controlled mutations and restorations were run from the worktree root with the shared GUI environment's
interpreter:

```text
sha256sum icoda/icoda_core/specification.py icoda/icoda_core/prompt.py
995a1239fbfd908952dadb42b33b98bf49d0f9875ab020cfba8197da5ed73a75  icoda/icoda_core/specification.py
10aa1f4eed20436c94465936a9603e093745210a8dc7bd269b805cafaf81972e  icoda/icoda_core/prompt.py
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest icoda/tests/test_specification.py::test_pre_profile_specification_loads_with_the_unchanged_cpp_default -q
FAILED icoda/tests/test_specification.py::test_pre_profile_specification_loads_with_the_unchanged_cpp_default
1 failed in 0.04s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest icoda/tests/test_specification.py::test_pre_profile_specification_loads_with_the_unchanged_cpp_default -q
1 passed in 0.07s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest icoda/tests/test_prompt.py::test_python_profile_and_prompt_rules_are_language_appropriate -q
FAILED icoda/tests/test_prompt.py::test_python_profile_and_prompt_rules_are_language_appropriate
1 failed in 0.10s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest icoda/tests/test_prompt.py::test_python_profile_and_prompt_rules_are_language_appropriate -q
1 passed in 0.09s
sha256sum icoda/icoda_core/specification.py icoda/icoda_core/prompt.py
995a1239fbfd908952dadb42b33b98bf49d0f9875ab020cfba8197da5ed73a75  icoda/icoda_core/specification.py
10aa1f4eed20436c94465936a9603e093745210a8dc7bd269b805cafaf81972e  icoda/icoda_core/prompt.py
```

The prescribed static commands ran from `icoda/`:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
```

The focused and full suites ran from the worktree root:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_python_gui.py icoda/tests/test_spec_editor.py -q
15 passed in 0.62s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
802 passed, 13 skipped in 15.02s
```

The ten-stop terminal list remains `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and `queue_var`
contains `empty`. The test counts agree with the controller's independent capture; elapsed time differs by normal
runtime variance.

The persistent foreground display remained process 63438 after the full suite. Real Tk passed:

```text
Xephyr :99 -screen 1280x800 -ac -noreset
DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-42-python-code-profile
exit status 0
```

`python-code-profile.png` is 1000 × 760 pixels and 41,236 bytes. Visual inspection confirms that all seven Python
values are legible: pytest, `python -m pytest`, `tests/test_<module>.py`, `.py`, snake_case module naming,
PascalCase class naming, and snake_case function naming.

## 2026-09-11 — iteration 43: profile-driven Python skeleton generation (gap 6b)

`icoda_core/generator.py:skeleton_files` now owns one language decision. Its optional `code_profile` mapping drives
the Python source extension, module/class/function naming, test framework, test runner, and test-file convention.
`write_skeleton` forwards that same mapping, and the minimal `App._save_specification` wiring supplies the approved
specification's existing profile. The omitted/default path retains the prior C++ dictionary and bytes. No C++
assertion, expected-output literal, simulation assertion, `steps.py` command, or gap-7 verification code was edited.

The iteration-39 carry-over was checked first. The claim holds: the first approved `StepRecord` names a successful
`tests/test_service.py`, whose model call reaches `python:service:main`; coverage mode expects the shared covered
colour. The second fixture uses the same selected-test/test-ok fields for node-action provenance.

```text
grep -n "test_ok\|selected_tests\|StepRecord" icoda/tests/test_python_gui.py
81:        steplog.StepRecord(
88:            selected_tests=["tests/test_service.py"],
89:            test_ok=True,
149:        steplog.StepRecord(
156:            selected_tests=["tests/test_service.py"],
157:            test_ok=True,
```

The two focused tests were added before production code. Against the unchanged one-argument/two-argument generator
API, the exact command and failure were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest icoda/tests/test_generator.py::test_python_skeleton_files_follow_the_code_profile icoda/tests/test_generator.py::test_generated_python_skeleton_is_analysable -q
FF                                                                       [100%]
=================================== FAILURES ===================================
______________ test_python_skeleton_files_follow_the_code_profile ______________

>   ???
E   TypeError: skeleton_files() takes 1 positional argument but 2 were given

icoda/tests/test_generator.py:31: TypeError
_________________ test_generated_python_skeleton_is_analysable _________________

tmp_path = PosixPath('/tmp/pytest-of-hlavacs/pytest-40/test_generated_python_skeleton0')

>   ???
E   TypeError: write_skeleton() takes 2 positional arguments but 3 were given

icoda/tests/test_generator.py:51: TypeError
=========================== short test summary info ============================
FAILED icoda/tests/test_generator.py::test_python_skeleton_files_follow_the_code_profile
FAILED icoda/tests/test_generator.py::test_generated_python_skeleton_is_analysable
2 failed in 0.15s
```

After implementation, the exact focused command passed:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest icoda/tests/test_generator.py::test_python_skeleton_files_follow_the_code_profile icoda/tests/test_generator.py::test_generated_python_skeleton_is_analysable -q
..                                                                       [100%]
2 passed in 0.12s
```

The default Python file assertion is exactly `.gitignore`, `README.md`, `pyproject.toml`, `src/demo_service.py`,
and `tests/test_demo_service.py`. The custom-profile assertions independently change all seven new path/naming/test
keys. The round trip through `python_analysis.parse_project` expects exactly
`python:src.demo_service:DemoService`, `python:src.demo_service:DemoService.run`,
`python:src.demo_service:main`, and `python:tests.test_demo_service:test_demo_service_runs`, with no parse errors.
The generated pytest test also ran independently:

```text
.                                                                        [100%]
1 passed in 0.00s
```

The two pre-existing C++ tests passed with the host's versioned Clang selected. Neither test's existing assertions
nor any C++ expected-output literal was edited:

```text
CC=clang-18 CXX=clang++-18 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest icoda/tests/test_generator.py::test_identifier_and_files icoda/tests/test_generator.py::test_skeleton_builds_and_is_analysable -q
..                                                                       [100%]
2 passed in 1.14s
```

An execution comparison against `HEAD:icoda/icoda_core/generator.py` additionally proved full C++ mappings and
contents equal for two names:

```text
Demo App: C++ skeleton byte-identical, sha256=e83b24a0d09f82152362bb8be65039a400d36d4020293fab09918502074d5810
3d viewer: C++ skeleton byte-identical, sha256=7b37fc7ac8a5de151c539082aeef159ad125961a1e15ca14d0bcbffd02cf46a3
```

The prescribed static commands ran from `icoda/`:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
```

The required focused suite and the full worktree suite passed:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_generator.py icoda/tests/test_python_gui.py -q
....s.....                                                               [100%]
9 passed, 1 skipped in 0.58s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
804 passed, 13 skipped in 15.09s
```

The full-suite increase from iteration 42's `802 passed, 13 skipped` is exactly the two named new generator tests.
The ten-stop simulation remains `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and queue text containing
`empty`; no simulation assertion was edited.

Xephyr process 69068 remained live and responsive immediately before real Tk. The exact GUI command exited 0 and
captured the established acceptance image set under `iteration-43-python-generator`; no developer-visible GUI
surface changed and no existing capture regressed, so no new generator-specific screenshot was required.

```text
  69068 Ss+  Xephyr :99 -screen 1280x800 -ac -noreset
name of display:    :99
version number:    11.0
vendor string:    The X.Org Foundation
DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-43-python-generator
exit status 0
```

## 2026-09-11 — iteration 44: real profile-driven Python gates (gap 6c)

Before edits, `icoda_core/steps.py:build_project` owned the two CMake build commands,
`icoda_core/steps.py:StepRunner._build_and_parse` combined the persisted test command and selected paths, and
`icoda_core/steps.py:test_project` executed that test command. The requested initial seam query was:

```text
grep -n "def .*build\|def .*test\|subprocess\|cmake\|ctest" icoda/icoda_core/steps.py | head -40
73:def build_project(root: Path, timeout: float = BUILD_TIMEOUT) -> BuildResult:
75:    commands = [["cmake", "--preset", "debug"], ["cmake", "--build", "--preset", "debug"]]
86:def _build_environment(root: Path) -> dict[str, str] | None:
104:def test_project(root: Path, command: Sequence[str], timeout: float = BUILD_TIMEOUT) -> TestResult:
460:    def _test_project(self, root: Path, command: Sequence[str]) -> TestResult:
613:    def rebuild(self, proposal: Proposal) -> Proposal:
632:    def _build_and_parse(self, proposal: Proposal) -> None:
669:    def _selected_tests(self, request: prompt.StepRequest) -> tuple[str, ...]:
```

`icoda_core/steps.py:gate_commands` is now the one language decision. It reads the existing saved Code Profile,
falling back through `analysis.detect_language`, and returns both gate commands. Python uses the current interpreter's
standard-library `compileall -q src` as its cheap build gate and splits the profile's `test_runner`; selected test
paths are appended to that runner. The compile-all gate catches syntax errors anywhere under `src/`, including an
unselected module that a targeted pytest invocation would never import. C++ retains exactly the former two CMake
command lists and `test_selection.command` CTest path. `StepRunner._build_project` and `_gate_commands` are the
smallest profile-bearing seam for worktrees; injected gates remain authoritative.

The focused test lives in a new `icoda/tests/test_python_gates.py` because `test_steps.py` has a module-wide
CMake/Ninja/libclang skip marker that must not suppress a Python-only proof. It was written before the production
change. Against unchanged `steps.py`, the exact command and failure were:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest icoda/tests/test_python_gates.py::test_python_skeleton_real_build_and_targeted_test_gates -q
F                                                                        [100%]
=================================== FAILURES ===================================
___________ test_python_skeleton_real_build_and_targeted_test_gates ____________

tmp_path = PosixPath('/tmp/pytest-of-hlavacs/pytest-48/test_python_skeleton_real_buil0')

>   ???
E   AssertionError: CMake Error: Could not read presets from /tmp/pytest-of-hlavacs/pytest-48/test_python_skeleton_real_buil0/demo-service:
E     File not found: /tmp/pytest-of-hlavacs/pytest-48/test_python_skeleton_real_buil0/demo-service/CMakePresets.json
E
E   assert False is True
E    +  where False = BuildResult(ok=False, output='CMake Error: Could not read presets from /tmp/pytest-of-hlavacs/pytest-48/test_python_sk...e:\nFile not found: /tmp/pytest-of-hlavacs/pytest-48/test_python_skeleton_real_buil0/demo-service/CMakePresets.json\n').ok

icoda/tests/test_python_gates.py:24: AssertionError
=========================== short test summary info ============================
FAILED icoda/tests/test_python_gates.py::test_python_skeleton_real_build_and_targeted_test_gates
1 failed in 0.16s
```

After implementation the identical focused command passed:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest icoda/tests/test_python_gates.py::test_python_skeleton_real_build_and_targeted_test_gates -q
.                                                                        [100%]
1 passed in 0.41s
```

The green assertions are `assert build.ok is True, build.output` and
`assert passing.ok is True, passing.output`. The command assertion is exactly
`assert commands.test == (sys.executable, "-m", "pytest", "-q", "tests/test_demo_service.py")`; it proves both
that the saved profile's non-default `-q` runner was used and that `test_selection.py`'s selected
`tests/test_demo_service.py` was appended. After replacing the two generated `== 0` expectations with `== 1`, the
red assertions are `assert failing.ok is False`,
`assert "FAILED tests/test_demo_service.py::test_demo_service_runs" in failing.output`, and
`assert "assert 0 == 1" in failing.output`. Thus `TestResult.output`, the same field shown to the developer, carries
the real runner failure.

The existing C++ gate test passed with the host's versioned Clang. No existing C++ assertion or expected command
literal was edited in iteration 44:

```text
CC=clang-18 CXX=clang++-18 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest icoda/tests/test_steps.py::test_step_zero_then_propose_approve_reject_undo -q
.                                                                        [100%]
1 passed in 3.34s
```

Ruff and the unchanged mypy scope passed from `icoda/`; the new test file is outside mypy's explicit source list,
so the previous 53-file count is unchanged:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m ruff check .
All checks passed!
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
```

The prescribed focused regression and full worktree suites passed:

```text
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_steps.py icoda/tests/test_generator.py -q
.ss....s                                                                 [100%]
5 passed, 3 skipped in 0.54s
/home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python -m pytest -q
805 passed, 13 skipped in 15.24s
```

The increase from iteration 43's `804 passed, 13 skipped` is exactly the one new test,
`test_python_skeleton_real_build_and_targeted_test_gates`. No simulation assertion was edited: its terminal
iterations remain `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor `2`, gate `none`, and queue text containing `empty`.

Immediately before real Tk, persistent Xephyr was alive and responsive. The exact GUI command exited 0 and wrote
the established 34-image acceptance set under `iteration-44-python-gates`. Gate selection has no new GUI surface;
all existing captures passed and no capture regressed.

```text
  75119 Ss+  Xephyr :99 -screen 1280x800 -ac -noreset
name of display:    :99
version number:    11.0
vendor string:    The X.Org Foundation
DISPLAY=:99 ICODA_TK_STUB=0 /home/hlavacs/Dokumente/GitHub/AI-Loop/ai-loop/.gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-44-python-gates
exit status 0
```

Gap 6 is now `DONE (gaps 6a, 6b, and 6c CLOSED)` in `GAP_ANALYSIS.md` and `SIMULATION.md`; only gap 7,
cross-platform release qualification, remains.

## 2026-09-11 — iteration 45: green Linux verification (gap 7A)

The project verification wrapper is `icoda/verify.bash`; its interpreter bootstrap is owned by the script's
top-level `python` resolution, while `icoda/tests/verify.py:commands` owns the ordered diff, static, provider,
sample-build, coverage, analysis, and GUI checks. Before any production edit, the two required worktree-root runs
failed at their interpreter prerequisites:

```text
bash icoda/verify.bash
verify: run ./icoda.bash once to create .icoda-venv
EXIT_STATUS=1
.gui-venv/bin/python icoda/tests/verify.py
/bin/bash: line 1: .gui-venv/bin/python: No such file or directory
EXIT_STATUS=127
```

Ignored local links to the already-provisioned shared development interpreter satisfied those two local paths.
With the harness otherwise unchanged, its first substantive failure was `sample-build`:

```text
=== sample-build: bash /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/tests/sample_project/build.sh debug ===
-- The CXX compiler identification is GNU 13.3.0
CMake Error in CMakeLists.txt:
  The target named "sample_lib" has C++ sources that may use modules, but the
  compiler does not provide a way to discover the import graph dependencies.
=== sample-build: FAIL (0.1s) ===
```

`icoda_core/steps.py:_build_environment` is the only compiler-selection implementation. On Linux it enumerates
installed `clang++` and numeric-suffixed `clang++-*` executables, probes their reported major version, requires the
matching C compiler and `clang-scan-deps`, and chooses the newest eligible result. No production `clang-18` literal
was added. `icoda/tests/verify.py:commands` reuses that environment and orders the existing sample build before
coverage pytest so tests consume a fresh compile database; `tests/sample_project/build.sh` uses CMake `--fresh` so
a cache created with another compiler cannot retain GCC. The host selection and build result were:

```text
sample-build: selected module-capable compiler /usr/bin/clang++-18
-- The CXX compiler identification is Clang 18.1.3
100% tests passed, 0 tests failed out of 1
=== sample-build: PASS (2.7s) ===
```

The iteration-44 micro-cleanup drops `root` from `StepRunner._gate_commands` because the runner's profile and store
belong to `self.root`; this avoids an empty profile silently falling back through a proposal-worktree root.

```text
def _gate_commands(self, selected_tests: Sequence[str]) -> GateCommands:
    return gate_commands(self.root, self.store.load_state().test_command, selected_tests, self._code_profile())
```

Both exact project entry points then completed green in the persistent `DISPLAY=:99` environment:

```text
bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 90.00%
307 passed, 3 skipped in 31.83s
=== pytest: PASS (32.0s) ===
=== analysis: PASS (0.1s) ===
=== gui: PASS (10.3s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-011331-445566/summary.txt
EXIT_STATUS=0
.gui-venv/bin/python icoda/tests/verify.py
Required test coverage of 85% reached. Total coverage: 90.00%
307 passed, 3 skipped in 31.80s
=== pytest: PASS (32.0s) ===
=== analysis: PASS (0.1s) ===
=== gui: PASS (10.4s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-010803-518809/summary.txt
EXIT_STATUS=0
```

No coverage threshold, skip marker, or coverage file list changed, and no test was added. The measured 90.00% is
5.00 percentage points above the 85% target. The required static and focused commands passed:

```text
.gui-venv/bin/python -m ruff check .
All checks passed!
.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
.gui-venv/bin/python -m pytest icoda/tests/test_steps.py icoda/tests/test_python_gates.py -q
ss..                                                                     [100%]
2 passed, 2 skipped in 0.42s
.gui-venv/bin/python -m pytest icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_steps.py icoda/tests/test_generator.py -q
.ss....s                                                                 [100%]
5 passed, 3 skipped in 0.53s
```

No existing C++ or Python gate assertion or expected command literal was edited. No simulation assertion was edited;
the terminal iterations remain `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and `queue_var` contains
`empty`. The full repository-root result has nine former module/sample skips executing as passes; no tests were added:

```text
.gui-venv/bin/python -m pytest -q
814 passed, 4 skipped in 30.70s
EXIT_STATUS=0
```

Xephyr process 83431 was alive and responsive immediately before the explicit real-Tk run. The exact command wrote
and validated the established 32-screenshot set, including the visually inspected 1200x760 `file-view.png`; no capture
regressed:

```text
83431 Xephyr :99 -screen 1280x800 -ac -noreset
name of display:    :99
version number:    11.0
vendor string:    The X.Org Foundation
DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-45-verify-green
EXIT_STATUS=0
```

Gap 6 remains `DONE (gaps 6a, 6b, and 6c CLOSED)`. Gap 7A is closed at a measured 90.00%; gap 7B (Windows and the
versioned three-platform matrix) and gap 7C (migration, recovery, and performance qualification) remain open.

## 2026-09-11 — iteration 46: persisted-state migration and interrupted-run recovery (gap 7C1)

Both tests were added to `icoda/tests/test_persistence.py` because that existing persistence-focused module has no
blocking module-level skip marker. `test_legacy_project_migrates_additive_defaults_without_changing_saved_values`
materialises a version-2 specification without `code_profile`, a state payload containing only its older phase,
queue, cursor, and test-command values, and a derived model without the later stale/body-hash fields.
`specification.upgrade` supplies `default_code_profile()`; `ProjectState.from_dict` supplies empty
`approved_approach`, batch size 1, empty `MindMapViewState`, `queue_order` scope, empty override, and disabled
auto-approval; `DerivedModel.from_json` and `_entity_from` supply non-stale/empty stale reason and empty body hash.
The assertions explicitly preserve the Unicode/multiline specification fields and every list/record, the exact
phase/queue/cursor/test command, and the model root, libclang version, file, entity, edge, and external values.

The migration test was green on its first run before production changes; no migration production change was needed:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_persistence.py::test_legacy_project_migrates_additive_defaults_without_changing_saved_values -q
.                                                                        [100%]
1 passed in 0.12s
```

Its final green run was:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_persistence.py::test_legacy_project_migrates_additive_defaults_without_changing_saved_values -q
.                                                                        [100%]
1 passed in 0.16s
```

`test_open_project_refuses_truncated_state_and_reports_leftover_worktree` first writes a valid state through
`ProjectStore.ensure`, removes its final seven bytes, and leaves `.icoda/worktree/unfinished.py` as an uncompleted
proposal. It asserts that `session.open_project` refuses the project with the exact useful message, direct
`ProjectStore.load_state` also refuses invalid JSON, and the unfinished file remains byte-exact in the reported
worktree. The failing-first run was:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_persistence.py::test_open_project_refuses_truncated_state_and_reports_leftover_worktree -q
F                                                                        [100%]
=================================== FAILURES ===================================
___ test_open_project_refuses_truncated_state_and_reports_leftover_worktree ____

tmp_path = PosixPath('/tmp/pytest-of-hlavacs/pytest-73/test_open_project_refuses_trun0')

>   ???
E   AttributeError: module 'icoda_core.persistence' has no attribute 'ProjectStateError'. Did you mean: 'ProjectState'?

icoda/tests/test_persistence.py:102: AttributeError
=========================== short test summary info ============================
FAILED icoda/tests/test_persistence.py::test_open_project_refuses_truncated_state_and_reports_leftover_worktree
1 failed in 0.15s
```

That exact missing recovery exception drove `icoda_core/persistence.py:ProjectStateError`. With the exception type
present but before the recovery behavior, the same test then exposed the silent-default defect directly:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_persistence.py::test_open_project_refuses_truncated_state_and_reports_leftover_worktree -q
F                                                                        [100%]
=================================== FAILURES ===================================
___ test_open_project_refuses_truncated_state_and_reports_leftover_worktree ____

tmp_path = PosixPath('/tmp/pytest-of-hlavacs/pytest-83/test_open_project_refuses_trun0')

>   ???
E   Failed: DID NOT RAISE ProjectStateError

icoda/tests/test_persistence.py:103: Failed
=========================== short test summary info ============================
FAILED icoda/tests/test_persistence.py::test_open_project_refuses_truncated_state_and_reports_leftover_worktree
1 failed in 0.14s
```

That `DID NOT RAISE` output drove the strict invalid-JSON branch in `ProjectStore.load_state` and
`icoda_core/session.py:open_project` now validates state before analysis and appends the detected worktree
disposition. Truncated state is refused, not recovered, because its missing bytes cannot be reconstructed without
inventing developer state. The exact developer-visible exception is:

```text
cannot open project: /tmp/icoda-recovery-evidence.NC0fVw/.icoda/state.json contains invalid JSON; refusing to replace the persisted state with defaults; leftover proposal worktree preserved at /tmp/icoda-recovery-evidence.NC0fVw/.icoda/worktree
```

The final recovery run was:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_persistence.py::test_open_project_refuses_truncated_state_and_reports_leftover_worktree -q
.                                                                        [100%]
1 passed in 0.15s
```

The iteration-45 visibility cleanup promoted the unchanged compiler selector to public
`icoda_core.steps.build_environment`, used by both production and verification:

```text
from icoda_core import steps
build_env = steps.build_environment(SAMPLE)
```

The required static gates passed from `icoda/`; no file was added to mypy's explicit input set, so the count remains
53:

```text
.gui-venv/bin/python -m ruff check .
All checks passed!
.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
```

The prescribed simulation/step/persistence suite and full repository suite passed:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_steps.py icoda/tests/test_persistence.py -q
.ss...........                                                           [100%]
12 passed, 2 skipped in 0.54s
.gui-venv/bin/python -m pytest -q
........................................................................ [  8%]
............................................s........................... [ 17%]
........................................................................ [ 26%]
........................................................................ [ 35%]
........................................................................ [ 43%]
........................................................................ [ 52%]
........................................................................ [ 61%]
........................................................................ [ 70%]
..s..................................................................... [ 79%]
........................................................................ [ 87%]
........................................................................ [ 96%]
...........ss...............                                             [100%]
816 passed, 4 skipped in 31.22s
```

The full-suite increase from `814 passed, 4 skipped` is exactly the two named durability tests above. The ten-stop
simulation retains terminal iterations `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and `queue_var`
containing `empty`; no simulation assertion was edited.

The final retained verification entry point exited 0. The tested-branch result remains exactly 90.00%, unchanged
from iteration 45 and above the unchanged 85% threshold:

```text
DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 90.00%
309 passed, 3 skipped in 31.81s
=== pytest: PASS (32.0s) ===
=== analysis: PASS (0.1s) ===
=== gui: PASS (10.4s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-012716-139311/summary.txt
EXIT_STATUS=0
```

Persistent Xephyr process 99388 was live and responsive immediately before the explicit real-Tk run. It exited 0,
the validated `file-view.png` was visually inspected, and the output directory contains exactly 32 PNG files. Thus
iteration 45's 32 count is correct, iteration 44's reported 34 was a reconciliation error, and no capture was lost:

```text
99388 Xephyr :99 -screen 1280x800 -ac -noreset
name of display:    :99
version number:    11.0
vendor string:    The X.Org Foundation
DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-46-durability
EXIT_STATUS=0
find icoda/.icoda-test-artifacts/iteration-46-durability -maxdepth 1 -type f -name '*.png' -printf '%f\n' | wc -l
32
```

Gap 7C is now split: 7C1 migration/recovery is closed by measured evidence, while 7C2 large-project performance
remains open and unmeasured. Gap 7A remains done at 90.00%, and gap 7B remains open; neither Windows qualification
nor the versioned platform matrix was started.

## 2026-09-11 — iteration 47: developer-visible interrupted-state recovery (gap 7C1)

The direct call inventory contains one `session.open_project` call, owned by `App._analyse`; `App.open_project`,
the recent-menu `_opener`, chooser, reload/save, constructor project, and `main` last-project paths all funnel into
that call:

```text
rg -n 'session\.open_project' icoda/icoda.py
640:            self.results.put(session.open_project(root, self.config))
```

`test_open_project_reports_truncated_state_without_tk_traceback` was added to `icoda/tests/test_app.py`. Before the
production change, its exact failing-first output proved that `App.open_project` synchronously propagated the new
exception before reaching `_analyse`'s existing status/dialog reporting path:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_app.py::test_open_project_reports_truncated_state_without_tk_traceback -q
F                                                                        [100%]
=================================== FAILURES ===================================
________ test_open_project_reports_truncated_state_without_tk_traceback ________

self = ProjectStore(root=PosixPath('/tmp/pytest-of-hlavacs/pytest-89/test_open_project_reports_trun0/interrupted'))

>   ???

icoda/icoda_core/persistence.py:165:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
/usr/lib/python3.12/json/__init__.py:346: in loads
    return _default_decoder.decode(s)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib/python3.12/json/decoder.py:337: in decode
    obj, end = self.raw_decode(s, idx=_w(s, 0).end())
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = <json.decoder.JSONDecoder object at 0x753535df6b40>
s = '{\n "phase": "specification",\n "implementation_queue": [],\n "implementation_cursor": 0,\n "test_command": [\n  "cte... {\n  "expanded": []\n },\n "implementation_scope": "queue_order",\n "implementation_override": "",\n "auto_approve": '
idx = 0

    def raw_decode(self, s, idx=0):
        """Decode a JSON document from ``s`` (a ``str`` beginning with
        a JSON document) and return a 2-tuple of the Python
        representation and the index in ``s`` where the document ended.

        This can be used to decode a JSON document from a string that may
        have extraneous data at the end.

        """
        try:
            obj, end = self.scan_once(s, idx)
        except StopIteration as err:
>           raise JSONDecodeError("Expecting value", s, err.value) from None
E           json.decoder.JSONDecodeError: Expecting value: line 17 column 18 (char 329)

/usr/lib/python3.12/json/decoder.py:355: JSONDecodeError

The above exception was the direct cause of the following exception:

app_module = <module 'icoda_app' from '/home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/icoda.py'>
tmp_path = PosixPath('/tmp/pytest-of-hlavacs/pytest-89/test_open_project_reports_trun0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x75353499e1b0>

>   ???

icoda/tests/test_app.py:60:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
icoda/icoda.py:574: in open_project
    ???
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = ProjectStore(root=PosixPath('/tmp/pytest-of-hlavacs/pytest-89/test_open_project_reports_trun0/interrupted'))

>   ???
E   icoda_core.persistence.ProjectStateError: cannot open project: /tmp/pytest-of-hlavacs/pytest-89/test_open_project_reports_trun0/interrupted/.icoda/state.json contains invalid JSON; refusing to replace the persisted state with defaults

icoda/icoda_core/persistence.py:167: ProjectStateError
=========================== short test summary info ============================
FAILED icoda/tests/test_app.py::test_open_project_reports_truncated_state_without_tk_traceback
1 failed in 0.17s
```

`App.open_project` no longer duplicates the state load before the worker; `session.open_project` remains the owner,
and `_analyse`/`_poll` now catch and report its exception. The developer-visible text asserted in both the status and
dialog seam is `cannot open project: <state path> contains invalid JSON; refusing to replace the persisted state with
defaults; leftover proposal worktree preserved at <worktree path>`. The final focused output was:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_app.py::test_open_project_reports_truncated_state_without_tk_traceback -q
.                                                                        [100%]
1 passed in 0.15s
```

`test_open_project_reports_leftover_worktree_when_state_is_valid` was added beside the prior recovery test in
`icoda/tests/test_persistence.py`. It writes a fully valid default `state.json`, then leaves
`.icoda/worktree/unfinished.py`; reopening must return the existing analysis message followed by the exact worktree
preservation notice and leave the file byte-exact. Its exact failing-first and green outputs were:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_persistence.py::test_open_project_reports_leftover_worktree_when_state_is_valid -q
F                                                                        [100%]
=================================== FAILURES ===================================
_______ test_open_project_reports_leftover_worktree_when_state_is_valid ________

tmp_path = PosixPath('/tmp/pytest-of-hlavacs/pytest-87/test_open_project_reports_left0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x71689589dd00>

>   ???
E   AssertionError: assert ['analysis complete'] == ['analysis co...oda/worktree']
E
E     Right contains one more item: 'leftover proposal worktree preserved at /tmp/pytest-of-hlavacs/pytest-87/test_open_project_reports_left0/.icoda/worktree'
E     Use -v to get more diff

icoda/tests/test_persistence.py:122: AssertionError
=========================== short test summary info ============================
FAILED icoda/tests/test_persistence.py::test_open_project_reports_leftover_worktree_when_state_is_valid
1 failed in 0.13s
.gui-venv/bin/python -m pytest icoda/tests/test_persistence.py::test_open_project_reports_leftover_worktree_when_state_is_valid -q
.                                                                        [100%]
1 passed in 0.11s
```

`session.open_project` now appends `leftover proposal worktree preserved at <path>` to normal
`OpenedProject.messages` after a successful state load. This deliberately surfaces the leftover without reclaiming,
deleting, resuming, or offering to discard it.

`test_ensure_preserves_existing_unreadable_state` was green on its first run, before either production edit; no
`ProjectStore.ensure` change was needed. Its durability assertion is exactly
`assert store.state_path.read_bytes() == truncated_state`:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_persistence.py::test_ensure_preserves_existing_unreadable_state -q
.                                                                        [100%]
1 passed in 0.17s
.gui-venv/bin/python -m pytest icoda/tests/test_persistence.py::test_ensure_preserves_existing_unreadable_state -q
.                                                                        [100%]
1 passed in 0.11s
```

The required static and focused gates passed; no source file was added to mypy's explicit set:

```text
cd icoda && .gui-venv/bin/python -m ruff check .
All checks passed!
cd icoda && .gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
.gui-venv/bin/python -m pytest icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_app.py icoda/tests/test_persistence.py -q
.....................                                                    [100%]
21 passed in 0.56s
```

The worktree-root suite gained exactly the three named tests above iteration 46's `816 passed, 4 skipped`:

```text
.gui-venv/bin/python -m pytest -q
........................................................................ [  8%]
............................................s........................... [ 17%]
........................................................................ [ 26%]
........................................................................ [ 34%]
........................................................................ [ 43%]
........................................................................ [ 52%]
........................................................................ [ 61%]
........................................................................ [ 69%]
...s.................................................................... [ 78%]
........................................................................ [ 87%]
........................................................................ [ 96%]
..............ss...............                                          [100%]
819 passed, 4 skipped in 30.66s
```

The retained verification entry point exited 0. No coverage configuration changed; the new recovery branch tests
moved measured coverage from 90.00% to 90.08%:

```text
DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 90.08%
312 passed, 3 skipped in 31.94s
=== pytest: PASS (32.1s) ===
=== analysis: PASS (0.1s) ===
=== gui: PASS (10.4s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-014236-611030/summary.txt
EXIT_STATUS=0
```

No simulation assertion was edited. The ten-stop terminal iterations remain
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor `2`, gate `none`, and `queue_var` containing `empty`.
Immediately before the explicit real-Tk run, Xephyr was alive and responsive. The representative `file-view.png`
was visually inspected, the command exited 0, and its output directory contains exactly the established 32 PNGs:

```text
110227 Xephyr :99 -screen 1280x800 -ac -noreset
name of display:    :99
version number:    11.0
vendor string:    The X.Org Foundation
DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-47-recovery-ui
EXIT_STATUS=0
find icoda/.icoda-test-artifacts/iteration-47-recovery-ui -maxdepth 1 -type f -name '*.png' -printf '%f\n' | wc -l
32
```

Gap 7C1 remains closed with both developer-visible holes pinned. Gap 7A remains closed at its 90.00% qualification
measurement, with the latest exercised result now 90.08%; gap 7B platform qualification and gap 7C2 large-project
performance remain open and were not started.

## 2026-09-11 — iteration 48: persisted phase display after successful open (gap 7C1)

The requested phase inventory was captured before adding the regression test:

```text
grep -n 'set_phase' icoda/icoda.py icoda/icoda_gui/step_panel.py icoda/icoda_gui/step_controller.py
icoda/icoda.py:590:        self.panel.set_phase(persistence.ProjectPhase.SPECIFICATION)
icoda/icoda.py:665:        self.panel.set_phase(state.phase)
icoda/icoda_gui/step_panel.py:153:    def set_phase(self, phase: persistence.ProjectPhase | str) -> None:
icoda/icoda_gui/step_controller.py:293:            self.window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
```

`App.show` is the successful-open owner: `App._poll` sends its `OpenedProject` result to `show`, which obtains the
persisted state through `implementation_queue.ensure_state(store, opened.model)` and passes `state.phase` to
`StepPanel.set_phase`. `App.open_project` performs no synchronous state load.

`test_open_project_shows_persisted_phase_after_analysis` was added to `icoda/tests/test_app.py`. It materialises a
real `.icoda/state.json` whose phase is the non-default `implementation`, opens that root through `App.open_project`
with the existing `ImmediateThread` idiom, and drains `_poll`. It asserts the developer-visible
`app.panel.phase_var` is exactly `implementation`. The first run was green, proving the property already held; there
was no fabricated red run and no production edit:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_app.py::test_open_project_shows_persisted_phase_after_analysis -q
.                                                                        [100%]
1 passed in 0.18s
```

Iteration 47's `test_open_project_reports_truncated_state_without_tk_traceback`,
`test_open_project_reports_leftover_worktree_when_state_is_valid`, and
`test_ensure_preserves_existing_unreadable_state` were not modified. The combined App/persistence run proves all
three remain green alongside the new test:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_app.py icoda/tests/test_persistence.py -q
.....................                                                    [100%]
21 passed in 0.22s
```

Static checks remain green, with the same 53-file mypy set and no source file added:

```text
cd icoda && .gui-venv/bin/python -m ruff check .
All checks passed!
cd icoda && .gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
```

The worktree-root suite gained exactly the one named test over iteration 47's `819 passed, 4 skipped` baseline:

```text
.gui-venv/bin/python -m pytest -q
........................................................................ [  8%]
............................................s........................... [ 17%]
........................................................................ [ 26%]
........................................................................ [ 34%]
........................................................................ [ 43%]
........................................................................ [ 52%]
........................................................................ [ 61%]
........................................................................ [ 69%]
....s................................................................... [ 78%]
........................................................................ [ 87%]
........................................................................ [ 96%]
...............ss...............                                         [100%]
820 passed, 4 skipped in 30.63s
```

The focused developer-control run is one pass above iteration 47 because it includes the new App regression test.
No simulation assertion was edited; the deterministic fake gates remain installed, and the ten-stop terminal
iterations remain `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor `2`, gate `none`, and `queue_var` containing `empty`:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_app.py icoda/tests/test_persistence.py -q
......................                                                   [100%]
22 passed in 0.57s
```

The first harness invocation inherited the desktop display and its GUI stage encountered another application's Tk
grab after every non-GUI gate had passed. The required persistent isolated display was still alive and had no
clients, so the unchanged harness was rerun with `DISPLAY=:99` and exited 0. Its final exact summary shows coverage
did not move from 90.08%:

```text
DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 90.08%
313 passed, 3 skipped in 32.02s
=== pytest: PASS (32.2s) ===
=== analysis: PASS (0.1s) ===
=== gui: PASS (10.4s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-015516-667726/summary.txt
EXIT_STATUS=0
```

Immediately before the explicit real-Tk run, Xephyr was alive and responsive. The command exited 0, produced the
same 32 named captures as iterations 46 and 47, and the visually inspected `file-view.png` shows the step-panel text
`Phase implementation`:

```text
118653 Xephyr :99 -screen 1280x800 -ac -noreset
name of display:    :99
version number:    11.0
vendor string:    The X.Org Foundation
DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-48-phase-display
EXIT_STATUS=0
find icoda/.icoda-test-artifacts/iteration-48-phase-display -maxdepth 1 -type f -name '*.png' -printf '%f\n' | wc -l
32
```

Gap 7A remains done at its 90.00% closure measurement and latest 90.08% exercised result. Gap 7C1 remains closed;
the successful-open phase display is now pinned without weakening unreadable-state recovery. Gap 7B platform
qualification and gap 7C2 large-project performance remain open and were not started.

## 2026-09-11 — iteration 49: large-project performance qualification (gap 7C2)

The timed public entry points were inventoried without changing them:

```text
rg -n '^def (layout_file_view|layout_call_view|layout_class_view|layout_mind_map|build_index|derive)\b' icoda/icoda_core/views.py icoda/icoda_core/coverage_index.py icoda/icoda_core/expansion.py
icoda/icoda_core/expansion.py:98:def derive(model: DerivedModel, graph: Graph, decisions: NodeDecisionMap,
icoda/icoda_core/coverage_index.py:55:def build_index(model: DerivedModel,
icoda/icoda_core/views.py:178:def layout_file_view(model: DerivedModel, clustering: Clustering, width: float = 1600.0,
icoda/icoda_core/views.py:223:def layout_class_view(graph: class_view.ClassGraph) -> ClassViewLayout:
icoda/icoda_core/views.py:282:def layout_mind_map(tree: mind_map.MindMap,
icoda/icoda_core/views.py:363:def layout_call_view(model: DerivedModel, root: str, depth: int = 3, callers: bool = False,
```

`icoda/tests/performance_acceptance.py:main` writes deterministic Python modules, each with one class, eight methods,
three module functions, intra-class calls, and cross-module calls, into a disposable temporary directory at the
50- and 300-module sizes. It measures `python_analysis.parse_project`, `views.layout_file_view`,
`views.layout_call_view`, `views.layout_class_view`, `views.layout_mind_map`, `coverage_index.build_index`, and
`expansion.derive` with `time.perf_counter` and a fresh `tracemalloc` window per call. It writes `performance.json`
and the human-readable `summary.txt` under the requested retained artifact directory.

The exact large-project run exited 0. Its full stdout was:

```text
.gui-venv/bin/python icoda/tests/performance_acceptance.py --output icoda/.icoda-test-artifacts/iteration-49-performance; performance_status=$?; echo EXIT_STATUS=$performance_status
ICODA large-project performance acceptance

Material-growth signal: >= 1.50x large/small microseconds per entity
Interactive-overview interpretation: summed measured stages <= 10.0 seconds

Size: small
Modules: 50
Entities: 600
Edges: 698
Stage                            Seconds    Peak MB    Microseconds/entity
-------------------------------  ---------  ---------  -------------------
parse_project                     0.226819      3.556              378.031
layout_file_view                  0.001992      0.075                3.320
layout_call_view                  0.000240      0.009                0.399
layout_class_view                 0.000262      0.013                0.437
layout_mind_map                   0.002822      0.216                4.704
coverage_index.build_index        0.404264      0.122              673.774
expansion.derive                  0.016933      0.679               28.222

Size: large
Modules: 300
Entities: 3600
Edges: 4198
Stage                            Seconds    Peak MB    Microseconds/entity
-------------------------------  ---------  ---------  -------------------
parse_project                     4.163253     20.799             1156.459
layout_file_view                  0.020001      0.392                5.556
layout_call_view                  0.000754      0.008                0.209
layout_class_view                 0.001389      0.058                0.386
layout_mind_map                   0.017050      1.254                4.736
coverage_index.build_index       84.799324      0.613            23555.368
expansion.derive                  0.155932      3.855               43.314

Scaling assessment:
- parse_project: 378.031 -> 1156.459 us/entity (3.059x); MATERIAL GROWTH.
- layout_file_view: 3.320 -> 5.556 us/entity (1.673x); MATERIAL GROWTH.
- layout_call_view: 0.399 -> 0.209 us/entity (0.524x); no material growth.
- layout_class_view: 0.437 -> 0.386 us/entity (0.883x); no material growth.
- layout_mind_map: 4.704 -> 4.736 us/entity (1.007x); no material growth.
- coverage_index.build_index: 673.774 -> 23555.368 us/entity (34.960x); MATERIAL GROWTH.
- expansion.derive: 28.222 -> 43.314 us/entity (1.535x); MATERIAL GROWTH.

Large summed stage latency: 89.157702 seconds; not acceptable for an interactive overview by the stated <= 10.0s interpretation.
Wrote icoda/.icoda-test-artifacts/iteration-49-performance/performance.json
Wrote icoda/.icoda-test-artifacts/iteration-49-performance/summary.txt
EXIT_STATUS=0
```

The resulting `summary.txt` is exactly the report above from `ICODA large-project performance acceptance` through
the `Large summed stage latency` line. The JSON artifact was also parsed successfully with `python -m json.tool`.
At the declared 1.50x signal, `layout_call_view`, `layout_class_view`, and `layout_mind_map` stayed flat, while four
named OPEN performance defects remain for a later iteration: `icoda_core/python_analysis.py:parse_project`
(378.031 → 1156.459 us/entity), `icoda_core/views.py:layout_file_view` (3.320 → 5.556 us/entity),
`icoda_core/coverage_index.py:build_index` (673.774 → 23555.368 us/entity), and
`icoda_core/expansion.py:derive` (28.222 → 43.314 us/entity). The 89.157702-second large total is not acceptable for
an interactive overview. No production code was changed for speed.

No pytest test was added: deterministic module/entity shape is asserted by the standalone harness itself, while the
requested timing and memory evidence remains outside pytest so it cannot become a flaky gate. The harness was
additionally type-checked from `icoda/`:

```text
.gui-venv/bin/python -m mypy tests/performance_acceptance.py
Success: no issues found in 1 source file
```

The required static gates passed. The explicit 53-file mypy set is unchanged because the new standalone harness is
not one of its listed paths:

```text
cd icoda && .gui-venv/bin/python -m ruff check .
All checks passed!
cd icoda && .gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
```

The root suite has the same result as iteration 48 because no pytest test was added. Runtime moved from 30.63s to
30.69s, a non-material 0.06s:

```text
.gui-venv/bin/python -m pytest -q
........................................................................ [  8%]
............................................s........................... [ 17%]
........................................................................ [ 26%]
........................................................................ [ 34%]
........................................................................ [ 43%]
........................................................................ [ 52%]
........................................................................ [ 61%]
........................................................................ [ 69%]
....s................................................................... [ 78%]
........................................................................ [ 87%]
........................................................................ [ 96%]
...............ss...............                                         [100%]
820 passed, 4 skipped in 30.69s
```

The focused developer-control run is unchanged at 22 passes:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_app.py icoda/tests/test_persistence.py -q
......................                                                   [100%]
22 passed in 0.60s
```

No simulation assertion was edited and its deterministic fake gates remain installed. The ten-stop terminal
iterations remain `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor `2`, gate `none`, and `queue_var` containing `empty`.

The retained verification entry point exited 0. Coverage remains 90.08%, so it did not move from iteration 48 and
remains above the unchanged 85% threshold:

```text
DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 90.08%
313 passed, 3 skipped in 31.93s
=== pytest: PASS (32.1s) ===
=== analysis: PASS (0.1s) ===
=== gui: PASS (10.4s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-021136-186058/summary.txt
EXIT_STATUS=0
```

Persistent Xephyr process 126596 was alive and responsive immediately before the explicit real-Tk run. The command
exited 0, produced exactly the established 32 PNG captures, and the visually inspected `file-view.png` is a valid
1200x760 ICODA overview with its phase, queue, graph controls, hierarchy, provider fields, and developer decisions
visible:

```text
126596 Xephyr :99 -screen 1280x800 -ac -noreset
name of display:    :99
version number:    11.0
vendor string:    The X.Org Foundation
DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-49-performance-ui
EXIT_STATUS=0
find icoda/.icoda-test-artifacts/iteration-49-performance-ui -maxdepth 1 -type f -name '*.png' -printf '%f\n' | wc -l
32
```

Gap 7C2's missing-measurement obligation is therefore DONE WITH NAMED OPEN PERFORMANCE DEFECTS; the current
large-project latency is not interactive, and remediation is deferred. Gap 7C1 remains closed including successful
phase display, gap 7A remains DONE at its 90.00% closure measurement (latest exercised run 90.08%), and gap 7B
remains open and unstarted. `icoda/docs/SIMULATION.md` was not changed because the simulation narrative did not change.

## 2026-09-11 — iteration 50: coverage-index performance repair

The required single-large-call profile kept project generation and parsing outside the profiler. Exact command and
top cumulative-time rows:

```text
.gui-venv/bin/python -c 'import cProfile, importlib.util, pstats, tempfile; from pathlib import Path; spec = importlib.util.spec_from_file_location("performance_acceptance", "icoda/tests/performance_acceptance.py"); harness = importlib.util.module_from_spec(spec); spec.loader.exec_module(harness); from icoda_core import coverage_index, python_analysis; temporary = tempfile.TemporaryDirectory(prefix="icoda-profile-"); project = Path(temporary.name) / "large"; harness._write_project(project, 300); model = python_analysis.parse_project(project); profiler = cProfile.Profile(); profiler.enable(); coverage_index.build_index(model, ()); profiler.disable(); pstats.Stats(profiler).strip_dirs().sort_stats("cumulative").print_stats(15)'
         3674111 function calls in 79.209 seconds

   Ordered by: cumulative time
   List reduced from 18 to 15 due to restriction <15>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        1    0.001    0.001   79.211   79.211 coverage_index.py:55(build_index)
     3301    0.004    0.000   79.210    0.024 coverage_index.py:60(<genexpr>)
     3300    0.004    0.000   79.205    0.024 coverage_index.py:65(_entry)
     3300    0.349    0.000   79.199    0.024 test_selection.py:34(caller_reachable)
   914400   78.678    0.000   78.678    0.000 model.py:140(callers)
   911100    0.063    0.000    0.063    0.000 {method 'add' of 'set' objects}
   914400    0.061    0.000    0.061    0.000 {method 'pop' of 'list' objects}
   911100    0.047    0.000    0.047    0.000 {method 'append' of 'list' objects}
     3302    0.001    0.000    0.002    0.000 {built-in method builtins.sorted}
     3300    0.001    0.000    0.001    0.000 coverage_index.py:93(_entity_key)
     3301    0.000    0.000    0.000 coverage_index.py:62(<genexpr>)
     3300    0.000    0.000    0.000 coverage_index.py:35(covered)
        1    0.000    0.000    0.000 coverage_index.py:89(_callables)
        1    0.000    0.000    0.000 {method 'disable' of '_lsprof.Profiler' objects}
        1    0.000    0.000    0.000 <string>:2(__init__)
```

The dominant function was `icoda/icoda_core/model.py:DerivedModel.callers`, reached from
`icoda/icoda_core/coverage_index.py:_entry`. `build_index` recomputed reverse caller reachability for each of 3,300
callable rows, and every traversal called `DerivedModel.callers`, which rescanned the complete edge list for every
visited node. That repeated per-callable traversal against all model edges produced 914,400 full edge scans and
made cost super-linear. Because `_entry` computed reachability before it inspected records, the same work occurred
with the harness's empty records tuple, explaining the recorded 84.799324 seconds.

Only `icoda/icoda_core/coverage_index.py:build_index`, `_entry`, and the new private
`_candidate_reachability` helper changed in production. The algorithm now builds exact-identifier and normalized-file
lookup maps plus a call-edge adjacency map once per `build_index` call, traverses forward once per distinct identifier
actually named by successful records, and inverts those results into the existing per-row evidence. With no records,
there are no candidate traversals. `build_index`'s public signature did not change; failed, undone, approach, and
unsuccessful records remain excluded, and no model-discovered test fallback was added.

`icoda/tests/test_coverage_index.py:test_index_credits_only_identifiers_named_by_each_successful_record` was added.
It contains seven callables, three call chains, two successful records, two failed records, and a model-reachable test
chain whose test identifier no successful record names; it asserts the complete exact `CoverageIndex`. It was
green-first against the old implementation, and remained green after the repair:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_coverage_index.py::test_index_credits_only_identifiers_named_by_each_successful_record -q
.                                                                        [100%]
1 passed in 0.02s
EXIT_STATUS=0
```

The focused provenance and GUI-consumer suite passed. The existing
`test_coverage_mode_uses_recorded_test_provenance_not_model_reachability` was not edited:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_coverage_index.py icoda/tests/test_node_status_gui.py icoda/tests/test_python_gui.py -q
..............                                                           [100%]
14 passed in 0.19s
EXIT_STATUS=0
```

The unchanged performance harness exited 0. Full stdout:

```text
.gui-venv/bin/python icoda/tests/performance_acceptance.py --output icoda/.icoda-test-artifacts/iteration-50-performance
ICODA large-project performance acceptance

Material-growth signal: >= 1.50x large/small microseconds per entity
Interactive-overview interpretation: summed measured stages <= 10.0 seconds

Size: small
Modules: 50
Entities: 600
Edges: 698
Stage                            Seconds    Peak MB    Microseconds/entity
-------------------------------  ---------  ---------  -------------------
parse_project                     0.224814      3.565              374.690
layout_file_view                  0.002008      0.075                3.347
layout_call_view                  0.000237      0.009                0.395
layout_class_view                 0.000244      0.013                0.407
layout_mind_map                   0.002713      0.216                4.522
coverage_index.build_index        0.003517      0.443                5.862
expansion.derive                  0.017108      0.679               28.513

Size: large
Modules: 300
Entities: 3600
Edges: 4198
Stage                            Seconds    Peak MB    Microseconds/entity
-------------------------------  ---------  ---------  -------------------
parse_project                     4.174826     20.802             1159.674
layout_file_view                  0.020123      0.392                5.590
layout_call_view                  0.000777      0.008                0.216
layout_class_view                 0.001355      0.058                0.376
layout_mind_map                   0.015741      1.254                4.373
coverage_index.build_index        0.020393      2.484                5.665
expansion.derive                  0.155938      3.855               43.316

Scaling assessment:
- parse_project: 374.690 -> 1159.674 us/entity (3.095x); MATERIAL GROWTH.
- layout_file_view: 3.347 -> 5.590 us/entity (1.670x); MATERIAL GROWTH.
- layout_call_view: 0.395 -> 0.216 us/entity (0.547x); no material growth.
- layout_class_view: 0.407 -> 0.376 us/entity (0.924x); no material growth.
- layout_mind_map: 4.522 -> 4.373 us/entity (0.967x); no material growth.
- coverage_index.build_index: 5.862 -> 5.665 us/entity (0.966x); no material growth.
- expansion.derive: 28.513 -> 43.316 us/entity (1.519x); MATERIAL GROWTH.

Large summed stage latency: 4.389153 seconds; acceptable for an interactive overview by the stated <= 10.0s interpretation.
Wrote icoda/.icoda-test-artifacts/iteration-50-performance/performance.json
Wrote icoda/.icoda-test-artifacts/iteration-50-performance/summary.txt
EXIT_STATUS=0
```

`build_index` before/after, using iteration 49 and iteration 50 artifacts:

| Size | Iteration | Seconds | Peak MB | Microseconds/entity | Large/small ratio |
|---|---:|---:|---:|---:|---:|
| small (600 entities) | 49 | 0.404264 | 0.122 | 673.774 | — |
| small (600 entities) | 50 | 0.003517 | 0.443 | 5.862 | — |
| large (3,600 entities) | 49 | 84.799324 | 0.613 | 23555.368 | 34.960x |
| large (3,600 entities) | 50 | 0.020393 | 2.484 | 5.665 | 0.966x |

Large summed stage latency fell from 89.157702s to 4.389153s and is now within the harness's 10.0s interactive
interpretation. `python_analysis.parse_project` now dominates at 4.174826s. The iteration-49 signals remain the
fixed comparison for untouched OPEN defects: `python_analysis.parse_project` 378.031 → 1156.459 us/entity
(3.059x), `views.layout_file_view` 3.320 → 5.556 (1.673x), and `expansion.derive` 28.222 → 43.314 (1.535x).

Static checks ran from `icoda/`; the explicit set remains 53 files because no source file entered or left it:

```text
.gui-venv/bin/python -m ruff check .
All checks passed!
RUFF_EXIT_STATUS=0
.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
MYPY_EXIT_STATUS=0
```

The worktree-root suite gained exactly the one named coverage-index test over the task's 820-pass baseline.
Runtime moved from the stated 30.47s baseline to 31.24s, a non-material 0.77s:

```text
.gui-venv/bin/python -m pytest -q
........................................................................ [  8%]
............................................s........................... [ 17%]
........................................................................ [ 26%]
........................................................................ [ 34%]
........................................................................ [ 43%]
........................................................................ [ 52%]
........................................................................ [ 61%]
........................................................................ [ 69%]
.....s.................................................................. [ 78%]
........................................................................ [ 87%]
........................................................................ [ 96%]
................ss...............                                        [100%]
821 passed, 4 skipped in 31.24s
EXIT_STATUS=0
```

The focused developer-control run remains 22 passes. No simulation assertion was edited, deterministic fake gates
remain installed, and terminal iterations `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor `2`, gate `none`, and queue text
containing `empty` are unchanged:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_app.py icoda/tests/test_persistence.py -q
......................                                                   [100%]
22 passed in 0.61s
EXIT_STATUS=0
```

The retained verification entry point exited 0. Coverage increased from 90.08% to 90.13% and remains above the
unchanged 85% threshold:

```text
DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 90.13%
314 passed, 3 skipped in 31.86s
=== pytest: PASS (32.0s) ===
=== analysis: PASS (0.1s) ===
=== gui: PASS (10.4s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-022701-877616/summary.txt
EXIT_STATUS=0
```

Xephyr was alive and responsive immediately before the separate real-Tk run. It exited 0 and retained exactly the
established 32 PNGs; visual inspection of `coverage-overview.png` and `diagram-coverage-colours.png` confirmed the
recorded-provenance rows and green-covered/red-uncovered colouring still render:

```text
134799 Ss+  Xephyr :99 -screen 1280x800 -ac -noreset
name of display:    :99
version number:    11.0
vendor string:    The X.Org Foundation
DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-50-coverage-speed
EXIT_STATUS=0
find icoda/.icoda-test-artifacts/iteration-50-coverage-speed -maxdepth 1 -type f -name '*.png' -printf '%f\n' | wc -l
32
```

Gap 7C2's measurement slice remains closed and its `coverage_index.build_index` defect is now CLOSED. Gap 7A remains
DONE at its 90.00% closure measurement (latest exercised 90.13%), gap 7C1 remains closed including successful phase
display, and gap 7B remains open and unstarted. The three untouched iteration-49 performance defects remain OPEN.
`icoda/docs/SIMULATION.md` was not changed because neither the simulation narrative nor any assertion changed.

## 2026-09-11 — iteration 51 platform matrix and performance bookkeeping

Gap 7B's exact row named a “versioned macOS/Linux/Windows release matrix” without specifying another file, so the
matrix was created as `icoda/docs/RELEASE_MATRIX.md`. It records Linux as the only qualified platform. Windows and macOS
are unqualified and unmeasured because no such host exists in this environment; it contains no inferred, predicted,
or claimed passing result for either unexecuted platform.

The platform-seam inventory was captured from the worktree root before writing tests:

```text
rg -n 'sys\.platform|os\.name|platform\.system|shutil\.which|os\.get_exec_path|\.exe' icoda/icoda.py icoda/icoda_core icoda/icoda_gui icoda/tests/verify.py
icoda/tests/verify.py:37:    shown = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
icoda/tests/verify.py:72:        "executable": sys.executable,
icoda/tests/verify.py:83:    command = [sys.executable, str(ROOT / "tests" / "gui_acceptance.py"),
icoda/tests/verify.py:85:    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
icoda/tests/verify.py:91:    python = sys.executable
icoda/tests/verify.py:96:    build_script = SAMPLE / ("build.cmd" if os.name == "nt" else "build.sh")
icoda/tests/verify.py:97:    build = ["cmd", "/c", str(build_script), "debug"] if os.name == "nt" \
icoda/icoda_gui/provider_field.py:34:    for suffix in (".exe", ".cmd", ".bat"):
icoda/icoda_core/process.py:63:        if sys.platform == "win32":
icoda/icoda_core/process.py:89:        start_new_session=sys.platform != "win32",
icoda/icoda_core/persistence.py:222:def config_path(platform: str = sys.platform, environ: Mapping[str, str] | None = None,
icoda/icoda_core/analysis.py:275:def libcxx_arguments(compiler: str, arguments: Sequence[str], platform: str = sys.platform) -> list[str]:
icoda/icoda_core/toolchain.py:100:def candidates(platform: str = sys.platform, environ: Mapping[str, str] | None = None,
icoda/icoda_core/toolchain.py:168:def default_sysroot(platform: str = sys.platform) -> str | None:
icoda/icoda_core/steps.py:89:        return GateCommands([[sys.executable, "-m", "compileall", "-q", "src"]],
icoda/icoda_core/steps.py:122:    if sys.platform == "darwin" and not os.environ.get("CXX") and shutil.which("brew"):
icoda/icoda_core/steps.py:127:    elif sys.platform.startswith("linux") and not os.environ.get("CXX"):
icoda/icoda_core/steps.py:129:        for directory in os.get_exec_path():
icoda/icoda_core/steps.py:151:    elif sys.platform == "win32" and not os.environ.get("CXX"):
icoda/icoda_core/steps.py:152:        found = shutil.which("clang-cl")
icoda/icoda_core/agent.py:103:    return Path(candidate).is_file() or shutil.which(candidate) is not None
icoda/icoda_core/agent.py:110:    finder: Callable[[str], str | None] = shutil.which,
icoda/icoda_core/agent.py:135:    finder: Callable[[str], str | None] = shutil.which,
icoda/icoda_core/session.py:153:    command = [sys.executable, "-m", "icoda_core.session", str(root)]
icoda/icoda_core/session.py:217:    if shutil.which("code"):
icoda/icoda_core/session.py:219:    if sys.platform == "darwin":
icoda/icoda_core/session.py:221:    if sys.platform == "win32":
EXIT_STATUS=0
```

The genuine platform-dependent behavior is command rendering, GUI display wrapping, sample-build selection,
Windows/POSIX process handling, configuration paths, libc++ arguments, libclang candidates/sysroot, compiler
discovery, and OS editor selection. The `sys.executable` references are interpreter reuse; the provider suffix loop
is platform-compatible filename probing without a host branch; and `agent.py` uses `shutil.which` only for general
executable availability.

Two new tests were added in `icoda/tests/test_platform_seams.py`:
`test_build_environment_macos_without_homebrew_uses_inherited_environment` and
`test_build_environment_windows_without_clang_cl_uses_inherited_environment`. Both monkeypatch `sys.platform`,
`shutil.which`, and `os.get_exec_path`; each proves its named non-Linux fallback branch bypasses Linux path scanning
and returns `None` without crashing when its native discovery prerequisite is absent. They were green-first, so no
production edit was necessary:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_platform_seams.py -q
..                                                                       [100%]
2 passed in 0.12s
EXIT_STATUS=0
```

The tests prove branch selection only. Existing injected-platform tests cover `persistence.config_path`,
`analysis.libcxx_arguments`, and `toolchain.candidates`, but real Windows/macOS filesystem, compiler, SDK, and
library behavior still needs those hosts. Complete `tests/verify.py` Windows/macOS command execution, Windows
`taskkill`/process trees, macOS SDK/Homebrew success, native editor opening, provider executable suffix/PATH
behavior, and the platform launchers cannot be proven without a real corresponding host.

Static checks ran from `icoda/`. The mypy set remains 53 files because the new pytest-only file is outside its
unchanged explicit source list:

```text
.gui-venv/bin/python -m ruff check .
All checks passed!
RUFF_EXIT_STATUS=0
.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
MYPY_EXIT_STATUS=0
```

The worktree-root suite gained exactly the two named platform-seam tests over iteration 50's 821-pass baseline.
Runtime moved from 31.24s to 31.18s, 0.06s lower and not a material increase:

```text
.gui-venv/bin/python -m pytest -q
823 passed, 4 skipped in 31.18s
EXIT_STATUS=0
```

The focused developer-control run remains 22 passes. No simulation source or assertion was edited, its deterministic
fake gates remain installed, and terminal iterations `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor `2`, gate `none`, and
`queue_var` containing `empty` are unchanged:

```text
.gui-venv/bin/python -m pytest icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_app.py icoda/tests/test_persistence.py -q
......................                                                   [100%]
22 passed in 0.58s
EXIT_STATUS=0
```

The retained Linux verification entry point exited 0. The two new branch tests increase its ICODA test count from
314 to 316 and its exercised coverage from iteration 50's 90.13% to 90.22%, above the unchanged 85% threshold:

```text
DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 90.22%
316 passed, 3 skipped in 32.03s
=== pytest: PASS (32.2s) ===
=== analysis: PASS (0.1s) ===
=== gui: PASS (10.4s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-024320-530911/summary.txt
EXIT_STATUS=0
```

Xephyr was alive and responsive immediately before the separate real-Tk run. The run exited 0 and retained exactly
the established 32 PNGs. Visual inspection of `coverage-overview.png` and `implementation-queue-override.png`
confirmed the project phase, selected target, gates, decision controls, coverage evidence, and overview hierarchy
remain visible:

```text
142911 Xephyr :99 -screen 1280x800 -ac -noreset
name of display:    :99
version number:    11.0
vendor string:    The X.Org Foundation
vendor release number:    12101011
DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-51-release-matrix
EXIT_STATUS=0
find icoda/.icoda-test-artifacts/iteration-51-release-matrix -maxdepth 1 -type f -name '*.png' -printf '%f\n' | wc -l
32
```

Gap 7A remains DONE at its 90.00% closure measurement (latest exercised result 90.22%). Gap 7B is DONE because the
versioned status matrix now exists, while Windows and macOS remain explicitly unqualified/unmeasured rather than
being represented as passing. Gap 7C1 remains closed including developer-visible phase display. Gap 7C2's
`coverage_index.build_index` defect is CLOSED at small 0.404264s → 0.003517s, large 84.799324s / 23555.368
us/entity → 0.020393s / 5.665 us/entity, ratio 34.960x → 0.966x, and summed large latency 89.157702s → 4.389153s.
The open-but-not-blocking measurements are `python_analysis.parse_project` at 4.174826s, 1159.674 us/entity,
3.095x; `views.layout_file_view` at 5.590 us/entity, 1.670x; and `expansion.derive` at 43.316 us/entity, 1.519x.
They are not blocking because the large-project summed overview latency is 4.389153s against the harness's 10.0s
interactive interpretation. `icoda/docs/SIMULATION.md` was not changed because neither its narrative nor any simulation
assertion changed.

## 2026-09-11 — iteration 52 final whole-plan reconciliation

The required ICODA documents had been retained under the worktree-root `docs/` directory, while the requested
`icoda/docs/` directory was absent. The four byte-identical documents were copied into `icoda/docs/`; the original
copies were preserved. The final worktree-root plan inventory commands and their verbatim outputs are:

```text
$ git ls-files '*.md'
CLAUDE.md
README.md
ai-loop/AI_LOOP_BACKLOG.md
ai-loop/IMPLEMENTATION_STATUS.md
ai-loop/README.md
ai-loop/README_FILE_LIST.md
ai-loop/WORKER_SYSTEMS.md
icoda/EVOLUTION.md
icoda/ICODA_PLAN.md
icoda/README.md
$ ls -1 icoda/docs
GAP_ANALYSIS.md
RELEASE_MATRIX.md
SIMULATION.md
VERIFY_LOG.md
```

The established static gates run from `icoda/`. A preliminary repository-root `.gui-venv/bin/python -m ruff
check .` also scanned the separate AI-Loop application and ended with `Found 231 errors.`; no AI-Loop or ICODA
production edit was made for that out-of-scope result. The final ICODA outputs are:

```text
$ .gui-venv/bin/python -m ruff check .
All checks passed!
RUFF_EXIT_STATUS=0
$ .gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
MYPY_EXIT_STATUS=0
```

The final full suite ran from the worktree root. Its count is identical to iteration 51's `823 passed, 4 skipped`;
no test was added, removed, edited, skipped, or renamed:

```text
$ .gui-venv/bin/python -m pytest -q
823 passed, 4 skipped in 30.83s
EXIT_STATUS=0
```

The final focused developer-control run is also unchanged at 22 passes. No simulation assertion was edited; its
deterministic fake gates and terminal invariants remain iterations `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor `2`, gate
`none`, and `queue_var` containing `empty`:

```text
$ .gui-venv/bin/python -m pytest icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_app.py icoda/tests/test_persistence.py -q
......................                                                   [100%]
22 passed in 0.60s
EXIT_STATUS=0
```

The first two fresh real-Tk simulation attempts exposed one genuine developer-visible gate failure. Both persisted
the architecture phase but failed before stop 03 because the panel could retain the old visible phase until the
asynchronous reload completed. The forcing output was:

```text
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/simulation_acceptance.py --project /tmp/icoda-simulation-iteration52-retry-gdRJHF/project --output icoda/.icoda-test-artifacts/iteration-52-final
Traceback (most recent call last):
  File "/home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/tests/simulation_acceptance.py", line 229, in <module>
    raise SystemExit(main())
                     ^^^^^^
  File "/home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/tests/simulation_acceptance.py", line 215, in main
    run.specification()
  File "/home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/tests/simulation_acceptance.py", line 79, in specification
    self._save_specification()
  File "/home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/tests/simulation_acceptance.py", line 117, in _save_specification
    raise RuntimeError("the specification Save control did not persist architecture")
RuntimeError: the specification Save control did not persist architecture
SIMULATION_ACCEPTANCE_EXIT_STATUS=1
SIMULATION_PNG_COUNT=2
SIMULATION_STATE_COUNT=0
```

The single minimal production fix is `icoda/icoda.py:App._save_specification`: immediately after the successful
`phases.transition` it publishes that same persisted `ARCHITECTURE` value through the existing
`StepPanel.set_phase`, before starting asynchronous `open_project`. This makes the persisted and developer-visible
phase agree at stop 02. No other production file changed for iteration 52, and no test or acceptance assertion was
edited.

The persistent display was alive and responsive immediately before both final capture runs:

```text
$ pgrep -af '^Xephyr :99 -screen 1280x800 -ac -noreset$'
151958 Xephyr :99 -screen 1280x800 -ac -noreset
$ DISPLAY=:99 xdpyinfo | sed -n '1,4p'
name of display:    :99
version number:    11.0
vendor string:    The X.Org Foundation
vendor release number:    12101011
```

Both final real-widget capture sets were regenerated after the fix into the same required directory:

```text
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-52-final
GUI_ACCEPTANCE_EXIT_STATUS=0
GUI_ACCEPTANCE_PNG_COUNT=32
TOTAL_PNG_COUNT=42
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/simulation_acceptance.py --project /tmp/icoda-simulation-iteration52-fixed-Nn2zRx/project --output icoda/.icoda-test-artifacts/iteration-52-final
SIMULATION_ACCEPTANCE_EXIT_STATUS=0
SIMULATION_PNG_COUNT=10
SIMULATION_STATE_COUNT=1
phase=implementation
cursor=2
terminal=true
```

All expected captures are present: the general set remains exactly 32, while the simulation set is
`sim-01-specification-code-refused.png` through `sim-10-terminal-overview.png` plus `simulation-state.json`.
Direct visual inspection of `implementation-queue-override.png` confirmed phase `implementation`, the selected
`centroid` target, scope, gate states, and decision controls. `sim-07-normalize-build-test.png` confirmed the
selected `service.Formatter.normalize` target, passed Build and Tests gates, and live Approve/Reject/Adapt controls.
`sim-10-terminal-overview.png` and `coverage-overview.png` confirmed the terminal empty queue and callable/test/step
coverage evidence.

The final post-fix verification entry point ran from the worktree root under the persistent real display:

```text
$ DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 90.22%
316 passed, 3 skipped in 32.01s
=== pytest: PASS (32.2s) ===
=== analysis: PASS (0.1s) ===
=== gui: PASS (10.4s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-030310-843903/summary.txt
VERIFY_EXIT_STATUS=0
```

The measured coverage did not move from iteration 51's 90.22% and remains above the unchanged 85% threshold.
Windows and macOS remain **UNQUALIFIED / UNMEASURED**. `SIMULATION.md` was changed only because stop 02's claimed
immediate developer-visible architecture phase contradicted the repeatedly failing real-Tk gate; it now records the
minimal fix and current gap-7 evidence. Its deterministic fake gates and assertions are unchanged.

The final plan-to-code read also corrected four stale earlier-slice statements in `GAP_ANALYSIS.md`: shared File
View/external expansion, bounded rule issues in prompts, the developer-triggered changed-function test action, and
the existing-project lifecycle/reconciliation are implemented by the symbols now named in their rows. No status was
upgraded without a code symbol. The remaining partial plan items and three open performance defects stay explicit.

## 2026-09-11 — iteration 53 document-tree and phase-publication repair

All four canonical records were re-read before edits. The required initial worktree-root inventory outputs were:

```text
$ ls -1 docs icoda/docs 2>&1
docs:
GAP_ANALYSIS.md
RELEASE_MATRIX.md
SIMULATION.md
VERIFY_LOG.md

icoda/docs:
GAP_ANALYSIS.md
RELEASE_MATRIX.md
SIMULATION.md
VERIFY_LOG.md
$ wc -l docs/*.md icoda/docs/*.md 2>&1
   194 docs/GAP_ANALYSIS.md
    80 docs/RELEASE_MATRIX.md
   229 docs/SIMULATION.md
  3461 docs/VERIFY_LOG.md
   200 icoda/docs/GAP_ANALYSIS.md
    80 icoda/docs/RELEASE_MATRIX.md
   239 icoda/docs/SIMULATION.md
  3606 icoda/docs/VERIFY_LOG.md
  8089 total
$ sha256sum docs/*.md icoda/docs/*.md 2>&1
03f6dbd6d97af0ef12c2dfc710db78fb4adaada04a7adf980b6b548b3318cb83  docs/GAP_ANALYSIS.md
45e45e415ceb769a2082f4ed3910db1d74bb5ef6003afdc4a023d458bd0c4c6b  docs/RELEASE_MATRIX.md
01b858f6fec331c91c9486610611b5ed474b49cedd99ebe157da3330d8406384  docs/SIMULATION.md
6fc8f74ae06363e58883bdfbca58842b30ccce3412436770b67d4867f3f8f7f9  docs/VERIFY_LOG.md
a0092e164529801b4e7408acc64f49a94cc0184d542545d30bb37b56edc9db57  icoda/docs/GAP_ANALYSIS.md
bab62bb349d6c475ed75f2e6ac67e717c642784098e761ec0acd9f64aa2047d3  icoda/docs/RELEASE_MATRIX.md
8f348c18cee4ca953d282e439bdaf37c75302e99357d6c7ca82c4b6a787137ca  icoda/docs/SIMULATION.md
b531d0375e8b6fd84b331742f43298e880f5820f2d76df9321c84c347476c1cb  icoda/docs/VERIFY_LOG.md
$ git status --porcelain -- docs icoda/docs
?? docs/
?? icoda/docs/
```

The pairwise comparison proved that root `VERIFY_LOG.md` was the pre-iteration-52 prefix and that the other three
root files were older, superseded snapshots; they contained no unique record to merge. `icoda/docs/` is canonical.
The canonical files were copied over the four root files before deletion. This required byte-identity proof was:

```text
$ sha256sum docs/*.md icoda/docs/*.md 2>&1
a0092e164529801b4e7408acc64f49a94cc0184d542545d30bb37b56edc9db57  docs/GAP_ANALYSIS.md
bab62bb349d6c475ed75f2e6ac67e717c642784098e761ec0acd9f64aa2047d3  docs/RELEASE_MATRIX.md
8f348c18cee4ca953d282e439bdaf37c75302e99357d6c7ca82c4b6a787137ca  docs/SIMULATION.md
b531d0375e8b6fd84b331742f43298e880f5820f2d76df9321c84c347476c1cb  docs/VERIFY_LOG.md
a0092e164529801b4e7408acc64f49a94cc0184d542545d30bb37b56edc9db57  icoda/docs/GAP_ANALYSIS.md
bab62bb349d6c475ed75f2e6ac67e717c642784098e761ec0acd9f64aa2047d3  icoda/docs/RELEASE_MATRIX.md
8f348c18cee4ca953d282e439bdaf37c75302e99357d6c7ca82c4b6a787137ca  icoda/docs/SIMULATION.md
b531d0375e8b6fd84b331742f43298e880f5820f2d76df9321c84c347476c1cb  icoda/docs/VERIFY_LOG.md
```

Only after that proof, the four root copies and empty root directory were removed:

```text
$ ls -1 docs icoda/docs 2>&1
ls: cannot access 'docs': No such file or directory
icoda/docs:
GAP_ANALYSIS.md
RELEASE_MATRIX.md
SIMULATION.md
VERIFY_LOG.md
$ git status --porcelain -- docs icoda/docs
?? icoda/docs/
```

Every live record reference now names the canonical tree. The following output contains only `icoda/docs/...`
targets; no result points to a worktree-root record:

```text
$ rg -n 'docs/(GAP_ANALYSIS|RELEASE_MATRIX|SIMULATION|VERIFY_LOG)' icoda README.md CLAUDE.md
icoda/docs/VERIFY_LOG.md:961:meet the unrestricted criterion; the exact remaining gaps are the eight items retained in `icoda/docs/SIMULATION.md`:
icoda/docs/VERIFY_LOG.md:1043:Seven unrestricted-product gaps remain in `icoda/docs/SIMULATION.md`: explicit signature confirmation in
icoda/docs/VERIFY_LOG.md:1136:required; only `icoda/docs/GAP_ANALYSIS.md`, `icoda/docs/SIMULATION.md`, and this verification log changed in iteration 26.
icoda/docs/VERIFY_LOG.md:1643:writer, widget, or persisted field changed. `icoda/docs/SIMULATION.md` was deliberately not edited because the
icoda/docs/VERIFY_LOG.md:3111:remains open and unstarted. `icoda/docs/SIMULATION.md` was not changed because the simulation narrative did not change.
icoda/docs/VERIFY_LOG.md:3320:`icoda/docs/SIMULATION.md` was not changed because neither the simulation narrative nor any assertion changed.
icoda/docs/VERIFY_LOG.md:3325:matrix was created as `icoda/docs/RELEASE_MATRIX.md`. It records Linux as the only qualified platform. Windows and macOS
icoda/docs/VERIFY_LOG.md:3460:interactive interpretation. `icoda/docs/SIMULATION.md` was not changed because neither its narrative nor any simulation
icoda/docs/GAP_ANALYSIS.md:70:- Iteration 51 closes gap 7B by recording the versioned three-platform status in `icoda/docs/RELEASE_MATRIX.md` without
icoda/docs/GAP_ANALYSIS.md:168:| Python identities, uncertain dynamic calls, `ast` parser, Python Code Profile, generator, build/test integration, and Python acceptance project | **DONE (gaps 6a, 6b, and 6c CLOSED)** | `icoda/icoda_core/python_analysis.py:parse_project`; `icoda/icoda_core/analysis.py:detect_language`; `icoda/icoda_core/analysis.py:parse_project_for_root`; `icoda/icoda_core/session.py:_derive_model`; `icoda/icoda_core/specification.py:default_code_profile`; `icoda/icoda_core/specification.schema.json`; `icoda/icoda_gui/spec_editor.py:PROFILE_FIELDS`; `icoda/icoda_core/prompt.py:_architecture_rules`; `icoda/icoda_core/prompt.py:_implementation_rules`; `icoda/icoda_core/generator.py:skeleton_files`; `icoda/icoda.py:App._save_specification`; `icoda/icoda_core/steps.py:gate_commands`; `icoda/icoda_core/steps.py:build_project`; `icoda/icoda_core/steps.py:StepRunner._gate_commands`; `icoda/tests/test_generator.py:test_python_skeleton_files_follow_the_code_profile`; `icoda/tests/test_generator.py:test_generated_python_skeleton_is_analysable`; `icoda/tests/test_python_gates.py:test_python_skeleton_real_build_and_targeted_test_gates`; `icoda/tests/test_python_analysis.py`; `icoda/tests/test_python_gui.py`; `icoda/tests/test_prompt.py:test_python_profile_and_prompt_rules_are_language_appropriate`; `icoda/tests/test_specification.py:test_pre_profile_specification_loads_with_the_unchanged_cpp_default`; `icoda/tests/test_spec_editor.py:test_python_profile_fields_are_present_and_persisted`; `icoda/tests/simulation_acceptance.py`; `icoda/tests/gui_acceptance.py:main`; `icoda/docs/SIMULATION.md` | Python auto-detection, AST analysis, all existing GUI views/controls, the language-selected Code Profile, Python-specific prompt rules, editor persistence, profile-driven skeleton generation, self-analysis, and the scripted lifecycle are complete. The single `gate_commands` language seam now gives Python projects a whole-source-tree byte-compilation build gate and executes the profile's test runner with targeted test paths, while C++ keeps its prior CMake/CTest construction. The deterministic simulation keeps its injected fake gates. No gap remains in gap 6. |
icoda/docs/GAP_ANALYSIS.md:171:| Gap 7B — Windows qualification and versioned macOS/Linux/Windows release matrix | **DONE (platform status matrix recorded; Linux only qualified)** | `icoda/docs/RELEASE_MATRIX.md`; `icoda/tests/test_platform_seams.py`; iteration-50 Linux evidence; iteration-51 verification log | The versioned matrix records Linux as the only qualified platform. Windows and macOS are explicitly **UNQUALIFIED / UNMEASURED** because no such host exists in this environment; no passing result is claimed, implied, or predicted for either unexecuted platform. Host-independent branch tests prove only the macOS-without-Homebrew and Windows-without-`clang-cl` fallback selection in `icoda_core/steps.py:build_environment`; they are not host qualification. |
icoda/docs/GAP_ANALYSIS.md:177:| Always-visible project state and developer control over every coding step (finishing criterion) | **DONE** | `icoda/icoda_core/session.py:OpenedProject.summary`; `icoda/icoda.py:App.show`; `icoda/icoda.py:App._refresh_external_edits`; `icoda/icoda_gui/spec_editor.py:SpecificationEditor.save`; `icoda/icoda_gui/step_panel.py:StepPanel`; `icoda/icoda_gui/step_controller.py:StepController`; `icoda/tests/test_app.py:test_open_project_shows_persisted_phase_after_analysis`; `icoda/tests/test_simulation.py:test_complete_developer_controlled_simulation`; `icoda/tests/test_simulation.py:test_app_focus_refresh_reconciles_external_body_edit_without_reopen`; `icoda/tests/test_graph_actions.py:test_real_app_scope_control_and_implement_here_override_persist_and_target_request`; `icoda/tests/test_step_gui.py:test_controller_auto_approves_two_green_steps_then_halts_on_failed_test_gate`; `icoda/tests/test_step_gui.py:test_app_adapt_re_requests_through_feedback_and_replaces_proposal`; `icoda/tests/simulation_acceptance.py:main`; `icoda/tests/gui_acceptance.py:main`; `icoda/docs/SIMULATION.md`; `icoda/docs/RELEASE_MATRIX.md` | The ten-stop simulation proves the lifecycle and refreshed overview surfaces. Iterations 26-51 additionally prove persisted batch scope and phase display, non-head queue override, proposal-local signature confirmation, bounded auto-approval, focus-driven external-edit reconciliation, editable structured proposal adaptation, exact recorded-test provenance, the detected Python Code Profile, profile-driven skeleton generation and gates, green Linux verification, legacy-state migration, App-visible unreadable-state refusal, valid-state leftover-worktree reporting, interactive large-project overview latency, and an honest versioned platform matrix. The three named 7C2 material-growth defects remain open but are not blocking because summed large-project overview latency is 4.389153s against the 10.0s interpretation. |
icoda/docs/GAP_ANALYSIS.md:178:| Final end-to-end step-by-step development simulation and analysis | **DONE** | `icoda/tests/test_simulation.py`; `icoda/tests/simulation_acceptance.py`; `icoda/docs/SIMULATION.md`; `icoda/tests/test_phase_runner.py:test_specification_refusal_precedes_prepare_mutations`; iteration-24 `sim-01-specification-code-refused.png` through `sim-10-terminal-overview.png` | The bounded simulation covers the complete `SPECIFICATION → ARCHITECTURE → IMPLEMENTATION` lifecycle. Iteration 24 directly proves that the sole `StepRunner.prepare` refusal precedes all preparation mutations and removes the duplicate `StepRunner.propose` check; the remaining product gaps are explicitly listed rather than expanded here. |
icoda/docs/GAP_ANALYSIS.md:196:5. **DONE — gap 7B, platform release qualification:** `icoda/docs/RELEASE_MATRIX.md` records the versioned
```

Exactly one test was added. It was green-first because the iteration-52 production line already existed:

```text
$ .gui-venv/bin/python -m pytest icoda/tests/test_app.py::test_save_specification_publishes_architecture_phase_before_reload -q
.                                                                        [100%]
1 passed in 0.18s
FOCUSED_EXIT_STATUS=0
```

With only `icoda.py:App._save_specification`'s architecture `set_phase` line temporarily removed, it failed as
required; the line was restored immediately and the same focused test then passed in 0.17s:

```text
$ .gui-venv/bin/python -m pytest icoda/tests/test_app.py::test_save_specification_publishes_architecture_phase_before_reload -q
F                                                                        [100%]
=================================== FAILURES ===================================
______ test_save_specification_publishes_architecture_phase_before_reload ______

app_module = <module 'icoda_app' from '/home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/icoda.py'>
tmp_path = PosixPath('/tmp/pytest-of-hlavacs/pytest-128/test_save_specification_publis0')

>   ???
E   AssertionError: assert 'specification' == 'architecture'
E
E     - architecture
E     + specification

icoda/tests/test_app.py:201: AssertionError
=========================== short test summary info ============================
FAILED icoda/tests/test_app.py::test_save_specification_publishes_architecture_phase_before_reload
1 failed in 0.16s
MUTATION_EXIT_STATUS=1
```

The restored inventory contains five lines, versus the four recorded before iteration 52:

```text
$ rg -n 'set_phase' icoda/icoda.py icoda/icoda_gui icoda/icoda_core
icoda/icoda.py:590:        self.panel.set_phase(persistence.ProjectPhase.SPECIFICATION)
icoda/icoda.py:619:        self.panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
icoda/icoda.py:666:        self.panel.set_phase(state.phase)
icoda/icoda_gui/step_panel.py:153:    def set_phase(self, phase: persistence.ProjectPhase | str) -> None:
icoda/icoda_gui/step_controller.py:293:            self.window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
```

The static gates ran from `icoda/`:

```text
$ .gui-venv/bin/python -m ruff check .
All checks passed!
RUFF_EXIT_STATUS=0
$ .gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 53 source files
MYPY_EXIT_STATUS=0
```

The worktree-root suite increased by exactly the one new test from iteration 52's `823 passed, 4 skipped` baseline:

```text
$ .gui-venv/bin/python -m pytest -q
824 passed, 4 skipped in 30.74s
ROOT_PYTEST_EXIT_STATUS=0
$ .gui-venv/bin/python -m pytest icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_app.py icoda/tests/test_persistence.py -q
.......................                                                  [100%]
23 passed in 0.57s
FOCUSED_CONTROL_EXIT_STATUS=0
```

No simulation assertion was edited. Its deterministic fake gates and terminal invariants remain iterations
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor `2`, gate `none`, and `queue_var` containing `empty`.

The persistent real display was alive and responsive before GUI execution:

```text
$ pgrep -af '^Xephyr :99 -screen 1280x800 -ac -noreset$'
163569 Xephyr :99 -screen 1280x800 -ac -noreset
$ DISPLAY=:99 xdpyinfo | sed -n '1,4p'
name of display:    :99
version number:    11.0
vendor string:    The X.Org Foundation
vendor release number:    12101011
```

Fresh real-Tk captures were written into one iteration-53 directory:

```text
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-53-final
GUI_ACCEPTANCE_EXIT_STATUS=0
GUI_ACCEPTANCE_PNG_COUNT=32
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/simulation_acceptance.py --project /tmp/icoda-simulation-iteration53-k0V4CR/project --output icoda/.icoda-test-artifacts/iteration-53-final
SIMULATION_ACCEPTANCE_EXIT_STATUS=0
SIMULATION_PNG_COUNT=10
SIMULATION_STATE_COUNT=1
phase=implementation
cursor=2
terminal=true
```

The simulation captures are exactly `sim-01-specification-code-refused.png` through
`sim-10-terminal-overview.png`. Visual inspection of stop 02 showed the six-page specification editor and Save
control; stop 07 showed the implementation target, separate passed Build/Tests gates, delta, and live developer
decisions; stop 10 showed phase `implementation`, four covered callables, an empty queue, and no proposal.

The final project gate ran under that display:

```text
$ DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 90.22%
317 passed, 3 skipped in 31.98s
=== pytest: PASS (32.2s) ===
=== analysis: PASS (0.1s) ===
=== gui: PASS (10.4s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-032312-715175/summary.txt
VERIFY_EXIT_STATUS=0
```

Coverage did not move from iteration 52's 90.22% and remains above the unchanged 85% threshold.

The final plan-to-code reconciliation is:

- M1.1 scaffold — **IMPLEMENTED** by `icoda.py:App`, `icoda.bash:ensure_venv`, `icoda.cmd`, and the ICODA CI job.
- M1.2 helpers — **IMPLEMENTED** by `process.run_bounded`, `process.kill_tree`, `git.promote_worktree`, and `Tooltip`.
- M1.3 sample — **IMPLEMENTED** by `tests/sample_project/CMakeLists.txt`, `src/core/stack.cppm`, and `tests/smoke_test.cpp`.
- M1.4 toolchain — **PARTIALLY IMPLEMENTED** by `toolchain.candidates`, `toolchain.library_beside`, `toolchain.load`, and `session.choose_libclang`; the promised developer-facing chooser is absent.
- M1.5 model — **IMPLEMENTED** by `model.Entity`, `model.Edge`, `model.DerivedModel`, and `model.merge_external_names`.
- M1.6 C++ analysis — **PARTIALLY IMPLEMENTED** by `analysis.Parser`, `analysis.Extractor`, `analysis.parse_doc_comment`, and `analysis.parse_project`; dynamic virtual-call marking and header/source logical pairing are absent.
- M1.7 clustering — **PARTIALLY IMPLEMENTED** by `clusters.seeded_label_propagation`, `clusters.split_large`, `clusters.Layout`, and `ProjectStore.save_layout`; GUI pin/rename controls and Louvain fallback are absent.
- M1.8 File View — **IMPLEMENTED** by `views.layout_file_view`, `views.merge_arrows`, `FileViewCanvas`, and `App.toggle_graph_expansion`.
- M1.9 persistence — **IMPLEMENTED** by `persistence.ProjectStore`, `persistence.UserConfig`, `App._provider_changed`, and `App.show`.
- M1.10 launchers — **IMPLEMENTED** by `icoda.bash:need_tool`, `check_clang`, `check_vcpkg`, `ensure_venv`, and `icoda_python.bash:choose_icoda_python`; Windows/macOS release execution remains unqualified.
- M2.1 generator — **IMPLEMENTED** by `generator.skeleton_files` and `generator.write_skeleton`.
- M2.2 specification — **IMPLEMENTED** by `specification.validate`, `specification.compact`, `SpecificationEditor`, and `App._save_specification`.
- M2.3 agent integration — **IMPLEMENTED** by `agent.load_providers`, `agent.check_providers`, `provider_check.main`, `prompt.build_prompt`, and `ProviderField`.
- M2.4 step protocol — **IMPLEMENTED** by `steps.StepRunner`, `response.parse_response`, `git.working_tree_diff`, and `StepController.adapt`/`undo`.
- M2.5 proposal panel — **IMPLEMENTED** by `StepPanel`, `StepController._show_proposal`, `_rationale_text`, and `_delta_text`.
- M2.6 Call View — **IMPLEMENTED** by `views.layout_call_view`, `CallViewCanvas`, and `CallViewCanvas.show_proposal`.
- M3.1 ordering/selection — **IMPLEMENTED** by `implementation_queue.build`, `override_target`, `target_usr`, and `StepController.implement_here`.
- M3.2 two-round/signature decisions — **IMPLEMENTED** by `StepRunner.propose_approach`, `approve_approach`, `SignatureChange`, `compute_delta`, and `StepController.confirm_signature`.
- M3.3 statuses/changed tests — **IMPLEMENTED** by `steplog.apply_statuses`, `bodyhash.changed`, `test_selection.select_tests`, and `StepController.run_tests`.
- M3.4 batching — **IMPLEMENTED** by `implementation_queue.Scope`, `auto_approve.derive`, and `StepController._consider_auto_approve`.
- M3.5 few-line multi-function grouping — **PARTIALLY IMPLEMENTED** by `prompt._implementation_rules` and `StepRunner.propose`; no grouping selector, size validator, special review treatment, or group test-coverage rule exists.
- M4.1 Class View — **IMPLEMENTED** by `class_view.build_class_graph`, `views.layout_class_view`, and `ClassViewCanvas`.
- M4.2 specification coverage — **PARTIALLY IMPLEMENTED**: `rules.check`, `node_status.derive`, and `CoverageOverview` expose tags/status/test coverage, but uncovered-requirement projection after specification edits is absent.
- M4.3 rule issues — **IMPLEMENTED** by `rules.check`, `rules.for_step`, `IssueOverview`, and `StepRunner._prompt`; EVOLUTION's hard function maximum and generated-code policy requirements remain advisory rather than enforced gates.
- M4.4 mind map — **IMPLEMENTED** by `mind_map.build_mind_map`, `views.layout_mind_map`, `MindMapCanvas`, and `App.select_step`.
- M5 Python — **IMPLEMENTED** by `python_analysis.parse_project`, `analysis.detect_language`, `specification.default_code_profile`, `generator.skeleton_files`, and `steps.gate_commands`.
- EVOLUTION Phase 0 — **IMPLEMENTED** by `SpecificationEditor`, `specification.save`, `generator.write_skeleton`, `phases.transition`, and `App._save_specification`.
- EVOLUTION Phase 1 — **IMPLEMENTED** by `StepRunner.propose`/`approve`/`reject`/`rebuild`/`undo`, `compute_delta`, and `StepController.approve_architecture`.
- EVOLUTION Phase 2 — **IMPLEMENTED EXCEPT M3.5 GROUPING** by `StepRunner.propose_approach`/`approve_approach`, `test_selection.select_tests`, `StepController.confirm_signature`, and `auto_approve.derive`.
- EVOLUTION Phase 3 — **IMPLEMENTED** by `session.open_project`, `App.edit_specification`, `App._refresh_external_edits`, and `steplog.apply_statuses`.
- Gap 7A — **DONE at 90.00% closure measurement**, implemented by `steps.build_environment`, `tests/verify.py:commands`, and `verify.bash`; latest coverage is 90.22%.
- Gap 7B — **DONE as an honest matrix obligation** by `icoda/docs/RELEASE_MATRIX.md` and `tests/test_platform_seams.py`; Windows and macOS remain unqualified/unmeasured.
- Gap 7C1 — **DONE including phase display** by `specification.upgrade`, `ProjectState.from_dict`, `ProjectStore.load_state`, `session.open_project`, `App.show`, and `App._save_specification`.
- Gap 7C2 — **DONE as measurement with `coverage_index.build_index` closed** by `performance_acceptance.main` and `coverage_index.build_index`; the three named performance defects remain open but non-blocking.

Still unimplemented from `ICODA_PLAN.md` / `EVOLUTION.md`: the developer-facing libclang chooser; C++ dynamic/
virtual-call marking; header/source pairing as one logical module node; GUI cluster pin/rename controls and Louvain
fallback; uncovered-requirement/specification-edit coverage projection; deliberate few-line multi-function grouping
selection/validation/review/test rules; hard enforcement of the 50-line maximum, one-test-per-function,
platform-wrapper, and library-policy requirements; real Windows and macOS qualification; and remediation of the
three non-blocking performance defects in `python_analysis.parse_project`, `views.layout_file_view`, and
`expansion.derive`.

## 2026-09-11 — iteration 54 uncovered-requirement projection

The plan words used as the acceptance target were:

```text
Specification coverage: `@satisfies` index, uncovered requirements, untagged entities, highlighting in all views.
```

EVOLUTION's matching behavior is: “a change shows up as uncovered requirements.” The implemented evidence rule is
intentionally narrow: `icoda_core/requirement_coverage.py:project` marks an item covered only when a current
`DerivedModel` entity contains that exact item identifier in the existing parsed `Entity.satisfies` tuple. It does
not infer coverage from text similarity, call reachability, tests, step history, or status. Schema-v2 requirements
retain `R-n`; goals have no stored identifier and therefore use their one-based specification position as `G-n`.
The frozen results are `ImplementingEntity` and `RequirementCoverage`; neither returns a filesystem root or absolute
path, and no persisted field was added.

Both pure tests were red-first: their first run failed during collection because the new module did not yet exist.
The one GUI test was independently red-first with `AttributeError: 'CoverageOverview' object has no attribute
'requirements'`. The final focused runs were:

```text
$ .gui-venv/bin/python -m pytest icoda/tests/test_requirement_coverage.py -q
..                                                                       [100%]
2 passed in 0.01s
FOCUSED_PURE_EXIT_STATUS=0

$ .gui-venv/bin/python -m pytest icoda/tests/test_node_status_gui.py::test_coverage_requirements_repaint_after_specification_save -q
.                                                                        [100%]
1 passed in 0.17s
FOCUSED_GUI_EXIT_STATUS=0
```

The three added tests are
`test_projection_marks_requirement_without_satisfies_entity_uncovered`,
`test_projection_names_explicitly_tagged_implementing_entity`, and
`test_coverage_requirements_repaint_after_specification_save`. The last test renders the existing Coverage tab,
saves a new `R-2`, exercises `App._save_specification` → `App.open_project` → `App.show`, and observes the repainted
covered `R-1` and `UNCOVERED` `R-2` rows.

The persistent display was started before any GUI command and remained alive:

```text
$ pgrep -af '^Xephyr :99 -screen 1280x800 -ac -noreset$'
172803 Xephyr :99 -screen 1280x800 -ac -noreset
$ DISPLAY=:99 xdpyinfo | sed -n '1,4p'
name of display:    :99
version number:    11.0
vendor string:    The X.Org Foundation
vendor release number:    12101011
```

The real-Tk general acceptance added exactly one capture to the prior 32:

```text
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-54-final
GUI_ACCEPTANCE_EXIT_STATUS=0
requirements_coverage={"width": 1200, "height": 760, "colours": 675, "variance": 1227.55}
$ find icoda/.icoda-test-artifacts/iteration-54-final -maxdepth 1 -type f -name '*.png' ! -name 'sim-*.png' | wc -l
33
```

The added file is `requirements-coverage.png`. Visual inspection showed the Coverage tab in its unchanged fifth
position, a “Specification coverage: 2/3 goals and requirements covered · 1 UNCOVERED” summary, covered `G-1` and
`R-54` rows naming `distance`, and an `UNCOVERED` `R-55` row saying `No implementing entity`.

The unchanged deterministic lifecycle was written to the same evidence directory:

```text
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/simulation_acceptance.py --project /tmp/icoda-simulation-iteration54-GNWZ5j/project --output icoda/.icoda-test-artifacts/iteration-54-final
SIMULATION_ACCEPTANCE_EXIT_STATUS=0
$ find icoda/.icoda-test-artifacts/iteration-54-final -maxdepth 1 -type f -name 'sim-*.png' | wc -l
10
phase=implementation
cursor=2
terminal=true
```

Those files are exactly `sim-01-specification-code-refused.png` through `sim-10-terminal-overview.png`. The injected
fake gates and terminal iteration list `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor `2`, gate `none`, and `queue_var`
containing `empty` are unchanged; no simulation assertion was edited.

The static gates ran from `icoda/`. The new core module increases the checked source count from 53 to 54:

```text
$ .gui-venv/bin/python -m ruff check .
All checks passed!
RUFF_EXIT_STATUS=0
$ .gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 54 source files
MYPY_EXIT_STATUS=0
```

The worktree-root suite increased by exactly the three named new tests from iteration 53's
`824 passed, 4 skipped in 30.72s` baseline:

```text
$ .gui-venv/bin/python -m pytest -q
827 passed, 4 skipped in 30.75s
ROOT_PYTEST_EXIT_STATUS=0
$ .gui-venv/bin/python -m pytest icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_app.py icoda/tests/test_persistence.py -q
.......................                                                  [100%]
23 passed in 0.58s
FOCUSED_CONTROL_EXIT_STATUS=0
```

The three-pass increase is one pass each for
`test_projection_marks_requirement_without_satisfies_entity_uncovered`,
`test_projection_names_explicitly_tagged_implementing_entity`, and
`test_coverage_requirements_repaint_after_specification_save`; the four skips are unchanged.

The phase-publication inventory is still exactly the five recorded lines:

```text
$ rg -n 'set_phase' icoda/icoda.py icoda/icoda_gui icoda/icoda_core
icoda/icoda.py:590:        self.panel.set_phase(persistence.ProjectPhase.SPECIFICATION)
icoda/icoda.py:619:        self.panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
icoda/icoda.py:666:        self.panel.set_phase(state.phase)
icoda/icoda_gui/step_panel.py:153:    def set_phase(self, phase: persistence.ProjectPhase | str) -> None:
icoda/icoda_gui/step_controller.py:293:            self.window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
```

The final project gate ran under the persistent real display:

```text
$ DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 90.28%
320 passed, 3 skipped in 32.07s
=== pytest: PASS (32.2s) ===
=== analysis: PASS (0.1s) ===
=== gui: PASS (10.7s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-034431-700739/summary.txt
VERIFY_EXIT_STATUS=0
```

Coverage rose from the previous 90.22% to 90.28% and remains above the unchanged 85% threshold. M4.2's uncovered-
requirement projection is implemented by `requirement_coverage.project` and `CoverageOverview.show`; untagged
entities remain visible as `rules.check`'s `missing-satisfies` issues. The wider EVOLUTION promise to colour every
diagram by specification-tag coverage remains unimplemented: the existing all-view coverage colour mode deliberately
continues to mean exact recorded-test provenance.

## 2026-09-11 — iteration 55 deliberate few-line grouping

The plan acceptance text was “Few-line multi-function steps (getter/setter pair, small overload set).” EVOLUTION
adds: “A step may cover several functions only in simple cases that span a few lines in total, such as a getter/setter
pair or a small overload set.” `icoda_core/grouping.py:derive` is the one pure entry point and returns frozen `Result`
and `GroupedEntity` values. It accepts only an adjacent accessor family or overload set in one project-relative file
and enclosing class, with each current span at or below `code_profile.max_function_lines` and the summed span at or
below `code_profile.hard_max_function_lines`. `ProjectState.implementation_grouping` defaults to `single_entity`;
`StepPanel.grouping_combobox` and `StepController.grouping_changed` own the persisted choice and visible preview.
`StepRunner._implementation_batch` marks deliberate groups, `StepRunner._grouping_refusal` revalidates parsed and
pre-promotion implemented spans, `_test_text` names every member, and
`rules.group_test_coverage` reuses `coverage_index.build_index` and `test_selection` matching to refuse proposal and
approval unless recorded reaching evidence exists for each member.

Both tests in `tests/test_grouping.py` were red-first: the initial run failed collection because `icoda_core.grouping`
did not exist. The GUI test was green-first after the selector implementation. Added tests:

- `test_accepted_accessor_group_names_every_entity_and_requires_evidence_for_each`
- `test_cross_class_accessor_group_is_refused_with_exact_reason`
- `test_grouping_selector_renders_and_changes_the_displayed_queue_target`

Focused results:

```text
$ .gui-venv/bin/python -m pytest icoda/tests/test_grouping.py -q
2 passed in 0.10s
$ .gui-venv/bin/python -m pytest icoda/tests/test_step_gui.py::test_grouping_selector_renders_and_changes_the_displayed_queue_target -q
1 passed in 0.19s
```

The persistent display was started before GUI work and stayed alive:

```text
$ pgrep -af '^Xephyr :99 -screen 1280x800 -ac -noreset$'
181797 Xephyr :99 -screen 1280x800 -ac -noreset
```

Real-Tk evidence:

```text
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-55-final
GUI_ACCEPTANCE_EXIT_STATUS=0
$ find icoda/.icoda-test-artifacts/iteration-55-final -maxdepth 1 -type f -name '*.png' ! -name 'sim-*.png' | wc -l
34
```

The added capture is `few-line-grouping.png`; the previous count was 33. The same directory contains the unchanged
ten `sim-01` through `sim-10` captures from:

```text
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/simulation_acceptance.py --project icoda/.icoda-test-artifacts/iteration-55-final/simulation-project --output icoda/.icoda-test-artifacts/iteration-55-final
SIMULATION_ACCEPTANCE_EXIT_STATUS=0
phase=implementation cursor=2 terminal=true
```

The deterministic fake gates, terminal iterations `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and
`queue_var` containing `empty` are unchanged. Default grouping is one entity, and no simulation assertion was edited.

Static and test gates:

```text
$ cd icoda && .gui-venv/bin/python -m ruff check .
All checks passed!
$ cd icoda && .gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 55 source files
$ .gui-venv/bin/python -m pytest -q
830 passed, 4 skipped in 30.80s
$ .gui-venv/bin/python -m pytest icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_app.py icoda/tests/test_persistence.py -q
23 passed in 0.61s
```

The mypy count rose from 54 to 55 only because of `grouping.py`. The root suite rose by exactly the three tests named
above from the iteration-54 baseline `827 passed, 4 skipped in 30.46s`; all four skips are unchanged.

The phase inventory remains exactly:

```text
icoda/icoda.py:590:        self.panel.set_phase(persistence.ProjectPhase.SPECIFICATION)
icoda/icoda.py:619:        self.panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
icoda/icoda.py:666:        self.panel.set_phase(state.phase)
icoda/icoda_gui/step_panel.py:153:    def set_phase(self, phase: persistence.ProjectPhase | str) -> None:
icoda/icoda_gui/step_controller.py:293:            self.window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
```

Final project verification:

```text
$ DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 89.75%
323 passed, 3 skipped in 31.93s
=== gui: PASS (11.0s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-041419-058076/summary.txt
VERIFY_EXIT_STATUS=0
```

Coverage moved from 90.28% to 89.75% because the new validator adds previously unmeasured refusal branches; it
remains above 85%. No Windows or macOS qualification changed.

## 2026-09-11 — iteration 56 cluster pin and rename controls

The plan says: “Clusters (`icoda_core/clusters.py`): weighted undirected file graph; seeded label propagation (own
implementation, directory as seed) with `networkx` for the graph; split clusters above 40 files; pins and names from
`layout.json`.” EVOLUTION's developer-facing requirement is: “The developer can pin a file to a cluster and rename
clusters; the assignments are stored in `.icoda/layout.json` so that they stay stable between runs and steps.” This
iteration implements those controls and deliberately leaves M1.7's Louvain fallback open.

`icoda_core/clusters.py:LayoutDecision` is frozen; `pin_cluster`, `unpin_cluster`, and `rename_cluster` are pure and
return sorted name/pin tuples. Pin records every current member as `file -> cluster_id`; the existing `cluster_files`
propagation/split runs normally on every analysis, then reapplies recorded file ids last. Unpin removes every pin
targeting that cluster. `Layout.names` and `Layout.pins`, whose `Layout.from_dict` defaults own absent legacy values,
continue through `ProjectStore.save_layout/load_layout`; no `ProjectState` field or second store was added.
`NodeActionMenu` offers Pin, Unpin, and Rename only when `NodeActionContext.cluster_id` is non-empty. At
`App.graph_actions`, that value comes only from a canonical `cluster:`-prefixed node key; an entity uses `entity:` or
a raw id present in `model.entities`. `App.dispatch_graph_action` and `_apply_cluster_layout` persist and repaint.
File View consumes `ClusterCircle.name` in `FileViewCanvas._draw_circles`; Call and Class consume the same renamed
`ExpansionNode.label` in `NodeAppearanceCanvas._draw_expansion_row`; Mind Map consumes `MindMapNode.name` in
`MindMapCanvas._draw_node`.

All four new tests were red-first; their initial combined run reported `4 failed in 0.19s` because the core functions
and `NodeActionContext.cluster_id` did not yet exist. Added tests:

- `test_pinned_cluster_keeps_membership_across_second_clustering_run`
- `test_cluster_rename_is_persisted_and_reloaded`
- `test_unpin_restores_normal_reclustering`
- `test_cluster_menu_pin_and_rename_entries_repaint_displayed_label`

Focused final results:

```text
$ .gui-venv/bin/python -m pytest icoda/tests/test_clusters.py::test_pinned_cluster_keeps_membership_across_second_clustering_run icoda/tests/test_clusters.py::test_cluster_rename_is_persisted_and_reloaded icoda/tests/test_clusters.py::test_unpin_restores_normal_reclustering -q
3 passed in 0.06s
$ .gui-venv/bin/python -m pytest icoda/tests/test_graph_actions.py::test_cluster_menu_pin_and_rename_entries_repaint_displayed_label -q
1 passed in 0.12s
```

The persistent display was started before GUI execution and remained alive:

```text
$ pgrep -af '^Xephyr :99 -screen 1280x800 -ac -noreset$'
197559 Xephyr :99 -screen 1280x800 -ac -noreset
```

Real-Tk evidence:

```text
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-56-final
GUI_ACCEPTANCE_EXIT=0 PNG_COUNT=35
```

The new `cluster-pin-rename.png` shows “Pinned Application Core” with Pin disabled and Unpin enabled. The general PNG
count rose from iteration 55's confirmed 34 after `few-line-grouping.png` to exactly 35.

```text
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/simulation_acceptance.py --project icoda/.icoda-test-artifacts/iteration-56-final/simulation-project --output icoda/.icoda-test-artifacts/iteration-56-final
SIMULATION_ACCEPTANCE_EXIT=0 PNG_COUNT=10
phase=implementation cursor=2 terminal=true
```

The deterministic fake gates, terminal iterations `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and
`queue_var` containing `empty` are unchanged. Pinning defaults off because `Layout.pins` defaults empty, grouping
remains one entity per step, and no simulation assertion was edited.

Static and test gates:

```text
$ cd icoda && .gui-venv/bin/python -m ruff check .
All checks passed!
$ cd icoda && .gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 55 source files
$ .gui-venv/bin/python -m pytest -q
834 passed, 4 skipped in 30.75s
$ .gui-venv/bin/python -m pytest icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_app.py icoda/tests/test_persistence.py -q
23 passed in 0.57s
```

The checked list was 55 source files after iteration 55's `grouping.py` and remains exactly 55 because this iteration
extended existing pure modules. The root suite increased from `830 passed, 4 skipped in 30.50s` by exactly the four
new tests named above; skips are unchanged.

The phase-publication inventory is still exactly five lines:

```text
icoda/icoda.py:591:        self.panel.set_phase(persistence.ProjectPhase.SPECIFICATION)
icoda/icoda.py:620:        self.panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
icoda/icoda.py:667:        self.panel.set_phase(state.phase)
icoda/icoda_gui/step_panel.py:154:    def set_phase(self, phase: persistence.ProjectPhase | str) -> None:
icoda/icoda_gui/step_controller.py:297:            self.window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
```

The unrelated iteration-55 cosmetic drift was reverted: the restored docstring begins “Connects the step panel and
the Call View to a :class:`steps.StepRunner`.” and the blank line after StepPanel's `# -- state` banner is restored.

Final project verification:

```text
$ DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 89.78%
327 passed, 3 skipped in 32.09s
=== pytest: PASS (32.3s) ===
=== analysis: PASS (0.1s) ===
=== gui: PASS (11.2s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-043108-102223/summary.txt
VERIFY_EXIT=0
```

Coverage is 0.50 percentage points below iteration 54's last quoted 90.28%, and 0.03 points above iteration 55's
89.75%; it remains above the unchanged 85% threshold. Windows and macOS rows remain unqualified and unchanged.

## 2026-09-11 — iteration 57 deterministic Louvain fallback

`ICODA_PLAN.md` names directory-seeded label propagation, the max-40 split, and persisted pins/names but contains no
Louvain sentence. `EVOLUTION.md` says: “Clusters are computed by community detection on the undirected, weighted
dependency graph (label propagation first; Louvain if the result is not stable enough), seeded by directory so that
the initial clustering follows the folder structure.” The implemented exact rule is: “Use Louvain if and only if the
file graph contains more than MAX_CLUSTER_SIZE files and seeded label propagation assigns every file the same
label.” NetworkX 3.6.1 supplies `louvain_communities`; the private helper uses seed 0, sorted graph construction and
communities, and majority directory seeds with deterministic suffixes. The existing max-40 split, pin override, and
rename map remain later in `cluster_files`. `Clustering.algorithm` defaults to `seeded_label_propagation`, and the
existing `OpenedProject.summary` status line displays it. The sample has 13 files and remains seven unchanged seeded
clusters. The single-file-to-developer-chosen-cluster picker remains missing, so the M1.7 row stays PARTIAL.

The four new clustering tests were red-first. Their final focused run, including the existing graph-action,
simulation, and mind-map regressions, was:

```text
$ .gui-venv/bin/python -m pytest icoda/tests/test_clusters.py icoda/tests/test_graph_actions.py icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_mind_map.py -q
27 passed in 0.72s
```

Static and root gates:

```text
$ cd icoda && .gui-venv/bin/python -m ruff check .
All checks passed!
$ cd icoda && .gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 55 source files
$ .gui-venv/bin/python -m pytest -q
838 passed, 4 skipped in 30.82s
```

The root increase from iteration 56's `834 passed, 4 skipped in 30.96s` is exactly the four new tests in
`tests/test_clusters.py`; no skip changed and no source module was added, so the mypy scope remains 55 files.

Xephyr was started before real-widget work and remained alive:

```text
206027 Xephyr :99 -screen 1280x800 -ac -noreset
```

Real-Tk evidence in the shared iteration-57 directory:

```text
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-57-final
GUI_ACCEPTANCE_EXIT=0 GENERAL_PNG_COUNT=35
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/simulation_acceptance.py --project icoda/.icoda-test-artifacts/iteration-57-final/simulation-project-final --output icoda/.icoda-test-artifacts/iteration-57-final
SIMULATION_ACCEPTANCE_EXIT=0 SIM_PNG_COUNT=10
phase=implementation cursor=2 terminal=true
```

The general count remains 35 because the selected algorithm uses the existing status line, so no dedicated widget
or capture was needed. The three-file simulation fixture does not trigger the fallback. Its deterministic fake gates,
terminal iterations `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, `queue_var` containing `empty`, default-off
pinning, and one-entity grouping remain unchanged; no simulation assertion was edited.

The phase inventory remains exactly five lines:

```text
icoda/icoda.py:591:        self.panel.set_phase(persistence.ProjectPhase.SPECIFICATION)
icoda/icoda.py:620:        self.panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
icoda/icoda.py:667:        self.panel.set_phase(state.phase)
icoda/icoda_gui/step_panel.py:154:    def set_phase(self, phase: persistence.ProjectPhase | str) -> None:
icoda/icoda_gui/step_controller.py:297:            self.window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
```

Final project verification:

```text
$ DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 89.80%
331 passed, 3 skipped in 31.99s
=== pytest: PASS (32.2s) ===
=== analysis: PASS (0.1s) ===
=== gui: PASS (11.3s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-044825-776411/summary.txt
VERIFY_EXIT=0
```

Coverage moved up 0.02 percentage points from iteration 56's 89.78% and remains above 85%. Windows and macOS rows
remain unqualified and unchanged.

## 2026-09-11 — iteration 58 single-file cluster picker

`ICODA_PLAN.md` says: “Clusters (`icoda_core/clusters.py`): weighted undirected file graph; seeded label propagation
(own implementation, directory as seed) with `networkx` for the graph; split clusters above 40 files; pins and names
from `layout.json`.” It contains no sentence specifically authorising an individual file picker. `EVOLUTION.md`
supplies that exact requirement: “The developer can pin a file to a cluster and rename clusters; the assignments are
stored in `.icoda/layout.json` so that they stay stable between runs and steps.”

The pure `clusters.pin_file` and `clusters.unpin_file` extend the existing frozen `LayoutDecision` path. Invalid
file/target selections return the sorted unchanged decision, matching iteration 56's non-raising convention.
`graph_canvas.PIN_FILE_TO_CLUSTER` is exposed only for canonical file-node contexts and uses a deterministic submenu
of current sorted cluster IDs. `App.dispatch_graph_action` sends it through the existing `_apply_cluster_layout`,
which saves the existing `Layout`, reclusters the already-open model, and calls `App.show` without source analysis.
The only label override remains after `split_large` in `clusters.cluster_files`, so it wins over both seeded labels
and Louvain labels.

All six new tests were red-first:

1. `test_pin_file_moves_only_selected_file_while_other_labels_stay_algorithmic`
2. `test_file_pin_is_persisted_reloaded_and_removable`
3. `test_pin_file_survives_louvain_triggered_run`
4. `test_reapplying_file_pin_is_idempotent_and_preserves_other_layout_entries`
5. `test_pin_file_refuses_unknown_file_or_unknown_target_cluster`
6. `test_file_menu_cluster_picker_is_file_only_and_repaints_chosen_membership`

The focused and complete suites passed:

```text
$ .gui-venv/bin/python -m pytest icoda/tests/test_clusters.py icoda/tests/test_graph_actions.py icoda/tests/test_session.py icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_mind_map.py -q
38 passed in 0.88s
$ .gui-venv/bin/python -m pytest -q
844 passed, 4 skipped in 30.77s
```

The root suite increased by exactly the six named tests from iteration 57's `838 passed, 4 skipped in 30.82s`; no
skip changed. The deterministic simulation assertions were not edited: terminal iterations remain
`[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and `queue_var` containing `empty`. Fresh layouts still have
empty pins, and grouping still defaults to one entity per step.

Static gates ran from `icoda/` and the checked source count remains iteration 57's 55 because no module was added:

```text
$ .gui-venv/bin/python -m ruff check .
All checks passed!
$ .gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 55 source files
```

Xephyr was started before GUI work and remained alive:

```text
218477 Xephyr :99 -screen 1280x800 -ac -noreset
```

Real-Tk evidence in the shared iteration-58 directory:

```text
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-58-final
GUI_ACCEPTANCE_EXIT=0 GENERAL_PNG_COUNT=36
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/simulation_acceptance.py --project icoda/.icoda-test-artifacts/iteration-58-final/simulation-project-final --output icoda/.icoda-test-artifacts/iteration-58-final
SIMULATION_ACCEPTANCE_EXIT=0 SIM_PNG_COUNT=10
phase=implementation cursor=2 terminal=true
```

`file-cluster-picker.png` is the one new general capture above iteration 57's 35. Before capture, the real-widget
harness hard-fails unless the canonical file action resolves, the submenu equals the current sorted cluster IDs, the
selected `file -> cluster_id` pin is persisted, and File View repaints that file inside the chosen cluster. The ten
simulation captures remain exactly `sim-01` through `sim-10`; its deterministic fake gates and assertions are
unchanged.

The phase-publication inventory remains exactly five lines:

```text
icoda/icoda.py:591:        self.panel.set_phase(persistence.ProjectPhase.SPECIFICATION)
icoda/icoda.py:620:        self.panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
icoda/icoda.py:667:        self.panel.set_phase(state.phase)
icoda/icoda_gui/step_panel.py:154:    def set_phase(self, phase: persistence.ProjectPhase | str) -> None:
icoda/icoda_gui/step_controller.py:297:            self.window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
```

Final project verification:

```text
$ DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 89.83%
337 passed, 3 skipped in 32.16s
=== pytest: PASS (32.3s) ===
=== analysis: PASS (0.1s) ===
=== gui: PASS (11.5s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-050752-388219/summary.txt
VERIFY_EXIT=0
```

Coverage moved up 0.03 percentage points from iteration 57's 89.80% and remains above 85%. GAP_ANALYSIS row 8 is
now DONE because the file-node picker is implemented end to end. Windows and macOS rows remain unqualified and
unchanged.

## 2026-09-11 — iteration 59 uncertain C++ virtual-call marking

Only `EVOLUTION.md` carries the marking requirement: “virtual calls are attributed to the static target and marked
as dynamic”. The M1.6 paragraph in `ICODA_PLAN.md` names call-expression extraction but contains no matching
dynamic/uncertain-marking sentence. `model.Edge.uncertain: bool = False` is the one additive relation field;
`DerivedModel.from_json` owns the old-model default, and `analysis.UnitResult.from_json` also defaults old unit-cache
entries. No relation/entity kind or second edge list was added.

The frozen plain-input `analysis.CallDispatch` and pure `analysis.is_uncertain_call` are the single dispatch decision
site. A virtual member called through a pointer/reference is uncertain unless its member/class is final or the call
is fully qualified; concrete-object virtual calls, non-virtual calls, final calls, fully qualified calls, and free
functions are certain. `Extractor._calls` is the thin libclang caller. Python emits `uncertain=False` because its AST
front end emits an edge only after its existing exact static target resolution and omits unresolved calls.

All seven new tests were red-first and then passed:

1. `test_virtual_member_through_base_pointer_is_uncertain`
2. `test_virtual_override_on_concrete_object_is_certain`
3. `test_non_virtual_member_call_is_certain`
4. `test_free_function_call_is_certain`
5. `test_real_parse_marks_only_base_pointer_virtual_call_uncertain`
6. `test_call_uncertainty_round_trip_and_legacy_default`
7. `test_call_view_renders_uncertain_call_differently_from_certain_call`

Libclang was available:

```text
LIBCLANG_CANDIDATES=2
LIBCLANG_FIRST=/usr/lib/llvm-18/lib/libclang.so.1
```

Focused, full, and protected regression runs:

```text
$ .gui-venv/bin/python -m pytest <the seven tests above> -q
7 passed in 0.21s
$ .gui-venv/bin/python -m pytest -q
851 passed, 4 skipped in 30.96s
$ .gui-venv/bin/python -m pytest icoda/tests/test_clusters.py icoda/tests/test_graph_actions.py icoda/tests/test_python_analysis.py icoda/tests/test_session.py icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_mind_map.py -q
44 passed in 0.87s
```

The root suite grew from iteration 58's `844 passed, 4 skipped in 30.77s` by exactly those seven tests; the skip
count did not change. The Python exact-set CALLS assertions pass unchanged. The simulation assertion source was not
edited: terminal iterations remain `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and `queue_var` contains
`empty`; fresh `Layout.pins` remains empty and implementation grouping remains one entity per step.

Static gates ran from `icoda/`; no module was added, so the confirmed 55-file scope remains 55:

```text
$ .gui-venv/bin/python -m ruff check .
All checks passed!
$ .gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 55 source files
```

Xephyr was started before all GUI work and remained alive:

```text
231026 Xephyr :99 -screen 1280x800 -ac -noreset
```

Real-Tk evidence in the shared iteration-59 directory:

```text
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-59-final
GUI_ACCEPTANCE_EXIT=0 GENERAL_PNG_COUNT=37
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/simulation_acceptance.py --project icoda/.icoda-test-artifacts/iteration-59-final/simulation-project-final --output icoda/.icoda-test-artifacts/iteration-59-final
SIMULATION_ACCEPTANCE_EXIT=0 SIM_PNG_COUNT=10
phase=implementation cursor=2 terminal=true
```

`uncertain-dynamic-call.png` is the one new general capture above iteration 58's 36. It shows one solid certain arrow
and one dashed uncertain arrow labelled `?`, plus the shared appearance legend; the harness hard-fails unless those
two styles and the legend all exist. The ten simulation captures remain `sim-01` through `sim-10`.

The phase-publication inventory remains exactly five lines:

```text
icoda/icoda.py:591:        self.panel.set_phase(persistence.ProjectPhase.SPECIFICATION)
icoda/icoda.py:620:        self.panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
icoda/icoda.py:667:        self.panel.set_phase(state.phase)
icoda/icoda_gui/step_panel.py:154:    def set_phase(self, phase: persistence.ProjectPhase | str) -> None:
icoda/icoda_gui/step_controller.py:297:            self.window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
```

Final project verification:

```text
$ DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 89.81%
344 passed, 3 skipped in 32.49s
=== pytest: PASS (32.7s) ===
=== analysis: PASS (0.1s) ===
=== gui: PASS (11.8s) ===
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-052618-223450/summary.txt
VERIFY_EXIT_STATUS=0
```

Coverage moved down 0.02 percentage points from iteration 58's 89.83% and remains above 85%. GAP_ANALYSIS's C++
analysis row is now `PARTIAL — DYNAMIC-CALL HALF DONE`; header/source logical pairing remains its open M1.6 half.
Windows and macOS rows remain unqualified and unchanged.

## 2026-09-11 — iteration 60 C++ header/source logical pairing

`analysis.pair_declarations` is the one pure pairing decision over already extracted Python `Entity` values. Equal
USRs merge regardless of file; a definition deterministically owns the body hash and source/line facts, while the
additive `Entity.declaration_file: str = ""` retains the header. `model._entity_from` and
`analysis._entity_from_json` own the two legacy defaults. The Python AST front end explicitly supplies `""` because
Python has no C++ declaration/header split. `CACHE_VERSION` remains `dynamic-calls-v1`: old unit entries load through
the explicit default and are paired during assembly, so invalidating them is unnecessary.

Focused feature tests:

```text
$ .gui-venv/bin/python -m pytest -q <the eight iteration-60 tests>
8 passed in 0.16s
```

The four `test_pair_declarations_*` tests, the real parse
`test_real_parse_pairs_header_declaration_and_source_definition`, the model
`test_entity_declaration_file_round_trip_and_legacy_default`, and the GUI
`test_class_view_renders_paired_entity_once_with_both_file_names` were red-first. The unit-cache default
`test_unit_result_declaration_file_legacy_default` was green-first because it was added after the implementation.

Full and protected regressions:

```text
$ .gui-venv/bin/python -m pytest -q
859 passed, 4 skipped in 30.91s
$ .gui-venv/bin/python -m pytest icoda/tests/test_analysis.py icoda/tests/test_persistence.py icoda/tests/test_clusters.py icoda/tests/test_graph_actions.py icoda/tests/test_python_analysis.py icoda/tests/test_session.py icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation icoda/tests/test_step_gui.py -q
113 passed in 16.92s
```

The increase from iteration 59's 851 passes is exactly the eight tests named above; all four skips are unchanged.
Iteration 59's seven call-uncertainty tests and Python's exact-set CALLS assertions pass unchanged. No simulation
assertion changed: terminal iterations remain `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and `queue_var`
contains `empty`. Fresh `Layout.pins` remains empty and implementation grouping remains `single_entity`.

Static checks from `icoda/`:

```text
$ .gui-venv/bin/python -m ruff check .
All checks passed!
$ .gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 55 source files
```

No module was added, so iteration 59's confirmed 55-file mypy scope remains 55. The pure core has no Tk import.
The foreground display used for all successful GUI runs was:

```text
246281 Xephyr :99 -screen 1280x800 -ac -noreset
```

Real-Tk evidence:

```text
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/gui_acceptance.py --project icoda/tests/sample_project --output icoda/.icoda-test-artifacts/iteration-60-final
GUI_ACCEPTANCE_EXIT=0 GENERAL_PNG_COUNT=37
$ DISPLAY=:99 ICODA_TK_STUB=0 .gui-venv/bin/python icoda/tests/simulation_acceptance.py --project icoda/.icoda-test-artifacts/iteration-60-final/simulation-project-final --output icoda/.icoda-test-artifacts/iteration-60-final
SIMULATION_ACCEPTANCE_EXIT=0 SIM_PNG_COUNT=10
phase=implementation cursor=2 terminal=true
```

The general count stays at iteration 59's 37 because pairing uses the existing hover detail instead of adding an
acceptance scene; the focused GUI test hard-checks one rendered member row and both file names. The ten simulation
captures remain `sim-01` through `sim-10`. An initial display connection attempt and an initial simulation invocation
without its required `--project` argument produced no images; both were corrected before the successful commands
above. A first `verify.bash` run also observed the GUI acceptance's intentionally persisted sample layout; that
generated layout was preserved under `/tmp`, removed from the sample, and the unchanged session assertion plus final
verification then passed.

The phase-publication inventory remains exactly five lines:

```text
icoda/icoda.py:591:        self.panel.set_phase(persistence.ProjectPhase.SPECIFICATION)
icoda/icoda.py:620:        self.panel.set_phase(persistence.ProjectPhase.ARCHITECTURE)
icoda/icoda.py:667:        self.panel.set_phase(state.phase)
icoda/icoda_gui/step_panel.py:154:    def set_phase(self, phase: persistence.ProjectPhase | str) -> None:
icoda/icoda_gui/step_controller.py:297:            self.window.panel.set_phase(persistence.ProjectPhase.IMPLEMENTATION)
```

Final project verification:

```text
$ DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 89.84%
352 passed, 3 skipped in 32.54s
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-054609-618346/summary.txt
VERIFY_EXIT_STATUS=0
```

Coverage moved up 0.03 percentage points from iteration 59's quoted 89.81% and remains above 85%. GAP_ANALYSIS now
marks M1.6 `DONE — M1.6 BOTH HALVES`; its sole explicitly numbered list is `Next slices`, now with eight entries.

## 2026-09-11 — iteration 61 class-view test-structure repair

Iteration 60's statement that no existing assertion was edited was incorrect. Its new
`test_class_view_renders_paired_entity_once_with_both_file_names` definition was inserted before the tail of
`test_class_view_canvas_renders_edges_member_statuses_and_empty_model`, absorbing that existing test's zoom and
empty-model assertions. The new definition was moved after the complete pre-existing test without changing either
test's assertions; the pairing test now ends with its entity-count and two hover-file assertions. The iteration-60
insertions in `test_analysis.py` and `test_persistence.py` were audited and were already between complete functions.

Focused and full regressions from the worktree root:

```text
$ .gui-venv/bin/python -m pytest icoda/tests/test_class_view.py -q
4 passed in 0.08s
$ .gui-venv/bin/python -m pytest icoda/tests/test_analysis.py icoda/tests/test_persistence.py icoda/tests/test_step_gui.py icoda/tests/test_session.py icoda/tests/test_python_analysis.py icoda/tests/test_simulation.py::test_complete_developer_controlled_simulation -q
87 passed in 16.90s
$ .gui-venv/bin/python -m pytest -q
859 passed, 4 skipped in 31.04s
```

The pass and skip counts are unchanged from iteration 60. Its eight feature tests, including the structurally
repaired class-view test, and iteration 59's seven call-uncertainty tests pass unchanged. No simulation assertion was
edited: terminal iterations remain `[0, 0, 1, 1, 2, 2, 2, 3, 3]`, cursor 2, gate `none`, and `queue_var` contains
`empty`. Fresh `Layout.pins` remains empty and implementation grouping remains `single_entity`.

Static checks from `icoda/`:

```text
$ .gui-venv/bin/python -m ruff check .
All checks passed!
$ .gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 55 source files
```

The persistent foreground display was started before verification and confirmed alive:

```text
253802 Xephyr :99 -screen 1280x800 -ac -noreset
```

Final project verification:

```text
$ DISPLAY=:99 bash icoda/verify.bash
Required test coverage of 85% reached. Total coverage: 89.84%
352 passed, 3 skipped in 32.59s
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-055939-983168/summary.txt
VERIFY_EXIT_STATUS=0
```

Coverage is unchanged from iteration 60's 89.84% and remains above 85%. Because no renderer changed, no separate
37-PNG `gui_acceptance.py` or 10-PNG `simulation_acceptance.py` command was required; the normal GUI acceptance
inside `verify.bash` passed. A generated sample `.icoda` directory containing `state.json` and a pinned
`layout.json` was found after the inherited iteration-60 troubleshooting and moved to the desktop trash; the final
sample listing contains no `.icoda`, so generated cluster pins are not retained.

Start and end SHA-256 checks were identical for `analysis.py`, `model.py`, `views.py`, `python_analysis.py`, the GUI
`class_view.py`, and the GUI `call_view.py`; this iteration changed only `tests/test_class_view.py` and this log.
The `set_phase` inventory remains exactly five lines at `icoda.py:591`, `icoda.py:620`, `icoda.py:667`,
`step_panel.py:154`, and `step_controller.py:297`. `GAP_ANALYSIS.md` was not changed because no gap status moved.

## 2026-09-11 — iteration 62 developer-facing libclang chooser

The frozen `toolchain.Selection` result and pure `toolchain.select_candidate` rule now make the persisted preference,
automatic first-candidate fallback, stale-preference fallback, and no-candidate result explicit without duplicating
`toolchain.candidates`. `session.choose_libclang` consumes that ordering. The Project menu opens a deterministic
radio-button chooser rather than a free-text path dialog; it marks the active detected candidate, shows the currently
loaded library separately, and stores `UserConfig.preferred_libclang` using `LEGACY_LIBCLANG_PREFERENCE` for old
payloads.

Red-first evidence was four `AttributeError: module 'icoda_core.toolchain' has no attribute 'select_candidate'`
failures. The implemented focused set passed `11 passed in 0.23s`; the complete worktree suite passed:

```text
865 passed, 4 skipped in 38.76s
```

This is the iteration-61 baseline 859 plus six new tests; the four skips are unchanged. Static checks from `icoda/`
reported `All checks passed!` and `Success: no issues found in 55 source files`.

The fresh persistent foreground display was confirmed as:

```text
260987 Xephyr :99 -screen 1280x800 -ac -noreset
```

Real verification completed successfully:

```text
Required test coverage of 85% reached. Total coverage: 89.88%
358 passed, 3 skipped in 32.25s
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-061452-086238/summary.txt
VERIFY_EXIT_STATUS=0
```

Coverage rose 0.04 percentage points from iteration 61's 89.84%. Standalone real-Tk GUI acceptance exited 0 and
produced 38 general PNGs, including `libclang-chooser.png`. Standalone simulation acceptance was invoked with
`--project`, exited 0, produced ten `sim-*.png` files plus `simulation-state.json`, and reported
`phase=implementation cursor=2 terminal=true`. Its deterministic gates and assertions were not edited.

The generated sample `.icoda` directory was moved intact to a temporary recovery directory after acceptance. The
sample ends with only its pre-existing tracked `build.sh` modification. GAP_ANALYSIS marks M1.4 DONE and appends the
ninth Next-slices item; no iteration-53 remaining-work plan item is still open, while the three named non-blocking
performance defects and unqualified Windows/macOS hosts remain honestly recorded outside that feature list.

## 2026-09-11 — iteration 63 re-verification

The current `GAP_ANALYSIS.md`, this log, `RELEASE_MATRIX.md`, and the repository `CLAUDE.md` were re-read before
verification and refreshed before this entry. The finishing-criterion rows for always-visible project state,
developer control over every coding step, and the final end-to-end development simulation remain **DONE**. No row
required by the job goal is open, so this iteration changed no source or test file and did not change any gap status.

The exact worktree-root full-suite result was:

```text
$ python -m pytest -q
865 passed, 4 skipped in 32.12s
```

The exact static-gate results from `icoda/` were:

```text
$ ../.gui-venv/bin/python -m ruff check .
All checks passed!
$ ../.gui-venv/bin/python -m mypy icoda.py icoda_core icoda_gui tests/verify.py tests/gui_acceptance.py tests/real_provider_acceptance.py
Success: no issues found in 55 source files
```

The project verifier ran on real Tk through `Xephyr :99` and exited 0:

```text
$ DISPLAY=:99 ICODA_VERIFY_PYTHON=../.gui-venv/bin/python bash verify.bash
Required test coverage of 85% reached. Total coverage: 89.88%
358 passed, 3 skipped in 32.99s
PASS: /home/hlavacs/Dokumente/GitHub/ai-runs/J20260909-213822-312934/icoda/.icoda-test-artifacts/20260911-065725-346105/summary.txt
```

Standalone real-Tk acceptance also exited 0. `gui_acceptance.py` wrote exactly **38 general PNGs** to
`icoda/.icoda-test-artifacts/iteration-63-reverification`. `simulation_acceptance.py` wrote exactly **10** captures,
named `sim-01-specification-code-refused.png` through `sim-10-terminal-overview.png`, plus
`simulation-state.json`. The state was read back as `phase=implementation cursor=2 terminal=true`; its screenshot
mapping contains those same ten names. Visual inspection of `sim-06-normalize-approach.png` confirmed the current
target and the developer's Approve approach, Reject, and Adapt controls; inspection of
`sim-10-terminal-overview.png` confirmed the empty implementation queue and the 4/4 covered callable overview.

Every capability-matrix row in `GAP_ANALYSIS.md` whose status is not DONE is listed explicitly here:

- `M4.2 specification coverage: @satisfies index, uncovered requirements, untagged entities, and highlighting in all views` — **PARTIAL (uncovered-requirement projection DONE)**; all-diagram tag colouring remains a documented non-goal for this run.
- `Enforced code-profile/rule requirements for generated C++` — **PARTIAL**; hard enforcement gates remain a documented non-goal for this run.
- `Gap 7C2 defect — icoda_core/python_analysis.py:parse_project` — **OPEN BUT NOT BLOCKING**.
- `Gap 7C2 defect — icoda_core/views.py:layout_file_view` — **OPEN BUT NOT BLOCKING**.
- `Gap 7C2 defect — icoda_core/expansion.py:derive` — **OPEN BUT NOT BLOCKING**.

The composite gap 7C2 measurement row remains DONE with those three defects explicitly open and non-blocking;
large-project summed overview latency remains the retained 4.389153s result rather than a fresh performance
measurement. `RELEASE_MATRIX.md` still records Linux as the only qualified platform and Windows/macOS as
**UNQUALIFIED / UNMEASURED**. The branch and commit remained
`ai/J20260909-213822-312934` at `170a5a72f87e39859d1ae9ce8b583a120b84947b`; no commit or merge was made. The
worktree was already dirty with the prior ICODA implementation at the start of this iteration; this iteration added
only this verification-log entry, while its generated verification and screenshot evidence is ignored artifact
data.

## 2026-09-20 — Recovery before error reporting

Added bounded provider recovery, corrective proposals that retain the normal build/test/phase gates, and a
Troubleshooting tab with conversation history, provider switching, cancellation, retry, diagnostic evidence,
and an interactive CLI launcher. Tests cover failed/unchanged updates, repeated failures, cancellation,
worktree preservation, delayed error display, stale callbacks, terminal quoting, and the completion queue
surviving a UI callback exception. Unknown UI failures are investigated; a successful redraw is not treated
as proof that a failed save or other operation succeeded.

Verification on macOS arm64 / Python 3.14.6:

- The full verifier at `.icoda-test-artifacts/20260920-174713-662246` passed lint, mypy, compilation, provider
  qualification, authenticated Codex 0.155.1 / `gpt-5.6-sol` acceptance, the C++ sample build/test, analysis,
  546 pytest tests, and the new recovery GUI check. Whole-tree coverage was 87.88%. Its original GUI stage
  exposed the screenshot helper's incorrect handling of floating macOS windows; that run's failed summary
  is retained unchanged.
- After correcting capture selection, standalone `tests/gui_acceptance.py` exited 0 and wrote its 38
  screenshots plus `gui-state.json` to `.icoda-test-artifacts/recovery-final-overviews`. The native-menu
  portion was slow but completed. The libclang dialog and the Troubleshooting window were visually inspected.
- `tests/recovery_gui_acceptance.py` exercised recovery, two scripted conversational turns, candidate context,
  visible controls, and the cleared busy state in real Tk. Its result and screenshot are in the full verifier's
  `recovery-gui` directory. This GUI scenario uses a scripted provider; the separate authenticated provider
  check above uses the real CLI.
- Final regression rerun: **546 passed in 72.29 seconds**. Core/GUI package coverage was 91.75%; that narrower
  coverage invocation does not measure the dynamically imported `icoda.py` entry point. The whole-tree number
  above remains the applicable complete coverage result. After the final unknown-callback correction,
  `tests/test_troubleshooting.py` and `tests/test_app.py` also passed together: **28 passed**.
- Final Ruff, mypy, and `git diff --check` passed. The previously missing local wheel build backend was
  installed and added to the development dependencies; wheel packaging tests pass.

The user had already updated the installed Codex CLI. Verification did not update it again. No recovery test
changed the user's `icoda-tests/Worktrees` project. Fresh-install platform qualification remains separate from
this feature verification.

## 2026-09-20 — Built-in source editor

Added an upper-right Source Editor tab alongside Entities. File, class, function, hierarchy, and Mind Map
selection open the corresponding source location. Editing includes literal case-sensitive/insensitive find,
replace/replace all, undo/redo, save/reload, and keyboard shortcuts. Saves preserve UTF-8 BOM/newline conventions
and file modes, use atomic replacement, and retain the buffer on failures or external-file conflicts. Unsaved
buffers are guarded on navigation, project changes, close, and workflow actions. Candidate edits target the
proposal worktree and invalidate its build/test/signature approval gates; main-project saves refresh analysis.

Complete verification passed on macOS arm64 / Python 3.14.6, with evidence in
`.icoda-test-artifacts/20260920-181259-410392`:

- Ruff, mypy (64 files), compileall, and diff checks passed.
- All **566 tests passed**, with **87.90% whole-tree coverage** against the 85% threshold.
- Provider qualification, authenticated real-provider acceptance, C++ sample build/test, and source analysis passed.
- The full GUI suite, recovery GUI suite, and new source-editor GUI suite passed. The editor scenario exercised
  real mouse events on C++ file/class/function nodes, Unicode search, native undo/redo for replacement operations,
  dirty-buffer navigation, disk save/reload, refresh scheduling, and unclipped controls.
- The source-editor screenshot and updated handbook pages were visually inspected. The PDF includes the new
  C++ editor screenshot with red rectangles around the tab, editing/search controls, and selected source line.

Source editing is limited to UTF-8 text files up to 2 MiB inside the selected project or candidate worktree.
Fresh-install Windows/Linux qualification is not implied by this macOS feature verification.

## 2026-09-20 — File boxes visible beside the hierarchy

Reproduced the reported Worktrees problem from a copy of the project's cached model and sources. Analysis
contained all four files and seven entities. At 1200x760, every file marker lay underneath the fixed hierarchy
panel: Fit was measuring the fixed status legend together with the graph and reserved no hierarchy space.

File View now fits only tagged graph content beside the hierarchy and below the status legend. Files are
labeled rectangles; both their labels and borders open the editor. Arrows meet rectangle edges, external nodes
stay near the actual graph, and Fit stays bounded for a single-file project. When fitted boxes collide, the core
provides a compact grid while preserving file identities, relations, and cluster metadata/actions.

Verification:

- The complete gate in `.icoda-test-artifacts/20260920-185742-033256` passed all stages: **567 tests**, **87.63%**
  whole-tree coverage, C++ build/test, provider acceptance, analysis, and three GUI suites. Its screenshots
  exposed overlapping labels in the larger sample, prompting the subsequent compact-grid adjustment.
- After that adjustment, **59 focused tests** passed across application behavior, core geometry, appearance,
  filtering, expansion, and editing. Ruff, mypy (61 files), and `git diff --check` passed.
- Real-Tk captures of the four-file Worktrees copy and 13-file C++ sample were inspected. Every file box was
  visible; the compact sample's rectangles did not overlap. The editor acceptance scenario passed in
  `.icoda-test-artifacts/file-boxes/acceptance-complete`, including repeated Fit, a single-file zoom bound,
  navigation, Unicode search/replace, undo/redo, and save/reload.
- The final broader GUI run verified box visibility, cluster pin/rename/menu behavior, the file-to-cluster picker,
  file zoom/pan, and call zoom/pan. It then stopped because macOS returned an almost blank desktop screenshot for
  the native node menu (`32 colours`, variance `2.3`). This run is **not** claimed as a complete GUI pass; its
  screenshots are retained in `.icoda-test-artifacts/file-boxes/verified-overviews`. The window-capture helper
  now prefers currently visible owned windows over stale offscreen windows with matching titles.

The user's `icoda-tests/Worktrees` repository remained clean. All reproduction and editing checks used copies
or isolated fixtures.

## 2026-09-20 — Prompt tab available before failures

Renamed the Troubleshooting tab to Prompt. Its Send and Open CLI controls previously required an existing
diagnosis, leaving normal project questions disabled. Project opening now initializes conversation context;
typing, provider selection, and operation completion refresh the controls. Retry step and Details still require
failure context. General questions retain conversation history without inventing a diagnosis, and Open CLI
receives the history and unsent draft. Project switches clear both. The Send shortcut consumes its key event
so it cannot also trigger the global Propose action.

Verification evidence is retained in `.icoda-test-artifacts/prompt-tab`:

- The new pre-failure conversation regression failed before the fix and passed afterward.
- The complete pytest suite passed: **572 tests in 69.42 seconds**. The first run exposed persistent cluster pins
  from an earlier GUI scenario in the shared sample; the default-clustering test now supplies an empty layout
  without changing the saved sample settings. The final recovery/Prompt subset also passed **35 tests**.
- Native Tk acceptance passed in `final-gui`, using four scripted provider turns: ordinary conversation before
  any error, follow-up history, enabled/disabled buttons, busy-state transitions, keyboard submission without a
  workflow action, project switching, and unresolved recovery. No external provider call was needed for this UI
  regression; actual terminal invocation is covered with an intercepted launcher in the unit tests.
- Ruff, mypy (60 files), and `git diff --check` passed.
- The handbook PDF was regenerated (96 pages, 37 images). Updated Prompt and recovery pages were rendered with
  Poppler and visually inspected; the existing screenshot highlight rectangles remain intact.

## 2026-09-20 — Visible project reload and compact review panel

Added Reload project beside the status message. It uses the existing asynchronous project analysis, stays
disabled while work is running or no project is open, refreshes externally changed clean editor buffers at
their current line, and preserves unsaved buffers and unchanged undo history. The menu and shortcut use the
same guarded reload path.

Review details now start collapsed with no proposal. Show details / Hide details retain tab contents and
Summary edits; new proposals, approaches, historical selections, and failures reveal the review area.
Released height goes to the diagrams and source editor, while the divider remains adjustable.

Verification evidence is retained in `.icoda-test-artifacts/reload-compact`:

- **575 pytest tests passed in 73.39 seconds**; Ruff, mypy (60 files), and `git diff --check` passed.
- An isolated native Tk scenario measured the panel at **164 px collapsed / 396 px expanded** in a 1200x760
  window, returning **232 px** to the upper panes. It checked toggling both before and after project opening,
  preserved Summary edits, visible controls, and automatic expansion for a diagnostic.
- The scenario edited a C++ source outside ICODA, reloaded it through the application handler, and confirmed
  that analysis discovered the new function and the clean editor refreshed at its original line. A second
  external edit confirmed that a dirty editor buffer remained intact. Reload availability followed analysis
  busy state. No user project was changed.
- Desktop computer-use permissions were unavailable; native widget geometry and application behavior were
  checked programmatically. No manual screenshot-based GUI pass is claimed for this change.
- The PDF was regenerated (96 pages, 37 images); its updated reload and review-panel instructions were rendered
  with Poppler and visually inspected.

## 2026-09-20 — Remove the remaining review-header whitespace

Moved Show details / Hide details onto the existing action row. The idle panel no longer reserves separate
title/status rows or inactive implementation controls. Real result titles and build/test/signature status
share one line. Collapsed height follows phase, progress text, and window-size changes; repeated resize
requests are coalesced, and the expanded review divider remains adjustable.

Verification:

- **96 focused tests passed** across application behavior, source editing, step controls, and Prompt/recovery.
  Ruff, mypy (61 files), and `git diff --check` passed.
- Native widget checks in `.icoda-test-artifacts/compact-header` measured **88 px idle / 320 px expanded** at
  1200x760, compared with the previous **164 / 396 px**. Both states reclaim a further **76 px**.
- Checked implementation controls and phase buttons for clipping, a one-line result/status row, returning
  from multi-line progress messages, resizing the window, retained Summary edits, and automatic result
  expansion. The isolated reload scenario still discovered an external C++ function and preserved dirty edits.
- The handbook PDF was regenerated (96 pages, 37 images); its revised panel instructions were rendered with
  Poppler and visually inspected. Desktop screenshots remain unavailable without computer-use permission;
  the application checks use native widget geometry rather than a manual visual pass.

## 2026-09-20 — Reread the saved specification

Added Reread specification beside Reload project and in the specification editor. The action validates
`.icoda/specification.json`, updates the editor and requirement coverage, and asks before replacing unsaved
edits (including unfinished new record forms). It preserves source buffers and does not write project files
or trigger source analysis. Editors are reused per project; callbacks cannot save into another project.
Missing, malformed, or invalid files get a recovery read before details are presented in Prompt.

Verification:

- **584 tests passed in 71.86 seconds**. After refining editor reuse across project switches, **51 focused
  application, specification-editor, and recovery tests passed**. Ruff, mypy on all 59 production source files,
  and `git diff --check` passed. An optional mypy run including `test_app.py` found two existing test typing
  issues (the menu command typed as object, and a lambda using list.append as a value); these are unchanged.
- Native Tk button invocation and geometry checks in `.icoda-test-artifacts/spec-reread` confirmed both buttons
  are fully visible (164 px each), refresh external changes, honor discard/cancel, and disable while busy.
  The checks use an isolated project and do not require desktop input or screenshot permissions.
- The handbook PDF was regenerated (96 pages, 37 images). Pages 5, 17, and 18 were rendered with Poppler and
  visually inspected for the new reread instructions and surrounding layout.

## 2026-09-20 — Default example source directory in new specifications

New C++ and Python specifications include a Code Profile style rule placing example and demo sources in the
project-root `examples/` directory, with `examples/<name>/` for multi-file examples. The existing compact
specification serialization carries the rule into architecture, implementation, and approach prompts.

- **58 specification, prompt, editor, and application tests passed**. Ruff, mypy for the changed production
  module, and `git diff --check` passed.
- A direct prompt-assembly check confirmed the rule appears in all three prompt types for both languages.
- The handbook explains the new default and how existing specifications can add it in Style notes. Its PDF
  was regenerated (96 pages, 37 images); page 15 was rendered and visually inspected.

## 2026-09-20 — Select, build, and run the intended example

Added the Example / executable selector above the diagrams. Choices identify the main source file and, once
refreshed, the CMake target and configuration. Selection opens the source, selects the Call View root, controls
From main, and persists per project. The row provides Refresh examples, Build, Run, Stop, and Output; the
Program output tab captures commands and completed output. Build/Run use CMake's file API artifact paths and
build only the selected target and its dependencies. Ambiguous targets require an explicit selection.

C++ main identifiers now include their source path, preventing separate entry points and their outgoing calls
from merging. The unit cache version is advanced; legacy main status and implementation-queue references are
resolved to the original source, with an old approved approach cleared when its identity changes.

Verification:

- The complete suite ran **593 tests: 592 passed**, with only the module-inventory documentation assertion
  failing because this feature added modules. Updated GAP_ANALYSIS and RELEASE_MATRIX counts; **all 10
  verification tests then passed**, including that assertion. Ruff, mypy (61 production files), and
  `git diff --check` passed.
- Real CMake fixtures compiled and ran two separate C++ main functions, verified independent call graphs,
  respected a renamed executable in a custom output directory, avoided an unrelated intentionally broken
  target, required selection when targets share a main, and prevented launch after cancellation.
- Selector tests cover source navigation, per-project persistence, From main, removed entries, cancelled
  unsaved edits, busy guards, ambiguous selection, and recovery of the main project on build failure.
- Native Tk checks in `.icoda-test-artifacts/executable-selector` used the actual combobox event and Run button
  to select and execute the second example. Output was `second`; the first executable was not built. The
  selection and graph root survived project reload. All five row buttons fit in a 1200x760 window.
- Native checks use widget geometry and application calls; no desktop screenshot or manual visual pass is
  claimed. The updated 96-page handbook PDF was rendered and pages 18–19 visually inspected.

Build/run currently targets configured CMake projects and captures non-interactive output without run
arguments. Project > Build and proposal gates retain their full-project behavior.

## 2026-09-20 — Create example sources in the examples directory

The C++ starter now creates `examples/basic/main.cpp` and points its executable target there. The reusable
module library stays in `src/`. Default Code Profiles explicitly preserve this separation, and the handbook,
C++ tutorial reference project, and tutorial capture tool use the new entry-point path.

Repaired the existing `icoda-tests/Worktrees` project: moved its example entry point and integration module to
`examples/basic/`, kept the reusable `work_tree` module in `src/work_tree/`, and separated their CMake targets.
Its specification now records the directory policy. The library remains in the architecture phase; no worker
implementation or job execution is claimed. The existing proposal worktree and step history were preserved.

Verification:

- **72 focused tests passed** across generation, application behavior, specification, prompts, specification
  editing, and repository verification. Ruff, mypy for both changed production modules, and diff checks passed.
- The repaired Worktrees project built and passed both CTests. ICODA analysis found all four source files without
  errors. Its executable selector resolved `Worktrees [Debug]` to `examples/basic/main.cpp` and ran it with exit 0.
- The tutorial reference was copied to an isolated directory, compiled, and passed both CTests. Running its
  example printed exactly `scores: 0 42 100` and exited successfully.
- The regenerated handbook contains 96 pages and 37 images. Pages 4, 15, 68, 81, and 90 were rendered with
  Poppler and visually inspected for the changed directory instructions and source listing.

## 2026-09-20 — Allow Prompt to edit project files

Prompt **Send** now uses Codex `workspace-write` or Claude `acceptEdits`, with instructions to read the saved
specification and apply requested file changes. Proposal generation and automatic investigation keep their
read-only defaults. Editing requests have a 30-minute limit and are never automatically replayed after failure
or cancellation, since partial edits may already exist. Failure evidence is available through Details.

Filesystem snapshots detect edits, creations, deletions, and renames, including in new projects without Git or
nested inside an ignored parent directory. Changes refresh project analysis or invalidate candidate build/test
results. Clean source buffers refresh or close after deletion; unsaved buffers are preserved. Conversation
context survives same-project reloads and failures, retaining the existing 16-message/20,000-character limit.

Verification:

- **611 tests passed** in the complete suite, including **86 focused tests** covering both provider permission modes, unchanged read-only defaults, partial
  failures without retries, renames, candidate checks, dirty buffers, stale callbacks, and conversation history.
  Ruff, mypy across 61 production files, and `git diff --check` passed.
- An actual Codex request using the application's default model renamed `examples/basic/app.cppm` to `app.cpp`
  in an isolated fixture by reading its specification, preserved the source bytes, and updated README references.
  Evidence: `.icoda-test-artifacts/writable-prompt/codex-live.json`.
- The actual Claude request was blocked before editing: installed Claude Code 2.1.191 reported that the configured
  `claude-fable-5-1` requires 2.1.251 or newer. No installation was changed; Claude invocation wiring is covered by
  tests, but a successful live Claude edit is not claimed.
- The native Tk acceptance check passed five scripted provider turns, performed a real file rename through Send,
  observed the renamed file in refreshed analysis, retained conversation history, and checked project switching
  and recovery controls. Evidence: `.icoda-test-artifacts/writable-prompt/gui-final2/recovery-gui.json` and screenshots.
- Updated the handbook and troubleshooting guide. Regenerated the 97-page handbook (37 images), rendered pages
  20, 43, and 94 with Poppler, and visually checked the changed instructions and the native Prompt screenshot.

## 2026-09-20 — Display one executable across all code views

The Example / executable selector now scopes File, Class, Call, Mind Map, Coverage, and Issues together.
Projects with multiple entry points require a choice before populating the views. A saved choice is restored
when unambiguous; a sole executable is selected automatically. Library-only projects retain their library view.
Switching keeps the active diagram tab, updates source navigation, and preserves unsaved-buffer protection.

CMake target sources and library dependency sources establish the display scope, including uncalled helper
files. Other executables used as build-order prerequisites are excluded. Without target metadata, the scope
follows outgoing source dependencies and declaration/definition pairs from the chosen entry point. The complete
analysis model remains available for workflow checks and recorded-test evidence; coverage displays only the
selected executable's callable rows. Proposal Call View previews use the same scope and open candidate sources.

Verification:

- **616 tests passed in 89.37 seconds**. Ruff, mypy across 61 production files, and `git diff --check` passed.
- Real CMake fixtures verify library membership, uncalled helpers, exclusion of other executable targets,
  ambiguous target/configuration choices, and independent build/run behavior.
- GUI regression tests verify every code view, mandatory choice, active-tab preservation, reload persistence,
  hidden-node navigation, proposal previews, and candidate source editing. Python coverage and targeted test
  actions retain recorded evidence even when the test source is outside the selected executable's display.
- `tests/executable_scope_gui_acceptance.py` configured, built, and analysed a native C++ fixture with `basic`,
  `smoke_test`, and a shared library. Real combobox events showed only basic's four files or smoke's three files,
  preserved the active tab, and restored smoke after reload. Evidence and four screenshots are retained in
  `.icoda-test-artifacts/executable-scope-final/`; basic File View and smoke Class View were visually inspected.
- Updated the handbook and module-inventory evidence for the new native acceptance program. Regenerated the
  97-page PDF (37 images), rendered and visually checked the revised selection instructions on page 18.

## 2026-09-20 — Select libraries without main

The Executable / library selector includes CMake static, shared, module, object, and interface library targets.
Libraries are identified by target and configuration independently of a main function or executable artifact.
All code views use the selected library's sources and library dependencies; executable callers and unrelated
libraries remain outside the scope. Multiple targets require a choice, and library choices survive reloads.

Call View displays the library's analysed functions and methods together, including unused API functions and
internal functions. A function can become the focused root; Library functions restores the complete overview.
The same behavior applies to candidate previews. Build operates on the selected library; Run is disabled in
the UI and rejected by the core operation before attempting configuration or launch.

Verification:

- **625 tests passed in 93.64 seconds**. Ruff, mypy across 61 production files, and `git diff --check` passed.
- Real CMake fixtures configured and built each of the five library kinds, including interface targets without
  artifacts. They verify unused functions, library-only selection, transitive dependencies, candidate paths,
  exclusion of unrelated sources, and no fallback to an arbitrary library after a saved target disappears.
- GUI regression checks cover all scoped views, several function roots, empty callable sets, executable/library
  switching, saved selection, candidate API additions, and Build/Run state.
- Native Tk acceptance passed using real combobox events with basic, smoke_test, and shared. The selected
  library displayed only its header and implementation, exposed Shared::value and unused_api in Call View,
  enabled Build, disabled Run, and restored the library after reload. Evidence and screenshots are retained
  in `.icoda-test-artifacts/library-scope/`; the library Call View was visually inspected.
- Updated the handbook and regenerated its 97-page PDF (37 images). Rendered and visually checked the selector
  instructions on page 18 and the following page using Poppler.

## 2026-09-20 — Keep hierarchy contents beneath their files and classes

The shared hierarchy previously rendered model insertion order: clusters, all files, then all entities. Its
indentation described ownership, but functions appeared together below the file list. The core now traverses
parents before their children, keeping each complete file/class subtree together in source order. All three
diagram hierarchies share that ordering. Parent-child branch lines make the nesting visible; function status
colors, source navigation, filtering, and expand/collapse behavior are preserved.

Verification:

- **629 tests passed in 89.74 seconds**. Expansion, GUI, and source-navigation cases cover multiple clusters and
  sibling files, nested classes, methods defined in a different file, filtered parents, and collapse/re-expand.
- Ruff, mypy across 61 production files, and `git diff --check` passed.
- Native `tests/editor_gui_acceptance.py` verified the on-screen row positions and indentation for two files,
  their classes, methods, and free functions. A real method click opened the correct source line; a real collapse
  click hid only the selected file's contents, and re-expanding restored the original row positions. The existing
  source-editor acceptance checks also passed. Evidence is in `.icoda-test-artifacts/hierarchy-order/`; the
  `file-hierarchy.png` screenshot was visually inspected.

## 2026-09-20 — Scroll the hierarchy and reliably drag diagrams

Each File, Call, and Class hierarchy now has a native vertical scrollbar and a bounded row viewport.
The mouse wheel inside the hierarchy scrolls its rows independently of diagram zoom. Scroll positions are
clamped when rows collapse or the view resizes; hidden rows cannot receive clicks. Hit testing prioritizes
the hierarchy over diagram nodes behind it, and pressing inside the hierarchy does not start a diagram pan.

Diagram dragging measures total movement from the press position, so a sequence of small mouse movements
correctly becomes a drag and remains positioned after resizing. Double-click handling runs on release, allowing
a rapid second press to start another drag. Drag releases do not open source as accidental double-clicks.

Verification:

- **632 tests passed in 89.24 seconds**. Cases cover scrollbar endpoints and page steps, wheel/zoom separation, collapse clamping,
  hierarchy hit priority, and slow cumulative drags across all four diagrams.
- Ruff, mypy across 61 production files, and `git diff --check` passed.
- Native `tests/editor_gui_acceptance.py` used a class with 60 methods in File, Call, and Class View. It verified
  visible scrollbars, wheel scrolling, the scrollbar's actual registered callback, source navigation from the
  last row, and a real click immediately followed by a 30-event slow drag. All existing editor checks passed.
  Evidence and screenshots are in `.icoda-test-artifacts/hierarchy-scroll-final/`.

## 2026-09-20 — Play a short sound when an LLM request finishes

Prompt replies, approach/proposal requests, and automatic LLM recovery now play the system notification sound
from their UI completion callbacks, including requests that finish with an error. Cancelled requests and stale
Prompt/recovery callbacks remain silent, as do ordinary approval, terminal-launch, and build/test operations.
Internal retries produce only the request's final completion notification.

Verification:

- **68 focused tests passed in 10.57 seconds** across troubleshooting and step-controller GUI behavior.
  Checks cover one ping per reply, UI-callback timing, success/error/cancellation, stale project callbacks,
  approaches/proposals, recovery, workflow preconditions, and silent non-LLM actions.
- Ruff, mypy for the three changed production modules, and `git diff --check` passed.
- A native Tk check invoked one system bell through `UiTasks` on the main UI thread after a separate worker
  completed, then closed its temporary window.

## 2026-09-20 — Simpler step descriptions and a visible editor filename

Proposal and approach prompts now ask for everyday language: one short summary, then up to three brief points
covering the change, checks, and important decisions. Titles use a short action. Required scope, estimates,
and trade-offs remain part of the request. This guidance applies to newly generated descriptions.

The source editor shows the filename in a bold heading, with an unsaved marker when needed. The project and
relative path remain underneath and are available in a tooltip, so a long path cannot hide the filename.

Verification:

- **74 existing prompt, source-editor, and step-controller tests passed in 10.66 seconds**.
- Ruff, mypy for both changed production modules, and `git diff --check` passed.
- Native `tests/editor_gui_acceptance.py` passed navigation, editing, undo/redo, saving, and reloading checks.
  Visually checked the filename heading in `.icoda-test-artifacts/editor-filename/source-editor.png`.

## 2026-09-20 — Drag the hierarchy panel by its header

The previous mouse fix moved the diagram; the hierarchy overlay still had a fixed screen position. Its shaded
header now says "Hierarchy — drag here to move" and moves the panel independently in File, Call, and Class View.
The scrollbar moves with it, row clicks keep their navigation behavior, and header releases cannot open nodes.
Each view retains the panel position across redraws. Dragging and resizing clamp it within the canvas, with the
number of visible rows adjusted to the available height.

Verification:

- **88 focused GUI and navigation tests passed in 17.32 seconds**, including slow header drags, single/double
  releases, independent diagram coordinates, redraw persistence, and drag/resize bounds.
- Ruff, mypy for the four changed production files and native acceptance script, and `git diff --check` passed.
- Native `tests/editor_gui_acceptance.py` passed in all three views: actual mouse events moved the hierarchy
  120 pixels left and 30 pixels down, its scrollbar followed, and a row click after scrolling still opened the
  correct source line. The existing diagram-drag and editor checks also passed. Screenshots and evidence are in
  `.icoda-test-artifacts/movable-hierarchy-final/`; the moved File and Class hierarchy screenshots were inspected.
