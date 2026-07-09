# AI Loop System Guide

This document describes how the ai-loop system works end to end: job creation, task dispatch, controller review, worker execution, GUI behavior, persistence, and the controls that let you cut a job short when needed.

## Overview

ai-loop is a durable controller/worker loop built around:

- SQLite for jobs, tasks, runs, decisions, progress estimates, and events
- Redis Streams for activation and terminal notifications
- a controller process that plans, reviews, and decides whether to continue
- a worker process that edits the worktree and runs the job test command
- a watcher process that reports terminal outcomes
- a Tkinter GUI that exposes the same system state in a single window

The intended mode is job-scoped isolation. Each job gets its own controller, worker, watcher, PID directory, log directory, and usually its own Git worktree.

## Main Files

- `start_job.py`: job creation, worktree setup, and initial PLAN enqueue
- `claude_controller.py`: controller loop that asks for the next action and reviews completed work
- `codex_worker.py`: worker loop that executes tasks, runs tests, captures diffs, and queues REVIEW
- `watcher.py`: terminal notification consumer
- `ai_loop_gui.py`: Tkinter GUI for job creation, inspection, resuming, cleanup, and hibernation controls
- `ai_loop/db.py`: SQLite schema and helpers
- `ai_loop/config.py`: runtime configuration and environment variable handling
- `ai_loop/progress.py`: rough percent-complete and remaining-time estimates
- `ai_loop/queues.py`: Redis helpers
- `ai_loop/recovery.py`: automatic recovery for short-lived failures

## Configuration

Common environment variables:

- `AI_LOOP_DB`: path to the SQLite database
- `AI_LOOP_RUNS_DIR`: path for job worktrees
- `AI_LOOP_WORKER`: default worker for new jobs
- `AI_LOOP_CONTROLLER`: default controller for new jobs
- `AI_LOOP_TEST_CMD`: default validation command when a target repository does not define one
- `AI_LOOP_CODEX_MODEL`: optional Codex CLI model override
- `AI_LOOP_FABLE_MODEL`: optional Claude Fable model override
- `AI_LOOP_OPUS_MODEL`: optional Claude Opus model override
- `AI_LOOP_CONTROLLER_MODEL`: optional Claude controller model override
- `AI_LOOP_GEMINI_MODEL`: optional Gemini model override
- `CODEX_BIN`, `CLAUDE_BIN`, `GEMINI_BIN`: executable names or paths
- `CODEX_BYPASS_SANDBOX`: when true, the worker runs without sandbox restrictions
- `REDIS_URL`: Redis connection string

Model override variables are optional. Leave them blank to use the CLI default model behavior.

## Job Lifecycle

1. A user submits a job through `./ai_job.bash`, `python3 start_job.py`, or the GUI.
2. The job record is written to SQLite.
3. A Git worktree is created unless `--no-worktree` was requested.
4. The loop enqueues a `PLAN` request on `ai:claude:requests`.
5. The controller chooses a task sized for the selected worker.
6. The worker runs the task, captures output and the Git snapshot, then stores a run row.
7. The worker enqueues `REVIEW`.
8. The controller reviews the run and chooses one of `CONTINUE`, `REPAIR`, `DONE`, or `HUMAN_NEEDED`.
9. Terminal outcomes are published to Redis and reflected in SQLite.

The job status flow is typically `planning -> queued -> implementing -> queued -> ...`, with `fixing` used when the controller requests a repair task.

## Status Meaning

- `planning`: the controller is preparing the next task
- `queued`: a task exists and is waiting for the worker to pick it up
- `implementing`: the worker is running a normal task
- `fixing`: the worker is running a repair task requested by the controller
- `human_needed`: the loop is blocked on an operator decision or external dependency
- `dead`: an internal failure occurred that the loop could not recover from
- `done`: the job completed and, when possible, the successful changes were promoted back to the target repository

## Worker Behavior

The worker process does the following for each task:

- re-read the task row before execution
- launch the configured implementation CLI
- run the task test command after the edit step
- capture `git status`, changed files, diff stat, and diff content
- write a durable run row to SQLite
- queue a `REVIEW` request for the controller

Task text and file guidance are re-read from the current worktree state so the worker can see updated instructions while the job is still running.

## Controller Behavior

The controller is responsible for:

- choosing the next task scope
- translating a decision into a task row
- replacing stale test-acceptance language with the current job test command when needed
- deciding whether the job should continue, repair, stop, or ask the user for help
- finishing the job when the work is complete

If the controller chooses `REPAIR`, the job enters `fixing` while the repair task is queued or running.

## GUI Behavior

The Tkinter GUI shows:

- the job list with live progress estimates
- the selected job summary
- the live status explanation
- logs for controller, worker, or watcher
- task and run history
- resume controls for controller, worker, constraints, and acceptance criteria
- cleanup controls for worktrees and database state
- a macOS hibernation helper window

The GUI only rewrites text widgets when the new content actually differs from the existing content. That keeps the interface responsive and avoids unnecessary redraws.

Every interactive GUI element has hover help so the meaning of the button, field, or selector is visible on demand.

## Cutting Work Short

There are several ways to end earlier than the currently queued work would normally allow:

- `Finish Early` in the GUI stops the job and preserves the current state
- `Stop Job` pauses the running controller, worker, and watcher processes
- lowering `max_iterations` before resuming makes the job end sooner
- `Human Needed` can be used as a deliberate stop point when the remaining work should be reconsidered manually

## Files On Disk

Default locations:

- `./ai_loop.sqlite3`: durable job database
- `../ai-runs/<job_id>`: isolated worktree for the job
- `./run/jobs/<job_id>`: per-job PID files
- `./logs/jobs/<job_id>`: per-job controller, worker, and watcher logs

## Commands

Common commands:

```bash
./ai_job.bash /path/to/repo "Implement the requested feature."
./ai_check_job.bash
./ai_check_job.bash <job_id>
./ai_watch_job.bash
./ai_print_log.bash --job <job_id>
./ai_resume_job.bash <job_id>
./ai_delete_job.bash <job_id>
./ai_clear_db.bash --yes
./ai_reset_loop.bash --yes
```

## Troubleshooting

If a job appears stuck in `queued`, check the per-job logs first. The worker may still be waiting on a missing binary, an execution failure, or a delayed Redis handoff.

If the job enters `human_needed`, inspect the latest decision reason, task history, and logs before resuming. The GUI is usually the fastest way to do that because it shows all of the current state in one place.

If the target repository is changing while the job runs, keep an eye on the task history and the run output. The loop will re-read current guidance files, but it will not guess what changed outside the repository.
