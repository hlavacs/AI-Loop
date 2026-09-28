import { viewError } from "./viewErrors";
import * as vscode from "vscode";
import { randomBytes } from "node:crypto";
import { mindMapHtml } from "./mindMapHtml";
import { MindMapMessage, parseMindMapMessage } from "./mindMapMessages";
import { MindMapModel, mindMapStepText } from "./mindMapModel";
import { SourceContext, revealSource } from "./sourceEditor";

/** Own a single session's Mind Map and validate every inbound message before dispatch. */
export class MindMapPanel implements vscode.Disposable {
  private readonly panel: vscode.WebviewPanel;
  private readonly model: MindMapModel;
  private readonly listeners: vscode.Disposable[] = [];
  private readonly sessionId: string;
  private disposed = false;
  private pending = Promise.resolve();
  private history?: vscode.OutputChannel;

  constructor(extensionUri: vscode.Uri, private readonly context: SourceContext,
    private readonly closed: () => void) {
    this.sessionId = context.session.identity.context!.sessionId;
    const media = vscode.Uri.joinPath(extensionUri, "media");
    this.panel = vscode.window.createWebviewPanel("icoda.mindMap", "ICODA Mind Map", vscode.ViewColumn.Active,
      { enableScripts: true, localResourceRoots: [media] });
    this.model = new MindMapModel(context.session, context.client, context.log, () => this.render());
    this.listeners.push(this.panel.onDidDispose(() => this.dispose()),
      this.panel.webview.onDidReceiveMessage(value => this.receive(value)));
    const uri = (file: string) => this.panel.webview.asWebviewUri(vscode.Uri.joinPath(media, file)).toString();
    this.panel.webview.html = mindMapHtml(randomBytes(24).toString("hex"), this.panel.webview.cspSource,
      uri("mindMap.js"), uri("mindMap.css"));
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
    const message = parseMindMapMessage(value);
    if (!message) { this.context.log("Dropped malformed or unknown Mind Map message."); return; }
    if (this.disposed || !vscode.workspace.isTrusted || !this.model.accepts(message)) {
      this.context.log("Dropped obsolete Mind Map message.");
      return;
    }
    if (message.type === "ready") { this.render(); return; }
    if (message.type === "viewport" || message.type === "fit") { void this.model.control(message); return; }
    this.pending = this.pending.then(() => this.action(message)).catch(error => {
      if (!this.disposed) { this.model.error = `Mind Map: ${viewError(error)}`; this.context.log(this.model.error); this.render(); }
    });
  }

  private async action(message: MindMapMessage): Promise<void> {
    if (this.disposed || !vscode.workspace.isTrusted || !this.model.accepts(message)) return;
    if (message.type === "select") {
      const ref = this.model.select(message.nodeId);
      if (ref) await revealSource(this.context, ref, true, () => !this.disposed && this.model.accepts(message));
    } else if (message.type === "openStep") {
      const record = await this.model.openStep(message);
      if (!record || this.disposed || !vscode.workspace.isTrusted || !this.model.accepts(message)) return;
      this.history ??= vscode.window.createOutputChannel("ICODA Mind Map History");
      this.history.replace(mindMapStepText(record));
      this.history.show(true);
    } else await this.model.control(message);
  }

  private render(): void { if (!this.disposed) void this.panel.webview.postMessage(this.model.render()); }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.model.dispose();
    this.history?.dispose();
    this.panel.dispose();
    for (const listener of this.listeners) listener.dispose();
    this.closed();
  }
}
