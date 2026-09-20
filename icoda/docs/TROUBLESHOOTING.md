# Troubleshooting

## Automatic recovery and the Prompt tab

The **Prompt** tab is available whenever a project is open, including before any error occurs. Choose an enabled
**Binary/Model**, type a message, and click **Send** (Command/Control-Return). Send supports questions and read-only
inspection. It is disabled for an empty message or while another operation is running. **Open CLI** opens an
interactive session with the conversation and your unsent prompt for edits using the provider's normal approvals.
**Retry step** and **Details** require a failed operation and stay disabled during ordinary conversations.

ICODA attempts recovery before displaying an operational failure. While it works, the status reads
**Trying automatic recovery**. Provider requests receive one read-only retry. When Codex explicitly reports
that its CLI is too old for the selected model, ICODA checks the selected executable's installation and tries
its supported updater (Homebrew for a Codex cask, otherwise `codex update` when supported), then retries the
same model and request once. App-bundled executables are never overwritten. Cancel stops the active process.

Failed proposals get one additional corrective request in their existing worktree. ICODA reruns the ordinary
build, tests, analysis, and phase checks; only a passing candidate can be approved. Project build/test repairs
use an isolated architecture candidate when a committed baseline exists. Existing uncommitted project or
candidate edits are preserved. ICODA does not invent an approved implementation approach, reset corrupt
workflow state, or commit manual edits as an automatic repair. Analysis failures trigger a rebuild and reanalysis.
Other failures receive a CLI investigation when a project and provider are available. Attempts are bounded so
persistent failures cannot create an endless loop.

If recovery cannot finish, the **Prompt** tab opens with a plain-language diagnosis and recovery
result. **Details** reveals the diagnostic evidence. Use **Send** for a conversation with the selected CLI;
the conversation includes the failure and previous messages and permits read-only investigation. You can
select another installed **Binary/Model** if the failing provider cannot respond. Common credential forms are
redacted from the conversation context.

Use **Open CLI** for an interactive session in the affected project or candidate worktree, with the failure
context and the provider's normal approvals, when edits or login are needed. Return to ICODA and choose
**Retry step** to run the failed operation and its checks again. Selecting a different project clears the chat.


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

## The launcher refuses to start

The Bash launcher stops with `icoda: .icoda-venv is missing; run these commands from <icoda directory>:` when the
prepared environment does not exist. It stops with `icoda: the ICODA environment is incomplete; run this command
from <icoda directory>:` when ICODA or one of `clang.cindex`, `jsonschema` and `networkx` cannot be imported. The
Windows launcher reports the same two causes as `icoda: .icoda-venv is missing.` and `icoda: the ICODA environment
is incomplete.`. Launch does not install or repair packages automatically.

Create the environment, then install the checkout and its development dependencies with the versions pinned by
`constraints.txt`:

```bash
python3 -m venv .icoda-venv
.icoda-venv/bin/python -m pip install -e '.[dev]' -c constraints.txt
```

On Windows:

```bat
py -3.12 -m venv .icoda-venv
.icoda-venv\Scripts\python.exe -m pip install -e ".[dev]" -c constraints.txt
```

Run the commands from the `icoda` directory, then launch again. The complete procedure and prerequisites are in
[Getting started](GETTING_STARTED.md#1-install) and
[Installation and launch](../HANDBOOK.md#2-installation-and-launch).

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

Two refusals come from `steps.StepRunner._invoke_provider` before ICODA can use a reply:

- **`Gemini CLI (Google) is disabled; choose an enabled provider`**: the selected entry exists but its `enabled`
  setting is false. Choose Claude Code or Codex CLI, the enabled providers in the shipped registry; changing the
  binary path does not enable a disabled entry.
- **`Codex CLI (OpenAI) timed out after 1800 seconds`** followed by `If it asks for a login: run 'codex login'`:
  the provider process exceeded `PROVIDER_TIMEOUT`. Check its terminal output and login, then press **Propose**
  again. For Claude Code, run `claude` and log in; for Codex CLI, run `codex login`.

`python -m icoda_core.provider_check` checks installed CLI versions and required flags without making a model
request. It does not prove that a login is current. See [LLM selection](../HANDBOOK.md#6-llm-selection) for the
provider setup procedure.

## A proposal reply is refused before the build

**`the reply exceeds the 200000-byte size limit`** means `_payload_size` exceeded `MAX_RESPONSE_BYTES` before
`extract_json` searched for JSON. Nothing was applied. Narrow the **Request** to fewer files or a smaller atomic
step and press **Propose** again; if the provider still ignores the bound, choose another model.

The following messages mean the JSON was found, but `response.validate` refused text or a candidate path:

- `files/0/content: must contain valid UTF-8 text` identifies a lone Unicode surrogate. Ask the provider to return
  valid UTF-8 text and propose again.
- `files/0/path: must not contain a NUL byte` identifies a NUL in a path. Remove the NUL and use a normal project
  path.
- `files/0/path: must be relative to the project root` identifies an absolute POSIX or Windows path;
  `files/0/path: must not leave the project root` identifies `..`; and `files/0/path: may not touch git, build
  output or the .icoda folder` identifies protected output or metadata. Request a plain relative source or test
  path inside the project. The full error starts `the JSON object does not match the response schema:`.

**`could not apply the files: candidate path 'linked/escaped.txt' leaves the project root`** is the
`response.apply_changes` symlink-escape refusal. A lexically relative path resolved through a symlink outside the
proposal worktree, so ICODA stopped before writing or deleting it. Remove that candidate path or replace the
project symlink with a real in-project directory, then propose again. The safety boundary and review procedure are
described in [LLM selection](../HANDBOOK.md#6-llm-selection) and [The first step](GETTING_STARTED.md#4-the-first-step).

## The build fails

**Project ▸ Build** and every proposal run the build gate: `cmake --preset debug` followed by `cmake --build
--preset debug` for C++. For Python, ICODA discovers project source roots and runs `python -m compileall -q -x
<excluded paths> <source roots>`; it does not assume that source is under `src`. The output is in the **Build** tab
and in the Prompt tab after recovery has been attempted (the full text is in the log).

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
`llvm` on Linux). If `clang.cindex` is missing from the prepared environment, repeat the pinned install command
from [Getting started](GETTING_STARTED.md#1-install).

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

**`LineGate.classify is 51 lines; split it below the hard maximum of 50.`** shows the exact refusal form. It is a
required quality refusal, not an advisory issue. `StepRunner._quality_refusal` calls `rules.promotion_refusal`
after the proposal is parsed, and approval calls `_quality_refusal` again so an altered or stale over-limit
candidate cannot be promoted. Split the function into focused helpers, keep the original and every new function
at 50 source lines or fewer, add tests for the same behaviour, and propose again. The worked procedure is
[Worked example B](../HANDBOOK.md#worked-example-b-split-a-c-function-refused-by-the-50-line-gate).

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

If saving reports an error but `.icoda/state.json` is still intact and a `.state.json.*.tmp` file remains beside
it, `persistence._atomic_write_text` failed before `os.replace` and cleanup could not unlink the temporary file.
Correct the directory permissions, confirm `state.json` is the intact version you want, and remove only the
orphaned `.state.json.*.tmp` file. Do not replace the good state file with the orphan. See
[Corrupt state](../HANDBOOK.md#corrupt-state) for the recovery procedure.

## Keyboard shortcuts do nothing

The shortcuts use the Command key on macOS (⌘N, ⌘O, ⌘R, ⌘E, ⌘B, ⌘Return, ⌘S in the source or specification editor) and
Control elsewhere. They work when the ICODA window has the focus; inside a text box, ⌘Return / Ctrl+Return still
proposes.

## Source edits cannot be saved

The Source Editor keeps the buffer if saving fails and retries the file operation once before showing the
problem in Prompt. If the file changed on disk, copy any edits you need to keep before using **Reload**
to inspect the other version. ICODA will not overwrite that version automatically.

Wait for a running build or generation operation to finish before saving. Candidate worktree edits reset the
proposal's build and test results; run **Rebuild** before approval. Project edits stay uncommitted until you use
**Project > Commit Manual Edits**. The built-in editor opens UTF-8 text files up to 2 MiB; use an external editor
for other encodings or larger files.

## Verification (for maintainers)

`./verify.bash` runs the whole gate and writes its evidence under `.icoda-test-artifacts/`; the newest run is
named in `LATEST`. Read `summary.txt` first, then the failing check's `.log`. The handbook's maintainer guide
explains the gate.

**`FAIL real-provider: missing Codex credential: run 'codex login'`** means `codex login status` found no current
session; an expired login has the same result. Authenticate with `codex login` and rerun the gate. If a release is
deliberately qualified without that external check, run `./verify.bash --allow-missing-real-provider`: the
`real-provider` stage remains in `summary.txt` and `summary.json` with outcome `SKIP` instead of being omitted or
reported as passed. See [Required verification after every change](../HANDBOOK.md#required-verification-after-every-change)
for the full procedure.
