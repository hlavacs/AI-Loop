# Tutorial: your first ICODA project

This linear tutorial assumes you have never used ICODA. You will create a Python formatter, analyse its generated
skeleton, approve its architecture, and approve one implemented function. Allow about 30 minutes; provider calls
take most of the time. For installation variants and prerequisites, keep [Getting started](GETTING_STARTED.md)
open. If any observed result differs from the one below, use [Troubleshooting](TROUBLESHOOTING.md) before continuing.

Provider titles and rationale are generated text and will vary. Button names, commands, phase names, gate labels,
and quoted refusal/status messages below are the implemented interface.

## 1. Install the pinned environment

Open a terminal in the repository's `icoda` directory and type:

```bash
python3 -m venv .icoda-venv
.icoda-venv/bin/python -m pip install -e '.[dev]' -c constraints.txt
```

On Windows Command Prompt, type:

```bat
py -3.12 -m venv .icoda-venv
.icoda-venv\Scripts\python.exe -m pip install -e ".[dev]" -c constraints.txt
```

`pyproject.toml` defines supported ranges; `constraints.txt` pins the versions used by this checkout. The three
launchers are `icoda.bash`, its sourced interpreter selector `icoda_python.bash`, and `icoda.cmd`. They check the
prepared environment and prerequisites, but never create the environment, install packages, elevate privileges, or
upgrade pip.

The tested wheel path is available when you need a non-editable installation. In an environment that already has
the pinned dependencies, these commands stay offline:

```bash
.icoda-venv/bin/python -m pip wheel --no-deps --no-build-isolation -w dist .
.icoda-venv/bin/python -m pip install --no-deps dist/icoda-0.1.0-py3-none-any.whl
.icoda-venv/bin/icoda
```

For this tutorial use the editable installation. Authenticate one enabled provider before launch: run `codex login`
or run `claude` and complete its login, then exit that CLI.

## 2. Launch and choose a project directory

On macOS or Linux, type:

```bash
project_dir="$(mktemp -d /tmp/icoda-formatter.XXXXXX)"
printf '%s\n' "$project_dir"
./icoda.bash
```

On Windows, create an empty folder, note its full path, and type `icoda.cmd`. The ICODA window opens with status
`No project open`. In the **LLM** box, set **Binary** to `codex` or `claude` and choose a **Model**. ICODA sends the
prompt over standard input. Codex runs with `--sandbox read-only`; Claude runs with
`--disallowedTools Edit,Write,MultiEdit,NotebookEdit,Bash`. ICODA, not the provider subprocess, applies a validated
reply inside `.icoda/worktree`.

Choose **File ▸ New Project…** and select the empty directory printed above (or the Windows folder). The status line
becomes `New project <directory-name>: write the specification and save it`, and the six-page Specification window
opens.

## 3. Write the specification

Enter exactly these values.

On **Overview**:

- Title: `Formatter`
- Description: `Normalize one line of text.`

On **Scope**:

- Goals: `trim leading and trailing whitespace`
- Not in scope: `file input`
- Not allowed: `third-party packages`
- Done when: `normalize has a passing unit test`

On **Use cases**, enter Title `Normalize a line` and Details `Return a line without surrounding whitespace.`, then
press **Add**. The list assigns `UC-1`.

On **Requirements**, add both records:

1. Title `normalize removes surrounding whitespace`, priority `must`, use cases `UC-1`.
2. Title `normalize has a unit test`, priority `must`, use cases `UC-1`.

They receive `R-1` and `R-2`. On **Decisions**, enter Title `Standard library only` and Why
`No dependency is needed.`, then press **Add**.

On **Code profile**, choose Language `Python`. Keep Test runner `python -m pytest`, Max function lines `30`, and
Hard max function lines `50`. The latter is a hard 50-line function limit: a touched function above 50 source lines
is blocked by `_quality_refusal` after proposal analysis and checked again by `approve` immediately before
promotion. It is not merely an Issues warning.

Press **Validate**. The message beside the buttons is `valid`. Press **Save**; it changes to `saved`, and a dialog
begins `Specification saved and the project skeleton written (5 files).` Press **Yes** at `Build it now?`.

The status temporarily reads `build passed — analysing the project …`. Analysis does not import or execute Python
source. When it finishes, **File View** contains `src/formatter.py` and `tests/test_formatter.py`, and the phase
label is `architecture`. You have now completed specification and first analysis.

## 4. Approve one architecture step

In **Request**, type:

```text
Add a stub normalize(value: str) -> str method to Formatter and its test shape; do not implement the method.
```

Press **Propose**. The lower hint reports the provider request, then the stable activities
`step 1: building the proposal`, `step 1: testing the proposal`, and `step 1: parsing the proposal`. ICODA accepts
only a structured reply. `MAX_RESPONSE_BYTES` is 200,000 bytes and is checked before JSON extraction or parsing;
validation refuses lone Unicode surrogates, NUL bytes in candidate paths, unsafe/absolute paths, and malformed
schema data. `response.apply_changes` resolves each destination and refuses a symlink escape from the worktree.

When the proposal appears, read **Delta**, **Diff**, **Build**, and **Tests**. The new method must remain a stub, and
the gate labels must say `Build: passed` and `Tests: passed`. If the title starts `Step 1: no usable proposal`, read
its exact reason and use **Adapt…**; repeat until the two gates pass. Press **Approve**. ICODA promotes the isolated
change, rebuilds and retests it in the project, records the step, and creates an
`icoda(architecture) step 1: ...` Git commit.

Press **Approve architecture**, then **Yes** at `Approve the architecture and begin implementation?`. The phase
label becomes `implementation`; the queue line starts `Current target:` and ends `— 1 remaining` for the new stub.

## 5. Approve the implementation approach

Press **Propose approach**. In the **Approach** tab, require this plan if the provider proposes anything broader:

```text
Return value.strip() and add a pytest test for both padded and already-clean strings.
```

Use **Adapt…** to send that constraint when necessary. A usable plan begins `Awaiting developer approval`. It is
prose only and has not changed any source file. Press **Approve approach**. The tab begins `Approved`, and the hint
ends `Press Propose to get the code and its tests.`

## 6. Approve one implementation step

Press **Propose**. ICODA writes the candidate only in `.icoda/worktree`, byte-compiles it, runs the configured
pytest identifiers, reparses it, and calculates the delta. Review the test and confirm that **Diff** contains the
small `strip()` implementation. Require `Build: passed` and `Tests: passed`; otherwise use **Reject…**, **Adapt…**,
or **More… ▸ Open worktree** followed by **More… ▸ Rebuild**.

Press **Approve**. ICODA repeats build and tests in the real project before committing. The queue now reads
`Implementation queue: empty — no unimplemented functions`. In **Coverage**, **recorded test reachability** means a
successful recorded test identifier can structurally reach an analysed callable through static call edges. It does
not claim assertion quality, runtime execution coverage, or branch coverage.

Persistence remains fail-safe during this workflow: `persistence._atomic_write_text` replaces `state.json` only
after the temporary contents are durable. If replacement and then cleanup unlink are both denied, the original
`state.json` remains intact and the accepted limitation is one orphaned `.state.json.*.tmp` beside it.

Maintainers can run `./verify.bash`; its ordered stages are diff check, Ruff, mypy, byte compilation, local provider
qualification, real-provider acceptance, C++ sample build/CTest, pytest with `--cov-fail-under=85`, fresh analysis,
and real-Tk GUI acceptance. The real-provider stage requires an authenticated Codex session or the explicit
`--allow-missing-real-provider` waiver, which records `SKIP` rather than omitting the stage.

You have completed the new-project path from pinned installation and first launch through analysis, specification,
architecture approval, and one approved implementation step. Continue with the three complete worked examples in
the [Handbook](../HANDBOOK.md#worked-examples), and return to [Troubleshooting](TROUBLESHOOTING.md) whenever a gate
or prerequisite differs from the observable results above.
