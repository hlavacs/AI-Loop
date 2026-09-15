# ICODA

**Interactive Code Development and Analysis** is a desktop application for developing C++ and Python software
with coding agents in small, reviewable steps. Write a specification, develop the architecture, and implement
functions while inspecting the source structure, proposed changes, and test evidence in one place.

You decide what to build, approve implementation approaches, and review code before it is committed. ICODA
derives its architecture views from the source code and verifies proposals in an isolated Git worktree.

[Quick Start](#quick-start) | [Workflow](#development-workflow) |
[Illustrated PDF Handbook](output/pdf/ICODA-Handbook.pdf) | [Development](#development)

![ICODA showing a source hierarchy, an implementation target, and a proposed approach](docs/images/handbook/implementation-approach.png)

*The implementation workspace combines the project structure, next target, and approach awaiting approval.
The [handbook](output/pdf/ICODA-Handbook.pdf) explains the complete interface with 32 screenshots.*

## What ICODA Does

- **Formal specifications:** record goals, exclusions, use cases, requirements, architectural decisions, and a
  Code Profile with language, library, style, and test conventions.
- **Source analysis:** inspect files, calls, classes, and a hierarchical Mind Map. Filter, zoom, pan, and follow
  entities back to their source locations.
- **Controlled generation:** review architecture proposals, then approve an implementation approach before
  requesting code and tests. Work through a persisted queue or select the next target yourself.
- **Build and test gates:** keep approval blocked when a proposal fails its configured checks. Review the source
  diff, entity changes, API signature changes, and build/test output before deciding.
- **Traceability:** connect requirements to code through `@satisfies` tags and inspect recorded test evidence,
  uncovered callables, advisory rule findings, and development history.
- **Git integration:** approve changes as commits, record manual edits, or revert the last approved step when
  its undo conditions are satisfied.

ICODA is independent of [AI-Loop](../ai-loop/README.md), the unattended job runner in the same repository.
It does not require AI-Loop or Redis.

## Quick Start

### Prerequisites

| Task | Requirements |
|---|---|
| Run the desktop application | Python 3.10 or newer with Tkinter, Git, and a graphical desktop |
| Generate proposals | An installed and authenticated Claude Code or Codex CLI |
| Analyse C++ | A compatible libclang and a generated `compile_commands.json` |
| Build and test C++ | CMake 3.28 or newer, Ninja, Clang, and the project's dependencies; `clang-scan-deps` for C++ modules |
| Build and test Python | The project's dependencies and its configured test runner, such as pytest |

Install vcpkg and set `VCPKG_ROOT` when the C++ project requires it. On macOS, generated C++ module projects
normally need Homebrew LLVM; Apple Clang alone may not provide the required module-scanning support.
See the [installation guide](HANDBOOK.md#2-installation-and-launch) for details.

### Launch

From the root of this repository, on macOS or Linux:

```bash
cd icoda
./icoda.bash
```

On Windows, in Command Prompt:

```bat
cd icoda
icoda.cmd
```

To open a project immediately, pass its absolute path from the `icoda/` directory:

```bash
./icoda.bash /absolute/path/to/project
```

```bat
icoda.cmd "C:\path\to\project"
```

The launcher creates `.icoda-venv`, installs ICODA's Python dependencies, and starts the application.
This virtual environment keeps ICODA's packages separate from other Python projects; manual activation is not
required. The Bash launcher also attempts to install missing system prerequisites through a supported package
manager. Windows reports missing prerequisites for you to install.

### Create or Open a Project

For a new project, choose **File > New Project...**, select an empty directory, and complete the Specification
editor. Select the language in **Code Profile**, validate the specification, and save. ICODA creates missing
skeleton files and moves into the architecture phase. Follow the build instructions, then choose
**File > Reload**.

For an existing project, start from a committed working tree and choose **File > Open Project...**. Python source
is analysed without importing or executing it. C++ analysis needs the compiler settings in `compile_commands.json`.
For a CMake project with a `debug` preset and a Ninja or Makefiles generator, run these commands in that project:

```bash
cmake --preset debug -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build --preset debug
```

ICODA looks for the newest compile database at the project root, in `build/`, or one directory below `build/`,
such as `build/debug/`. Reload after generating it. Use **Project > Choose libclang Library...** if library
discovery needs adjustment.

Existing CMake projects without ICODA state start in the implementation phase. Existing Python projects without
ICODA state start in the specification phase; saving their first specification may add missing skeleton files.
See [Starting a project](HANDBOOK.md#3-starting-a-project) before bringing an existing codebase into the workflow.

### Select a Coding Agent

Install and authenticate the provider CLI before generating a proposal. In the **LLM** panel, select its executable
in **Binary** and choose or enter a **Model**. Provider calls use your existing CLI authentication.

The shipped registry enables **Claude Code** and **Codex CLI**. Templates for Gemini CLI and other providers are
present but disabled until qualified. See [LLM selection](HANDBOOK.md#6-llm-selection) for custom paths and provider
configuration.

## Development Workflow

1. **Specify:** describe the purpose, scope, use cases, testable requirements, decisions, and coding conventions.
2. **Design:** request a bounded architecture proposal. Review the model delta, source diff, and build/test
   results; approve, reject with feedback, or adapt it. Approve the architecture explicitly when it is ready.
3. **Plan:** select the next implementation target or use the bottom-up queue, which places callees before callers.
   Review and approve the proposed approach.
4. **Implement and verify:** request code and tests. Inspect the isolated proposal and confirm API signature
   changes when required. Build and test gates must pass before approval.
5. **Commit and continue:** approval repeats build and test checks in the project, commits the accepted change,
   and advances the queue. Review coverage and remaining work before starting the next step.

A **gate** is an enforced checkpoint: a failing result blocks progress. Passing build and test gates means the
configured checks passed; it does not prove that every requirement or edge case is covered.

Optional **Auto-approve while gates pass** applies to eligible implementation code proposals. Architecture,
implementation approaches, and unconfirmed signature changes still need your decision.

## Project Data

ICODA keeps project-specific information under `.icoda/` in the project being developed:

| Files | Purpose |
|---|---|
| `specification.json` | Formal specification and Code Profile |
| `state.json`, `steps.jsonl` | Workflow state, implementation queue, and decision history |
| `layout.json` | Cluster names and pinned file assignments |
| `cache/`, `ui.json`, `icoda.log` | Derived model cache, local UI choices, and diagnostics |
| `worktree/` | Isolated checkout for the current proposal |

The specification, workflow records, and layout are normally versioned; local caches, UI settings, logs, and the
proposal worktree are ignored. The first proposal can initialize a Git repository and create the starting commit.
Review [Git, persistence, and recovery](HANDBOOK.md#10-git-persistence-and-recovery) for manual edits, undo, and
interrupted proposals.

## Status and Limitations

ICODA is currently version **0.1.0**. C++ and Python workflows are implemented, with native launchers for Linux,
macOS, and Windows. The committed [release matrix](docs/RELEASE_MATRIX.md) qualifies Linux; it does not yet record
full macOS or Windows qualification.

The specification editor validates structure and references, but does not yet run an AI-guided requirements
interview. Many Code Profile rules are advisory. Test coverage in the GUI represents recorded test provenance and
call reachability, not measured statement or branch coverage. C++ proposal gates currently expect `debug` build
and test presets. Known scaling issues and feature gaps are tracked in the [gap analysis](docs/GAP_ANALYSIS.md).

## Documentation

| Guide | Contents |
|---|---|
| [Illustrated PDF handbook](output/pdf/ICODA-Handbook.pdf) | Full user and maintainer guide with 32 screenshots |
| [Handbook source](HANDBOOK.md) | Searchable Markdown edition and editable source |
| [Design](EVOLUTION.md) | Architecture, concepts, and intended behavior |
| [Implementation plan](ICODA_PLAN.md) | Development milestones and their history |
| [Lifecycle simulation](docs/SIMULATION.md) | A complete developer-controlled workflow and its evidence |
| [Gap analysis](docs/GAP_ANALYSIS.md) | Implemented capabilities, remaining gaps, and performance findings |
| [Release matrix](docs/RELEASE_MATRIX.md) | Platform qualification and its limits |
| [Verification log](docs/VERIFY_LOG.md) | Detailed verification history |

## Development

Run contributor commands from `icoda/`. After the launcher has created the virtual environment, install the
development dependencies and run the full verification gate:

```bash
.icoda-venv/bin/python -m pip install -e '.[dev]'
./verify.bash
```

On Windows:

```bat
.icoda-venv\Scripts\python.exe -m pip install -e ".[dev]"
verify.cmd
```

The verifier runs whitespace checks, Ruff, mypy, byte compilation, provider qualification, the C++ sample build
and CTest, pytest with an 85% coverage threshold, fresh analysis, and real-Tk GUI acceptance. Run it after code or
GUI changes. GUI checks need a display; on headless Linux the verifier uses `xvfb-run` when available.

Each run retains command logs, JUnit results, coverage reports, environment details, GUI state, and screenshots in
`.icoda-test-artifacts/<run>/`. The `LATEST` file identifies the newest run. Inspect affected screenshots as well
as test results when reviewing GUI changes.

For a focused unit-test run without a display:

```bash
ICODA_TK_STUB=1 .icoda-venv/bin/python -m pytest -q
```

Some tests additionally require the built C++ sample and toolchain. Provider qualification checks installed CLI
compatibility without consuming model usage:

```bash
.icoda-venv/bin/python -m icoda_core.provider_check \
  --output .icoda-test-artifacts/provider-qualification.json
```

Real-provider acceptance consumes model usage and is separate from the standard verifier. Commands for it, the
full lifecycle simulation, and performance testing are in the [maintainer guide](HANDBOOK.md#12-maintainer-guide).

The desktop shell is [icoda.py](icoda.py). Core logic lives in [icoda_core/](icoda_core/), reusable Tk widgets in
[icoda_gui/](icoda_gui/), and verification scripts and tests in [tests/](tests/). Keep workflow and analysis
decisions in the core so they can be tested independently of the GUI. Follow the repository's
[contribution guidelines](../CLAUDE.md) and include relevant verification evidence with changes.

## License

ICODA is released under the [MIT License](../LICENSE). Copyright 2026 Helmut Hlavacs.
