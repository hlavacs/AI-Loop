# ICODA implementation plan

Status: active, baseline verified 2026-09-09. Companion to `EVOLUTION.md`, which is the design; this file says in which order it gets
built, how each step is verified, and what I need from you. Answer inline with `A:` where a question is open.

## Decisions taken today for the plan

- The coding agent writes the code milestone by milestone; you review each milestone by running its manual
  acceptance checks and reporting what you observe.
- One repository, two subfolders: AI-Loop was moved into `ai-loop/` on 2026-09-07 (history kept), ICODA is built
  in `icoda/`, where this plan and `EVOLUTION.md` already live. The connected folder stays the same; all paths in
  the milestones are relative to `icoda/`.
- ICODA shares nothing with AI-Loop: no imports, no copied code, no shared files or formats. Everything is written
  for ICODA, including its own specification schema and editor.
- There is no heuristic fallback parser; libclang only. When a project does not compile, the last derived model is
  shown and marked stale.
- Every step is carried out by an LLM chosen in the Binary/Model field; the seven binaries and their two models each
  ship as `providers.json`.
- C++20 module projects on macOS use Homebrew LLVM. ICODA first selects the libclang beside the project compiler;
  without a built project, Homebrew libclang precedes Xcode and Command Line Tools candidates. Apple's version
  numbers differ from LLVM's, so ICODA carries a small mapping table and a start-up self-test.
- The first test subject is a small sample C++ project that I write (about 15 files, CMake, C++20 modules, clusters,
  templates, lambdas). Your own C++ project becomes the acceptance test when you name it.

## Working method

Every step below ends with *verify:* — the check that says the step is done (the goal-driven rule from `CLAUDE.md`).
Automated tests run on Linux CI and locally on macOS; visual Tkinter behavior and real-provider workflows also get
manual acceptance. Each accepted step is one commit on `develop`. The plan is small-step by design: if a step turns
out to need more than about a day of work, it is split rather than stretched.

After every code or GUI change, run `./verify.bash` (`verify.cmd` on Windows). The gate must pass before the change
is accepted. It retains timestamped command logs, JUnit and branch-coverage reports, environment metadata, the
project analysis log, nonblank, unclipped File View and Call View screenshots at fitted and zoomed scales, and a
populated proposal Delta and Source diff screenshot in `.icoda-test-artifacts/`.
The proposal evidence also includes separate Build- and Tests-tab screenshots.

Conventions: pytest with a Tk stub (`ICODA_TK_STUB=1`) so the GUI is testable headless; GitHub Actions CI on Ubuntu
with clang, CMake and Ninja installed; MIT licence; Python 3.10+; `ruff` and `mypy` clean; every function within the
30/50-line rule of `EVOLUTION.md`, since ICODA should obey the rules it imposes.

## Verified baseline and completion order

**Baseline, macOS 2026-09-09:** the development environment is installed from `.[dev]`; 127 tests pass with no
skips, `ruff check .`, `mypy icoda.py icoda_core icoda_gui` and byte-compilation are clean. The sample project builds
and its CTest smoke test passes with Homebrew LLVM 22.1.4. Headless ICODA analysis selects the matching Homebrew
libclang 22.1.4 and reports no errors. Module-building tests use the generated `build.sh`, so they exercise the same
toolchain selection as a real ICODA project.

**M2 accepted on the Mac, 2026-09-09:** the local, non-generative qualification checked Claude Code 2.1.191 and
Codex CLI 0.152.1 against their configured help options; unavailable CLIs remain disabled. The explicit Codex
`gpt-5.6-sol` acceptance generated and prepared a project from a valid specification, returned a one-entity proposal
on its first attempt, built and parsed it, verified the source diff, specification tags and call edge, approved and
committed it, undid it, rebuilt and tested the restored source, re-analysed it, and finished with a clean tree.

Work continues in this dependency order:

1. Complete M3: two-round approach then code/test proposals, explicit signature-change confirmation, targeted tests
   and safe per-function batching that stops on the first failure.
2. Complete M4: Class View and common view interactions, specification coverage, rule checks included in prompts,
   and the persistent status/requirements/step mind map.
3. Specify and complete M5: Python identities and uncertain dynamic calls first, then the AST parser, generator,
   project/test integration and a Python acceptance project.
4. Qualify a release on macOS, Linux and Windows, including clean installation, recovery paths, large-project
   performance, migration, documentation and a versioned acceptance matrix.

Every item is a gate: its automated tests and stated manual acceptance must pass before work starts on the next item.

## M1 — App skeleton, core helpers, import, File View

Progress 2026-09-07: steps 1–9 implemented and tested in the VM (clang 18 built from the LLVM release tarball,
CMake and Ninja from pip); step 10 is the launcher as written in step 1. Two findings worth knowing: libclang
does not visit declarations inside `export`, so module units are parsed through a shadow copy with the module
keywords blanked (offsets preserved; USRs match); and the package is `icoda_core/` because a package named
`icoda/` cannot sit beside `icoda.py`. Mac spike result (2026-09-08): CMake cannot build C++20 modules with Apple's clang at all — its
`Compiler/AppleClang-CXX.cmake` never defines module scanning, whatever `clang-scan-deps` it is given. The macOS
toolchain for ICODA is therefore Homebrew LLVM (`brew install llvm`): `build.sh` selects it automatically, and
ICODA parses with the libclang beside the compiler named in `compile_commands.json`. Apple's libclang also
needs `-fcxx-modules` to recognise `import`, which the parser adds for Apple libraries.

**M1 accepted on the Mac, 2026-09-08:** `mac_check.sh` → sample built with Homebrew LLVM 22, `icoda.bash` shows
the File View with 13 files, 88 entities, 260 relations, 7 clusters, no parse errors, fitted to the window. What it
took beyond the VM: `-isysroot` from `xcrun --show-sdk-path` (CMake 4 omits it), `-fprebuilt-module-path` when
compile commands carry no module flags, `-nostdinc++ -isystem <prefix>/include/c++/v1` so libclang uses the
compiler's own libc++ (it cannot find it by itself and mixed in the SDK's copy), LLVM's `clang` bindings instead of
the `libclang` wheel, the shadow parse kept as a module interface unit (module renamed in place), and the analysis
in a child process so a libclang failure cannot take the window down.

1. Scaffold in `icoda/`: `pyproject.toml` (name `icoda`; dependencies `clang`, `networkx`, `jsonschema`; dev: pytest,
   ruff, mypy), `icoda.py` with the main window and an empty panel, the `icoda_core/` package with one stub module per
   row of the Program layout table in `EVOLUTION.md`, `icoda.bash`, `icoda_python.bash`, `icoda.cmd`, `.gitignore`,
   a short `README.md`, `tests/` with the Tk stub, and a second job in the root `.github/workflows/ci.yml` with
   working directory `icoda`. The licence is the repository's.
   *verify:* `icoda.bash` opens an empty window on your Mac; `pytest` is green in the VM and in CI.
2. Core helpers, written new with their tests: `icoda_core/git.py` (run git, create and remove worktrees, status, promote
   a worktree's changes onto the working tree with rollback when a copy fails half-way), `icoda_core/process.py`
   (subprocess with timeout, bounded output and process-tree kill), the provider invocation part of `icoda_core/agent.py`
   (command templates from `providers.json`, rate-limit detection and waiting), a hover tooltip for the GUI, and
   `icoda_python.bash` (pick a Python 3.10+ with Tkinter).
   *verify:* tests in the VM for promotion rollback on a mid-copy failure, output truncation, argv of the three
   first-class binaries, and rate-limit parsing; `grep -ri ai_loop icoda_core/ icoda.py tests/` finds nothing.
3. Sample project `tests/sample_project/`: CMake with `CMakePresets.json` and Ninja, C++20 modules (`.cppm`), one
   wrapper module around a "third-party" header, complete enums, two small class hierarchies, a template (`Stack<T>`)
   used with two types, a lambda passed to an STL algorithm, a free-function cluster, `main()` calling into all of it.
   This is also the spike for the module build with Apple clang: if it does not build on your Mac with the Xcode
   toolchain, we know on day two, not in M2.
   *verify:* builds with clang + Ninja in the VM and in CI; **you** build it on your Mac with `build.sh` and report.
4. libclang detection (`icoda_core/analysis.py`): candidates on macOS (Xcode toolchain, Command Line Tools, Homebrew
   `llvm`), Windows (Visual Studio LLVM component, LLVM installer, PATH), Linux (`llvm-config`, `/usr/lib/llvm-*`),
   the environment variable `ICODA_LIBCLANG`, then the pip wheel; Apple-clang → LLVM mapping table; start-up
   self-test (parse a one-line translation unit, read the version); result shown in the status bar and in the
   launcher output.
   *verify:* unit tests with a fake filesystem for every platform branch; on your Mac the status bar names the Xcode
   libclang and its version.
5. Derived model (`icoda_core/model.py`): entity and edge types from `EVOLUTION.md`, USR identity, JSON round trip for the
   cache, the status structure fed from `steps.jsonl`.
   *verify:* round-trip tests; schema documented in the module docstring.
6. Parsing (`icoda_core/analysis.py`): per translation unit from `compile_commands.json` — declarations, definitions,
   bases, members, template parameters, call expressions with the referenced declaration and the template arguments
   as edge label, includes and imports, Doxygen comment with `@satisfies`; incremental cache keyed by content hash;
   stale marking when the project does not compile.
   *verify:* tests against the sample project assert known facts: `main → Renderer::draw`, `Stack<T>` is one entity
   with two label variants on its edges, `std` is one external node, the enum has all enumerators, the `@satisfies`
   tag of one function is read; a deliberately broken copy of the sample yields the previous model marked stale.
7. Clusters (`icoda_core/clusters.py`): weighted undirected file graph; seeded label propagation (own implementation,
   directory as seed) with `networkx` for the graph; split clusters above 40 files; pins and names from
   `layout.json`.
   *verify:* deterministic tests; every file in exactly one cluster; a synthetic 300-file project with everything
   reachable from `main()` yields more than one cluster.
8. File View (`icoda_core/views.py` for geometry, `icoda.py` for the canvas): one circle per cluster, files on the
   circumference ordered for few crossings, arrows coloured by type with merged badges, thick centre-to-centre
   arrows at project zoom, zoom and pan, hover tooltip, click expands a file into its class list (placeholder until
   M4), double click opens the editor, external nodes.
   *verify:* geometry tests without Tk; you open the sample project on your Mac and see the clusters and arrows.
9. Persistence (`icoda_core/persistence.py`): `.icoda/` created on open, `layout.json`, `cache/`, `ui.json`; user config
   with known projects, last project, the libclang choice and the default binary and model.
   *verify:* tests; reopening the sample project restores the view.
10. Launcher hardening: `icoda.bash` checks Python, Tkinter, git, CMake, Ninja, a clang toolchain with libclang and
    vcpkg; installs what it can; creates `.icoda-venv` with the Python dependencies.
    *verify:* runs on your Mac from a clean clone; runs in the VM.

Milestone acceptance: `icoda.bash tests/sample_project` on your Mac shows the cluster circles with coloured arrows,
zoomable, and the status bar names the Homebrew libclang matching the compiler in `compile_commands.json`.

## M2 — Architecture loop

Progress 2026-09-09: step 1 done (`icoda_core/generator.py`; the skeleton builds, runs and analyses on macOS and in the VM). Step 2
done: `specification.schema.json`, `icoda_core/specification.py` (validation with readable problems, cross
references, ids, compact text for prompts) and the editor `icoda_gui/spec_editor.py`; File → New Project… opens the
editor for an empty directory, and saving the specification of a project without code writes the step 0 skeleton
(git init and the step 0 commit follow with step 4). Project → Specification… edits it later. Step 3 done:
`response.schema.json` + `icoda_core/response.py` (JSON extraction from prose or fences, schema and path rules,
applying files), `icoda_core/prompt.py` (role, Code Profile + compact specification, model subset = focus files
plus neighbours, phase rules, rejections/constraints/compiler output/validation error, response format), and
the Binary/Model field `icoda_gui/provider_field.py` in the side panel (options follow the binary, last model
per binary remembered, saved in `.icoda/ui.json` and as the default in the user configuration). The local
`provider_check` command now qualifies installed CLIs without making a model request and retains JSON evidence;
Claude Code and Codex are compatible, while the five unavailable CLIs remain disabled.
Step 4 done: `icoda_core/steps.py` + `steplog.py` — one persistent worktree `.icoda/worktree` (its `build/`
survives between steps), `prepare` (git init, build + parse, step 0 commit), `propose` (K attempts fed with the
validation error or the compiler output; the delta comes from parsing the worktree), `approve` (promote, rebuild,
log, one commit `icoda(<phase>) step N: <title>`), `reject` (reason into the next prompt), `rebuild` after manual
edits in the worktree, `undo` (revert commit), `commit_manual_edits`; statuses stub/implemented/tested from the
log. End-to-end test with a scripted provider and real builds passes in the VM. Step 5 done: the window has a
views notebook (File View, Call View: columns per call depth, status colours, green/orange outlines for a
proposal's new and changed entities, depth spinner, callers switch, root from the entity list), a step panel at
the bottom (phase, request, max entities; Propose, Approve, Reject…, Adapt…, Rebuild, Open worktree, Undo,
Commit manual edits) driven by `icoda_gui/step_controller.py` with the slow parts in a worker thread; Project
menu entries mirror the buttons. Proposal review has separate Delta, Source diff, Build and Tests tabs; the diff is computed
from the actual worktree and includes untracked additions. The architecture entity budget counts new modules,
types/aliases, callables and global variables from the parsed delta; an over-budget result becomes feedback for the
next attempt, and the Delta tab shows the count. `tests/real_provider_acceptance.py` additionally exercises a real
Codex call and retains the prompt, raw output, source diff, build logs, parsed delta, step logs and Git history. It
passed the complete create/propose/review/approve/undo/rebuild/re-analyse sequence on macOS on 2026-09-09.

1. Spike first: the step 0 skeleton generator (`icoda_core/generator.py`) emits a module-based CMake project with
   presets, `build.sh`/`build.cmd`, `vcpkg.json`, `Doxyfile`, a CTest smoke test and `main()` importing an empty
   module; the sample project's CMake setup is the template.
   *verify:* the generated skeleton builds and runs on your Mac and in CI.
2. Phase 0: the specification schema (`icoda_core/specification.schema.json`: title, summary, objectives, scope,
   stakeholders, assumptions, constraints, dependencies, use cases, requirements, decisions, risks, verification,
   open questions, Code Profile) and the specification editor (`icoda_gui/spec_editor.py`): one page per section,
   list editing for use cases, requirements, decisions, risks and verification, a Code Profile page, validation with
   `jsonschema` on save, load and save of `.icoda/specification.json`.
   *verify:* a specification saved from ICODA validates against the schema and reloads unchanged; Tk-stub tests of
   every page.
3. Agent integration (`icoda_core/agent.py`): `providers.json` with the seven binaries, their invocation templates and
   their two models (table in `EVOLUTION.md`); the Binary/Model field with model options that follow the binary;
   prompt assembly (Code Profile, compact specification, model subset, step request, prior rejections and
   adaptations); `response.schema.json` (rationale + files); validation with error-fed remake; rate-limit waiting.
   *verify:* argv tests for all seven templates, checked against the installed binaries' `--help` where available
   (unverifiable ones stay disabled in the list); a Tk-stub test that switching the binary swaps the model options
   and restores a typed custom model; tests with a scripted fake provider; prompt size measured on the sample project.
4. Step protocol (`icoda_core/steps.py`) on `icoda_core/git.py`: worktree per step, apply files, configure and build, parse,
   compute the delta, at most K attempts with compiler output; approve promotes, commits and appends to
   `steps.jsonl`; reject records the reason; adapt via prompt, structured summary or manual edit in the worktree;
   undo reverts the last step.
   *verify:* end-to-end test in a temporary git repository with the fake provider: three steps approved, one
   rejected, one undone, history linear, working tree clean.
5. Proposal panel in `icoda.py`: rationale, delta list, diff, the four buttons, the Binary/Model field.
   *verify:* Tk-stub tests of the wiring; a real-provider run on the Mac creating a small project from a
   specification, with retained review and undo evidence.
6. Call View: rooted graph, depth slider, callers switch, path highlight, recursion loop, template labels; opened
   for each proposal with the added entities highlighted.
   *verify:* geometry tests; manual.

## M3 — Implementation loop

Progress 2026-09-09: the state foundation is complete. Phase transitions are persisted in `steps.jsonl` and restored
in the GUI. `icoda_core/implementation.py` selects non-test stubs bottom-up, collapses recursive cycles and resolves
ties deterministically. Libclang analysis records SHA-256 hashes of exact callable bodies and associates conventional
test sources transitively through the production call graph. Approved records retain those hashes, associations and
separate compilation/CTest outcomes; `tested` requires all four facts to remain valid. Manual source commits are
re-parsed and explicitly downgrade affected callables. Generated Bash and Windows build scripts expose an internal
`build-only` mode, and proposal review shows independent Build and Tests tabs. Unit, parser, generated-project,
worktree, GUI and screenshot acceptance coverage is part of the standard verification gate. The translation-unit
cache schema is versioned so pre-M3 caches are invalidated and rebuilt with callable hashes.

1. Bottom-up order over the call graph (leaves first, cycles broken deterministically); "pick this function" from
   the views.
2. Two-round steps: prose proposals, then function body plus test (doctest through CTest) in a worktree; signature
   changes shown separately and confirmed.
3. Status bookkeeping: `stub` / `implemented` / `tested` in `steps.jsonl`; body hash; drop to `implemented` on manual
   edit; "run tests for changed functions".
4. Batching: class, cluster or all leaves with auto-approve while build and tests pass; stop on failure.
5. Few-line multi-function steps (getter/setter pair, small overload set).
   *verify (all):* fake-provider tests on the sample project covering order, approval, batching stop, and status
   transitions; manual run on your Mac implementing the sample project's stubs with Claude Code.

## M4 — Class View, coverage, rules, mind map

1. Class View with the edge table from `EVOLUTION.md`, collapse/expand, member ring.
2. Specification coverage: `@satisfies` index, uncovered requirements, untagged entities, highlighting in all views.
3. Rule checks as issues: function lines 30/50, members 10/15, many parameters, missing Doxygen, missing tags,
   platform API without wrapper; included in the next prompt.
4. Mind map tree with status, requirements and introducing step.
   *verify:* tests per feature on the sample project; manual on your Mac.

## M5 — Python

An `ast`-based Python parser producing the derived model, a Python Code Profile, Python generation. Planned after M4
has been used on a real project of yours; not detailed yet.

## Risks and how the plan handles them

- Apple clang and C++20 modules: decided 2026-09-08 — CMake has no module scanning for AppleClang, so macOS builds
  use Homebrew LLVM (`brew install llvm`); `build.sh` and the generated projects select it when present. Apple's
  clang remains fine for header-based projects. `import std;` stays unused; the standard library is included in
  the global module fragment, as the sample does.
- Apple libclang and the Python bindings: the mapping table plus the start-up self-test catch a mismatch on the first
  run; the pip wheel remains the fallback for header-based code.
- Writing the core helpers new: worktree promotion with rollback and bounded subprocess handling are the two places
  where subtle bugs hide; both get their tests in M1 step 2 before anything is built on them.
- Tk canvas performance: the 300-file synthetic project in M1 step 7 is also the performance test for the File View;
  the geometry code stays GUI-independent so a Qt port would touch only the canvas layer.
- Prompt size on large projects: measured in M2 step 3 on the sample and, once you name it, on your project.
- Windows (`icoda.cmd`, Visual Studio clang detection) can only be verified on a Windows machine; scheduled as a
  review round after M2, on your Windows machine.

## Open questions

- Which editor should a double click open? A: (default taken 2026-09-08) VS Code with `code --goto` when it is on the PATH, otherwise the system opener; a template can be set in the user configuration (`editor`).
- Test framework for generated C++ tests: doctest (single header, vendored) or Catch2 (vcpkg)? Recommendation: doctest. A: (default taken 2026-09-08) doctest.
- Which provider for the first end-to-end run in M2: Claude Code, Codex or Gemini? A: Codex CLI with `gpt-5.6-sol`
  (accepted 2026-09-09; Claude Code was installed but not authenticated).

## What I need from you

- Run `icoda.bash` (and `build.sh` of the sample project) on your Mac at each milestone and report.
- Push after each milestone.
- Name your C++ project when you want the acceptance test on real code.
