# ICODA — Interactive Code Development and Analysis

Status: design document, 2026-09-07. Supersedes the previous EVOLUTION.md; its AI-Loop backlog now lives in `AI_LOOP_BACKLOG.md`.

## Vision

ICODA is a new, standalone application that shares nothing with AI-Loop: no code, no files, no formats. Where a
batch runner like AI-Loop drives a coding agent unattended until a job is finished, ICODA keeps the developer in the
loop at every step. It always presents the software architecture visually, at various levels of detail, and it performs only one
specific step at a time. The developer keeps full control and builds up a gradually growing mind map of the system.

The details of function implementations are less important than the organisation of the code: data structures,
classes, types, derivations and, most importantly, which function calls which other function. ICODA is built around
that call graph.

## Decisions

These were settled on 2026-09-07 and the rest of the document assumes them.

**New standalone app that shares nothing with AI-Loop.** ICODA lives in its own subfolder `icoda/` of the
repository, beside `ai-loop/`, and is its own Python package; all paths in this document are relative to `icoda/`.
It does not import AI-Loop, does not copy code from it, and does not share files or formats with it; everything in
ICODA is written for ICODA. Unattended batch operation (job queues, e-mail commands, resumption after crashes) is
out of scope. The application is `icoda.py`, started through the launcher `icoda.bash` (see Program layout).

**The source code and the specification are the truth.** The specification says what the system must do; the source
code says what exists. ICODA keeps no architecture model of its own. The model it shows and reasons about is *derived*
from the code by libclang after every step, cached, and never edited by hand. Proposals are therefore code changes,
and what the developer approves is code. A manual edit made outside ICODA is legitimate and is picked up at the next
parse. What ICODA adds to the code is bookkeeping: which step introduced which entity, and which requirement of the
specification an entity serves.

**libclang for C++, from the toolchain.** C++ analysis uses libclang through `compile_commands.json`, which CMake
produces for free. On macOS the toolchain is Homebrew LLVM, because CMake cannot build C++20 modules with Apple's
clang; ICODA parses with the libclang that sits beside the compiler named in the compile commands. This resolves overloads, templates, member calls and lambdas properly, which lexical heuristics
cannot. ICODA uses the clang that is installed on the machine — the Visual Studio clang component on Windows, Xcode or
Homebrew LLVM on macOS, the distribution's LLVM on Linux — detects the candidates, lets the developer choose, and
builds the analysis configuration of the project with that same clang (`clang-cl` on Windows, which stays
ABI-compatible with MSVC and vcpkg), so that compiler and parser agree and C++20 modules resolve. The `libclang` pip
wheel is the fallback when no toolchain libclang is found. There is no heuristic fallback parser: when the project
does not compile, ICODA shows the last derived model and marks it stale.

**C++23 first, Python later.** The derived model, the step protocol and the views are language-neutral. The
generator, the code rules and the analysis ship end-to-end for C++23 first. Python follows as a second language
(milestone M5).

**C++20 modules are first-class from M1.** The derived model, the views and the generator treat a module interface
unit like any other module. Generated code always prefers modules: new projects are module-based, and headers are
used only where a library or a platform forces them (the Code Profile can override this per project). This is why
libclang comes from the toolchain: module files can only be read by the clang that built
them.

**Tkinter.** The GUI is Tkinter. The geometry code (circular layouts, member ring, zoom) in `icoda/views.py` is
GUI-independent; if the canvas becomes the limiting factor, that separation is what makes a later port to Qt
possible without touching the rest.

## Program layout

ICODA is a Python application with a shell launcher.

**`icoda.py`** is the application: the Tkinter main window, the panel with the views, the step loop and the wiring
between them. It is what the launcher executes. Supporting code lives in the packages `icoda_core/` (everything without Tk) and
`icoda_gui/` (the larger Tk widgets) next to it (a package cannot be called `icoda/` beside `icoda.py`: Python and
mypy would see two modules of one name), so that `icoda.py` itself stays within the code requirements of this
document instead of growing into one file:

| Module | Responsibility |
|---|---|
| `icoda_core/model.py` | derived model schema, USR identity, status bookkeeping |
| `icoda_core/toolchain.py` | finding and loading libclang, versions, the compiler's resource directory |
| `icoda_core/analysis.py` | parsing with libclang (shadow parse of module units), incremental cache, stale marking |
| `icoda_core/session.py` | opening a project end to end without a GUI: configuration, libclang, parse, clusters, layout |
| `icoda_core/clusters.py` | community detection, cluster pins, circle layout |
| `icoda_core/views.py` | File, Class, Call and mind-map geometry and presentation |
| `icoda_core/specification.py` | specification schema and validation (`specification.schema.json`), Code Profile, compact text form for prompts |
| `icoda_core/git.py` | git, worktrees, promotion with rollback |
| `icoda_core/process.py` | bounded subprocess with output limits |
| `icoda_core/steps.py` | worktree-based step protocol: propose (K attempts with feedback), approve, reject, adapt, undo, manual commits |
| `icoda_core/steplog.py` | `steps.jsonl` records and the function statuses derived from them |
| `icoda_core/generator.py` | step 0 skeleton, module-based code generation, Doxygen and `@satisfies` |
| `icoda_core/agent.py` | provider invocation from `providers.json`, rate-limit waiting |
| `icoda_core/prompt.py` | prompt assembly: Code Profile, compact specification, model subset around the step, phase rules, feedback |
| `icoda_core/response.py` | the agent's reply: JSON extraction, validation against `response.schema.json`, path rules, applying files |
| `icoda_core/persistence.py` | `.icoda/` files and the user configuration |
| `icoda_gui/spec_editor.py` | the specification editor: one page per section, numbered records, validation on save |
| `icoda_gui/provider_field.py` | the Binary/Model field whose model options follow the binary |
| `icoda_gui/step_panel.py` | the step panel: phase and request, proposal prose, delta and build output, the decision buttons |
| `icoda_gui/step_controller.py` | connects the step panel and the Call View to the step protocol; dialogs for reject and adapt |
| `icoda_gui/call_view.py` | the Call View canvas: columns per call depth, status colours, delta outlines, callers switch |
| `icoda_gui/tasks.py` | background work for the window with results delivered on the Tk thread |

**`icoda.bash`** is the launcher for macOS and Linux. It chooses a Python 3.10+ (`icoda_python.bash`), checks for
Tkinter, git, CMake, Ninja, a clang toolchain with libclang, and vcpkg — installing what it can through the package
manager and printing the manual command otherwise — creates or updates the virtual environment `.icoda-venv` with the
Python dependencies (the `clang` bindings matching the detected libclang, `networkx` for clustering, `jsonschema`
for the specification), and then runs `exec "$python_bin" icoda.py "$@"`. Redis is not checked; ICODA does not use it.

**`icoda.cmd`** is the Windows counterpart.

Command line: `icoda.bash` without arguments opens the last project; `icoda.bash <directory>` opens that project,
creating `.icoda/` if it is missing (Phase 0 for an empty directory, Phase 3 import for an existing CMake project).
No further options are planned.

## Core concepts

**Project.** A directory with a git repository, a CMake build and an `.icoda/` folder (see Persistence).

**Derived model.** A graph that ICODA extracts from the code. It is a cache of the truth, rebuilt after every step and
whenever ICODA notices that files changed; it is never the thing being edited.

Entities:

- *Module* — a logical unit: a C++20 module (the default for generated code) or, in imported code written with
  headers, a header/source pair. Either way it is one node in the views, expandable.
- *Namespace*.
- *Enum* — with all enumerators and their values.
- *Struct/Class* — data members with types, methods, base classes, template parameters.
- *Function* — free or member; signature (parameters with types, return type, qualifiers), Doxygen brief, body status.
- *Alias/Typedef* and *Constant/Define*.

Edges:

- *calls* — function → function, with the call site (file, line).
- *inherits* — class → base class.
- *contains* — module → entity, class → member.
- *uses-type* — function parameter or return, or data member → type.
- *includes/imports* — module → module (`#include` or `import`).

Identity is the libclang USR (Unified Symbol Resolution) of the entity; files are identified by path. Every function
has a status — `stub`, `implemented`, `tested` — that comes from the step log and the last test run, not from the
parser. The step log also records which step introduced an entity; a rename creates a new USR, so the step log records
rename pairs to keep the history attached. A function whose body was changed outside ICODA drops back from `tested`
to `implemented` until its tests pass again; the change is detected by a hash of the function's source text, stored
in the step log.

**Templates.** A template is one entity (`Stack<T>`), whatever types it is used with. The types seen at call sites
are kept as labels on the call edges and as a badge on the node, never as nodes of their own.

**Specification coverage.** Each entity's Doxygen comment may name the use cases or requirements it serves
(`@satisfies UC-3, R-12`). Through these tags ICODA links the code to the specification and shows which requirements
have no code yet and which code serves no requirement. This replaces the idea of "drift" between a model and the code:
with the code as truth there is nothing to drift from, only requirements that are not covered yet.

**Step.** The unit of work. A step is a proposal from the agent — rationale in prose and a code change — that the
developer decides on. Steps are numbered per project and form a linear history.

**Worktree.** Every step is generated in a git worktree of the project, using the worktree and promotion
helpers in `icoda_core/git.py`. ICODA builds and parses the worktree; the difference between the worktree's derived model and the current one
is the model delta shown to the developer. The delta is computed by ICODA, never claimed by the agent. Approving
promotes the worktree onto the working tree; rejecting discards it.

**Decision.** *Approve*, *reject* (with a reason), or *adapt* (edit the proposal or the prompt and run the step again).

**Session.** A sequence of steps in one phase, e.g. "architecture for the editor feature".

## Development cycle

### Phase 0 — Specification

When creating a new project, the developer writes a specification that is deliberately lean: title, description,
goals, what is not in scope, what must not be used (libraries, techniques), the conditions under which the project
is done, use cases (UC-n), requirements (R-n, with a priority and the use cases they serve) and decisions already
taken (D-n) — ICODA's own `specification.schema.json`, entered through the specification editor, six pages with a
tooltip example on every field. ICODA adds a **Code Profile** to the
specification: language and standard, the code requirements below, the library policy, target platforms, build layout.
The specification is stored in `.icoda/specification.json`, is committed, and is sent, compacted, with every step
prompt. It is one of the two truths and can be changed at any time; a change shows up as uncovered requirements.

What the system does with the specification is not to implement it. It lays out a plan, an architectural overview, and
it does not start with the whole architecture, which would be overwhelming, but with a first simple step.

### Phase 1 — Architecture

Goal: empty shells of structs, classes and functions, but complete enums and other defines, with the full call graph
from `main()` downwards. The project compiles, runs and can be debugged after every single step.

**Step 0 is always the same:** the project skeleton. `CMakeLists.txt` with `CMakePresets.json` (Debug and Release),
`main()`, the folder layout, `build.sh` and `build.cmd`, `.gitignore`, `vcpkg.json`, a `Doxyfile`, a CTest target with
one smoke test. The skeleton is module-based: `main()` imports a first, empty module, so that the module build
(CMake with Ninja and the toolchain's clang) is proven to work before any architecture step. The skeleton must build and run before the first architecture step is proposed.

**Atomic step.** One concept and its immediate collaborators: a handful of structs, classes, enums or functions, not
many. Budget: at most 5 new entities per step (configurable), any number of edges among them and to existing entities.
A step must leave the project compiling. Steps are ordered top-down, starting from `main()` and following the use cases
of the specification; the agent proposes the next step, and the developer can instead ask for a specific one
("introduce the renderer now").

**What goes into the code in this phase.** One C++20 module per concept, with an exported interface; headers only
where a library or platform forces them. Declarations with full signatures. Empty bodies, with one exception: calls
to other functions, and the construction of the structs and class instances they need, so that the call graph is real,
compiled code rather than a comment. Value-returning stubs return a default (`{}`). Enums are complete. Every entity
carries a Doxygen comment with its `@satisfies` tags. Function parameters evolve as later steps require them. No
algorithmic code. Because there is no control flow yet, the skeleton encodes *who may call whom*, not *when*; running
it walks the happy path from `main()` through empty functions, which is what makes it debuggable.

**Decision protocol.**

- A proposal is shown only once it compiles in its worktree. If the agent cannot make it compile within K attempts
  (default 3, each attempt fed the compiler output), the step is shown as failed together with the errors and the
  developer decides.
- *Approve*: the worktree is promoted onto the working tree, the smoke test runs, and one git commit
  `icoda(arch) step N: <title>` is created that includes the step log entry. The derived model is rebuilt.
- *Reject*: the reason is recorded and included in the next prompt; the worktree is discarded and the agent proposes
  a different step.
- *Adapt*: the developer edits the prompt, or edits the structured summary of the proposal (entity names, members,
  signatures, edges), which ICODA turns into hard constraints for the next attempt, or edits the code in the worktree
  directly in the editor, after which ICODA rebuilds and re-parses it. All three can be combined.
- *Undo*: any approved step can be undone. ICODA reverts the commit. History is linear, so later steps have to be
  undone first.

**Phase end.** The developer marks the architecture as approved. New architecture sessions can still be opened later
(Phase 3).

### Phase 2 — Implementation

After the architecture has been approved, ICODA fills in the missing implementations, based on the functions present.
One function per step; every step is approved, rejected or adapted by the developer. A step may cover several
functions only in simple cases that span a few lines in total, such as a getter/setter pair or a small overload set.

**Order.** Bottom-up over the call graph by default, leaves first, so that each function can be tested the moment it
is implemented. The developer can pick any function from the views instead.

**Each step.**

1. The agent presents one or two proposals in prose before showing any source code: the approach, which STL
   algorithms and containers or which libraries it would use, an estimated line count, the trade-offs.
2. The developer chooses one, adapts it (writes or edits the prompt) or rejects both, in which case the agent must
   generate new proposals.
3. The agent produces the function body and a unit test for it (doctest or Catch2 through CTest) in a worktree. A
   change to the function's signature is shown separately in the delta, because it changes the architecture, and
   needs an explicit confirmation.
4. ICODA builds the worktree and runs the tests.
5. The developer approves: promotion, commit `icoda(impl) step N: <qualified function name>`, status becomes
   `implemented`, and `tested` when the test passed.

**Batching.** To avoid click fatigue on a project with hundreds of functions, the developer can select a class, a
cluster or "all leaves" and enable *auto-approve while build and tests pass*. Every function is still its own step and
its own commit, and appears in the views for review afterwards. A rejected proposal or a failing test stops the batch.

**Implementation rules.** Functions minimise their line count by using modern C++23. Lambdas where they make sense.
STL wherever possible; prefer STL algorithms to hand-written loops. Templates for code reuse where it makes sense. When
an open-source library lowers the line count significantly, the agent proposes it in the prose proposal and the
developer decides; libraries are added through the vcpkg manifest, single-header libraries are vendored (see Code
requirements).

### Phase 3 — Existing projects and later changes

Import: the developer points ICODA at an existing CMake project. libclang derives the model from the code; all
functions start as `implemented`, no tests are assumed, and a specification can be written afterwards or left empty.
From then on the same loops apply to changes: a change request ("add undo to the editor") is added to the
specification, opens an architecture session (new entities, edges and stubs, one atomic step at a time) and is
followed by an implementation session. This is how ICODA is used after a project's first version, and how it is
applied to code that was never created with it. Manual edits between sessions need no ceremony: they are code, and
code is the truth. The only bookkeeping is the status: a hand-edited function loses `tested` until its tests run again.

## Architecture visualization

The core of ICODA is the dynamic visualization of the project. In a large panel the developer chooses the granularity
level and which aspect is shown.

| Level | What is shown | Expands into |
|---|---|---|
| Project | clusters as circles, inter-cluster relations | Cluster |
| Cluster | files on the circumference of the cluster circle, relations between files | File |
| File | classes, structs, enums, free functions of the file | Class |
| Class | members with types and signatures, relations between members | Function |
| Function | signature, Doxygen text, callers and callees, source | — |

Behaviour common to all views: zoom with the mouse wheel centred on the cursor, pan by dragging; a click expands a node one level in place; a double click opens the source location in the
developer's editor; hovering shows the Doxygen brief; a right click offers *propose the next step here* (Phase 1),
*implement this function* (Phase 2) and *run the tests of changed functions*. Filters by cluster, namespace and edge type. A stale model (code changed since
the last parse) is marked as such in every view. Specification coverage can be switched on: entities without a
`@satisfies` tag and requirements without any entity are highlighted. In Phase 2 functions are coloured by status
(`stub`, `implemented`, `tested`). Everything not connected to the current selection is dimmed.

Types and functions from external libraries — the standard library and vcpkg packages — are shown as one *external*
node per library (`std`, `fmt`, …). Edges to it show what the project uses; expanded, the node lists the used types
and functions, but it has no internals and takes part in no cluster.

### File View

Nodes are source files; a header/source pair is one node. If a file calls functions of another file, or contains
structs or classes derived from structs or classes of another file, this constitutes a relationship between the files.

Relationships are arrows. Direction: from the file that uses to the file that is used, i.e. `A → B` means A depends
on B. This is the UML convention and matches the direction of `#include`; the earlier draft had it the other way
round, and the convention is fixed here so that all views agree.

| Relationship | Colour |
|---|---|
| include / import | grey |
| call | blue |
| inheritance | green |
| uses-type / composition | orange |

Several relationships between the same pair of files merge into one arrow with a small badge per type.

**Clusters.** Relationships between files create clusters of related files. A file belongs to exactly one cluster.
Clusters are computed by community detection on the undirected, weighted dependency graph (label propagation first;
Louvain if the result is not stable enough), seeded by directory so that the initial clustering follows the folder
structure. Connected components are *not* used: in a real project everything is transitively connected to `main()` and
the whole project would collapse into one circle. The developer can pin a file to a cluster and rename clusters; the
assignments are stored in `.icoda/layout.json` so that they stay stable between runs and steps.

**Layout.** Each cluster is arranged on a circle with its files on the circumference, ordered so that strongly related
files are neighbours (fewest crossing chords). The circle is geometry only and is never drawn; the cluster name sits
in its empty centre. A cluster with a single file has that file at the centre and no circle at all. Cluster circles are placed on a ring, or by a force layout weighted with the
inter-cluster relations. At project level the arrows between clusters run from centre to centre, with the thickness
showing the number of relations; zooming into a cluster draws the individual arrows between files. A circle holds
about 40 files at most; a larger cluster is split by the algorithm. The view is zoomable, every file is clickable and
reveals more and more detail: clicking a file expands it in place into its Class View.

### Class View

Nodes are the structs, classes, enums and aliases of one file, one cluster or the whole project. Edges:

| Relationship | Drawing |
|---|---|
| inheritance | solid line, hollow triangle at the base class |
| composition (data member of class type) | solid line, filled diamond at the owner |
| uses (parameter or return type) | dashed line |
| calls between methods, aggregated per class pair | blue, thickness = number of calls |

A collapsed class shows its name and its counts (data members, methods, lines). An expanded class shows its members
with types and signatures; members that call each other are placed on a ring inside the class panel with callers and
callees adjacent. Enums show all their
enumerators. Template classes show their template parameters and a badge with the types they are used with. Selecting a class highlights its complete neighbourhood
and dims the rest.

### Call View

The function-level call graph, rooted at `main()` or at any selected function. A depth slider limits how far the graph
is expanded; a switch shows callers instead of callees; the path from `main()` to the selected function is
highlighted; recursion is drawn as a loop; a call into a template function carries the concrete type as a label on the edge
(`push (Circle)`). This is the view that shows "which function calls which", and it is the view
ICODA opens for a proposal to show what the step would add: new entities highlighted, changed signatures marked.

### Mind map

A persistent overview of the whole project as a tree — clusters, files, classes, functions — with the status colours,
the requirements each entity satisfies, and, for every entity, the step that introduced it. It grows with every
approved step; this is the "gradually increasing mind map" of the system, and it is the place to go back to a step and
see what it changed and which requirements it covered.

## Code analysis

**C++.** libclang via `compile_commands.json` (`CMAKE_EXPORT_COMPILE_COMMANDS=ON` in the presets). Per translation
unit ICODA extracts declarations and definitions with their USR, base classes, members with types, template parameters,
call expressions together with the referenced declaration (this resolves overloads, template calls, member calls and
lambdas; virtual calls are attributed to the static target and marked as dynamic), includes, and the Doxygen comment
with its `@satisfies` tags. Module interface and implementation units are parsed like any other translation unit,
and `import` relations become includes/imports edges. Parsing is incremental: only translation units whose files or included headers changed
since the last run are re-parsed, decided by content hash, and parsed units are cached under `.icoda/cache/`. ICODA
re-parses after every step and whenever it notices changed files (on focus, or through a file watcher). When the
project does not compile, ICODA keeps the last derived model and marks it stale.

**libclang location and version.** At start-up ICODA looks for libclang in the usual toolchain locations — on Windows
`VC\Tools\Llvm\x64\bin\libclang.dll` of the Visual Studio clang component or an LLVM installation, on macOS the Xcode
toolchain or Homebrew's `llvm`, on Linux the distribution's `llvm-*` packages — plus a path set by the developer, and
falls back to the `libclang` pip wheel. The Python bindings must match the library's major version; ICODA ships
bindings for the supported LLVM majors, checks the version at start-up and refuses a mismatch with a clear message
rather than failing later. The version is recorded in `.icoda/cache/`, and a change invalidates the cache. Templates
are one entity each; the template arguments seen at a call site are recorded on the call edge.

**Python (later).** An `ast`-based parser produces a derived model in the same schema.

**Rule checks** are computed from the derived model and shown as issues in the views: function line counts, member counts per class, functions with many parameters,
entities without Doxygen comments, entities without `@satisfies` tags, platform-specific API use without a portable
wrapper.

## Agent integration

Every step in ICODA is carried out by an LLM through a command-line binary, in a non-interactive invocation, one
invocation per step or per proposal round. Which binary and which model is a field in the GUI (see *LLM binary and
model* below); it is set per project and can be changed before any step.

The prompt contains the Code Profile, the compacted specification, the relevant subset of the derived model (the
clusters touched by the step and their neighbours, not the whole model, to keep prompts small on large projects), the
step request, and the rejections and adaptations recorded for this step so far.

The response is structured JSON validated against a schema — rationale and files, as full contents or unified diffs —
(`icoda_core/response.schema.json`); an invalid response is fed back with the validation error
for a remake. ICODA applies the files in the worktree, builds and parses; the model delta the developer sees is
computed from the parsed result, so the agent cannot misdescribe what it did. When a provider reports a rate limit,
ICODA waits for the replenishment time it names and retries instead of failing the step.

### LLM binary and model

The step panel has two fields. **Binary** is a combo box listing the supported command-line agents; it is editable,
so a full path (`/opt/homebrew/bin/claude`) or an unlisted binary can be typed. **Model** is a combo box offering the
two best models available for the chosen binary, the first one preselected; it is editable too, so any other model
ID the binary accepts can be typed. Choosing a different binary swaps the model options to that binary's two models
and preselects the first, unless the developer had typed a custom model for that binary earlier in the session, in
which case that one is restored. The selection is saved per project in `.icoda/ui.json` (the binary path is
machine-specific), the default for new projects in the user configuration, and every record in `steps.jsonl` notes
the binary and model that produced the step.

The list ships as data, `icoda_core/providers.json`, so that it can be updated without touching code: for each binary its
command, the argument template for a one-shot invocation, the model flag, and its two models. "Two best" means the
vendor's most capable model and its strongest runner-up as the vendor describes them, checked at every ICODA release
and stamped with the date. The launcher checks that the chosen binary is on `PATH` and prints its login hint when a
call fails with an authentication error.

| Binary | Command | One-shot invocation | Two models (checked 2026-09-07) |
|---|---|---|---|
| Claude Code (Anthropic) | `claude` | `claude -p --model <m> …` | `claude-fable-5-1` (Fable 5.1), `claude-opus-5` (Opus 5) |
| Codex CLI (OpenAI) | `codex` | `codex exec -m <m> …` | `gpt-6-astra` (GPT-6 Astra), `gpt-5.6-sol` (GPT-5.6 Sol) |
| Gemini CLI (Google) | `gemini` | `gemini -m <m> -p …` | `gemini-3.1-pro-preview` (3.1 Pro), `gemini-3.8-flash` (3.8 Flash) |
| OpenCode (open source, any provider) | `opencode` | `opencode run -m <provider/m> …` | `anthropic/claude-fable-5-1`, `openai/gpt-6-astra` |
| Aider (open source, any provider) | `aider` | `aider --model <m> --message …` | `anthropic/claude-fable-5-1`, `openai/gpt-6-astra` |
| GitHub Copilot CLI | `copilot` | `copilot -p … --model <m>` | GPT-6 Astra, Claude Fable 5.1 (IDs as listed by `/model`) |
| Qwen Code (Alibaba) | `qwen` | `qwen -p … -m <m>` | `qwen3-coder-plus`, `qwen3-coder-flash` |

Every invocation template is verified against the installed binary before it is enabled in the list (M2). Binaries that route to many providers (OpenCode, Aider) take provider-prefixed model IDs, which is why their
two entries name the same frontier models through a prefix.

## Persistence

Inside the project, `.icoda/` holds `specification.json` (committed); `steps.jsonl`, the step log (committed so that
the history travels with the code; one record per step with phase, request, proposals, decision, commit hash, USRs
added or changed, status changes, rename pairs); `layout.json` (cluster names and pins, committed); `cache/` (derived
model and parsed translation units, ignored by git) and `ui.json` (view state, ignored by git). ICODA's own settings
and the list of known projects live in the user's config directory.

Every approved step is exactly one git commit. ICODA requires a clean working tree before a step so that a step never
mixes with manual edits; uncommitted manual edits are committed first, as `manual edit`, on the developer's request.

## Code requirements

The line count of each function is limited to 30, with a hard maximum of 50. If this cannot be achieved, the function
is cut into smaller functions. Structs, classes and functions focus on a single purpose. The number of data and
function members of each class is limited to keep it simple and understandable; guideline: at most 10 data members and
15 methods, flagged in the views when exceeded, not blocked. Every entity carries a Doxygen comment. Violations are
shown as issues and are included in the next step prompt so that the agent corrects them.

### Code requirements C++

- C++23. Prefer modern concepts: composability, pimpl, facade, templates.
- Always prefer C++20 modules over headers. Generated code is module-based; a header is used only where a library
  or a platform forces it. Third-party headers are wrapped once in a module of their own (`import fmt;` style via
  a small wrapper module or the library's own module if it ships one).
- The analysis (Debug) preset builds with the toolchain's clang (`clang-cl` on Windows) so that compiler and parser
  agree; Release builds may use MSVC or GCC.
- Always prefer platform independence; target Windows, macOS and Linux. No platform API without a portable wrapper.
- CMake as baseline with `CMakePresets.json` for Debug and Release; `build.sh` and `build.cmd` on top of it.
- Build artefacts land in `build/`, executables and libraries in `bin/`.
- Libraries through vcpkg in manifest mode (`vcpkg.json`). vcpkg builds from source and caches the binaries, so
  binary caching is kept enabled; there is no download of prebuilt binaries. Single-header libraries are the
  exception: they are vendored under `third_party/`.
- Tests with a single-header framework (doctest or Catch2) through CTest; every implemented function has a test.
- Doxygen configuration in the repository; every entity documented, with `@satisfies` tags where a requirement applies.
- Assume GitHub; `.gitignore` excludes all dynamic files: `build/`, `bin/`, `vcpkg_installed/`, `.icoda/cache/`,
  `.icoda/ui.json`, IDE and OS files.

## Non-goals

Unattended operation, e-mail control, parallel jobs on several providers, Redis, systemd sandboxing. A full IDE: ICODA
has no editor of its own and jumps to the developer's editor instead. Languages other than C++ and Python. ICODA is
not used to develop ICODA for the time being.

## Further decisions (2026-09-07)

Answers to the open questions of the first draft; all of them are folded into the text above.

- A header/source pair, or a C++20 module, is one node.
- C++20 modules are first-class from M1, and generated code always prefers modules over headers.
- One entity per template; concrete types appear as labels on call edges and as a badge on the node.
- External libraries are one *external* node each.
- An implementation step may cover several functions only in simple cases spanning a few lines, such as a
  getter/setter pair or a small overload set.
- Specification links are `@satisfies` tags in the Doxygen comments.
- A hand-edited function drops from `tested` back to `implemented` until its tests pass again.
- libclang comes from the toolchain — the Visual Studio clang component, Xcode or Homebrew LLVM, the distribution's
  LLVM — chosen flexibly by the developer; the analysis build uses the same clang; the pip wheel is the fallback.
- ICODA is not used to develop ICODA for the time being.
- ICODA is implemented in `icoda.py` (with the `icoda_core/` package) and started by `icoda.bash` (`icoda.cmd` on Windows).
- One repository, two subfolders: AI-Loop in `ai-loop/`, ICODA in `icoda/`; `.github/`, `.gitignore`, `CLAUDE.md`
  and `LICENSE` at the root are the only things they have in common.
- ICODA shares nothing with AI-Loop: no code, no files, no formats. Everything is written for ICODA, including its
  own specification schema and editor. There is no heuristic analyzer fallback, libclang only.
- Every step is carried out by an LLM chosen in a Binary/Model field: seven command-line agents (Claude Code, Codex
  CLI, Gemini CLI, OpenCode, Aider, GitHub Copilot CLI, Qwen Code), two best models each, shipped as
  `providers.json`; the model options follow the chosen binary.

## Roadmap

| Milestone | Content |
|---|---|
| M1 App skeleton | The `icoda/` subfolder; `icoda.py`, `icoda.bash` and `icoda.cmd`; Tkinter shell; libclang detection; import of an existing CMake project via libclang (headers and C++20 modules); derived model schema; File View with clusters and coloured arrows. |
| M2 Architecture loop | Phase 0 with ICODA's own specification editor and the Code Profile; step 0 module-based skeleton generation; worktree-based step protocol with approve/reject/adapt and undo; Call View. |
| M3 Implementation loop | Proposals in prose; function and test generation; bottom-up order; batching; status colours. |
| M4 Class View and coverage | Class View; specification coverage; rule checks; mind map. |
| M5 Python | Derived model from an `ast`-based parser; Python Code Profile; Python generation. |
