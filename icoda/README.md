# ICODA — Interactive Code Development and Analysis

Step-by-step, developer-in-the-loop code development with a live architecture view. The design is in
`EVOLUTION.md`, the build plan in `ICODA_PLAN.md`.

Run it with `./icoda.bash [project-directory]` on macOS and Linux, or `icoda.cmd [project-directory]` on Windows.
The launcher picks a Python 3.10+ with Tkinter, creates the virtual environment `.icoda-venv`, installs the
dependencies and starts `icoda.py`.

The application is `icoda.py`; the supporting code lives in the packages `icoda_core/` (no Tk) and `icoda_gui/`
(the larger Tk widgets: the specification editor). Tests run with
`ICODA_TK_STUB=1 python -m pytest` and need no display.

For development, install the declared tools into the launcher environment, then run the complete verification gate
after every code or GUI change:

```bash
.icoda-venv/bin/python -m pip install -e '.[dev]'
./verify.bash
```

On Windows use `verify.cmd`. Each run retains timestamped command logs, JUnit and coverage reports, environment
metadata, the ICODA analysis log, fitted and zoomed File View and Call View screenshots, and a populated proposal
Delta and Source diff screenshot under `.icoda-test-artifacts/`; the `LATEST` file names the newest run.

Provider qualification is local and does not consume model usage. It records installed paths, versions, the exact
help command, and whether every configured invocation option is present:

```bash
.icoda-venv/bin/python -m icoda_core.provider_check \
  --output .icoda-test-artifacts/provider-qualification.json
```

The explicit M2 real-provider acceptance does consume model usage and therefore stays outside `verify.bash`. Give
it a new output directory each time. It generates a project from a specification, requests one architecture step,
checks the source diff and parsed call graph, approves and commits it, undoes it, then rebuilds, tests, re-analyses,
and proves the project is clean:

```bash
.icoda-venv/bin/python tests/real_provider_acceptance.py \
  --provider codex --model gpt-5.6-sol \
  --output .icoda-test-artifacts/real-provider-codex-YYYYMMDD-HHMMSS
```
