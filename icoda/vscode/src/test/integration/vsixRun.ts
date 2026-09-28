import { downloadAndUnzipVSCode, runTests, runVSCodeCommand } from "@vscode/test-electron";
import { cp, mkdir, readFile, writeFile } from "node:fs/promises";
import { isAbsolute, join } from "node:path";
import { platform, release } from "node:os";
import { extensionRoot, prepareProfile, reportDirectory, useDisplay, version } from "./run";

async function prepareHarness(report: string): Promise<string> {
  const harness = join(report, "harness");
  await mkdir(harness);
  await writeFile(join(harness, "package.json"), JSON.stringify({ name: "icoda-vsix-smoke", publisher: "icoda-test",
    version: "0.0.0", engines: { vscode: "^1.74.0" } }));
  for (const name of ["vsixSuite.js", "helpers.js"]) await cp(join(__dirname, name), join(harness, name));
  return harness;
}

async function install(report: string, profile: string): Promise<string[]> {
  const manifest = JSON.parse(await readFile(join(extensionRoot, "package.json"), "utf8")) as { version: string };
  const vsix = join(extensionRoot, "dist", `icoda-${manifest.version}.vsix`);
  const args = [`--user-data-dir=${profile}`, `--extensions-dir=${join(report, "vsix/extensions")}`];
  const result = await runVSCodeCommand([...args, "--install-extension", vsix, "--force"], {
    version, reuseMachineInstall: true,
  });
  await writeFile(join(report, "install.log"), result.stdout + result.stderr);
  console.log(result.stdout);
  return args;
}

async function launch(executable: string, report: string, workspace: string, python: string): Promise<void> {
  const profile = await prepareProfile(report, "vsix", python);
  const args = await install(report, profile);
  const harness = await prepareHarness(report);
  const launchArgs = [workspace, ...args, "--new-window", "--disable-telemetry", "--disable-gpu",
    `--logsPath=${join(report, "vsix/logs")}`];
  await writeFile(join(report, "launch.json"), JSON.stringify({ executable, launchArgs,
    extensionDevelopmentPath: harness, extensionTestsPath: join(harness, "vsixSuite.js") }, null, 2));
  await runTests({ vscodeExecutablePath: executable, version, extensionDevelopmentPath: harness,
    extensionTestsPath: join(harness, "vsixSuite.js"), launchArgs,
    extensionTestsEnv: { ICODA_TEST_REPORT: report, ICODA_TEST_WORKSPACE: workspace,
      ICODA_TEST_VSCODE_VERSION: version, PYTHONPATH: "" },
  });
}

async function main(): Promise<void> {
  if (!useDisplay()) return;
  const python = process.env.ICODA_TEST_PYTHON;
  if (!python || !isAbsolute(python)) throw new Error("Set ICODA_TEST_PYTHON to the prepared venv's absolute interpreter path.");
  const report = await reportDirectory();
  console.log(`Installed-VSIX reports: ${report}`);
  const workspace = join(report, "fixture");
  await cp(join(extensionRoot, "src/test/fixtures/python"), workspace, { recursive: true });
  const display = process.env.ICODA_TEST_DISPLAY_METHOD ?? (process.env.DISPLAY ? "X11" : "Wayland/native");
  await writeFile(join(report, "environment.json"), JSON.stringify({ version, os: platform(), release: release(),
    node: process.version, python, display }, null, 2));
  const executable = await downloadAndUnzipVSCode({ version });
  await launch(executable, report, workspace, python);
  const result = JSON.parse(await readFile(join(report, "vsix-results.json"), "utf8")) as { passed: number; failed: number };
  console.log(`Installed-VSIX smoke: ${result.passed} passed, ${result.failed} failed; VS Code ${version}; ${display}`);
}

void main().catch(error => { console.error(error); process.exitCode = 1; });
