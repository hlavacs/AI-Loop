import * as vscode from "vscode";
import { SpecificationDocuments } from "./specificationDocuments";

export const specificationScheme = "icoda-specification";

/** VS Code owns text editing/undo/dirty buffers; the service owns validation and persistence. */
export class SpecificationFileSystem implements vscode.FileSystemProvider, vscode.Disposable {
  private readonly changes = new vscode.EventEmitter<vscode.FileChangeEvent[]>();
  readonly onDidChangeFile = this.changes.event;

  constructor(private readonly documents: SpecificationDocuments,
    private readonly saving: (action: () => Promise<void>) => Promise<void>) {}

  watch(): vscode.Disposable { return new vscode.Disposable(() => {}); }
  stat(uri: vscode.Uri): vscode.FileStat {
    const key = uri.toString();
    return { type: vscode.FileType.File, ctime: 0, mtime: this.documents.modified(key),
      size: Buffer.byteLength(this.documents.read(key)) };
  }
  readFile(uri: vscode.Uri): Uint8Array { return Buffer.from(this.documents.read(uri.toString()), "utf8"); }
  async writeFile(uri: vscode.Uri, content: Uint8Array): Promise<void> {
    try {
      await this.saving(() => this.documents.save(uri.toString(), Buffer.from(content).toString("utf8")));
      this.changes.fire([{ type: vscode.FileChangeType.Changed, uri }]);
    } catch (error) { throw vscode.FileSystemError.NoPermissions(String(error)); }
  }
  readDirectory(): [string, vscode.FileType][] { return []; }
  createDirectory(): never { throw vscode.FileSystemError.NoPermissions("Use Open Specification."); }
  delete(): never { throw vscode.FileSystemError.NoPermissions("Specification documents cannot be deleted here."); }
  rename(): never { throw vscode.FileSystemError.NoPermissions("Specification documents cannot be renamed here."); }
  dispose(): void { this.changes.dispose(); }
}
