import { viewError } from "./viewErrors";
import * as vscode from "vscode";
import { randomBytes } from "node:crypto";
import { callViewHtml } from "./callViewHtml";
import { CallViewMessage, parseCallViewMessage } from "./callViewMessages";
import { CallViewModel } from "./callViewModel";
import { SourceContext, revealSource, sourceWarning } from "./sourceEditor";
import { SourceReference, TargetOperationResult } from "./protocol";
import { sameContext } from "./sessionState";
import { basename } from "node:path";
import { projectTracePath, TraceAction } from "./tracePlayback";

/** Thin VS Code boundary; one instance belongs to exactly one project session. */
export class CallViewPanel implements vscode.Disposable {
  private readonly panel: vscode.WebviewPanel;
  private readonly model: CallViewModel;
  private readonly listeners: vscode.Disposable[] = [];
  private readonly sessionId: string;
  private disposed = false;
  private pending = Promise.resolve();
  private synchronizing = Promise.resolve();

  constructor(extensionUri: vscode.Uri, private readonly context: SourceContext, private readonly closed: () => void) {
    this.sessionId = context.session.identity.context!.sessionId;
    const media = vscode.Uri.joinPath(extensionUri, "media");
    this.panel = vscode.window.createWebviewPanel(context.candidateSource ? "icoda.proposalCallView" : "icoda.callView",
      context.candidateSource ? "ICODA Proposal Call View" : "ICODA Call View", vscode.ViewColumn.Active, {
      enableScripts: true, localResourceRoots: [media],
    });
    this.model = new CallViewModel(context.session, context.client, context.log, () => this.render(), context.candidateSource?.sourceRootId);
    this.listeners.push(this.panel.onDidDispose(() => this.dispose()),
      this.panel.webview.onDidReceiveMessage(value => { void this.receive(value); }));
    const uri = (file: string) => this.panel.webview.asWebviewUri(vscode.Uri.joinPath(media, file)).toString();
    this.panel.webview.html = callViewHtml(randomBytes(24).toString("hex"), this.panel.webview.cspSource,
      uri("callView.js"), uri("callView.css"));
    this.sync();
  }

  async saveState(): Promise<void> { await this.model.saveState(); }

  reveal(): void { if (!this.disposed) this.panel.reveal(); }

  /** The host suite uses the same message validation/action queue as the webview. */
  integrationHooks() {
    return {
      snapshot: () => structuredClone({ ...this.model.render(), active: this.panel.active, visible: this.panel.visible }),
      dispatch: (message: unknown) => this.receive(message),
      loadTrace: async (path: string) => {
        await this.synchronizing;
        const message = { type: "traceLoad" as const, version: this.model.version };
        const loading = this.pending.then(() => this.loadTrace(message, vscode.Uri.file(path)));
        this.pending = loading.catch(() => {});
        await loading;
      },
    };
  }

  async traceCommand(action: TraceAction | "reset"): Promise<void> {
    if (!this.panel.active || !this.model.trace?.availability[action]) return;
    await this.receive(action === "reset" ? { type: "traceReset", version: this.model.version }
      : { type: "traceStep", action, version: this.model.version });
  }

  selectedSource(): SourceReference | undefined {
    const node = this.model.graph?.nodes.find(item => item.usr === this.model.selected);
    return !this.disposed && this.panel.active && node?.file
      ? { sourceRootId: node.sourceRootId, usr: node.usr } : undefined;
  }

  sync(): void {
    if (this.disposed) return;
    if (this.context.session.identity.context?.sessionId !== this.sessionId || !vscode.workspace.isTrusted) {
      this.dispose();
      return;
    }
    if (this.context.candidateSource && !sameContext(this.context.candidateSource, this.context.session.identity.context)) {
      this.dispose();
      return;
    }
    this.synchronizing = this.synchronizing.then(() => this.model.sync());
  }

  private async receive(value: unknown): Promise<void> {
    const message = parseCallViewMessage(value);
    if (!message) { this.context.log("Dropped malformed or unknown Call View message."); return; }
    if (this.disposed || !vscode.workspace.isTrusted || !this.model.accepts(message)) {
      this.context.log("Dropped obsolete Call View message.");
      return;
    }
    if (message.type === "ready") { this.render(); return; }
    if (message.type === "viewport" || message.type === "filter" || message.type === "fit") {
      await this.model.control(message);
      return;
    }
    this.pending = this.pending.then(() => this.action(message)).catch(error => {
      if (!this.disposed && this.model.accepts(message)) {
        this.model.error = `Call View: ${viewError(error)}`;
        this.context.log(this.model.error);
        this.render();
      }
    });
    await this.pending;
  }

  private async action(message: Exclude<CallViewMessage, { type: "ready" }>): Promise<void> {
    if (this.disposed || !vscode.workspace.isTrusted || !this.model.accepts(message)) return;
    if (message.type === "traceLoad") { await this.loadTrace(message); return; }
    let ref;
    if (message.type === "traceStep") ref = await this.model.navigateTrace(message.action, message.version);
    else if (message.type === "traceReset") ref = await this.model.navigateTrace("reset", message.version);
    else if (message.type === "traceSeek") ref = await this.model.navigateTrace("seek", message.version, message.usr);
    else if (message.type === "select") {
      ref = this.model.select(message.usr);
      if (!ref) sourceWarning(this.context.log, "This graph item has no project source location.");
    } else { await this.model.control(message); return; }
    if (ref) await revealSource(this.context, ref, true, () => !this.disposed && this.model.accepts(message));
  }

  private async loadTrace(message: Extract<CallViewMessage, { type: "traceLoad" }>, chosen?: vscode.Uri): Promise<void> {
    const root = this.context.session.data!.root;
    const files = chosen ? [chosen] : await vscode.window.showOpenDialog({ defaultUri: vscode.Uri.file(root),
      canSelectFiles: true, canSelectFolders: false, canSelectMany: false,
      title: "Load trace playback from this project", openLabel: "Load Trace",
      filters: { "ICODA traces": ["tsv", "trace"], "All files": ["*"] },
    });
    if (!files?.[0] || this.disposed || !this.model.accepts(message)) return;
    const path = await projectTracePath(root, files[0].fsPath);
    if (vscode.workspace.isTrusted && this.model.accepts(message)) await this.model.loadTrace(path, message.version);
  }

  async loadRecording(recording: TargetOperationResult): Promise<void> {
    const loading = this.pending.then(async () => {
      if (this.disposed || !vscode.workspace.isTrusted || !recording.path
          || !sameContext(recording, this.context.session.identity.context)) return;
      await this.synchronizing;
      const path = await projectTracePath(this.context.session.data!.root, recording.path);
      if (this.disposed || !sameContext(recording, this.context.session.identity.context)) return;
      await this.model.loadTrace(path, this.model.version);
      if (!this.disposed && sameContext(recording, this.context.session.identity.context)) {
        this.panel.title = `ICODA Trace: ${recording.target.name} · ${basename(path)}`;
      }
    });
    this.pending = loading.catch(() => {});
    await loading;
  }

  private render(): void {
    if (!this.disposed) void this.panel.webview.postMessage(this.model.render());
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.model.dispose();
    this.panel.dispose();
    for (const listener of this.listeners) listener.dispose();
    this.closed();
  }
}
