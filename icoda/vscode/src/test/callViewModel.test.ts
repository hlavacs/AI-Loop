import * as assert from "node:assert/strict";
import { test } from "node:test";
import { CallEdge, CallNode, CallViewModel, CallViewResponse, callViewRenderData } from "../callViewModel";
import { BackendError, SessionContext } from "../protocol";
import { ProjectSession } from "../projectSession";
import { PlaybackState } from "../tracePlayback";

const context = { sessionId: "project", modelRevision: 1, targetId: null };
const sourceRootId = "project:workspace";
const node = (usr: string, level: number, extra: Partial<CallNode> = {}): CallNode => ({
  usr, label: `example.${usr}`, x: 130 + level * 260, y: 22, level, kind: "function", status: "implemented",
  signature: "()", brief: "A function", sourceRootId, file: "main.py", line: 4, ...extra,
});
const edge = (source: string, target: string, extra: Partial<CallEdge> = {}): CallEdge => ({
  source, target, label: "", kind: "calls", loop: false, uncertain: false, free: false, ...extra,
});
const graph: CallViewResponse = {
  ...context, sourceRootId, view: "call", root: "main", roots: ["main"], depth: 3, callers: false,
  libraryMode: false, width: 1040, height: 88, stale: false, staleReason: "",
  nodes: [node("main", 0), node("A", 1, { added: true }), node("B", 2, { status: "tested", changed: true }), node("C", 3)],
  edges: [edge("main", "A"), edge("A", "B"), edge("B", "C", { uncertain: true }),
    edge("B", "B", { loop: true }), edge("A", "C")],
};

function client(reply: (method: string, params: Record<string, unknown>, context?: SessionContext) => unknown) {
  return { request: async <T>(method: string, params = {}, context?: SessionContext): Promise<T> =>
    (method.startsWith("view.state.") ? { ...context, state: { root: null, depth: 3, callers: false, filter: "", viewport: null } }
      : await reply(method, params, context)) as T };
}

function session() {
  const logs: string[] = [];
  const project = new ProjectSession(message => logs.push(message), () => {});
  project.identity.accept(project.identity.capture(), context, "open");
  project.sourceRootId = sourceRootId;
  project.data = { root: "/project", modelState: "fresh", staleReason: "", entityCount: 4, edgeCount: 5, targets: [] };
  return { project, logs };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test("render mapping preserves shared layout, recursion, uncertain/shared edges, statuses and markings", () => {
  const data = callViewRenderData(graph, "", "B");
  assert.deepEqual(data.edges, graph.edges);
  assert.equal(data.edges.filter(edge => edge.target === "C").length, 2);
  assert.equal(data.edges.find(edge => edge.source === edge.target)?.loop, true);
  assert.equal(data.edges.find(edge => edge.source === "B" && edge.target === "C")?.uncertain, true);
  assert.deepEqual(data.nodes.map(n => [n.usr, n.x, n.y, n.level]), graph.nodes.map(n => [n.usr, n.x, n.y, n.level]));
  assert.equal(data.width, graph.width);
  assert.equal(data.nodes[1]?.change, "added");
  assert.equal(data.nodes[2]?.change, "changed");
  assert.equal(data.nodes[2]?.selected, true);
  assert.match(data.nodes[2]!.tooltip, /example.B\nfunction · tested\nmain.py:4/);
});

test("P02 candidate graph routes its checked root and preserves project playback camera and saved state", async () => {
  const { project } = session();
  const main = new CallViewModel(project, client(() => graph), assert.fail, () => {});
  await main.sync();
  main.root = "A";
  main.viewport = { x: 51, y: -12, scale: 1.4 };
  main.select("B");
  main.dispose();
  const saved = structuredClone(project.callViewState);
  const candidateRoot = "project:proposal:checked";
  const requests: string[] = [];
  const candidate = new CallViewModel(project, client((method, params) => {
    requests.push(method);
    assert.equal(params.sourceRootId, candidateRoot);
    return { ...graph, sourceRootId: candidateRoot, nodes: graph.nodes.map(node => ({ ...node, sourceRootId: candidateRoot })) };
  }), assert.fail, () => {}, candidateRoot);
  await candidate.sync();
  assert.equal(candidate.render().proposal, true);
  assert.equal(candidate.render().graph?.nodes.find(node => node.usr === "A")?.change, "added");
  assert.equal(candidate.render().graph?.nodes.find(node => node.usr === "B")?.change, "changed");
  assert.deepEqual(candidate.select("B"), { sourceRootId: candidateRoot, usr: "B" });
  await candidate.loadTrace("calls.tsv", candidate.version);
  assert.deepEqual(requests, ["view.get"]);
  assert.equal(candidate.accepts({ type: "traceSeek", version: candidate.version, usr: "B" }), false);
  candidate.dispose();
  assert.deepEqual(project.callViewState, saved);
  const restored = new CallViewModel(project, client(() => assert.fail()), assert.fail, () => {});
  await restored.sync();
  assert.equal(restored.root, "A");
  assert.equal(restored.selected, "B");
  assert.deepEqual(restored.viewport, { x: 51, y: -12, scale: 1.4 });
  restored.dispose();
});

test("P02 stale candidate failures keep source lookup separate and drop late candidate graphs", async () => {
  const { project } = session();
  const late = deferred<CallViewResponse>();
  const candidate = new CallViewModel(project, client(() => late.promise), () => {}, () => {}, "candidate");
  const pending = candidate.sync();
  project.identity.invalidate();
  late.resolve(graph);
  await pending;
  assert.equal(candidate.graph, undefined);
  candidate.dispose();
});

test("entry points and library API roots survive filtering, without moving nodes", () => {
  const main = callViewRenderData(graph, "example.C");
  assert.equal(main.root, "main");
  assert.deepEqual(main.nodes.map(n => n.usr), ["main", "C"]);
  assert.equal(main.nodes[1]?.x, graph.nodes[3]?.x);
  assert.deepEqual(callViewRenderData(graph, "no matches").nodes.map(n => n.usr), ["main"]);
  const library = callViewRenderData({ ...graph, libraryMode: true, root: null, roots: ["main", "A"] }, "no matches");
  assert.equal(library.root, null);
  assert.equal(library.libraryMode, true);
  assert.deepEqual(library.nodes.map(n => n.usr), ["main", "A"]);
  assert.ok(library.nodes.every(n => n.root));
  assert.deepEqual(library.edges, [graph.edges[0]]);
});

test("selection changes only highlighting/source, retaining the chosen root and viewport without view.get", async () => {
  const { project } = session();
  let requests = 0;
  const view = new CallViewModel(project, client((method, params, identity) => {
    requests++;
    assert.equal(method, "view.get");
    assert.deepEqual(identity, context);
    assert.deepEqual(params, { view: "call", root: requests === 1 ? null : "A", depth: 3, callers: false });
    return requests === 1 ? graph : { ...graph, root: "A", roots: ["A"] };
  }), assert.fail, () => {});
  await view.sync();
  await view.control({ type: "root", version: view.version, usr: "A" });
  await view.control({ type: "viewport", version: view.version, viewport: { x: 123, y: -44, scale: 1.7 } });
  const before = view.viewport;
  assert.deepEqual(view.select("B"), { sourceRootId, usr: "B" });
  assert.equal(view.root, "A");
  assert.equal(view.viewport, before);
  assert.equal(view.render().graph?.nodes.find(n => n.usr === "B")?.selected, true);
  assert.equal(requests, 2);
  assert.equal(view.accepts({ type: "select", version: view.version, usr: "not-in-graph" }), false);
  assert.equal(view.accepts({ type: "root", version: view.version, usr: "not-in-graph" }), false);
});

test("depth and callers delegate layout; filter and fit use existing geometry locally", async () => {
  const { project } = session();
  const calls: Record<string, unknown>[] = [];
  const view = new CallViewModel(project, client((_method, params) => { calls.push(params); return graph; }), assert.fail, () => {});
  await view.sync();
  await view.control({ type: "depth", version: view.version, depth: 5 });
  await view.control({ type: "callers", version: view.version, callers: true });
  assert.deepEqual(calls.at(-1), { view: "call", root: null, depth: 5, callers: true });
  await view.control({ type: "filter", version: view.version, text: "example.C" });
  await view.control({ type: "fit", version: view.version, width: 1000, height: 500 });
  assert.deepEqual(view.render().graph?.nodes.map(n => n.usr), ["main", "C"]);
  assert.ok(view.viewport!.scale > 0 && view.viewport!.scale < 1);
  assert.equal(calls.length, 3);
});

test("stale session/revision/target read responses are rejected through SessionState", async () => {
  for (const mismatch of [{ sessionId: "other" }, { modelRevision: 9 }, { targetId: "library" }]) {
    const { project, logs } = session();
    const view = new CallViewModel(project, client(() => ({ ...graph, ...mismatch })), assert.fail, () => {});
    await view.sync();
    assert.equal(view.graph, undefined);
    assert.ok(logs.some(log => log.startsWith("Dropped stale response")));
  }
});

test("revision refresh replaces old graph and drops late results and obsolete webview input", async () => {
  const { project } = session();
  const old = deferred<CallViewResponse>();
  const view = new CallViewModel(project, client((_method, _params, identity) =>
    identity?.modelRevision === 1 ? old.promise : { ...graph, ...identity }), assert.fail, () => {});
  const first = view.sync();
  const version = view.version;
  project.identity.accept(project.identity.capture(), { ...context, modelRevision: 2 }, "analyse");
  await view.sync();
  old.resolve(graph);
  await first;
  assert.equal(view.graph?.modelRevision, 2);
  assert.equal(view.accepts({ type: "select", version, usr: "B" }), false);
  assert.equal(view.accepts({ type: "select", version: view.version, usr: "B" }), true);
});

test("closing or switching projects during a read cannot render its late success or failure", async () => {
  for (const action of ["dispose", "reset", "switch"]) {
    const { project } = session();
    const pending = deferred<CallViewResponse>();
    let renders = 0;
    const view = new CallViewModel(project, client(() => pending.promise), assert.fail, () => { renders++; });
    const running = view.sync();
    await new Promise<void>(done => setImmediate(done)); // Let state restoration reach the pending graph read.
    if (action === "dispose") view.dispose();
    else project.reset();
    if (action === "switch") project.identity.accept(project.identity.capture(), { ...context, sessionId: "other" }, "open");
    const before = renders;
    if (action === "reset") pending.reject(new Error("obsolete failure"));
    else pending.resolve(graph);
    await running;
    assert.equal(view.graph, undefined);
    assert.equal(renders, before);
  }
});

test("target changes reset roots; same-revision saves show stale state without reloading layout", async () => {
  const { project } = session();
  let requests = 0;
  const view = new CallViewModel(project, client((_method, params, identity) => {
    requests++;
    return { ...graph, ...identity, root: params.root ?? "main" };
  }), assert.fail, () => {});
  await view.sync();
  await view.control({ type: "root", version: view.version, usr: "B" });
  project.markSaved("main.py");
  await view.sync();
  assert.match(view.render().message, /Stale model: Saved main.py/);
  assert.equal(requests, 2);
  project.identity.accept(project.identity.capture(), { ...context, modelRevision: 2, targetId: "library" }, { targetId: "library" });
  await view.sync();
  assert.equal(view.root, null);
  assert.equal(requests, 3);
});

test("a disappeared explicit root falls back once; missing models explain analysis", async () => {
  const { project } = session();
  const logs: string[] = [];
  const view = new CallViewModel(project, client((_method, params) => {
    if (params.root) throw new BackendError("unknown_root", "Gone");
    return graph;
  }), message => logs.push(message), () => {});
  await view.sync();
  await view.control({ type: "root", version: view.version, usr: "B" });
  assert.equal(view.root, null);
  assert.equal(view.graph?.root, "main");
  assert.match(logs[0]!, /restoring its entry points/);
  const unavailable = new CallViewModel(project, client(() => { throw new BackendError("model_unavailable", "None"); }),
    () => {}, () => {});
  await unavailable.sync();
  assert.match(unavailable.render().message, /Run ICODA: Analyse Project/);
});

const playback: PlaybackState = {
  ...context, sourceRootId, traceId: "trace", position: 3, total: 6, currentEntityUsr: "B",
  source: { sourceRootId, file: "main.py", line: 14 },
  currentCall: { usr: "B", source: { sourceRootId, file: "main.py", line: 14 }, threadId: "one", depth: 2, sequence: 2 },
  repeatCount: 4, callerCounts: { A: 3, B: 1 }, status: "call 3 of 6: B — 4 consecutive calls",
  availability: { into: true, over: false, out: true, previous: true, reset: true },
};

test("closing and reopening Call View restores playback only in the same session revision and target", async () => {
  for (const change of ["none", "revision", "target", "reset"]) {
    const { project } = session();
    const backend = client((method, _params, identity) => method === "view.get" ? { ...graph, ...identity } : playback);
    const view = new CallViewModel(project, backend, assert.fail, () => {});
    await view.sync();
    await view.loadTrace("calls.tsv", view.version);
    await view.control({ type: "root", version: view.version, usr: "A" });
    await view.control({ type: "viewport", version: view.version, viewport: { x: 20, y: 30, scale: 1.4 } });
    const before = view.render();
    view.dispose();
    if (change === "reset") project.reset();
    else if (change !== "none") {
      const targetId = change === "target" ? "library" : null;
      project.identity.accept(project.identity.capture(), { ...context, modelRevision: 2, targetId },
        change === "target" ? { targetId } : "analyse");
    }
    const reopened = new CallViewModel(project, backend, assert.fail, () => {});
    await reopened.sync();
    assert.equal(view.accepts({ type: "ready" }), false, "closed model rejects old messages");
    if (change === "none") {
      assert.deepEqual(reopened.render().trace, before.trace);
      assert.deepEqual(reopened.render().graph, before.graph);
      assert.equal(reopened.selected, before.selected);
      assert.equal(reopened.root, before.root);
      assert.deepEqual(reopened.viewport, before.viewport);
      assert.deepEqual(await reopened.navigateTrace("into", reopened.version), { sourceRootId, usr: "B", line: 14 });
    } else {
      assert.equal(reopened.trace, undefined);
      assert.equal(reopened.selected, null);
      assert.equal(reopened.root, null);
    }
  }
});

test("trace actions delegate to Python, render its flags/counts, and retain root, filter and viewport", async () => {
  const { project } = session();
  const requests: { method: string; params: Record<string, unknown> }[] = [];
  const view = new CallViewModel(project, client((method, params) => {
    requests.push({ method, params });
    return method === "view.get" ? graph : playback;
  }), assert.fail, () => {});
  await view.sync();
  view.root = "A";
  view.viewport = { x: 20, y: 30, scale: 1.4 };
  view.filter = "no matches";
  await view.loadTrace("calls.tsv", view.version);
  assert.deepEqual(requests.at(-1)?.params, { view: "call", root: "A", depth: 3, callers: false, traceId: "trace" });
  const count = requests.length;
  assert.equal(await view.navigateTrace("over", view.version), undefined);
  assert.equal(requests.length, count); // The backend disabled Over despite position < total.
  assert.deepEqual(await view.navigateTrace("into", view.version), { sourceRootId, usr: "B", line: 14 });
  assert.deepEqual(requests.at(-1), { method: "trace.step", params: { traceId: "trace", action: "into" } });
  assert.deepEqual(view.render().trace, playback);
  assert.equal(view.render().graph?.nodes.find(node => node.selected)?.usr, "B");
  assert.equal(view.root, "A");
  assert.deepEqual(view.viewport, { x: 20, y: 30, scale: 1.4 });
  view.filter = "";
  const edges = view.render().graph!.edges as (CallEdge & { repeatCount: number })[];
  assert.equal(edges.find(edge => edge.source === "A" && edge.target === "B")?.repeatCount, 3);
  assert.equal(edges.find(edge => edge.source === "B" && edge.target === "B")?.repeatCount, 1);
});

test("Previous, Reset and graph seek use shared methods and clear selection/counters from the response", async () => {
  const { project } = session();
  const requests: string[] = [];
  const cleared = { ...playback, position: 0, currentEntityUsr: null, currentCall: null, source: null, repeatCount: 0, callerCounts: {} };
  const view = new CallViewModel(project, client((method, params) => {
    requests.push(`${method}:${params.action ?? ""}`);
    return method === "view.get" ? graph : method === "trace.load" ? playback : cleared;
  }), assert.fail, () => {});
  await view.sync();
  await view.loadTrace("calls.tsv", view.version);
  for (const action of ["previous", "reset", "seek"] as const) {
    await view.navigateTrace(action, view.version, action === "seek" ? "B" : undefined);
    assert.equal(view.selected, null);
    assert.equal(view.render().trace?.repeatCount, 0);
    assert.deepEqual(view.render().trace?.callerCounts, {});
  }
  assert.deepEqual(requests.slice(-3), ["trace.step:previous", "trace.reset:", "trace.step:seek"]);
  assert.equal(view.accepts({ type: "traceSeek", version: view.version, usr: "missing" }), false);
});

test("late trace replies/errors cannot survive disposal, revision/target changes, graph reload or session reset", async () => {
  for (const change of ["dispose", "reset", "revision", "target", "graph"]) {
    const { project } = session();
    const reply = deferred<PlaybackState>();
    const view = new CallViewModel(project, client((method, _params, identity) =>
      method === "view.get" ? { ...graph, ...identity } : reply.promise), assert.fail, () => {});
    await view.sync();
    const version = view.version;
    const running = view.loadTrace("calls.tsv", version);
    if (change === "dispose") view.dispose();
    else if (change === "reset") project.reset();
    else if (change === "graph") await view.control({ type: "depth", version, depth: 4 });
    else {
      const targetId = change === "target" ? "library" : null;
      project.identity.accept(project.identity.capture(), { ...context, modelRevision: 2, targetId },
        change === "target" ? { targetId } : "analyse");
      await view.sync();
    }
    if (change === "reset") reply.reject(new Error("obsolete error"));
    else reply.resolve(playback);
    await running;
    assert.equal(view.trace, undefined);
    assert.equal(view.selected, null);
    assert.equal(view.error, "");
  }
});

test("trace replies must match session, revision, target and loaded trace ID", async () => {
  for (const mismatch of [{ sessionId: "other" }, { modelRevision: 99 }, { targetId: "other" }, { traceId: "old" }]) {
    const { project } = session();
    const view = new CallViewModel(project, client(method => method === "view.get" ? graph
      : method === "trace.load" ? playback : { ...playback, ...mismatch, currentEntityUsr: "C" }), assert.fail, () => {});
    await view.sync();
    await view.loadTrace("calls.tsv", view.version);
    assert.equal(await view.navigateTrace("into", view.version), undefined);
    assert.equal(view.selected, "B");
    assert.equal(view.trace, playback);
  }
});

test("a superseded trace mutation cannot replace the latest successful seek", async () => {
  const { project } = session();
  const pending = deferred<PlaybackState>();
  const view = new CallViewModel(project, client((method, params) => method === "view.get" ? graph
    : params.action === "into" ? pending.promise : playback), assert.fail, () => {});
  await view.sync();
  await view.loadTrace("calls.tsv", view.version);
  const old = view.navigateTrace("into", view.version);
  await view.navigateTrace("seek", view.version, "B");
  pending.resolve({ ...playback, currentEntityUsr: "C" });
  assert.equal(await old, undefined);
  assert.equal(view.selected, "B");
});

test("reanalysis retains ordinary graph selection but invalidates an old trace selection", async () => {
  for (const loaded of [false, true]) {
    const { project } = session();
    const view = new CallViewModel(project, client((method, _params, identity) =>
      method === "view.get" ? { ...graph, ...identity } : playback), assert.fail, () => {});
    await view.sync();
    view.select("B");
    if (loaded) await view.loadTrace("calls.tsv", view.version);
    project.identity.accept(project.identity.capture(), { ...context, modelRevision: 2 }, "analyse");
    await view.sync();
    assert.equal(view.selected, loaded ? null : "B");
    assert.equal(view.trace, undefined);
  }
});
