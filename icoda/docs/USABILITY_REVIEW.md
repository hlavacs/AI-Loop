# ICODA — usability and documentation review

Date: 2026-09-15. Basis: the current `develop` branch (README, HANDBOOK, docs/, the 32 handbook screenshots, the step panel and main window code) plus the problems that came up while using the app on the Mac over the last week.

## Short verdict

ICODA has a lot of features now: two languages, class view, mind map, coverage, issues, an implementation queue with scopes and batches, auto-approve, a verify gate, a 1,008-line handbook with screenshots and a PDF. What it does not have yet is a smooth first hour. A new user (or Helmut after a week away) has to know the right order of about eight manual steps, gets no feedback while the tool is busy, and looks at a bottom panel with twelve buttons of which most are grey. The documentation is complete but written for the maintainer, not for the person who wants to build a small program with it this afternoon.

The thing most missing is not a feature. It is a guided path from "New Project" to the first approved step, with the app telling the user what to do next and what it is doing right now.

## Usability — what is missing

### 1. A guided first run

Today the first run goes: New Project → fill six specification pages → Save → read the build instructions → run cmake by hand in a terminal → File ▸ Reload → maybe Project ▸ Choose libclang → restart ICODA → pick Binary and Model in the LLM panel → Propose. Every step is documented, but nothing in the app leads from one to the next. After Save the user sees an empty diagram and has to remember what the handbook said.

Missing: a "Next step" hint in the status line or a small checklist panel ("1 Specification saved ✓ · 2 Build the skeleton … · 3 Reload · 4 Choose the agent · 5 Propose"), a Build button that runs the documented cmake commands itself, and loading the libclang library without a restart (or at least a dialog that offers to restart). The demo in `scratch/demo` still has no completed Propose → Approve run in its log; that is a sign the path is too long.

### 2. Feedback while the app is working

`set_busy` only greys the buttons. There is no progress bar, no "calling Claude Code, attempt 2 of 3", no spinner, and no way to cancel. A Claude call can take a minute; building a C++ skeleton longer. During that time the window looks dead. This is almost certainly behind the report "when I reopen the demo the whole app blocks": the log shows only normal opens, so either the Tk thread is really blocked by some synchronous work (parsing, git, libclang) or it only looks blocked. Without an indicator the two cannot be told apart.

Missing: a busy indicator with the current activity in words, a Cancel button for agent calls, and a watchdog that writes every thread's stack to `icoda.log` when the Tk thread has not answered for five seconds. The watchdog code exists in my workspace (`icoda_gui/tasks.Watchdog`, tested) but is not installed against the current, much larger `icoda.py`.

### 3. The step panel

The bottom panel holds twelve action buttons (Propose approach, Approve approach, Propose, Approve architecture, Approve, Confirm signatures, Reject…, Adapt…, Rebuild, Open worktree, Undo last step, Commit manual edits) plus Phase, Request, Max entities, Batch size, Scope, Grouping, Auto-approve and a queue label. At any moment most buttons are grey and the user has to guess why. There are no tooltips on this panel (the specification editor has them; the step panel has none).

Missing: show only the buttons that belong to the current phase instead of greying them; put the rare ones (Open worktree, Commit manual edits, Rebuild) into a menu; one sentence above the buttons that says what the user can do now ("The approach is approved. Press Propose to get the code for R-3."); tooltips that explain each button in one line, including why it is disabled.

### 4. Messages that sound like errors but are not

Examples from the screenshots and the code: "Auto-approve stopped — there is no current implementation proposal to approve automatically", "Step 3: no usable proposal — the proposal does not build", Mind Map nodes labelled "step unknown". The first is a normal state, the third is a missing value shown as text. The Issues view on the sample project reports "159 issues · 2 errors · 157 warnings"; with that much noise nobody reads the two errors.

Missing: neutral wording for normal states, hide or shorten labels with unknown values, and an Issues view that shows errors first and folds warnings by rule with a count.

### 5. Small things that add up

No keyboard shortcuts at all (no Ctrl-S in the editor, no Enter for Propose, no shortcut for Reload). Undo is a `git revert --no-commit`, which the user does not learn from the UI; a confirmation that says what will happen ("This reverts commit 'icoda(architecture) step 4: …' and keeps the change in the worktree") would help. Hidden Code Profile limits (max methods and so on) can only be changed in the JSON file. `test_command` has no field in the GUI. Only Claude Code and Codex are enabled; the Gemini template is there but disabled, and the LLM panel does not say so.

## Documentation — what is missing

### 1. A split between "use it" and "maintain it"

There are about 7,450 lines of documentation: README 251, HANDBOOK 1,008, EVOLUTION 514, ICODA_PLAN 271,
GAP_ANALYSIS 254, SIMULATION 284, RELEASE_MATRIX 120, VERIFY_LOG 4,746. Most of it is evidence and history for the
maintainer (verify gate, artifacts, simulation logs). The README front page links a 7 MB PDF as the first thing to
open. A user who wants to build a small program has to find the three relevant pages inside the handbook.

Missing: a two-page **Getting started** (install, first project, first step, what to do when the proposal does not build) that stands on its own; a clear line in the README saying "Users: read Getting started. Maintainers: read the rest"; the verification material moved out of the top-level README.

### 2. A tutorial with a real small project

The SIMULATION document proves the workflow works, but it is written as evidence, not as a lesson. A tutorial that builds one tiny program end to end — one use case, three requirements, five steps, what the user typed, what the agent answered, what was rejected and why — would teach more than the handbook's reference sections. The video script (`docs/video/SCRIPT.md`) is close to this and could become the tutorial text.

### 3. Troubleshooting and FAQ

The problems of the last week were all of the kind "it does not work and I do not know why": Claude Code returned an error (the prompt was swallowed by a flag), Save refused the use case (title cleared by Add), the dialog was too tall, the app seems to block. None of these has an entry anywhere. Missing: a Troubleshooting page with the real cases (agent CLI not found or not logged in, libclang not found, compile database missing, "dirty tree" refused, proposal does not build three times, app looks frozen — look in `.icoda/icoda.log`), and where the log file is.

### 4. Platform honesty

The release matrix qualifies Linux only. The primary user works on macOS, and the macOS notes (Homebrew LLVM for modules, Apple Clang limits) are scattered across README and handbook. Missing: a macOS section in the release matrix with what was actually tried, and one place that lists the macOS prerequisites in order.

### 5. In-app help

Nothing in the app points to the documentation: no Help menu, no "?" that opens the handbook section for the current panel, no About with the version. Since the user cannot copy text out of the terminal easily, a Help ▸ Open log file entry would also save time when reporting problems.

### 6. Documentation of what the tool sends

The handbook describes the protocol, but a user who wants to trust the tool needs to see the prompt that went out and the raw reply that came back, for the current step, in the app (a "Show prompt / Show reply" tab in the step panel). Related: the handbook does not explain how long a step may take or how many tokens a typical step uses.

## What to do first

1. Busy indicator with activity text, Cancel for agent calls, and the watchdog in `icoda.log`. This also settles the "app blocks" report.
2. A "next step" line above the step buttons, buttons shown only when they apply, tooltips on every button.
3. A two-page Getting started plus a Troubleshooting page; README pointing users there before anything else.
4. Build button and libclang loading without restart, so the first run has no terminal step.
5. Neutral status wording, Issues view with errors first and warnings folded.

Everything else (shortcuts, GUI for hidden profile fields and `test_command`, macOS qualification, tutorial from the video script, Help menu) can follow.

## What was done (same day)

Everything in the list above was implemented on 2026-09-15:

- **Feedback while working**: the step panel shows a moving bar and the current activity (`asking the agent for
  the next step (attempt 1 of 3)`, `building the proposal`, …); agent calls, builds and tests have a **Cancel**
  button (`process.cancel_running`, `steps.StepCancelled`); the analysis shows a bar in the status line and keeps
  the panel busy; a watchdog (`icoda_gui/tasks.Watchdog`) writes every thread's stack to `.icoda/icoda.log` when
  the Tk thread does not answer for five seconds; opening a project logs `opening:`, `showing:` and `shown:` lines.
- **Step panel**: a hint sentence above the buttons (`icoda_core/guidance.py`, pure and tested) says what to do
  next in every state; only the phase's buttons are shown; **Confirm signatures** appears only when needed;
  **Rebuild**, **Open worktree** and **Commit manual edits** moved into **More…**; every button and control has a
  tooltip that also says why a button is grey; **Prompt** and **Reply** tabs show the exchange with the agent;
  auto-approve refusals read `Auto-approve paused: … Decide yourself.` in the hint instead of an error-like title;
  the Undo confirmation names the step and explains the revert.
- **First run**: saving a new specification offers to build the skeleton; **Project ▸ Build** (⌘B / Ctrl+B)
  builds in the background and reloads; applying a libclang choice reloads the project instead of asking for a
  restart; **Project ▸ Test Command…** edits the gate command; the hidden Code Profile limits are editable.
- **Noise**: the Issues view lists errors first and folds warnings by rule; the Mind Map omits the step when it is
  unknown; the Binary field's tooltip and hint say which agents are not enabled yet.
- **Keyboard**: ⌘N/O/R/E/B/Return/Q (Control elsewhere); ⌘S and ⌘W in the specification editor.
- **Help menu**: Getting started, Tutorial, Handbook, Troubleshooting, Open Log File, About.
- **Documentation**: `docs/GETTING_STARTED.md`, `docs/TUTORIAL.md` (the simulation's formatter project),
  `docs/TROUBLESHOOTING.md`; the README sends users to them first and separates maintainer material; the
  handbook describes the new panel, menus and shortcuts; the release matrix has a macOS hands-on record.
- Also fixed on the way: `graph_filter.Graph` used a `MappingProxyType` default that Python 3.10 and 3.11 reject
  (`ValueError: mutable default … for field cluster_by_file`), so ICODA did not start on those versions.

Still open: a real Propose → Approve run on the Mac with Claude Code (the log will now show where time goes), the
verification gate on macOS, and regenerating the PDF edition of the handbook.
