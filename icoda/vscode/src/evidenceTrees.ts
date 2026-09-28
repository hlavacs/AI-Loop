import * as vscode from "vscode";
import { BackendClient } from "./backendClient";
import { ProjectSession } from "./projectSession";
import { EvidenceKind, EvidenceNode, EvidenceSelection, registerEvidenceCommands } from "./evidenceData";
import { EvidenceModel } from "./evidenceModel";
import { revealSource } from "./sourceEditor";

class EvidenceTree implements vscode.TreeDataProvider<EvidenceNode>, vscode.Disposable {
  private readonly changes = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changes.event;
  readonly model: EvidenceModel;

  constructor(kind: EvidenceKind, session: ProjectSession, client: Pick<BackendClient, "request">,
    log: (message: string) => void) {
    this.model = new EvidenceModel(kind, session, client, log, () => this.changes.fire());
  }

  getChildren(node?: EvidenceNode): EvidenceNode[] { return node ? node.children ?? [] : this.model.items(); }

  getTreeItem(node: EvidenceNode): vscode.TreeItem {
    const state = !node.children?.length ? vscode.TreeItemCollapsibleState.None : node.expanded
      ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.Collapsed;
    const item = new vscode.TreeItem(node.label, state);
    item.id = node.id;
    item.description = node.description;
    item.tooltip = node.tooltip ?? node.label;
    if (node.icon) item.iconPath = new vscode.ThemeIcon(node.icon);
    if (node.source) item.command = { command: "icoda.revealEvidence", title: "Open Source",
      arguments: [{ view: this.model.kind, id: node.id, version: this.model.version }] };
    return item;
  }

  dispose(): void { this.model.dispose(); this.changes.dispose(); }
}

/** Native trees use VS Code's keyboard, focus and theme handling; no new webview surface. */
export class EvidenceTrees implements vscode.Disposable {
  private readonly trees: Record<EvidenceKind, EvidenceTree>;
  private readonly disposables: vscode.Disposable[];

  constructor(private readonly session: ProjectSession, private readonly backend: () => Promise<BackendClient>,
    private readonly log: (message: string) => void) {
    const client: Pick<BackendClient, "request"> = { request: async (method, params, context) =>
      (await backend()).request(method, params, context) };
    this.trees = { issues: new EvidenceTree("issues", session, client, log),
      coverage: new EvidenceTree("coverage", session, client, log) };
    this.disposables = [vscode.window.createTreeView("icoda.issues", { treeDataProvider: this.trees.issues }),
      vscode.window.createTreeView("icoda.coverage", { treeDataProvider: this.trees.coverage }),
      ...registerEvidenceCommands((name, action) => vscode.commands.registerCommand(name, action),
        kind => this.refresh(kind), selection => this.reveal(selection))];
  }

  sync(): void {
    for (const tree of Object.values(this.trees)) void tree.model.sync();
  }

  private async refresh(kind: EvidenceKind): Promise<void> {
    if (vscode.workspace.isTrusted) await this.trees[kind].model.sync(true);
  }

  private async reveal(selection: EvidenceSelection): Promise<void> {
    if (!vscode.workspace.isTrusted) return;
    const model = this.trees[selection.view].model;
    if (!model.select(selection)) return;
    try {
      const client = await this.backend();
      const ref = model.select(selection);
      if (ref) await revealSource({ client, session: this.session, log: this.log }, ref, false);
    } catch (error) { this.log(String(error)); void vscode.window.showWarningMessage(`ICODA source: ${String(error)}`); }
  }

  dispose(): void {
    for (const tree of Object.values(this.trees)) tree.dispose();
    for (const disposable of this.disposables) disposable.dispose();
  }
}
