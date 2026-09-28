import * as assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { GraphInteractions } from "../graphInteractions";
import { ProjectSession } from "../projectSession";
import { BackendError, SessionContext } from "../protocol";
import { parseCallViewMessage } from "../callViewMessages";
import { parseFileViewMessage } from "../fileViewMessages";
import { parseClassViewMessage } from "../classViewMessages";
import { parseMindMapMessage } from "../mindMapMessages";
import { CallViewModel } from "../callViewModel";
import { FileViewModel } from "../fileViewModel";
import { ClassViewModel } from "../classViewModel";
import { MindMapModel } from "../mindMapModel";
import { TestElement } from "./webviewHarness";

const context = { sessionId: "p04", modelRevision: 1, targetId: null };
const sourceRootId = "p04:workspace";
const identity = { ...context, sourceRootId };
const decisions = { A: { hidden: false, dimmed: false }, B: { hidden: true, dimmed: false } };
function session() {
  const project = new ProjectSession(assert.fail, () => {});
  project.identity.accept(project.identity.capture(), context, "open");
  project.sourceRootId = sourceRootId;
  return project;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

test("P04 graph options use one strict schema in all four webviews", () => {
  for (const parse of [parseCallViewMessage, parseFileViewMessage, parseClassViewMessage, parseMindMapMessage]) {
    const valid = { type: "graphOptions", version: 4, text: "namespace:app::* edge:calls", depth: 2 };
    assert.deepEqual(parse(valid), valid);
    assert.ok(parse({ ...valid, text: "", depth: 0 }));
    for (const patch of [{ depth: -1 }, { depth: 13 }, { depth: true }, { depth: 1.5 }, { depth: NaN },
      { text: "x".repeat(257) }, { text: "x\0y" }, { text: {} }, { extra: 1 }, { version: -1 },
      { version: 1.5 }, { version: "4" }]) assert.equal(parse({ ...valid, ...patch }), undefined);
    const { text: _text, ...missing } = valid;
    assert.equal(parse(missing), undefined);
  }
});

for (const Model of [CallViewModel, FileViewModel, ClassViewModel, MindMapModel]) {
  test(`P04 ${Model.name} routes shared decisions without changing selection root or camera`, async () => {
    const project = session(), requests: { method: string; params: Record<string, unknown> }[] = [];
    const graph = { ...identity, view: "call", nodes: [{ id: "A", usr: "A", kind: "function", label: "A", members: [] }],
      edges: [], roots: ["A"], root: "A", width: 100, height: 100, clusterId: null, clusterPath: [], messages: [] };
    const client = { request: async <T>(method: string, params: Record<string, unknown> = {}): Promise<T> => {
      requests.push({ method, params });
      return (method === "graph.interactions" ? { ...identity, decisions }
        : method === "view.state.get" ? { ...identity, state: { clusterId: null, cameras: [] } } : graph) as T;
    } };
    let view!: InstanceType<typeof Model>;
    view = new Model(project, client, assert.fail, () => { view.render(); });
    await view.sync();
    view.viewport = { x: 71, y: -21, scale: 1.3 };
    view.selected = "A";
    const before = structuredClone(view.render());
    const reads = requests.length;
    await view.control({ type: "graphOptions", version: view.version, text: "namespace:app::*", depth: 1 });
    assert.deepEqual(requests.slice(reads), [{ method: "graph.interactions", params: {
      sourceRootId, text: "namespace:app::*", depth: 1, focus: "A" } }]);
    const after = view.render();
    assert.deepEqual(after.interactions.decisions, decisions);
    assert.deepEqual(after.graph, before.graph);
    assert.deepEqual(after.viewport, before.viewport);
    assert.equal(after.selected, before.selected);
    assert.equal(view.accepts({ type: "graphOptions", version: view.version - 1, text: "", depth: 0 }), false);
    await view.control({ type: "graphOptions", version: view.version, text: "", depth: 0 });
    assert.deepEqual(view.render().interactions.decisions, {});
    assert.equal(requests.length, reads + 1);
    view.dispose();
  });
}

test("P04 shared interactions discard superseded project graph and disposed replies", async () => {
  for (const change of ["options", "selection", "graph", "project", "dispose"]) {
    const project = session(), pending = deferred<object>();
    let count = 0, changed = 0;
    const model = new GraphInteractions(project, { request: async <T>(): Promise<T> => {
      count++;
      return (count === 1 ? await pending.promise : { ...identity, decisions: {} }) as T;
    } }, () => { changed++; }, assert.fail);
    model.snapshot(identity, "A");
    const request = model.control({ type: "graphOptions", text: "kind:function", depth: 1 });
    if (change === "options") await model.control({ type: "graphOptions", text: "", depth: 0 });
    if (change === "selection") model.snapshot(identity, "B");
    if (change === "graph") model.snapshot({ ...identity }, "A");
    if (change === "project") project.reset();
    if (change === "dispose") model.dispose();
    await Promise.resolve();
    const before = changed;
    pending.resolve({ ...identity, decisions });
    await request;
    assert.equal(changed, before, change);
    assert.deepEqual(model.snapshot(identity, "A").decisions, {}, change);
    model.dispose();
  }
});

test("P04 shared interactions route candidate and recording identities and expose local errors", async () => {
  const project = session();
  const candidate = { ...identity, sourceRootId: "p04:proposal:checked" };
  const calls: object[] = [], errors: string[] = [];
  const model = new GraphInteractions(project, { request: async <T>(_method: string, params = {}, ctx?: SessionContext): Promise<T> => {
    calls.push({ params, ctx });
    throw new BackendError("stale_evidence", "Reopen the candidate.");
  } }, () => {}, error => errors.push(error));
  model.snapshot(candidate, "A");
  await model.control({ type: "graphOptions", text: "edge:calls", depth: 0 });
  assert.deepEqual(calls[0], { params: { sourceRootId: candidate.sourceRootId, text: "edge:calls", depth: 0, focus: null }, ctx: context });
  assert.match(model.snapshot(candidate, "A").error, /Reopen the candidate/);
  model.snapshot(identity, "A", "recording");
  await Promise.resolve();
  assert.deepEqual(calls[1], { params: { sourceRootId, text: "edge:calls", depth: 0, focus: null, traceId: "recording" }, ctx: context });
  assert.equal(errors.length, 2);
  model.dispose();
});

test("P04 shipped shared controls decorate nodes edges and keyboard focus without moving the scene", () => {
  const doc = { activeElement: undefined as TestElement | undefined, getElementById: (id: string) => elements.get(id) };
  const elements = new Map<string, TestElement & { value?: string }>();
  for (const id of ["graphQuery", "graphNeighborhood", "graphClear", "graphOptions", "graphFeedback", "scene"]) {
    elements.set(id, new TestElement(id, doc));
  }
  const node = (id: string) => { const n = new TestElement(id, doc); n.setAttribute("data-id", id); return n; };
  const a = node("A"), b = node("B"), group = node("group"), edge = node("edge");
  edge.setAttribute("data-source", "A"); edge.setAttribute("data-target", "B");
  const classes = new Map<TestElement, Map<string, boolean>>();
  for (const item of [a, b, group, edge]) {
    classes.set(item, new Map());
    Object.assign(item.classList, { toggle: (key: string, value: boolean) => { classes.get(item)!.set(key, value); } });
  }
  elements.get("scene")!.querySelectorAll = selector => selector === ".edge" ? [edge] : [a, b, group];
  const js = readFileSync(resolve(__dirname, "../../media/graphInteractions.js"), "utf8");
  const ui = runInNewContext(js + "\nicodaGraphInteractions", { document: doc, clearTimeout, setTimeout });
  const messages: object[] = [];
  const send = (type: string, fields: object) => messages.push({ type, ...fields });
  const state = { version: 3, selected: "A", graph: { nodes: [{ id: "A" }, { id: "B" }, { id: "group", expandable: true }], roots: [] },
    interactions: { text: "kind:method", depth: 1, decisions: {
      A: { hidden: true, dimmed: true }, B: { hidden: true, dimmed: false }, group: { hidden: true, dimmed: false } } } };
  b.focus();
  ui.render(state, send);
  assert.equal(classes.get(a)!.get("graph-filtered"), false, "selection stays visible");
  assert.equal(classes.get(group)!.get("graph-filtered"), false, "expansion gateway stays visible");
  assert.equal(classes.get(b)!.get("graph-filtered"), true);
  assert.equal(classes.get(edge)!.get("graph-filtered"), true);
  assert.equal(doc.activeElement, elements.get("graphQuery"));
  ui.render({ ...state, interactions: { ...state.interactions, decisions: { B: { dimmed: true } } } }, send);
  assert.equal(classes.get(b)!.get("graph-filtered"), false);
  assert.equal(classes.get(b)!.get("graph-dimmed"), true);
  assert.equal(classes.get(edge)!.get("graph-dimmed"), true);
  elements.get("graphClear")!.emit("click");
  assert.deepEqual(JSON.parse(JSON.stringify(messages.at(-1))), { type: "graphOptions", text: "", depth: 0 });
  assert.equal(elements.get("scene")!.getAttribute("transform"), undefined);
});
