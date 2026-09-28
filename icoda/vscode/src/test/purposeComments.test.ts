import * as assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { test, TestContext } from "node:test";
import { runInNewContext } from "node:vm";
import { BackgroundPurposeComments } from "../purposeComments";
import { ProjectSession } from "../projectSession";
import { WorkflowModel } from "../workflowModel";
import { WorkflowNode } from "../workflowData";

const drain = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };

async function host(t: TestContext) {
  const calls: string[] = [], events = new Map<string, () => void>();
  const gates = { enabled: true, provider: true, pending: false, idle: true, active: false };
  const context = { sessionId: "project", modelRevision: 1, targetId: null };
  const session = new ProjectSession(() => {}, () => {});
  session.identity.accept(session.identity.capture(), context, "open");
  session.data = { root: "/project", modelState: "fresh", staleReason: "", entityCount: 1, edgeCount: 0, targets: [] };
  const resource = { dispose() {} };
  const event = (name: string) => (callback: () => void) => { events.set(name, callback); return resource; };
  const workspace = { isTrusted: true, textDocuments: [] as { isDirty: boolean; uri: { toString(): string } }[],
    getConfiguration: () => ({ get: () => gates.enabled }), onDidSaveTextDocument: event("save"),
    onDidChangeTextDocument: event("edit"), onDidChangeConfiguration: event("config") };
  const file = resolve(__dirname, "../workflowView.js"), requireFromView = createRequire(file);
  const loaded = { exports: {} as { WorkflowView: new (...args: unknown[]) => {
    model: WorkflowModel; purpose: WorkflowModel; background: BackgroundPurposeComments;
    sync(): void; dispose(): void; getChildren(): WorkflowNode[]; activity(method: string): Promise<void>;
  } } };
  runInNewContext(await readFile(file, "utf8"), { exports: loaded.exports,
    require: (id: string) => id === "vscode" ? {
      workspace, Uri: { file: (value: string) => value }, EventEmitter: class { event() {} fire() {} dispose() {} },
      window: { createOutputChannel: () => ({ ...resource, appendLine() {} }), createTreeView: () => resource,
        onDidChangeActiveTextEditor: event("editor"), onDidChangeTextEditorSelection: event("selection") },
      commands: { registerCommand: () => resource },
    } : requireFromView(id) });
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const view = new loaded.exports.WorkflowView(session, async () => ({ async request(method: string) {
    calls.push(method);
    if (method === "purpose.status") return { ...context, ready: gates.provider && !gates.pending && !gates.active };
    if (method === "purpose.propose") return { ...context, workflow: { id: "purpose", kind: "purpose", state: "completed",
      message: "Review", error: null, result: { round: "purpose", summary: "Comments", files: ["main.py"], candidateLocation: "/candidate" } } };
    return { ...context, workflow: null };
  } }), () => gates.idle);
  t.after(() => view.dispose());
  view.sync(); await drain(); calls.length = 0;
  return { view, calls, events, gates, workspace, session, async tick(ms = 30_000) { t.mock.timers.tick(ms); await drain(); } };
}

test("P10 background purpose fires after idle through WorkflowModel and leaves conversation state alone", async t => {
  const h = await host(t);
  const conversation = h.view.model.snapshot;
  await h.tick(29_999); assert.deepEqual([...h.calls], []);
  h.events.get("selection")!();
  await h.tick(29_999); assert.deepEqual([...h.calls], []);
  await h.tick(1);
  assert.deepEqual([...h.calls], ["purpose.status", "purpose.propose"]);
  assert.equal(h.view.model.snapshot, conversation);
  assert.ok(h.view.getChildren().some(item => item.command === "icoda.applyPurposeComments"));
  await h.tick(90_000);
  assert.equal(h.calls.filter(method => method === "purpose.propose").length, 1);
  assert.ok(!h.calls.includes("purpose.apply"));
});

for (const blocked of ["dirty", "untrusted", "no provider", "workflow active", "proposal pending", "foreground busy", "setting off"] as const) {
  test(`P10 background purpose is suppressed when ${blocked}`, async t => {
    const h = await host(t);
    if (blocked === "dirty") h.workspace.textDocuments.push({ isDirty: true, uri: { toString: () => "file:///project/main.py" } });
    if (blocked === "untrusted") h.workspace.isTrusted = false;
    if (blocked === "no provider") h.gates.provider = false;
    if (blocked === "workflow active") h.gates.active = true;
    if (blocked === "proposal pending") h.gates.pending = true;
    if (blocked === "foreground busy") h.gates.idle = false;
    if (blocked === "setting off") h.gates.enabled = false;
    await h.tick();
    assert.ok(!h.calls.includes("purpose.propose"));
    assert.equal(h.view.purpose.snapshot, undefined);
  });
}

for (const end of ["deactivate", "session change", "setting off"] as const) {
  test(`P10 background timer cancels its owned job on ${end}`, async t => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const state = { key: "first", enabled: true, eligible: true };
    const signals: AbortSignal[] = [];
    const timer = new BackgroundPurposeComments(() => state, signal => new Promise<boolean>(done => {
      signals.push(signal); signal.addEventListener("abort", () => done(true));
    }), assert.fail);
    timer.sync(); t.mock.timers.tick(30_000); await drain();
    assert.equal(signals.length, 1);
    if (end === "deactivate") timer.dispose();
    else { if (end === "session change") state.key = "second"; else state.enabled = false; timer.sync(); }
    await drain();
    assert.equal(signals[0]!.aborted, true);
    timer.dispose(); t.mock.timers.tick(90_000); await drain();
    assert.equal(signals.length, 1, "disposed timers never launch again");
  });
}

test("P10 foreground and trace activity cancels only background work and waits for it", async t => {
  const h = await host(t);
  let cancelled = false;
  const started = new Promise<void>(resolve => {
    h.view.purpose.run = async (_kind, _input, token) => {
      resolve();
      return new Promise(done => token.onCancellationRequested(() => { cancelled = true; done(undefined); }));
    };
  });
  h.view.purpose.purposeReady = async () => true;
  await h.tick(); await started;
  await h.view.activity("trace.step");
  assert.equal(cancelled, true);
  assert.ok(!h.calls.includes("workflow.cancel"), "foreground model is never cancelled");
});

test("P10 workspace setting is opt-in and resource scoped", async () => {
  const manifest = JSON.parse(await readFile(resolve(__dirname, "../../package.json"), "utf8"));
  const setting = manifest.contributes.configuration.properties["icoda.backgroundPurposeComments"];
  assert.equal(setting.default, false); assert.equal(setting.scope, "resource");
});
