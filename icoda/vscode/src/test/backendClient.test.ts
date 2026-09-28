import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { runTargetOperation } from "../targetOperations";
import * as assert from "node:assert/strict";
import { cp, mkdir, mkdtemp, readFile, readdir, rename, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test, TestContext } from "node:test";
import { pathToFileURL } from "node:url";
import { BackendClient, BackendOptions } from "../backendClient";
import { BackendError, OpenedProject, SessionContext } from "../protocol";
import { resolvePython } from "../pythonRuntime";
import { ProjectSession } from "../projectSession";
import { entityChoices, resolveSource } from "../sourceNavigation";
import { EvidenceModel } from "../evidenceModel";
import { MindMapModel } from "../mindMapModel";
import { ClassViewModel } from "../classViewModel";
import { FileViewModel } from "../fileViewModel";
import { CallEdge, CallViewModel } from "../callViewModel";
import { TraceAction, projectTracePath } from "../tracePlayback";
import { formatToolchain, toolchainParams, ToolchainInspection } from "../toolchain";

const packageRoot = resolve(__dirname, "../../..");

/** Every fixture launches this checkout's real service; cleanup waits for its process to close. */
async function fixture(t: TestContext, overrides: Partial<BackendOptions> = {}) {
  const directory = await mkdtemp(join(tmpdir(), "icoda vscode Grüße "));
  t.after(() => rm(directory, { recursive: true, force: true }));
  await writeFile(join(directory, "main.py"), 'raise RuntimeError("Opening must not execute or analyse me")\n');
  const python = await resolvePython(packageRoot, process.env.ICODA_TEST_PYTHON);
  const logs: string[] = [];
  const client = new BackendClient({ python, packageRoot, log: text => logs.push(text), ...overrides });
  t.after(() => client.dispose());
  return { client, directory, logs };
}

function context(project: OpenedProject): SessionContext {
  const { sessionId, modelRevision, targetId } = project;
  return { sessionId, modelRevision, targetId };
}

function hasCode(code: string): (error: unknown) => boolean {
  return error => error instanceof BackendError && error.code === code;
}

test("handshake and cache-only project.open use the real Python service", { timeout: 15_000 }, async t => {
  const { client, directory, logs } = await fixture(t);
  const initialized = await client.ready;
  assert.equal(initialized.protocolVersion, 1);
  assert.ok(initialized.backendVersion);
  assert.ok(initialized.runtime.python);
  assert.equal(initialized.capabilities.cancellation, true);
  assert.ok(initialized.capabilities.methods.includes("project.open"));
  const project = await client.request<OpenedProject>("project.open", { path: directory });
  assert.equal(project.root, directory);
  assert.equal(project.cached, false);
  assert.equal(project.modelRevision, 1);
  assert.ok(project.sessionId);
  assert.equal(project.targetId, null);
  assert.deepEqual(await readdir(directory), ["main.py"]);
  assert.equal(logs.join(""), "");
});

test("real-service toolchain inspection works before opening a project and returns structured missing tools", { timeout: 30_000 }, async t => {
  const { client, directory } = await fixture(t);
  const initialized = await client.ready;
  assert.ok(initialized.capabilities.methods.includes("toolchain.inspect"));
  const params = toolchainParams(key => key === "toolchain.cmakePath" ? join(directory, "missing-cmake") : "");
  const report = await client.request<ToolchainInspection>("toolchain.inspect", params);
  assert.deepEqual(report.runtime, initialized.runtime);
  assert.deepEqual(report.tools.map(tool => tool.name), ["cmake", "ninja", "clang", "llvm-symbolizer"]);
  assert.deepEqual(report.tools[0], { name: "cmake", path: null, source: "missing" });
  assert.match(formatToolchain(report), /missing_tool: cmake.*icoda\.toolchain\.cmakePath/);
  await assert.rejects(client.request("toolchain.inspect", { ...params, requiredTools: ["cmake"] }), error => {
    assert.ok(error instanceof BackendError);
    assert.equal(error.code, "missing_tool");
    assert.equal(error.details.tool, "cmake");
    assert.equal(error.details.setting, "icoda.toolchain.cmakePath");
    return true;
  });
  const project = await client.request<OpenedProject>("project.open", { path: directory });
  assert.equal(project.root, directory);
});

test("protocol-version mismatch rejects the handshake with structured details", { timeout: 15_000 }, async t => {
  const { client } = await fixture(t, { protocolVersion: 999 });
  await assert.rejects(client.ready, error => {
    assert.ok(error instanceof BackendError);
    assert.equal(error.code, "protocol_version_mismatch");
    assert.deepEqual(error.details, { supportedVersions: [1], requestedVersion: 999 });
    return true;
  });
  await client.closed;
  await assert.rejects(client.request("project.open"), hasCode("protocol_version_mismatch"));
});

test("concurrent requests retain individual response IDs and typed errors", { timeout: 15_000 }, async t => {
  const { client, directory } = await fixture(t);
  const opening = client.request<OpenedProject>("project.open", { path: directory });
  const requests = Array.from({ length: 24 }, (_, index) => {
    if (index % 3 === 0) return assert.rejects(client.request(`unknown.${index}`), error => {
      assert.ok(error instanceof BackendError);
      assert.equal(error.code, "unknown_method");
      assert.ok(error.message.includes(`unknown.${index}`));
      return true;
    });
    return client.request("operation.cancel", { requestId: `request-${index}` }).then(result => {
      assert.deepEqual(result, { requestId: `request-${index}`, cancellable: false, reason: "not_cancellable" });
    });
  });
  const [project] = await Promise.all([opening, Promise.all(requests)]);
  assert.equal(project.root, directory);
});

test("view.get preserves model_unavailable and the connection stays usable", { timeout: 15_000 }, async t => {
  const { client, directory } = await fixture(t);
  const project = await client.request<OpenedProject>("project.open", { path: directory });
  await assert.rejects(client.request("view.get", { view: "call" }, context(project)), error => {
    assert.ok(error instanceof BackendError);
    assert.equal(error.code, "model_unavailable");
    assert.deepEqual(error.details, {});
    return true;
  });
  const result = await client.request<{ path: string; line: number }>("source.resolve", {
    sourceRootId: project.sourceRootId, file: "main.py", line: 1,
  }, context(project));
  assert.equal(result.path, join(directory, "main.py"));
  assert.equal(result.line, 1);
});

test("killing the backend rejects every pending request", { timeout: 15_000 }, async t => {
  const { client, directory } = await fixture(t);
  const session = new ProjectSession(() => {}, () => {});
  await session.open(client, directory);
  const original = session.identity.context;
  const pid = client.pid;
  assert.ok(pid);
  // POSIX pause makes pending work deterministic without a slow/fake service method.
  if (process.platform !== "win32") process.kill(pid, "SIGSTOP");
  const pending = Array.from({ length: 5 }, () => client.request("project.open", { path: directory }));
  const rejected = pending.map(request => assert.rejects(request, hasCode("backend_exited")));
  // Flush request microtasks, but kill before polling incoming Python responses on Windows.
  await Promise.resolve();
  process.kill(pid, "SIGKILL");
  await Promise.all(rejected);
  await client.closed;
  await assert.rejects(client.request("operation.cancel", { requestId: 1 }), /Backend/);
  assert.throws(() => process.kill(pid, 0), { code: "ESRCH" });
  const python = await resolvePython(packageRoot, process.env.ICODA_TEST_PYTHON);
  const restarted = new BackendClient({ python, packageRoot, log: () => {} });
  t.after(() => restarted.dispose());
  assert.equal(await session.open(restarted, directory), true);
  assert.notEqual(session.identity.context?.sessionId, original?.sessionId);
  assert.equal(session.data?.root, directory);
});

test("missing Python rejects startup and all waiting requests", { timeout: 15_000 }, async t => {
  const { client } = await fixture(t, { python: join(tmpdir(), "icoda-no-such-python", "python") });
  await Promise.all([
    assert.rejects(client.ready, /Backend process error:.*ENOENT/),
    assert.rejects(client.request("project.open"), /Backend process error:.*ENOENT/),
  ]);
  await client.closed;
});

test("dispose is idempotent, closes Python, and rejects queued requests", { timeout: 15_000 }, async t => {
  const { client, directory } = await fixture(t);
  await client.ready;
  const pending = client.request("project.open", { path: directory });
  const rejected = assert.rejects(pending, /Backend disposed/);
  await Promise.all([client.dispose(), client.dispose(), rejected]);
  await assert.rejects(client.request("project.open"), /Backend disposed/);
  assert.throws(() => process.kill(client.pid!, 0), { code: "ESRCH" });
});

test("oversized requests fail locally without breaking the service", { timeout: 15_000 }, async t => {
  const { client } = await fixture(t);
  await assert.rejects(client.request("project.open", { path: "x".repeat(1024 * 1024) }), hasCode("message_too_large"));
  assert.deepEqual(await client.request("operation.cancel", { requestId: "still-alive" }), {
    requestId: "still-alive", cancellable: false, reason: "not_cancellable",
  });
});

test("stderr diagnostics do not corrupt protocol responses", { timeout: 15_000 }, async t => {
  const { client, directory, logs } = await fixture(t);
  await mkdir(join(directory, ".icoda"));
  await writeFile(join(directory, ".icoda/ui.json"), '["invalid persisted UI shape"]');
  await assert.rejects(client.request("project.open", { path: directory }), hasCode("internal_error"));
  const result = await client.request("operation.cancel", { requestId: "after-error" });
  assert.deepEqual(result, { requestId: "after-error", cancellable: false, reason: "not_cancellable" });
  await client.dispose();
  assert.match(logs.join(""), /Unhandled service error/);
});

test("real Python analysis updates context and counts; target selection preserves whole model", { timeout: 30_000 }, async t => {
  const { client, directory } = await fixture(t);
  await cp(join(packageRoot, "vscode/src/test/fixtures/python"), directory, { recursive: true });
  const session = new ProjectSession(() => {}, () => {});
  await session.open(client, directory);
  const opened = session.identity.context!;
  assert.equal(session.data?.modelState, "none");
  await session.analyse(client);
  assert.deepEqual(session.identity.context, { ...opened, modelRevision: 2, targetId: session.data!.targets[1]!.id });
  assert.equal(session.data?.modelState, "fresh");
  assert.equal(session.data?.entityCount, 7);
  assert.equal(session.data?.edgeCount, 5);
  assert.deepEqual(session.data?.targets.map(target => target.kind), ["whole-project", "executable"]);
  assert.equal(session.data?.targets[0]?.label, "Whole Project");
  const cache = await readFile(join(directory, ".icoda/cache/model.json"), "utf8");
  assert.equal(JSON.parse(cache).entities.length, 7);
  assert.equal(JSON.parse(cache).edges.length, 5);
  await verifySelections(session, client, directory, opened, cache);
});

async function verifySelections(session: ProjectSession, client: BackendClient, directory: string,
  opened: SessionContext, cache: string): Promise<void> {
  await session.select(client, null);
  assert.deepEqual(session.identity.context, { ...opened, modelRevision: 3 });
  const targetId = session.data!.targets[1]!.id;
  assert.ok(targetId);
  await session.select(client, targetId);
  assert.deepEqual(session.identity.context, { ...opened, modelRevision: 4, targetId });
  await session.select(client, targetId);
  assert.equal(session.identity.context?.modelRevision, 4);
  assert.equal(session.data?.entityCount, 7);
  assert.equal(session.data?.edgeCount, 5);
  assert.equal(await readFile(join(directory, ".icoda/cache/model.json"), "utf8"), cache);
  await session.open(client, directory);
  assert.notEqual(session.identity.context?.sessionId, opened.sessionId);
  assert.equal(session.identity.context?.targetId, targetId);
  assert.equal(session.identity.context?.modelRevision, 1);
}

test("failed real analysis retains stale counts, diagnostics and usable updated context", { timeout: 30_000 }, async t => {
  const { client, directory } = await fixture(t);
  await cp(join(packageRoot, "vscode/src/test/fixtures/python"), directory, { recursive: true });
  const logs: string[] = [];
  const states: string[] = [];
  const session = new ProjectSession(message => logs.push(message), () => states.push(session.data?.modelState ?? "closed"));
  await session.open(client, directory);
  await session.analyse(client);
  await writeFile(join(directory, "main.py"), "def broken(:\n");
  await assert.rejects(session.analyse(client), hasCode("analysis_failed"));
  assert.equal(session.identity.context?.modelRevision, 3);
  assert.equal(session.data?.modelState, "stale");
  assert.equal(session.data?.entityCount, 7);
  assert.equal(session.data?.edgeCount, 5);
  assert.match(session.data!.staleReason, /main.py/);
  assert.ok(logs.some(log => /analysis \(main.py\):/.test(log)));
  assert.ok(states.includes("analysing"));
  await session.select(client, null);
  assert.equal(session.identity.context?.targetId, null);
  await cp(join(packageRoot, "vscode/src/test/fixtures/python"), directory, { recursive: true });
  await session.analyse(client);
  assert.equal(session.data?.modelState, "fresh");
  assert.equal(session.identity.context?.modelRevision, 5);
});

async function sourceFixture(t: TestContext) {
  const fixtureData = await fixture(t);
  const { client, directory } = fixtureData;
  await cp(join(packageRoot, "vscode/src/test/fixtures/python"), directory, { recursive: true });
  const session = new ProjectSession(() => {}, () => {});
  await session.open(client, directory);
  await session.analyse(client);
  const choices = entityChoices(session.model!, directory, session.sourceRootId!);
  const ref = choices.find(item => item.ref.usr === "python:main:B")!.ref;
  return { ...fixtureData, session, ref };
}

test("AT03/AT04 real service resolves a moved entity, offers tied files and reports deletion locally", { timeout: 30_000 }, async t => {
  const { client, directory, session, ref, logs } = await sourceFixture(t);
  await mkdir(join(directory, "relocated"));
  const moved = join(directory, "relocated/main.py");
  await rename(join(directory, "main.py"), moved);
  assert.deepEqual(await resolveSource(client, session, ref), {
    kind: "open", uri: pathToFileURL(moved).href, line: 14, column: 1,
  });
  await mkdir(join(directory, "two"));
  await cp(moved, join(directory, "two/main.py"));
  assert.deepEqual(await resolveSource(client, session, ref), {
    kind: "choose", candidates: ["relocated/main.py", "two/main.py"], line: 14,
  });
  assert.deepEqual(await resolveSource(client, session, { sourceRootId: ref.sourceRootId, file: "two/main.py", line: 14 }), {
    kind: "open", uri: pathToFileURL(join(directory, "two/main.py")).href, line: 14, column: 1,
  });
  await rm(moved);
  await rm(join(directory, "two/main.py"));
  const missing = await resolveSource(client, session, ref);
  assert.equal(missing?.kind, "missing");
  assert.match(JSON.stringify(missing), /Source file was not found/);
  assert.doesNotMatch(JSON.stringify(missing), /source_missing|BackendError/);
  assert.doesNotMatch(JSON.stringify(missing) + logs.join(""), /provider|binary/i);
});

test("real service refuses source traversal and symlinks to files outside the chosen project", { timeout: 30_000 }, async t => {
  const { client, directory, session, ref } = await sourceFixture(t);
  const outside = await mkdtemp(join(tmpdir(), "icoda outside "));
  t.after(() => rm(outside, { recursive: true, force: true }));
  const file = join(outside, "main.py");
  await writeFile(file, "# outside project\n");
  await rm(join(directory, "main.py"));
  assert.equal((await resolveSource(client, session, { sourceRootId: ref.sourceRootId, file }))?.kind, "missing");
  assert.equal((await resolveSource(client, session, { sourceRootId: ref.sourceRootId, file: "../main.py" }))?.kind, "missing");
  if (process.platform !== "win32") {
    await symlink(file, join(directory, "main.py"));
    assert.equal((await resolveSource(client, session, ref))?.kind, "missing");
  }
});

test("manifest activation and compiled entry agree with project commands", async () => {
  const manifest = JSON.parse(await readFile(join(packageRoot, "vscode/package.json"), "utf8"));
  assert.equal(manifest.name, "icoda");
  assert.equal(manifest.publisher, "icoda");
  assert.deepEqual(Object.keys(manifest.devDependencies).sort(),
    ["@types/node", "@types/vscode", "@vscode/test-electron", "@vscode/vsce", "typescript"]);
  assert.equal(manifest.devDependencies["@vscode/vsce"], "3.6.0");
  assert.equal(manifest.dependencies, undefined);
  assert.ok(manifest.activationEvents.every((event: string) => /^(onCommand|onView):icoda\./.test(event)));
  assert.equal(manifest.contributes.commands.length, 56);
  for (const command of ["icoda.analyseProject", "icoda.selectTarget", "icoda.revealEntity", "icoda.showCallView"]) {
    assert.ok(manifest.activationEvents.includes(`onCommand:${command}`));
    assert.ok(manifest.contributes.commands.some((item: { command: string }) => item.command === command));
  }
  assert.deepEqual(manifest.contributes.menus.commandPalette, [
    { command: "icoda.selectTarget", when: "icoda.projectOpen" },
    { command: "icoda.revealEntity", when: "icoda.projectOpen" },
    { command: "icoda.showCallView", when: "icoda.projectOpen" },
    { command: "icoda.openFileView", when: "icoda.projectOpen" },
    { command: "icoda.openClassView", when: "icoda.projectOpen" },
    { command: "icoda.openMindMap", when: "icoda.projectOpen" },
    { command: "icoda.revealInFileView", when: "icoda.projectOpen" },
    { command: "icoda.assignFileCluster", when: "icoda.projectOpen" },
  ]);
  const targetMenu = manifest.contributes.menus["view/title"].find((item: { command: string }) => item.command === "icoda.selectTarget");
  assert.equal(targetMenu.when, "view == icoda.project && icoda.projectOpen");
  const reveal = manifest.contributes.commands.find((item: { command: string }) => item.command === "icoda.revealEntity");
  assert.equal(reveal.title, "Go to Entity");
  assert.equal(reveal.enablement, "icoda.projectOpen && isWorkspaceTrusted");
  const callView = manifest.contributes.commands.find((item: { command: string }) => item.command === "icoda.showCallView");
  assert.equal(callView.title, "Show Call View");
  assert.equal(callView.enablement, "icoda.projectOpen && isWorkspaceTrusted");
  const callMenu = manifest.contributes.menus["view/title"].find((item: { command: string }) => item.command === "icoda.showCallView");
  assert.equal(callMenu.when, "view == icoda.project && icoda.projectOpen");
  assert.ok(manifest.contributes.configuration.properties["icoda.pythonPath"]);
  assert.equal(manifest.contributes.views.icoda[0].id, "icoda.project");
  assert.ok(await readFile(join(packageRoot, "vscode", manifest.main), "utf8"));
});

test("real-service Call View contains main/A/B/C/D/E and selected B resolves to main.py", { timeout: 15_000 }, async t => {
  const { client, directory, logs } = await fixture(t);
  await cp(join(packageRoot, "vscode/src/test/fixtures/python"), directory, { recursive: true });
  const session = new ProjectSession(message => logs.push(message), () => {});
  await session.open(client, directory);
  await session.analyse(client);
  const view = new CallViewModel(session, client, message => logs.push(message), () => {});
  t.after(() => view.dispose());
  await view.sync();
  assert.equal(view.graph?.root, "python:main:main");
  assert.deepEqual(view.graph.edges.map(edge => [edge.source.split(":").at(-1), edge.target.split(":").at(-1)]).sort(),
    [["main", "A"], ["main", "E"], ["A", "B"], ["A", "D"], ["B", "C"]].sort());
  const node = view.graph.nodes.find(node => node.usr === "python:main:B")!;
  const viewport = { x: 17, y: 23, scale: 1.4 };
  await view.control({ type: "viewport", version: view.version, viewport });
  const ref = view.select(node.usr);
  assert.deepEqual(ref, { sourceRootId: session.sourceRootId, usr: node.usr });
  const source = await resolveSource(client, session, ref!);
  assert.equal(source?.kind, "open");
  if (source?.kind !== "open") assert.fail("B must resolve to source");
  assert.equal(source.uri, pathToFileURL(join(directory, "main.py")).toString());
  assert.equal(source.line, node.line);
  assert.equal(view.graph.root, "python:main:main");
  assert.deepEqual(view.viewport, viewport);
});

async function traceFixture(t: TestContext) {
  const fixtureData = await sourceFixture(t);
  const { client, session, directory, logs } = fixtureData;
  const view = new CallViewModel(session, client, text => logs.push(text), () => {});
  t.after(() => view.dispose());
  await view.sync();
  await view.control({ type: "root", version: view.version, usr: "python:main:A" });
  await view.control({ type: "viewport", version: view.version, viewport: { x: 13, y: -42, scale: 1.2 } });
  await view.loadTrace(join(directory, "calls.tsv"), view.version);
  for (const name of ["main", "A", "B"]) {
    await view.navigateTrace("into", view.version);
    assert.equal(view.trace?.currentEntityUsr, `python:main:${name}`);
  }
  return { ...fixtureData, view };
}

for (const [action, name, line, position] of [
  ["into", "C", 18, 4], ["over", "D", 23, 5], ["out", "E", 27, 6],
] as const) test(`AT05 real service from B: ${action} → ${name}, USR/source synchronized`, { timeout: 30_000 }, async t => {
  const { view, client, session, directory } = await traceFixture(t);
  const graph = view.graph, viewport = view.viewport;
  const ref = await view.navigateTrace(action, view.version);
  assert.deepEqual(ref, { sourceRootId: session.sourceRootId, usr: `python:main:${name}`, line });
  assert.equal(view.trace?.position, position);
  assert.equal(view.trace?.currentCall?.usr, ref!.usr);
  assert.equal(view.trace?.currentCall?.source?.line, line);
  assert.equal(view.trace?.currentCall?.threadId, "thread-1");
  assert.equal(view.graph, graph);
  assert.equal(view.viewport, viewport);
  assert.equal(view.root, "python:main:A");
  assert.equal(view.render().graph?.nodes.find(node => node.selected)?.usr, ref!.usr);
  assert.deepEqual(await resolveSource(client, session, ref!), {
    kind: "open", uri: pathToFileURL(join(directory, "main.py")).href, line, column: 1,
  });
});

test("AT09 real-service Previous, seek, Reset and exhaustion keep one cursor and repeat-edge state", { timeout: 30_000 }, async t => {
  const { view } = await traceFixture(t);
  await view.navigateTrace("previous", view.version);
  assert.equal(view.trace?.currentEntityUsr, "python:main:A");
  assert.equal(view.trace?.source?.line, 9);
  await view.navigateTrace("seek", view.version, "python:main:B");
  assert.equal(view.trace?.position, 3);
  assert.equal(view.trace?.repeatCount, 1);
  assert.deepEqual(view.trace?.callerCounts, { "python:main:A": 1 });
  const edges = view.render().graph!.edges as (CallEdge & { repeatCount: number })[];
  assert.equal(edges.find(edge => edge.source === "python:main:A" && edge.target === "python:main:B")?.repeatCount, 1);
  await view.navigateTrace("out", view.version);
  const last = view.trace;
  for (const action of ["into", "over", "out"] as TraceAction[]) {
    assert.equal(last?.availability[action], false);
    await view.navigateTrace(action, view.version);
    assert.equal(view.trace, last);
  }
  await view.navigateTrace("reset", view.version);
  assert.equal(view.selected, null);
  assert.equal(view.trace?.position, 0);
  assert.equal(view.trace?.currentCall, null);
  assert.deepEqual(view.trace?.callerCounts, {});
  assert.equal(view.render().graph?.nodes.some(node => node.selected), false);
});

test("AT08 real-service invalid/empty traces return typed errors and leave playback usable", { timeout: 30_000 }, async t => {
  const { view, client, session, directory } = await traceFixture(t);
  const selected = view.trace;
  for (const content of ["", "bad trace", "# icoda-call-trace-v1\nE\tbad\n"]) {
    const path = join(directory, "invalid.tsv");
    await writeFile(path, content);
    await assert.rejects(client.request("trace.load", { path }, session.identity.context), error => {
      assert.ok(error instanceof BackendError);
      assert.equal(error.code, "invalid_trace");
      assert.equal(error.details.path, path);
      return true;
    });
    await view.loadTrace(path, view.version);
    assert.equal(view.trace, selected);
    assert.equal(view.selected, "python:main:B");
    assert.match(view.render().message, /trace could not be loaded/);
    assert.doesNotMatch(view.render().message, /invalid_trace|BackendError/);
  }
  await view.navigateTrace("into", view.version);
  assert.equal(view.selected, "python:main:C");
  await writeFile(join(directory, "empty.tsv"), "# icoda-call-trace-v1\n");
  await view.loadTrace(join(directory, "empty.tsv"), view.version);
  assert.equal(view.selected, null);
  assert.match(view.trace!.status, /No project calls resolved/);
  assert.ok(Object.values(view.trace!.availability).every(flag => !flag));
});

test("native trace picker boundary accepts project caches and rejects other roots and escaping symlinks", async t => {
  const { client, directory } = await fixture(t);
  await client.ready;
  await mkdir(join(directory, ".icoda"));
  const file = join(directory, ".icoda/calls.tsv");
  await writeFile(file, "# icoda-call-trace-v1\n");
  assert.equal(await projectTracePath(directory, file), file);
  const outside = await mkdtemp(join(tmpdir(), "icoda external trace "));
  t.after(() => rm(outside, { recursive: true, force: true }));
  const external = join(outside, "calls.tsv");
  await writeFile(external, "");
  await assert.rejects(projectTracePath(directory, external), hasCode("invalid_trace"));
  if (process.platform !== "win32") {
    await symlink(external, join(directory, "escape.tsv"));
    await assert.rejects(projectTracePath(directory, join(directory, "escape.tsv")), hasCode("invalid_trace"));
  }
});

const prepareCpp = `
import os, sys
from pathlib import Path
from icoda_core import cmake, process
root = Path(sys.argv[1])
directory, command, environment = cmake.clang_configuration(root)
result = process.run_bounded(command, cwd=root, env=environment)
assert result.ok, result.stdout + result.stderr
`;

async function cppFixture(t: TestContext, slow = false) {
  const fixtureData = await fixture(t);
  const { client, directory } = fixtureData;
  const report = await client.request<ToolchainInspection>("toolchain.inspect");
  const missing = report.tools.filter(tool => ["cmake", "ninja", "clang"].includes(tool.name) && !tool.path);
  if (missing.length) { t.skip(`C++ service check needs ${missing.map(tool => tool.name).join(", ")}`); return; }
  await rm(join(directory, "main.py"));
  await writeFile(join(directory, "main.cpp"), "void helper() {}\nint main() { helper(); return 0; }\n");
  await writeFile(join(directory, "CMakeLists.txt"),
    "cmake_minimum_required(VERSION 3.20)\nproject(NodeTrace LANGUAGES CXX)\nadd_executable(demo main.cpp)\n"
    + (slow ? 'add_custom_command(TARGET demo PRE_BUILD COMMAND "${CMAKE_COMMAND}" -E sleep 60)\n' : ""));
  const python = await resolvePython(packageRoot, process.env.ICODA_TEST_PYTHON);
  await promisify(execFile)(python, ["-c", prepareCpp, directory], { cwd: packageRoot, timeout: 30_000 });
  const session = new ProjectSession(() => {}, () => {});
  await session.open(client, directory);
  await session.analyse(client);
  return { ...fixtureData, session };
}

test("G09 real service builds, records, loads and steps a C++ executable", { timeout: 60_000 }, async t => {
  const data = await cppFixture(t);
  if (!data) return;
  const { client, session } = data;
  const stages: string[] = [];
  const options = { progress: (message: string) => stages.push(message) };
  const built = await session.operate(client, "build.run", { trusted: true }, options);
  assert.ok(built?.executable);
  const recorded = await session.operate(client, "trace.record", { trusted: true, durationSeconds: 1 }, options);
  assert.ok(recorded?.path);
  assert.notEqual(recorded.executable, built.executable);
  assert.equal(recorded.targetId, built.targetId);
  const loaded = await client.request<{ traceId: string; resolvedCalls: number }>(
    "trace.load", { path: recorded.path }, session.identity.context);
  assert.ok(loaded.resolvedCalls >= 2);
  const step = await client.request<{ currentEntityUsr: string; source: { file: string } }>(
    "trace.step", { traceId: loaded.traceId, action: "into" }, session.identity.context);
  assert.ok(step.currentEntityUsr);
  assert.equal(step.source.file, "main.cpp");
  assert.ok(stages.includes("Build") && stages.includes("Running demo"));
});

test("native Cancel token maps to operation.cancel and a real build stays recoverable", { timeout: 30_000 }, async t => {
  const data = await cppFixture(t, true);
  if (!data) return;
  const { client, session } = data;
  let cancel: () => void = () => {};
  let disposed = false;
  const token = { isCancellationRequested: false,
    onCancellationRequested(listener: () => void) {
      cancel = listener;
      return { dispose() { disposed = true; } };
    } };
  const original = client.request.bind(client);
  const cancelledIds: number[] = [];
  client.request = ((method, params = {}, context, options) => {
    if (method === "operation.cancel") cancelledIds.push((params as { requestId: number }).requestId);
    return original(method, params, context, options);
  }) as typeof client.request;
  await assert.rejects(runTargetOperation(client, session, "build.run", { trusted: true }, token, stage => {
    if (stage === "Build") setTimeout(cancel, 150);
  }), hasCode("cancelled"));
  assert.equal(cancelledIds.length, 1);
  assert.ok(cancelledIds[0]! > 0);
  assert.ok(disposed);
  await session.listTargets(client);
  assert.ok(session.data?.targets.length);
});

async function fileFixture(t: TestContext) {
  const { client, directory } = await fixture(t);
  for (let group = 0; group < 5; group++) {
    await mkdir(join(directory, `group${group}`));
    for (let i = 0; i < 16; i++) {
      await writeFile(join(directory, `group${group}/file${i}.py`),
        `raise RuntimeError("Never execute analysis fixtures")\ndef work():\n    return ${i}\n`);
    }
  }
  const session = new ProjectSession(() => {}, () => {});
  await session.open(client, directory);
  await session.analyse(client);
  const model = new FileViewModel(session, client, assert.fail, () => {});
  t.after(() => model.dispose());
  await model.sync();
  return { client, directory, session, model };
}

test("real File View overview → expand → select → resolve, Back and reveal of relocated source", { timeout: 30_000 }, async t => {
  const { client, directory, session, model } = await fileFixture(t);
  const handshake = await client.ready;
  assert.ok(handshake.capabilities.views.includes("file") && handshake.capabilities.methods.includes("view.revealFile"));
  assert.equal(model.graph?.nodes.filter(n => n.kind === "cluster").length, 5);
  assert.ok(model.graph!.nodes.length < 81);
  const cluster = model.graph!.nodes.find(n => n.id === "cluster:group0")!;
  assert.equal(cluster.fileCount, 16);
  const camera = { x: 25, y: -40, scale: 1.4 };
  await model.control({ type: "viewport", viewport: camera, version: model.version });
  await model.control({ type: "enter", id: cluster.id, version: model.version });
  assert.equal(model.graph!.nodes.length, 16);
  const file = model.graph!.nodes[0]!;
  const ref = model.select(file.id)!;
  assert.deepEqual(await resolveSource(client, session, ref), {
    kind: "open", uri: pathToFileURL(join(directory, file.file!)).href, line: 1, column: 1,
  });
  await model.control({ type: "back", version: model.version });
  assert.deepEqual(model.viewport, camera);
  await model.reveal(ref);
  assert.equal(model.selected, file.id);
  await checkMovedFile(client, session, model, directory, file.file!);
});

async function checkMovedFile(client: BackendClient, session: ProjectSession, model: FileViewModel, directory: string, file: string) {
  const moved = `relocated/${file}`;
  await mkdir(join(directory, "relocated", file.split("/")[0]!), { recursive: true });
  await rename(join(directory, file), join(directory, moved));
  const ref = model.select(file)!;
  assert.deepEqual(await resolveSource(client, session, ref), {
    kind: "open", uri: pathToFileURL(join(directory, moved)).href, line: 1, column: 1,
  });
  await model.reveal({ sourceRootId: session.sourceRootId!, file: moved });
  assert.equal(model.selected, file);
  await rm(join(directory, moved));
  // The other directories now contain equally plausible cached basenames.
  assert.equal((await resolveSource(client, session, ref))?.kind, "choose");
}

test("real Class View opens classes and selects class/member sources through relocation and ambiguity", { timeout: 30_000 }, async t => {
  const { client, directory } = await fixture(t);
  await writeFile(join(directory, "classes.py"), 'raise RuntimeError("Never execute")\nclass Base: pass\n'
    + 'class Widget(Base):\n    def use(self, item: Base) -> Base:\n        return item\n');
  const session = new ProjectSession(() => {}, () => {});
  await session.open(client, directory);
  await session.analyse(client);
  const model = new ClassViewModel(session, client, assert.fail, () => {});
  t.after(() => model.dispose());
  await model.sync();
  assert.ok((await client.ready).capabilities.views.includes("class"));
  assert.deepEqual(model.graph!.nodes.map(n => n.label), ["classes.Base", "classes.Widget"]);
  const node = model.graph!.nodes.find(n => n.label.endsWith("Widget"))!;
  for (const source of [node, ...node.members!]) {
    assert.ok(model.accepts({ type: "select", version: model.version, id: source.usr! }));
    const ref = model.select(source.usr!)!;
    assert.deepEqual(await resolveSource(client, session, ref), {
      kind: "open", uri: pathToFileURL(join(directory, "classes.py")).href, line: source.line, column: 1,
    });
  }
  const ref = model.select(node.members![0]!.usr)!;
  await mkdir(join(directory, "moved"));
  await rename(join(directory, "classes.py"), join(directory, "moved/classes.py"));
  assert.deepEqual(await resolveSource(client, session, ref), {
    kind: "open", uri: pathToFileURL(join(directory, "moved/classes.py")).href, line: 4, column: 1,
  });
  await mkdir(join(directory, "duplicate"));
  await cp(join(directory, "moved/classes.py"), join(directory, "duplicate/classes.py"));
  assert.equal((await resolveSource(client, session, ref))?.kind, "choose");
  await rm(join(directory, "moved/classes.py"));
  await rm(join(directory, "duplicate/classes.py"));
  assert.equal((await resolveSource(client, session, ref))?.kind, "missing");
});

async function writeMindMapFixture(directory: string): Promise<void> {
  const source = join(directory, "library.cpp");
  await writeFile(source, '/// @satisfies R-1\nclass Widget {\npublic:\n    /// @satisfies R-1\n'
    + '    int run() { return 1; }\n};\n');
  await writeFile(join(directory, "compile_commands.json"), JSON.stringify([
    { directory, file: source, arguments: ["clang++", "-std=c++20", "-c", source] },
  ]));
  await mkdir(join(directory, ".icoda"));
  await writeFile(join(directory, ".icoda/specification.json"), JSON.stringify({
    schema_version: 2, title: "Mind Map", requirements: [
      { id: "R-1", title: "Return one", description: "Return one", priority: "must", use_cases: ["UC-1"] },
    ], use_cases: [{ id: "UC-1", title: "Run", description: "Run the widget" }],
  }));
  await writeFile(join(directory, ".icoda/steps.jsonl"), JSON.stringify({
    number: 2, phase: "architecture", decision: "approved", title: "Introduce Widget",
    files: ["library.cpp"], entities_added: ["c:@S@Widget", "c:@S@Widget@F@run#"],
  }) + "\n");
}

test("real Mind Map opens, persists expansion and resolves selected sources", { timeout: 30_000 }, async t => {
  const { client, directory } = await fixture(t);
  await writeMindMapFixture(directory);
  const session = new ProjectSession(() => {}, () => {});
  await session.open(client, directory);
  await session.analyse(client);
  const model = new MindMapModel(session, client, assert.fail, () => {});
  t.after(() => model.dispose());
  await model.sync();
  const capabilities = (await client.ready).capabilities;
  assert.ok(capabilities.views.includes("mindmap") && capabilities.methods.includes("mindmap.setExpanded"));
  const expanded: string[] = [];
  while (model.graph!.nodes.some(node => node.expandable && !node.expanded)) {
    const node = model.graph!.nodes.find(node => node.expandable && !node.expanded)!;
    expanded.push(node.id);
    await model.control({ type: "setExpanded", nodeId: node.id, expanded: true, version: model.version });
  }
  const node = model.graph!.nodes.find(node => node.usr === "c:@S@Widget@F@run#")!;
  assert.deepEqual(node.requirementIds, ["R-1"]);
  assert.deepEqual(node.useCaseIds, ["UC-1"]);
  assert.deepEqual(node.step, { number: 2, title: "Introduce Widget" });
  assert.equal(node.status, "stub");
  assert.equal(model.accepts({ type: "select", nodeId: node.id, version: model.version }), true);
  assert.deepEqual(await resolveSource(client, session, model.select(node.id)!), {
    kind: "open", uri: pathToFileURL(join(directory, "library.cpp")).href, line: 5, column: 1,
  });
  await verifyMindMapReload(client, session, model, directory, expanded);
});

async function verifyMindMapReload(client: BackendClient, session: ProjectSession, model: MindMapModel,
  directory: string, expanded: string[]): Promise<void> {
  const persisted = JSON.parse(await readFile(join(directory, ".icoda/state.json"), "utf8"));
  assert.deepEqual(persisted.mind_map.expanded, [...expanded].sort());
  const root = model.graph!.nodes.find(node => node.parent === null && node.expandable)!;
  const camera = { x: -123, y: 45, scale: 1.25 };
  await model.control({ type: "viewport", viewport: camera, version: model.version });
  await model.control({ type: "setExpanded", nodeId: root.id, expanded: false, version: model.version });
  assert.deepEqual(model.viewport, camera);
  assert.equal(model.selected, null);
  await session.open(client, directory);
  await model.sync();
  assert.equal(model.graph!.nodes.find(node => node.id === root.id)!.expanded, false);
  await model.control({ type: "setExpanded", nodeId: root.id, expanded: true, version: model.version });
  assert.ok(model.graph!.nodes.some(node => node.usr === "c:@S@Widget@F@run#"));
}


test("real service Issues and Coverage analyse a fixture and resolve selected evidence", { timeout: 30_000 }, async t => {
  const { client, directory } = await fixture(t);
  await writeMindMapFixture(directory);
  await writeFile(join(directory, ".icoda/steps.jsonl"), JSON.stringify({
    number: 3, phase: "implementation", decision: "approved", title: "Test Widget", test_ok: true,
    selected_tests: ["Widget::run"],
  }) + "\n");
  const session = new ProjectSession(() => {}, () => {});
  await session.open(client, directory);
  await session.analyse(client);
  for (const kind of ["issues", "coverage"] as const) {
    assert.ok((await client.ready).capabilities.methods.includes(kind === "issues" ? "issues.list" : "coverage.get"));
    const model = new EvidenceModel(kind, session, client, assert.fail, () => {});
    t.after(() => model.dispose());
    await model.sync();
    const node = kind === "issues" ? model.items()[0]!.children![0]! : model.items()[0]!.children![0]!.children![0]!;
    const ref = model.select({ view: kind, id: node.id, version: model.version });
    assert.ok(ref);
    assert.deepEqual(await resolveSource(client, session, ref), {
      kind: "open", uri: pathToFileURL(join(directory, "library.cpp")).href, line: ref.line, column: 1,
    });
    if (kind === "coverage") {
      assert.equal(model.items()[1]!.label, "Structural Test Reachability");
      assert.equal(model.items()[1]!.children![0]!.description, "Reached");
      assert.match(model.items()[1]!.children![0]!.tooltip!, /#3 Test Widget/);
    }
  }
});

test("real-service specification, validation, phase and provider round trip", { timeout: 15_000 }, async t => {
  const { client, directory } = await fixture(t);
  const { SpecificationModel } = await import("../specificationModel.js");
  const { SpecificationDocuments } = await import("../specificationDocuments.js");
  const session = new ProjectSession(() => {}, () => {});
  await session.open(client, directory);
  const model = new SpecificationModel(session, client, () => {});
  t.after(() => model.dispose());
  await model.sync();
  const profile = model.snapshot?.spec?.codeProfile;
  assert.ok(profile && typeof profile === "object" && "language" in profile);
  assert.equal(profile.language, "Python");
  assert.equal(model.snapshot?.spec?.schemaVersion, 2);
  assert.equal(model.snapshot?.spec?.exists, false);
  assert.equal(model.snapshot?.phase?.phase, "specification");
  assert.ok(Array.isArray(model.snapshot?.providers?.providers));
  assert.deepEqual(model.snapshot?.errors, []);
  const documents = new SpecificationDocuments(model, () => true);
  await documents.open("fixture");
  assert.equal((await documents.validate("fixture", documents.read("fixture"))).valid, true);
  await assert.rejects(documents.save("fixture", '{"title":""}'), /missing|empty/);
  await documents.save("fixture", documents.read("fixture"));
  const persisted = JSON.parse(await readFile(join(directory, ".icoda/specification.json"), "utf8"));
  assert.deepEqual(persisted, model.snapshot!.spec!.document);
  await model.sync();
  assert.equal(model.snapshot?.spec?.exists, true);
  assert.equal(model.snapshot?.phase?.phase, "architecture");
  assert.deepEqual(model.snapshot?.phase?.allowedTransitions, ["implementation"]);
  assert.equal(session.data?.modelState, "fresh");
  assert.ok(session.model?.entities.length);
});
