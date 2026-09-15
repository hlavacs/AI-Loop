# Screenshot capture plan

No screenshot is captured or copied in the present task. This plan fixes the states, commands, and output names for the rendering task. All demo values are synthetic; title bars, paths, logs, emails, and job text must be checked for private data before use.

## Display probe

The probe was executed from the worktree root in the same shell environment used for the tool checks on 2026-09-15:

```text
DISPLAY=:10.0
WAYLAND_DISPLAY=<unset>
XDG_SESSION_TYPE=x11
```

`wmctrl` and `xdotool` were not installed. `xwininfo -root -tree` was therefore used to attempt a visible-window listing; it exited 0 and reported a 1408×881 root plus visible AI-Loop, terminal, and file-manager windows. A usable X11 display is available. Capture should use that display and the applications' Pillow `ImageGrab`/XWD fallback logic. If a later runner has no display, install Xvfb and prefix the same capture command with `xvfb-run -a`; no mocked GUI is planned.

## AI-Loop

### Reproducible batch setup

The repository's `ai-loop/docs/capture_gui_screenshots.py` creates a temporary SQLite database, synthetic jobs, deterministic text, and eight GUI captures. To keep the source tree untouched, run it from a disposable copy, then copy only the named PNGs into this workspace:

```bash
cd /home/hlavacs/Dokumente/GitHub/ai-runs/J20260915-072058-858811/ai-loop
./ai_gui.bash --theme default
# Close the window after the launcher has prepared .gui-venv.
capture_tmp=$(mktemp -d /tmp/ai-loop-video-capture.XXXXXX)
cp -a . "$capture_tmp/ai-loop"
cd "$capture_tmp/ai-loop"
DISPLAY=:10.0 .gui-venv/bin/python docs/capture_gui_screenshots.py
mkdir -p /home/hlavacs/Dokumente/GitHub/ai-runs/J20260915-072058-858811/video/ai-loop/screenshots
cp docs/images/s11-gui-jobs-status.png docs/images/s12-gui-plan.png docs/images/s13-gui-task-controller.png docs/images/s14-gui-worker-details.png docs/images/s15-gui-logs-controls.png docs/images/s16-gui-provider-repair.png docs/images/s17-quick-job-form.png docs/images/s18-quick-job-complete.png /home/hlavacs/Dokumente/GitHub/ai-runs/J20260915-072058-858811/video/ai-loop/screenshots/
```

The initial launcher invocation is setup, not a capture. It may install local GUI dependencies; it must not create a real job. The capture script disables mail settings, fakes Redis sampling, writes its database and worktrees to a temporary directory, and uses only synthetic values.

### Required states

| Target output filename | Exact GUI screen/state and steps to reach it |
| --- | --- |
| `video/ai-loop/screenshots/s11-gui-jobs-status.png` | `Jobs` top-level tab; select synthetic job `demo-active-001`; open detail tab `Status`. Keep the filled Create Job form, three colored job rows, 50% progress, controller/worker summary, and resume controls visible. Produced first by the batch command. |
| `video/ai-loop/screenshots/s12-gui-plan.png` | Same selected job; click detail tab `Plan`. Show all four immutable plan entries and the current-step marker. Produced second. |
| `video/ai-loop/screenshots/s13-gui-task-controller.png` | Same selected job; click `Task`. Show task `demo-task-002`, detailed instructions, two completion checks, and `python -m pytest -q`; retain `Controller` in the adjacent tab bar. Produced third. |
| `video/ai-loop/screenshots/s14-gui-worker-details.png` | Same selected job; click `Worker`. Show running task text, first diagnostic result, failed validation `1 failed, 11 passed`, and retain `Details` in the tab bar. Produced fourth. |
| `video/ai-loop/screenshots/s15-gui-logs-controls.png` | Same selected job; click `Logs`, refresh the log, then open `Job Actions`. Keep the toolbar and menu entries `Status Details`, `Wait / Notify`, `Sign In + Resume`, and `Finish Early` visible beside the five synthetic log lines. Produced fifth. |
| `video/ai-loop/screenshots/s16-gui-provider-repair.png` | Select `demo-auth-002`, open `Status`, and invoke the synthetic Human Needed alert. Show the whole dialog, preserved-worktree explanation, `Sign In + Resume`, and `Dismiss`. Produced sixth. |
| `video/ai-loop/screenshots/s17-quick-job-form.png` | Return to the Jobs screen and fill the form with repo `/tmp/ai-loop-demo/one-failing-test`; goal `Diagnose the failure, make the smallest correct repair, and make the test suite pass.`; test `python -m pytest -q`; controller `claude`; worker `codex`; base `HEAD`; max iterations `12`; granularity `normal`; all three checkboxes off. Keep `Quick Job` visible. Produced seventh. |
| `video/ai-loop/screenshots/s18-quick-job-complete.png` | Select `demo-quick-fix-003`; open `Worker`. Show state `done`, 100%, completed task, `Validation: passed`, changed file `src/totals.py`, target-checkout validation `PASSED`, command `python -m pytest -q`, and `12 passed`. Produced eighth. |

The storyboard reuses these full captures with different red focus overlays. Reuse does not require another capture. Each 1408×812 image must be contained at 1404×810 pixels in the common screenshot box `[120,190]–[1800,1000]`, centered at `[258,190]–[1662,1000]`.

## ICODA

### Reproducible batch setup

Initialize ICODA's local environment once, close the initial window, copy the sample project to a disposable location, then run both crash-safe deterministic harnesses. Both output paths remain below `video/`:

```bash
cd /home/hlavacs/Dokumente/GitHub/ai-runs/J20260915-072058-858811/icoda
./icoda.bash
# Close the window after the launcher has prepared .icoda-venv.
view_project=$(mktemp -d /tmp/icoda-video-views.XXXXXX)
lifecycle_project=$(mktemp -d /tmp/icoda-video-lifecycle.XXXXXX)
cp -a tests/sample_project/. "$view_project/"
cp -a tests/sample_project/. "$lifecycle_project/"
mkdir -p ../video/icoda/screenshots/views ../video/icoda/screenshots/lifecycle
DISPLAY=:10.0 ICODA_TK_STUB=0 ../ai-loop/ai_run_crash_safe.bash -- .icoda-venv/bin/python tests/gui_acceptance.py --project "$view_project" --output ../video/icoda/screenshots/views
DISPLAY=:10.0 ICODA_TK_STUB=0 ../ai-loop/ai_run_crash_safe.bash -- .icoda-venv/bin/python tests/simulation_acceptance.py --project "$lifecycle_project" --output ../video/icoda/screenshots/lifecycle
```

The view harness programmatically opens each named tab and seeds deterministic graph/proposal states. The lifecycle harness replays ten developer decision points. Its fresh-project copy is disposable and separate from both product source and final screenshot output.

### Required states

| Target output filename | Exact GUI screen/state produced by the commands |
| --- | --- |
| `video/icoda/screenshots/views/file-view.png` | File View after sample-project analysis; complete hierarchy and selectable entities visible. |
| `video/icoda/screenshots/views/call-view.png` | Call View centered on the sample call graph with depth controls and readable node labels. |
| `video/icoda/screenshots/views/uncertain-dynamic-call.png` | Call View with fixed and dashed uncertain dispatch targets plus legend visible. |
| `video/icoda/screenshots/views/class-view.png` | Class View centered on the sample class, its methods/signatures, hierarchy, and status legend. |
| `video/icoda/screenshots/views/mind-map.png` | Mind Map with the source cluster expanded to files and entities. |
| `video/icoda/screenshots/views/requirements-coverage.png` | Coverage view showing specification links and recorded test reachability. |
| `video/icoda/screenshots/views/rule-issues.png` | Issues table with severity, rule, entity, action, and location columns. |
| `video/icoda/screenshots/views/provider-selection.png` | Main screen with Binary and Model selectors populated for the supported coding-agent path. |
| `video/icoda/screenshots/views/proposal-source-diff.png` | Proposal review with Source diff selected and passing build/test evidence retained. |
| `video/icoda/screenshots/views/signature-confirmation.png` | Proposal review with Signature changes selected and the explicit API confirmation gate visible. |
| `video/icoda/screenshots/views/implementation-approach.png` | Implementation phase with prose Approach awaiting developer approval. |
| `video/icoda/screenshots/views/diagram-filtered.png` | Derived graph after applying the harness's filter; controls, nodes, hierarchy, and toolchain line visible. |
| `video/icoda/screenshots/lifecycle/sim-01-specification-code-refused.png` | New-project lifecycle at the initial guard that refuses coding before the specification is complete. |
| `video/icoda/screenshots/lifecycle/sim-02-specification-save.png` | Specification editor immediately before saving the complete demo specification. |
| `video/icoda/screenshots/lifecycle/sim-03-architecture-reject.png` | First architecture proposal at the reject decision. |
| `video/icoda/screenshots/lifecycle/sim-04-architecture-approve.png` | Adapted architecture proposal with highlighted entity delta at approval. |
| `video/icoda/screenshots/lifecycle/sim-05-architecture-gate.png` | Architecture completion gate before implementation begins. |
| `video/icoda/screenshots/lifecycle/sim-06-normalize-approach.png` | First implementation target's prose approach. |
| `video/icoda/screenshots/lifecycle/sim-07-normalize-build-test.png` | First implementation result with measured delta and passed build/test gates. |
| `video/icoda/screenshots/lifecycle/sim-08-main-approach.png` | Final target's prose approach. |
| `video/icoda/screenshots/lifecycle/sim-09-main-build-test.png` | Final code proposal with result and gates visible. |
| `video/icoda/screenshots/lifecycle/sim-10-terminal-overview.png` | Completed project overview after the terminal lifecycle state. |

ICODA's specification pages are also available as current 2240×1360 reference captures under `icoda/docs/images/handbook/`. If used in the later storyboard, recapture Overview, Scope, Requirements, Decisions, and Code Profile through the specification editor so the final production uses one consistent GUI session.
