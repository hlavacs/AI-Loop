import * as assert from "node:assert/strict";
import * as vscode from "vscode";
import { copyFile, mkdir, readFile, rename, rm, stat, symlink, writeFile } from "node:fs/promises";
import { basename, delimiter, dirname, join, relative } from "node:path";
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { BackendClient } from "../../backendClient";
import { BackendError, ResolvedSource, SessionContext, TargetOperationResult } from "../../protocol";
import type { ToolchainInspection } from "../../toolchain";
import type { ProviderInventory } from "../../specificationData";
import type { WorkflowStatus } from "../../workflowData";
import type { ProposalReview } from "../../proposalData";
import type { EntityChoice } from "../../sourceNavigation";
import type { IntegrationTestApi } from "../../extension";
import type { PlaybackState } from "../../tracePlayback";
import type { CallHooks, LifecycleObservation, LifecycleRequest } from "./helpers";
import { existsSync } from "node:fs";
import { slowAnalysis, writeServiceShim } from "../slowBackend";
import { deactivate } from "../../extension";
import { activate, assertCall, assertEditor, callView, command, message, observeLifecycle, pause, report, until, workspace } from "./helpers";
import { screenshots } from "./screenshots";
import { untrustedSuite } from "./untrusted";

interface Result { name: string; passed: boolean; error?: string; skipped?: string }
class PrerequisiteSkip extends Error {}
const results: Result[] = [];
let api: IntegrationTestApi;

async function check(name: string, action: () => Promise<void>): Promise<void> {
  let timer: NodeJS.Timeout | undefined;
  try {
    await Promise.race([action(), new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error(`Timed out: ${name}`)), 60_000);
    })]);
    results.push({ name, passed: true });
    console.log(`PASS ${name}`);
  } catch (error) {
    if (error instanceof PrerequisiteSkip) {
      results.push({ name, passed: false, skipped: error.message });
      console.log(`SKIP ${name}: ${error.message}`);
      return;
    }
    results.push({ name, passed: false, error: error instanceof Error ? error.stack : String(error) });
    throw error;
  } finally { clearTimeout(timer); }
}

async function analyse(): Promise<void> {
  assert.equal(vscode.workspace.isTrusted, true);
  assert.deepEqual(vscode.workspace.workspaceFolders?.map(folder => folder.uri.fsPath), [workspace]);
  await command("icoda.openProject");
  assert.equal(api.snapshot().project?.root, workspace);
  await command("icoda.analyseProject");
  await command("icoda.project.focus");
  const state = api.snapshot();
  assert.equal(state.project?.modelState, "fresh");
  assert.equal(state.model?.entities.length, 7);
  assert.equal(state.model?.edges.filter(edge => edge.kind === "calls").length, 5);
  assert.deepEqual(state.model?.entities.map(entity => entity.usr).sort(),
    ["python:library:unused", ...["main", "A", "B", "C", "D", "E"].map(name => `python:main:${name}`)].sort());
  const tree = state.tree[0];
  assert.equal(tree?.label, workspace);
  assert.equal(tree?.children?.find(node => node.id === "model")?.label, "Model: fresh");
  assert.equal(tree?.children?.find(node => node.id === "entities")?.label, "Entities: 7");
  assert.equal(tree?.children?.find(node => node.id === "edges")?.label, `Edges: ${state.model?.edges.length}`);
}

async function reveal(): Promise<void> {
  await command("workbench.action.closePanel");
  const hooks = await callView(api);
  assert.ok(vscode.window.tabGroups.all.some(group => group.tabs.some(tab => tab.label === "ICODA Call View")));
  assert.equal(hooks.snapshot().graph?.nodes.length, 6);
  await message(hooks, { type: "select", usr: "python:main:B" });
  assert.equal(hooks.snapshot().selected, "python:main:B");
  await assertEditor("B", 14);
  await hooks.loadTrace(join(workspace, "calls.tsv"));
  assert.equal(hooks.snapshot().trace?.total, 6);
  assert.equal(hooks.snapshot().trace?.position, 0);
}

interface SourceObservation {
  requests: { method: string; params: object; result?: unknown; error?: BackendError }[];
  warnings: string[];
  choices: string[][];
  entityPicks: number;
}

/** Only QuickPick is answered by the test; requests, notifications and editor operations stay real. */
async function observeSources(name: string, choose: ((files: string[]) => string | undefined) | undefined,
  action: (seen: SourceObservation) => Promise<void>): Promise<void> {
  const seen: SourceObservation = { requests: [], warnings: [], choices: [], entityPicks: 0 };
  const request = BackendClient.prototype.request, picker = vscode.window.showQuickPick;
  const warning = vscode.window.showWarningMessage;
  const openedViews: string[] = [], terminals: string[] = [];
  const listeners = [
    vscode.window.tabGroups.onDidChangeTabs(event => {
      for (const tab of event.opened) {
        if (tab.input instanceof vscode.TabInputWebview) openedViews.push(tab.label);
      }
    }),
    vscode.window.onDidOpenTerminal(terminal => terminals.push(terminal.name)),
  ];
  BackendClient.prototype.request = async function<T>(...args: Parameters<BackendClient["request"]>): Promise<T> {
    const entry: SourceObservation["requests"][number] = { method: args[0], params: args[1] ?? {} };
    seen.requests.push(entry);
    try { entry.result = await request.apply(this, args); return entry.result as T; }
    catch (error) { if (error instanceof BackendError) entry.error = error; throw error; }
  };
  vscode.window.showWarningMessage = ((text: string) => {
    seen.warnings.push(text);
    return warning(text);
  }) as typeof warning;
  vscode.window.showQuickPick = (async (items: readonly string[] | readonly EntityChoice[], options: vscode.QuickPickOptions) => {
    if (options.placeHolder === "Go to an ICODA file, class or function") {
      seen.entityPicks++;
      const entity = (items as readonly EntityChoice[]).find(item => item.ref.usr === "python:main:B");
      assert.ok(entity, "the registered command offers the cached B entity");
      return entity;
    }
    assert.equal(options.placeHolder, "Choose the matching source file", "no provider or recovery picker");
    const files = [...items] as string[];
    seen.choices.push(files);
    assert.ok(choose, "an unambiguous or missing source must not offer a file choice");
    return choose(files);
  }) as typeof picker;
  try {
    await action(seen);
    assert.ok(seen.requests.length > 0, "navigation reached the real Python service");
    assert.ok(seen.requests.every(item => item.method === "source.resolve"),
      `no provider, Binary, Prompt or recovery request: ${seen.requests.map(item => item.method)}`);
    assert.deepEqual(openedViews, [], "navigation opens no Prompt or recovery webview");
    assert.deepEqual(terminals, [], "navigation starts no provider terminal");
  } finally {
    BackendClient.prototype.request = request;
    vscode.window.showQuickPick = picker;
    vscode.window.showWarningMessage = warning;
    for (const listener of listeners) listener.dispose();
    await writeFile(join(report, `${name}.json`), JSON.stringify({ ...seen, openedViews, terminals,
      requests: seen.requests.map(item => ({ ...item, error: item.error && {
        code: item.error.code, message: item.error.message, details: item.error.details,
      } })), callView: api.callView()?.snapshot(),
      editor: { uri: vscode.window.activeTextEditor?.document.uri.toString(),
        line: (vscode.window.activeTextEditor?.selection.active.line ?? -1) + 1 },
    }, null, 2));
  }
}

function assertSourceSelection(hooks: CallHooks, name = "B"): void {
  const state = hooks.snapshot();
  assert.equal(state.selected, `python:main:${name}`);
  assert.deepEqual(state.graph?.nodes.filter(node => node.selected).map(node => node.usr), [state.selected]);
  assert.equal(state.loading, false);
}

function assertResolved(seen: SourceObservation, file: string, line: number): void {
  const response = seen.requests.at(-1)!;
  assert.equal(response.error, undefined);
  const result = response.result as ResolvedSource;
  assert.equal(result.file, file);
  assert.equal(result.path, join(workspace, file));
  assert.equal(result.line, line);
}

function assertSourceError(seen: SourceObservation, code: string, message: string): BackendError {
  const error = seen.requests.at(-1)?.error;
  assert.ok(error instanceof BackendError);
  assert.equal(error.code, code);
  assert.equal(error.message, `${code}: ${message}`);
  assert.equal(error.details.file, "main.py");
  assert.equal(error.details.line, 14);
  assert.equal(error.details.sourceRootId, api.callView()?.snapshot().graph?.nodes[0]?.sourceRootId);
  return error;
}

async function sourceSetup(): Promise<CallHooks> {
  const hooks = await callView(api);
  await message(hooks, { type: "select", usr: "python:main:B" });
  await assertEditor("B", 14);
  assert.equal(api.snapshot().model?.entities.find(entity => entity.usr === "python:main:B")?.file, "main.py");
  return hooks;
}

async function movedSource(): Promise<void> {
  const hooks = await sourceSetup();
  const directory = join(workspace, "relocated");
  const file = "relocated/main.py";
  await mkdir(directory);
  try {
    await rename(join(workspace, "main.py"), join(workspace, file));
    await observeSources("at03-moved", undefined, async seen => {
      await command("icoda.revealEntity");
      assertResolved(seen, file, 14);
      assertSourceSelection(hooks);
      await assertEditor("B", 14, file);
      await callView(api);
      await message(hooks, { type: "select", usr: "python:main:C" });
      assertResolved(seen, file, 18);
      assertSourceSelection(hooks, "C");
      await assertEditor("C", 18, file);
      assert.equal(seen.entityPicks, 1);
      assert.equal(seen.requests.length, 2);
      assert.deepEqual(seen.warnings, []);
      assert.deepEqual(seen.choices, []);
    });
  } finally {
    await rename(join(workspace, file), join(workspace, "main.py"));
    await rm(directory, { recursive: true, force: true });
  }
}

async function ambiguousSource(): Promise<void> {
  const hooks = await sourceSetup();
  const choices = ["one/main.py", "two/main.py"];
  for (const directory of ["one", "two"]) await mkdir(join(workspace, directory));
  try {
    await copyFile(join(workspace, "main.py"), join(workspace, choices[1]!));
    await rename(join(workspace, "main.py"), join(workspace, choices[0]!));
    let choice = 0;
    await observeSources("at04-ambiguous", files => {
      assert.deepEqual(files, choices, "equally plausible files are offered without guessing");
      assertSourceSelection(hooks);
      const previous = vscode.window.visibleTextEditors.find(editor => editor.viewColumn === vscode.ViewColumn.Two);
      assert.equal(previous?.document.uri.fsPath, join(workspace, "library.py"));
      assert.equal(previous?.selection.active.line, 0);
      // Choose the second item through the command, then the first through Call View.
      return choices[choice++ === 0 ? 1 : 0];
    }, async seen => {
      for (const [index, file] of [choices[1]!, choices[0]!].entries()) {
        await showLibrary();
        if (index === 0) await command("icoda.revealEntity");
        else {
          await callView(api);
          await message(hooks, { type: "select", usr: "python:main:B" });
        }
        const failed = { ...seen, requests: seen.requests.slice(0, -1) };
        const error = assertSourceError(failed, "source_ambiguous", "Choose among equally ranked source files.");
        assert.deepEqual(error.details.candidates, choices);
        assert.deepEqual(seen.requests.at(-1)?.params, { sourceRootId: error.details.sourceRootId, file, line: 14 });
        assertResolved(seen, file, 14);
        assertSourceSelection(hooks);
        await assertEditor("B", 14, file);
      }
      assert.equal(seen.entityPicks, 1);
      assert.equal(seen.requests.length, 4, "each choice is revalidated by the service");
      assert.deepEqual(seen.choices, [choices, choices]);
      assert.deepEqual(seen.warnings, []);
    });
  } finally {
    await rename(join(workspace, choices[0]!), join(workspace, "main.py"));
    for (const directory of ["one", "two"]) await rm(join(workspace, directory), { recursive: true, force: true });
  }
}

async function showLibrary(): Promise<vscode.TextEditor> {
  const document = await vscode.workspace.openTextDocument(join(workspace, "library.py"));
  return vscode.window.showTextDocument(document, { viewColumn: vscode.ViewColumn.Two,
    preview: false, selection: new vscode.Range(0, 0, 0, 0) });
}

async function missingSource(boundary = false): Promise<void> {
  const hooks = await sourceSetup();
  const source = join(workspace, "main.py"), original = await readFile(source);
  // This sibling shares the project's path prefix, and the in-root symlink has the wanted basename.
  const outside = `${workspace}-outside`, linked = join(workspace, "linked");
  try {
    if (boundary) {
      await mkdir(outside);
      await rename(source, join(outside, "main.py"));
      await mkdir(linked);
      await symlink(join(outside, "main.py"), join(linked, "main.py"), "file");
    } else await rm(source);
    const editor = await showLibrary();
    const before = editor.document.getText();
    await observeSources(boundary ? "at04-boundary" : "at04-missing", undefined, async seen => {
      for (const navigate of [() => command("icoda.revealEntity"), async () => {
        await callView(api);
        await message(hooks, { type: "select", usr: "python:main:B" });
      }]) {
        await navigate();
        assertSourceError(seen, "source_missing", "Source file was not found inside the project.");
        assert.equal(seen.warnings.at(-1), "ICODA source location: The source file could not be found in this project. "
          + "Source file was not found inside the project.");
        assertSourceSelection(hooks);
        await assertEditor("unused", 1, "library.py");
        assert.equal(vscode.window.activeTextEditor?.document, editor.document);
        assert.equal(editor.document.getText(), before);
        assert.ok(vscode.window.visibleTextEditors.every(item => item.document.uri.fsPath !== join(outside, "main.py")));
      }
      assert.equal(seen.requests.length, 2);
      assert.equal(seen.warnings.length, 2);
      assert.equal(seen.entityPicks, 1);
      assert.deepEqual(seen.choices, []);
      // Restore source and select another node through the same live panel; no restart/reanalysis.
      await writeFile(source, original);
      await callView(api);
      await message(hooks, { type: "select", usr: "python:main:C" });
      assertSourceSelection(hooks, "C");
      assertResolved(seen, "main.py", 18);
      await assertEditor("C", 18);
    });
  } finally {
    await writeFile(source, original);
    if (boundary) {
      await rm(linked, { recursive: true, force: true });
      await rm(outside, { recursive: true, force: true });
    }
  }
}

async function dirtySourceBuffer(): Promise<void> {
  const hooks = await sourceSetup();
  const editor = await showLibrary(), document = editor.document;
  const original = await readFile(document.uri.fsPath, "utf8");
  const text = `${original}\n# unsaved AT04 buffer must survive source navigation\n`;
  const directory = join(workspace, "dirty-relocated"), file = "dirty-relocated/main.py";
  await mkdir(directory);
  try {
    assert.ok(await editor.edit(edit => edit.insert(document.positionAt(original.length), text.slice(original.length))));
    assert.equal(document.isDirty, true);
    await rename(join(workspace, "main.py"), join(workspace, file));
    await observeSources("at04-dirty-buffer", undefined, async seen => {
      await command("icoda.revealEntity");
      assertResolved(seen, file, 14);
      assertSourceSelection(hooks);
      await assertEditor("B", 14, file);
      await callView(api);
      await message(hooks, { type: "select", usr: "python:main:C" });
      assertResolved(seen, file, 18);
      assertSourceSelection(hooks, "C");
      await assertEditor("C", 18, file);
      assert.ok(vscode.workspace.textDocuments.includes(document));
      assert.equal(document.isDirty, true);
      assert.equal(document.getText(), text);
      assert.equal(await readFile(document.uri.fsPath, "utf8"), original);
      assert.deepEqual(seen.warnings, []);
      assert.deepEqual(seen.choices, []);
      assert.equal(seen.requests.length, 2);
      assert.equal(seen.entityPicks, 1);
    });
  } finally {
    await rename(join(workspace, file), join(workspace, "main.py"));
    await rm(directory, { recursive: true, force: true });
    await showLibrary();
    await command("workbench.action.files.revert"); // Only discard this test's own temporary-buffer edit.
  }
}

async function step(action: string, name: string, line: number, position: number): Promise<void> {
  const hooks = await callView(api);
  await command("icoda.traceReset");
  for (const caller of ["main", "A", "B"]) {
    await command("icoda.traceInto");
    assert.equal(hooks.snapshot().trace?.currentEntityUsr, `python:main:${caller}`);
  }
  await assertCall(hooks, "B", 14, 3);
  await callView(api);
  const before = hooks.snapshot();
  await command(`icoda.trace${action}`);
  await assertCall(hooks, name, line, position);
  assert.equal(hooks.snapshot().root, before.root);
  assert.deepEqual(hooks.snapshot().viewport, before.viewport);
}

async function resetPrevious(): Promise<void> {
  const hooks = await callView(api);
  await command("icoda.traceReset");
  assert.equal(hooks.snapshot().trace?.position, 0);
  assert.equal(hooks.snapshot().selected, null);
  assert.equal(hooks.snapshot().trace?.availability.previous, false);
  await message(hooks, { type: "traceSeek", usr: "python:main:D" });
  await assertCall(hooks, "D", 23, 5);
  await callView(api);
  await command("icoda.tracePrevious");
  await assertCall(hooks, "C", 18, 4);
  await callView(api);
  await command("icoda.traceReset");
  assert.equal(hooks.snapshot().trace?.position, 0);
  assert.equal(hooks.snapshot().trace?.currentEntityUsr, null);
  assert.equal(hooks.snapshot().selected, null);
  assert.deepEqual(hooks.snapshot().trace?.callerCounts, {});
  await command("icoda.traceInto");
  await assertCall(hooks, "main", 4, 1);
}

interface TraceStop {
  name: string; line: number; position: number; callers: Record<string, number>;
  enabled: (keyof PlaybackState["availability"])[]; repeat?: number;
}

function assertAvailability(hooks: CallHooks, enabled: TraceStop["enabled"]): void {
  assert.deepEqual(hooks.snapshot().trace?.availability, {
    into: enabled.includes("into"), over: enabled.includes("over"), out: enabled.includes("out"),
    previous: enabled.includes("previous"), reset: enabled.includes("reset"),
  });
}

function assertUnselected(hooks: CallHooks, total: number): void {
  const state = hooks.snapshot();
  assert.equal(state.trace?.total, total);
  assert.equal(state.trace?.position, 0);
  assert.equal(state.trace?.currentEntityUsr, null);
  assert.equal(state.trace?.currentCall, null);
  assert.equal(state.trace?.source, null);
  assert.equal(state.selected, null);
  assert.deepEqual(state.graph?.nodes.filter(node => node.selected), []);
  assert.equal(state.trace?.repeatCount, 0);
  assert.deepEqual(state.trace?.callerCounts, {});
  assertAvailability(hooks, total ? ["into", "over"] : []);
}

async function loadPlayback(file: string, total: number, into = 0): Promise<CallHooks> {
  const hooks = await callView(api);
  await hooks.loadTrace(join(workspace, file));
  assertUnselected(hooks, total);
  for (let index = 0; index < into; index++) await command("icoda.traceInto");
  return hooks;
}

async function playbackCommand(action: string): Promise<CallHooks> {
  const hooks = await callView(api); // assertCall focuses the editor; commands are scoped to the active panel.
  await command(`icoda.trace${action}`);
  return hooks;
}

async function assertPlayback(hooks: CallHooks, expected: TraceStop,
  source?: { file: string; usrs: Record<string, string> }): Promise<void> {
  const trace = hooks.snapshot().trace;
  assert.equal(trace?.repeatCount, expected.repeat ?? 1);
  assert.deepEqual(trace?.callerCounts, Object.fromEntries(Object.entries(expected.callers)
    .map(([name, count]) => [source ? source.usrs[name] : `python:main:${name}`, count])));
  assertAvailability(hooks, expected.enabled);
  await assertCall(hooks, expected.name, expected.line, expected.position, source?.file, source?.usrs[expected.name]);
}

async function leafPlayback(): Promise<void> {
  const hooks = await loadPlayback("calls.tsv", 6, 4);
  await assertPlayback(hooks, { name: "C", line: 18, position: 4, callers: { B: 1 },
    enabled: ["into", "over", "out", "previous", "reset"] });
  await assertPlayback(await playbackCommand("Into"), { name: "D", line: 23, position: 5, callers: { A: 1 },
    enabled: ["into", "over", "out", "previous", "reset"] });
  assert.equal(hooks.snapshot().trace?.currentCall?.sequence, 6, "C and B returns are not stops");
  await assertPlayback(await playbackCommand("Into"), { name: "E", line: 27, position: 6, callers: { main: 1 },
    enabled: ["previous", "reset"] });
}

async function repeatPlayback(): Promise<void> {
  const hooks = await loadPlayback("repeats.tsv", 5, 3);
  const repeated: TraceStop = { name: "B", line: 14, position: 3, repeat: 3, callers: { A: 3 },
    enabled: ["into", "over", "out", "previous", "reset"] };
  await assertPlayback(hooks, repeated);
  const before = hooks.snapshot();
  const edge = before.graph?.edges.find(item => item.source === "python:main:A" && item.target === "python:main:B");
  assert.ok(edge && "repeatCount" in edge);
  assert.equal(edge.repeatCount, 3);
  assert.match(before.trace!.status, /3 consecutive calls/);
  await assertPlayback(await playbackCommand("Over"), { name: "D", line: 23, position: 4, callers: { A: 1 },
    enabled: ["into", "over", "out", "previous", "reset"] });
  await assertPlayback(await playbackCommand("Previous"), repeated);
  assert.deepEqual(hooks.snapshot().trace, before.trace);
  assert.deepEqual(hooks.snapshot().graph, before.graph, "Previous restores the repeat-edge annotation");
  await assertPlayback(await playbackCommand("Into"), { name: "D", line: 23, position: 4, callers: { A: 1 },
    enabled: ["into", "over", "out", "previous", "reset"] });
  await assertPlayback(await playbackCommand("Previous"), repeated);
  await assertPlayback(await playbackCommand("Out"), { name: "E", line: 27, position: 5, callers: { main: 1 },
    enabled: ["previous", "reset"] });
  await playbackCommand("Reset");
  assertUnselected(hooks, 5);
  assert.ok(hooks.snapshot().graph?.edges.every(item => "repeatCount" in item && item.repeatCount === 0));
  await assertEditor("E", 27);
}

async function recursivePlayback(): Promise<void> {
  // main → outer A → B → inner A → C; B then calls E, outer A calls D, main calls E.
  const hooks = await loadPlayback("recursion.tsv", 8, 4);
  const inner: TraceStop = { name: "A", line: 9, position: 4, callers: { B: 1 },
    enabled: ["into", "over", "out", "previous", "reset"] };
  await assertPlayback(hooks, inner);
  assert.equal(hooks.snapshot().trace?.currentCall?.depth, 3);
  assert.equal(hooks.snapshot().trace?.currentCall?.sequence, 3);
  await assertPlayback(await playbackCommand("Over"), { name: "E", line: 27, position: 6, callers: { B: 1 },
    enabled: ["into", "over", "out", "previous", "reset"] });
  await assertPlayback(await playbackCommand("Previous"), { name: "C", line: 18, position: 5, callers: { A: 1 },
    enabled: ["into", "over", "out", "previous", "reset"] });
  await assertPlayback(await playbackCommand("Previous"), inner);
  await assertPlayback(await playbackCommand("Out"), { name: "D", line: 23, position: 7, callers: { A: 1 },
    enabled: ["into", "over", "out", "previous", "reset"] });
  await playbackCommand("Reset");
  assertUnselected(hooks, 8);
  await command("icoda.traceInto");
  await command("icoda.traceInto");
  await assertPlayback(hooks, { name: "A", line: 9, position: 2, callers: { main: 1 },
    enabled: ["into", "over", "previous", "reset"] });
  assert.equal(hooks.snapshot().trace?.currentCall?.depth, 1);
  await assertPlayback(await playbackCommand("Over"), { name: "E", line: 27, position: 8, callers: { main: 1 },
    enabled: ["previous", "reset"] });
}

async function unresolvedPlayback(): Promise<void> {
  const hooks = await loadPlayback("unresolved-only.tsv", 0);
  assert.match(hooks.snapshot().trace!.status, /No project calls resolved/);
  await loadPlayback("unresolved.tsv", 4, 2);
  const child: TraceStop = { name: "B", line: 14, position: 2, callers: {},
    enabled: ["into", "over", "out", "previous", "reset"] };
  await assertPlayback(hooks, child);
  assert.equal(hooks.snapshot().trace?.currentCall?.sequence, 2);
  await assertPlayback(await playbackCommand("Into"), { name: "C", line: 18, position: 3, callers: {},
    enabled: ["into", "over", "out", "previous", "reset"] });
  assert.equal(hooks.snapshot().trace?.currentCall?.sequence, 4);
  await assertPlayback(await playbackCommand("Previous"), child);
  // Out must retain the unresolved parent's invocation/return even though it has no visible stop.
  await assertPlayback(await playbackCommand("Out"), { name: "E", line: 27, position: 4, callers: { main: 1 },
    enabled: ["previous", "reset"] });
  assert.ok(hooks.snapshot().graph?.nodes.every(node => !node.usr.includes("unknown")));
}

async function interleavedPlayback(): Promise<void> {
  const destinations = [
    ["Into", { name: "C", line: 18, position: 4, callers: {}, enabled: ["into", "over", "previous", "reset"] }, "thread-2"],
    ["Over", { name: "D", line: 23, position: 8, callers: { A: 1 }, enabled: ["into", "over", "out", "previous", "reset"] }, "thread-1"],
    ["Out", { name: "E", line: 27, position: 9, callers: { main: 1 }, enabled: ["previous", "reset"] }, "thread-1"],
  ] satisfies [string, TraceStop, string][];
  const hooks = await loadPlayback("interleaved.tsv", 9);
  for (const [action, destination, thread] of destinations) {
    await playbackCommand("Reset");
    assertUnselected(hooks, 9);
    for (let index = 0; index < 3; index++) await command("icoda.traceInto");
    await assertPlayback(hooks, { name: "B", line: 14, position: 3, callers: { A: 1 },
      enabled: ["into", "over", "out", "previous", "reset"] });
    assert.equal(hooks.snapshot().trace?.currentCall?.threadId, "thread-1");
    await assertPlayback(await playbackCommand(action), destination);
    assert.equal(hooks.snapshot().trace?.currentCall?.threadId, thread);
    if (action === "Into") {
      await assertPlayback(await playbackCommand("Into"), { name: "D", line: 23, position: 5, callers: { C: 1 },
        enabled: ["into", "over", "out", "previous", "reset"] });
      assert.equal(hooks.snapshot().trace?.currentCall?.threadId, "thread-2");
      await assertPlayback(await playbackCommand("Into"), { name: "C", line: 18, position: 6, callers: { B: 1 },
        enabled: ["into", "over", "out", "previous", "reset"] });
      assert.equal(hooks.snapshot().trace?.currentCall?.threadId, "thread-1");
    }
  }
}

async function validReload(): Promise<void> {
  const previousId = api.callView()?.snapshot().trace?.traceId;
  const hooks = await loadPlayback("calls.tsv", 6);
  assert.notEqual(hooks.snapshot().trace?.traceId, previousId);
  assert.doesNotMatch(hooks.snapshot().message, /Trace playback:/);
  await assertPlayback(await playbackCommand("Into"), { name: "main", line: 4, position: 1, callers: {},
    enabled: ["into", "previous", "reset"] });
}

async function emptyPlayback(): Promise<void> {
  const hooks = await loadPlayback("calls.tsv", 6, 3);
  await assertPlayback(hooks, { name: "B", line: 14, position: 3, callers: { A: 1 },
    enabled: ["into", "over", "out", "previous", "reset"] });
  await loadPlayback("empty.tsv", 0);
  assert.match(hooks.snapshot().trace!.status, /No project calls resolved/);
  for (const action of ["Into", "Over", "Out", "Previous", "Reset"]) {
    await playbackCommand(action);
    assertUnselected(hooks, 0);
    await assertEditor("B", 14);
  }
  await validReload();
}

async function malformedPlayback(): Promise<void> {
  const hooks = await loadPlayback("calls.tsv", 6, 6);
  const last: TraceStop = { name: "E", line: 27, position: 6, callers: { main: 1 }, enabled: ["previous", "reset"] };
  await assertPlayback(hooks, last);
  const before = hooks.snapshot();
  await callView(api);
  await hooks.loadTrace(join(workspace, "malformed.tsv"));
  // This explanation is mapped from the real service's typed invalid_trace error at the UI boundary.
  assert.match(hooks.snapshot().message, /^Trace playback: The trace could not be loaded\./);
  assert.match(hooks.snapshot().message, /malformed\.tsv:2: expected 8 tab-separated fields/);
  assert.deepEqual(hooks.snapshot().trace, before.trace, "a failed load retains the usable recording");
  assert.deepEqual(hooks.snapshot().graph, before.graph);
  for (const action of ["Into", "Over", "Out"]) await assertPlayback(await playbackCommand(action), last);
  await validReload();
}

async function truncatedPlayback(): Promise<void> {
  // B returns, but A's return is absent before an unrelated depth-1 E entry.
  const hooks = await loadPlayback("truncated.tsv", 4, 3);
  const incomplete: TraceStop = { name: "B", line: 14, position: 3, callers: { A: 1 },
    enabled: ["into", "previous", "reset"] };
  await assertPlayback(hooks, incomplete);
  const before = hooks.snapshot().trace;
  for (const action of ["Over", "Out"]) {
    await assertPlayback(await playbackCommand(action), incomplete);
    assert.deepEqual(hooks.snapshot().trace, before, "missing parent return cannot invent a scope exit");
  }
  await assertPlayback(await playbackCommand("Into"), { name: "E", line: 27, position: 4, callers: { main: 1 },
    enabled: ["previous", "reset"] });
  await validReload();
}

async function exhaustedPlayback(): Promise<void> {
  const hooks = await loadPlayback("calls.tsv", 6, 6);
  const last: TraceStop = { name: "E", line: 27, position: 6, callers: { main: 1 }, enabled: ["previous", "reset"] };
  await assertPlayback(hooks, last);
  const before = hooks.snapshot().trace;
  for (const action of ["Into", "Over", "Out"]) {
    await assertPlayback(await playbackCommand(action), last);
    assert.deepEqual(hooks.snapshot().trace, before);
  }
  await assertPlayback(await playbackCommand("Previous"), { name: "D", line: 23, position: 5, callers: { A: 1 },
    enabled: ["into", "over", "out", "previous", "reset"] });
  await assertPlayback(await playbackCommand("Into"), last);
  await playbackCommand("Reset");
  assertUnselected(hooks, 6);
  await assertEditor("E", 27);
  await validReload();
}

async function recordExecutable(): Promise<void> {
  assert.equal(vscode.workspace.isTrusted, true);
  assert.deepEqual(vscode.workspace.workspaceFolders?.map(folder => folder.uri.fsPath), [workspace]);
  // Observe real replies; only answer the native target and recording-load choices.
  const request = BackendClient.prototype.request, picker = vscode.window.showQuickPick;
  const information = vscode.window.showInformationMessage;
  const requests: { method: string; params: object; result?: unknown; error?: string }[] = [];
  const artifacts: Record<string, unknown> = {};
  const versions: Record<string, string> = {};
  const stops: unknown[] = [];
  let targetPicks = 0, recordingOffers = 0;
  BackendClient.prototype.request = async function<T>(...args: Parameters<BackendClient["request"]>): Promise<T> {
    const entry: typeof requests[number] = { method: args[0], params: args[1] ?? {} };
    requests.push(entry);
    try { entry.result = await request.apply(this, args); return entry.result as T; }
    catch (error) { entry.error = String(error); throw error; }
  };
  const reply = <T>(method: string): T => {
    const entry = requests.filter(item => item.method === method).at(-1);
    assert.ok(entry?.result, `${method} returned a real result: ${entry?.error ?? "no response"}`);
    return entry.result as T;
  };
  vscode.window.showQuickPick = (async (items: readonly { targetId: string; label: string }[], options: vscode.QuickPickOptions) => {
    assert.equal(options.placeHolder, "Choose the ICODA executable, library or Whole Project");
    const target = api.snapshot().project?.targets.find(item => item.kind === "executable" && item.name === "demo");
    assert.ok(target?.id, "refresh exposed the real CMake executable");
    const choice = items.find(item => item.targetId === target.id);
    assert.ok(choice);
    targetPicks++;
    return choice;
  }) as unknown as typeof picker;
  vscode.window.showInformationMessage = (async (text: string, ...items: string[]) => {
    const recording = reply<TargetOperationResult>("trace.record");
    assert.equal(text, `ICODA: Recorded ${recording.target.label}. ${recording.path}`);
    assert.deepEqual(items, ["Load Trace"]);
    recordingOffers++;
    return "Load Trace";
  }) as unknown as typeof information;
  try {
    await command("icoda.showToolchain");
    const toolchain = reply<ToolchainInspection>("toolchain.inspect");
    // These are the shared core's prerequisites for a new Clang/Ninja build and recording.
    for (const name of ["cmake", "clang", "ninja"]) {
      const tool = toolchain.tools.find(item => item.name === name);
      assert.ok(tool, `shared discovery reports ${name}`);
      if (!tool.path) throw new PrerequisiteSkip(`AT11 requires ${name}; shared toolchain discovery found none. No tools installed.`);
      const result = await promisify(execFile)(tool.path, ["--version"]);
      versions[name] = result.stdout.trim().split("\n")[0]!;
    }
    // Existing-project setup: Refresh Targets requires a configured tree. Keep configuration policy in Python.
    const prepared = await promisify(execFile)(process.env.ICODA_TEST_PYTHON!, ["-c", [
      "import sys",
      "from pathlib import Path",
      "from icoda_core import cmake, process",
      "root = Path(sys.argv[1])",
      "directory, command, environment = cmake.clang_configuration(root)",
      "result = process.run_bounded(command, cwd=root, env=environment)",
      "print(result.stdout + result.stderr)",
      "assert result.ok, 'Fixture configuration failed'",
    ].join("\n"), workspace], { cwd: join(__dirname, "../../../.."), env: { ...process.env, ...toolchain.environment } });
    await writeFile(join(report, "at11-configure.log"), prepared.stdout + prepared.stderr);
    await command("icoda.openProject");
    assert.equal(api.snapshot().project?.root, workspace);
    await command("icoda.analyseProject");
    assert.equal(api.snapshot().project?.modelState, "fresh");
    const usrs: Record<string, string> = {};
    for (const name of ["main", "A", "B", "C", "D", "E"]) {
      const entity = api.snapshot().model?.entities.find(item => item.name === name);
      assert.ok(entity && typeof entity.usr === "string");
      assert.equal(entity.file, "main.cpp");
      usrs[name] = entity.usr;
    }
    await command("icoda.refreshTargets");
    reply("targets.refresh");
    await command("icoda.selectTarget");
    assert.equal(targetPicks, 1);
    const selected = reply<{ targetId: string }>("target.select");
    await command("icoda.buildTarget");
    const built = reply<TargetOperationResult>("build.run");
    assert.equal(built.targetId, selected.targetId);
    assert.equal(built.target.name, "demo");
    assert.ok(built.executable);
    await command("icoda.runTarget");
    assert.equal(reply<TargetOperationResult>("target.run").executable, built.executable);
    const ordinary = dirname(built.executable);
    const paths = [join(ordinary, "CMakeCache.txt"), join(ordinary, "compile_commands.json"), built.executable];
    const snapshot = async () => Promise.all(paths.map(async path => ({ path,
      sha256: createHash("sha256").update(await readFile(path)).digest("hex"),
      mtimeNs: (await stat(path, { bigint: true })).mtimeNs.toString(),
    })));
    artifacts.before = await snapshot();
    await command("workbench.action.closePanel");
    await command("icoda.recordTrace");
    const recording = reply<TargetOperationResult>("trace.record");
    artifacts.after = await snapshot();
    assert.deepEqual(artifacts.after, artifacts.before, "recording preserves ordinary build bytes and modification times");
    assert.equal(recordingOffers, 1);
    assert.equal(recording.targetId, selected.targetId);
    assert.equal(recording.target.name, "demo");
    assert.ok(recording.path && recording.executable);
    assert.notEqual(recording.executable, built.executable);
    const isolated = join(workspace, ".icoda/cache/instrumented-debug-build");
    assert.equal(dirname(recording.executable), isolated);
    assert.notEqual(ordinary, isolated);
    assert.ok((await stat(recording.executable)).size > 0);
    assert.ok((await stat(join(isolated, "CMakeCache.txt"))).size > 0);
    const traceText = await readFile(recording.path, "utf8");
    assert.ok(traceText.length > 100, "a real nonempty recording was produced");
    assert.ok(traceText.includes(recording.executable), "trace events name the recorded executable");
    const loaded = reply<PlaybackState & { path: string; resolvedCalls: number; recordedCalls: number }>("trace.load");
    assert.equal(loaded.path, recording.path);
    assert.equal(loaded.targetId, selected.targetId);
    assert.equal(loaded.resolvedCalls, 6);
    assert.equal(loaded.recordedCalls, 6);
    assert.ok(vscode.window.tabGroups.all.some(group => group.tabs.some(tab =>
      tab.label === `ICODA Trace: demo · ${basename(recording.path!)}`)));
    const hooks = await callView(api);
    assert.equal(hooks.snapshot().trace?.traceId, loaded.traceId);
    assertUnselected(hooks, 6);
    // Reload the produced file through the shared Load Trace helper as well as the recording offer.
    await loadPlayback(relative(workspace, recording.path), 6);
    const source = { file: "main.cpp", usrs };
    const verify = async (expected: TraceStop) => {
      await assertPlayback(hooks, expected, source);
      assert.equal(hooks.snapshot().trace?.source?.file, source.file);
      stops.push({ trace: hooks.snapshot().trace, selected: hooks.snapshot().selected,
        editor: { uri: vscode.window.activeTextEditor?.document.uri.toString(),
          line: vscode.window.activeTextEditor!.selection.active.line + 1 } });
    };
    const enabled: TraceStop["enabled"] = ["into", "over", "out", "previous", "reset"];
    const forward: TraceStop[] = [
      { name: "main", line: 8, position: 1, callers: {}, enabled: ["into", "previous", "reset"] },
      { name: "A", line: 6, position: 2, callers: { main: 1 }, enabled: ["into", "over", "previous", "reset"] },
      { name: "B", line: 4, position: 3, callers: { A: 1 }, enabled },
      { name: "C", line: 3, position: 4, callers: { B: 1 }, enabled },
    ];
    for (const stop of forward) {
      await playbackCommand("Into");
      await verify(stop);
    }
    for (const [action, stop] of [
      ["Over", { name: "D", line: 5, position: 5, callers: { A: 1 }, enabled }],
      ["Out", { name: "E", line: 7, position: 6, callers: { main: 1 }, enabled: ["previous", "reset"] }],
    ] satisfies [string, TraceStop][]) {
      await callView(api);
      await message(hooks, { type: "traceSeek", usr: usrs.B });
      await verify({ name: "B", line: 4, position: 3, callers: { A: 1 }, enabled });
      const before = hooks.snapshot();
      await playbackCommand(action);
      await verify(stop);
      assert.equal(hooks.snapshot().root, before.root);
      assert.deepEqual(hooks.snapshot().viewport, before.viewport);
    }
    assert.deepEqual(requests.filter(item => item.error), [], "no backend operation failed");
  } finally {
    BackendClient.prototype.request = request;
    vscode.window.showQuickPick = picker;
    vscode.window.showInformationMessage = information;
    await writeFile(join(report, "at11-recording.json"), JSON.stringify({ workspace, versions, requests, artifacts, stops }, null, 2));
  }
}

async function projectChecks(): Promise<void> {
  const cmakeFile = join(workspace, "CMakeLists.txt"), stateFile = join(workspace, ".icoda/state.json");
  const originalCmake = await readFile(cmakeFile), originalState = await readFile(stateFile);
  const gateFile = join(workspace, "p06-check.cmake"), started = join(workspace, "p06-started");
  const selected = selectedContext().targetId;
  const errors: string[] = [], showError = vscode.window.showErrorMessage;
  vscode.window.showErrorMessage = ((text: string) => { errors.push(text); return showError(text); }) as typeof showError;
  try {
    await writeFile(cmakeFile, originalCmake.toString() + '\nenable_testing()\nadd_test(NAME demo COMMAND demo)\n'
      + 'add_test(NAME p06_gate COMMAND "${CMAKE_COMMAND}" -P "${CMAKE_SOURCE_DIR}/p06-check.cmake")\n');
    await writeFile(gateFile, 'message(STATUS "P06 gate passed")\n');
    const state = JSON.parse(originalState.toString());
    state.test_command = ["ctest", "--test-dir", join(workspace, "build/debug"), "--output-on-failure"];
    await writeFile(stateFile, JSON.stringify(state));
    await observeLifecycle(async seen => {
      await command("icoda.selectTarget", { context: selectedContext(), targetId: null });
      await command("icoda.buildTarget");
      const build = seen.requests.find(item => item.method === "build.run");
      assert.ok(build?.result, String(build?.error));
      const built = build.result as TargetOperationResult;
      assert.deepEqual(built.check && { kind: built.check.kind, ok: built.check.ok }, { kind: "build", ok: true });
      assert.equal(built.target.kind, "whole-project");
      assert.equal(built.executable, null);
      assert.equal((build.params as { trusted: boolean }).trusted, true);
      await command("icoda.selectTarget", { context: selectedContext(), targetId: selected });
      const context = selectedContext();
      const files = ["CMakeCache.txt", "compile_commands.json", process.platform === "win32" ? "demo.exe" : "demo"];
      const snapshot = () => Promise.all(files.map(async name => {
        const path = join(workspace, "build/debug", name);
        return { name, hash: createHash("sha256").update(await readFile(path)).digest("hex"),
          time: (await stat(path, { bigint: true })).mtimeNs.toString() };
      }));
      const before = await snapshot();
      await command("icoda.testProject");
      const passed = seen.requests.filter(item => item.method === "tests.run").at(-1)!;
      assert.ok(passed.result, String(passed.error));
      assert.match((passed.result as TargetOperationResult).check!.output, /100% tests passed/);
      assert.equal((passed.result as TargetOperationResult).targetId, selected);
      assert.equal((passed.result as TargetOperationResult).target.kind, "whole-project");
      await writeFile(gateFile, 'message(FATAL_ERROR "P06 failing check")\n');
      await command("icoda.testProject");
      const failed = seen.requests.filter(item => item.method === "tests.run").at(-1)!;
      assert.equal((failed.error as BackendError).code, "test_failed");
      assert.match(failed.error!.message, /P06 failing check/);
      assert.ok(errors.some(text => text.includes("P06 failing check")));
      await writeFile(gateFile, 'file(WRITE "${CMAKE_CURRENT_LIST_DIR}/p06-started" "ready")\n'
        + 'execute_process(COMMAND "${CMAKE_COMMAND}" -E sleep 60)\n');
      const running = command("icoda.testProject");
      await until("CTest started the cancellable child", () => existsSync(started));
      seen.progress.at(-1)!.cancel();
      await running;
      const cancelled = seen.requests.filter(item => item.method === "tests.run").at(-1)!;
      assert.equal((cancelled.error as BackendError).code, "cancelled");
      assert.ok(seen.requests.some(item => item.method === "operation.cancel"));
      assert.ok(seen.progress.every(item => item.ended));
      await writeFile(gateFile, 'message(STATUS "P06 recovered")\n');
      await command("icoda.testProject");
      assert.ok(seen.requests.filter(item => item.method === "tests.run").at(-1)?.result);
      assert.deepEqual(selectedContext(), context);
      assert.deepEqual(await snapshot(), before, "tests leave ordinary build artifacts intact");
      await command("icoda.analyseProject");
      assert.equal(api.snapshot().project?.modelState, "fresh");
      await lifecycleReport("p06-project-checks", seen, { before, after: await snapshot(), errors });
    });
  } finally {
    vscode.window.showErrorMessage = showError;
    await writeFile(cmakeFile, originalCmake);
    await writeFile(stateFile, originalState);
    await rm(gateFile, { force: true }); await rm(started, { force: true });
  }
}

async function emptyWorkspace(): Promise<void> {
  assert.equal(vscode.workspace.workspaceFolders, undefined);
  api = await activate();
  await command("icoda.openProject");
  await command("icoda.analyseProject");
  await command("icoda.showOutput");
  assert.equal(api.snapshot().backendStarted, false);
  assert.equal(api.snapshot().project, undefined);
  assert.deepEqual(api.snapshot().tree, []);
  assert.match(api.snapshot().treeMessage ?? "", /Open a workspace folder/);
}

function selectedContext(): SessionContext {
  const target = api.snapshot().tree[0]?.children?.find(item => item.id === "targets")?.children?.[0];
  assert.ok(target?.selection, "native project tree exposes the selected session/revision/target");
  return target.selection.context;
}

function assertDead(pid: number): void {
  assert.throws(() => process.kill(pid, 0), { code: "ESRCH" }, `owned PID ${pid} has exited`);
}

async function lifecycleReport(name: string, seen: LifecycleObservation, extra: object = {}): Promise<void> {
  await writeFile(join(report, `${name}.json`), JSON.stringify({ ...extra,
    requests: seen.requests.map(({ client, error, ...entry }) => ({ ...entry, pid: client.pid,
      error: error && { message: error.message, code: error instanceof BackendError ? error.code : undefined } })),
    progress: seen.progress, messages: seen.messages, state: api.snapshot(), callView: api.callView()?.snapshot(),
  }, null, 2));
}

/** Reuse G14's temporary shim and file gate; the production service and its child analysis are unchanged. */
async function slowBackendTests(): Promise<void> {
  const runtime = require("../../pythonRuntime") as typeof import("../../pythonRuntime");
  const resolveBackend = runtime.resolveBackend;
  const extension = vscode.extensions.all.find(item => item.packageJSON.name === "icoda")!;
  const core = join(await resolveBackend(extension.extensionPath), "icoda_core");
  const shim = join(report, "slow-runtime");
  await writeServiceShim(shim, core, `${slowAnalysis}
held_analysis = service.Service.analyse_project
def optional_delay(self, project, params):
    if (project.store.root / "hold-analysis").exists():
        (project.store.root / "analysis-started").write_text("ready")
        return held_analysis(self, project, params)
    return original(self, project, params)
service.Service.analyse_project = optional_delay
`);
  runtime.resolveBackend = async () => shim;
  try {
    await command("icoda.restartBackend");
    await check("AT12 target switch supersedes slow analysis without publishing old model graph or trace", supersededAnalysis);
    await check("AT12 progress cancellation sends operation.cancel and leaves analysis usable", cancelledAnalysis);
    await check("AT14 busy backend crash settles requests and Restart Backend restores the project", crashedBackend);
    await check("AT14 restart reaps a busy backend and recovers with a fresh process", () => stopBusyBackend(false));
    await check("AT14 deactivation settles pending work disposes views and reaps the backend", () => stopBusyBackend(true));
  } finally {
    await releaseAnalysis();
    runtime.resolveBackend = resolveBackend;
    await deactivate();
  }
}

async function releaseAnalysis(): Promise<void> {
  await writeFile(join(workspace, "release-analysis"), "ready");
  await rm(join(workspace, "hold-analysis"), { force: true });
}

async function beginAnalysis(seen: LifecycleObservation): Promise<{ command: Thenable<unknown>; request: LifecycleRequest }> {
  for (const file of ["release-analysis", "analysis-started"]) await rm(join(workspace, file), { force: true });
  await writeFile(join(workspace, "hold-analysis"), "ready");
  const pending = command("icoda.analyseProject");
  await until("real Python worker at the G14 analysis gate", () => existsSync(join(workspace, "analysis-started")));
  const request = seen.requests.filter(item => item.method === "project.analyse").at(-1);
  assert.ok(request);
  assert.equal(request.settled, false, "switch/cancel/kill occurs before the real request finishes");
  assert.equal(api.snapshot().project?.modelState, "analysing");
  assert.equal(seen.progress.at(-1)?.ended, false, "native progress is still running");
  return { command: pending, request };
}

function assertOutcome(request: LifecycleRequest, code: string): void {
  assert.equal(request.settled, true);
  assert.equal(request.result, undefined);
  assert.ok(request.error instanceof BackendError);
  assert.equal(request.error.code, code);
  assert.match(request.error.message, code === "cancelled" ? /cancelled|superseded/i : /Backend.*exit|Backend disposed/i);
}

async function supersededAnalysis(): Promise<void> {
  const hooks = await loadPlayback("calls.tsv", 6, 3);
  const before = api.snapshot(), identity = selectedContext(), trace = hooks.snapshot().trace!;
  const targetId = identity.targetId === null
    ? before.project!.targets.find(item => item.id !== null)!.id : null;
  assert.notEqual(targetId, identity.targetId);
  const marker = join(workspace, "late.py");
  await writeFile(marker, "def obsolete_analysis_marker():\n    return 44\n");
  try {
    await observeLifecycle(async seen => {
      const observations: { context: SessionContext; marker: boolean; trace?: string; nodes: string[] }[] = [];
      const sample = () => observations.push({ context: selectedContext(),
        marker: Boolean(api.snapshot().model?.entities.some(item => item.usr === "python:late:obsolete_analysis_marker")),
        trace: hooks.snapshot().trace?.traceId, nodes: hooks.snapshot().graph?.nodes.map(item => item.usr) ?? [] });
      const timer = setInterval(sample, 10);
      try {
        const pending = await beginAnalysis(seen);
        const switching = command("icoda.selectTarget", { context: identity, targetId });
        await until("registered Select Target sent its request", () => seen.requests.find(item => item.method === "target.select"));
        assert.equal(pending.request.settled, false);
        await releaseAnalysis();
        await Promise.all([pending.command, switching]);
        await until("replacement graph finished loading", () => !hooks.snapshot().loading && hooks.snapshot().graph);
        assertOutcome(pending.request, "cancelled");
        assert.ok(seen.progress.every(item => item.ended));
        const current = selectedContext();
        assert.deepEqual(current, { ...identity, modelRevision: identity.modelRevision + 1, targetId });
        assert.deepEqual(api.snapshot().model, before.model, "cancelled candidate cannot replace the whole model");
        assert.equal(hooks.snapshot().trace, undefined, "old target's recording is cleared");
        assert.equal(hooks.snapshot().selected, null);
        const graph = seen.requests.filter(item => item.method === "view.get").at(-1)?.result as SessionContext;
        assert.ok(graph, "target switch fetched the real replacement graph");
        for (const key of ["sessionId", "modelRevision", "targetId"] as const) assert.equal(graph[key], current[key]);
        sample();
        await pause(100); // Include a later host event turn, after both requests and graph publication settled.
        assert.ok(observations.some(item => item.context.targetId === targetId));
        assert.ok(observations.every(item => !item.marker && !item.nodes.includes("python:late:obsolete_analysis_marker")));
        assert.ok(observations.filter(item => item.context.targetId === targetId).every(item =>
          item.context.modelRevision === current.modelRevision && item.trace !== trace.traceId));
        await rm(marker);
        await command("icoda.analyseProject");
        assert.equal(api.snapshot().project?.modelState, "fresh");
        assert.equal(selectedContext().modelRevision, current.modelRevision + 1);
        await lifecycleReport("at12-superseded", seen, { identity, current, observations });
      } finally { clearInterval(timer); await releaseAnalysis(); }
    });
  } finally { await rm(marker, { force: true }); }
}

async function cancelledAnalysis(): Promise<void> {
  const hooks = await loadPlayback("calls.tsv", 6, 3);
  const before = api.snapshot(), identity = selectedContext(), trace = hooks.snapshot().trace;
  await observeLifecycle(async seen => {
    try {
      const pending = await beginAnalysis(seen);
      seen.progress.at(-1)!.cancel(); // Same cancellation token used by the native progress Cancel button.
      const cancellation = await until("operation.cancel acknowledgement", () =>
        seen.requests.find(item => item.method === "operation.cancel" && item.settled));
      assert.deepEqual(cancellation.result, { ...cancellation.params, cancellable: true, reason: "cancel_requested" });
      await releaseAnalysis();
      await pending.command;
      assertOutcome(pending.request, "cancelled");
      assert.ok(seen.progress.every(item => item.ended));
      assert.ok(seen.messages.includes("ICODA: Operation cancelled or superseded."));
      assert.deepEqual(selectedContext(), identity);
      assert.deepEqual(api.snapshot().model, before.model);
      assert.deepEqual(hooks.snapshot().trace, trace);
      assert.equal(api.snapshot().project?.modelState, before.project?.modelState);
      await command("icoda.analyseProject");
      assert.equal(api.snapshot().project?.modelState, "fresh");
      assert.equal(selectedContext().modelRevision, identity.modelRevision + 1);
      await callView(api);
      assert.ok(seen.requests.some(item => item.method === "view.get" && item.result));
      await lifecycleReport("at12-cancelled", seen);
    } finally { await releaseAnalysis(); }
  });
}

async function crashedBackend(): Promise<void> {
  await loadPlayback("calls.tsv", 6, 3);
  const identity = selectedContext(), before = api.snapshot();
  await observeLifecycle(async seen => {
    const pending = await beginAnalysis(seen), old = pending.request.client, pid = old.pid!;
    try {
      process.kill(pid, "SIGKILL");
      await Promise.all([pending.command, old.closed]);
      await until("native tree marks the backend stopped", () => !api.snapshot().backendStarted);
      assertOutcome(pending.request, "backend_exited");
      assert.ok(seen.progress.every(item => item.ended));
      assertDead(pid);
      assert.equal(api.snapshot().project, undefined);
      assert.equal(api.snapshot().model, undefined);
      assert.equal(api.callView(), undefined);
      assert.match(api.snapshot().treeMessage ?? "", /Backend not started/);
      const stopped = api.snapshot();
      await releaseAnalysis();
      await command("icoda.restartBackend");
      const recovered = selectedContext();
      assert.notEqual(recovered.sessionId, identity.sessionId);
      assert.equal(recovered.targetId, identity.targetId);
      assert.equal(api.snapshot().project?.root, before.project?.root);
      assert.deepEqual(api.snapshot().model, before.model);
      await command("icoda.analyseProject");
      const replacement = seen.requests.at(-1)!.client;
      assert.notEqual(replacement.pid, pid);
      assert.equal(api.snapshot().project?.modelState, "fresh");
      await callView(api);
      assert.equal(api.callView()?.snapshot().trace, undefined, "a dead backend's trace cannot survive restart");
      await lifecycleReport("at14-crash", seen, { stopped, oldPid: pid, newPid: replacement.pid, identity, recovered });
    } finally { await releaseAnalysis(); }
  });
}

async function reopenedCallView(): Promise<void> {
  let hooks = await loadPlayback("calls.tsv", 6, 3);
  await message(hooks, { type: "root", usr: "python:main:A" });
  await hooks.dispatch({ type: "viewport", version: hooks.snapshot().version, viewport: { x: 25, y: 35, scale: 1.2 } });
  await observeLifecycle(async seen => {
    for (let iteration = 0; iteration < 3; iteration++) {
      const previous = hooks, before = previous.snapshot();
      const tab = vscode.window.tabGroups.all.flatMap(group => group.tabs).find(tab => tab.label === "ICODA Call View");
      assert.ok(tab?.input instanceof vscode.TabInputWebview);
      assert.equal(await vscode.window.tabGroups.close(tab), true);
      await until("closed panel's disposal hook", () => api.callView() === undefined);
      const requests = seen.requests.length;
      await previous.dispatch({ type: "traceSeek", version: before.version, usr: "python:main:E" });
      assert.equal(seen.requests.length, requests, "disposed message listener cannot reach the backend");
      hooks = await callView(api);
      assert.deepEqual(hooks.snapshot().trace, before.trace);
      assert.deepEqual(hooks.snapshot().graph, before.graph);
      assert.equal(hooks.snapshot().root, before.root);
      assert.deepEqual(hooks.snapshot().viewport, before.viewport);
      await until("reopened native Call View tab", () => vscode.window.tabGroups.all
        .some(group => group.tabs.some(tab => tab.label === "ICODA Call View")));
      assert.equal(vscode.window.tabGroups.all.flatMap(group => group.tabs).filter(tab => tab.label === "ICODA Call View").length, 1);
      const steps = seen.requests.filter(item => item.method === "trace.step").length;
      await command("icoda.traceInto");
      assert.equal(seen.requests.filter(item => item.method === "trace.step").length, steps + 1,
        "one command produces one request after repeated disposal/reopen");
      await assertPlayback(hooks, { name: "C", line: 18, position: 4, callers: { B: 1 },
        enabled: ["previous", "into", "over", "out", "reset"] });
      hooks = await playbackCommand("Previous");
      await assertCall(hooks, "B", 14, 3);
      hooks = await callView(api);
    }
    await lifecycleReport("at14-webview", seen);
  });
}

async function stopBusyBackend(deactivating: boolean): Promise<void> {
  await callView(api);
  const identity = selectedContext();
  await observeLifecycle(async seen => {
    const pending = await beginAnalysis(seen), old = pending.request.client, pid = old.pid!;
    try {
      const stopping = deactivating ? deactivate() : command("icoda.restartBackend");
      await until("pending request rejected by lifecycle cleanup", () => pending.request.settled);
      assertOutcome(pending.request, "backend_disposed");
      await releaseAnalysis();
      await Promise.all([stopping, pending.command, old.closed]);
      assertDead(pid);
      assert.ok(seen.progress.every(item => item.ended));
      assert.equal(api.callView(), undefined);
      if (deactivating) {
        assert.equal(api.snapshot().backendStarted, false);
        assert.equal(api.snapshot().project, undefined);
        assert.equal((await vscode.commands.getCommands(true)).includes("icoda.analyseProject"), false);
        assert.equal(vscode.window.tabGroups.all.flatMap(group => group.tabs).some(tab => tab.label === "ICODA Call View"), false);
      } else {
        assert.equal(api.snapshot().project?.root, workspace);
        assert.equal(selectedContext().targetId, identity.targetId);
        assert.notEqual(selectedContext().sessionId, identity.sessionId);
        assert.notEqual(seen.requests.at(-1)?.client.pid, pid);
        await command("icoda.analyseProject");
        assert.equal(api.snapshot().project?.modelState, "fresh");
        await callView(api);
      }
      await lifecycleReport(deactivating ? "at14-deactivate" : "at14-restart", seen, { oldPid: pid });
    } finally { await releaseAnalysis(); }
  });
}

async function workspaceSuite(): Promise<void> {
  await check("activation and all registered ICODA commands", async () => { api = await activate(); });
  await check("real Python analysis and populated project tree (AT01)", analyse);
  await check("Call View selection reveals native source and loads trace", reveal);
  await check("AT03 moved source opens the relocated file and line through Go to Entity and Call View", movedSource);
  await check("AT04 ambiguous basenames offer a file choice and revalidate the selected source", ambiguousSource);
  await check("AT04 missing source reports source_missing locally and keeps the editor and graph usable", () => missingSource());
  await check("AT04 outside-root matches and escaping symlinks are excluded", () => missingSource(true));
  await check("AT04 source navigation preserves a different file's unsaved editor buffer", dirtySourceBuffer);
  for (const [action, name, line, position] of [["Into", "C", 18, 4], ["Over", "D", 23, 5], ["Out", "E", 27, 6]] as const) {
    await check(`AT05 B → ${name} via Step ${action}, graph and active editor agree`, () => step(action, name, line, position));
  }
  await check("AT09 seek, Previous Call and Reset share the Python cursor", resetPrevious);
  await check("AT06 leaf Into skips returns and selects the next eligible call", leafPlayback);
  await check("AT06 repeats preserve counts and caller edges through Over, Into, Out, Previous and Reset", repeatPlayback);
  await check("AT06 recursion uses the selected invocation's return", recursivePlayback);
  await check("AT06 unresolved calls are skipped while their stack scopes remain usable", unresolvedPlayback);
  await check("AT07 interleaved threads keep Into global and Over/Out on the selected thread", interleavedPlayback);
  await check("AT08 empty trace disables playback and valid reload recovers", emptyPlayback);
  await check("AT08 malformed trace reports invalid_trace without losing selection and reload recovers", malformedPlayback);
  await check("AT08 truncated trace cannot invent scope exits and valid reload recovers", truncatedPlayback);
  await check("AT08 exhaustion retains selection, disables forward actions and reload recovers", exhaustedPlayback);
  await check("native light/dark Call View screenshots at wide/narrow widths", () => screenshots(api));
  await check("AT14 Call View close and reopen restores playback without accumulating listeners", reopenedCallView);
  await check("P04 shared graph filters and neighborhoods preserve native source playback and cameras", graphInteractions);
  await check("P03 Mind Map opens introducing history and source with session guards", mindMapHistory);
  await check("P01 File View assignment command, saved parents, source and cameras survive reopen and restart", fileClustering);
  await check("P02 proposal command shows core delta and candidate source while retaining project playback", proposalCallView);
  await check("P05 saved and external source changes refresh analysis without overwriting dirty editors", automaticSourceRefresh);
  await check("P08 native specification save builds a bare project, refreshes edits and retains failed-build saves", specificationSave);
  await check("P09 provider picker persists custom executable and model while missing providers leave browsing usable", providerSelection);
  await check("P10 idle purpose proposal is reviewable without changing Call View or source editor", backgroundPurpose);
  await check("P11 restart restores diagrams and reports retained work with safe recovery", persistenceRecovery);
  await slowBackendTests();
}

async function backgroundPurpose(): Promise<void> {
  const root = join(report, "p10-project"), backend = join(__dirname, "../../../.."), shim = join(report, "p10-runtime");
  const configFile = join(report, "p10-config", "config.json");
  await promisify(execFile)(process.env.ICODA_TEST_PYTHON!, ["-c", [
    "import runpy, sys", "from pathlib import Path", "from icoda_core import persistence",
    "persistence.config_path = lambda: Path(sys.argv[2])", "root = Path(sys.argv[1])",
    "runpy.run_path('tests/fixtures/fake_workflow.py')['prepare'](root)",
    "persistence.ProjectStore(root).save_ui({'provider': {'provider': 'fixture', 'model': 'purpose'}})",
  ].join("\n"), root, configFile], { cwd: backend });
  await writeServiceShim(shim, join(backend, "icoda_core"), `
import runpy
from pathlib import Path
from icoda_core import persistence
persistence.config_path = lambda: Path(${JSON.stringify(configFile)})
runpy.run_path(${JSON.stringify(join(backend, "tests/fixtures/fake_workflow.py"))})['install']()
`);
  const runtime = require("../../pythonRuntime") as typeof import("../../pythonRuntime");
  const resolveBackend = runtime.resolveBackend, picker = vscode.window.showWorkspaceFolderPick;
  let chosen = root;
  vscode.window.showWorkspaceFolderPick = (async () => vscode.workspace.workspaceFolders?.find(folder => folder.uri.fsPath === chosen)) as typeof picker;
  assert.ok(vscode.workspace.updateWorkspaceFolders(vscode.workspace.workspaceFolders!.length, 0, { uri: vscode.Uri.file(root) }));
  await until("P10 temporary folder", () => vscode.workspace.workspaceFolders?.find(folder => folder.uri.fsPath === root));
  const config = vscode.workspace.getConfiguration("icoda", vscode.Uri.file(root));
  runtime.resolveBackend = async () => shim;
  try {
    await command("icoda.restartBackend");
    await command("icoda.openProject");
    await command("icoda.analyseProject");
    const hooks = await callView(api);
    const usr = String(api.snapshot().model!.entities.find(entity => entity.name === "run")!.usr);
    await message(hooks, { type: "select", usr });
    await command("workbench.action.focusSecondEditorGroup");
    const editor = await until("P10 source editor", () => vscode.window.activeTextEditor);
    assert.equal(editor.document.uri.fsPath, join(root, "src/main.py"));
    await until("P10 initial Call View camera", () => hooks.snapshot().viewport);
    // Revealing the source splits the native editor group; wait for its resize camera before comparison.
    let camera = JSON.stringify(hooks.snapshot().viewport), resized = Date.now();
    await until("P10 settled split editor camera", () => {
      const current = JSON.stringify(hooks.snapshot().viewport);
      if (current !== camera) { camera = current; resized = Date.now(); }
      return Date.now() - resized >= 500;
    });
    const selection = editor.selection, graph = hooks.snapshot();
    const source = await readFile(join(root, "tests/test_main.py"), "utf8");
    await observeLifecycle(async seen => {
      await config.update("backgroundPurposeComments", true, vscode.ConfigurationTarget.WorkspaceFolder);
      await pause(30_100); // Exercise the production idle timer; no manual propose command or real provider.
      const job = await until("P10 checked background candidate", () => {
        const status = seen.requests.filter(item => item.method === "workflow.status").at(-1)?.result as WorkflowStatus | undefined;
        return status?.workflow?.state === "completed" ? status.workflow : undefined;
      });
      assert.equal(job.kind, "purpose");
      assert.equal(job.result?.round, "purpose");
      assert.ok(job.result?.files.includes("tests/test_main.py"));
      assert.match(await readFile(join(job.result!.candidateLocation!, "tests/test_main.py"), "utf8"), /Check the fixture arithmetic/);
      assert.equal(await readFile(join(root, "tests/test_main.py"), "utf8"), source);
      assert.equal(hooks.snapshot().selected, graph.selected);
      assert.deepEqual(hooks.snapshot().viewport, graph.viewport);
      assert.equal(hooks.snapshot().trace, graph.trace);
      assert.equal(vscode.window.activeTextEditor, editor);
      assert.ok(editor.selection.isEqual(selection));
      assert.equal(seen.requests.filter(item => item.method === "purpose.propose").length, 1);
      assert.ok(!seen.requests.some(item => ["purpose.apply", "conversation.send", "workflow.start"].includes(item.method)));
      assert.deepEqual(seen.progress, []); assert.deepEqual(seen.messages, []);
      await config.update("backgroundPurposeComments", false, vscode.ConfigurationTarget.WorkspaceFolder);
      await command("icoda.rejectPurposeComments");
      assert.ok(seen.requests.some(item => item.method === "purpose.reject" && !item.error));
      assert.equal(existsSync(job.result!.candidateLocation!), false);
      await writeFile(join(report, "p10-background-purpose.json"), JSON.stringify({ job, graph: hooks.snapshot(),
        editor: editor.document.uri.toString(), requests: seen.requests.map(({ method, params, result }) => ({ method, params, result })) }, null, 2));
    });
  } finally {
    await config.update("backgroundPurposeComments", undefined, vscode.ConfigurationTarget.WorkspaceFolder);
    chosen = workspace;
    await command("icoda.openProject");
    runtime.resolveBackend = resolveBackend;
    await command("icoda.restartBackend");
    vscode.window.showWorkspaceFolderPick = picker;
    const index = vscode.workspace.workspaceFolders!.findIndex(folder => folder.uri.fsPath === root);
    if (index >= 0) vscode.workspace.updateWorkspaceFolders(index, 1);
  }
}

async function specificationSave(): Promise<void> {
  const root = join(report, "p08_bare"), failedRoot = join(report, "p08_failed");
  const folderPicker = vscode.window.showWorkspaceFolderPick, showError = vscode.window.showErrorMessage;
  const errors: string[] = [];
  let chosen = root;
  vscode.window.showWorkspaceFolderPick = (async () => vscode.workspace.workspaceFolders?.find(folder => folder.uri.fsPath === chosen)) as typeof folderPicker;
  vscode.window.showErrorMessage = (async (text: string) => { errors.push(text); return undefined; }) as typeof showError;
  await mkdir(root);
  await writeFile(join(root, "README.md"), "Preserve existing notes\n");
  await mkdir(join(failedRoot, "src"), { recursive: true });
  const broken = "def broken(:\n";
  await writeFile(join(failedRoot, "src/p08_failed.py"), broken);
  assert.ok(vscode.workspace.updateWorkspaceFolders(vscode.workspace.workspaceFolders!.length, 0,
    { uri: vscode.Uri.file(root) }, { uri: vscode.Uri.file(failedRoot) }));
  await until("temporary P08 workspaces", () => vscode.workspace.workspaceFolders?.length === 3);
  const edit = async (document: vscode.TextDocument, text: string) => {
    const change = new vscode.WorkspaceEdit();
    change.replace(document.uri, new vscode.Range(document.positionAt(0), document.positionAt(document.getText().length)), text);
    assert.ok(await vscode.workspace.applyEdit(change));
    assert.ok(await document.save(), "native save succeeds even when the post-save build fails");
    assert.equal(document.isDirty, false);
  };
  try {
    await observeLifecycle(async seen => {
      for (chosen of [root, failedRoot]) {
        await command("icoda.openProject");
        assert.equal(api.snapshot().project?.root, chosen);
        await command("icoda.openSpecification");
        const document = vscode.window.activeTextEditor!.document;
        assert.equal(document.uri.scheme, "icoda-specification");
        const generated = await promisify(execFile)(process.env.ICODA_TEST_PYTHON!, ["-c",
          "import json, sys; from icoda_core import specification; print(json.dumps(specification.default_specification(sys.argv[1], 'Python')))",
          basename(chosen)], { cwd: join(__dirname, "../../../..") });
        await edit(document, generated.stdout);
        assert.equal(JSON.parse(await readFile(join(chosen, ".icoda/specification.json"), "utf8")).code_profile.language, "Python");
        assert.equal(JSON.parse(await readFile(join(chosen, ".icoda/state.json"), "utf8")).phase, "architecture");
        const phase = seen.requests.filter(item => item.method === "phase.get").at(-1)!.result as { phase: string };
        assert.equal(phase.phase, "architecture", "the specification tree reread the refreshed phase");
        if (chosen === root) {
          assert.equal(api.snapshot().project?.modelState, "fresh");
          assert.ok(api.snapshot().model?.entities.length);
          assert.equal(await readFile(join(root, "README.md"), "utf8"), "Preserve existing notes\n");
          const hooks = await callView(api), version = hooks.snapshot().version;
          const source = join(root, "src/p08_bare.py");
          await writeFile(source, await readFile(source, "utf8") + "\ndef after_save():\n    return 42\n");
          const spec = JSON.parse(document.getText());
          spec.summary = "Reanalyse after editing the saved specification";
          await edit(document, JSON.stringify(spec));
          await until("P08 model and Call View refreshed", () => api.snapshot().model?.entities.some(entity => entity.name === "after_save")
            && hooks.snapshot().version > version && !hooks.snapshot().loading);
          assert.equal(errors.length, 0);
        } else {
          assert.equal(api.snapshot().project?.modelState, "stale");
          assert.equal(await readFile(join(failedRoot, "src/p08_failed.py"), "utf8"), broken);
          assert.equal(errors.length, 1);
          assert.match(errors[0]!, /build_failed: Specification saved/);
          const save = seen.requests.filter(item => item.method === "spec.save").at(-1)!.result as { postSaveError: { code: string } };
          assert.equal(save.postSaveError.code, "build_failed");
        }
        await command("workbench.action.closeAllEditors");
        await command("icoda.openSpecification");
        assert.equal(JSON.parse(vscode.window.activeTextEditor!.document.getText()).code_profile.language, "Python");
        await command("workbench.action.closeAllEditors");
      }
      assert.ok(seen.progress.some(item => item.title?.includes("Saving specification") && item.ended));
      assert.ok(seen.requests.filter(item => item.method === "spec.save").every(item => (item.params as { postSave: boolean }).postSave));
      assert.ok(seen.requests.every(item => !/^(workflow\.start|recovery\.resolve|conversation\.send)$/.test(item.method)));
      await lifecycleReport("p08-specification-save", seen, { errors, state: api.snapshot() });
    });
  } finally {
    await command("workbench.action.closeAllEditors");
    chosen = workspace;
    await command("icoda.openProject");
    await command("icoda.analyseProject");
    vscode.workspace.updateWorkspaceFolders(1, 2);
    await until("P08 original workspace restored", () => vscode.workspace.workspaceFolders?.length === 1);
    vscode.window.showWorkspaceFolderPick = folderPicker;
    vscode.window.showErrorMessage = showError;
  }
}

async function untrustedSpecificationSave(): Promise<void> {
  assert.equal(vscode.workspace.isTrusted, false);
  await observeLifecycle(async seen => {
    await assert.rejects(async () => vscode.workspace.fs.writeFile(vscode.Uri.parse("icoda-specification:/p08.json"), Buffer.from("{}")),
      /workspace_untrusted/);
    assert.deepEqual(seen.requests, [], "native Save cannot reach spec.save or start the backend without trust");
  });
  assert.equal(api.snapshot().backendStarted, false);
  // Reuse the untrusted suite's verified process/network audit guard for the separate test-owned client.
  const guard = join(report, "service-guard"), previous = process.env.PYTHONPATH;
  process.env.PYTHONPATH = [guard, previous].filter(Boolean).join(delimiter);
  let client: BackendClient;
  try {
    client = new BackendClient({ python: process.env.ICODA_TEST_PYTHON!,
      packageRoot: join(__dirname, "../../../.."), log: () => {} });
  } finally {
    if (previous === undefined) delete process.env.PYTHONPATH;
    else process.env.PYTHONPATH = previous;
  }
  try {
    const initialized = await client.ready;
    assert.ok("specificationPostSave" in initialized.capabilities);
    assert.equal(initialized.capabilities.specificationPostSave, true);
    const attempts = await readFile(join(guard, "attempts.log"), "utf8");
    assert.equal(attempts, "ready\nready\n", "the second test-owned client installed the execution guard");
    const project = await client.request<SessionContext>("project.open", { path: workspace });
    const before = await client.request<{ document: unknown }>("spec.get", {}, project);
    await assert.rejects(client.request("spec.save", { document: before.document, postSave: true,
      unsavedDocuments: [], trusted: vscode.workspace.isTrusted }, project), (error: unknown) => {
      assert.ok(error instanceof BackendError);
      assert.equal(error.code, "workspace_untrusted");
      return true;
    });
    assert.deepEqual(await client.request("spec.get", {}, project), before);
    assert.equal(existsSync(join(workspace, ".icoda/specification.json")), false);
    assert.equal(existsSync(join(workspace, "src")), false);
    assert.equal(await readFile(join(guard, "attempts.log"), "utf8"), attempts, "no build or provider was attempted");
  } finally { await client.dispose(); }
  assert.equal(vscode.workspace.isTrusted, false);
  assert.equal(api.snapshot().backendStarted, false);
}

async function proposalCallView(): Promise<void> {
  const root = join(report, "p02-candidate"), backend = join(__dirname, "../../../..");
  await promisify(execFile)(process.env.ICODA_TEST_PYTHON!, ["-c", [
    "import json, runpy, sys",
    "from pathlib import Path",
    "from icoda_core import git, persistence, prompt, recovery, response, steps",
    "root = Path(sys.argv[1])",
    "runpy.run_path('tests/fixtures/fake_workflow.py')['prepare'](root)",
    "runner = steps.StepRunner(root, persistence.UserConfig())",
    "worktree = git.create_worktree(root, runner.store.dir / 'worktree', 'p02-retained')",
    "files = [{'path': 'src/helper.py', 'content': 'def helper():\\n    \\\"\\\"\\\"A helper.\\\"\\\"\\\"\\n    pass\\n'},",
    "         {'path': 'src/main.py', 'content': 'from src.helper import helper\\ndef run():\\n    \\\"\\\"\\\"An entry stub.\\\"\\\"\\\"\\n    helper()\\n'}]",
    "reply = json.dumps({'title': 'Candidate graph', 'rationale': 'Inspect calls and source', 'files': files})",
    "parsed, error = response.parse_response(reply)",
    "assert parsed, error",
    "candidate = steps.Proposal(1, prompt.StepRequest('architecture', 1, 'Add helper', max_entities=2), worktree, response=parsed, reply=reply)",
    "recovery.checkpoint_proposal(root, candidate)",
    "for file in files: (worktree / file['path']).write_text(file['content'])",
    "(root / '.icoda/cache/run.tsv').write_text('# icoda-call-trace-v1\\nE\\t0\\tt\\t0\\trun\\t\\trun\\t\\nX\\t1\\tt\\t0\\trun\\t\\trun\\t\\n')",
  ].join("\n"), root], { cwd: backend });
  const folderPicker = vscode.window.showWorkspaceFolderPick, picker = vscode.window.showQuickPick;
  const input = vscode.window.showInputBox, errorMessage = vscode.window.showErrorMessage;
  const errors: string[] = [];
  let chosen = root;
  vscode.window.showWorkspaceFolderPick = (async () => vscode.workspace.workspaceFolders?.find(folder => folder.uri.fsPath === chosen)) as typeof folderPicker;
  vscode.window.showQuickPick = (async (items: readonly { value: string }[], options: vscode.QuickPickOptions) => {
    assert.equal(options.placeHolder, "Recover interrupted proposal");
    return items.find(item => item.value === "resume");
  }) as unknown as typeof picker;
  vscode.window.showInputBox = (async () => "P02 review complete") as typeof input;
  vscode.window.showErrorMessage = ((text: string) => { errors.push(text); return errorMessage(text); }) as typeof errorMessage;
  assert.ok(vscode.workspace.updateWorkspaceFolders(vscode.workspace.workspaceFolders!.length, 0, { uri: vscode.Uri.file(root) }));
  await until("temporary candidate workspace", () => vscode.workspace.workspaceFolders?.find(folder => folder.uri.fsPath === root));
  try {
    await observeLifecycle(async seen => {
      await command("icoda.openProject");
      assert.equal(api.snapshot().project?.root, root);
      await command("icoda.selectTarget", { context: selectedContext(), targetId: null });
      const projectView = await callView(api);
      await projectView.loadTrace(join(root, ".icoda/cache/run.tsv"));
      await command("icoda.traceInto");
      await until("project webview initial camera", () => projectView.snapshot().viewport);
      await projectView.dispatch({ type: "fit", version: projectView.snapshot().version, width: 900, height: 600 });
      await pause(200); // Let the native webview receive the fitted camera before switching panels.
      const projectState = projectView.snapshot();
      await command("icoda.recoverProposal");
      await command("icoda.showProposalCallView");
      const candidate = await until("native candidate graph", () => {
        const hooks = api.proposalCallView(), state = hooks?.snapshot();
        return state?.graph && !state.loading && state.active ? hooks : undefined;
      });
      assert.equal(candidate.snapshot().proposal, true);
      assert.equal(candidate.snapshot().trace, undefined);
      assert.equal(candidate.snapshot().graph?.nodes.find(node => node.usr === "python:src.helper:helper")?.change, "added");
      assert.equal(candidate.snapshot().graph?.nodes.find(node => node.usr === "python:src.main:run")?.change, "changed");
      await message(candidate, { type: "select", usr: "python:src.helper:helper" });
      const document = await until("candidate source document", () => vscode.window.visibleTextEditors.find(editor =>
        editor.document.uri.fsPath === join(root, ".icoda/worktree/src/helper.py") && editor.selection.active.line === 0)?.document);
      assert.equal(existsSync(join(root, "src/helper.py")), false);
      const edit = new vscode.WorkspaceEdit();
      edit.insert(document.uri, new vscode.Position(document.lineCount, 0), "# unsaved candidate note\n");
      assert.ok(await vscode.workspace.applyEdit(edit));
      await message(candidate, { type: "select", usr: "python:src.helper:helper" });
      assert.ok(document.isDirty && document.getText().includes("unsaved candidate note"));
      await command("icoda.reviewProposal");
      const review = seen.requests.filter(item => item.method === "proposal.get").at(-1)?.result as ProposalReview;
      assert.equal(review.proposal?.canApprove, false);
      await command("icoda.approveProposal");
      assert.ok(errors.some(text => /Approval is blocked/.test(text)));
      assert.equal(seen.requests.some(item => item.method === "proposal.approve"), false);
      assert.ok(await document.save());
      await message(candidate, { type: "select", usr: "python:src.helper:helper" });
      assert.ok(seen.requests.some(item => item.method === "source.resolve" && item.error instanceof BackendError && item.error.code === "stale_evidence"));
      await command("icoda.reviewProposal");
      await command("icoda.rebuildProposal");
      await command("icoda.showProposalCallView");
      await until("rebuilt candidate graph", () => api.proposalCallView()?.snapshot().graph);
      const after = projectView.snapshot();
      assert.deepEqual(after.trace, projectState.trace);
      assert.deepEqual(after.viewport, projectState.viewport);
      assert.equal(after.root, projectState.root);
      assert.equal(after.selected, projectState.selected);
      await lifecycleReport("p02-candidate-call-view", seen, { candidate: api.proposalCallView()?.snapshot(),
        editor: document.uri.toString(), errors });
      await command("icoda.rejectProposal");
      assert.equal(api.proposalCallView(), undefined);
    });
  } finally {
    vscode.window.showQuickPick = picker;
    vscode.window.showInputBox = input;
    vscode.window.showErrorMessage = errorMessage;
    await command("workbench.action.closeAllEditors");
    chosen = workspace;
    await command("icoda.openProject");
    const index = vscode.workspace.workspaceFolders?.findIndex(folder => folder.uri.fsPath === root) ?? -1;
    if (index >= 0) vscode.workspace.updateWorkspaceFolders(index, 1);
    await until("original workspace restored", () => vscode.workspace.workspaceFolders?.length === 1);
    vscode.window.showWorkspaceFolderPick = folderPicker;
  }
}

async function automaticSourceRefresh(): Promise<void> {
  const path = join(workspace, "library.py"), created = join(workspace, "p05_new.py");
  const original = await readFile(path);
  const config = vscode.workspace.getConfiguration("icoda", vscode.Uri.file(workspace));
  const setting = config.inspect<boolean>("autoAnalyse")?.workspaceFolderValue;
  const contains = (usr: string) => api.snapshot().model?.entities.some(entity => entity.usr === usr);
  try {
    await command("icoda.analyseProject");
    await config.update("autoAnalyse", true, vscode.ConfigurationTarget.WorkspaceFolder);
    await observeLifecycle(async seen => {
      const document = await vscode.workspace.openTextDocument(path);
      await vscode.window.showTextDocument(document);
      const edit = new vscode.WorkspaceEdit();
      edit.insert(document.uri, new vscode.Position(document.lineCount, 0), "\ndef saved_marker():\n    return 5\n");
      assert.ok(await vscode.workspace.applyEdit(edit));
      await writeFile(created, "def external_marker():\n    return 8\n");
      await until("external change marked stale", () => api.snapshot().project?.modelState === "stale");
      await pause(600);
      assert.equal(seen.requests.some(item => item.method === "project.analyse"), false, "dirty buffers defer automatic tools");
      assert.ok(document.isDirty && document.getText().includes("saved_marker"));
      assert.ok(await document.save());
      await until("saved and created sources analysed", () => api.snapshot().project?.modelState === "fresh"
        && contains("python:library:saved_marker") && contains("python:p05_new:external_marker"));
      await writeFile(created, "def changed_marker():\n    return 9\n");
      await until("external change analysed", () => api.snapshot().project?.modelState === "fresh" && contains("python:p05_new:changed_marker"));
      await rm(created);
      await until("external deletion analysed", () => api.snapshot().project?.modelState === "fresh" && !contains("python:p05_new:changed_marker"));
      assert.ok(seen.requests.filter(item => item.method === "project.analyse").length >= 3);
      assert.ok(seen.requests.filter(item => item.method === "project.analyse").every(item => (item.params as { automatic: boolean }).automatic));
      await lifecycleReport("p05-source-refresh", seen, { saved: document.uri.toString(), dirty: document.isDirty });
    });
  } finally {
    await config.update("autoAnalyse", false, vscode.ConfigurationTarget.WorkspaceFolder);
    await command("workbench.action.closeAllEditors");
    await writeFile(path, original);
    await rm(created, { force: true });
    await command("icoda.analyseProject");
    await config.update("autoAnalyse", setting, vscode.ConfigurationTarget.WorkspaceFolder);
  }
}

async function fileClustering(): Promise<void> {
  const directory = join(workspace, "p01"), layoutPath = join(workspace, ".icoda/layout.json");
  const originalLayout = existsSync(layoutPath) ? await readFile(layoutPath) : undefined;
  const uiPath = join(workspace, ".icoda/ui.json");
  const originalUi = existsSync(uiPath) ? await readFile(uiPath) : undefined;
  const selected = selectedContext().targetId;
  const picker = vscode.window.showQuickPick;
  let assignment: string | null | undefined = "cluster:p01", picks = 0;
  vscode.window.showQuickPick = (async (items: readonly { id: string | null; label: string }[], options: vscode.QuickPickOptions) => {
    assert.equal(options.title, "Assign File to Cluster");
    assert.equal(options.placeHolder, "library.py");
    picks++;
    if (assignment === undefined) return undefined;
    const item = items.find(item => item.id === assignment);
    assert.ok(item, "the picker contains the shared core's cluster or automatic grouping");
    return item;
  }) as unknown as typeof picker;
  const open = async () => {
    await command("icoda.openFileView");
    return until("loaded native File View", () => {
      const hooks = api.fileView(), state = hooks?.snapshot();
      return state?.graph && !state.loading && state.active && state.visible ? hooks : undefined;
    });
  };
  try {
    await mkdir(directory);
    for (let i = 0; i < 45; i++) await writeFile(join(directory, `file${i}.py`), `def work():\n    return ${i}\n`);
    await observeLifecycle(async seen => {
      await command("icoda.selectTarget", { context: selectedContext(), targetId: null });
      await command("icoda.analyseProject");
      let hooks = await open();
      const action = async (type: string, fields = {}) => hooks.dispatch({ type, ...fields, version: hooks.snapshot().version });
      const parent = hooks.snapshot().graph!.nodes.find(node => node.id === "cluster:p01");
      assert.equal(parent?.fileCount, 45);
      await action("pin", { id: parent!.id });
      await showLibrary();
      await command("icoda.assignFileCluster");
      const layout = JSON.parse(await readFile(layoutPath, "utf8"));
      assert.equal(layout.pins["library.py"], "p01");
      assert.equal(Object.keys(layout.pins).length, 46);
      await command("icoda.revealInFileView");
      let state = hooks.snapshot();
      assert.equal(state.selected, "library.py");
      assert.equal(state.graph?.clusterPath.length, 2);
      assert.equal(state.graph?.clusterPath[0]?.id, "cluster:p01");
      const child = state.graph!.clusterId!;
      assert.ok(state.graph!.nodes.length <= 40);
      await action("select", { id: "library.py" });
      await until("File View native source", () => vscode.window.visibleTextEditors.find(editor =>
        editor.document.uri.fsPath === join(workspace, "library.py") && editor.selection.active.line === 0));
      const childCamera = { x: -41, y: 27, scale: 1.25 }, parentCamera = { x: 83, y: -19, scale: 0.75 };
      await action("viewport", { viewport: childCamera });
      await action("back");
      assert.equal(hooks.snapshot().graph?.clusterId, "cluster:p01");
      await action("viewport", { viewport: parentCamera });
      await action("enter", { id: child });
      assert.deepEqual(hooks.snapshot().viewport, childCamera);
      const tab = vscode.window.tabGroups.all.flatMap(group => group.tabs).find(tab => tab.label === "ICODA File View");
      assert.ok(tab);
      await vscode.window.tabGroups.close(tab);
      await until("File View closed", () => !api.fileView());
      hooks = await open();
      assert.equal(hooks.snapshot().graph?.clusterId, child);
      assert.deepEqual(hooks.snapshot().viewport, childCamera);
      await command("icoda.restartBackend");
      hooks = await open();
      assert.equal(hooks.snapshot().graph?.clusterId, child);
      assert.deepEqual(hooks.snapshot().viewport, childCamera);
      await action("back");
      assert.equal(hooks.snapshot().graph?.clusterId, "cluster:p01");
      assert.deepEqual(hooks.snapshot().viewport, parentCamera);
      await action("back");
      assert.equal(hooks.snapshot().graph?.clusterId, null);
      // Cancellation is a no-op; automatic grouping removes only the selected file's pin.
      assignment = undefined;
      await showLibrary();
      await command("icoda.assignFileCluster");
      assert.deepEqual(JSON.parse(await readFile(layoutPath, "utf8")), layout);
      assignment = null;
      await showLibrary();
      await command("icoda.assignFileCluster");
      const unpinned = JSON.parse(await readFile(layoutPath, "utf8"));
      assert.equal(unpinned.pins["library.py"], undefined);
      assert.equal(Object.keys(unpinned.pins).length, 45);
      assert.equal(picks, 3);
      assert.equal(seen.requests.filter(item => item.method === "cluster.assignFile").length, 2);
      state = hooks.snapshot();
      await lifecycleReport("p01-file-clustering", seen, { fileView: state, layout: unpinned,
        ui: JSON.parse(await readFile(uiPath, "utf8")), editor: vscode.window.visibleTextEditors.map(editor => ({
          uri: editor.document.uri.toString(), line: editor.selection.active.line + 1 })) });
    });
  } finally {
    vscode.window.showQuickPick = picker;
    const tabs = vscode.window.tabGroups.all.flatMap(group => group.tabs).filter(tab => tab.label === "ICODA File View");
    await vscode.window.tabGroups.close(tabs);
    await command("icoda.restartBackend");
    await rm(directory, { recursive: true, force: true });
    if (originalLayout) await writeFile(layoutPath, originalLayout); else await rm(layoutPath, { force: true });
    if (originalUi) await writeFile(uiPath, originalUi); else await rm(uiPath, { force: true });
    await command("icoda.analyseProject");
    await command("icoda.selectTarget", { context: selectedContext(), targetId: selected });
  }
}

async function graphInteractions(): Promise<void> {
  await command("workbench.action.closeAllEditors");
  await command("workbench.action.editorLayoutTwoColumns");
  await command("workbench.action.focusFirstEditorGroup");
  const calls = await callView(api);
  await calls.loadTrace(join(workspace, "calls.tsv"));
  await message(calls, { type: "traceSeek", usr: "python:main:B" });
  await assertCall(calls, "B", 14, 3);
  await calls.dispatch({ type: "viewport", version: calls.snapshot().version, viewport: { x: 87, y: -19, scale: 1.2 } });
  const before = calls.snapshot();
  await calls.dispatch({ type: "graphOptions", version: before.version, text: "edge:calls name:C", depth: 1 });
  const focused = await until("Call neighborhood decisions", () => {
    const snapshot = calls.snapshot();
    return !snapshot.interactions.pending && snapshot.interactions.decisions["python:main:C"] && snapshot;
  });
  assert.equal(focused.interactions.decisions["python:main:C"]!.hidden, false);
  assert.equal(focused.interactions.decisions["python:main:E"]!.hidden, true);
  assert.deepEqual(focused.viewport, before.viewport);
  assert.deepEqual(focused.graph, before.graph);
  assert.deepEqual(focused.trace, before.trace);
  assert.equal(focused.root, before.root);
  await calls.dispatch({ type: "graphOptions", version: before.version, text: "", depth: 1 });
  assert.equal(calls.snapshot().interactions.decisions["python:main:E"]!.dimmed, true);
  await callView(api); // A trace toolbar action originates in the graph, beside its source editor.
  await calls.dispatch({ type: "traceStep", version: calls.snapshot().version, action: "over" });
  await assertCall(calls, "D", 23, 5);
  await until("D neighborhood replaces B", () => !calls.snapshot().interactions.pending
    && calls.snapshot().interactions.decisions["python:main:C"]?.dimmed);
  assert.deepEqual(calls.snapshot().viewport, before.viewport);
  await calls.dispatch({ type: "graphOptions", version: calls.snapshot().version, text: "", depth: 0 });

  // Add classes only to the runner's temporary fixture copy; restore it before the next acceptance case.
  const selectedTarget = selectedContext().targetId;
  const file = join(workspace, "p04_graph.py");
  assert.equal(existsSync(file), false);
  try {
    await writeFile(file, "class Widget:\n    def run(self):\n        return 1\n\nclass Other:\n    pass\n");
    await command("icoda.analyseProject");
    await command("icoda.selectTarget", { context: selectedContext(), targetId: null });
    for (const [name, commandName, get] of [
      ["file", "icoda.openFileView", () => api.fileView()],
      ["class", "icoda.openClassView", () => api.classView()],
      ["mindmap", "icoda.openMindMap", () => api.mindMap()],
    ] as const) {
      await command("workbench.action.focusFirstEditorGroup");
      await command(commandName);
      const hooks = await until(`${name} graph loaded`, () => get()?.snapshot().graph && get());
      await until(`${name} camera`, () => hooks.snapshot().viewport);
      const initial = hooks.snapshot();
      assert.ok(initial.graph!.nodes.length);
      if (name === "class") {
        const classHooks = api.classView()!;
        const widget = classHooks.snapshot().graph!.nodes.find(node => node.label === "Widget" || node.label.endsWith(".Widget"));
        assert.ok(widget?.usr);
        await classHooks.dispatch({ type: "select", version: classHooks.snapshot().version, id: widget.usr });
        await until("class source editor", () => vscode.window.visibleTextEditors.find(editor =>
          editor.document.uri.fsPath === file && editor.selection.active.line === 0));
      }
      await hooks.dispatch({ type: "graphOptions", version: initial.version, text: "kind:method name:run", depth: 1 });
      const after = await until(`${name} filter decisions`, () => {
        const state = hooks.snapshot();
        return !state.interactions.pending && state.interactions.decisions["python:p04_graph:Widget.run"] && state;
      });
      assert.equal(after.interactions.error, "");
      assert.equal(after.interactions.decisions["python:p04_graph:Widget.run"]!.hidden, false);
      assert.equal(after.interactions.decisions["python:main:B"]!.hidden, true);
      assert.deepEqual(after.graph, initial.graph);
      assert.deepEqual(after.viewport, initial.viewport);
      await hooks.dispatch({ type: "graphOptions", version: initial.version - 1, text: "wrong", depth: 0 });
      await hooks.dispatch({ type: "graphOptions", version: initial.version, text: "wrong", depth: 99 });
      assert.equal(hooks.snapshot().interactions.text, "kind:method name:run");
      await hooks.dispatch({ type: "graphOptions", version: initial.version, text: "", depth: 0 });
      assert.deepEqual(hooks.snapshot().interactions.decisions, {});
    }
    await writeFile(join(report, "p04-interactions.json"), JSON.stringify({ before, focused,
      class: api.classView()?.snapshot(), file: api.fileView()?.snapshot(), mindmap: api.mindMap()?.snapshot() }, null, 2));
  } finally {
    await rm(file, { force: true });
    await command("icoda.analyseProject");
    await command("icoda.selectTarget", { context: selectedContext(), targetId: selectedTarget });
    const restored = await callView(api);
    await restored.loadTrace(join(workspace, "calls.tsv"));
  }
}

async function mindMapHistory(): Promise<void> {
  const editorLayout = await command("vscode.getEditorLayout");
  const historyPath = join(workspace, ".icoda/steps.jsonl"), statePath = join(workspace, ".icoda/state.json");
  const history = existsSync(historyPath) ? await readFile(historyPath) : undefined;
  const state = existsSync(statePath) ? await readFile(statePath) : undefined;
  const createOutput = vscode.window.createOutputChannel, request = BackendClient.prototype.request;
  let output = "", shows = 0, disposed = false, hold = false;
  let release!: () => void, received!: () => void;
  const barrier = new Promise<void>(resolve => { release = resolve; });
  const requested = new Promise<void>(resolve => { received = resolve; });
  const replies: unknown[] = [];
  vscode.window.createOutputChannel = ((name: string) => {
    const channel = createOutput(name);
    if (name !== "ICODA Mind Map History") return channel;
    const replace = channel.replace.bind(channel), show = channel.show.bind(channel), dispose = channel.dispose.bind(channel);
    channel.replace = text => { output = text; replace(text); };
    channel.show = () => { shows++; show(true); };
    channel.dispose = () => { disposed = true; dispose(); };
    return channel;
  }) as typeof createOutput;
  BackendClient.prototype.request = async function<T>(...args: Parameters<BackendClient["request"]>): Promise<T> {
    const result = await request.apply(this, args);
    if (args[0] === "mindmap.step") {
      replies.push(result);
      if (hold) { received(); await barrier; }
    }
    return result as T;
  };
  try {
    const record = { number: 2, phase: "architecture", decision: "approved", title: "Introduce B",
      entities_added: ["python:main:B"], files: ["main.py"] };
    const records = [record, { ...record, decision: "manual", title: "B history", rationale: "Keep the API",
      build_ok: true, test_ok: true, build_output: "P03 build passed", test_output: "P03 tests passed" },
      { ...record, decision: "rejected", title: "Wrong rejected record" },
      { ...record, round: "approach", title: "Wrong approach record" }];
    await writeFile(historyPath, records.map(item => JSON.stringify(item)).join("\n") + "\n");
    await command("workbench.action.focusFirstEditorGroup");
    await command("icoda.openMindMap");
    const hooks = await until("Mind Map loaded", () => api.mindMap()?.snapshot().graph && api.mindMap());
    await until("Mind Map initial fit rendered", () => hooks.snapshot().viewport);
    const action = (type: string, fields = {}) => hooks.dispatch({ type, ...fields, version: hooks.snapshot().version });
    const nodeId = "entity:python:main:B";
    while (!hooks.snapshot().graph!.nodes.some(node => node.id === nodeId)) {
      const expandable = hooks.snapshot().graph!.nodes.find(node => node.expandable && !node.expanded);
      assert.ok(expandable, "B is reachable through the shared hierarchy");
      await action("setExpanded", { nodeId: expandable.id, expanded: true });
    }
    await action("select", { nodeId });
    await assertEditor("B", 14);
    const camera = { x: -45, y: 28, scale: 1.2 };
    await action("viewport", { viewport: camera });
    await action("openStep", { nodeId });
    assert.match(output, /Step 2: manual — B history/);
    assert.match(output, /Keep the API[\s\S]*Build: passed\nP03 build passed[\s\S]*Tests: passed\nP03 tests passed/);
    assert.doesNotMatch(output, /Wrong rejected|Wrong approach/);
    assert.equal(shows, 1);
    assert.equal(hooks.snapshot().selected, nodeId);
    assert.deepEqual(hooks.snapshot().viewport, camera);
    await assertEditor("B", 14);
    // A reply already returned by Python cannot open history after the real target selection changes.
    hold = true;
    const pending = action("openStep", { nodeId });
    await requested;
    const selected = selectedContext().targetId;
    const next = selected === null ? api.snapshot().project!.targets.find(target => target.kind === "executable")!.id : null;
    await command("icoda.selectTarget", { context: selectedContext(), targetId: next });
    release();
    await pending;
    assert.equal(shows, 1);
    await command("icoda.selectTarget", { context: selectedContext(), targetId: selected });
    await writeFile(join(report, "p03-mindmap-history.json"), JSON.stringify({ replies, output, shows, camera }, null, 2));
    const tab = vscode.window.tabGroups.all.flatMap(group => group.tabs).find(tab => tab.label === "ICODA Mind Map");
    assert.ok(tab);
    await vscode.window.tabGroups.close(tab);
    assert.equal(disposed, true, "closing Mind Map disposes its history channel");
  } finally {
    release();
    BackendClient.prototype.request = request;
    vscode.window.createOutputChannel = createOutput;
    const tabs = vscode.window.tabGroups.all.flatMap(group => group.tabs).filter(tab => tab.label === "ICODA Mind Map");
    await vscode.window.tabGroups.close(tabs);
    if (history) await writeFile(historyPath, history); else await rm(historyPath, { force: true });
    if (state) await writeFile(statePath, state); else await rm(statePath, { force: true });
    await command("workbench.action.closePanel");
    await command("vscode.setEditorLayout", editorLayout);
    await command("workbench.action.focusFirstEditorGroup");
  }
}

/** Called by the real Extension Development Host, independently of Node's unit-test runner. */
export async function run(): Promise<void> {
  const mode = process.env.ICODA_TEST_MODE!;
  try {
    assert.equal(vscode.version, process.env.ICODA_TEST_VSCODE_VERSION);
    if (mode === "empty") await check("no-workspace activation and commands are safe", emptyWorkspace);
    else if (mode === "untrusted") {
      api = await untrustedSuite(check);
      await check("P08 Restricted Mode refuses native Save and post-save orchestration before persistence or build", untrustedSpecificationSave);
    }
    else if (mode === "cpp") {
      await check("C++ workspace activation and registered ICODA commands", async () => { api = await activate(); });
      await check("AT11 records the selected executable in isolation and steps real calls in the graph and editor", recordExecutable);
      await check("P06 Whole Project build and full CTest failure cancellation and recovery preserve target and build artifacts", projectChecks);
    }
    else await workspaceSuite();
  } finally {
    const passed = results.filter(result => result.passed).length;
    const skipped = results.filter(result => result.skipped).length;
    const failed = results.length - passed - skipped;
    await writeFile(join(report, `${mode}-results.json`), JSON.stringify({ version: vscode.version, mode, passed, failed, skipped,
      results, state: api?.snapshot(), callView: api?.callView()?.snapshot() }, null, 2));
    console.log(`Integration ${mode}: ${passed} passed, ${failed} failed, ${skipped} skipped`);
  }
}

async function providerSelection(): Promise<void> {
  const runtime = require("../../pythonRuntime") as typeof import("../../pythonRuntime");
  const resolveBackend = runtime.resolveBackend, picker = vscode.window.showQuickPick, input = vscode.window.showInputBox;
  const showError = vscode.window.showErrorMessage;
  const extension = vscode.extensions.all.find(item => item.packageJSON.name === "icoda")!;
  const backend = await resolveBackend(extension.extensionPath), shim = join(report, "p09-runtime");
  const configRoot = join(report, "p09-config"), executable = join(report, "p09 provider executable");
  await symlink(process.env.ICODA_TEST_PYTHON!, executable);
  await writeServiceShim(shim, join(backend, "icoda_core"), `
import os, runpy
from pathlib import Path
from dataclasses import replace
from icoda_core import agent, persistence
runpy.run_path(${JSON.stringify(join(backend, "tests/fixtures/fake_workflow.py"))})['install']()
fixture = agent.load_providers()[0]
agent.load_providers = lambda: [replace(fixture, login_hint='Use the controlled fixture CLI login')]
persistence.config_path = lambda: Path(${JSON.stringify(join(configRoot, "config.json"))})
`);
  const config = vscode.workspace.getConfiguration("icoda", vscode.Uri.file(workspace));
  const originalSelection = config.inspect("providerSelection")?.workspaceFolderValue;
  const originalUI = await readFile(join(workspace, ".icoda/ui.json"));
  let binary = executable, selectedModel = "custom-fixture-id";
  const errors: string[] = [], models: string[][] = [];
  vscode.window.showQuickPick = (async (items: readonly { label: string; model?: string; provider?: { id: string }; description?: string }[],
    options: vscode.QuickPickOptions) => {
    if (options.placeHolder?.startsWith("Select provider")) return items.find(item => item.provider?.id === "fixture");
    assert.ok(options.placeHolder?.startsWith("Select model"));
    models.push(items.map(item => item.description ?? ""));
    return items.find(item => item.model === "");
  }) as unknown as typeof picker;
  vscode.window.showInputBox = (async (options: vscode.InputBoxOptions) => {
    if (options.prompt?.startsWith("Provider executable")) return binary;
    if (options.prompt === "Custom provider model ID") return selectedModel;
    if (options.prompt?.startsWith("Message to the selected provider")) return "Explain main";
    assert.fail(`Unexpected provider input: ${options.prompt}`);
  }) as typeof input;
  vscode.window.showErrorMessage = ((text: string) => { errors.push(text); return showError(text); }) as typeof showError;
  runtime.resolveBackend = async () => shim;
  try {
    await observeLifecycle(async seen => {
      await command("icoda.restartBackend");
      const saved = () => seen.requests.filter(item => item.method === "providers.select" && !item.error).at(-1)?.result as ProviderInventory;
      await command("icoda.selectProviderModel");
      assert.deepEqual(saved().selection, { provider: "fixture", model: selectedModel });
      assert.equal(saved().providers[0]!.binaryPath, executable);
      assert.equal(saved().providers[0]!.authenticationConfigured, false);
      assert.equal(saved().providers[0]!.loginHint, "Use the controlled fixture CLI login");
      assert.ok(models[0]!.includes("ok"), "model suggestions come from the controlled Python registry");
      const ui = JSON.parse(await readFile(join(workspace, ".icoda/ui.json"), "utf8"));
      assert.deepEqual(ui.provider, { ...saved().selection, binary: executable });
      const defaults = JSON.parse(await readFile(join(configRoot, "config.json"), "utf8"));
      assert.equal(defaults.model, selectedModel);
      assert.equal(defaults.provider, "fixture");
      assert.equal(errors.length, 0);
      assert.ok(!seen.requests.some(item => /workflow.start|conversation.send|cli.command/.test(item.method)), "selection invokes no agent");
      const oldSession = saved().sessionId;
      await command("icoda.restartBackend");
      await until("P09 provider inventory after restart", () => seen.requests.some(item => item.method === "providers.list"
        && (item.result as ProviderInventory | undefined)?.sessionId !== oldSession && Boolean(item.result)));
      const inventory = seen.requests.filter(item => item.method === "providers.list").at(-1)!.result as ProviderInventory;
      assert.deepEqual(inventory.selection, saved().selection);
      assert.equal(inventory.providers[0]!.binaryPath, executable);
      // A stale folder setting must not override the desktop-compatible project selection.
      await config.update("providerSelection", { provider: "stale-setting", model: "fail" }, vscode.ConfigurationTarget.WorkspaceFolder);
      await command("icoda.sendConversation");
      const conversation = seen.requests.filter(item => item.method === "conversation.send").at(-1)!;
      assert.equal((conversation.params as { provider?: string }).provider, undefined);
      assert.equal((conversation.params as { model?: string }).model, undefined);
      const completed = seen.requests.filter(item => item.method === "workflow.status").at(-1)!.result as WorkflowStatus;
      assert.equal(completed.workflow?.state, "completed");
      assert.match(completed.workflow!.result!.summary, /Controlled conversation reply/);
      selectedModel = "fail";
      await command("icoda.selectProviderModel");
      await command("icoda.sendConversation");
      const failed = seen.requests.filter(item => item.method === "workflow.status").at(-1)!.result as WorkflowStatus;
      assert.equal(failed.workflow?.error?.code, "provider_failed");
      binary = join(report, "missing-provider");
      const before = await readFile(join(workspace, ".icoda/ui.json"), "utf8");
      await command("icoda.selectProviderModel");
      const failure = seen.requests.filter(item => item.method === "providers.select").at(-1)!;
      assert.ok(failure.error instanceof BackendError && failure.error.code === "provider_failed");
      assert.ok(errors.some(text => text.includes("Controlled fixture") && text.includes("missing-provider")));
      assert.equal(await readFile(join(workspace, ".icoda/ui.json"), "utf8"), before);
      // A previously saved executable can disappear too; inventory and browsing still work.
      await rm(executable);
      await command("icoda.restartBackend");
      await command("icoda.selectProviderModel");
      const missing = seen.requests.filter(item => item.method === "providers.list").at(-1)!.result as ProviderInventory;
      assert.equal(missing.providers[0]!.available, false);
      assert.equal(missing.providers[0]!.binaryPath, null);
      const navigationStart = seen.requests.length;
      const hooks = await callView(api);
      await message(hooks, { type: "select", usr: "python:main:B" });
      await assertEditor("B", 14);
      assert.equal(hooks.snapshot().selected, "python:main:B");
      assert.ok(seen.requests.slice(navigationStart).every(item => !/^(workflow|conversation|cli|recovery)\./.test(item.method)));
      await writeFile(join(report, "p09-provider-evidence.json"), JSON.stringify({ inventory, missing, errors, models,
        requests: seen.requests.map(({ method, params, result, error }) => ({ method, params, result,
          error: error instanceof BackendError ? { code: error.code, message: error.message } : undefined })),
        editor: vscode.window.activeTextEditor?.document.uri.toString() }, null, 2));
    });
  } finally {
    vscode.window.showQuickPick = picker; vscode.window.showInputBox = input; vscode.window.showErrorMessage = showError;
    runtime.resolveBackend = resolveBackend;
    await writeFile(join(workspace, ".icoda/ui.json"), originalUI);
    await config.update("providerSelection", originalSelection, vscode.ConfigurationTarget.WorkspaceFolder);
    await command("icoda.restartBackend");
  }
}


async function persistenceRecovery(): Promise<void> {
  const root = join(report, "p11-persistence"), backend = join(__dirname, "../../../..");
  await promisify(execFile)(process.env.ICODA_TEST_PYTHON!, ["-c", [
    "import runpy, sys",
    "from pathlib import Path",
    "from icoda_core import git, persistence, python_analysis",
    "root = Path(sys.argv[1])",
    "persistence.config_path = lambda: root.parent / 'p11-config.json'",
    "runpy.run_path('tests/fixtures/fake_workflow.py')['prepare'](root)",
    "source = root / 'src/main.py'",
    "source.write_text('def main():\\n    return helper()\\n\\ndef helper():\\n    return Worker().work()\\n\\nclass Worker:\\n    def work(self):\\n        return 1\\n')",
    "store = persistence.ProjectStore(root)",
    "store.save_model(python_analysis.parse_project(root))",
    "store.save_ui({'provider': {'provider': 'fixture', 'model': 'p11-saved'}, 'unrelated': 'preserved'})",
    "worktree = git.create_worktree(root, store.dir / 'worktree', 'p11-retained')",
    "(worktree / 'draft.txt').write_text('Retained developer work.\\n')",
  ].join("\n"), root], { cwd: backend });
  const folderPicker = vscode.window.showWorkspaceFolderPick, picker = vscode.window.showQuickPick;
  let chosen = root;
  const recoveryChoices: string[][] = [];
  vscode.window.showWorkspaceFolderPick = (async () => vscode.workspace.workspaceFolders?.find(folder => folder.uri.fsPath === chosen)) as typeof folderPicker;
  vscode.window.showQuickPick = (async (items: readonly { value: string; label: string }[], options: vscode.QuickPickOptions) => {
    assert.equal(options.placeHolder, "Recover interrupted proposal");
    recoveryChoices.push(items.map(item => item.value));
    return items.find(item => item.value === "keep");
  }) as unknown as typeof picker;
  assert.ok(vscode.workspace.updateWorkspaceFolders(vscode.workspace.workspaceFolders!.length, 0, { uri: vscode.Uri.file(root) }));
  await until("P11 workspace", () => vscode.workspace.workspaceFolders?.find(folder => folder.uri.fsPath === root));
  const stateFile = join(root, ".icoda/state.json"), historyFile = join(root, ".icoda/steps.jsonl");
  const draft = join(root, ".icoda/worktree/draft.txt"), source = join(root, "src/main.py");
  const before = await Promise.all([stateFile, historyFile, draft].map(file => readFile(file, "utf8")));
  const cameras = [{ x: -41, y: 23, scale: 1.25 }, { x: 71, y: -31, scale: 0.8 }, { x: 51, y: 12, scale: 1.3 }];
  try {
    await observeLifecycle(async seen => {
      await command("icoda.openProject");
      await command("icoda.selectTarget", { context: selectedContext(), targetId: null });
      let calls = await callView(api);
      assert.ok(calls.snapshot().graph?.nodes.some(node => node.usr === "python:src.main:helper"));
      await calls.dispatch({ type: "root", usr: "python:src.main:helper", version: calls.snapshot().version });
      await calls.dispatch({ type: "depth", depth: 5, version: calls.snapshot().version });
      await calls.dispatch({ type: "callers", callers: true, version: calls.snapshot().version });
      await calls.dispatch({ type: "filter", text: "helper", version: calls.snapshot().version });
      await until("P11 initial call camera", () => calls.snapshot().viewport);
      await pause(200);
      await calls.dispatch({ type: "viewport", viewport: cameras[0], version: calls.snapshot().version });
      await command("icoda.openClassView");
      let classes = await until("P11 classes", () => api.classView()?.snapshot().graph ? api.classView() : undefined);
      await until("P11 initial class camera", () => classes.snapshot().viewport);
      await pause(200);
      await classes.dispatch({ type: "viewport", viewport: cameras[1], version: classes.snapshot().version });
      await command("icoda.openMindMap");
      let mind = await until("P11 mind map", () => api.mindMap()?.snapshot().graph ? api.mindMap() : undefined);
      await until("P11 initial mind map camera", () => mind.snapshot().viewport);
      await pause(200); // Let the initial native fit response reach the webview before simulating a pan.
      await mind.dispatch({ type: "viewport", viewport: cameras[2], version: mind.snapshot().version });
      const edited = await readFile(source, "utf8") + "\n# User edit before restarting.\n";
      await writeFile(source, edited);
      const previousContext = selectedContext();
      await command("icoda.restartBackend");
      assert.notEqual(selectedContext().sessionId, previousContext.sessionId);
      assert.equal(selectedContext().targetId, null);
      assert.equal(api.snapshot().project?.modelState, "stale");
      assert.match(api.snapshot().project!.staleReason, /Analyse Project/);
      calls = await callView(api);
      assert.equal(calls.snapshot().root, "python:src.main:helper");
      assert.equal(calls.snapshot().depth, 5);
      assert.equal(calls.snapshot().callers, true);
      assert.equal(calls.snapshot().filter, "helper");
      assert.deepEqual(calls.snapshot().viewport, cameras[0]);
      await command("icoda.openClassView");
      classes = await until("P11 restored classes", () => api.classView()?.snapshot().graph ? api.classView() : undefined);
      assert.deepEqual(classes.snapshot().viewport, cameras[1]);
      await command("icoda.openMindMap");
      mind = await until("P11 restored mind map", () => api.mindMap()?.snapshot().graph ? api.mindMap() : undefined);
      assert.deepEqual(mind.snapshot().viewport, cameras[2]);
      const opened = seen.requests.filter(item => item.method === "project.open").at(-1)!.result as { ui: { provider: { model: string }; unrelated: string } };
      assert.equal(opened.ui.provider.model, "p11-saved");
      assert.equal(opened.ui.unrelated, "preserved");
      await command("icoda.recoverProposal");
      assert.deepEqual(recoveryChoices, [["resume", "keep", "discard"]]);
      assert.ok(seen.requests.some(item => item.method === "recovery.resolve" && (item.params as { choice: string }).choice === "keep"));
      assert.deepEqual(await Promise.all([stateFile, historyFile, draft].map(file => readFile(file, "utf8"))), before);
      await command("icoda.analyseProject");
      assert.equal(api.snapshot().project?.modelState, "fresh");
      assert.equal(await readFile(source, "utf8"), edited);
      assert.equal(await readFile(draft, "utf8"), before[2]);
      assert.ok(!seen.requests.some(item => /^(workflow.start|conversation.send|purpose.propose|proposal.approve|step.undo)$/.test(item.method)));
      await lifecycleReport("p11-persistence-recovery", seen, { recoveryChoices, cameras, project: api.snapshot() });
    });
  } finally {
    vscode.window.showQuickPick = picker;
    await command("workbench.action.closeAllEditors");
    chosen = workspace;
    await command("icoda.openProject");
    const index = vscode.workspace.workspaceFolders?.findIndex(folder => folder.uri.fsPath === root) ?? -1;
    if (index >= 0) vscode.workspace.updateWorkspaceFolders(index, 1);
    await until("P11 original workspace restored", () => vscode.workspace.workspaceFolders?.length === 1);
    vscode.window.showWorkspaceFolderPick = folderPicker;
  }
}
