import * as vscode from "vscode";
import { BackendClient } from "./backendClient";
import { ProjectSession } from "./projectSession";
import { BackendError } from "./protocol";
import { entityChoices } from "./sourceNavigation";
import { conversationText, QueueSetting, registerWorkflowCommands, terminalOptions, WorkflowInput, WorkflowKind, WorkflowNode, workflowNodes } from "./workflowData";
import { WorkflowModel } from "./workflowModel";
import { BackgroundPurposeComments } from "./purposeComments";

export class WorkflowView implements vscode.TreeDataProvider<WorkflowNode>, vscode.Disposable {
  private readonly changes = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changes.event;
  private readonly output = vscode.window.createOutputChannel("ICODA Providers");
  private readonly model: WorkflowModel;
  private readonly purpose: WorkflowModel;
  private readonly background: BackgroundPurposeComments;
  private readonly disposables: vscode.Disposable[];
  private disposed = false;
  private lastSave = 0;
  private refreshing = false;
  private foreground = 0;

  constructor(private readonly session: ProjectSession, backend: () => Promise<BackendClient>,
    private readonly idle: () => boolean, private readonly review: () => void = () => {}) {
    const client: Pick<BackendClient, "request"> = { request: async (method, params, context, options) =>
      (await backend()).request(method, params, context, options) };
    this.model = new WorkflowModel(session, client, () => this.changes.fire(), message => this.output.appendLine(message),
      undefined, () => vscode.workspace.isTrusted, () => this.unsaved());
    this.purpose = new WorkflowModel(session, client, () => this.changes.fire(), message => this.output.appendLine(message),
      undefined, () => vscode.workspace.isTrusted, () => this.unsaved());
    this.background = new BackgroundPurposeComments(() => ({
      key: session.identity.context ? JSON.stringify(session.identity.capture()) : undefined,
      enabled: Boolean(session.data && vscode.workspace.getConfiguration("icoda", vscode.Uri.file(session.data.root))
        .get("backgroundPurposeComments", false)),
      eligible: this.backgroundEligible(),
    }), signal => this.runBackgroundPurpose(signal), message => this.output.appendLine(message));
    this.disposables = [vscode.window.createTreeView("icoda.workflows", { treeDataProvider: this }),
      ...registerWorkflowCommands((name, action) => vscode.commands.registerCommand(name, action),
        (kind, title) => this.execute(kind, title)),
      vscode.workspace.onDidSaveTextDocument(() => { this.lastSave = Date.now(); this.background.activity(); }),
      vscode.workspace.onDidChangeTextDocument(() => this.background.activity()),
      vscode.window.onDidChangeActiveTextEditor(() => this.background.activity()),
      vscode.window.onDidChangeTextEditorSelection(() => this.background.activity()),
      vscode.workspace.onDidChangeConfiguration(event => {
        if (event.affectsConfiguration("icoda.backgroundPurposeComments")) this.background.sync();
      })];
  }

  async activity(method: string): Promise<void> {
    if (!["purpose.status", "purpose.propose", "workflow.status", "workflow.cancel", "operation.cancel"].includes(method)) {
      await this.background.stop();
      this.background.activity();
    }
  }

  private backgroundEligible(): boolean {
    return !this.disposed && vscode.workspace.isTrusted && !this.foreground && !this.refreshing
      && !this.model.busy && !this.purpose.busy && !this.unsaved().length && this.idle();
  }

  private async runBackgroundPurpose(signal: AbortSignal): Promise<boolean> {
    const ticket = this.session.identity.capture();
    if (!await this.purpose.purposeReady(ticket) || signal.aborted || !this.backgroundEligible()
      || !this.session.identity.isCurrent(ticket)) return false;
    await this.purpose.run("purpose", { idle: true, unsavedDocuments: this.unsaved() }, {
      get isCancellationRequested() { return signal.aborted; },
      onCancellationRequested(listener) {
        signal.addEventListener("abort", listener, { once: true });
        return { dispose: () => signal.removeEventListener("abort", listener) };
      },
    }, () => {}, ticket);
    return true;
  }

  sync(): void {
    this.background.sync();
    this.purpose.sync();
    this.model.sync();
    if (!this.disposed && !this.model.snapshot && !this.model.busy && !this.refreshing) void this.refreshQueue();
  }

  private unsaved(): string[] {
    return vscode.workspace.textDocuments.filter(document => document.isDirty).map(document => document.uri.toString());
  }

  continueAfterApproval(): void {
    if (!this.disposed && !this.model.busy) void this.refreshQueue(true);
  }

  private async refreshQueue(continueAfterApproval = false): Promise<void> {
    const ticket = this.session.identity.capture();
    this.refreshing = true;
    try {
      const status = await this.model.loadQueue(ticket);
      if (continueAfterApproval && !this.disposed && this.session.identity.isCurrent(ticket) && vscode.workspace.isTrusted
        && status?.continuation?.state === "running" && status.continuation.ready) {
        await this.runQueue({ unsavedDocuments: this.unsaved() }, ticket);
      }
    } catch (error) { if (!this.disposed && this.session.identity.isCurrent(ticket)) this.output.appendLine(String(error)); }
    finally {
      this.refreshing = false;
      if (!this.session.identity.isCurrent(ticket)) this.sync();
    }
  }

  private async runQueue(input: WorkflowInput, ticket = this.session.identity.capture()): Promise<void> {
    const result = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification,
      title: "ICODA: Automatic queue continuation", cancellable: true }, (progress, token) =>
      this.model.continueQueue(input, token, message => progress.report({ message }), ticket));
    if (result?.workflow?.result) this.review();
  }

  private async editQueue(key: QueueSetting): Promise<void> {
    const ticket = this.session.identity.capture();
    const status = await this.model.loadQueue(ticket), settings = status?.queueSettings;
    if (!settings || this.disposed || !vscode.workspace.isTrusted || !this.session.identity.isCurrent(ticket)) return;
    let value: string | boolean | number | undefined;
    if (key === "batchSize") {
      const text = await vscode.window.showInputBox({ prompt: "Maximum functions per implementation batch (positive integer)",
        value: String(settings.batchSize), validateInput: text => Number.isSafeInteger(Number(text)) && Number(text) >= 1
          ? undefined : "Enter a positive integer." });
      if (text !== undefined) value = Number(text);
    } else if (key === "autoApprove") {
      value = (await vscode.window.showQuickPick([
        { label: "Off", value: false }, { label: "On — approve code while gates pass", value: true },
      ], { placeHolder: "Approach and signature changes still require your approval." }))?.value;
    } else {
      value = (await vscode.window.showQuickPick(key === "scope" ? settings.scopes : settings.groupings,
        { placeHolder: key === "scope" ? "Implementation queue scope" : "Implementation grouping" }))?.value;
    }
    if (value !== undefined && !this.disposed && vscode.workspace.isTrusted && this.session.identity.isCurrent(ticket)) {
      await this.model.setQueue({ [key]: value }, ticket);
      if (this.model.snapshot?.continuation?.state === "running" && this.model.snapshot.continuation.ready) {
        await this.runQueue({ unsavedDocuments: this.unsaved() }, ticket);
      }
    }
  }
  getChildren(node?: WorkflowNode): WorkflowNode[] {
    if (node) return [];
    const purpose = this.purpose.snapshot;
    return [...workflowNodes(this.model.snapshot), ...(purpose ? workflowNodes(purpose)
      .filter(item => !["conversation.send", "conversation.history", "prompt.rephrase", "cli.command"].includes(item.id))
      .map(item => ({ ...item, id: `background:${item.id}` })) : [])];
  }
  getTreeItem(node: WorkflowNode): vscode.TreeItem {
    const item = new vscode.TreeItem(node.label);
    item.id = node.id; item.description = node.description;
    item.tooltip = node.description ? `${node.label}\n${node.description}` : node.label;
    if (node.command) item.command = { command: node.command, title: node.label };
    return item;
  }

  private async execute(kind: WorkflowKind, title: string): Promise<void> {
    if (this.disposed) return;
    if (!vscode.workspace.isTrusted) {
      void vscode.window.showWarningMessage("ICODA: AI workflows need a trusted workspace. Trust this workspace to continue.");
      return;
    }
    if (kind === "cancel") { await this.background.stop(); await this.model.cancel(); return; }
    const ticket = this.session.identity.capture();
    if (!ticket.context) return;
    this.foreground++;
    try {
      await this.background.stop();
      if (this.disposed || !vscode.workspace.isTrusted || !this.session.identity.isCurrent(ticket)) return;
      if (kind.startsWith("queue.")) { await this.editQueue(kind.slice(6) as QueueSetting); return; }
      if (kind === "conversation.history") {
        const history = await this.model.history(ticket);
        if (history && !this.disposed && vscode.workspace.isTrusted && this.session.identity.isCurrent(ticket)) {
          this.output.appendLine(conversationText(history) || "No conversation in this project session."); this.output.show(true);
        }
        return;
      }
      const input = kind === "purpose.apply" || kind === "purpose.reject" ? undefined : await this.input(kind);
      if (this.disposed || !vscode.workspace.isTrusted || !this.session.identity.isCurrent(ticket)) return;
      if (kind === "purpose.apply" || kind === "purpose.reject") {
        const purpose = this.purpose.snapshot?.workflow?.result?.round === "purpose" ? this.purpose : this.model;
        const message = await purpose.decidePurpose(kind, this.idle() && Date.now() - this.lastSave >= 500,
          vscode.workspace.textDocuments.filter(document => document.isDirty).map(document => document.uri.toString()),
          vscode.workspace.isTrusted);
        if (message) void vscode.window.showInformationMessage(`ICODA: ${message}`);
        return;
      }
      if (!input) return;
      input.unsavedDocuments = vscode.workspace.textDocuments.filter(document => document.isDirty).map(document => document.uri.toString());
      if (kind === "cli.command") {
        const command = await this.model.cli(input, ticket);
        if (command && !this.disposed && vscode.workspace.isTrusted && this.session.identity.isCurrent(ticket)) {
          const terminal = vscode.window.createTerminal(terminalOptions(command));
          this.disposables.push(terminal); terminal.show();
        }
        return;
      }
      if (kind === "purpose") input.idle = this.idle() && Date.now() - this.lastSave >= 500;
      if (kind === "implementation_queue") {
        const settings = await this.model.loadQueue(ticket);
        if (this.disposed || !vscode.workspace.isTrusted || !this.session.identity.isCurrent(ticket)) return;
        if (settings?.queueSettings?.autoApprove) { await this.runQueue(input, ticket); return; }
      }
      const result = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification,
        title: `ICODA: ${title}`, cancellable: true }, (progress, token) =>
        this.model.run(kind, input, token, message => progress.report({ message }), ticket));
      if (this.disposed || !vscode.workspace.isTrusted || !this.session.identity.isCurrent(ticket)) return;
      if (result?.workflow) void vscode.window.showInformationMessage(`ICODA: ${result.workflow.message}`);
      if (result?.workflow?.result && (kind === "conversation.send" || kind === "prompt.rephrase")) {
        if (kind === "conversation.send") this.output.appendLine(`Developer:\n${input.message}`);
        this.output.appendLine(`${title}:\n${result.workflow.result.summary}`); this.output.show(true);
      }
      if (result?.workflow?.result && result.workflow.result.round !== "purpose" && kind !== "conversation.send") this.review();
    } catch (error) {
      if (!this.disposed && this.session.identity.isCurrent(ticket)) {
        const code = error instanceof BackendError ? error.code : "workflow_failed";
        void vscode.window.showErrorMessage(`ICODA ${code}: ${String(error)}. See ICODA Providers output.`);
      }
    } finally { this.foreground--; this.background.activity(); }
  }

  private async input(kind: WorkflowKind): Promise<WorkflowInput | undefined> {
    const root = this.session.data?.root;
    // The backend's shared project selection is authoritative for every workflow.
    const input: WorkflowInput = { unsavedDocuments: [] };
    if (kind === "purpose") return input;
    if (kind === "prompt.rephrase") {
      return await vscode.window.showQuickPick(["Simplify the current proposal or pending approach description"],
        { placeHolder: "Rephrase review text. Code, checks and approval decisions stay unchanged." }) ? input : undefined;
    }
    if (kind === "conversation.send" || kind === "cli.command") {
      const value = await vscode.window.showInputBox({ prompt: kind === "conversation.send"
        ? "Message to the selected provider (may edit project/candidate files; changes remain uncommitted)"
        : "Optional draft to carry into the interactive CLI with the current conversation",
        validateInput: text => text.includes("\0") || text.length > 20000 || kind === "conversation.send" && !text.trim()
          ? "Enter a message of at most 20000 characters without NULs." : undefined });
      if (value === undefined) return undefined;
      if (value.trim()) input[kind === "conversation.send" ? "message" : "draft"] = value;
      return input;
    }
    const request = await vscode.window.showInputBox({ prompt: "Describe the proposal (optional). The current specification and queue still apply." });
    if (request === undefined) return undefined;
    if (request.trim()) input.request = request;
    const { model, sourceRootId } = this.session;
    if (!model || !root || !sourceRootId) return input;
    const choices = entityChoices(model, root, sourceRootId).map(item => ({ ...item, context: item.ref.usr ?? item.ref.file }));
    const selected = await vscode.window.showQuickPick(choices, { canPickMany: true,
      placeHolder: "Optional context: files or entities. Leave empty for the core's default context." });
    if (!selected) return undefined;
    input.focus = selected.map(item => item.context);
    return input;
  }

  dispose(): void {
    this.background.dispose(); this.purpose.dispose();
    this.disposed = true; this.model.dispose(); this.changes.dispose(); this.output.dispose();
    for (const disposable of this.disposables) disposable.dispose();
  }
}
