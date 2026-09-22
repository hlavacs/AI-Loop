# ICODA platform/release qualification matrix

Release record: ICODA 0.1.0, iteration 53, 2026-09-11.

This matrix distinguishes implemented platform branches from qualification evidence. Linux is the **ONLY qualified
platform**. Windows and macOS are implemented targets but remain **UNQUALIFIED** until the complete gate and native
behavior are executed and retained on those hosts. No result is inferred, predicted, or claimed for an operating
system that was not executed.

| Platform | Qualification status | Evidence today | Evidence still required |
|---|---|---|---|
| Linux | **QUALIFIED** | Iteration 53: `DISPLAY=:99 bash icoda/verify.bash` produced `Required test coverage of 85% reached. Total coverage: 90.22%`, `317 passed, 3 skipped`, and `VERIFY_EXIT_STATUS=0`; the worktree-root suite produced `824 passed, 4 skipped`; `gui_acceptance.py` produced exactly 32 PNGs and `simulation_acceptance.py` produced ten PNGs plus `simulation-state.json` under persistent `Xephyr :99`; the post-fix retained workload has 0.813075s summed stage latency and all seven observed ratios below the material-growth signal, without claiming linear worst-case complexity. | Qualification applies only to the recorded Linux host and configuration. Requalification requires another complete stored gate run whose metadata identifies that Linux host. |
| Windows | **IMPLEMENTED BUT UNQUALIFIED** | Windows branches exist for the launcher, command rendering and sample build, configuration paths, compiler and libclang discovery, editor opening, process-group creation and `taskkill`; injected-platform unit tests cover selected branch construction and fallbacks. No complete gate has run on a Windows host. | Run and retain the complete gate on a real Windows host, including `icoda.cmd` setup/launch, NTFS path and atomic-replace behavior, timeout/cancellation of real process trees, `clang-cl`/CMake/Ninja sample build, provider executable discovery, and real-Tk GUI acceptance with screenshots. |
| macOS | **IMPLEMENTED BUT UNQUALIFIED** | The Bash launcher, Command-key UI, application paths, Homebrew LLVM/libclang and SDK discovery, and `open` command branches are implemented. Interactive use from 2026-09-08 to 2026-09-15 and injected-platform unit tests provide hands-on and branch-level evidence, but no complete macOS gate run. | Run and retain the complete gate on a real macOS host, including fresh launcher setup, POSIX process-tree and persistence behavior, Homebrew LLVM plus native SDK sample build and analysis, provider invocation, coverage, and real-Tk GUI acceptance with screenshots. |

## Platform-seam inventory

The current source inventory contains 42 top-level Python modules under `icoda_core/`, counting every `*.py` file
including `__init__.py`, and 67 Python test modules under `tests/`, counting 60 top-level `test_*.py` modules plus the 7 `*_acceptance.py` programs. Supporting test utilities and the sample project are excluded.

The required worktree-root platform-seam inventory command now produces:

```text
$ rg -n 'sys\.platform|os\.name|platform\.system|shutil\.which|os\.get_exec_path|\.exe' icoda/icoda.py icoda/icoda_core icoda/icoda_gui icoda/tests/verify.py
icoda/tests/verify.py:40:    shown = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
icoda/tests/verify.py:78:        "executable": sys.executable,
icoda/tests/verify.py:89:    command = [sys.executable, str(ROOT / "tests" / "gui_acceptance.py"),
icoda/tests/verify.py:91:    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
icoda/tests/verify.py:98:    binary = shutil.which("codex")
icoda/tests/verify.py:110:    python = sys.executable
icoda/tests/verify.py:115:    build_script = SAMPLE / ("build.cmd" if os.name == "nt" else "build.sh")
icoda/tests/verify.py:116:    build = ["cmd", "/c", str(build_script), "debug"] if os.name == "nt" \
icoda/tests/verify.py:140:    shown = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
icoda/icoda.py:68:MODIFIER = "Command" if sys.platform == "darwin" else "Control"
icoda/icoda.py:69:ACCELERATOR = "⌘" if sys.platform == "darwin" else "Ctrl+"
icoda/icoda_core/analysis.py:367:def libcxx_arguments(compiler: str, arguments: Sequence[str], platform: str = sys.platform) -> list[str]:
icoda/icoda_gui/spec_editor.py:389:        modifier = "Command" if sys.platform == "darwin" else "Control"
icoda/icoda_core/toolchain.py:110:def candidates(platform: str = sys.platform, environ: Mapping[str, str] | None = None,
icoda/icoda_core/toolchain.py:202:def default_sysroot(platform: str = sys.platform) -> str | None:
icoda/icoda_gui/provider_field.py:47:    for suffix in (".exe", ".cmd", ".bat"):
icoda/icoda_core/session.py:160:    command = [sys.executable, "-m", "icoda_core.session", str(root)]
icoda/icoda_core/session.py:224:    if shutil.which("code"):
icoda/icoda_core/session.py:231:    if sys.platform == "darwin":
icoda/icoda_core/session.py:233:    if sys.platform == "win32":
icoda/icoda_core/agent.py:103:    return Path(candidate).is_file() or shutil.which(candidate) is not None
icoda/icoda_core/agent.py:110:    finder: Callable[[str], str | None] = shutil.which,
icoda/icoda_core/agent.py:135:    finder: Callable[[str], str | None] = shutil.which,
icoda/icoda_core/persistence.py:232:def config_path(platform: str = sys.platform, environ: Mapping[str, str] | None = None,
icoda/icoda_core/persistence.py:278:        if sys.platform != "win32":
icoda/icoda_core/process.py:99:    if sys.platform == "win32":
icoda/icoda_core/process.py:161:        start_new_session=sys.platform != "win32",
icoda/icoda_core/process.py:162:        creationflags=int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) if sys.platform == "win32" else 0,
icoda/icoda_core/steps.py:123:        return GateCommands([[sys.executable, "-m", "compileall", "-q", "-x",
icoda/icoda_core/steps.py:155:    if sys.platform == "win32" and (root / "build.cmd").is_file():
icoda/icoda_core/steps.py:167:    if sys.platform == "darwin" and not os.environ.get("CXX") and shutil.which("brew"):
icoda/icoda_core/steps.py:172:    elif sys.platform.startswith("linux") and not os.environ.get("CXX"):
icoda/icoda_core/steps.py:174:        for directory in os.get_exec_path():
icoda/icoda_core/steps.py:196:    elif sys.platform == "win32" and not os.environ.get("CXX"):
icoda/icoda_core/steps.py:197:        found = shutil.which("clang-cl")
```

The genuine platform-dependent behavior is command rendering, GUI display wrapping and keyboard modifiers,
sample-build command selection, Windows/POSIX process handling, configuration paths and replacement behavior,
libc++ arguments, libclang candidates/sysroot, compiler discovery, and OS editor selection. The `sys.executable`
occurrences merely reuse the running interpreter; the provider suffix loop and Codex probe are executable-
availability checks rather than platform selection.

The new host-independent tests
`test_build_environment_macos_without_homebrew_uses_inherited_environment` and
`test_build_environment_windows_without_clang_cl_uses_inherited_environment` monkeypatch `sys.platform`,
`shutil.which`, and `os.get_exec_path`. They prove that both non-Linux branches bypass Linux executable-path
scanning and return `None`, preserving the inherited environment, when their native compiler-discovery prerequisite
is absent. They do not qualify either operating system.

Other seams have the following evidence boundary:

- `persistence.config_path`, `analysis.libcxx_arguments`, and `toolchain.candidates` already have injected-platform
  unit tests, but real Windows/macOS filesystem, compiler, SDK, and library behavior cannot be proven without those
  hosts.
- `tests/verify.py` command rendering, GUI wrapping, and sample-build selection cannot be qualified without running
  the complete harness on a real Windows or macOS host.
- `process.kill_tree` and `process.run_bounded` cannot prove Windows `taskkill` and process-tree semantics without a
  real Windows host.
- Successful `steps.build_environment` construction from Windows `clang-cl` or macOS Homebrew LLVM cannot be proven
  without the corresponding real host; the new tests cover only the explicit missing-tool fallbacks.
- `toolchain.default_sysroot`, the successful Homebrew compiler path, and native macOS SDK behavior cannot be proven
  without a real macOS host.
- `session.editor_command` cannot prove the native `open` or `cmd /c start` launch behavior without the corresponding
  real host.
- The provider `.exe`/`.cmd`/`.bat` filename probes and executable availability checks cannot prove real Windows PATH
  and executable semantics without a real Windows host.

## macOS hands-on record (not gate evidence)

Between 2026-09-08 and 2026-09-15 ICODA was used interactively on the author's macOS machine through `icoda.bash`
(the launcher created `.icoda-venv` and installed the dependencies). What was observed and fixed there, in order:

- The main window, the specification editor and the libclang chooser open and are sized to the screen; an
  earlier version of the specification editor was taller than the screen, which led to `screen.fit_to_screen`
  and to packing every button bar first.
- **New Project** writes the C++ skeleton; the C++ module build needs Homebrew LLVM (`brew install llvm`), which
  the generated `build.sh` and `steps.build_environment` select automatically.
- The Claude Code CLI is invoked with the prompt on standard input (`prompt_mode: stdin`), because a prompt passed
  as an argument after `--disallowedTools` was swallowed on macOS as on Linux.
- A project directory inside another Git repository receives its own repository (`git.is_own_repository`), so
  that step 0 is committed into the project and not into the enclosing checkout.
- Error dialogs are shortened to ten lines (`dialogs.shorten`).
- The user reported that reopening the demo project sometimes leaves the window unresponsive. The log showed only
  normal opens; ICODA now shows a moving bar while analysing and a watchdog writes every thread's stack to the
  log when the Tk thread stops answering for five seconds, so the next occurrence is diagnosable.

To turn this record into qualification, run on a macOS host from `icoda/`:

```bash
.icoda-venv/bin/python -m pip install -e '.[dev]'
./verify.bash
```

and add the produced `summary.txt` figures (coverage, pytest counts, GUI screenshots) to the table above.
