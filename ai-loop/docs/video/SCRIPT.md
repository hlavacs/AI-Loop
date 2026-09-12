# AI-Loop introduction video script

Target pace: 145 spoken words per minute. Word counts cover narration only; timings are rounded to the nearest second.

ElevenLabs voice: `Helmut Lecture 2` (`T22wMY2gj3hkNGpCJOwd`). Availability was confirmed on 12 September
2026 with the configured ElevenLabs MCP connector through OAuth, using `creative_list_voices`. No audio was
generated during this check.

Repository metadata was checked before visual production on 12 September 2026. The Git origin proves the literal
repository URL as `https://github.com/hlavacs/AI-Loop.git`. The application window title in `ai_loop_gui.py` proves
the affiliation and website used in the narration and visuals.

## 1. Introduction and about Helmut

Estimated duration: 0:43. Word count: 104.

Hello, I am Helmut Hlavacs, and this is a short introduction to AI-Loop. I am affiliated with the University of
Vienna and Robimo GmbH in Vienna, Austria, and my website is robimo dot a t. If you have a question, an idea, or feedback, email me at
helmut dot hlavacs at gmail dot com. You will also find the AI-Loop GitHub repository with this video, so you can
inspect the project and its documentation yourself. In the next few minutes, I will explain the problem AI-Loop
addresses, the mental model behind it, and the main ways to start and supervise a job.

## 2. What AI-Loop is for

Estimated duration: 0:52. Word count: 125.

Coding agents are effective on focused changes, but larger jobs can cross many files and require repeated rounds of
implementation, tests, and review. A chat can run out of context or stop at a usage limit before the repository is
ready. AI-Loop turns that work into a persistent job. You provide a repository, a goal, and preferably a command
that can check the result. The useful mental model is a supervised development loop with durable memory. The model
does not need to finish everything in one conversation. Plans, tasks, decisions, results, progress, and terminal
state are stored, so work can pause and continue. It is best suited to clear goals whose results can be checked;
unclear requirements and decisions needing human authority still need you.

## 3. How the controller and worker loop works

Estimated duration: 0:52. Word count: 126.

Each active job normally has a controller, a worker, and a watcher. The controller creates the immutable overall
plan, turns it into concrete tasks, and reviews each result. The worker claims a task, edits the isolated Git
worktree, and runs the validation command. The controller then decides whether acceptance is met, more work is
needed, or human input is required. SQLite keeps the durable job state, while Redis Streams coordinates the
processes. The watcher observes terminal events, email replies, and scheduled status updates. If a model reports a
token limit with a reset time, AI-Loop records a waiting state and retries after replenishment. Successful work is
promoted only when paths do not conflict, and validation runs again in the target checkout before the job becomes
done.

## 4. Email feedback

Estimated duration: 0:39. Word count: 95.

Email support lets a long job report back without requiring the GUI to stay in front of you. When mail is
configured, AI-Loop sends a start message, a status message every twelve hours for an active job, and a notification
when the job finishes or needs attention. The messages include practical status such as progress, the current task,
and an estimate. You can reply in the same thread with a command. An accepted reply becomes a durable job
constraint, and if the job is waiting for human input, that reply resumes the same job automatically.

## 5. The GUI

Estimated duration: 0:43. Word count: 103.

The Tkinter GUI combines job creation and supervision. On the left, you select the repository, goal, validation
command, controller and worker, models, task granularity, and worktree options. The job list underneath shows durable
jobs and their status. On the right, tabs expose the immutable plan, current task, plain-language status, controller
messages, worker reports, diagnostic details, and logs. Toolbar actions refresh, stop, resume, or finish work sooner.
Finish Soon switches remaining work to coarse tasks without weakening tests or acceptance criteria; Finish Early
stops immediately and preserves resumable progress. The GUI also exposes assisted sign-in and repair workflows when
a selected provider needs attention.

## 6. A simple quick job

Estimated duration: 0:48. Word count: 116.

For a quick example, imagine a repository with a failing test and a clear goal: diagnose the failure, repair it, and
make the test suite pass. In Create Job, choose the repository, enter that goal, and provide the test command, or
leave automatic validation selected when its inferred command is appropriate. Choose the controller, worker, and
normal granularity, keep worktree isolation enabled, and select Create Job. The Plan tab shows the fixed four-part
plan. As work proceeds, use Task for the current instructions, Worker for recent results and changed files, and Logs
for raw process output. The loop can produce another task after review. When acceptance is met, promotion and the
target validation complete the job.

## 7. Specification details

Estimated duration: 0:37. Word count: 90.

For explicit contracts, use Specification. It records results, boundaries, user journeys,
requirements, risks, design choices, and proof of completion. Eight tabs cover
Overview, Scope, Use Cases, Requirements, Risks, Verification, Choices, and Review. Give requirements stable
identifiers and measurable acceptance criteria, and link each to a verification case. Review is the checklist;
Test specification performs a read-only holistic check. Save Draft, optionally Analyze, resolve findings and
blocking choices, Submit for Review, Approve, then Start Implementation. Approval pins the version. The
controller declares done only after linked verification proves every blocking gate.

## 8. Code analysis

Estimated duration: 0:38. Word count: 91.

Code analysis fits the same model. A goal can ask the loop to diagnose and repair a failing build, add coverage and
fix the problems that coverage exposes, or carry out a checked refactor or migration. The important part is to turn
analysis into observable acceptance: name the repository, state the desired outcome, and select a validation command
that exercises it. During the run, the Controller tab explains review decisions, the Worker tab reports tests and
changed files, and Details and Logs retain the deeper evidence needed to understand what happened.

## 9. Direct LLM use and external repair help

Estimated duration: 0:41. Word count: 100.

For a focused change, asking a coding model directly may be enough. AI-Loop helps when work needs durable state,
reviewed tasks, validation, or unattended continuation. Codex, Claude, and Gemini-compatible command-line tools can
serve as controller or worker, letting review and implementation use different models. When a provider needs help,
the GUI's Fix binary and Fix It actions run a command-line tool as a repair helper and resume after success.
Promotion or target validation failures can enter multi-provider recovery. Whichever route, keep the goal clear and
testable. Please send your experience and suggestions
to helmut dot hlavacs at gmail dot com.

## Timing summary

| Section | Words | Estimated duration |
| --- | ---: | ---: |
| 1. Introduction and about Helmut | 104 | 0:43 |
| 2. What AI-Loop is for | 125 | 0:52 |
| 3. How the controller and worker loop works | 126 | 0:52 |
| 4. Email feedback | 95 | 0:39 |
| 5. The GUI | 103 | 0:43 |
| 6. A simple quick job | 116 | 0:48 |
| 7. Specification details | 90 | 0:37 |
| 8. Code analysis | 91 | 0:38 |
| 9. Direct LLM use and external repair help | 100 | 0:41 |
| **Total** | **950** | **6:33** |
