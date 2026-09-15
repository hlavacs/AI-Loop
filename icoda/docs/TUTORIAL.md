# Tutorial: one small program, start to finish

This tutorial builds a tiny Python program with ICODA — a text formatter with two functions — from the
specification to implemented, tested code. It is the same project that ICODA's recorded lifecycle simulation
(`docs/SIMULATION.md`) and the introduction video use, so the screenshots in the handbook show exactly these
steps. Plan thirty to forty minutes; the agent calls take most of it.

What you type is shown in `code`; what ICODA shows is quoted. The agent's exact answers will differ from the ones
here — that is the point of reviewing them.

## 0. Before you start

Install ICODA and log in to your agent as described in **Getting started**. Start ICODA, and in the **LLM** box
choose `claude` (or `codex`) and a model. The status line at the bottom says `No project open`; the sentence above
the buttons in the lower panel says what to do: open or create a project.

## 1. The specification (10 minutes)

**File ▸ New Project…**, choose a new, empty folder, for example `~/projects/formatter`. The specification window
opens with six pages. Fill in only what follows; every field has a tooltip with an example.

**Overview**

- Title: `Formatter`
- Description: `A small library that normalizes lines of text, and a main program that prints the normalized
  form of a line with a "ready:" prefix.`

**Scope**

- Goals: `normalize a single line of text` and, on the next line, `print the normalized line from main`
- Not in scope: `reading files`, `configuration options`
- Not allowed: `third-party packages`
- Done when: `both functions are implemented and each has a passing test`

**Use cases** — fill in the fields on the right and press **Add**:

- Use case: `Normalize a line`; Details: `The caller passes a line with leading or trailing spaces and gets the
  trimmed line back.`

The entry appears in the list as `UC-1`.

**Requirements** — three entries, each with **Add**:

- `normalize returns the line without leading and trailing whitespace` — priority `must`, use cases `UC-1`.
- `main prints "ready: " followed by the normalized line` — priority `must`, use cases `UC-1`.
- `every public function has a unit test` — priority `should`.

They become `R-1`, `R-2`, `R-3`.

**Decisions** — one entry:

- Decision: `Use only the standard library`; Why: `The program is tiny; a dependency would cost more than it gives.`

**Code profile** — set Language to `Python`. ICODA fills in the Python defaults (standard `3.12`, test framework
`pytest`, test runner `python -m pytest`, test files `tests/test_<module>.py`, naming conventions). Leave them.

Press **Validate** — the bottom line says `valid` — then **Save** (Ctrl+S / ⌘S). ICODA writes the skeleton
(`src/`, `tests/`, `pyproject.toml`, a README) and asks whether to build it now. Answer **Yes**. For Python the
"build" is a byte-compilation check; it finishes in a second, the project is analysed, and the **File View** shows
the skeleton's files. The phase label reads `architecture`, and the hint above the buttons says: press Propose.

## 2. The architecture step (5 minutes)

Leave **Request** empty and **Max entities** at 5. Press **Propose** (Ctrl+Return / ⌘Return).

The lower panel shows the moving bar: `asking the agent for the next step (attempt 1 of 3)`, then `building the
proposal`, `testing the proposal`, `parsing the proposal`. After one to two minutes the **Call View** opens with
the proposed entities highlighted and the title reads something like

> Step 1: Add formatter architecture (attempt 1)

with `Build: passed` and `Tests: passed`. Look at the tabs:

- **Delta**: `service.Formatter`, `service.Formatter.normalize`, `service.main` — three entities added.
- **Diff**: a `class Formatter` with a `normalize` method that only has a docstring and `raise
  NotImplementedError` (or `pass`), and a `main` stub. Architecture steps add shape, not behaviour.
- **Prompt** and **Reply**: exactly what was sent and what came back, if you want to see it.

Suppose the agent added a second class you do not want. Press **Reject…** and type `Keep the public API smaller:
one Formatter class with normalize, and main`. The rejection is recorded, and the reason goes into the next
prompt. Press **Propose** again; the revised proposal should have the three entities above.

Press **Approve**. ICODA copies the change into the project, builds and tests it there, records step 1 in
`.icoda/steps.jsonl`, and commits it (`icoda(architecture) step 1: Add formatter architecture`). The File View
refreshes; `normalize` and `main` are grey stubs in the Class View.

The hint now says that the structure can be completed or approved. Our structure is complete: press **Approve
architecture** and confirm. The phase label changes to `implementation`, and the queue line reads

> Current target: service.Formatter.normalize — 2 remaining

## 3. Implementing `normalize` (5 minutes)

Implementation has two rounds per function. Press **Propose approach**. The agent answers in prose, shown in the
**Approach** tab:

> Replace the normalize stub with `return value.strip()`, keep the signature, and add
> `tests/test_service.py::test_normalize` covering spaces on both sides and an already clean line.

Expected entities and files are listed under it; no source has changed yet. This is the cheap moment to steer:
**Adapt…** with a constraint such as `also collapse inner runs of spaces` would ask again. We are happy: press
**Approve approach**.

Now press **Propose**. The agent writes the code and the test in the worktree; ICODA builds, runs the selected
tests and parses the result. The title reads

> Step 2: Implement Formatter.normalize (attempt 1)

with both gates passed. **Delta** shows the changed method and the added test function; **Diff** shows
`return value.strip()` and the new test; **Tests** shows pytest's output for the targeted test. Press **Approve**.
The queue advances:

> Current target: service.main — 1 remaining

and `normalize` turns green (tested) in the diagrams.

## 4. Implementing `main` (5 minutes)

The same two rounds: **Propose approach** — the plan is to call `Formatter().normalize` on the input and print
`ready: ` plus the result, with a test that captures the output — **Approve approach**, **Propose**, review,
**Approve**.

If a proposal fails its tests, the title says `Step 3: no usable proposal — the proposal tests fail`, the
**Tests** tab shows why, and the hint offers the ways out: **Reject…** with the reason, **Adapt…** with a
constraint, or edit the worktree yourself (**More… ▸ Open worktree**) and **More… ▸ Rebuild**. ICODA itself
already tried three times, feeding the failure back to the agent each time.

## 5. Done

The queue line reads `Implementation queue: empty — no unimplemented functions`, and the **Coverage** tab reports

> Test coverage: 4/4 callables covered · 0 uncovered

The **Mind Map** shows both functions with the step that introduced them and the requirements they satisfy; the
**Issues** tab lists any advice from the rule checks (errors first, warnings folded by rule). `git log` in the
project folder shows one commit per approved step plus the skeleton commit.

## What to try next

- **Undo last step** reverts step 3 with a new commit; `main` is a stub again and back in the queue.
- Edit `src/service.py` in your editor, switch back to ICODA: it notices the change and reloads; a tested
  function whose body changed drops back to *implemented* until a step tests it again.
- **Auto-approve while gates pass**: on a project with a longer queue, ICODA runs approach and code rounds on its
  own and pauses at the first failed gate, telling you why in the hint line.
- Start a C++ project: choose `C++` in the Code profile. The skeleton is a CMake project with C++20 modules and
  doctest; **Project ▸ Build** runs `cmake --preset debug` and the build for you.
