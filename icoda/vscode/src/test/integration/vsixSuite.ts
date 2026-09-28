import * as assert from "node:assert/strict";
import * as vscode from "vscode";
import { readFile, readdir, writeFile } from "node:fs/promises";
import { join, relative, sep } from "node:path";
import type { ProjectTree } from "../../projectTree";
import type { ProjectTreeNode } from "../../projectTreeData";
import type { CallViewPanel } from "../../callViewPanel";
import { command, report, until, workspace } from "./helpers";

let tree: ProjectTreeNode[] = [];
let panel: CallViewPanel | undefined;
const results: { name: string; passed: boolean; error?: string }[] = [];

/** Observe installed controllers, forwarding every call to the original implementation. */
function observe(root: string): () => void {
  const trees = require(join(root, "out/projectTree.js")) as { ProjectTree: typeof ProjectTree };
  const calls = require(join(root, "out/callViewPanel.js")) as { CallViewPanel: typeof CallViewPanel };
  const update = trees.ProjectTree.prototype.update;
  const sync = calls.CallViewPanel.prototype.sync;
  trees.ProjectTree.prototype.update = function(items) { update.call(this, items); tree = items; };
  calls.CallViewPanel.prototype.sync = function() { sync.call(this); panel = this; };
  return () => { trees.ProjectTree.prototype.update = update; calls.CallViewPanel.prototype.sync = sync; };
}

async function check(name: string, action: () => Promise<void>): Promise<void> {
  let timer: NodeJS.Timeout | undefined;
  try {
    await Promise.race([action(), new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error(`Timed out: ${name}`)), 60_000);
    })]);
    results.push({ name, passed: true });
    console.log(`PASS ${name}`);
  } catch (error) {
    results.push({ name, passed: false, error: String(error) });
    throw error;
  } finally { clearTimeout(timer); }
}

async function analyse(): Promise<void> {
  assert.deepEqual(vscode.workspace.workspaceFolders?.map(folder => folder.uri.fsPath), [workspace]);
  await command("icoda.analyseProject");
  await command("icoda.project.focus");
  assert.equal(tree[0]?.label, workspace);
  const children = tree[0]?.children;
  assert.equal(children?.find(node => node.id === "model")?.label, "Model: fresh");
  assert.equal(children?.find(node => node.id === "entities")?.label, "Entities: 7");
  assert.match(children?.find(node => node.id === "edges")?.label ?? "", /^Edges: [1-9]/);
}

async function showCalls(): Promise<void> {
  await command("icoda.showCallView");
  const state = await until("installed Call View graph", () => {
    const state = panel?.integrationHooks().snapshot();
    return state?.visible && !state.loading && state.graph?.nodes.length ? state : undefined;
  });
  assert.ok(vscode.window.tabGroups.all.some(group => group.tabs.some(tab => tab.label === "ICODA Call View")));
  assert.deepEqual(state.graph?.nodes.map(node => node.usr).sort(),
    ["main", "A", "B", "C", "D", "E"].map(name => `python:main:${name}`).sort());
  assert.equal(state.graph?.edges.length, 5);
}

async function backendPath(root: string): Promise<void> {
  const backend = join(root, "backend");
  const runtime = require(join(root, "out/pythonRuntime.js")) as typeof import("../../pythonRuntime");
  assert.equal(await runtime.resolveBackend(root), backend);
  for (const name of ["service.py", "providers.json", "response.schema.json", "specification.schema.json"]) {
    assert.ok((await readFile(join(backend, "icoda_core", name))).length);
  }
  const logs = join(report, "vsix/logs");
  const paths = (await readdir(logs, { recursive: true })).filter(path => path.endsWith("-ICODA.log"));
  const text = (await Promise.all(paths.map(path => readFile(join(logs, path), "utf8")))).join("\n");
  assert.ok(text.includes(`Backend package root: ${backend}`), "running backend logs the installed package root");
  assert.match(text, /Backend .*; protocol 1/);
  console.log(`Installed backend: ${backend}`);
}

export async function run(): Promise<void> {
  const extension = vscode.extensions.getExtension("icoda.icoda");
  assert.ok(extension, "VSIX installed in the fresh extensions directory");
  const restore = observe(extension.extensionPath);
  try {
    await check("installed production activation and commands", async () => {
      assert.equal(vscode.version, process.env.ICODA_TEST_VSCODE_VERSION);
      assert.ok(!relative(join(report, "vsix/extensions"), extension.extensionPath).split(sep).includes(".."));
      assert.equal(await extension.activate(), undefined, "production activation has no test exports");
      assert.equal(extension.isActive, true);
      const commands = await vscode.commands.getCommands(true);
      for (const item of extension.packageJSON.contributes.commands) assert.ok(commands.includes(item.command));
    });
    await check("installed Analyse Project and real populated tree", analyse);
    await check("installed Call View with real Python graph", showCalls);
    await check("backend and resources resolve inside installed extension", () => backendPath(extension.extensionPath));
  } finally {
    restore();
    const passed = results.filter(result => result.passed).length;
    await writeFile(join(report, "vsix-results.json"), JSON.stringify({ version: vscode.version, passed,
      failed: results.length - passed, results, extensionPath: extension.extensionPath,
      backend: join(extension.extensionPath, "backend"), tree, callView: panel?.integrationHooks().snapshot() }, null, 2));
  }
}
