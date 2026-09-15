# Troubleshooting

The cases below are the ones that came up while using ICODA, with what to do. Almost every problem leaves a trace
in the log, so start there.

## Where the log is

Every project writes `.icoda/icoda.log` in its own folder; **Help ▸ Open Log File** opens it. Before a project is
open, ICODA logs beside its settings file: `~/Library/Application Support/ICODA/icoda.log` on macOS,
`%APPDATA%\ICODA\icoda.log` on Windows, `~/.config/icoda/icoda.log` on Linux (**Help ▸ About ICODA** shows both
paths). The log has one line per event with a timestamp: analysis start and end, every parsed unit, the steps of a
proposal, failures with their traceback, and — when the window stops answering — a dump of every thread's stack
(lines beginning with `watchdog:`).

When you report a problem, the last thirty lines of the log say more than a screenshot.

## The window looks frozen

ICODA does its slow work (analysis, the agent call, builds, tests) in the background and shows a moving bar in the
lower panel with what it is doing; the status line at the bottom says the same. A step with an agent call takes one
to three minutes, a C++ build of a larger project longer. If the bar moves, wait or press **Cancel**.

If nothing moves for more than five seconds, the window really is stuck. ICODA notices this itself and writes the
stacks of all threads into the log (`watchdog: the window has not answered for N s`). Wait a moment — a modal
dialog may be hidden behind the main window (look in the Dock or task bar) — then send the `watchdog:` block from
the log together with what you did last.

## The agent call fails

The step title says `Step N: no usable proposal — …` and the **Build**, **Tests** and **Reply** tabs show the
details. The usual causes:

- **`claude is not on the PATH`** (or `codex`): the agent's tool is not installed, or ICODA was started from an
  environment that does not see it. Type the full path of the executable into **Binary**.
- **The agent asks for a login**: run the tool once in a terminal (`claude` or `codex`) and log in there. ICODA
  uses that login.
- **Rate limit or quota messages**: ICODA waits as long as the message says and tries again, up to three times.
  If it still fails, wait and press **Propose** again later.
- **The reply is not valid JSON / does not follow the contract**: the agent answered in prose. ICODA sends the
  validation error back and asks again (three attempts). If every attempt fails, write a more precise
  **Request** or choose another model. The **Reply** tab shows exactly what came back.
- **Claude Code returns an error immediately**: check that the tool accepts the flags ICODA uses (`claude
  --help` must list `-p`, `--model`, `--output-format` and `--disallowedTools`; `python -m
  icoda_core.provider_check` tests this without spending tokens). ICODA sends the prompt through standard input,
  so a very long prompt is not the problem.

## The build fails

**Project ▸ Build** and every proposal run the build gate: `cmake --preset debug` followed by `cmake --build
--preset debug` for C++, `python -m compileall src` for Python. The output is in the **Build** tab and in the
error dialog (shortened; the full text is in the log).

- **`CMake 3.28 or higher is required`**: update CMake.
- **`clang-scan-deps` not found**, or errors about modules: the compiler must be able to build C++20 modules. On
  macOS install LLVM with `brew install llvm`; ICODA and the generated `build.sh` use it automatically. On Linux
  install Clang 16 or newer together with `clang-scan-deps`.
- **The cache was configured for another source directory**: delete `build/debug` (the generated `build.sh` does
  this itself) and build again.
- **The build works in the terminal but not in ICODA**: ICODA runs the build with the environment it was started
  with. Start `icoda.bash` from a shell where `cmake`, `ninja` and the compiler are on the `PATH`.

## The model is empty, or "no compile_commands.json found"

For a C++ project, ICODA needs the compile database that CMake writes when the project is built (the generated
presets switch it on). Press **Project ▸ Build**; if you built by hand, use `cmake --preset debug
-DCMAKE_EXPORT_COMPILE_COMMANDS=ON` and reload. ICODA looks at the project root, in `build/` and one level below
it, and takes the newest file.

**"no libclang found"**: ICODA needs the libclang library of a Clang installation to parse C++. **Project ▸
Choose libclang Library…** lists what it found; choose one, press **Apply**, and ICODA reloads the project with it
(no restart is needed). If nothing is listed, install LLVM (`brew install llvm` on macOS, `libclang-dev` or
`llvm` on Linux) or `pip install libclang` into `.icoda-venv`.

A Python project is analysed without a build, but a file with a syntax error contributes no entities until it is
fixed; the file list in the status line reports how many files have parse errors.

## "uncommitted changes in the project"

A proposal starts from a clean Git tree, so that Approve and Undo are exact commits. If you edited files yourself,
ICODA offers to commit them as a manual step. Answer **Yes**, or commit them in Git and press **Propose** again.
Files that Git ignores (`build/`, `.icoda/worktree`) do not count.

## Approve stays grey

The tooltip on the grey button says why. The common cases: the proposal did not build or its tests did not pass
(`Build:` / `Tests:` under the title must both say `passed`); the proposal changes function signatures and
**Confirm signatures** has not been pressed; a historical step from the Mind Map is shown instead of the live
proposal (press **Propose** for a new one).

**Tests: not run** means no test command ran. For C++ the default is `ctest --preset debug`; **Project ▸ Test
Command…** changes it. For Python, the **Test runner** in the Code profile (for example `python -m pytest`) is
used.

## Saving the specification is refused

The message at the bottom of the specification window names the page and the entry: `Use cases UC-1: title is
missing`, `Requirements R-2: unknown use case UC-9`. Records are added with **Add** after filling in the fields on
the right; a selected record is edited in place and **Add** starts a new one.

## A window is too tall or the buttons are hidden

Every window is sized to the screen it opens on and its buttons are placed first, so this should not happen
anymore. If it does, note the screen resolution and the window, and report it. Error dialogs are shortened to ten
lines; the full text is always in the step panel and the log.

## The demo or a project cannot be reopened

Look at the log for the last lines before the reopen. If the last line is `parsing <unit>`, the analysis child
crashed in libclang on that unit; choose another libclang library or exclude the unit. If the analysis reports
`leftover proposal worktree preserved at …`, a proposal was interrupted; the next **Propose** resets the worktree.
If `.icoda/state.json` is damaged, ICODA refuses to guess: restore it from Git (`git checkout .icoda/state.json`)
when it is committed there, otherwise fix the JSON by hand — the message names the field.

## Keyboard shortcuts do nothing

The shortcuts use the Command key on macOS (⌘N, ⌘O, ⌘R, ⌘E, ⌘B, ⌘Return, ⌘S in the specification editor) and
Control elsewhere. They work when the ICODA window has the focus; inside a text box, ⌘Return / Ctrl+Return still
proposes.

## Verification (for maintainers)

`./verify.bash` runs the whole gate and writes its evidence under `.icoda-test-artifacts/`; the newest run is
named in `LATEST`. Read `summary.txt` first, then the failing check's `.log`. The handbook's maintainer guide
explains the gate.
