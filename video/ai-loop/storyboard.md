# AI-Loop introduction video storyboard

Format: 1920×1080, 30 fps, white background. The complete official University of Vienna logo appears on every slide, contained at 200×100 pixels and centered in `[1600,38]–[1840,138]`. Titles remain inside `[90,50]–[1500,145]`. Dark text and University blue are the only routine colors; focus overlays use a 6-pixel red stroke. Screenshot coordinates below are final-slide pixels.

Every 1408×812 GUI screenshot is proportionally contained at 1404×810 pixels inside target box `[120,190]–[1800,1000]`, giving rendered image box `[258,190]–[1662,1000]`. Nothing is cropped, stretched, or covered. Callout text stays in the left/right white margins; red outlines are transparent inside.

## Slide 01 — AI-Loop

- **Visual:** Title diagram.
- **Exact on-screen elements:** `AI-Loop`; subtitle `Persistent, checked coding-agent work`; `Helmut Hlavacs`; `University of Vienna`; centered four-node loop `PLAN → IMPLEMENT → VALIDATE → CONTINUE` with a return arrow from Continue to Plan.
- **Screenshot:** None. Diagram target `[180,250]–[1740,880]`.
- **Highlight:** None.

## Slide 02 — About Helmut Hlavacs

- **Visual:** Five-row contact card with small line icons.
- **Exact on-screen elements:** `Helmut Hlavacs`; `Professor, Faculty of Computer Science`; `University of Vienna`; `https://www.univie.ac.at/`; `helmut.hlavacs@univie.ac.at`; `https://github.com/hlavacs/AI-Loop`.
- **Screenshot:** None. Card target `[210,235]–[1710,900]`.
- **Highlight:** None.

## Slide 03 — What AI-Loop is for

- **Visual:** Left/right comparison.
- **Exact on-screen elements:** left heading `ONE CHAT`, one long bar ending at `context or usage limit`; right heading `DURABLE JOB`, four connected cards `change`, `test`, `review`, `continue`; footer labels `multi-file features`, `migrations`, `repairs`, `test coverage`.
- **Screenshot:** None. Comparison target `[120,245]–[1800,900]`.
- **Highlight:** None.

## Slide 04 — The basic idea

- **Visual:** Single flow diagram.
- **Exact on-screen elements:** input cards `Repository`, `Goal`, `Validation`; central loop `Controller → Task → Worker → Evidence → Controller`; exit cards `Done`, `Human input`, `Stopped safely`.
- **Screenshot:** None. Diagram target `[110,230]–[1810,910]`.
- **Highlight:** None.

## Slide 05 — A durable shared notebook

- **Visual:** Mental-model diagram.
- **Exact on-screen elements:** center card `DURABLE JOB RECORD` with rows `plan`, `tasks`, `runs`, `decisions`, `evidence`; surrounding cards `Controller`, `Worker`, `Watcher`, `Git worktree`, `Tests`; one pause icon and arrow labelled `resume later`.
- **Screenshot:** None. Diagram target `[160,220]–[1760,900]`.
- **Highlight:** None.

## Slide 06 — How it works: actors and storage

- **Visual:** Compact architecture diagram.
- **Exact on-screen elements:** `Controller: plans + reviews`; `Worker: edits + validates`; `Watcher: supervises + notifies`; center `Redis Streams`; lower data cards `SQLite job history` and `isolated Git worktree`; directional arrows showing controller/worker messages through Redis and both reading durable state.
- **Screenshot:** None. Diagram target `[125,230]–[1795,910]`.
- **Highlight:** None.

## Slide 07 — How it works: lifecycle

- **Visual:** Horizontal state path.
- **Exact on-screen elements:** `Create → Plan → Queue task → Implement → Review → Promote → Validate → Done`; branch from Implement to `waiting for tokens`; branch from Review to `human needed`; return arrows labelled `resume same job`; small note `worktree and history remain`.
- **Screenshot:** None. State path target `[90,250]–[1830,880]`.
- **Highlight:** None.

## Slide 08 — GUI tour: one operational view

- **Visual:** Full screenshot.
- **Exact on-screen elements:** title plus margin labels `Create + select jobs`, `Inspect durable state`, `Resume or repair`. Within the screenshot retain the top-level tabs, toolbar, filled form, three synthetic job rows, selected active job, and Status text.
- **Screenshot:** `video/ai-loop/screenshots/s11-gui-jobs-status.png` (capture plan source 1408×812); target `[120,190]–[1800,1000]`, rendered `[258,190]–[1662,1000]`.
- **Highlight:** red rectangles `[258,232]–[578,260]` for the top-level tabs, `[266,766]–[1023,849]` for the Jobs rows, and `[1044,268]–[1648,820]` for the inspection pane; thin red arrows originate in the corresponding white margins.

## Slide 09 — GUI tour: Create Job

- **Visual:** Full screenshot, form focus.
- **Exact on-screen elements:** title plus margin labels `repository + goal`, `validation command`, `independent roles`, `safe worktree default`. Retain every form field and the `Quick Job` button.
- **Screenshot:** `video/ai-loop/screenshots/s17-quick-job-form.png` (1408×812); target and rendered boxes as common contract.
- **Highlight:** `[310,296]–[1015,541]` around Repo and Goal; `[310,547]–[1016,572]` around Test; `[386,574]–[1016,631]` around controller/worker rows; `[275,658]–[1016,725]` around granularity, isolation checkboxes, and action button.

## Slide 10 — GUI tour: Jobs and Status

- **Visual:** Full screenshot.
- **Exact on-screen elements:** title plus margin labels `selected durable job`, `state + progress`, `process roles`. Keep job colors and the plain-language Status page readable.
- **Screenshot:** `video/ai-loop/screenshots/s11-gui-jobs-status.png` (1408×812); common target/rendered boxes.
- **Highlight:** `[266,766]–[1023,849]` around the three job rows; `[1046,294]–[1648,472]` around job/state/progress; `[1046,548]–[1648,817]` around controller and worker summaries.

## Slide 11 — GUI tour: immutable Plan

- **Visual:** Full screenshot.
- **Exact on-screen elements:** title plus labels `completed`, `working here`, `later`. The Plan tab shows exactly four enumerated steps and its legend.
- **Screenshot:** `video/ai-loop/screenshots/s12-gui-plan.png` (1408×812); common target/rendered boxes.
- **Highlight:** `[1046,297]–[1646,326]` around completed step 1; `[1046,336]–[1646,376]` around current step 2; red arrow to steps 3 and 4 at `[1046,395]–[1646,490]`.

## Slide 12 — GUI tour: Task and Controller

- **Visual:** Full screenshot.
- **Exact on-screen elements:** title plus labels `bounded assignment`, `completion checks`, `validation`. Keep the Task tab selected and the Controller tab visible next to it.
- **Screenshot:** `video/ai-loop/screenshots/s13-gui-task-controller.png` (1408×812); common target/rendered boxes.
- **Highlight:** `[1045,300]–[1645,533]` around task identity and detailed instructions; `[1045,653]–[1645,752]` around completion checks; `[1045,769]–[1645,799]` around the validation command; arrow points to the `Controller` tab at `[1170,268]–[1247,295]`.

## Slide 13 — GUI tour: Worker and Details

- **Visual:** Full screenshot.
- **Exact on-screen elements:** title plus labels `execution state`, `worker report`, `validation evidence`. Keep Worker selected and Details visible.
- **Screenshot:** `video/ai-loop/screenshots/s14-gui-worker-details.png` (1408×812); common target/rendered boxes.
- **Highlight:** `[1046,300]–[1645,425]` around worker and current-task state; `[1046,467]–[1645,620]` around result/report; `[1046,638]–[1645,730]` around failed validation evidence; arrow to Details tab `[1305,268]–[1360,295]`.

## Slide 14 — GUI tour: logs and controls

- **Visual:** Full screenshot.
- **Exact on-screen elements:** title plus labels `live process log`, `Finish Soon narrows scope`, `Finish Early preserves progress`, `Sign In + Resume`. Keep toolbar, open Job Actions menu, and five synthetic log lines visible.
- **Screenshot:** `video/ai-loop/screenshots/s15-gui-logs-controls.png` (1408×812); common target/rendered boxes.
- **Highlight:** `[1045,325]–[1647,492]` around log lines; `[463,190]–[848,365]` around Finish Soon and open Job Actions menu; arrows target `Sign In + Resume` and `Finish Early` in that menu.

## Slide 15 — GUI tour: recover, do not discard

- **Visual:** Full screenshot with modal.
- **Exact on-screen elements:** title plus labels `problem detected`, `worktree preserved`, `same-job resume`. Retain the complete Human Needed dialog, reason/history text, two possible actions, and buttons.
- **Screenshot:** `video/ai-loop/screenshots/s16-gui-provider-repair.png` (1408×812); common target/rendered boxes.
- **Highlight:** `[555,339]–[1268,428]` around reason/history; `[555,438]–[1268,606]` around actions; `[1054,760]–[1171,794]` around `Sign In + Resume`.

## Slide 16 — Walkthrough: start with the idea

- **Visual:** Idea card and compact terminal card.
- **Exact on-screen elements:** `Idea: a tiny order-totals project`; behavior card `Orders of 100 or more receive the discount`; repository tree `src/totals.py`, `tests/test_totals.py`; terminal input `$ python -m pytest -q`; terminal output `1 failed, 11 passed`; decision line `Let AI-Loop diagnose and repair it`.
- **Screenshot:** None. Cards target `[150,220]–[1770,910]`.
- **Highlight:** Red rectangle around `1 failed, 11 passed` and arrow to the decision line.

## Slide 17 — Walkthrough input 1: repository and goal

- **Visual:** Full screenshot with first input focus.
- **Exact on-screen elements:** overlay labels `1  Choose repository` and `2  State the outcome`; retain exact Repo value `/tmp/ai-loop-demo/one-failing-test` and exact Goal `Diagnose the failure, make the smallest correct repair, and make the test suite pass.`.
- **Screenshot:** `video/ai-loop/screenshots/s17-quick-job-form.png` (1408×812); common target/rendered boxes.
- **Highlight:** `[310,296]–[1015,329]` around Repo with arrow from step 1; `[310,332]–[790,541]` around Goal with arrow from step 2.

## Slide 18 — Walkthrough inputs 3 through 9

- **Visual:** Full screenshot with remaining input focus.
- **Exact on-screen elements:** numbered margin key: `3  Test: python -m pytest -q`; `4  Controller: claude`; `5  Worker: codex`; `6  Base: HEAD`; `7  Max iterations: 12`; `8  Granularity: normal`; `9  Worktree isolation on; parallel and bypass off`.
- **Screenshot:** `video/ai-loop/screenshots/s17-quick-job-form.png` (1408×812); common target/rendered boxes.
- **Highlight:** `[310,547]–[1016,572]` Test; `[386,575]–[1016,632]` role rows; `[386,634]–[1016,661]` base/max; `[275,659]–[1016,716]` granularity and checkboxes. Short red leader lines map each numbered key to its control.

## Slide 19 — Walkthrough input 10 and immediate output

- **Visual:** Two-step graphical pseudo-screencast.
- **Exact on-screen elements:** left inset reproduces only the form action area with `10  Click Quick Job`; blue arrow labelled `creates durable state`; right inset reproduces Jobs table with new row `demo-quick-fix-003`, initial state `planning`, progress `0%`; footer output labels `job ID`, `worktree`, `controller starts`.
- **Screenshot:** left inset uses source `video/ai-loop/screenshots/s17-quick-job-form.png`, explicit source crop `[630,470]–[770,550]`, contained in target `[180,300]–[820,760]`; right inset uses `video/ai-loop/screenshots/s11-gui-jobs-status.png`, explicit source crop `[10,535]–[770,812]`, contained in target `[1060,300]–[1740,760]`. Scale each crop proportionally and center it in its target; do not crop again after placement.
- **Highlight:** red rectangle `[300,515]–[570,620]` around action button in left inset; `[1110,480]–[1665,620]` around newly created row in right inset.

## Slide 20 — Walkthrough output: the plan

- **Visual:** Full screenshot.
- **Exact on-screen elements:** labels `Output 1: reproduce`, `Output 2: focused correction`, `Output 3: targeted + full tests`, `Output 4: review clean checkout`. Plan tab stays selected and all steps remain readable.
- **Screenshot:** `video/ai-loop/screenshots/s12-gui-plan.png` (1408×812); common target/rendered boxes.
- **Highlight:** one red moving-outline sequence, ending on current step `[1046,336]–[1646,376]`; no simultaneous boxes over all four lines.

## Slide 21 — Walkthrough output: controller creates a task

- **Visual:** Full screenshot.
- **Exact on-screen elements:** labels `Task: Correct the boundary comparison`; `Instructions: change one comparison; preserve passing cases`; `Acceptance: boundary test + all twelve tests`; `Validation: python -m pytest -q`.
- **Screenshot:** `video/ai-loop/screenshots/s13-gui-task-controller.png` (1408×812); common target/rendered boxes.
- **Highlight:** sequential red rectangles `[1045,300]–[1645,352]`, `[1045,548]–[1645,632]`, `[1045,653]–[1645,752]`, and `[1045,769]–[1645,799]`, one at a time to match narration.

## Slide 22 — Walkthrough output: worker evidence

- **Visual:** Full screenshot.
- **Exact on-screen elements:** labels `Worker runs task`, `First result diagnoses one comparison`, `Evidence: 1 failed, 11 passed`, `Controller decides the next task`. Worker tab stays selected.
- **Screenshot:** `video/ai-loop/screenshots/s14-gui-worker-details.png` (1408×812); common target/rendered boxes.
- **Highlight:** sequential red rectangles `[1046,300]–[1645,425]`, `[1046,467]–[1645,620]`, and `[1046,638]–[1645,730]`; final arrow points toward the Controller tab.

## Slide 23 — Walkthrough output: completion

- **Visual:** Full screenshot.
- **Exact on-screen elements:** labels `done — 100%`, `src/totals.py: 2 additions, 1 deletion`, `target-checkout validation: PASSED`, `12 passed`. Retain the selected completed job row and complete Worker result.
- **Screenshot:** `video/ai-loop/screenshots/s18-quick-job-complete.png` (1408×812); common target/rendered boxes.
- **Highlight:** `[266,815]–[870,848]` around completed job row; `[1046,466]–[1645,590]` around passed result and changed file; `[1046,621]–[1645,720]` around target validation and `12 passed`.

## Slide 24 — Choose the right level, then continue

- **Visual:** Closing card.
- **Exact on-screen elements:** three small paths `Direct model → focused question`, `AI-Loop → persistent checked work`, `Repair helper → fix tooling, resume job`; `https://github.com/hlavacs/AI-Loop`; `helmut.hlavacs@univie.ac.at`; `https://entertain.univie.ac.at/~hlavacs/`; `Robimo.at — AI-tooling service provider`; closing line `Thank you`.
- **Screenshot:** None. Three-path diagram target `[130,230]–[1790,610]`; contact card target `[250,650]–[1670,960]`.
- **Highlight:** None.
