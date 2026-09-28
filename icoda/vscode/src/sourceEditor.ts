import * as vscode from "vscode";
import { realpath } from "node:fs/promises";
import { BackendClient } from "./backendClient";
import { ProjectSession } from "./projectSession";
import { BackendError, SourceReference } from "./protocol";
import { SessionTicket } from "./sessionState";
import { AutomaticAnalysis, projectFile, watchSourcePaths } from "./sourceChanges";
import { resolveSource, sourceRoot, SourceOutcome } from "./sourceNavigation";
import { CandidateSource } from "./proposalData";
import { viewError } from "./viewErrors";

export interface SourceContext {
  client: BackendClient;
  session: ProjectSession;
  log: (message: string) => void;
  candidateSource?: CandidateSource;
}

/** Shared editor boundary for explicit commands and future graph/trace selections. */
export async function revealSource(context: SourceContext, ref: SourceReference, preserveFocus = false,
  stillCurrent: () => boolean = () => true): Promise<void> {
  const ticket = context.session.identity.capture();
  const active = () => current(context, ticket) && stillCurrent();
  if (!active()) return;
  try {
    const root = sourceRoot(context.session, ref, context.candidateSource);
    if (!root) return;
    let outcome = await resolveSource(context.client, context.session, ref, context.candidateSource);
    while (outcome?.kind === "choose" && active()) {
      const file = await vscode.window.showQuickPick(outcome.candidates, { placeHolder: "Choose the matching source file" });
      if (!file || !active()) return;
      // Revalidate the choice in the service, including symlink boundaries and removals during the picker.
      outcome = await resolveSource(context.client, context.session, { sourceRootId: ref.sourceRootId, file, line: outcome.line }, context.candidateSource);
    }
    if (!outcome || !active()) return;
    if (outcome.kind === "open") await openSource(root, outcome, preserveFocus, active);
    else if (outcome.kind !== "choose") sourceWarning(context.log, outcome.message);
  } catch (error) {
    if (active()) sourceWarning(context.log, viewError(error));
  }
}

function current(context: SourceContext, ticket: SessionTicket): boolean {
  return vscode.workspace.isTrusted && Boolean(ticket.context) && context.session.identity.isCurrent(ticket);
}

async function openSource(root: string, source: Extract<SourceOutcome, { kind: "open" }>,
  preserveFocus: boolean, active: () => boolean): Promise<void> {
  const document = await sourceDocument(root, vscode.Uri.parse(source.uri), active);
  if (!document || !active()) return;
  const position = document.validatePosition(new vscode.Position(source.line - 1, source.column - 1));
  const range = new vscode.Range(position, position);
  const editor = await vscode.window.showTextDocument(document, {
    preserveFocus, selection: range, viewColumn: preserveFocus ? vscode.ViewColumn.Beside : undefined,
  });
  if (active()) editor.revealRange(range, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
}

/** Reuse buffers (including dirty buffers and symlink aliases); never reload, revert or write. */
async function sourceDocument(root: string, uri: vscode.Uri, stillCurrent: () => boolean): Promise<vscode.TextDocument | undefined> {
  const path = await realpath(uri.fsPath);
  if (!projectFile(root, path)) throw new BackendError("source_missing", "Source is outside the selected project.");
  for (const document of vscode.workspace.textDocuments) {
    if (document.uri.scheme !== "file") continue;
    if (document.uri.toString() === uri.toString()) return document;
    try {
      if (await realpath(document.uri.fsPath) === path) return document;
    } catch { /* A removed open document cannot alias the existing resolved source. */ }
  }
  return stillCurrent() ? vscode.workspace.openTextDocument(vscode.Uri.file(path)) : undefined;
}

export function sourceWarning(log: (message: string) => void, message: string): void {
  const warning = `ICODA source location: ${message}`;
  log(warning);
  void vscode.window.showWarningMessage(warning);
}

/** A session owns both the save listener and debounce timer. */
export function watchSourceSaves(session: ProjectSession, log: (message: string) => void,
  analyse?: () => Promise<boolean>): vscode.Disposable {
  const root = session.data!.root;
  const automatic = new AutomaticAnalysis(session, analyse ?? (async () => true), log);
  const enabled = () => Boolean(analyse) && vscode.workspace.getConfiguration("icoda", vscode.Uri.file(root)).get("autoAnalyse", true);
  let ticket = session.identity.capture();
  const changes = watchSourcePaths(root, file => {
    const now = session.identity.capture();
    // Analysis can publish while the save is debouncing; only a selection/session change discards it.
    if (ticket.generation !== now.generation || ticket.context?.sessionId !== now.context?.sessionId) return;
    session.markSaved(file);
    if (enabled()) automatic.changed();
  }, log);
  const saved = (file: string, deleted = false) => {
    ticket = session.identity.capture();
    void changes.saved(file, deleted);
  };
  const listener = vscode.workspace.onDidSaveTextDocument(document => {
    if (document.uri.scheme === "file") saved(document.uri.fsPath);
  });
  const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(root, "**/*"));
  const external = (uri: vscode.Uri, deleted = false) => {
    if (!enabled() || uri.scheme !== "file") return;
    const file = projectFile(root, uri.fsPath);
    if (!file || file.split("/").some(part => part.startsWith(".") || ["build", "dist", "node_modules", "__pycache__", "venv"].includes(part))) return;
    saved(uri.fsPath, deleted);
  };
  return vscode.Disposable.from(listener, changes, automatic, watcher,
    watcher.onDidCreate(uri => external(uri)), watcher.onDidChange(uri => external(uri)),
    watcher.onDidDelete(uri => external(uri, true)));
}
