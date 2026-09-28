import * as assert from "node:assert/strict";
import { test } from "node:test";
import { ViewState } from "../viewState";
import { ProjectSession } from "../projectSession";
import { BackendError, SessionContext } from "../protocol";

const context = { sessionId: "p11", modelRevision: 1, targetId: null };
const camera = { viewport: { x: 31, y: -42, scale: 1.5 } };
function setup(reply: (method: string, params: object, identity?: SessionContext) => unknown) {
  const logs: string[] = [];
  const session = new ProjectSession(message => logs.push(message), () => {});
  session.identity.accept(session.identity.capture(), context, "open");
  const client = { request: async <T>(method: string, params = {}, identity?: SessionContext) =>
    await reply(method, params, identity) as T };
  const state = new ViewState<typeof camera>("mindmap", session, client, message => logs.push(message));
  return { state, session, logs };
}

test("P11 view state restores, coalesces writes and flushes before disposal", async () => {
  const writes: object[] = [];
  const { state } = setup((method, params, identity) => {
    if (method === "view.state.set") {
      assert.deepEqual(identity, context);
      writes.push(params);
    }
    return { ...identity, state: camera };
  });
  assert.deepEqual(await state.restore(), camera);
  state.schedule({ viewport: { x: 1, y: 2, scale: 1 } });
  state.schedule({ viewport: { x: 3, y: 4, scale: 2 } });
  state.dispose();
  await state.flush();
  assert.deepEqual(writes, [{ view: "mindmap", state: { viewport: { x: 3, y: 4, scale: 2 } } }]);
  state.schedule(camera);
  await state.flush();
  assert.equal(writes.length, 1);
});

test("P11 disposal drops pending and queued writes after project or target switches", async () => {
  for (const change of ["project", "target", "reselect"] as const) {
    for (const ordering of ["switch-first", "flush-first", "dispose-first"] as const) {
      const writes: object[] = [];
      const { state, session } = setup((method, params, identity) => {
        if (method === "view.state.set") writes.push({ params, identity });
        return { ...identity, state: camera };
      });
      await state.restore();
      state.schedule({ viewport: { x: 7, y: 8, scale: 1 } });
      const writing = ordering === "flush-first" ? state.flush() : Promise.resolve();
      if (ordering === "dispose-first") state.dispose();
      if (change === "project") {
        session.reset();
        assert.ok(session.identity.accept(session.identity.capture(), { ...context, sessionId: "new-project" }, "open"));
      } else {
        session.identity.invalidate();
        const targetId = change === "target" ? "library:other" : null;
        assert.ok(session.identity.accept(session.identity.capture(),
          { ...context, targetId, modelRevision: change === "target" ? 2 : 1 }, { targetId }));
      }
      if (ordering !== "dispose-first") state.dispose();
      await writing;
      await state.flush();
      assert.deepEqual(writes, [], `${change}: ${ordering}`);
    }
  }
});

test("P11 pending camera writes and late restores cannot cross target or session generations", async () => {
  for (const reset of [false, true]) {
    const writes: object[] = [];
    let resolve!: (value: unknown) => void;
    let slow = false;
    const { state, session } = setup((method, params, identity) => {
      if (method === "view.state.set") writes.push(params);
      if (slow) return new Promise(done => { resolve = done; });
      return { ...identity, state: camera };
    });
    await state.restore();
    state.schedule({ viewport: { x: 7, y: 8, scale: 1 } });
    if (reset) session.reset(); else session.identity.invalidate();
    await state.flush();
    assert.deepEqual(writes, []);
    session.identity.accept(session.identity.capture(), context, "open");
    slow = true;
    const pending = state.restore();
    session.identity.invalidate();
    resolve({ ...context, state: camera });
    assert.equal(await pending, undefined);
    state.dispose();
  }
});

test("P11 corrupt saved state is reported and never overwritten by default cameras", async () => {
  const requests: string[] = [];
  const { state, logs } = setup(method => {
    requests.push(method);
    throw new BackendError("view_state_invalid", "Repair .icoda/ui.json; saved bytes preserved.");
  });
  assert.equal(await state.restore(), undefined);
  state.schedule(camera);
  await state.flush();
  state.dispose();
  assert.deepEqual(requests, ["view.state.get"]);
  assert.match(logs[0]!, /Repair .icoda\/ui.json/);
});

// Model integration verifies the persistence adapter is actually wired to all three diagrams.
import { CallViewModel } from "../callViewModel";
import { ClassViewModel } from "../classViewModel";
import { MindMapModel } from "../mindMapModel";

for (const view of ["call", "class", "mindmap"] as const) {
  test(`P11 ${view} controls restore after model recreation and save camera changes`, async () => {
    const session = new ProjectSession(assert.fail, () => {});
    session.identity.accept(session.identity.capture(), context, "open");
    let saved: object = view === "call" ? { root: null, depth: 5, callers: true, filter: "work", ...camera }
      : view === "class" ? { clusterId: null, cameras: [{ clusterId: null, ...camera }] } : camera;
    const methods: string[] = [];
    let hold = false, release!: () => void;
    const client = { request: async <T>(method: string, params = {}, identity?: SessionContext): Promise<T> => {
      methods.push(method);
      if (hold && method === "view.state.get") await new Promise<void>(done => { release = done; });
      if (method === "view.state.set") saved = (params as { state: object }).state;
      return (method.startsWith("view.state.") ? { ...identity, view, state: saved }
        : { ...identity, view, nodes: [], edges: [], roots: [], width: 200, height: 100, bounds: { x: 0, y: 0 },
          sourceRootId: "p11:workspace", root: null, clusterId: null, messages: [] }) as T;
    } };
    const create = () => view === "call" ? new CallViewModel(session, client, assert.fail, () => {})
      : view === "class" ? new ClassViewModel(session, client, assert.fail, () => {})
        : new MindMapModel(session, client, assert.fail, () => {});
    const original = create();
    await original.sync();
    assert.deepEqual(original.viewport, camera.viewport);
    if (original instanceof CallViewModel) {
      assert.equal(original.depth, 5);
      assert.equal(original.callers, true);
      assert.equal(original.filter, "work");
    }
    const viewport = { x: -15, y: 24, scale: 0.7 };
    session.identity.invalidate(); // Reselecting the same target retains its wire identity.
    await original.sync();
    await original.control({ type: "viewport", version: original.version, viewport });
    await original.saveState();
    hold = true;
    session.identity.accept(session.identity.capture(), { ...context, modelRevision: 2 }, "analyse");
    const refreshing = original.sync();
    assert.equal(original.graph, undefined, "old graph must disappear before the saved state reply");
    assert.equal(original.loading, true);
    hold = false;
    release();
    await refreshing;
    original.dispose();
    // A new service session cannot use the in-memory Call View cache.
    session.reset();
    session.identity.accept(session.identity.capture(), { ...context, sessionId: "restarted" }, "open");
    const restored = create();
    await restored.sync();
    assert.deepEqual(restored.viewport, viewport);
    assert.equal(methods.filter(method => method === "view.state.set").length, 1);
    restored.dispose();
  });
}
