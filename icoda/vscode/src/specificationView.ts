import * as vscode from "vscode";
import { BackendClient } from "./backendClient";
import { ProjectSession } from "./projectSession";
import { Phase, ProviderInventory, SpecificationAction, SpecificationNode,
  Validation, providerChoice, registerSpecificationCommands } from "./specificationData";
import { SpecificationModel } from "./specificationModel";
import { SpecificationDocuments } from "./specificationDocuments";
import { SpecificationFileSystem, specificationScheme } from "./specificationFileSystem";

export class SpecificationView implements vscode.TreeDataProvider<SpecificationNode>, vscode.Disposable {
  private readonly changes = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changes.event;
  private readonly model: SpecificationModel;
  private readonly documents: SpecificationDocuments;
  private readonly disposables: vscode.Disposable[];
  private selectingProvider = false;

  constructor(private readonly session: ProjectSession, backend: () => Promise<BackendClient>,
    saving: (action: () => Promise<void>) => Promise<void>) {
    const client: Pick<BackendClient, "request"> = { request: async (method, params, context) =>
      (await backend()).request(method, params, context) };
    this.model = new SpecificationModel(session, client, () => this.changes.fire(), () => vscode.workspace.isTrusted);
    this.documents = new SpecificationDocuments(this.model, () => vscode.workspace.isTrusted,
      key => vscode.workspace.textDocuments.filter(document => document.isDirty && document.uri.toString() !== key)
        .map(document => document.uri.toString()),
      error => { void vscode.window.showErrorMessage(`ICODA specification: ${String(error)}`); });
    const filesystem = new SpecificationFileSystem(this.documents, action => saving(async () => vscode.window.withProgress({
      location: vscode.ProgressLocation.Notification, title: "ICODA: Saving specification and refreshing project…",
    }, action)));
    this.disposables = [filesystem, vscode.workspace.registerFileSystemProvider(specificationScheme, filesystem, { isCaseSensitive: true }),
      vscode.window.createTreeView("icoda.specification", { treeDataProvider: this }),
      ...registerSpecificationCommands((name, action) => vscode.commands.registerCommand(name, action), action => this.execute(action)),
      vscode.workspace.onDidCloseTextDocument(document => {
        if (document.uri.scheme === specificationScheme) this.documents.close(document.uri.toString());
      })];
  }

  sync(): void { void this.model.sync(); }
  getChildren(node?: SpecificationNode): SpecificationNode[] { return node?.children ?? (node ? [] : this.model.items()); }
  getTreeItem(node: SpecificationNode): vscode.TreeItem {
    const item = new vscode.TreeItem(node.label, node.children?.length
      ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.None);
    item.id = node.id;
    item.description = node.description;
    item.tooltip = node.description ? `${node.label}\n${node.description}` : node.label;
    return item;
  }

  private configuration(): vscode.WorkspaceConfiguration | undefined {
    const root = this.session.data?.root;
    return root ? vscode.workspace.getConfiguration("icoda", vscode.Uri.file(root)) : undefined;
  }

  private async execute(action: SpecificationAction): Promise<void> {
    if (!vscode.workspace.isTrusted || !this.session.identity.context) return;
    try {
      if (action === "open") await this.open();
      else if (action === "validate") await this.validate();
      else if (action === "phase") await this.advance();
      else await this.selectProvider();
    } catch (error) { void vscode.window.showErrorMessage(`ICODA specification: ${String(error)}`); }
  }

  private async open(): Promise<void> {
    const ticket = this.session.identity.capture(), context = ticket.context!;
    const key = this.documents.currentKey() ?? vscode.Uri.from({ scheme: specificationScheme,
      authority: context.sessionId, path: `/${context.modelRevision}/specification.json` }).toString();
    await this.documents.open(key);
    if (!this.model.current(ticket)) return;
    const document = await vscode.workspace.openTextDocument(vscode.Uri.parse(key));
    if (this.model.current(ticket)) await vscode.window.showTextDocument(document, { preview: false });
  }

  private async validate(): Promise<void> {
    const ticket = this.session.identity.capture();
    const active = vscode.window.activeTextEditor?.document;
    let validation: Validation;
    if (active?.uri.scheme === specificationScheme) {
      validation = await this.documents.validate(active.uri.toString(), active.getText());
    } else {
      await this.model.sync(true);
      if (!this.model.current(ticket)) return;
      const spec = this.model.snapshot?.spec;
      if (!spec) return;
      validation = await this.model.request<Validation>("spec.validate", { document: spec.document }, ticket);
      this.model.showValidation(validation);
    }
    if (this.model.current(ticket)) void vscode.window.showInformationMessage(validation.valid
      ? "ICODA: Specification is valid." : `ICODA: ${validation.findings.length} validation finding(s). See ICODA Specification.`);
  }

  private async advance(): Promise<void> {
    const ticket = this.session.identity.capture();
    const phase = await this.model.request<Phase>("phase.get", {}, ticket);
    if (!phase.allowedTransitions.length) {
      void vscode.window.showInformationMessage(phase.transitions.map(item => item.reason).join("\n") || "No phase transition is available.");
      return;
    }
    const choice = await vscode.window.showQuickPick(phase.allowedTransitions.map(target => ({ label: target,
      description: target === "implementation" ? "Approve architecture and begin implementation" : `Move from ${phase.phase}`, target })),
    { placeHolder: "Choose the project phase transition" });
    if (!choice || !this.model.current(ticket) || !vscode.workspace.isTrusted) return;
    await this.model.request<Phase>("phase.transition", { phase: choice.target, trusted: true }, ticket, true);
  }

  private async selectProvider(): Promise<void> {
    if (this.selectingProvider) return;
    this.selectingProvider = true;
    const ticket = this.session.identity.capture();
    const current = () => this.model.current(ticket) && vscode.workspace.isTrusted;
    try {
      const inventory = await this.model.request<ProviderInventory>("providers.list", {}, ticket);
      if (!current()) return;
      const choices = inventory.providers.filter(provider => provider.enabled).map(provider => ({ label: provider.label,
        description: provider.binaryPath ?? `Missing: ${provider.binary}`, detail: provider.loginHint, provider }));
      if (!choices.length) { void vscode.window.showInformationMessage(inventory.message || "No enabled providers are registered."); return; }
      const chosen = await vscode.window.showQuickPick(choices, { placeHolder: "Select provider (saved for this project and as the ICODA user default)" });
      if (!chosen || !current()) return;
      const provider = chosen.provider, selection = inventory.selection;
      const model = selection.provider === provider.id ? selection.model : provider.selectedModel;
      const binary = await vscode.window.showInputBox({ prompt: "Provider executable: command or absolute path, without arguments",
        value: provider.binary, validateInput: text => providerChoice({ provider: provider.id, model, binary: text })
          ? undefined : "Enter a trimmed executable path or command without control characters (at most 4096 characters)." });
      if (binary === undefined || !current()) return;
      const models = provider.models.map(item => ({ label: item.label, description: item.id, model: item.id }))
        .sort((left, right) => Number(right.model === model) - Number(left.model === model));
      if (!models.some(item => item.model === model)) models.unshift({ label: model, description: "Remembered custom model", model });
      const picked = await vscode.window.showQuickPick([...models, { label: "Enter custom model ID…", description: "Accepted by the selected CLI", model: "" }],
        { placeHolder: "Select model (registry suggestions; availability is determined by your CLI account)" });
      if (!picked || !current()) return;
      const modelId = picked.model || await vscode.window.showInputBox({ prompt: "Custom provider model ID", value: model,
        validateInput: text => providerChoice({ provider: provider.id, model: text, binary }) ? undefined
          : "Enter a trimmed model ID without control characters (at most 256 characters)." });
      if (modelId === undefined || !current()) return;
      const saved = await this.model.selectProvider({ provider: provider.id, model: modelId, binary }, ticket);
      if (!saved || !current()) return;
      const config = this.configuration();
      if (config) await config.update("providerSelection", saved.selection, vscode.ConfigurationTarget.WorkspaceFolder);
      if (current()) await this.model.sync(true);
    } catch (error) {
      if (current()) throw error;
    } finally { this.selectingProvider = false; }
  }

  dispose(): void {
    this.model.dispose(); this.documents.dispose(); this.changes.dispose();
    for (const disposable of this.disposables) disposable.dispose();
  }
}
