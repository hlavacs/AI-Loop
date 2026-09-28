import * as assert from "node:assert/strict";
import * as vscode from "vscode";
import { execFile } from "node:child_process";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { delimiter, join, resolve } from "node:path";
import { promisify } from "node:util";
import { BackendClient } from "../../backendClient";
import { BackendError, OpenedProject, ResolvedSource } from "../../protocol";
import type { IntegrationTestApi } from "../../extension";
import type { PlaybackState } from "../../tracePlayback";
import { activate, command, report, workspace } from "./helpers";

type Check = (name: string, action: () => Promise<void>) => Promise<void>;

const executionCommands = [
  "newProject", "refreshTargets", "buildTarget", "testProject", "runTarget", "recordTrace", "showToolchain",
  "proposeArchitecture", "proposeImplementationApproach", "runImplementationQueue", "cancelAIWorkflow",
  "proposePurposeComments", "applyPurposeComments", "rejectPurposeComments",
  "queueBatchSize", "queueScope", "queueGrouping", "queueAutoApprove",
  "sendConversation", "showConversation", "rephrase", "openCLI",
  "reviewProposal", "approveProposal", "rejectProposal", "adaptProposal", "rebuildProposal",
  "undoLastStep", "commitManualEdits", "recoverProposal",
];

/** Observe real notifications, and fail closed if a command attempts execution. */
async function guardedCommands(api: IntegrationTestApi): Promise<void> {
  const before = await files(workspace);
  const attempted: string[] = [], notifications: { command: string; text: string }[] = [];
  const restore: (() => void)[] = [];
  let current = "";
  const replace = (object: object, key: string, replacement: unknown) => {
    const target = object as Record<string, unknown>, original = target[key];
    target[key] = replacement;
    restore.push(() => { target[key] = original; });
  };
  const refuse = (operation: string) => () => {
    attempted.push(`${current}: ${operation}`);
    throw new Error(`Untrusted command attempted ${operation}`);
  };
  try {
    // Patch the CommonJS exports used by ICODA, not a copied import namespace.
    const processes = require("node:child_process") as object;
    for (const key of ["spawn", "exec", "execFile", "fork", "spawnSync", "execSync", "execFileSync"]) {
      replace(processes, key, refuse(key));
    }
    replace(BackendClient.prototype, "request", refuse("backend request"));
    for (const key of ["createTerminal", "showInputBox", "showQuickPick", "showOpenDialog"]) {
      replace(vscode.window, key, refuse(key));
    }
    for (const key of ["showWarningMessage", "showErrorMessage"] as const) {
      const original = vscode.window[key];
      replace(vscode.window, key, (text: string) => {
        notifications.push({ command: current, text });
        return original(text);
      });
    }
    for (const name of executionCommands) {
      current = `icoda.${name}`;
      const start = notifications.length;
      await command(current);
      assert.ok(notifications.slice(start).some(item => /Trust this workspace/i.test(item.text)),
        `${current} shows the trust refusal`);
      assert.equal(api.snapshot().backendStarted, false, `${current} did not start Python`);
      assert.equal(vscode.workspace.isTrusted, false);
    }
    // These also require Python, or stay disabled/no-op without an open session.
    for (const name of ["openProject", "analyseProject", "restartBackend", "openSpecification",
      "validateSpecification", "advancePhase", "selectProviderModel", "selectTarget", "revealEntity",
      "showCallView", "openFileView", "openClassView", "openMindMap", "revealInFileView",
      "refreshIssues", "refreshCoverage", "showStepHistory", "openProposalDiff",
      "traceInto", "traceOver", "traceOut", "tracePrevious", "traceReset"]) {
      current = `icoda.${name}`;
      await command(current);
    }
    assert.deepEqual(attempted, [], "no process, provider, terminal, input or backend request was attempted");
    assert.equal(api.snapshot().backendStarted, false);
    assert.equal(api.snapshot().project, undefined);
    assert.deepEqual(vscode.window.terminals, []);
    assert.deepEqual(await files(workspace), before);
    await writeFile(join(report, "untrusted-refusals.json"), JSON.stringify(notifications, null, 2));
  } finally {
    for (const undo of restore.reverse()) undo();
  }
}

async function guardedService(log: (text: string) => void): Promise<BackendClient> {
  const directory = join(report, "service-guard");
  await mkdir(directory, { recursive: true });
  const attempts = join(directory, "attempts.log");
  await writeFile(attempts, "");
  // Fail before any real tool/provider or network call if a service guard regresses.
  await writeFile(join(directory, "sitecustomize.py"), "import sys\n"
    + "def audit(event, args):\n"
    + "    if event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'socket.connect', 'socket.bind'):\n"
    + `        with open(${JSON.stringify(attempts)}, 'a') as output: output.write(event + '\\n')\n`
    + "        raise RuntimeError('Untrusted service test forbids execution and network access')\n"
    + "sys.addaudithook(audit)\n"
    + `with open(${JSON.stringify(attempts)}, 'a') as output: output.write('ready\\n')\n`);
  const previous = process.env.PYTHONPATH;
  process.env.PYTHONPATH = [directory, previous].filter(Boolean).join(delimiter);
  let client: BackendClient;
  try {
    client = new BackendClient({ python: process.env.ICODA_TEST_PYTHON!,
      packageRoot: resolve(__dirname, "../../../.."), log });
  } finally {
    if (previous === undefined) delete process.env.PYTHONPATH;
    else process.env.PYTHONPATH = previous;
  }
  try {
    await client.ready;
    assert.equal(await readFile(attempts, "utf8"), "ready\n", "Python execution guard is installed before requests");
    return client;
  } catch (error) { await client.dispose(); throw error; }
}

async function files(directory: string): Promise<Record<string, string>> {
  const result: Record<string, string> = {};
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) Object.assign(result, await files(path));
    else result[path] = (await readFile(path)).toString("base64");
  }
  return result;
}

/** Service reads need no trust field; this test-owned client is not the extension's gated runtime. */
async function serviceReads(): Promise<void> {
  assert.equal(vscode.workspace.isTrusted, false);
  const python = process.env.ICODA_TEST_PYTHON!;
  const packageRoot = resolve(__dirname, "../../../..");
  // Parse the existing sentinel fixture without importing/executing project source.
  await promisify(execFile)(python, ["-c", "import sys; from pathlib import Path; "
    + "from icoda_core import persistence,python_analysis; root=Path(sys.argv[1]); "
    + "persistence.ProjectStore(root).save_model(python_analysis.parse_project(root))", workspace],
  { cwd: packageRoot, timeout: 10_000 });
  const before = await files(workspace);
  const log: string[] = [];
  const client = await guardedService(text => log.push(text));
  try {
    const project = await client.request<OpenedProject>("project.open", { path: workspace });
    assert.equal(project.cached, true);
    assert.equal(project.model.entities.length, 7);
    for (const view of ["call", "file", "class", "mindmap"]) {
      const graph = await client.request<{ view: string; nodes: unknown[] }>("view.get", { view }, project);
      assert.equal(graph.view, view);
      assert.ok(Array.isArray(graph.nodes));
      if (view === "call") assert.equal(graph.nodes.length, 6);
    }
    const source = await client.request<ResolvedSource>("source.resolve",
      { sourceRootId: project.sourceRootId, usr: "python:main:B" }, project);
    assert.equal(source.path, join(workspace, "main.py"));
    assert.equal(source.line, 14);
    const trace = await client.request<PlaybackState>("trace.load", { path: "calls.tsv" }, project);
    assert.equal(trace.total, 6);
    for (const [action, name] of [["into", "C"], ["over", "D"], ["out", "E"]]) {
      await client.request("trace.step", { traceId: trace.traceId, action: "seek", usr: "python:main:B" }, project);
      const next = await client.request<PlaybackState>("trace.step", { traceId: trace.traceId, action }, project);
      assert.equal(next.currentEntityUsr, `python:main:${name}`);
    }
    const previous = await client.request<PlaybackState>("trace.step",
      { traceId: trace.traceId, action: "previous" }, project);
    assert.equal(previous.currentEntityUsr, "python:main:D");
    const reset = await client.request<PlaybackState>("trace.reset", { traceId: trace.traceId }, project);
    assert.equal(reset.position, 0);
    assert.equal(reset.currentEntityUsr, null);
    await client.request("project.close", {}, project);
  } finally {
    await client.dispose();
    await writeFile(join(report, "untrusted-service.log"), log.join(""));
  }
  assert.deepEqual(await files(workspace), before, "service reads and playback leave source/state untouched");
  assert.equal(await readFile(join(report, "service-guard/attempts.log"), "utf8"), "ready\n");
}

async function serviceRefusals(): Promise<void> {
  const client = await guardedService(() => {});
  const before = await files(workspace);
  try {
    const project = await client.request<OpenedProject>("project.open", { path: workspace });
    const requests: [string, object][] = [
      ["build.run", {}], ["tests.run", {}], ["target.run", {}], ["trace.record", {}], ["targets.refresh", {}],
      ["project.create", { parentPath: workspace, name: "forbidden", language: "Python" }],
      ["workflow.start", { kind: "architecture", unsavedDocuments: [] }],
      ["conversation.send", { message: "Do not run", unsavedDocuments: [] }],
      ["conversation.history", {}], ["prompt.rephrase", { unsavedDocuments: [] }],
      ["cli.command", { unsavedDocuments: [] }],
      ["purpose.propose", { idle: true, unsavedDocuments: [] }],
      ["purpose.apply", { workflowId: "missing", idle: true, unsavedDocuments: [] }],
      ["purpose.reject", { workflowId: "missing", idle: true, unsavedDocuments: [] }],
      ["proposal.approve", { unsavedDocuments: [], evidenceFingerprint: "missing" }],
      ["queue.settings.set", { settings: { autoApprove: true } }],
      ["queue.continue", { unsavedDocuments: [] }], ["recovery.list", {}],
      ["spec.save", { document: {} }], ["phase.transition", { phase: "architecture" }],
    ];
    for (const [method, params] of requests) {
      await assert.rejects(client.request(method, { ...params, trusted: false }, project), (error: unknown) => {
        assert.ok(error instanceof BackendError);
        assert.equal(error.code, method === "project.create" ? "not_trusted" : "workspace_untrusted", method);
        assert.match(error.message, /Trust this workspace/);
        return true;
      });
    }
  } finally { await client.dispose(); }
  assert.deepEqual(await files(workspace), before);
  assert.equal(await readFile(join(report, "service-guard/attempts.log"), "utf8"), "ready\n");
}

export async function untrustedSuite(check: Check): Promise<IntegrationTestApi> {
  let api!: IntegrationTestApi;
  await check("Restricted Mode activation retains trust guards and starts no backend", async () => {
    assert.equal(vscode.workspace.getConfiguration("security.workspace.trust").get("enabled"), true);
    assert.equal(vscode.workspace.isTrusted, false);
    assert.deepEqual(vscode.workspace.workspaceFolders?.map(folder => folder.uri.fsPath), [workspace]);
    api = await activate();
    const extension = vscode.extensions.all.find(item => item.packageJSON.name === "icoda")!;
    assert.equal(extension.packageJSON.capabilities.untrustedWorkspaces.supported, "limited");
    for (const item of extension.packageJSON.contributes.commands as { command: string; enablement?: string }[]) {
      if (item.command !== "icoda.showOutput") assert.match(item.enablement ?? "", /\bisWorkspaceTrusted\b/, item.command);
    }
    assert.match(api.snapshot().treeMessage ?? "", /Trust the workspace/);
  });
  await check("Restricted Mode refuses execution commands before tools providers terminals or backend requests", () => guardedCommands(api));
  await check("Restricted Mode output project placeholder and native source editor remain usable", async () => {
    await command("icoda.showOutput");
    await command("icoda.project.focus");
    assert.deepEqual(api.snapshot().tree, []);
    const document = await vscode.workspace.openTextDocument(join(workspace, "main.py"));
    const editor = await vscode.window.showTextDocument(document, { selection: new vscode.Range(13, 0, 13, 0) });
    assert.match(editor.document.lineAt(editor.selection.active.line).text, /^def B\(/);
    assert.equal(document.isDirty, false);
    assert.equal(api.snapshot().backendStarted, false);
  });
  await check("Read-only service open views source and recorded playback need no trust authorization", serviceReads);
  await check("Service rejects untrusted creation workflows conversation CLI purpose apply and proposal approval", serviceRefusals);
  assert.equal(vscode.workspace.isTrusted, false);
  assert.equal(api.snapshot().backendStarted, false, "only the separate test client was started");
  return api;
}
