# Getting started with ICODA

This is the short path: install, make one small project, get the first step from the agent, approve it. It takes
about half an hour the first time. The [handbook](../HANDBOOK.md) explains every control; this page only says what
to do next. Inside ICODA, the sentence above the buttons in the lower panel says the same thing at every moment.

## 1. Install

You need Python 3.10 or newer with Tkinter, Git, and a coding agent's command-line tool that is installed and
logged in: **Claude Code** (`claude`) or **Codex CLI** (`codex`). For C++ projects you also need CMake 3.28 or
newer, Ninja and Clang; on macOS install LLVM with `brew install llvm` because Apple's Clang cannot build C++20
modules with CMake. For Python projects nothing else is needed.

ICODA never installs system packages, requests administrator privileges, or contacts package indexes when it
starts. Install missing system prerequisites yourself; when a launcher finds one, it prints the exact command to
run and exits when that prerequisite is required. Then prepare the pinned Python environment explicitly from the
`icoda` directory of the repository:

```bash
cd icoda
python3 -m venv .icoda-venv
.icoda-venv/bin/python -m pip install -e '.[dev]' -c constraints.txt
./icoda.bash
```

On Windows, use Command Prompt:

```bat
cd icoda
py -3.12 -m venv .icoda-venv
.icoda-venv\Scripts\python.exe -m pip install -e ".[dev]" -c constraints.txt
icoda.cmd
```

`constraints.txt` records the exact versions used to develop ICODA while `pyproject.toml` defines the supported
version ranges. Repeat the corresponding `pip install` command after either file changes. The launchers only
validate Python, Tkinter, system tools, and this prepared environment before starting ICODA; they do not modify
the machine or environment.

For a non-editable wheel installation, first prepare the pinned dependencies above, then use the offline-tested
wheel path:

```bash
.icoda-venv/bin/python -m pip wheel --no-deps --no-build-isolation -w dist .
.icoda-venv/bin/python -m pip install --no-deps dist/icoda-0.1.0-py3-none-any.whl
.icoda-venv/bin/icoda
```

The wheel includes the entry module, packages, provider registry, and schemas. The `--no-build-isolation` and
`--no-deps` flags prevent this path from contacting a package index; they assume the pinned bootstrap is complete.

If the window does not open, look at **Troubleshooting** (`docs/TROUBLESHOOTING.md`); the log file is named there.

## 2. Choose the agent

In the **LLM** box on the right, choose the agent's command in **Binary** (`claude` or `codex`; a full path works
too) and a **Model**. The hint under the boxes tells you when ICODA does not know the binary. The agent's tool
must already be logged in — ICODA never asks for keys or passwords.

## 3. Make a new project

**File ▸ New Project…** (Ctrl+N, ⌘N on macOS), choose an empty folder. The specification window opens. Fill in:

- **Overview**: a title and two or three sentences about what the program does.
- **Scope**: goals (one per line), what is not in scope, what is not allowed (libraries, techniques), and when
  the project is done.
- **Use cases**: things a user does with the program, one per entry. Fill in the fields and press **Add**.
- **Requirements**: testable statements. Give each a priority and the use cases it belongs to.
- **Decisions**: choices that are already made, so that the agent does not reopen them.
- **Code profile**: use C++23 with C++20 modules for the handbook examples; choose the test framework and size limits.

Every field has a tooltip with an example: rest the pointer on its label. A small first project needs one use
case, three requirements and no decisions. Press **Save** (Ctrl+S / ⌘S). ICODA writes the project skeleton and
asks whether to build it now — answer **Yes**. The build runs in the background; when it is done, the analysis of
the skeleton appears in the **File View** and the project is in the *architecture* phase.

If you answered No: **Project ▸ Build** (Ctrl+B / ⌘B) does the same later. The hint above the buttons reminds you.

## 4. The first step

Leave the **Request** field empty (the agent then chooses the most useful step) or write what the next step
should do, for example `Add the Inventory class with add and remove`. Press **Propose** (Ctrl+Return / ⌘Return).

The lower panel shows a moving bar and what ICODA is doing: asking the agent, building the proposal in a separate
worktree, running the tests, parsing the result. This takes one to three minutes. **Cancel** stops it; nothing is
recorded then.

Provider subprocesses cannot edit the checkout: Codex uses `--sandbox read-only`, and Claude disables its edit,
write, notebook-edit and Bash tools. ICODA validates the structured reply before applying it in the worktree.
`MAX_RESPONSE_BYTES` is enforced before JSON parsing; lone Unicode surrogates, NUL bytes in candidate paths, unsafe
paths, and a `response.apply_changes` symlink escape are refused.

When the proposal is ready, ICODA switches to the **Call View** with the new entities marked. Read:

- the rationale on the left;
- **Diff** — the exact change;
- **Delta** — which classes and functions are added or changed;
- **Build** and **Tests** — the output of the checks.

Then decide:

- **Approve** takes the change into the project and makes one Git commit.
- **Reject…** asks for a reason; the agent gets it with the next request.
- **Adapt…** asks again with your constraints (or with the edits you made in the **Summary** tab).

If the proposal did not build or its tests failed, the title says so and the tabs show the output. Reject or adapt
it, or edit the worktree yourself and choose **More… ▸ Rebuild**.

A function longer than the hard 50-line function limit is also refused at proposal time. ICODA repeats the same
`_quality_refusal` at approval time, so split the function and propose again; the 30-line value remains an advisory
guideline for functions no longer than 50 lines.

## 5. From architecture to implementation

Repeat step 4 until the skeleton has the classes and functions the specification asks for (they stay stubs). Then
press **Approve architecture**. ICODA builds the implementation queue: every stub function, in a sensible order.

In the *implementation* phase each function takes two rounds: **Propose approach** asks the agent how it would
implement the current target (prose only); **Approve approach** accepts that; **Propose** then asks for the code
and its tests. The queue label above the buttons names the current target and how many are left. **Auto-approve
while gates pass** lets ICODA continue on its own while build and tests pass; it pauses at the first failure and
tells you why.

## 6. Everyday things

- **File ▸ Reload** (Ctrl+R / ⌘R) analyses the project again, for example after you edited files yourself. ICODA
  also reloads when the window regains focus after a change.
- **Undo last step** reverts the last approved step with a new commit; the history stays.
- **More… ▸ Commit manual edits** records your own edits as a manual step. A proposal starts only from a clean
  tree, so ICODA offers this itself when needed.
- **Project ▸ Test Command…** sets the command that every proposal must pass (`ctest --preset debug` by default
  for C++; the Code profile's test runner for Python).
- **Help ▸ Open Log File** opens `.icoda/icoda.log`, the first place to look when something is odd.

Everything ICODA writes lives in the project's `.icoda/` folder: the specification, the derived model, the step
log and the proposal worktree. The rest is ordinary Git history.

## Where to go next

- **Tutorial** (`docs/TUTORIAL.md`): the complete C++ Score Clamp example, from specification through reviewed implementation, CTest, and a running executable.
- **Handbook** (`HANDBOOK.md`): every view, control and file, plus the maintainer material.
- **Troubleshooting** (`docs/TROUBLESHOOTING.md`): the problems people actually meet, and their fixes.
