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
