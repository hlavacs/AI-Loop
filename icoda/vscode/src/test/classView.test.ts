import * as assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { parseClassViewMessage, registerClassCommand } from "../classViewMessages";
import { classViewHtml } from "../classViewHtml";
import { ClassViewModel, ClassViewResponse } from "../classViewModel";
import { ProjectSession } from "../projectSession";
import { SessionContext } from "../protocol";

const version = 3;

test("Class View messages validate exact shapes, bounded identities and shared camera fields", () => {
  const valid = [{ type: "ready" }, { type: "enter", id: "cluster:src", version },
    { type: "select", id: "src/main.py", version }, { type: "back", version },
    { type: "viewport", version, viewport: { x: 10, y: -20, scale: 2 } },
    { type: "fit", version, width: 900, height: 600 }];
  for (const message of valid) {
    assert.deepEqual(parseClassViewMessage(message), message);
    assert.equal(parseClassViewMessage({ ...message, extra: 1 }), undefined);
  }
  for (const message of [null, [], {}, { type: "traceLoad", version }, { type: "reveal", version }, { type: "back", version: -1 },
    { type: "enter", version, id: "" }, { type: "enter", version, id: "a\0" },
    { type: "enter", version, id: "x".repeat(4097) }, { type: "select", version, id: 3 },
    { type: "select", id: "a" }, { type: "reveal", version, file: "../injected" },
    { type: "viewport", version, viewport: { x: 0, y: 0, scale: Infinity } },
    { type: "fit", version, width: 0, height: 10 }]) assert.equal(parseClassViewMessage(message), undefined);
});

test("Class View commands are registered, contributed, activated and trust-gated", async () => {
  const calls: string[] = [], commands = new Map<string, () => unknown>();
  registerClassCommand((id, callback) => commands.set(id, callback), () => calls.push("open"));
  const manifest = JSON.parse(await readFile(resolve(__dirname, "../../package.json"), "utf8"));
  for (const [id, action] of commands) {
    action();
    assert.ok(manifest.activationEvents.includes(`onCommand:${id}`));
    const command = manifest.contributes.commands.find((c: { command: string }) => c.command === id);
    assert.equal(command.enablement, "icoda.projectOpen && isWorkspaceTrusted");
    assert.ok(manifest.contributes.menus.commandPalette.some((c: { command: string }) => c.command === id));
  }
  assert.deepEqual(calls, ["open"]);
  assert.equal(manifest.contributes.commands.find((c: { command: string }) => c.command === "icoda.openClassView").title, "Open Class View");
  const extension = await readFile(resolve(__dirname, "../../src/extension.ts"), "utf8");
  assert.match(extension, /registerClassCommand\(/);
  assert.match(extension, /this\.classView\?\.sync\(\)/);
  assert.match(extension, /this\.classView\?\.dispose\(\)/);
});

test("Class View uses a nonce CSP, one scrolling control row, DOM text and native source navigation", async () => {
  const html = classViewHtml("nonce", "local:", "local:script", "local:style");
  assert.match(html, /default-src 'none'; base-uri 'none'; form-action 'none'/);
  assert.match(html, /script-src 'nonce-nonce'/);
  assert.match(html, /script type="module" nonce="nonce"/);
  assert.doesNotMatch(html, /unsafe-inline|unsafe-eval|onclick=|Next Call/);
  assert.equal((html.match(/role="toolbar"/g) ?? []).length, 1);
  const root = resolve(__dirname, "../..");
  const [script, css, panel] = await Promise.all([readFile(resolve(root, "media/classView.js"), "utf8"),
    readFile(resolve(root, "media/callView.css"), "utf8"), readFile(resolve(root, "src/classViewPanel.ts"), "utf8")]);
  assert.match(script, /textContent/);
  assert.doesNotMatch(script, /innerHTML|eval\(/);
  assert.match(css, /flex-wrap: nowrap;.*overflow-x: auto/);
  assert.match(panel, /parseClassViewMessage\(value\)/);
  assert.match(script, /node.members.*map\(memberLabel\)/);
  assert.match(script, /inheritance: -28, composition: 0, usage: 28/);
  assert.match(panel, /revealSource\(this.context, ref, true/);
});

const context = { sessionId: "session", modelRevision: 1, targetId: null };
const sourceRootId = "session:workspace";
const overview: ClassViewResponse = {
  ...context, sourceRootId, view: "class", clusterId: null, clusterPath: [], overview: true,
  nodes: [{ id: "cluster:src", label: "Source\n2 classes", kind: "cluster", count: 2,
    x: 150, y: 100, width: 200, height: 54, expandable: true }], edges: [],
  headerHeight: 48, memberHeight: 25, bounds: { x: 50, y: 73 }, width: 200, height: 54, stale: false, staleReason: "",
};
const detail: ClassViewResponse = { ...overview, clusterId: "cluster:src", overview: false,
  clusterPath: [{ id: "cluster:src", label: "Source" }],
  nodes: [{ id: "class:Widget", usr: "class:Widget", entityId: "class:Widget", label: "Widget", kind: "class",
    x: 130, y: 100, width: 320, height: 81, file: "src/main.py", sourceRootId, line: 1, expandable: false,
    members: [{ usr: "method:run", entityId: "method:run", name: "run", kind: "method", declaration: "run(self)",
      status: "implemented", visibility: null, file: "src/main.py", sourceRootId, line: 2 }] }],
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
  return { session, logs, model: new ClassViewModel(session, client, message => logs.push(message), () => {}) };
}

test("expanding and Back preserve each camera; only visible classes and members can open source", async () => {
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
  assert.deepEqual(model.select("class:Widget"), { usr: "class:Widget", sourceRootId });
  assert.equal(model.select("/outside"), undefined);
  assert.equal(model.accepts({ type: "select", id: "method:run", version: model.version }), true);
  assert.deepEqual(model.select("method:run"), { usr: "method:run", sourceRootId });
  model.select("class:Widget");
  assert.equal(model.render().selected, "class:Widget");
  await model.control({ type: "back", version: model.version });
  assert.deepEqual(model.viewport, camera);
  await model.control({ type: "enter", id: "cluster:src", version: model.version });
  assert.deepEqual(model.viewport, detailCamera);
});

test("Class View rejects late replies, invalid nodes, stale actions and post-disposal work", async () => {
  let complete!: (value: ClassViewResponse) => void;
  const pending = new Promise<ClassViewResponse>(resolve => { complete = resolve; });
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

test("wrong response identities and a project switch never populate a Class View", async () => {
  for (const mismatch of [{ sessionId: "other" }, { modelRevision: 10 }, { targetId: "other" }]) {
    const { model, logs } = setup(() => ({ ...overview, ...mismatch }));
    await model.sync();
    assert.equal(model.graph, undefined);
    assert.ok(logs.some(text => text.startsWith("Dropped stale response")));
  }
  let complete!: (value: ClassViewResponse) => void;
  const pending = new Promise<ClassViewResponse>(resolve => { complete = resolve; });
  const { model, session } = setup(() => pending);
  const loading = model.sync();
  session.reset();
  complete(overview);
  await loading;
  assert.equal(model.graph, undefined);
});
