import * as assert from "node:assert/strict";
import { test } from "node:test";
import { ProjectSession } from "../projectSession";
import { AnalysedProject, BackendError, OpenedProject, SessionContext, TargetList } from "../protocol";
import { resolveSource } from "../sourceNavigation";
import { join } from "node:path";

const opened: OpenedProject = {
  sessionId: "a", sourceRootId: "a:workspace", root: "/chosen", modelRevision: 1, targetId: null,
  cached: true, model: { entities: [{ usr: "main" }, { usr: "library" }], edges: [{}], stale: false, stale_reason: "" },
  state: {}, ui: {}, layout: {},
};
const targets: TargetList = { ...opened, targets: [], diagnostics: [] };
const analysed: AnalysedProject = { ...opened, modelRevision: 2, diagnostics: [] };

function client(reply: (method: string, params: object, context?: SessionContext) => unknown) {
  return { request: async <T>(method: string, params = {}, context?: SessionContext): Promise<T> =>
    await reply(method, params, context) as T };
}

async function session() {
  const logs: string[] = [];
  const state = new ProjectSession(message => logs.push(message), () => {});
  await state.open(client(method => method === "project.open" ? opened : targets), "/chosen");
  return { state, logs };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test("target selection sends only target.select with current context and preserves whole counts", async () => {
  const { state } = await session();
  const calls: string[] = [];
  await state.select(client((method, params, context) => {
    calls.push(method);
    assert.deepEqual(context, { sessionId: "a", modelRevision: 1, targetId: null });
    assert.deepEqual(params, { targetId: "library" });
    return { ...analysed, targetId: "library", model: { ...opened.model, entities: [{}], edges: [] } };
  }), "library");
  assert.deepEqual(calls, ["target.select"]);
  assert.deepEqual(state.identity.context, { sessionId: "a", modelRevision: 2, targetId: "library" });
  assert.equal(state.data?.entityCount, 2);
  assert.equal(state.data?.edgeCount, 1);
});

test("analysis arriving after reset cannot restore a closed project or fetch targets", async () => {
  const { state, logs } = await session();
  const reply = deferred<AnalysedProject>();
  const running = state.analyse(client(method => {
    assert.equal(method, "project.analyse");
    return reply.promise;
  }));
  assert.equal(state.data?.modelState, "analysing");
  state.reset();
  reply.resolve(analysed);
  await running;
  assert.equal(state.data, undefined);
  assert.equal(state.identity.context, undefined);
  assert.ok(logs.some(log => log.includes("Dropped stale response")));
});

test("old analysis success or failure cannot overwrite another opened project", async () => {
  for (const failed of [false, true]) {
    const { state, logs } = await session();
    const reply = deferred<AnalysedProject>();
    const running = state.analyse(client(() => reply.promise));
    const replacement = { ...opened, sessionId: "b", root: "/other" };
    await state.open(client(method => method === "project.open" ? replacement : { ...targets, ...replacement }), "/other");
    if (failed) reply.reject(new BackendError("analysis_failed", "Old failure", { ...analysed }));
    else reply.resolve(analysed);
    await running;
    assert.equal(state.data?.root, "/other");
    assert.equal(state.data?.modelState, "fresh");
    assert.equal(state.identity.context?.sessionId, "b");
    assert.ok(logs.some(log => log.startsWith("Dropped")));
  }
});

test("late open, target list and selection responses are discarded after reset", async () => {
  for (const method of ["project.open", "targets.list", "target.select"]) {
    const { state, logs } = await session();
    const reply = deferred<unknown>();
    const backend = client(() => reply.promise);
    const running = method === "project.open" ? state.open(backend, "/other")
      : method === "targets.list" ? state.listTargets(backend) : state.select(backend, "library");
    state.reset();
    reply.resolve(method === "target.select" ? { ...analysed, targetId: "library" } : opened);
    await running;
    assert.equal(state.data, undefined);
    assert.equal(state.identity.context, undefined);
    assert.ok(logs.some(log => log.includes("Dropped stale response")));
  }
});

test("identity errors remain typed and leave analysis status usable for refresh", async () => {
  for (const code of ["stale_revision", "invalid_session", "stale_target"]) {
    const { state } = await session();
    const error = new BackendError(code, "Refresh required");
    await assert.rejects(state.analyse(client(() => { throw error; })), error);
    assert.equal(state.data?.modelState, "fresh");
    assert.equal(state.identity.context?.modelRevision, 1);
  }
});

test("target-list errors after analysis are surfaced rather than dropped as obsolete", async () => {
  const { state } = await session();
  const error = new BackendError("stale_revision", "Refresh required");
  await assert.rejects(state.analyse(client(method => {
    if (method === "project.analyse") return analysed;
    throw error;
  })), error);
  assert.equal(state.identity.context?.modelRevision, 2);
  assert.equal(state.data?.modelState, "fresh");
});

test("source requests use the held root and full session context", async () => {
  const { state } = await session();
  const ref = { sourceRootId: state.sourceRootId!, usr: "main" };
  const outcome = await resolveSource(client((method, params, context) => {
    assert.equal(method, "source.resolve");
    assert.deepEqual(params, ref);
    assert.deepEqual(context, state.identity.context);
    return { ...opened, file: "main.py", path: join(opened.root, "main.py"), line: 4 };
  }), state, ref);
  assert.equal(outcome?.kind, "open");
  const wrongRoot = await resolveSource(client(() => assert.fail("must not request another root")), state, {
    ...ref, sourceRootId: "other:workspace",
  });
  assert.equal(wrongRoot?.kind, "error");
});

test("source successes and typed errors arriving after reset are discarded", async () => {
  for (const failed of [false, true]) {
    const { state } = await session();
    const reply = deferred<unknown>();
    const pending = resolveSource(client(() => reply.promise), state, { sourceRootId: state.sourceRootId!, usr: "main" });
    state.reset();
    if (failed) reply.reject(new BackendError("source_ambiguous", "Old choice", { ...opened, candidates: ["a.py", "b.py"] }));
    else reply.resolve({ ...opened, file: "main.py", path: join(opened.root, "main.py"), line: 4 });
    assert.equal(await pending, undefined);
  }
});

test("source responses with stale session, revision or target are discarded", async () => {
  for (const identity of [{ sessionId: "other" }, { modelRevision: 8 }, { targetId: "old" }]) {
    const { state } = await session();
    const result = { ...opened, ...identity, file: "main.py", path: join(opened.root, "main.py"), line: 4 };
    const ref = { sourceRootId: state.sourceRootId!, usr: "main" };
    assert.equal(await resolveSource(client(() => result), state, ref), undefined);
    assert.equal(await resolveSource(client(() => {
      throw new BackendError("source_ambiguous", "Old candidates", { ...result, candidates: ["a.py", "b.py"] });
    }), state, ref), undefined);
  }
});

test("saved sources mark only local tree state stale, preserving model, counts and wire identity", async () => {
  const { state } = await session();
  const before = state.identity.context;
  state.markSaved("src/main.py");
  assert.equal(state.data?.modelState, "stale");
  assert.match(state.data!.staleReason, /src\/main.py.*Analyse Project/);
  assert.equal(state.model, opened.model);
  assert.equal(state.model?.stale, false);
  assert.equal(state.data?.entityCount, 2);
  assert.deepEqual(state.identity.context, before);
  await state.analyse(client(method => method === "project.analyse" ? analysed : { ...targets, modelRevision: 2 }));
  assert.equal(state.data?.modelState, "fresh");
  assert.equal(state.data?.staleReason, "");
  state.reset();
  assert.equal(state.model, undefined);
  assert.equal(state.sourceRootId, undefined);
  state.markSaved("old.py");
  assert.equal(state.data, undefined);
});

test("analysis started before a saved-source mark cannot clear that stale reason", async () => {
  const { state } = await session();
  const reply = deferred<AnalysedProject>();
  const pending = state.analyse(client(method => method === "project.analyse" ? reply.promise : { ...targets, modelRevision: 2 }));
  state.markSaved("during-analysis.py");
  reply.resolve(analysed);
  await pending;
  assert.equal(state.data?.modelState, "stale");
  assert.match(state.data!.staleReason, /during-analysis.py/);
});


test("target refresh accepts one revision advance and keeps the whole-project model", async () => {
  const { state } = await session();
  const model = state.model;
  const refreshed = { ...targets, modelRevision: 2, message: "Refreshed", path: null };
  assert.deepEqual(await state.operate(client(() => refreshed), "targets.refresh", {}, {}), refreshed);
  assert.equal(state.identity.context?.modelRevision, 2);
  assert.equal(state.model, model);
});

test("late target operation successes and failures cannot appear after project reset", async () => {
  for (const failure of [false, true]) {
    const { state, logs } = await session();
    const reply = deferred<unknown>();
    const running = state.operate(client(() => reply.promise), "trace.record", {}, {});
    state.reset();
    if (failure) reply.reject(new BackendError("run_failed", "obsolete"));
    else reply.resolve({ ...targets, path: "old.tsv", message: "obsolete" });
    assert.equal(await running, undefined);
    assert.equal(state.data, undefined);
    assert.ok(logs.some(log => log.startsWith("Dropped")));
  }
});

test("target operation replies must retain selected target and revision", async () => {
  for (const context of [{ modelRevision: 9 }, { targetId: "another" }]) {
    const { state } = await session();
    assert.equal(await state.operate(client(() => ({ ...targets, ...context })), "build.run", {}, {}), undefined);
    assert.equal(state.identity.context?.modelRevision, 1);
    assert.equal(state.identity.context?.targetId, null);
  }
});

test("target switch invalidates analysis before its acknowledgement and suppresses old progress", async () => {
  const { state, logs } = await session();
  const analysis = deferred<AnalysedProject>(), selection = deferred<unknown>();
  let progress!: (message: string) => void;
  const messages: string[] = [];
  const backend = { request: async <T>(method: string, _params: object, _context?: SessionContext,
    options?: { progress?: (message: string) => void }): Promise<T> => {
    if (method === "project.analyse") { progress = options!.progress!; return await analysis.promise as T; }
    assert.equal(method, "target.select"); return await selection.promise as T;
  } };
  const running = state.analyse(backend, { progress: message => messages.push(message) });
  progress("old analysis started");
  const switching = state.select(backend, "library");
  progress("obsolete progress");
  analysis.resolve(analysed); await running;
  assert.equal(state.identity.context?.modelRevision, 1);
  assert.equal(state.data?.modelState, "stale");
  selection.resolve({ ...analysed, targetId: "library" }); await switching;
  assert.deepEqual(messages, ["old analysis started"]);
  assert.equal(state.identity.context?.targetId, "library");
  assert.ok(logs.some(log => log.startsWith("Dropped stale response")));
});

test("late operation progress is scoped to its project ticket", async () => {
  const { state } = await session();
  const completion = deferred<unknown>();
  const messages: string[] = [];
  let progress!: (message: string) => void;
  const backend = { request: async <T>(_method: string, _params: object, _context?: SessionContext,
    options?: { progress?: (message: string) => void }): Promise<T> => {
    progress = options!.progress!; return await completion.promise as T;
  } };
  const running = state.operate(backend, "build.run", {}, { progress: message => messages.push(message) });
  state.reset(); progress("obsolete");
  completion.reject(new BackendError("cancelled", "Superseded"));
  assert.equal(await running, undefined); assert.deepEqual(messages, []);
});

test("late open, catalog and target errors are dropped after another project is chosen", async () => {
  for (const method of ["project.open", "targets.list", "target.select"]) {
    const { state, logs } = await session();
    const reply = deferred<unknown>(), backend = client(() => reply.promise);
    const running = method === "project.open" ? state.open(backend, "/other")
      : method === "targets.list" ? state.listTargets(backend) : state.select(backend, "library");
    state.reset(); reply.reject(new BackendError("cancelled", "Old request")); await running;
    assert.equal(state.identity.context, undefined);
    assert.ok(logs.some(message => message === `Dropped obsolete ${method} error.`));
  }
});
