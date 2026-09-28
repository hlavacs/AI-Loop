import * as assert from "node:assert/strict";
import * as vscode from "vscode";
import { join } from "node:path";
import type { IntegrationTestApi } from "../../extension";

export type CallHooks = NonNullable<ReturnType<IntegrationTestApi["callView"]>>;
export const workspace = process.env.ICODA_TEST_WORKSPACE!;
export const report = process.env.ICODA_TEST_REPORT!;
export const pause = (milliseconds: number) => new Promise<void>(done => setTimeout(done, milliseconds));
export const command = (name: string, ...args: unknown[]) => vscode.commands.executeCommand(name, ...args);

export async function until<T>(label: string, read: () => T | undefined | false): Promise<T> {
  const end = Date.now() + 15_000;
  while (Date.now() < end) {
    const value = read();
    if (value) return value;
    await pause(50);
  }
  throw new Error(`Timed out waiting for ${label}`);
}

export async function activate(): Promise<IntegrationTestApi> {
  const extension = vscode.extensions.all.find(item => item.packageJSON.name === "icoda");
  assert.ok(extension, "ICODA is installed in the Development Host");
  const api = await extension.activate() as IntegrationTestApi;
  assert.equal(extension.isActive, true);
  assert.ok(api?.snapshot, "test-only extension exports are available");
  const registered = await vscode.commands.getCommands(true);
  for (const item of extension.packageJSON.contributes.commands as { command: string }[]) {
    assert.ok(registered.includes(item.command), `${item.command} is registered`);
  }
  assert.equal(api.snapshot().backendStarted, false, "activation does not start Python");
  return api;
}

export async function callView(api: IntegrationTestApi): Promise<CallHooks> {
  await command("icoda.showCallView");
  return until("visible, active, loaded Call View", () => {
    const hooks = api.callView();
    const state = hooks?.snapshot();
    return state?.active && state.visible && state.graph?.nodes.length && !state.loading ? hooks : undefined;
  });
}

export async function message(hooks: CallHooks, action: { type: string; usr?: string }): Promise<void> {
  await hooks.dispatch({ ...action, version: hooks.snapshot().version });
}

export async function assertEditor(name: string, line: number, file = "main.py"): Promise<void> {
  // ICODA preserves graph focus. Focus the already-revealed editor, never reveal a file in the test.
  const visible = await until("revealed source editor", () => vscode.window.visibleTextEditors.find(editor =>
    editor.document.uri.fsPath === join(workspace, file) && editor.selection.active.line === line - 1));
  assert.equal(visible.viewColumn, vscode.ViewColumn.Two);
  await command("workbench.action.focusSecondEditorGroup");
  const active = await until("active source editor", () => vscode.window.activeTextEditor);
  assert.equal(active.document.uri.toString(), vscode.Uri.file(join(workspace, file)).toString());
  assert.equal(active.selection.active.line + 1, line);
  const declaration = file.endsWith(".cpp") ? `^(?:int|void) ${name}\\(` : `^def ${name}\\(`;
  assert.match(active.document.lineAt(active.selection.active.line).text, new RegExp(declaration));
}

export async function assertCall(hooks: CallHooks, name: string, line: number, position: number,
  file = "main.py", usr = `python:main:${name}`): Promise<void> {
  const state = hooks.snapshot();
  assert.equal(state.trace?.currentEntityUsr, usr);
  assert.equal(state.trace?.position, position);
  assert.equal(state.trace?.source?.line, line);
  assert.equal(state.selected, usr);
  assert.equal(state.graph?.nodes.find(node => node.selected)?.usr, state.selected);
  await assertEditor(name, line, file);
}

/** Observe the real command/client/progress boundary; only the cancellation input is supplied. */
export async function observeLifecycle<T>(action: (seen: LifecycleObservation) => Promise<T>): Promise<T> {
  // helpers.js also runs in the standalone VSIX harness, without development modules beside it.
  const { BackendClient } = require("../../backendClient") as typeof import("../../backendClient");
  const request = BackendClient.prototype.request, progress = vscode.window.withProgress;
  const seen: LifecycleObservation = { requests: [], progress: [], messages: [] };
  const information = vscode.window.showInformationMessage;
  BackendClient.prototype.request = async function<R>(...args: Parameters<typeof request>): Promise<R> {
    const entry: LifecycleRequest = { client: this, method: args[0], params: args[1] ?? {}, context: args[2], settled: false };
    seen.requests.push(entry);
    try { entry.result = await request.apply(this, args); return entry.result as R; }
    catch (error) { entry.error = error as Error; throw error; }
    finally { entry.settled = true; }
  };
  vscode.window.withProgress = (<R>(options: vscode.ProgressOptions,
    task: (progress: vscode.Progress<{ message?: string; increment?: number }>, token: vscode.CancellationToken) => Thenable<R>) => {
    return progress(options, async (nativeProgress, nativeToken) => {
      const source = new vscode.CancellationTokenSource();
      const listener = nativeToken.onCancellationRequested(() => source.cancel());
      if (nativeToken.isCancellationRequested) source.cancel();
      const entry = { title: options.title, ended: false, cancel: () => source.cancel() };
      seen.progress.push(entry);
      try { return await task(nativeProgress, source.token); }
      finally { entry.ended = true; listener.dispose(); source.dispose(); }
    });
  }) as typeof progress;
  vscode.window.showInformationMessage = ((text: string) => {
    seen.messages.push(text); return information(text);
  }) as typeof information;
  try { return await action(seen); }
  finally {
    BackendClient.prototype.request = request;
    vscode.window.withProgress = progress;
    vscode.window.showInformationMessage = information;
  }
}

export interface LifecycleRequest {
  client: import("../../backendClient").BackendClient;
  method: string;
  params: object;
  context?: import("../../protocol").SessionContext;
  settled: boolean;
  result?: unknown;
  error?: Error;
}

export interface LifecycleObservation {
  requests: LifecycleRequest[];
  progress: { title?: string; ended: boolean; cancel: () => void }[];
  messages: string[];
}
