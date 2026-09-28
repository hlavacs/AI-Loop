import * as assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test, TestContext } from "node:test";
import { promisify } from "node:util";
import { pathToFileURL } from "node:url";
import { runInNewContext } from "node:vm";
import { BackendClient } from "../backendClient";
import { ProposalModel } from "../proposalModel";
import { ProjectSession } from "../projectSession";
import { BackendError, SessionContext } from "../protocol";
import { resolvePython } from "../pythonRuntime";
import { conversationText, terminalOptions, registerWorkflowCommands, validWorkflowInput, workflowCommands, workflowNodes, WorkflowStatus, validQueuePatch, QueueSettings } from "../workflowData";
import { WorkflowModel } from "../workflowModel";

const context: SessionContext = { sessionId: "project", modelRevision: 1, targetId: null };
const input = { unsavedDocuments: [], focus: ["src/main.py"], provider: "fixture", model: "ok" };
const result = { round: "code", summary: "Add a helper", candidateLocation: "/candidate", files: ["src/helper.py"] };
function status(state = "running"): WorkflowStatus {
  return { ...context, workflow: { id: "job", kind: "architecture", state, message: "Checking proposal", error: null,
    result: state === "completed" ? result : null } };
}
function token() {
  let listener = () => {}, disposed = false;
  return { isCancellationRequested: false, cancel: () => listener(), get disposed() { return disposed; },
    onCancellationRequested(callback: () => void) { listener = callback; return { dispose() { disposed = true; } }; } };
}
function setup(respond: (method: string, params: unknown) => unknown) {
  const calls: { method: string; params: unknown }[] = [], diagnostics: string[] = [];
  const session = new ProjectSession(() => {}, () => {});
  session.identity.accept(session.identity.capture(), context, "open");
  const client = { async request<T>(method: string, params: unknown) {
    calls.push({ method, params }); return await respond(method, params) as T;
  } };
  const model = new WorkflowModel(session, client, () => {}, message => diagnostics.push(message), async () => {});
  return { model, session, calls, diagnostics };
}

test("workflow and queue commands register, reject external arguments and match manifest commands", async () => {
  const root = resolve(__dirname, "../..");
  const manifest = JSON.parse(await readFile(join(root, "package.json"), "utf8"));
  const handlers = new Map<string, (...args: unknown[]) => unknown>(), calls: string[] = [];
  registerWorkflowCommands((name, action) => { handlers.set(name, action); }, kind => calls.push(kind));
  assert.equal(manifest.contributes.commands.length, 56);
  for (const item of workflowCommands) {
    handlers.get(item.command)!({ trusted: true }); assert.equal(calls.length, 0);
    const contribution = manifest.contributes.commands.find((command: { command: string }) => command.command === item.command);
    assert.equal(contribution.title, item.title);
    assert.equal(contribution.enablement, "icoda.projectOpen && isWorkspaceTrusted");
    assert.ok(manifest.activationEvents.includes(`onCommand:${item.command}`));
  }
  for (const item of workflowCommands) handlers.get(item.command)!();
  assert.deepEqual(calls, workflowCommands.map(item => item.kind));
  const source = await readFile(join(root, "src/workflowView.ts"), "utf8");
  assert.match(source, /vscode.window.withProgress/); assert.match(source, /cancellable: true/);
  assert.match(source, /ICODA Providers/); assert.match(source, /document.isDirty/);
  const extension = await readFile(join(root, "src/extension.ts"), "utf8");
  assert.match(extension, /new WorkflowView/); assert.match(extension, /this.workflows.dispose\(\)/);
});

test("workflow inputs reject malformed context, provider selection, flags and injected fields", () => {
  assert.ok(validWorkflowInput(input));
  for (const value of [null, { ...input, trusted: true }, { ...input, unsavedDocuments: "file" },
    { ...input, focus: [1] }, { ...input, focus: ["\0"] }, { ...input, idle: "yes" },
    { ...input, model: undefined }, { ...input, request: "" }]) assert.equal(validWorkflowInput(value), false);
});

test("fake client drives progress, completion, candidate tree and listener cleanup", async () => {
  const { model, calls } = setup(method => status(method === "workflow.start" ? "running" : "completed"));
  const messages: string[] = [], cancellation = token();
  const completed = await model.run("architecture", input, cancellation, message => messages.push(message));
  assert.equal(completed?.workflow?.state, "completed"); assert.ok(cancellation.disposed);
  assert.deepEqual(calls.map(call => call.method), ["workflow.start", "workflow.status"]);
  assert.deepEqual(calls[0]!.params, { ...input, trusted: true, kind: "architecture" });
  assert.deepEqual(messages, ["Checking proposal"]);
  assert.ok(workflowNodes(completed).some(node => node.description === "/candidate"));
});

test("native cancellation before start response reaches the eventual workflow ID", async () => {
  const cancellation = token();
  const { model, calls } = setup(method => {
    if (method === "workflow.start") { cancellation.cancel(); return status(); }
    return status("cancelled");
  });
  await model.run("architecture", input, cancellation, () => {});
  assert.ok(cancellation.disposed);
  assert.deepEqual(calls[1], { method: "workflow.cancel", params: { trusted: true, workflowId: "job" } });
  const before = calls.length;
  await model.run("architecture", input, { ...token(), isCancellationRequested: true }, () => {});
  assert.equal(calls.length, before);
});

test("provider diagnostics remain separate from graph and source requests", async () => {
  const { model, calls, diagnostics } = setup(() => { throw new BackendError("provider_unavailable", "No fixture provider"); });
  await assert.rejects(model.run("architecture", input, token(), () => {}), /No fixture/);
  assert.match(diagnostics[0]!, /provider_unavailable/);
  assert.deepEqual(calls.map(call => call.method), ["workflow.start"]);
});

test("workflow success and failure are dropped after session, revision or target changes", async () => {
  for (const change of [{ sessionId: "new", modelRevision: 1, targetId: null },
    { ...context, modelRevision: 2 }, { ...context, modelRevision: 2, targetId: "entry" }]) {
    for (const failed of [false, true]) {
      let release!: () => void;
      const pending = new Promise<void>(resolve => { release = resolve; });
      const { model, session, diagnostics } = setup(async () => { await pending; if (failed) throw new Error("Old failure"); return status("completed"); });
      const run = model.run("architecture", input, token(), () => {});
      if (change.sessionId !== context.sessionId) { session.reset(); session.identity.accept(session.identity.capture(), change, "open"); }
      else session.identity.accept(session.identity.capture(), change, change.targetId ? { targetId: change.targetId } : "workflow");
      release(); assert.equal(await run, undefined); assert.equal(model.snapshot, undefined); assert.deepEqual(diagnostics, []);
    }
  }
});

test("mismatched replies and disposed workflows cannot publish; active jobs cancel on dispose", async () => {
  const wrong = setup(() => ({ ...status("completed"), sessionId: "other" }));
  assert.equal(await wrong.model.run("architecture", input, token(), () => {}), undefined);
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const { model, calls } = setup(async method => { if (method === "workflow.status") await pending; return status(); });
  const run = model.run("architecture", input, token(), () => {});
  await new Promise(resolve => setImmediate(resolve)); model.dispose(); release(); await run;
  assert.ok(calls.some(call => call.method === "workflow.cancel")); assert.equal(model.snapshot, undefined);
});

async function controlledService(t: TestContext, phase = "architecture") {
  const root = resolve(__dirname, "../../.."), fixture = join(root, "tests/fixtures/fake_workflow.py");
  const directory = await mkdtemp(join(tmpdir(), "icoda workflow ")), project = join(directory, "project");
  t.after(() => rm(directory, { recursive: true, force: true }));
  const python = await resolvePython(root, process.env.ICODA_TEST_PYTHON);
  await promisify(execFile)(python, ["-c", "import runpy,sys; from pathlib import Path; runpy.run_path(sys.argv[1])['prepare'](Path(sys.argv[2]), sys.argv[3])",
    fixture, project, phase], { cwd: root, timeout: 15_000 });
  const runtime = join(directory, "runtime"), shim = join(runtime, "icoda_core"), core = join(root, "icoda_core");
  await mkdir(shim, { recursive: true });
  await writeFile(join(shim, "__init__.py"), `__path__.append(${JSON.stringify(core)})\n` + await readFile(join(core, "__init__.py"), "utf8"));
  await writeFile(join(shim, "service.py"), `import runpy\nrunpy.run_path(${JSON.stringify(fixture)})['install']()\nrunpy.run_path(${JSON.stringify(join(core, "service.py"))}, run_name='__main__')\n`);
  const client = new BackendClient({ python, packageRoot: runtime, log: () => {} });
  t.after(() => client.dispose());
  const session = new ProjectSession(() => {}, () => {}); await session.open(client, project);
  return { client, session, project };
}

test("real service completes a proposal using only the shared fixture provider executable", { timeout: 30_000 }, async t => {
  const { client, session, project } = await controlledService(t);
  const model = new WorkflowModel(session, client, () => {}, () => {});
  const completed = await model.run("architecture", input, token(), () => {});
  assert.equal(completed?.workflow?.state, "completed", JSON.stringify(completed));
  assert.equal(completed?.workflow?.result?.build?.ok, true);
  assert.match(await readFile(join(project, ".icoda/worktree/src/helper.py"), "utf8"), /helper stub/);
  const source = await client.request<{ path: string }>("source.resolve", { file: "src/main.py", sourceRootId: session.sourceRootId }, session.identity.context);
  assert.equal(source.path, join(project, "src/main.py"));
  const review = new ProposalModel(session, client, () => {}, () => {});
  assert.ok((await review.load([]))?.proposal?.canApprove);
  assert.ok(await review.mutate("proposal.approve", { unsavedDocuments: [] }));
  const log = await readFile(join(project, ".icoda/steps.jsonl"), "utf8");
  assert.equal(JSON.parse(log.trim().split("\n").at(-1)!).decision, "approved");
  const commit = await promisify(execFile)("git", ["log", "-1", "--format=%s"], { cwd: project });
  assert.match(commit.stdout, /icoda\(architecture\) step 1: Add helper stub/);
  assert.match(await readFile(join(project, "src/helper.py"), "utf8"), /helper stub/);
  review.dispose(); model.dispose();
});

function purposeStatus(): WorkflowStatus {
  return { ...context, workflow: { id: "purpose-job", kind: "purpose", state: "completed", message: "Ready", error: null,
    result: { round: "purpose", summary: "Add documentation", candidateLocation: "/candidate", files: ["src/main.py"] } } };
}

async function purposeView(model: WorkflowModel, session: ProjectSession, window: object = {}) {
  const errors: string[] = [], information: string[] = [], warnings: string[] = [];
  const workspace = { isTrusted: true, textDocuments: [] as { isDirty: boolean; uri: { toString(): string } }[] };
  const file = resolve(__dirname, "../workflowView.js"), requireFromView = createRequire(file);
  const loaded = { exports: {} as { WorkflowView: { prototype: object } } };
  runInNewContext(await readFile(file, "utf8"), { exports: loaded.exports, require: (id: string) => id === "vscode" ? {
    workspace, ProgressLocation: { Notification: 1 }, TreeItem: class { constructor(readonly label: string) {} }, window: {
      showErrorMessage: (message: string) => errors.push(message),
      showInformationMessage: (message: string) => information.push(message),
      showWarningMessage: (message: string) => warnings.push(message), ...window,
    } } : requireFromView(id) });
  const view = Object.assign(Object.create(loaded.exports.WorkflowView.prototype), { model, session, idle: () => true, lastSave: 0,
    purpose: { snapshot: undefined, sync() {} }, background: { async stop() {}, activity() {}, sync() {} }, foreground: 0 });
  return { view, workspace, errors, information, warnings };
}

test("untrusted workspace sends no purpose decisions and preserves source and candidate files", { timeout: 30_000 }, async t => {
  const { client, session, project } = await controlledService(t);
  const calls: string[] = [];
  const model = new WorkflowModel(session, { request: (method, params, context) => {
    calls.push(method); return client.request(method, params, context);
  } }, () => {}, () => {});
  t.after(() => model.dispose());
  const result = await model.run("purpose", { unsavedDocuments: [], idle: true, provider: "fixture", model: "purpose" }, token(), () => {});
  assert.equal(result?.workflow?.state, "completed");
  const source = join(project, "tests/test_main.py"), candidate = join(result!.workflow!.result!.candidateLocation!, "tests/test_main.py");
  const before = await readFile(source), checked = await readFile(candidate);
  calls.length = 0;
  const { view, workspace, warnings, errors, information } = await purposeView(model, session);
  const handlers = new Map<string, (...args: unknown[]) => unknown>();
  registerWorkflowCommands((name, action) => handlers.set(name, action), (kind, title) => view.execute(kind, title));
  workspace.isTrusted = false;
  for (const method of ["purpose.apply", "purpose.reject"] as const) {
    const node = view.getChildren().find((node: { id: string }) => node.id === method);
    await handlers.get(view.getTreeItem(node).command.command)!();
    assert.deepEqual(calls, []);
    assert.deepEqual(await readFile(source), before); assert.deepEqual(await readFile(candidate), checked);
    assert.equal(model.snapshot?.workflow?.id, result?.workflow?.id);
    assert.match(warnings.at(-1)!, /trusted workspace/);
  }
  assert.equal(warnings.length, 2); assert.deepEqual(errors, []); assert.deepEqual(information, []);
});

test("disposed or stale purpose actions do not reach the decision model", async () => {
  for (const method of ["purpose.apply", "purpose.reject"] as const) {
    for (const blocked of ["disposed", "stale"]) {
      const { model, session } = setup(() => undefined);
      let decisions = 0;
      model.decidePurpose = async () => { decisions++; return undefined; };
      const { view } = await purposeView(model, session);
      if (blocked === "disposed") view.disposed = true;
      else session.identity.isCurrent = () => false;
      await view.execute(method, "Purpose Comments");
      assert.equal(decisions, 0, `${method}: ${blocked}`);
    }
  }
});

test("decidePurpose forwards trusted=false to the backend for apply and reject", async () => {
  for (const method of ["purpose.apply", "purpose.reject"] as const) {
    const { model, calls } = setup(() => { throw new BackendError("workspace_untrusted", "Trust this workspace."); });
    model.snapshot = purposeStatus();
    await assert.rejects(model.decidePurpose(method, true, [], false), { code: "workspace_untrusted" });
    assert.deepEqual(calls, [{ method, params: { workflowId: "purpose-job", idle: true, unsavedDocuments: [], trusted: false } }]);
    assert.equal(model.snapshot.workflow?.id, "purpose-job");
  }
});

test("purpose candidate tree actions route apply/reject with the selected workflow ID and clear decided state", async () => {
  for (const method of ["purpose.apply", "purpose.reject"] as const) {
    const fixture = setup(() => ({ ...context, modelRevision: 2, model: { files: [], entities: [], edges: [], stale: false, stale_reason: "" },
      decision: method === "purpose.apply" ? "applied" : "rejected", skipped: [], record: null, records: [] }));
    fixture.model.snapshot = purposeStatus();
    const { view, information, errors } = await purposeView(fixture.model, fixture.session);
    const node = view.getChildren().find((node: { id: string }) => node.id === method);
    const command = view.getTreeItem(node).command.command;
    const handlers = new Map<string, (...args: unknown[]) => unknown>();
    registerWorkflowCommands((name, action) => handlers.set(name, action), (kind, title) => view.execute(kind, title));
    await handlers.get(command)!();
    assert.deepEqual(fixture.calls, [{ method, params: { workflowId: "purpose-job", trusted: true, idle: true, unsavedDocuments: [] } }]);
    assert.equal(fixture.model.snapshot, undefined); assert.equal(fixture.session.identity.context?.modelRevision, 2);
    assert.match(information[0]!, /Purpose comments (applied|rejected)/); assert.deepEqual(errors, []);
  }
});

test("purpose decision errors are displayed and logged while the candidate remains rejectable", async () => {
  const fixture = setup(() => { throw new BackendError("stale_evidence", "Candidate changed; reject and propose again."); });
  fixture.model.snapshot = purposeStatus();
  const { view, errors } = await purposeView(fixture.model, fixture.session);
  await view.execute("purpose.apply", "Apply Purpose Comments");
  assert.match(errors[0]!, /stale_evidence.*Candidate changed/);
  assert.match(fixture.diagnostics[0]!, /stale_evidence/);
  assert.equal(fixture.model.snapshot.workflow?.id, "purpose-job");
});

test("dirty VS Code source and candidate documents block purpose application through the real service", { timeout: 30_000 }, async t => {
  const { client, session, project } = await controlledService(t);
  const model = new WorkflowModel(session, client, () => {}, () => {});
  t.after(() => model.dispose());
  const result = await model.run("purpose", { unsavedDocuments: [], idle: true, provider: "fixture", model: "purpose" }, token(), () => {});
  assert.equal(result?.workflow?.state, "completed");
  const source = join(project, "tests/test_main.py"), before = await readFile(source, "utf8");
  const { view, workspace, errors, information } = await purposeView(model, session);
  for (const root of [project, result!.workflow!.result!.candidateLocation!]) {
    workspace.textDocuments = [{ isDirty: true, uri: { toString: () => pathToFileURL(join(root, "tests/test_main.py")).href } }];
    await view.execute("purpose.apply", "Apply Purpose Comments");
    assert.match(errors.at(-1)!, /purpose_not_ready.*unsaved/);
    assert.equal(await readFile(source, "utf8"), before);
    assert.equal(model.snapshot?.workflow?.id, result?.workflow?.id);
  }
  workspace.textDocuments = [];
  await view.execute("purpose.apply", "Apply Purpose Comments");
  assert.equal(errors.length, 2); assert.match(information[0]!, /Purpose comments applied/);
  assert.match(await readFile(source, "utf8"), /Check the fixture arithmetic/);
  assert.equal(session.data?.modelState, "stale");
});

const queueSettings: QueueSettings = { batchSize: 1, scope: "queue_order", grouping: "single_entity", autoApprove: true,
  scopes: [{ value: "queue_order", label: "Queue order" }, { value: "single_entity", label: "Single entity" }],
  groupings: [{ value: "single_entity", label: "One entity" }] };
function queueStatus(state: "running" | "stopped" = "stopped", reason = "Not started."): WorkflowStatus {
  return { ...context, workflow: null, queueSettings, continuation: { state, reason, ready: state === "running" } };
}

test("queue settings validate inputs, route get/set and render native commands and stop reasons", async () => {
  const { model, calls } = setup(() => queueStatus());
  await model.loadQueue();
  await model.setQueue({ batchSize: 3, scope: "single_entity", autoApprove: false });
  assert.deepEqual(calls, [
    { method: "queue.settings.get", params: { trusted: true } },
    { method: "queue.settings.set", params: { trusted: true, settings: { batchSize: 3, scope: "single_entity", autoApprove: false } } },
  ]);
  for (const patch of [{}, { batchSize: 0 }, { batchSize: true }, { scope: "bad" }, { grouping: null }, { autoApprove: 1 }, { trusted: true }]) {
    assert.equal(validQueuePatch(patch, queueSettings), false);
    await assert.rejects(model.setQueue(patch as never), { code: "invalid_params" });
  }
  const nodes = workflowNodes(queueStatus("stopped", "the proposal test gate is not passing"));
  assert.equal(nodes.filter(node => node.command?.startsWith("icoda.queue")).length, 4);
  assert.ok(nodes.some(node => node.label === "Automatic continuation: stopped" && /test gate/.test(node.description!)));
  assert.ok(workflowNodes(queueStatus("running", "")).some(node => node.label === "Automatic continuation: running"));
});

test("queue settings and continuation enforce trust, stale tickets, disposal and late reply guards", async () => {
  for (const blocked of ["untrusted", "stale", "disposed", "late"]) {
    const fixture = setup(() => queueStatus());
    let trusted = blocked !== "untrusted", release!: () => void;
    const pending = new Promise<void>(resolve => { release = resolve; });
    const calls: string[] = [];
    const model = new WorkflowModel(fixture.session, { request: async <T>(method: string) => {
      calls.push(method); if (blocked === "late") await pending; return queueStatus() as T;
    } }, () => {}, () => {}, async () => {}, () => trusted);
    const ticket = fixture.session.identity.capture();
    if (blocked === "stale") fixture.session.reset();
    if (blocked === "disposed") model.dispose();
    const load = model.loadQueue(ticket);
    if (blocked === "late") { fixture.session.reset(); release(); }
    assert.equal(await load, undefined);
    await model.setQueue({ batchSize: 2 }, ticket);
    assert.equal(await model.continueQueue({ unsavedDocuments: [] }, token(), () => {}, ticket), undefined);
    assert.equal(calls.length, blocked === "late" ? 1 : 0);
    assert.equal(model.snapshot, undefined);
    trusted = false;
  }
});

test("queue continuation routes fresh evidence and live dirty buffers before automatic approval", async () => {
  const { session } = setup(() => undefined), calls: { method: string; params: any }[] = [];
  let dirty: string[] = [];
  const candidate = { ...status("completed"), ...queueStatus("running", ""), workflow: status("completed").workflow };
  const model = new WorkflowModel(session, { request: async <T>(method: string, params: unknown) => {
    calls.push({ method, params });
    if (method === "proposal.get") { dirty = ["file:///project/dirty.py"]; return { ...context, evidenceFingerprint: "fresh" } as T; }
    if (calls.filter(call => call.method === "queue.continue").length === 1) return candidate as T;
    throw new BackendError("unsaved_documents", "Save or close unsaved documents.");
  } }, () => {}, () => {}, async () => {}, () => true, () => dirty);
  await assert.rejects(model.continueQueue({ unsavedDocuments: [] }, token(), () => {}), { code: "unsaved_documents" });
  assert.deepEqual(calls.map(call => call.method), ["queue.continue", "proposal.get", "queue.continue"]);
  assert.deepEqual(calls[2]!.params, { trusted: true, unsavedDocuments: dirty, evidenceFingerprint: "fresh" });
  assert.equal(model.snapshot?.continuation?.state, "stopped");
});

test("queue continuation cancellation and trust loss prevent the next automatic decision", async () => {
  for (const reason of ["cancel", "trust", "disposed"]) {
    const { session } = setup(() => undefined), calls: string[] = [], cancellation = token();
    let trusted = true;
    const running = { ...status(), ...queueStatus("running", ""), workflow: status().workflow };
    const model = new WorkflowModel(session, { request: async <T>(method: string) => {
      calls.push(method); return (method === "workflow.cancel" ? queueStatus("stopped", "Cancelled.") : running) as T;
    } }, () => {}, () => {}, async () => {
      if (reason === "cancel") cancellation.cancel();
      else if (reason === "trust") trusted = false;
      else model.dispose();
    }, () => trusted);
    await model.continueQueue({ unsavedDocuments: [] }, cancellation, () => {});
    assert.equal(calls.filter(method => method === "queue.continue").length, 1);
    assert.ok(calls.includes("workflow.cancel")); assert.ok(cancellation.disposed);
  }
});

test("queue native settings reject untrusted, stale and disposed commands", async () => {
  for (const blocked of ["untrusted", "stale", "disposed"]) {
    const { model, session, calls } = setup(() => queueStatus());
    const { view, workspace } = await purposeView(model, session);
    if (blocked === "untrusted") workspace.isTrusted = false;
    if (blocked === "stale") session.identity.isCurrent = () => false;
    if (blocked === "disposed") view.disposed = true;
    await view.execute("queue.batchSize", "Set Queue Batch Size");
    assert.deepEqual(calls, []);
  }
});

test("real controlled queue stops for approach review then automatically approves code and renders empty", { timeout: 40_000 }, async t => {
  const { client, session, project } = await controlledService(t, "implementation");
  const model = new WorkflowModel(session, client, () => {}, () => {});
  t.after(() => model.dispose());
  await model.loadQueue(); await model.setQueue({ autoApprove: true });
  const stopped = await model.continueQueue({ provider: "fixture", model: "ok", unsavedDocuments: [] }, token(), () => {});
  assert.match(stopped?.continuation?.reason ?? "", /approach rounds require developer approval/);
  const review = new ProposalModel(session, client, () => {}, () => {});
  t.after(() => review.dispose());
  await review.load([]); assert.ok(await review.mutate("proposal.approve", { unsavedDocuments: [] }));
  model.sync();
  const resumed = await model.loadQueue();
  assert.equal(resumed?.continuation?.ready, true);
  const { view } = await purposeView(model, session, {
    withProgress: (_options: unknown, action: any) => action({ report() {} }, token()),
  });
  const errors: string[] = [];
  view.output = { appendLine: (text: string) => errors.push(text) };
  view.review = () => {};
  view.continueAfterApproval();
  const deadline = Date.now() + 20_000;
  while (model.snapshot?.continuation?.state !== "stopped" && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  assert.deepEqual(errors, []);
  const finished = model.snapshot;
  assert.equal(finished?.continuation?.state, "stopped"); assert.match(finished?.continuation?.reason ?? "", /empty/);
  assert.match(await readFile(join(project, "src/main.py"), "utf8"), /return 1/);
  assert.equal(JSON.parse(await readFile(join(project, ".icoda/state.json"), "utf8")).implementation_cursor, 1);
  assert.equal(session.identity.context?.modelRevision, 3);
});

test("queue native inputs route all four tree controls and discard cancelled or obsolete choices", async () => {
  for (const key of ["batchSize", "scope", "grouping", "autoApprove"] as const) {
    for (const outcome of ["accept", "cancel", "stale", "disposed", "untrusted"]) {
      const { model, session, calls } = setup(() => queueStatus());
      const value = { batchSize: 3, scope: "single_entity", grouping: "single_entity", autoApprove: false }[key];
      const choose = () => {
        if (outcome === "stale") session.reset();
        if (outcome === "disposed") view.disposed = true;
        if (outcome === "untrusted") workspace.isTrusted = false;
        return outcome === "cancel" ? undefined : key === "batchSize" ? String(value) : { value };
      };
      const { view, workspace } = await purposeView(model, session, { showInputBox: choose, showQuickPick: choose });
      model.snapshot = queueStatus();
      const node = view.getChildren().find((item: { id: string }) => item.id === `queue.${key}`);
      const handlers = new Map<string, (...args: unknown[]) => unknown>();
      registerWorkflowCommands((name, action) => handlers.set(name, action), (kind, title) => view.execute(kind, title));
      await handlers.get(view.getTreeItem(node).command.command)!();
      assert.deepEqual(calls.map(call => call.method), outcome === "accept" ? ["queue.settings.get", "queue.settings.set"] : ["queue.settings.get"]);
      if (outcome === "accept") assert.deepEqual(JSON.parse(JSON.stringify(calls[1]!.params)), { trusted: true, settings: { [key]: value } });
    }
  }
});

test("queue late failures after disposal or selection change are discarded", async () => {
  for (const method of ["load", "set", "continue"]) {
    for (const change of ["dispose", "session", "revision", "target", "trust"]) {
      const { session } = setup(() => undefined);
      let reject!: (error: Error) => void, trusted = true;
      const pending = new Promise<never>((_, fail) => { reject = fail; });
      const diagnostics: string[] = [];
      const model = new WorkflowModel(session, { request: async () => pending }, () => {}, text => diagnostics.push(text), async () => {}, () => trusted);
      model.snapshot = queueStatus();
      const action = method === "load" ? model.loadQueue() : method === "set" ? model.setQueue({ batchSize: 2 })
        : model.continueQueue({ unsavedDocuments: [] }, token(), () => {});
      if (change === "dispose") model.dispose();
      else if (change === "session") session.reset();
      else if (change === "trust") trusted = false;
      else session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2,
        targetId: change === "target" ? "new" : null }, change === "target" ? { targetId: "new" } : "workflow");
      reject(new BackendError("provider_failed", "Obsolete failure"));
      await action;
      assert.deepEqual(diagnostics, []);
    }
  }
});

test("native queue progress forwards approval cancellation to the backend adapter", async () => {
  const file = resolve(__dirname, "../workflowView.js"), requireFromView = createRequire(file);
  const loaded = { exports: {} as { WorkflowView: new (...args: any[]) => any } };
  const noop = { dispose() {} }, cancellation = token(), calls: string[] = [];
  let forwarded: AbortSignal | undefined;
  const { session } = setup(() => undefined);
  const client = { request: async (method: string, _params: unknown, _context: unknown, options?: { signal?: AbortSignal }) => {
    calls.push(method);
    if (method === "queue.continue") { forwarded = options?.signal; cancellation.cancel(); }
    return queueStatus("stopped", "Cancelled.");
  } };
  runInNewContext(await readFile(file, "utf8"), { exports: loaded.exports, require: (id: string) => id === "vscode" ? {
    EventEmitter: class { event = () => noop; fire() {} dispose() {} },
    workspace: { isTrusted: true, textDocuments: [], onDidSaveTextDocument: () => noop,
      onDidChangeTextDocument: () => noop, onDidChangeConfiguration: () => noop },
    commands: { registerCommand: () => noop }, ProgressLocation: { Notification: 1 },
    window: { createTreeView: () => noop, createOutputChannel: () => ({ ...noop, appendLine() {} }),
      onDidChangeActiveTextEditor: () => noop, onDidChangeTextEditorSelection: () => noop,
      withProgress: (_options: unknown, run: any) => run({ report() {} }, cancellation) },
  } : requireFromView(id) });
  const view = new loaded.exports.WorkflowView(session, async () => client, () => true);
  await view.runQueue({ unsavedDocuments: [] });
  assert.ok(forwarded?.aborted); assert.ok(calls.includes("workflow.cancel"));
  assert.ok(cancellation.disposed); view.dispose();
});

const conversationInput = { unsavedDocuments: [], provider: "fixture", model: "ok", message: "Explain run" };
function interactionStatus(kind: string, state = "completed"): WorkflowStatus {
  return { ...context, workflow: { id: "interaction", kind, state, message: "Reply ready", error: null,
    result: state === "completed" ? { round: kind, summary: "A plain reply <tag>", files: [], candidateLocation: null } : null } };
}
const cliReply = { ...context, argv: ["/path with spaces/provider", "--model", "a model", 'hello; $(touch bad) "quoted"\nGrüße'],
  cwd: "/project with spaces", env: { CUSTOM: "literal $value" } };

test("conversation and rephrase route to scoped cancellable workflows and render replies", async () => {
  for (const kind of ["conversation.send", "prompt.rephrase"] as const) {
    const { model, calls } = setup(method => interactionStatus(kind, method === kind ? "running" : "completed"));
    const args = kind === "conversation.send" ? conversationInput : { ...conversationInput, message: undefined };
    const reply = await model.run(kind, args, token(), () => {});
    assert.deepEqual(calls.map(call => call.method), [kind, "workflow.status"]);
    assert.deepEqual(calls[0]!.params, { ...args, trusted: true });
    assert.ok(workflowNodes(reply).some(node => node.label === "Latest reply" && node.description === "A plain reply <tag>"));
    assert.ok(workflowNodes(reply).some(node => node.command === "icoda.openCLI"));
  }
  const { model, calls } = setup(method => method === "cli.command" ? cliReply : { ...context,
    messages: [{ role: "Developer", text: "Hi" }, { role: "Assistant", text: "plain <tag>" }] });
  assert.equal(conversationText((await model.history())!), "Developer:\nHi\n\nAssistant:\nplain <tag>");
  assert.deepEqual(await model.cli({ unsavedDocuments: [], draft: "quoted draft" }), cliReply);
  assert.deepEqual(calls.map(call => call.method), ["conversation.history", "cli.command"]);
});

test("CLI terminal options preserve argument boundaries and reject malformed backend commands", async () => {
  assert.deepEqual(terminalOptions(cliReply), { name: "ICODA CLI", shellPath: cliReply.argv[0],
    shellArgs: cliReply.argv.slice(1), cwd: cliReply.cwd, env: cliReply.env });
  for (const invalid of [{ ...cliReply, argv: "shell command" }, { ...cliReply, argv: [] },
    { ...cliReply, argv: ["binary", "bad\0"] }, { ...cliReply, cwd: null }, { ...cliReply, env: { X: 1 } }]) {
    assert.throws(() => terminalOptions(invalid as never), /Invalid ICODA CLI/);
  }
});

test("interaction input guards reject blank messages and injected provider commands", async () => {
  const { model, calls } = setup(() => assert.fail("Invalid input must not reach the backend"));
  for (const args of [{ ...conversationInput, message: " " }, { ...conversationInput, message: "a".repeat(20001) },
    { ...conversationInput, message: "\0" }, { ...conversationInput, argv: ["command"] }]) {
    await assert.rejects(model.run("conversation.send", args, token(), () => {}), /Invalid AI/);
  }
  await assert.rejects(model.run("conversation.send", { unsavedDocuments: [] }, token(), () => {}), /Invalid AI/);
  await assert.rejects(model.cli({ ...conversationInput }), /Invalid CLI/);
  assert.equal(calls.length, 0);
});

test("interaction trust loss cancels providers and blocks terminal and history requests", async () => {
  for (const initiallyTrusted of [false, true]) {
    let trusted = initiallyTrusted;
    const { session } = setup(() => {}), calls: string[] = [];
    const model = new WorkflowModel(session, { async request<T>(method: string) {
      calls.push(method); trusted = false; return interactionStatus("conversation.send", "running") as T;
    } }, () => {}, () => {}, async () => {}, () => trusted);
    assert.equal(await model.run("conversation.send", conversationInput, token(), () => {}), undefined);
    assert.deepEqual(calls, initiallyTrusted ? ["conversation.send", "workflow.cancel"] : []);
    assert.equal(await model.history(), undefined);
    assert.equal(await model.cli({ unsavedDocuments: [] }), undefined);
    assert.equal(model.snapshot, undefined);
  }
});

test("interaction replies and failures are discarded after session target revision change or disposal", async () => {
  for (const action of ["conversation.send", "prompt.rephrase", "conversation.history", "cli.command"] as const) {
    for (const change of ["session", "target", "revision", "dispose"]) {
      for (const failure of [false, true]) {
        let release!: () => void;
        const pending = new Promise<void>(resolve => { release = resolve; });
        const { model, session, diagnostics } = setup(async () => {
          await pending; if (failure) throw new Error("Old provider error");
          return action === "cli.command" ? cliReply : action === "conversation.history" ? { ...context, messages: [] } : interactionStatus(action);
        });
        const work = action === "cli.command" ? model.cli({ unsavedDocuments: [] }) : action === "conversation.history" ? model.history()
          : model.run(action, action === "conversation.send" ? conversationInput : { unsavedDocuments: [] }, token(), () => {});
        if (change === "session") { session.reset(); session.identity.accept(session.identity.capture(), { ...context, sessionId: "other" }, "open"); }
        else if (change === "dispose") model.dispose();
        else session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2,
          targetId: change === "target" ? "next" : null }, change === "target" ? { targetId: "next" } : "workflow");
        release(); assert.equal(await work, undefined); assert.deepEqual(diagnostics, []); assert.equal(model.snapshot, undefined);
      }
    }
  }
});

test("P09 workflows inherit the project provider when the workspace setting disagrees", async () => {
  const { model, session } = setup(() => assert.fail("Collecting input must not invoke a provider"));
  const { view, workspace } = await purposeView(model, session, {
    showInputBox: () => "Use the saved provider", showQuickPick: () => [],
  });
  Object.assign(workspace, { getConfiguration: () => ({ get: () => ({ provider: "stale-setting", model: "fail" }) }) });
  for (const kind of ["architecture", "implementation_approach", "implementation_queue", "purpose",
    "conversation.send", "prompt.rephrase", "cli.command"]) {
    const input = await view.input(kind);
    assert.ok(input, kind);
    assert.equal(input.provider, undefined, kind);
    assert.equal(input.model, undefined, kind);
  }
});

test("native conversation rephrase history and CLI use input pick output and argument-array terminal", async () => {
  for (const kind of ["conversation.send", "prompt.rephrase", "conversation.history", "cli.command"] as const) {
    const { model, session, calls } = setup(method => method === "cli.command" ? cliReply : method === "conversation.history"
      ? { ...context, messages: [{ role: "Assistant", text: "Saved reply" }] } : interactionStatus(kind));
    const output: string[] = [], terminals: unknown[] = [], prompts: unknown[] = [];
    const { view, workspace, errors } = await purposeView(model, session, {
      showInputBox: (options: unknown) => { prompts.push(options); return "Hello provider"; },
      showQuickPick: (options: unknown) => { prompts.push(options); return "Simplify"; },
      withProgress: (_: unknown, run: (progress: unknown, token: unknown) => unknown) => run({ report() {} }, token()),
      createTerminal: (options: unknown) => { terminals.push(options); return { show() {}, dispose() {} }; },
    });
    Object.assign(workspace, { getConfiguration: () => ({ get: () => undefined }) });
    Object.assign(view, { output: { appendLine: (text: string) => output.push(text), show() {} }, disposables: [], review() {} });
    await view.execute(kind, kind);
    assert.deepEqual(errors, []);
    assert.equal(calls[0]!.method, kind);
    assert.equal(prompts.length, kind === "conversation.history" ? 0 : 1);
    if (kind === "cli.command") {
      assert.equal(terminals.length, 1);
      assert.deepEqual(terminals[0], { name: "ICODA CLI", shellPath: cliReply.argv[0], shellArgs: cliReply.argv.slice(1), cwd: cliReply.cwd, env: cliReply.env });
    } else assert.match(output.join("\n"), kind === "conversation.history" ? /Saved reply/ : /A plain reply <tag>/);
  }
});

test("native interaction guards prevent untrusted or stale terminal launches and reply rendering", async () => {
  for (const kind of ["conversation.send", "prompt.rephrase", "conversation.history", "cli.command"] as const) {
    for (const change of ["untrusted", "target", "dispose"]) {
      const { model, session, calls } = setup(() => { mutate(); return kind === "cli.command" ? cliReply : kind === "conversation.history"
        ? { ...context, messages: [] } : interactionStatus(kind); });
      const { view, workspace } = await purposeView(model, session, {
        withProgress: (_: unknown, run: (progress: unknown, token: unknown) => unknown) => run({ report() {} }, token()),
        createTerminal: () => assert.fail("No terminal after context change"),
      });
      view.input = async () => kind === "conversation.send" ? conversationInput : { unsavedDocuments: [] };
      view.output = { appendLine: () => assert.fail("No late reply rendering"), show() {} };
      function mutate() {
        if (change === "untrusted") workspace.isTrusted = false;
        else if (change === "dispose") view.disposed = true;
        else session.identity.accept(session.identity.capture(), { ...context, targetId: "next", modelRevision: 2 }, { targetId: "next" });
      }
      await view.execute(kind, kind);
      assert.equal(calls[0]?.method, kind);
      calls.length = 0; workspace.isTrusted = false;
      await view.execute(kind, kind); assert.equal(calls.length, 0);
    }
  }
});

test("controlled service conversations and rephrase retain proposal review and provider diagnostics", { timeout: 30_000 }, async t => {
  const { client, session } = await controlledService(t);
  const diagnostics: string[] = [];
  const model = new WorkflowModel(session, client, () => {}, text => diagnostics.push(text));
  t.after(() => model.dispose());
  const reply = await model.run("conversation.send", conversationInput, token(), () => {});
  assert.match(reply?.workflow?.result?.summary ?? "", /Controlled conversation reply/);
  assert.equal((await model.history())?.messages.length, 2);
  await model.run("architecture", input, token(), () => {});
  const rephrase = await model.run("prompt.rephrase", { unsavedDocuments: [], provider: "fixture", model: "ok" }, token(), () => {});
  assert.equal(rephrase?.workflow?.result?.summary, "A simpler description of the same step.");
  const review = new ProposalModel(session, client, () => {}, () => {});
  assert.ok((await review.load([]))?.proposal?.canApprove);
  const failed = await model.run("conversation.send", { ...conversationInput, model: "fail" }, token(), () => {});
  assert.equal(failed?.workflow?.error?.code, "provider_failed");
  assert.ok(diagnostics.some(message => message.includes("provider_failed")));
  review.dispose();
});
