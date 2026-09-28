import * as vscode from "vscode";
import { ProjectTreeNode } from "./projectTreeData";

/** Thin VS Code adapter for the plain project tree descriptions. */
export class ProjectTree implements vscode.TreeDataProvider<ProjectTreeNode>, vscode.Disposable {
  private readonly changes = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changes.event;
  private items: ProjectTreeNode[] = [];

  update(items: ProjectTreeNode[]): void {
    this.items = items;
    this.changes.fire();
  }

  getChildren(node?: ProjectTreeNode): ProjectTreeNode[] {
    return node ? node.children ?? [] : this.items;
  }

  getTreeItem(node: ProjectTreeNode): vscode.TreeItem {
    const item = new vscode.TreeItem(node.label, node.children
      ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.None);
    item.id = node.id;
    item.description = node.description;
    item.tooltip = node.tooltip;
    if (node.icon) item.iconPath = new vscode.ThemeIcon(node.icon);
    if (node.selection) {
      item.contextValue = "icoda.target";
      item.command = { command: "icoda.selectTarget", title: "Select Target", arguments: [node.selection] };
    }
    return item;
  }

  dispose(): void {
    this.changes.dispose();
  }
}
