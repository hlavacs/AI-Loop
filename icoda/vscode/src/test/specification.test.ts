import * as assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import { test } from "node:test";
import { ProjectSession } from "../projectSession";
import { BackendError, ProjectModel, SessionContext } from "../protocol";
import { SpecificationModel } from "../specificationModel";
import { SpecificationDocuments } from "../specificationDocuments";
import { Phase, ProviderInventory, Specification, providerChoice, providerSelection, registerSpecificationCommands,
  specificationCommands, specificationNodes } from "../specificationData";

const context: SessionContext = { sessionId: "one", modelRevision: 1, targetId: null };
const spec: Specification = { ...context, exists: true, schemaVersion: 2, document: { title: "Example" },
  codeProfile: { language: "Python", standard: "3.12", max_function_lines: 30 }, valid: true, findings: [] };
const phase: Phase = { ...context, phase: "architecture", allowedTransitions: ["implementation"],
  transitions: [{ phase: "implementation", reason: "" }] };
const providers: ProviderInventory = { ...context, selection: { provider: "fixture", model: "small" },
  emptyReason: null, message: "", providers: [{ id: "fixture", label: "Fixture", installed: true, enabled: true,
    available: true, binary: "fixture", binaryPath: "/fixture", loginHint: "fixture login", selectedModel: "small",
    authenticationConfigured: false, models: [{ id: "small", label: "Small", available: true }] }] };
const projectModel: ProjectModel = { files: [], entities: [], edges: [], stale: false, stale_reason: "" };
const saved = { ...spec, saved: true, root: "/project", sourceRootId: "one:workspace", model: projectModel,
  diagnostics: [], postSaveError: null };
const responses: Record<string, SessionContext> = { "spec.get": spec, "spec.validate": spec, "phase.get": phase, "providers.list": providers,
  "targets.list": { ...context, targets: [], diagnostics: [] } as SessionContext };

function setup(reply: (method: string, params: object, context?: SessionContext) => unknown = method => responses[method]) {
  const calls: { method: string; params: object; context?: SessionContext }[] = [], logs: string[] = [];
  const session = new ProjectSession(text => logs.push(text), () => {});
  session.data = { root: "/project", modelState: "fresh", staleReason: "", entityCount: 0, edgeCount: 0, targets: [] };
  session.identity.accept(session.identity.capture(), context, "open");
  const client = { request: async <T>(method: string, params: object = {}, context?: SessionContext): Promise<T> => {
    calls.push({ method, params, context }); return await reply(method, params, context) as T;
  } };
  const model = new SpecificationModel(session, client, () => {});
  return { model, session, calls, logs };
}

function flatten(nodes: ReturnType<typeof specificationNodes>): string {
  return JSON.stringify(nodes);
}

test("specification tree maps core phase, profile, findings and provider/model status", () => {
  const nodes = specificationNodes({ spec: { ...spec, valid: false, findings: [
    { id: "stable", severity: "error", message: "Title is required" }] }, phase, providers, errors: [] });
  const text = flatten(nodes);
  for (const value of ["Phase: architecture", "implementation", "Code Profile", "Python", "max function lines",
    "Title is required", "stable", "error", "Fixture", "Authentication not detected", "Selected"]) assert.ok(text.includes(value));
  assert.ok(flatten(specificationNodes({ spec, phase, providers: { ...providers, providers: [
    { ...providers.providers[0]!, authenticationConfigured: true }] }, errors: [] })).includes("not verified"));
});

test("empty and missing-provider states explain what to do while preserving other sections", () => {
  const text = flatten(specificationNodes({ spec: { ...spec, exists: false, codeProfile: {} },
    phase: { ...phase, phase: "specification", allowedTransitions: [], transitions: [{ phase: "architecture", reason: "Save a specification first" }] },
    providers: { ...providers, providers: [], emptyReason: "no_available_providers", message: "No enabled provider is installed." }, errors: [] }));
  for (const value of ["No saved specification", "No Code Profile", "Default is valid", "Save a specification first",
    "No enabled provider is installed", "Phase: specification"]) assert.ok(text.includes(value));
  assert.match(flatten(specificationNodes({ spec: { ...spec, codeProfile: null }, errors: [] })), /No Code Profile/);
  const unavailable = flatten(specificationNodes({ providers: { ...providers, providers: [
    { ...providers.providers[0]!, installed: false, available: false, models: [] }] }, errors: ["Cannot read specification"] }));
  assert.match(unavailable, /Not installed/); assert.match(unavailable, /Cannot read specification/);
});

test("specification manifest, native view, filesystem and four commands are registered and disposed", async () => {
  const registered = new Map<string, (...args: unknown[]) => unknown>(), calls: string[] = [];
  registerSpecificationCommands((name, action) => registered.set(name, action), action => calls.push(action));
  for (const command of registered.values()) { command({ phase: "implementation" }); command(null); command(); }
  assert.deepEqual(calls, ["open", "validate", "phase", "provider"]);
  const root = resolve(__dirname, "../..");
  const manifest = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
  assert.ok(manifest.contributes.views.icoda.some((view: { id: string }) => view.id === "icoda.specification"));
  assert.ok(manifest.activationEvents.includes("onView:icoda.specification"));
  for (const command of Object.values(specificationCommands)) {
    assert.ok(manifest.activationEvents.includes(`onCommand:${command}`));
    assert.ok(manifest.contributes.commands.some((item: { command: string; enablement: string }) =>
      item.command === command && item.enablement === "icoda.projectOpen && isWorkspaceTrusted"));
  }
  assert.equal(manifest.contributes.configuration.properties["icoda.providerSelection"].scope, "resource");
  const adapter = await readFile(resolve(root, "src/specificationView.ts"), "utf8");
  for (const pattern of [/createTreeView\("icoda.specification"/, /registerFileSystemProvider/, /registerSpecificationCommands/,
    /openTextDocument/, /isTrusted/, /ConfigurationTarget.WorkspaceFolder/]) assert.match(adapter, pattern);
  const extension = await readFile(resolve(root, "src/extension.ts"), "utf8");
  for (const method of ["sync", "dispose"]) assert.ok(extension.includes(`this.specification.${method}()`));
});

test("provider setting shape is bounded and only accepts provider/model identifiers", () => {
  assert.deepEqual(providerSelection(providers.selection), providers.selection);
  for (const input of [null, [], {}, { provider: "x" }, { provider: "x", model: "" },
    { provider: "x", model: "small", token: "forbidden" }, { provider: "x\0", model: "small" },
    { provider: "x", model: "a".repeat(257) }]) assert.equal(providerSelection(input), undefined);
});

test("late specification responses are dropped after session, revision or target changes", async () => {
  for (const change of ["session", "revision", "target"] as const) {
    let finish!: () => void, slow = true;
    const pending = new Promise<void>(resolve => { finish = resolve; });
    const { model, session } = setup(async (method, _params, identity) => {
      const delayed = slow;
      if (delayed) await pending;
      return { ...responses[method], ...identity, document: { title: delayed ? "old" : "new" } };
    });
    const loading = model.sync();
    if (change === "session") { session.reset(); session.identity.accept(session.identity.capture(), { ...context, sessionId: "two" }, "open"); }
    else session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2, targetId: change === "target" ? "two" : null },
      change === "target" ? { targetId: "two" } : "analyse");
    slow = false; await model.sync(); finish(); await loading;
    assert.equal(model.snapshot?.spec?.document.title, "new");
  }
});

test("overlapping refresh, mismatched responses and disposal cannot replace current specification", async () => {
  let finish!: () => void, slow = true;
  const pending = new Promise<void>(resolve => { finish = resolve; });
  const { model } = setup(async method => {
    if (slow) { await pending; return { ...responses[method], exists: false }; }
    return responses[method];
  });
  const first = model.sync(); slow = false; await model.sync(true); finish(); await first;
  assert.equal(model.snapshot?.spec?.exists, true);
  for (const mismatch of [{ sessionId: "two" }, { modelRevision: 3 }, { targetId: "two" }]) {
    const invalid = setup(method => ({ ...responses[method], ...mismatch })); await invalid.model.sync();
    assert.equal(invalid.model.snapshot?.spec, undefined); assert.equal(invalid.model.snapshot?.errors.length, 3);
  }
  const last = model.sync(true); model.dispose(); await last; assert.deepEqual(model.items(), []);
});

test("provider failure is isolated and closed specification tree does not start Python", async () => {
  const { model, session, calls } = setup(method => {
    if (method === "providers.list") throw new Error("Registry unavailable"); return responses[method];
  });
  await model.sync(); assert.equal(model.snapshot?.spec?.exists, true); assert.equal(model.snapshot?.phase?.phase, "architecture");
  assert.match(model.snapshot!.errors[0]!, /Registry unavailable/);
  session.reset(); await model.sync(); const count = calls.length; await model.sync();
  assert.equal(calls.length, count); assert.match(model.items()[0]!.label, /Open an ICODA project/);
});

test("native document saves validate first, publish a revision and preserve their current draft", async () => {
  const { model, calls, session } = setup((method, params, identity) => method === "spec.save"
    ? { ...saved, ...identity, modelRevision: identity!.modelRevision + 1, document: (params as Specification).document }
    : { ...responses[method], ...identity });
  const documents = new SpecificationDocuments(model, () => true);
  await documents.open("draft"); await documents.open("draft");
  assert.equal(calls.length, 1);
  await documents.save("draft", '{"title":"Changed"}');
  assert.deepEqual(calls.map(call => call.method), ["spec.get", "spec.validate", "spec.save", "targets.list", "spec.get", "phase.get", "providers.list"]);
  assert.deepEqual(calls[2]!.params, { document: { title: "Changed" }, trusted: true, postSave: true, unsavedDocuments: [] });
  assert.equal(session.identity.context?.modelRevision, 2);
  assert.equal(documents.read("draft"), '{"title":"Changed"}');
  await documents.save("draft", '{"title":"Again"}');
  assert.equal(session.identity.context?.modelRevision, 3); assert.equal(documents.currentKey(), "draft");
});

test("P08 saves refresh model, targets, phase and reread while retaining structured post-save failures", async () => {
  for (const failure of [null, "build_failed", "cancelled"]) {
    const failed = Boolean(failure);
    const errors: BackendError[] = [];
    let document = spec.document;
    const refreshed = { ...projectModel, stale: failed, stale_reason: failed ? "Missing cmake" : "" };
    const { model, session, calls } = setup((method, params, identity) => {
      if (method === "spec.save") {
        document = (params as Specification).document;
        const result = { ...saved, ...identity, modelRevision: identity!.modelRevision + 1, targetId: "generated",
          document, model: refreshed, postSaveError: failed ? { code: failure, message: "Refresh failed", details: {} } : null };
        if (failure === "cancelled") throw new BackendError("cancelled", "Refresh cancelled", result);
        return result;
      }
      return { ...responses[method], ...identity, document };
    });
    const documents = new SpecificationDocuments(model, () => true, () => ["file:///elsewhere/dirty.py"], error => errors.push(error));
    await documents.open("draft");
    await documents.save("draft", '{"title":"Saved"}');
    assert.equal(session.model, refreshed);
    assert.equal(session.data?.modelState, failed ? "stale" : "fresh");
    assert.equal(session.identity.context?.targetId, "generated");
    assert.equal(model.snapshot?.phase?.phase, "architecture");
    assert.equal(model.snapshot?.phase?.modelRevision, 2);
    assert.equal(model.snapshot?.spec?.document.title, "Saved");
    assert.equal(errors.length, Number(failed));
    if (failed) { assert.equal(errors[0]!.code, failure); assert.match(errors[0]!.message, /Specification saved/); }
    assert.deepEqual((calls.find(call => call.method === "spec.save")!.params as { unsavedDocuments: string[] }).unsavedDocuments,
      ["file:///elsewhere/dirty.py"]);
    documents.close("draft");
    await documents.open("reread");
    assert.equal(JSON.parse(documents.read("reread")).title, "Saved");
    assert.ok(calls.every(call => !/workflow|recovery|provider\./.test(call.method)));
  }
});

test("invalid JSON, core findings, untrusted workspaces and unknown documents cannot write", async () => {
  const { model, calls } = setup(method => method === "spec.validate" ? { ...spec, valid: false,
    findings: [{ id: "invalid", severity: "error", message: "Missing title" }] } : responses[method]);
  const documents = new SpecificationDocuments(model, () => true);
  await documents.open("draft"); const before = documents.read("draft");
  await assert.rejects(documents.save("draft", "{"), /valid JSON/);
  await assert.rejects(documents.save("draft", "{}"), /Missing title/);
  await assert.rejects(documents.save("unknown", "{}"), /Unknown specification/);
  assert.equal(documents.read("draft"), before);
  const untrusted = new SpecificationDocuments(model, () => false);
  await untrusted.open("other"); await assert.rejects(untrusted.save("other", "{}"), /Trust/);
  assert.ok(calls.every(call => call.method !== "spec.save"));
});

test("stale drafts and project switching during validation never send spec.save", async () => {
  const { model, session, calls } = setup(method => {
    if (method === "spec.validate") session.reset(); return responses[method];
  });
  const documents = new SpecificationDocuments(model, () => true);
  await documents.open("draft");
  await assert.rejects(documents.save("draft", "{}"), error => error instanceof BackendError && error.code === "stale_revision");
  await assert.rejects(documents.save("draft", "{}"), /project or revision changed/);
  assert.equal(documents.currentKey(), undefined);
  assert.ok(calls.every(call => call.method !== "spec.save"));
  documents.dispose(); assert.throws(() => documents.read("draft"), /Unknown specification/);
});

test("P09 provider choice parsing rejects credentials controls and malformed custom selections", () => {
  const choice = { provider: "fixture", model: "custom-id", binary: "/path with spaces/provider" };
  assert.deepEqual(providerChoice(choice), choice);
  for (const value of [null, {}, { ...choice, credentials: "forbidden" }, { ...choice, trusted: true },
    { ...choice, binary: "" }, { ...choice, binary: " provider" }, { ...choice, binary: "provider\n" },
    { ...choice, binary: "x".repeat(4097) }, { ...choice, model: "   " }, { ...choice, model: "x".repeat(257) }]) {
    assert.equal(providerChoice(value), undefined);
  }
});

test("P09 provider selection routes through the service and renders effective path custom model and CLI login", async () => {
  const choice = { provider: "fixture", model: "custom-id", binary: "/path with spaces/provider" };
  const inventory = { ...providers, selection: { provider: choice.provider, model: choice.model }, providers: [
    { ...providers.providers[0]!, binary: choice.binary, binaryPath: choice.binary, selectedModel: choice.model }] };
  const { model, calls } = setup(method => method === "providers.select" ? inventory : responses[method]);
  await model.sync();
  const commands = new Map<string, (...args: unknown[]) => unknown>();
  registerSpecificationCommands((name, action) => commands.set(name, action), action =>
    action === "provider" ? model.selectProvider(choice) : undefined);
  const before = calls.length;
  commands.get("icoda.selectProviderModel")!(choice);
  assert.equal(calls.length, before, "command arguments cannot bypass native choices");
  await commands.get("icoda.selectProviderModel")!();
  assert.deepEqual(calls.at(-1), { method: "providers.select", params: { ...choice, trusted: true }, context });
  for (const text of [choice.binary, choice.model, "fixture login", "Authentication not detected"]) {
    assert.ok(flatten(model.items()).includes(text));
  }
  assert.ok(!calls.some(item => /workflow.start|conversation.send|cli.command/.test(item.method)));
});

test("P09 provider selection drops stale replies and refuses untrusted disposed or invalid writes", async () => {
  const choice = { provider: "fixture", model: "custom-id", binary: "/fixture" };
  for (const change of ["session", "revision", "target", "dispose", "trust"]) {
    for (const fails of [false, true]) {
      const { session } = setup();
      let finish!: () => void, trusted = true, requests = 0;
      const pending = new Promise<void>(resolve => { finish = resolve; });
      const model = new SpecificationModel(session, { request: async <T>() => {
        requests++; await pending; if (fails) throw new BackendError("provider_failed", "Old provider"); return providers as T;
      } }, () => {}, () => trusted);
      const saving = model.selectProvider(choice);
      if (change === "trust") trusted = false;
      else if (change === "dispose") model.dispose();
      else if (change === "session") session.reset();
      else session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2,
        targetId: change === "target" ? "new" : null }, change === "target" ? { targetId: "new" } : "analyse");
      finish(); assert.equal(await saving, undefined); assert.equal(model.snapshot, undefined);
      if (["trust", "dispose", "session"].includes(change)) {
        await model.selectProvider(choice); assert.equal(requests, 1);
      }
    }
  }
  const { model, calls } = setup();
  await assert.rejects(model.selectProvider({ ...choice, binary: "\0" }), /Invalid provider/);
  assert.equal(calls.length, 0);
  const missing = setup(() => { throw new BackendError("provider_failed", "Fixture executable is missing"); });
  await assert.rejects(missing.model.selectProvider(choice), /provider_failed: Fixture executable is missing/);
  assert.deepEqual(missing.calls.map(item => item.method), ["providers.select"]);
});

test("P09 native provider picker cancels and rechecks project trust before persistence", async () => {
  for (const outcome of ["accept", "cancel-provider", "cancel-binary", "cancel-model", "cancel-custom", "trust", "session", "dispose"]) {
    const persisted = { ...providers, selection: { provider: "fixture", model: "custom" } };
    const inventory = { ...providers, providers: [{ ...providers.providers[0]!, models: [
      { id: "default", label: "Default", available: true }, ...providers.providers[0]!.models] }] };
    const { model, session, calls } = setup(method => method === "providers.select" ? persisted
      : method === "providers.list" ? inventory : responses[method]);
    const errors: string[] = [], writes: unknown[] = [];
    const workspace = { isTrusted: true, getConfiguration: () => ({ get: () => ({ provider: "fixture", model: "stale-setting" }),
      update: (...args: unknown[]) => writes.push(args) }) };
    const file = resolve(__dirname, "../specificationView.js"), requireFromView = createRequire(file);
    const loaded = { exports: {} as { SpecificationView: { prototype: object } } };
    runInNewContext(await readFile(file, "utf8"), { exports: loaded.exports, require: (id: string) => id === "vscode" ? {
      workspace, Uri: { file: (value: string) => value }, ConfigurationTarget: { WorkspaceFolder: "folder" },
      window: {
        showErrorMessage: (text: string) => errors.push(text),
        showQuickPick: (items: { model?: string }[], options: { placeHolder: string }) => {
          if (options.placeHolder.startsWith("Select provider")) return outcome === "cancel-provider" ? undefined : items[0];
          assert.equal(items[0]?.model, "small", "remembered registered model is offered first");
          return outcome === "cancel-model" ? undefined : items.find(item => item.model === "");
        },
        showInputBox: (options: { prompt: string; validateInput: (text: string) => string | undefined }) => {
          assert.ok(options.validateInput("\0"));
          if (options.prompt.startsWith("Provider executable")) return outcome === "cancel-binary" ? undefined : "/fixture";
          if (outcome === "trust") workspace.isTrusted = false;
          if (outcome === "session") session.reset();
          if (outcome === "dispose") model.dispose();
          return outcome === "cancel-custom" ? undefined : "custom";
        },
      },
    } : id === "./specificationFileSystem" ? {} : requireFromView(id) });
    const view = Object.assign(Object.create(loaded.exports.SpecificationView.prototype), { model, session });
    await model.sync();
    assert.ok(!flatten(view.getChildren()).includes("stale-setting"), "tree uses the shared project selection");
    const commands = new Map<string, (...args: unknown[]) => unknown>();
    registerSpecificationCommands((name, action) => commands.set(name, action), action => view.execute(action));
    await commands.get("icoda.selectProviderModel")!();
    assert.equal(calls.filter(item => item.method === "providers.select").length, outcome === "accept" ? 1 : 0, outcome);
    assert.equal(writes.length, outcome === "accept" ? 1 : 0, outcome);
    if (outcome === "accept") {
      assert.deepEqual(JSON.parse(JSON.stringify(writes[0])), ["providerSelection", persisted.selection, "folder"]);
      assert.deepEqual(JSON.parse(JSON.stringify(calls.find(item => item.method === "providers.select")!.params)),
        { provider: "fixture", model: "custom", binary: "/fixture", trusted: true });
    }
    assert.deepEqual(errors, [], outcome);
  }
});
