# AI-Loop introduction video shot list, version 2

This list maps one simple 1920 by 1080 slide to every narration segment in `docs/video/SCRIPT.md`. The common layout reserves the upper-right corner for the University of Vienna logo and keeps headlines, bullets, and images clear of that space. Generated diagrams are purpose-built graphics, not screenshots. New captures must use sanitized demo data and hide private paths, accounts, tokens, and messages.

## s01 — `s01_title`

- Visual type: Generated diagram.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Content: AI-Loop headline; `Helmut Hlavacs`; `University of Vienna`; a small plan, implement, validate, continue loop.
- Simplicity: One diagram, one headline, and no more than three short supporting lines.

## s02 — `s02_presenter`

- Visual type: Generated diagram.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Content: Presenter card with the University website, university email, and GitHub repository URL exactly as written in the script.
- Simplicity: One contact-card diagram, one headline, and four short contact lines.

## s03 — `s03_purpose`

- Visual type: Generated diagram.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Content: A single chat ending early on the left and a persistent multi-call job reaching checked completion on the right.
- Simplicity: One comparison diagram, one headline, and three short labels.

## s04 — `s04_basic_idea`

- Visual type: Generated diagram.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Content: Repository, outcome, and validation flowing into a controller, worker, evidence loop with three exit states.
- Simplicity: One loop diagram, one headline, and only short node labels.

## s05 — `s05_mental_model`

- Visual type: Generated diagram.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Content: Controller, worker, worktree, and tests surrounding a shared durable notebook; pause and resume arrows.
- Simplicity: One mental-model diagram, one headline, and no paragraph text.

## s06 — `s06_actors`

- Visual type: Generated diagram.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Content: Controller, worker, and watcher around the durable job record, with small SQLite, Redis Streams, and worktree labels.
- Simplicity: One architecture diagram, one headline, and compact labels only.

## s07 — `s07_lifecycle`

- Visual type: Generated diagram.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Content: Planning, queued, implementing, promotion, validation, and done on one path; small waiting and human-input branches.
- Simplicity: One lifecycle diagram, one headline, and no descriptive paragraphs.

## s08 — `s08_email`

- Visual type: Generated diagram.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Content: Sanitized email thread showing start, twelve-hour status, attention, completion, and a reply becoming a constraint.
- Simplicity: One email-thread diagram, one headline, and five short message labels.

## s09 — `s09_gui_overview`

- Visual type: Screenshot.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Screenshot status: Existing source file `docs/images/ai-loop-gui.png`; use the full application view and sanitize its title-bar byline and local repository path during visual production.
- Reserved image area: Left 100, top 220, right 1820, bottom 980 on the 1920 by 1080 slide; contain the full screenshot proportionally inside this 1720 by 760 area with padding, without cropping or overflow.
- Content: One headline above the screenshot and three short callouts inside the surrounding white margin.

## s10 — `s10_gui_create`

- Visual type: Screenshot.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Screenshot status: Existing source file `docs/images/ai-loop-gui.png`; use a proportional crop of the left-side Create Job view and sanitize the local repository path during visual production.
- Reserved image area: Left 180, top 210, right 1740, bottom 990 on the 1920 by 1080 slide; fit the crop proportionally inside this 1560 by 780 area with padding, without clipping controls, cropping content, or overflow.
- Content: One headline and four short callouts for goal, validation, roles, and isolation.

## s11 — `s11_gui_jobs`

- Visual type: Screenshot.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Screenshot status: New GUI capture required; capture the main window with a sanitized job selected in the Jobs list and the Status tab open.
- Reserved image area: Left 120, top 210, right 1800, bottom 990 on the 1920 by 1080 slide; contain the complete capture proportionally inside this 1680 by 780 area with padding, without cropping or overflow.
- Content: One headline and three short callouts for the selected job, state, and progress summary.

## s12 — `s12_gui_plan`

- Visual type: Screenshot.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Screenshot status: New GUI capture required; capture a sanitized completed or active job with the Plan tab open and the full plan readable.
- Reserved image area: Left 140, top 210, right 1780, bottom 990 on the 1920 by 1080 slide; contain the complete capture proportionally inside this 1640 by 780 area with padding, without cropping or overflow.
- Content: One headline and three short callouts for outcome, stages, and acceptance.

## s13 — `s13_gui_task_controller`

- Visual type: Screenshot.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Screenshot status: New GUI capture required; capture a sanitized active job with the Task tab open and the adjacent Controller tab visible in the tab bar.
- Reserved image area: Left 140, top 210, right 1780, bottom 990 on the 1920 by 1080 slide; contain the complete capture proportionally inside this 1640 by 780 area with padding, without cropping or overflow.
- Content: One headline and three short callouts for current assignment, acceptance, and next decision.

## s14 — `s14_gui_worker`

- Visual type: Screenshot.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Screenshot status: New GUI capture required; capture a sanitized job with the Worker tab open, a report visible, and the adjacent Details tab visible in the tab bar.
- Reserved image area: Left 140, top 210, right 1780, bottom 990 on the 1920 by 1080 slide; contain the complete capture proportionally inside this 1640 by 780 area with padding, without cropping or overflow.
- Content: One headline and three short callouts for result, changed files, and validation evidence.

## s15 — `s15_gui_logs`

- Visual type: Screenshot.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Screenshot status: New GUI capture required; capture a sanitized active or completed job with the Logs tab open and the refresh, stop, resume, Finish Soon, and Finish Early toolbar controls visible.
- Reserved image area: Left 140, top 210, right 1780, bottom 990 on the 1920 by 1080 slide; contain the complete capture proportionally inside this 1640 by 780 area with padding, without cropping or overflow.
- Content: One headline and four short callouts for logs, resume, Finish Soon, and Finish Early.

## s16 — `s16_gui_repair`

- Visual type: Screenshot.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Screenshot status: New GUI capture required; capture the provider authentication or repair dialog that offers Sign In, Fix binary, or Fix It, using sanitized provider and job data.
- Reserved image area: Left 300, top 210, right 1620, bottom 970 on the 1920 by 1080 slide; contain the entire dialog proportionally inside this 1320 by 760 area with padding, without cropping or overflow.
- Content: One headline and three short callouts for the detected problem, assisted action, and same-job resume.

## s17 — `s17_quick_job`

- Visual type: Screenshot.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Screenshot status: New GUI capture required; capture the Create Job view filled with a sanitized demo repository, the one-failing-test goal, its test command, normal granularity, and worktree isolation.
- Reserved image area: Left 220, top 210, right 1700, bottom 990 on the 1920 by 1080 slide; contain the complete form proportionally inside this 1480 by 780 area with padding, without clipping controls, cropping, or overflow.
- Content: One headline and three short callouts for narrow goal, test command, and normal granularity.

## s18 — `s18_quick_progress`

- Visual type: Screenshot.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Screenshot status: New GUI capture required; capture the same sanitized quick job after completion, with its latest worker result and successful target-checkout validation visible.
- Reserved image area: Left 140, top 210, right 1780, bottom 990 on the 1920 by 1080 slide; contain the complete capture proportionally inside this 1640 by 780 area with padding, without cropping or overflow.
- Content: One headline and three short callouts for current task, worker result, and final validation.

## s19 — `s19_spec_overview`

- Visual type: Screenshot.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Screenshot status: Existing source file `docs/images/specification-overview.png`; show this one screenshot without combining it with other specification captures.
- Reserved image area: Left 140, top 210, right 1780, bottom 990 on the 1920 by 1080 slide; contain the full screenshot proportionally inside this 1640 by 780 area with padding, without cropping or overflow.
- Content: One headline and three short labels for outcome, boundaries, and assumptions.

## s20 — `s20_spec_requirements`

- Visual type: Screenshot.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Screenshot status: Existing source file `docs/images/specification-requirements.png`; show this one screenshot without combining it with the requirement-dialog capture.
- Reserved image area: Left 140, top 210, right 1780, bottom 990 on the 1920 by 1080 slide; contain the full screenshot proportionally inside this 1640 by 780 area with padding, without cropping or overflow.
- Content: One headline and three short callouts for identifier, acceptance criterion, and linked verification.

## s21 — `s21_code_analysis`

- Visual type: Generated diagram.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Content: Repository flowing through diagnosis and focused change to a passing test, with three small example outcome labels.
- Simplicity: One process diagram, one headline, and no code listing or terminal wall.

## s22 — `s22_closing`

- Visual type: Generated diagram.
- Background: White.
- Branding: University of Vienna logo in the upper right corner.
- Content: Three simple paths labeled direct LLM, AI-Loop, and external LLM repair, followed by university email, GitHub repository, and `Robimo.at` as the closing line.
- Simplicity: One three-path diagram, one headline, and three short contact lines.

## Screenshot inventory

- Existing today: `docs/images/ai-loop-gui.png`, `docs/images/specification-choices.png`, `docs/images/specification-empty-new.png`, `docs/images/specification-field-help.png`, `docs/images/specification-overview-more-fields.png`, `docs/images/specification-overview.png`, `docs/images/specification-process-help.png`, `docs/images/specification-requirement-dialog.png`, `docs/images/specification-requirements.png`, `docs/images/specification-review.png`, and `docs/images/specification-scope.png`.
- New captures still required: Jobs list with Status; Plan; Task with Controller tab visible; Worker with Details tab visible; Logs with supervision toolbar; provider authentication or repair dialog; filled quick-job form; completed quick-job result with target validation.
- GUI-tour screenshot slides: s09 through s16, for a total of eight.
