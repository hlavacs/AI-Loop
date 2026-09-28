import * as assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import { ProjectSession } from "../projectSession";
import { BackendError, SessionContext } from "../protocol";
import { candidateDiff, ProposalReview, proposalCommands, proposalNodes, registerProposalCommands, validCandidateSelection, validRecoverySelection, validReviewInput } from "../proposalData";
import { ProposalModel } from "../proposalModel";

const context: SessionContext = { sessionId: "project", modelRevision: 1, targetId: null };
const emptyModel = { files: [], entities: [], edges: [], stale: false, stale_reason: "" };
function review(): ProposalReview {
  return { ...context, projectRoot: "/project", evidenceFingerprint: "review", records: [], autoApprove: false, message: "Ready",
    proposal: { round: "code", number: 1, summary: "Change helper", worktreeRoot: "/project/.icoda/worktree", files: [{ path: "src/helper.py", status: "M" }],
      delta: "Changed helper", error: "", entitySummary: "[]", signatureChanges: [], build: { ok: true, output: "built" },
      tests: { ok: true, output: "tested" }, evidenceFresh: true, canApprove: true } };
}
function setup(respond: (method: string, params: unknown) => unknown) {
  const calls: { method: string; params: unknown }[] = [], output: string[] = [];
  const session = new ProjectSession(() => {}, () => {});
  session.identity.accept(session.identity.capture(), context, "open");
  const client = { async request<T>(method: string, params: unknown) { calls.push({ method, params }); return await respond(method, params) as T; } };
  const model = new ProposalModel(session, client, () => {}, message => output.push(message), async () => {});
  return { model, session, calls, output };
}

async function viewClass(name: string, vscode: object): Promise<Record<string, { prototype: Record<string, (...args: unknown[]) => unknown> }>> {
  const file = resolve(__dirname, `../${name}.js`), exports = {}, requireFromView = createRequire(file);
  runInNewContext(await readFile(file, "utf8"), { exports, require: (id: string) => id === "vscode" ? vscode : requireFromView(id) });
  return exports;
}

test("AI workflow commands visibly explain untrusted workspaces before doing any work", async () => {
  const messages: string[] = [];
  const loaded = await viewClass("workflowView", { workspace: { isTrusted: false }, window: { showWarningMessage: (message: string) => messages.push(message) } });
  for (const kind of ["architecture", "implementation_approach", "implementation_queue", "purpose", "cancel"]) {
    await loaded.WorkflowView!.prototype.execute!.call({}, kind, "AI workflow");
  }
  assert.equal(messages.length, 5);
  assert.ok(messages.every(message => /AI workflows need a trusted workspace/.test(message)));
});

test("all proposal command paths visibly explain untrusted workspaces before doing any work", async () => {
  const messages: string[] = [];
  const loaded = await viewClass("proposalView", { workspace: { isTrusted: false },
    window: { showWarningMessage: (message: string) => messages.push(message) } });
  const view = Object.create(loaded.ProposalView!.prototype);
  for (const command of proposalCommands) await view.execute(command.method);
  await view.diff({ ...context, evidenceFingerprint: "review", path: "src/helper.py" });
  assert.equal(messages.length, proposalCommands.length + 1);
  assert.ok(messages.every(message => /Proposal decisions need a trusted workspace/.test(message)));
});

async function decisionView(respond: (method: string, params: unknown) => unknown,
  confirm: (...args: unknown[]) => unknown = () => "Confirm signatures") {
  const fixture = setup(respond), warnings: unknown[][] = [], errors: string[] = [];
  const workspace = { isTrusted: true, textDocuments: [] as { isDirty: boolean; uri: { toString(): string } }[] };
  const loaded = await viewClass("proposalView", { workspace, ProgressLocation: { Notification: 1 }, window: {
    showWarningMessage: (...args: unknown[]) => { warnings.push(args); return confirm(...args); },
    showErrorMessage: (message: string) => errors.push(message),
    withProgress: async (_options: unknown, work: Function) => work({ report() {} }, { onCancellationRequested: () => ({ dispose() {} }) }),
  } });
  const view = Object.assign(Object.create(loaded.ProposalView!.prototype), { model: fixture.model, session: fixture.session,
    candidateChanged() {}, output: { show() {}, appendLine() {} } });
  fixture.model.snapshot = review();
  fixture.model.snapshot.proposal!.signatureChanges = [{ usr: "helper", display_name: "helper",
    previous_signature: "def helper()", proposed_signature: "def helper(value)" }];
  return { ...fixture, view, workspace, warnings, errors };
}

test("backend signature code opens the modal and retries only with explicit confirmation", async () => {
  let attempts = 0;
  const fixture = await decisionView(() => {
    if (++attempts === 1) throw new BackendError("signature_unconfirmed", "Confirm signatures first.");
    return { ...context, modelRevision: 2, sourceRootId: "root", root: "/project", model: emptyModel, records: [], record: null };
  });
  assert.ok(await fixture.view.decide("proposal.approve", { unsavedDocuments: [] }, "review"));
  assert.equal(fixture.warnings.length, 1);
  assert.match(String(fixture.warnings[0]![0]), /Confirm.*signature/);
  const options = fixture.warnings[0]![1] as { modal: boolean; detail: string };
  assert.equal(options.modal, true);
  assert.match(options.detail, /def helper\(\)/); assert.match(options.detail, /def helper\(value\)/);
  assert.deepEqual(fixture.calls[1]!.params, { unsavedDocuments: [], confirmSignatures: true, evidenceFingerprint: "review", trusted: true });
});

test("signature retry respects cancellation, trust, current review and dirty editor changes", async () => {
  for (const change of ["cancel", "untrusted", "review", "session", "unsaved"]) {
    const fixture = await decisionView(() => { throw new BackendError("signature_unconfirmed", "Confirm signatures first."); }, () => {
      if (change === "cancel") return undefined;
      if (change === "untrusted") fixture.workspace.isTrusted = false;
      if (change === "review") fixture.model.snapshot!.evidenceFingerprint = "rebuilt";
      if (change === "session") fixture.session.reset();
      if (change === "unsaved") fixture.workspace.textDocuments.push({ isDirty: true, uri: { toString: () => "file:///project/src/helper.py" } });
      return "Confirm signatures";
    });
    const request = fixture.view.decide("proposal.approve", { unsavedDocuments: [] }, "review");
    if (change === "review") await assert.rejects(request, /changed during the decision/);
    else if (change === "unsaved") await assert.rejects(request, /Confirm signatures first/);
    else assert.equal(await request, false);
    assert.equal(fixture.calls.length, change === "unsaved" ? 2 : 1);
    if (change === "untrusted") assert.match(String(fixture.warnings.at(-1)![0]), /trusted workspace/);
    if (change === "unsaved") assert.deepEqual((fixture.calls[1]!.params as { unsavedDocuments: string[] }).unsavedDocuments, ["file:///project/src/helper.py"]);
  }
});

test("proposal commands warn if workspace trust is lost during a decision dialog", async () => {
  const fixture = await decisionView(assert.fail, () => { fixture.workspace.isTrusted = false; return "Confirm signatures"; });
  await fixture.view.execute("proposal.approve");
  assert.deepEqual(fixture.calls, []); assert.deepEqual(fixture.errors, []);
  assert.match(String(fixture.warnings.at(-1)![0]), /Proposal decisions need a trusted workspace/);
});

test("other proposal failures do not request signature confirmation or retry", async () => {
  for (const code of ["dirty_tree", "proposal_gate_failed", "stale_evidence", "undo_disallowed"]) {
    const fixture = await decisionView(() => { throw new BackendError(code, "Controlled refusal"); });
    await assert.rejects(fixture.view.decide("proposal.approve", { unsavedDocuments: [] }, "review"), /Controlled refusal/);
    assert.equal(fixture.calls.length, 1); assert.deepEqual(fixture.warnings, []);
  }
});

test("review commands register with 56 manifest commands and reject injected command arguments", async () => {
  const manifest = JSON.parse(await readFile(resolve(__dirname, "../../package.json"), "utf8"));
  const handlers = new Map<string, (...args: unknown[]) => unknown>(), calls: unknown[] = [];
  registerProposalCommands((name, action) => handlers.set(name, action), method => calls.push(method), value => calls.push(value));
  assert.equal(manifest.contributes.commands.length, 56);
  for (const command of proposalCommands) {
    assert.ok(manifest.activationEvents.includes(`onCommand:${command.command}`));
    assert.equal(manifest.contributes.commands.find((item: { command: string }) => item.command === command.command).title, command.title);
    handlers.get(command.command)!({ trusted: true }); assert.equal(calls.length, 0);
  }
  handlers.get("icoda.openProposalDiff")!({ ...context, path: "../secret", evidenceFingerprint: "review" });
  assert.equal(calls.length, 0);
  for (const command of proposalCommands) handlers.get(command.command)!();
  assert.deepEqual(calls, proposalCommands.map(item => item.method));
  const source = await readFile(resolve(__dirname, "../../src/extension.ts"), "utf8");
  assert.match(source, /new ProposalView/); assert.match(source, /this.proposals.dispose\(\)/);
});

test("candidate diffs use workspace and worktree roots, including Windows and absent sides", () => {
  const value = review();
  assert.deepEqual(candidateDiff(value, "src/helper.py"), { original: "/project/src/helper.py", candidate: "/project/.icoda/worktree/src/helper.py" });
  value.projectRoot = "C:\\project"; value.proposal!.worktreeRoot = "D:\\candidate";
  assert.deepEqual(candidateDiff(value, "src/helper.py"), { original: "C:\\project\\src\\helper.py", candidate: "D:\\candidate\\src\\helper.py" });
  value.proposal!.files[0]!.status = "A"; assert.equal(candidateDiff(value, "src/helper.py").original, null);
  value.proposal!.files[0]!.status = "D"; assert.equal(candidateDiff(value, "src/helper.py").candidate, null);
  for (const path of ["../outside", "C:/outside", "/outside", "src\\helper.py", "src/other.py"]) assert.throws(() => candidateDiff(value, path), /current candidate/);
});

test("native diff command constructs file URIs from the reviewed roots and drops stale tree selections", async () => {
  const calls: unknown[][] = [], value = review();
  const loaded = await viewClass("proposalView", { workspace: { isTrusted: true }, Uri: { file: (path: string) => ({ scheme: "file", fsPath: path }), parse: (path: string) => ({ path }) },
    commands: { executeCommand: (...args: unknown[]) => calls.push(args) }, window: { showErrorMessage: assert.fail } });
  const receiver = Object.assign(Object.create(loaded.ProposalView!.prototype), { model: { snapshot: value }, session: { identity: { context } } });
  const selection = { ...context, evidenceFingerprint: "review", path: "src/helper.py" };
  await loaded.ProposalView!.prototype.diff!.call(receiver, selection);
  assert.deepEqual(calls[0]!.slice(0, 3), ["vscode.diff", { scheme: "file", fsPath: "/project/src/helper.py" }, { scheme: "file", fsPath: "/project/.icoda/worktree/src/helper.py" }]);
  await loaded.ProposalView!.prototype.diff!.call(receiver, { ...selection, modelRevision: 2 });
  assert.equal(calls.length, 1);
});

test("review boundary validates method-specific arguments and safe candidate selections", () => {
  assert.ok(validReviewInput("proposal.approve", { unsavedDocuments: [], confirmSignatures: true }));
  for (const [method, input] of [["proposal.approve", { unsavedDocuments: [], confirmSignatures: "yes" }],
    ["proposal.reject", { unsavedDocuments: [], reason: "" }], ["proposal.approve", { unsavedDocuments: "file" }],
    ["proposal.adapt", { unsavedDocuments: [], constraints: [1] }], ["proposal.approve", { unsavedDocuments: [], trusted: true }],
    ["unknown", { unsavedDocuments: [] }]] as const) assert.equal(validReviewInput(method, input), false);
  const selection = { ...context, evidenceFingerprint: "review", path: "src/helper.py" };
  assert.ok(validCandidateSelection(selection));
  for (const extra of [{ path: "../secret" }, { path: "x\0y" }, { worktreeRoot: "/other" }, { modelRevision: 0 }]) assert.equal(validCandidateSelection({ ...selection, ...extra }), false);
});

test("approval honors backend availability and sends the exact reviewed evidence", async () => {
  const value = review(); value.proposal!.canApprove = false; value.proposal!.tests!.ok = false;
  const { model, calls, output } = setup(method => method === "proposal.get" ? value : { ...context, modelRevision: 2, sourceRootId: "root", root: "/project", model: emptyModel, records: [], record: null });
  await model.load([]);
  assert.ok(proposalNodes(model.snapshot).some(node => node.label === "Tests: failed"));
  assert.match(output[0]!, /built/); assert.match(output[0]!, /tested/);
  await assert.rejects(model.mutate("proposal.approve", { unsavedDocuments: [] }), /Approval is blocked/);
  assert.equal(calls.length, 1);
  value.proposal!.canApprove = true;
  assert.ok(await model.mutate("proposal.approve", { unsavedDocuments: [], confirmSignatures: true }));
  assert.deepEqual(calls[1]!.params, { unsavedDocuments: [], confirmSignatures: true, evidenceFingerprint: "review", trusted: true });
});

test("review reads and decisions discard late success or failure after scope changes or disposal", async () => {
  for (const mutation of [false, true]) for (const failed of [false, true]) for (const change of ["session", "revision", "target", "dispose"]) {
    let release!: () => void;
    const pending = new Promise<void>(resolve => { release = resolve; });
    const { model, session, output } = setup(async () => { await pending; if (failed) throw new BackendError("old", "Obsolete failure"); return review(); });
    if (mutation) model.snapshot = review();
    const request = mutation ? model.mutate("proposal.reject", { unsavedDocuments: [], reason: "Skip" }) : model.load([]);
    if (change === "dispose") model.dispose();
    else if (change === "session") session.reset();
    else session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2, targetId: change === "target" ? "entry" : null }, change === "target" ? { targetId: "entry" } : "workflow");
    release(); assert.ok(!await request); assert.deepEqual(output, []);
    model.sync(); assert.equal(model.snapshot, undefined);
  }
});

test("adapt polls shared workflow progress and cancels its owned job on disposal", async () => {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const { model, calls } = setup(async method => {
    if (method === "workflow.status") await pending;
    return { ...context, workflow: { id: "adapt", state: "running", message: "Checking adapted proposal" } };
  });
  model.snapshot = review();
  const messages: string[] = [];
  const request = model.mutate("proposal.adapt", { unsavedDocuments: [], constraints: ["Keep API"] }, message => messages.push(message));
  await new Promise(resolve => setImmediate(resolve)); model.dispose(); release();
  assert.equal(await request, false);
  assert.deepEqual(messages, ["Checking adapted proposal"]);
  assert.ok(calls.some(call => call.method === "workflow.cancel"));
});

test("signature confirmation stays bound to the review shown before the dialog", async () => {
  const { model, calls } = setup(() => review());
  await model.load([]);
  const confirmedEvidence = model.snapshot!.evidenceFingerprint;
  model.snapshot = { ...review(), evidenceFingerprint: "rebuilt" };
  await assert.rejects(model.mutate("proposal.approve", { unsavedDocuments: [], confirmSignatures: true }, () => {}, confirmedEvidence), /changed during the decision/);
  assert.equal(calls.length, 1);
});

test("disposing during an adaptation start cancels the eventual owned job", async () => {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const { model, calls } = setup(async method => {
    if (method === "proposal.adapt") await pending;
    return { ...context, workflow: { id: "late-adapt", state: "running", message: "Starting" } };
  });
  model.snapshot = review();
  const request = model.mutate("proposal.adapt", { unsavedDocuments: [] });
  model.dispose(); release();
  assert.equal(await request, false);
  assert.deepEqual(calls.at(-1), { method: "workflow.cancel", params: { trusted: true, workflowId: "late-adapt" } });
});

const recoveryId = "a".repeat(64);
function retained(): import("../proposalData").RecoveryList {
  return { ...context, items: [{ id: recoveryId, label: "Interrupted proposal", worktreeRoot: "/project/.icoda/worktree",
    choices: [{ value: "resume", label: "Resume for Review" }, { value: "keep", label: "Keep for Later" }, { value: "discard", label: "Discard Retained Proposal" }] }] };
}
const recoverySelection = { ...context, recoveryId };

test("recovery tree and command boundary use scoped IDs without accepting paths or decisions", async () => {
  const handlers = new Map<string, (...args: unknown[]) => unknown>(), routed: unknown[] = [];
  registerProposalCommands((name, action) => handlers.set(name, action), () => assert.fail(), () => assert.fail(), value => routed.push(value));
  const action = handlers.get("icoda.recoverProposal")!;
  action({ ...recoverySelection, choice: "discard" }); action({ ...recoverySelection, worktreeRoot: "/outside" }); action("discard");
  assert.deepEqual(routed, []);
  action(recoverySelection); action(); assert.deepEqual(routed, [recoverySelection, undefined]);
  assert.ok(validRecoverySelection(recoverySelection));
  assert.equal(validRecoverySelection({ ...recoverySelection, recoveryId: "../outside" }), false);
  const nodes = proposalNodes(undefined, retained());
  assert.equal(nodes.length, 1); assert.equal(nodes[0]!.label, "Interrupted proposal");
  assert.deepEqual(nodes[0]!.recovery, recoverySelection);
  const loaded = await viewClass("proposalView", { TreeItem: class { constructor(readonly label: string) {} } });
  const item = loaded.ProposalView!.prototype.getTreeItem!.call({}, nodes[0]) as { command: { command: string; arguments: unknown[] } };
  assert.equal(item.command.command, "icoda.recoverProposal"); assert.deepEqual(Array.from(item.command.arguments), [recoverySelection]);
  const manifest = JSON.parse(await readFile(resolve(__dirname, "../../package.json"), "utf8"));
  assert.ok(manifest.activationEvents.includes("onCommand:icoda.recoverProposal"));
  assert.match(manifest.contributes.commands.find((item: { command: string }) => item.command === "icoda.recoverProposal").enablement, /isWorkspaceTrusted/);
});

test("recovery model routes every choice, waits for checks, and never routes approval", async () => {
  for (const choice of ["resume", "keep", "discard"] as const) {
    const fixture = setup(method => method === "recovery.list" ? retained() : method === "workflow.status"
      ? { ...context, workflow: { id: "recovery", state: "failed", message: "Tests failed", error: { code: "proposal_failed", message: "Tests failed" } } }
      : choice === "resume" ? { ...context, workflow: { id: "recovery", state: "running", message: "Checking retained files" } } : { ...context, items: choice === "keep" ? retained().items : [] });
    await fixture.model.loadRecoveries();
    assert.ok(await fixture.model.recover(recoverySelection, choice, ["file:///project/.icoda/worktree/unsaved.py"], choice === "discard"));
    assert.deepEqual(fixture.calls[1], { method: "recovery.resolve", params: { recoveryId, choice,
      unsavedDocuments: ["file:///project/.icoda/worktree/unsaved.py"], confirmDiscard: choice === "discard", trusted: true } });
    assert.ok(fixture.calls.every(call => !["proposal.approve", "queue.continue", "workflow.start"].includes(call.method)));
    if (choice === "resume") assert.match(fixture.output[0]!, /Tests failed/);
  }
});

test("recovery model refuses untrusted, stale, disposed, unlisted and unconfirmed decisions", async () => {
  for (const guard of ["untrusted", "stale", "disposed", "unlisted", "unconfirmed"]) {
    const fixture = setup(assert.fail); fixture.model.recoveries = retained();
    if (guard === "disposed") fixture.model.dispose();
    if (guard === "stale") fixture.session.reset();
    if (guard === "unlisted") fixture.model.recoveries.items = [];
    if (guard === "untrusted") {
      const blocked = new ProposalModel(fixture.session, { request: async () => assert.fail("must not start Python") }, () => {}, assert.fail, undefined, () => false);
      blocked.recoveries = retained();
      assert.equal(await blocked.loadRecoveries(), undefined);
      assert.equal(await blocked.recover(recoverySelection, "resume", [], false), false);
    } else if (guard === "unlisted") await assert.rejects(fixture.model.recover(recoverySelection, "keep", [], false), /Refresh interrupted/);
    else assert.equal(await fixture.model.recover(recoverySelection, "discard", [], guard !== "unconfirmed"), false);
    assert.deepEqual(fixture.calls, []);
  }
});

test("recovery ignores late list and resolve replies after restart, selection changes and disposal", async () => {
  for (const method of ["list", "resolve"]) for (const change of ["session", "revision", "target", "dispose"]) for (const failed of [false, true]) {
    let release!: () => void;
    const pending = new Promise<void>(resolve => { release = resolve; });
    const fixture = setup(async () => { await pending; if (failed) throw new Error("old recovery"); return retained(); });
    fixture.model.recoveries = retained();
    const request = method === "list" ? fixture.model.loadRecoveries() : fixture.model.recover(recoverySelection, "keep", [], false);
    if (change === "dispose") fixture.model.dispose();
    else if (change === "session") fixture.session.reset();
    else fixture.session.identity.accept(fixture.session.identity.capture(), { ...context, modelRevision: 2,
      targetId: change === "target" ? "entry" : null }, change === "target" ? { targetId: "entry" } : "workflow");
    release(); assert.ok(!await request); fixture.model.sync(); assert.equal(fixture.model.recoveries, undefined);
    assert.deepEqual(fixture.output, []);
  }
});

async function recoveryView(choice: "resume" | "keep" | "discard", confirm: () => unknown = () => "Discard",
  pick: () => void = () => {}) {
  const fixture = setup(method => method === "recovery.list" ? { ...retained(), ...fixture.session.identity.context } : method === "proposal.get" ? review()
    : choice === "resume" ? { ...context, workflow: { id: "recovered", state: "completed", message: "Review" } } : { ...context, items: choice === "keep" ? retained().items : [] });
  const workspace = { isTrusted: true, textDocuments: [] as { isDirty: boolean; uri: { toString(): string } }[] };
  const warnings: unknown[][] = [], diffs: unknown[][] = [], errors: string[] = [];
  const loaded = await viewClass("proposalView", { workspace, ProgressLocation: { Notification: 1 },
    Uri: { file: (path: string) => ({ path }), parse: (path: string) => ({ path }) }, commands: { executeCommand: (...args: unknown[]) => diffs.push(args) },
    window: { showQuickPick: (choices: { value: string }[]) => { pick(); return choices.find(item => item.value === choice); },
      showWarningMessage: (...args: unknown[]) => { warnings.push(args); return confirm(); },
      showInformationMessage() {}, showErrorMessage: (message: string) => errors.push(message),
      withProgress: async (_options: unknown, work: Function) => work({ report() {} }, { onCancellationRequested: () => ({ dispose() {} }) }) } });
  const view = Object.assign(Object.create(loaded.ProposalView!.prototype), { model: fixture.model, session: fixture.session,
    candidateChanged() {}, output: { show() {}, appendLine() {} } });
  return { ...fixture, view, workspace, warnings, diffs, errors };
}

test("native recovery picker confirms only destructive discard and resume opens the candidate worktree diff", async () => {
  for (const choice of ["resume", "keep", "discard"] as const) {
    const fixture = await recoveryView(choice);
    await fixture.view.recover(recoverySelection);
    assert.deepEqual(fixture.errors, []);
    assert.equal(fixture.warnings.length, choice === "discard" ? 1 : 0);
    if (choice === "discard") assert.equal((fixture.warnings[0]![1] as { modal: boolean }).modal, true);
    if (choice === "resume") assert.deepEqual(fixture.diffs[0]!.slice(0, 3), ["vscode.diff",
      { path: "/project/src/helper.py" }, { path: "/project/.icoda/worktree/src/helper.py" }]);
    const cancelled = await recoveryView("discard", () => undefined);
    await cancelled.view.recover(recoverySelection);
    assert.deepEqual(cancelled.calls.map(call => call.method), ["recovery.list"]);
  }
});

test("native recovery rechecks trust, session, disposal and latest buffers after picker and modal", async () => {
  for (const stage of ["picker", "modal"]) for (const guard of ["trust", "session", "dispose", "unsaved"]) {
    const change = () => {
      if (guard === "trust") fixture.workspace.isTrusted = false;
      if (guard === "session") fixture.session.reset();
      if (guard === "dispose") { fixture.view.disposed = true; fixture.model.dispose(); }
      if (guard === "unsaved") fixture.workspace.textDocuments.push({ isDirty: true, uri: { toString: () => "file:///project/.icoda/worktree/helper.py" } });
    };
    const fixture = await recoveryView("discard", () => { if (stage === "modal") change(); return "Discard"; }, () => { if (stage === "picker") change(); });
    await fixture.view.recover(recoverySelection);
    const resolve = fixture.calls.find(call => call.method === "recovery.resolve");
    if (guard === "unsaved") assert.deepEqual((resolve!.params as { unsavedDocuments: string[] }).unsavedDocuments, ["file:///project/.icoda/worktree/helper.py"]);
    else assert.equal(resolve, undefined);
  }
});

test("project open and backend restart rediscover recovery once per session context", async () => {
  const fixture = await recoveryView("keep");
  fixture.view.sync(); fixture.view.sync();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(fixture.calls.length, 1);
  fixture.session.reset(); fixture.view.sync();
  fixture.session.identity.accept(fixture.session.identity.capture(), { ...context, sessionId: "restarted" }, "open");
  fixture.view.sync();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(fixture.calls.length, 2);
  assert.equal(fixture.model.recoveries?.sessionId, "restarted");
  assert.equal(fixture.view.getChildren().length, 1);
  fixture.view.disposed = true; fixture.view.sync(); assert.equal(fixture.calls.length, 2);
});

test("disposing during recovery startup cancels the eventual owned check job", async () => {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const fixture = setup(async method => {
    if (method === "recovery.resolve") await pending;
    return { ...context, workflow: { id: "recovery", state: "running", message: "Checking" } };
  });
  fixture.model.recoveries = retained();
  const work = fixture.model.recover(recoverySelection, "resume", [], false);
  fixture.model.dispose(); release();
  assert.equal(await work, false);
  assert.equal(fixture.calls.at(-1)!.method, "workflow.cancel");
  assert.deepEqual(fixture.calls.at(-1)!.params, { trusted: true, workflowId: "recovery" });
});
