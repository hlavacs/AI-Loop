# ICODA — Interactive Code Development and Analysis

Step-by-step, developer-in-the-loop code development with a live architecture view. The design is in
`EVOLUTION.md`, the build plan in `ICODA_PLAN.md`.

Run it with `./icoda.bash [project-directory]` on macOS and Linux, or `icoda.cmd [project-directory]` on Windows.
The launcher picks a Python 3.10+ with Tkinter, creates the virtual environment `.icoda-venv`, installs the
dependencies and starts `icoda.py`.

The application is `icoda.py`; the supporting code lives in the package `icoda_core/`. Tests run with
`ICODA_TK_STUB=1 python -m pytest` and need no display.
