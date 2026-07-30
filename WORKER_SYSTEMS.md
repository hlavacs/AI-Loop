# AI-Loop system architecture

This is the sole authoritative technical description of AI-Loop: components,
persistence, queues, lifecycle, planning, execution, estimates, recovery,
notifications, GUI synchronization, runtime bootstrap, and operational
boundaries.

## Design goals

AI-Loop is designed to make long development jobs durable and observable while keeping model vendors interchangeable.

The main invariants are:

1. SQLite is the authoritative state. Redis carries activation messages, not irreplaceable job data.
2. Every job has an immutable high-level plan and a configurable task granularity.
3. The controller decides; the worker edits and verifies.
4. Role program names are vendor-neutral: `controller.py` and `worker.py`.
5. A job/task state change is written before the corresponding external work proceeds.
6. Expected token replenishment waits are visible and self-resuming, not human-needed failures.
7. With authenticated mail enabled, job start, completion, and genuine unsolved blockers produce an email attempt and a durable notification event.
8. Successful worktree promotion never overwrites conflicting local target-checkout edits.
9. Machine-specific Python virtual environments are local runtime state and are never versioned.
10. An emailed command is accepted only from the configured notification address and only for its identified job.

## Component map

### `start_job.py`

Creates a job. It validates role and granularity choices, detects the test command, builds the static plan, snapshots dirty target-repository state in a pre-job commit, creates an isolated worktree unless disabled, copies the checkout overlay, initializes Redis consumer groups, starts per-job processes, enqueues `PLAN`, and attempts the job-start email.

### `controller.py`

Consumes `PLAN` and `REVIEW` requests. It selects the configured controller CLI, builds a schema-constrained prompt, validates the decision, stores work/time estimates, creates the next task, or terminates the job. On `DONE`, it promotes safe worktree changes to the original repository. It also handles controller token waits and terminal notification email.

### `worker.py`

Consumes task activations. It atomically changes the task from `queued` to `running` and the job to `implementing` or `fixing`, invokes the configured worker CLI, handles token waits, re-reads the current task test command, validates, captures a complete Git snapshot including untracked files, stores a run, and enqueues `REVIEW`.

### `watcher.py`

Observes `done`, `human`, and `dead` Redis streams and prints terminal payloads. A per-job watcher also sends a durable status email every 12 hours while its job remains active and polls for emailed commands when IMAP is configured. It exits for `done`/`dead`; after `human_needed` it remains alive until a command resumes the job or a manual resume replaces it.

### `ai_loop_gui.py`

Provides job creation, Goal File input, a Clear Goal action, compact independent
binary/model selectors for the controller and worker, granularity selection,
job/task status, immutable Plan display, wrapped logs, history, resume controls,
Finish Soon/Early, cleanup, Redis startup, and macOS hibernation controls.
Before creating a job, it verifies the selected provider CLIs and attempts npm
installation of a missing standard Codex, Claude, or Gemini executable.

### Library modules

- `ai_loop/config.py`: environment-backed immutable settings and role normalization.
- `ai_loop/db.py`: schema, migrations, JSON conversion, and state mutations.
- `ai_loop/email_commands.py`: trusted IMAP reply matching, command extraction, deduplication, and resume handling.
- `ai_loop/queues.py`: Redis connection, consumer groups, JSON validation, and stream I/O.
- `ai_loop/planning.py`: granularity validation, constraints, and static plan construction.
- `ai_loop/progress.py`: controller estimates with heuristic fallback and countdown ETA persistence.
- `ai_loop/token_wait.py`: token-limit detection, replenishment-time extraction, and bounded-interval waiting.
- `ai_loop/notifications.py`: startup SMTP/IMAP account checks and authenticated SMTP messages.
- `ai_loop/status_updates.py`: durable 12-hour scheduling and job progress assembly.
- `ai_loop/recovery.py`: one-at-a-time automatic repair attempt for internal controller/worker exceptions.

## Runtime bootstrap and shell entry points

`.venv/` and `.gui-venv/` are ignored machine-local directories. Neither may
be committed because a virtual environment contains interpreter links and
platform-specific installed files.

`ai_gui.bash` is the automatic GUI bootstrap path:

1. Source `ai_loop_python.bash` and select a runnable Python 3.10 or newer.
2. On macOS, avoid executing `/usr/bin/python3` when it is only the unavailable
   Command Line Tools stub.
3. Check Python, Tkinter, Git, and `redis-server`.
4. Attempt missing system-package installation with Homebrew, `apt-get`, `dnf`,
   or `pacman`.
5. If the selected Python cannot import `redis`, create `.gui-venv`, install
   `redis-py`, and restart `ai_loop_gui.py` with that interpreter.
6. If any automatic installation fails, print the underlying command error and
   the usual manual installation command.

At GUI job creation, the selected standard provider executable is checked
before a worktree or database job is created. A missing Codex, Claude, or Gemini
CLI is installed with its npm package. If npm is missing, the GUI first attempts
to install Node/npm using a supported system package manager. Custom executable
paths are never guessed or overwritten. Provider authentication remains an
interactive user responsibility.

The non-GUI launchers do not currently provide the same complete bootstrap:

- `ai_job.bash`, `ai_resume_job.bash`, `ai_delete_job.bash`,
  `ai_run_claude.bash`, `ai_run_codex.bash`, `ai_run_watcher.bash`,
  `ai_watch_job.bash`, and `ai_run_loop_proof.bash` select Python through
  `ai_loop_python.bash` and require that interpreter to import `redis`.
- `ai_check_job.bash`, `ai_print_log.bash`, `ai_clear_db.bash`,
  `ai_clear_log.bash`, and `ai_reset_loop.bash` invoke `python3` directly.
- The shared selector considers `.venv` and installed Python commands, but not
  the GUI-created `.gui-venv`. Therefore running the GUI does not currently
  bootstrap the non-GUI scripts on a fresh clone.

These differences are operational constraints, not intended data-model
semantics. A future consolidation should make every Python-using script select
the same supported local interpreter and dependency environment.

## Durable data model

The default database is `ai_loop.sqlite3`. Connections use WAL mode, foreign keys, and a busy timeout.

### `jobs`

One row per overall job. Important fields include:

- repository, worktree, branch, and base ref
- goal, constraints, acceptance criteria, and test command
- controller and worker choices
- `granularity`: `fine`, `normal`, or `coarse`
- `plan_json`: immutable high-level milestone list
- `finish_requested`: Finish Soon mode
- `estimated_completed_units`, `estimated_remaining_units`, and `estimated_remaining_seconds`
- `waiting_until`: UTC token-reset-plus-one-minute instant
- max iterations, history summary, status, and timestamps

Schema migration uses `ensure_column`, so opening an older database adds new fields without discarding jobs. Older jobs have an empty plan; the GUI explicitly labels that case rather than inventing history.

### `tasks`

One controller-created executable unit. It stores iteration, goal, constraints, acceptance, the job test command, creator, status, and timestamps.

Task statuses are normally `queued`, `running`, `waiting_tokens`, `completed`, `human_needed`, or `dead`.

### `runs`

One worker execution result. It stores worker/test return codes and output, Git status, diff stat, diff, changed paths, error, status, and start/finish times. Historical column names such as `codex_rc` remain for database compatibility even when another worker is selected.

### `decisions`

The validated controller response for each PLAN or REVIEW. It stores the action, reason, history summary, complete JSON, and task/run linkage.

### `events`

Append-only operational facts: creation, process launch, queueing, waits, runs, promotion, recovery, notification success/failure, cleanup, and terminal outcomes.

### `progress_estimates`

Stores the last displayed percent, time of progress, smoothed fallback rate, and predicted end. A new controller estimate invalidates the previous countdown row, establishing a new predicted end exactly once; GUI refreshes then count down toward it rather than restarting the same duration.

## Redis streams

Redis is an activation and notification layer:

| Stream | Payload field | Purpose |
| --- | --- | --- |
| `ai:claude:requests` | `request` | PLAN and REVIEW activation |
| `ai:codex:tasks` | `task` | Worker task activation |
| `ai:done` | `event` | Successful terminal event |
| `ai:human` | `event` | Genuine human-needed terminal event |
| `ai:dead` | `event` | Unrecoverable internal failure |

Names are retained for database/queue compatibility; role executables are vendor-neutral.

Every message is JSON round-trip checked. Per-job processes use groups suffixed with the job ID and ignore job-scoped messages belonging to other jobs. SQLite rows are always sufficient to inspect what Redis was meant to activate.

## Job creation sequence

1. Normalize repo, controller, worker, and granularity.
2. Infer or accept the test command.
3. Build granularity constraints.
4. Build and store a four-milestone static plan.
5. Create a pre-job snapshot commit if the target checkout is dirty.
6. Create `ai/<job-id>` and `../ai-runs/<job-id>` unless `--no-worktree` is selected.
7. Copy the dirty checkout overlay into the worktree.
8. Insert the `planning` job row and creation event.
9. Create job-scoped Redis groups.
10. Launch `controller.py`, `worker.py`, and `watcher.py` with per-job runtime/log directories.
11. Enqueue PLAN.
12. Attempt the threaded job-start email and store `email_started_sent`, `email_started_failed`, or `email_started_skipped`.

The static plan is deliberately high-level. It describes repository inspection, implementation of the goal, validation, and final acceptance review. It is stored at creation and never modified on resume or controller review.

## Controller decision contract

The controller must return JSON with:

- `action`: `CONTINUE`, `REPAIR`, `DONE`, or `HUMAN_NEEDED`
- `reason`
- `history_summary`
- `progress.completed_work_units`
- `progress.remaining_work_units`
- `progress.remaining_minutes`, or null only when time cannot be estimated
- `next_task` for CONTINUE and REPAIR

The JSON schema rejects extra properties and malformed task structures. If CLI output is syntactically invalid, the controller requests a bounded number of JSON remakes. Internal fallback HUMAN_NEEDED decisions receive a conservative default progress object before persistence.

The controller is explicitly told to avoid HUMAN_NEEDED when an automated diagnostic or safe repair exists. It should use REPAIR for fixable code, configuration, tool, path, build, or test problems.

## Granularity policy

Granularity belongs to the job, not the model.

### Fine

The controller creates narrow focused tasklets and splits at natural behavior/file-cluster boundaries. The worker stops at the explicit small acceptance boundary. This maximizes review frequency and controller control.

### Normal

The controller creates medium coherent tasks, grouping directly related discovery and implementation while separating independent features and risky migrations.

### Coarse

The controller minimizes round trips with substantial tasks that may combine related discovery, implementation, documentation, and verification. It splits only at architectural, dependency, or risk boundaries. The worker is told not to leave obvious in-scope follow-up tasklets.

All modes retain the same job goal, test command, acceptance criteria, maintainability expectations, and quality checks.

## Finish Soon and Finish Early

`Finish Soon` sets `finish_requested=1` and changes granularity to coarse. The next review is told to drop optional/speculative work, return DONE immediately if core acceptance is satisfied, or create at most one consolidated final task. It does not interrupt a worker in the middle of a safe run.

`Finish Early` stops processes immediately and marks the job human-needed with a preserved-progress explanation. It is resumable and intentionally does not claim that acceptance was met.

## Worker execution sequence

1. Read task and job.
2. In one transaction, set task `running` and job `implementing` or `fixing`.
3. Recompute referenced guidance paths from current goal/constraints/acceptance.
4. Build a granularity-specific prompt.
5. Run the selected CLI in the worktree.
6. If output contains a parseable token limit, enter the token wait flow and retry the same command later.
7. Re-read the task row so a corrected test command is honored.
8. Run validation.
9. Capture Git status, tracked diff, untracked-file diffs, changed paths, and outputs.
10. Insert the run and update task state.
11. Enqueue REVIEW, or emit a terminal event for a genuine worker-level human/dead failure.

The worker timeout is two hours for the implementation CLI and 30 minutes for
the task test command. Crash-prone target executables can be run through
`ai_run_crash_safe.bash`. That wrapper uses GNU `timeout` or `gtimeout` when
available and otherwise cannot enforce its requested wall-clock limit. On
macOS it runs targets through LLDB; LLDB authorization and targets that perform
an early `exec` can prevent the payload from completing.

## Live guidance refresh

Both roles extract file-like paths mentioned in the goal, constraints, and acceptance criteria. Paths must resolve inside the worktree; `..` escapes and unrelated absolute paths are rejected.

For PLAN/REVIEW, the controller receives current content, modification time, size, and truncation information. For worker tasks, existing guidance paths are listed and the worker is told to re-read them at task start and again before finalizing a long task that depends on them.

## Status model and stale-state prevention

Job statuses:

- `planning`: controller is preparing a task
- `queued`: a normal task exists and awaits worker pickup
- `implementing`: worker owns a normal running task
- `fixing`: a repair task is queued or running
- `waiting_tokens`: controller or worker is sleeping until a known replenishment time
- `done`: acceptance passed and completion/promotion handling finished
- `human_needed`: automation cannot safely resolve the next action
- `dead`: internal failure survived recovery

The worker's pickup transaction updates task and job together. GUI refresh also reconciles active rows from the authoritative latest task: a running normal task forces `implementing`, a running repair forces `fixing`, and a token-waiting task forces `waiting_tokens`. A genuinely queued task with no live worker is displayed as `queued / worker offline`. Expanded task rows are preserved while the GUI refreshes.

The GUI refresh interval is 1.5 seconds by default. The task child row uses the current task status and timestamp on every refresh.

## Progress and remaining-time estimates

Every controller decision estimates completed work units, remaining work units, and remaining minutes. Percent is calculated from work units and may reach 99% before DONE; it is no longer artificially capped at 85%. Completed units are monotonic.

The remaining duration becomes a predicted end time and counts down between decisions. If no controller estimate exists—especially for migrated old jobs—the prior run/task heuristic and smoothed observed progress rate are used as a fallback.

The GUI separates information into Plan, Task, Status, Controller, Worker, Details, and Logs tabs. Status shows percent complete, logical work estimates, remaining duration, process health, blockers, and solutions. Details contains the extensive database and runtime snapshot. All display text boxes are read-only, word-wrapped, and rewritten only when their generated content changes.

CLI status tools show percent and remaining time.

## Token exhaustion

`ai_loop/token_wait.py` recognizes usage/token/rate-limit, quota-exhausted, out-of-tokens, and too-many-requests language. It extracts:

- ISO date/time values, including timezone offsets
- relative hour/minute/second durations
- local clock reset times with optional AM/PM

The target instant always includes a one-minute safety margin. On a parseable limit:

1. Set job and, for worker waits, task to `waiting_tokens`.
2. Store UTC `waiting_until` and a `waiting_for_tokens` event.
3. Log remaining seconds at intervals no longer than 60 seconds.
4. At the target, clear `waiting_until`, restore `planning`, `implementing`, or `fixing`, and add `token_wait_finished`.
5. Retry the same controller request or worker task automatically.

No HUMAN_NEEDED event, popup, or email is emitted for this expected wait. A token failure without an extractable reset time follows normal unresolved-blocker handling.

## Email notifications and reply commands

### Outgoing messages

Terminal notification is attempted when:

- a job reaches `done`
- the controller or worker reaches a genuine `human_needed`
- a controller/worker exception becomes `dead`
- promotion fails and requires human conflict resolution

Job creation attempts a start email. The per-job watcher attempts a status email after 12 hours and every 12 hours after that while the job is in `planning`, `queued`, `implementing`, `fixing`, or `waiting_tokens`. The message includes progress, estimated remaining time, role choices, activity counts, current task, and the latest controller summary. Start attempts use `email_started_sent`, `email_started_failed`, or `email_started_skipped`; status attempts use the corresponding `email_status_*` event. The stored event time keeps the schedule stable across watcher restarts.

Mail is enabled only when `AI_LOOP_SMTP_HOST` and `AI_LOOP_SMTP_PASSWORD` are both non-empty. If either is empty, startup account checks are skipped, no outgoing messages are sent, reply polling is disabled, and attempts are classified as `skipped`. There is no `sendmail` fallback and no passwordless SMTP path.

When enabled, startup calls `check_mail_access` before normal GUI/job work:

1. Require SMTP user and notification recipient.
2. Connect with SMTP SSL or STARTTLS, authenticate, and issue `NOOP` without sending a test message.
3. If IMAP is configured, connect with IMAP SSL or STARTTLS, authenticate, and select the configured mailbox read-only.
4. Return a structured result containing enabled/healthy flags plus separate SMTP and mailbox details.
5. Print failures in the CLI; in the GUI, show an error dialog and retain the result in both the top status box and the selected-job Status tab. With no selected job, the Status tab still displays mail access.

An absent IMAP host leaves SMTP healthy but reports mailbox access as not configured. Any configured SMTP or IMAP authentication/access failure makes the overall startup result unhealthy. The check does not stop non-mail job execution.

Each terminal attempt writes `email_notification_sent`, `email_notification_failed`, or `email_notification_skipped` with status, recipient, and delivery detail. Notification failure does not change a successfully computed terminal job state.

The successful `DONE` path promotes worktree changes, writes the durable `done` state/event, calls `notify_terminal(..., "done", ...)`, and then publishes `ai:done`. The email attempt intentionally precedes Redis publication so a Redis failure cannot suppress completion mail. Thus a configured account sends a completion email after successful promotion; a promotion conflict instead sends the normal `human_needed` notification.

Every outgoing job message has the deterministic root thread ID and an `X-AI-Loop-Notification` marker. Status and terminal messages reference the root. This keeps replies associated with one job and prevents an inbox copy of an outgoing notification from being accepted as user input.

### Incoming reply algorithm

If mail is disabled or `AI_LOOP_IMAP_HOST` is empty, incoming commands are disabled. Otherwise each scoped watcher:

1. Connects with IMAP-over-SSL, or STARTTLS when configured.
2. Opens `AI_LOOP_IMAP_MAILBOX` read-only and examines recent messages without changing their read state.
3. Rejects AI-Loop notification messages and senders other than the exact `AI_LOOP_NOTIFY_EMAIL` address.
4. Requires the job thread ID in `In-Reply-To`/`References`, or a reply-style subject containing the scoped job ID.
5. Extracts `text/plain`, removes quoted history and an optional `Command:` prefix, and ignores an empty result.
6. Deduplicates by message ID using durable `email_command_received`/`email_command_applied` events.
7. Appends the accepted text to the job constraints as `New command received by email: …`.

For an active job, the new constraint affects future controller/worker tasks and does not interrupt a running task. For `human_needed`, the watcher invokes `resume_job.py` for the same job with the command as an added constraint. Normal resume changes the state to `planning`, launches replacement per-job processes, and enqueues `PLAN`. On success the old watcher exits; on failure it restores `human_needed`, records `email_command_failed`, and remains available for another reply or manual resume.

The GUI Human Needed alert is a tracked, non-modal `Toplevel`. Its status check runs even when full auto-refresh is disabled, so an emailed or manual resume closes the alert. Authentication blockers use the same tracked window and expose `Sign In + Resume` explicitly.

## GUI text and help behavior

All dashboard text widgets use word wrapping, so lines break at the right edge and remain readable without horizontal scrolling. The shared `set_text` helper compares current and new content; it only changes the widget when content differs and preserves the vertical view. Logs jump to the end only after changed content is loaded.

Controls have explicit explanatory hover text. A recursive fallback attaches informative help to passive labels, scrollbars, frames, and any future widget that was not explicitly registered. Tooltips use an 11-point font, padding, and a 460-pixel wrap length.

## Process and file compatibility

New processes use:

- PID files: `controller.pid`, `worker.pid`, `watcher.pid`
- logs: `controller.log`, `worker.log`, `watcher.log`
- Python programs: `controller.py`, `worker.py`, `watcher.py`

The GUI can still read legacy model-named PID/log files so already-running jobs are visible and stoppable. No model-named controller or worker Python source file remains.

## Completion and promotion

When the controller returns DONE:

1. Inspect worktree porcelain status, including renames and deletions.
2. Build the changed-path set.
3. Check each path for local changes in the original repo.
4. If any conflict exists, stop with HUMAN_NEEDED and email; do not overwrite.
5. Copy added/modified paths and remove deleted paths.
6. Store promotion and done events.
7. Publish `ai:done` and email readiness.

No merge or destructive reset is used.

## Failure and recovery

Redis connection errors are retried by long-running consumers. Transient Claude transport failures use capped exponential backoff. Parseable token-limit failures use the explicit replenishment flow instead.

An unexpected controller or worker exception calls `attempt_auto_recovery`. A per-job marker prevents concurrent recovery. The recovery agent sees controller, worker, and watcher log tails, may repair the AI-Loop repository, syntax-checks changes, and launches resume after success. If recovery fails, the original process records `dead`, publishes the dead stream event, and attempts email.

The GUI attempts to install a missing standard provider CLI before job
creation. Missing custom binaries, failed package installation, and provider
authentication cannot be resolved generically; those conditions are reported
with the underlying error and a usual manual command or become human-needed if
encountered later by a running controller or worker. Fixable target-repository
build/test problems should normally become REPAIR tasks instead.

## Process launch and isolation

Per-job environment variables include:

- `AI_LOOP_JOB_ID`
- `AI_LOOP_RUNTIME_DIR=run/jobs/<job-id>`
- `AI_LOOP_LOG_DIR=logs/jobs/<job-id>`
- selected CLI binary/model variables
- `CODEX_BYPASS_SANDBOX`

Unix processes start in new sessions so the GUI can terminate their process groups. Windows uses a new process group where supported.

Worktree isolation is the primary protection for all workers. Codex safe mode adds `--sandbox workspace-write`; bypass mode uses the unrestricted Codex flag. Claude workers use edit permissions in normal mode and the Claude permission-skip flag in bypass mode. Gemini maps the same choice to its supported sandbox/autonomy flags.

## Test-command selection

Automatic detection checks visible CMake presets, plain CMake, npm, then Python project markers. The controller cannot silently replace the job test command: task creation rewrites test-related acceptance language back to the authoritative job command and stores that command on every task.

## Operational paths

- Database: `AI_LOOP_DB` or `./ai_loop.sqlite3`
- Worktrees: `AI_LOOP_RUNS_DIR` or sibling `ai-runs/`
- Per-job runtime: `run/jobs/<job-id>/`
- Per-job logs: `logs/jobs/<job-id>/`
- Recovery marker: `run/jobs/<job-id>/auto_recovery.running`
- Sandbox bypass marker: `run/jobs/<job-id>/bypass_sandbox`
- Local primary environment: `.venv/`
- GUI fallback environment: `.gui-venv/`

## Known shell-platform constraints

- `ai_hibernation.bash status` reads `pmset -g`. Some current macOS versions
  expose `hibernatemode` only through `pmset -g custom`, so status can report
  unavailable even when the mode is configured.
- `ai_loopctl.bash` and `ai_delete_job.bash` terminate recorded parent PIDs.
  Unlike the GUI process-group termination path, they can leave provider or
  test subprocesses alive.
- `ai_remove_worktrees.bash` is intentionally destructive: by default it
  force-removes registered AI worktrees and leftover directories under the
  configured runs directory.
- GUI construction must be tested with access to the native window server.
  A Tk process can abort in a headless sandbox even when the launcher works in
  the user's desktop session.

## Maintenance checklist

When changing lifecycle behavior:

1. Add/migrate durable fields before consuming them.
2. Update GUI, CLI status tools, active-status queries, cleanup, and docs together.
3. Keep Redis payloads reconstructible from SQLite.
4. Update both controller schema text and `decision.schema.json`.
5. Preserve plan immutability.
6. Keep granularity independent of provider/model.
7. Ensure token waits never emit premature human-needed notifications.
8. Run Python compilation, shell syntax checks, database migration smoke tests,
   token-time parser tests, and GUI construction with a display harness.
9. Exercise Bash help/status/dry-run paths with both a populated `.venv` and a
   fresh-clone environment that has no local virtual environment.
10. Keep this file as the single worker-system architecture document; do not
    add compatibility pointer files with competing `WORKER_SYSTEM` names.
