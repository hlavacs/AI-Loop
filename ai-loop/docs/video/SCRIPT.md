# AI-Loop introduction video script, version 2

Target pace: 150 spoken words per minute. Word counts cover narration only. The later audio-production task must use the ElevenLabs voice `Helmut Lecture 2` through the configured OAuth connector.

## s01 — Title

Slide ID: `s01_title`

Narration:

Hello, I am Helmut Lawatsch from the University of Vienna. Welcome to this introduction to AI-Loop, a tool for persistent and supervised work with coding agents. In the next few minutes, I will show the idea behind it, how a job progresses, and how the graphical interface helps you start and follow the work.

Visual elements:

- Headline: AI-Loop
- Presenter name: Helmut Hlavacs
- Affiliation: University of Vienna
- Simple plan, implement, validate, continue loop

## s02 — About the presenter

Slide ID: `s02_presenter`

Narration:

I am a professor in the Faculty of Computer Science at the University of Vienna, where I lead the research group for Education, Didactics and Entertainment Computing. The university website is W W W dot univie dot A C dot at. My university email is helmut dot Lawatsch at univie dot A C dot at. The project is open source. Its repository is github dot com slash Lawatsch slash A I dash Loop. The exact addresses are shown on this slide so you can copy them.

Visual elements:

- Headline: About Helmut Hlavacs
- University website: `https://www.univie.ac.at/`
- University email: `helmut.hlavacs@univie.ac.at`
- GitHub repository: `https://github.com/hlavacs/AI-Loop`

## s03 — What AI-Loop is for

Slide ID: `s03_purpose`

Narration:

Coding agents are very effective on focused changes. Larger goals are harder. They may cross many files, require repeated implementation and review, or outlast one model context or quota window. AI-Loop is for those longer, testable repository jobs. It keeps the work moving across multiple agent calls while preserving progress, evidence, and decisions. You remain the owner of the goal and of choices that require human authority.

Visual elements:

- Headline: For work larger than one chat
- Single chat ending before completion
- Persistent job continuing through several agent calls
- Short labels: long-running, testable, supervised

## s04 — The basic idea

Slide ID: `s04_basic_idea`

Narration:

The basic idea is simple. Give AI-Loop a repository, a clear outcome, and a validation command. The system divides the outcome into bounded tasks. A worker implements one task, checks it, and reports evidence. A controller reviews that result and chooses the next step. This repeats until the acceptance conditions are met, the job needs a human decision, or continuing would no longer be useful.

Visual elements:

- Headline: One goal, checked in small steps
- Three inputs: repository, outcome, validation
- Circular controller, worker, evidence diagram
- Three exits: done, human input, stopped

## s05 — The mental model

Slide ID: `s05_mental_model`

Narration:

Think of AI-Loop as a small supervised software team with a shared notebook. The controller is the reviewer and planner. The worker is the implementer. The repository worktree is the workshop. Tests are the definition of observable progress. The notebook is durable state: plan, tasks, constraints, reports, decisions, and current status. Because that state survives individual conversations, the team can pause, resume, and continue without pretending that one prompt contains the whole project.

Visual elements:

- Headline: A supervised team with durable memory
- Controller, worker, worktree, and tests as four icons
- Shared notebook in the center
- Pause and resume arrows

## s06 — How it works: the actors

Slide ID: `s06_actors`

Narration:

Three processes normally cooperate on an active job. The controller creates the fixed overall plan, issues concrete tasks, and reviews results. The worker claims one task, edits an isolated Git worktree, and runs the requested checks. The watcher observes status, scheduled updates, and replies. SQLite stores durable job state. Redis Streams coordinates requests and events between the processes. The models can change between roles, but the job record remains the stable center.

Visual elements:

- Headline: Controller, worker, watcher
- Three-role diagram around a durable job record
- Small SQLite and Redis labels
- Isolated worktree icon beside the worker

## s07 — How it works: the lifecycle

Slide ID: `s07_lifecycle`

Narration:

A job starts with planning, then moves through queued and implementing states as tasks are claimed and reviewed. If a model reaches a known token reset time, AI-Loop can wait and retry. If a real decision is missing, the job enters human needed instead of guessing. On success, safe changes are promoted from the worktree. Validation runs again in the target checkout, and only then does the durable state become done.

Visual elements:

- Headline: A job has an explicit lifecycle
- Linear state path from planning to done
- Side branches for waiting and human input
- Promotion and final validation gate

## s08 — Email feedback

Slide ID: `s08_email`

Narration:

AI-Loop can keep you informed by email while the interface is closed or in the background. With mail configured, it sends a message when a job starts, a status update every twelve hours while work is active, and a notification when the job finishes or needs attention. The status includes progress, current task, recent activity, and an estimate. You can reply in the same thread with a command. An accepted reply becomes a durable constraint and can resume a human-blocked job.

Visual elements:

- Headline: The loop reports back
- Simple four-message email thread
- Start, twelve-hour status, attention, completion labels
- Reply becomes a job constraint arrow

## s09 — GUI overview

Slide ID: `s09_gui_overview`

Narration:

Now let us tour the graphical interface. The main window has two broad areas. On the left are job creation controls and the durable list of jobs. On the right is the selected job's information, organized into tabs. A compact toolbar across the top holds the main supervision actions. This overview is enough to understand the layout before we look at individual views.

Visual elements:

- Headline: One window for creating and supervising jobs
- Full application screenshot
- Three small callouts: create, job list, inspect

## s10 — Create Job view

Slide ID: `s10_gui_create`

Narration:

The Create Job area begins with the target repository and the overall goal. Below that, you can provide a validation command or use automatic detection. You choose controller and worker tools, their models, task granularity, and worktree behavior. These options define how the loop will operate. For a first run, a precise goal, a reliable test command, normal granularity, and worktree isolation are sensible defaults.

Visual elements:

- Headline: Define the job
- Create Job screenshot
- Callouts: goal, validation, roles, isolation

## s11 — Jobs list and status

Slide ID: `s11_gui_jobs`

Narration:

The Jobs list is the navigation point for durable work. Each row identifies a job and its current state. Selecting a row loads that job on the right. The Status view summarizes progress in plain language, including what is happening now and whether attention is needed. You do not have to infer state from raw logs, although those logs remain available when you need deeper evidence.

Visual elements:

- Headline: Find the job and read its state
- Jobs list with Status tab screenshot
- Callouts: selected job, state, progress summary

## s12 — Plan view

Slide ID: `s12_gui_plan`

Narration:

The Plan tab shows the stable outline for the whole job. It is intentionally broader than a worker task. The controller uses it to preserve direction while issuing smaller pieces of work. Reading this tab answers two questions: what complete result is the loop pursuing, and how is that result divided? Because the plan is retained with the job, later reviews have a consistent reference point.

Visual elements:

- Headline: The plan preserves direction
- Plan tab screenshot
- Callouts: overall outcome, stages, acceptance

## s13 — Task and Controller views

Slide ID: `s13_gui_task_controller`

Narration:

The Task view contains the exact bounded assignment currently given to the worker. It should be specific enough to implement and verify. The Controller view records review decisions around that work: whether acceptance was met, why another task is needed, or why the job must wait. Together these views separate instructions from judgment. That separation makes a long run easier to audit than one continuous conversation.

Visual elements:

- Headline: Instructions and review stay separate
- Task tab screenshot with Controller tab visible
- Callouts: current assignment, acceptance, next decision

## s14 — Worker and Details views

Slide ID: `s14_gui_worker`

Narration:

The Worker tab shows the implementation report for recent work. It names the outcome, changed files, and checks that were run. The Details view exposes additional structured information about the job when the summary is not enough. These views are especially useful during code analysis: you can see the claimed diagnosis and then inspect the concrete evidence supporting it, without overloading the main status display.

Visual elements:

- Headline: See what changed and how it was checked
- Worker tab screenshot with Details tab visible
- Callouts: result, changed files, validation evidence

## s15 — Logs and supervision controls

Slide ID: `s15_gui_logs`

Narration:

The Logs tab contains raw process output for diagnosis. The toolbar provides refresh, stop, resume, Finish Soon, and Finish Early actions. Finish Soon asks the controller to group remaining work more coarsely while keeping tests and acceptance intact. Finish Early stops promptly and preserves resumable progress. These are supervision controls, not substitutes for a clear goal. Most of the time, Status and Worker are easier to read than Logs.

Visual elements:

- Headline: Inspect deeply or change course
- Logs tab and toolbar screenshot
- Callouts: logs, resume, finish soon, finish early

## s16 — Authentication and repair view

Slide ID: `s16_gui_repair`

Narration:

Provider tools sometimes need sign-in or local repair. When AI-Loop detects that situation, the interface can present assisted actions such as signing in, fixing a binary, or invoking Fix It. After a successful repair, the same durable job can resume. The important point on this screen is continuity: authentication trouble does not require reconstructing the goal, plan, and completed work in a fresh chat.

Visual elements:

- Headline: Repair the tool, keep the job
- Authentication or repair dialog screenshot
- Callouts: problem, assisted action, resume same job

## s17 — A quick-job example

Slide ID: `s17_quick_job`

Narration:

Here is a simple quick job. Imagine a small repository with one failing test. Select that repository and enter this goal: diagnose the failure, make the smallest correct repair, and make the test suite pass. Set the validation command to the project's test command, keep normal granularity and an isolated worktree, then create the job. The screenshot shows a deliberately short contract. The outcome is observable, the scope is narrow, and success can be checked automatically.

Visual elements:

- Headline: Quick job: repair one failing test
- Filled Create Job screenshot
- Callouts: narrow goal, test command, normal granularity

## s18 — Quick-job progress

Slide ID: `s18_quick_progress`

Narration:

After creation, the plan appears and the first task is queued. The worker reproduces the failure, inspects the relevant code, applies a focused change, and runs the test. Its report returns to the controller. If the evidence is incomplete, another task follows. If acceptance is met, promotion and target-checkout validation finish the job. On this screen, the useful signals are the current task, latest worker result, and final validation state.

Visual elements:

- Headline: Follow evidence to completion
- Completed quick-job screenshot
- Callouts: current task, worker result, final validation

## s19 — Specification overview

Slide ID: `s19_spec_overview`

Narration:

For larger or riskier work, the Specification window builds a stronger contract before implementation. Its tabs cover overview, scope, use cases, requirements, risks, verification, choices, and review. Start with the desired result and explicit boundaries. Record assumptions and dependencies instead of leaving them implicit. The point is not to produce a large document. It is to give the controller stable, reviewable facts that remain useful throughout the job.

Visual elements:

- Headline: Turn a goal into a testable contract
- Specification Overview screenshot
- Three short labels: outcome, boundaries, assumptions

## s20 — Specification requirements and proof

Slide ID: `s20_spec_requirements`

Narration:

Requirements should have stable identifiers and measurable acceptance criteria. Link each important requirement to a verification case that names the method, expected result, and evidence. Risks record what might fail and how it will be reduced. Choices capture decisions that should not be guessed by an agent. The Review tab gathers the blocking checks. You can save a draft, analyze it, resolve findings, submit it, approve it, and then start implementation with a pinned specification version.

Visual elements:

- Headline: Connect requirements to proof
- Specification Requirements screenshot
- Callouts: identifier, acceptance, linked verification

## s21 — Code analysis

Slide ID: `s21_code_analysis`

Narration:

Code analysis works best when it leads to a checked outcome. You might ask AI-Loop to diagnose a failing build, find the cause of a regression, add coverage and repair what the new tests expose, or prepare a carefully verified migration. State what must be true afterward and choose a validation command that can demonstrate it. The controller reviews the reasoning, while worker reports, details, and logs retain the file changes and test evidence behind the conclusion.

Visual elements:

- Headline: Analysis should end in evidence
- Repository, diagnosis, change, test diagram
- Example outcomes: regression fixed, coverage added, migration checked

## s22 — Direct models, external fixing, and closing

Slide ID: `s22_closing`

Narration:

For one focused change, asking an L L M directly may be the fastest approach. Use AI-Loop when the work benefits from durable state, separate review, repeated validation, or unattended continuation. Controller and worker roles can use different supported command-line models. You can also use an external L L M for fixing a provider tool or diagnosing a blocked run, then return to the preserved job. AI-Loop is open source, and feedback is welcome at my university email. Thank you for watching. For related work, visit Robimo dot at.

Visual elements:

- Headline: Choose the right level of support
- Direct LLM, AI-Loop, and external repair paths
- University email and GitHub repository
- Closing line: Robimo.at

## Timing summary

Narration word count: 1,549 words.

Estimated duration at 150 spoken words per minute: 10 minutes 20 seconds.
