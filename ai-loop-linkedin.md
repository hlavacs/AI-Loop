# ai-loop — autonomous, durable orchestration for AI coding agents

Most AI coding tools generate a single change and then pause, waiting for a review and a fresh prompt before they continue. That keeps a developer in the loop for every step and caps how much real progress an agent can make on its own. ai-loop takes a different approach: give it a goal, and it plans, implements, verifies, and advances task by task with minimal supervision.

The architecture separates thinking from doing — and you choose which model plays each role:

🧠 A controller handles planning and review — decomposing a goal into discrete tasks and deciding what should happen next at each step.

🔧 A worker implements one task at a time, so responsibilities stay clear and each unit of work is small and verifiable.

🎛️ Both roles are configurable per job. Run Claude as the controller and Codex as the worker, pair Claude Opus with Claude Fable, or mix and match however the task demands — and change the pairing on the fly. You match the reasoning model to the planning and the execution model to the implementation, instead of being locked into a single vendor for everything.

🌳 Every job runs in its own git worktree, keeping parallel work isolated and the main branch clean throughout.

💾 State lives in SQLite — jobs, tasks, decisions, and events are all persisted. The loop survives crashes, restarts, and even machine sleep. If it isn't in the database, it didn't happen.

Just as important, the system is built to be operated in production, not only demonstrated. A cross-platform GUI lets you create jobs, tail logs, pause and resume work, and switch controller or worker models on the fly. When a task genuinely requires human judgment, the loop transitions to a `human_needed` state and reports exactly what is required — no silent failures, and no runs spinning indefinitely on something they cannot resolve.

A word on scope: ai-loop is deliberately lean. It's a focused, no-frills tool for everyday programming — the steady stream of features, fixes, and refactors that make up a developer's day. It stays small on purpose. The larger ambition lives at my company, Robimo, where we're building a far more elaborate system for orchestrating long-running work — jobs that run for weeks rather than minutes, such as end-to-end ML training pipelines. ai-loop is the sharp daily-driver; Robimo is the heavy machinery for tasks at a completely different scale.

The premise underneath it all: the next step in AI-assisted development isn't a smarter autocomplete. It's dependable orchestration — a loop you can hand a goal and trust to make measurable progress.

If you're working on autonomous agents, orchestration, or durable agent infrastructure, I'd welcome the chance to compare notes. 👇

#AI #SoftwareEngineering #Agents #DeveloperTools #Automation
