# Narration

<!-- Spoken word count: 1795. -->

## Slide 01

Hello, I am Helmut Hlavacs from the University of Vienna. This is AI-Loop, a way to run substantial coding-agent work as a persistent, checked process. Instead of hoping that one long conversation reaches the finish line, AI-Loop repeats a clear cycle: plan a bounded step, implement it, validate the result, and continue. I will explain that model and then walk through the complete flow on screen.

## Slide 02

I am a professor in the Faculty of Computer Science at the University of Vienna, where I lead the research group for Education, Didactics and Entertainment Computing. AI-Loop is open source, and you can find my university web site, my university e-mail address, and the project's GitHub repository listed here on the slide.

## Slide 03

Coding agents are very effective at focused changes. The difficulty grows when a goal spans many files, multiple tests, and repeated review. A session may lose context or reach a usage limit before the repository is ready. AI-Loop is for that larger shape of work: features, migrations, repairs, coverage campaigns, and other jobs that benefit from durable progress and an objective validation command.

## Slide 04

You give AI-Loop three things: a repository, the outcome you want, and a command that can check success. A controller turns the outcome into bounded tasks. A worker edits an isolated worktree and runs the checks. Evidence returns to the controller, which either asks for another step or declares completion. The loop stops in one of three explicit ways: done, waiting for human input, or safely stopped with its work preserved.

## Slide 05

The useful mental model is a shared notebook that does not disappear when one model call ends. It records the overall plan, current and completed tasks, individual runs, controller decisions, validation evidence, and terminal state. The controller and worker read different pages, but they act on the same durable job. A watcher supervises the processes. The Git worktree contains the actual edits. If execution pauses, the notebook and worktree are still there when you resume.

## Slide 06

There are three active roles. The controller plans, delegates, and reviews. The worker makes repository changes and reports concrete evidence. The watcher tracks health, token waits, notifications, and completion. Redis Streams carries the messages between processes. SQLite stores the durable history. Git provides the isolated worktree and later promotion. This separation matters: implementation is not allowed to grade itself, and a process restart does not erase the record of what already happened.

## Slide 07

A job begins with creation and an immutable overall plan. The controller queues a task; the worker implements it; then the controller reviews the report. That cycle can repeat many times. A token limit moves the job into a waiting state until capacity returns. Missing credentials or a product decision move it to human needed. After approval, AI-Loop promotes the work and validates the target checkout. Only that final checked state becomes done. Every pause can resume the same job.

## Slide 08

The graphical interface puts the whole operation in one window. Across the top are refresh, stop, finish, resume, job actions, and system controls. The left side creates jobs and lists durable jobs. The right side explains whichever job is selected. Notice that the text is operational rather than decorative: state, progress, active roles, and the current task are all visible. The top-level tabs also expose specifications, project analysis, and a focused AI-Loop assistant.

## Slide 09

The Create Job panel begins with the repository and a plain-language goal. The Test field supplies a command, or auto lets AI-Loop infer one. Controller and worker are independent choices, including optional model overrides. Base reference, iteration limit, and task granularity define the run. Worktree isolation is the safe default. Parallel execution and sandbox bypass are explicit opt-ins. A regular Create Job starts the full workflow; Quick Job is convenient for a small, well-bounded repair.

## Slide 10

The Jobs table is the durable index. Each row shows its identifier, state, progress, controller, worker, task and run counts, and last update. Colors make active, waiting, failed, and completed work easy to scan. Selecting a row opens its Status page. Here AI-Loop explains the state in plain language, estimates remaining work, identifies both processes, and names the worker's current task. This is the first place to look when you return after an unattended run.

## Slide 11

The Plan tab shows the job's fixed, enumerated route to the requested outcome. A check mark means completed, the highlighted arrow means the current stage, and open circles are later stages. The controller may turn each stage into smaller tasks, but it cannot silently replace the overall promise. This example first reproduces the failure, then applies a focused correction, runs targeted and complete checks, and finally reviews the evidence in the clean target checkout.

## Slide 12

The Task tab turns one plan step into an auditable assignment. It names the current task, says what is happening, gives detailed instructions, and states exactly how completion will be checked. Here the worker must change only the comparison responsible for the boundary failure, preserve existing behavior, pass the targeted test, and pass all twelve tests. The validation command is visible at the bottom. The adjacent Controller tab retains the decisions that produced this assignment.

## Slide 13

The Worker tab shows execution from the implementation side. At the top are the selected worker, current task state, and immediate action. Below are results sent back to the controller, newest first. This first result is diagnostic: no file changed, one comparison was identified, and validation still reports one failed test and eleven passing tests. That failure is useful evidence, not a hidden error. The Details tab keeps lower-level run and process information available when diagnosis needs it.

## Slide 14

Logs provide the chronological process view: task queued, worker started, validation invoked, result recorded, and controller review requested. The controls preserve human authority. Stop halts processes without deleting history. Finish Soon asks the controller to use coarser remaining work while keeping acceptance quality. Finish Early stops immediately and preserves progress. Job Actions includes status explanation, waiting and notification tools, provider sign-in, and same-job resume. You can intervene without throwing away the investigation.

## Slide 15

When automation cannot continue safely, AI-Loop says so directly. In this example, provider sign-in is required. The dialog records the reason and confirms that the worktree is preserved. The user may authenticate and resume, or reply through the configured job email with a different command. The important behavior is continuity: repair the tool or provide the missing decision, verify that it is available, and continue the same durable job rather than starting from an empty conversation.

## Slide 16

Now let us follow one complete example. The new project is a tiny order-totals package. Its rule is simple: orders of one hundred or more receive a discount. The repository already contains the function and twelve tests, but the boundary case is wrong. The user's first check is python dash m pytest dash q, and the output is one failed, eleven passed. The desired outcome is not a rewrite; it is a minimal diagnosis and a proved correction.

## Slide 17

In AI-Loop, the first input is the repository location. The folder chooser places slash tmp slash ai dash loop dash demo slash one dash failing dash test in the Repo field. The second input is the goal: diagnose the failure, make the smallest correct repair, and make the test suite pass. This sentence describes an outcome and a constraint. It does not guess the bug, so the controller must first collect evidence before authorizing a change.

## Slide 18

Next come the remaining settings. Input three is the exact validation command, python dash m pytest dash q. Input four selects Claude as controller; input five selects Codex as worker. Input six keeps the base at HEAD. Input seven limits the example to twelve iterations. Input eight uses normal granularity. Input nine keeps worktree isolation on while parallel execution and sandbox bypass remain off. Optional model fields are intentionally empty, so each command-line tool uses its configured default.

## Slide 19

The tenth and final user input is clicking Quick Job. That action creates durable records before model work begins: a job identifier, an isolated worktree, the selected roles, the goal, and the validation command. The new row appears immediately in the Jobs table with planning state and zero percent progress. Then the controller process starts. From this point the user can watch, close the interface, or leave it unattended; the job is no longer dependent on this window staying open.

## Slide 20

The controller's first output is the four-part plan. First, reproduce the single failing test and identify its cause. Second, apply the smallest focused correction. Third, run the targeted test and then the complete suite. Fourth, review the evidence and validate the clean target checkout. The plan is visible before implementation progresses. In this frame, diagnosis is complete and the correction is current, so we can see both history and the exact next stage.

## Slide 21

The next output is a bounded worker task. Its goal is to correct the boundary comparison and prove the repair. The instructions allow changing only the responsible comparison and require all previously passing cases to remain unchanged. Completion has two observable conditions: the boundary test passes, and all twelve tests pass without warnings. Finally, the task repeats the validation command. The worker therefore receives not just a request, but scope, constraints, and a definition of done.

## Slide 22

The worker runs the task in the isolated worktree and reports back. The earlier diagnostic run identified one comparison without editing files, and its test output remained one failed and eleven passed. The controller uses that evidence to authorize the focused correction. After the edit, the same command runs again. This report-and-review boundary is the heart of AI-Loop: each next action is based on preserved results, and validation output remains visible instead of being reduced to an unsupported claim.

## Slide 23

Here is the final output. The job row is done at one hundred percent. The worker reports the repaired inclusive boundary check, with two additions and one deletion in src slash totals dot py. Validation passed in the worktree. AI-Loop then promoted the result and ran the same command in the target checkout, where all twelve tests passed. We can account for the input, the plan, the task, the changed file, and both layers of validation from one durable record.

## Slide 24

Use a model directly when one focused question or edit is enough. Use AI-Loop when work benefits from persistence, separate review, repeated checks, safe pauses, or unattended continuation. If a provider tool breaks, use the repair path and then resume the preserved job. The project, my university email, and my personal page are on screen. Robimo is an AI-tooling service provider. Thank you for watching.
