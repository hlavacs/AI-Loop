# File Structure

```text
.
├── README.md
├── README_AI_LOOP.md
├── WORKER_SYSTEM.txt
├── decision.schema.json
├── ai_loop/
│   ├── __init__.py
│   ├── config.py
│   ├── db.py
│   ├── progress.py
│   └── queues.py
├── claude_controller.py
├── codex_worker.py
├── resume_job.py
├── start_job.py
├── watcher.py
├── ai_check_job.bash
├── ai_clear_db.bash
├── ai_clear_log.bash
├── ai_delete_job.bash
├── ai_hibernation.bash
├── ai_job.bash
├── ai_loop_python.bash
├── ai_loopctl.bash
├── ai_print_log.bash
├── ai_remove_worktrees.bash
├── ai_reset_loop.bash
├── ai_resume_job.bash
├── ai_run_claude.bash
├── ai_run_codex.bash
├── ai_run_crash_safe.bash
├── ai_run_loop_proof.bash
├── ai_run_watcher.bash
└── ai_watch_job.bash
```

## Top-Level Files

- `README.md`: file structure index.
- `README_AI_LOOP.md`: existing project notes.
- `WORKER_SYSTEM.txt`: worker system prompt text.
- `decision.schema.json`: JSON schema for controller decisions.
- `claude_controller.py`: Claude-side controller process.
- `codex_worker.py`: Codex-side worker process.
- `resume_job.py`: job resume entrypoint.
- `start_job.py`: job creation entrypoint.
- `watcher.py`: event watcher process.

## Package

- `ai_loop/__init__.py`: package marker.
- `ai_loop/config.py`: configuration loading.
- `ai_loop/db.py`: SQLite schema and database helpers.
- `ai_loop/progress.py`: progress formatting and reporting helpers.
- `ai_loop/queues.py`: queue and stream helpers.

## Shell Scripts

- `ai_check_job.bash`
- `ai_clear_db.bash`
- `ai_clear_log.bash`
- `ai_delete_job.bash`
- `ai_hibernation.bash`
- `ai_job.bash`
- `ai_loop_python.bash`
- `ai_loopctl.bash`
- `ai_print_log.bash`
- `ai_remove_worktrees.bash`
- `ai_reset_loop.bash`
- `ai_resume_job.bash`
- `ai_run_claude.bash`
- `ai_run_codex.bash`
- `ai_run_crash_safe.bash`
- `ai_run_loop_proof.bash`
- `ai_run_watcher.bash`
- `ai_watch_job.bash`

## Local Runtime Artifacts

- `ai_loop.sqlite3`: local SQLite database.
- `logs/`: local process logs.
- `run/`: local process PID files.
- `.venv/`: local Python virtual environment.
- `.pytest_cache/`: local pytest cache.
- `__pycache__/` and `ai_loop/__pycache__/`: local Python bytecode caches.
