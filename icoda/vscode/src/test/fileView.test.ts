import * as assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import { parseFileViewMessage, registerFileCommands } from "../fileViewMessages";
import { fileViewHtml } from "../fileViewHtml";
import { FileViewModel, FileViewResponse } from "../fileViewModel";
import { ProjectSession } from "../projectSession";
import { BackendError, SessionContext } from "../protocol";
import { TestElement } from "./webviewHarness";

const version = 3;

test("File View messages validate exact shapes, bounded identities and shared camera fields", () => {
  const valid = [{ type: "ready" }, { type: "enter", id: "cluster:src", version },
    { type: "select", id: "src/main.py", version }, { type: "back", version }, { type: "reveal", version },
    { type: "viewport", version, viewport: { x: 10, y: -20, scale: 2 } },
    { type: "fit", version, width: 900, height: 600 }];
  for (const message of valid) {
    assert.deepEqual(parseFileViewMessage(message), message);
    assert.equal(parseFileViewMessage({ ...message, extra: 1 }), undefined);
  }
  for (const message of [null, [], {}, { type: "traceLoad", version }, { type: "back", version: -1 },
    { type: "enter", version, id: "" }, { type: "enter", version, id: "a\0" },
    { type: "enter", version, id: "x".repeat(4097) }, { type: "select", version, id: 3 },
    { type: "select", id: "a" }, { type: "reveal", version, file: "../injected" },
    { type: "viewport", version, viewport: { x: 0, y: 0, scale: Infinity } },
    { type: "fit", version, width: 0, height: 10 }]) assert.equal(parseFileViewMessage(message), undefined);
});

test("File View commands are registered, contributed, activated and trust-gated", async () => {
  const calls: string[] = [], commands = new Map<string, () => unknown>();
  registerFileCommands((id, callback) => commands.set(id, callback), () => calls.push("open"),
    () => calls.push("reveal"), () => calls.push("assign"));
  const manifest = JSON.parse(await readFile(resolve(__dirname, "../../package.json"), "utf8"));
  for (const [id, action] of commands) {
    action();
    assert.ok(manifest.activationEvents.includes(`onCommand:${id}`));
    const command = manifest.contributes.commands.find((c: { command: string }) => c.command === id);
    assert.equal(command.enablement, "icoda.projectOpen && isWorkspaceTrusted");
    assert.ok(manifest.contributes.menus.commandPalette.some((c: { command: string }) => c.command === id));
  }
  assert.deepEqual(calls, ["open", "reveal", "assign"]);
  assert.equal(manifest.contributes.commands.find((c: { command: string }) => c.command === "icoda.openFileView").title, "Open File View");
  const extension = await readFile(resolve(__dirname, "../../src/extension.ts"), "utf8");
  assert.match(extension, /registerFileCommands\(/);
  assert.match(extension, /this\.fileView\?\.sync\(\)/);
  assert.match(extension, /this\.fileView\?\.dispose\(\)/);
});

test("File View uses a nonce CSP, one scrolling control row, DOM text and native source navigation", async () => {
  const html = fileViewHtml("nonce", "local:", "local:script", "local:style");
  assert.match(html, /default-src 'none'; base-uri 'none'; form-action 'none'/);
  assert.match(html, /script-src 'nonce-nonce'/);
  assert.match(html, /script type="module" nonce="nonce"/);
  assert.doesNotMatch(html, /unsafe-inline|unsafe-eval|onclick=|Next Call/);
  assert.equal((html.match(/role="toolbar"/g) ?? []).length, 1);
  const root = resolve(__dirname, "../..");
  const [script, css, panel] = await Promise.all([readFile(resolve(root, "media/fileView.js"), "utf8"),
    readFile(resolve(root, "media/callView.css"), "utf8"), readFile(resolve(root, "src/fileViewPanel.ts"), "utf8")]);
  assert.match(script, /textContent/);
  assert.doesNotMatch(script, /innerHTML|eval\(/);
  assert.match(css, /flex-wrap: nowrap;.*overflow-x: auto/);
  assert.match(panel, /parseFileViewMessage\(value\)/);
  assert.match(panel, /revealSource\(this.context, ref, true/);
});

const context = { sessionId: "session", modelRevision: 1, targetId: null };
const sourceRootId = "session:workspace";
const overview: FileViewResponse = {
  ...context, sourceRootId, view: "file", clusterId: null, clusterPath: [], overview: true,
  nodes: [{ id: "cluster:src", name: "Source", label: "Source\n2 files", kind: "cluster", fileCount: 2,
    x: 150, y: 100, width: 200, height: 54, expandable: true }], edges: [],
  bounds: { x: 50, y: 73 }, width: 200, height: 54, stale: false, staleReason: "",
};
const detail: FileViewResponse = { ...overview, clusterId: "cluster:src", overview: false,
  clusterPath: [{ id: "cluster:src", label: "Source" }],
  nodes: [{ id: "src/main.py", entityId: "src/main.py", label: "main.py", kind: "file",
    x: 130, y: 100, width: 160, height: 36, file: "src/main.py", sourceRootId, line: 1, expandable: false }],
};

function setup(reply: (method: string, params: Record<string, unknown>, identity?: SessionContext) => unknown) {
  const logs: string[] = [];
  const session = new ProjectSession(message => logs.push(message), () => {});
  session.identity.accept(session.identity.capture(), context, "open");
  session.sourceRootId = sourceRootId;
  session.data = { root: "/chosen", modelState: "fresh", staleReason: "", entityCount: 2, edgeCount: 0, targets: [] };
  const client = { request: async <T>(method: string, params = {}, identity?: SessionContext): Promise<T> =>
    (method.startsWith("view.state.") ? { ...identity, state: { clusterId: null, cameras: [] } }
      : await reply(method, params, identity)) as T };
  return { session, logs, model: new FileViewModel(session, client, message => logs.push(message), () => {}) };
}

test("expanding and Back preserve each camera; only current file nodes can open source", async () => {
  const { model } = setup((_method, params) => params.clusterId ? detail : overview);
  await model.sync();
  assert.equal(model.accepts({ type: "select", id: "cluster:src", version: model.version }), false);
  const camera = { x: -100, y: 32, scale: 1.7 };
  await model.control({ type: "viewport", viewport: camera, version: model.version });
  await model.control({ type: "enter", id: "cluster:src", version: model.version });
  assert.equal(model.viewport, undefined);
  await model.control({ type: "fit", width: 800, height: 600, version: model.version });
  const detailCamera = model.viewport;
  assert.ok(detailCamera);
  assert.deepEqual(model.select("src/main.py"), { file: "src/main.py", sourceRootId, line: 1 });
  assert.equal(model.select("/outside"), undefined);
  assert.equal(model.render().selected, "src/main.py");
  await model.control({ type: "back", version: model.version });
  assert.deepEqual(model.viewport, camera);
  await model.control({ type: "enter", id: "cluster:src", version: model.version });
  assert.deepEqual(model.viewport, detailCamera);
});

test("reveal delegates cluster ancestry to Python and highlights the returned file", async () => {
  const { model } = setup((method, params) => method === "view.revealFile"
    ? { ...context, sourceRootId, clusterPath: ["cluster:src"], clusterId: "cluster:src", entityId: "src/main.py" }
    : params.clusterId ? detail : overview);
  await model.sync();
  await model.reveal({ file: "src/main.py", sourceRootId });
  assert.equal(model.clusterId, "cluster:src");
  assert.equal(model.selected, "src/main.py");
  assert.deepEqual(model.graph?.nodes, detail.nodes);
});

test("File View rejects late replies, invalid nodes, stale actions and post-disposal work", async () => {
  let complete!: (value: FileViewResponse) => void;
  const pending = new Promise<FileViewResponse>(resolve => { complete = resolve; });
  const { session, model } = setup((_method, _params, identity) => identity?.modelRevision === 1
    ? pending : { ...overview, ...identity });
  const first = model.sync();
  const oldVersion = model.version;
  session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2 }, "analyse");
  await model.sync();
  complete(overview);
  await first;
  assert.equal(model.graph?.modelRevision, 2);
  assert.equal(model.accepts({ type: "enter", id: "cluster:src", version: oldVersion }), false);
  assert.equal(model.accepts({ type: "enter", id: "invented", version: model.version }), false);
  model.dispose();
  assert.equal(model.accepts({ type: "ready" }), false);
});

test("wrong response identities and a project switch never populate a File View", async () => {
  for (const mismatch of [{ sessionId: "other" }, { modelRevision: 10 }, { targetId: "other" }]) {
    const { model, logs } = setup(() => ({ ...overview, ...mismatch }));
    await model.sync();
    assert.equal(model.graph, undefined);
    assert.ok(logs.some(text => text.startsWith("Dropped stale response")));
  }
  let complete!: (value: FileViewResponse) => void;
  const pending = new Promise<FileViewResponse>(resolve => { complete = resolve; });
  const { model, session } = setup(() => pending);
  const loading = model.sync();
  session.reset();
  complete(overview);
  await loading;
  assert.equal(model.graph, undefined);
});

test("cluster edit messages reject malformed pin, unpin and rename requests", () => {
  for (const type of ["pin", "unpin", "rename"]) {
    const message = { type, id: "cluster:src", version };
    assert.deepEqual(parseFileViewMessage(message), message);
    for (const invalid of [{ ...message, id: "" }, { ...message, id: "src" }, { ...message, id: "cluster: " },
      { ...message, id: "cluster:" }, { ...message, id: 1 }, { ...message, id: "cluster:a\0" },
      { ...message, id: "cluster:" + "x".repeat(4096) }, { ...message, version: -1 },
      { ...message, version: 1.5 }, { ...message, version: undefined }, { ...message, name: "Injected" },
      { ...message, pinned: true }, { ...message, sessionId: "injected" }]) {
      assert.equal(parseFileViewMessage(invalid), undefined);
    }
  }
});

test("cluster edits route through the service and preserve root, selection and per-level viewport", async () => {
  const calls: { method: string; params: Record<string, unknown>; identity?: SessionContext }[] = [];
  const { model } = setup((method, params, identity) => {
    calls.push({ method, params, identity });
    return (method === "view.get" ? params.clusterId : params.viewClusterId) ? detail : overview;
  });
  await model.sync();
  const overviewCamera = { x: -100, y: 20, scale: 0.7 }, detailCamera = { x: 50, y: -30, scale: 1.5 };
  await model.control({ type: "viewport", version: model.version, viewport: overviewCamera });
  await model.control({ type: "pin", id: "cluster:src", version: model.version });
  assert.deepEqual(model.viewport, overviewCamera);
  assert.equal(model.clusterId, null);
  await model.control({ type: "enter", id: "cluster:src", version: model.version });
  await model.control({ type: "viewport", version: model.version, viewport: detailCamera });
  model.select("src/main.py");
  await model.editCluster({ type: "rename", id: "cluster:src", version: model.version }, "Grüße <Core>");
  await model.control({ type: "unpin", id: "cluster:src", version: model.version });
  assert.equal(model.clusterId, "cluster:src");
  assert.deepEqual(model.graph?.clusterPath, detail.clusterPath);
  assert.equal(model.selected, "src/main.py");
  assert.deepEqual(model.viewport, detailCamera);
  assert.deepEqual(calls.filter(call => call.method.startsWith("cluster.")), [
    { method: "cluster.pin", params: { clusterId: "cluster:src", viewClusterId: null, hierarchy: true }, identity: context },
    { method: "cluster.rename", params: { clusterId: "cluster:src", viewClusterId: "cluster:src", hierarchy: true, name: "Grüße <Core>" }, identity: context },
    { method: "cluster.unpin", params: { clusterId: "cluster:src", viewClusterId: "cluster:src", hierarchy: true }, identity: context },
  ]);
  await model.control({ type: "back", version: model.version });
  assert.deepEqual(model.viewport, overviewCamera);
  await model.control({ type: "enter", id: "cluster:src", version: model.version });
  assert.deepEqual(model.viewport, detailCamera);
});

test("cluster edits reject obsolete identities and keep the graph usable on service errors", async () => {
  let complete!: (value: FileViewResponse) => void;
  let fail = false;
  const calls: string[] = [];
  const { model, session } = setup((method, _params, identity) => {
    calls.push(method);
    if (method === "view.get") return { ...overview, ...identity };
    if (fail) throw new BackendError("invalid_params", "Invalid name", {});
    return new Promise<FileViewResponse>(resolve => { complete = resolve; });
  });
  await model.sync();
  for (const id of ["cluster:missing", "src/main.py", "external:overview"]) {
    await model.control({ type: "pin", id, version: model.version });
  }
  await model.editCluster({ type: "rename", id: "cluster:src", version: model.version }, "  ");
  await model.control({ type: "unpin", id: "cluster:src", version: model.version - 1 });
  assert.deepEqual(calls, ["view.get"]);
  const pending = model.control({ type: "pin", id: "cluster:src", version: model.version });
  session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2 }, "analyse");
  await model.sync();
  complete({ ...overview, nodes: [] });
  await pending;
  assert.equal(model.graph?.modelRevision, 2);
  assert.equal(model.graph?.nodes.length, 1);
  fail = true;
  await model.editCluster({ type: "rename", id: "cluster:src", version: model.version }, "New");
  assert.match(model.error, /Invalid name/);
  assert.ok(model.accepts({ type: "enter", id: "cluster:src", version: model.version }));
  model.dispose();
  const count = calls.length;
  await model.control({ type: "pin", id: "cluster:src", version: model.version });
  assert.equal(calls.length, count);
});

test("cluster labels and context actions render as text without changing the webview camera", async () => {
  const elements = new Map<string, TestElement>(), messages: Record<string, unknown>[] = [];
  const document = { activeElement: undefined as TestElement | undefined,
    getElementById: (id: string) => elements.get(id), addEventListener() {},
    createElementNS: (_namespace: string, name: string) => new TestElement(name, document) };
  for (const id of ["graph", "scene", "back", "breadcrumb", "reveal", "zoomOut", "fit", "zoomIn", "status",
    "clusterMenu", "clusterPin", "clusterRename", "fileAssign"]) elements.set(id, new TestElement(id, document));
  const get = (id: string) => elements.get(id)!;
  Object.assign(get("clusterMenu"), { style: {}, offsetWidth: 180, offsetHeight: 60 });
  const api = runInNewContext(await readFile(resolve(__dirname, "../../media/fileView.js"), "utf8") + "\n({ render });", {
    document, window: { addEventListener() {}, innerWidth: 1000, innerHeight: 700 },
    acquireVsCodeApi: () => ({ postMessage: (value: Record<string, unknown>) => messages.push(value) }),
  }) as { render(value: unknown): void };
  const viewport = { x: -50, y: 12, scale: 1.4 };
  const graph = { ...overview, nodes: [{ ...overview.nodes[0], name: "Grüße <script>",
    label: "Grüße <script>\n2 files", pinned: true, renamed: true }] };
  api.render({ type: "render", version: 1, graph, viewport, loading: false });
  const scene = get("scene"), node = scene.children[0]!;
  assert.deepEqual(node.children.slice(2).map(item => item.textContent), ["Grüße <script>", "2 files"]);
  assert.match(node.getAttribute("aria-label")!, /Pinned · Renamed/);
  const transform = scene.getAttribute("transform");
  node.emit("contextmenu", { clientX: 40, clientY: 50 });
  assert.equal(get("clusterPin").textContent, "Unpin Cluster");
  get("clusterPin").emit("click");
  assert.equal(JSON.stringify(messages.at(-1)), JSON.stringify({ type: "unpin", version: 1, id: "cluster:src" }));
  node.emit("keydown", { key: "F10", shiftKey: true });
  get("clusterRename").emit("click");
  assert.equal(messages.at(-1)?.type, "rename");
  api.render({ type: "render", version: 2, graph: overview, viewport, loading: false });
  scene.children[0]!.emit("contextmenu", { clientX: 40, clientY: 50 });
  assert.equal(get("clusterPin").textContent, "Pin Cluster");
  get("clusterPin").emit("click");
  assert.equal(messages.at(-1)?.type, "pin");
  assert.equal(scene.getAttribute("transform"), transform);
  api.render({ type: "render", version: 3, graph: detail, viewport, loading: false });
  get("breadcrumb").emit("click", { clientX: 40, clientY: 50 });
  assert.equal(get("clusterMenu").hidden, false);
  get("clusterMenu").emit("keydown", { key: "Escape" });
  assert.equal(get("clusterMenu").hidden, true);
  assert.equal(scene.getAttribute("transform"), transform);
});

test("native cluster rename input validates names and rechecks trust, session and disposal", async () => {
  for (const change of ["none", "cancel", "revision", "session", "invalidate", "trust", "dispose"]) {
    const calls: string[] = [];
    const { model, session } = setup(method => { calls.push(method); return overview; });
    await model.sync();
    const workspace = { isTrusted: true };
    let complete!: (value?: string) => void;
    const file = resolve(__dirname, "../fileViewPanel.js"), requireFromView = createRequire(file);
    const exports = {} as { FileViewPanel: { prototype: object } };
    runInNewContext(await readFile(file, "utf8"), { exports, require: (id: string) => id === "vscode" ? {
      workspace, window: { showInputBox: (options: { value: string; validateInput(value: string): string | undefined }) => {
        assert.equal(options.value, "Source");
        assert.ok(options.validateInput(" \n "));
        assert.equal(options.validateInput("New"), undefined);
        return new Promise<string | undefined>(resolve => { complete = resolve; });
      } } } : id === "./sourceEditor" ? {} : requireFromView(id) });
    const panel = Object.assign(Object.create(exports.FileViewPanel.prototype), { model, context: { session }, disposed: false });
    const pending = panel.action({ type: "rename", id: "cluster:src", version: model.version });
    if (change === "revision") session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2 }, "analyse");
    if (change === "session") session.reset();
    if (change === "invalidate") session.identity.invalidate();
    if (change === "trust") workspace.isTrusted = false;
    if (change === "dispose") panel.disposed = true;
    complete(change === "cancel" ? undefined : "New");
    await pending;
    assert.deepEqual(calls, change === "none" ? ["view.get", "cluster.rename"] : ["view.get"]);
  }
});

test("P01 assignment validates file messages and routes only current files and offered clusters", async () => {
  const message = { type: "assign" as const, id: "src/main.py", version };
  assert.deepEqual(parseFileViewMessage(message), message);
  for (const value of [{ ...message, id: "" }, { ...message, clusterId: "cluster:forged" },
    { ...message, id: "bad\0file" }, { ...message, version: -1 }]) assert.equal(parseFileViewMessage(value), undefined);
  const calls: { method: string; params: Record<string, unknown> }[] = [];
  const graph = { ...detail, clusters: [{ id: "cluster:target", label: "Target", fileCount: 3 }] };
  const { model } = setup((method, params) => { calls.push({ method, params }); return graph; });
  await model.sync();
  const camera = { x: 51, y: -24, scale: 1.2 };
  await model.control({ type: "viewport", version: model.version, viewport: camera });
  await model.assignFile({ ...message, version: model.version }, "cluster:forged");
  await model.assignFile({ ...message, id: "outside", version: model.version }, null);
  assert.equal(calls.length, 1);
  await model.assignFile({ ...message, version: model.version }, "cluster:target");
  await model.assignFile({ ...message, version: model.version }, null);
  assert.deepEqual(calls.slice(1), ["cluster:target", null].map(clusterId => ({ method: "cluster.assignFile",
    params: { file: "src/main.py", clusterId, viewClusterId: "cluster:src", hierarchy: true } })));
  assert.deepEqual(model.viewport, camera);
  model.dispose();
});

test("P01 native assignment picker handles unpin, cancellation and obsolete selections", async () => {
  for (const change of ["assign", "unpin", "cancel", "revision", "trust", "dispose"]) {
    const calls: Record<string, unknown>[] = [];
    const graph = { ...detail, clusters: [{ id: "cluster:target", label: "Target", fileCount: 3 }] };
    const { model, session } = setup((method, params) => { if (method === "cluster.assignFile") calls.push(params); return graph; });
    await model.sync();
    const workspace = { isTrusted: true };
    let choose!: (value: unknown) => void;
    let offered: { id: string | null; label: string }[] = [];
    const file = resolve(__dirname, "../fileViewPanel.js"), requireFromView = createRequire(file);
    const exports = {} as { FileViewPanel: { prototype: object } };
    runInNewContext(await readFile(file, "utf8"), { exports, require: (id: string) => id === "vscode" ? {
      workspace, window: { showQuickPick: (items: typeof offered) => {
        offered = items; return new Promise(resolve => { choose = resolve; });
      } } } : id === "./sourceEditor" ? {} : requireFromView(id) });
    const panel = Object.assign(Object.create(exports.FileViewPanel.prototype), { model, context: { session }, disposed: false });
    const pending = panel.action({ type: "assign", id: "src/main.py", version: model.version });
    assert.equal(JSON.stringify(offered.map(item => item.id)), JSON.stringify([null, "cluster:target"]));
    if (change === "revision") session.identity.invalidate();
    if (change === "trust") workspace.isTrusted = false;
    if (change === "dispose") panel.disposed = true;
    choose(change === "cancel" ? undefined : offered[change === "unpin" ? 0 : 1]);
    await pending;
    assert.equal(calls.length, ["assign", "unpin"].includes(change) ? 1 : 0);
    if (calls.length) assert.equal(calls[0]!.clusterId, change === "unpin" ? null : "cluster:target");
    model.dispose();
  }
});

test("P01 File View restores nested level cameras and Back visits the saved parent", async () => {
  const { session } = setup(() => overview);
  const camera = { x: 43, y: -18, scale: 1.3 }, parentCamera = { x: 3, y: 7, scale: 0.6 };
  let saved = { clusterId: "cluster:src" as string | null,
    cameras: [{ clusterId: "cluster:src" as string | null, viewport: camera }, { clusterId: "cluster:parent", viewport: parentCamera }] };
  const graph = { ...detail, clusterPath: [{ id: "cluster:parent", label: "Parent" }, ...detail.clusterPath] };
  const client = { request: async <T>(method: string, params: Record<string, unknown> = {}): Promise<T> => {
    if (method === "view.state.set") saved = params.state as typeof saved;
    return (method.startsWith("view.state.") ? { ...context, state: saved }
      : params.clusterId === "cluster:src" ? graph
      : params.clusterId === "cluster:parent" ? { ...overview, clusterId: "cluster:parent", clusterPath: [graph.clusterPath[0]] }
      : overview) as T;
  } };
  const model = new FileViewModel(session, client, assert.fail, () => {});
  await model.sync();
  assert.equal(model.clusterId, "cluster:src");
  assert.deepEqual(model.viewport, camera);
  await model.control({ type: "back", version: model.version });
  assert.equal(model.clusterId, "cluster:parent");
  assert.deepEqual(model.viewport, parentCamera);
  assert.equal(saved.clusterId, "cluster:parent");
  model.dispose();
  const reopened = new FileViewModel(session, client, assert.fail, () => {});
  await reopened.sync();
  assert.equal(reopened.clusterId, "cluster:parent");
  assert.deepEqual(reopened.viewport, parentCamera);
  await reopened.control({ type: "enter", id: "cluster:src", version: reopened.version });
  assert.deepEqual(reopened.viewport, camera);
  reopened.dispose();
});

test("P01 stale state restoration cannot overwrite another target or write after disposal", async () => {
  const { session } = setup(() => overview);
  let finish!: (value: unknown) => void;
  const calls: string[] = [];
  const client = { request: async <T>(method: string, _params: unknown, identity?: SessionContext): Promise<T> => {
    calls.push(method);
    if (method === "view.state.get" && identity?.modelRevision === 1) return new Promise<T>(resolve => { finish = value => resolve(value as T); });
    return (method === "view.state.get" ? { ...identity, state: { clusterId: null, cameras: [] } }
      : { ...overview, ...identity }) as T;
  } };
  const model = new FileViewModel(session, client, assert.fail, () => {});
  const pending = model.sync();
  session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2 }, "analyse");
  await model.sync();
  finish({ ...context, state: { clusterId: "cluster:old", cameras: [] } });
  await pending;
  assert.equal(model.graph?.modelRevision, 2);
  assert.equal(model.clusterId, null);
  await model.control({ type: "viewport", version: model.version, viewport: { x: 1, y: 2, scale: 1 } });
  model.dispose();
  const writes = calls.filter(method => method === "view.state.set").length;
  await new Promise(resolve => setTimeout(resolve, 200));
  assert.equal(calls.filter(method => method === "view.state.set").length, writes);
});

test("P01 reselecting the same target during state restoration still loads the current graph", async () => {
  const { session } = setup(() => overview);
  let finish!: (value: unknown) => void, restoring = 0;
  const state = { ...context, state: { clusterId: null, cameras: [] } };
  const client = { request: async <T>(method: string): Promise<T> => {
    if (method === "view.state.get") {
      if (++restoring === 1) return new Promise<T>(resolve => { finish = value => resolve(value as T); });
      return state as T;
    }
    return overview as T;
  } };
  const model = new FileViewModel(session, client, assert.fail, () => {});
  const pending = model.sync();
  session.identity.invalidate(); // Reselecting the same target changes intent, but not wire identity.
  await model.sync();
  finish(state);
  await pending;
  assert.deepEqual(model.graph, overview);
  assert.equal(model.loading, false);
  model.dispose();
});
