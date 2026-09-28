import { viewError } from "./viewErrors";
import * as vscode from "vscode";
import { randomBytes } from "node:crypto";
import { fileViewHtml } from "./fileViewHtml";
import { FileViewMessage, parseFileViewMessage } from "./fileViewMessages";
import { FileViewModel } from "./fileViewModel";
import { SourceContext, revealSource } from "./sourceEditor";
import { SourceReference } from "./protocol";

/** Own a single session's File View and validate every inbound message before dispatch. */
export class FileViewPanel implements vscode.Disposable {
  private readonly panel: vscode.WebviewPanel;
  private readonly model: FileViewModel;
  private readonly listeners: vscode.Disposable[] = [];
  private readonly sessionId: string;
  private disposed = false;
  private pending = Promise.resolve();
  private synchronizing = Promise.resolve();

  constructor(extensionUri: vscode.Uri, private readonly context: SourceContext,
    private readonly closed: () => void, private readonly revealActive: () => void) {
    this.sessionId = context.session.identity.context!.sessionId;
    const media = vscode.Uri.joinPath(extensionUri, "media");
    this.panel = vscode.window.createWebviewPanel("icoda.fileView", "ICODA File View", vscode.ViewColumn.Active,
      { enableScripts: true, localResourceRoots: [media] });
    this.model = new FileViewModel(context.session, context.client, context.log, () => this.render());
    this.listeners.push(this.panel.onDidDispose(() => this.dispose()),
      this.panel.webview.onDidReceiveMessage(value => { void this.receive(value); }));
    const uri = (file: string) => this.panel.webview.asWebviewUri(vscode.Uri.joinPath(media, file)).toString();
    this.panel.webview.html = fileViewHtml(randomBytes(24).toString("hex"), this.panel.webview.cspSource,
      uri("fileView.js"), uri("fileView.css"));
    this.sync();
  }

  reveal(): void { if (!this.disposed) this.panel.reveal(); }

  /** Native host tests use the same validation and action queue as the webview. */
  integrationHooks() {
    return {
      snapshot: () => structuredClone({ ...this.model.render(), active: this.panel.active, visible: this.panel.visible }),
      dispatch: (message: unknown) => this.receive(message),
    };
  }

  async assignSelected(): Promise<void> {
    await this.synchronizing;
    if (this.model.selected) await this.receive({ type: "assign", id: this.model.selected, version: this.model.version });
  }

  async saveState(): Promise<void> { await this.model.saveState(); }

  sync(): void {
    if (this.disposed) return;
    if (this.context.session.identity.context?.sessionId !== this.sessionId || !vscode.workspace.isTrusted) {
      this.dispose();
      return;
    }
    this.synchronizing = this.synchronizing.then(() => this.model.sync());
  }

  async revealFile(ref: SourceReference): Promise<void> {
    await this.pending;
    await this.synchronizing;
    await this.model.sync();
    if (this.disposed || !vscode.workspace.isTrusted) return;
    await this.model.reveal(ref);
  }

  private async receive(value: unknown): Promise<void> {
    const message = parseFileViewMessage(value);
    if (!message) { this.context.log("Dropped malformed or unknown File View message."); return; }
    if (this.disposed || !vscode.workspace.isTrusted || !this.model.accepts(message)) {
      this.context.log("Dropped obsolete File View message.");
      return;
    }
    if (message.type === "ready") { this.render(); return; }
    if (message.type === "viewport" || message.type === "fit") { await this.model.control(message); return; }
    this.pending = this.pending.then(() => this.action(message)).catch(error => {
      if (!this.disposed) { this.model.error = `File View: ${viewError(error)}`; this.context.log(this.model.error); this.render(); }
    });
    await this.pending;
  }

  private async action(message: FileViewMessage): Promise<void> {
    if (this.disposed || !vscode.workspace.isTrusted || !this.model.accepts(message)) return;
    if (message.type === "reveal") { this.revealActive(); return; }
    if (message.type === "assign") {
      const ticket = this.context.session.identity.capture();
      const choices = [{ label: "Automatic grouping (unpin file)", id: null as string | null },
        ...(this.model.graph?.clusters ?? []).map(item => ({ label: item.label, id: item.id,
          description: `${item.fileCount} files · ${item.id}` }))];
      const choice = await vscode.window.showQuickPick(choices, { title: "Assign File to Cluster", placeHolder: message.id });
      if (choice && !this.disposed && vscode.workspace.isTrusted
          && this.context.session.identity.isCurrent(ticket) && this.model.accepts(message)) {
        await this.model.assignFile(message, choice.id);
      }
      return;
    }
    if (message.type === "rename") {
      const ticket = this.context.session.identity.capture();
      const name = await vscode.window.showInputBox({ title: "Rename Cluster", prompt: "Cluster name",
        value: this.model.cluster(message.id)?.label,
        validateInput: value => value.trim() ? undefined : "Enter a nonempty cluster name." });
      if (name !== undefined && !this.disposed && vscode.workspace.isTrusted
          && this.context.session.identity.isCurrent(ticket) && this.model.accepts(message)) {
        await this.model.editCluster(message, name);
      }
      return;
    }
    if (message.type === "select") {
      const ref = this.model.select(message.id);
      if (ref) await revealSource(this.context, ref, true, () => !this.disposed && this.model.accepts(message));
    } else await this.model.control(message);
  }

  private render(): void { if (!this.disposed) void this.panel.webview.postMessage(this.model.render()); }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.model.dispose();
    this.panel.dispose();
    for (const listener of this.listeners) listener.dispose();
    this.closed();
  }
}
