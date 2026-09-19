# ICODA introduction video storyboard

Format: 1920×1080, 30 fps, white background. The complete official University of Vienna logo appears on every slide, contained at 200×100 pixels and centered in `[1600,38]–[1840,138]`. Titles remain inside `[90,50]–[1500,145]`. Dark text and University blue are the only routine colors; focus overlays use a 6-pixel red stroke with a transparent interior. Coordinates below are final-slide pixels.

Unless a slide says otherwise, each ICODA GUI capture is proportionally contained in `[120,190]–[1800,1000]` and centered without cropping or stretching. This box lies below and therefore leaves the logo box `[1600,38]–[1840,138]` clear. The expected 1200×760 capture aspect produces an approximately `[320,190]–[1600,1000]` rendered image; the renderer must calculate the exact centered box from the captured dimensions before applying overlays.

## Slide 01 — ICODA

- **Visual:** Title diagram.
- **Exact on-screen elements:** `ICODA`; subtitle `Interactive Code Development and Analysis`; `Helmut Hlavacs`; `University of Vienna`; `https://entertain.univie.ac.at/~hlavacs/`; centered progression `SPECIFICATION → ARCHITECTURE → IMPLEMENTATION` above a small loop `propose → inspect evidence → decide`.
- **Screenshot or diagram:** drawn title diagram.
- **Contain target:** `[180,240]–[1740,900]`, below and clear of the logo box.
- **Highlight:** none; the title, affiliation, personal page, and lifecycle diagram are the complete visual focus.

## Slide 02 — About Helmut Hlavacs

- **Visual:** Five-row contact card with small line icons.
- **Exact on-screen elements:** `Helmut Hlavacs`; `Professor, Faculty of Computer Science`; `University of Vienna`; `https://www.univie.ac.at/`; `helmut.hlavacs@univie.ac.at`; `https://entertain.univie.ac.at/~hlavacs/`; `https://github.com/hlavacs/AI-Loop/tree/main/icoda`.
- **Screenshot or diagram:** drawn contact-card diagram.
- **Contain target:** card `[210,235]–[1710,900]`, below and clear of the logo box.
- **Highlight:** none; the contact-card rows are the complete visual focus.

## Slide 03 — What ICODA is for

- **Visual:** Left/right comparison.
- **Exact on-screen elements:** left heading `CODE AS TEXT` with cards `files`, `symbols`, `tests`; right heading `CODE AS A DECISION SYSTEM` with cards `specification`, `architecture`, `proposals`, `evidence`, `history`; footer `new projects`, `existing systems`, `controlled AI-assisted change`.
- **Screenshot or diagram:** drawn comparison diagram.
- **Contain target:** comparison `[120,235]–[1800,900]`, below and clear of the logo box.
- **Highlight:** none; the two-column comparison and footer are the complete visual focus.

## Slide 04 — The basic idea

- **Visual:** Single flow diagram.
- **Exact on-screen elements:** inputs `Written specification`, `Source tree`, `Developer intent`; center `Derived code model`; views `File`, `Call`, `Class`, `Mind Map`, `Coverage`, `Issues`; decision loop `Sandboxed provider subprocess → validated reply → isolated worktree → build + tests → developer decision → Git commit`.
- **Screenshot or diagram:** drawn data-flow and decision-loop diagram.
- **Contain target:** diagram `[105,220]–[1815,915]`, below and clear of the logo box.
- **Highlight:** none; the input, model, views, and sandboxed proposal loop are the complete visual focus.

## Slide 05 — The mental model: two truths

- **Visual:** Two-column model joined by a comparison lens.
- **Exact on-screen elements:** left card `INTENT` with `goals`, `scope`, `requirements`, `decisions`, `code profile`; right card `IMPLEMENTATION` with `files`, `entities`, `calls`, `tests`, `history`; center lens `ICODA derives the map and exposes the gaps`; lower line `the developer owns every consequential decision`.
- **Screenshot or diagram:** drawn two-truths diagram.
- **Contain target:** diagram `[150,220]–[1770,900]`, below and clear of the logo box.
- **Highlight:** none; the intent and implementation cards joined by the ICODA lens are the complete visual focus.

## Slide 06 — How ICODA works

- **Visual:** Numbered architecture pipeline.
- **Exact on-screen elements:** bootstrap card `constraints.txt pins the prepared environment`; launcher note `validate only — never install or upgrade`; `1  Parse the project`; `2  Build a derived model`; `3  Select a phase and target`; `4  Ask the configured coding agent`; `5  Apply in an isolated worktree`; `6  Build and test`; `7  Approve, reject, or adapt`; `8  Commit approved work`; storage cards `.icoda specification + state + step log` and `Git history`.
- **Screenshot or diagram:** drawn bootstrap card and numbered architecture pipeline.
- **Contain target:** pipeline `[120,220]–[1800,920]`, below and clear of the logo box.
- **Highlight:** none; the pinned bootstrap card, validate-only launcher note, and operating pipeline are the complete visual focus.

## Slide 07 — GUI tour: File View

- **Visual:** Full GUI screenshot.
- **Exact on-screen elements:** labels `shared filter + neighborhood controls`, `clusters, files, and entities`, `LLM Binary + Model`, `selectable entity tree`, and `phase, request, evidence, decisions`. Explain the diagram hierarchy, top view tabs, right-side controls, and lower workflow panel that are visible.
- **Screenshot:** `video/icoda/screenshots/views/file-view.png` (exact ICODA capture id from the capture plan).
- **Contain target:** `[120,190]–[1800,1000]`, centered proportionally; logo box remains clear.
- **Highlight:** red rectangles `[320,218]–[1260,655]` around the file diagram, `[1262,218]–[1598,655]` around LLM selectors and entity tree, and `[320,660]–[1598,995]` around the workflow panel; red arrow `[180,250]→[420,250]` points to graph controls.

## Slide 08 — GUI tour: Call View

- **Visual:** Full GUI screenshot.
- **Exact on-screen elements:** labels `callers and callees`, `arrow direction`, `depth + fit controls`, `hierarchy remains expandable`, and `side panel identifies the selected entity`. Explain the selected Call View tab, readable nodes and directed edges, toolbar, entity tree, and workflow panel.
- **Screenshot:** `video/icoda/screenshots/views/call-view.png` (exact ICODA capture id from the capture plan).
- **Contain target:** `[120,190]–[1800,1000]`, centered proportionally; logo box remains clear.
- **Highlight:** red rectangle `[320,250]–[1258,650]` around the call graph; arrows `[180,330]→[520,360]` to a caller edge and `[1740,350]→[1450,350]` to the entity tree; rectangle `[880,220]–[1258,250]` around depth and zoom controls.

## Slide 09 — GUI tour: Class View

- **Visual:** Full GUI screenshot.
- **Exact on-screen elements:** labels `classes and structs`, `methods + signatures`, `inheritance and type relations`, `status legend`, and `zoom, pan, fit`. Explain the class boxes, member rows, connecting relationships, toolbar, entity selection tree, and persistent lower decision panel.
- **Screenshot:** `video/icoda/screenshots/views/class-view.png` (exact ICODA capture id from the capture plan).
- **Contain target:** `[120,190]–[1800,1000]`, centered proportionally; logo box remains clear.
- **Highlight:** red rectangles `[350,285]–[900,570]` around the central class and member signatures and `[930,270]–[1235,600]` around related types; red arrow `[1750,330]→[1500,350]` points to the selected entity.

## Slide 10 — GUI tour: Mind Map

- **Visual:** Full GUI screenshot.
- **Exact on-screen elements:** labels `project → cluster → file → entity`, `expand a branch`, `select history from the map`, and `same workflow context below`. Explain the expanded source cluster, nested branches, connector lines, map controls, entity tree, and proposal panel.
- **Screenshot:** `video/icoda/screenshots/views/mind-map.png` (exact ICODA capture id from the capture plan).
- **Contain target:** `[120,190]–[1800,1000]`, centered proportionally; logo box remains clear.
- **Highlight:** red rectangle `[340,260]–[1210,620]` around the expanded hierarchy; red arrows `[185,345]→[480,365]` to the source cluster and `[1750,440]→[1455,440]` to contextual entities.

## Slide 11 — GUI tour: Requirements Coverage

- **Visual:** Full GUI screenshot.
- **Exact on-screen elements:** labels `specification requirement`, `implementing entity`, `recorded test reachability`, `successful step records + analysed call edges`, `not runtime or branch coverage`, `reached / not reached summary`, and `open the source`. Explain that specification traceability and structural recorded test reachability are separate dimensions; cover the summary, rows, right-side context, and lower workflow controls.
- **Screenshot:** `video/icoda/screenshots/views/requirements-coverage.png` (exact ICODA capture id from the capture plan).
- **Contain target:** `[120,190]–[1800,1000]`, centered proportionally; logo box remains clear.
- **Highlight:** red rectangles `[335,255]–[1245,340]` around the recorded test reachability summary and `[335,345]–[1245,610]` around requirement and structural evidence rows; red arrow `[1760,400]→[1490,400]` points to entity context.

## Slide 12 — GUI tour: Rule Issues

- **Visual:** Full GUI screenshot.
- **Exact on-screen elements:** labels `severity`, `rule`, `entity`, `action`, `location`, `30 lines: advisory`, `over 50 lines: blocked`, `checked at proposal and approval`, and `double-click to inspect source`. Explain the Issues tab, issue-count summary, all five table columns, selected issue context, and the separate blocking hard 50-line function gate.
- **Screenshot:** `video/icoda/screenshots/views/rule-issues.png` (exact ICODA capture id from the capture plan).
- **Contain target:** `[120,190]–[1800,1000]`, centered proportionally; logo box remains clear.
- **Highlight:** red rectangle `[335,270]–[1245,600]` around the issue table; sequential red arrows `[180,330]→[410,330]`, `[180,390]→[650,390]`, and `[1750,455]→[1480,455]` identify severity, the 30-line advisory and blocking hard 50-line rule, and source context.

## Slide 13 — Walkthrough input: create the project

- **Visual:** Drawn pseudo-screencast with an ICODA File menu, native directory dialog, and immediate-output card.
- **Exact on-screen elements:** numbered inputs `1  File → New Project…` and `2  Directory: /tmp/icoda-demo/formatter`; outputs `directory created`, `.icoda state created`, `Phase: specification`, and `Specification editor opens`.
- **Screenshot:** drawn.
- **Contain target:** File-menu inset `[110,250]–[570,820]`; directory dialog `[650,250]–[1780,700]`; output card `[650,740]–[1780,930]`; all are below and clear of the logo box.
- **Highlight:** red rectangle `[142,315]–[535,375]` around `New Project…`, red rectangle `[720,410]–[1680,485]` around the directory value, and red arrow `[1680,485]→[1560,790]` points to the created-state output.

## Slide 14 — Walkthrough output: specification blocks code

- **Visual:** Full lifecycle screenshot.
- **Exact on-screen elements:** input `3  Click Propose before saving`; outputs `Phase: specification`, `no code proposal yet`, `Save the specification before proposing`, `state unchanged`, and `next action: open the editor`. Explain the still-sparse project views, provider selectors, disabled phase controls, failure title, detailed refusal, and status line.
- **Screenshot:** `video/icoda/screenshots/lifecycle/sim-01-specification-code-refused.png` (exact ICODA capture id from the capture plan).
- **Contain target:** `[120,190]–[1800,1000]`, centered proportionally; logo box remains clear.
- **Highlight:** red rectangle `[320,665]–[1598,995]` around phase, failed-step title, and refusal details; red arrow `[1750,720]→[1510,720]` points to `Phase: specification`.

## Slide 15 — Walkthrough inputs: specify, build, and configure

- **Visual:** Specification-editor screenshot, provider-selection screenshot inset, and drawn build/test output strip.
- **Exact on-screen elements:** inputs `4  Overview: title + description`; `5  Scope: goals, exclusions, constraints, done conditions`; `6  Use cases`; `7  Requirements with priorities and links`; `8  Decisions with rationale`; `9  Code profile: Python, pytest, 30-line advisory, hard 50-line limit`; `10  Validate, then Save`; `11  Confirm Build now`; `12  Project → Test Command…: python -m pytest -q`; `13  Binary: codex`; `14  Model: configured default`; outputs `.icoda/specification.json`, `step 0 recorded`, `project skeleton written`, `build passed`, `analysis populates all views`, and `phase → architecture`.
- **Screenshot:** primary `video/icoda/screenshots/lifecycle/sim-02-specification-save.png` and inset `video/icoda/screenshots/views/provider-selection.png` (exact ICODA capture ids from the capture plan).
- **Contain target:** specification editor `[80,190]–[1380,900]`; provider inset `[1410,240]–[1810,560]`; drawn output strip `[80,920]–[1810,1010]`; all remain clear of the logo box.
- **Highlight:** red rectangle `[180,220]–[1260,270]` around the six editor pages; arrows `[120,355]→[420,355]` to the visible fields and `[1310,850]→[1190,850]` to Save; red rectangles `[1480,295]–[1770,365]` around Binary and Model and `[620,935]–[1040,992]` around build/test output.

## Slide 16 — Walkthrough output and input: inspect, then reject

- **Visual:** Full lifecycle screenshot.
- **Exact on-screen elements:** inputs `15  Keep Request blank and Max entities 5`; `16  Click Propose`; `17  Inspect Delta, Diff, Build, Tests, Prompt, Reply`; `18  Click Reject…`; `19  Reason: Keep the public API smaller`; outputs `Draft formatter architecture`, `Formatter, normalize, main`, `Build: passed`, `Tests: passed`, and `proposal discarded; reason retained`.
- **Screenshot:** `video/icoda/screenshots/lifecycle/sim-03-architecture-reject.png` (exact ICODA capture id from the capture plan).
- **Contain target:** `[120,190]–[1800,1000]`, centered proportionally; logo box remains clear.
- **Highlight:** sequential red rectangles `[320,665]–[760,740]` around phase/request/actions, `[790,745]–[1595,970]` around Diff and gate evidence, and `[435,708]–[525,744]` around `Reject…`; red arrow `[525,744]→[700,790]` leads to the drawn rejection-reason callout.

## Slide 17 — Walkthrough output and input: approve the adaptation

- **Visual:** Full lifecycle screenshot.
- **Exact on-screen elements:** inputs `20  Click Propose again`, `21  Review the adapted Delta and entity summary`, `22  Click Approve`; outputs `Add formatter architecture`, `public API kept smaller`, `highlighted entity delta`, `Build: passed`, `Tests: passed`, and `approved source promoted and committed`.
- **Screenshot:** `video/icoda/screenshots/lifecycle/sim-04-architecture-approve.png` (exact ICODA capture id from the capture plan).
- **Contain target:** `[120,190]–[1800,1000]`, centered proportionally; logo box remains clear.
- **Highlight:** red rectangles `[790,745]–[1595,970]` around the adapted Delta and `[320,665]–[1595,740]` around the proposal title and passing gates; red arrow `[180,715]→[380,715]` points to `Approve`.

## Slide 18 — Walkthrough gate: enter implementation

- **Visual:** Full lifecycle screenshot.
- **Exact on-screen elements:** input `23  Click Approve architecture`; outputs `architecture proposal cleared`, `derived File View updated`, `architecture completion gate enabled`, `implementation queue: Formatter.normalize, main`, and `phase → implementation`. Explain the visible file graph, controls, entity list, empty proposal area, and sole phase-transition action.
- **Screenshot:** `video/icoda/screenshots/lifecycle/sim-05-architecture-gate.png` (exact ICODA capture id from the capture plan).
- **Contain target:** `[120,190]–[1800,1000]`, centered proportionally; logo box remains clear.
- **Highlight:** red rectangle `[320,220]–[1258,650]` around the updated architecture and red rectangle `[320,665]–[1595,760]` around the empty proposal and enabled gate; red arrow `[180,720]→[430,720]` points to `Approve architecture`.

## Slide 19 — Walkthrough target one: approve the approach

- **Visual:** Full lifecycle screenshot.
- **Exact on-screen elements:** inputs `24  Keep Batch size 1, Scope Queue order, Grouping One entity, Auto-approve off`; `25  Click Propose approach`; `26  Review expected entity and files`; `27  Click Approve approach`; outputs `Current target: service.Formatter.normalize — 2 remaining` and `Replace the normalize stub directly and add one focused test`.
- **Screenshot:** `video/icoda/screenshots/lifecycle/sim-06-normalize-approach.png` (exact ICODA capture id from the capture plan).
- **Contain target:** `[120,190]–[1800,1000]`, centered proportionally; logo box remains clear.
- **Highlight:** red rectangle `[320,665]–[1595,735]` around queue settings and current target, rectangle `[790,745]–[1595,970]` around the prose approach, and red arrow `[180,715]→[500,715]` to `Approve approach`.

## Slide 20 — Walkthrough target one: verify and approve code

- **Visual:** Full lifecycle screenshot.
- **Exact on-screen elements:** inputs `28  Click Propose`; `29  Inspect Delta, Diff, Build, Tests, Prompt, Reply`; `30  Click Approve`; outputs `Implement Formatter.normalize`, `return value.strip()`, `tests/test_service.py added`, `Python syntax/build gate passed`, `Test gate passed: python -m pytest -q`, `source promoted + committed`, and `recorded evidence structurally reaches normalize`.
- **Screenshot:** `video/icoda/screenshots/lifecycle/sim-07-normalize-build-test.png` (exact ICODA capture id from the capture plan).
- **Contain target:** `[120,190]–[1800,1000]`, centered proportionally; logo box remains clear.
- **Highlight:** sequential red rectangles `[320,665]–[780,740]` around title and passing statuses, `[790,745]–[1595,970]` around measured Delta/build/test evidence, and `[350,705]–[430,742]` around `Approve`; red arrow `[180,500]→[610,500]` points to the structurally reached class-view entity.

## Slide 21 — Walkthrough target two: approve the approach

- **Visual:** Full lifecycle screenshot.
- **Exact on-screen elements:** inputs `31  Click Propose approach`; `32  Review entity and files`; `33  Click Approve approach`; outputs `queue advances automatically`, `Current target: service.main — 1 remaining`, and `Complete main using Formatter and add its observable result test`. Explain the Mind Map, expanded project hierarchy, queue settings, prose Approach tab, and decision buttons.
- **Screenshot:** `video/icoda/screenshots/lifecycle/sim-08-main-approach.png` (exact ICODA capture id from the capture plan).
- **Contain target:** `[120,190]–[1800,1000]`, centered proportionally; logo box remains clear.
- **Highlight:** red rectangle `[340,260]–[1210,620]` around the Mind Map, rectangle `[320,665]–[1595,735]` around the new target, rectangle `[790,745]–[1595,970]` around the approach, and red arrow `[180,715]→[500,715]` to `Approve approach`.

## Slide 22 — Walkthrough target two: verify and approve code

- **Visual:** Full lifecycle screenshot.
- **Exact on-screen elements:** inputs `34  Click Propose`; `35  Inspect source Diff and both gates`; `36  Click Approve`; outputs `Implement main`, `return f"ready:{value}"`, `test_main expects ready:item`, `Build: passed`, `Tests: passed`, `source promoted + committed`, and `recorded evidence structurally reaches main`.
- **Screenshot:** `video/icoda/screenshots/lifecycle/sim-09-main-build-test.png` (exact ICODA capture id from the capture plan).
- **Contain target:** `[120,190]–[1800,1000]`, centered proportionally; logo box remains clear.
- **Highlight:** red rectangle `[340,275]–[1240,595]` around the visible Issues view, sequential rectangle `[790,745]–[1595,970]` around Diff and gate evidence, and red arrow `[180,715]→[390,715]` to `Approve`.

## Slide 23 — Walkthrough output: terminal overview

- **Visual:** Full lifecycle screenshot.
- **Exact on-screen elements:** outputs `Implementation queue: empty — no unimplemented functions`, `recorded test reachability links both callables to a successful test record`, `approved steps in history`, `working tree clean`, and `all scripted provider replies consumed`; release card `verify.bash includes real-provider acceptance` and `missing authentication: fail, or explicit waiver records SKIP`. Explain the structural evidence, terminal queue, absent proposal, disabled action state, and release acceptance card.
- **Screenshot:** `video/icoda/screenshots/lifecycle/sim-10-terminal-overview.png` (exact ICODA capture id from the capture plan).
- **Contain target:** `[120,190]–[1800,1000]`, centered proportionally; logo box remains clear.
- **Highlight:** red rectangles `[335,255]–[1245,610]` around final recorded test reachability and `[320,665]–[1595,760]` around the empty implementation queue; red arrows `[1750,410]→[1470,410]` to both structurally reached entities and `[180,720]→[500,720]` to the terminal state; a red arrow on the release card points to `real-provider acceptance`.

## Slide 24 — Keep intent, evidence, and decisions together

- **Visual:** Closing diagram and contact card.
- **Exact on-screen elements:** three cards `Specify the intended system`, `Inspect structure and evidence`, `Approve only verified change`; `https://github.com/hlavacs/AI-Loop/tree/main/icoda`; `helmut.hlavacs@univie.ac.at`; `https://entertain.univie.ac.at/~hlavacs/`; `Robimo.at - AI-tooling service provider`; closing line `Thank you`.
- **Screenshot or diagram:** drawn closing diagram and contact card.
- **Contain target:** three-card diagram `[130,220]–[1790,600]`; contact card `[250,640]–[1670,960]`; both remain clear of the logo box.
- **Highlight:** none; the three summary cards and closing contact card are the complete visual focus.
