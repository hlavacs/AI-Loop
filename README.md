# Generic Claude + Codex Development Loop

This directory contains a durable continuous development loop:

- SQLite stores jobs, tasks, runs, Claude decisions, and events.
- Redis Streams are used only for activation messages and terminal notifications.
- Claude CLI controls planning and review.
- A per-job worker (Codex CLI or Claude Fable) implements one task at a time.
- Git worktrees isolate jobs by default.

## Requirements

- Python 3.10+
- Tkinter for the optional GUI (`python -m tkinter` should open a test window)
- Redis
- `redis-py`
- `git`
- Claude CLI available as `claude`
- Codex CLI available as `codex`, or set `CODEX_BIN`

Install the Python dependency:

```bash
python -m pip install redis
```

## Start Redis

```bash
redis-server --save "" --appendonly no
```

Or use an existing Redis and set:

```bash
export REDIS_URL=redis://localhost:6379/0
```

## Initialize the Database

The scripts initialize the schema automatically. To initialize it explicitly:

```bash
python - <<'PY'
from ai_loop.config import load_settings
from ai_loop.db import init_db

settings = load_settings()
init_db(settings.db_path)
print(settings.db_path)
PY
```

Optional settings:

```bash
export AI_LOOP_DB="$PWD/ai_loop.sqlite3"
export AI_LOOP_RUNS_DIR="$(dirname "$PWD")/ai-runs"
export AI_LOOP_PYTHON=python3
export CODEX_BIN=codex
```

The shell wrappers prefer `AI_LOOP_PYTHON` when set, then local virtualenv
interpreters, then versioned `python3` commands. They do not require a bare
`python` executable.

`./ai_job.bash` uses the selected interpreter to submit the job, but it does
not force every target project through pytest. If `AI_LOOP_TEST_CMD` is unset,
`start_job.py` infers a generic validation command from the target repository:
CMake presets first, then plain CMake, then `npm test`, then `pytest -q` for
Python projects, and finally `true` when no known runner is detected.

The wrapper accepts either an explicit repository plus job description, or a
single text file. With the text-file form, the file contents are used as the job
description and the file's containing directory is used as the target repository:

```bash
./ai_job.bash /path/to/repo "Implement the requested feature."
./ai_job.bash /path/to/repo/job.txt
```

Set `AI_LOOP_TEST_CMD` to override that detection for a target repository.

## Tkinter GUI

The cross-platform GUI is a Python/Tkinter script and does not call the bash
wrappers. It creates jobs, launches the controller/worker/watcher Python
processes, tails logs, shows task/run history, stops jobs, resumes paused jobs,
changes controller/worker choices, and resets the loop database. If the active
Python is missing `redis-py`, the GUI creates `.gui-venv`, installs `redis`
there, and restarts itself. It also has a Start Redis button and will start a
local `redis-server --save "" --appendonly no` automatically before queueing a
job when `REDIS_URL` points at localhost. Cleanup controls are split into
Clear Worktrees, Reset DB, and Full Reset so you can remove generated worktrees,
clear durable job records, or do both. When a job enters `human_needed`, the
GUI shows an alert and lists practical next actions in the selected job's
Overview tab. On macOS, the GUI also exposes hibernation status plus enable and
disable actions backed by `pmset`.

```bash
python3 ai_loop_gui.py
./ai_gui.bash --theme default
./ai_gui.bash --list-themes
```

The default theme keeps the current platform-native Tk style. Any theme printed
by `--list-themes` can be passed with `--theme <name>`.

Use the controller/worker dropdowns and model fields to select `codex`,
`fable`, `opus`, or `claude` behavior. Defaults come from the same environment
variables as the CLI (`AI_LOOP_CONTROLLER`, `AI_LOOP_WORKER`,
`AI_LOOP_FABLE_MODEL`, `AI_LOOP_OPUS_MODEL`, `AI_LOOP_CONTROLLER_MODEL`,
`CODEX_BIN`, and `CLAUDE_BIN`).

## Choosing the Worker

Each job stores which implementation worker it uses: `codex` (default),
`fable` (Claude Fable via the Claude CLI; `claude` is accepted as an alias),
or `opus` (Claude Opus via the Claude CLI, model `AI_LOOP_OPUS_MODEL`).

```bash
./ai_job.bash --worker fable /path/to/repo "Implement the requested feature."
python3 start_job.py --worker fable --repo /path/to/repo --goal "..."
export AI_LOOP_WORKER=fable   # default for new jobs when --worker is not given
```

The Fable/Opus workers run:

```bash
claude -p --model "$AI_LOOP_FABLE_MODEL" --permission-mode acceptEdits --allowedTools Bash,Edit,Write,MultiEdit,NotebookEdit
```

Set `AI_LOOP_FABLE_MODEL` to change the model (default `claude-fable-5`).

## Choosing the Controller

Each job also stores which controller plans and reviews: `opus` (default),
`claude` (Claude CLI with its default model or `AI_LOOP_CONTROLLER_MODEL`),
`fable`, or `codex`.

```bash
./ai_job.bash --controller fable --worker fable /path/to/repo "Implement feature X."
python3 start_job.py --controller opus --repo /path/to/repo --goal "..."
export AI_LOOP_CONTROLLER=fable   # override the default when --controller is not given
```

`fable` and `opus` run the Claude CLI with `--model` (`AI_LOOP_FABLE_MODEL`,
default `claude-fable-5`; `AI_LOOP_OPUS_MODEL`, default `opus`). `codex` runs
`codex exec --sandbox read-only --output-last-message` and parses the decision
JSON from the last agent message.

## Task Sizing

Task sizing follows the job's worker. With the `codex` worker, the controller
plans many tiny tasklets (one narrow objective, one file cluster, short stop
point). With `fable` or `opus` workers, the controller plans larger coherent
tasks that may span several related files and include their own discovery and
verification, cutting controller round-trips. The default job constraints and
the worker prompt adjust accordingly.

With `CODEX_BYPASS_SANDBOX=1` the Fable worker uses
`--dangerously-skip-permissions` instead. Note the Claude CLI has no
filesystem sandbox comparable to Codex's `workspace-write`; the Git worktree
isolation is the main guardrail.

By default Codex runs with:

```bash
codex exec --sandbox workspace-write
```

To bypass Codex sandboxing and approvals:

```bash
export CODEX_BYPASS_SANDBOX=1
```

That changes Codex execution to use:

```bash
codex exec --dangerously-bypass-approvals-and-sandbox
```

## Loop Process Operations

Normal jobs start their own Claude controller, Codex worker, and watcher. You do not need to start global loop processes before creating a job.

Use the control script for status and emergency stop:

```bash
./ai_loopctl.bash status
./ai_loopctl.bash stop
```

For legacy/manual debugging, each process can still be run in a separate terminal from this directory:

```bash
python claude_controller.py
```

```bash
python codex_worker.py
```

```bash
python watcher.py
```

The controller listens on `ai:claude:requests`.
The worker listens on `ai:codex:tasks`.
The watcher prints terminal events from `ai:done`, `ai:human`, and `ai:dead`.

## Create a Generic Job

```bash
python start_job.py \
  --repo /path/to/repo \
  --goal "Implement the requested feature in small safe steps" \
  --test-cmd "pytest -q" \
  --constraint "Preserve public APIs unless the task requires changing them." \
  --acceptance "The feature is documented where users would expect it." \
  --max-iterations 50000 \
  --base-ref HEAD \
  --wait
```

With `--wait`, the command prints status updates until the job reaches `done`, `human_needed`, or `dead`, then prints inspect commands. It waits indefinitely by default; pass `--timeout <seconds>` with a positive value to impose a foreground wait limit. Omit `--wait` to submit the job asynchronously.

By default, each ai-loop job gets its own Claude controller, Codex worker, and terminal watcher. Active jobs can run concurrently because every job uses its own Redis consumer groups, PID directory, and process log directory. Set `AI_LOOP_SINGLE_ACTIVE_JOB=1` to restore the old single-active-job guard; with that guard enabled, `--allow-parallel` or `AI_LOOP_ALLOW_PARALLEL_JOBS=1` starts another job anyway.

```bash
./ai_check_job.bash
./ai_watch_job.bash
./ai_job.bash /path/to/repo "Second job"
./ai_delete_job.bash [job-id]
./ai_clear_db.bash --yes
```

By default this creates:

- SQLite job state in `./ai_loop.sqlite3`
- Git branch `ai/<job_id>`
- Git worktree `../ai-runs/<job_id>`
- Per-job PID files in `./run/jobs/<job_id>`
- Per-job process logs in `./logs/jobs/<job_id>`
- A `PLAN` request on `ai:claude:requests`

To work directly in the repository instead of a worktree:

```bash
python start_job.py \
  --repo /path/to/repo \
  --goal "Make the requested change" \
  --test-cmd "pytest -q" \
  --no-worktree
```

Check whether a job exists in the system:

```bash
./ai_check_job.bash <job_id>
```

List all known jobs:

```bash
./ai_check_job.bash
```

Print the durable loop log from SQLite and tail process log files from `./logs`:

```bash
./ai_print_log.bash
./ai_print_log.bash --job <job_id> --limit 50
```

Watch an active job periodically:

```bash
./ai_watch_job.bash
```

The watcher picks the newest `planning`, `queued`, `implementing`, or `fixing` job automatically.

Resume a job that reached `human_needed` because the test command was wrong:

```bash
./ai_resume_job.bash
./ai_resume_job.bash <job_id> \
  --test-cmd "ctest --test-dir build/debug-macos -C Debug --output-on-failure" \
  --wait
```

With no arguments, `./ai_resume_job.bash` resumes the newest `human_needed` job and sets `--max-iterations` to `50000`.
Override that default with `AI_LOOP_RESUME_MAX_ITERATIONS`.
With `--wait`, resume waits indefinitely by default; pass `--timeout <seconds>` with a positive value to impose a foreground wait limit.

Resume a job with a corrected target path or goal:

```bash
./ai_resume_job.bash <job_id> \
  --goal "Implement the requested feature under the intended target directory." \
  --constraint "Do not modify unrelated packages or generated files." \
  --acceptance "The implementation lives in the requested target area." \
  --wait
```

This updates the stored job fields, marks the job as `planning`, and queues a new `PLAN` request.

Clear run, decision, and event log rows, and truncate process log files, while keeping jobs and tasks:

```bash
./ai_clear_log.bash --dry-run
./ai_clear_log.bash --yes
```

The process log files are created by `./ai_run_claude.bash`, `./ai_run_codex.bash`, and `./ai_run_watcher.bash`. Restart already-running workers with those wrappers to begin writing `./logs/*.log`. To wipe the entire job database, use `./ai_clear_db.bash --yes` instead.

Delete one job record from SQLite:

```bash
./ai_delete_job.bash [job-id]
```

This removes the durable job/task/run/decision rows for that job. If no job id is given, it deletes the newest active job (`planning`, `queued`, `implementing`, or `fixing`). It does not delete worktree folders; use `./ai_remove_worktrees.bash` for worktree cleanup.

Reset the local loop by deleting active job records, clearing the database, and restarting the controller, worker, and watcher:

```bash
./ai_reset_loop.bash --dry-run
./ai_reset_loop.bash --yes
```

## Loop Behavior

1. `start_job.py` creates a durable SQLite job record.
2. It creates an isolated Git worktree unless `--no-worktree` is provided.
3. It sends a `PLAN` request to `ai:claude:requests`.
4. `claude_controller.py` asks Claude for one small first Codex task.
5. The controller stores Claude's decision and sends one task to `ai:codex:tasks`.
6. `codex_worker.py` runs `codex exec` in the job worktree.
7. The worker runs the task test command, captures git status, changed files, diff stat, and diff.
8. The worker stores a durable run and sends a `REVIEW` request to `ai:claude:requests`.
9. Claude reviews state and returns `CONTINUE`, `REPAIR`, `DONE`, or `HUMAN_NEEDED`.
10. Terminal outcomes are published to `ai:done`, `ai:human`, or `ai:dead`.

Before creating a job, `start_job.py` commits current target-repo changes when needed so new worktrees include the user's latest files. The loop does not commit Codex task changes or merge branches automatically.

Project instruction files such as `AGENTS.md` are optional. When present and relevant, Claude and Codex should follow them. When absent, the loop should continue from the job goal, constraints, local code patterns, and tests instead of treating the missing file as a blocker.

File-like paths mentioned in the job goal, constraints, or acceptance criteria are treated as possible live guidance files. On each PLAN/REVIEW, Claude receives refreshed content and modification times for existing referenced files in the worktree. On each task, Codex is told to re-read the current versions before working. This is generic and does not depend on a particular filename.

Claude reviews more than task completion. It should reject or repair visible violations of project guidelines, local architecture, naming/style patterns, scope control, maintainability, proportional test coverage, and unrelated refactors.

`HUMAN_NEEDED` is a last resort. Claude should first analyze the blocker, identify concrete solution paths, and create a `REPAIR` task whenever the loop can safely diagnose or fix the problem automatically. Such jobs are shown as `fixing` while the repair task is queued or running.

Transient Claude CLI transport/service failures are retried indefinitely by the controller instead of emitting `HUMAN_NEEDED`. This covers connection resets, timeouts, overload/rate-limit responses, and similar temporary service failures. Configure the wait behavior with `AI_LOOP_CLAUDE_TRANSIENT_BACKOFF_SECONDS` (default `5`) and `AI_LOOP_CLAUDE_TRANSIENT_MAX_BACKOFF_SECONDS` (default `60`). Missing binaries, promotion conflicts, non-transient CLI failures, and real Claude `HUMAN_NEEDED` decisions still surface to the human stream.

Executable scene or asset load errors such as `scene load failed: error=io_error` are treated as likely working-directory or asset-path issues first. Claude should ask Codex to reproduce from the repository/worktree root, compare the failing launch directory, inspect expected asset paths, and repair path resolution or launch documentation before considering `HUMAN_NEEDED`.

The controller should split work into small tasklets: one narrow objective, one clear stop point, and no bundled audit-plus-implementation milestones. Restart the workers after changing prompt code so running processes pick up the new tasklet policy.
