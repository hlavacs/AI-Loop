import * as assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { test } from "node:test";
import { registerTargetCommands, targetCommands, runTargetOperation } from "../targetOperations";
import { ProjectSession } from "../projectSession";
import { BackendClient } from "../backendClient";
import { BackendError, validateProjectCheck } from "../protocol";

test("P06 all five trusted target commands register the manifest's operation and title", async () => {
  const root = resolve(__dirname, "../..");
  const manifest = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
  const handlers = new Map<string, () => unknown>();
  const calls: string[][] = [];
  const registrations = registerTargetCommands((name, action) => { handlers.set(name, action); return name; },
    (method, title) => calls.push([method, title]));
  assert.equal(registrations.length, 5);
  for (const command of targetCommands) {
    handlers.get(command.command)!();
    const contribution = manifest.contributes.commands.find((item: { command: string }) => item.command === command.command);
    assert.equal(contribution.title, command.title);
    assert.equal(contribution.enablement, "icoda.projectOpen && isWorkspaceTrusted");
    assert.ok(manifest.activationEvents.includes(`onCommand:${command.command}`));
  }
  assert.deepEqual(calls, targetCommands.map(item => [item.method, item.title]));
  const source = await readFile(resolve(root, "src/extension.ts"), "utf8");
  assert.match(source, /registerTargetCommands\(/);
  assert.match(source, /targetOperation\(method: string, title: string\)[\s\S]*?await this.backend\(\)/);
  assert.match(source, /title: `ICODA: \$\{title\}`, cancellable: true/);
  assert.match(source, /if \(!vscode.workspace.isTrusted\)/);
});

test("already-cancelled native tokens propagate abort and release their listener on errors", async () => {
  let disposed = false;
  const token = { isCancellationRequested: true,
    onCancellationRequested: () => ({ dispose() { disposed = true; } }) };
  const session = new ProjectSession(() => {}, () => {});
  session.operate = async function(_client: unknown, _method: string, _params: object, options: { signal: AbortSignal }) {
    assert.ok(options.signal.aborted);
    throw new Error("cancelled");
  };
  await assert.rejects(runTargetOperation({} as BackendClient, session, "build.run", {}, token, () => {}), /cancelled/);
  assert.ok(disposed);
});

test("P06 full checks validate messages and preserve the selected model through failures and stale replies", async () => {
  validateProjectCheck({ kind: "tests", ok: true, output: "1 passed" }, "tests");
  for (const check of [undefined, null, [], {}, { kind: "tests", ok: false, output: "failed" },
    { kind: "build", ok: true, output: "" }, { kind: "tests", ok: true, output: 7 },
    { kind: "tests", ok: true, output: "", extra: true }]) {
    assert.throws(() => validateProjectCheck(check, "tests"), /invalid_response/);
  }
  const logs: string[] = [];
  const session = new ProjectSession(message => logs.push(message), () => {});
  const opened = { sessionId: "p06", modelRevision: 1, targetId: "library", root: "/project",
    sourceRootId: "p06:workspace", cached: true, state: {}, ui: {}, layout: {},
    model: { entities: [{ usr: "main" }], edges: [], stale: false, stale_reason: "" } };
  const targets = [{ id: null, kind: "whole-project", label: "Whole Project" }];
  const client = { request: async <T>(method: string) => (method === "project.open" ? opened
    : { ...opened, targets, diagnostics: [] }) as T };
  await session.open(client, "/project");
  const identity = session.identity.context, model = session.model, data = { ...session.data };
  const result = { ...opened, targets, diagnostics: [], target: targets[0], executable: null, path: null,
    message: "Whole Project: tests passed (saved files).", check: { kind: "tests", ok: true, output: "1 passed" } };
  const backend = { request: async <T>(method: string, params: object, context: unknown) => {
    assert.equal(method, "tests.run"); assert.deepEqual(params, { trusted: true });
    assert.deepEqual(context, identity); return result as T;
  } };
  assert.deepEqual(await session.operate(backend, "tests.run", { trusted: true }, {}), result);
  assert.deepEqual(session.data, data); assert.equal(session.model, model);
  assert.deepEqual(session.identity.context, identity); assert.ok(logs.includes(result.message));
  await assert.rejects(session.operate({ request: async () => { throw new BackendError("test_failed", "assertion failed"); } },
    "tests.run", { trusted: true }, {}), /test_failed/);
  assert.deepEqual(await session.operate(backend, "tests.run", { trusted: true }, {}), result);
  let finish!: (value: unknown) => void;
  const pending = session.operate({ request: async <T>() => await new Promise<unknown>(resolve => { finish = resolve; }) as T },
    "tests.run", { trusted: true }, {});
  session.reset(); finish(result);
  assert.equal(await pending, undefined); assert.equal(session.data, undefined);
});
