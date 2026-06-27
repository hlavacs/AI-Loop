# Generic Claude + Codex Development Loop

This directory contains a durable continuous development loop:

- SQLite stores jobs, tasks, runs, Claude decisions, and events.
- Redis Streams are used only for activation messages and terminal notifications.
- Claude CLI controls planning and review.
- Codex CLI implements one task at a time.
- Git worktrees isolate jobs by default.

## Requirements

- Python 3.10+
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

`./job.bash` also uses that selected interpreter for its default validation
command, so the implicit test command is equivalent to:

```bash
/absolute/path/to/selected/python -m pytest -q
```

If the selected interpreter needs the loop virtualenv packages through
`PYTHONPATH`, `./job.bash` stores that absolute `PYTHONPATH` prefix in the
test command as well.

Set `AI_LOOP_TEST_CMD` to override that default for a target repository.

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

## Start the Loop Processes

Use the control script to run the loop in the background:

```bash
./loopctl.bash start
./loopctl.bash status
./loopctl.bash stop
./loopctl.bash restart
```

Or run each command in a separate terminal from this directory:

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
  --max-iterations 8 \
  --base-ref HEAD \
  --wait
```

With `--wait`, the command prints status updates until the job reaches `done`, `human_needed`, or `dead`, then prints inspect commands. Omit `--wait` to submit the job asynchronously.

By default this creates:

- SQLite job state in `./ai_loop.sqlite3`
- Git branch `ai/<job_id>`
- Git worktree `../ai-runs/<job_id>`
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
./check_job.bash <job_id>
```

List all known jobs:

```bash
./check_job.bash
```

Print the durable loop log from SQLite and tail process log files from `./logs`:

```bash
./print_log.bash
./print_log.bash --job <job_id> --limit 50
```

Resume a job that reached `human_needed` because the test command was wrong:

```bash
python resume_job.py <job_id> \
  --test-cmd "ctest --test-dir build/debug-macos -C Debug --output-on-failure" \
  --wait
```

Resume a job with a corrected target path or goal:

```bash
python resume_job.py <job_id> \
  --goal "Implement the simple engine under src/versions/simple." \
  --constraint "Do not implement this in src/versions/v4 or src/versions/v5." \
  --acceptance "The implementation lives under src/versions/simple." \
  --wait
```

This updates the stored job fields, marks the job as `planning`, and queues a new `PLAN` request.

Clear run, decision, and event log rows, and truncate process log files, while keeping jobs and tasks:

```bash
./clear_log.bash --dry-run
./clear_log.bash --yes
```

The process log files are created by `./run_claude.bash`, `./run_codex.bash`, and `./run_watcher.bash`. Restart already-running workers with those wrappers to begin writing `./logs/*.log`. To wipe the entire job database, use `./clear_db.bash --yes` instead.

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

The loop never commits or merges automatically.
The controller should split work into small tasklets: one narrow objective, one clear stop point, and no bundled audit-plus-implementation milestones. Restart the workers after changing prompt code so running processes pick up the new tasklet policy.
