# ICODA for VS Code

Analyse a local C++ or Python project, explore its File, Call, Class and Mind Map
views, navigate native source editors, and play recorded function calls. Python
analysis parses source without executing the project. ICODA also exposes target
build/run/recording, specification, evidence and proposal review commands.

## Install

Follow the [step-by-step installation guide for Windows, Linux and macOS](INSTALL.md).
It covers obtaining or building the VSIX, preparing Python, installing optional
C++ tools, setting executable paths, opening the first project and troubleshooting.
Use current local desktop VS Code and a separately prepared Python environment;
the extension does not install dependencies during activation.

Linux has extension-host qualification evidence. Windows VSIX installation,
backend startup and C++ analysis have also been checked; full Windows/macOS UI
qualification, remote hosts and browser-only VS Code remain pending. See the
guide's verification scope and the migration record for the precise limits.

## First project and trace playback

1. Open a local project folder, trust it, configure `icoda.pythonPath`, then run
   **ICODA: Analyse Project**. In a multi-folder workspace choose the intended root.
   The ICODA Project tree shows the model state and entity/edge counts.
2. Run **ICODA: Show Call View** and select a function to reveal its source.
   Use the depth/filter/caller controls, zoom/pan and Fit to explore the graph.
   File, Class and Mind Map commands expose the other architecture views.
3. Use **ICODA: Refresh Targets** and **ICODA: Select Target** for an executable.
   **Build Target**, **Run Target** and **Record Trace** use shared backend tools.
   Recording uses an isolated instrumented build and offers **Load Trace** when
   complete. Existing traces can be loaded from the Call View toolbar.
4. Trace playback navigates recorded calls, not live statements or variables.
   The compact toolbar contains Load Trace, Previous Call, Step Over, Step Into,
   Step Out and Reset; narrow views use overflow. With B selected in
   `main → A → B → C; A → D; main → E`, Into selects C, Over D and Out E.
   Previous traverses grouped calls, Reset clears selection, and unavailable
   actions are disabled. The backend owns stepping semantics and repeat counts.

After saving source, ICODA marks the model stale; run **Analyse Project** to
refresh it. Saves do not currently trigger automatic reanalysis.

All four views use the same toolbar Filter, supporting names and expressions.
The filter accepts exact namespaces: `namespace:vve` shows the facade,
while `namespace:vve::*` also includes nested namespaces such as `vve::simple`.
File and Class groups stay visible only when they contain a match. The selected
source and Call View roots remain visible for navigation.

To create a project, run **ICODA: New Project** in a trusted window. Choose an
existing parent folder, enter the new folder/project name, choose C++ or Python,
and enter an optional specification description. ICODA uses the shared default
Code Profile to save a valid specification, write the skeleton and enter the
architecture phase. All existing targets are refused, including empty folders.
Choose **Open in New Window** or **Add to Workspace**, or dismiss to leave the
current workspace as it is. Run **Open Project** for the chosen new folder, then
**Open Specification** to refine its full specification and **Analyse Project**
to inspect it. Build C++ using its generated `build.sh` / `build.cmd` first to
produce compilation commands. Creation does not build, analyse, invoke a provider
or initialize Git; the existing proposal preparation initializes Git later.
Ordinary specification saves do not regenerate a skeleton or trigger a build.

## Development workflows and remaining parity

Use **Open Specification**, **Validate Specification**, **Advance Phase** and
**Select Provider/Model** to prepare the workflow. With an installed authenticated
provider, **Propose Architecture**, **Propose Implementation Approach** and
**Run Implementation Queue** produce a candidate or an approach for review.
These explicit actions invoke the provider; ordinary graph/source browsing does not.
**Review Proposal** shows entity/API changes and build/test output; file entries
open native diffs against the actual candidate worktree. After editing a candidate,
use **Rebuild Proposal** before **Approve Proposal**. Failed gates, unsaved or
changed evidence, and unconfirmed signature changes block approval. Rejection,
adaptation, manual-edit commits and conditional undo use the shared core rules.

File View clusters offer **Pin Cluster** / **Unpin Cluster** and **Rename Cluster…**
from right-click or Shift+F10; the expanded cluster breadcrumb opens the same menu.
Rename uses native input. Names/pins persist in `.icoda/layout.json` across reload
and reopen, while edits retain the current root and viewport. Verification
(2026-09-28): `tests/test_service.py::test_cluster_pin_rename_unpin_persist_across_service_restart`
and its cluster validation/oversized-parent cases; `vscode/src/test/fileView.test.ts`
cluster message, routing, rendering, viewport and native-input cases.

The Workflow tree now edits **Batch size**, **Queue scope**, **Queue grouping** and
**Auto-approve while gates pass**, persisted in the shared `.icoda/state.json`.
With automatic approval on, **Run Implementation Queue** generates code after an
approved approach, approves passing code through the normal evidence gates, and
requests the next approach. Each approach still requires your approval. Failed
checks, signature confirmation, provider failure, cancellation and an empty queue
stop continuation; the tree shows its state and reason. Unsaved or changed
proposal evidence blocks automatic decisions too. All actions require Workspace
Trust. Reopening a project restores settings without starting a provider.
Verification (2026-09-28): `tests/test_service.py::test_queue_settings_persist_across_restart_and_invalidate_approach`,
`test_queue_continuation_passing_fake_step_advances` and the queue gate/cancellation/evidence
cases; `tests/test_step_gui.py::test_desktop_queue_settings_use_shared_updates_and_preserve_controls`;
`vscode/src/test/workflow.test.ts` queue routing, native-input, guard, rendering and
controlled-service continuation tests.

**Send Conversation** asks the selected provider about the current project and
can carry out explicit source edits. **Show Conversation History** displays its
session transcript in ICODA Providers output. History survives analysis and clears
on project reopen/backend restart; it is not an approval step. Save dirty buffers
before requesting edits. When reviewing a code proposal, edits use its worktree
and changed files still require fresh build/test evidence before approval.
**Open CLI** carries the conversation and an optional draft into a VS Code terminal
with the provider's normal interactive approvals. **Rephrase Current Description**
simplifies only the current proposal rationale or pending approach plan. It
changes no source or approval decision. All require Workspace Trust; provider
calls have cancellable progress. Failed/cancelled editing requests are not retried,
and any partial edits mark analysis stale. Use **Analyse Project** to refresh.
These actions reuse the shared Python provider/prompt logic; no provider is
started by source navigation. Verification (2026-09-28, gap 5): controlled-provider
service/desktop regressions and native-API routing/guard/rendering tests in
`vscode/src/test/workflow.test.ts`; see the migration record for exact test names.

No parity gaps remain in the seven-gap follow-up: gap 7 now has a real
Restricted Mode integration suite. Explicitly deferred behaviors and known limitations remain recorded in the
source repository's `icoda/docs/VSCODE_MIGRATION.md` parity matrix.
In Restricted Mode, all ICODA views and commands except **Show Output** are
disabled until the workspace is trusted, because starting the Python backend
requires trust. The Project tree may show an inert placeholder; VS Code native
source editing remains usable. The service's read-only model/view/source and
recorded-playback methods need no trust flag and are tested separately through
a test-owned client. The extension never starts its backend in an untrusted
workspace.

M1 is the first usable analysis/Call View/source/playback milestone. M5 is the
completed-migration milestone, adding workflows, lifecycle, qualification and
packaging. The seven-gap follow-up and G18 documentation review are complete;
full M5 acceptance still requires the matrix's explicit deferrals and unqualified
journeys. The five open nits remain known limitations: unknown Class visibility,
single-level clusterPath, inline Class threshold, duplicate File box computation,
and `specification.validate` typed `Any`. None is claimed fixed.

Interrupted proposals now appear in the Proposal tree after opening
a project or restarting the backend. **Recover Interrupted Proposal** offers Resume
for Review, Keep for Later, and Discard. Resume preserves candidate edits, reruns
shared checks and opens the candidate worktree diff; failed checks and signature
changes still block approval. Recovered proposals require explicit approval even
with automatic approval enabled. Discard requires confirmation and refuses dirty
project files or unsaved buffers. Git locks and named branches are preserved.
Verification (2026-09-28): `tests/test_service.py::test_recovery_choices_preserve_source_and_resume_review`,
`test_recovery_failed_gate_and_unsaved_evidence_still_block_approval`,
`test_recovery_queue_stops_automatic_approval_and_keeps_approach_gate`;
`vscode/src/test/proposal.test.ts` recovery routing, native picker/confirmation,
restart, guards and candidate-diff tests.

**Propose Purpose Comments** creates a checked
candidate; use **Apply Purpose Comments** or **Reject Purpose Comments** in the
workflow tree or Command Palette to decide it. Both decisions require Workspace
Trust. Apply uses the shared desktop logic and refuses busy operations, foreground
proposals, unsaved project/candidate buffers and changed source/candidate evidence. After applying, run **Analyse
Project** to refresh source facts. Evidence: `tests/test_service.py` purpose apply,
reject, stale-candidate and active-proposal cases, plus
`test_purpose_decisions_refuse_untrusted_workspace`; `vscode/src/test/workflow.test.ts`
untrusted command/tree refusal without file changes, `trusted=false` forwarding,
stale/disposed actions, command routing, dirty-document refusal and error display
(paths relative to `icoda/`). Preserved candidates can still block new work after
restart; restarting does not recreate review evidence.
Use the source repository's `icoda/docs/VSCODE_MIGRATION.md` parity matrix and AT
ledger to select follow-up work and its required acceptance evidence.

## Troubleshooting

**ICODA: Show Output** records the interpreter, backend package root and protocol
version. Installed extensions should report their own `backend/` directory.
**Restart Backend** applies interpreter changes and restores project selection.
If sources are missing, reinstall the VSIX; when developing, rebuild the package.
For `ModuleNotFoundError`, install the named dependency into the configured
interpreter, not another Python environment. Missing libclang or compilation
commands are C++ setup problems; regenerate the database using the project's
build instructions. **Show Toolchain** reports effective tool paths and discovery
diagnostics. Overrides are `icoda.toolchain.cmakePath`, `ninjaPath`, `clangPath`
and `llvmSymbolizerPath`. Windows Visual Studio discovery exists but has not been
qualified by this installation test. Missing/ambiguous source is reported locally
or offers a file choice; provider settings do not repair source paths.

## Build, test and debug

Prepare the Python development dependencies explicitly from `icoda/` using a
venv interpreter: `python -m pip install -e '.[dev]' -c constraints.txt`. Set
`ICODA_TEST_PYTHON` to that interpreter's absolute venv path, retaining its symlink.
Run the full ICODA core/service/desktop regression suite from `icoda/`:

```sh
export ICODA_TEST_PYTHON
export PATH="$(dirname "$ICODA_TEST_PYTHON"):$PATH"
export ICODA_TEST_REPORT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/icoda-tests-XXXXXX")"
python -m pytest -q
```

Pytest defaults to Tk-stub tests and controlled provider fixtures; it does not
launch a real provider or the Electron suites. The repository-root pytest suite
also needs AI-Loop's independent test dependencies and runs local network-service
tests; those are not ICODA runtime requirements. For the real C++ recording check,
run `python -m pytest -v tests/test_service.py::test_at11_real_service_records_loads_and_steps_without_touching_ordinary_tree`
from `icoda/`; missing tool prerequisites are reported as skips.

From `icoda/vscode/`, with Node.js 22+ and npm installed:

```sh
npm ci
npm run compile
npm test
npm run test:integration
npm run package
npm run test:vsix
```

Set `ICODA_TEST_PYTHON` to an absolute prepared venv interpreter path before the
test commands. Unit tests stay separate from the Electron suites. Host suites
use pinned test-electron 2.5.2 and VS Code 1.96.4, reusing the cached binary or
downloading it when absent. They need a native display or `xvfb-run` on Linux.
Their profiles, fixtures, logs and results go to system temp; optional
`ICODA_TEST_REPORT_DIR` must also be inside system temp. The integration suite
captures native screenshots. The trusted workspace and empty-window runs retain
the test helper's `--no-sandbox` and disabled Workspace Trust. An additive run
launches the same pinned VS Code binary directly, with a fresh profile, trust
enabled and no `--disable-workspace-trust`. It asserts Restricted Mode, refused
commands and zero execution attempts; separate test-owned service reads and
trust-error checks cannot launch tools/providers or access network services.

The standalone desktop release gate is `./verify.bash` from `icoda/` (Windows:
`verify.cmd`); it invokes a real provider, so run it only when that external check
is in scope. It is not part of the offline extension suites above.
The source repository's `icoda/HANDBOOK.md` maintainer guide lists the standalone
GUI, simulation, performance and real-provider acceptance commands. Redirect their
output/artifacts to system temp when reproducing migration evidence. The migration
record identifies the three desktop GUI assertions already failing on the base commit.

`npm run package` compiles and stages current `icoda_core/*.py` plus its three
JSON resources, dependency constraints and licence into ignored `backend/`, then
uses pinned vsce 3.6.0 to write ignored `dist/icoda-0.1.0.vsix`. Staging is cleared
before copying and removed afterward, including on failure. The archive includes
compiled `out/*.js`, `media/`, that backend, README, installation guide and package metadata. It omits
TypeScript, tests/fixtures, source maps, `.vscode-test/`, all `node_modules/`, and
build scripts. There are no runtime npm dependencies. Packaging is local only;
the publisher identifier `icoda` does not imply a Marketplace publication.
The build sets a fixed ZIP epoch unless `SOURCE_DATE_EPOCH` is supplied, so the
same inputs and tool versions produce byte-identical archives.

`npm run test:vsix` rebuilds and installs the archive into fresh temporary profile
and extension directories, copies the Python fixture outside the checkout, and
tests production activation, Analyse Project/tree, Call View, and the installed
backend root/resources. Only a temporary test harness uses a development path;
ICODA is loaded from the installed VSIX. No production test exports are enabled.

For F5 debugging, open `icoda/vscode/` and select **Run ICODA Extension**. Use
`npm run watch` for incremental compilation. Packaging removes its staged backend,
so development continues to use the live checkout's `icoda_core/`. To debug the service directly, run
`python -m icoda_core.service` from `icoda/` (or installed `backend/`); stdin/stdout
carry newline-delimited protocol v1 JSON and stderr carries diagnostics.

Detailed migration scope and retained verification evidence live in
`icoda/docs/VSCODE_MIGRATION.md` in the source repository. Packaging does not imply
complete desktop parity or broader platform/accessibility qualification.

To continue implementation, start with that record's explicitly Deferred rows
and AT ledger. `src/extension.ts` owns commands/lifecycle, `src/backendClient.ts`
and `src/sessionState.ts` own transport/identity, and `media/` renders the diagrams.
`icoda_core/service.py` adapts the shared core; keep stepping in
`icoda_core/call_trace.py`. Run the relevant suites above and retain separate native
acceptance evidence before changing a qualification status. Full Windows/macOS UI,
display scaling, high contrast and a ViennaVulkanEngine large-project frontend journey
remain unqualified; the Windows backend analysis check is narrower. Restricted Mode is verified separately on Linux VS Code 1.96.4.
