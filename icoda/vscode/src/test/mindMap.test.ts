import * as assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { parseMindMapMessage, registerMindMapCommand } from "../mindMapMessages";
import { mindMapHtml } from "../mindMapHtml";
import { MindMapModel, MindMapResponse, MindMapStep, mindMapStepText } from "../mindMapModel";
import { ProjectSession } from "../projectSession";
import { BackendError, SessionContext } from "../protocol";

const version = 3;

test("Mind Map validates exact message shapes, node IDs, expansion booleans and cameras", () => {
  const valid = [{ type: "ready" }, { type: "setExpanded", nodeId: "cluster:src", expanded: true, version },
    { type: "setExpanded", nodeId: "cluster:src", expanded: false, version },
    { type: "select", nodeId: "file:src/main.py", version },
    { type: "viewport", version, viewport: { x: 10, y: -20, scale: 2 } },
    { type: "fit", version, width: 900, height: 600 }];
  for (const message of valid) {
    assert.deepEqual(parseMindMapMessage(message), message);
    assert.equal(parseMindMapMessage({ ...message, extra: 1 }), undefined);
  }
  for (const nodeId of [null, 3, {}, "", " ", "a\0", "x".repeat(4097), "\ud800"]) {
    assert.equal(parseMindMapMessage({ type: "select", nodeId, version }), undefined);
    assert.equal(parseMindMapMessage({ type: "setExpanded", nodeId, version, expanded: true }), undefined);
  }
  for (const expanded of [undefined, null, "false", 0, 1, {}]) {
    assert.equal(parseMindMapMessage({ type: "setExpanded", nodeId: "cluster:src", version, expanded }), undefined);
  }
  for (const message of [null, [], {}, { type: "back", version }, { type: "traceLoad", version },
    { type: "select", nodeId: "a", version: -1 }, { type: "select", nodeId: "a", version: 0.1 },
    { type: "select", nodeId: "a" }, { type: "fit", version, width: 0, height: 10 },
    { type: "viewport", version, viewport: { x: 0, y: 0, scale: Infinity } }]) {
    assert.equal(parseMindMapMessage(message), undefined);
  }
});

test("Mind Map command is registered, contributed, activated and trust-gated", async () => {
  const commands = new Map<string, () => unknown>(), calls: string[] = [];
  registerMindMapCommand((id, action) => commands.set(id, action), () => calls.push("open"));
  assert.deepEqual([...commands.keys()], ["icoda.openMindMap"]);
  commands.get("icoda.openMindMap")!();
  assert.deepEqual(calls, ["open"]);
  const manifest = JSON.parse(await readFile(resolve(__dirname, "../../package.json"), "utf8"));
  assert.ok(manifest.activationEvents.includes("onCommand:icoda.openMindMap"));
  const command = manifest.contributes.commands.find((c: { command: string }) => c.command === "icoda.openMindMap");
  assert.equal(command.enablement, "icoda.projectOpen && isWorkspaceTrusted");
  assert.equal(command.title, "Open Mind Map");
  assert.ok(manifest.contributes.menus.commandPalette.some((c: { command: string }) => c.command === command.command));
  const extension = await readFile(resolve(__dirname, "../../src/extension.ts"), "utf8");
  assert.match(extension, /registerMindMapCommand\(/);
  assert.match(extension, /this\.mindMap\?\.sync\(\)/);
  assert.match(extension, /this\.mindMap\?\.dispose\(\)/);
});

test("Mind Map uses nonce CSP, one control row, DOM text, requirement/step details and native source", async () => {
  const html = mindMapHtml("nonce", "local:", "local:script", "local:style");
  assert.match(html, /default-src 'none'; base-uri 'none'; form-action 'none'/);
  assert.match(html, /script-src 'nonce-nonce'/);
  assert.match(html, /script type="module" nonce="nonce"/);
  assert.doesNotMatch(html, /unsafe-inline|unsafe-eval|onclick=|Next Call/);
  assert.equal((html.match(/role="toolbar"/g) ?? []).length, 1);
  const root = resolve(__dirname, "../..");
  const [script, css, panel] = await Promise.all([readFile(resolve(root, "media/mindMap.js"), "utf8"),
    readFile(resolve(root, "media/callView.css"), "utf8"), readFile(resolve(root, "src/mindMapPanel.ts"), "utf8")]);
  assert.match(script, /textContent/);
  assert.doesNotMatch(script, /innerHTML|eval\(/);
  assert.match(script, /node.requirements.map\(requirementLabel\)/);
  assert.match(script, /node.step.number.*node.step.title/);
  assert.match(css, /flex-wrap: nowrap;.*overflow-x: auto/);
  assert.match(panel, /parseMindMapMessage\(value\)/);
  assert.match(panel, /revealSource\(this.context, ref, true/);
});

const context = { sessionId: "session", modelRevision: 1, targetId: null };
const sourceRootId = "session:workspace";
const overview: MindMapResponse = {
  ...context, sourceRootId, view: "mindmap", totalNodes: 2, nodes: [{
    id: "cluster:src", label: "Source", qualifiedName: "Source", kind: "cluster", parent: null,
    children: ["file:main.py"], depth: 0, x: 160, y: 48, width: 260, height: 36,
    expandable: true, expanded: false, status: "implemented", requirementIds: [], requirements: [], useCaseIds: [],
    step: null, file: null, usr: null, line: 1, sourceRootId,
  }], edges: [], bounds: { x: 0, y: 0 }, width: 320, height: 96, stale: false, staleReason: "",
  empty: false, emptyReason: "", hasSteps: false, requirements: [], messages: ["No steps yet."],
};
const expanded: MindMapResponse = { ...overview, height: 146, width: 634,
  nodes: [{ ...overview.nodes[0]!, expanded: true }, { ...overview.nodes[0]!, id: "file:main.py", label: "main.py",
    kind: "file", parent: "cluster:src", children: [], depth: 1, x: 474, y: 98, file: "main.py", expandable: false }],
  edges: [{ source: "cluster:src", target: "file:main.py" }],
};

function setup(reply: (method: string, params: Record<string, unknown>, identity?: SessionContext) => unknown) {
  const logs: string[] = [];
  const session = new ProjectSession(message => logs.push(message), () => {});
  session.identity.accept(session.identity.capture(), context, "open");
  session.sourceRootId = sourceRootId;
  const client = { request: async <T>(method: string, params = {}, identity?: SessionContext): Promise<T> =>
    (method.startsWith("view.state.") ? { ...identity, state: { viewport: null } }
      : await reply(method, params, identity)) as T };
  return { session, logs, model: new MindMapModel(session, client, message => logs.push(message), () => {}) };
}

test("expansion uses the backend, retains camera and restricts actions to visible nodes", async () => {
  const calls: string[] = [];
  const { model } = setup((method, params) => { calls.push(method); return params.expanded ? expanded : overview; });
  await model.sync();
  assert.match(model.render().message, /No steps yet/);
  const camera = { x: -100, y: 32, scale: 1.7 };
  await model.control({ type: "viewport", viewport: camera, version: model.version });
  await model.control({ type: "setExpanded", nodeId: "cluster:src", expanded: true, version: model.version });
  assert.deepEqual(model.viewport, camera);
  assert.deepEqual(model.select("file:main.py"), { file: "main.py", line: 1, sourceRootId });
  assert.equal(model.select("missing"), undefined);
  assert.equal(model.accepts({ type: "setExpanded", nodeId: "file:main.py", expanded: true, version: model.version }), false);
  await model.control({ type: "setExpanded", nodeId: "cluster:src", expanded: false, version: model.version });
  assert.equal(model.selected, null);
  assert.equal(model.accepts({ type: "select", nodeId: "file:main.py", version: model.version }), false);
  assert.deepEqual(calls, ["view.get", "mindmap.setExpanded", "mindmap.setExpanded"]);
  await model.control({ type: "fit", width: 800, height: 600, version: model.version });
  assert.ok(model.viewport!.scale > 0);
});

test("Mind Map rejects late replies, obsolete actions and work after disposal", async () => {
  let complete!: (value: MindMapResponse) => void;
  const pending = new Promise<MindMapResponse>(resolve => { complete = resolve; });
  const { session, model } = setup((_method, _params, identity) => identity?.modelRevision === 1
    ? pending : { ...overview, ...identity });
  const first = model.sync();
  const oldVersion = model.version;
  session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2 }, "analyse");
  await model.sync();
  complete(overview);
  await first;
  assert.equal(model.graph?.modelRevision, 2);
  assert.equal(model.accepts({ type: "setExpanded", nodeId: "cluster:src", expanded: true, version: oldVersion }), false);
  model.dispose();
  assert.equal(model.accepts({ type: "ready" }), false);
  assert.equal(model.select("cluster:src"), undefined);
});

test("mismatched responses and a project switch cannot publish a Mind Map", async () => {
  for (const mismatch of [{ sessionId: "other" }, { modelRevision: 10 }, { targetId: "other" }]) {
    const { model, logs } = setup(() => ({ ...overview, ...mismatch }));
    await model.sync();
    assert.equal(model.graph, undefined);
    assert.ok(logs.some(text => text.startsWith("Dropped stale response")));
  }
  let complete!: (value: MindMapResponse) => void;
  const pending = new Promise<MindMapResponse>(resolve => { complete = resolve; });
  const { model, session } = setup(() => pending);
  const loading = model.sync();
  session.reset();
  complete(overview);
  await loading;
  assert.equal(model.graph, undefined);
});

test("unavailable and empty models explain the missing analysis or metadata", async () => {
  const { model } = setup(() => { throw new BackendError("model_unavailable", "missing"); });
  await model.sync();
  assert.match(model.render().message, /Analyse Project/);
  const empty = setup(() => ({ ...overview, nodes: [], totalNodes: 0, empty: true, emptyReason: "No project nodes.",
    messages: ["No specification requirements yet.", "No steps yet."] }));
  await empty.model.sync();
  assert.match(empty.model.render().message, /No project nodes.*No specification.*No steps/);
});

test("failed expansion leaves the previous hierarchy usable for retry", async () => {
  let fail = true;
  const { model } = setup((method) => {
    if (method === "view.get") return overview;
    if (fail) throw new BackendError("internal_error", "Cannot write state");
    return expanded;
  });
  await model.sync();
  await model.control({ type: "setExpanded", nodeId: "cluster:src", expanded: true, version: model.version });
  assert.equal(model.graph, overview);
  assert.match(model.render().message, /Cannot write state/);
  fail = false;
  await model.control({ type: "setExpanded", nodeId: "cluster:src", expanded: true, version: model.version });
  assert.equal(model.graph, expanded);
  assert.equal(model.error, "");
});

test("P03 Mind Map opens only current backend history and drops stale replies", async () => {
  const nodeId = overview.nodes[0]!.id;
  const record: MindMapStep = { number: 2, title: "Introduce source", decision: "manual", round: "code",
    phase: "architecture", request: "Add source", rationale: "Keep the API", reason: "", commit: "abc",
    files: ["main.py"], entities_added: ["python:main:B"], entities_changed: [], entities_renamed: [],
    build_ok: true, test_ok: false, build_output: "Build passed", test_output: "Test failed" };
  const graph = { ...overview, nodes: [{ ...overview.nodes[0]!, step: { number: record.number, title: record.title } }] };
  const response = { ...context, nodeId, record };
  for (const change of ["none", "session", "target", "revision", "generation", "dispose", "version", "mismatch", "missing"]) {
    let finish!: (value: typeof response) => void, fail!: (error: Error) => void;
    const pending = new Promise<typeof response>((resolve, reject) => { finish = resolve; fail = reject; });
    const calls: string[] = [];
    const { model, session } = setup((method, params, identity) => {
      if (method === "view.get") return graph;
      calls.push(method);
      assert.equal(method, "mindmap.step");
      assert.deepEqual(params, { nodeId });
      assert.deepEqual(identity, context);
      return pending;
    });
    await model.sync();
    model.select(nodeId);
    const camera = { x: 42, y: -15, scale: 0.8 };
    await model.control({ type: "viewport", version: model.version, viewport: camera });
    const message = { type: "openStep" as const, nodeId, version: model.version };
    assert.deepEqual(parseMindMapMessage(message), message);
    for (const invalid of [{ ...message, step: 2 }, { ...message, nodeId: "" }, { ...message, version: -1 }]) {
      assert.equal(parseMindMapMessage(invalid), undefined);
    }
    assert.equal(model.accepts({ ...message, nodeId: "hidden" }), false);
    const opening = model.openStep(message);
    if (change === "session") session.reset();
    if (change === "target") session.identity.accept(session.identity.capture(), { ...context, targetId: "other", modelRevision: 2 }, { targetId: "other" });
    if (change === "revision") session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2 }, "analyse");
    if (change === "generation") session.identity.invalidate();
    if (change === "dispose") model.dispose();
    if (change === "version") model.version++;
    if (change === "missing") fail(new BackendError("step_unavailable", "No introducing step is recorded."));
    else finish(change === "mismatch" ? { ...response, sessionId: "other" } : response);
    assert.deepEqual(await opening, change === "none" ? record : undefined, change);
    assert.deepEqual(calls, ["mindmap.step"]);
    assert.equal(model.selected, nodeId);
    assert.deepEqual(model.viewport, camera);
    if (change === "missing") assert.match(model.render().message, /No introducing step/);
  }
  const withoutHistory = setup(() => overview).model;
  await withoutHistory.sync();
  assert.equal(withoutHistory.accepts({ type: "openStep", nodeId, version: withoutHistory.version }), false);
  assert.match(mindMapStepText(record), /Step 2: manual — Introduce source/);
  assert.match(mindMapStepText(record), /Build: passed\nBuild passed[\s\S]*Tests: failed\nTest failed/);
  const script = await readFile(resolve(__dirname, "../../media/mindMap.js"), "utf8");
  assert.match(mindMapHtml("nonce", "local:", "local:js", "local:css"), /id="openStep" disabled/);
  assert.match(script, /send\("openStep", \{ nodeId: state.selected \}\)/);
  assert.match(script, /disabled = next.loading \|\| !selected\?\.step/);
});
