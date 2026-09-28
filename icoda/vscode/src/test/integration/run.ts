import { downloadAndUnzipVSCode, runTests } from "@vscode/test-electron";
import { cp, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { spawn, spawnSync } from "node:child_process";
import { tmpdir, platform, release } from "node:os";
import { isAbsolute, join, relative, resolve, sep } from "node:path";

export const version = "1.96.4"; // Compatible with engines.vscode ^1.74.0; never use a moving stable tag.
export const extensionRoot = resolve(__dirname, "../../..");

export function useDisplay(): boolean {
  const { DISPLAY, WAYLAND_DISPLAY, XDG_SESSION_TYPE } = process.env;
  console.log("Display environment:", { DISPLAY, WAYLAND_DISPLAY, XDG_SESSION_TYPE });
  if (platform() !== "linux" || DISPLAY || WAYLAND_DISPLAY) return true;
  const probe = spawnSync("xvfb-run", ["--help"], { encoding: "utf8" });
  if (probe.error || probe.status !== 0) {
    throw new Error("No DISPLAY or WAYLAND_DISPLAY and xvfb-run is unavailable; install Xvfb or supply a display.");
  }
  const result = spawnSync("xvfb-run", ["-a", "-s", "-screen 0 1600x1000x24", process.execPath, ...process.argv.slice(1)], {
    stdio: "inherit", env: { ...process.env, ICODA_TEST_DISPLAY_METHOD: "Xvfb" },
  });
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
  return false;
}

export async function reportDirectory(): Promise<string> {
  const parent = resolve(process.env.ICODA_TEST_REPORT_DIR ?? tmpdir());
  const local = relative(resolve(tmpdir()), parent);
  if (isAbsolute(local) || local.split(sep)[0] === "..") throw new Error("ICODA_TEST_REPORT_DIR must be inside system temp.");
  await mkdir(parent, { recursive: true });
  return mkdtemp(join(parent, "icoda-integration-"));
}

export async function prepareProfile(report: string, mode: string, python: string): Promise<string> {
  const profile = join(report, mode, "profile");
  await mkdir(join(profile, "User"), { recursive: true });
  await writeFile(join(profile, "User", "settings.json"), JSON.stringify({
    "icoda.pythonPath": python, "security.workspace.trust.enabled": mode === "untrusted",
    // The source-refresh case enables this explicitly; cached-path/playback cases control analysis themselves.
    "icoda.autoAnalyse": false,
    ...(mode === "untrusted" ? { "security.workspace.trust.startupPrompt": "never" } : {}),
    "telemetry.telemetryLevel": "off", "update.mode": "none",
    "extensions.autoCheckUpdates": false, "extensions.autoUpdate": false,
    "workbench.enableExperiments": false, "workbench.startupEditor": "none",
    "workbench.tips.enabled": false, "window.restoreWindows": "none",
    "git.enabled": false,
  }, null, 2));
  return profile;
}

async function launch(executable: string, report: string, mode: string, workspace: string, python: string): Promise<void> {
  const profile = await prepareProfile(report, mode, python);
  // A workspace file allows temporary folders without restarting the host on single-folder conversion.
  const opened = mode === "workspace" ? join(report, "integration.code-workspace") : workspace;
  if (mode === "workspace") await writeFile(opened, JSON.stringify({ folders: [{ path: workspace }] }));
  await runTests({
    vscodeExecutablePath: executable, version, extensionDevelopmentPath: extensionRoot,
    extensionTestsPath: join(__dirname, "suite.js"),
    launchArgs: [...(mode === "workspace" || mode === "cpp" ? [opened] : []), "--new-window",
      "--disable-telemetry", "--disable-gpu", `--user-data-dir=${profile}`,
      `--extensions-dir=${join(report, mode, "extensions")}`, `--logsPath=${join(report, mode, "logs")}`],
    extensionTestsEnv: { ICODA_TEST_MODE: mode, ICODA_TEST_REPORT: report, ICODA_TEST_WORKSPACE: workspace,
      ICODA_TEST_VSCODE_VERSION: version },
  });
}

async function launchUntrusted(executable: string, report: string, python: string): Promise<void> {
  const workspace = join(report, "untrusted-fixture");
  await cp(join(extensionRoot, "src/test/fixtures/python"), workspace, { recursive: true });
  const profile = await prepareProfile(report, "untrusted", python);
  // test-electron 2.5.2 runTests unconditionally adds --disable-workspace-trust.
  // Use its pinned download, but launch this additional host without that switch.
  const args = [workspace, "--new-window", "--no-sandbox", "--disable-gpu-sandbox", "--disable-gpu",
    "--disable-updates", "--disable-telemetry", "--skip-welcome", "--skip-release-notes",
    `--user-data-dir=${profile}`, `--extensions-dir=${join(report, "untrusted/extensions")}`,
    `--logsPath=${join(report, "untrusted/logs")}`, `--extensionDevelopmentPath=${extensionRoot}`,
    `--extensionTestsPath=${join(__dirname, "suite.js")}`];
  await writeFile(join(report, "untrusted-launch.json"), JSON.stringify({ executable, args }, null, 2));
  await new Promise<void>((done, reject) => {
    const child = spawn(executable, args, { stdio: "inherit", env: { ...process.env,
      ICODA_TEST_MODE: "untrusted", ICODA_TEST_REPORT: report, ICODA_TEST_WORKSPACE: workspace,
      ICODA_TEST_VSCODE_VERSION: version } });
    const stop = () => { child.kill(); };
    process.once("SIGINT", stop);
    const timeout = setTimeout(() => { stop(); reject(new Error("Untrusted host timed out.")); }, 120_000);
    child.once("error", reject);
    child.once("close", (code, signal) => {
      clearTimeout(timeout); process.removeListener("SIGINT", stop);
      if (code === 0) done();
      else reject(new Error(`Untrusted host exited: ${code ?? signal}`));
    });
  });
}

async function main(): Promise<void> {
  if (!useDisplay()) return;
  const python = process.env.ICODA_TEST_PYTHON;
  if (!python || !isAbsolute(python)) throw new Error("Set ICODA_TEST_PYTHON to the prepared venv's absolute interpreter path (retain its symlink).");
  const report = await reportDirectory();
  console.log(`Integration reports: ${report}`);
  const workspace = join(report, "fixture");
  await cp(join(extensionRoot, "src/test/fixtures/python"), workspace, { recursive: true });
  const cppWorkspace = join(report, "recorded C++");
  await cp(join(extensionRoot, "src/test/fixtures/cpp"), cppWorkspace, { recursive: true });
  const display = process.env.ICODA_TEST_DISPLAY_METHOD ?? (process.env.DISPLAY ? "X11" : "Wayland/native");
  await writeFile(join(report, "environment.json"), JSON.stringify({ version, os: platform(), release: release(),
    node: process.version, python, display, DISPLAY: process.env.DISPLAY, WAYLAND_DISPLAY: process.env.WAYLAND_DISPLAY,
    XDG_SESSION_TYPE: process.env.XDG_SESSION_TYPE }, null, 2));
  const executable = await downloadAndUnzipVSCode({ version });
  for (const mode of ["workspace", "empty"]) await launch(executable, report, mode, workspace, python);
  await launch(executable, report, "cpp", cppWorkspace, python);
  await launchUntrusted(executable, report, python);
  const results = await Promise.all(["workspace", "empty", "cpp", "untrusted"].map(async mode =>
    JSON.parse(await readFile(join(report, `${mode}-results.json`), "utf8")) as { passed: number; failed: number; skipped: number }));
  console.log(`Integration: ${results.reduce((sum, result) => sum + result.passed, 0)} passed, `
    + `${results.reduce((sum, result) => sum + result.failed, 0)} failed, `
    + `${results.reduce((sum, result) => sum + result.skipped, 0)} skipped; VS Code ${version}; ${display}`);
}

if (require.main === module) void main().catch(error => { console.error(error); process.exitCode = 1; });
