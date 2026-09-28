import * as assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readFileSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { monitorEventLoopDelay, performance } from "node:perf_hooks";
import { test, TestContext } from "node:test";
import { promisify } from "node:util";
import { runInNewContext } from "node:vm";
import { BackendClient, BackendOptions, RequestOptions } from "../backendClient";
import { BackendError, Notification, OpenedProject, SessionContext } from "../protocol";
import { resolvePython } from "../pythonRuntime";
import { slowAnalysis, writeServiceShim } from "./slowBackend";

const root = resolve(__dirname, "../../..");
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
}

const slowOperation = `
import sys
from icoda_core import executables, process
service.operation_tools = lambda *_args: {"environment": {}, "tools": []}
def operate(root, model, selected, action, cancelled, options, **kwargs):
    code = "import os,time; print(os.getpid(), flush=True); time.sleep(60)"
    run = executables._operation_runner(root, cancelled, kwargs["environment"], kwargs["cancel_event"], [], kwargs["progress"], kwargs["log"])
    run([sys.executable, "-c", code], "Running controlled child")
executables.operate = operate
`;

async function runtime(t: TestContext, bootstrap = slowOperation) {
  const directory = await mkdtemp(join(tmpdir(), "icoda lifecycle "));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const python = await resolvePython(root, process.env.ICODA_TEST_PYTHON);
  const project = join(directory, "project"), packageRoot = join(directory, "runtime");
  await mkdir(project);
  await writeFile(join(project, "main.py"), 'def main():\n    """Controlled entry."""\n    return 1\n');
  const prepare = "import sys; from pathlib import Path; from icoda_core import persistence,python_analysis; root=Path(sys.argv[1]); persistence.ProjectStore(root).save_model(python_analysis.parse_project(root))";
  await promisify(execFile)(python, ["-c", prepare, project], { cwd: root, timeout: 10_000 });
  await writeServiceShim(packageRoot, join(root, "icoda_core"), bootstrap);
  return { python, project, packageRoot };
}

test("BackendClient keeps the Node event loop responsive during slow analysis", { timeout: 20_000 }, async t => {
  const fixture = await runtime(t, slowAnalysis), started = deferred<void>();
  const client = new BackendClient({ ...fixture, log: () => {}, onNotification: note => {
    if (note.params.message === "Slow analysis started") started.resolve();
  } });
  t.after(() => client.dispose());
  const project = await client.request<OpenedProject>("project.open", { path: fixture.project });
  const delay = monitorEventLoopDelay({ resolution: 10 }); delay.enable();
  t.after(() => delay.disable());
  const begin = performance.now(), pending = client.request<OpenedProject>("project.analyse", {}, project);
  await started.promise; delay.reset();
  let ticks = 0;
  const timer = setInterval(() => ticks++, 10); t.after(() => clearInterval(timer));
  // Python cannot finish until this host timer/I/O runs: no machine-speed assertion.
  await new Promise(resolve => setTimeout(resolve, 20));
  await writeFile(join(fixture.project, "release-analysis"), "ready");
  const analysed = await pending;
  clearInterval(timer); delay.disable();
  assert.ok(ticks > 0); assert.equal(analysed.model.stale, false);
  assert.ok(analysed.model.entities.length > 0);
  t.diagnostic(JSON.stringify({ analysisMs: performance.now() - begin, ticks,
    eventLoopMaxMs: delay.max / 1e6, eventLoopP95Ms: delay.percentile(95) / 1e6 }));
});

function resources() {
  const all: { kind: string; disposed: boolean }[] = [];
  const resource = (kind: string) => {
    const item = { kind, disposed: false, dispose() { this.disposed = true; } };
    all.push(item); return item;
  };
  const viewClass = (kind: string) => class {
    private item = resource(kind);
    dispose() { this.item.dispose(); }
    sync() {} update() {} refresh() {} reveal() {} activity() {}
    async saveState() {}
  };
  return { all, resource, viewClass };
}

function vscodeFixture(python: string, project: string, tracked: ReturnType<typeof resources>) {
  const commands = new Map<string, (...args: unknown[]) => Promise<unknown>>();
  const removed = deferred<(event: unknown) => void>(), errors: string[] = [], output: string[] = [];
  const uri = (fsPath: string) => ({ fsPath, scheme: "file", toString: () => `file://${fsPath}` });
  const folder = { uri: uri(project) };
  const dialogs = { folders: [uri(dirname(project))] as ReturnType<typeof uri>[] | undefined,
    name: "Fresh Project" as string | undefined, language: "Python" as string | undefined,
    summary: "Specification description" as string | undefined, choice: undefined as string | undefined };
  const prompts: string[] = [], information: string[] = [];
  const executed: { name: string; args: unknown[] }[] = [], added: unknown[][] = [];
  const inputs: { title: string; validateInput?: (value: string) => string | undefined }[] = [];
  const listener = (kind: string) => () => tracked.resource(kind);
  const vscode = { Uri: { file: uri, parse: (value: string) => uri(value.replace("file://", "")) },
    ProgressLocation: { Notification: 1 }, ExtensionMode: { Test: 3 }, workspace: {
      isTrusted: true, workspaceFolders: [folder],
      getConfiguration: () => ({ get: (key: string, fallback: unknown) => key === "pythonPath" ? python : fallback }),
      onDidChangeWorkspaceFolders: (callback: (event: unknown) => void) => { removed.resolve(callback); return tracked.resource("folders"); },
      onDidGrantWorkspaceTrust: listener("trust"), onDidChangeConfiguration: listener("configuration"),
      updateWorkspaceFolders: (...args: unknown[]) => { added.push(args); return true; },
    }, commands: {
      registerCommand: (name: string, action: (...args: unknown[]) => Promise<unknown>) => { commands.set(name, action); return tracked.resource("command"); },
      executeCommand: async (name: string, ...args: unknown[]) => { executed.push({ name, args }); },
    }, window: {
      createOutputChannel: () => Object.assign(tracked.resource("output"), {
        append: (text: string) => output.push(text), appendLine: (text: string) => output.push(text), show() {},
      }),
      createTreeView: () => tracked.resource("treeView"),
      showOpenDialog: async (options: { canSelectFiles: boolean; canSelectFolders: boolean; canSelectMany: boolean }) => {
        assert.equal(options.canSelectFiles, false); assert.equal(options.canSelectFolders, true);
        assert.equal(options.canSelectMany, false); prompts.push("folder"); return dialogs.folders;
      },
      showInputBox: async (options: { title: string; validateInput?: (value: string) => string | undefined }) => {
        inputs.push(options);
        const kind = options.title.endsWith("Name") ? "name" : "summary";
        prompts.push(kind); return dialogs[kind];
      },
      showQuickPick: async (choices: string[]) => {
        assert.deepEqual(Array.from(choices), ["C++", "Python"]); prompts.push("language"); return dialogs.language;
      },
      showInformationMessage: async (message: string) => { information.push(message); return dialogs.choice; },
      showWarningMessage() {}, showErrorMessage: (message: string) => errors.push(message),
      withProgress: async (_options: unknown, work: Function) => work({ report() {} },
        { isCancellationRequested: false, onCancellationRequested: listener("cancellation") }),
    } };
  return { vscode, commands, removed, errors, output, uri, folder, dialogs, prompts, information, executed, added, inputs };
}

async function controller(t: TestContext, open = true) {
  const fixture = await runtime(t), tracked = resources(), host = vscodeFixture(fixture.python, fixture.project, tracked);
  const clients: BackendClient[] = [], child = deferred<number>();
  const opens: OpenedProject[] = [];
  const creations: { params: object; context?: SessionContext }[] = [];
  const creation = { pause: undefined as (() => Promise<void>) | undefined };
  const notifications: ((note: Notification) => void)[] = [];
  class Client extends BackendClient {
    constructor(options: BackendOptions) {
      super({ ...options, onNotification: (note: Notification) => {
        options.onNotification?.(note);
        if (note.method === "operation.log" && /^\d+\s*$/.test(String(note.params.message))) child.resolve(Number(note.params.message));
      } }); clients.push(this); notifications.push(options.onNotification!);
    }
    async request<T = unknown>(method: string, params = {}, context?: SessionContext, options: RequestOptions = {}): Promise<T> {
      const result = await super.request<T>(method, params, context, options);
      if (method === "project.open") opens.push(result as OpenedProject);
      if (method === "project.create") { creations.push({ params, context }); await creation.pause?.(); }
      return result;
    }
  }
  const modules: Record<string, object> = { "vscode": host.vscode, "./backendClient": { BackendClient: Client },
    "./sourceEditor": { watchSourceSaves: () => tracked.resource("sourceWatcher") } };
  for (const name of ["ProjectTree", "EvidenceTrees", "SpecificationView", "WorkflowView", "ProposalView", "CallViewPanel", "FileViewPanel", "ClassViewPanel", "MindMapPanel"]) {
    modules[`./${name[0]!.toLowerCase()}${name.slice(1)}`] = { [name]: tracked.viewClass(name) };
  }
  const file = resolve(__dirname, "../extension.js"), exports: Record<string, Function> = {}, requireFrom = createRequire(file);
  runInNewContext(readFileSync(file, "utf8"), { exports, AbortController, Promise,
    require: (name: string) => modules[name] ?? requireFrom(name) });
  exports.activate!({ extensionUri: host.uri(join(fixture.packageRoot, "vscode")), subscriptions: [] });
  t.after(() => exports.deactivate!());
  if (open) await Promise.all([host.commands.get("icoda.openProject")!(), host.commands.get("icoda.openProject")!()]);
  else host.vscode.workspace.workspaceFolders = [];
  assert.deepEqual(host.errors, []); assert.equal(clients.length, Number(open));
  host.information.length = 0;
  return { ...fixture, ...host, tracked, clients, child, opens, creations, creation, notifications, deactivate: () => exports.deactivate!() };
}

test("newProject is discoverable and creates through the shared service without switching projects", { timeout: 20_000 }, async t => {
  const manifest = JSON.parse(await readFile(join(root, "vscode/package.json"), "utf8"));
  assert.ok(manifest.activationEvents.includes("onCommand:icoda.newProject"));
  assert.deepEqual(manifest.contributes.commands.find((item: { command: string }) => item.command === "icoda.newProject"),
    { command: "icoda.newProject", title: "New Project", category: "ICODA", enablement: "isWorkspaceTrusted" });
  const fixture = await controller(t), before = fixture.opens[0]!;
  assert.ok(fixture.commands.has("icoda.newProject"));
  await fixture.commands.get("icoda.newProject")!();
  assert.deepEqual(fixture.errors, []);
  assert.deepEqual(fixture.prompts, ["folder", "name", "language", "summary"]);
  assert.deepEqual(structuredClone(fixture.creations), [{ params: { parentPath: dirname(fixture.project), name: "Fresh Project",
    language: "Python", summary: "Specification description", trusted: true },
    context: { sessionId: before.sessionId, modelRevision: before.modelRevision, targetId: before.targetId } }]);
  const created = join(dirname(fixture.project), "Fresh Project");
  const spec = JSON.parse(await readFile(join(created, ".icoda/specification.json"), "utf8"));
  assert.equal(spec.title, "Fresh Project"); assert.equal(spec.summary, "Specification description");
  assert.equal(spec.code_profile.language, "Python");
  assert.match(await readFile(join(created, "src/fresh_project.py"), "utf8"), /class FreshProject/);
  assert.equal(fixture.opens.length, 1);
  assert.equal(fixture.executed.filter(item => item.name === "vscode.openFolder").length, 0);
  assert.deepEqual(fixture.added, []);
});

test("newProject native inputs validate required values and cancellation never starts the backend", { timeout: 20_000 }, async t => {
  const fixture = await controller(t, false), create = fixture.commands.get("icoda.newProject")!;
  for (const name of ["", " ", "bad\0name"]) {
    fixture.dialogs.name = name;
    await create(); assert.ok(fixture.errors.pop()?.includes("Enter a project name"));
    assert.equal(fixture.clients.length, 0);
  }
  const validate = fixture.inputs[0]!.validateInput!;
  assert.ok(validate(" ")); assert.equal(validate("Sample Project"), undefined);
  fixture.dialogs.name = "Fresh Project";
  fixture.dialogs.language = "Ruby";
  await create(); assert.ok(fixture.errors.pop()?.includes("Choose C++ or Python"));
  fixture.dialogs.language = "Python";
  for (const key of ["folders", "name", "language", "summary"] as const) {
    const original = { ...fixture.dialogs };
    fixture.dialogs[key] = undefined;
    await create(); Object.assign(fixture.dialogs, original);
    assert.equal(fixture.clients.length, 0);
  }
  fixture.dialogs.folders![0]!.scheme = "remote";
  await create(); assert.ok(fixture.errors.pop()?.includes("Choose a local parent folder"));
  assert.deepEqual(fixture.errors, []); assert.equal(fixture.clients.length, 0);
});

test("newProject trust guard runs before native pickers or backend startup", async t => {
  const fixture = await controller(t, false);
  fixture.vscode.workspace.isTrusted = false;
  await fixture.commands.get("icoda.newProject")!();
  assert.equal(fixture.errors.length, 1); assert.match(fixture.errors[0]!, /Trust this workspace/);
  assert.deepEqual(fixture.prompts, []); assert.equal(fixture.clients.length, 0);
});

test("newProject routes path validation to the core and preserves existing targets", { timeout: 20_000 }, async t => {
  const fixture = await controller(t, false), create = fixture.commands.get("icoda.newProject")!;
  fixture.dialogs.name = "../escape";
  await create(); assert.match(fixture.errors.pop()!, /single folder name/);
  fixture.dialogs.name = "project";
  await create(); assert.match(fixture.errors.pop()!, /target already exists/);
  assert.equal(await readFile(join(fixture.project, "main.py"), "utf8"), 'def main():\n    """Controlled entry."""\n    return 1\n');
  assert.deepEqual(fixture.information, []); assert.deepEqual(fixture.added, []);
  assert.equal(fixture.opens.length, 0);
});

for (const choice of ["Open in New Window", "Add to Workspace"]) {
  test(`newProject empty-workspace creation offers explicit ${choice}`, { timeout: 20_000 }, async t => {
    const fixture = await controller(t, false);
    fixture.dialogs.choice = choice;
    await fixture.commands.get("icoda.newProject")!();
    assert.deepEqual(fixture.errors, []); assert.equal(fixture.creations[0]!.context, undefined);
    assert.equal(fixture.information.length, 1);
    const created = join(dirname(fixture.project), "Fresh Project");
    const opened = fixture.executed.filter(item => item.name === "vscode.openFolder");
    if (choice === "Open in New Window") {
      assert.equal(opened.length, 1); assert.equal((opened[0]!.args[0] as { fsPath: string }).fsPath, created);
      assert.equal(opened[0]!.args[1], true); assert.deepEqual(fixture.added, []);
    } else {
      assert.equal(opened.length, 0); assert.equal(fixture.added.length, 1);
      assert.deepEqual(fixture.added[0]!.slice(0, 2), [0, 0]);
      assert.equal((fixture.added[0]![2] as { uri: { fsPath: string } }).uri.fsPath, created);
    }
    assert.equal(fixture.opens.length, 0);
  });
}

for (const change of ["session", "target", "trust", "dispose", "error"]) {
  test(`newProject drops late replies after ${change} change`, { timeout: 20_000 }, async t => {
    const fixture = await controller(t), ready = deferred<void>(), release = deferred<void>();
    fixture.creation.pause = async () => { ready.resolve(); await release.promise; if (change === "error") throw new Error("Old error"); };
    fixture.dialogs.choice = "Open in New Window";
    const pending = fixture.commands.get("icoda.newProject")!();
    await ready.promise;
    if (change === "trust") fixture.vscode.workspace.isTrusted = false;
    else if (change === "dispose") await fixture.deactivate();
    else if (change === "target") await fixture.commands.get("icoda.selectTarget")!({ context: fixture.opens[0], targetId: null });
    else await fixture.commands.get("icoda.openProject")!();
    release.resolve(); await pending;
    assert.deepEqual(fixture.errors, []); assert.deepEqual(fixture.information, []);
    assert.equal(fixture.executed.filter(item => item.name === "vscode.openFolder").length, 0);
    assert.deepEqual(fixture.added, []);
  });
}

test("newProject drops workspace-open choice after a session change", { timeout: 20_000 }, async t => {
  const fixture = await controller(t);
  fixture.vscode.window.showInformationMessage = async () => {
    await fixture.commands.get("icoda.openProject")!(); return "Open in New Window";
  };
  await fixture.commands.get("icoda.newProject")!();
  assert.deepEqual(fixture.errors, []);
  assert.equal(fixture.executed.filter(item => item.name === "vscode.openFolder").length, 0);
});

test("output accepts context-free and current logs but drops stale or partial session logs", { timeout: 20_000 }, async t => {
  const fixture = await controller(t), project = fixture.opens.at(-1)!;
  const { sessionId, modelRevision, targetId } = project, context = { sessionId, modelRevision, targetId };
  const notify = fixture.notifications[0]!;
  fixture.output.length = 0;
  notify({ method: "operation.log", params: { message: "Toolchain startup" } });
  notify({ method: "operation.log", params: { ...context, message: "Current operation" } });
  for (const stale of [{ ...context, sessionId: "old" }, { ...context, modelRevision: modelRevision - 1 },
    { ...context, targetId: null }, { sessionId }, { modelRevision }]) {
    notify({ method: "operation.log", params: { ...stale, message: "Stale operation" } });
  }
  assert.deepEqual(fixture.output, ["Toolchain startup", "Current operation"]);
});

for (const method of ["build.run", "target.run", "trace.record"]) {
  test(`project.close reaps the owned ${method} child and releases its lock`, { timeout: 20_000 }, async t => {
    const fixture = await runtime(t), started = deferred<number>();
    const client = new BackendClient({ ...fixture, log: () => {}, onNotification: note => {
      if (note.method === "operation.log" && /^\d+\s*$/.test(String(note.params.message))) started.resolve(Number(note.params.message));
    } });
    t.after(() => client.dispose());
    const project = await client.request<OpenedProject>("project.open", { path: fixture.project });
    const running = assert.rejects(client.request(method, { trusted: true }, project), error => error instanceof BackendError && error.code === "cancelled");
    const pid = await started.promise;
    await client.request("project.close", {}, project); await running;
    assert.throws(() => process.kill(pid, 0), { code: "ESRCH" });
    const second = new BackendClient({ ...fixture, log: () => {} }); t.after(() => second.dispose());
    assert.ok(await second.request("project.open", { path: fixture.project }));
  });
}

test("deactivation disposes watchers, panels and trees and reaps an active child", { timeout: 20_000 }, async t => {
  const fixture = await controller(t);
  for (const command of ["icoda.showCallView", "icoda.openFileView", "icoda.openClassView", "icoda.openMindMap"]) {
    await fixture.commands.get(command)!();
  }
  const running = fixture.commands.get("icoda.runTarget")!();
  const pid = await fixture.child.promise;
  await fixture.deactivate(); await running;
  assert.throws(() => process.kill(pid, 0), { code: "ESRCH" });
  assert.throws(() => process.kill(fixture.clients[0]!.pid!, 0), { code: "ESRCH" });
  assert.ok(fixture.tracked.all.some(item => item.kind === "sourceWatcher"));
  assert.ok(fixture.tracked.all.some(item => item.kind === "CallViewPanel"));
  assert.ok(fixture.tracked.all.every(item => item.disposed), JSON.stringify(fixture.tracked.all.filter(item => !item.disposed)));
});

test("folder removal closes owned resources and backend before accepting a new project", { timeout: 20_000 }, async t => {
  const fixture = await controller(t);
  await fixture.commands.get("icoda.showCallView")!();
  const owned = [...fixture.tracked.all];
  const running = fixture.commands.get("icoda.runTarget")!();
  const pid = await fixture.child.promise;
  (await fixture.removed.promise)({ removed: [fixture.folder] });
  await fixture.clients[0]!.closed; await running;
  await new Promise(resolve => setImmediate(resolve));
  assert.throws(() => process.kill(pid, 0), { code: "ESRCH" });
  assert.ok(owned.every(item => item.disposed));
  await fixture.commands.get("icoda.openProject")!();
  assert.equal(fixture.clients.length, 2); assert.deepEqual(fixture.errors, []);
});

test("restart command restores project and target without reload and shares concurrent startup", { timeout: 20_000 }, async t => {
  const fixture = await controller(t);
  const first = fixture.clients[0]!;
  const before = fixture.opens.at(-1)!;
  assert.ok(before.targetId);
  await fixture.commands.get("icoda.selectTarget")!({ context: before, targetId: null });
  process.kill(first.pid!, "SIGKILL"); await first.closed;
  await fixture.commands.get("icoda.restartBackend")!();
  assert.equal(fixture.clients.length, 2);
  const opened = fixture.opens.at(-1)!;
  assert.equal(opened.root, before.root); assert.equal(opened.targetId, null);
  assert.notEqual(opened.sessionId, before.sessionId);
  await Promise.all([fixture.commands.get("icoda.openProject")!(), fixture.commands.get("icoda.openProject")!()]);
  assert.equal(fixture.clients.length, 2); assert.deepEqual(fixture.errors, []);
});
