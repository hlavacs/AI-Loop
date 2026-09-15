# Project inventory for video production

Inventory date: 2026-09-15. Counts include test and documentation utilities where noted. Existing files were inspected but not changed.

## AI-Loop

### Product story

AI-Loop turns a repository-level coding goal into a durable job. A controller makes and reviews bounded tasks; a worker changes code and runs validation; a watcher maintains progress and notification handling. SQLite preserves the job, plan, tasks, runs, decisions, events, and terminal state. Redis Streams coordinates processes, and isolated Git worktrees keep active changes separate from the original checkout. The Tkinter GUI exposes creation, status, plan, task, controller, worker, details, logs, specification, analysis, and assistance views.

### Entry points and implementation areas

- GUI and launchers: `ai-loop/ai_loop_gui.py`, `ai-loop/ai_gui.bash`, `ai-loop/ai_gui.cmd`.
- Job processes: `ai-loop/controller.py`, `ai-loop/worker.py`, `ai-loop/watcher.py`, `ai-loop/start_job.py`, `ai-loop/resume_job.py`.
- Durable state and coordination: `ai-loop/ai_loop/db.py`, `queues.py`, `planning.py`, `job_status.py`, `progress.py`.
- Safety and recovery: `process_runner.py`, `recovery.py`, `auth.py`, `token_wait.py`, `systemd_sandbox.py`.
- Specification and evidence: `specifications.py`, `specification_gui.py`, `specification_compiler.py`, `specification_workflow.py`, `evidence_adapters.py`, `verification_orchestrator.py`, `verification_dashboard.py`, and `project_analysis/`.
- Notification path: `notifications.py`, `email_commands.py`, `status_updates.py`.
- Runtime requirements: Python 3.10+, Git, Redis/redis-py, Tkinter for GUI, and at least one supported controller and worker CLI. Package version is 1.0.0.
- Scale observed: 72 Python files, 27 `test_*.py` files, and 19 existing documentation PNG screenshots.

### Existing production references

- Current product documentation: `ai-loop/README.md` and `ai-loop/docs/HANDBOOK.md`.
- Deterministic GUI capture harness: `ai-loop/docs/capture_gui_screenshots.py`.
- Deterministic specification capture harness: `ai-loop/docs/capture_specification_screenshots.py`.
- Useful sanitized 1408×812 captures: `s11-gui-jobs-status.png` through `s18-quick-job-complete.png` in `ai-loop/docs/images/`.
- Additional specification captures: Overview, Scope, Requirements, Choices, Review, help, and dialog states in `ai-loop/docs/images/`.
- Earlier video materials in `ai-loop/docs/video/` are reference-only. The new production uses the current `VIDEO.md` requirements and the files under `video/`.

## ICODA

### Product story

ICODA, Interactive Code Development and Analysis, combines a written specification, a derived code model, graphical architecture views, isolated LLM proposals, build/test evidence, and explicit developer decisions. Work advances from specification to architecture to implementation. Approved proposals become Git commits; rejected or adapted proposals preserve decision history. The GUI provides file, call, class, mind-map, coverage, issue, proposal, and specification views.

### Entry points and implementation areas

- GUI and launchers: `icoda/icoda.py`, `icoda/icoda.bash`, `icoda/icoda.cmd`, and `icoda/icoda_gui/`.
- Analysis/model: `icoda_core/analysis.py`, `python_analysis.py`, `model.py`, `views.py`, `class_view.py`, `mind_map.py`.
- Specification/coverage/rules: `specification.py`, `requirement_coverage.py`, `coverage_index.py`, `rules.py`.
- Agent proposal workflow: `agent.py`, `prompt.py`, `response.py`, `steps.py`, `adaptation.py`, `auto_approve.py`.
- Isolation and gates: `git.py`, `process.py`, `toolchain.py`, `test_selection.py`, `implementation.py`, `implementation_queue.py`.
- Persistence and history: `session.py`, `persistence.py`, `steplog.py`, `phases.py`.
- Runtime requirements: Python 3.10+, Tkinter, Git, a logged-in Claude or Codex CLI; C++ projects additionally use CMake/Ninja/Clang. Package version is 0.1.0.
- Scale observed: 114 Python files, 50 `test_*.py` files, and 32 existing handbook PNG screenshots.

### Existing production references

- Current product documentation: `icoda/README.md`, `icoda/docs/GETTING_STARTED.md`, `icoda/docs/TUTORIAL.md`, and `icoda/HANDBOOK.md`.
- Deterministic view capture harness: `icoda/tests/gui_acceptance.py`.
- Deterministic ten-state lifecycle capture: `icoda/tests/simulation_acceptance.py`.
- Existing handbook captures cover File, Call, Class, Mind Map, Coverage, Issues, provider choice, source diff, signature confirmation, specification pages, and the full simulated workflow.
- Earlier materials in `icoda/docs/video/` are reference-only. ICODA storyboarding, narration, rendering, and audio are deliberately deferred.

