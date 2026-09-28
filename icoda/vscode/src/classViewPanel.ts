import { viewError } from "./viewErrors";
import * as vscode from "vscode";
import { randomBytes } from "node:crypto";
import { classViewHtml } from "./classViewHtml";
import { ClassViewMessage, parseClassViewMessage } from "./classViewMessages";
import { ClassViewModel } from "./classViewModel";
import { SourceContext, revealSource } from "./sourceEditor";

/** Own a single session's Class View and validate every inbound message before dispatch. */
export class ClassViewPanel implements vscode.Disposable {
  private readonly panel: vscode.WebviewPanel;
  private readonly model: ClassViewModel;
  private readonly listeners: vscode.Disposable[] = [];
  private readonly sessionId: string;
  private disposed = false;
  private pending = Promise.resolve();

  constructor(extensionUri: vscode.Uri, private readonly context: SourceContext,
    private readonly closed: () => void) {
    this.sessionId = context.session.identity.context!.sessionId;
    const media = vscode.Uri.joinPath(extensionUri, "media");
    this.panel = vscode.window.createWebviewPanel("icoda.classView", "ICODA Class View", vscode.ViewColumn.Active,
      { enableScripts: true, localResourceRoots: [media] });
    this.model = new ClassViewModel(context.session, context.client, context.log, () => this.render());
    this.listeners.push(this.panel.onDidDispose(() => this.dispose()),
      this.panel.webview.onDidReceiveMessage(value => this.receive(value)));
    const uri = (file: string) => this.panel.webview.asWebviewUri(vscode.Uri.joinPath(media, file)).toString();
    this.panel.webview.html = classViewHtml(randomBytes(24).toString("hex"), this.panel.webview.cspSource,
      uri("classView.js"), uri("classView.css"));
    this.sync();
  }

  async saveState(): Promise<void> { await this.model.saveState(); }

  reveal(): void { if (!this.disposed) this.panel.reveal(); }

  integrationHooks() {
    return { snapshot: () => structuredClone(this.model.render()),
      dispatch: (message: unknown) => { this.receive(message); return this.pending; } };
  }

  sync(): void {
    if (this.disposed) return;
    if (this.context.session.identity.context?.sessionId !== this.sessionId || !vscode.workspace.isTrusted) {
      this.dispose();
      return;
    }
    void this.model.sync();
  }

  private receive(value: unknown): void {
    const message = parseClassViewMessage(value);
    if (!message) { this.context.log("Dropped malformed or unknown Class View message."); return; }
    if (this.disposed || !vscode.workspace.isTrusted || !this.model.accepts(message)) {
      this.context.log("Dropped obsolete Class View message.");
      return;
    }
    if (message.type === "ready") { this.render(); return; }
    if (message.type === "viewport" || message.type === "fit") { void this.model.control(message); return; }
    this.pending = this.pending.then(() => this.action(message)).catch(error => {
      if (!this.disposed) { this.model.error = `Class View: ${viewError(error)}`; this.context.log(this.model.error); this.render(); }
    });
  }

  private async action(message: ClassViewMessage): Promise<void> {
    if (this.disposed || !vscode.workspace.isTrusted || !this.model.accepts(message)) return;
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
