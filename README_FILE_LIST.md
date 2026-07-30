# File Structure

```text
.
├── README.md
├── WORKER_SYSTEMS.md
├── decision.schema.json
├── docs/
│   └── images/
│       └── ai-loop-gui.png
├── ai_loop/
│   ├── __init__.py
│   ├── config.py
│   ├── db.py
│   ├── email_commands.py
│   ├── notifications.py
│   ├── planning.py
│   ├── progress.py
│   ├── queues.py
│   ├── recovery.py
│   ├── status_updates.py
│   └── token_wait.py
├── controller.py
├── worker.py
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

- `README.md`: complete installation and user guide.
- `WORKER_SYSTEMS.md`: sole authoritative technical architecture and lifecycle guide.
- `decision.schema.json`: JSON schema for controller decisions.
- `docs/images/ai-loop-gui.png`: current GUI screenshot embedded in the README.
- `controller.py`: model-neutral planning and review controller process.
- `worker.py`: model-neutral implementation worker process.
- `resume_job.py`: job resume entrypoint.
- `start_job.py`: job creation entrypoint.
- `watcher.py`: event watcher process.

## Package

- `ai_loop/__init__.py`: package marker.
- `ai_loop/config.py`: configuration loading.
- `ai_loop/db.py`: SQLite schema and database helpers.
- `ai_loop/email_commands.py`: secure IMAP reply matching, command extraction, deduplication, and job resume handling.
- `ai_loop/notifications.py`: startup SMTP/IMAP access checks and authenticated SMTP messages.
- `ai_loop/planning.py`: immutable plans and granularity policy.
- `ai_loop/progress.py`: progress formatting and reporting helpers.
- `ai_loop/queues.py`: queue and stream helpers.
- `ai_loop/recovery.py`: internal failure recovery.
- `ai_loop/status_updates.py`: durable 12-hour status email scheduling.
- `ai_loop/token_wait.py`: quota reset parsing and automatic waits.

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
